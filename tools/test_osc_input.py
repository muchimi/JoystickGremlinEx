"""OSC receive-to-design-selection checks with real Qt and no sockets/devices.

Run: python tools/test_osc_input.py
Production receive, dispatch, repeater and row-selection methods are executed.
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

from PySide6 import QtCore, QtWidgets

from test_qt_marshalling import APP, flush_deletes, pump_until


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
from gremlin.types import CallbackMode, EventSourceType


CONFIG = NS(verbose_mode_osc=False, verbose_mode_events=False, verbose_mode_ui_level=lambda level: False,
            highlight_enabled=True, highlight_input_buttons=True, highlight_input_axis=True,
            osc_no_arg_autorelease=False)
STATE = NS(is_running=False, current_mode="Default", runtime_mode="Default", osc_tab_guid="osc",
           is_highlighting_suspended=Mock(return_value=False))
SERVICES = NS(config=NS(Configuration=lambda: CONFIG), shared_state=STATE,
              base_classes=NS(PickleTarget=type("PickleTarget", (), {})),
              util=NS(get_guid=lambda: "event", assert_ui_thread=lambda: None,
                      is_ui_thread=lambda: QtCore.QThread.isMainThread()),
              ui=NS(ui_common=NS(DeviceWidgetTracker=lambda: NS(getCache=lambda *args: {}))))
SERVICES.input_devices = NS(callback_registry=NS(registry={}))
NSPACE = dict(QtCore=QtCore, enum=enum, InputType=InputType, EventSourceType=EventSourceType,
              CallbackMode=CallbackMode, gremlin=SERVICES, time=time,
              syslog=logging.getLogger("osc-input-checks"))
SERVICES.util.scale_to_range = load_function("gremlin/util.py", "scale_to_range", NSPACE)
SERVICES.input_item = NS(getInputIdKey=load_function("gremlin/input_item.py", "getInputIdKey", NSPACE))
Identifier = load_class("gremlin/ui/osc_device.py", "OscInputItem", {
    "InputMode", "CommandMode", "toMessageKey",
}, NSPACE)
Event = load_class("gremlin/event_handler.py", "Event", {"__init__", "identifier", "getInputType"}, NSPACE, qobject=False)
AxisValues = load_class("gremlin/event_handler.py", "AxisValues", {"__init__"}, NSPACE, qobject=False)
SERVICES.event_handler = NS(Event=Event, AxisValues=AxisValues)
NSPACE["OscDeviceTabWidget"] = NS(device_guid="osc")
Client = load_class("gremlin/ui/osc_device.py", "InputOscClient", {"_handle_osc_message_received"}, NSPACE)
Dispatcher = load_class("gremlin/event_handler.py", "JoystickEventProcessor", {"_fireCallbacks_ui"}, NSPACE)
RowMethods = load_class("gremlin/input_item.py", "InputItemWidget", {
    "_handle_button_state_change_callback", "_handle_axis_state_change_callback",
}, NSPACE)
ButtonRepeater = load_class("gremlin/ui/ui_common.py", "QButtonStateWidget", {"_handle_update_ui"}, NSPACE)
AxisRepeater = load_class("gremlin/ui/ui_common.py", "QAxisRepeaterProgressbar", {"_handle_update_ui"}, NSPACE)


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


class Row(QtWidgets.QLabel):
    button_detected = RowMethods._handle_button_state_change_callback
    axis_detected = RowMethods._handle_axis_state_change_callback

    def __init__(self):
        super().__init__("Unselected")
        self._selected = False
        self.trigger_count = 0

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, value):
        assert QtCore.QThread.isMainThread(), "Selection must reach the GUI thread"
        self._selected = value
        self.setText("Selected" if value else "Unselected")

    def trigger(self):
        self.trigger_count += 1


class OscInputTests(unittest.TestCase):
    def setUp(self):
        self.qt_errors = []
        self.exception_hook = patch.object(sys, "excepthook", lambda kind, value, tb: self.qt_errors.append(value))
        self.exception_hook.start()
        STATE.is_running = False
        STATE.is_highlighting_suspended.return_value = False
        CONFIG.highlight_enabled = CONFIG.highlight_input_buttons = CONFIG.highlight_input_axis = True
        self.bus = Bus()
        self.dispatcher = Dispatcher()
        self.dispatcher._listener_callbacks = {}
        for signal in (self.bus.joystick_event_ui, self.bus.vjoy_output_event_ui):
            signal.connect(self.dispatcher._fireCallbacks_ui, QtCore.Qt.ConnectionType.QueuedConnection)
        self.events = []
        self.bus.osc_event.connect(self.events.append, QtCore.Qt.ConnectionType.QueuedConnection)
        self.client = Client()
        self.client._event_listener = self.bus
        self.client._osc_map = {}
        self.client._state_data = {}
        self.client._verbose = False
        self.rows = []
        self.repeaters = []

    def tearDown(self):
        for obj in [self.client, self.dispatcher, self.bus, *self.rows, *self.repeaters]:
            obj.deleteLater()
        flush_deletes()
        self.exception_hook.stop()
        self.assertEqual(self.qt_errors, [])

    def add_button(self, message, source_index=0, mode=None):
        identifier = Input(message, source_index=source_index, mode=mode)
        self.client._osc_map.setdefault(identifier.message_key, []).append(identifier)
        row = Row()
        repeater = ButtonRepeater()
        repeater._state_change_callback = row.button_detected
        repeater._update_value_ui = Mock()
        self.dispatcher._listener_callbacks.setdefault(EventSourceType.OSC, {}).setdefault(
            CallbackMode.Edit, {},
        ).setdefault("osc", {}).setdefault(InputType.JoystickButton, {})[identifier.message_key] = [repeater._handle_update_ui]
        self.rows.append(row)
        self.repeaters.append(repeater)
        return identifier, row

    def add_axis(self, message, source_index=0):
        identifier = Input(message, mode=Identifier.InputMode.Axis, source_index=source_index)
        self.client._osc_map.setdefault(identifier.message_key, []).append(identifier)
        row = Row()
        repeater = AxisRepeater()
        repeater._device_guid = "osc"
        repeater._input_id = identifier
        repeater._get_values_callback = None
        repeater._value = None
        repeater._state_change_callback = row.axis_detected
        repeater._set_value_ui = Mock()
        self.dispatcher._listener_callbacks.setdefault(EventSourceType.OSC, {}).setdefault(
            CallbackMode.Edit, {},
        ).setdefault("osc", {}).setdefault(InputType.JoystickAxis, {})[identifier.message_key] = [repeater._handle_update_ui]
        self.rows.append(row)
        self.repeaters.append(repeater)
        return identifier, row

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

    def test_detected_osc_press_selects_input_on_gui_thread(self):
        identifier, row = self.add_button("/select")
        self.receive("/select", [1.0])
        self.assertTrue(row.selected)
        self.assertEqual(row.text(), "Selected")
        self.assertEqual(row.trigger_count, 1)
        self.assertIs(self.events[0].identifier, identifier)

    def test_second_parameter_input_is_matched_and_selected(self):
        identifier, row = self.add_button("/select", source_index=1)
        self.receive("/select", [0.0, 1.0])
        self.assertTrue(row.selected)
        self.assertIs(self.events[0].identifier, identifier)
        self.assertEqual(self.events[0].raw_value, 1.0)

    def test_suspended_design_highlighting_does_not_select(self):
        self.add_button("/select")
        STATE.is_highlighting_suspended.return_value = True
        self.receive("/select", [1.0])
        self.assertFalse(self.rows[0].selected)

    def test_disabled_button_highlighting_does_not_select(self):
        self.add_button("/select")
        CONFIG.highlight_input_buttons = False
        self.receive("/select", [1.0])
        self.assertFalse(self.rows[0].selected)

    def test_button_release_does_not_select(self):
        self.add_button("/select")
        self.receive("/select", [0.0])
        self.assertFalse(self.rows[0].selected)

    def test_unrelated_address_does_not_select(self):
        self.add_button("/select", source_index=1)
        self.receive("/select/other", [0.0, 1.0])
        self.assertFalse(self.rows[0].selected)
        self.assertEqual(self.events, [])

    def test_detected_axis_selects_input_and_keeps_parameter_value(self):
        identifier, row = self.add_axis("/axis", source_index=1)
        self.receive("/axis", [0.0, 0.75])
        self.assertTrue(row.selected)
        self.assertIs(self.events[0].identifier, identifier)
        self.assertEqual(self.events[0].raw_value, 0.75)
        self.assertEqual(self.events[0].value, 0.5)

    def test_suspended_axis_highlighting_does_not_select(self):
        self.add_axis("/axis")
        STATE.is_highlighting_suspended.return_value = True
        self.receive("/axis", [0.75])
        self.assertFalse(self.rows[0].selected)

    def test_runtime_message_still_emits_event_without_selecting_design_row(self):
        identifier, row = self.add_button("/select", source_index=1)
        STATE.is_running = True
        self.receive("/select", [0.0, 1.0])
        self.assertFalse(row.selected)
        self.assertIs(self.events[0].identifier, identifier)
        self.assertTrue(self.events[0].is_pressed)

    def test_change_mode_input_selects_on_zero_value(self):
        identifier, row = self.add_button("/change", mode=Identifier.InputMode.OnChange)
        self.receive("/change", [0.0])
        self.assertTrue(row.selected)
        self.assertIs(self.events[0].identifier, identifier)
        self.assertEqual(self.events[0].value, 0.0)


if __name__ == "__main__":
    unittest.main()
