# -*- coding: utf-8; -*-

# Based on original concept / code by Lionel Ott - Copyright (C) 2015 - 2019 Lionel Ott
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations  # deprecated with python 3.14+
import logging
import threading
import time
from lxml import etree as ElementTree
import traceback
from PySide6 import QtWidgets, QtCore, QtGui
from reportlab.graphics.barcode import widgets
import gremlin.actions
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.ui.ui_common
import gremlin.util
import gremlin.repeater
import gremlin.remote
import gremlin.singleton_decorator
import gremlin.ui.osc_device
import gremlin.ui.qsliderwidget
from shiboken6 import Shiboken
from gremlin.input_types import InputType
from gremlin import input_devices, joystick_handling, util
from gremlin.error import ProfileError
from gremlin.util import load_icon, load_pixmap, safe_format, safe_read, scale_to_range
import gremlin.input_item
import os
import enum
from gremlin.remote import remote_control
from gremlin.types import ButtonOutputMode, SendType, SyncMode, VjoyAction
import vjoy.vjoy
from functools import partial
from psygnal import Signal
import dinput
# import gremlin.pid

import gremlin.ui.midi_device
import gremlin.base_profile
import gremlin.shared_state
import gremlin.curve_handler


IdMapToButton = -2  # map to button special ID
# os.environ['LINE_PROFILE'] = "1"

syslog = logging.getLogger("system")


@gremlin.singleton_decorator.SingletonDecorator
class StepWidgetGroup:
    def __init__(self):
        self.group = QtWidgets.QButtonGroup()

    def clear(self):
        self.group = QtWidgets.QButtonGroup()


class MergeWidget(gremlin.ui.ui_common.QDataWidget):
    """merge axis widget - lets the user pick a device and axis"""

    delete_requested = QtCore.Signal(object)  # requesdt to delete (passes the data block)
    changed = QtCore.Signal(object)  # request to update visualization (passes the data block)

    def __init__(self, data, label: str = None, filter_input=None, action_data=None, parent=None):
        """creates a merge axis selector

        :param data : the merge block that sets or stores the return data
        :param label: label to display as a title
        :param filter_input : callback function - returns true if the entry is ok, false if not, the data passed is the device_id, input_id of the selection
        """

        super().__init__(parent=parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.data: MergeData = data
        self._filter_input = filter_input
        self.action_data = action_data
        self._hook_requested = False

        config = gremlin.config.Configuration()

        self.main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())

        step_widget = gremlin.ui.ui_common.QFrameBox(f"<b>{label if label else 'Merge Axis'}</b>")
        self.main_layout.addWidget(gremlin.ui.ui_common.getHContainer(step_widget, widget_only=True))

        # self.main_layout.addWidget(QtWidgets.QLabel(label if label else "Merge axis:"))

        # merge operations
        self.container_merge_widget = QtWidgets.QWidget()
        self.container_merge_layout = QtWidgets.QVBoxLayout(self.container_merge_widget)

        self.merge_selector_device_widget = gremlin.ui.ui_common.QDataComboBox()
        self.merge_selector_input_widget = gremlin.ui.ui_common.QDataComboBox()

        merge_remove_widget = gremlin.ui.ui_common.Buttons.getRemoveWidget(callback=self._remove_cb)

        device_widget = QtWidgets.QWidget()
        device_layout = QtWidgets.QGridLayout(device_widget)
        device_layout.addWidget(QtWidgets.QLabel("Merge Device:"), 0, 0)
        device_layout.addWidget(self.merge_selector_device_widget, 0, 1)
        device_layout.addWidget(QtWidgets.QLabel(" "), 0, 2)
        device_layout.addWidget(QtWidgets.QLabel("Merge Axis:"), 1, 0)
        device_layout.addWidget(self.merge_selector_input_widget, 1, 1)

        self.merge_device_listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback=self._listen_cb, tooltip="Listen for axis to merge")
        device_layout.addWidget(self.merge_device_listen_widget, 0, 2)
        device_layout.addWidget(merge_remove_widget, 0, 3)
        device_layout.setColumnStretch(4, 2)

        self.container_merge_layout.addWidget(device_widget)

        self.merge_selector_device_widget.currentIndexChanged.connect(self._merged_device_changed_cb)
        self.merge_selector_input_widget.currentIndexChanged.connect(self._merged_input_changed_cb)

        # populate the selector with hardware inputs
        self.merge_device_map = {}  # holds the device information keyed by device_id (str)
        self.merge_input_map = {}  # holds the list of axes for the given device by device_id(str)
        devices = sorted(joystick_handling.axis_input_devices(), key=lambda x: x.name)

        self._merge_enabled = len(devices) > 0  # assume enabled

        # figure out the default device to use
        default_device = None
        selected_input_id = 1
        if self.data.device_id:
            default_device: dinput.DeviceSummary = next((dev for dev in devices if dev.device_id == self.data.device_id), None)
            if default_device:
                if default_device.device_guid == self.action_data.hardware_device_guid:
                    # the merge device to pick is the same as the current device
                    if default_device.axis_count == 1:
                        # there is only one input which is already used
                        self._merge_enabled = False

                valid_input_ids = default_device.getValidAxisInputIds()
                if self.data.input_id and self.data.input_id in valid_input_ids:
                    selected_input_id = self.data.input_id

        if not default_device:
            default_device = next(
                (dev for dev in devices if dev.device_guid == self.action_data.hardware_device_guid),
                None,
            )
            if default_device:
                axis_count = default_device.axis_count
                if axis_count == 1:
                    # there is only one input which is already used
                    self._merge_enabled = False

                else:
                    # pick a suitable input
                    input_id = self.action_data.hardware_input_id
                    if input_id < axis_count:
                        # pick next if possible
                        selected_input_id = input_id + 1
                    elif input_id > 1:
                        # pick one below if next not available
                        selected_input_id = input_id - 1

                    self.data.input_id = selected_input_id

        if not self._merge_enabled:
            return

        if not default_device:
            # pick the first one if nothing else got selected
            default_device = devices[0]

        selected_device_index = devices.index(default_device)
        with QtCore.QSignalBlocker(self.merge_selector_device_widget):
            for dev in devices:
                self.merge_device_map[dev.device_id] = dev
                axis_list = {}
                for index in range(dev.axis_count):
                    input_id = dev.axis_sequence_to_input_id(index)
                    if dev.device_guid == self.action_data.hardware_device_guid and input_id == self.action_data.hardware_input_id:
                        # skip self as a possible input
                        continue
                    axis_list[input_id] = dev.get_axis_name(input_id)
                if axis_list:
                    self.merge_input_map[dev.device_id] = axis_list
                    self.merge_selector_device_widget.addItem(dev.name, dev.device_id)

        self.last_merge_device_id = None

        self._update_axis_list(default_device.device_id, selected_input_id)

        # merge operation mode

        self._merge_widgets_map = {}

        row_widgets = []
        self.option_widget = QtWidgets.QButtonGroup()

        self.merge_description_widget = QtWidgets.QLabel()
        merge_options = [
            [
                MergeOperationType.Add,
                MergeOperationType.Average,
                MergeOperationType.Center,
                MergeOperationType.Min,
                MergeOperationType.Max,
            ],
            [
                MergeOperationType.ScaleFull,
                MergeOperationType.ScaleFullCentered,
                MergeOperationType.ScaleHalf,
                MergeOperationType.ScaleHalfCentered,
            ],
            [MergeOperationType.Trim, MergeOperationType.TrimCentered],
        ]
        id = 0
        for merge_group in merge_options:
            widgets = []
            for merge_type in merge_group:
                rb = gremlin.ui.ui_common.QDataRadioButton(
                    label=MergeOperationType.to_display_name(merge_type),
                    data=merge_type,
                )
                widgets.append(rb)
                self._merge_widgets_map[merge_type] = rb
                if merge_type == self.data.operation:
                    rb.setChecked(True)
                    description = _merge_operation_to_description_lookup[merge_type]
                    self.merge_description_widget.setText(description)
                rb.clicked.connect(self._merge_mode_changed_cb)
                self.option_widget.addButton(rb, id=id)
                id += 1

            widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
            row_widgets.append(widget)

        self.merge_invert_widget = QtWidgets.QCheckBox("Invert")
        self.merge_invert_widget.setChecked(self.data.invert)
        self.merge_invert_widget.clicked.connect(self._merge_invert_changed_cb)
        row_widgets.append(self.merge_invert_widget)

        self.container_merge_options_widget = gremlin.ui.ui_common.getVContainer(row_widgets, widget_only=True)

        widget = gremlin.ui.ui_common.getHContainer(self.merge_description_widget, "Merge Operation:", widget_only=True)

        self.container_merge_layout.addWidget(widget)
        self.container_merge_layout.addWidget(self.container_merge_options_widget)

        self.merge_curve_widget = gremlin.ui.ui_common.QCurveWidget()
        self.merge_curve_widget.curveChanged.connect(self._handle_curve_changed)
        widgets = [self.merge_curve_widget]
        if config.show_input_axis:
            self.merge_axis_repeater_widget = gremlin.ui.ui_common.QProgressBar(orientation=QtCore.Qt.Orientation.Horizontal)
            self.merge_axis_repeater_label_widget = QtWidgets.QLabel()
            widgets.append(self.merge_axis_repeater_widget)
            widgets.append(self.merge_axis_repeater_label_widget)
        else:
            self.merge_axis_repeater_widget = None

        widget = gremlin.ui.ui_common.getHContainer(widgets, "Merge curve:", widget_only=True)
        self.container_merge_layout.addWidget(widget)

        self.main_layout.addWidget(self.container_merge_widget)

        # select the default device
        with QtCore.QSignalBlocker(self.merge_selector_device_widget):
            self.merge_selector_device_widget.setCurrentIndex(selected_device_index)

        selected_input_index = self.merge_selector_input_widget.findData(selected_input_id)
        if selected_input_index == -1:
            selected_input_index = 0
        self.merge_selector_input_widget.setCurrentIndex(selected_input_index)

    def event(self, event):
        if event.type() == QtCore.QEvent.Show:
            if self._hook_requested:
                self._do_hook()
        elif event.type() == QtCore.QEvent.Hide:
            self.unhook()
        return super().event(event)

    def _do_hook(self):
        if not self._hook_requested:
            self._hook_requested = True

    def unhook(self):
        if self._hook_requested:
            self._hook_requested = False

    def _handle_curve_changed(self, curve_data):
        """update made to the merged axis curve"""
        self.data.curve_data = curve_data
        if self.data.callback:
            # update the repeater data on curve change
            sd = gremlin.event_handler.AxisState()
            values = sd.getAxisValues(self.data.device_guid, self.data.input_id)
            if values:
                self.data.callback(values.actual)

    def setValue(self, value: float):
        """called when the axis value is updated"""
        if not Shiboken.isValid(self):
            return
        self.merge_curve_widget.setValue(value)
        if self.merge_axis_repeater_widget:
            self.merge_axis_repeater_label_widget.setText(f"{value:0.04f}")
            if self.data.curve_data:
                cv = self.data.curve_data.curve_value(value)
                self.merge_axis_repeater_widget.setValue([value, cv])
            else:
                self.merge_axis_repeater_widget.setValue(value)

    def _update_axis_list(self, device_id, select_input_id=None):
        """updates the axis list for a merge input"""

        if self.last_merge_device_id and gremlin.util.compare_guid(self.last_merge_device_id, device_id):
            return

        device = joystick_handling.getDevice(device_id)
        input_device_guid = self.action_data.hardware_device_guid
        input_input_id = self.action_data.hardware_input_id
        verbose = gremlin.config.Configuration().verbose_mode_merge

        with QtCore.QSignalBlocker(self.merge_selector_input_widget):
            self.merge_selector_input_widget.clear()
            if not device:
                return
            index = 0

            valid_input_ids = device.getValidAxisInputIds()
            # gremlin.util.compare_guid(device.device_guid, input_device_id)
            for input_id in valid_input_ids:
                if input_id == input_input_id and gremlin.util.compare_guid(input_device_guid, device_id):
                    # skip current input as a merge target
                    continue
                axis_name = device.getAxisName(input_id)
                if verbose:
                    syslog.info(f"merged axis: {axis_name}  input id: {input_id} item input id: {input_input_id}")
                self.merge_selector_input_widget.addItem(axis_name, input_id)

            index = self.merge_selector_input_widget.findData(select_input_id)
            if index != 1:
                self.merge_selector_input_widget.setCurrentIndex(index)

            self.last_merge_device_id = device.device_id

        # update merge data block
        self.data.device_guid = device.device_guid
        self.data.device_id = device.device_id
        self.data.input_id = self.merge_selector_input_widget.currentData()

    @QtCore.Slot()
    def _merged_device_changed_cb(self):
        """merge device changed"""
        index = self.merge_selector_device_widget.currentIndex()
        device_id = self.merge_selector_device_widget.itemData(index)
        input_id = self.data.input_id

        self._update_axis_list(device_id, input_id)
        self.data.device_id = device_id
        self.data.input_id = input_id
        self.changed.emit(self.data)

    @QtCore.Slot()
    def _merged_input_changed_cb(self):
        """merge input changed"""
        index = self.merge_selector_input_widget.currentIndex()
        input_id = self.merge_selector_input_widget.itemData(index)
        self.data.input_id = input_id
        self.changed.emit(self.data)

    @QtCore.Slot(bool)
    def _merge_invert_changed_cb(self, checked: bool):
        self.data.invert = checked
        self.changed.emit(self.data)

    @QtCore.Slot(bool)
    def _merge_mode_changed_cb(self, checked: bool):
        """merge mode selection change"""
        widget = self.sender()
        op = widget.data
        self.data.operation = op
        description = _merge_operation_to_description_lookup[op]
        self.merge_description_widget.setText(description)
        self.changed.emit(self.data)

    def _remove_cb(self):
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText("This will delete this merge data.\nAre you sure?")
        pixmap = gremlin.ui.ui_common.Icons.to_pixmap(gremlin.ui.ui_common.Icons.warningIcon())
        message_box.setIconPixmap(pixmap)
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_confirmed_cb()

    def _delete_confirmed_cb(self):
        self.delete_requested.emit(self.data)

    def _listen_cb(self):
        gremlin.util.InvokeUiMethod(self._listen_ui)

    def _listen_ui(self):
        """listen to an input for an axis - runs on UI thread"""
        self.axis_listen_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.JoystickAxis],
            return_kb_event=False,
            filter_func=self._filter_input,
            callback=self._update_merged_axis,
        )

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.axis_listen_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        self.axis_listen_dialog.show()

    def _update_merged_axis(self, event: gremlin.event_handler.Event):
        """merged axis selected via the listen button - runs on UI thread"""
        device_id = event.device_id
        input_id = event.identifier
        self.data.device_id = device_id
        self.data.input_id = input_id
        self._select_merge_target(device_id, input_id)
        self.axis_listen_dialog.close()

    def _select_merge_target(self, device_id, input_id):
        gremlin.util.InvokeUiMethod(self._select_merge_target_ui, device_id, input_id)

    def _select_merge_target_ui(self, device_id, input_id):
        """selects a given merge axis"""
        if Shiboken.isValid(self):
            index = self.merge_selector_device_widget.findData(device_id)
            if index != -1:
                if index != self.merge_selector_device_widget.currentIndex():
                    with QtCore.QSignalBlocker(self.merge_selector_device_widget):
                        self.merge_selector_device_widget.setCurrentIndex(index)  # this also updates the axis list if needed
                        self._update_axis_list(device_id, input_id)
                        self.data.device_id = device_id
                        self.data.device_guid = gremlin.util.parse_guid(device_id)

                index = self.merge_selector_input_widget.findData(input_id)
                if index != -1:
                    if index != self.merge_selector_input_widget.currentIndex():
                        with QtCore.QSignalBlocker(self.merge_selector_input_widget):
                            self.merge_selector_input_widget.setCurrentIndex(index)
                            self.data.input_id = input_id


class StepWidget(gremlin.ui.ui_common.QDataWidget):
    defaultChanged = Signal(int, bool)  # fires when default flag changes (index, flag)
    valueChanged = Signal(int, float)  # fires when value changes (index, value)
    deleteRequested = Signal(int)  # fires when delete is requested

    def __init__(self, index, value):
        super().__init__()
        self.index = index
        layout = QtWidgets.QHBoxLayout(self)

        w = gremlin.ui.ui_common.get_text_width("-0.000")

        self.value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.value_widget.setMinimumWidth(w)
        self.value_widget.setValue(value)
        self.value_widget.valueChanged.connect(self._step_value_changed)
        self.default_cb = gremlin.ui.ui_common.QDataRadioButton("")
        bg = StepWidgetGroup()
        bg.group.addButton(self.default_cb)

        self.default_cb.setToolTip("Set as profile start value")
        self.default_cb.clicked.connect(self._step_default_changed)

        self.delete_widget = QtWidgets.QPushButton()
        self.delete_widget.setToolTip("Delete step")
        self.delete_widget.setIcon(load_icon("mdi.delete"))
        self.delete_widget.setMaximumWidth(20)
        self.delete_widget.clicked.connect(self._delete)

        layout.addWidget(self.value_widget)
        layout.addWidget(self.delete_widget)
        layout.addWidget(self.default_cb)
        layout.addStretch()

    @QtCore.Slot(bool)
    def _step_default_changed(self, checked: bool):
        self.defaultChanged.emit(self.index, checked)

    @QtCore.Slot()
    def _step_value_changed(self):
        self.valueChanged.emit(self.index, self.value_widget.value())

    @QtCore.Slot()
    def _delete(self):
        self.deleteRequested.emit(self.index)

    def value(self) -> float:
        return self.value_widget.value()

    def setValue(self, value: float):
        with QtCore.QSignalBlocker(self.value_widget):
            self.value_widget.setValue(value)

    def setDefault(self, value: bool):
        """enable or disable default state"""
        bg = StepWidgetGroup()
        bg.group.buttons()[self.index].setChecked(value)


class MergeOperationType(enum.IntEnum):
    """merge operation method"""

    NotSet = 0
    Add = 1  # the two inputs are added
    Average = 2  # the two inputs are averaged
    Center = 3  # centered (left - right)/2
    Min = 4  # min of two axes
    Max = 5  # max of two axes
    ScaleFull = (6,)  # scale -1 to +1
    ScaleHalf = (7,)  # scale 0 to + 1
    Multiply = (8,)  # multiplies one axis with the value of another
    Trim = (9,)  # trim
    TrimCentered = 10  # centered trim
    ScaleFullCentered = 11  # scale centered
    ScaleHalfCentered = 12

    @staticmethod
    def to_display_name(value: MergeOperationType):  # noqa: F821
        return _merge_operation_display_lookup[value]

    @staticmethod
    def to_enum(value: str):
        return _merge_operation_to_enum_lookup[value]

    @staticmethod
    def to_string(value: MergeOperationType):  # noqa: F821
        return _merge_operation_to_string_lookup[value]

    @staticmethod
    def to_description(value: MergeOperationType):  # noqa: F821
        return _merge_operation_to_description_lookup[value]


_merge_operation_to_enum_lookup = {
    "none": MergeOperationType.NotSet,
    "add": MergeOperationType.Add,
    "average": MergeOperationType.Average,
    "center": MergeOperationType.Center,
    "min": MergeOperationType.Min,
    "max": MergeOperationType.Max,
    "scalefull": MergeOperationType.ScaleFull,
    "scalehalf": MergeOperationType.ScaleHalf,
    "multiply": MergeOperationType.Multiply,
    "trim": MergeOperationType.Trim,
    "trimcentered": MergeOperationType.TrimCentered,
    "scalefullc": MergeOperationType.ScaleFullCentered,
    "scalehalfc": MergeOperationType.ScaleHalfCentered,
}

_merge_operation_to_string_lookup = {
    MergeOperationType.NotSet: "none",
    MergeOperationType.Add: "add",
    MergeOperationType.Average: "average",
    MergeOperationType.Center: "center",
    MergeOperationType.Min: "min",
    MergeOperationType.Max: "max",
    MergeOperationType.ScaleFull: "scalefull",
    MergeOperationType.ScaleHalf: "scalehalf",
    MergeOperationType.Multiply: "multiply",
    MergeOperationType.Trim: "trim",
    MergeOperationType.TrimCentered: "trimcentered",
    MergeOperationType.ScaleFullCentered: "scalefullc",
    MergeOperationType.ScaleHalfCentered: "scalehalfc",
}


_merge_operation_display_lookup = {
    MergeOperationType.NotSet: "N/A",
    MergeOperationType.Add: "Add",
    MergeOperationType.Average: "Average",
    MergeOperationType.Center: "Center",
    MergeOperationType.Min: "Minimum",
    MergeOperationType.Max: "Maximum",
    MergeOperationType.ScaleFull: "Scale ",
    MergeOperationType.ScaleHalf: "Scale half",
    MergeOperationType.Multiply: "Multiply",
    MergeOperationType.Trim: "Trim",
    MergeOperationType.TrimCentered: "Trim (centered)",
    MergeOperationType.ScaleFullCentered: "Scale (centered)",
    MergeOperationType.ScaleHalfCentered: "Scale half (centered)",
}

_merge_operation_to_description_lookup = {
    MergeOperationType.NotSet: "Not set",
    MergeOperationType.Add: "A + B",
    MergeOperationType.Average: "Average (A+B)/2",
    MergeOperationType.Center: "Centered (A-B)/2",
    MergeOperationType.Min: "Min(A, B)",
    MergeOperationType.Max: "Max(A, B)",
    MergeOperationType.ScaleFull: "Scale 0..1 is derived from full deviation, results in an output -1 to +1",
    MergeOperationType.ScaleHalf: "Scale 0..1 is derived from half axis value - use for centered scale inputs, and results in an output -1 to +1",
    MergeOperationType.Multiply: "A * B",
    MergeOperationType.Trim: "Trim A with B - B is scaled 0 to 1 and applies a trim value to A",
    MergeOperationType.TrimCentered: "Trim A with B - B is centered adpplies a trim value to A",
    MergeOperationType.ScaleFullCentered: "Scale 0..1 is derived from full deviation",
    MergeOperationType.ScaleHalfCentered: "Scale 0..1 is derived from half axis value - use for centered scale inputs",
}


# class GridPopupWindow(gremlin.ui.ui_common.QRememberDialog):
class GridPopupWindow(gremlin.ui.ui_common.QShowAtCursorDialog):
    def __init__(self, vjoy_id, input_type, vjoy_input_id, parent=None):
        super().__init__(self.__class__.__name__, parent=parent)

        self.vjoy_id = vjoy_id
        self.input_type = input_type
        self.vjoy_input_id = vjoy_input_id

        self.setWindowTitle("Mapping Details")
        self.setModal(True)
        # self.setMinimumHeight(200)
        # self.setMinimumWidth(400)

        usage_data = gremlin.joystick_handling.VJoyUsageState()
        action_map = usage_data.get_action_map(vjoy_id, input_type, vjoy_input_id)
        if not action_map:
            self.close()

        self.main_layout = QtWidgets.QVBoxLayout(self)

        source_widget = gremlin.ui.ui_common.getHContainer(
            QtWidgets.QLabel(f"Vjoy {vjoy_id} Button {vjoy_input_id} mapped by:"),
            widget_only=True,
        )

        widgets = [source_widget]

        has_action = False
        for action in action_map:
            if action:
                if action.device_input_type == InputType.JoystickAxis:
                    name = f"Axis {action.device_input_id}"
                elif action.device_input_type in VJoyRemapWidget.input_type_buttons:
                    name = f"Button {action.device_input_id}"
                elif action.device_input_type == InputType.JoystickHat:
                    name = f"Hat {action.device_input_id}"

                widget = gremlin.ui.ui_common.getHContainer([action.device_name, name], widget_only=True, left_margin=12)
                widgets.append(widget)
                has_action = True

        if has_action:
            # place actions in a vertical scroll box
            self.scroll_area = QtWidgets.QScrollArea()
            self.scroll_widget = QtWidgets.QWidget()
            self.scroll_layout = QtWidgets.QVBoxLayout()
            self.scroll_widget.setLayout(self.scroll_layout)
            self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.setWidget(self.scroll_widget)

            widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

            self.scroll_layout.addWidget(widget)
            self.scroll_layout.setContentsMargins(6, 0, 6, 0)
            self.scroll_layout.addStretch()

            widget = self.scroll_widget
        else:
            widget = QtWidgets.QLabel("No usage data found.")

        self.main_layout.addWidget(widget)

        close_widget = gremlin.ui.ui_common.QDataPushButton("Close", callback=self._handle_close)
        widget = gremlin.ui.ui_common.getHContainer(close_widget, widget_only=True, left_stretch=True)
        self.main_layout.addWidget(widget)

    def _handle_close(self, widget):
        self.close()


class VJoyRemapWidget(gremlin.input_item.AbstractActionWidget):
    """Dialog which allows the selection of a vJoy output to use as
    as the remapping for the currently selected input.
    """

    locked = False

    # all button type inputs (hat is handled separately as is axis)
    input_type_buttons = [
        InputType.JoystickButton,
        InputType.Keyboard,
        InputType.KeyboardLatched,
        InputType.OpenSoundControl,
        InputType.Midi,
        InputType.ModeControl,
    ]

    def __init__(self, action_data, parent=None):
        """Creates a new VjoyRemapWidget.

        :param action_data profile data managed by this widget
        :param parent the parent of this widget
        """
        self._hook_requested = False

        # delay load flags
        self._step_ui_loaded = False  # true if stepped UI is loaded
        self._grid_ui_loaded = False  # true if button grid UI is loaded
        self._merged_ui_loaded = False  # true if the merged UI is loaded
        self._hat_mapping_ui_loaded = False  # true if the hat mapping UI is loaded
        self._repeater_created = False
        self._use_radio = False  # use radio buttons or used buttons

        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, VjoyRemap)

    def _create(self, action_data):
        self._update_merge_data()
        self.action_data: VjoyRemap = action_data

    def _create_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self.id = gremlin.util.get_guid()  # unique id
        config = gremlin.config.Configuration()
        self.verbose_inputs = config.verbose_mode_inputs
        self.verbose = config.verbose
        self.verbose_details = config.verbose_mode_inputs_extra
        self.last_merge_device_id = None  # id of the last populated merge axis target
        self._as = gremlin.event_handler.AxisState()
        self.container_height = 42

        self.container_repeater_widget = None
        self.container_repeater_layout = None

        self._info_widget = None

        self.cb_hat_list = []
        self.rb_hat_list = {}

        if VJoyRemapWidget.locked:
            return

        el = gremlin.event_handler.EventListener()

        self._ui_loaded = False

        if not gremlin.shared_state.vjoy_enabled:
            self.main_layout.addWidget(QtWidgets.QLabel("VJOY is not available.  Ensure VJOY is installed and configured."))
            return

        self.button_group = None  # holds the button grid

        veh = gremlin.event_handler.VjoyRemapEventHandler()
        veh.grid_visible_changed.connect(self.refresh_grid)

        try:
            VJoyRemapWidget.locked = True

            self.valid_types = [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat,
                InputType.Midi,
                InputType.OpenSoundControl,
            ]

            self._axis_tracking_enabled = False
            self.grid_visible_widget = None
            self.is_button_mode = False  # true if the action is mapping to a button
            self._grid_widgets = {}  # list of checkboxes in the button grid indexed by button id (1...max_button)
            self.slider_widget = None  # slider for stepped setup

            self.usage_state = gremlin.joystick_handling.VJoyUsageState()

            self.main_layout.setSpacing(0)

            self._merge_enabled = False  # disable merging by default

            # Create UI widgets for absolute / relative axis modes if the remap

            self.input_type = self.action_data.get_input_type()

            # init default widget tracking
            self.button_grid_widget = None
            self.button_grid_stack_widget = None  # container for the grid widget
            self.container_axis_widget = None

            # handler to update curve widget if displayed
            self.curve_update_handler = None

            self._is_axis = self.action_data.input_is_axis()

            # if the input is chained
            self.chained_input = self.action_data.input_item.is_action

            # create UI components
            self._repeater_value_widget = None
            self._repeater_axis_widget = None
            self._relative_pulse_widget = None

            steps = [
                self._create_override_input_type,
                self._create_selector,
                self._create_repeater,
                self._create_input_axis,
                self._create_range_widgets,
                self._create_sync_widget,
                self._create_button_modes,
                self._create_hat_mapping,
                self._create_output_range,
                self._create_merge_ui,
                self._create_step_ui,
                self._create_info,
                self._create_input_grid,
                self._update_axis_widget,
            ]

            verbose_perf = gremlin.config.Configuration().verbose_mode_perf
            if verbose_perf:
                _container = self.action_data.get_container()
                syslog.info(f"VJOYREMAP: create UI: [{self.action_data.debug_name}]")
                for callback in steps:
                    gremlin.util.timeit(callback)
            else:
                for callback in steps:
                    callback()

            self.main_layout.setContentsMargins(0, 0, 0, 0)

            el = gremlin.event_handler.EventListener()
            # el.button_usage_changed.connect(self._button_usage_changed) # listen to grid button changes
            el.set_vjoy_button_usage.connect(self._handle_vjoy_button_usage_changed)  # listen to grid button changes # called when a button actually flips

            # jp = gremlin.event_handler.JoystickEventProcessor()
            # jp.registerListenerCallback(
            #     device_guid = self.action_data.device_guid,
            #     input_type = self.action_data.input_type,
            #     input_id = self.action_data.input_id,
            #     callback = self._joystick_event_handler
            # )

            # el.joystick_event_ui.connect(self._joystick_event_handler)

            # set the action type from the input type
            self.load_actions_from_input_type()

            # hook repeater
            self._update_merge_data()

            # update the remote data
            self.remote_widget.refreshClients()

        finally:
            VJoyRemapWidget.locked = False
            self._ui_loaded = True

    def _handle_vjoy_button_usage_changed(self, vjoy_id, button_id, state):
        if vjoy_id != self.action_data.vjoy_id:
            return  # not ours
        gremlin.util.InvokeUiMethod(self._populate_grid)

    def _add_merge_data(self, device_guid, input_id):
        """adds a mapping to the tracking data"""
        device_id = gremlin.util.normalize_guid(device_guid)
        if device_id not in self._merge_device_input_map:
            self._merge_device_input_map[device_id] = []
        if input_id not in self._merge_device_input_map[device_id]:
            self._merge_device_input_map[device_id].append(input_id)

    def _update_merge_data(self):
        """build map of ID to axis ID for merge operations"""
        if not self._merged_ui_loaded:
            # nothing to update
            return
        self._merge_device_input_map = {}
        if self.action_data.get_input_type() == InputType.JoystickAxis:
            for data in self.action_data._merge_data:
                self._add_merge_data(data.device_guid, data.input_id)

            self._add_merge_data(
                self.action_data.hardware_device_guid,
                self.action_data.hardware_input_id,
            )

            verbose = gremlin.config.Configuration().verbose_mode_outputs
            if verbose:
                syslog.info("Merge data update: ")
                for device_guid, input_id in self._merge_device_input_map.items():
                    device: dinput.DeviceSummary = gremlin.joystick_handling.getDevice(device_guid)
                    syslog.info(f"\t{device.name} [{device.device_id}] -> axis {input_id} ({device.get_axis_name(input_id)})")

    def getCurveData(self, event, value):
        """returns active curve data that applies to the container through included response curve actions"""
        curves = []

        actions = self.action_data.get_sibblings()
        for action in actions:
            if hasattr(action, "getCurveData"):
                curve_data = action.getCurveData()
                if curve_data:
                    curves.append(curve_data)

        # add self
        if self.action_data.curve_data is not None:
            curves.append(self.action_data.curve_data)

        return curves

    def _get_selector_input_type(self):
        """gets a modified input type based on the current mode"""
        input_type = self.action_data.get_input_type()

        if input_type in VJoyRemapWidget.input_type_buttons and self.action_data.action_mode in (
            VjoyAction.VJoySetAxis,
            VjoyAction.VJoyInvertAxis,
            VjoyAction.VJoyRangeAxis,
            VjoyAction.VJoySetAxisStepped,
        ):
            return InputType.JoystickAxis
        return input_type

    def _update_range_text(self):
        v1 = self.action_data.button_range_min
        v2 = self.action_data.button_range_max
        self._range_text = f"[{v1:0.3f},{v2:0.3f}]"

    def _create_repeater(self):
        """creates an input repeater"""
        input_type = self.action_data.get_input_type()
        if input_type == InputType.JoystickAxis:
            self._repeater_axis_widget = gremlin.ui.ui_common.QAxisRepeaterProgressbar(
                self.action_data.input_item,
                callback=self._get_repeater_value,
            )
            # get the current value
            value = self.action_data.get_filtered_axis_value()

            if value is not None:
                self._repeater_axis_widget.setValue(value)
                self._repeater_value_widget = QtWidgets.QLabel(f"{value:0.4f}")

            widgets = ["Output:", self._repeater_axis_widget, self._repeater_value_widget]

            # wrap horizontal setup in vertical containers for independent height
            self.container_repeater_widget, self.container_repeater_layout = gremlin.ui.ui_common.getHContainer(widgets, use_vcontainers=True, left_margin=12)
            self.main_layout.addWidget(self.container_repeater_widget)

        self._repeater_created = True

    def _get_repeater_value(self, event: gremlin.event_handler.Event):
        """called by the merge repeater to update values when the input changes"""
        values = self.action_data.get_filtered_axis_value(event.value, channels=True)
        return values

    # def _update_repeater_value(self, value):
    #     """callback for the output repeater when it changes values"""
    #     if self._repeater_value_widget and Shiboken.isValid(
    #         self._repeater_value_widget
    #     ):
    #         if hasattr(value, "__iter__"):
    #             # compound value
    #             value = value[0]

    #         self._repeater_value_widget.setText(f"{value:0.4f}")

    def _update_repeater(self, value=None):
        """updates the input repeater section"""

        if not self._ui_loaded:
            return
        if not Shiboken.isValid(self):
            return
        if not self._repeater_axis_widget:
            # not an axis
            return

        # syslog.info(f"update vjoy remap repeater: {value:0.3f}")

        range_widget_visible = False
        axis_widget_visible = False
        if self.action_data.input_is_axis():
            if not value:
                raw_value = self.action_data.get_raw_axis_value()
                value = raw_value

            # get curves applied to the current container
            curves = self.action_data.getCurves()
            if self.action_data.curve_data:
                curves.append(self.action_data.curve_data)  # current applied curve

            if value is None:
                return  # nothing to update
            match self.action_data.action_mode:
                case VjoyAction.VJoyAxisToButton:
                    if not Shiboken.isValid(self._repeater_range_widget):
                        return
                    range_widget_visible = True
                    v1 = self.action_data.button_range_min
                    v2 = self.action_data.button_range_max
                    in_range = gremlin.util.valueInRange(value, v1, v2)
                    if in_range:
                        self._repeater_range_widget.setText(f"In range ({value:0.3f} in {self._range_text})")
                        self._repeater_range_widget.setIcon(gremlin.ui.ui_common.Icons.validIcon())
                        # self._repeater_button_widget.setValue(True)
                    else:
                        self._repeater_range_widget.setText(f"Out of range ({value:0.3f} not in {self._range_text})")
                        self._repeater_range_widget.setIcon(gremlin.ui.ui_common.Icons.invalidIcon())
                        # self._repeater_button_widget.setValue(False)
                case VjoyAction.VJoyAxis:
                    # plain axis output
                    # if not Shiboken.isValid(self._repeater_axis_widget):
                    #     return

                    values = self.action_data.get_filtered_axis_value(value, curves=curves, channels=True)
                    # syslog.info(f"got data: {data}")
                    if values is not None:
                        axis_widget_visible = True
                        self._repeater_axis_widget.setValue(values)
                        if self._repeater_value_widget:
                            self._repeater_value_widget.setText(f"{values.actual:+0.4f}")
                    else:
                        syslog.error(f"VJOY: repeater: got invalid value for axis - received value {value}")
                case VjoyAction.VJoyMergeAxis:
                    # axis merging
                    # if not Shiboken.isValid(self._repeater_axis_widget):
                    #     return
                    values = self.action_data.get_filtered_axis_value(value, curves=curves, channels=True)
                    if values is not None:
                        axis_widget_visible = True
                        self._repeater_axis_widget.setValue(values)
                        if self._repeater_value_widget:
                            self._repeater_value_widget.setText(f"{values.actual:+0.4f}")
                    else:
                        syslog.error(f"VJOY: repeater: got invalid value for axis - received value {value}")

        self._repeater_range_widget.setVisible(range_widget_visible)
        if self._repeater_axis_widget.isVisible() != axis_widget_visible:
            self._repeater_axis_widget.setVisible(axis_widget_visible)

        # grow based on channel count
        count = self._repeater_axis_widget.channels
        ch = self._repeater_axis_widget.channelHeight

        h = max(
            gremlin.ui.ui_common.getLayoutWidgetHeight(self.container_repeater_layout, 32),
            32 + ch * (count - 1),
        )
        self.container_repeater_widget.setMaximumHeight(h)
        self.container_repeater_widget.setMinimumHeight(h)

    def _create_range_widgets(self):

        self.button_range_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.button_range_min_widget.setValue(self.action_data.button_range_min)
        self.button_range_min_widget.valueChanged.connect(self._button_range_min_changed_cb)

        self.button_range_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.button_range_max_widget.setValue(self.action_data.button_range_max)
        self.button_range_max_widget.valueChanged.connect(self._button_range_max_changed_cb)

        self.button_grab_min_widget = gremlin.ui.ui_common.Buttons.getGrabWidget(tooltip="Grab minimum value", callback=self._grab_min)
        self.button_grab_max_widget = gremlin.ui.ui_common.Buttons.getGrabWidget(tooltip="Grab maximum value", callback=self._grab_max)

        self._update_range_text()
        self._repeater_range_widget = gremlin.ui.ui_common.QIconLabel()

        # quick buttons
        quick_list = [
            ("Reset", "reset", "Reset -1.0 1.0"),
            ("Half", "half", "Half range -0.5 +0.5"),
            ("L-Half", "lhalf", "Lower half -1.0 0.0"),
            ("U-Half", "uhalf", "Upper Half 0.0 +1.0"),
            ("Bot", "bot", "Bottom range -1.0 -0.75"),
            ("Top", "top", "Top range +0.75 +1.00"),
        ]

        widgets = [
            QtWidgets.QLabel("Axis to Button Range Min:"),
            self.button_range_min_widget,
            self.button_grab_min_widget,
            QtWidgets.QLabel("Range Max:"),
            self.button_range_max_widget,
            self.button_grab_max_widget,
        ]

        for label, data, tooltip in quick_list:
            widget = gremlin.ui.ui_common.QDataPushButton(
                label,
                data=data,
                tooltip=tooltip,
                callback=self._handle_button_range_quick_set,
            )
            widgets.append(widget)

        widgets.append(self._repeater_range_widget)

        self.container_axis_to_button_range_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, min_height=self.container_height)
        self.container_axis_to_button_range_widget.setToolTip("Button to axis range parameters. The button will be output if the input axis in this range.")
        self.main_layout.addWidget(self.container_axis_to_button_range_widget)

    @QtCore.Slot()
    def _handle_button_range_quick_set(self, widget):
        """handle quick set range buttons"""
        data = widget.data
        match data:
            case "reset":
                v1 = -1.0
                v2 = 1.0
            case "half":
                v1 = -0.5
                v2 = 0.5
            case "lhalf":
                v1 = -1.0
                v2 = 0.0
            case "uhalf":
                v1 = 0.0
                v2 = 1.0
            case "bot":
                v1 = -1.0
                v2 = -0.75
            case "top":
                v1 = 0.75
                v2 = 1.0
            case _:
                return
        self.button_range_min_widget.setValue(v1)
        self.button_range_max_widget.setValue(v2)

    @QtCore.Slot()
    def _grab_min(self):
        """grabs min range value"""
        value = self.get_axis_value()
        self.button_range_min_widget.setValue(value)

    @QtCore.Slot()
    def _grab_max(self):
        """grabs max range value"""
        value = self.get_axis_value()
        self.button_range_max_widget.setValue(value)

    def _create_hat_mapping(self):
        """delay load the hat mapping widgets"""
        self.container_hat_mapping_stack_widget = QtWidgets.QStackedWidget()
        self.main_layout.addWidget(self.container_hat_mapping_stack_widget)

    def ensureHatMappingLoaded(self):
        """ensures the hat mapping UI is loaded"""
        if not self._hat_mapping_ui_loaded:
            self._create_hat_mapping_ui()

    def _create_hat_mapping_ui(self):
        """creates the 8 way hat inputs based on the hat input value"""

        self.container_hat_widget = QtWidgets.QWidget()
        self.container_hat_widget.setContentsMargins(0, 0, 0, 0)

        self.container_hat_layout = QtWidgets.QVBoxLayout(self.container_hat_widget)
        self.container_hat_layout.setContentsMargins(0, 0, 0, 0)

        self.container_hat_grid_widget = QtWidgets.QWidget()
        self.container_hat_grid_layout = QtWidgets.QGridLayout(self.container_hat_grid_widget)

        self.container_hat_options_widget = QtWidgets.QWidget()
        self.container_hat_options_widget.setContentsMargins(0, 0, 0, 0)
        self.container_hat_options_layout = QtWidgets.QHBoxLayout(self.container_hat_options_widget)

        self.container_hat_mapping_stack_widget.addWidget(self.container_hat_widget)

        # self.rb_hat_pulse_list = []

        self.hat_pulse_widget = QtWidgets.QPushButton("All Pulse")
        self.hat_pulse_widget.setToolTip("Sets all mappings to pulse mode")
        self.hat_hold_widget = QtWidgets.QPushButton("All Hold")
        self.hat_hold_widget.setToolTip("Sets all mappings to hold mode")

        self.hat_press_widget = QtWidgets.QPushButton("All Press")
        self.hat_press_widget.setToolTip("Sets all mappings to press mode")

        self.hat_release_widget = QtWidgets.QPushButton("All Release")
        self.hat_release_widget.setToolTip("Sets all mappings to release mode")

        self.hat_noop_widget = QtWidgets.QPushButton("All NoOp")
        self.hat_noop_widget.setToolTip("Sets all mappings to NoOp (do nothing) mode")

        self.hat_unmap_widget = QtWidgets.QPushButton("Clear Buttons")
        self.hat_unmap_widget.setToolTip("Clears all mappings")
        self.hat_map_widget = QtWidgets.QPushButton("Map Buttons")
        self.hat_map_widget.setToolTip("Maps all positions sequentially using the first button as the reference if set.")

        self.hat_hold_widget.clicked.connect(self._set_all_hold)
        self.hat_pulse_widget.clicked.connect(self._set_all_pulse)
        self.hat_press_widget.clicked.connect(self._set_all_press)
        self.hat_release_widget.clicked.connect(self._set_all_release)
        self.hat_noop_widget.clicked.connect(self._set_all_noop)

        self.hat_unmap_widget.clicked.connect(self._clear_map)
        self.hat_map_widget.clicked.connect(self._auto_map)

        self.container_hat_options_layout.addWidget(self.hat_hold_widget)
        self.container_hat_options_layout.addWidget(self.hat_pulse_widget)
        self.container_hat_options_layout.addWidget(self.hat_press_widget)
        self.container_hat_options_layout.addWidget(self.hat_release_widget)
        self.container_hat_options_layout.addWidget(self.hat_noop_widget)
        self.container_hat_options_layout.addWidget(self.hat_unmap_widget)
        self.container_hat_options_layout.addWidget(self.hat_map_widget)
        self.container_hat_options_layout.addStretch()

        positions = self.action_data.hat_positions

        self.container_hat_layout.addWidget(self.container_hat_options_widget)
        self.container_hat_layout.addWidget(self.container_hat_grid_widget)

        row = 0
        for position in positions:  # 9 positions - 8 cardinal and center push
            cb = gremlin.ui.ui_common.QDataComboBox()
            cb.data = position
            name = vjoy.vjoy.Hat.direction_to_name[position]
            icon = vjoy.vjoy.Hat.direction_to_icon[position]
            lbl = gremlin.ui.ui_common.QIconLabel(
                icon_path=icon,
                text=f"{name}:",
                use_wrap=False,
                icon_color=QtGui.QColor(gremlin.ui.ui_common.Color.activeColor()),
                icon_size=32,
                use_qta=True,
            )

            lbl.setIcon(icon)
            self.container_hat_grid_layout.addWidget(lbl, row, 0)
            self.container_hat_grid_layout.addWidget(cb, row, 1)
            self.cb_hat_list.append(cb)
            cb.currentIndexChanged.connect(self._hat_mapping_changed)

            mode_container_widget = QtWidgets.QWidget()
            mode_container_widget.setContentsMargins(0, 0, 0, 0)
            mode_container_layout = QtWidgets.QHBoxLayout(mode_container_widget)

            rb_hold = gremlin.ui.ui_common.QDataRadioButton("Hold")
            rb_hold.setToolTip("Output will match the current state of the input.")
            rb_hold.data = position
            rb_pulse = gremlin.ui.ui_common.QDataRadioButton("Pulse")
            rb_pulse.setToolTip("Output will pulse on (pressed), wait a delay, and turn off (released) when triggered.")
            rb_pulse.data = position
            rb_press = gremlin.ui.ui_common.QDataRadioButton("Press")
            rb_press.setToolTip("Output will be turned on (pressed) when triggered.")
            rb_press.data = position
            rb_release = gremlin.ui.ui_common.QDataRadioButton("Release")
            rb_release.setToolTip("Output will be turned off (released) when triggered.")
            rb_release.data = position
            rb_noop = gremlin.ui.ui_common.QDataRadioButton("NoOp")
            rb_noop.setToolTip("No output.")
            rb_noop.data = position

            rb_hold.clicked.connect(self._hat_hold_changed)
            rb_pulse.clicked.connect(self._hat_pulse_changed)
            rb_press.clicked.connect(self._hat_press_changed)
            rb_release.clicked.connect(self._hat_release_changed)
            rb_noop.clicked.connect(self._hat_noop_changed)

            mode_container_layout.addWidget(rb_hold)
            mode_container_layout.addWidget(rb_pulse)
            mode_container_layout.addWidget(rb_press)
            mode_container_layout.addWidget(rb_release)
            mode_container_layout.addWidget(rb_noop)

            self.container_hat_grid_layout.addWidget(mode_container_widget, row, 2)

            # must match enum sequence
            self.rb_hat_list[position] = [
                rb_hold,
                rb_pulse,
                rb_press,
                rb_release,
                rb_noop,
            ]

            row += 1

        self.container_hat_grid_layout.addWidget(QtWidgets.QLabel(), 0, 4)
        self.container_hat_grid_layout.setColumnStretch(4, 3)
        self._update_hat_mapping()

        self._hat_mapping_ui_loaded = True  # indicate loaded

    def _cleanup_ui(self):
        """called when widget is destroyed"""
        # jp = gremlin.event_handler.JoystickEventProcessor()
        # jp.registerListenerCallback(
        #     device_guid = self.action_data.device_guid,
        #     input_type = self.action_data.input_type,
        #     input_id = self.action_data.input_id,
        #     callback = self._joystick_event_handler
        #     )
        pass

    @QtCore.Slot(bool)
    def _hat_sticky_changed(self, checked: bool):
        self.action_data.hat_sticky = checked

    @QtCore.Slot(bool)
    def _pulse_repeat_mode_changed(self, checked: bool):
        self.action_data.pulse_repeat = checked
        self._update_ui()

    def _set_all_mode(self, mode: ButtonOutputMode):
        positions = self.action_data.hat_positions
        for position in positions:
            self.action_data.hat_mode_map[position] = mode
        self._update_hat_mapping()

    @QtCore.Slot()
    def _set_all_hold(self):
        """sets all mappings to hold mode"""
        self._set_all_mode(ButtonOutputMode.Hold)

    @QtCore.Slot()
    def _set_all_pulse(self):
        """sets all mappings to pulse mode"""
        self._set_all_mode(ButtonOutputMode.Pulse)

    @QtCore.Slot()
    def _set_all_press(self):
        """sets all mappings to pulse mode"""
        self._set_all_mode(ButtonOutputMode.Press)

    @QtCore.Slot()
    def _set_all_release(self):
        """sets all mappings to pulse mode"""
        self._set_all_mode(ButtonOutputMode.Release)

    @QtCore.Slot()
    def _set_all_noop(self):
        """sets all mappings to pulse mode"""
        self._set_all_mode(ButtonOutputMode.NoOp)

    @QtCore.Slot()
    def _clear_map(self):
        """sets all mappings to pulse mode"""
        result = gremlin.ui.ui_common.ConfirmBox(prompt="Clear all hat button mappings?")
        if result:
            positions = self.action_data.hat_positions
            for position in positions:
                self.action_data.hat_map[position] = 0
            self._update_hat_mapping()

    @QtCore.Slot()
    def _auto_map(self):
        """sets all mappings to pulse mode"""
        result = gremlin.ui.ui_common.ConfirmBox(prompt="Remap all hat button mappings?")
        if result:
            positions = self.action_data.hat_positions
            dev = self.action_data.vjoy_map[self.action_data.vjoy_id]
            button_count = dev.button_count
            for index, position in enumerate(positions):
                if index == 0:
                    button_id = self.action_data.hat_map[position]
                    if button_id == 0:
                        # default if first button is not set
                        button_id = 1

                self.action_data.hat_map[position] = button_id

                button_id += 1
                if button_id > button_count:
                    # wrap around
                    button_id = 1

            self._update_hat_mapping()

    @QtCore.Slot()
    def _hat_mapping_changed(self):
        """updates a hat button mapping selection"""
        cb = self.sender()
        position = cb.data
        button_id = cb.currentData()
        self.action_data.hat_map[position] = button_id

    def _hat_mode_changed(self, widget, mode: ButtonOutputMode):
        if widget.isChecked():
            position = widget.data
            self.action_data.hat_mode_map[position] = mode

    @QtCore.Slot()
    def _hat_hold_changed(self):
        """updates a hat button mapping selection"""
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Hold)

    @QtCore.Slot()
    def _hat_pulse_changed(self):
        """updates a hat button mapping selection"""
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Pulse)

    @QtCore.Slot()
    def _hat_press_changed(self):
        """updates a hat button mapping selection"""
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Press)

    @QtCore.Slot()
    def _hat_release_changed(self):
        """updates a hat button mapping selection"""
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Release)

    @QtCore.Slot()
    def _hat_noop_changed(self):
        """updates a hat button mapping selection"""
        self._hat_mode_changed(self.sender(), ButtonOutputMode.NoOp)

    def _update_hat_mapping(self):
        """updates the hat button options for hat to button mapping"""

        if not self.cb_hat_list:
            return
        vjoy_id = self.action_data.vjoy_id
        if vjoy_id not in self.action_data.vjoy_map:
            syslog.warning(f"VJOY: hat mapping: vjoy [{vjoy_id}] not found.")
            return

        dev = self.action_data.vjoy_map[self.action_data.vjoy_id]
        count = dev.button_count
        positions = self.action_data.hat_positions
        for index, position in enumerate(positions):  # 9 positions - 8 cardinal and center push
            cb = self.cb_hat_list[index]
            with QtCore.QSignalBlocker(cb):
                cb.clear()
                cb.addItem("Not mapped", 0)
                for id in range(1, count + 1):
                    cb.addItem(f"Button {id}", id)

            mode = self.action_data.hat_mode_map[position]
            rb = self.rb_hat_list[position][int(mode)]
            with QtCore.QSignalBlocker(rb):
                rb.setChecked(True)

        self._load_hat_mapping()

    def _load_hat_mapping(self):
        """loads the hat data into the UI"""
        positions = self.action_data.hat_positions
        for index, position in enumerate(positions):  # 9 positions - 8 cardinal and center push
            button_id = self.action_data.hat_map[position]  # 0 means disabled
            button_index = button_id
            cb = self.cb_hat_list[index]
            if button_index < cb.count():
                with QtCore.QSignalBlocker(cb):
                    cb.setCurrentIndex(button_index)

    def _create_sync_widget(self):
        """creates the sync widget"""
        input_type = self.action_data.get_input_type()
        default_value = self.action_data.axis_start_value if input_type == InputType.JoystickAxis else self.action_data.button_start_value

        modes = [SyncMode.Default, SyncMode.Input]

        self._sync_widget = gremlin.ui.ui_common.QSyncModeWidget(
            mode=self.action_data.sync_mode,
            callback=self._sync_on_start_changed,
            input_type=input_type,
            default_value=default_value,
            sync_modes=modes,
        )
        self._sync_widget.valueChanged.connect(self._default_value_changed)
        widgets = [self._sync_widget]
        self.sync_on_start_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.sync_on_start_widget.setContentsMargins(12, 8, 0, 8)
        self.main_layout.addWidget(self.sync_on_start_widget)

    def _default_value_changed(self, value):
        if value is None or isinstance(value, bool):
            # update button value
            self.action_data.button_start_value = value
        else:
            # update axis value
            self.action_data.axis_start_value = value

    def _create_input_axis(self):
        """creates the axis input widget"""

        self.absolute_checkbox = QtWidgets.QRadioButton("Absolute")
        self.absolute_checkbox.setChecked(self.action_data.axis_mode == "absolute")
        self.relative_checkbox = QtWidgets.QRadioButton("Relative")
        self.relative_checkbox.setChecked(self.action_data.axis_mode == "relative")

        self.reverse_checkbox = QtWidgets.QCheckBox("Reverse Axis")
        self.reverse_checkbox.setToolTip("When enabled, inverts the input")
        self.reverse_checkbox.setChecked(self.action_data.reverse)
        self.reverse_checkbox.clicked.connect(self._axis_reverse_changed)

        self.b_min_value = QtWidgets.QPushButton("-1")
        w = 32
        self.set_width(self.b_min_value, w)
        self.b_center_value = QtWidgets.QPushButton("0")

        self.set_width(self.b_center_value, w)
        self.b_max_value = QtWidgets.QPushButton("+1")
        self.set_width(self.b_max_value, w)

        self._relative_value_widget = gremlin.ui.ui_common.QFloatLineEdit(min_range=0, max_range=1)
        self._relative_value_widget.setToolTip(
            "Relative value to add or remove from the axis.  This value is scaled with the deviation of the input if the input is an axis."
        )
        self._relative_value_widget.setValue(self.action_data.relative_value)
        self._relative_value_widget.valueChanged.connect(self._relative_value_changed)

        self._use_relative_value_widget = QtWidgets.QCheckBox("Use relative value:")
        self._use_relative_value_widget.setChecked(self.action_data.use_relative_value)
        self._use_relative_value_widget.clicked.connect(self._use_relative_value_changed)

        self._relative_pulse_widget = gremlin.ui.ui_common.QDelayWidget()
        self._relative_pulse_widget.setToolTip("Pulse Delay in milliseconds while the input is deviated or pressed")
        self._relative_pulse_widget.setValue(self.action_data.relative_pulse_delay)
        self._relative_pulse_widget.valueChanged.connect(self._relative_pulse_value_changed)

        self.relative_scaling_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.relative_scaling_widget.setMinimum(0)
        self.relative_scaling_widget.setMaximum(1000.0)
        self.relative_scaling_widget.setDecimals(3)

        self.container_reverse_widget = gremlin.ui.ui_common.getHContainer(
            self.reverse_checkbox,
            min_height=self.container_height,
            widget_only=True,
            left_margin=12,
        )
        self.main_layout.addWidget(self.container_reverse_widget)

        widgets = [
            self.absolute_checkbox,
            self.relative_checkbox,
            self._use_relative_value_widget,
        ]
        self.container_output_mode_widget = gremlin.ui.ui_common.getHContainer(
            widgets,
            "Output mode:",
            min_height=self.container_height,
            widget_only=True,
            left_margin=12,
        )
        self.main_layout.addWidget(self.container_output_mode_widget)

        # relative mode options
        widgets = [
            "Min:",
            self.b_min_value,
            "Center:",
            self.b_center_value,
            "Max:",
            self.b_max_value,
            "Relative scale:",
            self.relative_scaling_widget,
        ]

        self.container_relative_widget = gremlin.ui.ui_common.getHContainer(
            widgets,
            "Relative mode options:",
            min_height=self.container_height,
            widget_only=True,
            left_margin=12,
        )

        widgets = [
            "Relative Value:",
            self._relative_value_widget,
            self._relative_pulse_widget,
        ]

        self.container_target_widget = gremlin.ui.ui_common.getHContainer(widgets, min_height=self.container_height, widget_only=True, left_margin=12)

        self.main_layout.addWidget(self.container_relative_widget)
        self.main_layout.addWidget(self.container_target_widget)

        self.absolute_checkbox.clicked.connect(self._axis_mode_changed)
        self.relative_checkbox.clicked.connect(self._axis_mode_changed)
        self.relative_scaling_widget.valueChanged.connect(self._axis_scaling_changed)

        # self.sb_start_value.valueChanged.connect(self._axis_start_value_changed)
        self.b_min_value.clicked.connect(self._b_min_start_value_clicked)
        self.b_center_value.clicked.connect(self._b_center_start_value_clicked)
        self.b_max_value.clicked.connect(self._b_max_start_value_clicked)

        # hook the inputs and profile
        self._enable_axis_tracking()

    @QtCore.Slot(float)
    def _relative_value_changed(self, value):
        self.action_data.relative_value = value

    @QtCore.Slot(bool)
    def _use_relative_value_changed(self, checked: bool):
        self.action_data.use_relative_value = checked
        self._update_ui()

    @QtCore.Slot(int)
    def _relative_pulse_value_changed(self, value):
        """called when the pulse value changes"""
        if value >= 0:
            self.action_data.relative_pulse_delay = value

    def _create_output_range(self):
        """creates the output range widget"""

        self.curve_button_widget = QtWidgets.QPushButton("Output Curve")

        active_color = gremlin.ui.ui_common.Color.activeColor()
        normal_color = gremlin.ui.ui_common.Color.normalColor()
        self.curve_icon_inactive = util.load_icon("mdi.chart-bell-curve", qta_color=normal_color)
        self.curve_icon_active = util.load_icon("mdi.chart-bell-curve", qta_color=active_color)
        self.curve_button_widget.setToolTip("Curve output")
        self.curve_button_widget.clicked.connect(self._curve_button_cb)

        self.curve_clear_widget = QtWidgets.QPushButton("Clear curve")
        delete_icon = load_icon("mdi.delete")
        self.curve_clear_widget.setIcon(delete_icon)
        self.curve_clear_widget.setToolTip("Removes the curve output")
        self.curve_clear_widget.clicked.connect(self._curve_delete_button_cb)

        self.output_range_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.output_range_min_widget.setValue(self.action_data.output_range_min)
        self.output_range_min_widget.valueChanged.connect(self._output_range_min_changed_cb)

        self.output_range_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.output_range_max_widget.setValue(self.action_data.output_range_max)

        self.output_range_max_widget.valueChanged.connect(self._output_range_max_changed_cb)

        reset_widget = QtWidgets.QPushButton("Reset")
        reset_widget.setToolTip("Resets the output range to default")
        reset_widget.clicked.connect(self._reset_output_range)

        widgets = [
            self.curve_button_widget,
            self.curve_clear_widget,
        ]

        self.container_output_curve_widget = gremlin.ui.ui_common.getHContainer(
            widgets,
            "Output Curve Options",
            min_height=self.container_height,
            widget_only=True,
            left_margin=12,
        )
        self.main_layout.addWidget(self.container_output_curve_widget)

        widgets = [
            QtWidgets.QLabel("Range Min:"),
            self.output_range_min_widget,
            QtWidgets.QLabel("Range Max:"),
            self.output_range_max_widget,
            reset_widget,
        ]

        self.container_output_range_widget, self.container_output_range_layout = gremlin.ui.ui_common.getHContainer(
            widgets, "Output Scale:", min_height=self.container_height
        )
        self.container_output_range_widget.setToolTip(
            "Allows you to set limits to the output range of an axis to constrain the output to a particular reduced range from normal."
        )

        self._update_curve_icon()
        self.main_layout.addWidget(self.container_output_range_widget)

    def event(self, event):
        if event.type() == QtCore.QEvent.Show:
            if self._hook_requested:
                self._do_hook()
        elif event.type() == QtCore.QEvent.Hide:
            self.unhook()
        return super().event(event)

    def _enable_axis_tracking(self):
        self._hook_requested = True
        self._do_hook()

    def _do_hook(self):
        if self._hook_requested and not self._axis_tracking_enabled:
            self._axis_tracking_enabled = True
            el = gremlin.event_handler.EventListener()
            el.profile_start.connect(self._profile_start)
            el.profile_stop.connect(self._profile_stop)

    def unhook(self):
        if self._hook_requested:
            self._disable_axis_tracking()

    def _disable_axis_tracking(self):
        """disables tracking"""
        if self._axis_tracking_enabled:
            # if not self.chained_input:
            #     el = gremlin.event_handler.EventListener()
            #     el.removeUIJoystickEventCallback(self._joystick_event_handler)
            self._axis_tracking_enabled = False

    def _create_merge_ui(self):
        """creates the axis merging UI components"""
        self.container_merge_stack_widget = QtWidgets.QStackedWidget()
        self.main_layout.addWidget(self.container_merge_stack_widget)

    def ensureMergeMappingLoaded(self):
        if not self._merged_ui_loaded:
            self._merged_ui_loaded = True
            self._create_merge_mapping_ui()

    def _create_merge_mapping_ui(self):
        """populates the merge mapping UI"""
        self.container_merge_widget, self.container_merge_layout = gremlin.ui.ui_common.getVContainer(label="Merge Information")
        self._update_merge_widgets()
        self.container_merge_stack_widget.addWidget(self.container_merge_widget)

    def _update_merge_widgets(self):
        """populates the list of merge axes"""
        if not self._merged_ui_loaded:
            # nothing to update
            return
        count = 1
        gremlin.util.clear_layout(self.container_merge_layout)
        invert_merged_output_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Invert Merged Output",
            value=self.action_data.invert_merged_output,
            callback=self._handle_invert_merged_output_changed,
            tooltip="Invert merged output result",
        )

        if not self.action_data._merge_data:
            # add at least one
            self.action_data._merge_data = [MergeData()]

        self.container_merge_layout.addWidget(invert_merged_output_widget)

        for data in self.action_data._merge_data:
            widget = MergeWidget(
                data,
                f"Merge Axis {count}:",
                filter_input=self._filter_input,
                action_data=self.action_data,
            )
            widget.delete_requested.connect(self._delete_merge_widget)
            widget.changed.connect(self._changed_merge_widget)
            data.callback = widget.setValue  # callback for axis input dynamic updates
            count += 1
            self.container_merge_layout.addWidget(widget)

        merge_add_widget = gremlin.ui.ui_common.Buttons.getAddWidget(callback=self._add_merge_axis)
        self.merge_clear_widget = gremlin.ui.ui_common.Buttons.getClearWidget(callback=self._clear_merge_axis)
        widgets = [merge_add_widget, self.merge_clear_widget]
        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.container_merge_layout.addWidget(widget)

        self.action_data.queueAxisEvent()  # fire a joystick update to update the ui

    @QtCore.Slot(object)
    def _delete_merge_widget(self, data: MergeData):  # noqa: F821
        """called when a merge axis should be deleted"""
        if data in self.action_data._merge_data and len(self.action_data._merge_data) > 1:
            # can only delete if there is more than one entry

            self.action_data._merge_data.remove(data)
            self._update_merge_widgets()
            self._update_merge_data()

    @QtCore.Slot(object)
    def _changed_merge_widget(self, data: MergeData):  # noqa: F821
        """called when merge axis data changes"""
        self._update_axis_widget()
        self._update_merge_data()

    @QtCore.Slot(bool)
    def _handle_invert_merged_output_changed(self, checked: bool):
        self.action_data.invert_merged_output = checked

    def _add_merge_axis(self):
        self.action_data._merge_data.append(MergeData())
        self._update_merge_widgets()
        self._update_merge_data()

    def _clear_merge_axis(self):

        if len(self.action_data._merge_data) > 1:
            # can only clear if more than one merge axis as there must be always at least 1
            message_box = QtWidgets.QMessageBox()
            message_box.setText("Delete confirmation")
            message_box.setInformativeText("This will delete all merge data.\nAre you sure?")
            pixmap = gremlin.ui.ui_common.Icons.to_pixmap(gremlin.ui.ui_common.Icons.warningIcon())
            message_box.setIconPixmap(pixmap)
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            gremlin.util.centerDialog(message_box)
            result = message_box.exec()
            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                self._delete_confirmed_cb()

    def _delete_confirmed_cb(self):
        self.action_data._merge_data.clear()
        self._update_merge_widgets()
        self._update_merge_data()

    def _filter_input(self, event: gremlin.event_handler.Event) -> bool:
        # only accept axes different from the current input axis
        if gremlin.util.compare_guid(event.device_id, self.action_data.hardware_device_id) and event.identifier == self.action_data.get_input_id():
            # don't listen to the same input as the current input for merged axis
            return False
        return True

    def _update_merged_axis(self, event: gremlin.event_handler.Event):
        """merged axis selected via the listen button"""
        self.axis_listen_dialog.item_selected.disconnect(self._update_merged_axis)  # stop listening
        device_id = event.device_id
        input_id = event.identifier
        self._select_merge_target(device_id, input_id)

    def _select_merge_target(self, device_id, input_id):
        """selects a given merge axis"""
        index = self.merge_selector_device_widget.findData(device_id)
        if index != -1:
            if index != self.merge_selector_device_widget.currentIndex():
                with QtCore.QSignalBlocker(self.merge_selector_device_widget):
                    self.merge_selector_device_widget.setCurrentIndex(index)  # this also updates the axis list if needed
                    self._update_axis_list(device_id, input_id)
                    self.action_data.merge_device_id = device_id

            index = self.merge_selector_input_widget.findData(input_id)
            if index != -1:
                if index != self.merge_selector_input_widget.currentIndex():
                    with QtCore.QSignalBlocker(self.merge_selector_input_widget):
                        self.merge_selector_input_widget.setCurrentIndex(index)
                        self.action_data.merge_input_id = input_id

    def _update_curve_icon(self):
        if self.action_data.curve_data:
            self.curve_button_widget.setIcon(self.curve_icon_active)
            self.curve_clear_widget.setEnabled(True)
        else:
            self.curve_button_widget.setIcon(self.curve_icon_inactive)
            self.curve_clear_widget.setEnabled(False)

    QtCore.Slot()

    def _curve_button_cb(self):
        if not self.action_data.curve_data:
            curve_data = gremlin.curve_handler.AxisCurveData()
            curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(
                self.action_data.hardware_device_guid,
                self.action_data.hardware_input_id,
            )
            curve_data.curve_update()
            self.action_data.curve_data = curve_data

        syslog.info(f"Before curve update: {self.action_data.curve_data}")

        dialog = gremlin.curve_handler.AxisCurveDialog(self.action_data.curve_data)
        util.centerDialog(dialog, dialog.width(), dialog.height())
        # setup the update handler for value inputs into the curve
        self.curve_update_handler = dialog.curve_update_handler
        self._update_axis_widget()

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        gremlin.shared_state.pop_suspend_highlighting()
        self.curve_update_handler = None
        self.action_data.curve_data = dialog.getCurveData()
        self.action_data.curve_data.curve_update()  # update any changes to the curve

        syslog.info(f"After curve update: {self.action_data.curve_data}")

        self._update_curve_icon()

    QtCore.Slot()

    def _curve_delete_button_cb(self):
        """removes the curve data"""
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Confirmation")
        message_box.setInformativeText("Delete curve data for this output?")
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)

        response = message_box.exec()

        if response == QtWidgets.QMessageBox.StandardButton.Ok:
            self.action_data.curve_data = None
            self._update_curve_icon()

    QtCore.Slot()

    def _reset_output_range(self):
        """resets the output range"""
        self.output_range_min_widget.setValue(-1.0)
        self.output_range_max_widget.setValue(1.0)

    QtCore.Slot()

    def _output_range_min_changed_cb(self):
        value = self.output_range_min_widget.value()
        self.action_data.output_range_min = value
        self._update_axis_widget()

    QtCore.Slot()

    def _output_range_max_changed_cb(self):
        self.action_data.output_range_max = self.output_range_max_widget.value()
        self._update_axis_widget()

    QtCore.Slot()

    def _button_range_min_changed_cb(self):
        """button min range value changed"""
        self.action_data.button_range_min = self.button_range_min_widget.value()
        self._update_range_text()
        self._update_axis_widget()

    QtCore.Slot()

    def _button_range_max_changed_cb(self):
        """button max range value changed"""
        self.action_data.button_range_max = self.button_range_max_widget.value()
        self._update_range_text()
        self._update_axis_widget()

    def _profile_start(self):
        """called when the profile starts"""
        self._disable_axis_tracking()

    def _profile_stop(self):
        """called when the profile stops"""
        self._update_axis_widget()
        self._enable_axis_tracking()

    @QtCore.Slot(gremlin.event_handler.Event)
    def _joystick_event_handler(self, event: gremlin.event_handler.Event):
        """handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time"""
        if gremlin.shared_state.is_running:
            return

        assert gremlin.util.is_ui_thread()  # new handler for joystick should be on the ui thread

        if event.device_guid != self.action_data.device_guid:
            return
        if event.event_type != self.action_data.input_type:
            return
        if event.identifier != self.action_data.input_id:
            return

        if self.action_data.action_mode == VjoyAction.VJoyMergeAxis:
            # allow event processing for any device part of the merge operation
            if not self.action_data.isMergeEvent(event):
                return

            device_guid = gremlin.util.normalize_guid(event.device_guid)
            input_id = event.identifier
            event_key = (device_guid, input_id)

            md_list = [md for md in self.action_data._merge_data if md.key == event_key and md.callback is not None]
            for data in md_list:
                data.callback(event.value)

        else:
            if not event.device_guid == self.action_data.hardware_device_guid:
                return
            if not event.identifier == self.action_data.hardware_input_id:
                return

        value = event.value

        if self.curve_update_handler:
            # update the dynamic curve widget if active
            self.curve_update_handler(value)

        self._update_repeater(value)

    def _current_input_axis(self):
        """gets the current input axis value"""
        return gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)

    def _update_axis_widget(self):
        """updates the axis output repeater with the value

        :param value: the floating point input value, if None uses the cached value

        """
        if not self._ui_loaded:
            return
        # always read the current input as the value could be from another device for merged inputs
        if self.action_data.input_is_axis():  # == InputType.JoystickAxis:
            curves = [self.action_data.curve_data] if self.action_data.curve_data else None
            value = self.action_data.get_filtered_axis_value(curves=curves)

            # update the curved window if displayed
            if self.curve_update_handler is not None:
                self.curve_update_handler(value)  # use the current axis input value, not the curved value

            self._update_repeater()

    @QtCore.Slot(bool)
    def _merge_mode_changed_cb(self, checked: bool):
        """merge mode selection change"""
        widget = self.sender()
        self.merge_type = widget.data

    def _update_info(self):
        """updates the output display info widget"""
        input_type = self.action_data._get_input_type()  # self.action_data.hardware_input_type # state._active_device_input_type
        input_id = self.action_data.hardware_input_id  # state._active_device_input_id

        vjoy_id = self.action_data.vjoy_id
        vjoy_input_id = self.action_data.vjoy_input_id

        # command modes
        value = self.action_data.action_mode
        if value in (
            VjoyAction.VJoyDisableLocal,
            VjoyAction.VJoyDisableRemote,
            VjoyAction.VJoyEnableLocalOnly,
            VjoyAction.VJoyEnableRemoteOnly,
            VjoyAction.VJoyEnableLocalAndRemote,
            VjoyAction.VJoyEnableLocal,
            VjoyAction.VJoyEnableRemote,
            VjoyAction.VJoyToggleRemote,
        ):
            action_name = "GremlinEx Command"
        else:
            action_name = None

        match self.action_data.action_mode:
            case VjoyAction.VJoyAxisToButton:
                action_name = f"Vjoy device {vjoy_id} button {vjoy_input_id}"

        is_axis = self.action_data.input_is_axis()
        if is_axis:
            if not action_name:
                action_name = f"Vjoy device {vjoy_id} axis {vjoy_input_id} ({joystick_handling.get_axis_name(vjoy_input_id)})"
            if input_type != InputType.JoystickAxis:
                name = f"Input axis -> {action_name}"
            else:
                axis_name = joystick_handling.get_axis_name(input_id)
                name = f"Axis {input_id} ({axis_name}) -> {action_name}"
        elif input_type in VJoyRemapWidget.input_type_buttons:
            if not action_name:
                action_name = f"Vjoy device {vjoy_id} button {vjoy_input_id}"
            name = f"Button {input_id} -> {action_name}"
        elif input_type == InputType.JoystickHat:
            if not action_name:
                action_name = f"Vjoy device {vjoy_id} hat {vjoy_input_id}"
            name = f"Hat {input_id} -> {action_name}"
        else:
            if not action_name:
                action_name = f"Vjoy device {vjoy_id} button {vjoy_input_id}"
            name = f"Input trigger -> {action_name}"

        if self._info_widget:
            self._info_widget.setText(name)

    def _create_info(self):
        """shows what device is currently selected"""
        self._info_widget = QtWidgets.QLabel()
        box = gremlin.ui.ui_common.getHContainer(self._info_widget, widget_only=True)
        self.main_layout.addWidget(box)
        self._update_info()

    def set_width(self, widget, width, height=22):
        widget.setFixedSize(width, height)

    def _create_override_input_type(self):
        """creates a manual input type override"""

        current_input_type = self.action_data.get_input_type()
        self._override_enabled_widget = QtWidgets.QCheckBox(f"Override input type ({InputType.to_display_name(current_input_type)})")
        input_type = self.action_data.override_input_type
        self._override_enabled_widget.setChecked(input_type is not None)
        self._override_enabled_widget.clicked.connect(self._update_override)
        self._override_axis_widget = gremlin.ui.ui_common.QDataRadioButton("Axis", InputType.JoystickAxis)
        self._override_axis_widget.clicked.connect(self._update_override_changed)
        self._override_button_widget = gremlin.ui.ui_common.QDataRadioButton("Button", InputType.JoystickButton)
        self._override_button_widget.clicked.connect(self._update_override_changed)
        self._override_hat_widget = gremlin.ui.ui_common.QDataRadioButton("Hat", InputType.JoystickHat)
        self._override_hat_widget.clicked.connect(self._update_override_changed)

        widgets = [
            self._override_enabled_widget,
            self._override_axis_widget,
            self._override_button_widget,
            self._override_hat_widget,
        ]

        self.container_override_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, min_height=self.container_height)
        self._update_override()
        self.main_layout.addWidget(self.container_override_widget)

    @QtCore.Slot()
    def _update_override(self):
        """updates the override widget"""
        enabled = self._override_enabled_widget.isChecked()
        self._override_axis_widget.setEnabled(enabled)
        self._override_button_widget.setEnabled(enabled)
        self._override_hat_widget.setEnabled(enabled)
        input_type = self.action_data.override_input_type
        with QtCore.QSignalBlocker(self._override_axis_widget):
            self._override_axis_widget.setChecked(input_type == InputType.JoystickAxis)
        with QtCore.QSignalBlocker(self._override_button_widget):
            self._override_button_widget.setChecked(input_type == InputType.JoystickButton)
        with QtCore.QSignalBlocker(self._override_hat_widget):
            self._override_hat_widget.setChecked(input_type == InputType.JoystickHat)

    @QtCore.Slot(bool)
    def _update_override_changed(self, checked: bool):
        widget = self.sender()
        input_type = widget.data
        if self.action_data.override_input_type != input_type:
            self.action_data.override_input_type = input_type
            self._update_override()

    def _create_button_modes(self):
        """button output options"""
        self.button_rb_hold = gremlin.ui.ui_common.QDataRadioButton("Hold")
        self.button_rb_hold.setToolTip("Output will be pressed (on) while the input is in range.")
        self.button_rb_hold.data = ButtonOutputMode.Hold
        self.button_rb_hold.setChecked(self.action_data.button_mode == ButtonOutputMode.Hold)

        self.button_rb_pulse = gremlin.ui.ui_common.QDataRadioButton("Pulse")
        self.button_rb_pulse.setToolTip("Output will pulse on (pressed), wait a delay, and turn off (released) when the range is entered")
        self.button_rb_pulse.data = ButtonOutputMode.Pulse
        self.button_rb_pulse.setChecked(self.action_data.button_mode == ButtonOutputMode.Pulse)

        self.button_rb_press = gremlin.ui.ui_common.QDataRadioButton("Press")
        self.button_rb_press.setToolTip("Output will be turned on (pressed) and stay on if the range is entered.")
        self.button_rb_press.data = ButtonOutputMode.Press
        self.button_rb_press.setChecked(self.action_data.button_mode == ButtonOutputMode.Press)

        self.button_rb_release = gremlin.ui.ui_common.QDataRadioButton("Release")
        self.button_rb_release.setToolTip("Output will be turned off (released) and stay off is the range is entered.")
        self.button_rb_release.data = ButtonOutputMode.Release
        self.button_rb_release.setChecked(self.action_data.button_mode == ButtonOutputMode.Release)

        self.button_rb_noop = gremlin.ui.ui_common.QDataRadioButton("NoOp")
        self.button_rb_noop.setToolTip("No output.")
        self.button_rb_noop.data = ButtonOutputMode.NoOp
        self.button_rb_noop.setChecked(self.action_data.button_mode == ButtonOutputMode.NoOp)

        self.pulse_duration_widget = gremlin.ui.ui_common.QDelayWidget(
            value=self.action_data.pulse_delay,
            callback=self._pulse_value_changed,
            tooltip="Pulse Delay in milliseconds",
        )

        self.pulse_interval_widget = gremlin.ui.ui_common.QDelayWidget(
            value=self.action_data.pulse_repeat_delay,
            tooltip="Repeat delay in milliseconds",
            callback=self._pulse_repeat_value_changed,
        )

        self.button_repeat_widget = gremlin.ui.ui_common.QDataCheckbox(
            value=self.action_data.pulse_repeat,
            callback=self._pulse_repeat_mode_changed,
            tooltip="When enabled, pulses are repeated while the input is triggered.",
        )

        widgets = [
            self.button_rb_hold,
            self.button_rb_pulse,
            self.button_rb_press,
            self.button_rb_release,
            self.button_rb_noop,
        ]

        self.container_button_mode_widget = gremlin.ui.ui_common.getHContainer(widgets, "Output Mode:", min_height=self.container_height, widget_only=True)

        self.container_pulse_widget = gremlin.ui.ui_common.getGridContainer(self.pulse_duration_widget, "Duration (ms):", widget_only=True)
        self.container_repeat_widget = gremlin.ui.ui_common.getGridContainer(self.button_repeat_widget, "Pulse Repeat:", widget_only=True)
        self.container_interval_widget = gremlin.ui.ui_common.getGridContainer(self.pulse_interval_widget, "Interval (ms):", widget_only=True)

        widgets = [
            self.container_pulse_widget,
            self.container_repeat_widget,
            self.container_interval_widget,
        ]

        widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True, left_margin=12)
        gremlin.ui.ui_common.synchronize_grids(widgets)

        widgets = [
            widget,
        ]

        self.container_pulse_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

        self.button_rb_hold.clicked.connect(self._button_mode_changed)
        self.button_rb_pulse.clicked.connect(self._button_mode_changed)
        self.button_rb_press.clicked.connect(self._button_mode_changed)
        self.button_rb_release.clicked.connect(self._button_mode_changed)
        self.button_rb_noop.clicked.connect(self._button_mode_changed)

        self.main_layout.addWidget(self.container_button_mode_widget)
        self.main_layout.addWidget(self.container_pulse_widget)

    @QtCore.Slot()
    def _button_mode_changed(self):
        widget = self.sender()
        mode = widget.data
        self.action_data.button_mode = mode
        self._update_ui()

    def _create(self, action_data):
        self.action_data: VjoyRemap = action_data

    def _create_selector(self):
        """creates the button option panel"""

        config = gremlin.config.Configuration()

        self.selector_widget = QtWidgets.QWidget()

        grids = []
        width = 200

        # behavior combo box  - lets the user select the output behavior
        self.cb_action_list = gremlin.ui.ui_common.QDataComboBox()
        self.cb_action_list.setFixedWidth(width)

        self.cb_action_list.currentIndexChanged.connect(self._handle_action_mode_changed)
        self.action_label = QtWidgets.QLabel()

        self.container_mode_selector_widget = gremlin.ui.ui_common.getGridContainer(
            ["Mode:", self.cb_action_list, self.action_label],
            widget_only=True,
            bottom_margin=4,
        )
        grids.append(self.container_mode_selector_widget)

        self.lbl_vjoy_device_selector = QtWidgets.QLabel("Device:")
        self.cb_vjoy_device_selector = gremlin.ui.ui_common.QDataComboBox()
        self.cb_vjoy_device_selector.setFixedWidth(width)

        self.container_device_selector_widget = gremlin.ui.ui_common.getGridContainer(
            [self.lbl_vjoy_device_selector, self.cb_vjoy_device_selector, " "],
            widget_only=True,
            bottom_margin=4,
        )
        grids.append(self.container_device_selector_widget)

        self.lbl_vjoy_output_selector = QtWidgets.QLabel("Output:")
        self.cb_vjoy_output_selector = gremlin.ui.ui_common.QDataComboBox()
        self.cb_vjoy_output_selector.setFixedWidth(width)

        self._next_unused_widget = gremlin.ui.ui_common.QDataPushButton(
            "Next Unused",
            callback=self._handle_next_unused,
            tooltip="Selects the next unused input in the profile if one is available",
        )

        self.lbl_hat_selector = QtWidgets.QLabel("Press Position:")

        self.cb_hat_selector = gremlin.ui.ui_common.QDataComboBox(callback=self._handle_hat_selector_changed)
        self.cb_hat_selector.setFixedWidth(width)

        self.lbl_hat_return_selector = QtWidgets.QLabel("Release position:")

        self.cb_hat_return_selector = gremlin.ui.ui_common.QDataComboBox(callback=self._handle_hat_return_selector_changed)
        self.cb_hat_return_selector.setFixedWidth(width)

        self.container_output_selector_widget = gremlin.ui.ui_common.getGridContainer(
            [
                self.lbl_vjoy_output_selector,
                self.cb_vjoy_output_selector,
                self._next_unused_widget,
            ],
            widget_only=True,
            bottom_margin=4,
        )
        grids.append(self.container_output_selector_widget)

        self.container_hat_selector_widget = gremlin.ui.ui_common.getGridContainer(
            [self.lbl_hat_selector, self.cb_hat_selector, " "],
            widget_only=True,
            bottom_margin=4,
        )
        grids.append(self.container_hat_selector_widget)

        self.container_hat_return_selector_widget = gremlin.ui.ui_common.getGridContainer(
            [self.lbl_hat_return_selector, self.cb_hat_return_selector, " "],
            widget_only=True,
            bottom_margin=4,
        )
        grids.append(self.container_hat_return_selector_widget)

        for widget in grids:
            self.main_layout.addWidget(widget)

        self.show_disconnected_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Show disconnected",
            value=config.vjoy_show_disconnected,
            tooltip="Hide or display disconnected VJOY devices",
            callback=self._handle_show_vjoy_disconnect_changed,
        )

        widget = gremlin.ui.ui_common.getHContainer(self.show_disconnected_widget, widget_only=True, bottom_margin=6)

        self.main_layout.addWidget(widget)
        self.main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())

        # self.warning_widget = gremlin.ui.ui_common.QWarningWidget()
        warning_color = gremlin.ui.ui_common.Color.warningColor()
        self.warning_widget = gremlin.ui.ui_common.QIconLabel(
            "ph.shield-warning-fill",
            use_qta=True,
            icon_color=QtGui.QColor(warning_color),
            text="",
            use_wrap=False,
        )
        self.container_warning_widget = gremlin.ui.ui_common.getHContainer(self.warning_widget, min_height=self.container_height, widget_only=True)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self.remote_widget = gremlin.ui.ui_common.RemoteClientWidget(self.action_data.remote_config)

        self.chkb_ignore_release = QtWidgets.QCheckBox("Ignore release")
        self.chkb_ignore_release.setToolTip("If enabled, the action will ignore release triggers (this is input and container dependent) - normal is OFF")
        self.chkb_ignore_release.setStyleSheet("")

        self.chkb_paired = QtWidgets.QCheckBox("Paired Group Member")
        # self.chkb_paired.setStyleSheet(css)
        self.chkb_paired.setToolTip("Paired groups with a remote client - when enabled - sends a remote signal and a local signal (this is seldom used).")

        self.chkb_auto_release_widget = QtWidgets.QCheckBox("Auto Release")
        self.chkb_auto_release_widget.setToolTip(
            "Autorelease will trigger a release action when the input is released if the input does not issue one and that is the desired behavior."
        )
        self.chkb_auto_release_widget.setChecked(self.action_data.auto_release)

        self.grid_visible_widget = QtWidgets.QCheckBox("Show button grid")
        self.grid_visible_widget.setToolTip("Sets the button grid visibility, use ctrl+ to enable/disable globally")
        self.grid_visible_widget.setChecked(self.action_data.grid_visible)
        self.grid_visible_widget.clicked.connect(self._grid_visible_cb)

        widgets = [
            self._execute_widget,
            self.chkb_ignore_release,
            self.chkb_paired,
            self.chkb_auto_release_widget,
            gremlin.ui.ui_common.QHorizontalSeparator(),
            self.grid_visible_widget,
        ]

        self.container_options_widget = gremlin.ui.ui_common.getHContainer(widgets, min_height=self.container_height, widget_only=True)

        # selector hooks
        self.cb_vjoy_device_selector.currentIndexChanged.connect(self._vjoy_id_changed)
        self.cb_vjoy_output_selector.currentIndexChanged.connect(self._handle_vjoy_output_id_changed)

        # set axis range widget
        self.axis_range_container_widget = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(self.axis_range_container_widget)
        self.sb_button_range_low = gremlin.ui.ui_common.QFloatLineEdit()
        self.sb_button_range_low.setMinimum(-1.0)
        self.sb_button_range_low.setMaximum(1.0)
        self.sb_button_range_low.setDecimals(3)
        self.sb_button_range_high = gremlin.ui.ui_common.QFloatLineEdit()
        self.sb_button_range_high.setMinimum(-1.0)
        self.sb_button_range_high.setMaximum(1.0)
        self.sb_button_range_high.setDecimals(3)
        self.b_range_reset = QtWidgets.QPushButton("Reset")
        self.b_range_half = QtWidgets.QPushButton("Half")
        self.b_range_lhalf = QtWidgets.QPushButton("L-Half")
        self.b_range_hhalf = QtWidgets.QPushButton("H-Half")
        self.b_range_top = QtWidgets.QPushButton("Top")
        self.b_range_bottom = QtWidgets.QPushButton("Bot")

        box.addWidget(QtWidgets.QLabel("Range Min:"))
        box.addWidget(self.sb_button_range_low)
        box.addWidget(QtWidgets.QLabel("Max:"))
        box.addWidget(self.sb_button_range_high)
        box.addWidget(self.b_range_reset)
        box.addWidget(self.b_range_half)
        box.addWidget(self.b_range_lhalf)
        box.addWidget(self.b_range_hhalf)
        box.addWidget(self.b_range_bottom)
        box.addWidget(self.b_range_top)
        box.addStretch()

        # button to axis value widget

        self.button_to_axis_value_widget = gremlin.ui.ui_common.QFloatLineEdit(
            value=self.action_data.target_value,
            callback=self._button_to_axis_value_changed,
        )

        self.target_is_relative = gremlin.ui.ui_common.QDataCheckbox(
            "Is Relative",
            value=self.action_data.target_is_relative,
            tooltip="When enabled, the value is added to the current axis (relative value)",
            callback=self._target_relative_changed,
        )

        self.target_use_last = gremlin.ui.ui_common.QDataCheckbox(
            "Use last",
            value=self.action_data.target_use_last,
            callback=self._handle_target_use_last_changed,
            tooltip="When enabled, sends a wiggle axis to force the target application to re-read the input axis to the last axis value.",
        )

        widgets = [
            "Set Value:",
            self.button_to_axis_value_widget,
            self.target_use_last,
            self.target_is_relative,
        ]

        self.target_value_container_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        self.main_layout.addWidget(self.selector_widget)
        self.main_layout.addWidget(self.container_warning_widget)
        self.main_layout.addWidget(self.remote_widget)
        self.main_layout.addWidget(self.container_options_widget)
        self.main_layout.addWidget(self.axis_range_container_widget)
        self.main_layout.addWidget(self.target_value_container_widget)

        # hook events

        self.chkb_ignore_release.clicked.connect(self._ignore_release_changed)
        self.chkb_paired.clicked.connect(self._paired_changed)
        self.chkb_auto_release_widget.clicked.connect(self._autorelease_changed)

        # self.start_button_group.buttonClicked.connect(self._start_changed)
        self.sb_button_range_low.valueChanged.connect(self._button_range_low_changed)
        self.sb_button_range_high.valueChanged.connect(self._button_range_high_changed)
        self.button_to_axis_value_widget.valueChanged.connect(self._button_to_axis_value_changed)

        self.b_range_reset.clicked.connect(self._b_range_reset_clicked)
        self.b_range_half.clicked.connect(self._b_range_half_clicked)
        self.b_range_lhalf.clicked.connect(self._b_range_lhalf_clicked)
        self.b_range_hhalf.clicked.connect(self._b_range_hhalf_clicked)
        self.b_range_bottom.clicked.connect(self._b_range_bot_clicked)
        self.b_range_top.clicked.connect(self._b_range_top_clicked)
        self.main_layout.addStretch()

        # populate data
        self._update_device_list()

        # sync grids
        gremlin.ui.ui_common.synchronize_grids(grids)

    def _update_device_list(self):
        """reloads the device list"""
        with QtCore.QSignalBlocker(self.cb_vjoy_device_selector):
            self.cb_vjoy_device_selector.clear()
            config = gremlin.config.Configuration()
            connected_only = not config.vjoy_show_disconnected
            device_list = gremlin.joystick_handling.vjoy_devices(connected_only)
            for dev in device_list:
                # for dev in gremlin.joystick_handling.vjoy_devices():
                self.cb_vjoy_device_selector.addItem(dev.name, dev.vjoy_id)

            vjoy_id = self.action_data.vjoy_id

            if connected_only and not gremlin.joystick_handling.is_vjoy_connected(vjoy_id):
                # add the missing device even if not connected so it is in the list
                dev = gremlin.joystick_handling.vjoy_info_from_vjoy_id(vjoy_id, connected_only=False)
                self.cb_vjoy_device_selector.addItem(dev.name, dev.vjoy_id)

            index = self.cb_vjoy_device_selector.findData(vjoy_id)
            if index != -1:
                self.cb_vjoy_device_selector.setCurrentIndex(index)
            else:
                # change the action ID
                syslog.warning(
                    f"VJOY REMAP: vjoy device [{vjoy_id}] not found in the available vjoy device list - resetting to [{self.cb_vjoy_device_selector.currentData()}]"
                )
                self.action_data.vjoy_id = self.cb_vjoy_device_selector.currentData()

            # update warning if needed
            self._vjoy_id_changed(self.cb_vjoy_device_selector.currentIndex())

    def _handle_sendmode_changed(self, mode: SendType):
        """sets the send mode"""
        self.action_data.sendMode = mode

    @QtCore.Slot(bool)
    def _handle_show_vjoy_disconnect_changed(self, checked: bool):
        config = gremlin.config.Configuration()
        config.vjoy_show_disconnected = checked
        self._update_device_list()

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        self.action_data.exec_on_release = checked

    def setWarning(self, text):
        """updates warning"""
        self.warning_widget.setText(text)
        visible = bool(text)
        self.container_warning_widget.setVisible(visible)

    def update_steps(self):
        """updates the stepped list widgets"""
        steps = len(self.action_data.target_step_list)
        enabled = steps > 0
        self.step_start_index_widget.setEnabled(enabled)
        self.step_start_value_widget.setEnabled(enabled)

        self.latched_device_widget.setEnabled(self.action_data._stepped_latched)

        index = self.step_start_index_widget.value()
        if steps > 0:
            index = gremlin.util.clamp(index, 1, steps)

            with QtCore.QSignalBlocker(self.step_start_index_widget):
                self.step_start_index_widget.setValue(index)
                self.step_start_index_widget.setRange(1, steps + 1)
            self.action_data.target_step_list.sort()

            with QtCore.QSignalBlocker(self.step_list_widget):
                csv = gremlin.util.floatlist_to_csv(self.action_data.target_step_list, decimals=3)
                self.step_list_widget.setText(csv)

            # updates individual step widgets and layout
            self._ensure_step_widgets()

            self.step_count_widget.setValue(steps, False)

            self.action_data: VjoyRemap
            if self.action_data.target_step_start_index not in self.action_data.target_step_list:
                # reset the default if no longer in the list
                self.action_data.target_step_start_index = 0

            self.step_start_value_widget.setValue(
                self.action_data.target_step_list[self.action_data.target_step_start_index],
                emit=False,
            )

            self.slider_widget.setTickMarks(self.action_data.target_step_list)

            self._update_start_value()

    def _create_step_widget(self, id, value):
        """creates a step widget for the step value"""
        widget = StepWidget(id, value)
        widget.valueChanged.connect(self._step_value_changed)
        widget.defaultChanged.connect(self._step_default_changed)
        widget.deleteRequested.connect(self._step_delete)
        return widget

    def _ensure_step_widgets(self):
        """ensures we have a widget for each defined step value"""
        widgets = []
        self.target_step_index_map.clear()
        bg = StepWidgetGroup()
        bg.clear()
        for index, value in enumerate(self.action_data.target_step_list):
            widget = self._create_step_widget(index, value)
            widgets.append((index, widget))

        for index, widget in widgets:
            self.target_step_index_map[index] = widget

        # redo the layout in sorted order if needed
        self._update_step_widget_layout()

    def _update_step_widget_layout(self):
        """ensures the step widgets appear in the step sort order"""
        gremlin.ui.ui_common.clear_layout(self.step_widget_layout)
        row = 0
        col = 0
        max_col = 5
        for index, widget in self.target_step_index_map.items():
            self.step_widget_layout.addWidget(widget, row, col)
            col += 1
            if col > max_col:
                row += 1
                col = 0

    @QtCore.Slot()
    def _add_step(self):
        """adds new step"""
        data = self.action_data.target_step_list
        count = len(data)
        if count >= 20:
            # syslog = logging.getLogger("system")
            syslog.error("VJOY: unable to add more than 20 steps.")
            return
        if count > 1:
            v1 = data[0]
            v2 = data[1]
        elif count == 0:
            v1 = -1
            v2 = 1
        elif count == 1:
            v1 = data[0]
            if v1 > -1:
                v2 = -1
            elif v1 < 1:
                v2 = 1

        value = (v1 + v2) / 2
        self.action_data.target_step_list.append(value)
        self.action_data.target_step_list.sort()
        self.update_steps()

    @QtCore.Slot()
    def _step_count_changed(self):
        """called when the count of steps changes"""
        import random

        target_count = self.step_count_widget.value()
        current_count = len(self.action_data.target_step_list)
        if target_count < current_count:
            # need fewer points
            while len(self.action_data.target_step_list) > target_count:
                self.action_data.target_step_list.pop()
        else:
            count = len(self.action_data.target_step_list)
            while count < target_count:
                value = random.randrange(-100, 100) / 100
                while value in self.action_data.target_step_list:
                    value = random.randrange(-100, 100) / 100

                self.action_data.target_step_list.append(value)
                count = len(self.action_data.target_step_list)

        self.update_steps()

    @QtCore.Slot(bool)
    def _step_direction_changed(self, checked: bool):
        self.action_data.target_step_direction = -1 if checked else 1

    @QtCore.Slot(bool)
    def _step_latched_changed(self, checked: bool):
        self.action_data._stepped_latched = checked
        self.update_steps()

    @QtCore.Slot()
    def _step_start_index_changed(self):
        index = self.step_start_index_widget.value()
        count = len(self.action_data.target_step_list)
        new_index = gremlin.util.clamp(index, 1, count)
        if new_index != index:
            with QtCore.QSignalBlocker(self.step_start_index_widget):
                self.step_start_index_widget.setValue(new_index)
            index = new_index

        self.action_data.target_step_start_index = index - 1
        value = self.action_data.target_step_list[self.action_data.target_step_start_index]
        self.step_start_value_widget.setText(f"{value:0.3f}")
        self.update_steps()

    @QtCore.Slot()
    def _step_list_changed(self):
        steps = gremlin.util.csv_to_floatlist(self.step_list_widget.text())
        if steps is None:
            steps = []
        self.action_data.target_step_list = steps
        self.update_steps()

    @QtCore.Slot(int, float)
    def _step_value_changed(self, index: int, value: float):
        # reorder the widgets if the value changed

        self.action_data.target_step_list[index] = value
        self.action_data.target_step_list.sort()

        # re-order the widgets based on the sorted steps
        self.update_steps()

    @QtCore.Slot(int, bool)
    def _step_default_changed(self, index: int, flag: bool):
        if flag:
            self.action_data.target_step_start_index = index
            self._update_start_value()

    @QtCore.Slot(int)
    def _step_delete(self, index: int):
        """delete requested"""
        result = gremlin.ui.ui_common.ConfirmBox(f"Delete step {index}?")
        if result:
            del self.action_data.target_step_list[index]
            self._ensure_step_widgets()  # redo the layout
            self.slider_widget.setTickMarks(self.action_data.target_step_list)

    def _create_step_ui(self):
        """creates the axis step mode UI components"""
        # stepped output - delay load this widget until it's used
        self.container_stepped_stack_widget = QtWidgets.QStackedWidget()
        self.main_layout.addWidget(self.container_stepped_stack_widget)

    def ensureStepUi(self):
        if not self._step_ui_loaded:
            # delay load the UI
            self._create_actual_step_ui()

    def _create_actual_step_ui(self):
        """creates the stepped UI widget - this is delay loaded because it can take time to load and should only be done if used"""
        if self._step_ui_loaded:
            # already created
            return

        self.target_step_index_map = {}  # map of step index to step widget ID keyed by index in the step list

        self.container_stepped_widget = QtWidgets.QWidget()
        self.container_stepped_layout = QtWidgets.QVBoxLayout(self.container_stepped_widget)

        self.step_value_container_widget = QtWidgets.QWidget()
        self.step_value_container_layout = QtWidgets.QHBoxLayout(self.step_value_container_widget)

        self.progression_container_widget = QtWidgets.QWidget()
        self.progression_container_layout = QtWidgets.QHBoxLayout(self.progression_container_widget)

        self.step_start_index_widget = gremlin.ui.ui_common.QIntLineEdit()
        self.step_count_widget = gremlin.ui.ui_common.QIntLineEdit()
        self.step_count_widget.setRange(0, 100)
        self.step_count_widget.valueChanged.connect(self._step_count_changed)
        self.step_start_value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.step_start_value_widget.setReadOnly(True)
        value = self.action_data.target_step_list[self.action_data.target_step_start_index]
        self.step_start_value_widget.setValue(value)

        self.step_velocity_mode_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Use velocity/acceleration mode",
            value=self.action_data._target_step_linear_mode,
            callback=self._handle_step_linear_changed,
            tooltip="When set, the stepping does not use ticks and the up/down functions increase/decrease the axis while the input is triggered.)",
        )

        widgets = []

        widget = gremlin.ui.ui_common.QDelayWidget(
            value=self.action_data.pulse_delay,
            label="Update Interval (ms):",
            tooltip="Pulse interval in milliseconds",
            callback=self._pulse_value_changed,
        )

        widgets.append(widget)

        widget = gremlin.ui.ui_common.QFloatLineEdit(
            value=self.action_data._target_step_velocity,
            callback=self._handle_step_velocity_changed,
        )

        widget = gremlin.ui.ui_common.getHContainer(
            widget,
            "Rate of change:",
            widget_only=True,
            tooltip="Rate of change (velocity) per second, determines the rate of change while the input is pressed",
        )

        widgets.append(widget)

        widget = gremlin.ui.ui_common.QFloatLineEdit(
            value=self.action_data._target_step_acceleration,
            callback=self._handle_step_acceleration_changed,
        )

        widget = gremlin.ui.ui_common.getHContainer(
            widget,
            "Acceleration:",
            widget_only=True,
            tooltip="Velocity rate of change (acceleration) per second, set to 0 for linear",
        )

        widgets.append(widget)

        self.container_linear_timings = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

        self.container_stepped_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.container_stepped_layout.addWidget(QtWidgets.QLabel("Stepping Configuration:"))
        self.container_stepped_layout.addWidget(self.step_velocity_mode_widget)
        self.container_stepped_layout.addWidget(self.container_linear_timings)

        self.step_latched_enabled_widget = QtWidgets.QCheckBox("Latch secondary input for reverse action")
        self.step_latched_enabled_widget.setToolTip("If enabled, allows binding of another input to trigger a down step")
        self.step_latched_enabled_widget.setChecked(self.action_data._stepped_latched)
        self.step_latched_enabled_widget.clicked.connect(self._step_latched_changed)

        direction = self.action_data.target_step_direction
        self_step_direction_up_widget = gremlin.ui.ui_common.QDataRadioButton("Up", data=1)
        self_step_direction_up_widget.setChecked(direction == 1)
        self_step_direction_up_widget.clicked.connect(self._step_direction_changed)

        self_step_direction_down_widget = gremlin.ui.ui_common.QDataRadioButton("Down", data=-1)
        self_step_direction_down_widget.setChecked(direction == -1)
        self_step_direction_down_widget.clicked.connect(self._step_direction_changed)

        self.step_direction_widget = gremlin.ui.ui_common.getHContainer(
            [self_step_direction_up_widget, self_step_direction_down_widget],
            "Step direction:",
            min_height=self.container_height,
            widget_only=True,
        )

        self.step_start_index_widget.setRange(1, 100)
        self.step_start_index_widget.valueChanged.connect(self._step_start_index_changed)

        self.step_list_widget = gremlin.ui.ui_common.QDataLineEdit()
        self.step_list_widget.lostFocus.connect(self._step_list_changed)

        self.add_step_widget = QtWidgets.QPushButton("Add Step")
        self.add_step_widget.setToolTip("Adds a new step")
        self.add_step_widget.clicked.connect(self._add_step)

        self.slider_widget = gremlin.ui.qsliderwidget.QSliderWidget(object_name=f"Slider for VjoyWidget: {self.action_data.input_display_name}")
        self.slider_widget.setRange(-1, 1)
        self.slider_widget.setReadOnly(True)
        self.slider_widget.setDrawHandles(False)
        self.slider_widget.setMinimumWidth(200)
        self.slider_widget.setMarkerVisible(False)

        self.normalize_widget = QtWidgets.QPushButton("Normalize")
        self.normalize_widget.setToolTip("Normalizes steps to be evenly spaced")
        self.normalize_widget.clicked.connect(self._normalize_steps)

        self.low_progression_widget = QtWidgets.QPushButton("Low")
        self.low_progression_widget.setToolTip("Steps follow a linear progression from the low range.  Most steps are in the lower half.")
        self.low_progression_widget.clicked.connect(self._low_progression_steps)

        self.high_progression_widget = QtWidgets.QPushButton("High")
        self.high_progression_widget.setToolTip("Steps follow a linear progression from the high range.  Most steps are in the higher half.")
        self.high_progression_widget.clicked.connect(self._high_progression_steps)

        self.cubic_progression_low_widget = QtWidgets.QPushButton("Geometric Low")
        self.cubic_progression_low_widget.setToolTip("Steps follow a geometric (log) progression.")
        self.cubic_progression_low_widget.clicked.connect(self._geometric_progression_steps_low)

        self.cubic_progression_high_widget = QtWidgets.QPushButton("Geometric High")
        self.cubic_progression_high_widget.setToolTip("Steps follow a geometric (log) progression.")
        self.cubic_progression_high_widget.clicked.connect(self._geometric_progression_steps_high)

        # self.step_value_container_layout.addWidget(self.grab_widget)
        self.step_value_container_layout.addWidget(self.add_step_widget)
        self.step_value_container_layout.addWidget(QtWidgets.QLabel("Start index:"))
        self.step_value_container_layout.addWidget(self.step_start_index_widget)
        self.step_value_container_layout.addWidget(QtWidgets.QLabel("Start value:"))
        self.step_value_container_layout.addWidget(self.step_start_value_widget)
        self.step_value_container_layout.addWidget(QtWidgets.QLabel("Steps:"))
        self.step_value_container_layout.addWidget(self.step_count_widget)
        self.step_value_container_layout.addWidget(self.step_direction_widget)

        self.step_value_container_layout.addStretch()

        self.progression_container_layout.addWidget(QtWidgets.QLabel("Distribution:"))
        self.progression_container_layout.addWidget(self.normalize_widget)
        self.progression_container_layout.addWidget(self.low_progression_widget)
        self.progression_container_layout.addWidget(self.high_progression_widget)
        self.progression_container_layout.addWidget(self.cubic_progression_low_widget)
        self.progression_container_layout.addWidget(self.cubic_progression_high_widget)
        self.progression_container_layout.addStretch()

        self.step_widget_container = QtWidgets.QWidget()
        self.step_widget_layout = QtWidgets.QGridLayout(self.step_widget_container)
        self.step_widget_layout.addWidget(QtWidgets.QWidget(), 0, 6)
        self.step_widget_layout.setColumnStretch(6, 2)

        widgets = [
            self.slider_widget,
            self.step_value_container_widget,
            self.step_widget_container,
            self.progression_container_widget,
        ]
        self.container_ticks_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

        self.container_stepped_layout.addWidget(self.container_ticks_widget)

        self.stepped_selector_device_widget = gremlin.ui.ui_common.QDataComboBox()
        self.stepped_selector_input_widget = gremlin.ui.ui_common.QDataComboBox()

        listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback=self._stepped_listen)

        self.latched_device_widget = QtWidgets.QWidget()
        device_layout = QtWidgets.QGridLayout(self.latched_device_widget)

        row = 0
        device_layout.addWidget(QtWidgets.QLabel("Down Device:"), row, 0)
        device_layout.addWidget(self.stepped_selector_device_widget, row, 1)
        device_layout.addWidget(listen_widget, row, 3)
        device_layout.addWidget(QtWidgets.QLabel(" "), row, 4)

        row += 1
        device_layout.addWidget(QtWidgets.QLabel("Down Input:"), row, 0)
        device_layout.addWidget(self.stepped_selector_input_widget, row, 1)
        device_layout.setColumnStretch(4, 2)

        self.container_stepped_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.container_stepped_layout.addWidget(self.step_latched_enabled_widget)
        self.container_stepped_layout.addWidget(self.latched_device_widget)

        self.stepped_selector_device_widget.currentIndexChanged.connect(self._stepped_device_changed_cb)
        self.stepped_selector_input_widget.currentIndexChanged.connect(self._stepped_input_changed_cb)

        self.stepped_device_map = {}  # holds the device information keyed by device_id (str)
        self.stepped_input_map = {}  # holds the list of buttons for the given device by device_id(str)
        devices = sorted(joystick_handling.button_input_devices(), key=lambda x: x.name)

        # default device
        device_guid = self.action_data.hardware_device_guid if self.action_data.stepped_device_id is None else self.action_data.stepped_device_id
        device_index = None
        current_index = 0

        for dev in devices:
            self.stepped_device_map[dev.device_id] = dev
            button_list = {}
            for input_id in range(1, dev.button_count + 1):
                if dev.device_guid == self.action_data.hardware_device_guid and input_id == self.action_data.hardware_input_id:
                    # skip self as a possible input
                    continue
                button_list[input_id] = f"Button {input_id}"

            if button_list:
                self.stepped_input_map[dev.device_id] = button_list
                self.stepped_selector_device_widget.addItem(dev.name, dev.device_id)
                if device_index is None and dev.device_id == device_guid:
                    device_index = current_index
                current_index += 1

        if device_index is not None:
            self.stepped_selector_device_widget.setCurrentIndex(device_index)

        self.container_stepped_stack_widget.addWidget(self.container_stepped_widget)
        self._enable_axis_tracking()
        self.update_steps()

        self._step_ui_loaded = True

    def _handle_step_linear_changed(self, checked: bool):
        self.action_data._target_step_linear_mode = checked
        self._update_ui()

    def _handle_step_velocity_changed(self, value: float):
        self.action_data._target_step_velocity = value

    def _handle_step_acceleration_changed(self, value: float):
        self.action_data._target_step_acceleration = value

    def get_axis_value(self, channels=False):
        """gets the current axis value - if channels enabled, returns a list of the transforms"""
        # value = gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
        # if channels:
        #     raw_value = self.action_data.get_raw_axis_value()
        #     curve_value = self.action_data.get_curved_axis_value(raw_value)
        #     data = gremlin.event_handler.AxisValues()

        value = self.action_data.get_filtered_axis_value()
        return value

    def _update_start_value(self):
        """updates the start value widget repeater"""
        index = self.action_data.target_step_start_index
        value = self.action_data.target_step_list[index]
        self.step_start_value_widget.setValue(value)

        # check the correct widget
        widget = self.target_step_index_map[index]
        widget.setDefault(True)

    @QtCore.Slot()
    def _normalize_steps(self):
        """normalizes the steps"""
        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1, 1]
        elif count == 1:
            data = [0]
        else:
            data = []
            interval = 2 / (count - 1)
            x = -1
            for _ in range(count):
                data.append(x)
                x += interval

        self.action_data.target_step_list = data
        self.update_steps()

    @QtCore.Slot()
    def _low_progression_steps(self):
        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1, 1]
        elif count == 1:
            data = [0]
        else:
            data = []
            interval = 1
            x = 1
            for _ in range(count):
                data.append(x)
                x -= interval
                interval /= 2
        self.action_data.target_step_list = data
        self.update_steps()

    @QtCore.Slot()
    def _high_progression_steps(self):
        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1, 1]
        elif count == 1:
            data = [0]
        else:
            data = []
            interval = 1
            x = -1
            for _ in range(count):
                data.append(x)
                x += interval
                interval /= 2
        self.action_data.target_step_list = data
        self.update_steps()

    @QtCore.Slot()
    def _geometric_progression_steps_low(self):
        self._geometric_progression(False)

    @QtCore.Slot()
    def _geometric_progression_steps_high(self):
        self._geometric_progression(True)

    def _geometric_progression(self, inverted=False):
        import numpy as np

        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1, 1]
        elif count == 1:
            data = [0]
        else:
            data = []
            progression = np.geomspace(1, 10, count)
            for n in progression:
                value = gremlin.util.scale_to_range(float(n), source_min=1, source_max=10, invert=inverted)

                data.append(value)
            data.sort()

        self.action_data.target_step_list = data
        self.update_steps()

    @QtCore.Slot()
    def _grab_handler(self):
        """grab the min value from the axis position"""
        value = gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
        if value not in self.action_data.target_step_list:
            self.action_data.target_step_list.append(value)
            self.action_data.target_step_list.sort()
            self._ensure_step_widgets()

    def _stepped_listen(self):
        gremlin.util.InvokeUiMethod(self._stepped_listen_ui)

    def _stepped_listen_ui(self):
        """listens for the button to use as the down step - runs on UI thread"""
        button_press_dialog = gremlin.ui.ui_common.InputListenerWidget([InputType.JoystickButton], return_kb_event=False)

        button_press_dialog.item_selected.connect(self._update_button)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        button_press_dialog.show()

    def _update_button(self, event: gremlin.event_handler.Event):
        gremlin.util.InvokeUiMethod(self._update_button_ui, event)

    def _update_button_ui(self, event: gremlin.event_handler.Event):
        """called when a button input is selected - runs on ui thread"""
        hardware_index = self.stepped_selector_device_widget.findData(event.device_id)
        self.stepped_selector_device_widget.setCurrentIndex(hardware_index)
        input_index = self.stepped_selector_input_widget.findData(event.identifier)
        self.stepped_selector_input_widget.setCurrentIndex(input_index)

    @QtCore.Slot()
    def _stepped_device_changed_cb(self):
        """stepped device changed"""
        index = self.stepped_selector_device_widget.currentIndex()
        device_id = self.stepped_selector_device_widget.itemData(index)
        active_input_id = self.action_data.stepped_input_id
        current_index = 0
        selected_input_index = None
        with QtCore.QSignalBlocker(self.stepped_selector_input_widget):
            self.stepped_selector_input_widget.clear()
            first_input_id = None
            for input_id, button_name in self.stepped_input_map[device_id].items():
                self.stepped_selector_input_widget.addItem(button_name, input_id)
                if first_input_id is None:
                    first_input_id = input_id
                if selected_input_index is None and input_id == active_input_id:
                    selected_input_index = current_index
                current_index += 1

            if selected_input_index is not None:
                index = self.stepped_selector_input_widget.findData(selected_input_index)
                if index != -1:
                    self.stepped_selector_input_widget.setCurrentIndex(selected_input_index)
                else:
                    self.action_data.stepped_input_id = first_input_id
            else:
                self.action_data.stepped_input_id = first_input_id

        self.action_data.stepped_device_id = device_id

    @QtCore.Slot()
    def _stepped_input_changed_cb(self):
        """stepped input changed"""
        index = self.stepped_selector_input_widget.currentIndex()
        input_id = self.stepped_selector_input_widget.itemData(index)
        self.action_data.stepped_input_id = input_id

    def load_actions_from_input_type(self):
        """occurs when the type of input is changed"""
        with QtCore.QSignalBlocker(self.cb_action_list):
            self.cb_action_list.clear()
            input_type = self.action_data.get_input_type()

            actions = ()
            if self.action_data.input_is_axis() or input_type == InputType.JoystickAxis:
                # axis can only set an axis
                actions = (
                    VjoyAction.VJoyAxis,
                    VjoyAction.VJoyAxisToButton,
                    VjoyAction.VJoyMergeAxis,
                )

            elif self.action_data.input_is_button() or input_type == InputType.JoystickButton:
                # various button modes
                actions = (
                    VjoyAction.VJoyButton,  # hold button
                    VjoyAction.VJoyButtonInverted,  # invert button
                    VjoyAction.VJoyButtonPress,  # press button
                    VjoyAction.VJoyButtonRelease,  # release button
                    VjoyAction.VJoyPulse,  # pulse button
                    VjoyAction.VJoyToggle,  # toggle button
                    VjoyAction.VJoyHat,  # hold hat
                    VjoyAction.VJoyHatPress,  # press hat
                    VjoyAction.VJoyHatPulse,  # pulse hat
                    VjoyAction.VJoyInvertAxis,  # invert axis
                    VjoyAction.VJoySetAxis,  # set axis
                    VjoyAction.VJoySetAxisStepped,  # stepped axis
                    VjoyAction.VJoyRangeAxis,  # range axis
                    VjoyAction.VJoyMergeAxis,  # merge axis
                    VjoyAction.VJoyEnableLocalOnly,
                    VjoyAction.VJoyEnableRemoteOnly,
                    VjoyAction.VJoyEnableLocal,
                    VjoyAction.VJoyEnableRemote,
                    VjoyAction.VJoyEnableLocalAndRemote,
                    VjoyAction.VJoyDisableLocal,
                    VjoyAction.VJoyDisableRemote,
                    VjoyAction.VJoyToggleRemote,
                    VjoyAction.VJoyEnablePairedRemote,
                    VjoyAction.VJoyDisablePairedRemote,
                )

            elif self.action_data.hardware_input_type == InputType.JoystickHat:
                # hat actions
                actions = [VjoyAction.VJoyHat, VjoyAction.VJoyHatToButton]

            else:
                syslog.warning(f"VJOYREMAP: don't know what actions to load for input type: {input_type} {input_type.name}")

            for action in actions:
                self.cb_action_list.addItem(VjoyAction.to_name(action), action)

    def _vjoy_id_changed(self, index):
        """occurs when the vjoy output device is changed"""
        with QtCore.QSignalBlocker(self.cb_vjoy_device_selector):
            device_id = self.cb_vjoy_device_selector.itemData(index)
            self.action_data.vjoy_id = device_id
            self._update_vjoy_device_input_list()
            self._update_hat_mapping()
            self.notify_device_changed()

            # update warning if the device is disconnected
            if not gremlin.joystick_handling.is_vjoy_connected(device_id):
                self.setWarning(f"Warning: Device VJOY [{device_id}] is not currently connected.")
            else:
                self.setWarning(None)

    def _handle_vjoy_output_id_changed(self, index):
        """occurs when the vjoy output input ID is changed"""
        if self.cb_vjoy_output_selector.count():
            # ignore if there are no outputs
            with QtCore.QSignalBlocker(self.cb_vjoy_output_selector):
                if (
                    self.action_data.action_mode
                    in (
                        VjoyAction.VJoyHat,
                        VjoyAction.VJoyHatPress,
                        VjoyAction.VJoyHatPulse,
                    )
                    and self.action_data.input_type == InputType.JoystickButton
                ):
                    # hat output - grab the hat positions
                    id = self.cb_vjoy_output_selector.itemData(index)
                    self.action_data.vjoy_hat_id = id
                    position = self.cb_hat_selector.currentData()
                    self.action_data.vjoy_hat_position = position
                    return_position = self.cb_hat_return_selector.currentData()
                    self.action_data.vjoy_hat_return_position = return_position
                else:
                    input_id = self.cb_vjoy_output_selector.itemData(index)
                    self.action_data.set_input_id(input_id)

                if self.is_button_mode:
                    self.select_button(self.action_data.vjoy_id, input_id)

                # self._populate_grid(self.action_data.vjoy_id, input_id)
                self.notify_device_changed()

    def _handle_hat_selector_changed(self, index):
        """occurs when hat is changed"""
        position = index[0]
        self.action_data.vjoy_hat_position = position

    def _handle_hat_return_selector_changed(self, index):
        """occurs when hat is changed"""
        position = index[0]
        self.action_data.vjoy_hat_return_position = position

    def _handle_tag_callback(self, action: VjoyRemap, extra_data: dict):  # noqa: F821
        if action.vjoy_id == self.action_data.vjoy_id:
            # same vjoy device
            input_type = (
                action._get_input_type() if hasattr(action, "_get_input_type") else action.input_type if hasattr(action, "input_type") else None
            )  # ignore
            if input_type == self.action_data.get_input_type():
                match input_type:
                    case InputType.JoystickAxis:
                        extra_data["axis"][action.vjoy_input_id] = True
                    case InputType.JoystickButton:
                        extra_data["buttons"][action.vjoy_input_id] = True
                    case InputType.JoystickHat:
                        extra_data["hats"][action.vjoy_input_id] = True

        return True

    def _handle_next_unused(self, widget):
        """picks the next available button in the profile"""
        profile = gremlin.shared_state.current_profile
        extra_data = {"buttons": {}, "axis": {}, "hats": {}}
        tag_list = ["vjoyremap", "remap"]  # grab new and legacy actions
        profile.filter_actions(tag_list, self._handle_tag_callback, extra_data)
        input_type = self._get_input_type()
        used_list = None
        device = gremlin.joystick_handling.getDevice(self.action_data.vjoy_device_guid)
        match input_type:
            case InputType.JoystickAxis:
                used_list = list(extra_data["axis"].keys())
                valid_list = list(device.axis_id_map.keys())
            case InputType.JoystickButton:
                used_list = list(extra_data["buttons"].keys())
                valid_list = list(range(1, device.button_count))
            case InputType.JoystickHat:
                used_list = list(extra_data["hats"].keys())
                valid_list = list(range(1, device.hat_count))

        if valid_list:
            # device has the required outputs
            next_unused = valid_list[0]
            if used_list:
                # remove the used items from the unused list
                unused_list = list(set(valid_list) - set(used_list))
                if unused_list:
                    next_unused = unused_list[0]

            # find the entry in the drop down and select
            index = self.cb_vjoy_output_selector.findData(next_unused)
            if index != -1:
                self.cb_vjoy_output_selector.setCurrentIndex(index)

    def refresh_grid(self):
        """refreshes the grid"""
        if VjoyAction.is_button_action(self.action_data.action_mode):
            gremlin.util.InvokeUiMethod(self._refresh_grid_ui)  # ensure on UI thread

    def _refresh_grid_ui(self):
        if Shiboken.isValid(self):
            with QtCore.QSignalBlocker(self.grid_visible_widget):
                self.grid_visible_widget.setChecked(self.action_data.grid_visible)

            self._populate_grid()
            self._update_ui()

    def notify_device_changed(self):
        state = gremlin.joystick_handling.VJoyUsageState()
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = state._active_device_guid
        event.device_name = state._active_device_name
        event.device_input_type = self.action_data.input_type
        event.device_input_id = state._active_device_input_id
        event.vjoy_id = self.action_data.vjoy_id
        event.vjoy_input_id = self.action_data.vjoy_input_id
        event.source = self.action_data
        el.profile_device_changed.emit(event)
        el.icon_changed.emit(event)

        self._update_info()

    def _update_vjoy_device_input_list(self):
        """loads a list of valid outputs for the current vjoy device based on the mode"""
        with QtCore.QSignalBlocker(self.cb_vjoy_output_selector):
            self.cb_vjoy_output_selector.clear()
            input_type = self._get_selector_input_type()
            action_mode = self.action_data.action_mode

            self.setWarning(None)  # clear any warnings

            if self.action_data.vjoy_id not in self.action_data.vjoy_map:
                self.action_data.refresh_vjoy()
                if self.action_data.vjoy_id not in self.action_data.vjoy_map:
                    self.setWarning(f"VJOY configuration has changed and GremlinEx is unable to find requested Vjoy device [{self.action_data.vjoy_id}]")
                    return

            if not gremlin.joystick_handling.is_vjoy_connected(self.action_data.vjoy_id):
                self.setWarning(f"VJOY device [{self.action_data.vjoy_id}] is not currently connected or available.")

            dev = self.action_data.vjoy_map[self.action_data.vjoy_id]
            if action_mode in (
                VjoyAction.VJoySetAxis,
                VjoyAction.VJoySetAxisStepped,
                VjoyAction.VJoyRangeAxis,
                VjoyAction.VJoyAxis,
                VjoyAction.VJoyInvertAxis,
                VjoyAction.VJoyMergeAxis,
            ):
                count = dev.axis_count
                for id in range(1, count + 1):
                    axis_name = dev.axis_names[id - 1]
                    self.cb_vjoy_output_selector.addItem(f"Axis {axis_name}", id)

                output_index = self.cb_vjoy_output_selector.findData(self.action_data.vjoy_input_id)
                if output_index != -1:
                    self.cb_vjoy_output_selector.setCurrentIndex(output_index)
            elif input_type in VJoyRemapWidget.input_type_buttons:
                if action_mode in (
                    VjoyAction.VJoyButton,
                    VjoyAction.VJoyButtonPress,
                    VjoyAction.VJoyButtonRelease,
                    VjoyAction.VJoyPulse,
                    VjoyAction.VJoyToggle,
                    VjoyAction.VJoyAxisToButton,
                    VjoyAction.VJoyHatToButton,
                ):
                    count = dev.button_count
                    for id in range(1, count + 1):
                        self.cb_vjoy_output_selector.addItem(f"Button {id}", id)
                    input_id = self.action_data.vjoy_input_id

                    index = self._get_output_index()
                    if index != -1:
                        with QtCore.QSignalBlocker(self.cb_vjoy_output_selector):
                            self.cb_vjoy_output_selector.setCurrentIndex(index)

                    if input_id < 1 or input_id > count:
                        self.setWarning(f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy button # {input_id}")
                        return
                elif action_mode in (
                    VjoyAction.VJoyHat,
                    VjoyAction.VJoyHatPress,
                    VjoyAction.VJoyHatPulse,
                ):
                    # map to hat
                    count = dev.hat_count
                    icon_map = vjoy.vjoy.Hat.getEightDirectionsIconMap()
                    name_map = vjoy.vjoy.Hat.getEightDirectionsNameMap()

                    with QtCore.QSignalBlocker(self.cb_vjoy_output_selector):
                        for i in range(count):
                            # each position of the hat
                            id = i + 1
                            self.cb_vjoy_output_selector.addItem(f"Hat {id}", id)

                        # hat key
                        index = self._get_output_index()
                        if index != -1:
                            with QtCore.QSignalBlocker(self.cb_vjoy_output_selector):
                                self.cb_vjoy_output_selector.setCurrentIndex(index)

                    # hat position selectors
                    with QtCore.QSignalBlocker(self.cb_hat_selector):
                        with QtCore.QSignalBlocker(self.cb_hat_return_selector):
                            hat_position_index = -1
                            hat_return_index = -1
                            for i, position in enumerate(name_map.keys()):
                                icon_name = icon_map[position]
                                icon = gremlin.util.load_icon(icon_name)
                                key = (position,)
                                self.cb_hat_selector.addItem(icon, f"{name_map[position]}", key)
                                self.cb_hat_return_selector.addItem(icon, f"{name_map[position]}", key)
                                if position == self.action_data.vjoy_hat_position:
                                    hat_position_index = i
                                if position == self.action_data.vjoy_hat_return_position:
                                    hat_return_index = i

                                # hat position key
                                if hat_position_index != -1:
                                    self.cb_hat_selector.setCurrentIndex(hat_position_index)

                                # hat return position key
                                if hat_return_index != -1:
                                    self.cb_hat_return_selector.setCurrentIndex(hat_return_index)

                    input_id = self.action_data.vjoy_input_id
                    if input_id < 1 or input_id > count:
                        self.setWarning(f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy hat # {input_id}")
                        return

            elif input_type == InputType.JoystickHat:
                count = dev.hat_count
                for id in range(1, count + 1):
                    self.cb_vjoy_output_selector.addItem(f"Hat {id}", id)
                input_id = self.action_data.vjoy_input_id
                if input_id < 1 or input_id > count:
                    self.setWarning(f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy hat # {input_id}")
                    return

    def _get_output_index(self):
        index = self.cb_vjoy_output_selector.findData(self.action_data.vjoy_input_id)
        return index or -1

    @QtCore.Slot(float)
    def _target_value_changed(self, value):
        """called when the value box changes"""
        if value.isnumeric():
            value = float(value)
            self.action_data.target_value = value
            self.target_value_valid = True
        else:
            self.target_value_valid = False

    @QtCore.Slot(bool)
    def _target_relative_changed(self, checked: bool):
        self.action_data.target_is_relative = checked

    @QtCore.Slot(bool)
    def _handle_target_use_last_changed(self, checked: bool):
        self.action_data.target_use_last = checked
        self._update_ui()

    def _update_ui(self):
        """updates ui based on the current action requested to show/hide needed components"""
        if not Shiboken.isValid(self):
            return

        if not self._ui_loaded:
            return

        action_data = self.action_data

        action = action_data.action_mode
        input_type = action_data.input_type

        axis_visible = False
        pulse_visible = False
        repeat_visible = self.action_data.pulse_repeat
        step_repeat_visible = self.action_data._target_step_linear_mode

        sync_on_start_visible = False
        grid_visible = False
        show_grid_visible = True
        output_range_visible = False
        button_range_visible = False
        output_mode_visible = False  # output mode for button output
        output_curve_visible = False
        options_visible = False

        override_visible = False
        relative_visible = False

        hat_visible = False
        hat_position_visible = False
        hat_return_position_visible = False
        input_selector_visible = True

        _exec_on_release_visible = False
        paired_visible = False
        merge_visible = False

        stepped_visible = False
        ticks_visible = False
        reverse_visible = False

        set_target_visible = False
        relative_target_visible = False
        default_target_visible = False
        repeater_visible = False

        self.chkb_auto_release_widget.setVisible(
            input_type
            in (
                InputType.KeyboardLatched,
                InputType.Keyboard,
                InputType.Midi,
                InputType.OpenSoundControl,
            )
        )

        is_axis = self.action_data.input_is_axis()  # input_type == InputType.JoystickAxis

        if is_axis:
            grid_visible = action == VjoyAction.VJoyAxisToButton

            button_range_visible = action == VjoyAction.VJoyAxisToButton
            pulse_visible = self.action_data.button_mode == ButtonOutputMode.Pulse

            axis_visible = not (grid_visible or output_range_visible)  # or hardware_widget_visible)
            merge_visible = action == VjoyAction.VJoyMergeAxis and axis_visible
            reverse_visible = True
            relative_visible = self.action_data.axis_mode == "relative"
            if relative_visible:
                relative_target_visible = self.action_data.use_relative_value
                default_target_visible = not relative_target_visible

            output_curve_visible = action in (
                VjoyAction.VJoyAxis,
                VjoyAction.VJoyMergeAxis,
                VjoyAction.VJoyRangeAxis,
            )

            # start_value_enabled = not self.action_data.sync_on_start

            sync_on_start_visible = action == VjoyAction.VJoyAxis

            if action == VjoyAction.VJoyMergeAxis:
                # can clear if more than one merge axis defined
                self.merge_clear_widget.setEnabled(len(self.action_data._merge_data) > 1)

            repeater_visible = True

        elif input_type in VJoyRemapWidget.input_type_buttons:
            output_range_visible = action == VjoyAction.VJoyRangeAxis
            sync_on_start_visible = True
            pulse_visible = action in (VjoyAction.VJoyPulse, VjoyAction.VJoyHatPulse)
            _start_visible = action in (
                VjoyAction.VJoyButton,
                VjoyAction.VJoyButtonPress,
                VjoyAction.VJoyButtonRelease,
            )
            if action in (
                VjoyAction.VJoyPulse,
                VjoyAction.VJoyButtonPress,
                VjoyAction.VJoyToggle,
                VjoyAction.VJoyButtonRelease,
                VjoyAction.VJoyButton,
            ):
                grid_visible = True
                _start_visible = True
            paired_visible = action == VjoyAction.VJoyButtonPress
            _exec_on_release_visible = action_data.input_type in VJoyRemapWidget.input_type_buttons
            options_visible = True

            hat_position_visible = action in (
                VjoyAction.VJoyHat,
                VjoyAction.VJoyHatPress,
                VjoyAction.VJoyHatPulse,
            )
            hat_return_position_visible = action in (
                VjoyAction.VJoyHat,
                VjoyAction.VJoyHatPulse,
            )

            # if action == VjoyAction.VJoyHat:
            #     # show hat options
            #     hat_visible = True

        elif input_type == InputType.JoystickHat:
            if action == VjoyAction.VJoyHatToButton:
                grid_visible = False
                hat_visible = True
                show_grid_visible = False
            _start_visible = True
            input_selector_visible = not hat_visible
            options_visible = True

        output_selector_visible = True

        match action:
            case VjoyAction.VJoyAxis:
                output_mode_visible = True
            case VjoyAction.VJoyRangeAxis:
                grid_visible = False
            # case VjoyAction.VJoyMergeAxis:
            #     output_mode_visible = True
            case VjoyAction.VJoySetAxis:
                output_range_visible = False
                relative_visible = True
                output_mode_visible = True
                set_target_visible = not self.action_data.target_use_last

            case VjoyAction.VJoySetAxisStepped:
                output_range_visible
                grid_visible = False
                stepped_visible = True
                ticks_visible = not self.action_data._target_step_linear_mode  # hide steps if in linear mode
            case VjoyAction.VJoyAxisToButton:
                output_range_visible = False

                grid_visible = True

            case VjoyAction.VJoyPulse:
                pulse_visible = True

        # control actions
        output_selector_visible = action not in (
            VjoyAction.VJoyToggleRemote,
            VjoyAction.VJoyEnableRemoteOnly,
            VjoyAction.VJoyEnableLocalOnly,
            VjoyAction.VJoyDisableRemote,
            VjoyAction.VJoyDisableLocal,
            VjoyAction.VJoyEnableRemote,
            VjoyAction.VJoyEnableLocal,
            VjoyAction.VJoyEnableLocalAndRemote,
            VjoyAction.VJoyEnablePairedRemote,
            VjoyAction.VJoyDisablePairedRemote,
        )

        # absolute_visible = not relative_visible

        is_command = VjoyAction.is_command(action)
        selector_visible = not is_command

        button_to_axis_visible = action == VjoyAction.VJoySetAxis

        grid_visible = grid_visible and self.action_data.grid_visible

        # self.pulse_widget.setVisible(pulse_visible)
        # self.start_widget.setVisible(start_visible)
        self.grid_visible_widget.setVisible(show_grid_visible)

        # self._axis_start_value_enabled_widget.setEnabled(start_value_enabled)
        # self.sb_start_value.setEnabled(start_value_enabled)

        if self.button_grid_widget:
            # hide/show the grid in the stack widget
            self.button_grid_stack_widget.setCurrentIndex(1 if grid_visible else 0)
            # self.button_grid_widget.setVisible(grid_visible)

        if self.container_axis_widget:
            self.container_axis_widget.setVisible(axis_visible)

        # merge axis options
        if self._merge_enabled:
            self.container_merge_widget.setVisible(merge_visible)

        self.container_stepped_stack_widget.setVisible(stepped_visible)

        # self.hardware_input_container_widget.setVisible(hardware_widget_visible)
        self.axis_range_container_widget.setVisible(output_range_visible)
        # self.chkb_exec_on_release.setVisible(exec_on_release_visible)
        # self._execute_widget.setVisible()
        self.chkb_paired.setVisible(paired_visible)
        self.target_value_container_widget.setVisible(button_to_axis_visible)

        if self._step_ui_loaded:
            # stepped UI specific widgets
            axis_steps_visible = action == VjoyAction.VJoySetAxisStepped
            self.step_value_container_widget.setVisible(axis_steps_visible)
            self.container_linear_timings.setVisible(step_repeat_visible)
            self.container_ticks_widget.setVisible(ticks_visible)

        self.lbl_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_output_selector.setVisible(selector_visible)
        self.lbl_vjoy_output_selector.setVisible(selector_visible)

        self.is_button_mode = grid_visible

        self.action_label.setText(VjoyAction.to_description(action))

        # self.button_grid_widget.setVisible(self.action_data.grid_visible)
        self.button_grid_stack_widget.setVisible(grid_visible)

        if self._hat_mapping_ui_loaded:
            self.container_hat_widget.setVisible(hat_visible)

        self.cb_vjoy_output_selector.setVisible(input_selector_visible)
        self.lbl_vjoy_output_selector.setVisible(input_selector_visible)

        # self.sb_start_value.setEnabled(start_value_enabled)

        self.button_to_axis_value_widget.setEnabled(set_target_visible)

        self.container_axis_to_button_range_widget.setVisible(button_range_visible)
        self.container_button_mode_widget.setVisible(button_range_visible)
        self.container_relative_widget.setVisible(relative_visible)
        self.container_output_range_widget.setVisible(output_range_visible)
        self.container_output_curve_widget.setVisible(output_curve_visible)
        self.container_output_mode_widget.setVisible(output_mode_visible)
        self.container_reverse_widget.setVisible(reverse_visible)
        self.container_override_widget.setVisible(override_visible)
        self.container_merge_stack_widget.setVisible(merge_visible)

        self.container_pulse_widget.setVisible(pulse_visible)
        self.pulse_duration_widget.setVisible(pulse_visible)
        self.container_interval_widget.setVisible(repeat_visible)
        self.container_options_widget.setVisible(options_visible)
        if self.container_repeater_widget:
            self.container_repeater_widget.setVisible(repeater_visible)

        self.container_target_widget.setVisible(relative_target_visible)
        self.container_relative_widget.setVisible(default_target_visible)

        self.sync_on_start_widget.setVisible(sync_on_start_visible)

        self.container_output_selector_widget.setVisible(output_selector_visible)
        self.container_device_selector_widget.setVisible(output_selector_visible)
        self.show_disconnected_widget.setVisible(output_selector_visible)

        self.container_hat_selector_widget.setVisible(hat_position_visible)
        self.container_hat_return_selector_widget.setVisible(hat_return_position_visible)

        self._update_info()

    def _handle_action_mode_changed(self, index):
        """called when the drop down value changes"""
        with QtCore.QSignalBlocker(self.cb_action_list):
            action: VjoyAction = self.cb_action_list.itemData(index)
            match action:
                case VjoyAction.VJoySetAxisStepped:
                    # delay load axis step UI
                    self.ensureStepUi()
                case VjoyAction.VJoyHatToButton:
                    # delay load hat mapping UI
                    self.ensureHatMappingLoaded()
                case VjoyAction.VJoyMergeAxis:
                    # delay load merge mapping UI
                    self.ensureMergeMappingLoaded()

            self.action_data.action_mode = action
            self.action_data.input_id = self.action_data.get_input_id()
            self.cb_vjoy_output_selector.clear()  # ensure output is refreshed
            self._update_ui()
            self._update_vjoy_device_input_list()
            self._update_merge_data()
            self._update_repeater()
            self.notify_device_changed()

    def _get_action_mode(self):
        """returns the action mode"""
        index = self.cb_action_list.currentIndex()
        action = self.cb_action_list.itemData(index)
        return action

    @QtCore.Slot(int)
    def _pulse_value_changed(self, value):
        """called when the pulse value changes"""
        self.action_data.pulse_delay = value

    @QtCore.Slot(int)
    def _pulse_repeat_value_changed(self, value):
        """called when the pulse value changes"""
        if value >= 0:
            self.action_data.pulse_repeat_delay = value

    def _start_changed(self, rb):
        """called when the start mode is changed"""
        id = self.start_button_group.checkedId()
        self.action_data.button_start_value = id == 1

    def _create_pixmal(self, color):
        from PySide6.QtGui import QPixmap, QPainter, QPen, QBrush, QColor
        from PySide6.QtCore import Qt

        size = 24
        radius = 4
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)  # For smooth, anti-aliased edges
        pen = QPen(QColor(color))  # Blue outline, 4px thick
        brush = QBrush(QColor(color))  # Semi-transparent red fill
        painter.setPen(pen)
        painter.setBrush(brush)
        w2 = size // 2
        diameter = radius * 2
        painter.drawEllipse(w2 - radius, w2 - radius, diameter, diameter)
        painter.end()
        return pixmap

    def _create_input_grid(self):
        """create a grid of buttons for easy selection"""

        if self.action_data.vjoy_id not in self.action_data.vjoy_map:
            self.action_data.refresh_vjoy()
            if self.action_data.vjoy_id not in self.action_data.vjoy_map:
                gremlin.ui.ui_common.MessageBox(
                    prompt=f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy device # {self.action_data.vjoy_id}"
                )
                return

        self.button_grid_stack_widget = QtWidgets.QStackedWidget()
        self.button_grid_stack_widget.addWidget(QtWidgets.QWidget())  # blank item at index 0

        if self.action_data.grid_visible and not self.button_grid_widget:
            # create the widget if requested

            # add the legend
            label_used_here_widget = QtWidgets.QLabel("Used in this mapping")
            label_used_somewhere_widget = QtWidgets.QLabel("Used in the profile")
            label_unused_widget = QtWidgets.QLabel("Not used")

            used_pixmap = self._create_pixmal(gremlin.ui.ui_common.Color.greenColor())
            used_elsewhere_pixmap = self._create_pixmal(gremlin.ui.ui_common.Color.orangeColor())
            unused_pixmap = self._create_pixmal(gremlin.ui.ui_common.Color.grayColor())  # assuming gray for not used
            icon_used_here_widget = QtWidgets.QLabel()
            icon_used_here_widget.setPixmap(used_pixmap)
            icon_used_somewhere_widget = QtWidgets.QLabel()
            icon_used_somewhere_widget.setPixmap(used_elsewhere_pixmap)
            icon_unused_widget = QtWidgets.QLabel()
            icon_unused_widget.setPixmap(unused_pixmap)
            used_here_widget = gremlin.ui.ui_common.getHContainer([icon_used_here_widget, label_used_here_widget], widget_only=True)
            used_somewhere_widget = gremlin.ui.ui_common.getHContainer([icon_used_somewhere_widget, label_used_somewhere_widget], widget_only=True)
            unused_widget = gremlin.ui.ui_common.getHContainer([icon_unused_widget, label_unused_widget], widget_only=True)
            legend_widget = gremlin.ui.ui_common.getHContainer(["Legend:", used_here_widget, used_somewhere_widget, unused_widget, "||"], widget_only=True)

            self.button_grid_widget = QtWidgets.QWidget()

            widgets = [legend_widget, self.button_grid_widget]
            grid_container_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

            # link all radio buttons
            self.button_group = QtWidgets.QButtonGroup()
            self.button_group.buttonClicked.connect(self._select_changed)
            self.icon_map = {}

            self._last_button_id = -1

            vjoy_id = self.action_data.vjoy_id
            input_type = self._get_selector_input_type()
            dev = self.action_data.vjoy_map[vjoy_id]
            count = dev.button_count
            grid = QtWidgets.QGridLayout(self.button_grid_widget)
            grid.setSpacing(2)
            self.remap_type_layout = grid

            max_col = 16
            col = 0
            row = 0

            vjoy_id = dev.vjoy_id  # use joystick id as vjoy_id is -1 if disconnected
            input_type = self.action_data.input_type
            css = gremlin.ui.ui_common.Color.cssButtonState()

            for id in range(1, count + 1):
                # container for the vertical box

                if self._use_radio:
                    v_cont = QtWidgets.QWidget()
                    # v_cont.setFixedWidth(32)
                    v_box = QtWidgets.QVBoxLayout(v_cont)
                    v_box.setContentsMargins(0, 0, 0, 5)
                    v_box.setAlignment(QtCore.Qt.AlignCenter)

                    # line 1
                    h_cont = QtWidgets.QWidget()
                    h_cont.setFixedWidth(36)
                    h_box = QtWidgets.QHBoxLayout(h_cont)
                    h_box.setContentsMargins(0, 0, 0, 0)
                    h_box.setAlignment(QtCore.Qt.AlignCenter)
                    cb = gremlin.ui.ui_common.QDataRadioButton()

                    self.button_group.addButton(cb)
                    self.button_group.setId(cb, id)
                    cb.data = id  # data has the button id

                    name = str(id)
                    h_box.addWidget(cb)
                    v_box.addWidget(h_cont)

                    # line 2
                    line2_cont = gremlin.ui.ui_common.GridClickWidget(vjoy_id, input_type, id)
                    line2_cont.setFixedWidth(36)
                    h_box = QtWidgets.QHBoxLayout(line2_cont)
                    h_box.setContentsMargins(0, 0, 0, 0)
                    h_box.setSpacing(0)

                    icon_lbl = QtWidgets.QLabel()

                    lbl = QtWidgets.QLabel(name)
                    lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

                    self.icon_map[id] = icon_lbl

                    h_box.addWidget(icon_lbl)
                    h_box.addWidget(lbl)
                    v_box.addWidget(line2_cont)

                    line2_cont.clicked.connect(self._grid_button_clicked)

                    grid.addWidget(v_cont, row, col)

                else:
                    # use used push button
                    widget = gremlin.ui.ui_common.QUsedPushButton(
                        str(id), id, used=False, marker=False, callback=self._button_clicked, checkable=True, checked=self.action_data.input_id == id
                    )

                    widget.setStyleSheet(css)  # apply the button state CSS
                    container = gremlin.ui.ui_common.getVContainer(widget, widget_only=True)
                    container.setFixedSize(42, 42)
                    grid.addWidget(container, row, col)
                    self._grid_widgets[id] = widget
                    self.button_group.addButton(widget)

                col += 1
                if col == max_col:
                    row += 1
                    col = 0

            # align grid left
            grid.addWidget(QtWidgets.QWidget(), 0, max_col)
            grid.setColumnStretch(max_col, 2)

        self.button_grid_stack_widget.addWidget(grid_container_widget)  # index 1
        self.main_layout.addWidget(self.button_grid_stack_widget)

    @QtCore.Slot()
    def _button_clicked(self, btn):
        """called when the button is clicked"""
        button_id = btn.data
        vjoy_id = self.action_data.vjoy_id
        self.select_button(vjoy_id, button_id)

    @QtCore.Slot(bool)
    def _grid_visible_cb(self, visible):
        _el = gremlin.event_handler.EventListener()
        self.action_data.grid_visible = visible
        self._update_ui()

    def _grid_visible_changed(self, visible):
        gremlin.util.InvokeUiMethod(self._grid_visible_changed_ui, visible)  # ensure on UI thread

    def _grid_visible_changed_ui(self, visible):
        """global grid visible change event"""
        if not Shiboken.isValid(self):
            return

        with QtCore.QSignalBlocker(self.grid_visible_widget):
            self.grid_visible_widget.setChecked(visible)

        self._populate_grid()

    @QtCore.Slot()
    def _grid_button_clicked(self):
        sender = self.sender()
        vjoy_id = sender.vjoy_id
        input_type = sender.input_type
        vjoy_input_id = sender.vjoy_input_id

        popup = GridPopupWindow(vjoy_id, input_type, vjoy_input_id)
        popup.exec()

    def select_button(self, vjoy_id, button_id, emit=False):
        """selects a button"""

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_vjoy and config.verbose_mode_extra

        el = gremlin.event_handler.EventListener()
        if self._last_button_id != -1 and self._last_button_id != button_id:
            # clear the old button if it was previously selected

            if verbose:
                syslog.info(f"VJOYREMAP: send button clear {vjoy_id} {self._last_button_id} {self.action_data.id}")
            el.set_vjoy_button_usage.emit(vjoy_id, self._last_button_id, False, self.action_data.id)

        if self._last_button_id == button_id:
            # already selected
            return

        # set the new
        self._last_button_id = button_id
        self.action_data.set_input_id(button_id)

        # update the selector
        with QtCore.QSignalBlocker(self.cb_vjoy_output_selector):
            self.cb_vjoy_output_selector.setCurrentIndex(button_id - 1)

        # set the usage state for this button
        if verbose:
            syslog.info(f"VJOYREMAP: send button select {vjoy_id} {button_id} {self.action_data.id}")
        el.set_vjoy_button_usage.emit(vjoy_id, button_id, True, self.action_data.id)

        # update the UI when a state change occurs
        if emit:
            self.notify_device_changed()

    def _set_grid_state(self, button_id: int, state: bool):
        # update the grid
        if button_id in self._grid_widgets:
            used_pixmap = load_pixmap("used.png")
            unused_pixmap = load_pixmap("unused.png")
            cb = self._grid_widgets[button_id]
            with QtCore.QSignalBlocker(cb):
                cb.setChecked(state)
            lbl = self.icon_map[button_id]
            lbl.setPixmap(used_pixmap if state else unused_pixmap)

    def _select_changed(self, rb):
        # called when a button is toggled
        vjoy_id = self.action_data.vjoy_id
        button_id = self.button_group.checkedId()
        self.select_button(vjoy_id, button_id)

    def _populate_ui(self):
        """Populates the UI components."""
        # Get the appropriate vjoy device identifier
        vjoy_dev_id = 0

        # log_sys(f"populate vjoy data for action id: {self.action_data.action_id}  action mode: {self.action_data.action_mode}  vjoy: {self.action_data.vjoy_id}")
        if self.action_data.vjoy_id not in [0, None]:
            vjoy_dev_id = self.action_data.vjoy_id

        # Get the input type which can change depending on the container used
        input_type = self.action_data.input_type

        if self.action_data.parent.tag == "hat_buttons":
            input_type = InputType.JoystickButton

        # Handle obscure bug which causes the action_data to contain no
        # input_type information
        if input_type is None:
            input_type = InputType.JoystickButton
            syslog.warning("None as input type encountered")

        # If no valid input item is selected get the next unused one
        if self.action_data.vjoy_input_id in [0, None]:
            free_inputs = self._get_profile_root().list_unused_vjoy_inputs()

            input_name = self.type_to_name_map[input_type].lower()
            input_type = self.name_to_type_map[input_name.capitalize()]
            if vjoy_dev_id == 0:
                vjoy_dev_id = sorted(free_inputs.keys())[0]
            input_list = free_inputs[vjoy_dev_id][input_name]
            # If we have an unused item use it, otherwise use the first one
            if len(input_list) > 0:
                _vjoy_input_id = input_list[0]
            else:
                _vjoy_input_id = 1
        # If a valid input item is present use it
        else:
            _vjoy_input_id = self.action_data.vjoy_input_id

        is_button_mode = False

        try:
            index = self.cb_action_list.findData(self.action_data.action_mode)
            if index == -1:
                # log_sys_warn(f"Mode not found in drop down: {self.action_data.action_mode.name} - resetting to default mode")
                self.action_data.action_mode = self.cb_action_list.itemData(0)
                index = 0
            else:
                self.cb_action_list.setCurrentIndex(index)

            is_axis = self._is_axis
            if is_axis and self.action_data.action_mode == VjoyAction.VJoyAxis:
                with QtCore.QSignalBlocker(self.reverse_checkbox):
                    self.reverse_checkbox.setChecked(self.action_data.reverse)

                with QtCore.QSignalBlocker(self.absolute_checkbox):
                    with QtCore.QSignalBlocker(self.relative_checkbox):
                        if self.action_data.axis_mode == "absolute":
                            self.absolute_checkbox.setChecked(True)
                        else:
                            self.relative_checkbox.setChecked(True)

                with QtCore.QSignalBlocker(self.relative_scaling_widget):
                    self.relative_scaling_widget.setValue(self.action_data.axis_scaling)

            elif self.action_data.input_type in VJoyRemapWidget.input_type_buttons:
                is_button_mode = True

            if self.action_data.action_mode == VjoyAction.VJoyAxisToButton:
                is_button_mode = True
                with QtCore.QSignalBlocker(self.sb_button_range_low):
                    self.sb_button_range_low.setValue(self.action_data.button_range_min)
                with QtCore.QSignalBlocker(self.sb_button_range_high):
                    self.sb_button_range_high.setValue(self.action_data.button_range_max)

                with QtCore.QSignalBlocker(self.button_to_axis_value_widget):
                    self.button_to_axis_value_widget.setValue(self.action_data.target_value)

            if is_button_mode:
                # self.pulse_widget.setValue(self.action_data.pulse_delay)
                self.pulse_duration_widget.setValue(self.action_data.pulse_delay)

                with QtCore.QSignalBlocker(self.sb_button_range_low):
                    self.sb_button_range_low.setValue(self.action_data.button_range_min)

                with QtCore.QSignalBlocker(self.sb_button_range_high):
                    self.sb_button_range_high.setValue(self.action_data.button_range_max)

                # with QtCore.QSignalBlocker(self.chkb_exec_on_release):
                #     self.chkb_exec_on_release.setChecked(self.action_data.exec_on_release)

                with QtCore.QSignalBlocker(self.chkb_ignore_release):
                    self.chkb_ignore_release.setChecked(self.action_data.ignore_release)

                with QtCore.QSignalBlocker(self.chkb_paired):
                    self.chkb_paired.setChecked(self.action_data.paired)

            # update based on current mode

            self._populate_grid()
            self._update_vjoy_device_input_list()

            # if is_button_mode:
            #     self.select_button(vjoy_dev_id, vjoy_input_id, emit = False)

            self._update_ui()

        except gremlin.error.GremlinError as err:
            util.display_error(
                "A needed vJoy device is not accessible:\n" + "Default values have been set for the input, but they are not what has been specified."
            )
            syslog.error(f"{err}\n{traceback.format_exc()}")

        except Exception as err:
            syslog.error(f"{err}\n{traceback.format_exc()}")

    @QtCore.Slot(bool)
    def _axis_reverse_changed(self, checked: bool):
        self.action_data.reverse = checked

    @QtCore.Slot()
    def _axis_mode_changed(self):
        self.action_data.axis_mode = "absolute" if self.absolute_checkbox.isChecked() else "relative"
        self._update_ui()

    @QtCore.Slot()
    def _axis_scaling_changed(self):
        self.action_data.axis_scaling = self.relative_scaling_widget.value()

    @QtCore.Slot()
    def _axis_range_low_changed(self):
        self.action_data.output_range_min = self.sb_axis_range_low_widget.value()
        self._update_range_text()

    @QtCore.Slot(bool)
    def _axis_start_value_enabled(self, checked: bool):
        self.action_data.axis_start_value_enabled = checked
        self._update_ui()

    def _sync_on_start_changed(self, mode):
        self.action_data.sync_mode = mode

    @QtCore.Slot()
    def _axis_range_high_changed(self):
        self.action_data.output_range_max = self.sb_axis_range_high_widget.value()
        self._update_range_text()

    @QtCore.Slot()
    def _axis_start_value_changed(self):
        self.action_data.axis_start_value = self.sb_start_value.value()

    @QtCore.Slot()
    def _button_range_low_changed(self):
        self.action_data.button_range_min = self.sb_button_range_low.value()

    @QtCore.Slot()
    def _button_range_high_changed(self):
        self.action_data.button_range_max = self.sb_button_range_high.value()

    @QtCore.Slot()
    def _button_to_axis_value_changed(self):
        self.action_data.target_value = self.button_to_axis_value_widget.value()

    @QtCore.Slot()
    def _b_range_reset_clicked(self, value):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(1.0)

    @QtCore.Slot()
    def _b_range_half_clicked(self, value):
        self.sb_button_range_low.setValue(-0.5)
        self.sb_button_range_high.setValue(0.5)

    @QtCore.Slot()
    def _b_range_lhalf_clicked(self, value):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(0.0)

    @QtCore.Slot()
    def _b_range_hhalf_clicked(self, value):
        self.sb_button_range_low.setValue(0.0)
        self.sb_button_range_high.setValue(1.0)

    @QtCore.Slot()
    def _b_range_bot_clicked(self):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(-0.75)

    @QtCore.Slot()
    def _b_range_top_clicked(self):
        self.sb_button_range_low.setValue(0.75)
        self.sb_button_range_high.setValue(1.0)

    @QtCore.Slot()
    def _b_min_start_value_clicked(self):
        self.sb_start_value.setValue(-1.0)

    @QtCore.Slot()
    def _b_center_start_value_clicked(self):
        self.sb_start_value.setValue(0.0)

    @QtCore.Slot()
    def _b_max_start_value_clicked(self):
        self.sb_start_value.setValue(1.0)

    @QtCore.Slot(bool)
    def _ignore_release_changed(self, checked: bool):
        self.action_data.ignore_release = checked

    @QtCore.Slot(bool)
    def _paired_changed(self, checked: bool):
        self.action_data.paired = checked  # self.chkb_paired.isChecked()

    @QtCore.Slot(bool)
    def _autorelease_changed(self, checked: bool):
        self.action_data.auto_release = checked

    def _populate_grid(self):
        if not self.action_data.grid_visible:
            # nothing to do
            return
        gremlin.util.InvokeUiMethod(self._populate_grid_ui)

    def _populate_grid_ui(self):
        """updates the usage grid based on current VJOY mappings"""

        if self.button_group is None:
            # create a grid widget at widget position 1
            self._create_input_grid()

        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            syslog.info(f"populate grid {self.action_data.id}")

        if self._use_radio:
            used_pixmap = load_pixmap("used.png")
            unused_pixmap = load_pixmap("unused.png")
            self._grid_widgets = {}
            vjoy_id = self.action_data.vjoy_id

            used_list = self.usage_state.used_button_list(vjoy_id)

            for cb in self.button_group.buttons():
                button_id = self.button_group.id(cb)
                self._grid_widgets[button_id] = cb
                used = button_id in used_list

                if used and button_id == self.action_data.vjoy_input_id:
                    # update OURS only for the CB
                    with QtCore.QSignalBlocker(cb):
                        cb.setChecked(True)

                lbl = self.icon_map[button_id]
                lbl.setPixmap(used_pixmap if used else unused_pixmap)
        else:
            used_list = self.usage_state.used_button_list(self.action_data.vjoy_id)

            for button_id, widget in self._grid_widgets.items():
                used = button_id in used_list
                widget.setMarker(used)  # used somewhere
                used = button_id == self.action_data.vjoy_input_id
                widget.setUsed(used)  # local
                widget.setChecked(used)  # update the checkbox state


class VJoyRemapFunctor(gremlin.base_profile.AbstractFunctor):
    """Executes a remap action when called."""

    def findMainWindow(self):
        # Global function to find the (open) QMainWindow in application
        app = QtWidgets.QApplication.instance()
        for widget in app.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMainWindow):
                return widget
        return None

    def __init__(self, action_data: VjoyRemap, parent=None):  # noqa: F821
        super().__init__(action_data, parent)
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_vjoy or config.verbose_mode_joystick
        self.verbose_extra = self.verbose and config.verbose_mode_extra
        self.vjoy_id = action_data.vjoy_id
        self.vjoy_input_id = action_data.vjoy_input_id
        self.input_type = action_data.get_input_type()
        self.axis_scaling = action_data.axis_scaling
        self.action_mode = action_data.action_mode
        self.pulse_delay = action_data.pulse_delay
        self.start_pressed = action_data.button_start_value
        self.target_value = action_data.target_value
        self.last_value = 0  # axis value
        self.target_is_relative = action_data.target_is_relative
        self.target_value_valid = action_data.target_value_valid
        self.step_index = action_data.target_step_start_index
        self.step_direction = 1.0  # assume going up for linear step mode
        self.synced = False  # true if synchronized, resets on profile start

        v1 = action_data.button_range_min
        v2 = action_data.button_range_max
        self._latched_container_condition_node = None
        self._latched_action_condition_node = None
        self._pid = None
        self._velocity = 0.01
        self._acceleration = 2.0
        self._start_time = None

        self.repeat_interval = 0  # computed repeat interval

        self.usage_data = gremlin.joystick_handling.VJoyUsageState()

        if v1 > v2:
            # swap range so v1 < v2
            v1, v2 = v2, v1
        self.range_low = v1
        self.range_high = v2

        self.exec_on_release = action_data.exec_on_release
        self.paired = action_data.paired

        self.needs_auto_release = self._check_for_auto_release(action_data)
        if self.action_data.get_input_type() in (
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.Midi,
            InputType.OpenSoundControl,
        ):
            self.action_data.auto_release = self.action_data.auto_release or self.action_data.auto_release
        self.thread_running = False
        self.should_stop_thread = False
        self.thread_last_update = time.time()
        self.thread = None
        self.axis_delta_value = 0.0
        self.axis_value = 0.0
        self.axis_start_value = action_data.axis_start_value
        self.curve_actions = None  # list of curve actions that apply to our input

        self.remote_client: gremlin.remote.RemoteClient = gremlin.remote.remote_client
        self.hat_position = (0, 0)
        self.pressed_hat_buttons = {}
        self.in_range = False  # true when in axis to button mode and the axis was in range
        self.lock = threading.Lock()

        self.pulse_worker_map = {}  # map of (device_id, input_id) to pulse worker object
        self._relative_pulse_worker = None  # pulse worker for relative mode
        self.client_list = [0]  # send to all clients by default

    def _step_runner(self, tick: float, start: float, target: float, offset: float):
        value = start
        while self._step_is_running:
            value += offset
            if offset < 0 and value <= target:
                break
            elif offset > 0 and value >= target:
                break
            self._set_axis(self.vjoy_id, self.vjoy_input_id, value)
            time_stop = time.time() + tick
            while self._step_is_running and time.time() < time_stop:
                time.sleep(0)

        self._step_is_running = False

    def getCurveActions(self):
        """finds curve action siblings to this remap action"""
        actions = []
        nodes = []
        for node in self.getSiblings():
            if gremlin.input_item._is_curve_tag(node.action.tag):
                nodes.append(node)

        # sort the list in reverse priority order (highest prority runs first)
        if nodes:
            nodes.sort(key=lambda x: x.priority)
            nodes.reverse()
            for node in nodes:
                action = node.action
                actions.append(action)
        return actions

    def getCurveData(self, event, value):
        """returns active curve data that applies to the container through included response curve actions"""
        actions = self.getCurveActions()
        curves = []
        if actions:
            for action in actions:
                if action.curve_data:
                    # see if the curve should apply
                    if event is None or self.shouldExecute(event, value, action):
                        curves.append(action.curve_data)

        # add self
        if self.action_data.curve_data is not None:
            curves.append(self.action_data.curve_data)

        return curves

    def _convert_condition(self, condition):
        """converts a base condition to an action condition"""
        if isinstance(condition, gremlin.input_item.BaseKeyboardCondition):
            return gremlin.actions.KeyboardCondition(condition.scan_code, condition.is_extended, condition.comparison)

        elif isinstance(condition, gremlin.input_item.BaseJoystickCondition):
            return gremlin.actions.JoystickCondition(condition)

        elif isinstance(condition, gremlin.input_item.BaseVJoyCondition):
            return gremlin.actions.VJoyCondition(condition)

        elif isinstance(condition, gremlin.input_item.BaseInputActionCondition):
            return gremlin.actions.InputActionCondition(condition.comparison)

        assert False, f"Invalid base condition to convert: {type(condition).__name__}"

    def _create_activation_condition(self, activation_condition, target):
        """Creates activation condition objects base on the given data.

        :param activation_condition data about activation condition to be
            used in order to generate executable nodes
        """
        conditions = []
        for condition in activation_condition.conditions:
            if isinstance(condition, gremlin.input_item.BaseActivationCondition):
                for sub_condition in condition.conditions:
                    conditions.append(self._convert_condition(sub_condition))
            else:
                conditions.append(self._convert_condition(condition))

        return gremlin.input_item.BaseActivationCondition(conditions, activation_condition.rule, target)

    def shouldExecute(self, event, value, action) -> bool:
        """determines if the given action should execute or not: returns True if the condition is satisfied"""

        activation_condition: gremlin.input_item.BaseActivationCondition = action.activation_condition
        if activation_condition is None or not activation_condition.conditions:
            # no condition
            return True

        functor = self._create_activation_condition(activation_condition, self.action_data)

        return gremlin.input_item.BaseActivationCondition.rule_function[functor._rule]([partial(c, event, value) for c in functor._conditions])

    def applyContainerCurves(self, value: float):
        """applies the container curve data to the curve"""
        for action in self.curve_actions:
            if action.curve_data:
                value = action.curve_data.curve_value(value)

        return value

    @property
    def reverse(self):
        # axis reversed state
        return self.usage_data.is_inverted(self.vjoy_id, self.vjoy_input_id)

    def toggle_reverse(self):
        # toggles reverse mode for the axis
        inverted = self.usage_data.is_inverted(self.vjoy_id, self.vjoy_input_id)
        self.usage_data.set_inverted(self.vjoy_id, self.vjoy_input_id, not inverted)
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            syslog.info(f"toggle reverse: {self.vjoy_id} {self.vjoy_input_id} new state: {self.reverse}")

    def setReverse(self, value: bool):
        """sets the axis' reverse state"""
        self.usage_data.set_inverted(self.vjoy_id, self.vjoy_input_id, value)

    def latch_extra_inputs(self, container_condition_node=None, action_condition_node=None):
        """returns the list of extra devices to latch to this functor (device_guid, input_type, input_id)

        :param container_condition_node: the execution graph condition node applied to the container, if any
        :param action_condition_node: the execution graph condition node applied to the action, if any

        """
        self._latched_container_condition_node = container_condition_node
        self._latched_action_condition_node = action_condition_node
        if self.action_data.action_mode == VjoyAction.VJoyMergeAxis:
            latched = []
            verbose = gremlin.config.Configuration().verbose_mode_merge
            for data in self.action_data._merge_data:
                latched.append((data.device_guid, InputType.JoystickAxis, data.input_id))
                device = gremlin.joystick_handling.getDevice(data.device_guid)
                if verbose:
                    syslog.info(f"MERGE: latched [{device.name}] axis: {data.input_id}  {device.get_axis_name(data.input_id)}")

            return latched
            # return [(self.action_data.merge_device_guid, self.action_data.merge_input_type, self.action_data.merge_input_id)]
        if self.action_data.action_mode == VjoyAction.VJoySetAxisStepped:
            return [
                (
                    self.action_data.stepped_device_guid,
                    self.action_data.stepped_input_type,
                    self.action_data.stepped_input_id,
                )
            ]
        return []

    def profile_start(self):
        """occurs on profile start"""
        # setup initial state

        is_local, is_remote = self.action_data.sendFlags()
        is_paired = gremlin.remote.remote_control.paired
        config = gremlin.config.Configuration()
        verbose = self.verbose or config.verbose_mode_outputs or config.verbose_mode_vjoy
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        raw_input_type = self.action_data.hardware_raw_input_type
        self.pressed_hat_buttons = {}
        self.synced = False  # indicate not synchronized

        # update the target client list
        self.client_list = self.action_data.remote_config.getClientList()

        # get the current mode
        mode = gremlin.shared_state.runtime_mode
        # get the profile start mode
        start_mode = gremlin.shared_state.current_profile.get_start_mode()

        # vjoy startup config
        vs = gremlin.joystick_handling.VjoyStart()

        if self.input_type in VJoyRemapWidget.input_type_buttons:
            # set start button state
            if self.action_data.button_start_value is not None and gremlin.joystick_handling.is_vjoy_connected(self.action_data.vjoy_id):
                if verbose:
                    syslog.info(
                        f"VJOY REMAP: startup vjoy: [{self.action_data.vjoy_id}] button [{self.action_data.vjoy_button_id}] set to {'pressed' if self.action_data.button_start_value else 'released'}"
                    )
                joystick_handling.VJoyProxy()[self.action_data.vjoy_id].button(self.action_data.vjoy_button_id).is_pressed = self.action_data.button_start_value
        if self.input_type == InputType.JoystickAxis:
            # send initial axis values to the output

            self.usage_data.set_range(self.vjoy_id, self.vjoy_input_id, self.range_low, self.range_high)
            # print(f"Axis start value: vjoy: {self.vjoy_id} axis: {self.vjoy_input_id}  value: {self.axis_start_value}")

            match self.action_mode:
                case VjoyAction.VJoyAxis:
                    # straight axis

                    input_id = self.action_data.hardware_input_id

                    # straight axis
                    raw_input_type = self.action_data.hardware_raw_input_type

                    astate = gremlin.event_handler.AxisState()
                    values = astate.getAxisValues(
                        self.action_data.hardware_device_guid,
                        self.action_data.hardware_input_id,
                    )
                    if not values:
                        actual_value = self.action_data.get_raw_axis_value()
                    else:
                        actual_value = values.actual

                    # apply any curves
                    curves = self.getCurveData(None, actual_value)
                    filtered_value = self.action_data.get_filtered_axis_value(actual_value, curves=curves)
                    ranged_value = self.action_data.get_ranged_axis_value(filtered_value)

                    # output value
                    value = ranged_value

                    trigger = False

                    if verbose:
                        device = gremlin.joystick_handling.getDevice(self.hardware_device_guid)
                        assert device is not None, f"Unable to find device for {str(self.hardware_device_guid)}"
                        vjoy_stub = f"sync mode: [{self.action_data.sync_mode.name}] set start value for vjoy axis: {self.vjoy_input_id}"
                        device_stub = f"{device.name} input: {self.action_data.input_type.name} input id: {input_id}"

                    match self.action_data.sync_mode:
                        case SyncMode.Default:
                            trigger = True
                            if verbose:
                                syslog.info(f"{vjoy_stub} default : {self.action_data.state.default_value}")
                            value = self.action_data.axis_start_value
                        case SyncMode.Input:
                            trigger = True
                            if verbose:
                                syslog.info(f"VJOY REMAP SYNC: {device_stub} {vjoy_stub} input : {value:0.3f}")
                            value = value
                        case SyncMode.LastOrInput:
                            trigger = True
                            last = self.action_data.axis_last_value
                            if last is None:
                                if verbose:
                                    syslog.info(f"VJOY REMAP SYNC: {vjoy_stub} last or input : use input value : {value:0.3f}")
                            else:
                                if verbose:
                                    syslog.info(f"VJOY REMAP SYNC: {vjoy_stub} last or input : use last value : {last:0.3f}")
                                value = last
                        case SyncMode.LastOrDefault:
                            pass  # do nothing

                        case SyncMode.Ignore:
                            pass  # do nothing

                    if trigger and start_mode == mode:
                        vs.setStartValue(self.vjoy_id, self.vjoy_input_id, value)
                        self.action_data.axis_last_value = value

                    if raw_input_type == InputType.OpenSoundControl and self.action_data.axis_start_value_enabled:
                        # sync OSC with the start value
                        message = input_id.message
                        osc_value = gremlin.util.scale_to_range(value, target_min=0, target_max=1)
                        gremlin.ui.osc_device.osc_client.sendData(message, osc_value)

                case VjoyAction.VJoyAxisToButton:
                    value = joystick_handling.get_curved_axis(device_guid, input_id)
                    action_value = gremlin.actions.Value(value)
                    event = gremlin.event_handler.Event(
                        self.input_type,
                        device_guid=device_guid,
                        identifier=input_id,
                        is_axis=True,
                        value=value,
                        raw_value=value,
                        curved_value=value,
                    )
                    self.action_data.axis_last_value = value
                    self.process_event(event, action_value)

        elif self.input_type == InputType.JoystickHat and self.action_mode == VjoyAction.VJoyHatToButton:
            value = joystick_handling.get_hat(device_guid, input_id)
            if value in vjoy.vjoy.Hat.to_continuous_position:
                self.hat_position = vjoy.vjoy.Hat.to_continuous_position[value]
            else:
                self.hat_position = (0, 0)
            self.pressed_hat_buttons = {}
            event = gremlin.event_handler.Event(
                self.input_type,
                device_guid=device_guid,
                identifier=input_id,
                raw_value=self.hat_position,
                value=self.hat_position,
            )

            self.process_event(event, self.hat_position)

        elif self.input_type == InputType.JoystickButton:
            # button presses
            if verbose:
                vjoy_stub = f"VJOY REMAP: sync mode: [{self.action_data.sync_mode.name}] set button start value:"

            # assume we are setting the start state
            trigger = True
            trigger_reverse = False
            trigger_setValue = False

            # determine pressed start state
            is_pressed = False

            match raw_input_type:
                case InputType.JoystickButton:
                    # input is momentary
                    match self.action_mode:
                        case VjoyAction.VJoyButton:
                            is_pressed = joystick_handling.get_button(device_guid, input_id)
                        case VjoyAction.VJoyButtonInverted:
                            is_pressed = not joystick_handling.get_button(device_guid, input_id)

                        case VjoyAction.VJoyButton.VJoyButtonPress:
                            is_pressed = True
                        case VjoyAction.VJoyButton.VJoyButtonRelease:
                            is_pressed = False
                            trigger = False
                        case VjoyAction.VJoyInvertAxis:
                            is_pressed = joystick_handling.get_button(device_guid, input_id)
                            trigger_reverse = self.action_data.sync_mode in (
                                SyncMode.Input,
                                SyncMode.LastOrInput,
                                SyncMode.LastOrDefault,
                            )
                        case VjoyAction.VJoySetAxis:
                            is_pressed = joystick_handling.get_button(device_guid, input_id)
                            trigger_setValue = is_pressed and self.action_data.sync_mode in (
                                SyncMode.Input,
                                SyncMode.LastOrInput,
                                SyncMode.LastOrDefault,
                            )
                        case VjoyAction.VJoyHat | VjoyAction.VJoyHatPress | VjoyAction.VJoyHatPulse:
                            # hat
                            is_pressed = joystick_handling.get_button(device_guid, input_id)

                case InputType.OpenSoundControl:
                    message = self.action_data.input_item.message_key
                    match self.action_mode:
                        case VjoyAction.VJoyButton:
                            is_pressed = gremlin.ui.osc_device.osc_client.getData(message)
                        case VjoyAction.VJoyButton.VJoyButtonPress:
                            is_pressed = True
                        case VjoyAction.VJoyButton.VJoyButtonRelease:
                            trigger = True
                            is_pressed = False
                case InputType.Midi:
                    message = self.action_data.input_item.message_key
                    match self.action_mode:
                        case VjoyAction.VJoyButton:
                            is_pressed = gremlin.ui.midi_device.midi_client.getData(message)
                        case VjoyAction.VJoyButton.VJoyButtonPress:
                            is_pressed = True
                        case VjoyAction.VJoyButton.VJoyButtonRelease:
                            is_pressed = False

            match self.action_data.sync_mode:
                case SyncMode.Default:
                    value = self.action_data.button_start_value
                    if verbose:
                        syslog.info(f"{vjoy_stub} default : {value}")

                case SyncMode.Input:
                    if verbose:
                        syslog.info(f"{vjoy_stub} input : {is_pressed}")
                    value = is_pressed

                case SyncMode.LastOrInput:
                    last = self.action_data.button_last_value
                    if last is None:
                        if verbose:
                            syslog.info(f"{vjoy_stub} last or input : use input value : {is_pressed}")
                        value = is_pressed
                    else:
                        if verbose:
                            syslog.info(f"{vjoy_stub} last or input : use last value : {last:0.3f}")
                        value = last
                case SyncMode.LastOrDefault:
                    last = self.action_data.button_last_value
                    if last is None:
                        value = self.action_data.button_start_value
                        if verbose:
                            syslog.info(f"{vjoy_stub} last or input : use default value : {value}")

                    else:
                        if verbose:
                            syslog.info(f"{vjoy_stub} last or default: use last value : {last}")
                        value = last
                case SyncMode.Ignore:
                    trigger = False  # do nothing

            if trigger:
                # trigger the button output
                if value is None:
                    value = False  # for inputs like OSC

                if self.action_data.action_mode in (
                    VjoyAction.VJoyHat,
                    VjoyAction.VJoyHatPress,
                    VjoyAction.VJoyHatPulse,
                ):
                    # hat output
                    position = self.action_data.vjoy_hat_position if is_pressed else self.action_data.vjoy_hat_return_position
                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                            joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = position
                    if is_remote:
                        self.remote_client.send_hat(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            position,
                            client_list=self.client_list,
                            force_remote=is_paired,
                        )

                else:
                    # button output

                    vs.setStartState(self.vjoy_id, self.vjoy_input_id, value)
                    self.action_data.button_last_value = value
                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                            joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = value
                    if is_remote or is_paired:
                        self.remote_client.send_button(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            value,
                            client_list=self.client_list,
                            force_remote=is_paired,
                        )

            if trigger_reverse:
                # trigger the reverse axis action
                self.setReverse(value)

            if trigger_setValue:
                # trigger the set axis action
                self._set_axis_value()

        if self.action_mode == VjoyAction.VJoySetAxisStepped:
            # initial stepped axis value

            if self.action_data._target_step_linear_mode:
                # linear mode - read the intial output axis value
                self.last_value = self._get_axis(self.vjoy_id, self.vjoy_input_id)

            else:
                if start_mode == mode:
                    self.step_index = self.action_data.target_step_start_index
                    value = self.action_data.target_step_list[self.step_index]
                    vs.setStartValue(self.vjoy_id, self.vjoy_input_id, value)
                    self.action_data.axis_last_value = value

    def profile_stop(self):
        """called when profile stops"""

        # clear any pulse workers still active
        worker: gremlin.repeater.PulseWorker
        for worker in self.pulse_worker_map.values():
            worker.stop()
        self.pulse_worker_map.clear()
        if self._relative_pulse_worker:
            self._relative_pulse_worker.stop()

        if self.input_type in VJoyRemapWidget.input_type_buttons:
            # issue vjoy button releases if needed
            is_local, is_remote = self.action_data.sendFlags()
            is_paired = gremlin.remote.remote_control.paired
            action_mode = self.action_data.action_mode
            if action_mode in (
                VjoyAction.VJoyHat,
                VjoyAction.VJoyHatPress,
                VjoyAction.VJoyHatPulse,
            ):
                # hat modes
                position = (0, 0)  # return hat to center
                if is_local:
                    if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                        joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = position
                if is_remote:
                    self.remote_client.send_hat(
                        self.vjoy_id,
                        self.vjoy_input_id,
                        position,
                        client_list=self.client_list,
                        force_remote=is_paired,
                    )
            elif action_mode in (
                VjoyAction.VJoyButton,
                VjoyAction.VJoyButton.VJoyButtonPress,
                VjoyAction.VJoyButton.VJoyButtonRelease,
                VjoyAction.VJoyButtonInverted,
            ):
                # button modes
                is_pressed = False
                if is_local:
                    if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                        joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = is_pressed
                if is_remote or is_paired:
                    self.remote_client.send_button(
                        self.vjoy_id,
                        self.vjoy_input_id,
                        is_pressed,
                        client_list=self.client_list,
                        force_remote=is_paired,
                    )

    def _compute_value(self, value: float, direction: int) -> float:
        now = time.time()
        if self._start_time is None:
            t = 0
            self._start_time = now
            self._start_value = value
        else:
            t = now - self._start_time

        # equation of accelerated motion:
        # s = v*t + (a*t^2)/2
        v = self._velocity
        a = self._acceleration
        delta = (v * t) + (0.5 * a * (t**2))
        new_value = self._start_value + delta * direction
        return gremlin.util.clamp(new_value)

    def _pulse_on(self, data):
        """called when pulse is on"""
        device_id, input_type, input_id, position, is_local, is_remote, force_remote = data
        if self.verbose_extra:
            syslog.info(f"Pulse ON {device_id} button {input_id}")

        if self.action_data.action_mode == VjoyAction.VJoySetAxisStepped:
            # compute the next value

            last_value = self._get_axis(device_id, input_id)

            if self.action_data._target_step_linear_mode:
                # # PID mode
                # sp = 1.0 if self.step_direction > 0 else -1.0 # target set point
                # if not self._pid:
                #     # setup a pid that returns values between 0 and 2 for the full axis range
                #     kp = 0.1
                #     ki = 0.2
                #     kd = 0
                #     self._pid = gremlin.pid.PID(kp, ki, kd,
                #                                 setpointRamp=5.0,
                #                                 proportionnalOnMeasurement=True,
                #                                 outputLimits = (-1, 1))

                #     if self.verbose: syslog.info(f"STEPPED AXIS: linear PID setup: starting value: [{last_value:0.3f}]")

                # value = self._pid(sp, last_value)
                value = self._compute_value(last_value, self.step_direction)
                if self.verbose:
                    syslog.info(f"STEPPED AXIS: linear: direction: [{self.step_direction}] new value: [{value:0.3f}]")
            else:
                # normal pulsed stepping
                delta = self.action_data._target_step_delta
                value = max(-1.0, min(1.0, last_value + delta * self.step_direction))

                if self.verbose:
                    syslog.info(f"STEPPED AXIS: linear pulse: direction: [{self.step_direction}] delta: [{delta:0.3f}] new value: [{value:0.3f}]")
                self._set_axis(device_id, input_id, value)

        else:
            match input_type:
                case InputType.JoystickButton:
                    if self.verbose_extra:
                        syslog.info(f"pulse ON vjoy [{device_id}] button [{input_id}]")

                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(device_id):
                            joystick_handling.VJoyProxy()[device_id].button(input_id).is_pressed = True
                    if is_remote:
                        self.remote_client.send_button(
                            device_id,
                            input_id,
                            True,
                            client_list=self.client_list,
                            force_remote=force_remote,
                        )
                case InputType.JoystickHat:
                    if self.verbose_extra:
                        syslog.info(f"pulse ON vjoy [{device_id}] hat [{input_id}] position: [{position}]")
                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                            joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = position
                    if is_remote:
                        self.remote_client.send_hat(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            position,
                            client_list=self.client_list,
                            force_remote=force_remote,
                        )

    def _pulse_off(self, data):
        """called when pulse is off"""
        # if self.action_data._target_step_linear_mode:
        #     return # nothing to do if in PID mode

        device_id, input_type, input_id, position, is_local, is_remote, force_remote = data

        match input_type:
            case InputType.JoystickButton:
                if self.verbose_extra:
                    syslog.info(f"Pulse OFF vjoy [{device_id}] button {input_id}")
                if is_local:
                    if gremlin.joystick_handling.is_vjoy_connected(device_id):
                        joystick_handling.VJoyProxy()[device_id].button(input_id).is_pressed = False
                if is_remote:
                    self.remote_client.send_button(
                        device_id,
                        input_id,
                        False,
                        client_list=self.client_list,
                        force_remote=force_remote,
                    )

            case InputType.JoystickHat:
                position = self.action_data.vjoy_hat_return_position

                if self.verbose_extra:
                    syslog.info(f"pulse OFF vjoy [{device_id}] hat [{input_id}] position: [{position}]")
                if is_local:
                    if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                        joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = position
                if is_remote:
                    self.remote_client.send_hat(
                        self.vjoy_id,
                        self.vjoy_input_id,
                        position,
                        client_list=self.client_list,
                        force_remote=force_remote,
                    )

    def pulse_start(
        self,
        device_id: int,
        input_type: InputType,
        input_id: int,
        position: tuple = None,
        duration: float = 0,
        interval: float = 0,
        is_local: bool = True,
        is_remote: bool = False,
        force_remote: bool = False,
    ):
        """pulse setup"""
        verbose = self.verbose
        if verbose:
            syslog.info(
                f"Pulse START vjoy {device_id} input type: {input_type.name} input id {input_id} position: {position} duration: {duration:0.3f} interval: {interval:0.3f}"
            )
        key = (device_id, input_type, input_id, position)
        worker: gremlin.repeater.PulseWorker
        if key in self.pulse_worker_map:
            worker = self.pulse_worker_map[key]
            if worker.is_running:
                # worker already running - ignore pulse request
                if verbose:
                    syslog.info("\talready pulsing - ignored")
                return
        else:
            args = (
                device_id,
                input_type,
                input_id,
                position,
                is_local,
                is_remote,
                force_remote,
            )
            worker = gremlin.repeater.PulseWorker(duration, interval, self._pulse_on, self._pulse_off, data=args)
            self.pulse_worker_map[key] = worker

        if verbose:
            syslog.info("\activate")
        worker.start()

    def pulse_stop(
        self,
        device_id: int,
        input_type: InputType,
        input_id: int,
        position: tuple = None,
    ):
        """request a pulse abort"""
        if self.verbose:
            syslog.info(f"Pulse STOP {device_id} button {input_id}")
        key = (device_id, input_type, input_id, position)
        if key in self.pulse_worker_map:
            worker: gremlin.repeater.PulseWorker = self.pulse_worker_map[key]
            del self.pulse_worker_map[key]
            worker.stop()

    def _relative_pulse_on(self, data):
        vjoy_id, vjoy_input_id, is_local, is_remote = data
        if not gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
            return

        with self.lock:
            # value position is now between 0 and 1
            offset = self.direction * self.action_data.relative_value * self.scale_factor

            syslog.info(f"Tick: {offset:0.3f} scale: {self.scale_factor:0.3f}")

            # read the current output axis value
            value = joystick_handling.VJoyProxy()[self.vjoy_id].axis(self.vjoy_input_id).value

            # apply the offset
            value = gremlin.util.clamp(value + offset)
            if is_local:
                joystick_handling.VJoyProxy()[self.vjoy_id].axis(self.vjoy_input_id).value = value
            if is_remote:
                self.remote_client.send_relative_axis(
                    self.vjoy_id,
                    self.vjoy_input_id,
                    value,
                    client_list=self.client_list,
                )
            # remember the last value
            self.action_data.axis_last_value = value

    def _set_axis_value(self):
        """sets the axis value"""
        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
            verbose = self.verbose
            if self.action_data.target_use_last:
                # set the output to the current value, but wiggle it so the target app detects a change
                # this is to "reset" an axis to a known value if the target environment changed the input outside of the control data being setn
                # the wiggle value is a small offet to trigger the target game to cause it to retrigger - there has to be a change of the game would not pick it up
                offset = 0.01
                # read the current output value
                value = self.action_data.axis_last_value
                if value is None:
                    # read the last value
                    value = self._get_axis(self.vjoy_id, self.vjoy_input_id)
                    if verbose:
                        syslog.info(f"reading axis value: {value:0.3f}")
                else:
                    if verbose:
                        syslog.info(f"using last axis value: {value:0.3f}")

                wiggle_value = value - offset
                if wiggle_value < -1.0:
                    wiggle_value = value + offset

                self.target_value = value  # value to restore after wiggle

                if verbose:
                    syslog.info(f"VJOY: set last value [{self.vjoy_id}] axis  {self.vjoy_input_id} value: {value:0.3f} wiggle value: {wiggle_value:0.3f}")
                self._set_axis(self.vjoy_id, self.vjoy_input_id, wiggle_value)
                timer = threading.Timer(0.25, self._handle_set_axis_wiggle)
                timer.start()

                return True

            target_value_valid = self.target_value_valid or self.action_data.use_relative_value

            if target_value_valid:
                target_value = self.target_value

                if self.action_data.use_relative_value:
                    # read the current output axis value
                    value = joystick_handling.VJoyProxy()[self.vjoy_id].axis(self.vjoy_input_id).value
                    # apply the offset
                    value += target_value
                else:
                    value = target_value

                value = gremlin.util.clamp(value)
                if verbose:
                    syslog.info(f"VJOY: set device [{self.vjoy_id}] axis  {self.vjoy_input_id} value: {value:0.3f}")
                self._set_axis(self.vjoy_id, self.vjoy_input_id, value)

                # remember the last value
                self.action_data.axis_last_value = value
        return True

    # def smooth(self, value, reverse = False, power = 3):
    #     '''
    #         int smoothIt(int from, int to, int val, int power, int reverse) {
    #         float to2;
    #         to2 = to - from;
    #         int ret;
    #         if (reverse == 1) {
    #             ret = (pow((val - from) / to2 - 1, power) + 1) * to2 + from; //
    #             return ret;
    #         } else {
    #             ret = pow((val - from) / to2, power) * to2 + from; //
    #             return ret;
    #         }
    #         }

    #     '''
    #     v_end = 1.0
    #     v_start = 0.0
    #     power = 3
    #     if reverse:
    #         return (pow((value - v_start) / v_end - 1, power) + 1) * v_end + v_start
    #     return pow((value - v_start) / v_end, power) * v_end + v_start

    def process_event(self, event, action_value: gremlin.actions.Value, extra_data=None):
        """runs when a joystick event occurs like a button press or axis movement when a profile is running"""
        # if self.action_data.merged and event.is_axis:
        #     # merged axis data is handled by the internal hook - ignore
        #     return True
        if event.is_axis:
            # axis input
            verbose = self.verbose

            if self.action_data.action_mode == VjoyAction.VJoyMergeAxis:
                # make sure conditions are valid for latched input
                # the reason is conditions are only evaluated for the actual mapped input, not the latched inputs
                # therfore we need to evaluate the conditions for the latched input as well
                if event.device_guid != self.hardware_device_guid or event.identifier != self.hardware_input_id:
                    # event is for a latched input = run conditions if any are applied

                    # check for condition applied to container
                    if self._latched_container_condition_node:
                        node = self._latched_container_condition_node
                        result = node.execute(event, action_value, extra_data)
                        if not result:
                            return True  # condition failed but functor is ok

                    # check for condition applied to this action
                    if self._latched_action_condition_node:
                        node = self._latched_action_condition_node
                        result = node.execute(event, action_value, extra_data)
                        if not result:
                            return True  # condition failed but functor is ok

            if event.is_repeater:
                # use the repeater value
                value = event.value
            else:
                curves = None
                if event.curve_value is not None:
                    # curve data already applied, only apply our own curve if present
                    if self.action_data.curve_data:
                        curves = [self.action_data.curve_data]
                    value = event.curve_value
                    if verbose:
                        source = "input curve value"
                else:
                    # not using curve data, apply all applicable curves
                    curves = self.getCurveData(event, action_value)
                    if verbose:
                        source = "action value"
                    value = action_value.current

                if verbose:
                    curve_count = len(curves) if curves else 0

                # this handles axis merging and applies any curves and axis inversion
                filtered_value = self.action_data.get_filtered_axis_value(value, curves=curves)
                if filtered_value is None:
                    filtered_value = value

                ranged_value = self.action_data.get_ranged_axis_value(filtered_value)

                if ranged_value is None:
                    ranged_value = filtered_value

                if verbose:
                    syslog.info(
                        f"VjoyRemap: using input value source {source}: [{value:0.3f}] -> filtered [{filtered_value:0.3f}] -> range [{ranged_value:0.3f}] applied curves: {curve_count}"
                    )

            action_value = gremlin.actions.Value(value=ranged_value, raw=event.raw_value, is_pressed=event.is_pressed)
            event.curve_value = ranged_value

        return self._process_event(event, action_value, extra_data)

    def _process_event(
        self,
        event: gremlin.event_handler.Event,
        action_value: gremlin.actions.Value,
        extra_data,
    ):
        """runs when a joystick even occurs like a button press or axis movement when a profile is running"""
        is_local, is_remote = self.action_data.sendFlags()

        verbose = self.verbose
        # verbose = True
        verbose_extra = self.verbose_extra

        # syslog = logging.getLogger("system")
        if event.force_remote:
            # force remote mode on if specified in the event
            is_remote = True
            is_local = False

        force_remote = event.force_remote

        auto_complete = True  # assume the functor completes this pass

        self.action_data: VjoyRemap

        input_type = event.getInputType()
        result = True  # assume functor executes

        if event.is_axis:  # self.input_type == InputType.JoystickAxis:
            # axis response mode

            if verbose:
                syslog.info(
                    f"Value raw: {action_value.raw:0.3f}  current {action_value.current:0.3f}  Event raw: {event.raw_value:0.3f} value: {event.value:0.3f} curve: {event.curve_value:0.3f}"
                )

            axis_mode = self.action_data.axis_mode

            # read the value from the extra data if set
            if extra_data is not None and "value" in extra_data:
                value = extra_data["value"]
            else:
                # use curve value if any
                value = event.curve_value
                if value is None:
                    # use regular value if any
                    value = event.value

                if value is None:
                    return True

            if value is None or not isinstance(value, float):
                if verbose:
                    syslog.error(f"VJOYREMAP: invalid value {value} for axis")
                return

            # axis mode
            match self.action_mode:
                case VjoyAction.VJoyAxisToButton:
                    v1 = self.range_low
                    v2 = self.range_high
                    in_range = gremlin.util.valueInRange(value, v1, v2)
                    # syslog.info(f"axis: {value:0.3f}")
                    is_pressed = None
                    match self.action_data.button_mode:
                        case ButtonOutputMode.Hold:
                            if in_range:
                                if not self.in_range:
                                    # toggle ON
                                    self.in_range = True
                                    is_pressed = True
                                    if verbose:
                                        syslog.info(f"AXIS TO BUTTON: ON in range vjoy {self.vjoy_id} button {self.vjoy_input_id}")

                            else:
                                # not in range
                                if self.in_range:
                                    # toggle OFF
                                    if verbose:
                                        syslog.info(f"AXIS TO BUTTON: OFF out of range vjoy {self.vjoy_id} button {self.vjoy_input_id}")
                                    self.in_range = False
                                    is_pressed = False

                        case ButtonOutputMode.Pulse:
                            input_id = self.vjoy_input_id
                            device_id = self.vjoy_id
                            input_type = InputType.JoystickButton
                            position = None
                            if in_range:
                                if not self.in_range:
                                    self.in_range = True
                                    if verbose:
                                        syslog.info(f"VJOY: trigger start range pulse vjoy {device_id} hat {input_id}")
                                    repeat_interval = self.action_data.pulse_repeat_delay / 1000 if self.action_data.pulse_repeat else -1
                                    self.pulse_start(
                                        device_id,
                                        input_type,
                                        input_id,
                                        position,
                                        self.pulse_delay / 1000,
                                        repeat_interval,
                                        is_local,
                                        is_remote,
                                        force_remote,
                                    )
                                    auto_complete = False
                            else:
                                if self.in_range:
                                    self.in_range = False
                                    if verbose:
                                        syslog.info(f"VJOY: trigger stop range pulse vjoy {device_id} hat {input_id}")
                                    self.pulse_stop(device_id, input_type, input_id, position)
                            return True

                        case ButtonOutputMode.Press:
                            is_pressed = True

                        case ButtonOutputMode.Release:
                            is_pressed = False

                        case _:
                            # do nothing
                            return True

                    if is_pressed is not None:
                        if verbose:
                            syslog.info(f"VJOY: set device [{self.vjoy_id}] button {self.vjoy_input_id} pressed: {is_pressed}")
                        self.action_data.button_last_value = is_pressed
                        if is_local:
                            if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                                joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = is_pressed
                        if is_remote:
                            self.remote_client.send_button(
                                self.vjoy_id,
                                self.vjoy_input_id,
                                is_pressed,
                                client_list=self.client_list,
                            )

                case _:
                    if axis_mode == "absolute":
                        # apply any range function to the raw position

                        if verbose:
                            syslog.info(
                                f"AXIS ABSOLUTE: send vjoy {self.vjoy_id} axis {self.vjoy_input_id} range: [{self.range_low:0.3f},{self.range_high:0.3f}] scale: {self.axis_scaling:0.3f} value: {value:0.3f}"
                            )

                        if verbose:
                            syslog.info(f"VJOY: set device [{self.vjoy_id}] axis  {self.vjoy_input_id} value: {value:0.3f}")

                        self.action_data.axis_last_value = value
                        self._set_axis(self.vjoy_id, self.vjoy_input_id, value)

                        # remember the last value
                        self.action_data.axis_last_value = value

                    elif axis_mode == "relative":
                        # relative mode

                        if self.action_data.use_relative_value:
                            # input is an axis
                            scale_factor = event.value
                            if scale_factor < 0:
                                scale_factor = -scale_factor
                                direction = -1
                            else:
                                direction = +1
                            if not self._relative_pulse_worker:
                                self._relative_pulse_worker = gremlin.repeater.PulseWorker(
                                    0,
                                    self.action_data.relative_pulse_delay / 1000,
                                    on_callback=self._relative_pulse_on,
                                    data=(
                                        self.vjoy_id,
                                        self.vjoy_input_id,
                                        is_local,
                                        is_remote,
                                    ),
                                )

                        else:
                            self.scale_factor = 1.0

                        if self.action_data.reverse:
                            direction = -direction

                        # update tracking values

                        # self.lock.acquire()
                        self.scale_factor = scale_factor
                        self.direction = direction
                        # self.lock.release()

                        if verbose_extra:
                            syslog.info(f"Tick value: {direction * scale_factor: 0.3f}")

                        if scale_factor >= 0.02:
                            if not self._relative_pulse_worker.is_running:
                                if verbose_extra:
                                    syslog.info("VJOY: Tick start")
                                self._relative_pulse_worker.start()  # start pulsing updates to the axis while deviated
                        else:
                            if verbose_extra:
                                syslog.info("VJOY: Tick stop")
                            self._relative_pulse_worker.stop()  # stop pulsing updates to the axis if not deviated

                        return True  # done

        elif self.action_mode == VjoyAction.VJoyHatToButton:
            if isinstance(action_value, tuple):
                position = action_value
            else:
                position = action_value.current

            pressed_positions = list(self.pressed_hat_buttons.keys())
            is_pressed = event.is_pressed  # position != (0,0)
            mode = self.action_data.hat_mode_map[position]

            input_id = self.action_data.hat_map[position]
            device_id = self.vjoy_id
            # sticky = self.action_data.hat_sticky
            if input_id > 0:
                match mode:
                    case ButtonOutputMode.Pulse:
                        if is_pressed:
                            if verbose:
                                syslog.info(f"VJOY: trigger start pulse vjoy {device_id} hat {input_id}")
                            repeat_interval = self.action_data.pulse_repeat_delay / 1000 if self.action_data.pulse_repeat else -1
                            self.pulse_start(
                                device_id,
                                input_type,
                                input_id,
                                position,
                                self.pulse_delay / 1000,
                                repeat_interval,
                                is_local,
                                is_remote,
                                force_remote,
                            )
                            auto_complete = False
                        else:
                            if verbose:
                                syslog.info(f"VJOY: trigger stop pulse vjoy {device_id} hat {input_id}")
                            self.pulse_stop(device_id, input_type, input_id, position)

                            # threading.Timer(0.01, self._fire_pulse, [self.vjoy_id, input_id, self.pulse_delay/1000, self.action_data.pulse_repeat, self.action_data.pulse_repeat_delay/1000]).start()
                    case ButtonOutputMode.Hold:
                        if is_pressed:
                            # release the prior buttons
                            for pressed_position in pressed_positions:
                                if position == pressed_position:
                                    continue
                                release_input_id = self.pressed_hat_buttons[pressed_position]
                                if release_input_id > 0:
                                    if is_local:
                                        if gremlin.joystick_handling.is_vjoy_connected(device_id):
                                            joystick_handling.VJoyProxy()[device_id].button(release_input_id).is_pressed = False
                                    if is_remote:
                                        self.remote_client.send_button(
                                            device_id,
                                            release_input_id,
                                            False,
                                            client_list=self.client_list,
                                        )

                                del self.pressed_hat_buttons[pressed_position]
                    case ButtonOutputMode.Press:
                        is_pressed = True
                        if input_id in self.pressed_hat_buttons:
                            del self.pressed_hat_buttons[input_id]
                    case ButtonOutputMode.Release:
                        is_pressed = False
                        if input_id in self.pressed_hat_buttons:
                            del self.pressed_hat_buttons[input_id]
                    case ButtonOutputMode.NoOp:
                        # do nothing
                        return True

                # press the new button
                self.pressed_hat_buttons[position] = input_id
                self.action_data.button_last_value = is_pressed
                if is_local:
                    if gremlin.joystick_handling.is_vjoy_connected(device_id):
                        joystick_handling.VJoyProxy()[device_id].button(input_id).is_pressed = is_pressed
                if is_remote:
                    self.remote_client.send_button(device_id, input_id, is_pressed, client_list=self.client_list)

            else:
                # release
                match mode:
                    case ButtonOutputMode.NoOp:
                        # do nothing
                        return True
                    case ButtonOutputMode.Press:
                        return True
                    case ButtonOutputMode.Release:
                        return True

                for pressed_position in pressed_positions:
                    input_id = self.pressed_hat_buttons[pressed_position]
                    if input_id > 0:
                        if verbose:
                            syslog.info(f"VJOY: set device [{self.vjoy_id}] button {input_id} pressed: False")
                        if is_local:
                            if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                                joystick_handling.VJoyProxy()[self.vjoy_id].button(input_id).is_pressed = False
                        if is_remote:
                            self.remote_client.send_button(
                                self.vjoy_id,
                                input_id,
                                False,
                                client_list=self.client_list,
                            )

                    del self.pressed_hat_buttons[pressed_position]

            self.hat_position = position

        elif input_type in VJoyRemapWidget.input_type_buttons:
            # process a button output
            is_paired = remote_control.paired
            force_remote = event.force_remote or is_paired

            # determine if event should be fired based on release mode
            is_pressed = event.is_pressed
            trigger = False
            fire_event = (self.action_data.exec_on_release and not is_pressed) or (self.action_data.exec_on_press and is_pressed)

            # if self.vjoy_input_id == 2:
            #     syslog.info(f"=============================================================== button 2 set pressed {is_pressed}")

            if self.action_mode in (
                VjoyAction.VJoyButton,
                VjoyAction.VJoyButtonInverted,
            ):
                # normal default button output behavior

                match self.action_mode:
                    case VjoyAction.VJoyButton:
                        pressed_value = is_pressed
                    case VjoyAction.VJoyButtonInverted:
                        pressed_value = not is_pressed

                if not is_pressed and self.action_data.exec_on_release:
                    pressed_value = not pressed_value

                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                            if verbose:
                                syslog.info(f"VJOY: set device [{self.vjoy_id}] button [{self.vjoy_input_id}] pressed: [True]")
                            joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = pressed_value
                    if is_remote or is_paired:
                        self.remote_client.send_button(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            pressed_value,
                            client_list=self.client_list,
                            force_remote=force_remote,
                        )

                if self.action_data.exec_on_press and is_pressed:
                    auto_release = False
                    if is_pressed and not self.action_data.ignore_release:
                        if extra_data and "autorelease" in extra_data:
                            auto_release = extra_data["autorelease"]
                        else:
                            auto_release = (
                                input_type
                                in [
                                    InputType.Keyboard,
                                    InputType.KeyboardLatched,
                                    InputType.Midi,
                                    InputType.OpenSoundControl,
                                ]
                                and self.needs_auto_release
                            )
                        if auto_release:
                            if verbose:
                                syslog.info(f"VjoyRemap: autorelease enabled for {str(event)}")
                            input_devices.CallbackActions().register_button_release(
                                (self.vjoy_id, self.vjoy_input_id),
                                event,
                                is_local=is_local,
                                is_remote=is_remote,
                                force_remote=force_remote,
                                activate_on=False,  # released
                            )

                    if verbose:
                        syslog.info(f"\t{self.vjoy_input_id} pressed: {is_pressed}  ignore release: {self.action_data.ignore_release}")
                    trigger = is_pressed or (
                        not auto_release and not is_pressed
                    )  # trigger on press, or on release unless an auto-release was already registered for the release action to avoid double releases
                    if not is_pressed and self.action_data.ignore_release:
                        # ignore release action on press/release modes
                        if verbose:
                            syslog.info("\tignoring release")
                        trigger = False
                elif not is_pressed:
                    # send a release trigger
                    trigger = True

                if trigger:
                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                            if verbose:
                                syslog.info(f"\tTrigger vjoy [{self.vjoy_id}] button [{self.vjoy_input_id}] pressed: [{is_pressed}]")
                            joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = pressed_value
                    if is_remote or is_paired:
                        self.remote_client.send_button(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            pressed_value,
                            client_list=self.client_list,
                            force_remote=is_paired,
                        )
                else:
                    # indicate no execution
                    result = False

            elif self.action_mode == VjoyAction.VJoyHat:
                # hat output when mapped to a button (hold mode)
                if verbose:
                    syslog.info(f"VJOY: hold hat device [{self.vjoy_id}] hat {self.vjoy_input_id} position: {self.action_data.vjoy_hat_position}")
                if is_pressed:
                    direction = self.action_data.vjoy_hat_position
                else:
                    direction = self.action_data.vjoy_hat_return_position
                if is_local:
                    if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                        joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = direction
                    if is_remote or is_paired:
                        self.remote_client.send_hat(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            direction,
                            client_list=self.client_list,
                            force_remote=is_paired,
                        )

            elif self.action_mode == VjoyAction.VJoyHatPress:
                # hat ouput when mapped to a button (press only)
                if verbose:
                    syslog.info(f"VJOY: set hat device [{self.vjoy_id}] hat {self.vjoy_input_id} position: {self.action_data.vjoy_hat_position}")
                direction = self.action_data.vjoy_hat_position
                if is_local:
                    if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                        joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = direction
                    if is_remote or is_paired:
                        self.remote_client.send_hat(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            direction,
                            client_list=self.client_list,
                            force_remote=is_paired,
                        )

            elif self.action_mode == VjoyAction.VJoyHatPulse:
                # hat ouput when mapped to a button (press only)
                if verbose:
                    syslog.info(f"VJOY: pulse hat device [{self.vjoy_id}] hat {self.vjoy_input_id} position: {self.action_data.vjoy_hat_position}")

                input_id = self.vjoy_input_id
                device_id = self.vjoy_id
                input_type = InputType.JoystickHat
                position = self.action_data.vjoy_hat_position
                # pulse action
                if fire_event:
                    auto_complete = False

                    repeat_interval = self.action_data.pulse_repeat_delay / 1000 if self.action_data.pulse_repeat else -1
                    self.pulse_start(
                        device_id,
                        input_type,
                        input_id,
                        position,
                        self.pulse_delay / 1000,
                        repeat_interval,
                        is_local,
                        is_remote,
                        force_remote,
                    )
                else:
                    if verbose:
                        syslog.info(f"VJOY: trigger stop pulse vjoy {device_id} button {input_id}")
                    self.pulse_stop(self.vjoy_id, input_type, input_id, position)

            elif self.action_mode == VjoyAction.VJoyButtonPress:
                # press button (no auto release)
                if verbose:
                    syslog.info(f"VJOY: set device [{self.vjoy_id}] button {self.vjoy_input_id} pressed: True")

                if fire_event:
                    self.action_data.button_last_value = True
                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                            joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = True
                    if is_remote or is_paired:
                        self.remote_client.send_button(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            True,
                            client_list=self.client_list,
                            force_remote=is_paired,
                        )

            elif self.action_mode == VjoyAction.VJoyButtonRelease:
                # release button (no auto release)
                if verbose:
                    syslog.info(f"VJOY: set device [{self.vjoy_id}] button {self.vjoy_input_id} pressed: False")
                if fire_event:
                    self.action_data.button_last_value = False
                    if is_local:
                        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                            joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = False
                    if is_remote or is_paired:
                        self.remote_client.send_button(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            False,
                            client_list=self.client_list,
                            force_remote=is_paired,
                        )

            elif self.action_mode == VjoyAction.VJoyToggle:
                # toggle action

                if fire_event:
                    if input_type in [InputType.JoystickButton, InputType.Keyboard] and event.is_pressed:
                        if is_local:
                            if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                                button = joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id)
                                button.is_pressed = not button.is_pressed
                                self.action_data.button_last_value = button.is_pressed
                                if verbose:
                                    syslog.info(f"VJOY: set device [{self.vjoy_id}] button {input_id} pressed: {button.is_pressed}")
                        if is_remote:
                            self.remote_client.toggle_button(self.vjoy_id, self.vjoy_input_id)

            elif self.action_mode == VjoyAction.VJoyPulse:
                input_id = self.vjoy_input_id
                device_id = self.vjoy_id
                input_type = InputType.JoystickButton
                position = None
                if verbose:
                    syslog.info(f"VJOY: trigger start pulse vjoy {device_id} button {input_id}")
                # pulse action
                if fire_event:
                    auto_complete = False
                    repeat_interval = self.action_data.pulse_repeat_delay / 1000 if self.action_data.pulse_repeat else -1
                    self.pulse_start(
                        device_id,
                        input_type,
                        input_id,
                        position,
                        self.pulse_delay / 1000,
                        repeat_interval,
                        is_local,
                        is_remote,
                        force_remote,
                    )
                else:
                    if verbose:
                        syslog.info(f"VJOY: trigger stop pulse vjoy {device_id} button {input_id}")
                    self.pulse_stop(self.vjoy_id, input_type, input_id, position)
            elif self.action_mode == VjoyAction.VJoyInvertAxis:
                # invert the specified axis
                if fire_event:
                    self.toggle_reverse()

            elif self.action_mode == VjoyAction.VJoySetAxis:
                # set the value on the specified axis
                if fire_event:
                    return self._set_axis_value()

            elif self.action_mode == VjoyAction.VJoyRangeAxis:
                # changes the output range on the target device / axis
                if fire_event:
                    self.usage_data.set_range(
                        self.vjoy_id,
                        self.vjoy_input_id,
                        self.range_low,
                        self.range_high,
                    )

            elif VjoyAction.is_command(self.action_mode):
                # update remote control mode
                if fire_event:
                    remote_control.mode = self.action_mode

            elif self.action_mode == VjoyAction.VJoySetAxisStepped:
                # process stepped axis request
                input_type = InputType.JoystickAxis
                position = None

                if fire_event:
                    latched = (
                        self.action_data._stepped_latched
                        and event.device_guid == self.action_data.stepped_device_guid
                        and event.identifier == self.action_data.stepped_input_id
                    )
                    primary = event.device_guid == self.hardware_device_guid and event.identifier == self.hardware_input_id

                    if primary or latched:
                        trigger = False
                        trigger = (event.is_pressed and not self.action_data.exec_on_release) or (not event.is_pressed and self.action_data.exec_on_release)
                        if trigger:
                            # determine direction we're going
                            direction = self.action_data.target_step_direction

                            if self.action_data._target_step_linear_mode:
                                # linear mode = start pulsing while pressed
                                self.repeat_interval = self.action_data.pulse_delay / 1000
                                self.step_direction = direction if primary else -direction
                                self._start_time = None
                                self._start_value = None
                                if verbose:
                                    syslog.info(
                                        f"STEPPED AXIS: start linear update - interval [{self.repeat_interval:0.3f}] Linear velocity mode: [{self.action_data._target_step_linear_mode}]  direction: [{self.step_direction}]"
                                    )
                                self.pulse_start(
                                    self.vjoy_id,
                                    input_type,
                                    self.vjoy_input_id,
                                    position,
                                    0,
                                    self.repeat_interval,
                                    is_local,
                                    is_remote,
                                    force_remote,
                                )
                            else:
                                # non linear step mode
                                # trigger = False
                                key = ("stepped-axis", self.vjoy_input_id)
                                device = gremlin.joystick_handling.vjoy_info_from_vjoy_id(self.vjoy_id)
                                if key not in device.data:
                                    device.data[key] = self.action_data.target_step_start_index

                                start_index = device.data[key]
                                count = len(self.action_data.target_step_list)
                                index = start_index

                                value = self._get_axis(self.vjoy_id, self.vjoy_input_id)
                                if not self.synced:
                                    # synchronize index if needed
                                    if self.action_data.sync_mode in (SyncMode.Input, SyncMode.LastOrInput) and value is not None:
                                        # sync the current index with the current axis value
                                        v1 = v2 = None

                                        # syslog.info(f"Sync mode: {value:0.3f}")
                                        for i in range(count):
                                            v2 = self.action_data.target_step_list[i]
                                            if v1 is not None:
                                                if value >= v1 and value <= v2:
                                                    index = i
                                                    break
                                                v1 = v2
                                    self.synced = True
                                else:
                                    # get the next or prior index

                                    if primary:
                                        index += direction
                                    elif latched:
                                        index -= direction
                                    if index < 0:
                                        index = 0
                                    elif index == count:
                                        index = count - 1
                                    index = gremlin.util.clamp(index, 0, count - 1)
                                value = self.action_data.target_step_list[index]

                                self._set_axis(self.vjoy_id, self.vjoy_input_id, value)

                                device.data[key] = index  # remember the last step index used
                                if verbose:
                                    syslog.info(f"STEPPED AXIS: previous index: [{start_index}] new index: [{index}] new value: {value:0.3f}")

                                # remember the last value
                                syslog.info(f"set step last value: {value:0.3f}")
                                self.action_data.axis_last_value = value
                else:
                    # release
                    if self.action_data._target_step_linear_mode:
                        # stop the updates
                        if verbose:
                            syslog.info("STEPPED AXIS: stop linear update")
                        self.pulse_stop(self.vjoy_id, input_type, self.vjoy_input_id, position)

                    result = False

            else:
                # basic handling of the button

                if fire_event:
                    self.action_data.button_last_value = is_pressed
                    if is_local:
                        if verbose:
                            syslog.info(f"VJOY: send local button [{self.vjoy_id}] button: {self.vjoy_input_id} pressed: {is_pressed}")
                        joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = is_pressed
                    if is_remote:
                        if verbose:
                            syslog.info(f"VJOY: send remote button [{self.vjoy_id}] button: {self.vjoy_input_id} pressed: {is_pressed}")
                        self.remote_client.send_button(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            is_pressed,
                            client_list=self.client_list,
                        )

        elif input_type == InputType.JoystickHat:
            if verbose:
                syslog.info(f"VJOY: set device [{self.vjoy_id}] hat {self.vjoy_input_id} direction: {action_value.current}")
            if is_local:
                if self.verbose:
                    syslog.info(f"VJOY: send local hat: vjoy [{self.vjoy_id}] hat [{self.vjoy_input_id}] value: {action_value.current}")
                joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = action_value.current
            if is_remote:
                if self.verbose:
                    syslog.info(f"VJOY: send remote hat: vjoy [{self.vjoy_id}] hat [{self.vjoy_input_id}] value: {action_value.current}")
                self.remote_client.send_hat(
                    self.vjoy_id,
                    self.vjoy_input_id,
                    action_value.current,
                    client_list=self.client_list,
                )

        if auto_complete:
            self.functor_complete.emit()  # indicate completed
        return result

    def _set_axis(self, vid: int, axis_id: int, value: float):
        """sets the axis value using the inversion factor"""

        # fix: RC20 double inversion
        # inverted = self.usage_data.is_inverted(vid, axis_id)
        # if inverted:
        #     # invert the value
        #     value = -value

        is_local, is_remote = self.action_data.sendFlags()
        if is_local:
            if self.verbose:
                syslog.info(f"VJOY: send local axis: vjoy [{self.vjoy_id}] axis [{self.vjoy_input_id}] value: {value:0.03f}")
            joystick_handling.VJoyProxy()[self.vjoy_id].axis(self.vjoy_input_id).value = value
        if is_remote:
            if self.verbose:
                syslog.info(f"VJOY: send remote axis: vjoy [{self.vjoy_id}] axis [{self.vjoy_input_id}] value: {value:0.03f}")
            self.remote_client.send_axis(self.vjoy_id, self.vjoy_input_id, value, client_list=self.client_list)

    def _get_axis(self, vid: int, axis_id: int) -> float:
        """gets the axis value using the inversion factor"""
        value = joystick_handling.VJoyProxy()[self.vjoy_id].axis(self.vjoy_input_id).value
        inverted = self.usage_data.is_inverted(vid, axis_id)
        if inverted:
            value = -value
        return value

    def _handle_set_axis_wiggle(self):
        """handles the axis set value after a wiggle value send"""
        value = self.target_value
        self._set_axis(self.vjoy_id, self.vjoy_input_id, value)

    def relative_axis_thread(self):
        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
            self.thread_running = True
            vjoy_dev = joystick_handling.VJoyProxy()[self.vjoy_id]
            self.axis_value = vjoy_dev.axis(self.vjoy_input_id).value
            is_local, is_remote = self.action_data.sendFlags()
            while self.thread_running:
                try:
                    # If the vjoy value has was changed from what we set it to
                    # in the last iteration, terminate the thread
                    change = vjoy_dev.axis(self.vjoy_input_id).value - self.axis_value
                    if abs(change) > 0.0001:
                        self.thread_running = False
                        self.should_stop_thread = True
                        return

                    self.axis_value = max(-1.0, min(1.0, self.axis_value + self.axis_delta_value))

                    value = self.axis_value

                    if is_local:
                        if self.verbose:
                            syslog.info(f"VJOY: send local relative axis: vjoy [{self.vjoy_id}] axis [{self.vjoy_input_id}] value: {value:0.03f}")
                        vjoy_dev.axis(self.vjoy_input_id).value = value
                    if is_remote:
                        if self.verbose:
                            syslog.info(f"VJOY: send remote relative axis: vjoy [{self.vjoy_id}] axis [{self.vjoy_input_id}] value: {value:0.03f}")
                        self.remote_client.send_axis(
                            self.vjoy_id,
                            self.vjoy_input_id,
                            value,
                            client_list=self.client_list,
                        )
                    # remember the last value
                    self.action_data.axis_last_value = value

                    if self.should_stop_thread and self.thread_last_update + 1.0 < time.time():
                        self.thread_running = False
                    time.sleep(0)

                except gremlin.error.VJoyError:
                    self.thread_running = False
        else:
            self.thread_running = False

        self.functor_complete.emit()  # indicate completed


class MergeData:
    """defines a merge axis input"""

    def __init__(
        self,
        device_id=None,
        input_id=None,
        operation: MergeOperationType = MergeOperationType.Center,
        invert=False,
    ):
        self._device_id = gremlin.util.normalize_guid(device_id)
        self._device_guid = gremlin.util.parse_guid(device_id)
        self._input_id = input_id
        self.operation = operation
        self.invert = invert
        self.id = gremlin.util.get_guid()
        self.curve_data = None  # curve applied to the merged axis
        self.callback = None  # axis callback - holds the update callback when an axis input changes to update the curve

    @property
    def key(self) -> tuple:
        return (self._device_id, self._input_id)  # unique key

    @property
    def keyOp(self) -> tuple:
        """gets a key that includes the operation to conduct"""
        return (self._device_id, self._input_id, self.operation)  # unique key

    @property
    def device_id(self):
        return self._device_id

    @property
    def device_guid(self):
        return self._device_guid

    @device_id.setter
    def device_id(self, value):
        self._device_id = gremlin.util.normalize_guid(value)
        self._device_guid = gremlin.util.parse_guid(value)

    @device_guid.setter
    def device_guid(self, value):
        self._device_id = gremlin.util.normalize_guid(value)
        self._device_guid = value

    @property
    def input_id(self):
        return self._input_id

    @input_id.setter
    def input_id(self, value):
        self._input_id = value

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        if other is None:
            return False
        if self.device_id != other.device_id:
            return False
        if self.input_id != other.input_id:
            return False
        return True

    def to_xml(self):
        """saves data to xml and return that xml node"""
        node = ElementTree.Element("merge-data")
        node.set("device-id", self.device_id)
        node.set("input-id", safe_format(self.input_id, int))
        operation = MergeOperationType.to_string(self.operation)
        node.set("operation", safe_format(operation, str))
        node.set("invert", safe_format(self.invert, bool))
        device = gremlin.joystick_handling.getDevice(self.device_id)
        if device is None:
            syslog.error(f"MERGE DATA: Unable to get device for id {self.device_id}")
            comment = f"Unknown device: {self.device_id} Operation: [{operation}]"
        else:
            comment = f"Merged Device: {device.name}/[{self.device_id}] Axis: [{self.input_id}]/{device.get_axis_name(self.input_id)} Operation: [{operation}]"
        node_comment = ElementTree.Comment(comment)
        node.append(node_comment)
        if self.curve_data:
            curve_node = self.curve_data._generate_xml()
            node.append(curve_node)
        return node

    def from_xml(self, node, extra_data=None):
        """read node data from xml"""
        if not node.tag == "merge-data":
            return
        device_id = safe_read(node, "device-id", str, "")
        if not device_id:
            return
        device_id = gremlin.util.normalize_guid(device_id)
        device_guid = gremlin.util.parse_guid(device_id)
        self.device_id = device_id
        self.device_guid = device_guid
        self.input_id = safe_read(node, "input-id", int, 1)
        if "operation" in node.attrib:
            op_str = node.get("operation")
            if gremlin.util.isNumeric(op_str):
                # legacy
                self.operation = MergeOperationType(int(op_str))
            else:
                self.operation = MergeOperationType.to_enum(op_str)
        else:
            self.operation = MergeOperationType.Center  # default

        self.invert = safe_read(node, "invert", bool, False)

        for child in node:
            if child.tag == "curve-data":
                # curve data node
                curve_data = gremlin.curve_handler.AxisCurveData()
                curve_data._parse_xml(child)
                self.curve_data = curve_data

    def compute(self, value: float):
        """applies the transform"""
        current = joystick_handling.get_axis(self.device_id, self.input_id)
        match self.operation:
            case MergeOperationType.Add:
                new_value = value + current
            case MergeOperationType.Substract:
                new_value = value - current
            case MergeOperationType.Average:
                new_value = (value + current) / 2
            case MergeOperationType.Center:
                new_value = (value - current) / 2
            case MergeOperationType.ScaleHalf:
                scale = abs(current)
                new_value = value * scale
            case MergeOperationType.ScaleFull:
                scale = gremlin.util.scale_to_range(current, target_min=0, target_max=1)
                new_value = value * scale
            case _:
                # no change
                return value

        return gremlin.util.clamp(new_value)


class VjoyRemap(gremlin.base_profile.AbstractAction):
    """Action remapping physical joystick inputs to vJoy inputs."""

    name = "Vjoy Remap"
    tag = "vjoyremap"
    hint = """Advanced VJOY mapper.
This action maps an input to a VJOY device.
Supports axis merging, curved output, command, hat and button mappings.
"""

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)

    functor = VJoyRemapFunctor
    widget = VJoyRemapWidget

    def __init__(self, parent):
        """vjoyremap action block"""
        super().__init__(parent)
        self.parent = parent
        self.setPriority(9)
        # Set vjoy ids to None so we know to pick the next best one
        # automatically

        self.vjoy_map = {}  # list of vjoy devices by their vjoy index ID
        self.refresh_vjoy()

        self._vjoy_id: int = 1
        self._vjoy_input_id: int = 1
        self._vjoy_axis_id = 1
        self._vjoy_button_id = 1
        self.vjoy_hat_id = 1
        self.vjoy_hat_position = (0, 0)  # hat position as a tuple
        self.vjoy_hat_return_position = (
            0,
            0,
        )  # hat return position - center is the default

        self.usage_data = gremlin.joystick_handling.VJoyUsageState()
        self._input_type: InputType = self.get_input_type()
        if self._input_type in (InputType.ModeControl, InputType.VirtualButton):
            self._input_type = InputType.JoystickButton
        self.device_guid = self.hardware_device_guid
        self.input_id = self.hardware_input_id
        self.input_type = self.hardware_input_type

        # default hat map table setup and default mapping for new hats
        self.hat_map = {}  # map of button id keyed by hat position tuple
        self.hat_positions = list(vjoy.vjoy.Hat.to_continuous_direction.keys())
        # self.hat_positions.remove((0,0)) # remove center position
        self.hat_mode_map = {}  # bool table keyed by hat position
        self.hat_sticky = False  # determines if hats are sticky or not - sticky means all positions are active until all returns to the center position
        button_id = 1
        for position in self.hat_positions:
            self.hat_map[position] = button_id
            if position == (0, 0):
                self.hat_mode_map[position] = ButtonOutputMode.NoOp  # center do nothing
            else:
                self.hat_mode_map[position] = ButtonOutputMode.Hold  # hold by default
            button_id += 1

        self.sync_on_start = (
            True  # true if the value should sync on profile start to synchronize with input (on by default as it's generally a desired behavior)
        )
        self.sync_mode = SyncMode.Ignore  # ignore by default

        self._reverse: bool = False
        self.axis_mode = "absolute"
        self.axis_scaling: float = 1.0
        self.axis_start_value: float = 0.0  # start value if sync mode is set to default and the output is an axis
        self.axis_last_value = None  # last axis value

        self.curve_data = None  # present if curve data is needed

        self.button_start_value: bool = False  # start button value if output to button is selected (if sync mode is set to default) - default is TURN OFF
        self.button_last_value: bool = None  # last button sent

        _config = gremlin.config.Configuration()
        self._grid_visible = None

        self.exec_on_press = True  # true if trigger should execute on input press event
        self.exec_on_release = False  # true if trigger should execute on input release event

        self._paired: bool = False

        self.auto_release = False  # true if we should do an auto-release (only means anything on momentary inputs)
        self.ignore_release = False  # true if the button release should be ignored

        self._merge_data = []  # list of merged axes

        self.invert_merged_output = False  # true if merged axis output is inverted

        self.output_range_min: float = -1.0  # min for merged output
        self.output_range_max: float = 1.0  # max for merged output
        self.merge_invert: bool = False  # inversion flag for merged output
        self.merged = False

        # default mode
        self._action_mode = VjoyAction.VJoyButton

        self.button_range_min = -1.0  # axis to button range min
        self.button_range_max = 1.0  # axis to button range max
        self.button_mode = ButtonOutputMode.Hold

        is_axis = self.input_is_axis()

        # pick an appropriate default action set for the type of input this is
        if is_axis:
            # input is setup as an axis
            self._action_mode = VjoyAction.VJoyAxis
        elif self.input_type in VJoyRemapWidget.input_type_buttons:
            self._action_mode = VjoyAction.VJoyButton
        elif self.input_type == InputType.JoystickHat:
            self._action_mode = VjoyAction.VJoyHat

        self.current_state = 0  # toggle value for the input 1 means set, any other value means not set for buttons
        self.pulse_delay = 250  # pulse delay
        self.pulse_repeat_delay = 250  # pulse repeat delay (time between pulses)
        self.pulse_repeat = False  # true if pulses repeat

        self.target_value = 0.0
        self.target_step_list = [
            -1,
            -0.5,
            0,
            0.5,
            1,
        ]  # list of values to send - if empty - uses the fixed target_value

        self._current_step_index = 0  # index of last value sent
        self._target_step_start_index = 0  # start index when profile is loaded (initial step)
        self._target_step_direction = 1  # direction of stepping, +1 or -1

        self._target_step_interval = 0.1  # interval for linear stepping
        self._target_step_delta = 0.01  # delta when in manual pulse mode
        self._target_step_linear_mode = True  # true if using velocity/acceleration mode controller for simple up/down
        self._target_step_velocity = 0.01  # rate of change per second for accelerated mode
        self._target_step_acceleration = 2.0  # acceleration for the rate of change
        self._stepped_latched = True  # true if the step down latching is enabled

        self.target_value_valid = True
        self.target_is_relative = False  # true if the set value axis is a relative value (+ or -)
        self.target_use_last = False  # true if the last sent axis value is sent again
        self.relative_value = 0.2  # relative value to add or remove
        self.relative_pulse_delay = 100  # relative pulse delay in miliseconds
        self.use_relative_value = False  # true if set value should use relative value
        self._stepped_device_id: str = None  # device of the down step action to latch
        self._stepped_device_guid: dinput.GUID = None  # device GUID of the down step device
        self.stepped_input_type = gremlin.input_types.InputType.JoystickButton
        self.stepped_input_id: int = None  # input of the down step action to latch

        self.override_input_type = None  # manual input type override

        # trim curves
        curve = gremlin.curve_handler.AxisCurveData()
        self.trim_curve = curve

    def actionDeleted(self):
        """called if the action is being deleted"""
        if self._input_type == InputType.JoystickButton:
            el = gremlin.event_handler.EventListener()
            el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, False, self.id)

    @property
    def vjoy_id(self):
        """vjoy device number"""
        return self._vjoy_id

    @vjoy_id.setter
    def vjoy_id(self, value: int):
        if value != self._vjoy_id:
            if self.input_type == InputType.JoystickButton:
                # notify of button usage change for the tracking
                el = gremlin.event_handler.EventListener()
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, False, self.id)
                self._vjoy_id = value
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, True, self.id)
            else:
                self._vjoy_id = value

    @property
    def vjoy_device_guid(self):
        """gets the vjoy device GUID"""
        return gremlin.joystick_handling.getVjoyDeviceGuid(self._vjoy_id)

    @property
    def vjoy_device_id(self):
        # legacy API same as vjoy_id
        return self._vjoy_id

    @property
    def input_type(self) -> InputType:
        return self._input_type

    @input_type.setter
    def input_type(self, value: InputType):
        if self._input_type != value:
            if self._input_type == InputType.JoystickButton:
                # notify of button usage change for the tracking
                el = gremlin.event_handler.EventListener()
                el.vjoy_button_usage.emit(self.vjoy_id, self._vjoy_input_id, False, self.id)

            self._input_type = value

            if self._input_type == InputType.JoystickButton:
                el = gremlin.event_handler.EventListener()
                el.vjoy_button_usage.emit(self.vjoy_id, self._vjoy_input_id, True, self.id)

    @property
    def vjoy_button_id(self) -> int:
        return self._vjoy_button_id

    @vjoy_button_id.setter
    def vjoy_button_id(self, value: int):
        if value != self._vjoy_button_id:
            if self._vjoy_button_id == InputType.JoystickButton:
                # notify of button usage change for the tracking
                el = gremlin.event_handler.EventListener()
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_button_id, False, self.id)
                self._vjoy_button_id = value
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_button_id, True, self.id)
            else:
                self._vjoy_button_id = value

    @property
    def axis_start_value_enabled(self) -> bool:
        """true if the axis start value is enabled"""
        return self.sync_mode == SyncMode.Default and self.action_mode == VjoyAction.VJoyAxis

    def queueAxisEvent(self):
        """queues an axis event on demand to force updates"""
        input_type = self.get_input_type()
        if input_type == InputType.JoystickAxis:
            sd = gremlin.event_handler.AxisState()
            device_guid = self.hardware_device_id
            input_id = self.hardware_input_id
            sd.queueAxisEvent(device_guid, input_id)
            if self.action_mode == VjoyAction.VJoyMergeAxis:
                for data in self._merge_data:
                    if data.callback:
                        d_device_id, d_input_id = data.key
                        values = sd.getAxisValues(d_device_id, d_input_id)
                        if values:
                            data.callback(values.actual)

    @property
    def target_step_direction(self) -> int:
        return self._target_step_direction

    @target_step_direction.setter
    def target_step_direction(self, value: int):
        self._target_step_direction = value

    @property
    def target_step_start_index(self) -> int:
        return self._target_step_start_index

    @target_step_start_index.setter
    def target_step_start_index(self, value: int):
        self._target_step_start_index = value
        self._current_step_index = value

    def is_scaled(self):
        """true if the axis output is scaled"""
        return abs(self.output_range_min - self.output_range_max) != 2.0

    def get_input_type(self, override=True):
        if override and self.override_input_type is not None:
            return self.override_input_type
        elif hasattr(self.parent, "get_input_type"):
            input_type = self.parent.get_input_type()
            if input_type is not None:
                return input_type
        return super().get_input_type()

    def refresh_vjoy(self):
        """updates vjoy devices device map"""
        self.vjoy_map = gremlin.joystick_handling.vjoy_device_map()

    def get_raw_axis_value(self):
        if self.input_is_hardware():
            return gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
        return self.hardware_input_id.getAxisValue()

    # def _apply_curve(self, value: float, curves=None) -> float:
    #     """applies an output curve to the input if any curves are to be applied """

    #     if curves is None:
    #         curves = [self.curve_data] if self.curve_data else []

    #     if not curves:
    #         """ no curves to apply """
    #         return value

    #     config = gremlin.config.Configuration()
    #     verbose = config.verbose_mode_merge or (config.verbose_mode_curve and gremlin.shared_state.is_running) or config.verbose_mode_vjoy
    #     curve_value = None

    #     raw_value = value

    #     if self.action_mode == VjoyAction.VJoyAxis:
    #         # plain axis

    #         if curves:
    #             if verbose:
    #                 curve_msg = f"Applying {len(curves)} curves: "

    #             for curve_data in curves:
    #                 curve_value = curve_data.curve_value(value)  # remember to make sure curve_data had curve_update() called or the data will be incorrect
    #                 # syslog.info(f"Apply curve data: {curve_data} input: {value:0.3f} output: {curve_value:0.3f}")
    #                 if verbose:
    #                     curve_msg += f"[{value:0.3f} -> [{curve_value:0.3f}] |"
    #                 value = curve_value

    #             if verbose:
    #                 syslog.info(f"VJOY AXIS Filter: applied curve: {curve_msg} final curve value: {curve_value:0.3f}  input: {raw_value:0.3f}")

    #         # apply scale or invert to input
    #         is_scaled = self.is_scaled()
    #         is_reverse = self.reverse
    #         if is_scaled or is_reverse:
    #             value = scale_to_range(
    #                 value,
    #                 target_min=self.output_range_min,
    #                 target_max=self.output_range_max,
    #                 invert=is_reverse,
    #             )

    #     return value

    # def _get_merge_value(self):
    #     """applies merging to the value"""
    #     config = gremlin.config.Configuration()
    #     verbose = config.verbose_mode_merge or (config.verbose_mode_curve and gremlin.shared_state.is_running) or config.verbose_mode_vjoy

    #     merged_values = None

    #     if self.action_mode == VjoyAction.VJoyMergeAxis:  # and self.merge_mode != MergeOperationType.NotSet:
    #         if gremlin.joystick_handling.is_hardware_device(self.hardware_device_guid):
    #             v1 = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
    #         elif gremlin.joystick_handling.is_vjoy_device(self.hardware_device_guid):
    #             v1 = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
    #         else:
    #             v1 = self.hardware_input_id.axis_value

    #         if self.reverse:  # if the primary input should be reversed before merge
    #             v1 = -v1

    #         # include in merged data the input axis
    #         merged_values = [v1]
    #         value = v1
    #         sd = gremlin.event_handler.AxisState()
    #         if verbose:
    #             d1_name = gremlin.joystick_handling.getDeviceName(self.hardware_device_guid)
    #             syslog.info(f"MERGE: source: [{d1_name}] axis: [{self.hardware_input_id}] steps: {len(self._merge_data)}")
    #             step = 1

    #         for data in self._merge_data:
    #             merge_device_id = data.device_id
    #             merge_input_id = data.input_id
    #             merge_device_guid = data.device_guid
    #             merge_input_type = InputType.JoystickAxis

    #             if not merge_device_id or merge_input_id is None or merge_device_guid is None:
    #                 # no data
    #                 continue

    #             v2 = None

    #             if gremlin.joystick_handling.is_hardware_device(merge_device_guid):
    #                 values = sd.getAxisValues(merge_device_guid, merge_input_id)
    #                 if values:
    #                     v2 = values.actual
    #                 else:
    #                     sd.registerDeviceGuid(merge_device_guid)
    #                     values = sd.getAxisValues(merge_device_guid, merge_input_id)

    #                     if values:
    #                         v2 = values.actual
    #                     else:
    #                         device_name = gremlin.joystick_handling.device_name_from_guid(merge_device_guid)
    #                         v2 = gremlin.joystick_handling.get_curved_axis(merge_device_guid, merge_input_id)
    #                         syslog.warning(f"Unable to get value for hardware device: {device_name} [{merge_device_guid}] input: [{merge_input_id}] - using alternate method. value: {v2:0.3f}")

    #             elif gremlin.joystick_handling.is_vjoy_device(merge_device_guid):
    #                 values = sd.getAxisValues(merge_device_guid, merge_input_id)
    #                 if values:
    #                     v2 = values.actual
    #                 else:
    #                     sd.registerDeviceGuid(merge_device_guid)
    #                     values = sd.getAxisValues(merge_device_guid, merge_input_id)
    #                     if values:
    #                         v2 = values.actual
    #                     else:
    #                         device_name = gremlin.joystick_handling.device_name_from_guid(merge_device_guid)
    #                         v2 = gremlin.joystick_handling.get_curved_axis(merge_device_guid, merge_input_id)
    #                         syslog.warning(f"Unable to get value for vjoy device: {device_name} [{merge_device_guid}] input: [{merge_input_id}] - using alternate method. value: {v2:0.3f}")

    #             else:
    #                 # find the merged device
    #                 ec = gremlin.execution_graph.ExecutionContext()
    #                 input_item = ec.findInputItem(
    #                     merge_device_guid,
    #                     merge_input_type,
    #                     merge_input_id,
    #                     gremlin.shared_state.current_mode,
    #                 )
    #                 if input_item:
    #                     v2 = input_item.axis_value

    #             if v1 is None or v2 is None:
    #                 # something wasn't found
    #                 syslog.error(f"VjoyRemap: merge: unable to get an axis value, one of the inputs was not found.: id: [{str(merge_device_guid)}] axis: [{merge_input_id}] ")
    #                 return 0.0

    #             if data.curve_data:
    #                 # apply any curve to the merged data before applying it
    #                 v2 = data.curve_data.curve_value(v2)

    #             merged_values.append(v2)  # add the merge value

    #             match data.operation:
    #                 case MergeOperationType.Add:
    #                     value = scale_to_range(
    #                         v1 + v2,
    #                         target_min=self.output_range_min,
    #                         target_max=self.output_range_max,
    #                         invert=self.merge_invert,
    #                     )

    #                 case MergeOperationType.Average:
    #                     value = scale_to_range(
    #                         (v1 + v2) / 2,
    #                         target_min=self.output_range_min,
    #                         target_max=self.output_range_max,
    #                         invert=self.merge_invert,
    #                     )

    #                 case MergeOperationType.Center:
    #                     value = scale_to_range(
    #                         (v1 - v2) / 2,
    #                         target_min=self.output_range_min,
    #                         target_max=self.output_range_max,
    #                         invert=self.merge_invert,
    #                     )

    #                 case MergeOperationType.Min:
    #                     value = scale_to_range(
    #                         min(v1, v2),
    #                         target_min=self.output_range_min,
    #                         target_max=self.output_range_max,
    #                         invert=self.merge_invert,
    #                     )

    #                 case MergeOperationType.Max:
    #                     value = scale_to_range(
    #                         max(v1, v2),
    #                         target_min=self.output_range_min,
    #                         target_max=self.output_range_max,
    #                         invert=self.merge_invert,
    #                     )

    #                 case MergeOperationType.ScaleFull:
    #                     scale = v2
    #                     value = scale_to_range(v1 * scale)

    #                 case MergeOperationType.ScaleHalf:
    #                     if v2 > 0:
    #                         scale = v2
    #                         value = scale_to_range(v1 * scale)
    #                     else:
    #                         scale = abs(v2)
    #                         value = scale_to_range(v1 * -scale)

    #                 case MergeOperationType.ScaleFullCentered:
    #                     scale = scale_to_range(v2, target_min=0, target_max=1)
    #                     value = scale_to_range(v1 * scale)

    #                 case MergeOperationType.ScaleHalfCentered:
    #                     scale = abs(v2)
    #                     value = scale_to_range(v1 * scale)

    #                 case MergeOperationType.Multiply:
    #                     value = scale_to_range(v1 * v2)

    #                 case MergeOperationType.Trim:
    #                     v2 = scale_to_range(v2, target_min=0, target_max=1)  # scale v2 0 to 1
    #                     if v1 > 0:
    #                         value = v2 + ((1 - v2) * v1)
    #                     else:
    #                         value = v2 + ((v2 + 1) * v1)

    #                 case MergeOperationType.TrimCentered:
    #                     # v2 = scale_to_range(v2, target_min=0, target_max = 1) # scale v2 0 to 1
    #                     # v2 is -1 to +1
    #                     a = scale_to_range(v2, target_min=0, target_max=1)  # scale v2 0 to 1
    #                     b = a - 0.5
    #                     c = scale_to_range(b, source_min=0, source_max=0.5, target_min=0, target_max=1)
    #                     t = b
    #                     syslog.info(f"v2: {v2:0.03f} a: {a:0.03f} b: {b:0.03f} c: {c:0.03f} t: {t:0.03f}")
    #                     if v1 > 0:
    #                         value = v2 + ((1 - t) * v1)
    #                     else:
    #                         value = v2 + ((t + 1) * v1)

    #             if verbose:
    #                 d2_name = gremlin.joystick_handling.getDeviceName(merge_device_guid)

    #                 syslog.info(f"Merge operation: step [{step}]: {data.operation.name}: v1 {v1:0.03f} - merge with [{d2_name}] axis [{merge_input_id}]  v2: [{v2:0.03f}] result: [{value:0.03f}]")
    #                 step += 1

    #             v1 = value
    #     else:
    #         # not a merge mode, get the current value of the input
    #         if gremlin.joystick_handling.is_hardware_device(self.hardware_device_guid):
    #             value = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
    #         elif gremlin.joystick_handling.is_vjoy_device(self.hardware_device_guid):
    #             value = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)

    #     return value

    # def get_filtered_axis_value(self, value: float = None, curves: list = None, channels=False) -> float:
    #     ''' gets the filtered axis output value '''
    #     raw_value = value
    #     merge_value : float = None
    #     curve_value : float = None
    #     if self.action_mode == VjoyAction.VJoyMergeAxis:
    #         # action mode is curve mode
    #         value = self._get_merge_value()
    #         merge_value = value

    #     if curves or self.curve_data:
    #         value = self._apply_curve(value, curves)
    #         curve_value = value

    #     if self.invert_merged_output:
    #         # invert the final output if needed
    #         value = -value

    #     if channels:
    #         data = gremlin.event_handler.AxisValues(actual=value, raw=raw_value, curved=curve_value, merged=merge_value)
    #         return data

    #     return value

    def get_filtered_axis_value(self, value: float = None, curves: list = None, channels=False) -> float:
        """computes the output value for the current configuration - applies curves if curves are provided
        if channels is enabled, returns the data as an AxisValue object with channels
        """
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_merge or (config.verbose_mode_curve and gremlin.shared_state.is_running) or config.verbose_mode_vjoy
        curve_value = None
        merged_values = None

        if verbose:
            device = gremlin.joystick_handling.getDevice(self.hardware_device_guid)
            if not device:
                syslog.warning(f"Unable to find device: [{gremlin.util.normalize_guid(self.hardware_device_guid)}]")
                return None
            device_stub = f"[{device.name}/{device.get_axis_name(self.hardware_input_id)}]"

        if value is not None:
            if verbose:
                source = f"{device_stub} from value"
            axis_value = value
        else:
            if verbose:
                source = f"{device_stub} get hardware value"
            # get the calibrated, curved input (if input is curved and calibrated)
            axis_value = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
            if axis_value is None:
                # not an axis type or device not found
                return None

        if isinstance(axis_value, list) and axis_value:
            axis_value = axis_value[0]

        value = axis_value
        raw_value = value

        if not curves:
            # process curves
            curves = [self.curve_data] if self.curve_data else []

        if self.action_mode == VjoyAction.VJoyAxis:
            # plain axis

            if curves:
                if verbose:
                    curve_msg = f"Applying {len(curves)} curves: "

                for curve_data in curves:
                    curve_value = curve_data.curve_value(value)  # remember to make sure curve_data had curve_update() called or the data will be incorrect
                    # syslog.info(f"Apply curve data: {curve_data} input: {value:0.3f} output: {curve_value:0.3f}")
                    if verbose:
                        curve_msg += f"[{value:0.3f} -> [{curve_value:0.3f}] |"
                    value = curve_value

                if verbose:
                    syslog.info(f"VJOY AXIS Filter: applied curve: {curve_msg} final curve value: {curve_value:0.3f}  input: {raw_value:0.3f}")

            # apply scale or invert to input
            is_scaled = self.is_scaled()
            is_reverse = self.reverse
            if is_scaled or is_reverse:
                value = scale_to_range(
                    value,
                    target_min=self.output_range_min,
                    target_max=self.output_range_max,
                    invert=is_reverse,
                )
                if verbose:
                    syslog.info(
                        f"VJOY AXIS Filter: using source: [{source}] applied filter: [{axis_value:0.3f}]  scaled: {is_scaled} reversed: {is_reverse} -> included: [{value:0.3f}]"
                    )
            else:
                if verbose:
                    syslog.info(f"VJOY AXIS Filter: using source: [{source}] applied filter: [{axis_value:0.3f}] -> included: [{value:0.3f}]")

        elif self.action_mode == VjoyAction.VJoyMergeAxis:  # and self.merge_mode != MergeOperationType.NotSet:
            if gremlin.joystick_handling.is_hardware_device(self.hardware_device_guid):
                v1 = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
            elif gremlin.joystick_handling.is_vjoy_device(self.hardware_device_guid):
                v1 = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
            else:
                v1 = self.hardware_input_id.axis_value

            if self.reverse:  # if the primary input should be reversed before merge
                v1 = -v1

            if curves:
                for curve_data in curves:
                    v1 = curve_data.curve_value(v1)

            # include in merged data the input axis
            merged_values = [v1]
            value = v1
            sd = gremlin.event_handler.AxisState()
            if verbose:
                d1_name = gremlin.joystick_handling.getDeviceName(self.hardware_device_guid)
                syslog.info(f"MERGE: source: [{d1_name}] axis: [{self.hardware_input_id}] steps: {len(self._merge_data)}")
                step = 1

            for data in self._merge_data:
                merge_device_id = data.device_id
                merge_input_id = data.input_id
                merge_device_guid = data.device_guid
                merge_input_type = InputType.JoystickAxis

                if not merge_device_id or merge_input_id is None or merge_device_guid is None:
                    # no data
                    continue

                v2 = None

                if gremlin.joystick_handling.is_hardware_device(merge_device_guid):
                    values = sd.getAxisValues(merge_device_guid, merge_input_id)
                    if values:
                        v2 = values.actual
                    else:
                        sd.registerDeviceGuid(merge_device_guid)
                        values = sd.getAxisValues(merge_device_guid, merge_input_id)

                        if values:
                            v2 = values.actual
                        else:
                            device_name = gremlin.joystick_handling.device_name_from_guid(merge_device_guid)
                            v2 = gremlin.joystick_handling.get_curved_axis(merge_device_guid, merge_input_id)
                            syslog.warning(
                                f"Unable to get value for hardware device: {device_name} [{merge_device_guid}] input: [{merge_input_id}] - using alternate method. value: {v2:0.3f}"
                            )

                elif gremlin.joystick_handling.is_vjoy_device(merge_device_guid):
                    values = sd.getAxisValues(merge_device_guid, merge_input_id)
                    if values:
                        v2 = values.actual
                    else:
                        sd.registerDeviceGuid(merge_device_guid)
                        values = sd.getAxisValues(merge_device_guid, merge_input_id)
                        if values:
                            v2 = values.actual
                        else:
                            device_name = gremlin.joystick_handling.device_name_from_guid(merge_device_guid)
                            v2 = gremlin.joystick_handling.get_curved_axis(merge_device_guid, merge_input_id)
                            syslog.warning(
                                f"Unable to get value for vjoy device: {device_name} [{merge_device_guid}] input: [{merge_input_id}] - using alternate method. value: {v2:0.3f}"
                            )

                else:
                    # find the merged device
                    ec = gremlin.execution_graph.ExecutionContext()
                    input_item = ec.findInputItem(
                        merge_device_guid,
                        merge_input_type,
                        merge_input_id,
                        gremlin.shared_state.current_mode,
                    )
                    if input_item:
                        v2 = input_item.axis_value

                if v1 is None or v2 is None:
                    # something wasn't found
                    syslog.error(
                        f"VjoyRemap: merge: unable to get an axis value, one of the inputs was not found.: id: [{str(merge_device_guid)}] axis: [{merge_input_id}] "
                    )
                    return 0.0

                if data.curve_data:
                    # apply any curve to the merged data before applying it
                    v2 = data.curve_data.curve_value(v2)

                merged_values.append(v2)  # add the merge value

                match data.operation:
                    case MergeOperationType.Add:
                        value = scale_to_range(
                            v1 + v2,
                            target_min=self.output_range_min,
                            target_max=self.output_range_max,
                            invert=self.merge_invert,
                        )

                    case MergeOperationType.Average:
                        value = scale_to_range(
                            (v1 + v2) / 2,
                            target_min=self.output_range_min,
                            target_max=self.output_range_max,
                            invert=self.merge_invert,
                        )

                    case MergeOperationType.Center:
                        value = scale_to_range(
                            (v1 - v2) / 2,
                            target_min=self.output_range_min,
                            target_max=self.output_range_max,
                            invert=self.merge_invert,
                        )

                    case MergeOperationType.Min:
                        value = scale_to_range(
                            min(v1, v2),
                            target_min=self.output_range_min,
                            target_max=self.output_range_max,
                            invert=self.merge_invert,
                        )

                    case MergeOperationType.Max:
                        value = scale_to_range(
                            max(v1, v2),
                            target_min=self.output_range_min,
                            target_max=self.output_range_max,
                            invert=self.merge_invert,
                        )

                    case MergeOperationType.ScaleFull:
                        scale = v2
                        value = scale_to_range(v1 * scale)

                    case MergeOperationType.ScaleHalf:
                        if v2 > 0:
                            scale = v2
                            value = scale_to_range(v1 * scale)
                        else:
                            scale = abs(v2)
                            value = scale_to_range(v1 * -scale)

                    case MergeOperationType.ScaleFullCentered:
                        scale = scale_to_range(v2, target_min=0, target_max=1)
                        value = scale_to_range(v1 * scale)

                    case MergeOperationType.ScaleHalfCentered:
                        scale = abs(v2)
                        value = scale_to_range(v1 * scale)

                    case MergeOperationType.Multiply:
                        value = scale_to_range(v1 * v2)

                    case MergeOperationType.Trim:
                        v2 = scale_to_range(v2, target_min=0, target_max=1)  # scale v2 0 to 1
                        if v1 > 0:
                            value = v2 + ((1 - v2) * v1)
                        else:
                            value = v2 + ((v2 + 1) * v1)

                    case MergeOperationType.TrimCentered:
                        # v2 = scale_to_range(v2, target_min=0, target_max = 1) # scale v2 0 to 1
                        # v2 is -1 to +1
                        a = scale_to_range(v2, target_min=0, target_max=1)  # scale v2 0 to 1
                        b = a - 0.5
                        c = scale_to_range(b, source_min=0, source_max=0.5, target_min=0, target_max=1)
                        t = b
                        syslog.info(f"v2: {v2:0.03f} a: {a:0.03f} b: {b:0.03f} c: {c:0.03f} t: {t:0.03f}")
                        if v1 > 0:
                            value = v2 + ((1 - t) * v1)
                        else:
                            value = v2 + ((t + 1) * v1)

                if verbose:
                    d2_name = gremlin.joystick_handling.getDeviceName(merge_device_guid)

                    syslog.info(
                        f"Merge operation: step [{step}]: {data.operation.name}: v1 {v1:0.03f} - merge with [{d2_name}] axis [{merge_input_id}]  v2: [{v2:0.03f}] result: [{value:0.03f}]"
                    )
                    step += 1

                v1 = value

            if self.invert_merged_output:
                # invert the final output if needed
                value = -value

        if channels:
            data = gremlin.event_handler.AxisValues(actual=value, raw=raw_value, curved=curve_value, merged=merged_values)
            return data

        return value

    def get_ranged_axis_value(self, value: float) -> float:
        """get scaled and ranged  ** NO INVERSION **"""
        if value is None:
            return value
        v1 = self.output_range_min
        v2 = self.output_range_max
        if v1 > v2:
            v1, v2 = v2, v1
        s = self.axis_scaling
        if v1 != -1.0 or v2 != 1.0 or s != 1.0:
            value = gremlin.util.scale_to_range(value * s, target_min=v1, target_max=v2)
        return value

    def isMergeDeviceGuid(self, device_guid):
        for data in self._merge_data:
            if gremlin.util.compare_guid(device_guid, data.device_guid):
                return True
        return False

    def isMergeEvent(self, event) -> bool:
        """True if the event is part of a merge operation"""
        if event.is_axis:
            device_guid = gremlin.util.normalize_guid(event.device_guid)
            input_id = event.identifier
            if (event.device_guid == self.hardware_device_guid and event.identifier == self.hardware_input_id) or (
                event.device_guid == self.get_device_guid() and event.identifier == self.get_input_id()
            ):
                # process self
                return True

            key = (device_guid, input_id)
            keys = [md.key for md in self._merge_data]
            return key in keys
        return False

    @property
    def stepped_device_id(self) -> str:
        return self._stepped_device_id

    @stepped_device_id.setter
    def stepped_device_id(self, value: str | dinput.GUID):
        if value is None:
            self._stepped_device_id = None
            self._stepped_device_guid = None
            return
        if not isinstance(value, str):
            value = str(value)
        self._stepped_device_id = value
        self._stepped_device_guid = util.parse_guid(value)

    @property
    def stepped_device_guid(self) -> dinput.GUID:
        return self._stepped_device_guid

    @stepped_device_guid.setter
    def stepped_device_guid(self, value: dinput.GUID):
        if value is None:
            self._stepped_device_id = None
            self._stepped_device_guid = None
            return
        self._stepped_device_guid = value
        self._stepped_device_id = str(value)

    def display_name(self):
        """display name for this action"""
        if self.action_mode in (
            VjoyAction.VJoyAxis,
            VjoyAction.VJoySetAxis,
            VjoyAction.VJoyInvertAxis,
            VjoyAction.VJoyAxisToButton,
        ):
            return f"VJoy #{self._vjoy_id} Mode: {self.action_mode.name} Axis: {self.vjoy_axis_id}"
        elif self.action_mode in (
            VjoyAction.VJoyButtonPress,
            VjoyAction.VJoyButton,
            VjoyAction.VJoyToggle,
            VjoyAction.VJoyButtonRelease,
        ):
            return f"VJoy #{self._vjoy_id} Mode: {self.action_mode.name} Button: {self.vjoy_button_id}"
        elif self.action_mode in (VjoyAction.VJoyHat, VjoyAction.VJoyHatToButton):
            return f"VJoy #{self._vjoy_id} Mode: {self.action_mode.name} Hat: {self.vjoy_hat_id}"
        elif self.action_mode == VjoyAction.VJoyMergeAxis:
            stub = ""
            for index, data in enumerate(self._merge_data):
                device: dinput.DeviceSummary = gremlin.joystick_handling.getDevice(data.device_id)
                stub += f", merge[{index}] = device: {device.name} axis: {data.input_id}/{device.get_axis_name(data.input_id)} invert: [{data.invert}] operation: [{data.operation.name}]"
            return f"VJoy #{self._vjoy_id} Mode: {self.action_mode.name} Axis: {self.vjoy_axis_id} {stub} "
        else:
            return f"VJoy #{self._vjoy_id} Mode: {self.action_mode.name}"

    @property
    def paired(self):
        return self._paired

    @paired.setter
    def paired(self, value):
        self._paired = value

    @property
    def vjoy_input_id(self):
        return self._vjoy_input_id

    @vjoy_input_id.setter
    def vjoy_input_id(self, value):
        if self._vjoy_input_id != value:
            self._vjoy_input_id = value
            # input_type = self._get_input_type()
            # if input_type == InputType.JoystickAxis:
            #     syslog.info(f"vjoy axis set to : {value}")
            # self.data_changed.emit()

    @property
    def vjoy_axis_id(self):
        return self._vjoy_axis_id

    @vjoy_axis_id.setter
    def vjoy_axis_id(self, value: int):
        if self._vjoy_axis_id != value:
            self._vjoy_axis_id = value
            # input_type = self._get_input_type()
            # if input_type == InputType.JoystickAxis:
            #     syslog.info(f"vjoy axis set to : {value}")
            # self.data_changed.emit()

    def _get_input_type(self):
        """derives the vjoy input type for based on the action"""
        # input_type = self.get_input_type()
        input_type = None
        if self.action_mode in (
            VjoyAction.VJoySetAxis,
            VjoyAction.VJoyInvertAxis,
            VjoyAction.VJoyAxis,
            VjoyAction.VJoyMergeAxis,
            VjoyAction.VJoySetAxisStepped,
        ):
            input_type = InputType.JoystickAxis
        elif self.action_mode in (
            VjoyAction.VJoyHat,
            VjoyAction.VJoyHatPress,
            VjoyAction.VJoyHatPulse,
        ):
            input_type = self.input_type
        elif self.action_mode in (
            VjoyAction.VJoyButtonPress,
            VjoyAction.VJoyButtonRelease,
            VjoyAction.VJoyButton,
            VjoyAction.VJoyPulse,
            VjoyAction.VJoyHatToButton,
            VjoyAction.VJoyAxisToButton,
        ):
            input_type = InputType.JoystickButton
        else:
            syslog.warning(f"VJOYREMAP ICON: don't know how to handle action mode: {self.action_mode}")
        return input_type

    @property
    def action_mode(self) -> VjoyAction:
        if not self._action_mode:
            input_type = self.get_input_type()
            if input_type in VJoyRemapWidget.input_type_buttons:
                default_action_mode = VjoyAction.VJoyButtonPress
            elif input_type == InputType.JoystickHat:
                default_action_mode = VjoyAction.VJoyHat
            elif input_type == InputType.JoystickAxis:
                default_action_mode = VjoyAction.VJoyAxis
            else:
                default_action_mode = VjoyAction.VJoyButtonPress
            self.action_mode = default_action_mode

        return self._action_mode

    @action_mode.setter
    def action_mode(self, value: VjoyAction):
        self._action_mode = value
        # print (f"action mode set to : {value}")

        # sync the button mode with drop down style mode
        match self.action_mode:
            case VjoyAction.VJoyPulse:
                self.button_mode == ButtonOutputMode.Pulse
            case VjoyAction.VJoyButtonPress:
                self.button_mode == ButtonOutputMode.Press
            case VjoyAction.VJoyButton:
                self.button_mode == ButtonOutputMode.Hold
            case VjoyAction.VJoyButtonRelease:
                self.button_mode == ButtonOutputMode.Release

    @property
    def reverse(self):
        # axis reversed state
        return self._reverse

    @reverse.setter
    def reverse(self, value):
        self.usage_data.set_inverted(self.vjoy_id, self.vjoy_axis_id, value)
        self._reverse = value

    def toggle_reverse(self):
        # toggles reverse mode for the axis
        self.reverse = not self.reverse

    @property
    def reverse_configured(self) -> bool:
        """returns the configured reverse value rather than the live mode"""
        return self._reverse

    @property
    def grid_visible(self) -> bool:
        if self._grid_visible is None:
            # not set
            config = gremlin.config.Configuration()
            return config.button_grid_visible
        return self._grid_visible

    @grid_visible.setter
    def grid_visible(self, value: bool):
        if value != self._grid_visible:
            self._grid_visible = value

            el = gremlin.event_handler.EventListener()
            if el.get_control_state():
                # also update global if button grid is set to control
                config = gremlin.config.Configuration()
                config.button_grid_visible = value

                # also reset ALL vjoy remaps
                extra_data = {"value": value}
                gremlin.shared_state.current_profile.filter_actions(self.tag, self._update_grid_callback, extra_data)

            # notify all visible controls to update
            veh = gremlin.event_handler.VjoyRemapEventHandler()
            veh.grid_visible_changed.emit(value)

    def setGridVisible(self, value):
        self._grid_visible = value

    def _update_grid_callback(self, action: VjoyRemap, extra_data: dict = None):  # noqa: F821
        value = extra_data["value"]
        action.setGridVisible(value)

    def icon(self):
        """Returns the icon corresponding to the remapped input.

        :return icon representing the remap action
        """
        import gremlin.shared_state

        if self.action_mode in (
            VjoyAction.VJoyToggleRemote,
            VjoyAction.VJoyEnableRemoteOnly,
            VjoyAction.VJoyEnableLocalOnly,
            VjoyAction.VJoyDisableRemote,
            VjoyAction.VJoyDisableLocal,
            VjoyAction.VJoyEnableRemote,
            VjoyAction.VJoyEnableLocal,
            VjoyAction.VJoyEnableLocalAndRemote,
            VjoyAction.VJoyEnablePairedRemote,
            VjoyAction.VJoyDisablePairedRemote,
        ):
            return "fa6s.gear"

        is_dark = gremlin.shared_state.is_dark_theme
        prefix = "dark_" if is_dark else ""
        input_type = self._get_input_type()
        fallback = f"{prefix}joystick.png"

        suffix = None
        match input_type:
            case InputType.JoystickAxis:
                if self._vjoy_input_id > 8:
                    input_string = "button"
                    suffix = f"{self.vjoy_input_id:03d}.png"
                else:
                    input_string = "axis"
                    match self._vjoy_input_id:
                        case 1:
                            suffix = "x"
                        case 2:
                            suffix = "y"
                        case 3:
                            suffix = "z"
                        case 4:
                            suffix = "rx"
                        case 5:
                            suffix = "ry"
                        case 6:
                            suffix = "rz"
                        case 7:
                            suffix = "s1"
                        case 8:
                            suffix = "s2"

            case InputType.JoystickButton:
                if self.action_mode in (
                    VjoyAction.VJoyHat,
                    VjoyAction.VJoyHatPress,
                    VjoyAction.VJoyHatPulse,
                ):
                    position = (0, 0)
                    return gremlin.util.load_icon(vjoy.vjoy.Hat.getEightDirectionsIconMap()[position])
                else:
                    input_string = "button"
                    suffix = f"{self.vjoy_input_id:03d}"
                    fallback = "mdi.gesture-tap-button"
            case InputType.JoystickHat:
                if self._vjoy_input_id > 4:
                    input_string = "button"
                else:
                    input_string = "mdi.axis-arrow"
                    fallback = "mdi.axis-arrow"
            case _:
                input_string = None

        if input_string:
            if suffix:
                icon_path = f"{prefix}icon_{input_string}_{suffix}.png" if suffix else fallback
                icon_file = gremlin.util.find_icon(icon_path)
                if icon_file and os.path.isfile(icon_file):
                    return icon_file
            else:
                return input_string

        return fallback

    def requires_virtual_button(self):
        """Returns whether or not the action requires an activation condition.

        :return True if an activation condition is required, False otherwise
        """
        input_type = self.input_type

        if input_type in VJoyRemapWidget.input_type_buttons:
            return False
        elif input_type == InputType.JoystickAxis:
            if self.input_type == InputType.JoystickAxis:
                return False
            else:
                return True
        elif input_type == InputType.JoystickHat:
            return False
        else:
            return True

    def set_input_id(self, index):
        el = gremlin.event_handler.EventListener()
        if self.action_mode in (
            VjoyAction.VJoyAxis,
            VjoyAction.VJoyInvertAxis,
            VjoyAction.VJoySetAxis,
        ):
            if self.vjoy_axis_id != index:
                self.vjoy_axis_id = index
        elif self.action_mode in (
            VjoyAction.VJoyHat,
            VjoyAction.VJoyHatPress,
            VjoyAction.VJoyHatPulse,
        ):
            if self.vjoy_hat_id != index:
                self.vjoy_hat_id = index
        else:
            # button
            if self.vjoy_button_id != index:
                # notify of button usage change for the tracking
                el.set_vjoy_button_usage.emit(self._vjoy_id, self.vjoy_button_id, False, self.id)
                self.vjoy_button_id = index
                el.set_vjoy_button_usage.emit(self._vjoy_id, self.vjoy_button_id, True, self.id)
        self.vjoy_input_id = index

    def get_input_id(self):
        """returns input id based on the action mode"""
        if self.action_mode in (
            VjoyAction.VJoyAxis,
            VjoyAction.VJoyInvertAxis,
            VjoyAction.VJoySetAxis,
        ):
            return self.vjoy_axis_id
        elif self.action_mode in (
            VjoyAction.VJoyHat,
            VjoyAction.VJoyHatPress,
            VjoyAction.VJoyHatPulse,
        ):
            return self.vjoy_hat_id
        else:
            return self.vjoy_button_id

    def _parse_xml(self, node, data=None, extra_data=None):
        """Populates the data storage with data from the XML node.

        :param node XML node with which to populate the storage
        """

        try:
            vjoy_id = safe_read(node, "vjoy", int, 1)
            if vjoy_id not in self.vjoy_map:
                self.refresh_vjoy()  # ensure we have the latest device list

            if vjoy_id not in self.vjoy_map:
                syslog.error(f"Profile load: vjoy device {vjoy_id} was not found in the list of valid VJOY devices")
                self.vjoy_axis_id = 1
                self.vjoy_button_id = 1
                self.vjoy_hat_id = 1
                return

            self.vjoy_id = vjoy_id

            if "mode" in node.attrib:
                value = node.attrib["mode"]
                self.action_mode = VjoyAction.from_string(value)
            else:
                if self.input_type in VJoyRemapWidget.input_type_buttons:
                    default_action_mode = VjoyAction.VJoyButtonPress
                elif self.input_type == InputType.JoystickHat:
                    default_action_mode = VjoyAction.VJoyHat
                elif self.input_type == InputType.JoystickAxis:
                    default_action_mode = VjoyAction.VJoyAxis
                self.action_mode = default_action_mode

            self.vjoy_hat_position = (0, 0)
            if self.action_mode in (
                VjoyAction.VJoyHat,
                VjoyAction.VJoyHatPress,
                VjoyAction.VJoyHatPulse,
            ):
                if "position" in node.attrib:
                    self.vjoy_hat_position = vjoy.vjoy.Hat.getDirection(node.get("position"))
                if "return-position" in node.attrib:
                    self.vjoy_hat_return_position = vjoy.vjoy.Hat.getDirection(node.get("return-position"))

            if "input" in node.attrib:
                index = safe_read(node, "input", int, 1)
                self.set_input_id(index)

            for input_type in InputType.to_list():
                attrib_name = InputType.to_string(input_type)
                if attrib_name in node.attrib:
                    self.input_type = input_type
                    self.vjoy_input_id = safe_read(node, attrib_name, int, 1)
                    self.vjoy_axis_id = self.vjoy_input_id
                    self.vjoy_button_id = self.vjoy_input_id
                    break

            self.pulse_delay = 250
            self.merge_input_id = None
            self.merge_device_id = None

            if "grid-visible" in node.attrib:
                self._grid_visible = safe_read(node, "grid-visible", bool, False)

            # sync on start (axis input only)

            if "sync_on_start" in node.attrib:
                sync = safe_read(node, "sync_on_start", bool, False)
                if sync:
                    self.sync_mode = SyncMode.Input
            if "sync-mode" in node.attrib:
                self.sync_mode = SyncMode(safe_read(node, "sync-mode", int, 0))

            if "reverse" in node.attrib:
                self.reverse = safe_read(node, "reverse", bool, False)

            if "axis-type" in node.attrib:
                self.axis_mode = safe_read(node, "axis-type", str, "absolute")
            if "axis-scaling" in node.attrib:
                self.axis_scaling = safe_read(node, "axis-scaling", float, 1.0)

            if "pulse_delay" in node.attrib:
                value = safe_read(node, "pulse_delay", int, 250)
                self.pulse_delay = value
            if "start_pressed" in node.attrib:
                value = node.get("start_pressed")
                if value == "none":
                    self.button_start_value = None
                else:
                    self.button_start_value = safe_read(node, "start_pressed", bool, False)

            if "target_value" in node.attrib:
                self.target_value = safe_read(node, "target_value", float, 0.0)
                self.target_value_valid = True

            if "target-use-last" in node.attrib:
                self.target_use_last = safe_read(node, "target-use-last", bool, False)

            if "target_relative" in node.attrib:
                self.target_is_relative = safe_read(node, "target_relative", bool, False)

            if "relative_value" in node.attrib:
                relative_value = gremlin.util.clamp(safe_read(node, "relative_value", float, 0.1))
                if relative_value < 0:
                    relative_value = abs(relative_value)
                self.relative_value = relative_value

            if "use_relative_value" in node.attrib:
                self.use_relative_value = safe_read(node, "use_relative_value", bool, False)

            if "relative_pulse_delay" in node.attrib:
                self.relative_pulse_delay = safe_read(node, "relative_pulse_delay", int, 500)

            if "range_low" in node.attrib:
                self.button_range_min = safe_read(node, "range_low", float, -1.0)

            if "range_high" in node.attrib:
                self.button_range_max = safe_read(node, "range_high", float, 1.0)

            if "range_mode" in node.attrib:
                mode = safe_read(node, "range_mode", str, "")
                mode = mode.casefold()
                match mode:
                    case "noop":
                        mode = ButtonOutputMode.NoOp
                    case "hold":
                        mode = ButtonOutputMode.Hold
                    case "pulse":
                        mode = ButtonOutputMode.Pulse
                    case "press":
                        mode = ButtonOutputMode.Press
                    case "release":
                        mode = ButtonOutputMode.Release
                    case _:
                        # legacy mode
                        is_pulse = safe_read(node, "pulse", bool, False)
                        mode = ButtonOutputMode.Pulse if is_pulse else ButtonOutputMode.Hold
                self.button_mode = mode

            if "output_range_low" in node.attrib:
                self.output_range_min = safe_read(node, "output_range_low", float, -1.0)

            if "output_range_high" in node.attrib:
                self.output_range_max = safe_read(node, "output_range_high", float, 1.0)

            if "axis_start_value" in node.attrib:
                self.axis_start_value = safe_read(node, "axis_start_value", float, -1.0)

            self.exec_on_press = safe_read(node, "exec_on_press", bool, True)
            self.exec_on_release = safe_read(node, "exec_on_release", bool, False)

            if "paired" in node.attrib:
                self.paired = safe_read(node, "paired", bool, False)

            self.invert_merged_output = safe_read(node, "invert-merged-output", bool, False)

            self._merge_data.clear()

            if self.action_mode == VjoyAction.VJoyMergeAxis:
                # legacy
                if "merge_device_id" in node.attrib and "merge_input_id" in node.attrib:
                    device_id = node.get("merge_device_id")
                    device_id = gremlin.util.normalize_guid(device_id)
                    input_id = safe_read(node, "merge_input_id", int, 0)
                    if "merge_input_type" in node.attrib:
                        merge_input_type = safe_read(node, "merge_input_type", str, "")
                        merge_input_type = gremlin.input_types.InputType.to_enum(merge_input_type)
                    merge_mode = MergeOperationType.Center
                    if "merge_mode" in node.attrib:
                        mode = node.get("merge_mode")
                        try:
                            merge_mode = MergeOperationType.to_enum(mode)
                        except Exception as err:
                            syslog.error(f"Invalid MergeOperation {mode}:")
                            syslog.error(f"{err}\n{traceback.format_exc()}")

                    invert = safe_read(node, "merge_invert", bool, False)
                    data = MergeData(device_id, input_id, operation=merge_mode, invert=invert)
                    self._merge_data.append(data)

                else:
                    # as of m76t22 - multi-merge support
                    for child in node:
                        if child.tag == "merge-axis":
                            for data_node in child:
                                data = MergeData()
                                data.from_xml(data_node)
                                self._merge_data.append(data)

                            break

            if "merge_min" in node.attrib:
                self.output_range_min = safe_read(node, "merge_min", float, -1.0)
            if "merge_max" in node.attrib:
                self.output_range_max = safe_read(node, "merge_max", float, 1.0)

            if "grid_visible" in node.attrib:
                self.grid_visible = safe_read(node, "grid_visible", bool, True)

            if "auto_release" in node.attrib:
                self.auto_release = safe_read(node, "auto_release", bool, False)

            if "ignore-release" in node.attrib:
                self.ignore_release = safe_read(node, "ignore-release", bool, False)

            if "step-dir" in node.attrib:
                self.target_step_direction = safe_read(node, "step-dir", int, 1)

            if "steps" in node.attrib:
                csv = node.get("steps")
                self.target_step_list = gremlin.util.csv_to_floatlist(csv)

            self._stepped_latched = safe_read(node, "latched", bool, True)

            if "step-start-index" in node.attrib:
                self.target_step_start_index = safe_read(node, "step-start-index", int, 0)
            if "stepped-device-id" in node.attrib:
                self.stepped_device_id = node.get("stepped-device-id")

            if "stepped-input-id" in node.attrib:
                self.stepped_input_id = safe_read(node, "stepped-input-id", int, 0)

            self._target_step_linear_mode = safe_read(node, "linear", bool, False)
            self._target_step_delta = safe_read(node, "delta", float, 0.01)
            self._target_step_velocity = safe_read(node, "velocity", float, 0.01)
            if self._target_step_velocity < 0:
                self._target_step_velocity = 0.0
            self._target_step_acceleration = safe_read(node, "acceleration", float, 2.0)
            if self._target_step_acceleration < 0:
                self._target_step_acceleration = 0.0

            if "override-input-type" in node.attrib:
                input_type = safe_read(node, "override-input-type", str, "")
                self.override_input_type = gremlin.input_types.InputType.to_enum(input_type)

            if "pulse-delay" in node.attrib:
                self.pulse_delay = safe_read(node, "pulse-delay", int, 250)
            if "repeat" in node.attrib:
                self.pulse_repeat = safe_read(node, "repeat", bool, False)
            if "repeat-delay" in node.attrib:
                self.pulse_repeat_delay = safe_read(node, "repeat-delay", int, 250)

            # curve data

            curve_node = util.get_xml_child(node, "curve-data")
            if curve_node is None:
                # older style
                curve_node = util.get_xml_child(node, "response-curve-ex")
                if curve_node is None:
                    curve_node = util.get_xml_child(node, "response-curve")

            if curve_node is not None:
                self.curve_data = gremlin.curve_handler.AxisCurveData()
                self.curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.hardware_device_guid, self.hardware_input_id)
                self.curve_data._parse_xml(curve_node)
                self.curve_data.curve_update()

            # hat buttons
            if self.action_mode == VjoyAction.VJoyHatToButton:
                hat_nodes = util.get_xml_child(node, "hat_to_button", multiple=True)
                for node_hat in hat_nodes:
                    name = safe_read(node_hat, "name", str, "")
                    position = vjoy.vjoy.Hat.name_to_direction[name]
                    button_id = safe_read(node_hat, "input", int, 1)
                    self.hat_map[position] = button_id
                    mode = safe_read(node_hat, "mode", str, "")
                    match mode.casefold():
                        case "hold":
                            mode = ButtonOutputMode.Hold
                        case "pulse":
                            mode = ButtonOutputMode.Pulse
                        case "press":
                            mode = ButtonOutputMode.Press
                        case "release":
                            mode = ButtonOutputMode.Release
                        case _:
                            # legacy mode
                            is_pulse = safe_read(node_hat, "pulse", bool, False)
                            mode = ButtonOutputMode.Pulse if is_pulse else ButtonOutputMode.Hold

                    self.hat_mode_map[position] = mode

                if "hat_sticky" in node.attrib:
                    self.hat_sticky = safe_read(node, "hat_sticky", bool, False)

        except ProfileError:
            self.vjoy_input_id = None
            self.vjoy_id = None

    def _generate_xml(self):
        """Returns an XML node encoding this action's data.

        :return XML node containing the action's data
        """
        node = ElementTree.Element(VjoyRemap.tag)
        node.set("vjoy", str(self.vjoy_id))

        save_exec_on_release = VjoyAction.is_command(self.action_mode) or self.action_mode in (
            VjoyAction.VJoyButtonPress,
            VjoyAction.VJoyInvertAxis,
            VjoyAction.VJoySetAxis,
            VjoyAction.VJoyPulse,
        )

        if self.action_mode in (
            VjoyAction.VJoyHat,
            VjoyAction.VJoyHatPress,
            VjoyAction.VJoyHatPulse,
        ):
            position_name = vjoy.vjoy.Hat.getName(self.vjoy_hat_position)
            if position_name:
                node.set("position", position_name)
            position_name = vjoy.vjoy.Hat.getName(self.vjoy_hat_return_position)
            if position_name:
                node.set("return-position", position_name)
        else:
            node.set(InputType.to_string(self.input_type), str(self.vjoy_input_id))

        node.set("mode", safe_format(VjoyAction.to_string(self.action_mode), str))

        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))

        write_node_input = True

        if self.override_input_type is not None:
            node.set(
                "override-input-type",
                gremlin.input_types.InputType.to_string(self.override_input_type),
            )

        # node.set("sync_on_start", safe_format(self.sync_on_start, bool))
        node.set("sync-mode", safe_format(self.sync_mode, int))

        match self.action_mode:
            case VjoyAction.VJoyAxis:
                node.set("axis-type", safe_format(self.axis_mode, str))
                node.set("axis-scaling", safe_format(self.axis_scaling, float))
                node.set("axis_start_value", safe_format(self.axis_start_value, float))
                # node.set("axis_start_value_enabled", safe_format(self.axis_start_value_enabled, bool))
                node.set("range_low", safe_format(self.button_range_min, float))
                node.set("range_high", safe_format(self.button_range_max, float))
                node.set("output_range_low", safe_format(self.output_range_min, float))
                node.set("output_range_high", safe_format(self.output_range_max, float))
                reverse = safe_format(self.reverse_configured, bool)
                node.set("reverse", reverse)

            case VjoyAction.VJoyButtonPress:
                # button, command or
                if self.button_start_value is None:
                    node.set("start_pressed", "none")
                else:
                    node.set("start_pressed", safe_format(self.button_start_value, bool))

                node.set("paired", safe_format(self.paired, bool))

            case VjoyAction.VJoySetAxis:
                node.set("target-use-last", safe_format(self.target_use_last, bool))

            case VjoyAction.VJoyMergeAxis:
                node.set("invert-merged-output", safe_format(self.invert_merged_output, bool))

                if self._merge_data:
                    child = ElementTree.SubElement(node, "merge-axis")
                    for data in self._merge_data:
                        node_data = data.to_xml()
                        child.append(node_data)

                node.set("merge_invert", safe_format(self.merge_invert, bool))
                node.set("merge_min", safe_format(self.output_range_min, float))
                node.set("merge_max", safe_format(self.output_range_max, float))
                reverse = safe_format(self.reverse_configured, bool)
                node.set("reverse", reverse)

                # node.set("merge_input_type", gremlin.input_types.InputType.to_string(self.merge_input_type))

            case VjoyAction.VJoyPulse:
                # uses button mode below
                node.set("pulse_delay", safe_format(self.pulse_delay, int))
                if self.pulse_repeat:
                    node.set("repeat", safe_format(self.pulse_repeat, bool))
                    node.set("repeat-delay", safe_format(self.pulse_repeat_delay, int))

            case VjoyAction.VJoyAxisToButton:
                node.set("range_low", safe_format(self.button_range_min, float))
                node.set("range_high", safe_format(self.button_range_max, float))
                node.set("range_mode", safe_format(self.button_mode.name, str))

            case VjoyAction.VJoyHatToButton:
                for position, button_id in self.hat_map.items():
                    node_hat = ElementTree.Element("hat_to_button")
                    name = vjoy.vjoy.Hat.direction_to_name[position]
                    node_hat.set("name", name)
                    node_hat.set("input", safe_format(button_id, int))
                    mode = self.hat_mode_map[position]
                    node_hat.set("mode", mode.name)
                    # node_hat.set("pulse", safe_format(is_pulse, bool)) # legacy
                    node.append(node_hat)
                    write_node_input = False

                node.set("hat_sticky", safe_format(self.hat_sticky, bool))

            case VjoyAction.VJoySetAxisStepped:
                node.set("step-dir", safe_format(self.target_step_direction, int))
                node.set("steps", gremlin.util.floatlist_to_csv(self.target_step_list))
                node.set("step-start-index", safe_format(self.target_step_start_index, int))
                node.set("latched", safe_format(self._stepped_latched, bool))
                if self.stepped_device_id:
                    node.set("stepped-device-id", self.stepped_device_id)
                if self.stepped_input_id:
                    node.set("stepped-input-id", str(self.stepped_input_id))
                node.set("linear", safe_format(self._target_step_linear_mode, bool))
                node.set("velocity", safe_format(self._target_step_velocity, float))
                node.set("acceleration", safe_format(self._target_step_acceleration, float))
                node.set("delta", safe_format(self._target_step_delta, float))
                node.set("pulse_delay", safe_format(self.pulse_delay, int))

        node.set("auto_release", safe_format(self.auto_release, bool))
        node.set("ignore-release", safe_format(self.ignore_release, bool))
        if self._grid_visible is not None:
            node.set("grid-visible", safe_format(self.grid_visible, bool))

        node.set("target_value", safe_format(self.target_value, float))
        node.set("target_relative", safe_format(self.target_is_relative, bool))
        node.set("relative_value", safe_format(self.relative_value, float))
        node.set("use_relative_value", safe_format(self.use_relative_value, bool))
        node.set("relative_pulse_delay", safe_format(self.relative_pulse_delay, int))

        if self.button_mode == ButtonOutputMode.Pulse:
            node.set("pulse-delay", safe_format(self.pulse_delay, int))
            if self.pulse_repeat:
                node.set("repeat", safe_format(self.pulse_repeat, bool))
                node.set("repeat-delay", safe_format(self.pulse_repeat_delay, int))

        if self.curve_data is not None:
            curve_node = self.curve_data._generate_xml()
            node.append(curve_node)

        if VjoyAction.is_command(self.action_mode) or self.action_mode:
            node.set("start_pressed", safe_format(self.button_start_value, bool))
            node.set("paired", safe_format(self.paired, bool))

        if save_exec_on_release:
            node.set("exec_on_release", safe_format(self.exec_on_release, bool))

        node.set("grid_visible", safe_format(self.grid_visible, bool))

        if write_node_input:
            node.set("input", safe_format(self.vjoy_input_id, int))

        return node

    def _is_valid(self):
        """Returns whether or not the action is configured properly.

        :return True if the action is configured correctly, False otherwise
        """

        if self.vjoy_id is None or self.vjoy_input_id is None:
            return False
        return True

    def _get_output_name(self) -> str:
        if self.action_mode == VjoyAction.VJoyAxis:
            return "Axis"
        elif self.action_mode in (
            VjoyAction.VJoyHat,
            VjoyAction.VJoyHatPress,
            VjoyAction.VJoyHatPulse,
        ):
            return "Hat"
        elif self.action_mode in (
            VjoyAction.VJoyButton,
            VjoyAction.VJoyButtonPress,
            VjoyAction.VJoyAxisToButton,
            VjoyAction.VJoyButtonRelease,
            VjoyAction.VJoyHatToButton,
            VjoyAction.VJoyToggle,
        ):
            return "Button"
        else:
            return "Control"

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Mode", self.action_mode.name)
        table.addField("Vjoy Device", self.vjoy_id)
        table.addField("Output Type:", self._get_output_name())

        match self.action_mode:
            case VjoyAction.VJoyAxis:
                table.addField("Axis", f"{self.vjoy_axis_id}")

            case VjoyAction.VJoyMergeAxis:
                for data in self._merge_data:
                    device_id, input_id = data.key
                    device = gremlin.joystick_handling.getDevice(device_id)
                    assert device is not None, f"Unable to get device for id {device_id}"
                    table.addField(f"Merge: {device.name}", f"{input_id}")

            case VjoyAction.VJoyButton:
                table.addField("Button (hold)", f"{self.vjoy_button_id}")
            case VjoyAction.VJoyButtonPress:
                table.addField("Button (press)", f"{self.vjoy_button_id}")
            case VjoyAction.VJoyButtonRelease:
                table.addField("Button (release)", f"{self.vjoy_button_id}")
            case VjoyAction.VJoyToggle:
                table.addField("Button (toggle)", f"{self.vjoy_button_id}")
            case VjoyAction.VJoyAxisToButton:
                table.addField("Button (axis to button)", f"{self.vjoy_button_id}")
                table.addField(
                    "Range",
                    f"[{self.button_range_min:0.3f},{self.button_range_max:0.3f}]",
                )
                table.addField("Mode", f"{self.button_mode.name}")

            case VjoyAction.VJoyPulse:
                table.addField("Button (pulse)", f"{self.vjoy_button_id}")
                table.addField("Pulse Delay", f" {self.pulse_delay}ms")
                if self.pulse_repeat:
                    table.addField("Pulse Repeat", "yes")
                    table.addField("Repeat Delay", f"Repeat Delay: {self.pulse_repeat_delay}ms")

            case VjoyAction.VJoyInvertAxis:
                table.addField("Invert Axis", "yes")

            case VjoyAction.VJoySetAxis:
                if self.use_relative_value:
                    table.addField("Relative Axis", f"{self.target_value:0.3f}")
                else:
                    table.addField("Set Axis", f"{self.target_value:0.3f}")

            case VjoyAction.VJoyDisableLocal:
                table.addField("Control", "Disable local control")

            case VjoyAction.VJoyDisablePairedRemote:
                table.addField("Control", "Disable paired remote")

            case VjoyAction.VJoyEnableLocal:
                table.addField("Control", "Enable local control")

            case VjoyAction.VJoyEnableLocalAndRemote:
                table.addField("Control", "Enable local and remote control")

            case VjoyAction.VJoyEnableRemote:
                table.addField("Control", "Disable remote control")

            case VjoyAction.VJoyHat:
                table.addField("Set Hat Position", "")

            case VjoyAction.VJoyHatToButton:
                for position in self.hat_map:
                    input_id = self.action_data.hat_map[position]
                    table.addField(f"{vjoy.vjoy.Hat.direction_to_name(position)}", f"{input_id}")

            case VjoyAction.VJoySetAxisStepped:
                pass

            case _:
                pass

        return table.to_html()

    def report_record(self) -> tuple:
        """returns reporting row record data for this action in graphvis format"""

        label = ""
        label += f"| Mode | {VjoyAction.to_description(self.action_mode)} "
        label += f"| VJoy ID | {self.vjoy_id}"

        content = ""

        match self.action_mode:
            case VjoyAction.VJoyAxis:
                content += f"Axis | {self.vjoy_axis_id}"
            case VjoyAction.VJoyMergeAxis:
                content += "Merge"
                subcontent = ""
                for data in self.action_data._merge_data:
                    device_id, input_id = data.key
                    device = gremlin.joystick_handling.getDevice(device_id)
                    subcontent += f"{device.name} | Axis: {input_id}"
                content += f"| {{{subcontent}}}"
            case VjoyAction.VJoyButton:
                content += f"Button Hold | {self.vjoy_button_id}"
            case VjoyAction.VJoyButtonPress:
                content += f"Button Press | {self.vjoy_button_id}"
            case VjoyAction.VJoyButtonRelease:
                content += f"Button Release | {self.vjoy_button_id}"
            case VjoyAction.VJoyToggle:
                content += f"Button Toggle | {self.vjoy_button_id}"
            case _:
                content += f"{self.action_mode.name}"

        if content:
            label += f"| {{{content}}}"

        return label

    def __str__(self):
        if self.action_mode in (
            VjoyAction.VJoySetAxis,
            VjoyAction.VJoyInvertAxis,
            VjoyAction.VJoyAxis,
        ):
            input_string = "axis"
        elif self.action_mode in (
            VjoyAction.VJoyHat,
            VjoyAction.VJoyHatPress,
            VjoyAction.VJoyHatPulse,
        ):
            input_string = "hat"
        elif self.action_mode in (
            VjoyAction.VJoyButtonPress,
            VjoyAction.VJoyButtonRelease,
            VjoyAction.VJoyPulse,
            VjoyAction.VJoyHatToButton,
            VjoyAction.VJoyButton,
        ):
            input_string = "button"
        elif self.action_mode == VjoyAction.VJoyMergeAxis:
            input_string = "merge axis"
        elif self.action_mode == VjoyAction.VJoySetAxisStepped:
            input_string = "stepped axis"
        else:
            input_string = f"unhandled: [{self.action_mode.name}]"
        return f"VjoyRemap: VJOY device: {self.vjoy_id} {input_string}: {self.vjoy_input_id}"


version = 1
name = "Vjoy Remap"
create = VjoyRemap
