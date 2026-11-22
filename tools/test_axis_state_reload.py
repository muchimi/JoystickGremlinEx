# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Hardware-free axis reload checks: python tools/test_axis_state_reload.py."""

import ast
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def definitions(path, class_name, methods=None):
    tree = ast.parse((ROOT / path).read_bytes())
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    node.decorator_list = []
    node.bases = []
    if methods is not None:
        node.body = [child for child in node.body if getattr(child, "name", None) in methods]
    return node


class AxisReloadChecks(unittest.TestCase):
    def setUp(self):
        self.profile = object()
        self.services = ModuleType("gremlin")
        self.services.__path__ = []
        self.services.shared_state = NS(profile_loading=False, current_profile=self.profile)
        self.services.config = NS(Configuration=lambda: NS(verbose_mode_joystick=False, verbose_mode_events=False))
        self.services.util = NS(normalize_guid=str)
        self.devices = {}
        handling = ModuleType("gremlin.joystick_handling")
        handling.getDevice = Mock(side_effect=lambda guid: self.devices.get(guid))
        self.services.joystick_handling = handling
        inputs = ModuleType("gremlin.input_item")
        inputs.InputItem = type("InputItem", (), {})
        self.services.input_item = inputs
        self.types = NS(JoystickAxis=2)
        self.reload = Mock()
        namespace = dict(gremlin=self.services, InputType=self.types,
                         syslog=logging.getLogger("axis-reload-checks"), EventListener=lambda: NS(reload_axis_state=self.reload))
        nodes = [definitions("gremlin/event_handler.py", "AxisData"),
                 definitions("gremlin/event_handler.py", "AxisState", {"registerAxisInputItem", "registerDevice", "_get_key", "getItem"})]
        module = ast.Module(body=[*ast.parse("from __future__ import annotations").body, *nodes], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "event_handler.py", "exec"), namespace)
        self.state = namespace["AxisState"]()
        self.state._data = {}
        self.state._joystick_input_item_map = {}
        self.state._registered_devices = []
        self.axis_data = namespace["AxisData"]
        self.services.event_handler = NS(AxisState=lambda: self.state)
        handler = definitions("gremlin/input_item.py", "InputItem", {"_handle_axis_state_request"}).body[0]
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "input_item.py", "exec"), namespace)
        inputs.InputItem._handle_axis_state_request = namespace["_handle_axis_state_request"]
        self.modules = patch.dict(sys.modules, {"gremlin": self.services,
                                  "gremlin.input_item": inputs, "gremlin.joystick_handling": handling})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def item(self, guid="current", axis=3, profile=None):
        item = self.services.input_item.InputItem()
        item.device_guid, item.input_id = guid, axis
        item._is_axis = True
        item.parent = NS(profile=self.profile if profile is None else profile)
        item.get_input_type = lambda: self.types.JoystickAxis
        return item

    def device(self, guid="current", kind="Joystick"):
        device = NS(device_id=guid, device_guid=guid, name=guid, device_type=kind,
                    axis_id_map=[1, 3], linear_id_map=[1, 2], axis_count=2,
                    getAxisLinearId=lambda axis: {1: 1, 3: 2}[axis])
        self.devices[guid] = device
        return device

    def test_missing_device_does_not_assert_or_partially_register(self):
        self.state.registerAxisInputItem(self.item("removed"))
        self.assertEqual(self.state._data, {})
        self.assertEqual(self.state._joystick_input_item_map, {})

    def test_axis_missing_from_replacement_device_is_skipped(self):
        self.device()
        self.state.registerAxisInputItem(self.item(axis=8))
        self.assertEqual(self.state._data, {})
        self.assertEqual(self.state._joystick_input_item_map, {})

    def test_current_native_and_failover_axes_register(self):
        for kind in ("Joystick", "VJoy", "Maestro"):
            with self.subTest(kind=kind):
                device = self.device(kind=kind)
                item = self.item()
                self.state.registerAxisInputItem(item)
                data = self.state._data[("current", 3)]
                self.assertIs(data.device, device)
                self.assertEqual(data.linear_id, 2)
                self.assertIs(self.state.getItem("current", 3), item)

    def test_registration_uses_one_registry_snapshot(self):
        device = self.device()
        lookup = self.services.joystick_handling.getDevice
        lookup.side_effect = [device, None]
        self.state.registerAxisInputItem(self.item())
        lookup.assert_called_once_with("current")
        self.assertIs(self.state._data[("current", 3)].device, device)

    def test_reload_during_profile_load_does_not_broadcast(self):
        self.services.shared_state.profile_loading = True
        self.assertIsNone(self.state.getItem("current", 3))
        self.reload.emit.assert_not_called()

    def test_old_profile_cannot_overwrite_current_axis(self):
        self.device()
        current = self.item()
        current._handle_axis_state_request()
        stale = self.item(profile=object())
        stale._handle_axis_state_request()
        self.assertIs(self.state.getItem("current", 3), current)

    def test_item_ignores_reload_while_loading(self):
        self.device()
        self.services.shared_state.profile_loading = True
        self.item()._handle_axis_state_request()
        self.assertEqual(self.state._data, {})

    def test_reload_after_conversion_ignores_old_guid_and_finds_new_axis(self):
        self.device(guid="maestro-equivalent", kind="Maestro")
        old = self.item(guid="removed-vjoy", profile=object())
        current = self.item(guid="maestro-equivalent")
        self.reload.emit.side_effect = lambda: [item._handle_axis_state_request() for item in (old, current)]
        self.assertIs(self.state.getItem("maestro-equivalent", 3), current)
        self.assertNotIn(("removed-vjoy", 3), self.state._data)
        self.reload.emit.assert_called_once()

    def test_axis_data_still_rejects_invalid_direct_construction(self):
        with self.assertRaisesRegex(AssertionError, "removed.*3"):
            self.axis_data("removed", 3)


if __name__ == "__main__":
    unittest.main()
