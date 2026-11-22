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
"""Real Qt viewer/repeater checks with retained Maestro state and mocked OSC.

Run: python tools/test_maestro_repeaters.py
"""

import math
from concurrent.futures import ThreadPoolExecutor
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
import test_remote
import test_vjoy
from test_qt_marshalling import APP, Colors, flush_deletes, pump_until
from gremlin import maestro_identity
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
load("gremlin/joystick_handling.py", "_maestro_output_summary")
get_virtual_output_axis = load("gremlin/joystick_handling.py", "get_virtual_output_axis")
ENV["_pin_deleted_widget"] = Mock()
load("gremlin/util.py", "delete_widget")
Processor = load("gremlin/event_handler.py", "JoystickEventProcessor", {
    "registerListenerUICallback", "unregisterListenerUICallback", "_fireCallbacks_ui", "process_vjoy_ui",
}, "object")
for name in ("_viewer_event_source", "_normalize_axis_value_key", "QProgressBar", "QJoystickListener", "QAxisRepeaterProgressbar",
             "QButtonStateWidget", "JoystickDeviceAxisStateWidget", "HatWidget", "HatState",
             "AxesTimeline", "TimeLinePlotWidget", "JoystickDeviceButtonStateWidget"):
    load("gremlin/ui/ui_common.py", name)
Maestro = load("gremlin/maestro.py", "Maestro", {
    "_control", "_notify_output", "_set_axis", "_set_button", "_set_hat", "setAxis", "setButton", "setHat",
    "_read_axis_raw", "_read_button", "_read_hat", "markOutputUsed", "getController", "syncDinput", "_scan_hid_order",
}, "object")
for name in ("MaestroAxis", "MaestroButton", "MaestroHat", "MaestroOutputDevice"):
    load("gremlin/maestro.py", name)
Selector = load("gremlin/ui/input_viewer.py", "VisualizationSelector", {"selectVirtualDevice", "_available_devices", "_reload_selector_ui"}, "QtWidgets.QWidget")
Dialog = load("gremlin/ui/input_viewer.py", "InputViewerDialog", {"_update_virtual_selector", "_closed"}, "QtWidgets.QWidget")
ENV["HAT_POSITIONS"] = {(0, 0): 0, (0, 1): 1, (1, 1): 2, (1, 0): 3, (1, -1): 4,
                        (0, -1): 5, (-1, -1): 6, (-1, 0): 7, (-1, 1): 8}
macro.module("gremlin.input_item", InputItem=InputItem, getInputIdKey=lambda value: value)
macro.MODULES["gremlin.maestro_identity"] = maestro_identity
macro.module("gremlin.maestro", MaestroOutputDevice=ENV["MaestroOutputDevice"])
macro.module("gremlin.actions", Value=lambda value, raw=None, is_pressed=None: NS(current=value, raw=raw, is_pressed=is_pressed))
RemapFunctor = load("action_plugins/map_to_vjoy/__init__.py", "VJoyRemapFunctor", {
    "process_event", "_process_event", "_set_axis", "_is_maestro_target", "_output_key", "_output_device", "_send_flags", "_can_broadcast",
    "_pulse_on", "_pulse_off",
    "client_list",
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
        macro.CONFIG.verbose_mode_maestro = False
        macro.CONFIG.enable_remote_broadcast = False
        macro.CONFIG.splitJoystickRepeater = True
        macro.CONFIG.changed = self.bus.changed
        macro.gremlin.util.assert_ui_thread = lambda: self.assertTrue(QtCore.QThread.isMainThread())
        macro.gremlin.util.to_guid = lambda value: value if isinstance(value, uuid.UUID) else uuid.UUID(value)
        macro.gremlin.util.scale_to_range = lambda value, source_min=-1, source_max=1, target_min=-1, target_max=1: target_min + (value - source_min) / (source_max - source_min) * (target_max - target_min)
        macro.gremlin.util.delete_widget = ENV["delete_widget"]
        macro.gremlin.joystick_handling.VirtualDeviceUsageState = lambda: NS(used_button_list=lambda guid: [])
        self.maestro.button_count, self.maestro.hat_count = 40, 2
        self.maestro.input_enabled = True
        self.vjoy.data = {}
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
        controller = NS(id="gex-1", key="controller-1", axis_count=2, button_count=40, hat_count=2, axis_names=["X", "Y"],
                        instance_token=None, profile=NS(VendorId=1, ProductId=0x4701))
        self.service._controller_map = {1: controller}
        self.service._active_service_devices = {}
        self.service._native_gamepad_inputs = []
        ENV.update(GEX_VENDOR_ID=1, GEX_PRODUCT_ID=1, gex_product_id=lambda device_id: 0x4701)
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
        ENV["get_output_target"] = macro.get_output_target
        macro.gremlin.joystick_handling.get_axis = lambda guid, axis: self.service._read_axis_raw(1, axis) / 32767
        ENV["get_axis"] = macro.gremlin.joystick_handling.get_axis
        macro.gremlin.joystick_handling.get_virtual_output_axis = get_virtual_output_axis
        ENV["joystick_handling"] = macro.gremlin.joystick_handling
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

    def test_vjoy_axis_preview_receives_and_writes_failover_output(self):
        self.targets[1] = self.targets[self.key]
        self.vjoy.getAxisInputIdList = lambda: [2]
        self.vjoy.getAxisLinearId = lambda input_id: 1
        self.vjoy.getAxisName = self.vjoy.get_axis_name
        self.output.axis(2).value = 0.5
        widget = ENV["JoystickDeviceAxisStateWidget"](self.vjoy)
        self.widgets.append(widget)
        editor = widget.value_label_widgets[2]
        self.assertAlmostEqual(editor.value(), 0.5, places=3)

        self.output.axis(2).value = -0.5
        pump_until(lambda: abs(editor.value() + 0.5) < 0.001)
        editor.setValue(0.25)
        self.assertAlmostEqual(self.output.axis(2).value, 0.25, places=3)
        self.factory.assert_not_called()

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

    def test_input_axis_repeater_constructor_registers_for_live_updates(self):
        changed = Mock()
        listener = ENV["QAxisRepeaterProgressbar"](
            input_item=InputItem(self.maestro, macro.InputType.JoystickAxis, 1),
            values=AxisValues(-0.5),
            state_change_callback=changed,
        )
        self.widgets.append(listener)
        self.assertTrue(listener.connected)
        self.assertIn(listener._handle_update_ui, self.processor._callback_map)
        self.assertEqual(listener.value(), [-0.5])

        # DirectInput uses Any; virtual output uses Virtual. Input rows accept both.
        self.processor._fireCallbacks_ui(self.event(value=0.25, source=EventSourceType.Any))
        self.assertEqual(listener.value(), [0.25])
        self.assertEqual(changed.call_args.args[0].actual, 0.25)
        self.output.axis(1).value = 0.75
        self.assertEqual(listener.value(), [0.75])
        self.assertEqual(changed.call_count, 2)

    def test_input_axis_repeater_parent_destruction_unregisters_callback(self):
        parent = QtWidgets.QWidget()
        listener = ENV["QAxisRepeaterProgressbar"](
            input_item=InputItem(self.maestro, macro.InputType.JoystickAxis, 1),
        )
        listener.setParent(parent)
        self.widgets.append(listener)
        callback = listener._handle_update_ui
        self.assertIn(callback, self.processor._callback_map)
        Shiboken.delete(parent)
        self.assertNotIn(callback, self.processor._callback_map)
        self.output.axis(1).value = 0.75

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

    def test_remote_vjoy_outputs_update_viewer_when_directinput_is_stale(self):
        test_vjoy.VJoyChecks.setUpClass()
        vjoy = test_vjoy.VJoyChecks()
        vjoy.setUp()
        self.addCleanup(vjoy.doCleanups)
        vjoy.services.event_handler.Event = Event
        vjoy.services.event_handler.EventListener = lambda: self.bus
        vjoy.ns["_output_event_context"].cache_clear()
        for control in (vjoy.axis, vjoy.button, vjoy.hat):
            control.device_guid = self.vjoy.device_guid
        outputs.Proxy.vjoy_devices[1] = vjoy.device
        ENV["get_axis"] = Mock(return_value=0.0)

        self.vjoy.axis_count = 1
        self.vjoy.getAxisInputIdList = lambda: [6]
        self.vjoy.getAxisLinearId = lambda input_id: 1
        self.vjoy.axis_sequence_to_input_id = lambda index: 6
        self.vjoy.getAxisName = self.vjoy.get_axis_name
        self.vjoy.button_count = self.vjoy.hat_count = 1
        axes, buttons, hats, timeline = [ENV[name](self.vjoy) for name in (
            "JoystickDeviceAxisStateWidget", "JoystickDeviceButtonStateWidget", "HatState", "AxesTimeline",
        )]
        self.widgets.extend((axes, buttons, hats, timeline))

        test_remote.RemoteChecks.setUpClass()
        remote = test_remote.RemoteChecks()
        remote.setUp()
        macro.gremlin.shared_state.is_running = True
        remote.services.joystick_handling.VJoyProxy = outputs.Proxy
        loopback = Mock()
        self.bus.joystick_event.connect(loopback)
        with ThreadPoolExecutor(max_workers=1) as worker:
            for send, args in (
                (remote.sender.send_axis, (1, 6, -0.5)),
                (remote.sender.send_button, (1, 1, True)),
                (remote.sender.send_hat, (1, 1, (0, -1))),
            ):
                send(*args)
                worker.submit(remote.transfer).result(timeout=2)

            pump_until(lambda: buttons._widget_map[1].highlight)
            self.assertAlmostEqual(axes.value_label_widgets[6].value(), -0.5, places=3)
            self.assertEqual(hats._hat_map[1].angle, hats._hat_map[1]._angle_map[(0, -1)])
            timeline._update_points()
            self.assertEqual(timeline.plot_widget._series[6][-1], 0.5)
            reopened_axes = ENV["JoystickDeviceAxisStateWidget"](self.vjoy)
            self.widgets.append(reopened_axes)
            self.assertAlmostEqual(reopened_axes.value_label_widgets[6].value(), -0.5, places=3)

            remote.sender.toggle_button(1, 1)
            worker.submit(remote.transfer).result(timeout=2)
            remote.sender.send_hat(1, 1, (0, 0))
            worker.submit(remote.transfer).result(timeout=2)
            pump_until(lambda: not buttons._widget_map[1].highlight and hats._hat_map[1].angle == -1)
        loopback.assert_not_called()

    def test_remote_maestro_outputs_use_bridge_layout_and_retained_values(self):
        output_view = NS(**vars(self.maestro))
        output_view.input_enabled = False
        output_view.is_gamepad = False
        output_view.data = self.maestro.data.copy()
        output_view.get_axis = lambda axis: self.service._read_axis_raw(1, axis)
        output_view.get_button = lambda button: self.service._read_button(1, button)
        output_view.get_hat = lambda hat: self.service._read_hat(1, hat)
        self.maestro.data["maestro_output_summary"] = output_view
        self.maestro.axis_count = self.maestro.button_count = self.maestro.hat_count = 1
        selector = Selector()
        self.widgets.append(selector)
        viewer_device = next(device for device in selector._available_devices() if device.device_guid == self.maestro.device_guid)
        self.assertIs(viewer_device, output_view)

        test_remote.RemoteChecks.setUpClass()
        remote = test_remote.RemoteChecks()
        remote.setUp()
        macro.gremlin.shared_state.is_running = True
        macro.CONFIG.enable_remote_broadcast = True
        routing = remote.services.joystick_handling
        routing.get_output_target = {self.key: NS(kind="maestro", maestro=self.output)}.get
        routing.get_output_device = {output_view.device_guid: self.output}.get
        remote.config.vjoy_installed = False
        routing.VJoyProxy = Mock(side_effect=AssertionError("Maestro output opened vJoy"))
        routing.vjoy_id_from_guid = Mock(return_value=None)
        master = NS(**vars(output_view))
        master.device_guid = uuid.UUID(int=42)
        master.virtual_id = 7
        master.name = "Master flight controls"
        master.data = {"maestro_key": "maestro://master:8010/gex-2"}
        output_view.data["maestro_key"] = "maestro://client:8010/gex-2"
        self.service._controller_map[1].key = output_view.data["maestro_key"]
        remote.ns["maestro_devices"] = lambda: [output_view]
        routing.get_virtual_device = {str(master.device_guid): master}.get

        functor = RemapFunctor()
        functor.remote_client = remote.sender
        config = remote.make_routing()
        functor.vjoy_id, functor.vjoy_input_id = master.virtual_id, 2
        functor.action_mode = VjoyAction.VJoyAxis
        functor.action_data = NS(virtual_device=master, action_mode=VjoyAction.VJoyAxis,
                                 sendFlags=lambda: (False, True), remote_config=config)
        functor.usage_data = NS(is_inverted=lambda *args: False)
        functor.verbose = functor.verbose_extra = False

        readbacks = {name: load("gremlin/joystick_handling.py", name) for name in ("get_axis", "get_button", "get_hat", "get_hat_position", "get_device")}
        hat_angles = {code * 4500 - 4500: direction for direction, code in ENV["HAT_POSITIONS"].items() if code}
        with patch.dict(ENV, readbacks, DeviceSummary=NS, vjoy=NS(Hat=NS(to_continuous_position=hat_angles))), patch.multiple(
            macro.gremlin.joystick_handling, get_button=readbacks["get_button"], get_hat_position=readbacks["get_hat_position"],
            maestro_devices=lambda: [output_view],
        ):
            with ThreadPoolExecutor(max_workers=1) as worker:
                remote.sender.send_axis(self.key, 2, -0.5)
                worker.submit(remote.transfer).result(timeout=2)
                remote.sender.send_button(2, 40, True)
                worker.submit(remote.transfer).result(timeout=2)
                remote.sender.send_hat(self.key, 2, (0, -1))
                worker.submit(remote.transfer).result(timeout=2)

                axes, buttons, hats, timeline = [ENV[name](viewer_device) for name in (
                    "JoystickDeviceAxisStateWidget", "JoystickDeviceButtonStateWidget", "HatState", "AxesTimeline",
                )]
                self.widgets.extend((axes, buttons, hats, timeline))
                self.assertAlmostEqual(axes.value_label_widgets[2].value(), -0.5, places=3)
                self.assertTrue(buttons._widget_map[40].highlight)
                self.assertEqual(hats._hat_map[2].angle, hats._hat_map[2]._angle_map[(0, -1)])
                timeline._update_points()
                self.assertAlmostEqual(timeline.plot_widget._series[2][-1], 0.5, places=3)

                functor._set_axis(master.virtual_id, 2, 0.75)
                packet = worker.submit(remote.transfer).result(timeout=2)
                self.assertEqual(packet["data"]["device"], {
                    "maestro_id": "gex-2", "name": "Master flight controls", "gamepad": False,
                })
                self.assertEqual(packet["to"], 0)
                remote.sender.toggle_button(self.key, 40)
                worker.submit(remote.transfer).result(timeout=2)
                config.isCustom = True
                config.getClient(0).selected = False
                config.addClient("Client", remote.receiver.clientId).selected = True
                functor.action_data.vjoy_hat_return_position = (0, 0)
                functor._pulse_off((master.virtual_id, macro.InputType.JoystickHat, 2, (0, -1), False, True, False))
                packet = worker.submit(remote.transfer).result(timeout=2)
                self.assertEqual(packet["to"], remote.receiver.clientId)
                pump_until(lambda: not buttons._widget_map[40].highlight and hats._hat_map[2].angle == -1)
                self.processor._fireCallbacks_ui(self.event(input_id=2, value=0.0, source=EventSourceType.dInput))
                self.assertAlmostEqual(axes.value_label_widgets[2].value(), 0.75, places=3)
        routing.VJoyProxy.assert_not_called()
        routing.vjoy_id_from_guid.assert_not_called()

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
        widget._devices = self.devices
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
