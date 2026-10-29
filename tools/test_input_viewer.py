"""Input viewer trash/selector checks with real Qt and no hardware/config writes.

Run: python tools/test_input_viewer.py
"""

import ast
from enum import IntEnum
import functools
import inspect
import logging
import time
from types import SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import patch
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from test_qt_marshalling import APP, Colors, definitions, flush_deletes, invoke, pump_until
from test_wait_cursor import Manager as CursorManager, showing_wait


def load(path, names, members=None, base=None):
    nodes = definitions(path, names)
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            if members is not None:
                node.body = [member for member in node.body if getattr(member, "name", None) in members]
            if base:
                node.bases = [ast.Name(id=base, ctx=ast.Load())]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, "exec"), NAMESPACE)


def container(widgets, widget_only=False, **kwargs):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(widget)
    for child in widgets:
        if child == "||":
            continue
        stretch = 0
        if isinstance(child, tuple):
            child, stretch = child
        layout.addWidget(QtWidgets.QLabel(child) if isinstance(child, str) else child, stretch)
    return widget if widget_only else (widget, layout)


class IconButton(QtWidgets.QPushButton):
    def __init__(self, callback=None, parent=None, **kwargs):
        super().__init__(parent)
        if callback:
            self.clicked.connect(lambda: callback(self))


class DeviceSummary:
    axis_count = 1
    vjoy_id = -1
    button_count = hat_count = virtual_id = 0
    connected = True
    disabled = is_virtual = False

    def __init__(self, key):
        self.key = self.device_id = self.device_guid = key
        self.name = key

    def getAxisInputIdList(self):
        return [1]

    def axis_sequence_to_input_id(self, index):
        return index + 1

    def get_axis_name(self, input_id):
        return "X"


class Bus(QtCore.QObject):
    shutdown = QtCore.Signal()


class ViewerConfig:
    def __init__(self):
        self.values = {}
        self.devices = {}

    def reload(self):
        pass

    def getKey(self, device, visualization):
        return (device.key, visualization)

    def getDevice(self, key):
        return self.devices.get(key)

    def getValue(self, key, device, visualization):
        return self.values.get(key, False)

    def setValue(self, key, device, visualization, value):
        self.values[key] = value
        self.devices[key] = device


CONFIG = NS(verbose_mode_ui=False, input_viewer_combine_buttonhats=True)
VC = ViewerConfig()
BUS = Bus()
CURSOR_MANAGER = CursorManager()
DEVICES = [DeviceSummary("Stick"), DeviceSummary("Other stick")]
PINNED = []
ICONS = NS(circleArrowRight=QtGui.QIcon, circleArrowLeft=QtGui.QIcon)
COMMON = NS(Buttons=NS(getDeleteWidget=lambda **kwargs: QtWidgets.QPushButton("Trash")),
            getHContainer=container, QHorizontalLine=QtWidgets.QFrame, Icons=ICONS)
SERVICES = NS(
    util=NS(get_guid=uuid.uuid4, InvokeUiMethod=invoke, is_ui_thread=lambda: True),
    config=NS(Configuration=lambda: CONFIG),
    ui=NS(ui_common=COMMON),
    joystick_handling=NS(all_joystick_devices=lambda: DEVICES,
                        getDeviceName=lambda guid: guid),
    event_handler=NS(EventListener=lambda: BUS, JoystickEventProcessor=lambda: NS(),
                     AxisState=lambda: NS(getAxisValues=lambda *args: NS(actual=0.5))),
    shared_state=NS(ui=NS(_get_tab_map=lambda: {})),
)
NAMESPACE = dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets,
                 QWidget=QtWidgets.QWidget, Qt=QtCore.Qt, Shiboken=Shiboken,
                 Signal=QtCore.Signal, Callable=Callable, IntEnum=IntEnum, DeviceSummary=DeviceSummary,
                 gremlin=SERVICES, ui_common=COMMON, inspect=inspect, time=time,
                 Color=Colors, Icons=ICONS, QIconButton=IconButton,
                 getVContainer=container, getHContainer=container,
                 VisualizationConfig=lambda: VC,
                 WorkManager=lambda: CURSOR_MANAGER, functools=functools,
                 _pin_deleted_widget=PINNED.append,
                 syslog=logging.getLogger("input-viewer-checks"))
load("gremlin/worker.py", {"with_wait_cursor"})
load("gremlin/types.py", {"VisualizationType"})
VisualizationType = NAMESPACE["VisualizationType"]
VC.keyboard_key = ("Keyboard", VisualizationType.Keyboard)
VC.state_key = ("State", VisualizationType.State)
SERVICES.types = NS(VisualizationType=VisualizationType)
load("gremlin/util.py", {"delete_widget", "clear_layout", "_clear_layout", "get_layout_widgets"})
for name in ("delete_widget", "clear_layout", "get_layout_widgets"):
    setattr(SERVICES.util, name, NAMESPACE[name])
load("gremlin/ui/ui_common.py", {"QDataCheckbox"}, {
    "__init__", "_handle_clicked", "setReadOnly", "data", "setIgnoreKeyboard",
})
load("gremlin/ui/ui_common.py", {"QActionCheckbox", "AxesTimeline", "TimeLinePlotWidget", "resetWidgetSize"})
COMMON.QActionCheckbox = NAMESPACE["QActionCheckbox"]
COMMON.resetWidgetSize = NAMESPACE["resetWidgetSize"]
load("gremlin/ui/ui_common.py", {"JoystickDeviceWidget"}, {
    "__init__", "_handle_shutdown", "device_guid", "hook", "unhook", "_cleanup_ui", "_create_temporal_axis",
})
COMMON.JoystickDeviceWidget = NAMESPACE["JoystickDeviceWidget"]
load("gremlin/ui/input_viewer.py", {"VisualizerWidget", "VisualizationSelector"})
load("gremlin/ui/input_viewer.py", {"InputViewerDialog"}, {
    "closeSystemWidget", "_add_widget", "_add_remove_visualization_widget", "_visualizer_count", "_update_ui",
    "_clear_all", "_clear", "_clear_joystick_visualizers", "_delete_widget", "_cleanup_joystick_widgets",
    "load_viewer_widgets", "showKeyboard", "hideKeyboard", "showState", "hideState",
    "saveKeyboardState", "saveStateState", "_select_used",
}, base="QWidget")
load("gremlinEx.py", {"GremlinUi"}, {"_get_tab_map", "getMappedDeviceList"}, base="object")


class InputViewerTests(unittest.TestCase):
    def setUp(self):
        VC.values.clear()
        VC.devices.clear()
        self.viewer = NAMESPACE["InputViewerDialog"]()
        self.viewer._viewer_widget_map = {}
        self.viewer._device_key_map = {}
        self.viewer._visualizer_widgets = {}
        self.viewer._state_visible = self.viewer._keyboard_visible = False
        self.viewer.visualizerWidth = 620
        self.viewer._stacked_widget = QtWidgets.QStackedWidget(self.viewer)
        self.viewer._stacked_widget.addWidget(QtWidgets.QWidget())
        self.viewer._stacked_widget.addWidget(QtWidgets.QWidget())
        self.layout = QtWidgets.QVBoxLayout(self.viewer)
        self.viewer.views = NS(add_widget=lambda key, widget: self.layout.addWidget(widget))
        self.selector = NAMESPACE["VisualizationSelector"](
            change_callback=self.viewer._add_remove_visualization_widget, viewer=self.viewer,
        )
        self.viewer.vis_selector = self.selector
        self.selector.updateSelector()
        self.key = (DEVICES[0].key, VisualizationType.AxisTemporal)
        self.viewer._add_remove_visualization_widget(DEVICES[0], VisualizationType.AxisTemporal, True)

    def tearDown(self):
        for wrapper in self.viewer._viewer_widget_map.values():
            if wrapper.widget is not None and Shiboken.isValid(wrapper.widget):
                SERVICES.util.delete_widget(wrapper.widget)
        self.selector.deleteLater()
        self.viewer.deleteLater()
        flush_deletes()
        PINNED.clear()
        pump_until(lambda: not showing_wait())

    def click_trash(self, key=None):
        wrapper = self.viewer._viewer_widget_map[key or self.key]
        wrapper.findChild(QtWidgets.QPushButton).click()

    def assert_closed(self):
        self.assertIsNone(self.viewer._viewer_widget_map[self.key].widget)
        self.assertNotIn(self.key, self.viewer._visualizer_widgets)
        self.assertFalse(self.selector._selector_widgets[self.key].isChecked())
        self.assertFalse(VC.values[self.key])
        self.assertEqual(self.viewer._stacked_widget.currentIndex(), 0)

    def test_trash_closes_timeline_and_stops_both_timers(self):
        content = self.viewer._visualizer_widgets[self.key]
        timers = content.findChildren(QtCore.QTimer)
        self.assertEqual(len(timers), 2)
        self.assertTrue(all(timer.isActive() for timer in timers))
        self.click_trash()
        self.assert_closed()
        self.assertTrue(all(not timer.isActive() for timer in timers))
        flush_deletes()
        self.assertFalse(Shiboken.isValid(content))

    def test_trash_closes_timeline_after_selector_rebuild(self):
        old_selector = self.selector._selector_widgets[self.key]
        self.selector.updateSelector()
        flush_deletes()
        self.assertFalse(Shiboken.isValid(old_selector))
        self.click_trash()
        self.assert_closed()

    def test_selector_after_rebuild_reads_current_checkbox_before_old_is_deleted(self):
        self.selector.updateSelector()
        self.selector._selector_widgets[self.key]._checkbox.click()
        self.assert_closed()

    def test_timeline_can_be_reopened_after_rebuilding_selectors_and_closing(self):
        old_content = self.viewer._visualizer_widgets[self.key]
        self.selector.updateSelector()
        flush_deletes()
        self.click_trash()
        self.assert_closed()
        self.selector._selector_widgets[self.key]._checkbox.click()
        content = self.viewer._visualizer_widgets[self.key]
        self.assertIsNot(content, old_content)
        self.assertTrue(all(timer.isActive() for timer in content.findChildren(QtCore.QTimer)))

    def test_trash_keeps_other_device_timeline_running(self):
        other_key = (DEVICES[1].key, VisualizationType.AxisTemporal)
        self.viewer._add_remove_visualization_widget(DEVICES[1], VisualizationType.AxisTemporal, True)
        other_content = self.viewer._visualizer_widgets[other_key]
        self.click_trash()
        self.assertIsNone(self.viewer._viewer_widget_map[self.key].widget)
        self.assertIs(self.viewer._viewer_widget_map[other_key].widget, other_content)
        self.assertTrue(all(timer.isActive() for timer in other_content.findChildren(QtCore.QTimer)))
        self.assertEqual(self.viewer._stacked_widget.currentIndex(), 1)


class StaticVisualizer(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.hooked = False

    def hook(self):
        self.hooked = True

    def unhook(self):
        self.hooked = False

    def setReadonly(self, value):
        pass

    def populateState(self):
        pass

    def buttonWidget(self):
        return self

    def hatWidget(self):
        return self


class SelectUsedTests(unittest.TestCase):
    def setUp(self):
        VC.values.clear()
        VC.devices.clear()
        self.keyboard = DeviceSummary("Keyboard")
        self.state = DeviceSummary("State")
        self.stick = DeviceSummary("Stick")
        self.stick.device_guid = uuid.uuid4()
        self.stick.key = self.stick.device_id = str(self.stick.device_guid)
        self.stick.button_count = self.stick.hat_count = 1
        self.vjoy = DeviceSummary("VJoy GUID")
        self.vjoy.key = (1, 1, 0, 0)
        self.vjoy.vjoy_id = 1
        self.vjoy.is_virtual = True
        self.disconnected = DeviceSummary("Disconnected")
        self.disconnected.connected = False
        self.disabled = DeviceSummary("Disabled")
        self.disabled.disabled = True
        self.devices = [self.stick, self.vjoy, self.disconnected, self.disabled]
        device_map = {device.device_id: device for device in [*self.devices, self.keyboard, self.state]}
        self.mapped = []
        self.actions = []
        self.created = []
        real_joystick_widget = COMMON.JoystickDeviceWidget

        def create_visualizer(device, visualization):
            self.created.append((device.key, visualization))
            if visualization == VisualizationType.AxisTemporal:
                return real_joystick_widget(device, visualization)
            return StaticVisualizer()

        for target, values in (
            (SERVICES.joystick_handling, dict(all_joystick_devices=lambda: self.devices,
                                            getDevice=lambda guid: device_map.get(str(guid)),
                                            getDeviceName=lambda guid: device_map[str(guid)].name,
                                            getDeviceFromVjoyId=lambda vid: self.vjoy if vid == self.vjoy.vjoy_id else None)),
            (SERVICES.shared_state, dict(keyboard_tab_id="Keyboard", keyboard_tab_guid="Keyboard",
                                        state_tab_id="State", state_tab_guid="State",
                                        current_profile=NS(list_actions=lambda: self.actions))),
            (SERVICES.shared_state.ui, dict(getMappedDeviceList=lambda: self.mapped)),
            (SERVICES.ui, dict(virtual_keyboard=NS(QKeyboardWidget=StaticVisualizer),
                              state_device=NS(StateVisualizerWidget=StaticVisualizer))),
            (COMMON, dict(JoystickDeviceWidget=create_visualizer)),
        ):
            patcher = patch.multiple(target, create=True, **values)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.viewer = NAMESPACE["InputViewerDialog"]()
        self.viewer._viewer_widget_map = {}
        self.viewer._device_key_map = {}
        self.viewer._visualizer_widgets = {}
        self.viewer._state_visible = self.viewer._keyboard_visible = False
        self.viewer._keyboard_visualizer_widget = self.viewer.keyboard_widget = None
        self.viewer._state_visualizer_widget = self.viewer._state_filter_widget = None
        self.viewer.keyboard_widget_selector = COMMON.QActionCheckbox("Keyboard", parent=self.viewer)
        self.viewer.state_widget_selector = COMMON.QActionCheckbox("State", parent=self.viewer)
        self.viewer.visualizerWidth = 620
        self.viewer._stacked_widget = QtWidgets.QStackedWidget(self.viewer)
        self.viewer._stacked_widget.addWidget(QtWidgets.QWidget())
        self.viewer._stacked_widget.addWidget(QtWidgets.QWidget())
        self.layout = QtWidgets.QVBoxLayout(self.viewer)

        def clear_views():
            while self.layout.count():
                SERVICES.util.delete_widget(self.layout.takeAt(0).widget())

        def remove_view(key):
            self.layout.removeWidget(self.viewer._viewer_widget_map[key])

        self.viewer.views = NS(add_widget=lambda key, widget: self.layout.addWidget(widget),
                               clear=clear_views, remove_widget=remove_view)
        self.selector = NAMESPACE["VisualizationSelector"](
            change_callback=self.viewer._add_remove_visualization_widget, viewer=self.viewer,
        )
        self.viewer.vis_selector = self.selector
        self.selector.clear.connect(self.viewer._clear)
        self.viewer.load_viewer_widgets()
        self.selector.updateSelector()

    def tearDown(self):
        self.viewer._clear_all()
        self.selector.deleteLater()
        self.viewer.deleteLater()
        flush_deletes()
        PINNED.clear()
        pump_until(lambda: not showing_wait())

    def test_wait_cursor_covers_reconfiguration_and_deferred_layout_work(self):
        self.mapped[:] = [self.stick.device_guid, self.keyboard.device_guid, self.state.device_guid]
        seen = []

        def mapped_devices():
            self.assertTrue(showing_wait())
            QtCore.QTimer.singleShot(0, lambda: seen.append(showing_wait()))
            return self.mapped

        with patch.object(SERVICES.shared_state.ui, "getMappedDeviceList", mapped_devices):
            self.selector._select_used()

        self.assertTrue(showing_wait())
        self.assertEqual(CURSOR_MANAGER._cursor_push, 0)
        pump_until(lambda: not showing_wait())
        self.assertEqual(seen, [True])

    def test_failed_reconfiguration_releases_all_cursor_holds(self):
        with patch.object(self.viewer, "load_viewer_widgets", side_effect=RuntimeError("rebuild failed")):
            with self.assertRaisesRegex(RuntimeError, "rebuild failed"):
                self.selector._select_used()

        self.assertEqual(CURSOR_MANAGER._cursor_push, 0)
        pump_until(lambda: not showing_wait())

    def test_select_used_rebuilds_checked_views_including_vjoy_and_system_devices(self):
        self.mapped[:] = [self.stick.device_guid, self.vjoy.device_guid,
                          self.keyboard.device_guid, self.state.device_guid]
        self.selector._select_used()

        self.assertEqual(self.selector._devices, [self.stick, self.vjoy])
        expected = {(self.stick.key, VisualizationType.AxisCurrent),
                    (self.stick.key, VisualizationType.ButtonHat),
                    (self.vjoy.key, VisualizationType.AxisCurrent)}
        self.assertEqual(set(self.viewer._visualizer_widgets), expected)
        for key, widget in self.selector._selector_widgets.items():
            self.assertEqual(widget.isChecked(), key in expected)
            self.assertEqual(VC.values[key], key in expected)
        self.assertTrue(self.viewer.keyboard_widget_selector.isChecked())
        self.assertTrue(self.viewer.state_widget_selector.isChecked())
        self.assertTrue(self.viewer._keyboard_visible)
        self.assertTrue(self.viewer._state_visible)
        self.assertTrue(VC.values[VC.keyboard_key])
        self.assertTrue(VC.values[VC.state_key])
        self.assertNotIn(VisualizationType.AxisTemporal, [vis for _, vis in self.created])

    def test_select_used_clears_saved_timelines_and_unmapped_active_visualizers(self):
        old_key = (self.vjoy.key, VisualizationType.AxisTemporal)
        self.viewer._add_remove_visualization_widget(self.vjoy, VisualizationType.AxisTemporal, True)
        old_content = self.viewer._visualizer_widgets[old_key]
        timers = old_content.findChildren(QtCore.QTimer)
        mapped_timeline = (self.stick.key, VisualizationType.AxisTemporal)
        VC.setValue(mapped_timeline, self.stick, VisualizationType.AxisTemporal, True)
        self.viewer.showKeyboard()
        self.viewer.showState()
        old_checkbox = self.selector._selector_widgets[mapped_timeline]
        self.created.clear()
        self.mapped[:] = [self.stick.device_guid]

        self.selector._select_used()

        self.assertNotIn(old_key, self.viewer._visualizer_widgets)
        self.assertFalse(VC.values[old_key])
        self.assertFalse(VC.values[mapped_timeline])
        self.assertTrue(all(not timer.isActive() for timer in timers))
        self.assertFalse(self.viewer._keyboard_visible)
        self.assertFalse(self.viewer._state_visible)
        self.assertFalse(self.viewer.keyboard_widget_selector.isChecked())
        self.assertFalse(self.viewer.state_widget_selector.isChecked())
        self.assertFalse(VC.values[VC.keyboard_key])
        self.assertFalse(VC.values[VC.state_key])
        self.assertNotIn(VisualizationType.AxisTemporal, [vis for _, vis in self.created])
        flush_deletes()
        self.assertFalse(Shiboken.isValid(old_content))
        self.assertFalse(Shiboken.isValid(old_checkbox))

    def test_select_used_includes_vjoy_outputs_and_removes_them_when_no_longer_used(self):
        self.mapped[:] = [self.stick.device_guid]
        self.actions[:] = [NS(virtual_device=self.vjoy, vjoy_id=self.vjoy.vjoy_id),
                           NS(virtual_device=self.vjoy, vjoy_id=self.vjoy.vjoy_id)]
        self.selector._select_used()

        output_key = (self.vjoy.key, VisualizationType.AxisCurrent)
        self.assertIn(output_key, self.viewer._visualizer_widgets)
        self.assertTrue(self.selector._selector_widgets[output_key].isChecked())
        self.assertEqual(self.selector._devices.count(self.vjoy), 1)
        self.assertNotIn(VisualizationType.AxisTemporal, [vis for _, vis in self.created])

        self.actions.clear()
        self.selector._select_used()
        self.assertNotIn(output_key, self.viewer._visualizer_widgets)
        self.assertNotIn(output_key, self.selector._selector_widgets)
        self.assertFalse(VC.values[output_key])

    def test_select_used_resolves_vjoy_output_ids_and_skips_missing_outputs(self):
        self.actions[:] = [NS(virtual_device=None, vjoy_id=self.vjoy.vjoy_id),
                           NS(virtual_device=None, vjoy_id=99),
                           NS(virtual_device=None, vjoy_id=None)]
        self.selector._select_used()
        self.assertEqual(self.selector._devices, [self.vjoy])
        self.assertEqual(set(self.viewer._visualizer_widgets), {(self.vjoy.key, VisualizationType.AxisCurrent)})

    def test_select_used_clears_everything_when_no_supported_devices_are_mapped(self):
        self.mapped[:] = [self.stick.device_guid, self.keyboard.device_guid, self.state.device_guid]
        self.selector._select_used()
        self.mapped[:] = [self.disconnected.device_guid, self.disabled.device_guid, "Missing"]

        self.viewer._select_used()

        self.assertEqual(self.selector._selector_widgets, {})
        self.assertEqual(self.viewer._visualizer_widgets, {})
        self.assertFalse(self.viewer._keyboard_visible)
        self.assertFalse(self.viewer._state_visible)
        self.assertFalse(any(VC.values.values()))
        self.assertEqual(self.viewer._stacked_widget.currentIndex(), 0)

    def test_select_used_handles_system_only_mappings_independently(self):
        for mapped_device, other_key, visible_flag in (
            (self.keyboard, VC.state_key, "_keyboard_visible"),
            (self.state, VC.keyboard_key, "_state_visible"),
        ):
            with self.subTest(device=mapped_device.name):
                self.mapped[:] = [mapped_device.device_guid]
                self.selector._select_used()
                self.assertEqual(self.selector._selector_widgets, {})
                self.assertEqual(self.viewer._visualizer_widgets, {})
                self.assertTrue(getattr(self.viewer, visible_flag))
                self.assertFalse(VC.values[other_key])
                self.assertEqual(self.viewer._stacked_widget.currentIndex(), 1)


class MappedDeviceListTests(unittest.TestCase):
    def test_mapped_list_includes_all_tabs_and_refreshes_after_mapping_changes(self):
        devices = [NS(device_guid=name) for name in ("Stick", "Keyboard", "State", "Unused")]
        mappings = {"Stick": {"Current": True}, "Keyboard": {"Other": True},
                    "State": {"Current": True}, "Unused": {"Current": False}}
        ui = NAMESPACE["GremlinUi"]()
        ui.ui = NS(devices_tab_header_widget=NS(count=lambda: len(devices), tabData=devices.__getitem__))
        ui._get_mappings = mappings.__getitem__
        ui._mapped_device_list = ["Stale device"]

        self.assertEqual(ui.getMappedDeviceList(), ["Stick", "Keyboard", "State"])

        mappings["Stick"] = {"Current": False}
        mappings["Unused"] = {"Other": True}
        devices.pop(1)
        self.assertEqual(ui.getMappedDeviceList(), ["State", "Unused"])


if __name__ == "__main__":
    unittest.main()
