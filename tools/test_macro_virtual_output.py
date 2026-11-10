"""Real Qt macro value/selector and output regressions with mocked drivers.

Run: python tools/test_macro_virtual_output.py
"""

import ast
import collections
import logging
import os
from pathlib import Path
import sys
import traceback
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from lxml import etree as ElementTree
from PySide6 import QtCore, QtGui, QtWidgets
from psygnal import Signal
from shiboken6 import Shiboken

from test_qt_marshalling import APP, UTIL, flush_deletes, invoke

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from gremlin.input_types import InputType
from gremlin.types import DeviceType


syslog = logging.getLogger("macro-output-checks")
QWidget, QSize = QtWidgets.QWidget, QtCore.QSize
get_text_width = lambda text: QtGui.QFontMetrics(APP.font()).horizontalAdvance(text)
parse_guid, write_guid = UUID, str


def safe_read(node, key, kind, default=None):
    value = node.get(key)
    if value is None:
        return default
    return value.lower() in ("true", "1") if kind is bool else kind(value)


def safe_format(value, kind):
    return str(value).lower() if kind is bool else str(value)


def load(path, name, methods=None, base=None):
    node = next(n for n in ast.parse((ROOT / path).read_bytes()).body if getattr(n, "name", None) == name)
    if isinstance(node, ast.ClassDef):
        node.decorator_list = []
        if methods is not None:
            node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in methods]
        if base:
            node.bases = [ast.parse(base, mode="eval").body]
    tree = ast.Module(body=[*ast.parse("from __future__ import annotations").body, node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), str(ROOT / path), "exec"), globals())
    return globals()[name]


MODULES = {}
def module(name, **attributes):
    result = ModuleType(name)
    result.__path__ = []
    result.__dict__.update(attributes)
    MODULES[name] = result
    if "." in name:
        parent, key = name.rsplit(".", 1)
        setattr(MODULES[parent], key, result)
    return result


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def container(widgets=None, label=None, widget_only=False):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    if label:
        layout.addWidget(QtWidgets.QLabel(label))
    for child in widgets if isinstance(widgets, list) else [widgets] if widgets is not None else []:
        layout.addWidget(child)
    return widget if widget_only else (widget, layout)


class Combo(QtWidgets.QComboBox):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)


class Radio(QtWidgets.QRadioButton):
    def __init__(self, text, data=None, callbackEx=None):
        super().__init__(text)
        self.data = data
        if callbackEx:
            self.toggled.connect(lambda checked: callbackEx(self, checked))


CONFIG = NS(startup_streamdeck_enabled=False, verbose_mode_macro=False, verbose_mode_vjoy=False)
REMOTE = Mock()
STATE = NS(outputIgnored=Mock(return_value=False))
gremlin = module("gremlin")
module("gremlin.util", InvokeUiMethod=invoke, assert_ui_thread=lambda: None, is_ui_thread=UTIL["is_ui_thread"],
       get_guid=lambda: str(uuid4()), clear_layout=clear_layout, load_icon=lambda *args, **kwargs: QtGui.QIcon())
module("gremlin.config", Configuration=lambda: CONFIG, STREAMDECK_ENABLED=False)
module("gremlin.shared_state", is_dark_theme=False)
module("gremlin.types", DeviceType=DeviceType)
module("gremlin.input_types", InputType=InputType)
module("gremlin.remote", remote_control=NS(state=(True, False)), remote_client=REMOTE)
module("gremlin.event_handler", JoystickState=lambda: STATE)
module("gremlin.joystick_handling")
module("gremlin.macro")
module("gremlin.ui")
module("gremlin.ui.state_device", StateData=lambda: NS())
directions = {(0, 0): "Center", (0, 1): "North", (1, 0): "East"}
direction_lookup = {**directions, **{value: key for key, value in directions.items()}}
module("gremlin.common", direction_tuple_lookup=direction_lookup,
       input_to_ui_string=lambda kind, index: f"{InputType.to_string(kind)} {index}")
gremlin.util.hat_tuple_to_direction = lambda value: directions[value]
gremlin.util.hat_direction_to_tuple = lambda value: direction_lookup[value]

load("gremlin/macro.py", "MacroAbstractAction")
for name in ("JoystickAction", "VJoyMacroAction"):
    setattr(gremlin.macro, name, load("gremlin/macro.py", name))
for name in ("KeyAction", "MouseButtonAction", "MouseMotionAction", "PauseAction", "RemoteControlAction",
             "StateAction", "StreamDeckAction", "MacroDescriptionAction"):
    setattr(gremlin.macro, name, type(name, (), {}))

for name in ("QLineEdit", "QFloatLineEdit", "AbstractInputSelector", "VirtualDeviceSelector"):
    load("gremlin/ui/ui_common.py", name)
QDataComboBox = Combo
common = module("gremlin.ui.ui_common", QFloatLineEdit=QFloatLineEdit, QDataComboBox=Combo,
                VirtualDeviceSelector=VirtualDeviceSelector, QDataRadioButton=Radio,
                QHorizontalLine=QtWidgets.QFrame, NoKeyboardPushButton=QtWidgets.QPushButton,
                getHContainer=container, getVContainer=container, clear_layout=clear_layout,
                Buttons=NS(getListenWidget=lambda **kwargs: QtWidgets.QPushButton("Listen")))
load("gremlin/macro_handler.py", "MacroListModel")
load("action_plugins/macro/__init__.py", "MacroActionEditor")
load("action_plugins/macro/__init__.py", "Macro", {
    "_parse_xml", "_generate_xml", "_str_to_joy_value", "_joy_value_to_str",
}, "object")
for name in ("set_axis", "set_button", "set_hat"):
    setattr(gremlin.joystick_handling, name, load("gremlin/joystick_handling.py", name))


def device(guid, name, kind, axes=(1, 2), buttons=4, hats=1):
    return NS(device_guid=UUID(int=guid), name=name, device_type=kind, is_virtual=True,
              vjoy_id=1 if kind == DeviceType.VJoy else -1, virtual_id=1, disabled=False, connected=True,
              axis_count=len(axes), button_count=buttons, hat_count=hats,
              axis_id_map={axis: index for index, axis in enumerate(axes)},
              axis_sequence_to_input_id=lambda index: axes[index], get_axis_name=lambda index: f"Axis {index}")


class Backend:
    def __init__(self):
        self.axes = {index: NS(value=0.0) for index in (1, 2, 8)}
        self.buttons = {index: NS(is_pressed=False) for index in range(1, 5)}
        self.hats = {1: NS(direction=(0, 0))}

    def axis(self, index):
        return self.axes[index]

    def button(self, index):
        return self.buttons[index]

    def hat(self, index):
        return self.hats[index]


class MacroVirtualOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patcher = patch.dict(sys.modules, MODULES)
        cls.patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()

    def setUp(self):
        global get_output_target, VJoyProxy
        self.vjoy = device(1, "vJoy 1", DeviceType.VJoy, axes=(2, 8))
        self.maestro = device(2, "Maestro 1", DeviceType.Maestro)
        self.devices = [self.vjoy, self.maestro]
        self.backends = {self.vjoy.device_guid: Backend(), self.maestro.device_guid: Backend()}
        self.targets = {dev.device_guid: NS(device=dev, kind="maestro" if dev.device_type == DeviceType.Maestro else "vjoy",
                                          out_id=1, remote_id=1, maestro=self.backends[dev.device_guid]) for dev in self.devices}
        self.targets[1] = self.targets[self.vjoy.device_guid]
        get_output_target = Mock(side_effect=lambda key: self.targets.get(key))
        VJoyProxy = Mock(return_value={1: self.backends[self.vjoy.device_guid]})
        gremlin.joystick_handling.get_output_target = get_output_target
        gremlin.joystick_handling.VJoyProxy = VJoyProxy
        gremlin.joystick_handling.getDevice = lambda guid: next((dev for dev in self.devices if dev.device_guid == guid), None)
        gremlin.joystick_handling.getDeviceFromVjoyId = lambda index: self.vjoy if self.vjoy in self.devices and index == 1 else None
        gremlin.joystick_handling.virtual_devices = lambda connected_only=True: self.devices.copy()
        STATE.outputIgnored.return_value = False
        REMOTE.reset_mock()
        self.widgets = []
        MacroActionEditor.locked = False

    def tearDown(self):
        for widget in self.widgets:
            widget.deleteLater()
        flush_deletes()

    def action(self, kind=InputType.JoystickAxis, value=0.625, dev=None, axis_type="absolute"):
        dev = dev or self.maestro
        input_id = next(iter(dev.axis_id_map)) if kind == InputType.JoystickAxis else 1
        return VJoyMacroAction(1, kind, input_id, value, axis_type, dev.device_guid)

    def editor(self, action):
        model = MacroListModel([action])
        editor = MacroActionEditor(model, model.index(0, 0))
        self.widgets.append(editor)
        return editor

    def test_dropdown_lists_all_virtual_backends_and_real_axis_ids(self):
        editor = self.editor(self.action())
        selector = editor.ui_elements["vjoy_selector"]
        self.assertEqual(selector.device_dropdown.count(), 2)
        self.assertEqual({selector.device_dropdown.itemData(i) for i in range(2)}, {self.vjoy.device_guid, self.maestro.device_guid})
        selector.set_selection(InputType.JoystickAxis, self.vjoy.device_guid, 8)
        self.assertEqual(selector.get_selection(), {"device_id": self.vjoy.device_guid, "input_type": InputType.JoystickAxis, "input_id": 8})

    def test_value_editor_commits_numeric_value_and_updates_macro_row(self):
        action = self.action()
        editor = self.editor(action)
        changed = Mock()
        editor.model.dataChanged.connect(changed)
        value = editor.ui_elements["axis_value"]
        value._widget.setText("-0.375")
        value._widget.focusOut.emit()
        self.assertEqual(action.value, -0.375)
        self.assertIsInstance(action.value, float)
        self.assertIn("-0.375", editor.model.data(editor.index, QtCore.Qt.DisplayRole))
        changed.assert_called_once()
        editor._modify_vjoy_value()
        self.assertEqual(action.value, -0.375)

    def test_opening_editor_preserves_value_without_model_notifications(self):
        action = self.action(value=0.875)
        model = MacroListModel([action])
        changed = Mock()
        model.dataChanged.connect(changed)
        self.widgets.append(MacroActionEditor(model, model.index(0, 0)))
        self.assertEqual(action.value, 0.875)
        changed.assert_not_called()

    def test_reverse_value_button_changes_stored_value(self):
        action = self.action(value=0.625)
        editor = self.editor(action)
        editor.ui_elements["axis_reverse"].click()
        self.assertEqual(action.value, -0.625)

    def test_relative_mode_selected_in_ui_is_used_for_execution(self):
        action = self.action(value=0.25)
        editor = self.editor(action)
        editor.ui_elements["axis_relative"].click()
        self.assertEqual(action.axis_type, "relative")
        self.backends[self.maestro.device_guid].axis(1).value = 0.5
        action(is_local=True, is_remote=False)
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 0.75)

    def test_selector_retains_disconnected_targets_and_filters_capabilities(self):
        self.maestro.connected = False
        self.vjoy.disabled = True
        selector = VirtualDeviceSelector(Mock(), [InputType.JoystickAxis])
        self.widgets.append(selector)
        self.assertEqual(selector.device_dropdown.count(), 1)
        self.assertIn("disconnected", selector.device_dropdown.itemText(0))
        changed = Mock()
        selector.input_changed.connect(changed)
        selector.set_selection(InputType.JoystickAxis, self.maestro.device_guid, 2, emit=True)
        changed.assert_called_once_with()
        self.assertEqual(selector.get_selection()["device_id"], self.maestro.device_guid)

    def test_device_change_preserves_axis_value_and_keeps_virtual_step(self):
        action = self.action(value=0.625)
        editor = self.editor(action)
        selector = editor.ui_elements["vjoy_selector"]
        selector.device_dropdown.setCurrentIndex(selector.device_dropdown.findData(self.vjoy.device_guid))
        self.assertIs(editor.model.get_entry(0), action)
        self.assertEqual(action.device_guid, self.vjoy.device_guid)
        self.assertEqual(action.value, 0.625)
        editor._handle_listen_selection_ui(NS(device_guid=self.maestro.device_guid, event_type=InputType.JoystickAxis, identifier=2))
        self.assertIsInstance(editor.model.get_entry(0), VJoyMacroAction)
        self.assertEqual(action.device_guid, self.maestro.device_guid)

    def test_input_type_change_uses_correct_default_button_and_hat_values(self):
        action = self.action()
        editor = self.editor(action)
        editor._modify_vjoy({"device_id": self.maestro.device_guid, "input_type": InputType.JoystickButton, "input_id": 2})
        self.assertEqual(action.value, "press")
        editor.ui_elements["button_toggle"].click()
        self.assertEqual(action.value, "toggle")
        editor._modify_vjoy({"device_id": self.maestro.device_guid, "input_type": InputType.JoystickHat, "input_id": 1})
        self.assertEqual(action.value, (0, 0))
        editor.ui_elements["hat_direction"].setCurrentText("North")
        self.assertEqual(action.value, (0, 1))

    def test_missing_device_does_not_silently_retarget_saved_macro(self):
        action = self.action()
        self.devices = []
        editor = self.editor(action)
        self.assertEqual(editor.ui_elements["vjoy_selector"].device_dropdown.currentIndex(), -1)
        self.assertEqual(action.device_guid, self.maestro.device_guid)
        self.assertEqual(action.value, 0.625)

    def test_new_virtual_step_defaults_to_available_maestro(self):
        self.devices = [self.maestro]
        editor = self.editor(self.action())
        editor._change_action("Virtual Device")
        self.assertEqual(editor.model.get_entry(0).device_guid, self.maestro.device_guid)
        self.assertEqual(editor.model.get_entry(0).value, "press")

    def test_local_axis_routes_to_selected_backend_with_colliding_indices(self):
        for dev in (self.vjoy, self.maestro):
            with self.subTest(device=dev.name):
                action = self.action(dev=dev)
                action(is_local=True, is_remote=False)
                self.assertEqual(self.backends[dev.device_guid].axis(action.input_id).value, 0.625)

    def test_sparse_vjoy_axis_is_addressed_by_id_instead_of_count(self):
        action = VJoyMacroAction(1, InputType.JoystickAxis, 8, -0.5)
        action(is_local=True, is_remote=False)
        self.assertEqual(self.backends[self.vjoy.device_guid].axis(8).value, -0.5)

    def test_relative_axis_reads_selected_backend_and_clamps(self):
        self.backends[self.maestro.device_guid].axis(1).value = 0.9
        self.action(value=0.5, axis_type="relative")(is_local=True, is_remote=True)
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 1.0)
        REMOTE.send_relative_axis.assert_called_once_with(1, 1, 0.5, None, None)

    def test_remote_only_outputs_do_not_acquire_local_vjoy(self):
        for kind, value, method in ((InputType.JoystickButton, "press", "send_button"),
                                    (InputType.JoystickButton, "release", "send_button"),
                                    (InputType.JoystickButton, "toggle", "toggle_button"),
                                    (InputType.JoystickAxis, 0.5, "send_axis"),
                                    (InputType.JoystickHat, (0, 1), "send_hat")):
            with self.subTest(kind=kind, value=value):
                REMOTE.reset_mock()
                self.action(kind, value)(is_local=False, is_remote=True)
                getattr(REMOTE, method).assert_called_once()
        get_output_target.assert_not_called()
        VJoyProxy.assert_not_called()
        self.assertFalse(self.backends[self.maestro.device_guid].button(1).is_pressed)

    def test_force_remote_relative_axis_keeps_routing_arguments(self):
        self.action(value=-0.5, axis_type="relative")(
            is_local=True, is_remote=False, force_remote=True, client_list=["peer"])
        REMOTE.send_relative_axis.assert_called_once_with(1, 1, -0.5, ["peer"], True)
        get_output_target.assert_not_called()
        VJoyProxy.assert_not_called()

    def test_buttons_toggle_and_hats_work_on_maestro(self):
        backend = self.backends[self.maestro.device_guid]
        for value, expected in ((True, True), ("toggle", False), ("toggle", True), (False, False)):
            self.action(InputType.JoystickButton, value)(is_local=True, is_remote=False)
            self.assertEqual(backend.button(1).is_pressed, expected)
        self.action(InputType.JoystickHat, (0, 1))(is_local=True, is_remote=False)
        self.assertEqual(backend.hat(1).direction, (0, 1))

    def test_unavailable_or_invalid_local_target_still_sends_remote(self):
        action = self.action(axis_type="relative")
        action.input_id = 99
        with self.assertLogs(syslog, level="WARNING"):
            action(is_local=True, is_remote=True)
        VJoyProxy.assert_not_called()
        self.targets.clear()
        with self.assertLogs(syslog, level="WARNING"):
            self.action()(is_local=True, is_remote=True)
        self.assertTrue(REMOTE.send_axis.called)

    def test_legacy_vjoy_step_uses_existing_failover_router(self):
        self.targets[1] = self.targets[self.maestro.device_guid]
        VJoyMacroAction(1, InputType.JoystickAxis, 1, -0.75)(is_local=True, is_remote=False)
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, -0.75)
        VJoyProxy.assert_not_called()

    def test_pickle_state_preserves_guid_and_accepts_legacy_states(self):
        original = self.action(value=0.75)
        state = original.__getstate__()
        restored = self.action()
        restored.__setstate__(state)
        self.assertEqual(restored.device_guid, self.maestro.device_guid)
        self.assertEqual(restored.value, 0.75)
        del state["device_guid"]
        restored.__setstate__(state)
        self.assertIsNone(restored.device_guid)

    def test_xml_roundtrip_preserves_backend_value_and_axis_mode(self):
        for kind, value in ((InputType.JoystickAxis, -0.5), (InputType.JoystickButton, "toggle"), (InputType.JoystickHat, (0, 1))):
            with self.subTest(kind=kind):
                macro = Macro()
                macro.sequence = [self.action(kind, value, axis_type="relative")]
                macro.exclusive, macro.repeat, macro.force_remote = False, None, False
                macro.execute_on_press, macro.execute_on_release = True, False
                macro.auto_restart, macro.auto_stop = False, False
                node = macro._generate_xml()
                restored = Macro()
                restored.repeat = None
                restored._parse_xml(node)
                action = restored.sequence[0]
                self.assertEqual(action.device_guid, self.maestro.device_guid)
                self.assertEqual(action.value, value)
                if kind == InputType.JoystickAxis:
                    self.assertEqual(action.axis_type, "relative")

    def test_legacy_xml_keeps_vjoy_id_and_normalizes_button_value(self):
        macro = Macro()
        macro.repeat = None
        macro._parse_xml(ElementTree.fromstring(b'<macro><properties/><actions><vjoy vjoy-id="1" input-type="button" input-id="3" value="True"/></actions></macro>'))
        self.assertIsNone(macro.sequence[0].device_guid)
        self.assertEqual(macro.sequence[0].vjoy_id, 1)
        self.assertEqual(macro.sequence[0].value, "press")


if __name__ == "__main__":
    unittest.main(verbosity=2)
