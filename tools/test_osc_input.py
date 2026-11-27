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
"""OSC receive-to-design-selection checks with real Qt and no sockets/devices.

Run: python tools/test_osc_input.py
Exercises the production receiver and editor highlight handler without rendering input rows.
"""

import ast
import enum
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore

from test_qt_marshalling import APP, flush_deletes


ROOT = Path(__file__).resolve().parents[1]


class ServiceImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if all(alias.name.startswith("gremlin") for alias in node.names) else node

    def visit_ImportFrom(self, node):
        return None if node.module and node.module.startswith("gremlin") else node


def load_class(path, name, members, namespace, qobject=True):
    node = next(node for node in ast.parse((ROOT / path).read_bytes()).body
                if isinstance(node, ast.ClassDef) and node.name == name)
    node.body = [member for member in node.body if getattr(member, "name", None) in members]
    node.decorator_list = []
    node.bases = [ast.Attribute(value=ast.Name(id="QtCore", ctx=ast.Load()), attr="QObject", ctx=ast.Load())] if qobject else []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(ServiceImports().visit(module)), path, "exec"), namespace)
    return namespace[name]


def load_function(path, name, namespace):
    node = next(node for node in ast.parse((ROOT / path).read_bytes()).body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from gremlin.input_types import InputType
from gremlin.types import EventSourceType


CONFIG = NS(verbose_mode_osc=False, highlight_enabled=True, highlight_input_buttons=True,
            highlight_input_axis=True, highlight_autoswitch=False,
            osc_no_arg_autorelease=False)
STATE = NS(is_running=False, runtime_mode="Default", osc_tab_guid="osc",
           is_highlighting_suspended=Mock(return_value=False))
SERVICES = NS(config=NS(Configuration=lambda: CONFIG), shared_state=STATE,
              base_classes=NS(PickleTarget=type("PickleTarget", (), {})),
              util=NS(get_guid=lambda: "event"))
SERVICES.input_devices = NS(callback_registry=NS(registry={}))
NSPACE = dict(QtCore=QtCore, enum=enum, InputType=InputType, EventSourceType=EventSourceType,
              gremlin=SERVICES, time=time,
              syslog=logging.getLogger("osc-input-checks"))
SERVICES.util.scale_to_range = load_function("gremlin/util.py", "scale_to_range", NSPACE)
Identifier = load_class("gremlin/ui/osc_device.py", "OscInputItem", {
    "InputMode", "CommandMode", "toMessageKey",
}, NSPACE)
Event = load_class("gremlin/event_handler.py", "Event", {"__init__", "identifier", "getInputType"}, NSPACE, qobject=False)
AxisValues = load_class("gremlin/event_handler.py", "AxisValues", {"__init__"}, NSPACE, qobject=False)
SERVICES.event_handler = NS(Event=Event, AxisValues=AxisValues)
NSPACE["OscDeviceTabWidget"] = NS(device_guid="osc")
Client = load_class("gremlin/ui/osc_device.py", "InputOscClient", {"_handle_osc_message_received"}, NSPACE)
Editor = load_class("gremlinEx.py", "GremlinUi", {"_highlight_osc_input", "_input_id_matches"}, NSPACE)


class Bus(QtCore.QObject):
    osc_event = QtCore.Signal(object)
    joystick_event_ui = QtCore.Signal(object)
    vjoy_output_event_ui = QtCore.Signal(object)


class Input(Identifier):
    def __init__(self, message, mode=None, source_index=0):
        super().__init__()
        self.message = message
        self.mode = mode or self.InputMode.Button
        self.source_index = source_index
        self.message_key = self.toMessageKey(self.CommandMode.Message, message, source_index)
        self.autoRelease = False
        self.autorelease_delay = 0
        self._axis_values = []
        self.button_value = False

    def setButtonValue(self, value):
        self.button_value = value


class OscInputTests(unittest.TestCase):
    def setUp(self):
        self.qt_errors = []
        self.exception_hook = patch.object(sys, "excepthook", lambda kind, value, tb: self.qt_errors.append(value))
        self.exception_hook.start()
        STATE.is_running = False
        STATE.is_highlighting_suspended.return_value = False
        CONFIG.highlight_enabled = CONFIG.highlight_input_buttons = CONFIG.highlight_input_axis = True
        CONFIG.highlight_autoswitch = False
        self.bus = Bus()
        self.editor = Editor()
        self.editor.config = CONFIG
        self.editor._tabswitch_needed = Mock(return_value=False)
        self.editor._find_tab_index = Mock(return_value=0)
        self.view = NS(getSelectedWidget=Mock(return_value=None))
        self.editor.getRegisteredWidget = Mock(return_value=NS(inputItemListView=self.view))
        self.editor._select_input_handler = Mock(side_effect=self.assert_gui_thread)
        self.bus.osc_event.connect(self.editor._highlight_osc_input)
        self.events = []
        self.bus.osc_event.connect(self.events.append, QtCore.Qt.ConnectionType.QueuedConnection)
        self.client = Client()
        self.client._event_listener = self.bus
        self.client._osc_map = {}
        self.client._state_data = {}
        self.client._verbose = False

    def tearDown(self):
        for obj in (self.client, self.editor, self.bus):
            obj.deleteLater()
        flush_deletes()
        self.exception_hook.stop()
        self.assertEqual(self.qt_errors, [])

    def assert_gui_thread(self, *args, **kwargs):
        self.assertTrue(QtCore.QThread.isMainThread())

    def add_input(self, message, source_index=0, mode=None):
        identifier = Input(message, source_index=source_index, mode=mode)
        self.client._osc_map.setdefault(identifier.message_key, []).append(identifier)
        return identifier

    def assert_selection(self, message_key):
        self.editor._select_input_handler.assert_called_once_with(
            "osc", InputType.OpenSoundControl, message_key,
            force_switch=True, extra_data={"source": "osc_highlight"},
        )

    def receive(self, message, values):
        errors = []

        def send():
            try:
                self.client._handle_osc_message_received(message, values)
            except Exception as err:
                errors.append(err)

        worker = threading.Thread(target=send)
        worker.start()
        worker.join()
        self.assertEqual(errors, [])
        APP.processEvents()

    def test_press_requests_off_page_input_on_gui_thread(self):
        identifier = self.add_input("/vtol_toggle")
        self.receive("/vtol_toggle", [1.0])
        self.assert_selection("/vtol_toggle")
        self.assertIs(self.events[0].identifier, identifier)

    def test_second_parameter_input_is_matched_and_selected(self):
        other = self.add_input("/select")
        identifier = self.add_input("/select", source_index=1)
        self.receive("/select", [0.0, 1.0])
        self.assert_selection("/select 1")
        self.assertFalse(self.editor._input_id_matches(NS(input_id=other, message_key=other.message_key), "/select 1"))
        self.assertTrue(self.editor._input_id_matches(NS(input_id=identifier, message_key=identifier.message_key), "/select 1"))
        self.assertIs(self.events[-1].identifier, identifier)
        self.assertEqual(self.events[-1].raw_value, 1.0)

    def test_suspended_design_highlighting_does_not_select(self):
        self.add_input("/select")
        STATE.is_highlighting_suspended.return_value = True
        self.receive("/select", [1.0])
        self.editor._select_input_handler.assert_not_called()

    def test_disabled_button_highlighting_does_not_select(self):
        self.add_input("/select")
        CONFIG.highlight_input_buttons = False
        self.receive("/select", [1.0])
        self.editor._select_input_handler.assert_not_called()

    def test_button_release_does_not_select(self):
        self.add_input("/select")
        self.receive("/select", [0.0])
        self.editor._select_input_handler.assert_not_called()

    def test_unrelated_address_does_not_select(self):
        self.add_input("/select", source_index=1)
        self.receive("/select/other", [0.0, 1.0])
        self.editor._select_input_handler.assert_not_called()
        self.assertEqual(self.events, [])

    def test_detected_axis_selects_input_and_keeps_parameter_value(self):
        identifier = self.add_input("/axis", source_index=1, mode=Identifier.InputMode.Axis)
        self.receive("/axis", [0.0, 0.75])
        self.assert_selection("/axis 1")
        self.assertIs(self.events[0].identifier, identifier)
        self.assertEqual(self.events[0].raw_value, 0.75)
        self.assertEqual(self.events[0].value, 0.5)

    def test_suspended_axis_highlighting_does_not_select(self):
        self.add_input("/axis", mode=Identifier.InputMode.Axis)
        STATE.is_highlighting_suspended.return_value = True
        self.receive("/axis", [0.75])
        self.editor._select_input_handler.assert_not_called()

    def test_runtime_message_still_emits_event_without_selecting_design_row(self):
        identifier = self.add_input("/select", source_index=1)
        STATE.is_running = True
        self.receive("/select", [0.0, 1.0])
        self.editor._select_input_handler.assert_not_called()
        self.assertIs(self.events[0].identifier, identifier)
        self.assertTrue(self.events[0].is_pressed)

    def test_change_mode_input_selects_on_zero_value(self):
        identifier = self.add_input("/change", mode=Identifier.InputMode.OnChange)
        self.receive("/change", [0.0])
        self.assert_selection("/change")
        self.assertIs(self.events[0].identifier, identifier)
        self.assertEqual(self.events[0].value, 0.0)

    def test_other_device_tab_respects_auto_switch(self):
        self.add_input("/vtol_toggle")
        self.editor._tabswitch_needed.return_value = True
        self.receive("/vtol_toggle", [1.0])
        self.editor._select_input_handler.assert_not_called()

        CONFIG.highlight_autoswitch = True
        self.receive("/vtol_toggle", [1.0])
        self.assert_selection("/vtol_toggle")

    def test_already_selected_visible_row_does_not_refresh(self):
        identifier = self.add_input("/vtol_toggle")
        self.view.getSelectedWidget.return_value = NS(selected=True, input_item=identifier)
        self.receive("/vtol_toggle", [1.0])
        self.editor._select_input_handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
