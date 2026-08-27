# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
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
from typing import Callable
import logging

from PySide6 import QtWidgets, QtCore


from dinput import DeviceSummary

import gremlin.config
import gremlin.ui.ui_common
import gremlin.base_profile
import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.input_types import InputType
import gremlin.ui
import gremlin.input_item
import gremlin.util
import gremlin.ui.ui_common
from shiboken6 import Shiboken
from psygnal import Signal
import gremlin.util
from gremlin.util import parse_bool, safe_read, safe_format, parse_guid, write_guid, load_icon
from gremlin.input_item import InputItem, BaseAbstractCondition, AbstractConditionWidget, AbstractContainer, AbstractAction, AbstractCondition
import dinput


syslog = logging.getLogger("system")

# Prevent stacked Curve Editor dialogs when multiple device tabs still hold
# stale EventListener.curve_edit connections (cleanup used to skip disconnect).
_active_curve_dialog = None


class BaseJoystickCondition(BaseAbstractCondition):
    """Joystick state based condition.

    This condition is based on the state of a joystick axis, button, or hat.
    """

    def __init__(self, extra_data: dict = None, target : AbstractContainer | AbstractAction = None):
        """Creates a new instance."""
        super().__init__(extra_data, target = target)
        self.device_guid = 0  # use this as the invalid GUID
        self.input_type = None
        self.input_id = 0
        self.range = [0.0, 0.0]
        self.device_name = ""
        self.use_calibrated_data = True  # true if the input should use the calibrated data if any
        self.ignore_release = False  # true if the condition always succeeds on input release

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """

        super().from_xml(node, data, extra_data)

        self.input_type = InputType.to_enum(safe_read(node, "input", str, ""))
        comparison = safe_read(node, "comparison", str, "")
        if not comparison:
            match self.input_type:
                case InputType.JoystickAxis:
                    comparison = "inside"
                case InputType.JoystickButton:
                    comparison = "pressed"
                case InputType.JoystickHat:
                    comparison = "center"
        self.comparison = comparison

        self.input_id = safe_read(node, "id", int, 1)
        self.device_guid = parse_guid(node.get("device-guid"))
        self.device_name = safe_read(node, "device-name", str, "")
        self.range = [
            safe_read(node, "range-low", float, 0),
            safe_read(node, "range-high", float, 0),
        ]
        self.use_calibrated_data = safe_read(node, "use-calibrated", bool, False)
        self.ignore_release = safe_read(node, "ignore-release", bool, False)

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        # node = lxml.etree.Element("condition")
        node = super().to_xml()
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "joystick")
        node.set("input", InputType.to_string(self.input_type))
        node.set("id", safe_format(self.input_id, int))
        node.set("device-guid", write_guid(self.device_guid))
        node.set("device-name", str(self.device_name))
        node.set("range-low", safe_format(self.range[0], float))
        node.set("range-high", safe_format(self.range[1], float))
        node.set("ignore-release", safe_format(self.ignore_release, bool))
        node.set("use-calibrated", safe_format(self.use_calibrated_data, bool))

        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return self.input_type is not None  # super().is_valid() and self.input_type is not None

    def __str__(self):
        return f"Joystick Condition: id: {self.id} comparison: {self.comparison} input type: {self.input_type.name} device: {self.device_name} input id: {self.input_id}  range: [{self.range[0]:0.3f},{self.range[0]:0.3f}]  use calibrated: {self.use_calibrated_data}"

    def to_html(self) -> str:
        """html output version"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Condition", "Joystick")
        table.addField("Comparison", self.comparison)
        table.addField("Device", self.device_name)
        table.addField("Type", self.input_type.name)
        table.addField("ID", f"{self.input_id}")
        if self.input_type == InputType.JoystickAxis:
            table.addField("Range", f"[{self.range[0]:0.3f},{self.range[1]:0.3f}]")
            table.addField("Use calibrated data", "Yes" if self.use_calibrated_data else "No")

        table.addField("Ignore release", "Yes" if self.ignore_release else "No")
        return table.to_html()


class JoystickConditionWidget(AbstractConditionWidget):
    """Widget allowing the configuration of a joystick based condition."""

    def __init__(self,
                condition: AbstractCondition | BaseAbstractCondition,
                remove_callback : Callable = None,
                extra_data: dict = None,
                parent=None):

        super().__init__(condition, remove_callback=remove_callback, extra_data=extra_data, parent=parent)
        self.input_event = None
        self.setTitle("Joystick Condition")

    def _create_ui(self, extra_data: dict = None):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return

        gremlin.ui.ui_common.clear_layout(self.main_layout)

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback=self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback=self._paste_condition)

        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label="Listen", callback=self._request_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            callback=self.handle_remove,
            tooltip="Delete condition",
        )

        widgets, layout = gremlin.ui.ui_common.getHContainer(
            [
                self.copy_widget,
                self.paste_widget,
                self.record_button_widget,
                self.delete_button_widget,
            ]
        )

        self.delay_widget = None

        self.main_layout.addWidget(QtWidgets.QLabel("Activate if:"))

        self.device_selector_widget = gremlin.ui.ui_common.QLimitedComboBox()
        self.device_selector_widget.currentIndexChanged.connect(self._device_selected)
        self.input_selector_widget = gremlin.ui.ui_common.QLimitedComboBox()
        self.input_selector_widget.currentIndexChanged.connect(self._input_selected)
        # self.axis_repeater_widget = ui_common.QAxisRepeaterProgressbar()  # todo: determin parameters for the axis repeater for conditions
        # self.axis_repeater_widget.valueChanged.connect(self._axis_value_changed)

        self.use_calibrated_input_widget = QtWidgets.QCheckBox("Use calibrated input")
        self.use_calibrated_input_widget.setToolTip(
            "When enabled, the condition will use as input the calibrated data if found.  When disabled, the condition will use the raw input."
        )
        self.use_calibrated_input_widget.setChecked(self.condition.use_calibrated_data)
        self.use_calibrated_input_widget.clicked.connect(self._use_calibrated_input_changed)

        self.selector_container_widget = QtWidgets.QWidget()
        self.selector_container_layout = QtWidgets.QGridLayout(self.selector_container_widget)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Device:"), 0, 0)
        self.selector_container_layout.addWidget(self.device_selector_widget, 0, 1)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Input:"), 1, 0)
        self.selector_container_layout.addWidget(self.input_selector_widget, 1, 1)
        # self.selector_container_layout.addWidget(self.axis_repeater_widget, 2, 1)

        self.selector_container_layout.addWidget(QtWidgets.QWidget(), 0, 2)  # spacer column

        self.selector_container_layout.addWidget(widgets, 0, 4)
        self.selector_container_layout.setColumnStretch(2, 2)

        self.range_status_widget = None

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        self.options_container_widget = QtWidgets.QWidget()
        self.options_container_widget.setContentsMargins(0, 0, 0, 0)
        self.options_container_layout = QtWidgets.QHBoxLayout(self.options_container_widget)
        self.options_container_layout.setContentsMargins(0, 0, 0, 0)

        self.options_container_layout.addWidget(self.use_calibrated_input_widget)

        self.main_layout.addWidget(self.selector_container_widget)
        self.main_layout.addWidget(self.ui_container_widget)
        self.main_layout.addWidget(self.options_container_widget)

        self._populate_device_selector()
        self._populate_input_selector()

    @QtCore.Slot()
    def _device_selected(self):
        """device changed, update input list"""
        device = self.device_selector_widget.currentData()
        self.condition.device_guid = device.device_guid
        self._populate_input_selector()

    @QtCore.Slot()
    def _input_selected(self):

        device: gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        input_type, input_id = self.input_selector_widget.currentData()
        self.condition.device_guid = device.device_guid
        self.condition.input_type = input_type
        self.condition.input_id = input_id
        self.condition.device_name = device.name

        self._init_ui()

    def _populate_device_selector(self):
        device_guid = self.condition.device_guid
        current_index = None
        with QtCore.QSignalBlocker(self.device_selector_widget):
            self.device_selector_widget.clear()
            index = 0
            device: gremlin.joystick_handling.DeviceSummary
            for device in gremlin.joystick_handling.physical_devices():
                self.device_selector_widget.addItem(device.name, device)
                if current_index is None and device_guid and device.device_guid == device_guid:
                    current_index = index
                index += 1

            if current_index is not None:
                self.device_selector_widget.setCurrentIndex(current_index)

        # update condition for the selected device
        device: gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        self.condition.device_guid = device.device_guid

    def _populate_input_selector(self):

        input_id = self.condition.input_id
        input_type = self.condition.input_type
        device: gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()

        with QtCore.QSignalBlocker(self.input_selector_widget):
            self.input_selector_widget.clear()

            index = 0  # index of the entry
            current_index = None  # index of the input to select

            # axes - axes are not necessarily sequential
            for i in device.axis_index_list():
                axis_name = device.get_axis_name(i)
                self.input_selector_widget.addItem(axis_name, (InputType.JoystickAxis, i))
                if current_index is None and input_id == i and input_type == InputType.JoystickAxis:
                    current_index = index
                index += 1

            # buttons
            for i in range(device.button_count):
                button_name = device.get_button_name(i + 1)
                self.input_selector_widget.addItem(button_name, (InputType.JoystickButton, i + 1))
                if current_index is None and input_id == i + 1 and input_type == InputType.JoystickButton:
                    current_index = index
                index += 1

            # hats
            for i in range(device.hat_count):
                hat_name = f"Hat {i + 1}"
                self.input_selector_widget.addItem(hat_name, (InputType.JoystickHat, i + 1))
                if current_index is None and input_id == i + 1 and input_type == InputType.JoystickHat:
                    current_index = index
                index += 1

            if current_index is not None:
                self.input_selector_widget.setCurrentIndex(current_index)

            input_type, input_id = self.input_selector_widget.currentData()
            self.condition.input_type = input_type
            self.condition.input_id = input_id

            # update the other UI based on input type
            self._init_ui()

    def _init_ui(self):
        input_type = self.condition.input_type
        # axis_visible = False
        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
                # self.axis_repeater_widget.setInput(
                #     device_guid = self.condition.device_guid,
                #     input_id = self.condition.input_id,
                # )
                # axis_visible = True

            case InputType.JoystickButton:
                self._button_ui()

            case InputType.JoystickHat:
                self._hat_ui()

        # self.axis_repeater_widget.setVisible(axis_visible)
        self._update_ui()

    def _update_ui(self):
        """updates UI based on input type"""
        gremlin.util.assert_ui_thread()
        # visible = False
        # self.axis_repeater_widget.setVisible(visible)

        if self.delay_widget:
            input_type = self.condition.input_type
            visible = input_type == InputType.JoystickButton and self.condition.comparison in ("notchangedin", "changedin")
            self.delay_widget.setVisible(visible)

    def _axis_ui(self):
        """Creates the UI needed to configure an axis based condition."""

        gremlin.util.clear_layout(self.ui_container_layout)
        self.lower_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.lower_widget.setMinimum(-1.0)
        self.lower_widget.setMaximum(1.0)

        self.grab_low_widget = gremlin.ui.ui_common.QDataPushButton()
        self.grab_low_widget.setIcon(gremlin.ui.ui_common.Icons.recordIcon())
        self.grab_low_widget.setMaximumWidth(20)
        self.grab_low_widget.clicked.connect(self._grab_low)
        self.grab_low_widget.setToolTip("Grab axis value")

        self.lower_widget.setValue(self.condition.range[0])
        self.lower_widget.valueChanged.connect(self._range_lower_changed_cb)

        self.upper_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.upper_widget.setMinimum(-1.0)
        self.upper_widget.setMaximum(1.0)

        self.upper_widget.setValue(self.condition.range[1])
        self.upper_widget.valueChanged.connect(self._range_upper_changed_cb)

        self.grab_high_widget = gremlin.ui.ui_common.QDataPushButton()
        self.grab_high_widget.setIcon(
            load_icon(
                "mdi.checkbox-blank-circle",
                qta_color=gremlin.ui.ui_common.Color.recordColor(),
            )
        )
        self.grab_high_widget.setMaximumWidth(20)
        self.grab_high_widget.clicked.connect(self._grab_high)
        self.grab_high_widget.setToolTip("Grab axis value")

        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Inside")
        self.comparison_dropdown.addItem("Outside")
        if self.condition.comparison not in ("inside", "outside"):
            self.condition.comparison = "inside"

        self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.setCallback(self._comparison_changed_cb)

        self.range_status_widget = gremlin.ui.ui_common.QIconLabel()
        self.range_status_widget.setIcon(
            "mdi.checkbox-marked-outline",
            color=gremlin.ui.ui_common.Color.activeColor(),
        )

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(self.comparison_dropdown)
        range_layout.addWidget(self.lower_widget)
        range_layout.addWidget(self.grab_low_widget)

        range_layout.addWidget(gremlin.ui.ui_common.QLabel("and"))
        range_layout.addWidget(self.upper_widget)
        range_layout.addWidget(self.grab_high_widget)
        range_layout.addWidget(self.range_status_widget)
        range_layout.addStretch()

        input_label = QtWidgets.QLabel(f"<b>{self.condition.device_name} Axis {self.condition.input_id:d}</b>")
        input_label.setWordWrap(True)
        self.ui_container_layout.addWidget(input_label, 0, 1)
        self.ui_container_layout.addWidget(gremlin.ui.ui_common.QLabel("is"), 0, 2)
        self.ui_container_layout.addLayout(range_layout, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.ui_container_layout.setColumnStretch(4, 2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

        self._update_range_state(self._axis_value())

    def _axis_value(self):
        if self.condition.use_calibrated_data:
            value = gremlin.joystick_handling.get_axis(self.condition.device_guid, self.condition.input_id)
        else:
            value = gremlin.joystick_handling.get_curved_axis(self.condition.device_guid, self.condition.input_id)
        return value

    def _button_ui(self):
        """Creates the UI needed to configure a button based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Pressed", "pressed")
        self.comparison_dropdown.addItem("Released", "released")
        self.comparison_dropdown.addItem("Changed In", "changedin")
        self.comparison_dropdown.addItem("Not Changed In", "notchangedin")
        self.comparison_dropdown.setWidthToContent()
        if self.condition.comparison not in (
            "pressed",
            "released",
            "notchangedin",
            "changedin",
        ):
            self.condition.comparison = "pressed"

        index = self.comparison_dropdown.findData(self.condition.comparison)
        if index != -1:
            self.comparison_dropdown.setCurrentIndex(index)

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(
            self.condition.delay,
            is_seconds=True,
            show_shortcuts=False,
            label="Delay (s):",
            callback=self._handle_delay_changed,
        )

        self.comparison_dropdown.setCallback(self._comparison_changed_cb)

        self.ui_container_layout.addWidget(
            QtWidgets.QLabel(f"<b>{self.condition.device_name} Button {self.condition.input_id:d}</b>"),
            0,
            1,
        )
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)

        widgets = [self.comparison_dropdown, self.delay_widget]
        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.ui_container_layout.addWidget(widget, 0, 3, alignment=QtCore.Qt.AlignLeft)

        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip(
            "When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events."
        )
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget, 0, 5)
        self.ui_container_layout.setColumnStretch(5, 2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

        self._update_ui()

    def _handle_delay_changed(self, value: float):
        gremlin.util.InvokeUiMethod(self._handle_delay_changed_ui, value)

    def _handle_delay_changed_ui(self, value: float):
        self.condition.delay = value

    def _hat_ui(self):
        """Creates the UI needed to configure a hat based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        directions = [
            "Center",
            "North",
            "North East",
            "East",
            "South East",
            "South",
            "South West",
            "West",
            "North West",
        ]

        self.comparison_dropdown = gremlin.ui.ui_common.QHatSelectorComboBox()
        if not self.condition.comparison or self.condition.comparison.capitalize() not in directions:
            self.condition.comparison = "center"

        self.comparison_dropdown.setValue(self.condition.comparison)
        self.comparison_dropdown.valueChanged.connect(self._comparison_changed_cb)

        input_name = f"<b>{self.condition.device_name} Hat {self.condition.input_id}</b>"

        self.ui_container_layout.addWidget(QtWidgets.QLabel(input_name), 0, 1)
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget, 0, 5)

        self.ui_container_layout.setColumnStretch(6, 2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

    @QtCore.Slot(object)
    def _input_pressed_cb(self, event):
        """Processes input events to update the UI and model.

        :param event the input event to process
        """
        self.condition.device_guid = event.device_guid
        self.condition.input_type = event.event_type
        self.condition.input_id = event.identifier

        self.condition.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid)  # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition.comparison = gremlin.util.hat_tuple_to_direction(event.value)
        self._create_ui()

    @QtCore.Slot()
    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""
        self.input_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
            return_kb_event=False,
            multi_keys=False,
        )
        self.input_dialog.item_selected.connect(self._input_pressed_cb)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.input_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        self.input_dialog.show()

    @QtCore.Slot(float)
    def _range_lower_changed_cb(self, value):
        """Updates the lower part of an axis range.

        :param value the new value
        """
        self.condition.range[0] = value

    @QtCore.Slot(float)
    def _range_upper_changed_cb(self, value):
        """Updates the upper part of an axis range.

        :param value the new value
        """
        self.condition.range[1] = value

    @QtCore.Slot()
    def _grab_low(self):
        self.lower_widget.setValue(self._axis_value())  # also updates condition_data

    @QtCore.Slot()
    def _grab_high(self):
        self.upper_widget.setValue(self._axis_value())  # also updates condition_data

    @QtCore.Slot(bool)
    def _use_calibrated_input_changed(self, checked: bool):
        self.condition.use_calibrated_data = checked
        self._update_range_state(self._axis_value())

    @QtCore.Slot(float, float)
    def _axis_value_changed(self, value: float, curved_value: float):
        self._update_range_state(value)

    def _update_range_state(self, value):
        gremlin.util.InvokeUiMethod(self._update_range_state_ui, value)  # ensure UI thread

    def _update_range_state_ui(self, value):
        """updates the range flag based on the input value"""
        if not Shiboken.isValid(self.range_status_widget):
            return
        if self.range_status_widget:
            visible = False

            v1, v2 = self.condition.range
            in_range = gremlin.util.valueInRange(value, v1, v2)
            match self.condition.comparison:
                case "inside":
                    if in_range:
                        self.range_status_widget.setText("in range")
                        visible = True

                case "outside":
                    if not in_range:
                        self.range_status_widget.setText("outside of range")
                        visible = True

            self.range_status_widget.setVisible(visible)

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, data):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        if data:
            if self.condition.input_type == InputType.JoystickButton:
                self.condition.comparison = data
            elif self.condition.input_type == InputType.JoystickHat:
                self.condition.comparison = gremlin.types.HatDirection.to_string(data)
            elif self.condition.input_type == InputType.JoystickAxis:
                self.condition.comparison = data
                self._update_range_state(self._axis_value())
            else:
                syslog.warning(f"Invalid input type encountered: {self.condition.input_type}")

            self._update_ui()

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked: bool):
        self.condition.ignore_release = checked


class JoystickInputItemModel(gremlin.input_item.InputItemListModel):
    """model for the list of input items for a joystick device"""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        device_guid: str,
        mode: str,
        custom_load_handler: Callable = None,
        custom_remove_handler: Callable = None,
        custom_filter_handler: Callable = None,
        show_filtered_only=False,
    ):
        """creates a new model for the input items of a joystick device

        :param profile the profile data for the device this model represents
        :param device_guid the GUID of the device this model represents
        :param mode the current mode to display inputs for
        :param custom_filter_handler a handler that takes an input item and returns true if it should be filtered (not displayed) or false if it should be visible
        :param show_filtered_only if true only show filtered items, if false show all items with filtered items visually indicated
        """
        super().__init__(
            profile=profile,
            device_guid=device_guid,
            mode=mode,
            allowed_types=[
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat,
            ],
            custom_sort_handler=self._custom_sort,
            custom_load_handler=custom_load_handler,
            custom_remove_handler=custom_remove_handler,
            custom_filter_handler=custom_filter_handler,
            show_filtered_only=show_filtered_only,
        )

    def _custom_sort(self, items):
        """sorting for joystick devices has axes first, buttons next, hats last"""
        data = [(item, item.sortKey) for item in items]
        data.sort(key=lambda x: x[1])
        # sequence the list
        indices = (data.index(x) for x in data)
        return indices


class JoystickDeviceTabWidget(gremlin.input_item.BaseDeviceTabWidget):
    """Widget used to display the input joystick device."""

    inputChanged = Signal(str, object, object)  # indicates the input selection changed sends (device_guid string, input_type, input_id)

    def __init__(
        self,
        device: DeviceSummary,
        profile: gremlin.base_profile.Profile,
        mode: str,
        object_name="Joystick",
        data=None,
        parent=None,
    ):
        """Creates a new object instance.

        :param device device information about this widget's device
        :param profile profile data of the entire device
        :param mode the current mode to display
        :param parent the parent of this widget
        """

        assert isinstance(device, DeviceSummary), "Device invalid"

        self.device_guid = device.device_guid
        super().__init__(
            device=device,
            profile=profile,
            mode=mode,
            object_name=object_name,
            enable_filter=True,
            parent=parent,
        )

        config = gremlin.config.Configuration()

        # Store parameters

        self.data: gremlin.ui.tab = data

        self._refresh_lock = False  # semaphore to block refresh in progress
        self.hook_id = gremlin.util.get_guid()
        self.curve_update_handler = {}  # map of curve handlers to the input by index

        self.device = device
        self.profile = profile
        profile.ensure_mode_exists(mode)
        self.device_profile = profile.getDeviceNode(self.device_guid)

        profile = gremlin.shared_state.current_profile

        # self.widget_tracker = gremlin.ui.ui_common.DeviceWidgetTracker() # caches the  InputConfigurationItem for this item
        self.last_item_data_key = None
        self._last_selected_index = _index = 0
        self._last_selected_input_item = None
        self.device_guid = device.device_guid

        self.device_name = device.name
        self._debug_widget = None
        self._input_dirty = False  # true if the input list should be refreshed

        self._last_selected_index = 0  # last selected index in the list

        # if device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
        #     self.inputItemListView.limit_input_types([InputType.JoystickAxis])

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(2)
        if verbose:
            device = gremlin.joystick_handling.getDevice(self._device_guid)
            syslog.info(f"Create Joystick Device tab widget: for [{device.name}]")
            if "left" in device.name.casefold():
                pass

            profile.settings.dump_visible_map(self.device_guid)

        # model that holds all the input items for the joystick device
        model = JoystickInputItemModel(
            profile=profile,
            device_guid=device.device_guid,
            mode=mode,
            custom_load_handler=self._load_handler,
            custom_remove_handler=self._remove_handler,
            custom_filter_handler=self._filter_data,
            show_filtered_only=True,
        )

        self.setInputItemListModel(model)
        model.addCallback(self._handle_model_changed)  # listen to model changes

        # Handle vJoy as input and vJoy as output devices properly

        vjoy_as_input = profile.settings._vjoy_as_input

        # For vJoy as output only show axes entries, for all others treat them
        # as if they were physical input devices

        # device stats
        self.stats: gremlin.base_profile.JoystickInputStats = profile.settings.getJoystickInputStats(device.device_guid)
        self.stats_widget = gremlin.ui.ui_common.QJoystickInputWidget(device.device_guid)
        self.stats_widget.setStats(self.stats)

        # Add modifiable device label

        line_edit = gremlin.ui.ui_common.QDataLineEdit()
        line_edit.setText(profile.getDeviceLabel(device.device_guid))
        line_edit.textChanged.connect(self.update_device_label)

        # lock widget (add filter for joystick devices)
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data=self.device_guid, filter=True, filter_enabled=True)
        lock_widget.filterChanged.connect(self._handle_filter_changed)

        widget = gremlin.ui.ui_common.getHContainer([self.stats_widget, "||", lock_widget], widget_only=True)

        self.addLeftPanelHeaderWidget(widget)

        width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())

        grids = []

        widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Label:", widget_only=True)
        line_edit.setMinimumWidth(width)
        self.addLeftPanelHeaderWidget(widget)

        grids.append(widget)

        if config.show_container_id:
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            grids.append(widget)

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            grids.append(widget)

        gremlin.ui.ui_common.synchronize_grids(grids)

        # Add a help text for the purpose of the vJoy tab
        if device is not None and device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
            # msg = '''
            #     This tab allows assigning a response curve to virtual axis.
            #     The purpose of this is to enable split and merge axis to be
            #     customized to a user's needs with regards to dead zone and
            #     response curve.
            #     '''
            msg = "Virtual Input Device"
            widget = gremlin.ui.ui_common.QInfoBox(msg)
            self.addLeftPanelHeaderWidget(widget)

        config = gremlin.config.Configuration()

        if config.debug_ui:
            self._debug_widget = QtWidgets.QLabel("Debug widget")
            self._debug_widget.setMaximumHeight(32)
            self.addRightPanelWidget(self._debug_widget)

        el = gremlin.event_handler.EventListener()
        # update on an edit mode change so we update the display
        el.edit_mode_changed.connect(self._handle_edit_mode_changed)
        # update display on config change
        el.config_changed.connect(self._config_changed_cb)
        el.curve_edit.connect(self._edit_curve_item_cb)
        el.curve_delete.connect(self._delete_curve_item_cb)

        self.updating = False
        self.last_event = None

    def _load_handler(self, model: JoystickInputItemModel, emit=True) -> bool:
        """called when the data model for the input list needs to be updated - refreshes the model view"""

        model.pushSuspend()  # suspend triggers
        model.clear(emit=False)

        # device : dinput.DeviceSummary = gremlin.joystick_handling.getDevice(self.device_guid)
        # if device.is_virtual and device.vjoy_id == 4:
        #     pass

        registry = gremlin.shared_state.current_profile.registry
        mode = gremlin.shared_state.edit_mode
        input_list = registry.getInputItems(self.device_guid, mode, (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat))
        if not input_list:
            # retry default init
            profile = gremlin.shared_state.current_profile
            profile.ensureInputItems(self.device_guid, True)
            profile.setFilterDefaults(self.device_guid, True)
            input_list = registry.getInputItems(self.device_guid, mode, (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat))

        if len(input_list) > 0:
            input_list.sort(key=lambda x: x.sortKey)
            for index, input_item in enumerate(input_list):
                model.setItemAt(index, input_item)

            # filter the inputs
            model.applyFilter(emit=False)

        model.popSuspend()  # resume triggers
        if emit:
            model.trigger()  # causes an update
        return True

    def _remove_handler(self, model: JoystickInputItemModel, index, emit_change=True):
        """clears a single index"""
        if index in model._index_map:
            del model._index_map[index]
            item = next((key for key, data in model._item_map.items() if data == index), None)
            if item:
                del model._item_map[item]

            model._update_filter()

    def _filter_data(self, input_item: InputItem):
        """custom filter handled - true if the item is included in the list, false if not"""
        profile = gremlin.shared_state.current_profile
        # filtered = true if the input should not be displayed (filtered), false if it should be visible
        visible = profile.settings.getInputVisible(input_item.device_guid, input_item.input_type, input_item.input_id)
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            device = gremlin.joystick_handling.getDevice(input_item.device_guid)
            syslog.info(f"custom filter for input [{device.name}] [{input_item.display_name}] visible: {visible}")
        return visible

    def onInputListViewCreated(self):
        """called when the list view is created"""

        assert self.stats is not None, "stats should be created before listview"
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info("JoystickDevice: update stats on list view create")

        self.update_stats_display(refresh=True)

    def _handle_model_changed(self, data, force : bool = False):
        """called when the input model changes to update the display of stats and filter status"""
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info("JoystickDevice: update stats on model change")
        self.update_stats_display(refresh=True)

    def setInputVisible(self, input_item: InputItem, visible: bool, emit=False):
        """ensures the given input item is visible in the list view"""
        settings = self.profile.settings
        settings.setInputVisible(input_item.device_guid, input_item.input_type, input_item.input_id, visible, emit=emit)

    def getDefaultFilter(self) -> dict:
        """gets the default filter for the given device"""

        device_guid = self.device_guid
        device = gremlin.joystick_handling.getDevice(device_guid)
        profile: gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        settings: gremlin.base_profile.Settings = profile.settings

        # see if the profile has a default input setup saved for this input

        if settings.hasFilterDefinition(device_guid):
            item_list = settings.getVisibleInputCounts(device_guid, [InputType.JoystickAxis, InputType.JoystickButton], as_list=True)
            if item_list:
                for device_guid, input_type, input_id in item_list:
                    input_filter = settings.getInputVisible(device_guid, input_type, input_id)  # example, adjust as needed
                    return input_filter

        # come up with a default value

        input_filter = {}
        input_filter[device.device_id] = {}

        # default axes
        if device.axis_count:
            axis_count = max(device.axis_count, 3)  # first three axes
            input_filter[device.device_id][InputType.JoystickAxis] = {}
            for index in range(axis_count):
                input_id = device.axis_sequence_to_input_id(index)
                if input_id in input_filter[device.device_id][InputType.JoystickAxis]:
                    del input_filter[device.device_id][InputType.JoystickAxis][input_id]
                else:
                    # not visible
                    input_filter[device.device_id][InputType.JoystickAxis][input_id] = False
        if device.button_count:
            button_count = max(device.button_count, 2)  # first 2 buttons
            input_filter[device.device_id][InputType.JoystickButton] = {}
            for input_id in range(1, button_count + 1):
                if input_id in input_filter[device.device_id][InputType.JoystickButton]:
                    del input_filter[device.device_id][InputType.JoystickButton][input_id]
                else:
                    input_filter[device.device_id][InputType.JoystickButton][input_id] = False
        # ignore hats

        # save the defaults to the settings
        settings.applyFilter(input_filter)

        return input_filter

    def getInputFilter(self):
        """gets the input filter for the current device"""
        profile = gremlin.shared_state.current_profile
        return profile.settings.getInputVisibleMap()

    def update_stats(self):
        """updates mappings and filter stats"""
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateFilters(self.getInputFilter())
            self.stats.updateMappings()

    def ensure_stats(self):
        """ensures we have joystick input stats for the current device"""
        if not self.stats:
            profile = gremlin.shared_state.current_profile
            self.stats: gremlin.base_profile.JoystickInputStats = profile.settings.getJoystickInputStats(self.device_guid)

    def update_mappings(self):
        """updates input mapping status data"""
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateMappings()

    def update_filtered(self):
        """updates input mapping filter status data"""
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateFilters(self.getInputFilter())

    def update_stats_display(self, refresh: bool = True):
        """updates the display of stats"""
        if refresh:
            self.update_stats()

        self.stats_widget.setStats(self.stats)

    def _handle_filter_changed(self, value: bool):
        gremlin.util.InvokeUiMethod(self._handle_filter_changed_ui, value)  # ensure on UI thread

    def _handle_filter_changed_ui(self, value: bool):
        """update filtered to used inputs only"""

        dialog_filter = JoystickFilterDialog(self.device_guid, callback=self._handle_filter_dialog)
        dialog_filter.exec()

    def _handle_filter_dialog(self):
        """runs when the filter dialog is closed"""
        dialog = self.sender()
        if dialog.accepted:
            # get the current selected input
            input_item = self.inputItemListView.getSelectedItem()

            # see if there are changes to the filter

            # set the filter list from the visible inputs
            self.inputItemListModel.refresh()

            index = self.inputItemListModel.indexOfInputItem(input_item)
            if index == -1 and self.inputItemListModel.rows():
                # select the first item
                index = 0

            if index != -1:
                self.inputItemListView._select_item_ui(index, emit=False)

            # update the repeater
            self.update_stats_display()

            try:
                index = -1

                selected_index = self.inputItemListView.current_index
                input_item = self.inputItemListModel.itemAt(selected_index)
                # filter setup
                self.inputItemListModel.show_filtered = True
                # find the index in the filtered list, -1 if not found
                count = self.inputItemListModel.count()
                if count:
                    index = self.inputItemListModel.indexOf(input_item)
                    if index == -1:
                        # no longer displayed, select the first item
                        index = 0

                if index != -1:
                    self.inputItemListView._select_item_ui(index)

            finally:
                dialog.deleteLater()

    def _handle_locked_changed(self, value: bool):
        if value:
            # lock
            self._handle_lock_inputs(self.device_guid)
        else:
            # unlock
            self._handle_unlock_inputs(self.device_guid)

    def update_used_filter(self, value: bool):
        """handles filter changes"""
        self.inputItemListModel.show_filtered = value

    def _cleanup_ui(self):
        """called when deleted"""
        super()._cleanup_ui()

        el = gremlin.event_handler.EventListener()
        # Always disconnect EventListener slots. The previous gate checked for a
        # non-existent signal on the list view, so connections (including
        # curve_edit) accumulated across tab rebuilds and stacked Curve Editors.
        for signal, slot in (
            (el.edit_mode_changed, self._handle_edit_mode_changed),
            (el.config_changed, self._config_changed_cb),
            (el.lock_inputs, self._handle_lock_inputs),
            (el.unlock_inputs, self._handle_unlock_inputs),
            (el.jump_to_mapped_input, self._handle_jump_to_mapped_input),
            (el.input_filtered_change, self._handle_input_filter_changed),
            (el.curve_edit, self._edit_curve_item_cb),
            (el.curve_delete, self._delete_curve_item_cb),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

        if self.inputItemListView is not None and Shiboken.isValid(self.inputItemListView):
            self.inputItemListView.setParent(None)
            self.inputItemListView.deleteLater()

    def _edit_curve_item_cb(self, index: int, input_item: InputItem):
        gremlin.util.InvokeUiMethod(self._edit_curve_item_ui, index, input_item)

    def _edit_curve_item_ui(self, index: int, input_item: InputItem):
        """edit curve request"""
        gremlin.util.assert_ui_thread()
        import gremlin.curve_handler
        import gremlin.event_handler

        global _active_curve_dialog

        if not Shiboken.isValid(self):
            return

        assert isinstance(input_item, InputItem), "Invalid input item"
        if gremlin.util.normalize_guid(input_item.device_guid) != gremlin.util.normalize_guid(self.device_guid):
            # not ours
            return

        # One Curve Editor at a time — stale curve_edit slots must not stack dialogs
        if _active_curve_dialog is not None and Shiboken.isValid(_active_curve_dialog):
            return

        device_guid = input_item.device_guid
        input_id = input_item.input_id

        curve_data: gremlin.curve_handler.AxisCurveData = input_item.curve_data
        if not curve_data:
            curve_data = gremlin.curve_handler.AxisCurveData()
            curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(device_guid, input_id)
            curve_data.curve_update()
            input_item.curve_data = curve_data

        dialog = gremlin.curve_handler.AxisCurveDialog(curve_data)
        gremlin.util.centerDialog(dialog, dialog.width(), dialog.height())
        _active_curve_dialog = dialog

        # hook input value changed handler
        self._curve_update_handler = dialog.curve_update_handler
        self.curve_update_handler[index] = self._curve_update_handler
        # update the dialog with the current input value
        value = gremlin.joystick_handling.get_axis(device_guid, input_id)
        self._curve_update_handler(value)

        jep = gremlin.event_handler.JoystickEventProcessor()
        jep.registerListenerUICallback(device_guid=device_guid, input_id=input_id, input_type=input_item.input_type, callback=self._handle_curve_update)

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.dialog_closed.connect(self._unhook_curve)
        try:
            dialog.exec()
        finally:
            if _active_curve_dialog is dialog:
                _active_curve_dialog = None

        self.curve_update_handler[index] = None

        input_item.curve_data.curve_update()

        # renable highlighting
        gremlin.shared_state.pop_suspend_highlighting()

        self._update_curve_icon(index, input_item)

    def _unhook_curve(self):
        jep = gremlin.event_handler.JoystickEventProcessor()
        jep.unregisterListenerUICallback(device_guid=self.device_guid, input_id=None, input_type=None, callback=self._handle_curve_update)

    def _handle_curve_update(self, event: gremlin.event_handler.Event):
        if not event.is_axis:
            return
        if not event.device_guid == self.device_guid:
            return
        if self._curve_update_handler:
            self._curve_update_handler(event.value)

    def unhook(self):
        pass

    def _delete_curve_item_cb(self, index: int, input_item):
        gremlin.util.InvokeUiMethod(self._delete_curve_item_ui, index, input_item)

    def _delete_curve_item_ui(self, index: int, input_item):
        """delete curve request"""
        gremlin.util.assert_ui_thread()

        if not Shiboken.isValid(self):
            return

        assert isinstance(input_item, InputItem), "Invalid input item"
        if gremlin.util.normalize_guid(input_item.device_guid) != gremlin.util.normalize_guid(self.device_guid):
            # not ours
            return

        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("Delete this input curve?")
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
            if verbose:
                syslog.info("delete curve data")
            input_item.curve_data = None
            self._update_curve_icon(index, input_item)

    def _update_input_value_changed_cb(self, index: int, value: float):
        if index in self.curve_update_handler and self.curve_update_handler[index] is not None:
            self.curve_update_handler[index](value)

    def _handle_edit_mode_changed(self, mode: str):
        gremlin.util.InvokeUiMethod(self._edit_mode_changed_ui, mode)  # ensure on UI thread

    def _edit_mode_changed_ui(self, mode: str):
        """called on edit mode change"""
        if not Shiboken.isValid(self):
            return
        self.set_mode(mode)
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_mode
        if verbose:
            syslog.info(f"DeviceTabWidget: {self.device_name} change mode: [{mode}]")
        self.update_curve_icons()

    def update_curve_icons(self):
        if self.inputItemListView:  # check for delay load
            widgets = self.inputItemListView.getWidgets()
            if widgets:
                for index, widget in enumerate(widgets):
                    if widget is not None:
                        self._update_curve_icon(index, self.inputItemListView.model.data(index))

    def _update_curve_icon(self, index: int, data):
        if self.inputItemListView:
            widget = self.inputItemListView.widget(index)
            if widget is not None:
                widget.update_display()

    def _config_changed_cb(self):
        gremlin.util.InvokeUiMethod(self._config_changed_ui)

    def _config_changed_ui(self):
        gremlin.util.assert_ui_thread()
        if self.inputItemListView:  # check for delay load
            self.inputItemListModel.refresh()

    def _custom_widget_handler(self, list_view, index: int, identifier, data, parent=None):
        """creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        """

        if data.input_type == InputType.JoystickAxis:
            widget = gremlin.input_item.InputItemWidget(input_item=identifier.input_item, parent=parent, data=data)
            prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
            widget.setIcon(f"{prefix}joystick.png", use_qta=False)
            if widget.axis_repeater_widget is not None and identifier.is_axis:
                widget.axis_repeater_widget.valueChanged.connect(lambda x: self._update_input_value_changed_cb(index, x))
        elif data.input_type == InputType.JoystickButton:
            widget = gremlin.input_item.InputItemWidget(input_item=identifier.input_item, parent=parent, data=data)
            widget.setIcon("mdi.gesture-tap-button")
        elif data.input_type == InputType.JoystickHat:
            widget = gremlin.input_item.InputItemWidget(input_item=identifier.input_item, parent=parent, data=data)
            widget.setIcon("ei.fullscreen")
        widget.create_action_icons(data)
        widget.disable_close()
        widget.disable_edit()
        widget.setDescription(data.description)
        widget.index = index

        return widget

    @property
    def running(self):
        return gremlin.shared_state.is_running

    def set_mode(self, mode):
        """changes the mode of the tab"""

        if gremlin.config.Configuration().verbose_mode_detailed:
            # syslog = logging.getLogger("system")
            syslog.info(
                f"Device tab: change mode requested: device tab: {gremlin.shared_state.get_device_name(self.device.device_guid)} current mode: [{mode}]  new mode: [{mode}] "
            )

        self.device_profile.ensure_mode_exists(mode)

        self.inputItemListModel.mode = mode

        # self.inputItemListView.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.inputItemListModel.refresh()
            self.selectInputItemIndex(self._last_selected_index)

    def _create_description_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.description_changed_cb(index)

    def update_device_label(self, text):
        """Updates the label assigned to this device.

        :param text the new label text
        """
        self.device_profile.setDeviceLabel(self.device.device_guid, text)

    @property
    def inputCount(self) -> int:
        """number of inputs in the device"""
        return self.inputItemListModel.rows()

    @property
    def inputWidgetCount(self) -> int:
        """number of input widgets currently in the device"""
        return self.inputItemListView.count()

    def input_item_index_lookup(self, index):
        """Returns the profile data belonging to the provided index.

        This function determines which actual input item a given index refers to
        and then returns the content for it.

        :param index the index for which to return the data
        :param input_items the profile data from which to return the data
        :return profile data corresponding to the provided index
        """
        current_mode = gremlin.shared_state.edit_mode
        device_profile = gremlin.shared_state.device_profile_map[self.device_guid]
        self.device_profile.ensure_mode_exists(current_mode)
        input_items = device_profile.modes[current_mode]
        axis_count = len(input_items.config[InputType.JoystickAxis])
        button_count = len(input_items.config[InputType.JoystickButton])
        hat_count = len(input_items.config[InputType.JoystickHat])

        if index < axis_count:
            # Handle non continuous axis setups
            axis_keys = sorted(input_items.config[InputType.JoystickAxis].keys())
            if not input_items.has_data(InputType.JoystickAxis, axis_keys[index]):
                syslog.error(f"Attempting to retrieve non existent axis input, type={InputType.to_string(InputType.JoystickAxis)} index={axis_keys[index]}")

            return input_items.get_data(InputType.JoystickAxis, axis_keys[index])
        elif index < axis_count + button_count:
            if not input_items.has_data(InputType.JoystickButton, index - axis_count + 1):
                syslog.error(
                    f"Attempting to retrieve non existent button input, type={InputType.to_string(InputType.JoystickButton)} index={index - axis_count + 1}"
                )

            return input_items.get_data(InputType.JoystickButton, index - axis_count + 1)
        elif index < axis_count + button_count + hat_count:
            if not input_items.has_data(InputType.JoystickHat, index - axis_count - button_count + 1):
                syslog.error(
                    f"Attempting to retrieve non existent hat input, type={InputType.to_string(InputType.JoystickHat)} index={index - axis_count - button_count + 1}"
                )

            return input_items.get_data(InputType.JoystickHat, index - axis_count - button_count + 1)


class JoystickFilterDialog(gremlin.ui.ui_common.QRememberDialog):
    # class JoystickInputDialog(QtWidgets.QDialog):
    """joystick filter dialog"""

    def __init__(self, device_guid, callback=None, parent=None):
        """
        :param device_guid: the id of the device being filtered
        :param callback: close handler (optional)
        :param parent: parent widget, optional
        """

        super().__init__(self.__class__.__name__, parent=parent)
        # super().__init__(parent=parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle("Input Filter Configuration")
        self.setModal(True)

        try:
            # self.setUpdatesEnabled(False)

            self._input_widgets = {}  # holds a reference to the input widget

            device = gremlin.joystick_handling.getDevice(device_guid)
            profile = gremlin.shared_state.current_profile
            self.settings = profile.settings
            self.device = device
            self.device_guid = device.device_guid

            # grab a copy of the inputs

            # save a copy of the current input map
            self._current_filters = self.settings.getFilterMap()
            self._default_filters = self.settings.getDefaultFilterMap()

            self.stats = gremlin.base_profile.JoystickInputStats(self.device_guid, self._current_filters)

            # device properties

            self.stats_widget = gremlin.ui.ui_common.QJoystickInputWidget(self.device_guid)

            mapped_count_widget = QtWidgets.QLabel("")

            widgets = [
                "Input filter for:",
                device.name,
            ]

            header_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

            self.main_layout.addWidget(header_widget)
            container = gremlin.ui.ui_common.getHContainer([self.stats_widget, mapped_count_widget], widget_only=True)
            stats_container = gremlin.ui.ui_common.getHContainer(container, widget_only=True)
            self.main_layout.addWidget(stats_container)

            css = gremlin.ui.ui_common.Color.cssButtonState()

            data = []
            if device.axis_count:
                input_type = InputType.JoystickAxis
                for index in range(device.axis_count):
                    linear_id = index + 1
                    input_id = device.axis_sequence_to_input_id(index)
                    # syslog.info(f"{device.name} axis {index} linear index: {linear_id} -> input {input_id}")
                    name = device.getAxisName(input_id)
                    data.append((device_guid, input_type, input_id, name, linear_id))
            if device.button_count:
                input_type = InputType.JoystickButton
                for index in range(device.button_count):
                    input_id = index + 1
                    name = device.get_button_name(input_id)
                    data.append((device_guid, input_type, input_id, name, input_id))
            if device.hat_count:
                input_type = InputType.JoystickHat
                for index in range(device.hat_count):
                    input_id = index + 1
                    name = device.get_hat_name(input_id)
                    data.append((device_guid, input_type, input_id, name, input_id))

            # axis widget

            self.group_widgets = {}
            flow_layouts = {}

            if device.axis_count:
                input_type = InputType.JoystickAxis
                self.group_widgets[input_type] = QtWidgets.QGroupBox(f"Axis ({device.axis_count} inputs, {self.stats.visible_axis_count} visible)")
                flow_layouts[input_type] = gremlin.ui.ui_common.QFlowLayout(self.group_widgets[input_type])

            if device.button_count:
                input_type = InputType.JoystickButton
                self.group_widgets[input_type] = QtWidgets.QGroupBox(f"Buttons ({device.button_count} inputs, {self.stats.visible_button_count} visible)")
                flow_layouts[input_type] = gremlin.ui.ui_common.QFlowLayout(self.group_widgets[input_type])

            if device.hat_count:
                input_type = InputType.JoystickHat
                self.group_widgets[input_type] = QtWidgets.QGroupBox(f"Hats ({device.hat_count} inputs, {self.stats.visible_hat_count} visible)")
                flow_layouts[input_type] = gremlin.ui.ui_common.QFlowLayout(self.group_widgets[input_type])

            self._widgets = []  # holds the input filter buttons in the dialog
            mapped_count = 0
            input_count = 0
            device = gremlin.joystick_handling.getDevice(device_guid)
            for _, input_type, input_id, name, linear_id in data:
                visible = self.settings.getInputVisible(device_guid, input_type, input_id)
                is_used = profile.isInputMapped(device_guid, input_type, input_id)
                if is_used:
                    mapped_count += 1
                input_count += 1
                if linear_id == input_id:
                    tooltip = f"{InputType.to_name(input_type)} {input_id}" if input_type != InputType.JoystickAxis else device.get_axis_name(input_id)
                else:
                    tooltip = (
                        f"{InputType.to_name(input_type)} {input_id}/L{linear_id}" if input_type != InputType.JoystickAxis else device.get_axis_name(input_id)
                    )

                widget = gremlin.ui.ui_common.QUsedPushButton(
                    str(input_id) if input_type != InputType.JoystickAxis else device.get_axis_name(input_id, short_name=True),
                    used=is_used,
                    callback=self._handle_toggle,  # single input toggle
                    data=(input_type, input_id),
                    checkable=True,
                    checked=visible,
                    tooltip=tooltip,
                )

                widget.setStyleSheet(css)
                # hook the input so the button highlights on triggers
                widget.hook(device_guid, input_type, input_id)

                flow_layouts[input_type].addWidget(widget)

                if input_type not in self._input_widgets:
                    self._input_widgets[input_type] = {}
                self._input_widgets[input_type][input_id] = widget
                self._widgets.append(widget)

            self.input_map = data

            mapped_count_widget.setText(f"- Found {input_count} input(s), {mapped_count} mapped")
            self.stats_widget.setStats(self.stats)

            container_group, container_layout = gremlin.ui.ui_common.getVContainer()
            # add groups
            for group_widget in self.group_widgets.values():
                container_layout.addWidget(group_widget)

            # scroll area
            self.scroll_area = gremlin.ui.ui_common.QScrollableWidget(container_group)
            self.scroll_area.setMinimumHeight(200)
            self.main_layout.addWidget(self.scroll_area)

            widgets = []

            widget = gremlin.ui.ui_common.QDataPushButton(
                "Default",
                callbackEx=self._handle_filter,
                data="default",
                tooltip="Automatic default.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)

            # show mapped button always
            current_mode = gremlin.shared_state.edit_mode
            widget = gremlin.ui.ui_common.QDataPushButton(
                f"Mapped ({current_mode})",
                callbackEx=self._handle_filter,
                data="mapped",
                tooltip=f"Include mapped inputs in mode [{current_mode}] only.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)

            # show mapped button always
            widget = gremlin.ui.ui_common.QDataPushButton(
                "Mapped (all)",
                callbackEx=self._handle_filter,
                data="mapped_all",
                tooltip="Include mapped inputs only for all profile modes.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)

            if device.axis_count:
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Hide Axis",
                    callbackEx=self._handle_filter,
                    data="hide_axis",
                    tooltip="Hide all axes",
                )
                widgets.append(widget)
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Show Axis",
                    callbackEx=self._handle_filter,
                    data="show_axis",
                    tooltip="Show all axes",
                )
                widgets.append(widget)

            if device.button_count:
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Hide Buttons",
                    callbackEx=self._handle_filter,
                    data="hide_buttons",
                    tooltip="Remove all buttons",
                )
                widgets.append(widget)
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Show Buttons",
                    callbackEx=self._handle_filter,
                    data="show_buttons",
                    tooltip="Show all buttons",
                )
                widgets.append(widget)

            if device.hat_count:
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Hide Hats",
                    callbackEx=self._handle_filter,
                    data="hide_hats",
                    tooltip="Remove all hats",
                )
                widgets.append(widget)
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Show Hats",
                    callbackEx=self._handle_filter,
                    data="show_hats",
                    tooltip="Show all hats",
                )
                widgets.append(widget)

            widget = gremlin.ui.ui_common.QDataPushButton(
                "Hide All",
                callbackEx=self._handle_filter,
                data="hide_all",
                tooltip="Hide all inputs.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)
            widget = gremlin.ui.ui_common.QDataPushButton(
                "Show All",
                callbackEx=self._handle_filter,
                data="show_all",
                tooltip="Show all inputs",
            )
            widgets.append(widget)
            widget = gremlin.ui.ui_common.QDataPushButton(
                "Revert",
                callbackEx=self._handle_filter,
                data="revert",
                tooltip="Revert to current",
            )
            widgets.append(widget)

            if __debug__:
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Dump",
                    callbackEx=self._handle_dump,
                    tooltip="Dumps current visible and default data to log file",
                )
                widgets.append(widget)

            widget = gremlin.ui.ui_common.getFlowContainer(widgets, widget_only=True)
            self.main_layout.addWidget(widget)

            msg = """Toggle visible inputs by clicking on them, or press one of the shortcut actions. Control-click on <b>Default</b>, <b>Mapped</b> and <b>Hide All</b> shortcuts to apply the filter to all devices.
    Shift-click makes the filter additive (existing visible inputs will not be removed).
    Mapped inputs are shown with a green dot.
    Inputs will highlight when the associated axis, button or hat is triggered to help with identification.
    If an input is hidden, it can be made visible again in this dialog.  Hidden inputs do not delete any mappings.
    """
            info_widget = gremlin.ui.ui_common.QInfoBox(msg, hide_key=self.__class__.__name__)

            self.main_layout.addWidget(info_widget)

            self.main_layout.addStretch()

            # status for device filter
            self.status_widget = gremlin.ui.ui_common.QIconLabel()
            self.main_layout.addWidget(self.status_widget)

            self.save_default_widget = QtWidgets.QPushButton("Save as default")
            self.save_default_widget.clicked.connect(self._handle_set_default_for_device)
            self.save_default_widget.setToolTip("Saves the current filter selection as default for new profiles for this device")

            self.delete_default_widget = QtWidgets.QPushButton("Delete Default")
            self.delete_default_widget.clicked.connect(self._handle_delete_default_for_device)
            self.delete_default_widget.setToolTip("Saves the current filter selection as default for new profiles for this device")

            self.ok_widget = QtWidgets.QPushButton("Ok")
            self.ok_widget.clicked.connect(self._ok_button_cb)

            self.cancel_widget = QtWidgets.QPushButton("Cancel")
            self.cancel_widget.clicked.connect(self._cancel_button_cb)
            widgets = [
                self.save_default_widget,
                self.delete_default_widget,
                "||",
                self.ok_widget,
                self.cancel_widget,
            ]

            widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
            self.main_layout.addWidget(widget)

            if callback:
                self.accepted.connect(callback)

            # hook inputs so buttons can highlight
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event_handler)

        finally:
            pass

        self._update_ui()

    def _update_ui(self):
        """updates widgets"""

        delete_visible = False
        if self.settings.isDefaultFiltered(self.device.device_guid):
            icon = gremlin.ui.ui_common.Icons.recordIcon("#1EC047")
            label = "This device has a default saved."
            delete_visible = True
        else:
            icon = gremlin.ui.ui_common.Icons.recordIcon("#7E7E7E")
            label = "No saved defaults found."
        self.status_widget.setIcon(icon)
        self.status_widget.setText(label)
        self.delete_default_widget.setVisible(delete_visible)

    def closeEvent(self, event):
        self._input_widgets.clear()  # remove all widget references
        for widget in self._widgets:
            widget.unhook()
            gremlin.util.delete_widget(widget)

        gremlin.util.clear_widget_references(self)
        super().closeEvent(event)

    def _joystick_event_handler(self, event):
        gremlin.util.InvokeUiMethod(self._joystick_event_handler_ui, event)

    def _joystick_event_handler_ui(self, event):
        """handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time"""
        gremlin.util.assert_ui_thread()
        if event.device_guid != self.device_guid:
            # not an event we care about
            return

        input_id = event.identifier
        input_type = event.event_type

        if input_type in self._input_widgets and input_id in self._input_widgets[input_type]:
            btn = self._input_widgets[input_type][input_id]
            match input_type:
                case InputType.JoystickAxis:
                    btn.pulseHighlight()
                case InputType.JoystickButton:
                    btn.setHighlight(event.is_pressed)
                case InputType.JoystickHat:
                    value = event.value
                    is_pressed = value != (0, 0)
                    btn.setHighlight(is_pressed)

    def dump_filter(self, p_device_guid=None):
        syslog.info("=" * 30)
        syslog.info("dialog input filter dump")
        visible_count = 0

        for device_guid, input_type, input_id, _, _ in self.input_map:
            if p_device_guid and p_device_guid != device_guid:
                continue
            is_included = self._is_input_visible(input_type, input_id)
            if not is_included:
                # syslog.info(f"\t{input_type.name} {input_id} visible")
                visible_count += 1

        syslog.info(f"\tVisible count: {visible_count}")

        self._dump_visible_map()

    def _sync(self):
        """syncs inputs with data"""
        gremlin.util.InvokeUiMethod(self._sync_ui)  # ensure on UI thread

    def _sync_ui(self):

        widget: gremlin.ui.ui_common.QUsedPushButton
        device_guid = self.device.device_guid
        for widget in self._widgets:
            input_type, input_id = widget.data
            visible = self.settings.getInputVisible(device_guid, input_type, input_id)
            checked = widget.isChecked()
            if checked != visible:
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(visible)

        # update stats
        self.stats.updateFilters(self.settings.getInputFilterForDevice(device_guid))
        self.stats_widget.setStats(self.stats)
        self.updateGroups()

    def _revert(self):
        """reverts to the existing setup"""
        self.settings.setFilterMap(self._current_filters)
        self.settings.setDefaultFilterMap(self._default_filters)

    def _handle_dump(self, widget, is_control: bool, is_shift: bool, is_alt: bool, is_right: bool):
        self.settings.dump_visible_map(self.device_guid)

    @QtCore.Slot()
    def _handle_filter(self, widget, is_control: bool, is_shift: bool, is_alt: bool, is_right: bool):
        mode = widget.data
        device = self.device

        # global modes that impact multiple inputs
        match mode:
            case "default":
                # do the default selection
                if is_control:
                    # multi devices
                    self.settings.setAllDefault(additive=is_shift)
                else:
                    self.settings.setDeviceDefault(device, additive=is_shift)

            case "revert":
                # revert to current
                self._revert()

            case "hide_all":
                # hide all inputs
                if is_control:
                    self.settings.setallHidden()
                else:
                    # hide all for this device only
                    self.settings.setAllHiddenDevice(device)

            case "show_all":
                # filter all inputs
                if is_control:
                    self.settings.setAllVisible()
                else:
                    self.settings.setAllVisibleDevice(device)

            case "hide_axis":
                # hide axes
                if is_control:
                    self.settings.setInputTypeVisible(InputType.JoystickAxis, False)
                else:
                    self.settings.setInputTypeVisibleDevice(device, InputType.JoystickAxis, False)

            case "show_axis":
                # show axes
                if is_control:
                    self.settings.setInputTypeVisible(InputType.JoystickAxis, True, is_shift)
                else:
                    self.settings.setInputTypeVisibleDevice(device, InputType.JoystickAxis, True, is_shift)

            case "hide_buttons":
                # hide buttons
                if is_control:
                    self.settings.setInputTypeVisible(InputType.JoystickButton, False)
                else:
                    self.settings.setInputTypeVisibleDevice(device, InputType.JoystickButton, False)

            case "show_buttons":
                # show buttons
                if is_control:
                    self.settings.setInputTypeVisible(InputType.JoystickButton, True, is_shift)
                else:
                    self.settings.setInputTypeVisibleDevice(device, InputType.JoystickButton, True, is_shift)

            case "mapped":
                # filter to mapped devices only
                current_mode = gremlin.shared_state.edit_mode
                if is_control:
                    self.settings.setMappedVisible(current_mode, is_shift)
                else:
                    self.settings.setMappedVisibleDevice(device, current_mode, is_shift)

            case "mapped_all":
                if is_control:
                    # apply to all devices
                    self.settings.setMappedVisible(mode)
                else:
                    self.settings.setMappedVisibleDevice(device, mode)

            case "hide_hats":
                # hide hats
                if is_control:
                    self.settings.setInputTypeVisible(InputType.JoystickHat, False)
                else:
                    self.settings.setInputTypeVisibleDevice(device, InputType.JoystickHat, False)

            case "show_hats":
                # hide hats
                if is_control:
                    self.settings.setInputTypeVisible(InputType.JoystickHat, True, is_shift)
                else:
                    self.settings.setInputTypeVisibleDevice(device, InputType.JoystickHat, True, is_shift)

        # update visuals
        self._sync()

    def updateGroups(self):
        device = self.device
        # group headers
        if device.axis_count:
            self.group_widgets[InputType.JoystickAxis].setTitle(f"Axis ({device.axis_count} inputs, {self.stats.visible_axis_count} visible)")
        if device.button_count:
            self.group_widgets[InputType.JoystickButton].setTitle(f"Button ({device.button_count} inputs, {self.stats.visible_button_count} visible)")
        if device.hat_count:
            self.group_widgets[InputType.JoystickHat].setTitle(f"Hat ({device.hat_count} inputs, {self.stats.visible_hat_count} visible)")

    @QtCore.Slot()
    def _handle_toggle(self, btn):
        """handles a filter change"""
        data = btn.data
        input_type, input_id = data

        visible = btn.isChecked()
        # syslog.info(f"checked: {visible} input id: {input_id}")
        is_filtered = visible
        self._set_input_visible(input_type, input_id, is_filtered, emit=False)

    def _set_input_visible(self, input_type: InputType, input_id: int, visible: bool, emit=False):
        """sets the filtered state internal to the dialog"""
        verbose = gremlin.config.Configuration().verbose_mode_filter

        self.settings.setInputVisible(self.device_guid, input_type, input_id, visible)
        if verbose and input_type == InputType.JoystickAxis:
            syslog.info(f"set filter: [{self.device.name}] axis: {input_id} visible: {visible}")

        # update corresponding input button if needed
        widget = self._input_widgets[input_type][input_id]
        checked = widget.isChecked()
        if checked != visible:
            self._toggle_button(widget)
        if emit:
            self.stats.updateFilters(self.input_visible_map)
            self.stats_widget.setStats(self.stats)
            self.updateGroups()

    def _toggle_button(self, widget: gremlin.ui.ui_common.QUsedPushButton):
        """forces a button toggle"""
        gremlin.util.InvokeUiMethod(self._toggle_button_ui, widget)

    def _toggle_button_ui(self, widget: gremlin.ui.ui_common.QUsedPushButton):
        with QtCore.QSignalBlocker(widget):
            widget.setChecked(not widget.isChecked())

    def _dump_visible_map(self):
        """dumps the visible map to the log file"""
        self.settings.dump_visible_map(self.device_guid)

    @QtCore.Slot()
    def _ok_button_cb(self):
        self.accept()

    @QtCore.Slot()
    def _cancel_button_cb(self):
        """cancel button pressed"""
        # restore the saved data
        self._revert()
        self.reject()

    @QtCore.Slot()
    def _handle_set_default_for_device(self):
        # save the default
        # sync defaults based on current selection
        input_map = self.settings.getInputFilterForDevice(self.device_guid)
        # delete current defaults
        self.settings.clearDefaultDeviceFilters(self.device)
        for device_guid in input_map:
            for input_type in input_map[device_guid]:
                for input_id in input_map[device_guid][input_type]:
                    visible = input_map[device_guid][input_type][input_id]
                    self.settings.setDefaultInputVisible(device_guid, input_type, input_id, visible)

        result = self.settings.saveFilterDefaults(self.device_guid)
        if result:
            gremlin.ui.ui_common.MessageBoxInfo(
                prompt=f"Default filter saved.\nDevice [{self.device.name}].",
                parent=self,
            )
        else:
            gremlin.ui.ui_common.MessageBoxWarning(
                prompt=f"Error saving defaults.\nCheck the log file for details.\nDevice [{self.device.name}].",
                parent=self,
            )

        self._sync()  # sync inputs with new data

    @QtCore.Slot()
    def _handle_delete_default_for_device(self):
        gremlin.ui.ui_common.MessageBoxYesNo(
            prompt=f"Delete defaults for device [{self.device.name}]?",
            callback=self._handle_delete_confirm,
            parent=self,
        )

    def _handle_delete_confirm(self, result):
        if result == QtWidgets.QMessageBox.StandardButton.Yes:
            device_guid = self.device.device_guid
            result = self.settings.clearDefaultsFiltered(device_guid)
            if not result:
                gremlin.ui.ui_common.MessageBoxWarning(
                    prompt=f"Error deleting defaults.\nCheck the log file for details.\nDevice [{self.device.name}].",
                    parent=self,
                )
            self._update_ui()
