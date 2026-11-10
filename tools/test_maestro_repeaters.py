"""Real Qt viewer/repeater checks with retained Maestro state and mocked OSC.

Run: python tools/test_maestro_repeaters.py
"""

import math
import struct
import threading
import time
from types import SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, patch
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import test_virtual_output_selectors as outputs
from test_qt_marshalling import APP, Colors, flush_deletes, pump_until
from gremlin.types import CallbackMode, EventSourceType, HatDirection, VisualizationType, VjoyAction


macro = outputs.macro
ENV = dict(outputs.ENV, math=math, struct=struct, threading=threading, time=time,
           CallbackMode=CallbackMode, EventSourceType=EventSourceType, HatDirection=HatDirection,
           VisualizationType=VisualizationType, Callable=Callable, Qt=QtCore.Qt,
           QWidget=QtWidgets.QWidget, QtGui=QtGui, VjoyAction=VjoyAction)


def load(path, name, methods=None, base=None):
    return outputs.load(path, name, methods, base, ENV)


class Palette(Colors):
    def selectBorderColor(self):
        return "#808080"

    def ChannelColors(self):
        return [("#00ff00", "#008000")] * 4

    def cssRepeater(self):
        return ""

    cssButtonState = cssRepeater


def container(widgets=None, widget_only=False, **kwargs):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    for child in widgets if isinstance(widgets, list) else [widgets] if widgets else []:
        if child == "||":
            layout.addStretch()
        else:
            layout.addWidget(QtWidgets.QLabel(child) if isinstance(child, str) else child)
    return widget if widget_only else (widget, layout)


class Flow(QtWidgets.QHBoxLayout):
    lineCountChanged = QtCore.Signal(object, int)
    lineCount = 1


class Button(QtWidgets.QPushButton):
    def __init__(self, text, data, callback=None, **kwargs):
        super().__init__(text)
        self.data, self.highlight = data, False
        if callback:
            self.clicked.connect(lambda: callback(self))

    def _set_highlight_ui(self, value):
        self.highlight = value


class Event:
    def __init__(self, **kwargs):
        self.__dict__.update(dict(extra_data=None, raw_value=None, is_pressed=None,
                                 is_axis=False, source=EventSourceType.Virtual), **kwargs)

    def getInputType(self):
        return self.event_type


class Bus(QtCore.QObject):
    shutdown = QtCore.Signal()
    profile_loaded = QtCore.Signal()
    profile_unhook = QtCore.Signal()
    device_initialized = QtCore.Signal()
    changed = QtCore.Signal(str, object)
    vjoy_output_event = QtCore.Signal(object)
    vjoy_output_event_ui = QtCore.Signal(object)
    joystick_event = QtCore.Signal(object)


class InputItem:
    def __init__(self, device, kind, input_id):
        self.device_guid, self.kind, self.input_id = device.device_guid, kind, input_id

    def getOverrideInputType(self):
        return self.kind


ENV.update(Event=Event, Color=Palette, QFlowLayout=Flow, QUsedPushButton=Button,
           load_icon=lambda *args, **kwargs: QtGui.QIcon(),
           getVContainer=container, getHContainer=container,
           QFloatLineEdit=macro.QFloatLineEdit, Pixmaps=lambda: NS(
               onIconPixmap=QtGui.QPixmap(16, 16), offIconPixmap=QtGui.QPixmap(16, 16)))
AxisValues = load("gremlin/event_handler.py", "AxisValues")
ENV["_pin_deleted_widget"] = Mock()
load("gremlin/util.py", "delete_widget")
Processor = load("gremlin/event_handler.py", "JoystickEventProcessor", {
    "registerListenerUICallback", "unregisterListenerUICallback", "_fireCallbacks_ui", "process_vjoy_ui",
}, "object")
for name in ("_normalize_axis_value_key", "QProgressBar", "QJoystickListener", "QAxisRepeaterProgressbar",
             "QButtonStateWidget", "JoystickDeviceAxisStateWidget", "HatWidget", "HatState",
             "AxesTimeline", "TimeLinePlotWidget", "JoystickDeviceButtonStateWidget"):
    load("gremlin/ui/ui_common.py", name)
Maestro = load("gremlin/maestro.py", "Maestro", {
    "_control", "_notify_output", "_set_axis", "_set_button", "_set_hat", "setAxis", "setButton", "setHat",
    "_read_axis_raw", "_read_button", "_read_hat", "markOutputUsed", "getController", "syncDinput",
}, "object")
for name in ("MaestroAxis", "MaestroButton", "MaestroHat", "MaestroOutputDevice"):
    load("gremlin/maestro.py", name)
Selector = load("gremlin/ui/input_viewer.py", "VisualizationSelector", {"selectVirtualDevice", "_available_devices", "_reload_selector_ui"}, "QtWidgets.QWidget")
Dialog = load("gremlin/ui/input_viewer.py", "InputViewerDialog", {"_update_virtual_selector", "_closed"}, "QtWidgets.QWidget")
ENV["HAT_POSITIONS"] = {(0, 0): 0, (0, 1): 1, (1, 1): 2, (1, 0): 3, (1, -1): 4,
                        (0, -1): 5, (-1, -1): 6, (-1, 0): 7, (-1, 1): 8}
macro.module("gremlin.input_item", InputItem=InputItem, getInputIdKey=lambda value: value)
macro.module("gremlin.maestro", MaestroOutputDevice=ENV["MaestroOutputDevice"])
macro.module("gremlin.actions", Value=lambda value, raw=None, is_pressed=None: NS(current=value, raw=raw, is_pressed=is_pressed))
RemapFunctor = load("action_plugins/map_to_vjoy/__init__.py", "VJoyRemapFunctor", {
    "process_event", "_process_event", "_set_axis", "_is_maestro_target", "_output_key", "_output_device", "_send_flags",
}, "object")
macro.gremlin.types.EventSourceType = EventSourceType


class MaestroRepeaterTests(unittest.TestCase):
    setUpClass = classmethod(outputs.VirtualOutputSelectorTests.setUpClass.__func__)
    tearDownClass = classmethod(outputs.VirtualOutputSelectorTests.tearDownClass.__func__)

    def setUp(self):
        outputs.VirtualOutputSelectorTests.setUp(self)
        self.bus = Bus()
        self.processor = Processor()
        self.processor._listener_callbacks, self.processor._callback_map, self.processor._group_map = {}, {}, {}
        self.bus.vjoy_output_event_ui.connect(self.processor.process_vjoy_ui)
        macro.gremlin.event_handler.EventListener = lambda: self.bus
        macro.gremlin.event_handler.Event = Event
        macro.gremlin.event_handler.AxisValues = AxisValues
        macro.gremlin.event_handler.JoystickEventProcessor = lambda: self.processor
        macro.gremlin.event_handler.AxisState = lambda: NS(getAxisValues=lambda *args: AxisValues(0), getAxisData=lambda *args: None)
        macro.gremlin.shared_state.is_running = False
        macro.gremlin.shared_state.current_profile = None
        macro.CONFIG.verbose_mode_ui_level = lambda level: False
        macro.CONFIG.splitJoystickRepeater = True
        macro.CONFIG.changed = self.bus.changed
        macro.gremlin.util.assert_ui_thread = lambda: self.assertTrue(QtCore.QThread.isMainThread())
        macro.gremlin.util.to_guid = lambda value: value if isinstance(value, uuid.UUID) else uuid.UUID(value)
        macro.gremlin.util.scale_to_range = lambda value, source_min=-1, source_max=1, target_min=-1, target_max=1: target_min + (value - source_min) / (source_max - source_min) * (target_max - target_min)
        macro.gremlin.util.delete_widget = ENV["delete_widget"]
        macro.gremlin.joystick_handling.VirtualDeviceUsageState = lambda: NS(used_button_list=lambda guid: [])
        self.maestro.button_count, self.maestro.hat_count = 40, 2
        self.maestro.device_id = self.maestro.key = str(self.maestro.device_guid)
        self.vjoy.device_id = self.vjoy.key = str(self.vjoy.device_guid)
        macro.gremlin.joystick_handling.all_joystick_devices = lambda: self.devices
        macro.gremlin.shared_state.ui = NS(_get_tab_map=lambda: {})
        self.maestro.getAxisInputIdList = lambda: [1, 2]
        self.maestro.getAxisLinearId = lambda input_id: input_id
        self.maestro.getAxisName = self.maestro.get_axis_name
        self.service = Maestro()
        self.service.enabled, self.service._lock, self.service._stopping = True, threading.RLock(), threading.Event()
        self.service.client = NS(write=Mock())
        controller = NS(id="gex-1", key="controller-1", axis_count=2, button_count=40, hat_count=2, axis_names=["X", "Y"])
        self.service._controller_map = {1: controller}
        self.service._device_map = {1: self.maestro}
        self.maestro.data = {"maestro_key": controller.key}
        macro.gremlin.joystick_handling.maestro_devices = lambda connected_only=True: [device for device in self.devices if device.device_type == macro.DeviceType.Maestro]
        self.service._buffer_map = {1: bytearray(9) + bytearray([255, 255])}
        self.output = ENV["MaestroOutputDevice"](1, self.service)
        singleton = patch.dict(ENV, Maestro=lambda: self.service)
        singleton.start()
        self.addCleanup(singleton.stop)
        self.targets[self.maestro.device_guid].maestro = self.output
        self.targets[self.key].maestro = self.output
        macro.gremlin.joystick_handling.get_axis = lambda guid, axis: self.service._read_axis_raw(1, axis) / 32767
        macro.gremlin.joystick_handling.get_button = lambda guid, button: self.service._read_button(1, button)
        macro.gremlin.joystick_handling.get_hat_position = lambda guid, hat: self.output.hat(hat).direction

    def tearDown(self):
        for widget in self.widgets:
            if Shiboken.isValid(widget):
                if hasattr(widget, "unhook"):
                    widget.unhook()
                if hasattr(widget, "_cleanup_ui"):
                    widget._cleanup_ui()
        self.widgets = [widget for widget in self.widgets if Shiboken.isValid(widget)]
        outputs.VirtualOutputSelectorTests.tearDown(self)

    def widget(self, name):
        widget = ENV[name](self.maestro)
        self.widgets.append(widget)
        return widget

    def event(self, kind=None, input_id=1, value=0.5, source=EventSourceType.Virtual, device=None):
        kind = kind or macro.InputType.JoystickAxis
        return Event(device_guid=device or self.maestro.device_guid, event_type=kind, identifier=input_id,
                     value=value, is_pressed=bool(value), is_axis=kind == macro.InputType.JoystickAxis, source=source)

    def test_any_source_dispatch_and_explicit_sources_are_filtered_and_deduplicated(self):
        common, direct = Mock(), Mock()
        for source in (EventSourceType.Any, EventSourceType.Virtual):
            guid = self.key if source == EventSourceType.Any else self.maestro.device_guid
            self.processor.registerListenerUICallback(guid, macro.InputType.JoystickAxis, 1, common, CallbackMode.All, source)
        self.processor.registerListenerUICallback(self.maestro.device_guid, macro.InputType.JoystickAxis, 1, direct, CallbackMode.All, EventSourceType.dInput)
        self.processor._fireCallbacks_ui(self.event())
        common.assert_called_once()
        direct.assert_not_called()
        macro.gremlin.shared_state.is_running = True
        self.processor._fireCallbacks_ui(self.event(source=EventSourceType.dInput))
        self.assertEqual(common.call_count, 2)
        direct.assert_called_once()

    def test_unhook_removes_both_modes_and_all_sources_without_removing_other_controls(self):
        callback = Mock()
        for axis in (1, 2):
            for source in (EventSourceType.Any, EventSourceType.Virtual):
                self.processor.registerListenerUICallback(self.maestro.device_guid, macro.InputType.JoystickAxis, axis, callback, CallbackMode.All, source)
        self.processor.unregisterListenerUICallback(self.maestro.device_guid, macro.InputType.JoystickAxis, 1, callback)
        self.processor._fireCallbacks_ui(self.event())
        callback.assert_not_called()
        self.processor._fireCallbacks_ui(self.event(input_id=2))
        callback.assert_called_once()
        self.processor.unregisterListenerUICallback(callback=callback)
        self.assertNotIn(callback, self.processor._callback_map)

    def test_maestro_current_axes_update_bar_number_and_percent_without_feedback(self):
        widget = self.widget("JoystickDeviceAxisStateWidget")
        self.assertNotIn("#-1", widget.title())
        self.output.axis(2).value = 0.5
        pump_until(lambda: abs(widget.value_label_widgets[2].value() - 0.5) < 0.001 and widget.axis_widgets[2].value()[0] == 0.5)
        self.assertAlmostEqual(widget.axis_widgets[2].value()[0], 0.5)
        self.assertEqual(widget.percent_widgets[2].text(), "75.0 %")
        self.assertEqual(self.service.client.write.call_count, 1)

    def test_vjoyremap_updates_published_maestro_after_directinput_discovery_clears_matches(self):
        for local in (False, True):
            with self.subTest(local_service=local):
                self.service._local_service = local
                ENV["dinput"].DILL = NS(getDevices=lambda: [])
                self.service.syncDinput()
                self.assertEqual(self.service._device_map, {})
                widget = self.widget("JoystickDeviceAxisStateWidget")
                functor = RemapFunctor()
                functor._valid, functor.verbose, functor.verbose_extra = True, False, False
                functor.vjoy_id, functor.vjoy_input_id, functor.action_mode = 1, 1, VjoyAction.VJoyAxis
                functor.action_data = NS(virtual_device=self.maestro, action_mode=VjoyAction.VJoyAxis,
                                        axis_mode="absolute", curve_data=None,
                                        get_filtered_axis_value=lambda value, **kwargs: value,
                                        get_ranged_axis_value=lambda value: value)
                functor.usage_data, functor.functor_complete = NS(is_inverted=lambda *args: False), NS(emit=Mock())
                functor.getCurveData = Mock(return_value=None)
                event = self.event(value=0.5 if not local else -0.75)
                event.curve_value, event.is_repeater, event.force_remote = None, False, False
                functor.process_event(event)
                self.assertAlmostEqual(self.output.axis(1).value, event.value, places=3)
                APP.processEvents()
                self.assertAlmostEqual(widget.value_label_widgets[1].value(), event.value, places=3)
                self.assertAlmostEqual(widget.axis_widgets[1].value()[0], event.value, places=3)

    def test_maestro_initial_axis_and_temporal_samples_use_retained_output(self):
        self.output.axis(1).value = -0.75
        widget = self.widget("JoystickDeviceAxisStateWidget")
        self.assertAlmostEqual(widget.value_label_widgets[1].value(), -0.75, places=3)
        timeline = self.widget("AxesTimeline")
        timeline._update_points()
        self.assertAlmostEqual(timeline.plot_widget._series[1][-1], 0.75, places=3)

    def test_maestro_button_40_press_release_and_initial_state(self):
        self.output.button(40).is_pressed = True
        widget = self.widget("JoystickDeviceButtonStateWidget")
        button = widget._widget_map[40]
        self.assertTrue(button.isChecked())
        self.assertTrue(button.highlight)
        self.output.button(40).is_pressed = False
        self.assertFalse(button.isChecked())
        self.assertFalse(button.highlight)
        self.output.button(40).is_pressed = True
        self.assertTrue(button.isChecked())
        self.assertNotIn("#-1", widget.title())

    def test_maestro_hats_initial_state_directions_and_center_are_independent(self):
        self.output.hat(2).direction = (1, 1)
        widget = self.widget("HatState")
        self.assertNotEqual(widget._hat_map[2].angle, -1)
        for direction in ENV["HAT_POSITIONS"]:
            self.output.hat(1).direction = direction
            self.assertEqual(widget._hat_map[1].angle, widget._hat_map[1]._angle_map[direction])
        self.assertEqual(widget._hat_map[2].angle, widget._hat_map[2]._angle_map[(1, 1)])

    def test_single_axis_repeater_rebinds_to_another_axis_and_reads_initial_output(self):
        listener = ENV["QAxisRepeaterProgressbar"]()
        self.widgets.append(listener)
        listener.setInput(self.maestro.device_guid, macro.InputType.JoystickAxis, 1)
        self.output.axis(1).value = 0.75
        pump_until(lambda: listener.value()[0] == 0.75)
        listener.setInput(self.maestro.device_guid, macro.InputType.JoystickAxis, 2)
        self.output.axis(1).value = -0.5
        APP.processEvents()
        self.assertEqual(listener.value()[0], 0.75)
        self.output.axis(2).value = -0.25
        pump_until(lambda: listener.value()[0] == -0.25)
        listener._trigger_update_ui()
        self.assertAlmostEqual(listener.value()[0], -0.25, places=3)

    def test_button_and_hat_repeaters_default_to_any_source(self):
        for kind, input_id in ((macro.InputType.JoystickButton, 40), (macro.InputType.JoystickHat, 2)):
            changed = Mock()
            widget = ENV["QButtonStateWidget"](InputItem(self.maestro, kind, input_id), state_change_callback=changed)
            self.widgets.append(widget)
            self.assertEqual(widget._event_source, EventSourceType.Any)
            if kind == macro.InputType.JoystickButton:
                self.output.button(40).is_pressed = True
                self.assertTrue(widget._last_state_value)
                self.output.button(40).is_pressed = False
                self.assertFalse(widget._last_state_value)
            else:
                self.output.hat(2).direction = (1, 0)
                self.assertIn(HatDirection.East, widget._hat_icons)
                self.output.hat(2).direction = (0, 0)
                self.assertIn(HatDirection.Center, widget._hat_icons)
            self.assertEqual(changed.call_count, 2)

    def test_manual_axis_button_and_hat_controls_write_selected_maestro_once(self):
        axes = self.widget("JoystickDeviceAxisStateWidget")
        axes.value_label_widgets[1].setValue(0.25)
        self.assertEqual(self.service.client.write.call_count, 1)
        self.assertAlmostEqual(self.output.axis(1).value, 0.25, places=3)
        self.output.button(40).is_pressed = True
        buttons = self.widget("JoystickDeviceButtonStateWidget")
        self.service.client.write.reset_mock()
        buttons._widget_map[40].click()
        self.assertFalse(self.output.button(40).is_pressed)
        self.assertEqual(self.service.client.write.call_count, 1)
        hats = self.widget("HatState")
        self.service.client.write.reset_mock()
        hats._hat_map[2].clicked.emit((0, 1))
        self.assertEqual(self.output.hat(2).direction, (0, 1))
        self.assertEqual(self.service.client.write.call_count, 1)
        self.factory.assert_not_called()

    def test_closed_repeaters_leave_no_callbacks_in_either_profile_mode(self):
        widgets = [self.widget(name) for name in ("JoystickDeviceAxisStateWidget", "JoystickDeviceButtonStateWidget", "HatState")]
        for widget in widgets:
            if hasattr(widget, "unhook"):
                widget.unhook()
            else:
                widget._cleanup_ui()
        self.assertEqual(self.processor._callback_map, {})
        for running in (False, True):
            macro.gremlin.shared_state.is_running = running
            self.output.axis(1).value = 0.5
            self.output.button(40).is_pressed = True
            self.output.hat(2).direction = (1, 0)
        APP.processEvents()

    def test_deleted_button_is_pruned_without_stopping_other_button_updates(self):
        widget = self.widget("JoystickDeviceButtonStateWidget")
        button = widget._widget_map[40]
        Shiboken.delete(button)
        try:
            self.processor._fireCallbacks_ui(self.event(macro.InputType.JoystickButton, 40, True))
            self.assertNotIn(40, widget._widget_map)
            self.processor._fireCallbacks_ui(self.event(macro.InputType.JoystickButton, 1, True))
            self.assertTrue(widget._widget_map[1].highlight)
        finally:
            widget._widget_map.pop(40, None)

    def test_qt_parent_destruction_unregisters_button_repeater_callbacks(self):
        widget = self.widget("JoystickDeviceButtonStateWidget")
        callback = widget.process_event_ui
        self.assertIn(callback, self.processor._callback_map)
        Shiboken.delete(widget)
        self.assertNotIn(callback, self.processor._callback_map)
        for running in (False, True):
            macro.gremlin.shared_state.is_running = running
            self.processor._fireCallbacks_ui(self.event(macro.InputType.JoystickButton, 40, True))

    def test_queued_output_after_parent_deletion_still_updates_surviving_viewer(self):
        survivor = self.widget("JoystickDeviceButtonStateWidget")
        removed = self.widget("JoystickDeviceButtonStateWidget")
        callback = removed.process_event_ui
        worker = threading.Thread(target=lambda: setattr(self.output.button(40), "is_pressed", True))
        worker.start()
        worker.join()
        Shiboken.delete(removed)
        pump_until(lambda: survivor._widget_map[40].highlight)
        self.assertNotIn(callback, self.processor._callback_map)

    def test_callback_can_destroy_a_repeater_already_in_the_dispatch_snapshot(self):
        target = {}
        def destroy(event):
            Shiboken.delete(target["widget"])
        self.processor.registerListenerUICallback(self.maestro.device_guid, macro.InputType.JoystickButton,
                                                  40, destroy, CallbackMode.All)
        removed = target["widget"] = self.widget("JoystickDeviceButtonStateWidget")
        callback = removed.process_event_ui
        survivor = self.widget("JoystickDeviceButtonStateWidget")
        self.processor._fireCallbacks_ui(self.event(macro.InputType.JoystickButton, 40, True))
        self.assertFalse(Shiboken.isValid(removed))
        self.assertNotIn(callback, self.processor._callback_map)
        self.assertTrue(survivor._widget_map[40].highlight)
        self.processor.unregisterListenerUICallback(callback=destroy)

    def test_cleanup_tolerates_deleted_children_and_repeated_calls(self):
        widget = self.widget("JoystickDeviceButtonStateWidget")
        callback = widget.process_event_ui
        child = widget._widget_map[40]
        child.deleteLater()
        flush_deletes()
        self.assertFalse(Shiboken.isValid(child))
        widget._cleanup_ui()
        widget._cleanup_ui()
        self.assertEqual(widget._widget_map, {})
        self.assertNotIn(callback, self.processor._callback_map)

    def test_output_notifications_use_actual_axis_ids_and_controller_identity(self):
        self.maestro.axis_sequence_to_input_id = lambda index: (2, 8)[index]
        events = []
        self.bus.vjoy_output_event.connect(events.append)
        self.output.axis(2).value = 1.0
        self.assertEqual(events[-1].identifier, 8)
        self.assertEqual(events[-1].device_guid, self.maestro.device_guid)
        self.assertEqual(events[-1].source, EventSourceType.Virtual)

    def test_output_notifications_use_published_identity_instead_of_temporary_native_match(self):
        widget = self.widget("JoystickDeviceAxisStateWidget")
        native_match = NS(**self.maestro.__dict__)
        native_match.device_guid = uuid.UUID(int=99)
        self.service._device_map = {1: native_match}
        self.output.axis(1).value = 0.625
        APP.processEvents()
        self.assertAlmostEqual(widget.value_label_widgets[1].value(), 0.625, places=3)

    def test_failed_or_stopped_output_does_not_emit_a_false_state_change(self):
        notified = Mock()
        self.bus.vjoy_output_event.connect(notified)
        self.service.client.write.side_effect = OSError("Bridge unavailable")
        with self.assertRaises(OSError):
            self.output.axis(1).value = 0.5
        self.assertEqual(self.output.axis(1).value, 0.0)
        self.service._stopping.set()
        self.output.button(40).is_pressed = True
        self.output.hat(1).direction = (1, 0)
        notified.assert_not_called()

    def test_worker_outputs_are_delivered_on_the_gui_thread_without_input_loopback(self):
        axes, buttons, hats = [self.widget(name) for name in ("JoystickDeviceAxisStateWidget", "JoystickDeviceButtonStateWidget", "HatState")]
        loopback = Mock()
        self.bus.joystick_event.connect(loopback)
        def write():
            self.output.axis(1).value = -0.5
            self.output.button(40).is_pressed = True
            self.output.hat(2).direction = (0, -1)
        worker = threading.Thread(target=write)
        worker.start()
        worker.join()
        pump_until(lambda: buttons._widget_map[40].highlight and abs(axes.value_label_widgets[1].value() + 0.5) < 0.001)
        self.assertEqual(hats._hat_map[2].angle, hats._hat_map[2]._angle_map[(0, -1)])
        loopback.assert_not_called()

    def test_viewer_virtual_picker_includes_more_than_three_devices_and_keeps_guid(self):
        self.devices = [macro.device(i, f"Maestro {i}", macro.DeviceType.Maestro) for i in range(2, 8)]
        widget = Dialog()
        self.widgets.append(widget)
        widget.virtual_device_selector, widget.select_virtual_widget = QtWidgets.QComboBox(widget), QtWidgets.QPushButton(widget)
        widget.virtual_device_selector.autoSize = widget.virtual_device_selector.adjustSize
        widget._update_virtual_selector()
        self.assertEqual(widget.virtual_device_selector.count(), 6)
        guid = self.devices[-1].device_guid
        widget.virtual_device_selector.setCurrentIndex(widget.virtual_device_selector.findData(guid))
        self.devices.reverse()
        widget._update_virtual_selector()
        self.assertEqual(widget.virtual_device_selector.currentData(), guid)
        self.devices.clear()
        widget._update_virtual_selector()
        self.assertFalse(widget.select_virtual_widget.isEnabled())

    def test_selector_refresh_reloads_current_virtual_devices_and_filters_unavailable_ones(self):
        widget = Selector()
        self.widgets.append(widget)
        widget._devices = []
        widget._update_selector_ui = Mock()
        self.vjoy.disabled = True
        widget._reload_selector_ui()
        self.assertEqual(widget._devices, [self.maestro])
        self.maestro.connected = False
        widget._reload_selector_ui()
        self.assertEqual(widget._devices, [])

    def test_closing_viewer_disconnects_the_registered_slots_and_runs_cleanup(self):
        widget = Dialog()
        self.widgets.append(widget)
        widget.refresh, widget.reload, widget._cleanup_joystick_widgets = Mock(), Mock(), Mock()
        widget.main_layout = QtWidgets.QVBoxLayout(widget)
        widget._viewer_widget_map, widget._device_key_map, widget._event_data, widget._visualizer_widgets = {}, {}, {}, {}
        self.bus.profile_loaded.connect(widget.refresh)
        self.bus.profile_unhook.connect(widget.reload)
        self.bus.device_initialized.connect(widget.refresh)
        widget._closed()
        widget._cleanup_joystick_widgets.assert_called_once()
        self.bus.profile_loaded.emit()
        self.bus.profile_unhook.emit()
        self.bus.device_initialized.emit()
        widget.refresh.assert_not_called()
        widget.reload.assert_not_called()

    def test_select_virtual_device_includes_buttons_and_hats_and_separates_providers(self):
        widget = Selector()
        self.widgets.append(widget)
        controls = {}
        for device in (self.maestro, self.vjoy):
            key = getattr(device, "key", str(device.device_guid))
            for kind in (VisualizationType.AxisCurrent, VisualizationType.AxisTemporal, VisualizationType.Button, VisualizationType.Hat):
                controls[key, kind] = QtWidgets.QCheckBox(widget)
        widget._selector_widgets = controls
        widget._create_callback = lambda *args: Mock()
        widget.selectVirtualDevice(self.key)
        for (key, kind), checkbox in controls.items():
            self.assertEqual(checkbox.isChecked(), key == self.maestro.key and kind != VisualizationType.AxisTemporal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
