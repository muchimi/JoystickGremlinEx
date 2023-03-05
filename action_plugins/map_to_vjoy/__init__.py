# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2019 Lionel Ott
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


import logging
import threading
import time
from xml.etree import ElementTree

from PyQt5 import QtWidgets, QtCore, QtGui

from gremlin.base_classes import InputActionCondition
from gremlin.common import InputType
from gremlin import input_devices, joystick_handling, util
from gremlin.error import ProfileError
from gremlin.profile import safe_format, safe_read, Profile
import gremlin.ui.common
import gremlin.ui.input_item
import os

    

class VJoyUsageState():
    ''' tracks assigned VJOY functions '''
    _free_inputs = None
    _device_list = None
    _profile = None
    _load_list = []
    

    def __init__(self, profile = None):

        if profile:
            profile = gremlin.shared_state.current_profile
            self.set_profile(profile)
        
        if not VJoyUsageState._device_list:
            VJoyUsageState._device_list = gremlin.joystick_handling.vjoy_devices()

    def push_load_list(self, device_id, input_type, input_id):
        ''' ensure data loaded by this profile is updated the first time through '''
        VJoyUsageState._load_list.append((device_id, input_type, input_id))

    def ensure_profile(self):
        if not VJoyUsageState._profile:
            self.set_profile(gremlin.shared_state.current_profile)

            for device_id, input_type, input_id in VJoyUsageState._load_list:
                self.set_state(device_id, input_type, input_id, True)
            VJoyUsageState._load_list.clear()

    def set_profile(self, profile):
        ''' loads profile data and free input lists'''
        if profile != VJoyUsageState._profile:
            VJoyUsageState._profile = profile
            VJoyUsageState._free_inputs = VJoyUsageState._profile.list_unused_vjoy_inputs()


    def map_input_type(self, input_type) -> str:
        if isinstance(input_type, InputType):
            if input_type == InputType.JoystickButton:
                name = "button"
            elif input_type == InputType.JoystickAxis:
                name = "axis"
            elif input_type == InputType.JoystickHat:
                name = "hat"
        else:
            name = input_type
        return name
    
    def get_count(self, device_id, input_type):
        self.ensure_profile()
        name = self.map_input_type(input_type)
        dev = next((d for d in VJoyUsageState._device_list if d.vjoy_id == device_id), None)
        if dev:
            if name == "axis":
                return dev.axis_count
            elif name == "button":
                return dev.button_count
            elif name == "hat":
                return dev.hat_count
        return 0

    def set_state(self, device_id, input_type, input_id, state):
        ''' sets the state of the device '''
        self.ensure_profile()
        name = self.map_input_type(input_type)
        unused_list = VJoyUsageState._free_inputs[device_id][name]
        if state:
            if input_id in unused_list:
                unused_list.remove(input_id)
                print(f"Set state: device: {device_id} type: {name} id: {input_id}")                
        else:
            # clear state
            if not input_id in unused_list:
                unused_list.append(input_id)
                unused_list.sort()                
                print(f"Clear state: device: {device_id} type: {name} id: {input_id}")

                

    def get_state(self, device_id, input_type, input_id):
        ''' returns the current usage state of the input '''
        self.ensure_profile()
        unused_list = VJoyUsageState._free_inputs[device_id][input_type]
        if input_id == 3:
            pass
        if input_id in unused_list:
            return False
        return True
    
    
    

    def used_list(self, device_id, input_type):
        ''' returns a list of used joystick IDs for the specified vjoy'''
        self.ensure_profile()
        name = self.map_input_type(input_type)
        unused_list = VJoyUsageState._free_inputs[device_id][name]
        count = self.get_count(device_id, input_type)
        if count > 0:
            return [id for id in range(1, count+1) if not id in unused_list]
        return []
    
    def unused_list(self, device_id, input_type):
        ''' returns a list of unused input IDs for the specified vjoy'''
        self.ensure_profile()
        name = self.map_input_type(input_type)
        unused_list = VJoyUsageState._free_inputs[device_id][name]
        return unused_list

    @property
    def free_inputs(self):
        return VJoyUsageState._free_inputs
    
    @property 
    def device_list(self):
        return VJoyUsageState._device_list
    
    @property 
    def input_count(self, device_id, input_type):
        ''' returns the number of input counts for a given vjoy ID and type (axis, button or hat)
        
        :device_id:
            device ID, first VJOY is index 1

        :input_type: 
            InputType.JoystickAxis
            InputType.JoystickButton
            InputType.JoystickHat
        
        '''
        return self.get_count(device_id,input_type)
    
usage_data = VJoyUsageState()

class VJoyWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Dialog which allows the selection of a vJoy output to use as
    as the remapping for the currently selected input.
    """

    # Mapping from types to display names
    type_to_name_map = {
        InputType.JoystickAxis: "Axis",
        InputType.JoystickButton: "Button",
        InputType.JoystickHat: "Hat",
        InputType.Keyboard: "Button",
    }
    name_to_type_map = {
        "Axis": InputType.JoystickAxis,
        "Button": InputType.JoystickButton,
        "Hat": InputType.JoystickHat
    }

    def __init__(self, action_data, parent=None):
        """Creates a new VjoyRemapWidget.

        :param action_data profile data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, VjoyRemap))

        


    def _create_ui(self):
        """Creates the UI components."""
        input_types = {
            InputType.Keyboard: [
                InputType.JoystickButton
            ],
            InputType.JoystickAxis: [
                InputType.JoystickAxis,
                InputType.JoystickButton
            ],
            InputType.JoystickButton: [
                InputType.JoystickButton
            ],
            InputType.JoystickHat: [
                InputType.JoystickButton,
                InputType.JoystickHat
            ]
        }

        self.valid_types = [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ]


        self.usage_state = VJoyUsageState()
        
        self.vjoy_selector = gremlin.ui.common.VJoySelector(
            lambda x: self.save_changes(),
            input_types[self._get_input_type()],
            self.action_data.get_settings().vjoy_as_input
        )

        self.main_layout.addWidget(self.vjoy_selector)

        # Create UI widgets for absolute / relative axis modes if the remap
        # action is being added to an axis input type
        self.input_type = self.action_data.input_type
     
        if self.input_type == InputType.JoystickAxis:
           self._create_input_axis()

        elif self.input_type == InputType.JoystickButton:
            self._create_input_grid()

        self.main_layout.setContentsMargins(0, 0, 0, 0)


    def _create_input_axis(self):
        ''' creates the axis input widget '''

        

        self.remap_type_widget = QtWidgets.QWidget()
        self.remap_type_layout = QtWidgets.QHBoxLayout(self.remap_type_widget)

        self.absolute_checkbox = QtWidgets.QRadioButton("Absolute")
        self.absolute_checkbox.setChecked(True)
        self.relative_checkbox = QtWidgets.QRadioButton("Relative")
        self.relative_scaling = gremlin.ui.common.DynamicDoubleSpinBox()

        self.remap_type_layout.addStretch()
        self.remap_type_layout.addWidget(self.absolute_checkbox)
        self.remap_type_layout.addWidget(self.relative_checkbox)
        self.remap_type_layout.addWidget(self.relative_scaling)
        self.remap_type_layout.addWidget(QtWidgets.QLabel("Scale"))

        self.remap_type_widget.hide()
        self.main_layout.addWidget(self.remap_type_widget)

        # The widgets should only be shown when we actually map to an axis
        if self.action_data.input_type == InputType.JoystickAxis:
            self.remap_type_widget.show()

    def _create_input_grid(self):
        ''' create a grid of buttons for easy selection'''
        
        # link all radio buttons         
        self.button_group = QtWidgets.QButtonGroup()
        self.button_group.buttonClicked.connect(self._select_changed)
        self.icon_map = {}

        self.active_id = -1

        sel = self.vjoy_selector.get_selection()
        device_id = sel['device_id']
        input_type = sel['input_type']
        input_id = sel['input_id']

        dev = next((d for d in self.usage_state.device_list if d.vjoy_id == device_id), None)
        if dev:
            count = self.usage_state.get_count(device_id, input_type)
            self.remap_type_widget = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(self.remap_type_widget)
            grid.setSpacing(2)
            self.remap_type_layout = grid
                    
            max_col = 16
            col = 0
            row = 0

            for id in range(1, count+1):
                # container for the vertical box
                v_cont = QtWidgets.QWidget()
                #v_cont.setFixedWidth(32)
                v_box = QtWidgets.QVBoxLayout(v_cont)
                v_box.setContentsMargins(0,0,0,5)
                v_box.setAlignment(QtCore.Qt.AlignCenter)

                # line 1
                h_cont = QtWidgets.QWidget()
                h_cont.setFixedWidth(36)
                h_box = QtWidgets.QHBoxLayout(h_cont)
                h_box.setContentsMargins(0,0,0,0)
                h_box.setAlignment(QtCore.Qt.AlignCenter)
                cb = QtWidgets.QRadioButton()

                self.button_group.addButton(cb)
                self.button_group.setId(cb, id)
                # if id == input_id:
                #     cb.setChecked(True)
                #     self.active_id = id
                #     self.usage_state.set_state(device_id,'button',id,True)
                name = str(id)
                h_box.addWidget(cb)
                v_box.addWidget(h_cont)

                # line 2
                h_cont = QtWidgets.QWidget()
                h_cont.setFixedWidth(36)
                h_box = QtWidgets.QHBoxLayout(h_cont)
                h_box.setContentsMargins(0,0,0,0)
                h_box.setSpacing(0)

                icon_lbl = QtWidgets.QLabel()
                
                lbl = QtWidgets.QLabel(name)

                self.icon_map[id] = icon_lbl
                
                h_box.addWidget(icon_lbl)
                h_box.addWidget(lbl)
                v_box.addWidget(h_cont)


                grid.addWidget(v_cont, row, col)
                col+=1
                if col == max_col:
                    row+=1
                    col=0

            self.main_layout.addWidget(self.remap_type_widget)

            self._populate_grid(device_id, input_type)

            
                

    def _select_changed(self, cb):
        # called when a button is toggled
        id = self.button_group.checkedId()
        #id = int(cb.objectName())
        if self.active_id == id:
            return

        if self.active_id != -1:
            # clear the old
            self.usage_state.set_state(self.action_data.vjoy_device_id,
                                    self.action_data.input_type,
                                    self.active_id,
                                    False)
        
        # set the new
        self.usage_state.set_state(self.action_data.vjoy_device_id,
                                   self.action_data.input_type,
                                   id,
                                   True )        

        self.vjoy_selector.set_selection(self.action_data.input_type, 
                                            self.action_data.vjoy_device_id,
                                            id)
        
        self.active_id = id

        


    def _populate_ui(self):
        """Populates the UI components."""
        # Get the appropriate vjoy device identifier
        vjoy_dev_id = 0
        if self.action_data.vjoy_device_id not in [0, None]:
            vjoy_dev_id = self.action_data.vjoy_device_id

        # Get the input type which can change depending on the container used
        input_type = self.action_data.input_type
        if self.action_data.parent.tag == "hat_buttons":
            input_type = InputType.JoystickButton

        # Handle obscure bug which causes the action_data to contain no
        # input_type information
        if input_type is None:
            input_type = InputType.JoystickButton
            logging.getLogger("system").warning("None as input type encountered")

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
                vjoy_input_id = input_list[0]
            else:
                vjoy_input_id = 1
        # If a valid input item is present use it
        else:
            vjoy_input_id = self.action_data.vjoy_input_id

        try:
            self.vjoy_selector.set_selection(
                input_type,
                vjoy_dev_id,
                vjoy_input_id
            )

            if self.action_data.input_type == InputType.JoystickAxis:
                if self.action_data.axis_mode == "absolute":
                    self.absolute_checkbox.setChecked(True)
                else:
                    self.relative_checkbox.setChecked(True)
                self.relative_scaling.setValue(self.action_data.axis_scaling)

                self.absolute_checkbox.clicked.connect(self.save_changes)
                self.relative_checkbox.clicked.connect(self.save_changes)
                self.relative_scaling.valueChanged.connect(self.save_changes)

            # Save changes so the UI updates properly
            self.save_changes()

        except gremlin.error.GremlinError as e:
            util.display_error(
                "A needed vJoy device is not accessible: {}\n\n".format(e) +
                "Default values have been set for the input, but they are "
                "not what has been specified."
            )
            logging.getLogger("system").error(str(e))


    
    def save_changes(self):
        """Saves UI contents to the profile data storage."""
        # Store remap data
        try:
            vjoy_data = self.vjoy_selector.get_selection()
            device_id = vjoy_data['device_id']
            input_id = vjoy_data['input_id']

            print(f"change detect: device {device_id} input id {input_id}")

            input_type_changed = self.action_data.input_type != vjoy_data["input_type"]
            input_id_changed = self.action_data.vjoy_device_id != vjoy_data["input_id"]

            self.action_data.vjoy_device_id = vjoy_data["device_id"]
            self.action_data.vjoy_input_id = vjoy_data["input_id"]
            self.action_data.input_type = vjoy_data["input_type"]

            if self.action_data.input_type == InputType.JoystickAxis:
                self.action_data.axis_mode = "absolute"
                if self.relative_checkbox.isChecked():
                    self.action_data.axis_mode = "relative"
                self.action_data.axis_scaling = self.relative_scaling.value()

            elif self.action_data.input_type == InputType.JoystickButton:
                self._populate_grid(device_id, input_id)
                print(f"used: {self.usage_state.used_list(device_id, self.action_data.input_type)}")

            # Signal changes
            if input_type_changed: # or input_id_changed:
                self.action_modified.emit()

        except gremlin.error.GremlinError as e:
            logging.getLogger("system").error(str(e))

    def _populate_grid(self, device_id, input_id):
        ''' updates the usage grid based on current VJOY mappings '''
        icon_path = os.path.join("action_plugins","map_to_vjoy")
        unused_path = os.path.join(icon_path, "unused.png")
        used_path = os.path.join(icon_path, "used.png")
        used_icon = QtGui.QIcon(used_path)
        unused_icon = QtGui.QIcon(unused_path)
        used_pixmap = QtGui.QPixmap(used_path)
        unused_pixmap = QtGui.QPixmap(unused_path)

        self.usage_state.free_inputs

        for cb in self.button_group.buttons():
            id = self.button_group.id(cb)
            
            # ctrl = self.icon_map[id]
            # ctrl.setPixmap(unused_pixmap if id in free_buttons else used_pixmap)
            if id == input_id:
                cb.setChecked(True)
                self.usage_state.set_state(device_id,'button',id,True)
            
            used = self.usage_state.get_state(device_id,'button',id)

            lbl = self.icon_map[id]
            lbl.setPixmap(used_pixmap if used else unused_pixmap)


class VJoyRemapFunctor(gremlin.base_classes.AbstractFunctor):

    """Executes a remap action when called."""

    def __init__(self, action):
        super().__init__(action)
        self.vjoy_device_id = action.vjoy_device_id
        self.vjoy_input_id = action.vjoy_input_id
        self.input_type = action.input_type
        self.axis_mode = action.axis_mode
        self.axis_scaling = action.axis_scaling

        self.needs_auto_release = self._check_for_auto_release(action)
        self.thread_running = False
        self.should_stop_thread = False
        self.thread_last_update = time.time()
        self.thread = None
        self.axis_delta_value = 0.0
        self.axis_value = 0.0

    def process_event(self, event, value):
        if self.input_type == InputType.JoystickAxis:
            if self.axis_mode == "absolute":
                joystick_handling.VJoyProxy()[self.vjoy_device_id] \
                    .axis(self.vjoy_input_id).value = value.current
            else:
                self.should_stop_thread = abs(event.value) < 0.05
                self.axis_delta_value = \
                    value.current * (self.axis_scaling / 1000.0)
                self.thread_last_update = time.time()
                if self.thread_running is False:
                    if isinstance(self.thread, threading.Thread):
                        self.thread.join()
                    self.thread = threading.Thread(
                        target=self.relative_axis_thread
                    )
                    self.thread.start()

        elif self.input_type == InputType.JoystickButton:
            if event.event_type in [InputType.JoystickButton, InputType.Keyboard] \
                    and event.is_pressed \
                    and self.needs_auto_release:
                input_devices.ButtonReleaseActions().register_button_release(
                    (self.vjoy_device_id, self.vjoy_input_id),
                    event
                )

            joystick_handling.VJoyProxy()[self.vjoy_device_id] \
                .button(self.vjoy_input_id).is_pressed = value.current

        elif self.input_type == InputType.JoystickHat:
            joystick_handling.VJoyProxy()[self.vjoy_device_id] \
                .hat(self.vjoy_input_id).direction = value.current

        return True

    def relative_axis_thread(self):
        self.thread_running = True
        vjoy_dev = joystick_handling.VJoyProxy()[self.vjoy_device_id]
        self.axis_value = vjoy_dev.axis(self.vjoy_input_id).value
        while self.thread_running:
            try:
                # If the vjoy value has was changed from what we set it to
                # in the last iteration, terminate the thread
                change = vjoy_dev.axis(self.vjoy_input_id).value - self.axis_value
                if abs(change) > 0.0001:
                    self.thread_running = False
                    self.should_stop_thread = True
                    return

                self.axis_value = max(
                    -1.0,
                    min(1.0, self.axis_value + self.axis_delta_value)
                )
                vjoy_dev.axis(self.vjoy_input_id).value = self.axis_value

                if self.should_stop_thread and \
                        self.thread_last_update + 1.0 < time.time():
                    self.thread_running = False
                time.sleep(0.01)
            except gremlin.error.VJoyError:
                self.thread_running = False

    def _check_for_auto_release(self, action):
        activation_condition = None
        if action.parent.activation_condition:
            activation_condition = action.parent.activation_condition
        elif action.activation_condition:
            activation_condition = action.activation_condition

        # If an input action activation condition is present the auto release
        # may have to be disabled
        needs_auto_release = True
        if activation_condition:
            for condition in activation_condition.conditions:
                if isinstance(condition, InputActionCondition):
                    # Remap like actions typically have an always activation
                    # condition associated with them
                    if condition.comparison != "always":
                        needs_auto_release = False

        return needs_auto_release


class VjoyRemap(gremlin.base_classes.AbstractAction):

    """Action remapping physical joystick inputs to vJoy inputs."""

    name = "VjoyRemap"
    tag = "vjoyremap"

    default_button_activation = (True, True)
    input_types = [
        InputType.JoystickAxis,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard
    ]

    functor = VJoyRemapFunctor
    widget = VJoyWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container to which this action belongs
        """
        super().__init__(parent)

        # Set vjoy ids to None so we know to pick the next best one
        # automatically
        self.vjoy_device_id = None
        self.vjoy_input_id = None
        self.input_type = self.parent.parent.input_type
        self.axis_mode = "absolute"
        self.axis_scaling = 1.0

        

    def icon(self):
        """Returns the icon corresponding to the remapped input.

        :return icon representing the remap action
        """
        # Do not return a valid icon if the input id itself is invalid
        if self.vjoy_input_id is None:
            return None

        input_string = "axis"
        if self.input_type == InputType.JoystickButton:
            input_string = "button"
        elif self.input_type == InputType.JoystickHat:
            input_string = "hat"
        return "action_plugins/map_to_vjoy/gfx/icon_{}_{:03d}.png".format(
                input_string,
                self.vjoy_input_id
            )
    


    def requires_virtual_button(self):
        """Returns whether or not the action requires an activation condition.

        :return True if an activation condition is required, False otherwise
        """
        input_type = self.get_input_type()

        if input_type in [InputType.JoystickButton, InputType.Keyboard]:
            return False
        elif input_type == InputType.JoystickAxis:
            if self.input_type == InputType.JoystickAxis:
                return False
            else:
                return True
        elif input_type == InputType.JoystickHat:
            if self.input_type == InputType.JoystickHat:
                return False
            else:
                return True

    def _parse_xml(self, node):
        """Populates the data storage with data from the XML node.

        :param node XML node with which to populate the storage
        """

        try:
            if "axis" in node.attrib:
                self.input_type = InputType.JoystickAxis
                self.vjoy_input_id = safe_read(node, "axis", int)
            elif "button" in node.attrib:
                self.input_type = InputType.JoystickButton
                self.vjoy_input_id = safe_read(node, "button", int)
            elif "hat" in node.attrib:
                self.input_type = InputType.JoystickHat
                self.vjoy_input_id = safe_read(node, "hat", int)
            elif "keyboard" in node.attrib:
                self.input_type = InputType.Keyboard
                self.vjoy_input_id = safe_read(node, "button", int)
            else:
                raise gremlin.error.GremlinError(
                    "Invalid remap type provided: {}".format(node.attrib)
                )

            self.vjoy_device_id = safe_read(node, "vjoy", int)

            # hack to sync all loaded profile setups with the status grid
            usage_data = VJoyUsageState()
            usage_data.push_load_list(self.vjoy_device_id,self.input_type,self.vjoy_input_id)
            

            if self.get_input_type() == InputType.JoystickAxis and \
                    self.input_type == InputType.JoystickAxis:
                self.axis_mode = safe_read(node, "axis-type", str, "absolute")
                self.axis_scaling = safe_read(node, "axis-scaling", float, 1.0)
        except ProfileError:
            self.vjoy_input_id = None
            self.vjoy_device_id = None

    def _generate_xml(self):
        """Returns an XML node encoding this action's data.

        :return XML node containing the action's data
        """
        node = ElementTree.Element(VjoyRemap.tag)
        node.set("vjoy", str(self.vjoy_device_id))
        if self.input_type == InputType.Keyboard:
            node.set(
                InputType.to_string(InputType.JoystickButton),
                str(self.vjoy_input_id)
            )
        else:
            node.set(
                InputType.to_string(self.input_type),
                str(self.vjoy_input_id)
            )

        if self.get_input_type() == InputType.JoystickAxis and \
                self.input_type == InputType.JoystickAxis:
            node.set("axis-type", safe_format(self.axis_mode, str))
            node.set("axis-scaling", safe_format(self.axis_scaling, float))

        

        return node

    def _is_valid(self):
        """Returns whether or not the action is configured properly.

        :return True if the action is configured correctly, False otherwise
        """
        return not(self.vjoy_device_id is None or self.vjoy_input_id is None)



        

version = 1
name = "VjoyRemap"
create = VjoyRemap


