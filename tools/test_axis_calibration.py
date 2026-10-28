"""Calibration math and UI checks without hardware or configuration writes.

Run with: python tools/test_axis_calibration.py
Qt widgets use the offscreen platform; device and configuration services are fakes.
"""

import ast
import html
import logging
import math
import os
import sys
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from lxml import etree
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin import error  # noqa: E402
from gremlin.input_types import InputType  # noqa: E402
from gremlin.singleton_decorator import SingletonDecorator  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["calibration-checks", "-platform", "offscreen"])
DEVICE = "12345678-1234-1234-1234-123456789abc"


class Signal:
    def __init__(self):
        self.callbacks = []
        self.events = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, *args):
        self.events.append(args)
        for callback in list(self.callbacks):
            callback(*args)


class BaseDialog(QtWidgets.QDialog):
    def __init__(self, name, parent=None):
        super().__init__(parent)


class Slider(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int, float)

    def __init__(self, invoke=None):
        super().__init__()
        self.invoke = invoke or (lambda method, *args: method(*args))
        self.values = []
        self.markers = []

    def setValue(self, value):
        self.invoke(self._set_value_ui, value)

    def _set_value_ui(self, value):
        self.values.append(value)

    def setMarkerValue(self, value):
        self.invoke(self._set_marker_value_ui, value)

    def _set_marker_value_ui(self, value):
        self.markers.append(value)


class FloatWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.values = []

    def setValue(self, value):
        self._update_value(value)

    def _update_value(self, value, emit=True):
        self.values.append(value)


class DeadzoneWidget(QtWidgets.QWidget):
    def setValues(self, values):
        self.values = values


def definitions(path, names):
    return [node for node in ast.parse((ROOT / path).read_bytes()).body if getattr(node, "name", None) in names]


def load_calibration(source=None):
    utilities = dict(logging=logging, html=html, error=error)
    utility_nodes = definitions("gremlin/util.py", {
        "scale_to_range", "clamp", "axis_calibration", "slider_calibration",
        "normalize_guid", "compare_guid", "safe_read", "safe_format", "isNumeric",
        "read_bool", "parse_bool",
    })
    utilities["syslog"] = logging.getLogger("calibration-checks")
    exec(compile(ast.Module(body=utility_nodes, type_ignores=[]), "gremlin/util.py", "exec"), utilities)
    util = NS(**{name: value for name, value in utilities.items() if callable(value)})
    services = NS(util=util, singleton_decorator=NS(SingletonDecorator=SingletonDecorator))
    services.ui = NS(ui_common=NS(BaseDialogUi=BaseDialog))
    services.ui.ui_common.QDataComboBox = QtWidgets.QComboBox
    services.ui.ui_common.clear_layout = lambda layout: [layout.takeAt(0).widget().deleteLater() for _ in range(layout.count())]
    services.ui.ui_common.Buttons = NS(getOkWidget=lambda callback: QtWidgets.QPushButton("OK"))
    util.clear_layout = services.ui.ui_common.clear_layout
    namespace = dict(
        gremlin=services, QtWidgets=QtWidgets, QtCore=QtCore, QtGui=QtGui,
        InputType=InputType, Shiboken=Shiboken, QColor=QtGui.QColor, etree=etree,
        os=os, threading=threading, QSliderWidget=Slider, ui_common=services.ui.ui_common,
        parse_guid=uuid.UUID, safe_read=utilities["safe_read"], safe_format=utilities["safe_format"],
        syslog=logging.getLogger("calibration-checks"),
    )
    tree = ast.parse(source if source is not None else (ROOT / "gremlin/ui/axis_calibration.py").read_bytes())
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))]
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / "gremlin/ui/axis_calibration.py"), "exec"), namespace)
    return namespace


def reference_value(data, raw_value, normalize, util):
    """Original utility-based mapping, independent of the optimized fast path."""
    value = util.scale_to_range(raw_value, source_min=-32768, source_max=32767) if normalize else raw_value
    if data.inverted:
        value = util.scale_to_range(value, invert=True)
    if data.centered:
        value = util.axis_calibration(value, data.calibrated_min, data.calibrated_center, data.calibrated_max)
        if data.deadzone_center_min < value < data.deadzone_center_max:
            value = 0.0
        elif value <= data.deadzone_center_min:
            value = util.scale_to_range(value, source_min=data.deadzone_min, source_max=data.deadzone_center_min, target_max=0)
        elif value >= data.deadzone_center_max:
            value = util.scale_to_range(value, source_min=data.deadzone_center_max, source_max=data.deadzone_max, target_min=0)
    else:
        value = util.slider_calibration(value, data.calibrated_min, data.calibrated_max)
        value = util.scale_to_range(value, source_min=data.deadzone_min, source_max=data.deadzone_max)
    return value + 0.0


def load_input_item_reader(namespace):
    """Use the real profile parser with unrelated device UI imports disabled."""
    source = ROOT / "gremlin/input_item.py"
    item_class = next(node for node in ast.parse(source.read_bytes()).body if isinstance(node, ast.ClassDef) and node.name == "InputItem")
    reader = next(node for node in item_class.body if isinstance(node, ast.FunctionDef) and node.name == "from_xml")
    reader.body = [node for node in reader.body if not isinstance(node, ast.Import)]
    reader_namespace = dict(namespace, ContainerPlugins=lambda: NS(tag_map={}), html=html, read_bool=namespace["gremlin"].util.read_bool)
    curve_tag = definitions("gremlin/base_classes.py", {"_is_curve_tag"})
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *curve_tag, reader,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), reader_namespace)
    return reader_namespace["from_xml"]


class CalibrationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace = load_calibration()

    def setUp(self):
        self.ns = self.namespace
        self.services = self.ns["gremlin"]
        self.config = NS(
            changed=Signal(), filter_axis_events=False, filter_axis_threshold=0.005,
            verbose_mode_calib=False, get_calibration=Mock(return_value=(-32768, 0, 32767)),
        )
        self.listener = NS(
            calibration_changed=Signal(), joystick_event=Signal(), keyboard_event=Signal(),
            joystick_event_ui=Signal(),
        )
        self.services.config = NS(Configuration=lambda: self.config)
        self.services.event_handler = NS(EventListener=lambda: self.listener)
        self.services.shared_state = NS(
            data_path=str(ROOT / "tools"), current_profile=None,
            push_suspend_highlighting=Mock(), pop_suspend_highlighting=Mock(),
        )
        self.device = NS(
            device_guid=DEVICE, axis_count=2, name="test device",
            axismap_list=[NS(axis_index=1, linear_index=1), NS(axis_index=6, linear_index=2)],
        )
        self.services.joystick_handling = NS(physical_devices=lambda: [self.device], get_axis=Mock(return_value=0.0))
        self.on_ui = True
        self.pending = []
        self.services.util.is_ui_thread = lambda: self.on_ui
        self.services.util.assert_ui_thread = lambda: self.assertTrue(self.on_ui)
        self.services.util.InvokeUiMethod = Mock(side_effect=self.invoke)
        self.data = self.ns["CalibrationData"]()

    def invoke(self, method, *args):
        if self.on_ui:
            return method(*args)
        self.pending.append((method, args))

    def flush_ui(self):
        self.on_ui = True
        while self.pending:
            method, args = self.pending.pop(0)
            method(*args)

    def make_dialog(self):
        dialog_class = self.ns["CalibrationDialogEx"]
        dialog = dialog_class.__new__(dialog_class)
        QtWidgets.QDialog.__init__(dialog)
        dialog._closing = dialog._calibrating = dialog._auto_calibrate = False
        dialog._device_guid, dialog._input_id = DEVICE, 6
        dialog._lock = threading.Lock()
        dialog._axis_widget_limits = dialog._last_raw_value = dialog._last_calibrated_value = None
        dialog.action_data = self.data
        self.data.device_guid, self.data.input_id = DEVICE, 6
        dialog._input_slider_widget = Slider(self.services.util.InvokeUiMethod)
        dialog._calibrated_slider_widget = Slider(self.services.util.InvokeUiMethod)
        dialog._raw_value_widget, dialog._calibrated_value_widget = FloatWidget(), FloatWidget()
        dialog._calibrated_min_widget, dialog._calibrated_center_widget, dialog._calibrated_max_widget = FloatWidget(), FloatWidget(), FloatWidget()
        dialog._inverted_widget, dialog._auto_calibrate_widget = QtWidgets.QCheckBox(), QtWidgets.QCheckBox()
        dialog._container_center_widget = QtWidgets.QWidget()
        dialog._deadzone_widget = DeadzoneWidget()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def event(self, value=0.25, identifier=6, device_guid=DEVICE, is_axis=True, pressed=True):
        return NS(
            value=value, raw_value=int(value * 32767), identifier=identifier,
            device_guid=device_guid, is_axis=is_axis, is_pressed=pressed,
            event_type=InputType.JoystickAxis if is_axis else InputType.JoystickButton,
        )

    def test_numerical_mapping_matches_original_across_configurations(self):
        configurations = (
            (True, -1, 0, 1, -1, 0, 0, 1),
            (False, -1, 0, 1, -1, 0, 0, 1),
            (True, -0.8, 0.1, 0.9, -0.9, -0.1, 0.2, 0.95),
            (False, -0.7, 0, 0.9, -0.9, 0, 0, 0.8),
            (False, -2, 0, 2, -1, 0, 0, 1),
            (True, 0, 0, 0, -1, 0, 0, 1),
            (True, -1, None, 1, -1, 0, 0, 1),
        )
        fields = ("_is_centered", "_calibrated_min", "_calibrated_center", "_calibrated_max", "_deadzone_min", "_deadzone_center_min", "_deadzone_center_max", "_deadzone_max")
        for configuration in configurations:
            for name, value in zip(fields, configuration):
                setattr(self.data, name, value)
            for inverted in (False, True):
                self.data._inverted = inverted
                for normalize, samples in (
                    (True, (-40000, -32768, -12000, 0, 15000, 32767, 40000)),
                    (False, (-2, -1, -0.5, -0.1, -0.0, 0.0, 0.3, 0.7, 1, 2)),
                ):
                    for value in samples:
                        with self.subTest(configuration=configuration, inverted=inverted, normalize=normalize, value=value):
                            self.assertAlmostEqual(self.data.getValue(value, normalize), reference_value(self.data, value, normalize, self.services.util), places=12)

    def test_filter_return_shape_and_special_values_are_preserved(self):
        self.data.threshold_enabled = True
        self.data.threshold = 0.5
        self.assertEqual(self.data.getValue(0.25, normalize=False, filter=True), (0.25, True))
        self.assertEqual(self.data.getValue(-0.0, normalize=False), 0.0)
        self.assertEqual(math.copysign(1, self.data.getValue(-0.0, normalize=False)), 1)
        self.assertTrue(math.isnan(self.data.getValue(math.nan, normalize=False)))
        self.assertEqual(self.data.getValue(math.inf, normalize=False), 1)

    def test_direct_setting_changes_are_visible_without_cache_invalidation(self):
        self.assertEqual(self.data.getValue(0.4, normalize=False), 0.4)
        self.data._calibrated_max = 0.8
        self.assertAlmostEqual(self.data.getValue(0.4, normalize=False), 0.5)
        self.data._deadzone_center_max = 0.25
        self.assertAlmostEqual(self.data.getValue(0.4, normalize=False), 1 / 3)

    def test_deadzone_update_emits_once_with_complete_state(self):
        snapshots = []
        self.listener.calibration_changed.connect(lambda data: snapshots.append(data.deadzone))
        self.data.deadzone = [-0.9, -0.1, 0.2, 0.95]
        self.assertEqual(snapshots, [[-0.9, -0.1, 0.2, 0.95]])
        self.data.deadzone = [-0.9, -0.1, 0.2, 0.95]
        self.assertEqual(len(snapshots), 1)
        self.data.centered = False
        snapshots.clear()
        self.data.deadzone = [-0.8, 0.9]
        self.assertEqual(snapshots, [[-0.8, 0.9]])

    def test_deadzone_max_can_change_after_becoming_zero(self):
        self.data.deadzone_max = 0
        self.data.deadzone_max = 0.8
        self.assertEqual(self.data.deadzone_max, 0.8)
        count = len(self.listener.calibration_changed.events)
        self.data.deadzone_max = 0.8
        self.assertEqual(len(self.listener.calibration_changed.events), count)

    def test_copy_preserves_slider_and_threshold_configuration(self):
        self.data.centered = False
        self.data.threshold_enabled = True
        self.data.threshold = 0.125
        self.data.deadzone = [-0.8, 0.7]
        copied = self.ns["CalibrationData"](self.data)
        self.assertFalse(copied.centered)
        self.assertTrue(copied.threshold_enabled)
        self.assertEqual(copied.threshold, 0.125)
        self.assertEqual(copied.deadzone, [-0.8, 0.7])
        self.assertEqual(copied, self.data)

    def test_equality_detects_all_user_configuration_changes(self):
        self.assertNotEqual(self.data, None)
        for name, value in (
            ("centered", False), ("deadzone_min", -0.8), ("deadzone_max", 0.8),
            ("deadzone_center_min", -0.1), ("deadzone_center_max", 0.1),
            ("threshold_enabled", True), ("threshold", 0.1), ("inverted", True),
        ):
            with self.subTest(name=name):
                other = self.data.clone()
                setattr(other, name, value)
                self.assertNotEqual(self.data, other)

    def test_calibration_lifecycle_and_configuration_signal(self):
        self.assertFalse(self.data.calibrating())
        self.data.startCalibrate()
        self.assertTrue(self.data.calibrating())
        self.assertEqual(self.data.calibrated_min, 0)
        self.data.stopCalibrate()
        self.assertFalse(self.data.calibrating())
        self.config.changed.emit("filter_axis_events", True)
        self.config.changed.emit("filter_axis_threshold", 0.02)
        self.assertTrue(self.data.threshold_enabled)
        self.assertEqual(self.data.threshold, 0.02)

    def test_xml_load_notifies_once_and_roundtrips(self):
        self.data.device_guid, self.data.input_id = uuid.UUID(DEVICE), 6
        self.data.centered = False
        self.data.inverted = True
        self.data.deadzone = [-0.8, 0.9]
        self.data.threshold = 0.02
        node = self.data.to_xml()
        self.listener.calibration_changed.events.clear()
        loaded = self.ns["CalibrationData"]()
        loaded.from_xml(node)
        self.assertEqual(len(self.listener.calibration_changed.events), 1)
        self.assertEqual(loaded, self.data)
        self.assertEqual(etree.tostring(loaded.to_xml()), etree.tostring(node))

    def test_centered_xml_load_emits_complete_state_once(self):
        self.data.device_guid, self.data.input_id = uuid.UUID(DEVICE), 1
        self.data.calibrated_min, self.data.calibrated_center, self.data.calibrated_max = -0.8, 0.1, 0.9
        self.data.deadzone = [-0.9, -0.1, 0.2, 0.95]
        node = self.data.to_xml()
        snapshots = []
        self.listener.calibration_changed.connect(lambda data: snapshots.append((data.calibrated_center, data.deadzone)))
        loaded = self.ns["CalibrationData"]()
        loaded.from_xml(node)
        self.assertEqual(snapshots, [(0.1, [-0.9, -0.1, 0.2, 0.95])])
        self.assertEqual(loaded, self.data)

    def test_xml_without_device_does_not_emit_or_change_data(self):
        before = self.data.clone()
        for xml in ('<calibration/>', '<calibration device-guid="None"/>'):
            self.data.from_xml(etree.fromstring(xml))
        self.assertEqual(self.data, before)
        self.assertEqual(self.listener.calibration_changed.events, [])

    def test_manager_reuses_calibration_and_loads_legacy_only_once(self):
        manager = self.ns["CalibrationManager"]()
        manager.calibration_map.clear()
        first = manager.getCalibration(DEVICE, 6)
        self.assertIs(manager.getCalibration(DEVICE, 6), first)
        self.config.get_calibration.assert_called_once_with(DEVICE, 6)

    def test_manager_cache_misses_do_not_raise_debugger_exception_events(self):
        manager = self.ns["CalibrationManager"]()
        manager.calibration_map.clear()
        exceptions = []
        lookup_code = manager.getCalibration.__func__.__code__

        def trace(frame, event, arg):
            if frame.f_code is lookup_code and event == "exception" and issubclass(arg[0], KeyError):
                exceptions.append(arg[1])
            return trace

        previous_trace = sys.gettrace()
        try:
            sys.settrace(trace)
            zero = manager.getCalibration(DEVICE, 0)  # New device and axis.
            axis = manager.getCalibration(DEVICE, 6)  # Existing device, new axis.
            reused = manager.getCalibration(DEVICE, 6)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(exceptions, [])
        self.assertEqual(zero.input_id, 0)
        self.assertIs(reused, axis)
        self.assertEqual(self.config.get_calibration.call_count, 2)

    def test_profile_curve_uses_resolved_axis_calibration(self):
        reader = load_input_item_reader(self.ns)
        manager = self.ns["CalibrationManager"]()
        self.services.ui.axis_calibration = NS(CalibrationManager=lambda: manager)
        cases = (
            ('id="6"', 1, 6),
            ('id="6" input_id="0"', 1, 6),
            ('input_id="2"', 1, 2),
            ('', 7, 7),
        )
        for tag in ("curve-data", "response-curve", "response-curve-ex"):
            for attributes, initial_id, expected_id in cases:
                with self.subTest(tag=tag, attributes=attributes):
                    manager.calibration_map.clear()
                    expected = manager.getCalibration(DEVICE, expected_id)
                    expected._calibrated_min = -0.75
                    self.config.get_calibration.reset_mock()
                    curve = NS(_parse_xml=Mock(), calibration=None)
                    self.services.curve_handler = NS(AxisCurveData=Mock(return_value=curve))
                    item = NS(
                        device_guid=DEVICE, input_id=initial_id, input_type=InputType.JoystickAxis,
                        curve_data=None, _containers=Mock(), _handle_content_changed=Mock(),
                    )
                    item.setInputType = lambda value: setattr(item, "input_type", value)
                    root = etree.fromstring(f'<mode name="Default"><axis {attributes}><{tag}/></axis></mode>')
                    reader(item, root[0], item)
                    self.assertEqual(item.input_id, expected_id)
                    self.assertTrue(item.is_axis)
                    self.assertIs(item.curve_data.calibration, expected)
                    self.assertEqual(set(manager.calibration_map[DEVICE]), {expected_id})
                    curve._parse_xml.assert_called_once_with(root[0][0])
                    self.config.get_calibration.assert_not_called()

    def test_profile_axis_without_curve_resolves_id_without_loading_calibration(self):
        reader = load_input_item_reader(self.ns)
        item = NS(
            device_guid=DEVICE, input_id=0, input_type=InputType.JoystickAxis,
            curve_data=None, _containers=Mock(), _handle_content_changed=Mock(),
        )
        item.setInputType = lambda value: setattr(item, "input_type", value)
        root = etree.fromstring('<mode name="Default"><axis id="6"/></mode>')
        reader(item, root[0], item)
        self.assertEqual(item.input_id, 6)
        self.assertTrue(item.is_axis)
        self.assertIsNone(item.curve_data)
        self.config.get_calibration.assert_not_called()

    def test_manager_save_dispatches_only_when_off_ui_thread(self):
        manager = self.ns["CalibrationManager"]()
        with patch.object(manager, "_save_ui") as save:
            manager._save(False, True)
            save.assert_called_once_with(False, True, None)
            self.services.util.InvokeUiMethod.assert_not_called()
            self.on_ui = False
            manager._save(True, False)
            self.assertEqual(save.call_count, 1)
            self.flush_ui()
            save.assert_called_with(True, False, None)

    def test_legacy_dialog_creates_sparse_axes_once_and_filters_unrelated_events(self):
        widget_class = self.ns["AxisCalibrationWidget"]
        with patch.dict(self.ns, AxisCalibrationWidget=Mock(side_effect=widget_class)):
            dialog = self.ns["CalibrationUi"]()
            self.assertEqual(self.ns["AxisCalibrationWidget"].call_count, 2)
        self.addCleanup(dialog.close)
        dialog._handle_event(self.event(0.5))
        self.assertEqual(dialog.axes[1].slider.value(), int(0.5 * 32767))
        self.assertEqual(dialog.axes[0].slider.value(), 0)
        dialog._handle_event(self.event(device_guid="other"))
        dialog._handle_event(self.event(is_axis=False))
        dialog._handle_event(self.event(identifier=99))
        self.services.util.InvokeUiMethod.assert_not_called()

    def test_legacy_widget_only_rewrites_changed_labels(self):
        widget = self.ns["AxisCalibrationWidget"]()
        self.addCleanup(widget.deleteLater)
        labels = [NS(setText=Mock()) for _ in range(4)]
        widget.current, widget.minimum, widget.center, widget.maximum = labels
        widget.set_current(100)
        self.assertEqual([label.setText.call_count for label in labels], [1, 0, 0, 1])
        widget.set_current(100)
        self.assertEqual([label.setText.call_count for label in labels], [1, 0, 0, 1])
        widget.set_current(50)
        self.assertEqual([label.setText.call_count for label in labels], [2, 0, 0, 1])

    def test_dialog_keeps_bounds_stable_while_updating_live_readouts(self):
        dialog = self.make_dialog()
        for value in (0.1, 0.2, 0.2):
            dialog._joystick_event_handler(self.event(value))
        self.assertEqual(dialog._input_slider_widget.values, [[-1.0, 0.0, 1.0]])
        self.assertEqual(dialog._input_slider_widget.markers, [0.1, 0.2])
        self.assertEqual(dialog._raw_value_widget.values, [0.1, 0.2])
        self.assertEqual(dialog._calibrated_value_widget.values, [0.1, 0.2])
        self.assertEqual(dialog._calibrated_slider_widget.values, [0.1, 0.2])
        self.services.util.InvokeUiMethod.assert_not_called()

    def test_dialog_refreshes_bounds_after_settings_change(self):
        dialog = self.make_dialog()
        dialog._joystick_event_handler(self.event())
        self.data.calibrated_max = 0.8
        dialog._joystick_event_handler(self.event())
        self.assertEqual(len(dialog._input_slider_widget.values), 2)
        self.assertEqual(dialog._input_slider_widget.values[-1], [-1.0, 0.0, 0.8])
        self.assertAlmostEqual(dialog._calibrated_value_widget.values[-1], 0.3125)

    def test_manual_drag_restores_clamped_handles_even_if_limits_stay_unchanged(self):
        dialog = self.make_dialog()
        self.data._calibrated_min = 0.999
        dialog._update_ui(0.25)
        self.assertEqual(len(dialog._input_slider_widget.values), 1)
        dialog._slider_changed(0, 1.5)
        self.assertEqual(self.data.calibrated_min, 0.999)
        self.assertEqual(len(dialog._input_slider_widget.values), 2)
        self.assertEqual(dialog._input_slider_widget.values[-1], [0.999, 0.0, 1.0])

    def test_dialog_worker_events_are_marshaled_and_closed_events_ignored(self):
        dialog = self.make_dialog()
        self.on_ui = False
        dialog._joystick_event_handler(self.event())
        self.assertEqual(dialog._input_slider_widget.markers, [])
        self.assertEqual(len(self.pending), 1)
        self.flush_ui()
        self.assertEqual(dialog._input_slider_widget.markers, [0.25])
        dialog._closing = True
        dialog._joystick_event_handler(self.event(0.5))
        self.assertEqual(dialog._input_slider_widget.markers, [0.25])

    def test_auto_calibration_uses_every_extreme_without_requerying_device(self):
        dialog = self.make_dialog()
        dialog._auto_calibrate = True
        dialog._auto_calibrate_widget.setChecked(True)
        self.data._calibrated_min = self.data._calibrated_max = 0
        for value in (-0.8, 0.9, 0.2, -0.9):
            dialog._joystick_event_handler(self.event(value))
        self.assertEqual((self.data.calibrated_min, self.data.calibrated_max), (-0.9, 0.9))
        self.assertEqual(dialog._input_slider_widget.markers, [-0.8, 0.9, 0.2, -0.9])
        self.assertEqual(len(self.listener.calibration_changed.events), 3)
        self.services.joystick_handling.get_axis.assert_not_called()

    def test_capture_listener_filters_events_before_dispatch_and_keeps_extrema(self):
        widget = self.ns["CalibrationListenerWidget"](DEVICE, 6, None)
        self.addCleanup(widget.close)
        widget.joystick_event_handler(self.event(device_guid="other"))
        widget.joystick_event_handler(self.event(identifier=1))
        widget.joystick_event_handler(self.event(is_axis=False, pressed=False))
        for value in (-0.7, 0.9, -0.8, 0.2):
            widget.joystick_event_handler(self.event(value))
        self.assertEqual((widget.calibrationMin, widget.calibrationMax), (-0.8, 0.9))
        self.services.util.InvokeUiMethod.assert_not_called()


if __name__ == "__main__":
    unittest.main()
