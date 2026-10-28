"""Input viewer trash/selector checks with real Qt and no hardware/config writes.

Run: python tools/test_input_viewer.py
"""

import ast
from enum import IntEnum
import inspect
import logging
import time
from types import SimpleNamespace as NS
from typing import Callable
import unittest
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from test_qt_marshalling import APP, Colors, definitions, flush_deletes, invoke


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

    def getValue(self, key, device, visualization):
        return self.values.get(key, False)

    def setValue(self, key, device, visualization, value):
        self.values[key] = value
        self.devices[key] = device


CONFIG = NS(verbose_mode_ui=False, input_viewer_combine_buttonhats=True)
VC = ViewerConfig()
BUS = Bus()
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
                 _pin_deleted_widget=PINNED.append,
                 syslog=logging.getLogger("input-viewer-checks"))
load("gremlin/types.py", {"VisualizationType"})
VisualizationType = NAMESPACE["VisualizationType"]
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
}, base="QWidget")


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


if __name__ == "__main__":
    unittest.main()
