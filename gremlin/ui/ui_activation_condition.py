# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - Joystick Gremlin Ex is (C) EMCS 2025 
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


from PySide6 import QtCore, QtGui, QtWidgets

import logging
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
from gremlin import hints, input_devices, macro, util
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.types
import gremlin.ui
from gremlin.util import load_icon
import gremlin.util
import gremlin.base_classes as bc
from . import ui_common
from gremlin.base_conditions import *
import gremlin.keyboard

syslog = logging.getLogger("system")
class ActivationConditionWidget(QtWidgets.QWidget):

    """Widget displaying the UI used to configure activation conditions."""

    # Signal which is emitted whenever the widget's contents change
    activation_condition_modified = QtCore.Signal()

    # Maps activation type name to index
    activation_type_to_index = {
        None: 0,
        "action": 1,
        "container": 2
    }

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data associated with the conditions
        :param parent the parent widget of this
        """
        super().__init__(parent)
        self.profile_data = profile_data
        if isinstance(profile_data, gremlin.base_profile.AbstractContainer):
            self.container = profile_data
        else:
            self.container = None

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self._create_ui()


        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._update_ui)

    def _create_ui(self):
        """Creates the configuration UI."""

        self.help_button = QtWidgets.QPushButton(load_icon("gfx/help.png"), "")
        self.help_button.clicked.connect(self._show_hint)

        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.setContentsMargins(0,0,0,0)
        self.controls_layout.addWidget(QtWidgets.QLabel("Conditions Definitions:"))
        self.controls_layout.addWidget(self.help_button)

        self.controls_layout.addStretch()

        self.main_layout.addLayout(self.controls_layout)

        # conditions for the container

        
        self.container_condition_frame_widget = QtWidgets.QFrame()
        self.container_condition_frame_widget.setContentsMargins(0,0,0,0)
        self.container_condition_frame_layout = QtWidgets.QVBoxLayout(self.container_condition_frame_widget)
        self.container_condition_frame_widget.setFrameShape(QtWidgets.QFrame.Shape.Box)

        self.activation_count_widget = QtWidgets.QLabel()
        self.container_condition_frame_layout.addWidget(self.activation_count_widget)
        self.container_condition_model = ConditionModel(self.profile_data, self.profile_data.activation_container_condition)
        self.container_condition_view = ConditionView()
        self.container_condition_view.set_model(self.container_condition_model)
        
        self.container_condition_frame_layout.addWidget(self.container_condition_view)
        self.container_condition_frame_layout.addStretch()

        
        self.main_layout.addWidget(self.container_condition_frame_widget)

        self.container_condition_view.redraw()

        self._update_counts()
        
        

    @QtCore.Slot(object)
    def _update_ui(self, container):
       if self.container == container:
            self._update_counts()


    def _update_counts(self):
        ''' refreshes counts '''   
        if self.container:
            self.activation_count_widget.setText(f"Container conditions ({self.container.condition_count} found):")
        else:
            # not a container
            self.activation_count_widget.setText(f"Container conditions (N/A):")  

    def _show_hint(self, state):
        """Shows a help message.

        :param state push button state
        """
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            hints.hint.get("cond:granularity", "")
        )


class AbstractConditionWidget(QtWidgets.QGroupBox):

    """Abstract class for condition ui widgets."""

    # Signal emitted when a condition is deleted
    #deleted = QtCore.Signal(base_classes.AbstractCondition)
    deleted = QtCore.Signal(object)

    def __init__(self, condition_data, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.condition_data = condition_data

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._create_ui()

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        pass


class KeyboardConditionWidget(AbstractConditionWidget):

    """Widget allowing the configuration of a keyboard based condition."""

    def __init__(self, condition_data, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(condition_data, parent)
        self.setTitle("Keyboard Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        

        ui_common.clear_layout(self.main_layout)

        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)


        self.key_label = QtWidgets.QLabel("")
        if self.condition_data.input_item:
            self.key_label.setText(f"<b>{self.condition_data.input_item.display_name}</b>")
        
        self.record_button_widget = ui_common.NoKeyboardPushButton(load_icon("gfx/button_edit.png"), "Select Keys")
        self.record_button_widget.clicked.connect(self._request_user_input)
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        self.delete_button_widget = QtWidgets.QPushButton(load_icon(f"gfx/{prefix}button_delete.png"), ""
        )
        self.delete_button_widget.clicked.connect(
            lambda: self.deleted.emit(self.condition_data)
        )

        self.comparison_dropdown = ui_common.QComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if self.condition_data.comparison:
            self.comparison_dropdown.setCurrentText(
                self.condition_data.comparison.capitalize()
            )
        self.comparison_dropdown.currentTextChanged.connect(
            self._comparison_changed_cb
        )



        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        self.grid_layout.addWidget(self.key_label, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(self.record_button_widget, 0, 5)
        self.grid_layout.addWidget(self.delete_button_widget, 0, 6)
        self.grid_layout.setColumnStretch(4,2)

        self.main_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.ui_container_widget)


    @QtCore.Slot(object)
    def _key_pressed_cb(self, key):
        """Updates the UI and model with the newly pressed key information.

        :param key the key that has been pressed
        """
        from gremlin.ui.keyboard_device import KeyboardInputItem
        input_item = KeyboardInputItem()
        input_item.key = key
        self.condition_data.input_item = input_item
        self.condition_data.scan_code = key.scan_code
        self.condition_data.is_extended = key.is_extended
        self.condition_data.comparison = \
            self.comparison_dropdown.currentText().lower()
        self.key_label.setText(f"<b>{input_item.display_name}</b>")

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        self.condition_data.comparison = text.lower()


    @QtCore.Slot()
    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""

        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        sequence = []
        if self.condition_data.input_item:
            sequence = self.condition_data.input_item.sequence
        self._keyboard_dialog = InputKeyboardDialog(sequence = sequence, parent = self, select_single = False, index = -1)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        self._keyboard_dialog.showNormal()  

    @QtCore.Slot()
    def _dialog_ok_cb(self):
        ''' callled when the dialog completes '''

        # grab a new data index as this is a new entry
        self._key_pressed_cb(self._keyboard_dialog.latched_key)

        


class JoystickConditionWidget(AbstractConditionWidget):

    """Widget allowing the configuration of a joystick based condition."""

    def __init__(self, condition_data, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        self.input_event = None
        super().__init__(condition_data, parent)
        self.setTitle("Joystick Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""

        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""

        ui_common.clear_layout(self.main_layout)

        self.record_button = QtWidgets.QPushButton(load_icon(f"gfx/{prefix}button_edit.png"), "Listen")
        self.record_button.clicked.connect(self._request_user_input)
        
        self.delete_button = QtWidgets.QPushButton(load_icon(f"gfx/{prefix}button_delete.png"), "")        
        self.delete_button.clicked.connect(
            lambda: self.deleted.emit(self.condition_data)
        )

        self.main_layout.addWidget(QtWidgets.QLabel("Activate if:"))


        self.device_selector_widget = ui_common.QLimitedComboBox()
        self.device_selector_widget.currentIndexChanged.connect(self._device_selected)
        self.input_selector_widget = ui_common.QLimitedComboBox()
        self.input_selector_widget.currentIndexChanged.connect(self._input_selected)
        self.axis_repeater_widget = ui_common.AxisStateWidget(orientation=QtCore.Qt.Orientation.Horizontal, show_percentage=False)
        self.axis_repeater_widget.valueChanged.connect(self._axis_value_changed)

        self.use_calibrated_input_widget = QtWidgets.QCheckBox("Use calibrated input")
        self.use_calibrated_input_widget.setToolTip("When enabled, the condition will use as input the calibrated data if found.  When disabled, the condition will use the raw input.")
        self.use_calibrated_input_widget.setChecked(self.condition_data.use_calibrated_data)
        self.use_calibrated_input_widget.clicked.connect(self._use_calibrated_input_changed)

        self.selector_container_widget = QtWidgets.QWidget()
        self.selector_container_layout = QtWidgets.QGridLayout(self.selector_container_widget)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Device:"), 0, 0)
        self.selector_container_layout.addWidget(self.device_selector_widget, 0, 1) 
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Input:"), 1, 0)
        self.selector_container_layout.addWidget(self.input_selector_widget, 1, 1) 
        self.selector_container_layout.addWidget(self.axis_repeater_widget, 2, 1)

        self.selector_container_layout.addWidget(QtWidgets.QWidget(), 0, 2) # spacer column
        self.selector_container_layout.addWidget(self.record_button, 0, 3) 
        self.selector_container_layout.addWidget(self.delete_button, 0, 4) 
        self.selector_container_layout.setColumnStretch(2,2)

        self.range_status_widget = None

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        self.options_container_widget = QtWidgets.QWidget()
        self.options_container_widget.setContentsMargins(0,0,0,0)
        self.options_container_layout = QtWidgets.QHBoxLayout(self.options_container_widget)
        self.options_container_layout.setContentsMargins(0,0,0,0)

        self.options_container_layout.addWidget(self.use_calibrated_input_widget)


        self.main_layout.addWidget(self.selector_container_widget)
        self.main_layout.addWidget(self.ui_container_widget)
        self.main_layout.addWidget(self.options_container_widget)

        self._populate_device_selector()
        self._populate_input_selector()



    @QtCore.Slot()
    def _device_selected(self):
        ''' device changed, update input list'''
        device = self.device_selector_widget.currentData()
        self.condition_data.device_guid = device.device_guid
        self._populate_input_selector()

    @QtCore.Slot()
    def _input_selected(self):

        device : gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        input_type,  input_id = self.input_selector_widget.currentData()
        self.condition_data.device_guid = device.device_guid
        self.condition_data.input_type = input_type
        self.condition_data.input_id =  input_id
        self.condition_data.device_name = device.name
        
        self._update_ui()


    def _populate_device_selector(self):
        device_guid = self.condition_data.device_guid
        current_index = None
        with QtCore.QSignalBlocker(self.device_selector_widget):
            self.device_selector_widget.clear()
            index = 0
            device : gremlin.joystick_handling.DeviceSummary
            for device in gremlin.joystick_handling.physical_devices():
                self.device_selector_widget.addItem(device.name, device)
                if current_index is None and device_guid and device.device_guid == device_guid:
                    current_index = index
                index +=1

            if current_index is not None:
                self.device_selector_widget.setCurrentIndex(current_index)

        # update condition for the selected device
        device : gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        self.condition_data.device_guid = device.device_guid
    
    def _populate_input_selector(self):
        import gremlin.util
        input_id = self.condition_data.input_id
        input_type = self.condition_data.input_type
        device : gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        

        
        with QtCore.QSignalBlocker(self.input_selector_widget):
            self.input_selector_widget.clear()
            

            index = 0 # index of the entry
            current_index = None # index of the input to select

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
                if current_index is None and input_id == i + 1  and input_type == InputType.JoystickButton:
                    current_index = index
                index += 1


          
            # hats
            for i in range(device.hat_count):
                hat_name = f"Hat {i+1}"
                self.input_selector_widget.addItem(hat_name, (InputType.JoystickHat, i + 1))
                if current_index is None and input_id == i + 1 and input_type == InputType.JoystickHat:
                    current_index = index
                index+=1


            if current_index is not None:
                self.input_selector_widget.setCurrentIndex(current_index)

            input_type, input_id = self.input_selector_widget.currentData()
            self.condition_data.input_type = input_type
            self.condition_data.input_id = input_id

            # update the other UI based on input type
            self._update_ui()
            
        

    def _update_ui(self):
        ''' updates UI based on input type'''
        input_type = self.condition_data.input_type
        visible = False



        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
                visible = True

            case InputType.JoystickButton:
                self._button_ui()
        
            case InputType.JoystickHat:
                self._hat_ui()
            
        with QtCore.QSignalBlocker(self.axis_repeater_widget):
            if not visible:
                self.axis_repeater_widget.unhookDevice()
            else:
                self.axis_repeater_widget.hookDevice(self.condition_data.device_guid, self.condition_data.input_type, self.condition_data.input_id)
                
        self.axis_repeater_widget.setVisible(visible)
                

    def _axis_ui(self):
        """Creates the UI needed to configure an axis based condition."""
        
        gremlin.util.clear_layout(self.ui_container_layout)
        self.lower_widget = ui_common.QFloatLineEdit()
        self.lower_widget.setMinimum(-1.0)
        self.lower_widget.setMaximum(1.0)

        self.grab_low_widget = ui_common.QDataPushButton()
        self.grab_low_widget.setIcon(load_icon("mdi.record-rec",qta_color = "red"))
        self.grab_low_widget.setMaximumWidth(20)
        self.grab_low_widget.clicked.connect(self._grab_low)
        self.grab_low_widget.setToolTip("Grab axis value")

        
        self.lower_widget.setValue(self.condition_data.range[0])
        self.lower_widget.valueChanged.connect(self._range_lower_changed_cb)


        self.upper_widget = ui_common.QFloatLineEdit()
        self.upper_widget.setMinimum(-1.0)
        self.upper_widget.setMaximum(1.0)
        
        
        self.upper_widget.setValue(self.condition_data.range[1])
        self.upper_widget.valueChanged.connect(self._range_upper_changed_cb)

        self.grab_high_widget = ui_common.QDataPushButton()
        self.grab_high_widget.setIcon(load_icon("mdi.record-rec",qta_color = "red"))
        self.grab_high_widget.setMaximumWidth(20)
        self.grab_high_widget.clicked.connect(self._grab_high)
        self.grab_high_widget.setToolTip("Grab axis value")
        

        self.comparison_dropdown = ui_common.QComboBox()
        self.comparison_dropdown.addItem("Inside")
        self.comparison_dropdown.addItem("Outside")
        if not self.condition_data.comparison in ("inside","outside"):
            self.condition_data.comparison = "inside"
            
        self.comparison_dropdown.setCurrentText(self.condition_data.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.range_status_widget = ui_common.QIconLabel()
        self.range_status_widget.setIcon("fa.check", color="green")
        

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(self.comparison_dropdown)
        range_layout.addWidget(self.lower_widget)
        range_layout.addWidget(self.grab_low_widget)
        range_layout.addWidget(QtWidgets.QLabel("and"))
        range_layout.addWidget(self.upper_widget)
        range_layout.addWidget(self.grab_high_widget)
        range_layout.addWidget(self.range_status_widget)
        range_layout.addStretch()

        input_label = QtWidgets.QLabel(f"<b>{self.condition_data.device_name} Axis {self.condition_data.input_id:d}</b>")
        input_label.setWordWrap(True)
        self.ui_container_layout.addWidget(input_label, 0, 1)
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addLayout(range_layout, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.ui_container_layout.setColumnStretch(4,2)

        if not self.condition_data.comparison:
            # update the comparison
            self.condition_data.comparison = self.comparison_dropdown.currentText()

        
        self._update_range_state(self._axis_value())

    def _axis_value(self):
        if self.condition_data.use_calibrated_data:
            value = gremlin.joystick_handling.get_axis(self.condition_data.device_guid, self.condition_data.input_id)
        else:
            value = gremlin.joystick_handling.get_curved_axis(self.condition_data.device_guid, self.condition_data.input_id)
        return value

    def _button_ui(self):
        """Creates the UI needed to configure a button based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        self.comparison_dropdown = ui_common.QComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if not self.condition_data.comparison in ("pressed","released"):
            self.condition_data.comparison = "pressed"
        self.comparison_dropdown.setCurrentText(self.condition_data.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.ui_container_layout.addWidget(
            QtWidgets.QLabel(
                f"<b>{self.condition_data.device_name} Button {self.condition_data.input_id:d}</b>"
                ),
            0,
            1
        )
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.ui_container_layout.setColumnStretch(4,2)

        if not self.condition_data.comparison:
            # update the comparison
            self.condition_data.comparison = self.comparison_dropdown.currentText()

    def _hat_ui(self):
        """Creates the UI needed to configure a hat based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        directions = [
            "Center", "North", "North East", "East", "South East",
            "South", "South West", "West", "North West"
        ]

        self.comparison_dropdown = ui_common.QHatSelectorComboBox()
        if not self.condition_data.comparison or not self.condition_data.comparison.capitalize() in directions:
            self.condition_data.comparison = "center"

        self.comparison_dropdown.setValue(self.condition_data.comparison)
        self.comparison_dropdown.valueChanged.connect(self._comparison_changed_cb)
        
        input_name = f"<b>{self.condition_data.device_name} Hat {self.condition_data.input_id}</b>"

        self.ui_container_layout.addWidget(QtWidgets.QLabel(input_name),0,1)
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.ui_container_layout.setColumnStretch(4,2)


        if not self.condition_data.comparison:
            # update the comparison
            self.condition_data.comparison = self.comparison_dropdown.currentText()


    def _input_pressed_cb(self, event):
        """Processes input events to update the UI and model.

        :param event the input event to process
        """
        self.condition_data.device_guid = event.device_guid
        self.condition_data.input_type = event.event_type
        self.condition_data.input_id = event.identifier

        self.condition_data.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid) # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition_data.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition_data.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition_data.comparison =  util.hat_tuple_to_direction(event.value)
        self._create_ui()

    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""
        self.input_dialog = ui_common.InputListenerWidget(
            [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ],
            return_kb_event=False,
            multi_keys=False
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
            150
        )
        self.input_dialog.show()

    @QtCore.Slot(float)
    def _range_lower_changed_cb(self, value):
        """Updates the lower part of an axis range.

        :param value the new value
        """
        self.condition_data.range[0] = value


    @QtCore.Slot(float)
    def _range_upper_changed_cb(self, value):
        """Updates the upper part of an axis range.

        :param value the new value
        """
        self.condition_data.range[1] = value

    @QtCore.Slot()
    def _grab_low(self):
        self.lower_widget.setValue(self._axis_value()) # also updates condition_data
        

    @QtCore.Slot()
    def _grab_high(self):
        self.upper_widget.setValue(self._axis_value()) # also updates condition_data

    @QtCore.Slot(bool)
    def _use_calibrated_input_changed(self, checked):
        self.condition_data.use_calibrated_data = checked
        self._update_range_state(self._axis_value())

    @QtCore.Slot(float, float)
    def _axis_value_changed(self, value : float, curved_value : float):
        self._update_range_state(value)

    def _update_range_state(self, value):
        ''' updates the range flag based on the input value '''
        if self.range_status_widget:
            visible = False
            
            v1, v2 = self.condition_data.range
            match self.condition_data.comparison:
                case "inside":
                    if value >= v1 and value <= v2:
                        self.range_status_widget.setText("in range")
                        visible = True
                    
                case "outside":
                    if value < v1 or value > v2:
                        self.range_status_widget.setText("outside of range")
                        visible = True

            self.range_status_widget.setVisible(visible)


    @QtCore.Slot(str)
    def _comparison_changed_cb(self, data):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        if self.condition_data.input_type == InputType.JoystickButton:
            self.condition_data.comparison = data.casefold()
        elif self.condition_data.input_type == InputType.JoystickHat:
            self.condition_data.comparison = gremlin.types.HatDirection.to_string(data)
        elif self.condition_data.input_type == InputType.JoystickAxis:
            self.condition_data.comparison = data.casefold()
        else:
            syslog.warning(
                f"Invalid input type encountered: {self.condition_data.input_type}"
            )
        
        self._update_range_state(self._axis_value())

class VJoyConditionWidget(AbstractConditionWidget):

    """Widget allowing the configuration of a vJoy based condition."""

    def __init__(self, condition_data, parent=None):
        """Creates a new widget.

        Parameters
        ==========
        condition_data : VJoyCondition
            data to be represented by the widget
        parent : QObject
            parent of this widget
        """
        self.input_event = None
        super().__init__(condition_data, parent)
        self.setTitle("vJoy Condition")

        # Initialize UI fully
        self._modify_vjoy(self.vjoy_selector.get_selection())


    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        ui_common.clear_layout(self.main_layout)

        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)



        self.vjoy_selector = ui_common.VJoySelector(
            self._modify_vjoy,
            [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ]
        )
        self.vjoy_selector.set_selection(
            self.condition_data.input_type,
            self.condition_data.vjoy_id,
            self.condition_data.input_id
        )
        self.delete_button = QtWidgets.QPushButton(
            load_icon("gfx/{prefix}button_delete.png"), "")
        self.delete_button.clicked.connect(
            lambda: self.deleted.emit(self.condition_data)
        )


        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)


        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        if self.condition_data.input_type == InputType.JoystickAxis:
            self._axis_ui()
        elif self.condition_data.input_type == InputType.JoystickButton:
            self._button_ui()
        elif self.condition_data.input_type == InputType.JoystickHat:
            self._hat_ui()

        self.grid_layout.addWidget(self.vjoy_selector, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(self.delete_button, 0, 5)
        self.grid_layout.setColumnStretch(4,2)

        self.main_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.ui_container_widget)

        input_type = self.condition_data.input_type
        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
            case InputType.JoystickButton:
                self._button_ui()
            case InputType.JoystickHat:
                self._hat_ui()

    def _axis_ui(self):
        """Creates the UI needed to configure an axis based condition."""
        self.lower_widget = ui_common.QFloatLineEdit()
        self.lower_widget.setMinimum(-1.0)
        self.lower_widget.setMaximum(1.0)
        
        
        self.lower_widget.setValue(self.condition_data.range[0])
        self.lower_widget.valueChanged.connect(self._range_lower_changed_cb)
        self.upper_widget = ui_common.QFloatLineEdit()
        self.upper_widget.setMinimum(-1.0)
        self.upper_widget.setMaximum(1.0)

        self.upper_widget.setValue(self.condition_data.range[1])
        self.upper_widget.valueChanged.connect(self._range_upper_changed_cb)

        self.comparison_widget = ui_common.QComboBox()
        self.comparison_widget.addItem("Inside")
        self.comparison_widget.addItem("Outside")
        if not self.condition_data.comparison in ("inside","outside"):
            self.condition_data.comparison = "inside"
        self.comparison_widget.setCurrentText(self.condition_data.comparison.capitalize())
        self.comparison_widget.currentTextChanged.connect(self._comparison_changed_cb)

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(self.comparison_widget)
        range_layout.addWidget(self.lower_widget)
        range_layout.addWidget(QtWidgets.QLabel("and"))
        range_layout.addWidget(self.upper_widget)
        range_layout.addStretch()

        input_label = QtWidgets.QLabel(f"<b>vJoy {self.condition_data.vjoy_id:d} Axis {self.condition_data.input_id:d}</b>")
        input_label.setWordWrap(True)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(input_label)
        layout.addWidget(QtWidgets.QLabel("is"))
        layout.addLayout(range_layout)
        layout.addStretch()
        self.ui_container_layout.addLayout(layout, 0, 1)
        
        

    def _button_ui(self):
        """Creates the UI needed to configure a button based condition."""
        self.comparison_widget = ui_common.QComboBox()
        self.comparison_widget.addItem("Pressed")
        self.comparison_widget.addItem("Released")
        if not self.condition_data.comparison in ("pressed","released"):
            self.condition_data.comparison = "pressed"
        self.comparison_widget.setCurrentText(self.condition_data.comparison.capitalize())
        self.comparison_widget.currentTextChanged.connect(self._comparison_changed_cb)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(QtWidgets.QLabel(f"<b>vJoy {self.condition_data.vjoy_id:d} Button {self.condition_data.input_id:d}</b>"))
        layout.addWidget(QtWidgets.QLabel("is"))
        layout.addWidget(self.comparison_widget)
        layout.addStretch()

        self.ui_container_layout.addLayout(layout, 0, 1)
        

    def _hat_ui(self):
        """Creates the UI needed to configure a hat based condition."""
        directions = [
            "Center", "North", "North East", "East", "South East",
            "South", "South West", "West", "North West"
        ]
        self.comparison_widget = ui_common.QHatSelectorComboBox()
        if not self.condition_data.comparison or not self.condition_data.comparison.capitalize() in directions:
            self.condition_data.comparison = "center"
        self.comparison_widget.setValue(self.condition_data.comparison)
        self.comparison_widget.valueChanged.connect(self._comparison_changed_cb)
        
        layout = QtWidgets.QHBoxLayout()

        layout.addWidget(QtWidgets.QLabel(f"<b>vJoy {self.condition_data.vjoy_id:d} Hat {self.condition_data.input_id:d}</b>"))
        layout.addWidget(QtWidgets.QLabel("is"))
        layout.addWidget(self.comparison_widget)
        layout.addStretch()

        self.ui_container_layout.addLayout(layout, 0, 1)

    def _modify_vjoy(self, data):
        # fix: 5/29/24 EMCS don't override prior value if already a valid value to prevent a condition reset
        self.condition_data.vjoy_id = data["device_id"]
        self.condition_data.input_type = data["input_type"]
        self.condition_data.input_id = data["input_id"]

        if data["input_type"] == InputType.JoystickAxis:
            if not self.condition_data.comparison in ("inside","outside"):
                self.condition_data.comparison = "inside"
        elif data["input_type"] == InputType.JoystickButton:
            if not self.condition_data.comparison in ("pressed","released"):
                self.condition_data.comparison = "pressed"
        elif data["input_type"] == InputType.JoystickHat:
            directions = ("center", "north", "north-east", "east", "south-east","south", "south-west", "west", "north-west")
            if not self.condition_data.comparison in directions:
                self.condition_data.comparison = "center"
        self._create_ui()

    def _range_lower_changed_cb(self, value):
        """Updates the lower part of an axis range.

        :param value the new value
        """
        self.condition_data.range[0] = value

    def _range_upper_changed_cb(self, value):
        """Updates the upper part of an axis range.

        :param value the new value
        """
        self.condition_data.range[1] = value

    def _comparison_changed_cb(self, data):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        if self.condition_data.input_type == InputType.JoystickButton:
            self.condition_data.comparison = data.casefold()
        elif self.condition_data.input_type == InputType.JoystickHat:
            self.condition_data.comparison = gremlin.types.HatDirection.to_string(data)
        elif self.condition_data.input_type == InputType.JoystickAxis:
            self.condition_data.comparison = data.casefold()
        else:
            syslog.warning(
                f"Invalid input type encountered: {self.condition_data.input_type}"
            )


class InputActionConditionWidget(AbstractConditionWidget):

    """Creates the UI needed to configure an input action based condition."""

    def __init__(self, condition_data, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(condition_data, parent)
        self.setTitle("Action Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""

        ui_common.clear_layout(self.main_layout)
        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)

        self.state_dropdown = ui_common.QComboBox()
        self.state_dropdown.addItem("Pressed")
        self.state_dropdown.addItem("Released")
        if self.condition_data.comparison:
            self.state_dropdown.setCurrentText(
                self.condition_data.comparison.capitalize()
            )
        else:
            self.condition_data.comparison = "pressed"
        self.state_dropdown.currentTextChanged.connect(
            self._state_selection_changed
        )
        self.delete_button = QtWidgets.QPushButton(
            load_icon(f"gfx/{prefix}button_delete.png"), "")
        
        self.delete_button.clicked.connect(
            lambda: self.deleted.emit(self.condition_data)
        )

        self.grid_layout.addWidget(QtWidgets.QLabel("Activate when"), 0, 0)
        self.grid_layout.addWidget(
            QtWidgets.QLabel("<b>this (virtual) button</b>"),
            0,
            1
        )
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(
            self.state_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft
        )


        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(self.delete_button, 0, 6)
        self.grid_layout.setColumnStretch(4,2)
        self.main_layout.addWidget(self.grid_widget)



    def _state_selection_changed(self, label):
        """Updates the activation state of the condition.

        :param label the new activation state
        """
        self.condition_data.comparison = label.lower()


class ConditionModel(ui_common.AbstractModel):

    """Stores and represents condition data."""

    def __init__(self, action_data, condition_data, parent=None):
        """Creates a new model to store condition data.

        :param condition_data the condition data to represent
        :param parent the parent of this object
        """
        super().__init__(parent)
        self.condition_data = condition_data
        self.action_data = action_data
        self.input_item = action_data.input_item
        self.container = None
        if isinstance(action_data, gremlin.base_profile.AbstractContainer):
            self.container = action_data
        elif isinstance(action_data, gremlin.base_profile.AbstractAction):
            # find the container for the given action 
            self.container = action_data.get_container()

    def rows(self):
        """Returns the number of rows in the model.
        :return number of rows
        """
        return len(self.condition_data.conditions)

    def data(self, index):
        """Returns the data stored at the given index.

        :param index the index for which to return the data
        :return the data stored at the provided index
        """
        return self.condition_data.conditions[index]

    def add_condition(self, condition):
        """Adds a condition to to the model.

        :param condition_data the condition data to add
        """

        self.condition_data.conditions.append(condition)
        tracker = ConditionTracker()
        mode = gremlin.shared_state.current_mode
        container = self.container
        input_item = self.input_item
        data = ConditionTrackerData(mode, input_item, container, condition)
        tracker.registerCondition(data)
        self.data_changed.emit()
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.emit(container)

        

    def delete_condition(self, condition):
        """Deletes a condition from the model.

        Attempts to locate the provided condition and deletes it, if it is
        present.

        :param condition the condition to remove.
        """
        idx = self.condition_data.conditions.index(condition)
        if idx != -1:
            del self.condition_data.conditions[idx]
        tracker = ConditionTracker()
        tracker.unregisterCondition(condition)
        container = self.container
        
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.emit(container)
        self.data_changed.emit()

    @property
    def rule(self):
        """Returns the current application rule for the conditions.

        :return current application rule of conditions
        """
        return self.condition_data.rule

    @rule.setter
    def rule(self, rule):
        """Sets the application rule of the conditions.

        :param rule the new application type
        """
        self.condition_data.rule = rule


class ConditionView(ui_common.AbstractView):

    """Widget visualizing a condition model instance."""

    # Mapping between data and ui classes
    
    
    condition_map = {
        "Keyboard":
            [KeyboardCondition, KeyboardConditionWidget],
        "Joystick":
            [JoystickCondition, JoystickConditionWidget],
        "vJoy":
            [VJoyCondition, VJoyConditionWidget],
        "Action":
            [InputActionCondition, InputActionConditionWidget]
    }

    # Mapping between application rule label and enumeration
    rules_map = {
        "All": ActivationRule.All,
        "Any": ActivationRule.Any,
        ActivationRule.All: "All",
        ActivationRule.Any: "Any"
    }

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.controls_layout = QtWidgets.QHBoxLayout()
        self.conditions_layout = QtWidgets.QVBoxLayout()

        self.main_layout.addLayout(self.controls_layout)
        self.main_layout.addLayout(self.conditions_layout)

        # Condition truth rules
        self.rule_selector = ui_common.QComboBox()
        self.rule_selector.addItem("All")
        self.rule_selector.addItem("Any")
        self.rule_selector.currentTextChanged.connect(self._rule_changed_cb)
        self.controls_layout.addWidget(QtWidgets.QLabel("Requires "))
        self.controls_layout.addWidget(self.rule_selector)
        self.controls_layout.addWidget(
            QtWidgets.QLabel("condition(s) to be met")
        )

        self.controls_layout.addStretch()

        # Condition selector
        self.condition_selector = ui_common.QComboBox()
        self.condition_selector.addItem("Keyboard Condition")
        self.condition_selector.addItem("Joystick Condition")
        self.condition_selector.addItem("vJoy Condition")
        self.condition_selector.addItem("Action Condition")
        config = gremlin.config.Configuration()
        last_selector = config.condition_selector
        index = self.condition_selector.findText(last_selector)
        if index != -1:
            self.condition_selector.setCurrentIndex(index)
        self.condition_selector.currentIndexChanged.connect(self._change_condition_selector)
        self.condition_add_button = QtWidgets.QPushButton("Add")
        self.condition_add_button.clicked.connect(self._add_condition)
        self.controls_layout.addWidget(self.condition_selector)
        self.controls_layout.addWidget(self.condition_add_button)

        self.help_button = QtWidgets.QPushButton(load_icon("gfx/help.png"), "")
        self.help_button.clicked.connect(self._show_hint)
        self.controls_layout.addWidget(self.help_button)

    @QtCore.Slot()
    def _change_condition_selector(self):
        config = gremlin.config.Configuration()
        config.condition_selector = self.condition_selector.currentText()

    def redraw(self):
        """Redraws the entire view."""

        el = gremlin.event_handler.EventListener()
        el.condition_redraw.emit(self.model.action_data)
        
        ui_common.clear_layout(self.conditions_layout)

        lookup = {}
        for entry in ConditionView.condition_map.values():
            lookup[entry[0]] = entry[1]

        for i in range(self.model.rows()):
            data = self.model.data(i)
            condition_widget = lookup[type(data)](data)
            condition_widget.deleted.connect(
                lambda local_data: self.model.delete_condition(local_data)
            )
            self.conditions_layout.addWidget(condition_widget)

        
        el.condition_state_changed.emit(self.model.action_data)

    def _add_condition(self):
        """Adds a condition to the view's model."""
        data_type = ConditionView.condition_map[self.condition_selector.currentText().split()[0]][0]
        self.model.add_condition(data_type())
        

    def _rule_changed_cb(self, text):
        """Updates the rule of the model.

        :param text the new rule value
        """
        self.model.rule = ConditionView.rules_map[text]

    def _model_changed(self):
        """Updates the view when the model changes."""
        self.rule_selector.setCurrentText(
            ConditionView.rules_map[self.model.rule]
        )

        


    def _show_hint(self, state):
        """Shows a help message regarding the condition types.

        :param state push button state
        """
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            hints.hint.get("cond:types", "")
        )
