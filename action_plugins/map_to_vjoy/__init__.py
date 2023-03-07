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
import action_plugins


class GridClickWidget(QtWidgets.QWidget):
    ''' implements a widget that reponds to a mouse click '''
    pressPos = None
    clicked = QtCore.pyqtSignal()

    def __init__(self, vjoy_device_id, input_type, vjoy_input_id, parent = None):
        super(GridClickWidget, self).__init__(parent=parent)
        self.vjoy_device_id = vjoy_device_id
        self.input_type = input_type
        self.vjoy_input_id = vjoy_input_id
        

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton :
            self.pressPos = event.pos()

    def mouseReleaseEvent(self, event):
        # ensure that the left button was pressed *and* released within the
        # geometry of the widget; if so, emit the signal;
        if (self.pressPos is not None and 
            event.button() == QtCore.Qt.LeftButton and 
            event.pos() in self.rect()):
                self.clicked.emit()
        self.pressPos = None

class GridButton(QtWidgets.QPushButton):
    def __init__(self, action):
        super(GridButton,self).__init__()
        self.action = action

    def _clicked(self):
        pass
        
    
class GridPopupWindow(QtWidgets.QDialog):
    def __init__(self, vjoy_device_id, input_type, vjoy_input_id):
        super(GridPopupWindow, self).__init__()

        self.vjoy_device_id = vjoy_device_id
        self.input_type = input_type
        self.vjoy_input_id = vjoy_input_id

        self.setWindowTitle("Mapping Details")

        usage_data = VJoyUsageState()
        action_map = usage_data.get_action_map(vjoy_device_id, input_type, vjoy_input_id)
        if not action_map:
            self.close()


        
        box = QtWidgets.QVBoxLayout()
        self.layout = box
        
        source =  QtWidgets.QWidget()
        source_box = QtWidgets.QHBoxLayout(source)
        source_box.addWidget(QtWidgets.QLabel(f"Vjoy {vjoy_device_id} Button {vjoy_input_id} mapped by:"))
        box.addWidget(source)

        for action in action_map:
            item = QtWidgets.QWidget()
            item_box = QtWidgets.QHBoxLayout(item)
            item_box.addWidget(QtWidgets.QLabel(action.device_name))
            if action.device_input_type == InputType.JoystickAxis:
                name = f"Axis {action.device_input_id}"
            elif action.device_input_type == InputType.JoystickButton:
                name = f"Button {action.device_input_id}"
            elif action.device_input_type == InputType.JoystickHat:                
                name = f"Hat {action.device_input_id}"
            item_box.addWidget(QtWidgets.QLabel(name))
            #item_box.addWidget(GridButton(action))
            box.addWidget(item)


        self.setLayout(box)


class VJoyUsageState():
    ''' tracks assigned VJOY functions '''
    _free_inputs = None
    _device_list = None
    _profile = None
    _load_list = []

    # holds the mapping by vjoy device, input and ID to a list of raw hardware defining the mapping
    _action_map = None

    # list of users buttons by vjoy device ID
    _used_map = {}
    # list of unused buttons by vjoy device ID
    _unused_map = {}

    _active_device_guid = None # guid of the hardware device
    _active_device_name = None # name of the hardware device
    _active_device_input_type = 0 # type of selected hardware input (axis, button or hat)
    _active_device_input_id = 0 # id of the function on the hardware device (button #, hat # or axis #)

    class MappingData:
        vjoy_device_id = None
        vjoy_input_type = None
        vjoy_input_id = None
        device_input_type = None
        device_guid = None
        device_name = None
        device_input_id = None

        def __init__(self, vjoy_device_id, input_type, vjoy_input_id, action_data):
            self.vjoy_device_id = vjoy_device_id
            self.vjoy_input_type = input_type
            self.vjoy_input_id = vjoy_input_id
            
            device_guid, device_name, dev_input_type, dev_input_id = action_data
            self.device_guid = device_guid
            self.device_name = device_name
            self.device_input_type = dev_input_type
            self.device_input_id = dev_input_id
            
    

    def __init__(self, profile = None):

        if profile:
            profile = gremlin.shared_state.current_profile
            self.set_profile(profile)
        
        if not VJoyUsageState._device_list:
            VJoyUsageState._device_list = gremlin.joystick_handling.vjoy_devices()

        # listen for active device changes
        el = gremlin.event_handler.EventListener()
        el.profile_device_changed.connect(self._profile_device_changed)


    def _profile_device_changed(self, event):
        VJoyUsageState._active_device_guid = event.device_guid
        VJoyUsageState._active_device_name = event.device_name
        VJoyUsageState._active_device_input_type = event.device_input_type
        VJoyUsageState._active_device_input_id = event.device_input_id

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
            self._load_inputs()
            # VJoyUsageState._free_inputs = VJoyUsageState._profile.list_unused_vjoy_inputs()

            for device_id in VJoyUsageState._free_inputs.keys():
                used = []




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
                #print(f"Set state: device: {device_id} type: {name} id: {input_id}")                
        else:
            # clear state
            if not input_id in unused_list:
                unused_list.append(input_id)
                unused_list.sort()                
                #print(f"Clear state: device: {device_id} type: {name} id: {input_id}")

                

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
    


    def _load_inputs(self):
        """Returns a list of unused vjoy inputs for the given profile.

        :return dictionary of unused inputs for each input type
        """




        vjoy_devices = joystick_handling.vjoy_devices()
        devices = self._profile.devices
        # action_plugins = gremlin.plugin_manager.ActionPlugins()

        def extract_remap_actions(action_sets):
            """Returns a list of remap actions from a list of actions.

            :param action_sets set of actions from which to extract Remap actions
            :return list of Remap actions contained in the provided list of actions
            """
            remap_actions = []
            for actions in [a for a in action_sets if a is not None]:
                for action in actions:
                    if isinstance(action, action_plugins.remap.Remap) or isinstance(action, VjoyRemap):
                        remap_actions.append(action)
            return remap_actions



        # Create list of all inputs provided by the vjoy devices
        vjoy = {}
        for entry in vjoy_devices:
            vjoy[entry.vjoy_id] = {"axis": [], "button": [], "hat": []}
            for i in range(entry.axis_count):
                vjoy[entry.vjoy_id]["axis"].append(
                    entry.axis_map[i].axis_index
                )
            for i in range(entry.button_count):
                vjoy[entry.vjoy_id]["button"].append(i+1)
            for i in range(entry.hat_count):
                vjoy[entry.vjoy_id]["hat"].append(i+1)

        # List all input types
        all_input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard
        ]

        # Create a list of all used remap actions
        remap_actions = []
        for dev in devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    for item in mode.config[input_type].values():
                        for container in item.containers:
                            action_list = extract_remap_actions(container.action_sets)
                            remap_actions.append([dev, input_type, item.input_id, action_list])
        
        action_map = {}
        # Remove all remap actions from the list of available inputs
        for dev, input_type, input_id, actions in remap_actions:
            # Skip remap actions that have invalid configuration
            if not actions:
                # no actions found
                continue
            
            for action in actions:
                type_name = InputType.to_string(action.input_type)
                if action.vjoy_input_id in [0, None] \
                        or action.vjoy_device_id in [0, None] \
                        or action.vjoy_input_id not in vjoy[action.vjoy_device_id][type_name]:
                    continue

                vjoy_device_id = action.vjoy_device_id
                vjoy_input_id = action.vjoy_input_id

                if not vjoy_device_id in action_map.keys():
                    action_map[vjoy_device_id] = {}
                if not input_type in action_map[vjoy_device_id].keys():    
                    action_map[vjoy_device_id][input_type] = {}

                if not vjoy_input_id in action_map[vjoy_device_id][input_type].keys():
                    action_map[vjoy_device_id][input_type][vjoy_input_id] = []

                action_map[vjoy_device_id][input_type][vjoy_input_id].append([dev.device_guid, dev.name, input_type, input_id])

                idx = vjoy[action.vjoy_device_id][type_name].index(action.vjoy_input_id)
                del vjoy[action.vjoy_device_id][type_name][idx]

        VJoyUsageState._free_inputs = vjoy
        VJoyUsageState._action_map = action_map

    def get_action_map(self, vjoy_device_id, input_type, input_id):
        ''' gets what's mapped to a vjoy device by input type and input id '''
        if not VJoyUsageState._action_map:
            self._load_inputs()

        if not vjoy_device_id in VJoyUsageState._action_map.keys():
            # no mappings for this vjoy device
            return []
        if not input_type in VJoyUsageState._action_map[vjoy_device_id].keys():
            # no mappings for this type of input
            return []
        if not input_id in VJoyUsageState._action_map[vjoy_device_id][input_type]:
            # no mapping for this specific id
            return []
        
        action_map = []
        for action_data in VJoyUsageState._action_map[vjoy_device_id][input_type][input_id]:
            data = VJoyUsageState.MappingData(vjoy_device_id, input_type, input_id, action_data)
            action_map.append(data)

        return action_map
    
    
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

        self.main_layout.setSpacing(0)
        
        self.vjoy_selector = gremlin.ui.common.VJoySelector(
            lambda x: self.save_changes(),
            input_types[self._get_input_type()],
            self.action_data.get_settings().vjoy_as_input
        )

        
        self.main_layout.addWidget(self.vjoy_selector)
        self._create_header()

        # Create UI widgets for absolute / relative axis modes if the remap
        # action is being added to an axis input type
        self.input_type = self.action_data.input_type
     
        if self.input_type == InputType.JoystickAxis:
           self._create_input_axis()

        elif self.input_type == InputType.JoystickButton:
            self._create_button_options()
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


    def _create_header(self):
        ''' shows what device is currently selected '''
        header  =  QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(header)
        box.addWidget(QtWidgets.QLabel(VJoyUsageState._active_device_name))
        input_type = VJoyUsageState._active_device_input_type
        input_id = VJoyUsageState._active_device_input_id
        if input_type == InputType.JoystickAxis:
            if input_id == 1:
                axis_name = "X"
            elif input_id == 2:
                axis_name = "Y"
            elif input_id == 3:
                axis_name = "Z"      
            elif input_id == 4:
                axis_name = "RX"
            elif input_id == 5:
                axis_name = "RY"
            elif input_id == 6:
                axis_name = "RZ"
            elif input_id == 7:
                axis_name = "S1"                                                                          
            elif input_id == 8:
                axis_name = "S2"                
            else:
                axis_name = "(unknown)"
            name = f"Axis {input_id} ({axis_name})"
        elif input_type == InputType.JoystickButton:
            name = f"Button {input_id}"
        elif input_type == InputType.JoystickHat:                
            name = f"Hat {input_id}"
        box.addWidget(QtWidgets.QLabel(name))
        box.addStretch()

        self.main_layout.addWidget(header)

    def _create_button_options(self):
        ''' creates the button option panel '''
        self.option_widget =  QtWidgets.QWidget()
        option_box = QtWidgets.QHBoxLayout(self.option_widget)
        self.cb_action_list = QtWidgets.QComboBox()

        lbl = QtWidgets.QLabel("Behavior:")

        option_box.addWidget(lbl)
        option_box.addWidget(self.cb_action_list)
        self.cb_action_list.addItem("Default",VjoyAction.VJoyNormal)
        self.cb_action_list.addItem("Pulse",VjoyAction.VJoyPulse)
        self.cb_action_list.addItem("Toggle",VjoyAction.VJoyToggle)
        self.cb_action_list.setFixedWidth(60)
        self.main_layout.addWidget(self.option_widget)

        # pulse panel

        self.pulse_widget = QtWidgets.QWidget()
        delay_box = QtWidgets.QHBoxLayout(self.pulse_widget)
        self.pulse_spin_widget = QtWidgets.QSpinBox()
        self.pulse_spin_widget.setMinimum(0)
        self.pulse_spin_widget.setMaximum(60000)
        delay_box.addWidget(QtWidgets.QLabel("Duration (ms):"))
        delay_box.addWidget(self.pulse_spin_widget)



        self.start_widget = QtWidgets.QWidget()
        self.start_button_group = QtWidgets.QButtonGroup()
        
        start_layout = QtWidgets.QHBoxLayout(self.start_widget)
        self.rb_start_released = QtWidgets.QRadioButton("Released")
        self.rb_start_pressed = QtWidgets.QRadioButton("Pressed")
        
        self.start_button_group.addButton(self.rb_start_released)
        self.start_button_group.addButton(self.rb_start_pressed)

        self.start_button_group.setId(self.rb_start_released, 0)
        self.start_button_group.setId(self.rb_start_pressed, 1)

        if self.action_data.start_pressed:
            self.rb_start_pressed.setChecked(True)
        else:
            self.rb_start_released.setChecked(True)

        start_layout.addWidget(QtWidgets.QLabel("Start Mode:"))
        start_layout.addWidget(self.rb_start_released )
        start_layout.addWidget(self.rb_start_pressed )

        # add the two containers to the option line

        option_box.addWidget(self.start_widget)
        option_box.addWidget(self.pulse_widget)
        option_box.addStretch()


        # update based on current mode
        self._action_mode_changed(self.action_data.action_mode)
       
        # hook events
        self.cb_action_list.currentIndexChanged.connect(self._action_mode_changed)
        self.pulse_spin_widget.valueChanged.connect(self._pulse_value_changed)
        self.start_button_group.buttonClicked.connect(self._start_changed)

    def _action_mode_changed(self, index):
        ''' called when the drop down value changes '''
        action = self.cb_action_list.itemData(index)
        if action == VjoyAction.VJoyPulse:
            self.pulse_widget.setVisible(True)
            self.start_widget.setVisible(False)
        else:
            self.pulse_widget.setVisible(False)
            self.start_widget.setVisible(True)

        self.action_data.action_mode = action

    def _pulse_value_changed(self, value):
        ''' called when the pulse value changes '''
        if value >= 0:
            self.action_data.pulse_delay = value


    def _start_changed(self, rb):
        ''' called when the start mode is changed '''
        id = self.start_button_group.checkedId()
        self.action_data.start_pressed = id == 1



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

            vjoy_device_id = dev.vjoy_id
            input_type = InputType.JoystickButton


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
                line2_cont = GridClickWidget(vjoy_device_id, input_type, id)
                line2_cont.setFixedWidth(36)
                h_box = QtWidgets.QHBoxLayout(line2_cont)
                h_box.setContentsMargins(0,0,0,0)
                h_box.setSpacing(0)
                

                icon_lbl = QtWidgets.QLabel()
                
                lbl = QtWidgets.QLabel(name)
                

                self.icon_map[id] = icon_lbl
                
                h_box.addWidget(icon_lbl)
                h_box.addWidget(lbl)
                v_box.addWidget(line2_cont)

                line2_cont.clicked.connect(self._grid_button_clicked)


                grid.addWidget(v_cont, row, col)
                col+=1
                if col == max_col:
                    row+=1
                    col=0

            self.main_layout.addWidget(self.remap_type_widget)

            self._populate_grid(device_id, input_type)

            
    def _grid_button_clicked(self):
        sender = self.sender()
        vjoy_device_id = sender.vjoy_device_id
        input_type = sender.input_type
        vjoy_input_id = sender.vjoy_input_id

        popup = GridPopupWindow(vjoy_device_id, input_type, vjoy_input_id)
        popup.exec()
                

    def _select_changed(self, rb):
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
        

        self.usage_state.set_state(self.action_data.vjoy_device_id,
                                   self.action_data.input_type,
                                   id,
                                   True )        


        # set the new
        self.active_id = id
        self.vjoy_selector.set_selection(self.action_data.input_type, 
                                            self.action_data.vjoy_device_id,
                                            id)

        # update the UI when a state change occurs
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = VJoyUsageState._active_device_guid
        event.device_name = VJoyUsageState._active_device_name
        event.device_input_type = VJoyUsageState._active_device_input_type
        event.device_input_id = VJoyUsageState._active_device_input_id
        event.input_type = self.action_data.input_type
        event.input_id = id
        el.profile_device_mapping_changed.emit(event)


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

            elif self.action_data.input_type == InputType.JoystickButton:
                self.cb_action_list.setCurrentIndex(self.action_data.action_mode)
                self.pulse_spin_widget.setValue(self.action_data.pulse_delay)
                if self.action_data.start_pressed:
                    self.rb_start_pressed.setChecked(True)
                else:
                    self.rb_start_released.setChecked(True)

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

            # print(f"change detect: device {device_id} input id {input_id}")


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
                #print(f"used: {self.usage_state.used_list(device_id, self.action_data.input_type)}")

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

    def findMainWindow(self):
        # Global function to find the (open) QMainWindow in application
        app = QtWidgets.QApplication.instance()
        for widget in app.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMainWindow):
                return widget
        return None

    def __init__(self, action):
        super().__init__(action)
        self.vjoy_device_id = action.vjoy_device_id
        self.vjoy_input_id = action.vjoy_input_id
        self.input_type = action.input_type
        self.axis_mode = action.axis_mode
        self.axis_scaling = action.axis_scaling
        self.action_mode = action.action_mode
        self.pulse_delay = action.pulse_delay
        self.start_pressed = action.start_pressed

        self.needs_auto_release = self._check_for_auto_release(action)
        self.thread_running = False
        self.should_stop_thread = False
        self.thread_last_update = time.time()
        self.thread = None
        self.axis_delta_value = 0.0
        self.axis_value = 0.0

        self.lock = threading.Lock()

          
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)


    def _profile_start(self):
        # setup initial state
        if self.input_type == InputType.JoystickButton:
            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = self.start_pressed
	
    # async routine to pulse a button
    def _fire_pulse(self, *args):

        self.lock.acquire()
        vjoy_device_id, vjoy_input_id, duration = args
        # vjoy_device_id = args]
        # vjoy_input_id = args[2]
        # duration = args[3]

        button = joystick_handling.VJoyProxy()[vjoy_device_id].button(vjoy_input_id)
        button.is_pressed = True
        time.sleep(duration)
        button.is_pressed = False
        self.lock.release()

    def process_event(self, event, value):
        ''' runs when a joystick even occurs like a button press or axis movement '''
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

            if self.action_mode == VjoyAction.VJoyNormal:
                # normal default behavior
                if event.event_type in [InputType.JoystickButton, InputType.Keyboard] \
                        and event.is_pressed \
                        and self.needs_auto_release:
                    input_devices.ButtonReleaseActions().register_button_release(
                        (self.vjoy_device_id, self.vjoy_input_id),
                        event
                    )
            elif self.action_mode == VjoyAction.VJoyToggle:
                # toggle action
                if event.event_type in [InputType.JoystickButton, InputType.Keyboard] \
                        and event.is_pressed:
                    button = joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id)
                    button.is_pressed = not button.is_pressed
            elif self.action_mode == VjoyAction.VJoyPulse:
                # pulse action
                if not self.lock.locked():
                    threading.Timer(0.01, self._fire_pulse, [self.vjoy_device_id, self.vjoy_input_id, self.pulse_delay/1000]).start()

            else:
                # basic handling
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


class VjoyAction:
    ''' defines available vjoy actions supported by this plugin'''
    VJoyNormal = 0 # normal
    VJoyToggle = 1 # toggle function on/off
    VJoyPulse = 2 # pulse function (pulses a button)

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
        self.action_mode = VjoyAction.VJoyNormal
        self.current_state = 0 # toggle value for the input 1 means set, any other value means not set for buttons
        self.pulse_delay = 250 # pulse delay
        self.start_pressed = False # true if a button starts as pressed when the profile is loaded

        

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
            
            self.action_mode = VjoyAction.VJoyNormal
            self.pulse_delay = 250

            if self.get_input_type() == InputType.JoystickAxis and \
                self.input_type == InputType.JoystickAxis:
                self.axis_mode = safe_read(node, "axis-type", str, "absolute")
                self.axis_scaling = safe_read(node, "axis-scaling", float, 1.0)
            elif self.get_input_type() == InputType.JoystickButton and self.input_type == InputType.JoystickButton:

                if "action_mode" in node.attrib:
                    self.action_mode = safe_read(node,"action_mode", int, VjoyAction.VJoyNormal)
                if "pulse_delay" in node.attrib:
                    self.pulse_delay = safe_read(node,"pulse_delay", int, 250)
                if "start_pressed" in node.attrib:
                    self.start_pressed = safe_read(node,"start_pressed", bool, False)
                    pass


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

        if self.get_input_type() == InputType.JoystickAxis and self.input_type == InputType.JoystickAxis:
            node.set("axis-type", safe_format(self.axis_mode, str))
            node.set("axis-scaling", safe_format(self.axis_scaling, float))

        elif self.get_input_type() == InputType.JoystickButton and self.input_type == InputType.JoystickButton:
            node.set("action_mode", safe_format(self.action_mode, int))
            node.set("pulse_delay", safe_format(self.pulse_delay, int))
            node.set("start_pressed", safe_format(self.start_pressed, bool))

        

        return node

    def _is_valid(self):
        """Returns whether or not the action is configured properly.

        :return True if the action is configured correctly, False otherwise
        """
        return not(self.vjoy_device_id is None or self.vjoy_input_id is None)



        

version = 1
name = "VjoyRemap"
create = VjoyRemap


