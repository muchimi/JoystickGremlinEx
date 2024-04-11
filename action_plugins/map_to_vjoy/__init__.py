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


import logging
import threading
import time
from xml.etree import ElementTree

from PySide6 import QtWidgets, QtCore, QtGui

from gremlin.base_classes import InputActionCondition
from gremlin.common import InputType
from gremlin import input_devices, joystick_handling, util
from gremlin.error import ProfileError
from gremlin.profile import safe_format, safe_read, Profile, parse_guid, write_guid
import gremlin.ui.common
import gremlin.ui.input_item
import os
import action_plugins
import enum
from gremlin.input_devices import VjoyAction, remote_state


IdMapToButton = -2 # map to button special ID
syslog = logging.getLogger("system")




class GridClickWidget(QtWidgets.QWidget):
    ''' implements a widget that reponds to a mouse click '''
    pressPos = None
    clicked = QtCore.Signal()

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
            event.button() == QtCore.Qt.LeftButton and   event.pos() in self.rect()):
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
 
    _axis_invert_map = {} # holds map of inverted axes for output
    _axis_range_map = {} # holds active axis range maps

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
        self.ensure_vjoy()


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

    def ensure_vjoy(self):
        ''' ensures the inversion map is loaded '''
        if not self._axis_invert_map:
            joystick_handling.joystick_devices_initialization()
            devices = joystick_handling.vjoy_devices()
            if devices:
                for dev in devices:
                    dev_id = dev.vjoy_id
                    VJoyUsageState._axis_invert_map[dev_id] = {}
                    VJoyUsageState._axis_range_map[dev_id] = {}
                    for axis_id in range(1, dev.axis_count+1):
                        VJoyUsageState._axis_invert_map[dev_id][axis_id] = False
                        VJoyUsageState._axis_range_map[dev_id][axis_id] = [-1.0, 1.0]

    def set_inverted(self, device_id, input_id, inverted):
        ''' sets the inversion flag for a given vjoy device '''
        VJoyUsageState._axis_invert_map[device_id][input_id] = inverted
        
    def is_inverted(self, device_id, input_id):
        ''' returns true if the specified device/axis is inverted '''
        return VJoyUsageState._axis_invert_map[device_id][input_id]
    
    def toggle_inverted(self, device_id, input_id):
        ''' toggles inversion state of specified device/axis is inverted '''
        VJoyUsageState._axis_invert_map[device_id][input_id] = not VJoyUsageState._axis_invert_map[device_id][input_id]
        syslog.debug(f"Vjoy Axis {device_id} {input_id} inverted state: {VJoyUsageState._axis_invert_map[device_id][input_id]}")

    def set_range(self, device_id, input_id, min_range = -1.0, max_range = 1.0):
        ''' sets the axis min/max range for the active range computation '''
        if min_range > max_range:
            r = min_range
            min_range = max_range
            max_range = r
            
        VJoyUsageState._axis_range_map[device_id][input_id] = [min_range, max_range]

    def get_range(self, device_id, input_id):
        ''' gets the current range for an axis (min,max)'''
        return VJoyUsageState._axis_range_map[device_id][input_id]
    




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
        # if input_id == 3:
        #     pass
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


        # Create UI widgets for absolute / relative axis modes if the remap
        # action is being added to an axis input type
        self.input_type = self.action_data.input_type
       
        #self.main_layout.addWidget(self.vjoy_selector)
        

        # add the selector
        self._create_selector()
        self._create_input_axis()
        self._create_input_grid()
        self._create_info()

        self.main_layout.setContentsMargins(0, 0, 0, 0)

    def _get_selector_input_type(self):
        ''' gets a modified input type based on the current mode '''
        input_type = self._get_input_type()
        if input_type == InputType.JoystickButton and \
                        self.action_data.action_mode in (VjoyAction.VJoySetAxis,
                                                         VjoyAction.VJoyInvertAxis,
                                                         VjoyAction.VJoyRangeAxis):
            return InputType.JoystickAxis
        return self._get_input_type()

    def _create_input_axis(self):
        ''' creates the axis input widget '''



        self.axis_widget = QtWidgets.QWidget()
        axis_grid = QtWidgets.QGridLayout(self.axis_widget)
        axis_grid.setColumnStretch(8,1)
        
        self.reverse_checkbox = QtWidgets.QCheckBox("Reverse")

        self.absolute_checkbox = QtWidgets.QRadioButton("Absolute")
        self.absolute_checkbox.setChecked(True)
        self.relative_checkbox = QtWidgets.QRadioButton("Relative")
        self.relative_scaling = gremlin.ui.common.DynamicDoubleSpinBox()


        self.sb_start_value = gremlin.ui.common.DynamicDoubleSpinBox()
        # w = 100
        # self.set_width(self.sb_start_value,w)
        self.sb_start_value.setMinimum(-1.0)
        self.sb_start_value.setMaximum(1.0)
        self.sb_start_value.setDecimals(3)


        self.b_min_value = QtWidgets.QPushButton("-1")
        w = 32
        self.set_width(self.b_min_value,w)
        self.b_center_value = QtWidgets.QPushButton("0")
        
        self.set_width(self.b_center_value,w)
        self.b_max_value = QtWidgets.QPushButton("+1")
        self.set_width(self.b_max_value,w)

        self.sb_axis_range_low = gremlin.ui.common.DynamicDoubleSpinBox()
        self.sb_axis_range_low.setMinimum(-1.0)
        self.sb_axis_range_low.setMaximum(1.0)
        self.sb_axis_range_low.setDecimals(3)
        self.sb_axis_range_high = gremlin.ui.common.DynamicDoubleSpinBox()
        self.sb_axis_range_high.setMinimum(-1.0)
        self.sb_axis_range_high.setMaximum(1.0)        
        self.sb_axis_range_high.setDecimals(3)

        

        row = 0
        col = 0
        axis_grid.addWidget(QtWidgets.QLabel("Reverse Axis:"),row,col)
        row+=1
        axis_grid.addWidget(self.reverse_checkbox,row,col)

        row = 0
        col+=1
        axis_grid.addWidget(QtWidgets.QLabel("Output Mode:"),row,col)
        row+=1
        axis_grid.addWidget(self.absolute_checkbox,row,col)
        row+=1
        axis_grid.addWidget(self.relative_checkbox,row,col)


        row = 0
        col+=1
        axis_grid.addWidget(QtWidgets.QLabel("Start Value:"),row,col,1,3)

        row+=1
        axis_grid.addWidget(self.sb_start_value,row,col,1,3)

        row+=1
        axis_grid.addWidget(self.b_min_value,row,col)
        col+=1
        axis_grid.addWidget(self.b_center_value,row,col)
        col+=1
        axis_grid.addWidget(self.b_max_value,row,col)

        row = 0
        col+=1
        axis_grid.addWidget(QtWidgets.QLabel("Axis"),row,col)
        row+=1
        axis_grid.addWidget(QtWidgets.QLabel("Scale:"),row,col)
        row+=1
        axis_grid.addWidget(self.relative_scaling,row,col)

        row = 0
        col+=1
        axis_grid.addWidget(QtWidgets.QLabel("Axis Output Range:"),row,col,1,2)
        row+=1
        axis_grid.addWidget(QtWidgets.QLabel("Min:"),row,col)
        row+=1
        axis_grid.addWidget(self.sb_axis_range_low,row,col)

        col+=1
        row=1
        axis_grid.addWidget(QtWidgets.QLabel("Max:"),row,col)
        row+=1
        axis_grid.addWidget(self.sb_axis_range_high,row,col)

        self.main_layout.addWidget(self.axis_widget)
        

        self.reverse_checkbox.clicked.connect(self._axis_reverse_changed) 
        self.absolute_checkbox.clicked.connect(self._axis_mode_changed)
        self.relative_checkbox.clicked.connect(self._axis_mode_changed)
        self.relative_scaling.valueChanged.connect(self._axis_scaling_changed)

        self.sb_start_value.valueChanged.connect(self._axis_start_value_changed)
        self.b_min_value.clicked.connect(self._b_min_start_value_clicked)
        self.b_center_value.clicked.connect(self._b_center_start_value_clicked)
        self.b_max_value.clicked.connect(self._b_max_start_value_clicked)


        self.sb_axis_range_low.valueChanged.connect(self._axis_range_low_changed)
        self.sb_axis_range_high.valueChanged.connect(self._axis_range_high_changed)


    def get_axis_name(self, input_id):
        ''' gets the axis name based on the input # '''
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
        return axis_name

    def _create_info(self):
        ''' shows what device is currently selected '''
        header  =  QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(header)
        box.addWidget(QtWidgets.QLabel(VJoyUsageState._active_device_name))
        input_type = VJoyUsageState._active_device_input_type
        input_id = VJoyUsageState._active_device_input_id
        vjoy_device_id = self.action_data.vjoy_device_id      
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

        if input_type == InputType.JoystickAxis:
            axis_name = self.get_axis_name(input_id)
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} axis {vjoy_input_id} ({self.get_axis_name(vjoy_input_id)})"
            name = f"Axis {input_id} ({axis_name}) -> {action_name}"
        elif input_type == InputType.JoystickButton:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} button {vjoy_input_id}"
            name = f"Button {input_id} -> {action_name}"
        elif input_type == InputType.JoystickHat:                
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} hat {vjoy_input_id}"
            name = f"Hat {input_id} -> {action_name}"
        else:
            name = f"Unknown input type: {input_type}"
        
        
        box.addWidget(QtWidgets.QLabel(name))
        # if syslog.isEnabledFor(logging.DEBUG):
        #     box.addWidget(QtWidgets.QLabel(f"Id: {self.action_data.action_id}"))
        box.addStretch()

        self.main_layout.addWidget(header)


    def set_width(self, widget, width, height = 22):
        widget.setFixedSize(width, height)



    def _create_selector(self):
        ''' creates the button option panel '''
        self.selector_widget =  QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.selector_widget)
        grid.setColumnStretch(3,1)


        # behavior combo box  - lets the user select the output behavior
        self.cb_action_list = gremlin.ui.common.NoWheelComboBox()
        self.cb_action_list.currentIndexChanged.connect(self._action_mode_changed)
        lbl = QtWidgets.QLabel("Mode:")
       
        row = 0
        grid.addWidget(lbl,row,0)
        grid.addWidget(self.cb_action_list, row, 1)

        self.action_label = QtWidgets.QLabel()
        grid.addWidget(self.action_label,row,2,1,3)


        # vjoy device selection - display vjoy target ID and vjoy target input - the input changes based on the behavior

        row = 2        
        self.lbl_vjoy_device_selector = QtWidgets.QLabel("Device:")
        grid.addWidget(self.lbl_vjoy_device_selector,row,0)
        self.cb_vjoy_device_selector = gremlin.ui.common.NoWheelComboBox()
        grid.addWidget(self.cb_vjoy_device_selector,row,1)
        
                             
        self.vjoy_map = {} # holds the count of axes for 
        devices = sorted(joystick_handling.vjoy_devices(),key=lambda x: x.vjoy_id)
        for dev in devices:
            self.cb_vjoy_device_selector.addItem(f"VJoy device {dev.vjoy_id}", dev.vjoy_id)
            self.vjoy_map[dev.vjoy_id] = dev
        

        row = 3
        self.cb_vjoy_input_selector = gremlin.ui.common.NoWheelComboBox()
        self.lbl_vjoy_input_selector = QtWidgets.QLabel("Output:")
        grid.addWidget(self.lbl_vjoy_input_selector,row,0)
        grid.addWidget(self.cb_vjoy_input_selector,row,1)

        row = 4

        source =  QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(source)

        self.chkb_exec_on_release = QtWidgets.QCheckBox("Exec on release")
        box.addWidget(self.chkb_exec_on_release)

        self.chkb_paired = QtWidgets.QCheckBox("Paired Group Member")
        box.addWidget(self.chkb_paired)


        grid.addWidget(source, row, 1)

        # selector hooks
        self.cb_vjoy_device_selector.currentIndexChanged.connect(self._vjoy_device_id_changed)
        self.cb_vjoy_input_selector.currentIndexChanged.connect(self._vjoy_input_id_changed)


        # second hardware input selector
        row = 4
        self.lbl_input_device_a = QtWidgets.QLabel("Axis A Input Device:")
        self.lbl_input_axis_a = QtWidgets.QLabel("Axis A Input Axis:")
        self.lbl_input_device_name_a = QtWidgets.QLabel(self.action_data.hardware_device.name)
        self.lbl_input_axis_name_a = QtWidgets.QLabel(self.get_axis_name(self.action_data.hardware_input_id))

        self.lbl_input_device_b = QtWidgets.QLabel("Axis B Input Device:")
        self.lbl_input_axis_b = QtWidgets.QLabel("Axis B Input Axis:")
        self.hardware_device = gremlin.ui.common.NoWheelComboBox()
        self.hardware_axis = gremlin.ui.common.NoWheelComboBox()
        self.hardware_device.currentIndexChanged.connect(self._hardware_device_changed)
        self.hardware_axis.currentIndexChanged.connect(self._hardware_axis_changed)

        grid.addWidget(self.lbl_input_device_a, row, 0)
        grid.addWidget(self.lbl_input_device_name_a, row, 1)
        grid.addWidget(self.lbl_input_device_b, row, 2)
        grid.addWidget(self.hardware_device, row, 3)
        row = 5

        grid.addWidget(self.lbl_input_axis_a, row, 0)
        grid.addWidget(self.lbl_input_axis_name_a, row, 1)
        grid.addWidget(self.lbl_input_axis_b, row, 2)
        grid.addWidget(self.hardware_axis, row, 3)
        

        # pulse panel
        
        self.pulse_widget = QtWidgets.QWidget()
        delay_box = QtWidgets.QHBoxLayout(self.pulse_widget)
        self.pulse_spin_widget = QtWidgets.QSpinBox()
        self.pulse_spin_widget.setMinimum(0)
        self.pulse_spin_widget.setMaximum(60000)
        lbl = QtWidgets.QLabel("Duration (ms):")
        delay_box.addWidget(lbl)
        delay_box.addWidget(self.pulse_spin_widget)
        delay_box.addStretch()
        

        
        self.target_value_widget = QtWidgets.QWidget()
        target_value_box = QtWidgets.QHBoxLayout(self.target_value_widget)
        lbl = QtWidgets.QLabel("Value:")
        target_value_box.addWidget(lbl)
        self.target_value_text = QtWidgets.QLineEdit()
        v = QtGui.QDoubleValidator(-1.0, 1.0, 2)
        v.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        self.target_value_text.setText(f"{self.action_data.target_value:0.2f}")
        self.target_value_text.setValidator(v)
        target_value_box.addWidget(self.target_value_text)
        target_value_box.addWidget(QtWidgets.QLabel("-1.00 .. 0.00 .. +1.00"))
        target_value_box.addStretch()


        # start button state widget
        
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
        start_layout.addStretch()

        # set axis range widget
        self.axis_range_value_widget = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(self.axis_range_value_widget)
        self.sb_button_range_low = gremlin.ui.common.DynamicDoubleSpinBox()
        self.sb_button_range_low.setMinimum(-1.0)
        self.sb_button_range_low.setMaximum(1.0)
        self.sb_button_range_low.setDecimals(3)
        self.sb_button_range_high = gremlin.ui.common.DynamicDoubleSpinBox()
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
        self.button_to_axis_widget = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(self.button_to_axis_widget)
        self.sb_button_to_axis_value = gremlin.ui.common.DynamicDoubleSpinBox()
        self.sb_button_to_axis_value.setMinimum(-1.0)
        self.sb_button_to_axis_value.setMaximum(1.0)
        self.sb_button_to_axis_value.setDecimals(3)
        box.addWidget(QtWidgets.QLabel("Axis Value:"))
        box.addWidget(self.sb_button_to_axis_value)
        box.addStretch()

        self.main_layout.addWidget(self.selector_widget)
        self.main_layout.addWidget(self.pulse_widget)
        self.main_layout.addWidget(self.start_widget)
        self.main_layout.addWidget(self.target_value_widget)
        self.main_layout.addWidget(self.axis_range_value_widget)
        self.main_layout.addWidget(self.button_to_axis_widget)
       
        # hook events

        
        

        self.chkb_exec_on_release.clicked.connect(self._exec_on_release_changed)
        self.chkb_paired.clicked.connect(self._paired_changed)
        self.target_value_text.textChanged.connect(self._target_value_changed)
        self.pulse_spin_widget.valueChanged.connect(self._pulse_value_changed)
        self.start_button_group.buttonClicked.connect(self._start_changed)
        self.sb_button_range_low.valueChanged.connect(self._button_range_low_changed)
        self.sb_button_range_high.valueChanged.connect(self._button_range_high_changed)
        self.sb_button_to_axis_value.valueChanged.connect(self._button_to_axis_value_changed)


        self.b_range_reset.clicked.connect(self._b_range_reset_clicked)
        self.b_range_half.clicked.connect(self._b_range_half_clicked)
        self.b_range_lhalf.clicked.connect(self._b_range_lhalf_clicked)
        self.b_range_hhalf.clicked.connect(self._b_range_hhalf_clicked)
        self.b_range_bottom.clicked.connect(self._b_range_bot_clicked)
        self.b_range_top.clicked.connect(self._b_range_top_clicked)


        
    def load_actions_from_input_type(self):
        ''' occurs when the type of input is changed '''
        with QtCore.QSignalBlocker(self.cb_action_list):
            self.cb_action_list.clear()

            actions = ()
            if self.action_data.input_type == InputType.JoystickAxis:
                # axis can only set an axis
                actions = (VjoyAction.VJoyAxis, VjoyAction.VJoyAxisToButton) #, VjoyAction.VjoyMergeAxis)
                
                
            elif self.action_data.input_type == InputType.JoystickButton:
                # various button modes
                actions = ( VjoyAction.VJoyButton,
                            VjoyAction.VJoyPulse,
                            VjoyAction.VJoyToggle,
                            VjoyAction.VJoyInvertAxis,
                            VjoyAction.VJoySetAxis,
                            VjoyAction.VJoyRangeAxis,
                            #VjoyAction.VjoyMergeAxis,
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
                
            elif self.action_data.input_type == InputType.JoystickHat:
                # hat mode is the only mode
                actions = (VjoyAction.VJoyHat)

            for action in actions:
                self.cb_action_list.addItem(VjoyAction.to_name(action), action)                

    def _vjoy_device_id_changed(self, index):
        ''' occurs when the vjoy output device is changed '''
        with QtCore.QSignalBlocker(self.cb_vjoy_device_selector):
            device_id = self.cb_vjoy_device_selector.itemData(index)
            self.action_data.vjoy_device_id = device_id
            self._update_vjoy_device_input_list()
            self.notify_device_changed()
        

    def _vjoy_input_id_changed(self, index):
        ''' occurs when the vjoy output input ID is changed '''
        with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):
            input_id = self.cb_vjoy_input_selector.itemData(index)
            self.action_data.set_input_id(input_id)
            #self._update_ui_action_mode(self.action_data.action_mode)
            self._populate_grid(self.action_data.vjoy_device_id, input_id)
            self.notify_device_changed()


    def _hardware_device_changed(self, index):
        ''' occurs when the hardware device input is changed '''
        with QtCore.QSignalBlocker(self.hardware_device):
            device = self.hardware_device.itemData(index)
            self.action_data.merge_device_b_guid = device.device_guid
            self._populate_hardware_axis()

    def _hardware_axis_changed(self, index):
        ''' occurs when the hardware device axis input is changed'''
        with QtCore.QSignalBlocker(self.hardware_axis):
            axis = self.hardware_axis.itemData(index)
            self.action_data.merge_device_b_axis = axis


    def notify_device_changed(self):
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = usage_data._active_device_guid
        event.device_name = usage_data._active_device_name
        event.device_input_type = self.action_data.input_type
        event.device_input_id = usage_data._active_device_input_id
        event.vjoy_device_id = self.action_data.vjoy_device_id
        event.vjoy_input_id = self.action_data.vjoy_input_id
        el.profile_device_changed.emit(event)
        el.icon_changed.emit(event)

    def _update_vjoy_device_input_list(self):
        ''' loads a list of valid outputs for the current vjoy device based on the mode '''
        with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):
            self.cb_vjoy_input_selector.clear()
            input_type = self._get_selector_input_type()
            action_mode = self._get_action_mode()

            dev = self.vjoy_map[self.action_data.vjoy_device_id]
            if input_type == InputType.JoystickAxis and action_mode != VjoyAction.VJoyAxisToButton:
                count = dev.axis_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Axis {id} {self.get_axis_name(id)}",id)
            elif input_type == InputType.JoystickButton or action_mode == VjoyAction.VJoyAxisToButton:
                count = dev.button_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Button {id}",id)
            elif input_type == InputType.JoystickHat:
                count = dev.button_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Hat {id}",id)
            index = self.cb_vjoy_input_selector.findData(self.action_data.vjoy_input_id)
            if index == -1:
                raise ValueError(f"Unable to set input box: input id not found: {self.action_data.vjoy_input_id}")
            self.cb_vjoy_input_selector.setCurrentIndex(index)
            self._populate_grid(self.action_data.vjoy_device_id, self.action_data.vjoy_input_id)


    def _target_value_changed(self, value):
        ''' called when the value box changes '''
        if value.isnumeric():
            value = float(value)
            self.action_data.target_value = value
            self.target_value_valid = True
        else:
            self.target_value_valid = False

    def _update_ui_action_mode(self, action_data):
        ''' updates ui based on the current action requested to show/hide needed components '''
        action = action_data.action_mode
        input_type = action_data.input_type


        axis_visible = False
        pulse_visible = False
        start_visible = False
        grid_visible = False
        range_visible = False
        target_value_visible = False
        exec_on_release_visible = False
        paired_visible = False
        hardware_widget_visible = False

        if input_type == InputType.JoystickAxis:
            
            grid_visible = action == VjoyAction.VJoyAxisToButton
            range_visible = action in (VjoyAction.VJoyRangeAxis, VjoyAction.VJoyAxisToButton)
            # hardware_widget_visible = action == VjoyAction.VjoyMergeAxis
            axis_visible = not (grid_visible or range_visible or hardware_widget_visible)

        elif input_type == InputType.JoystickButton:
            pulse_visible = action == VjoyAction.VJoyPulse
            start_visible = action == VjoyAction.VJoyButton
            grid_visible = action in (VjoyAction.VJoyPulse, VjoyAction.VJoyButton, VjoyAction.VJoyToggle)
            paired_visible = action == VjoyAction.VJoyButton
            target_value_visible = action == VjoyAction.VJoyButton
            exec_on_release_visible =  action_data.input_type == InputType.JoystickButton # or is_command
        elif input_type == InputType.JoystickHat:
            pass

        is_command = VjoyAction.is_command(action)
        selector_visible = not is_command

        
        button_to_axis_visible = action == VjoyAction.VJoySetAxis

        self.pulse_widget.setVisible(pulse_visible)
        self.start_widget.setVisible(start_visible)
        self.button_grid_widget.setVisible(grid_visible)
        self.axis_widget.setVisible(axis_visible)


        self.lbl_input_device_a.setVisible(hardware_widget_visible)
        self.lbl_input_axis_a.setAcceptDrops(hardware_widget_visible)
        self.lbl_input_device_name_a.setVisible(hardware_widget_visible)
        self.lbl_input_axis_name_a.setAcceptDrops(hardware_widget_visible)

        self.lbl_input_device_b.setVisible(hardware_widget_visible)
        self.lbl_input_axis_b.setAcceptDrops(hardware_widget_visible)
        self.hardware_device.setVisible(hardware_widget_visible)
        self.hardware_axis.setVisible(hardware_widget_visible)


        self.axis_range_value_widget.setVisible(range_visible)
        self.chkb_exec_on_release.setVisible(exec_on_release_visible)
        self.chkb_paired.setVisible(paired_visible)
        self.target_value_widget.setVisible(target_value_visible)
        self.button_to_axis_widget.setVisible(button_to_axis_visible)

        self.lbl_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_input_selector.setVisible(selector_visible)
        self.lbl_vjoy_input_selector.setVisible(selector_visible)

        self.action_label.setText(VjoyAction.to_description(action))
        

    def _action_mode_changed(self, index):
        ''' called when the drop down value changes '''
        with QtCore.QSignalBlocker(self.cb_action_list):
            action = self.cb_action_list.itemData(index)
            self.action_data.action_mode = action
            self.action_data.input_id = self.action_data.get_input_id()
            self._update_ui_action_mode(self.action_data)
            self._update_vjoy_device_input_list()
            self.notify_device_changed()

    def _get_action_mode(self):
        ''' returns the action mode '''
        index = self.cb_action_list.currentIndex()
        action = self.cb_action_list.itemData(index)
        return action


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
        

        self.button_grid_widget = QtWidgets.QWidget()

        # link all radio buttons         
        self.button_group = QtWidgets.QButtonGroup()
        self.button_group.buttonClicked.connect(self._select_changed)
        self.icon_map = {}

        self.active_id = -1

        
        vjoy_device_id = self.action_data.vjoy_device_id
        input_type = self._get_selector_input_type()

        dev = self.vjoy_map[vjoy_device_id]
        count = dev.button_count
        grid = QtWidgets.QGridLayout(self.button_grid_widget)
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

            # wire the radio check
            #cb.clicked.connect(self._select_changed)

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

        self.main_layout.addWidget(self.button_grid_widget)
   
    
            
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
        self.action_data.set_input_id(id)

        # update the selector
        with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):
            self.cb_vjoy_input_selector.setCurrentIndex(id-1)

        # update the grid icons
        self._populate_grid(self.action_data.vjoy_device_id,id)
        
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

        # if self.action_data.action_id == "0cf2394a99bd4383a6d17129a57e35d4":
        #     pass

        #syslog.debug(f"populate vjoy data for action id: {self.action_data.action_id}  action mode: {self.action_data.action_mode}  vjoy: {self.action_data.vjoy_device_id}")
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

        is_button_mode = False

        try:
            with QtCore.QSignalBlocker(self.cb_vjoy_device_selector):
                index = self.cb_vjoy_device_selector.findData(vjoy_dev_id)
                if index != -1:
                    self.cb_vjoy_device_selector.setCurrentIndex(index)
            with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):
                index = self.cb_vjoy_input_selector.findData(vjoy_input_id)
                if index != -1:
                    self.cb_vjoy_input_selector.setCurrentIndex(index)

            # set the action type from the input type
            self.load_actions_from_input_type()

            index = self.cb_action_list.findData(self.action_data.action_mode)
            if index == -1:
                syslog.warning(f"Mode not found in drop down: {self.action_data.action_mode.name} - resetting to default mode")
                self.action_data.action_mode = self.cb_action_list.itemData(0)
                index = 0
            else:
                self.cb_action_list.setCurrentIndex(index)
            #     # use a suitable default
            #     action_mode = self.cb_action_list.itemData(0)
            #     self.action_data.action_mode = data.action_mode
            #     self.cb_action_list.setCurrentIndex(0)
                

            if self.action_data.input_type == InputType.JoystickAxis:
                with QtCore.QSignalBlocker(self.reverse_checkbox):
                    self.reverse_checkbox.setChecked(self.action_data.reverse)
                
                with QtCore.QSignalBlocker(self.absolute_checkbox):
                    with QtCore.QSignalBlocker(self.relative_checkbox):
                        if self.action_data.axis_mode == "absolute":    
                            self.absolute_checkbox.setChecked(True)
                        else:
                            self.relative_checkbox.setChecked(True)

                with QtCore.QSignalBlocker(self.sb_start_value):
                    self.sb_start_value.setValue(self.action_data.axis_start_value)

                with QtCore.QSignalBlocker(self.relative_scaling):
                    self.relative_scaling.setValue(self.action_data.axis_scaling)

                with QtCore.QSignalBlocker(self.sb_axis_range_low):
                    self.sb_axis_range_low.setValue(self.action_data.range_low)                    

                with QtCore.QSignalBlocker(self.sb_axis_range_high):
                    self.sb_axis_range_high.setValue(self.action_data.range_high)


            elif self.action_data.input_type == InputType.JoystickButton:
                is_button_mode = True

            if self.action_data.action_mode == VjoyAction.VJoyAxisToButton:
                is_button_mode = True
            
            

            if is_button_mode:
                self.pulse_spin_widget.setValue(self.action_data.pulse_delay)
                if self.action_data.start_pressed:
                    self.rb_start_pressed.setChecked(True)
                else:
                    self.rb_start_released.setChecked(True)


                with QtCore.QSignalBlocker(self.sb_button_range_low):
                    self.sb_button_range_low.setValue(self.action_data.range_low)                    

                with QtCore.QSignalBlocker(self.sb_button_range_high):
                    self.sb_button_range_high.setValue(self.action_data.range_high)    

                with QtCore.QSignalBlocker(self.chkb_exec_on_release):
                    self.chkb_exec_on_release.setChecked(self.action_data.exec_on_release)

                with QtCore.QSignalBlocker(self.chkb_paired):
                    self.chkb_paired.setChecked(self.action_data.paired)

            # populate hardware devices if in merge mode
            self._populate_hardware()
            self._populate_hardware_axis()

            # update based on current mode

            self._populate_grid(vjoy_dev_id, input_type)
            self._update_vjoy_device_input_list()
            self._update_ui_action_mode(self.action_data)

        except gremlin.error.GremlinError as e:
            util.display_error(
                "A needed vJoy device is not accessible: {}\n\n".format(e) +
                "Default values have been set for the input, but they are "
                "not what has been specified."
            )
            logging.getLogger("system").error(str(e))


    def _axis_reverse_changed(self):
        self.action_data.reverse = self.reverse_checkbox.isChecked()

    def _axis_mode_changed(self):
        self.action_data.axis_mode = 'absolute' if self.absolute_checkbox.isChecked() else "relative"
    
    def _axis_scaling_changed(self):
        self.action_data.axis_scaling = self.relative_scaling.value()

    def _axis_range_low_changed(self):
        self.action_data.range_low = self.sb_axis_range_low.value()

    def _axis_range_high_changed(self):
        self.action_data.range_high = self.sb_axis_range_high.value()    

    def _axis_start_value_changed(self):
        self.action_data.axis_start_value = self.sb_start_value.value()

    def _button_range_low_changed(self):
        self.action_data.range_low = self.sb_button_range_low.value()

    def _button_range_high_changed(self):
        self.action_data.range_high = self.sb_button_range_high.value()
    
    def _button_to_axis_value_changed(self):
        self.action_data.target_value = self.sb_button_to_axis_value.value()
    
    def _b_range_reset_clicked(self, value):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(1.0)
        
    def _b_range_half_clicked(self, value):
        self.sb_button_range_low.setValue(-0.5)
        self.sb_button_range_high.setValue(0.5)

    def _b_range_lhalf_clicked(self, value):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(0.0)

    def _b_range_hhalf_clicked(self, value):
        self.sb_button_range_low.setValue(0.0)
        self.sb_button_range_high.setValue(1.0)

    def _b_range_bot_clicked(self, value):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(-0.75)

    def _b_range_top_clicked(self, value):
        self.sb_button_range_low.setValue(0.75)
        self.sb_button_range_high.setValue(1.0)


    def _b_min_start_value_clicked(self, value):
        self.sb_start_value.setValue(-1.0)

    def _b_center_start_value_clicked(self, value):
        self.sb_start_value.setValue(0.0)        

    def _b_max_start_value_clicked(self, value):
        self.sb_start_value.setValue(1.0)

    def _exec_on_release_changed(self, value):
        self.action_data.exec_on_release = self.chkb_exec_on_release.isChecked()

    def _paired_changed(self, value):
        self.action_data.paired = self.chkb_paired.isChecked()
    
    def _populate_grid(self, device_id, input_id):
        ''' updates the usage grid based on current VJOY mappings '''
        icon_path = os.path.join("action_plugins","map_to_vjoy")
        unused_path = os.path.join(icon_path, "unused.png")
        used_path = os.path.join(icon_path, "used.png")
        used_icon = QtGui.QIcon(used_path)
        unused_icon = QtGui.QIcon(unused_path)
        used_pixmap = QtGui.QPixmap(used_path)
        unused_pixmap = QtGui.QPixmap(unused_path)

        # self.usage_state.free_inputs

        for cb in self.button_group.buttons():
            id = self.button_group.id(cb)
            
            # ctrl = self.icon_map[id]
            # ctrl.setPixmap(unused_pixmap if id in free_buttons else used_pixmap)
            if id == input_id:
                with QtCore.QSignalBlocker(cb):
                    cb.setChecked(True)
                self.usage_state.set_state(device_id,'button',id,True)
            
            used = self.usage_state.get_state(device_id,'button',id)

            lbl = self.icon_map[id]
            lbl.setPixmap(used_pixmap if used else unused_pixmap)

    def _populate_hardware(self):
        ''' populates hardware inputs UI 
        
            this will show all possible hardware inputs if they have an axis
            and defaults to the one mapped to this action
        
        '''
        import gremlin.joystick_handling
        phys_devices = gremlin.joystick_handling.physical_devices()
        # filter out devices with axis input only
        axis_devices = [d for d in phys_devices if d.axis_count > 0]
        self.hardware_device.clear()
        current_guid = self.action_data.hardware_device_guid
        current_device = next((d for d in axis_devices if d.device_guid == current_guid), None)
        if axis_devices:
            with QtCore.QSignalBlocker(self.hardware_device):
                for device in axis_devices:
                    self.hardware_device.addItem(device.name, device)

        if current_device:
            index = self.hardware_device.findData(current_device)
            self.hardware_device.setCurrentIndex(index)

                    


    def _populate_hardware_axis(self):
        ''' fills the axis drop down based on the current hardware device selected '''
        index = self.hardware_device.currentIndex()
        if index != -1:
            device = self.hardware_device.itemData(index)
            self.hardware_axis.clear()
            
            current_guid = self.action_data.hardware_device_guid
            current_axis = -1
            if current_guid == device.device_guid:
                # current selected input device is the same as the device mapped to this action
                current_axis = self.action_data.hardware_input_id
            with QtCore.QSignalBlocker(self.hardware_axis):
                for axis in range(1,device.axis_count+1):
                    if axis != current_axis:
                        # add axis only if it's not already the one mapped to this action
                        self.hardware_axis.addItem(f"Axis {self.get_axis_name(axis)} ({axis})", axis)





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
        self.target_value = action.target_value
        self.target_value_valid = action.target_value_valid
        self.range_low = action.range_low
        self.range_high = action.range_high

        self.exec_on_release = action.exec_on_release
        self.paired = action.paired

        self.needs_auto_release = self._check_for_auto_release(action)
        self.thread_running = False
        self.should_stop_thread = False
        self.thread_last_update = time.time()
        self.thread = None
        self.axis_delta_value = 0.0
        self.axis_value = 0.0
        self.axis_start_value = action.axis_start_value

        self.remote_client = input_devices.remote_client
        self.merge_guid = action.merge_device_b_guid
        self.merge_axis = action.merge_device_b_axis
        if self.merge_guid:
            pass

        self.lock = threading.Lock()

          
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)

    @property
    def reverse(self):
        # axis reversed state
        return usage_data.is_inverted(self.vjoy_device_id, self.vjoy_input_id)
        
    def toggle_reverse(self):
        # toggles reverse mode for the axis
        value = usage_data.is_inverted(self.vjoy_device_id, self.vjoy_input_id)
        usage_data.set_inverted(self.vjoy_device_id, self.vjoy_input_id, not value)
        syslog.debug(f"toggle reverse: {self.vjoy_device_id} {self.vjoy_input_id} new state: {self.reverse}")


    def _profile_start(self):
        # setup initial state
        if self.input_type == InputType.JoystickButton:
            # set start button state
            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = self.start_pressed
        if self.input_type == InputType.JoystickAxis:
            # set start axis range
            usage_data.set_range(self.vjoy_device_id, self.vjoy_input_id, self.range_low, self.range_high)
            # print(f"Axis start value: vjoy: {self.vjoy_device_id} axis: {self.vjoy_input_id}  value: {self.axis_start_value}")
            joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = self.axis_start_value
            self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, self.axis_start_value)

	
    # async routine to pulse a button
    def _fire_pulse(self, *args):

        self.lock.acquire()
        vjoy_device_id, vjoy_input_id, duration = args
        # vjoy_device_id = args]
        # vjoy_input_id = args[2]
        # duration = args[3]

        button = joystick_handling.VJoyProxy()[vjoy_device_id].button(vjoy_input_id)
        button.is_pressed = True
        self.remote_client.send_button(vjoy_device_id, vjoy_input_id, True)
        time.sleep(duration)
        button.is_pressed = False
        self.remote_client.send_button(vjoy_device_id, vjoy_input_id, False)
        self.lock.release()

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
    
    def process_event(self, event, value):
        ''' runs when a joystick even occurs like a button press or axis movement when a profile is running '''
        (is_local, is_remote) = input_devices.remote_state.state
        if event.force_remote:
            # force remote mode on if specified in the event
            is_remote = True
            is_local = False
        
        if self.input_type == InputType.JoystickAxis:
            target = value.current

            # axis mode
            if self.action_mode == VjoyAction.VJoyAxisToButton:
                r_min = self.range_low
                r_max = self.range_high
                #r_min, r_max = usage_data.get_range(self.vjoy_device_id, self.vjoy_input_id)
                if value.current >= r_min and value.current <= r_max:
                    # axis in range
                    print (f"In range {value.current}")
                    if not event.is_pressed:
                        if is_local:
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = True
                        if is_remote:
                            self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, True)
                else:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = False 
                    if is_remote:
                        self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, False)
  
                    

            elif self.axis_mode == "absolute":
                # apply any range function to the raw position
                #input_min = -1.0 
                #input_max = +1.0
                # sub-range is r_min, r_max 
                # y = r_min + (x - input_min)*(r_max - r_min)/(input_max - input_min)
                r_min, r_max = usage_data.get_range(self.vjoy_device_id, self.vjoy_input_id)
                if self.reverse:
                    target = -target
                    syslog.debug(f"reversed: {target}")
                    

                value = r_min + (target + 1.0)*((r_max - r_min)/2.0)
                
                if is_local:
                    joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = value
                if is_remote:
                    self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, value)
            else:
                value = -target if self.reverse else target
                self.should_stop_thread = abs(event.value) < 0.05
                self.axis_delta_value = \
                    value * (self.axis_scaling / 1000.0)
                self.thread_last_update = time.time()
                if self.thread_running is False:
                    if isinstance(self.thread, threading.Thread):
                        self.thread.join()
                    self.thread = threading.Thread(target=self.relative_axis_thread)
                    self.thread.start()

        elif self.input_type == InputType.JoystickButton:

            target_press = not self.exec_on_release
            is_paired = remote_state.paired
            force_remote = event.force_remote or is_paired
            
            # determine if event should be fired based on release mode
            fire_event =  (self.exec_on_release and not event.is_pressed) or (not self.exec_on_release and event.is_pressed)

            if self.action_mode == VjoyAction.VJoyButton:
                # normal default behavior
                if self.exec_on_release:
                    if not event.is_pressed:
                        if is_local:
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = True
                        if is_remote or is_paired:
                            self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, True, force_remote = force_remote )
                else:

                    if event.event_type in [InputType.JoystickButton, InputType.Keyboard] and event.is_pressed and self.needs_auto_release:
                        input_devices.ButtonReleaseActions().register_button_release(
                            (self.vjoy_device_id, self.vjoy_input_id),
                            event,
                            is_local = is_local,
                            is_remote = is_remote,
                            force_remote = force_remote
                        )

                    if event.is_pressed:
                        if is_local:    
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = value.current                        
                        if is_remote or is_paired:
                            self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, value.current, force_remote = is_paired )
                    
            
            elif self.action_mode == VjoyAction.VJoyToggle:
                # toggle action
                if fire_event:
                    if event.event_type in [InputType.JoystickButton, InputType.Keyboard] \
                            and event.is_pressed:
                        if is_local:
                            button = joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id)
                            button.is_pressed = not button.is_pressed
                        if is_remote:
                            self.remote_client.toggle_button(self.vjoy_device_id, self.vjoy_input_id)
                    

            elif self.action_mode == VjoyAction.VJoyPulse:
                
                # pulse action
                if fire_event:
                    if not self.lock.locked():
                        threading.Timer(0.01, self._fire_pulse, [self.vjoy_device_id, self.vjoy_input_id, self.pulse_delay/1000]).start()
            elif self.action_mode == VjoyAction.VJoyInvertAxis:
                # invert the specified axis
                if fire_event:
                    self.toggle_reverse()
                
            elif self.action_mode == VjoyAction.VJoySetAxis:
                # set the value on the specified axis
                if self.target_value_valid and fire_event:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = self.target_value
                    if is_remote:
                        self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, self.target_value)

            elif self.action_mode == VjoyAction.VJoyRangeAxis:
                # changes the output range on the target device / axis
                if fire_event:
                    usage_data.set_range(self.vjoy_device_id, self.vjoy_input_id, self.range_low, self.range_high)

            elif VjoyAction.is_command(self.action_mode):
                # update remote control mode
                if fire_event:
                    remote_state.mode = self.action_mode


            else:
                # basic handling of the button
                if fire_event:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = value.current
                    if is_remote:
                        self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, value.current)


        elif self.input_type == InputType.JoystickHat:
            if is_local:
                joystick_handling.VJoyProxy()[self.vjoy_device_id].hat(self.vjoy_input_id).direction = value.current
            if is_remote:
                self.remote_client.send_hat(self.vjoy_device_id, self.vjoy_input_id, value.current)

        

        return True

    def relative_axis_thread(self):
        self.thread_running = True
        vjoy_dev = joystick_handling.VJoyProxy()[self.vjoy_device_id]
        self.axis_value = vjoy_dev.axis(self.vjoy_input_id).value
        (is_local, is_remote) = input_devices.remote_state.state
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
                
                if is_local:
                    vjoy_dev.axis(self.vjoy_input_id).value = self.axis_value
                if is_remote:
                    self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, self.axis_value)

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
        """ vjoyremap action block """
        super().__init__(parent)

        # Set vjoy ids to None so we know to pick the next best one
        # automatically
        self._vjoy_device_id = 1
        self.vjoy_input_id = 1
        self.input_type = self.hardware_input_type

        self.vjoy_axis_id = 1
        self.vjoy_button_id = 1
        self.vjoy_hat_id = 1
     
        self._reverse = False
        self.axis_mode = "absolute"
        self.axis_scaling = 1.0
        self.axis_start_value = 0.0
        self._exec_on_release = False
        self._paired = False
        self.merge_device_a_guid = self.hardware_device_guid
        self.merge_device_a_axis = self.hardware_input_id
        self._merge_device_b_guid = None
        self._merge_device_b_axis = 1


        self._action_mode = VjoyAction.VJoyButton

        self.range_low = -1.0 # axis range min
        self.range_high = 1.0 # axis range max
        

        # pick an appropriate default action set for the type of input this is
        if self.input_type == InputType.JoystickAxis:
            self.action_mode = VjoyAction.VJoyAxis
        elif self.input_type == InputType.JoystickButton:
            self.action_mode = VjoyAction.VJoyButton
        elif self.input_type == InputType.JoystickHat:
            self.action_mode = VjoyAction.VJoyHat

        self.current_state = 0 # toggle value for the input 1 means set, any other value means not set for buttons
        self.pulse_delay = 250 # pulse delay
        self.start_pressed = False # true if a button starts as pressed when the profile is loaded
        self.target_value = 0.0
        self.target_value_valid = True
        


    @property
    def merge_device_b_guid(self):
        return self._merge_device_b_guid
    @merge_device_b_guid.setter
    def merge_device_b_guid(self, value):
        if value:
            pass
        self._merge_device_b_guid = value        

    @property
    def merge_device_b_axis(self):
        return self._merge_device_b_axis 
    @merge_device_b_axis.setter
    def merge_device_b_axis(self, value):
        self._merge_device_b_axis = value

    @property
    def exec_on_release(self):
        return self._exec_on_release
    
    @exec_on_release.setter
    def exec_on_release(self, value):
        self._exec_on_release = value

    @property
    def paired(self):
        return self._paired
    
    @paired.setter
    def paired(self, value):
        self._paired = value
        

    @property
    def vjoy_device_id(self):
        return self._vjoy_device_id
    
    @vjoy_device_id.setter
    def vjoy_device_id(self, value):
        self._vjoy_device_id = value
    
    @property
    def action_mode(self):
        return self._action_mode
    @action_mode.setter
    def action_mode(self, value):
        self._action_mode = value

    @property
    def reverse(self):
        # axis reversed state
        return usage_data.is_inverted(self.vjoy_device_id, self.vjoy_axis_id) or self._reverse
        
    @reverse.setter
    def reverse(self,value):
        # input_id: 5 device id: 1 axis id: 5
        # if self.vjoy_input_id == 5 and self.vjoy_device_id == 1 and self.vjoy_axis_id == 5:
        #     pass
        usage_data.set_inverted(self.vjoy_device_id, self.vjoy_axis_id, value)
        self._reverse = value

    def toggle_reverse(self):
        # toggles reverse mode for the axis
        self.reverse = not self.reverse


    @property
    def reverse_configured(self):
        ''' returns the configured reverse value rather than the live mode '''
        return  self._reverse

    def icon(self):
        """Returns the icon corresponding to the remapped input.

        :return icon representing the remap action
        """
        # Do not return a valid icon if the input id itself is invalid
        if self.vjoy_input_id is None:
            return None

        if self.input_type == InputType.JoystickAxis:
            input_string = "axis"
        elif self.action_mode in (VjoyAction.VJoySetAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoyAxis):
            input_string = "axis"
        elif self.action_mode == VjoyAction.VJoyHat:
            input_string = "hat"
        else:
            input_string = "button"
        
        return f"action_plugins/map_to_vjoy/gfx/icon_{input_string}_{self.vjoy_input_id:03d}.png"
            
    


    def requires_virtual_button(self):
        """Returns whether or not the action requires an activation condition.

        :return True if an activation condition is required, False otherwise
        """
        input_type = self.input_type

        if input_type in [InputType.JoystickButton, InputType.Keyboard]:
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
        if self.action_mode in (VjoyAction.VJoyAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoySetAxis):
                self.vjoy_axis_id = index
        elif self.action_mode == VjoyAction.VJoyHat:
            self.vjoy_hat_id = index
        else:
            self.vjoy_button_id = index
        self.vjoy_input_id = index      

    def get_input_id(self):
        ''' returns input id based on the action mode '''
        if self.action_mode in (VjoyAction.VJoyAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoySetAxis):
            return self.vjoy_axis_id
        elif self.action_mode == VjoyAction.VJoyHat:
            return self.vjoy_hat_id
        else:
            return self.vjoy_button_id


    def _parse_xml(self, node):
        """Populates the data storage with data from the XML node.

        :param node XML node with which to populate the storage
        """

        # if self.action_id == "0cf2394a99bd4383a6d17129a57e35d4":
        #     pass

        try:
            
            if "axis" in node.attrib:
                self.input_type = InputType.JoystickAxis
                self.vjoy_input_id = safe_read(node, "axis", int)
                self.vjoy_axis_id = self.vjoy_input_id
            elif "button" in node.attrib:
                self.input_type = InputType.JoystickButton
                self.vjoy_input_id = safe_read(node, "button", int)
                self.vjoy_button_id = self.vjoy_input_id
            elif "hat" in node.attrib:
                self.input_type = InputType.JoystickHat
                self.vjoy_input_id = safe_read(node, "hat", int)
                self.vjoy_hat_id = self.vjoy_input_id
            elif "keyboard" in node.attrib:
                self.input_type = InputType.Keyboard
                self.vjoy_input_id = safe_read(node, "button", int)
            else:
                raise gremlin.error.GremlinError(
                    "Invalid remap type provided: {}".format(node.attrib)
                )

            self.vjoy_device_id = safe_read(node, "vjoy", int)

            if "input" in node.attrib:
                index = safe_read(node,"input", int, 1)
                self.set_input_id(index)


            # hack to sync all loaded profile setups with the status grid
            usage_data = VJoyUsageState()
            usage_data.push_load_list(self.vjoy_device_id,self.input_type,self.vjoy_input_id)
            
            
            self.pulse_delay = 250

            if "mode" in node.attrib:
                value = node.attrib['mode']
                self.action_mode = VjoyAction.from_string(value)
            else:
                if self.input_type == InputType.JoystickButton:
                    default_action_mode = VjoyAction.VJoyButton
                elif self.input_type == InputType.JoystickHat:
                    default_action_mode = VjoyAction.VJoyHat
                elif self.input_type == InputType.JoystickAxis:
                    default_action_mode = VjoyAction.VJoyAxis                
                self.action_mode = default_action_mode

            if "reverse" in node.attrib:
                self.reverse = safe_read(node,"reverse",bool,False)
                
            
            if "axis-type" in node.attrib:
                self.axis_mode = safe_read(node, "axis-type", str, "absolute")
            if "axis-scaline" in node.attrib:
                self.axis_scaling = safe_read(node, "axis-scaling", float, 1.0)

            if "pulse_delay" in node.attrib:
                self.pulse_delay = safe_read(node,"pulse_delay", int, 250)
            if "start_pressed" in node.attrib:
                self.start_pressed = safe_read(node,"start_pressed", bool, False)
                
            if "target_value" in node.attrib:
                self.target_value  = safe_read(node,"target_value", float, 0.0)                                        
                self.target_value_valid = True

            if "range_low" in node.attrib:
                self.range_low = safe_read(node,"range_low", float, -1.0)
        
            if "range_high" in node.attrib:
                self.range_high = safe_read(node,"range_high", float, 1.0)

            if "axis_start_value" in node.attrib:
                self.axis_start_value = safe_read(node,"axis_start_value", float, -1.0)

            if "exec_on_release" in node.attrib:
                self.exec_on_release = safe_read(node,"exec_on_release",bool, False)
   

            if "paired" in node.attrib:
                self.paired = safe_read(node,"paired", bool, False)

            # if "merge_device_guid" in node.attrib:
            #     self.merge_device_b_guid = parse_guid(safe_read(node,"merge_device_guid", str, None))

            # if "merge_device_axis" in node.attrib:
            #     self.merge_device_b_axis = safe_read(node,"merge_device_axis",int)

            # if self.reverse:
            #     syslog.debug(f"reverse TRUE for: input_id: {self.vjoy_input_id} device id: {self.vjoy_device_id} axis id: {self.vjoy_axis_id}")

        except ProfileError:
            self.vjoy_input_id = None
            self.vjoy_device_id = None

    def _generate_xml(self):
        """Returns an XML node encoding this action's data.

        :return XML node containing the action's data
        """
        node = ElementTree.Element(VjoyRemap.tag)
        node.set("vjoy", str(self.vjoy_device_id))

        save_exec_on_release = VjoyAction.is_command(self.action_mode) or \
                               self.action_mode in (VjoyAction.VJoyButton,
                                                    VjoyAction.VJoyInvertAxis,
                                                    VjoyAction.VJoySetAxis,
                                                    VjoyAction.VJoyPulse)
        
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

        node.set("mode", safe_format(VjoyAction.to_string(self.action_mode), str))
        
        node.set("input", safe_format(self.vjoy_input_id, int))
        
        if self.action_mode == VjoyAction.VJoyAxis:
            node.set("axis-type", safe_format(self.axis_mode, str))
            node.set("axis-scaling", safe_format(self.axis_scaling, float))
            node.set("axis_start_value", safe_format(self.axis_start_value, float))
            node.set("range_low", safe_format(self.range_low, float))
            node.set("range_high", safe_format(self.range_high, float))
            reverse = safe_format(self.reverse_configured, bool)
            node.set("reverse", reverse)

        elif self.action_mode == VjoyAction.VJoyButton \
            or VjoyAction.is_command(self.action_mode) \
            or self.action_mode :
            # button, command or 
            node.set("start_pressed", safe_format(self.start_pressed, bool))
            
            node.set("paired", safe_format(self.paired, bool))
            
        elif self.action_mode == VjoyAction.VJoySetAxis:
            node.set("target_value", safe_format(self.target_value, float))
        # elif self.action_mode == VjoyAction.VjoyMergeAxis:
        #     node.set("merge_device_guid", write_guid(self.merge_device_b_guid))

            # value = str(self.merge_device_b_axis)
            # node.set("merge_device_axis", value )

        if self.action_mode == VjoyAction.VJoyPulse:
            node.set("pulse_delay", safe_format(self.pulse_delay, int))            

        if save_exec_on_release:
            node.set("exec_on_release", safe_format(self.exec_on_release, bool))

        return node

    def _is_valid(self):
        """Returns whether or not the action is configured properly.

        :return True if the action is configured correctly, False otherwise
        """
        return not(self.vjoy_device_id is None or self.vjoy_input_id is None)


version = 1
name = "VjoyRemap"
create = VjoyRemap


