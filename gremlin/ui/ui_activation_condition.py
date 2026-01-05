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


from PySide6 import QtCore, QtGui, QtWidgets

import logging
import gremlin.base_profile
import gremlin.clipboard
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
from gremlin import hints, input_devices, macro, util
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.types
import gremlin.ui
import gremlin.ui.ui_common
from gremlin.util import load_icon
import gremlin.util
import gremlin.base_classes as bc
from . import ui_common
from shiboken6 import Shiboken
from gremlin.base_conditions import *
import gremlin.keyboard
import psygnal
from psygnal import Signal
syslog = logging.getLogger("system")
class ActivationConditionWidget(QtWidgets.QWidget):

    """Widget displaying the UI used to configure activation conditions."""

    # Signal which is emitted whenever the widget's contents change
    activation_condition_modified = Signal()

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
        #if isinstance(profile_data, gremlin.base_profile.AbstractContainer) or isinstance(profile_data, gremlin.base_profile.ConditionContainer):
        if isinstance(profile_data, gremlin.base_profile.ConditionContainer):
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
        if not Shiboken.isValid(self):
            return
        self.help_button = gremlin.ui.ui_common.Buttons.getHelpWidget(callback = self._show_hint)

        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.setContentsMargins(0,0,0,0)
        self.controls_layout.addWidget(QtWidgets.QLabel("Conditions Definitions:"))
        self.controls_layout.addWidget(self.help_button)
        self.controls_layout.addStretch()

      

        self.main_layout.addLayout(self.controls_layout)

        # conditions for the container

        
        self.container_condition_frame_widget = gremlin.ui.ui_common.QBoxFrame()
        self.container_condition_frame_widget.setContentsMargins(0,0,0,0)
        self.container_condition_frame_layout = QtWidgets.QVBoxLayout(self.container_condition_frame_widget)
        

        self.activation_count_widget = QtWidgets.QLabel()
        self.container_condition_frame_layout.addWidget(self.activation_count_widget)
        self.container_condition_model = ConditionModel(self.profile_data, self.profile_data.activation_condition)
        
       
        self.container_condition_view = ConditionView()
        self.container_condition_view.setContainer(self.profile_data)
        self.container_condition_view.setModel(self.container_condition_model)
        
        self.container_condition_frame_layout.addWidget(self.container_condition_view)
        #self.container_condition_frame_layout.addStretch()

        
        self.main_layout.addWidget(self.container_condition_frame_widget)

        self.container_condition_view.redraw()

        self._update_counts()
        
    def _update_condition(self):
        gremlin.util.InvokeUiMethod(self._update_conditions_ui)
    
    @QtCore.Slot()
    def _update_conditions_ui(self):
        ''' updates the condition UI for this container '''
        #self.activation_condition_modified.emit()
        self.container_condition_view.redraw()



    @QtCore.Slot(object)
    def _update_ui(self, container):
       if self.container.id == container.id:
            self._update_counts()



    def _update_counts(self):
        ''' refreshes counts '''   
        if not Shiboken.isValid(self.activation_count_widget):
            return
        if self.container:
            self.activation_count_widget.setText(f"Container action conditions ({self.container.condition_count} found):")
        else:
            # not a container
            self.activation_count_widget.setText(f"Conditions:")  


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
    #deleted = Signal(base_classes.AbstractCondition)
    deleted = Signal(object)

    def __init__(self, condition : AbstractCondition, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.condition = condition

        self.main_layout = QtWidgets.QVBoxLayout(self)

        
        self._create_ui()

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        pass


    @QtCore.Slot()
    def _copy_condition(self):
        helper = ConditionHelper()
        helper.copy_condition(self.condition)

    @QtCore.Slot()
    def _paste_condition(self):
        clipboard = gremlin.clipboard.Clipboard()
        helper = ConditionHelper()
        helper.paste_condition(self.condition.owner.container, clipboard.data)


class KeyboardConditionWidget(AbstractConditionWidget):

    """Widget allowing the configuration of a keyboard based condition."""

    def __init__(self, condition, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(condition, parent)
        self.setTitle("Keyboard Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return

        ui_common.clear_layout(self.main_layout)

        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)


        self.key_label = QtWidgets.QLabel("")
        if self.condition.input_item:
            self.key_label.setText(f"<b>{self.condition.input_item.display_name}</b>")

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)
        
        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label = "Listen", callback = self._request_user_input)
        self.select_button_widget = gremlin.ui.ui_common.Buttons.getKeyboardWidget(label = "Select Keys", callback = self._select_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition))
        

        widgets,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                             self.paste_widget,
                                                             self.record_button_widget,
                                                             self.select_button_widget,
                                                             self.delete_button_widget,
                                                             ])
        

        self.comparison_dropdown = ui_common.QComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if self.condition.comparison:self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)



        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        self.grid_layout.addWidget(self.key_label, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(widgets, 0, 5)
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
        if isinstance(key, list):
            key = key.pop()
        input_item.key = key
        self.condition.input_item = input_item
        self.condition.scan_code = key.scan_code
        self.condition.is_extended = key.is_extended
        self.condition.comparison = \
            self.comparison_dropdown.currentText().lower()
        self.key_label.setText(f"<b>{input_item.display_name}</b>")

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        self.condition.comparison = text.lower()

    @QtCore.Slot()
    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""
        self.input_dialog = ui_common.InputListenerWidget(
            [
                InputType.Keyboard,
                InputType.KeyboardLatched,
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

    @QtCore.Slot(object)
    def _input_pressed_cb(self, key):
        """Processes input events to update the UI and model.

        :param event the input event to process
        """
        
        self.condition.comparison = "pressed"

        self._key_pressed_cb(key)   


    @QtCore.Slot()
    def _select_user_input(self):
        """ brings up the keyboard to select keys from """

        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        sequence = []
        if self.condition.input_item:
            sequence = self.condition.input_item.sequence
        self._keyboard_dialog = InputKeyboardDialog(sequence = sequence, parent = self, select_single = False, index = -1)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        gremlin.util.centerDialog(self._keyboard_dialog)
        self._keyboard_dialog.showNormal()  

    @QtCore.Slot()
    def _dialog_ok_cb(self):
        ''' callled when the dialog completes '''

        # grab a new data index as this is a new entry
        self._key_pressed_cb(self._keyboard_dialog.latched_key)


class ModeConditionWidget(AbstractConditionWidget):
    ''' mode condition UI '''
    def __init__(self, condition, parent=None):
        super().__init__(condition, parent)
        self.setTitle("Mode Condition")

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return        
        
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition))
        widget = gremlin.ui.ui_common.getHContainer(self.delete_button_widget, left_stretch=True, widget_only = True)
        self.main_layout.addWidget(widget)

        self.mode_selector = gremlin.ui.ui_common.QModeSelector()
        if not self.condition.mode:
            self.condition.mode = gremlin.shared_state.edit_mode
        self.mode_selector.setMode(self.condition.mode)
             
        self.mode_selector.modeChanged.connect(self._handle_mode_changed)

        self.comparison_dropdown = gremlin.ui.ui_common.QComboBox()
        self.comparison_dropdown.addItem("Equal", "equal")
        self.comparison_dropdown.addItem("Not Equal", "not_equal")
        if self.condition.comparison:
            index = self.comparison_dropdown.findData(self.condition.comparison)
            if index != -1:
                self.comparison_dropdown.setCurrentIndex(index)
        
        #if self.condition.comparison: self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentIndexChanged.connect(self._comparison_changed_cb)

        self.key_label = QtWidgets.QLabel("")



        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)


        widgets = [
            "Activate if current mode is",
            self.comparison_dropdown,
            "to",
            self.mode_selector,
            self.ignore_release_widget
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget)

        self.description_widget = QtWidgets.QLabel()
        widget = gremlin.ui.ui_common.getHContainer(["Description:", self.description_widget], widget_only = True)
        self.main_layout.addWidget(widget)


        # self.grid_layout.addWidget(self.ignore_release_widget, 0, 5)        
        # self.grid_layout.setColumnStretch(5,2)
        #self.main_layout.addWidget(self.grid_widget)

          
    def _handle_mode_changed(self, mode):          
        self.condition.mode = mode

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked):
        self.condition.ignore_release = checked
        
    def setDescription(self, value):
        self.description_widget.setText(value if value else "n/a")


    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        ''' update comparison '''
        self.condition.comparison = self.comparison_dropdown.currentData()


class StateConditionWidget(AbstractConditionWidget):
    ''' state condition UI '''
    def __init__(self, condition, parent=None):
        super().__init__(condition, parent)
        self.setTitle("State Condition")

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition))
        widget = gremlin.ui.ui_common.getHContainer(self.delete_button_widget, left_stretch=True, widget_only = True)
        self.main_layout.addWidget(widget)

        self.state_selector = gremlin.ui.ui_common.QComboBox()
        self.state_selector.currentIndexChanged.connect(self._state_changed)
        self.state_description_widget = QtWidgets.QLabel()
        widget = gremlin.ui.ui_common.getHContainer(["State:", self.state_selector], widget_only = True)
        self.main_layout.addWidget(widget)

        


        widget = gremlin.ui.ui_common.getHContainer(["Description:", self.state_description_widget], widget_only = True)
        self.main_layout.addWidget(widget)

        self.comparison_dropdown = ui_common.QComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if self.condition.comparison:self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.key_label = QtWidgets.QLabel("")

        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        self.grid_layout.addWidget(self.key_label, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.grid_layout.addWidget(self.ignore_release_widget, 0, 5)        
        
        self.grid_layout.setColumnStretch(5,2)

        self.main_layout.addWidget(self.grid_widget)

        self.populate_selector()
        
    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked):
        self.condition.ignore_release = checked
        
    def setDescription(self, value):
        self.state_description_widget.setText(value if value else "n/a")

    @QtCore.Slot()
    def _state_changed(self):
        if Shiboken.isValid(self.state_selector):
            data = self.state_selector.currentData()
            description = data.description
            self.setDescription(description)
            self.condition.key = data.key
            self.condition.description = description

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        self.condition.comparison = text.lower()

    def populate_selector(self):
        ''' updates the available states '''
        import gremlin.ui.state_device
        with QtCore.QSignalBlocker(self.state_selector):
            self.state_selector.clear()
            sd = gremlin.ui.state_device.StateData()
            for key, data in sd.getStates().items():
                self.state_selector.addItem(key, data)

            key = self.condition.key
            if key:
                index = self.state_selector.findText(key)
                if index >= 0:
                    self.state_selector.setCurrentIndex(index)
            else:
                # pick the first as the default
                self.condition.key = self.state_selector.currentText()
            
            if self.state_selector.count():
                data = self.state_selector.currentData()
                description = data.description
                self.setDescription(description)        
                self.condition.description = description

class JoystickConditionWidget(AbstractConditionWidget):

    """Widget allowing the configuration of a joystick based condition."""

    def __init__(self, condition, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        self.input_event = None
        super().__init__(condition, parent)
        self.setTitle("Joystick Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return

        ui_common.clear_layout(self.main_layout)

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)
   

        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label = "Listen", callback = self._request_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition))

        widgets,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                             self.paste_widget,
                                                             self.record_button_widget,
                                                             self.delete_button_widget,
                                                             ])



        

        self.main_layout.addWidget(QtWidgets.QLabel("Activate if:"))


        self.device_selector_widget = ui_common.QLimitedComboBox()
        self.device_selector_widget.currentIndexChanged.connect(self._device_selected)
        self.input_selector_widget = ui_common.QLimitedComboBox()
        self.input_selector_widget.currentIndexChanged.connect(self._input_selected)
        self.axis_repeater_widget = ui_common.QHookedProgressBar(orientation=QtCore.Qt.Orientation.Horizontal)
        self.axis_repeater_widget.valueChanged.connect(self._axis_value_changed)

        self.use_calibrated_input_widget = QtWidgets.QCheckBox("Use calibrated input")
        self.use_calibrated_input_widget.setToolTip("When enabled, the condition will use as input the calibrated data if found.  When disabled, the condition will use the raw input.")
        self.use_calibrated_input_widget.setChecked(self.condition.use_calibrated_data)
        self.use_calibrated_input_widget.clicked.connect(self._use_calibrated_input_changed)

        self.selector_container_widget = QtWidgets.QWidget()
        self.selector_container_layout = QtWidgets.QGridLayout(self.selector_container_widget)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Device:"), 0, 0)
        self.selector_container_layout.addWidget(self.device_selector_widget, 0, 1) 
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Input:"), 1, 0)
        self.selector_container_layout.addWidget(self.input_selector_widget, 1, 1) 
        self.selector_container_layout.addWidget(self.axis_repeater_widget, 2, 1)

        self.selector_container_layout.addWidget(QtWidgets.QWidget(), 0, 2) # spacer column
        
        self.selector_container_layout.addWidget(widgets, 0, 4) 
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
        self.condition.device_guid = device.device_guid
        self._populate_input_selector()

    @QtCore.Slot()
    def _input_selected(self):

        device : gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        input_type,  input_id = self.input_selector_widget.currentData()
        self.condition.device_guid = device.device_guid
        self.condition.input_type = input_type
        self.condition.input_id =  input_id
        self.condition.device_name = device.name
        
        self._update_ui()


    def _populate_device_selector(self):
        device_guid = self.condition.device_guid
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
        self.condition.device_guid = device.device_guid
    
    def _populate_input_selector(self):
        import gremlin.util
        input_id = self.condition.input_id
        input_type = self.condition.input_type
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
            self.condition.input_type = input_type
            self.condition.input_id = input_id

            # update the other UI based on input type
            self._update_ui()
            
        

    def _update_ui(self):
        ''' updates UI based on input type'''
        input_type = self.condition.input_type
        visible = False



        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
                visible = True

            case InputType.JoystickButton:
                self._button_ui()
        
            case InputType.JoystickHat:
                self._hat_ui()
            
        self.axis_repeater_widget.hookDevice(self.condition.id, self.condition.device_guid, self.condition.input_type, self.condition.input_id)
                
        self.axis_repeater_widget.setVisible(visible)

    
    def _axis_ui(self):
        """Creates the UI needed to configure an axis based condition."""
        
        gremlin.util.clear_layout(self.ui_container_layout)
        self.lower_widget = ui_common.QFloatLineEdit()
        self.lower_widget.setMinimum(-1.0)
        self.lower_widget.setMaximum(1.0)

        self.grab_low_widget = ui_common.QDataPushButton()
        self.grab_low_widget.setIcon(ui_common.Icons.recordIcon())
        self.grab_low_widget.setMaximumWidth(20)
        self.grab_low_widget.clicked.connect(self._grab_low)
        self.grab_low_widget.setToolTip("Grab axis value")

        
        self.lower_widget.setValue(self.condition.range[0])
        self.lower_widget.valueChanged.connect(self._range_lower_changed_cb)


        self.upper_widget = ui_common.QFloatLineEdit()
        self.upper_widget.setMinimum(-1.0)
        self.upper_widget.setMaximum(1.0)
        
        
        self.upper_widget.setValue(self.condition.range[1])
        self.upper_widget.valueChanged.connect(self._range_upper_changed_cb)

        self.grab_high_widget = ui_common.QDataPushButton()
        self.grab_high_widget.setIcon(load_icon("mdi.checkbox-blank-circle",qta_color = gremlin.ui.ui_common.Color.recordColor()))
        self.grab_high_widget.setMaximumWidth(20)
        self.grab_high_widget.clicked.connect(self._grab_high)
        self.grab_high_widget.setToolTip("Grab axis value")
        

        self.comparison_dropdown = ui_common.QComboBox()
        self.comparison_dropdown.addItem("Inside")
        self.comparison_dropdown.addItem("Outside")
        if not self.condition.comparison in ("inside","outside"):
            self.condition.comparison = "inside"
            
        self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.range_status_widget = ui_common.QIconLabel()
        self.range_status_widget.setIcon("mdi.checkbox-marked-outline", color = gremlin.ui.ui_common.Color.activeColor())
        

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
        self.ui_container_layout.setColumnStretch(4,2)

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
        self.comparison_dropdown = ui_common.QComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if not self.condition.comparison in ("pressed","released"):
            self.condition.comparison = "pressed"
        self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.ui_container_layout.addWidget(
            QtWidgets.QLabel(
                f"<b>{self.condition.device_name} Button {self.condition.input_id:d}</b>"
                ),
            0,
            1
        )
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget, 0, 5)
        self.ui_container_layout.setColumnStretch(5,2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

    def _hat_ui(self):
        """Creates the UI needed to configure a hat based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        directions = [
            "Center", "North", "North East", "East", "South East",
            "South", "South West", "West", "North West"
        ]

        self.comparison_dropdown = ui_common.QHatSelectorComboBox()
        if not self.condition.comparison or not self.condition.comparison.capitalize() in directions:
            self.condition.comparison = "center"

        self.comparison_dropdown.setValue(self.condition.comparison)
        self.comparison_dropdown.valueChanged.connect(self._comparison_changed_cb)
        
        input_name = f"<b>{self.condition.device_name} Hat {self.condition.input_id}</b>"

        self.ui_container_layout.addWidget(QtWidgets.QLabel(input_name),0,1)
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        



        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget,0,5)


        self.ui_container_layout.setColumnStretch(6,2)


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

        self.condition.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid) # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition.comparison =  util.hat_tuple_to_direction(event.value)
        self._create_ui()

    @QtCore.Slot()
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
        self.condition.range[0] = value


    @QtCore.Slot(float)
    def _range_upper_changed_cb(self, value):
        """Updates the upper part of an axis range.

        :param value the new value
        """
        self.condition.range[1] = value

    @QtCore.Slot()
    def _grab_low(self):
        self.lower_widget.setValue(self._axis_value()) # also updates condition_data
        

    @QtCore.Slot()
    def _grab_high(self):
        self.upper_widget.setValue(self._axis_value()) # also updates condition_data

    @QtCore.Slot(bool)
    def _use_calibrated_input_changed(self, checked):
        self.condition.use_calibrated_data = checked
        self._update_range_state(self._axis_value())

    @QtCore.Slot(float, float)
    def _axis_value_changed(self, value : float, curved_value : float):
        self._update_range_state(value)

    def _update_range_state(self, value):
        gremlin.util.InvokeUiMethod(self._update_range_state_ui, value) # ensure UI thread

    def _update_range_state_ui(self, value):
        ''' updates the range flag based on the input value '''
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
        if self.condition.input_type == InputType.JoystickButton:
            self.condition.comparison = data.casefold()
        elif self.condition.input_type == InputType.JoystickHat:
            self.condition.comparison = gremlin.types.HatDirection.to_string(data)
        elif self.condition.input_type == InputType.JoystickAxis:
            self.condition.comparison = data.casefold()
        else:
            syslog.warning(
                f"Invalid input type encountered: {self.condition.input_type}"
            )
        
        self._update_range_state(self._axis_value())


    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked):
        self.condition.ignore_release = checked

class VJoyConditionWidget(AbstractConditionWidget):

    """Widget allowing the configuration of a vJoy based condition."""

    def __init__(self, condition, parent=None):
        """Creates a new widget.

        Parameters
        ==========
        condition_data : VJoyCondition
            data to be represented by the widget
        parent : QObject
            parent of this widget
        """
        self.input_event = None
        super().__init__(condition, parent)
        self.setTitle("vJoy Condition")

        # Initialize UI fully
        self._modify_vjoy(self.vjoy_selector.get_selection())




    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return
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
            self.condition.input_type,
            self.condition.vjoy_id,
            self.condition.input_id
        )

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)
 
        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label = "Listen", callback = self._request_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition))

        widget,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                            self.paste_widget, 
                                                            self.record_button_widget,
                                                            self.delete_button_widget])


        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        label = QtWidgets.QLabel("Activate if:")
        label.setStyleSheet("background: none")


        is_trigger = True
        if self.condition.input_type == InputType.JoystickAxis:
            is_trigger = False # does not have a release mode
            self._axis_ui()
        elif self.condition.input_type == InputType.JoystickButton:
            self._button_ui()
        elif self.condition.input_type == InputType.JoystickHat:
            self._hat_ui()

        self.grid_layout.addWidget(self.vjoy_selector, 0, 0)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 2)
        self.grid_layout.addWidget(widget, 0, 3)
        self.grid_layout.setColumnStretch(2,2)

        if is_trigger:
            self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
            self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
            self.ignore_release_widget.setChecked(self.condition.ignore_release)
            self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        

        self.main_layout.addWidget(label)
        self.main_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.ui_container_widget)

        if is_trigger:
            self.main_layout.addWidget(self.ignore_release_widget)

        input_type = self.condition.input_type
        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
            case InputType.JoystickButton:
                self._button_ui()
            case InputType.JoystickHat:
                self._hat_ui()



    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked):
        self.condition.ignore_release = checked                

  		
    @QtCore.Slot()
    def _request_user_input(self):
        self.input_dialog = ui_common.InputListenerWidget(
            [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ],
            return_kb_event=False,
            multi_keys=False,
            filter_func=self._filter_input
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

    def _filter_input(self, event) -> bool:
        # only accept virtual events
        return event.is_virtual
    
    def _input_pressed_cb(self, event):
        """Processes input events to update the UI and model.

        :param event the input event to process
        """
        self.condition.device_guid = event.device_guid
        self.condition.input_type = event.event_type
        self.condition.input_id = event.identifier

        self.condition.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid) # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition.comparison =  util.hat_tuple_to_direction(event.value)
        self._create_ui()    
                    

    def _axis_ui(self):
        """Creates the UI needed to configure an axis based condition."""
        self.lower_widget = ui_common.QFloatLineEdit()
        self.lower_widget.setMinimum(-1.0)
        self.lower_widget.setMaximum(1.0)
        
        
        self.lower_widget.setValue(self.condition.range[0])
        self.lower_widget.valueChanged.connect(self._range_lower_changed_cb)
        self.upper_widget = ui_common.QFloatLineEdit()
        self.upper_widget.setMinimum(-1.0)
        self.upper_widget.setMaximum(1.0)

        self.upper_widget.setValue(self.condition.range[1])
        self.upper_widget.valueChanged.connect(self._range_upper_changed_cb)

        self.comparison_widget = ui_common.QComboBox()
        self.comparison_widget.addItem("Inside")
        self.comparison_widget.addItem("Outside")
        if not self.condition.comparison in ("inside","outside"):
            self.condition.comparison = "inside"
        self.comparison_widget.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_widget.currentTextChanged.connect(self._comparison_changed_cb)

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(self.comparison_widget)
        range_layout.addWidget(self.lower_widget)
        range_layout.addWidget(QtWidgets.QLabel("and"))
        range_layout.addWidget(self.upper_widget)
        range_layout.addStretch()

        input_label = QtWidgets.QLabel(f"<b>vJoy {self.condition.vjoy_id:d} Axis {self.condition.input_id:d}</b>")
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
        if not self.condition.comparison in ("pressed","released"):
            self.condition.comparison = "pressed"
        self.comparison_widget.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_widget.currentTextChanged.connect(self._comparison_changed_cb)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(QtWidgets.QLabel(f"<b>vJoy {self.condition.vjoy_id:d} Button {self.condition.input_id:d}</b>"))
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
        if not self.condition.comparison or not self.condition.comparison.capitalize() in directions:
            self.condition.comparison = "center"
        self.comparison_widget.setValue(self.condition.comparison)
        self.comparison_widget.valueChanged.connect(self._comparison_changed_cb)
        
        layout = QtWidgets.QHBoxLayout()

        layout.addWidget(QtWidgets.QLabel(f"<b>vJoy {self.condition.vjoy_id:d} Hat {self.condition.input_id:d}</b>"))
        layout.addWidget(QtWidgets.QLabel("is"))
        layout.addWidget(self.comparison_widget)
        layout.addStretch()

        self.ui_container_layout.addLayout(layout, 0, 1)

    def _modify_vjoy(self, data):
        # fix: 5/29/24 EMCS don't override prior value if already a valid value to prevent a condition reset
        self.condition.vjoy_id = data["device_id"]
        self.condition.input_type = data["input_type"]
        self.condition.input_id = data["input_id"]

        if data["input_type"] == InputType.JoystickAxis:
            if not self.condition.comparison in ("inside","outside"):
                self.condition.comparison = "inside"
        elif data["input_type"] == InputType.JoystickButton:
            if not self.condition.comparison in ("pressed","released"):
                self.condition.comparison = "pressed"
        elif data["input_type"] == InputType.JoystickHat:
            directions = ("center", "north", "north-east", "east", "south-east","south", "south-west", "west", "north-west")
            if not self.condition.comparison in directions:
                self.condition.comparison = "center"
        self._create_ui()
        

    def _range_lower_changed_cb(self, value):
        """Updates the lower part of an axis range.

        :param value the new value
        """
        self.condition.range[0] = value

    def _range_upper_changed_cb(self, value):
        """Updates the upper part of an axis range.

        :param value the new value
        """
        self.condition.range[1] = value

    def _comparison_changed_cb(self, data):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        if self.condition.input_type == InputType.JoystickButton:
            self.condition.comparison = data.casefold()
        elif self.condition.input_type == InputType.JoystickHat:
            self.condition.comparison = gremlin.types.HatDirection.to_string(data)
        elif self.condition.input_type == InputType.JoystickAxis:
            self.condition.comparison = data.casefold()
        else:
            syslog.warning(
                f"Invalid input type encountered: {self.condition.input_type}"
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
        if not Shiboken.isValid(self):
            return
        ui_common.clear_layout(self.main_layout)
        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)
   

        self.state_dropdown = ui_common.QComboBox()
        self.state_dropdown.addItem("Pressed")
        self.state_dropdown.addItem("Released")
        if self.condition.comparison:
            self.state_dropdown.setCurrentText(self.condition.comparison.capitalize())
        else:
            self.condition.comparison = "pressed"
        self.state_dropdown.currentTextChanged.connect(self._state_selection_changed)

        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition))
        widgets,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                             self.paste_widget,
                                                             self.delete_button_widget,
                                                             ])

        self.grid_layout.addWidget(QtWidgets.QLabel("Activate when"), 0, 0)
        self.grid_layout.addWidget(QtWidgets.QLabel("<b>this input</b>"),0,1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.state_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)


        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(widgets, 0, 6)
        self.grid_layout.setColumnStretch(4,2)
        self.main_layout.addWidget(self.grid_widget)



    def _state_selection_changed(self, label):
        """Updates the activation state of the condition.

        :param label the new activation state
        """
        self.condition.comparison = label.lower()


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
        self.input_item = None
        self.container = None
        if isinstance(action_data, gremlin.base_profile.AbstractContainer):
            self.container = action_data
            self.input_item = action_data.input_item 
        elif isinstance(action_data, gremlin.base_profile.AbstractAction):
            # find the container for the given action 
            self.container = action_data.get_container()
        elif isinstance(action_data, gremlin.base_profile.ConditionContainer):
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
        condition.setOwner(self.condition_data)
        tracker = ConditionTracker()
        mode = gremlin.shared_state.current_mode
        container = self.container
        input_item = self.input_item
        if input_item:
            data = ConditionTrackerData(mode, input_item, container, condition, rule = ActivationRule.All)
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
        if condition in self.condition_data.conditions:
            self.condition_data.conditions.remove(condition)

        if self.input_item:
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
        return self.condition_data._rule

    @rule.setter
    def rule(self, rule):
        """Sets the application rule of the conditions.

        :param rule the new application type
        """
        self.condition_data._rule = rule


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
            [InputActionCondition, InputActionConditionWidget],
        "State":
            [StateCondition, StateConditionWidget],
        "Mode":
            [ModeCondition, ModeConditionWidget]
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

        self._container = None
        self._redraw_lock = False

        self.main_layout = QtWidgets.QVBoxLayout(self)


        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.setSpacing(8)
        self.conditions_layout = QtWidgets.QVBoxLayout()

        self.main_layout.addLayout(self.controls_layout)
        self.main_layout.addLayout(self.conditions_layout)

        # Condition truth rules
        self.rule_selector = ui_common.QComboBox()
        self.rule_selector.addItem("All")
        self.rule_selector.addItem("Any")
        self.rule_selector.currentTextChanged.connect(self._rule_changed_cb)
        self.controls_layout.addWidget(QtWidgets.QLabel("Requires"))
        self.controls_layout.addWidget(self.rule_selector)
        self.controls_layout.addWidget(QtWidgets.QLabel("condition(s):"))

        self.controls_layout.addStretch()




        # Condition selector
        self.condition_selector = ui_common.QComboBox()
        self.condition_selector.addItem("Keyboard Condition", )
        self.condition_selector.addItem("Joystick Condition")
        self.condition_selector.addItem("vJoy Condition")
        self.condition_selector.addItem("Action Condition")
        self.condition_selector.addItem("State Condition")
        self.condition_selector.addItem("Mode Condition")
        
        config = gremlin.config.Configuration()
        last_selector = config.condition_selector
        index = self.condition_selector.findText(last_selector)
        if index != -1:
            self.condition_selector.setCurrentIndex(index)
        self.condition_selector.currentIndexChanged.connect(self._change_condition_selector)
        self.condition_add_button = gremlin.ui.ui_common.Buttons.getAddWidget(tooltip = "Adds a condition", callback = self._add_condition)
        
        self.controls_layout.addWidget(self.condition_selector)
        self.controls_layout.addWidget(self.condition_add_button)
        
        self.help_button = gremlin.ui.ui_common.Buttons.getHelpWidget(callback = self._show_hint)
        self.controls_layout.addWidget(self.help_button)

        copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget(callback = self._copy_condition)
        paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget(callback = self._paste_condition)

        self.controls_layout.addWidget(copy_widget)
        self.controls_layout.addWidget(paste_widget)
        



    def setContainer(self, container):
        ''' sets the container '''
        self._container = container

  		
    @QtCore.Slot()
    def _copy_condition(self):
        helper = ConditionHelper()
        helper.copy_condition(self._container.activation_condition)

    @QtCore.Slot()
    def _paste_condition(self):
        clipboard = gremlin.clipboard.Clipboard()
        helper = ConditionHelper()
        helper.paste_condition(self._container, clipboard.data)        
              

    @QtCore.Slot()
    def _change_condition_selector(self):
        config = gremlin.config.Configuration()
        config.condition_selector = self.condition_selector.currentText()

    def redraw(self):
        gremlin.util.InvokeUiMethod(self._redraw_ui) # ensure on UI thread

    def _redraw_ui(self):
        """Redraws the entire view.  must be on UI thread"""

        if not Shiboken.isValid(self):
            return
        if self._redraw_lock:
            return
        
        try:
            self._redraw_lock = True
        
        
            gremlin.util.clear_layout(self.conditions_layout)

            # create a widget for each condition
            lookup = {}
            for entry in ConditionView.condition_map.values():
                lookup[entry[0]] = entry[1]

            condition_count = self.model.rows()
            for i in range(condition_count):
                data = self.model.data(i)
                condition_widget = lookup[type(data)](data)
                condition_widget.deleted.connect(
                    lambda local_data: self.model.delete_condition(local_data)
                )
                self.conditions_layout.addWidget(condition_widget)

        finally:
            self._redraw_lock = False
            

        


    def _add_condition(self, condition = None):
        """Adds a condition to the view's model."""
        
        if not condition:
            data_type = ConditionView.condition_map[self.condition_selector.currentText().split()[0]][0]
            self.model.add_condition(data_type())
        else:
            self.model.add_condition(condition)


        

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
        self.redraw()

        


    def _show_hint(self, state):
        """Shows a help message regarding the condition types.

        :param state push button state
        """
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            hints.hint.get("cond:types", "")
        )
