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
"""Hardware-free Qt Virtual Remap selector checks: python tools/test_vjoy_remap_selector.py."""

import ast
import logging
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

import numpy as np
from PySide6 import QtCore, QtWidgets
from psygnal import Signal
from shiboken6 import Shiboken

from test_qt_marshalling import definitions, flush_deletes, invoke, pump_until


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType  # noqa: E402
from gremlin.types import DeviceType, VjoyAction  # noqa: E402


SERVICES = NS()
source = definitions("action_plugins/map_to_vjoy/__init__.py", {"VJoyRemapWidget"})[0]
source.bases = [ast.Attribute(value=ast.Name(id="QtWidgets", ctx=ast.Load()), attr="QWidget", ctx=ast.Load())]
source.body = [node for node in source.body if getattr(node, "name", None) in {
    "_update_device_selector", "_handle_virtual_device_input_changed", "_update_device_input_list",
    "_handle_virtual_button_usage_changed", "_populate_grid_ui", "_selected_output_uses_failover",
    "_is_stepped_latch_input", "_update_button_ui", "_stepped_device_changed_cb",
    "_update_stepped_selectors", "_stepped_input_changed_cb", "_stepped_input_type_changed_cb",
    "_distribute_curve_steps", "_update_curve_icon",
}]


class IconLabel(QtWidgets.QWidget):
    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(parent)


class Events:
    config_option_changed = Signal()
    profile_loaded = Signal()
    device_initialized = Signal()
    device_change_event = Signal()


namespace = dict(np=np, QtCore=QtCore, QtWidgets=QtWidgets, Shiboken=Shiboken, gremlin=SERVICES,
                 InputType=InputType, VjoyAction=VjoyAction, QIconLabel=IconLabel,
                 syslog=logging.getLogger("selector-checks"))
exec(compile(ast.fix_missing_locations(ast.Module(body=[*ast.parse("from __future__ import annotations").body,
    source, *definitions("gremlin/ui/ui_common.py", {"QFailoverWidget"})], type_ignores=[])),
    "action_plugins/map_to_vjoy/__init__.py", "exec"), namespace)
Selector = namespace["VJoyRemapWidget"]


def device(guid="output-1", connected=True):
    return NS(device_guid=guid, name=guid, connected=connected, virtual_id=1,
              device_type=DeviceType.VJoy, axis_count=3, get_axis_name=lambda axis: f"Axis {axis}")


class OutputSelectorTests(unittest.TestCase):
    def setUp(self):
        self.devices = []
        self.config = NS(vjoy_show_disconnected=False)
        self.query = Mock(side_effect=lambda connected_only: [
            dev for dev in self.devices if not connected_only or dev.connected
        ])
        SERVICES.config = NS(Configuration=lambda: self.config)
        SERVICES.joystick_handling = NS(virtual_devices=self.query, virtual_device_key=lambda dev: dev.device_guid,
                                        get_output_target=Mock(return_value=None))
        self.events = Events()
        SERVICES.event_handler = NS(EventListener=lambda: self.events)
        SERVICES.util = NS(InvokeUiMethod=invoke)
        self.ui = Selector()
        self.ui.action_data = NS(virtual_device=None, action_mode=VjoyAction.VJoyAxis,
                                 vjoy_input_id=2, virtual_id=-1, grid_visible=True,
                                 refresh_virtual_inputs=Mock())
        self.ui.virtual_device_selector_widget = QtWidgets.QComboBox(self.ui)
        self.ui.failover_widget = namespace["QFailoverWidget"](parent=self.ui,
            visibility_provider=self.ui._selected_output_uses_failover)
        self.addCleanup(self.ui.failover_widget._cleanup_ui)
        self.ui.virtual_output_selector_widget = QtWidgets.QComboBox(self.ui)
        self.ui.virtual_device_selector_widget.currentIndexChanged.connect(self.ui._handle_virtual_device_input_changed)
        self.ui._get_selector_input_type = lambda: InputType.JoystickAxis
        self.ui._update_hat_mapping = Mock()
        self.ui._update_ui = Mock()
        self.ui.notify_device_changed = Mock()
        self.ui.setWarning = Mock()
        self.ui._grid_widgets = {}

    def tearDown(self):
        self.ui.deleteLater()
        flush_deletes()

    def assert_empty_outputs(self):
        self.assertEqual(self.ui.virtual_device_selector_widget.count(), 0)
        self.assertEqual(self.ui.virtual_output_selector_widget.count(), 0)
        self.assertIn("No virtual output devices", self.ui.setWarning.call_args.args[0])

    def test_no_devices_warns_without_changing_the_action(self):
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.assertIsNone(self.ui.action_data.virtual_device)
        self.ui.notify_device_changed.assert_not_called()
        self.ui.action_data.refresh_virtual_inputs.assert_not_called()

    def test_empty_list_preserves_saved_disconnected_target(self):
        saved = self.ui.action_data.virtual_device = device(connected=False)
        self.ui.virtual_output_selector_widget.addItem("Old output", 1)
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.assertIs(self.ui.action_data.virtual_device, saved)
        # Later UI population must not restore outputs hidden by the filter.
        self.ui._update_device_input_list()
        self.assert_empty_outputs()

    def test_device_removal_clears_stale_outputs(self):
        self.devices = [device()]
        self.ui._update_device_selector()
        saved = self.ui.action_data.virtual_device
        self.assertEqual(self.ui.virtual_output_selector_widget.count(), 3)
        self.devices.clear()
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.assertIs(self.ui.action_data.virtual_device, saved)

    def test_device_reappearing_restores_selection_and_clears_warning(self):
        self.ui.action_data.virtual_device = device()
        self.ui._update_device_selector()
        current = device()
        self.devices = [current]
        self.ui._update_device_selector()
        self.assertIs(self.ui.action_data.virtual_device, current)
        self.assertEqual(self.ui.virtual_output_selector_widget.currentData(), 2)
        self.ui.setWarning.assert_called_with(None)

    def test_missing_target_falls_back_to_first_available_output(self):
        self.ui.action_data.virtual_device = device("missing")
        self.devices = [device("maestro-1"), device("vjoy-1")]
        self.ui._update_device_selector()
        self.assertIs(self.ui.action_data.virtual_device, self.devices[0])
        self.ui.notify_device_changed.assert_called_once()

    def test_matching_guid_rebinds_to_the_current_device_instance(self):
        self.ui.action_data.virtual_device = device("maestro-1")
        self.devices = [device("vjoy-1"), device("maestro-1")]
        self.ui._update_device_selector()
        self.assertEqual(self.ui.virtual_device_selector_widget.currentIndex(), 1)
        self.assertIs(self.ui.action_data.virtual_device, self.devices[1])
        self.ui.notify_device_changed.assert_called_once()

    def test_show_disconnected_repopulates_an_empty_selector(self):
        self.devices = [device(connected=False)]
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.config.vjoy_show_disconnected = True
        self.ui._update_device_selector()
        self.assertIs(self.ui.action_data.virtual_device, self.devices[0])
        self.assertEqual(self.ui.virtual_output_selector_widget.count(), 3)
        self.assertEqual([call.args for call in self.query.call_args_list], [(True,), (False,)])

    def test_grid_refresh_without_a_target_is_harmless(self):
        self.ui._populate_grid_ui()

    def test_failover_refresh_from_profile_worker_uses_ui_thread(self):
        selected = device()
        self.ui.virtual_device_selector_widget.addItem(selected.name, selected)
        calls = []

        def resolve_target(key):
            calls.append((QtCore.QThread.isMainThread(), key))
            return NS(device=NS(device_type=DeviceType.Maestro))

        SERVICES.joystick_handling.get_output_target.side_effect = resolve_target
        worker = threading.Thread(target=self.events.config_option_changed.emit)
        worker.start()
        worker.join()
        self.assertEqual(calls, [])
        pump_until(lambda: bool(calls))
        self.assertEqual(calls, [(True, selected.device_guid)])
        self.assertFalse(self.ui.failover_widget.isHidden())

    def test_failover_refresh_after_selector_is_cleared_or_deleted(self):
        selector = self.ui.virtual_device_selector_widget
        self.ui.virtual_device_selector_widget = None
        self.events.config_option_changed.emit()
        self.assertTrue(self.ui.failover_widget.isHidden())
        self.ui.virtual_device_selector_widget = selector
        selector.deleteLater()
        flush_deletes(selector)
        self.assertFalse(self.ui._selected_output_uses_failover())

    def test_pending_failover_refresh_is_ignored_after_cleanup(self):
        selected = device()
        self.ui.virtual_device_selector_widget.addItem(selected.name, selected)
        lookup = SERVICES.joystick_handling.get_output_target
        lookup.reset_mock()
        worker = threading.Thread(target=self.events.config_option_changed.emit)
        worker.start()
        worker.join()
        self.ui.failover_widget._cleanup_ui()
        flush_deletes()
        self.events.profile_loaded.emit()
        lookup.assert_not_called()

    def test_button_usage_notification_without_a_target_is_harmless(self):
        self.ui._handle_virtual_button_usage_changed("vjoy", 1)


class SteppedLatchSelectorTests(unittest.TestCase):
    def setUp(self):
        self.ui = Selector()
        self.addCleanup(self.ui.close)
        self.button = InputType.JoystickButton
        self.hat = InputType.JoystickHat
        self.ui.action_data = NS(
            stepped_device_id="first", stepped_input_type=self.hat, stepped_input_id=1, stepped_hat_direction=(0, 1)
        )
        self.ui.stepped_input_map = {
            "first": {self.button: [2], self.hat: [1]},
            "second": {self.button: [1, 2, 3, 4, 5], self.hat: [1, 2]},
        }
        self.ui.stepped_selector_device_widget = QtWidgets.QComboBox(self.ui)
        self.ui.stepped_selector_input_type_widget = QtWidgets.QComboBox(self.ui)
        self.ui.stepped_selector_input_widget = QtWidgets.QComboBox(self.ui)
        self.ui.stepped_hat_container = QtWidgets.QWidget(self.ui)
        self.ui.stepped_direction_widget = NS(setValue=Mock())
        for device_id in self.ui.stepped_input_map:
            self.ui.stepped_selector_device_widget.addItem(device_id, device_id)
        for widget, callback in (
            (self.ui.stepped_selector_device_widget, self.ui._stepped_device_changed_cb),
            (self.ui.stepped_selector_input_type_widget, self.ui._stepped_input_type_changed_cb),
            (self.ui.stepped_selector_input_widget, self.ui._stepped_input_changed_cb),
        ):
            widget.currentIndexChanged.connect(lambda _, combo=widget, update=callback: update(combo.currentData()))
        self.ui._update_stepped_selectors()

    def test_listen_updates_device_and_type_before_selecting_button(self):
        self.ui._update_button_ui(NS(device_id="second", event_type=self.button, identifier=5))
        data = self.ui.action_data
        self.assertEqual((data.stepped_device_id, data.stepped_input_type, data.stepped_input_id), ("second", self.button, 5))
        self.assertEqual(self.ui.stepped_selector_device_widget.currentData(), "second")
        self.assertEqual(self.ui.stepped_selector_input_type_widget.currentData(), self.button)
        self.assertEqual(self.ui.stepped_selector_input_widget.currentText(), "Button 5")
        self.assertTrue(self.ui.stepped_hat_container.isHidden())

    def test_listen_captures_hat_direction_and_ignores_unavailable_inputs(self):
        for event in (
            NS(device_id="first", event_type=InputType.JoystickAxis, identifier=1),
            NS(device_id="first", event_type=self.button, identifier=1),
            NS(device_id="unavailable", event_type=self.button, identifier=1),
        ):
            self.assertFalse(self.ui._is_stepped_latch_input(event))
            self.ui._update_button_ui(event)
        self.assertEqual(self.ui.action_data.stepped_device_id, "first")
        self.assertEqual(self.ui.action_data.stepped_input_type, self.hat)

        self.ui._update_button_ui(NS(device_id="second", event_type=self.hat, identifier=2, value=(1, -1)))
        self.assertEqual(self.ui.action_data.stepped_hat_direction, (1, -1))
        self.assertEqual(self.ui.stepped_selector_input_widget.currentText(), "Hat 2")
        self.ui.stepped_direction_widget.setValue.assert_called_with((1, -1))
        self.assertFalse(self.ui.stepped_hat_container.isHidden())


class CurveStepDistributionTests(unittest.TestCase):
    def setUp(self):
        self.ui = Selector()
        self.addCleanup(self.ui.close)
        self.ui.action_data = NS(target_step_list=np.linspace(-0.8, 0.8, 9).tolist(), curve_data=None)
        self.ui._update_steps_ui = Mock()

    def test_flatter_center_gets_closer_steps(self):
        def cube(position, *, apply_filter):
            self.assertFalse(apply_filter)
            return position ** 3

        self.ui.action_data.curve_data = NS(curve_value=cube)
        self.ui._distribute_curve_steps()
        steps = self.ui.action_data.target_step_list
        self.assertEqual(len(steps), 9)
        self.assertEqual((steps[0], steps[-1]), (-0.8, 0.8))
        np.testing.assert_allclose(steps, -np.array(steps[::-1]), atol=1e-12)
        self.assertGreater(min(np.diff(steps)), 0.0)
        self.assertLess(steps[5] - steps[4], steps[-1] - steps[-2])
        self.ui._update_steps_ui.assert_called_once()

    def test_straight_or_constant_curve_keeps_even_spacing(self):
        for slope in (-0.4, 0.0, 0.4):
            with self.subTest(slope=slope):
                self.ui.action_data.curve_data = NS(curve_value=lambda x, **_: slope * x)
                self.ui._distribute_curve_steps()
                np.testing.assert_allclose(np.diff(self.ui.action_data.target_step_list), 0.2, atol=1e-12)

    def test_distribution_button_tracks_curve_definition(self):
        self.ui.distribute_curve_steps_widget = QtWidgets.QPushButton(self.ui)
        self.ui._output_curve_controls = []
        self.ui.curve_icon_active = self.ui.curve_icon_inactive = None
        self.ui._update_curve_icon()
        self.assertTrue(self.ui.distribute_curve_steps_widget.isHidden())
        self.ui.action_data.curve_data = NS()
        self.ui._update_curve_icon()
        self.assertFalse(self.ui.distribute_curve_steps_widget.isHidden())


if __name__ == "__main__":
    unittest.main()
