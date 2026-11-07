"""Hardware-free gated-axis model/UI regressions: python tools/test_gated_axis.py."""

import ast
import copy
from enum import Enum, auto
import html
from itertools import pairwise
import logging
import math
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from lxml import etree as ElementTree
from psygnal import Signal
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken
from test_qt_marshalling import APP, definitions, flush_deletes, invoke, pump_until


def load(path, names, namespace):
    nodes = definitions(path, names)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.Module(body=[future, *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), path, "exec"), namespace)


def delete_widget(widget):
    widget.hide()
    widget.deleteLater()


def clear_layout(layout):
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget:
            delete_widget(widget)


class Listener(QtCore.QObject):
    config_option_changed = QtCore.Signal()
    keyboard_event = QtCore.Signal(object)


class DataButton(QtWidgets.QPushButton):
    def __init__(self, text="", callback=None, data=None, tooltip=None):
        super().__init__(text)
        self.data = data
        if callback:
            self.clicked.connect(lambda: callback(self))


class InputItem:
    """Only container serialization is stubbed; range/gate XML is production code."""
    def __init__(self):
        self.containers = []

    def setOverrideInputType(self, input_type):
        self.input_type = input_type

    def to_xml(self):
        node = ElementTree.Element("axis")
        for name in self.containers:
            ElementTree.SubElement(node, "container", name=name)
        return node

    def from_xml(self, node, data, extra_data=None):
        self.containers = [child.get("name") for child in node]


class Slider(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._values = []

    def setValue(self, values):
        self._values = list(values)

    def value(self):
        return self._values.copy()

    def setHandleIcon(self, *args):
        pass


LISTENER = Listener()
CONFIG = NS(verbose_mode_gate=False, verbose_mode_extra=False, verbose_mode_details=False,
            verbose=False, gated_axis_display_events=True)
COLOR = NS(inactiveColor=lambda: "#888888", activeContentColor=lambda: "#ffffff", recordColor=lambda: "#ff0000")
GREMLIN = NS(config=NS(Configuration=lambda: CONFIG), util=NS(
    InvokeUiMethod=invoke, assert_ui_thread=lambda: None, clear_layout=clear_layout,
    delete_widget=delete_widget, clamp=lambda value, low, high: max(low, min(high, value)),
    is_close=math.isclose, load_icon=lambda *args, **kwargs: QtGui.QIcon(),
    get_guid=lambda: str(uuid4()), ansiText=str,
), ui=NS(ui_common=NS(QDataPushButton=DataButton, Color=lambda: COLOR, MessageBox=Mock(),
                     Icons=NS(gearIcon=lambda **kwargs: QtGui.QIcon()))),
    event_handler=NS(EventListener=lambda: LISTENER), shared_state=NS(char_width=8),
    singleton_decorator=NS(SingletonDecorator=lambda cls: cls))
UI = dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, QWidget=QtWidgets.QWidget,
          QSize=QtCore.QSize, Shiboken=Shiboken, gremlin=GREMLIN, threading=threading,
          syslog=logging.getLogger("system"), Signal=Signal,
          Enum=Enum, auto=auto, html=html, logging=logging, math=math, copy=copy,
          ElementTree=ElementTree, MAX_UNDO=20, InputType=NS(JoystickAxis=1, JoystickButton=2), pairwise=pairwise,
          load_icon=GREMLIN.util.load_icon,
          get_text_width=lambda text: QtGui.QFontMetrics(APP.font()).horizontalAdvance(text))
load("gremlin/util.py", {"scale_to_range", "safe_format", "safe_read", "get_xml_child", "isNumeric", "is_close", "triplets"}, UI)
for name in ("scale_to_range", "safe_format", "safe_read", "get_xml_child", "is_close", "triplets"):
    setattr(GREMLIN.util, name, UI[name])
UI["get_guid"] = GREMLIN.util.get_guid
load("gremlin/ui/ui_common.py", {"QDataWidget", "QDataLabel", "QLineEdit", "QFloatLineEdit"}, UI)
GREMLIN.ui.ui_common.QDataWidget = UI["QDataWidget"]
GREMLIN.ui.ui_common.QDataLabel = UI["QDataLabel"]
GREMLIN.ui.ui_common.QFloatLineEdit = UI["QFloatLineEdit"]
load("gremlin/gated_handler.py", {
    "DisplayMode", "GateConditionType", "GateRangeOutputMode", "TriggerMode", "GateInfo", "RangeInfo",
    "GateInfoWidget", "RangeInfoWidget", "GateData", "GateEventHandler", "_decimals", "_single_step",
    "_display_mode_to_string", "_display_mode_to_enum", "_gate_condition_to_name", "_gate_condition_to_enum",
    "_gate_range_to_string", "_gate_range_to_enum", "_trigger_mode_to_string",
    "_gate_condition_to_display_name", "_gate_range_to_display_name",
}, UI)
EVENTS = UI["GateEventHandler"]()
UI["GateEventHandler"] = lambda: EVENTS
load("action_plugins/gated_axis/__init__.py", {"QGatedAxisWidget"}, UI)


class GateDataFixture(UI["GateData"]):
    def __init__(self, values=(-1.0, 1.0), action_data=None):
        self.profile_mode = values if isinstance(values, str) else "Default"
        if isinstance(values, str):
            values = (-1.0, 1.0)
        self.id = str(uuid4())
        self._hooked = False
        self._action_data = action_data
        self._ranges = []
        self._range_item_map = {}
        self.filter_map = dict.fromkeys(UI["TriggerMode"], True)
        self.display_mode = UI["DisplayMode"].Normal
        self.range_min = self.display_range_min = -1.0
        self.range_max = self.display_range_max = 1.0
        self._gates = [UI["GateInfo"](id=f"{id(self)}-{index}", value=value, parent=self, used=True)
                       for index, value in enumerate(values)]
        self._update()

    def _find_input_item(self):
        return self._action_data.get_input_item()

    def _new_input_item(self, *args):
        return InputItem()

    def hook(self):
        self._hooked = True

    def unhook(self):
        self._hooked = False


UI["GateData"] = GateDataFixture


class Widget(UI["QGatedAxisWidget"]):
    def __init__(self, values=(-1.0, -0.5, 0.5, 1.0)):
        QtWidgets.QWidget.__init__(self)
        self.id = str(uuid4())
        self.input_item = InputItem()
        self.action_data = NS(get_input_item=lambda: self.input_item)
        self._gate_data = GateDataFixture(values, self.action_data)
        self.action_data.gates = [self._gate_data]
        self.action_data.gate_data = self._gate_data
        self._sort_lock = self._lock = False
        self._hooked = False
        self._stack = []
        self._filter_widgets = []
        self.verbose_ui = self.verbose_extra = False
        self._option_display_events = True
        self._gwi_map, self._rwi_map = {}, {}
        self.gate_flow_widget = QtWidgets.QWidget(self)
        self.range_flow_widget = QtWidgets.QWidget(self)
        self.gate_flow_layout = QtWidgets.QVBoxLayout(self.gate_flow_widget)
        self.range_flow_layout = QtWidgets.QVBoxLayout(self.range_flow_widget)
        self.container_range_layout = self.range_flow_layout
        self.gate_count_widget = QtWidgets.QLabel(self)
        self.range_count_widget = QtWidgets.QLabel(self)
        self.container_options_widget = QtWidgets.QWidget(self)
        self.container_output_widget = QtWidgets.QWidget(self)
        self._display_mode_widget = QtWidgets.QComboBox(self)
        for mode in UI["DisplayMode"]:
            self._display_mode_widget.addItem(mode.name, mode)
        self._display_mode_widget.currentIndexChanged.connect(self._display_mode_changed_cb)
        self._slider_widget = Slider(self)
        self._grab_icon = QtGui.QIcon()
        self._create_steps_ui()
        self.container_steps_widget.setParent(self)
        self.hook()
        self._reload_widgets()


class GateWidgetTests(unittest.TestCase):
    def setUp(self):
        self.widgets = []
        self.errors = []
        self.exception_hook = patch.object(sys, "excepthook", lambda *args: self.errors.append(args[1]))
        self.exception_hook.start()

    def tearDown(self):
        for widget in self.widgets:
            widget.unhook()
            Shiboken.delete(widget)
        flush_deletes()
        self.exception_hook.stop()
        self.assertEqual(self.errors, [])

    def widget(self, *args):
        widget = Widget(*args)
        self.widgets.append(widget)
        return widget

    def assert_consistent(self, widget, count):
        gates = widget.gate_data.getGates()
        self.assertEqual(len(gates), count)
        self.assertEqual(set(widget._gwi_map), set(gates))
        self.assertEqual(widget.gate_flow_layout.count(), count)
        self.assertEqual(widget.gate_count_widget.text(), f"Gates ({count}):")
        self.assertEqual(widget.range_flow_layout.count(), count - 1)
        self.assertEqual(widget.range_count_widget.text(), f"Ranges ({count - 1}):")
        self.assertEqual(widget._slider_widget.value(), [gate.value for gate in gates])
        self.assertEqual([gate.slider_index for gate in gates], list(range(count)))
        for index, gate in enumerate(gates):
            gwi = widget.get_gate_widget(gate)
            self.assertEqual(gwi.label_widget.text(), f"Gate {index + 1}:")
            self.assertAlmostEqual(gwi.value_widget.value(), gate.display_value)
            self.assertAlmostEqual(gwi.value_widget.minimum(), widget.gate_data.to_display(gates[index - 1].value + 0.001 if index else -1.0))
            self.assertAlmostEqual(gwi.value_widget.maximum(), widget.gate_data.to_display(gates[index + 1].value - 0.001 if index + 1 < count else 1.0))

    def xml(self, widget):
        return ElementTree.tostring(widget.gate_data.to_xml())

    def assert_undo_restores(self, widget, before, count):
        self.assertEqual(len(widget._stack), 1)
        previous = widget.gate_data
        widget._undo()
        self.assertEqual(self.xml(widget), before)
        self.assert_consistent(widget, count)
        self.assertEqual(widget._stack, [])
        self.assertIs(widget.action_data.gate_data, widget.gate_data)
        self.assertIs(widget.action_data.gates[0], widget.gate_data)
        self.assertEqual(previous.id, widget.gate_data.id)
        self.assertFalse(previous._hooked)
        self.assertTrue(widget.gate_data._hooked)

    def test_delete_first_middle_last_during_display_updates(self):
        for index in (0, 1, 3):
            with self.subTest(index=index):
                widget = self.widget()
                removed = widget.gate_data.getGates()[index]
                factory = UI["GateInfoWidget"]

                def create(*args, **kwargs):
                    result = factory(*args, **kwargs)
                    # Simulate a pending value/display signal arriving mid-rebuild.
                    EVENTS.gate_display_changed.emit(widget.gate_data.getGates()[0])
                    return result

                with patch.dict(UI, GateInfoWidget=create):
                    widget.get_gate_widget(removed).clear_widget.click()
                self.assert_consistent(widget, 3)

    def test_minimum_gate_count(self):
        widget = self.widget()
        for _ in range(2):
            widget.get_gate_widget(widget.gate_data.getGates()[1]).clear_widget.click()
        self.assert_consistent(widget, 2)
        with patch.object(GREMLIN.ui.ui_common, "MessageBox") as message:
            widget.get_gate_widget(widget.gate_data.getGates()[0]).clear_widget.click()
            message.assert_called_once()
        self.assert_consistent(widget, 2)

    def test_queued_deleted_gate_does_not_restore_slider_handle(self):
        widget = self.widget()
        removed = widget.gate_data.getGates()[-1]
        QtCore.QTimer.singleShot(0, lambda: EVENTS.gate_display_changed.emit(removed))
        widget.deleteGate(removed)
        APP.processEvents()
        self.assert_consistent(widget, 3)

    def test_foreign_gate_does_not_change_slider(self):
        widget = self.widget()
        foreign = GateDataFixture([-1.0, -0.8, -0.4, 0.0, 0.4, 0.8, 1.0])
        EVENTS.gate_display_changed.emit(foreign.getGates()[-1])
        self.assert_consistent(widget, 4)

    def test_missing_neighbor_widgets(self):
        for index in (0, 2):
            with self.subTest(index=index):
                widget = self.widget()
                gates = widget.gate_data.getGates()
                neighbor = widget.get_gate_widget(gates[index])
                Shiboken.delete(neighbor)
                widget._update_range(gates[1])
                widget._reload_widgets()
                self.assert_consistent(widget, 4)

    def test_worker_reload_holds_lock_on_ui_thread(self):
        widget = self.widget()
        states = []
        factory = UI["GateInfoWidget"]

        def create(*args, **kwargs):
            states.append((QtCore.QThread.isMainThread(), widget._sort_lock))
            return factory(*args, **kwargs)

        with patch.dict(UI, GateInfoWidget=create):
            worker = threading.Thread(target=widget._sort_gate_layout)
            worker.start()
            worker.join()
            pump_until(lambda: len(states) == 4)
        self.assertEqual(states, [(True, True)] * 4)
        self.assertFalse(widget._sort_lock)
        self.assert_consistent(widget, 4)

    def test_edit_surviving_gate_after_delete(self):
        widget = self.widget()
        widget.deleteGate(widget.gate_data.getGates()[2])
        gate = widget.gate_data.getGates()[1]
        widget.get_gate_widget(gate).value_widget.setValue(-0.25)
        self.assertAlmostEqual(gate.value, -0.25)
        self.assert_consistent(widget, 3)

    def test_moving_gate_keeps_live_ranges_and_refreshes_labels(self):
        widget = self.widget()
        ranges = list(widget._rwi_map)
        gates = widget.gate_data.getGates()
        original_widget = widget.get_gate_widget(gates[1])
        widget._slider_value_changed_cb(1, -0.25)
        for before, after in zip(ranges, widget.gate_data.getUsedRanges()):
            self.assertIs(before, after)
        self.assertIn("-0.250", widget.get_range_widget(ranges[0]).range_widget.text())
        self.assertIn("-0.250", widget.get_range_widget(ranges[1]).range_widget.text())
        ranges[0].mode = UI["GateRangeOutputMode"].Fixed
        ranges[0].fixed_value = 0.42
        saved = widget.gate_data.to_xml().find("range")
        self.assertEqual(saved.get("mode"), "fixed")
        self.assertAlmostEqual(float(saved.get("fixed_value")), 0.42)
        original_widget.value_widget.setValue(-0.2)
        self.assertIs(widget.get_gate_widget(gates[1]), original_widget)
        self.assert_consistent(widget, 4)

    def test_delete_preserves_unaffected_range_configuration(self):
        for index in (0, 1, 3):
            with self.subTest(index=index):
                widget = self.widget()
                ranges = list(widget.gate_data.getUsedRanges())
                for number, rng in enumerate(ranges):
                    rng.description = f"range-{number}"
                removed = widget.gate_data.getGates()[index]
                unaffected = [rng for rng in ranges if removed.id not in (rng.g1.id, rng.g2.id)]
                widget.deleteGate(removed)
                for rng in unaffected:
                    self.assertTrue(any(current is rng for current in widget.gate_data.getUsedRanges()))
                    self.assertEqual(rng.description, f"range-{ranges.index(rng)}")
                self.assert_consistent(widget, 3)

    def test_split_and_merge_keep_lower_configuration_without_aliasing(self):
        widget = self.widget()
        lower, split, upper = widget.gate_data.getUsedRanges()
        split.description = "middle"
        split.autorelease_map[UI["GateConditionType"].EnterRange] = False
        added = widget._add_gate(0.0)
        current = widget.gate_data.getUsedRanges()
        self.assertIs(current[0], lower)
        self.assertIs(current[3], upper)
        self.assertEqual(current[1].description, "middle")
        self.assertFalse(current[1].autorelease_map[UI["GateConditionType"].EnterRange])
        self.assertFalse(current[2].hasAnyContainers())
        self.assertIsNot(current[1].item_data_map, current[2].item_data_map)
        self.assert_consistent(widget, 5)
        widget.deleteGate(added)
        self.assertEqual(widget.gate_data.getUsedRanges()[1].description, "middle")
        self.assert_consistent(widget, 4)

    def test_context_menu_delete_and_undo(self):
        widget = self.widget()
        before = self.xml(widget)
        action = QtGui.QAction("Delete Gate", widget)
        action.setData(1)
        action.triggered.connect(widget._trigger_delete_gate)
        action.trigger()
        self.assert_consistent(widget, 3)
        self.assert_undo_restores(widget, before, 4)

    def test_cancel_delete_keeps_configuration_and_undo_stack(self):
        widget = self.widget()
        gate = widget.gate_data.getGates()[1]
        gate.item_data_map[UI["GateConditionType"].OnCross] = InputItem()
        gate.item_data_map[UI["GateConditionType"].OnCross].containers = ["mapped action"]
        with patch.object(widget, "_prompt_delete", return_value=False) as prompt:
            widget.get_gate_widget(gate).clear_widget.click()
        prompt.assert_called_once()
        self.assertEqual(widget._stack, [])
        self.assert_consistent(widget, 4)

    def test_add_undo_restores_before_addition(self):
        widget = self.widget()
        before = self.xml(widget)
        widget._add_gate(0.0)
        self.assert_consistent(widget, 5)
        self.assert_undo_restores(widget, before, 4)

    def test_change_count_and_undo(self):
        for count in (2, 7):
            with self.subTest(count=count):
                widget = self.widget()
                before = self.xml(widget)
                widget._set_gate_count(count)
                self.assert_consistent(widget, count)
                self.assert_undo_restores(widget, before, 4)

    def test_normalize_buttons_save_one_snapshot_and_undo(self):
        for button_name in ("normalize_widget", "normalize_reset_widget"):
            with self.subTest(button=button_name):
                widget = self.widget((-0.9, -0.8, -0.7, 0.6))
                before = self.xml(widget)
                getattr(widget, button_name).click()
                expected = (-0.9, -0.4, 0.1, 0.6) if button_name == "normalize_widget" else (-1, -1 / 3, 1 / 3, 1)
                for gate, value in zip(widget.gate_data.getGates(), expected):
                    self.assertAlmostEqual(gate.value, value)
                self.assert_consistent(widget, 4)
                self.assert_undo_restores(widget, before, 4)

    def test_manual_edit_and_drag_undo(self):
        for manual in (False, True):
            with self.subTest(manual=manual):
                widget = self.widget()
                before = self.xml(widget)
                if manual:
                    widget.get_gate_widget(widget.gate_data.getGates()[1]).value_widget.setValue(-0.25)
                else:
                    widget._slider_drag_start_cb(1)
                    widget._slider_value_changed_cb(1, -0.25)
                    widget._slider_value_changed_cb(1, -0.2)
                self.assert_undo_restores(widget, before, 4)

    def test_undo_roundtrips_gate_and_range_mappings(self):
        widget = self.widget()
        gate = widget.gate_data.getGates()[1]
        rng = widget.gate_data.getUsedRanges()[1]
        gate.item_data_map[UI["GateConditionType"].OnCross] = InputItem()
        gate.item_data_map[UI["GateConditionType"].OnCross].containers = ["gate mapping"]
        rng.item_data_map[UI["GateConditionType"].EnterRange] = InputItem()
        rng.item_data_map[UI["GateConditionType"].EnterRange].containers = ["range mapping"]
        rng.mode = UI["GateRangeOutputMode"].Ranged
        rng.output_range_min, rng.output_range_max = -0.3, 0.7
        gate.autorelease_map[UI["GateConditionType"].OnCross] = False
        rng.autorelease_map[UI["GateConditionType"].InRange] = True
        before = self.xml(widget)
        widget.deleteGate(gate)
        self.assert_undo_restores(widget, before, 4)
        self.assertFalse(widget.gate_data.getGates()[1].autorelease_map[UI["GateConditionType"].OnCross])
        self.assertTrue(widget.gate_data.getUsedRanges()[1].autorelease_map[UI["GateConditionType"].InRange])

    def test_old_profiles_use_default_autorelease_flags(self):
        widget = self.widget()
        snapshot = widget.gate_data.to_xml()
        for node in snapshot.iter():
            for name in list(node.attrib):
                if name.startswith("autorelease_"):
                    del node.attrib[name]
        restored = GateDataFixture("Default", widget.action_data)
        restored.from_xml(snapshot, widget.input_item)
        self.assertTrue(restored.getGates()[0].autorelease_map[UI["GateConditionType"].OnCross])
        self.assertFalse(restored.getUsedRanges()[0].autorelease_map[UI["GateConditionType"].InRange])

    def test_failed_undo_keeps_stack_and_current_model(self):
        widget = self.widget()
        widget._add_gate(0.0)
        previous = widget.gate_data
        with patch.object(GateDataFixture, "from_xml", side_effect=ValueError("invalid snapshot")):
            with self.assertRaisesRegex(ValueError, "invalid snapshot"):
                widget._undo()
        self.assertEqual(len(widget._stack), 1)
        self.assertIs(widget.gate_data, previous)
        self.assertTrue(previous._hooked)
        self.assert_consistent(widget, 5)

    def test_percentage_edit_limits_drag_and_undo(self):
        widget = self.widget()
        widget._display_mode_widget.setCurrentIndex(widget._display_mode_widget.findData(UI["DisplayMode"].Percent))
        self.assert_consistent(widget, 4)
        before = self.xml(widget)
        gate = widget.gate_data.getGates()[1]
        widget.get_gate_widget(gate).value_widget.setValue(50.0)
        self.assertAlmostEqual(gate.value, 0.0)
        self.assert_consistent(widget, 4)
        self.assert_undo_restores(widget, before, 4)
        widget._slider_value_changed_cb(1, -0.25)
        self.assertAlmostEqual(widget.get_gate_widget(widget.gate_data.getGates()[1]).value_widget.value(), 37.5)
        self.assert_consistent(widget, 4)

    def test_custom_display_units_convert_back_to_model(self):
        widget = self.widget()
        widget.setDisplayRange(-100, 100)
        self.assert_consistent(widget, 4)
        before = self.xml(widget)
        gate = widget.gate_data.getGates()[1]
        widget.get_gate_widget(gate).value_widget.setValue(-25)
        self.assertAlmostEqual(gate.value, -0.25)
        self.assert_consistent(widget, 4)
        self.assert_undo_restores(widget, before, 4)
        self.assertEqual((widget.gate_data.display_range_min, widget.gate_data.display_range_max), (-100, 100))

    def test_stale_model_callbacks_after_undo_are_ignored(self):
        widget = self.widget()
        gate = widget.gate_data.getGates()[1]
        stale_widget = widget.get_gate_widget(gate)
        widget._add_gate(0.0)
        widget._undo()
        stale_widget.valueChanging.emit(gate)
        gate.setValue(-0.25, emit=True)
        self.assertEqual(widget._stack, [])
        self.assertAlmostEqual(widget.gate_data.getGates()[1].value, -0.5)
        self.assert_consistent(widget, 4)

    def test_grab_position_and_undo(self):
        widget = self.widget()
        before = self.xml(widget)
        gate = widget.gate_data.getGates()[1]
        widget._axis_value = -0.25
        widget.get_gate_widget(gate).requestGrab.emit(gate)
        self.assertAlmostEqual(gate.value, -0.25)
        self.assert_undo_restores(widget, before, 4)

    def test_reduce_and_normalize_creates_one_undo_entry(self):
        widget = self.widget()
        before = self.xml(widget)
        widget._set_steps_confirm_cb(3)
        self.assert_consistent(widget, 3)
        self.assert_undo_restores(widget, before, 4)

    def test_rejected_percentage_edit_does_not_create_undo_entry(self):
        widget = self.widget()
        widget._display_mode_widget.setCurrentIndex(widget._display_mode_widget.findData(UI["DisplayMode"].Percent))
        gate = widget.gate_data.getGates()[1]
        widget.get_gate_widget(gate).value_widget.setValue(90)
        self.assertAlmostEqual(gate.value, -0.5)
        self.assertEqual(widget._stack, [])
        self.assert_consistent(widget, 4)

    def test_index_signal_updates_widget_once(self):
        widget = self.widget()
        gate = widget.gate_data.getGates()[1]
        gwi = widget.get_gate_widget(gate)
        with patch.object(gwi, "update_gate_label") as label:
            EVENTS.gate_index_changed.emit(gate)
            label.assert_called_once()

    def test_unhook_and_rehook_release_config_and_keyboard_subscriptions(self):
        keys = []
        with patch.object(Widget, "_keyboard_handler", lambda self, event: keys.append(event)):
            widget = self.widget()
            with patch.object(widget, "_options_changed_ui") as options:
                widget.unhook()
                widget.unhook()
                LISTENER.config_option_changed.emit()
                LISTENER.keyboard_event.emit("unhooked")
                self.assertEqual(keys, [])
                options.assert_not_called()
                widget.hook()
                widget.hook()
                LISTENER.config_option_changed.emit()
                LISTENER.keyboard_event.emit("hooked")
                self.assertEqual(keys, ["hooked"])
                options.assert_called_once()
            widget.unhook()

    def test_hiding_events_still_updates_range_count(self):
        widget = self.widget()
        widget._option_display_events = False
        widget.deleteGate(widget.gate_data.getGates()[1])
        self.assert_consistent(widget, 3)


if __name__ == "__main__":
    unittest.main()
