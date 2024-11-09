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

from __future__ import annotations
import logging
import threading
import time
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.actions
import gremlin.config
import gremlin.event_handler
import gremlin.input_types
import gremlin.joystick_handling
from gremlin.util import load_icon

from gremlin.base_conditions import InputActionCondition
from gremlin.input_types import InputType
from gremlin import input_devices, joystick_handling, util
from gremlin.error import ProfileError
from gremlin.util import safe_format, safe_read
import gremlin.ui.ui_common
import gremlin.ui.input_item
import os
import action_plugins
import enum
from gremlin.input_devices import VjoyAction, remote_state
from gremlin.util import *


IdMapToButton = -2 # map to button special ID
import gremlin.ui.input_item
import gremlin.base_profile
import gremlin.shared_state
import gremlin.curve_handler



class MergeOperationType (enum.IntEnum):
    ''' merge operation method'''
    NotSet = 0
    Add = 1 # the two inputs are added
    Average = 2 # the two inputs are averaged
    Center = 3 # centered (left - right)/2
    Min = 4 # min of two axes
    Max = 5 # max of two axes

    @staticmethod
    def to_display_name(value : MergeOperationType):
        return _merge_operation_display_lookup[value]
    
    @staticmethod
    def to_enum(value : str):
        return _merge_operation_to_enum_lookup[value]
    
    @staticmethod
    def to_string(value : MergeOperationType):
        return _merge_operation_to_string_lookup[value]
    
    @staticmethod
    def to_description(value : MergeOperationType):
        return _merge_operation_to_description_lookup[value]
    

_merge_operation_to_enum_lookup = {
    "none" : MergeOperationType.NotSet,
    "add" : MergeOperationType.Add,
    "average" : MergeOperationType.Average,
    "center" : MergeOperationType.Center,
    "min" : MergeOperationType.Min,
    "max" : MergeOperationType.Max,

}        

_merge_operation_to_string_lookup = {
    MergeOperationType.NotSet : "none",
    MergeOperationType.Add : "add",
    MergeOperationType.Average : "average",
    MergeOperationType.Center : "center",
    MergeOperationType.Min : "min",
    MergeOperationType.Max : "max",
}        


_merge_operation_display_lookup = {
    MergeOperationType.NotSet : "N/A",
    MergeOperationType.Add : "Add",
    MergeOperationType.Average : "Average",
    MergeOperationType.Center : "Center",
    MergeOperationType.Min : "Minimum",
    MergeOperationType.Max : "Maximum",
}

_merge_operation_to_description_lookup = {
    MergeOperationType.NotSet : "Not set",
    MergeOperationType.Add : "A + B",
    MergeOperationType.Average : "Average (A+B)/2",
    MergeOperationType.Center : "Centered (A-B)/2",
    MergeOperationType.Min : "Min(A, B)",
    MergeOperationType.Max : "Max(A, B)",

}


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
            elif action.device_input_type in VJoyWidget.input_type_buttons:
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
        if device_id in VJoyUsageState._axis_invert_map:
            vjoy = VJoyUsageState._axis_invert_map[device_id]
            if input_id in vjoy:
                vjoy[input_id] = inverted
        
    def is_inverted(self, device_id, input_id):
        ''' returns true if the specified device/axis is inverted '''
        return VJoyUsageState._axis_invert_map[device_id][input_id]
    
    def toggle_inverted(self, device_id, input_id):
        ''' toggles inversion state of specified device/axis is inverted '''
        if input_id in VJoyUsageState._axis_invert_map[device_id]:
            VJoyUsageState._axis_invert_map[device_id][input_id] = not VJoyUsageState._axis_invert_map[device_id][input_id]
            log_sys(f"Vjoy Axis {device_id} {input_id} inverted state: {VJoyUsageState._axis_invert_map[device_id][input_id]}")
        else:
            logging.getLogger("system").error(f"Vjoy Axis invert: {device_id} - axis {input_id} is not a valid output axis.")

    def set_range(self, device_id, input_id, min_range = -1.0, max_range = 1.0):
        ''' sets the axis min/max range for the active range computation '''
        if min_range > max_range:
            r = min_range
            min_range = max_range
            max_range = r
        if input_id in VJoyUsageState._axis_invert_map[device_id]:
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
            if input_type in VJoyWidget.input_type_buttons:
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

        :input_type: InputType enum
            
        
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

        # List all input types
        all_input_types = InputType.to_list()

        # Create list of all inputs provided by the vjoy devices
        vjoy = {}
        for entry in vjoy_devices:
            vjoy[entry.vjoy_id] = {}
            for input_type in all_input_types:
                vjoy[entry.vjoy_id][InputType.to_string(input_type)] = []
            for i in range(entry.axis_count):
                vjoy[entry.vjoy_id]["axis"].append(
                    entry.axis_map[i].axis_index
                )
            for i in range(entry.button_count):
                vjoy[entry.vjoy_id]["button"].append(i+1)
            for i in range(entry.hat_count):
                vjoy[entry.vjoy_id]["hat"].append(i+1)



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
    locked = False

 

    # all button type inputs (hat is handled separately as is axis)
    input_type_buttons = [InputType.JoystickButton,
                          InputType.Keyboard,
                          InputType.KeyboardLatched,
                          InputType.OpenSoundControl,
                          InputType.Midi,
                          ]

    def __init__(self, action_data, parent=None):
        """Creates a new VjoyRemapWidget.

        :param action_data profile data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, VjoyRemap))

    def _create_ui(self):
        """Creates the UI components."""

        if VJoyWidget.locked:
            return
        
        try:
            VJoyWidget.locked = True

            self.valid_types = [
                    InputType.JoystickAxis,
                    InputType.JoystickButton,
                    InputType.JoystickHat,
                    InputType.Midi,
                    InputType.OpenSoundControl,
                ]

            self.grid_visible_widget = None

            self.usage_state = VJoyUsageState()

            self.main_layout.setSpacing(0)

            self._merge_enabled = False # disable merging by default


            # Create UI widgets for absolute / relative axis modes if the remap
            # action is being added to an axis input type
            self.input_type = self.action_data.hardware_input_type #._get_input_type() # self.action_data.input_type
        
            #self.main_layout.addWidget(self.vjoy_selector)

            # init default widget tracking
            self.button_grid_widget  = None
            self.container_axis_widget = None

            # handler to update curve widget if displayed
            self.curve_update_handler = None

            # if self.action_data.input_type in (InputType.Midi, InputType.OpenSoundControl):
            #     pass

            self._is_axis = self.action_data.input_is_axis()

            # if the input is chained 
            self.chained_input = self.action_data.input_item.is_action
            

            # type_label = QtWidgets.QLabel(f"Input type: {InputType.to_display_name(self.input_type)}")
            # self.main_layout.addWidget(type_label)

            # create UI components
            self._create_selector()
            self._create_input_axis()
            self._create_merge_ui()
            self._create_input_grid()
            self._create_info()

            # update UI visibility
            self._update_ui_action_mode(self.action_data)

            self.main_layout.setContentsMargins(0, 0, 0, 0)
        finally:
            VJoyWidget.locked = False

    def _get_selector_input_type(self):
        ''' gets a modified input type based on the current mode '''
        input_type = self.action_data.hardware_input_type

        if input_type in VJoyWidget.input_type_buttons and \
                        self.action_data.action_mode in (VjoyAction.VJoySetAxis,
                                                         VjoyAction.VJoyInvertAxis,
                                                         VjoyAction.VJoyRangeAxis):
            return InputType.JoystickAxis
        return input_type

    def _create_input_axis(self):
        ''' creates the axis input widget '''



        self.container_axis_widget = QtWidgets.QWidget()
        self.container_axis_widget.setContentsMargins(0,0,0,0)

        self.container_axis_layout = QtWidgets.QGridLayout(self.container_axis_widget)
        self.container_axis_layout.setColumnStretch(8,1)
        self.container_axis_layout.setContentsMargins(0,0,0,0)
        
        self.reverse_checkbox = QtWidgets.QCheckBox("Reverse")

        self.absolute_checkbox = QtWidgets.QRadioButton("Absolute")
        self.absolute_checkbox.setChecked(True)
        self.relative_checkbox = QtWidgets.QRadioButton("Relative")
        self.relative_scaling = gremlin.ui.ui_common.DynamicDoubleSpinBox()


        self.sb_start_value = gremlin.ui.ui_common.DynamicDoubleSpinBox()
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

        self.sb_axis_range_low = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_axis_range_low.setMinimum(-1.0)
        self.sb_axis_range_low.setMaximum(1.0)
        self.sb_axis_range_low.setDecimals(3)
        self.sb_axis_range_high = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_axis_range_high.setMinimum(-1.0)
        self.sb_axis_range_high.setMaximum(1.0)
        self.sb_axis_range_high.setDecimals(3)

        # output axis repeater
        self.container_repeater_widget = QtWidgets.QWidget()
        self.container_repeater_layout = QtWidgets.QHBoxLayout(self.container_repeater_widget)
        self._axis_repeater_widget = gremlin.ui.ui_common.AxisStateWidget(show_percentage=False,orientation=QtCore.Qt.Orientation.Horizontal)
        self.curve_button_widget = QtWidgets.QPushButton("Output Curve")
        
        
        self.curve_icon_inactive = util.load_icon("mdi.chart-bell-curve",qta_color="gray")
        self.curve_icon_active = util.load_icon("mdi.chart-bell-curve",qta_color="blue")
        self.curve_button_widget.setToolTip("Curve output")
        self.curve_button_widget.clicked.connect(self._curve_button_cb)

        self.curve_clear_widget = QtWidgets.QPushButton("Clear curve")
        delete_icon = load_icon("mdi.delete")
        self.curve_clear_widget.setIcon(delete_icon)
        self.curve_clear_widget.setToolTip("Removes the curve output")
        self.curve_clear_widget.clicked.connect(self._curve_delete_button_cb)


        self.container_repeater_layout.addWidget(self.curve_button_widget)
        self.container_repeater_layout.addWidget(self.curve_clear_widget)
        self.container_repeater_layout.addWidget(self._axis_repeater_widget)
        self.container_repeater_layout.addStretch()
        self._update_curve_icon()
        

        row = 0
        col = 0
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Reverse Axis:"),row,col)
        row+=1
        self.container_axis_layout.addWidget(self.reverse_checkbox,row,col)

        row = 0
        col+=1
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Output Mode:"),row,col)
        row+=1
        self.container_axis_layout.addWidget(self.absolute_checkbox,row,col)
        row+=1
        self.container_axis_layout.addWidget(self.relative_checkbox,row,col)


        row = 0
        col+=1
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Start Value:"),row,col,1,3)

        row+=1
        self.container_axis_layout.addWidget(self.sb_start_value,row,col,1,3)

        row+=1
        self.container_axis_layout.addWidget(self.b_min_value,row,col)
        col+=1
        self.container_axis_layout.addWidget(self.b_center_value,row,col)
        col+=1
        self.container_axis_layout.addWidget(self.b_max_value,row,col)

        row = 0
        col+=1
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Axis"),row,col)
        row+=1
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Scale:"),row,col)
        row+=1
        self.container_axis_layout.addWidget(self.relative_scaling,row,col)

        row = 0
        col+=1
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Axis Output Range:"),row,col,1,2)
        row+=1
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Min:"),row,col)
        row+=1
        self.container_axis_layout.addWidget(self.sb_axis_range_low,row,col)

        col+=1
        row=1
        self.container_axis_layout.addWidget(QtWidgets.QLabel("Max:"),row,col)
        row+=1
        self.container_axis_layout.addWidget(self.sb_axis_range_high,row,col)

        



        
        self.main_layout.addWidget(self.container_axis_widget)
        self.main_layout.addWidget(self.container_repeater_widget)
        

        

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


        # hook the inputs and profile
        el = gremlin.event_handler.EventListener()
        el.custom_joystick_event.connect(self._joystick_event_handler)
        if not self.chained_input:
            el.joystick_event.connect(self._joystick_event_handler)
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)

        self._update_axis_widget()

    def _create_merge_ui(self):
        ''' creates the axis merging UI components '''
        # merge operations
        self.container_merge_widget = QtWidgets.QWidget()
        self.container_merge_layout = QtWidgets.QVBoxLayout(self.container_merge_widget)

        self.merge_selector_device_widget = gremlin.ui.ui_common.NoWheelComboBox()
        self.merge_selector_input_widget = gremlin.ui.ui_common.NoWheelComboBox()

        device_layout = QtWidgets.QGridLayout()
        device_layout.addWidget(QtWidgets.QLabel("Merge Device:"),0,0)
        device_layout.addWidget(self.merge_selector_device_widget,0,1)
        device_layout.addWidget(QtWidgets.QLabel(" "),0,2)
        device_layout.addWidget(QtWidgets.QLabel("Merge Axis:"),1,0)
        device_layout.addWidget(self.merge_selector_input_widget,1,1)
        device_layout.setColumnStretch(2,2)
        self.container_merge_layout.addLayout(device_layout)

        self.merge_selector_device_widget.currentIndexChanged.connect(self._device_changed_cb)
        self.merge_selector_input_widget.currentIndexChanged.connect(self._input_changed_cb)

        # populate the selector with hardware inputs
        self.merge_device_map = {} # holds the device information keyed by device_id (str)
        self.merge_input_map = {} # holds the list of axes for the given device by device_id(str)
        devices = sorted(joystick_handling.axis_input_devices(),key=lambda x: x.name)

        self._merge_enabled = len(devices) > 0 # assume enabled
        
        # figure out the default device to use
        default_device = None
        selected_input_id = 1
        if self.action_data.merge_device_id:
            default_device = next((dev for dev in devices if dev.device_id == self.action_data.merge_device_id), None)
            if default_device:
                
                if default_device.device_guid == self.action_data.hardware_device_guid:
                    # the merge device to pick is the same as the current device
                    if default_device.axis_count == 1:
                        # there is only one input which is already used
                        self._merge_enabled = False

                if self.action_data.merge_input_id and self.action_data.merge_input_id <= default_device.axis_count :        
                    selected_input_id = self.action_data.merge_input_id

        if not default_device:
            default_device = next((dev for dev in devices if dev.device_guid == self.action_data.hardware_device_guid), None)
            if default_device:
                axis_count = default_device.axis_count
                if axis_count == 1:
                    # there is only one input which is already used
                    self._merge_enabled = False

                else:
                    # pick a suitable input
                    input_id = self.action_data.hardware_input_id
                    if input_id < axis_count:
                        # pick next if possoble
                        selected_input_id = input_id + 1
                    elif input_id > 1:
                        # pick one below if next not available
                        selected_input_id = input_id - 1
                    
        
        if not self._merge_enabled:
            return

        if not default_device:
            # pick the first one if nothing else got selected
            default_device = devices[0]

        


        selected_device_index = devices.index(default_device)

        for dev in devices:
            self.merge_device_map[dev.device_id] = dev
            axis_list = {}
            for input_id in range(1, dev.axis_count+1):
                if dev.device_guid == self.action_data.hardware_device_guid and \
                    input_id == self.action_data.hardware_input_id:
                    # skip self as a possible input
                    continue 
                axis_name = self.get_axis_name(input_id)
                axis_list[input_id] = f"Axis {input_id} ({axis_name})"

            if axis_list:
                self.merge_input_map[dev.device_id] = axis_list
                self.merge_selector_device_widget.addItem(dev.name, dev.device_id)


        # merge operation mode
        self.container_merge_options_widget = QtWidgets.QWidget()
        self.container_merge_options_layout = QtWidgets.QHBoxLayout(self.container_merge_options_widget)
        self._merge_widgets_map = {}
        for merge_type in MergeOperationType:
            if merge_type != MergeOperationType.NotSet:
                rb = gremlin.ui.ui_common.QDataRadioButton(text = MergeOperationType.to_display_name(merge_type), data = merge_type)
                self.container_merge_options_layout.addWidget(rb)
                self._merge_widgets_map[merge_type] = rb
                if merge_type == self.action_data.merge_mode:
                    rb.setChecked(True)
                rb.clicked.connect(self._merge_mode_changed_cb)

        self.merge_invert_widget = QtWidgets.QCheckBox("Invert")
        self.merge_invert_widget.setChecked(self.action_data.merge_invert)
        self.merge_invert_widget.clicked.connect(self._merge_invert_changed_cb)
        self.container_merge_options_layout.addWidget(self.merge_invert_widget)


        # ranged merged output
        self.container_output_range_widget = QtWidgets.QWidget()
        self.container_output_range_layout = QtWidgets.QHBoxLayout(self.container_output_range_widget)
        self.container_output_range_widget.setContentsMargins(0,0,0,0)
        
        self.sb_range_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.sb_range_min_widget.setValue(self.action_data.output_range_min)
        self.sb_range_min_widget.valueChanged.connect(self._range_min_changed_cb)

        self.sb_range_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.sb_range_max_widget.setValue(self.action_data.output_range_max)

        self.sb_range_max_widget.valueChanged.connect(self._range_max_changed_cb)
        self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Min:"))
        self.container_output_range_layout.addWidget(self.sb_range_min_widget)
        self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Max:"))
        self.container_output_range_layout.addWidget(self.sb_range_max_widget)
        self.container_output_range_layout.addStretch()


        self.container_merge_options_layout.addStretch()

        self.container_merge_layout.addWidget(self.container_merge_options_widget)
        self.container_merge_layout.addWidget(self.container_output_range_widget)

        self.main_layout.addWidget(self.container_merge_widget)

        # select the default device
        self.merge_selector_device_widget.setCurrentIndex(selected_device_index)

        selected_input_index = self.merge_selector_input_widget.findData(selected_input_id)
        if selected_input_index == -1:
            selected_input_index = 0
        self.merge_selector_input_widget.setCurrentIndex(selected_input_index)




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
            curve_data.curve_update()
            self.action_data.curve_data = curve_data
            
        dialog = gremlin.curve_handler.AxisCurveDialog(self.action_data.curve_data)
        util.centerDialog(dialog, dialog.width(), dialog.height())
        self.curve_update_handler = dialog.curve_update_handler
        self._update_axis_widget(self._current_input_axis())

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        gremlin.shared_state.pop_suspend_highlighting()
        self.curve_update_handler = None

        self._update_curve_icon()

    QtCore.Slot()
    def _curve_delete_button_cb(self):
        ''' removes the curve data '''
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Confirmation")
        message_box.setInformativeText("Delete curve data for this output?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
        )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        is_cursor = isCursorActive()
        if is_cursor:
            popCursor()
        response = message_box.exec()
        if is_cursor:
            pushCursor()
        if response == QtWidgets.QMessageBox.StandardButton.Ok:
            self.action_data.curve_data = None
            self._update_curve_icon()
        

    QtCore.Slot()
    def _range_min_changed_cb(self):
        value = self.sb_range_min_widget.value()
        self.action_data.output_range_min = value
        self._update_axis_widget()        

    QtCore.Slot()
    def _range_max_changed_cb(self):
        self.action_data.output_range_max = self.sb_range_max_widget.value()
        self._update_axis_widget()                

    @QtCore.Slot()
    def _device_changed_cb(self):
        ''' merge device changed '''
        index = self.merge_selector_device_widget.currentIndex()
        device_id = self.merge_selector_device_widget.itemData(index)
        with QtCore.QSignalBlocker(self.merge_selector_input_widget):
            self.merge_selector_input_widget.clear()
            first_input_id = None
            for input_id, axis_name in self.merge_input_map[device_id].items():
                self.merge_selector_input_widget.addItem(axis_name, input_id)
                if first_input_id is None:
                    first_input_id = input_id
        self.action_data.merge_device_id = device_id
        self.action_data.merge_input_id = first_input_id
        
        
    @QtCore.Slot()
    def _input_changed_cb(self):
        ''' merge input changed '''
        index = self.merge_selector_input_widget.currentIndex()
        input_id = self.merge_selector_input_widget.itemData(index)
        self.action_data.merge_input_id = input_id


    def _profile_start(self):
        ''' called when the profile starts '''
        el = gremlin.event_handler.EventListener()
        el.custom_joystick_event.disconnect(self._joystick_event_handler)
        if not self.chained_input:
            el.joystick_event.disconnect(self._joystick_event_handler)
        

    def _profile_stop(self):
        ''' called when the profile stops'''
        self._update_axis_widget()
        el = gremlin.event_handler.EventListener()
        el.custom_joystick_event.connect(self._joystick_event_handler)
        if not self.chained_input:
            el.joystick_event.connect(self._joystick_event_handler)

    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
        if gremlin.shared_state.is_running:
            return 

        if not event.is_axis:
            return 
        
        value = None
        
        if self.action_data.action_mode == VjoyAction.VjoyMergeAxis:
            # merge - check two sets 
            if event.device_guid == self.action_data.hardware_device_guid and event.device_guid == self.action_data.merge_device_guid:
                # merge hardware is the same as current input - accept only the two input itds
                if event.identifier != self.action_data.hardware_input_id and event.identifier != self.action_data.merge_input_id:
                    return
            else:
                # not the same:
                if event.device_guid == self.action_data.hardware_device_guid and event.identifier != self.action_data.hardware_input_id:
                    return
                if event.device_guid == self.action_data.merge_device_guid and event.identifier != self.action_data.merge_input_id:
                    return
            
        
        else:
            if event.device_guid != self.action_data.hardware_device_guid:
                return
            if event.identifier != self.action_data.hardware_input_id:
                return
            if event.is_custom:
                value = event.value
        
        self._update_axis_widget(value)
        

    def _current_input_axis(self):
        ''' gets the current input axis value '''
        return gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid, 
                                                  self.action_data.hardware_input_id) 
        

    def _update_axis_widget(self, value : float = None):
        ''' updates the axis output repeater with the value 
        
        :param value: the floating point input value, if None uses the cached value
        
        '''
        # always read the current input as the value could be from another device for merged inputs
        if self.input_type == InputType.JoystickAxis:
            self._axis_repeater_widget.setVisible(True)
            raw_value = self.action_data.get_raw_axis_value()
            if value is None:
                # filter and merge the data
                filtered_value = self.action_data.get_filtered_axis_value(raw_value)
                value = filtered_value
            if self.action_data.curve_data is not None:
                # curve the data 
                curved_value = self.action_data.curve_data.curve_value(value)
                self._axis_repeater_widget.show_curved = True
                self._axis_repeater_widget.setValue(value, curved_value)
            else:
                self._axis_repeater_widget.show_curved = False
                self._axis_repeater_widget.setValue(value)
                
                

            # update the curved window if displayed
            if self.curve_update_handler is not None:
                self.curve_update_handler(raw_value)
        else:
            self._axis_repeater_widget.setVisible(False)

        



    @QtCore.Slot(bool)
    def _merge_invert_changed_cb(self, checked):
        self.action_data.merge_invert = checked
        self._update_axis_widget()

    @QtCore.Slot(bool)
    def _merge_mode_changed_cb(self, checked):
        ''' merge mode selection change '''
        widget = self.sender()
        self.merge_type = widget.data

    @property
    def merge_type(self) -> MergeOperationType:
        return self.action_data.merge_type
    
    @merge_type.setter
    def merge_type(self, value : MergeOperationType):
        if self.action_data.merge_mode != value:
            self.action_data.merge_mode = value
            widget = self._merge_widgets_map[value]
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(True)
            self._update_axis_widget()



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
            axis_name = f"(unknown [{input_id}])"
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

        match self.action_data.action_mode:
            case VjoyAction.VJoyAxisToButton:
                action_name = f"Vjoy device {vjoy_device_id} button {vjoy_input_id}"


        is_axis = self.action_data.input_is_axis()
        if is_axis:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} axis {vjoy_input_id} ({self.get_axis_name(vjoy_input_id)})"
            if input_type != InputType.JoystickAxis:
                name = f"Input axis -> {action_name}"
            else:
                axis_name = self.get_axis_name(input_id)
                name = f"Axis {input_id} ({axis_name}) -> {action_name}"
        elif input_type in VJoyWidget.input_type_buttons:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} button {vjoy_input_id}"
            name = f"Button {input_id} -> {action_name}"
        elif input_type == InputType.JoystickHat:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} hat {vjoy_input_id}"
            name = f"Hat {input_id} -> {action_name}"
        else:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} button {vjoy_input_id}"
            name = f"Input trigger -> {action_name}"
        
        
        box.addWidget(QtWidgets.QLabel(name))
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
        self.cb_action_list = gremlin.ui.ui_common.NoWheelComboBox()
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
        self.cb_vjoy_device_selector = gremlin.ui.ui_common.NoWheelComboBox()
        grid.addWidget(self.cb_vjoy_device_selector,row,1)
        
                             
        self.vjoy_map = {} # holds the count of axes for
        devices = sorted(joystick_handling.vjoy_devices(),key=lambda x: x.vjoy_id)
        for dev in devices:
            #self.cb_vjoy_device_selector.addItem(f"VJoy device {dev.vjoy_id}", dev.vjoy_id)
            self.cb_vjoy_device_selector.addItem(dev.name, dev.vjoy_id)
            self.vjoy_map[dev.vjoy_id] = dev
        

        row = 3
        self.cb_vjoy_input_selector = gremlin.ui.ui_common.NoWheelComboBox()
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

        grid_visible_container_widget = QtWidgets.QWidget()
        grid_visible_container_widget.setContentsMargins(0,0,0,0)
        self.grid_visible_container_layout = QtWidgets.QHBoxLayout(grid_visible_container_widget)
        self.grid_visible_container_layout.setContentsMargins(0,0,0,0)

        start_layout.addWidget(grid_visible_container_widget)
        start_layout.addStretch()

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
        self.target_value_container_widget = QtWidgets.QWidget()
        self.target_value_container_layout = QtWidgets.QHBoxLayout(self.target_value_container_widget)
        self.sb_button_to_axis_value = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_button_to_axis_value.setMinimum(-1.0)
        self.sb_button_to_axis_value.setMaximum(1.0)
        self.sb_button_to_axis_value.setDecimals(3)
        self.target_value_container_layout.addWidget(QtWidgets.QLabel("Axis Value:"))
        self.target_value_container_layout.addWidget(self.sb_button_to_axis_value)
        self.target_value_container_layout.addStretch()

        self.main_layout.addWidget(self.selector_widget)
        self.main_layout.addWidget(self.pulse_widget)
        self.main_layout.addWidget(self.start_widget)
        self.main_layout.addWidget(self.axis_range_container_widget)
        self.main_layout.addWidget(self.target_value_container_widget)
       
        # hook events

        
        

        self.chkb_exec_on_release.clicked.connect(self._exec_on_release_changed)
        self.chkb_paired.clicked.connect(self._paired_changed)
        #self.target_value_text.textChanged.connect(self._target_value_changed)
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
            if self.action_data.input_is_axis():
                # axis can only set an axis
                actions = (VjoyAction.VJoyAxis, VjoyAction.VJoyAxisToButton, VjoyAction.VjoyMergeAxis)
                
                
            elif self.action_data.input_type in (InputType.JoystickButton, InputType.Keyboard, InputType.KeyboardLatched, InputType.OpenSoundControl, InputType.Midi):
                # various button modes
                actions = ( VjoyAction.VJoyButton,
                            VjoyAction.VjoyButtonRelease,
                            VjoyAction.VJoyPulse,
                            VjoyAction.VJoyToggle,
                            VjoyAction.VJoyInvertAxis,
                            VjoyAction.VJoySetAxis,
                            VjoyAction.VJoyRangeAxis,
                            VjoyAction.VjoyMergeAxis,
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
                actions = [VjoyAction.VJoyHat]

            else:
                log_sys_warn(f"VJOYREMAP: don't know what actions to load for input type: {self.action_data.input_type}")

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
            if action_mode in (VjoyAction.VJoySetAxis, VjoyAction.VJoyRangeAxis, VjoyAction.VJoyAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VjoyMergeAxis):
                count = dev.axis_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Axis {id} ({self.get_axis_name(id)})",id)
            elif input_type in (VJoyWidget.input_type_buttons) or action_mode == VjoyAction.VJoyAxisToButton:
                count = dev.button_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Button {id}",id)
            elif input_type == InputType.JoystickHat:
                count = dev.button_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Hat {id}",id)
            else:
                # keyboard, latched keyboard, midi and OSC
                pass

            index = self.cb_vjoy_input_selector.findData(self.action_data.vjoy_input_id)
            if index != -1:
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
        merge_visible =  False
        repeater_visible = False
        
        
        

        if self._is_axis:
            grid_visible = action == VjoyAction.VJoyAxisToButton
            range_visible = action in (VjoyAction.VJoyRangeAxis, VjoyAction.VJoyAxisToButton)
            axis_visible = not (grid_visible or range_visible) # or hardware_widget_visible)
            merge_visible = action == VjoyAction.VjoyMergeAxis and axis_visible
            repeater_visible = True

        elif input_type in VJoyWidget.input_type_buttons:
            pulse_visible = action == VjoyAction.VJoyPulse
            start_visible = action in (VjoyAction.VJoyButton, VjoyAction.VjoyButtonRelease)
            grid_visible = action in (VjoyAction.VJoyPulse, VjoyAction.VJoyButton, VjoyAction.VJoyToggle, VjoyAction.VjoyButtonRelease)
            paired_visible = action == VjoyAction.VJoyButton
            exec_on_release_visible =  action_data.input_type in VJoyWidget.input_type_buttons
        elif input_type == InputType.JoystickHat:
            pass

        match action:
            case VjoyAction.VJoyRangeAxis:
                range_visible = True
                grid_visible = False
            case VjoyAction.VJoySetAxis:
                range_visible = False
            case VjoyAction.VJoyAxisToButton:
                repeater_visible = False


        self.container_repeater_widget.setVisible(repeater_visible)

        is_command = VjoyAction.is_command(action)
        selector_visible = not is_command

        button_to_axis_visible = action == VjoyAction.VJoySetAxis

        grid_visible = grid_visible and self.action_data.grid_visible

        self.pulse_widget.setVisible(pulse_visible)
        self.start_widget.setVisible(start_visible)
        if self.button_grid_widget:
            self.button_grid_widget.setVisible(grid_visible)
        if self.container_axis_widget:
            self.container_axis_widget.setVisible(axis_visible)
        
        # merge axis options
        if self._merge_enabled:
            self.container_merge_widget.setVisible(merge_visible)


        # self.hardware_input_container_widget.setVisible(hardware_widget_visible)
        self.axis_range_container_widget.setVisible(range_visible)
        self.chkb_exec_on_release.setVisible(exec_on_release_visible)
        self.chkb_paired.setVisible(paired_visible)
        # self.target_value_widget.setVisible(target_value_visible)
        self.target_value_container_widget.setVisible(button_to_axis_visible)

        self.lbl_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_input_selector.setVisible(selector_visible)
        self.lbl_vjoy_input_selector.setVisible(selector_visible)

        self.action_label.setText(VjoyAction.to_description(action))

        

    def _action_mode_changed(self, index):
        ''' called when the drop down value changes '''
        with QtCore.QSignalBlocker(self.cb_action_list):
            action : VjoyAction = self.cb_action_list.itemData(index)
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

        grid_visible = self.action_data.grid_visible   
        if self.grid_visible_widget is None:
            self.grid_visible_widget = QtWidgets.QCheckBox("Show button grid")
            self.grid_visible_widget.clicked.connect(self._grid_visible_cb)
            self.grid_visible_container_layout.addWidget(self.grid_visible_widget)

        with QtCore.QSignalBlocker(self.grid_visible_widget):
            self.grid_visible_widget.setChecked(grid_visible)

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
        input_type = self.action_data.input_type


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
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            

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
        self.button_grid_widget.setVisible(grid_visible)
   
    @QtCore.Slot(bool)
    def _grid_visible_cb(self, checked):
        self.action_data.grid_visible = checked
        self.button_grid_widget.setVisible(checked)

    @QtCore.Slot()            
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

        #log_sys(f"populate vjoy data for action id: {self.action_data.action_id}  action mode: {self.action_data.action_mode}  vjoy: {self.action_data.vjoy_device_id}")
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
        button_id = None

        
        
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
                #log_sys_warn(f"Mode not found in drop down: {self.action_data.action_mode.name} - resetting to default mode")
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

                with QtCore.QSignalBlocker(self.sb_start_value):
                    self.sb_start_value.setValue(self.action_data.axis_start_value)

                with QtCore.QSignalBlocker(self.relative_scaling):
                    self.relative_scaling.setValue(self.action_data.axis_scaling)

                with QtCore.QSignalBlocker(self.sb_axis_range_low):
                    self.sb_axis_range_low.setValue(self.action_data.range_low)

                with QtCore.QSignalBlocker(self.sb_axis_range_high):
                    self.sb_axis_range_high.setValue(self.action_data.range_high)

            elif self.action_data.input_type in (InputType.JoystickButton, InputType.Keyboard, InputType.KeyboardLatched, InputType.OpenSoundControl, InputType.Midi):
                is_button_mode = True

            if self.action_data.action_mode == VjoyAction.VJoyAxisToButton:
                is_button_mode = True
                with QtCore.QSignalBlocker(self.sb_button_range_low):
                    self.sb_button_range_low.setValue(self.action_data.range_low)
                with QtCore.QSignalBlocker(self.sb_button_range_high):
                    self.sb_button_range_high.setValue(self.action_data.range_high)
            
                with QtCore.QSignalBlocker(self.sb_button_to_axis_value):
                    self.sb_button_to_axis_value.setValue(self.action_data.target_value)

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

            # # populate hardware devices if in merge mode
            # self._populate_hardware()
            # self._populate_hardware_axis()

            # update based on current mode

            self._populate_grid(vjoy_dev_id, button_id)
            self._update_vjoy_device_input_list()
            self._update_ui_action_mode(self.action_data)

        except gremlin.error.GremlinError as e:
            util.display_error(
                f"A needed vJoy device is not accessible: {e}\n\n" +
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
    
    def _populate_grid(self, device_id, button_id):
        ''' updates the usage grid based on current VJOY mappings '''
        used_pixmap = load_pixmap("used.png")
        unused_pixmap = load_pixmap("unused.png")

        for cb in self.button_group.buttons():
            id = self.button_group.id(cb)

            if id == button_id:
                with QtCore.QSignalBlocker(cb):
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
    
    def __init__(self, action_data):
        super().__init__(action_data)
        self.action_data : VjoyRemap = action_data
        self.vjoy_device_id = action_data.vjoy_device_id
        self.vjoy_input_id = action_data.vjoy_input_id
        self.input_type = action_data.input_type
        self.axis_mode = action_data.axis_mode
        self.axis_scaling = action_data.axis_scaling
        self.action_mode = action_data.action_mode
        self.pulse_delay = action_data.pulse_delay
        self.start_pressed = action_data.start_pressed
        self.target_value = action_data.target_value
        self.target_value_valid = action_data.target_value_valid
        self.range_low = action_data.range_low
        self.range_high = action_data.range_high

        self.exec_on_release = action_data.exec_on_release
        self.paired = action_data.paired

        self.needs_auto_release = self._check_for_auto_release(action_data)
        self.thread_running = False
        self.should_stop_thread = False
        self.thread_last_update = time.time()
        self.thread = None
        self.axis_delta_value = 0.0
        self.axis_value = 0.0
        self.axis_start_value = action_data.axis_start_value

        self.remote_client = input_devices.remote_client

        self.lock = threading.Lock()

        
    @property
    def reverse(self):
        # axis reversed state
        return usage_data.is_inverted(self.vjoy_device_id, self.vjoy_input_id)
        
    def toggle_reverse(self):
        # toggles reverse mode for the axis
        value = usage_data.is_inverted(self.vjoy_device_id, self.vjoy_input_id)
        usage_data.set_inverted(self.vjoy_device_id, self.vjoy_input_id, not value)
        log_sys(f"toggle reverse: {self.vjoy_device_id} {self.vjoy_input_id} new state: {self.reverse}")

    def latch_extra_inputs(self):
        ''' returns the list of extra devices to latch to this functor (device_guid, input_type, input_id) '''
        if self.action_data.merged:
            return [(self.action_data.merge_device_guid, self.action_data.merge_input_type, self.action_data.merge_input_id)]
        return []


    def profile_start(self):
        # setup initial state
        if self.input_type in VJoyWidget.input_type_buttons:
            # set start button state
            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = self.start_pressed
        if self.input_type == InputType.JoystickAxis:
            # set start axis range
            usage_data.set_range(self.vjoy_device_id, self.vjoy_input_id, self.range_low, self.range_high)
            # print(f"Axis start value: vjoy: {self.vjoy_device_id} axis: {self.vjoy_input_id}  value: {self.axis_start_value}")
            match self.action_mode:
                case VjoyAction.VJoyAxis:
                    joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = self.axis_start_value
                    self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, self.axis_start_value)

                case VjoyAction.VJoyAxisToButton:
                    device_guid = self.action_data.hardware_device_guid
                    input_id = self.action_data.hardware_input_id
                    value = joystick_handling.get_curved_axis(device_guid, input_id)
                    action_value = gremlin.actions.Value(value)
                    event = gremlin.event_handler.Event(gremlin.input_types.InputType.JoystickAxis,
                                                        device_guid = device_guid,
                                                        identifier=input_id,
                                                        is_axis=True,
                                                        value = action_value)
                    self.process_event(event, action_value)

	
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


    def process_event(self, event, action_value : gremlin.actions.Value):
        ''' runs when a joystick event occurs like a button press or axis movement when a profile is running '''
        # if self.action_data.merged and event.is_axis:
        #     # merged axis data is handled by the internal hook - ignore
        #     return True
        if event.is_axis:
            # process input options and any merge and curve operation
            value = self.action_data.get_filtered_axis_value(action_value.current)

            if self.action_data.curve_data is not None:
                # curve the output 
                value = self.action_data.curve_data.curve_value(value)

            action_value = gremlin.actions.Value(value)
        
        return self._process_event(event, action_value)
    
    def _process_event(self, event, value):
        ''' runs when a joystick even occurs like a button press or axis movement when a profile is running '''
        (is_local, is_remote) = input_devices.remote_state.state
        if event.force_remote:
            # force remote mode on if specified in the event
            is_remote = True
            is_local = False

        if event.is_axis: # self.input_type == InputType.JoystickAxis:
            # axis response mode
         
            target = value.current

            # axis mode
            if self.action_mode == VjoyAction.VJoyAxisToButton:
                r_min = self.range_low
                r_max = self.range_high
                #r_min, r_max = usage_data.get_range(self.vjoy_device_id, self.vjoy_input_id)
                if value.current >= r_min and value.current <= r_max:
                    # axis in range
                    # print (f"In range {value.current}")
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
                r_min, r_max = usage_data.get_range(self.vjoy_device_id, self.vjoy_input_id)
                if self.reverse:
                    target = -target

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

        elif self.input_type in VJoyWidget.input_type_buttons:
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

                    #if event.is_pressed:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = value.current
                    if is_remote or is_paired:
                        self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, value.current, force_remote = is_paired )
                    

                    
            
            elif self.action_mode == VjoyAction.VjoyButtonRelease:
                # normal default behavior
                if event.is_pressed:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = False
                    if is_remote or is_paired:
                        self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, False, force_remote = is_paired )
                    
            
            
            
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



class VjoyRemap(gremlin.base_profile.AbstractAction):

    """Action remapping physical joystick inputs to vJoy inputs."""

    name = "Vjoy Remap"
    tag = "vjoyremap"

    default_button_activation = (True, True)

    functor = VJoyRemapFunctor
    widget = VJoyWidget

    @property
    def priority(self):
        return 9

    def __init__(self, parent):
        """ vjoyremap action block """
        super().__init__(parent)
        self.parent = parent
        # Set vjoy ids to None so we know to pick the next best one
        # automatically
        self._vjoy_device_id : int = 1
        self.vjoy_input_id : int  = 1
        self.input_type : InputType = self.hardware_input_type

        self.vjoy_axis_id = 1
        self.vjoy_button_id = 1
        self.vjoy_hat_id = 1
     
        self._reverse : bool = False
        self.axis_mode = "absolute"
        self.axis_scaling : float  = 1.0
        self.axis_start_value : float = 0.0
        self.curve_data = None # present if curve data is needed

        config = gremlin.config.Configuration()
        self._grid_visible = config.button_grid_visible # true if the button grid is visible

        self._exec_on_release : bool = False
        self._paired : bool = False

        self._merge_device_id : str = None # input guid (str) of the merged device
        self._merge_device_guid : dinput.GUID = None # input guid for the merge device
        self.merge_input_id : int = None # input id of the merged input
        self.merge_input_type : gremlin.input_types.InputType =  gremlin.input_types.InputType.JoystickAxis # only merging axes at this point
        self._merge_mode : MergeOperationType = MergeOperationType.NotSet # default merge method
        self.output_range_min : float = -1.0 # min for merged output
        self.output_range_max : float = 1.0 # max for merged output
        self.merge_invert : bool = False # inversion flag for merged output
        self.merged = False
        
        # default mode
        self._action_mode = VjoyAction.VJoyButton

        self.range_low = -1.0 # axis range min
        self.range_high = 1.0 # axis range max
        is_axis = self.input_is_axis()

        # pick an appropriate default action set for the type of input this is
        if is_axis:
                # input is setup as an axis
                self._action_mode = VjoyAction.VJoyAxis
        elif self.input_type in VJoyWidget.input_type_buttons:
            self._action_mode = VjoyAction.VJoyButton
        elif self.input_type == InputType.JoystickHat:
            self._action_mode = VjoyAction.VJoyHat

        self.current_state = 0 # toggle value for the input 1 means set, any other value means not set for buttons
        self.pulse_delay = 250 # pulse delay
        self.start_pressed = False # true if a button starts as pressed when the profile is loaded
        self.target_value = 0.0
        self.target_value_valid = True


    def get_raw_axis_value(self):
        return gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)

    def get_filtered_axis_value(self, value : float = None) -> float:
        ''' computes the output value for the current configuration  '''

        if value is None:
            value = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, 
                                                        self.hardware_input_id)

        if self.merge_mode != MergeOperationType.NotSet:
            if self.merge_device_id and self.merge_input_id:
                # always read v1 and v2 because the input value may be of either inputs
                v1 = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, 
                                                        self.hardware_input_id) 
                v2 = gremlin.joystick_handling.get_curved_axis(self.merge_device_guid, 
                                                    self.merge_input_id) 
                
                match self.merge_mode:
                    case MergeOperationType.Add:
                        value = scale_to_range(v1+v2,
                                            target_min=self.output_range_min, 
                                            target_max=self.output_range_max,
                                            invert = self.merge_invert)
                    case MergeOperationType.Average:
                        value = scale_to_range((v1+v2)/2,
                                                target_min=self.output_range_min, 
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)
                    case MergeOperationType.Center:
                        value = scale_to_range((v1-v2)/2,
                                                target_min=self.output_range_min, 
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)
                    case MergeOperationType.Min:
                        value = scale_to_range(min(v1,v2),
                                                target_min=self.output_range_min, 
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)
                    case MergeOperationType.Max:
                        value = scale_to_range(max(v1,v2),
                                                target_min=self.output_range_min, 
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)
        return value

    @property
    def merge_mode(self) -> MergeOperationType:
        return self._merge_mode
    @merge_mode.setter
    def merge_mode(self, value : MergeOperationType):
        self._merge_mode = value
        self.merged = value != MergeOperationType.NotSet
 
    @property
    def merge_device_id(self) -> str:
        return self._merge_device_id
    
    @merge_device_id.setter
    def merge_device_id(self, value : str | dinput.GUID):
        if value is None:
            self._merge_device_id = None
            self._merge_device_guid = None
            return
        if not isinstance(value, str):
            value = str(value)
        self._merge_device_id = value
        self._merge_device_guid = util.parse_guid(value)
    
    @property
    def merge_device_guid(self) -> dinput.GUID:
        return self._merge_device_guid
    @merge_device_guid.setter
    def merge_device_guid(self, value : dinput.GUID):
        if value is None:
            self._merge_device_id = None
            self._merge_device_guid = None
            return
        self._merge_device_guid = value
        self._merge_device_id = str(value)
    


    def display_name(self):
        ''' display name for this action '''
        if self.action_mode == VjoyAction.VJoyAxis:
            return f"VJoy #{self._vjoy_device_id} Axis: {self.vjoy_axis_id}"
        elif self.action_mode == VjoyAction.VJoyButton:
            return f"VJoy #{self._vjoy_device_id} Button: {self.vjoy_button_id}"
        elif self.action_mode == VjoyAction.VJoyHat:
            return f"VJoy #{self._vjoy_device_id} Hat: {self.vjoy_hat_id}"
        else:
            return f"VJoy #{self._vjoy_device_id} Mode: {self.action_mode}"
        
        
    def input_is_axis(self):
        ''' true if the input is an axis type input '''

        is_axis = hasattr(self.hardware_input_id, "is_axis") and self.hardware_input_id.is_axis
        if hasattr(self.input_item,"is_axis"):
            is_axis = is_axis or self.input_item.is_axis
        is_axis = is_axis or self.input_type == InputType.JoystickAxis 
        return is_axis

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
    def action_mode(self) -> VjoyAction:
        return self._action_mode
    
    @action_mode.setter
    def action_mode(self, value : VjoyAction):
        self._action_mode = value
        # print (f"action mode set to : {value}")


    @property
    def reverse(self):
        # axis reversed state
        return usage_data.is_inverted(self.vjoy_device_id, self.vjoy_axis_id) or self._reverse
        
    @reverse.setter
    def reverse(self,value):
        usage_data.set_inverted(self.vjoy_device_id, self.vjoy_axis_id, value)
        self._reverse = value

    def toggle_reverse(self):
        # toggles reverse mode for the axis
        self.reverse = not self.reverse


    @property
    def reverse_configured(self) -> bool:
        ''' returns the configured reverse value rather than the live mode '''
        return  self._reverse
    
    @property
    def grid_visible(self) -> bool:
        return self._grid_visible
    @grid_visible.setter
    def grid_visible(self, value : bool):
        self._grid_visible = value
        config = gremlin.config.Configuration()
        config.button_grid_visible = value

    def icon(self):
        """Returns the icon corresponding to the remapped input.

        :return icon representing the remap action
        """
        # Do not return a valid icon if the input id itself is invalid
        # if self.vjoy_input_id is None:
        #     return None
        fallback = "joystick.svg"
        if self.action_mode in (VjoyAction.VJoySetAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoyAxis):
            input_string = "axis"
            fallback = "joystick.svg"
        elif self.action_mode == VjoyAction.VJoyHat:
            input_string = "hat"
            fallback = "mdi.axis-arrow"
        elif self.action_mode in (VjoyAction.VJoyButton, VjoyAction.VjoyButtonRelease, VjoyAction.VJoyPulse):
            input_string = "button"
            fallback = "mdi.gesture-tap-button"
        else:
            input_string = None
            #log_sys_warn(f"VjoyRemap: don't know how to handle action mode: {self.action_mode}")

        
        icon_path = f"icon_{input_string}_{self.vjoy_input_id:03d}.png" if input_string else "joystick.png"
        
        icon_file = get_icon_path(icon_path)
        if os.path.isfile(icon_file):
            return icon_file
            
        return fallback
    
        #return super().icon()
            
    


    def requires_virtual_button(self):
        """Returns whether or not the action requires an activation condition.

        :return True if an activation condition is required, False otherwise
        """
        input_type = self.input_type

        if input_type in VJoyWidget.input_type_buttons:
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

        try:
            valid = False
            for input_type in InputType.to_list():
                attrib_name = InputType.to_string(input_type)
                if attrib_name in node.attrib:
                    self.input_type = input_type
                    self.vjoy_input_id = safe_read(node, attrib_name, int)
                    self.vjoy_axis_id = self.vjoy_input_id
                    self.vjoy_button_id = self.vjoy_input_id
                    valid = True
                    break

            if not valid:
                raise gremlin.error.GremlinError(f"VJOYREMAP: Invalid remap type provided: {node.attrib}")

            self.vjoy_device_id = safe_read(node, "vjoy", int)

            if "input" in node.attrib:
                index = safe_read(node,"input", int, 1)
                self.set_input_id(index)


            # hack to sync all loaded profile setups with the status grid
            usage_data = VJoyUsageState()
            usage_data.push_load_list(self.vjoy_device_id,self.input_type,self.vjoy_input_id)
            
            
            self.pulse_delay = 250
            self.merge_input_id = None
            self.merge_device_id = None

            if "mode" in node.attrib:
                value = node.attrib['mode']
                self.action_mode = VjoyAction.from_string(value)
            else:
                if self.input_type in VJoyWidget.input_type_buttons:
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

            if "merge_device_id" in node.attrib:
                self.merge_device_id = node.get("merge_device_id")
            
            if "merge_input_id" in node.attrib:
                self.merge_input_id = safe_read(node,"merge_input_id", int, 0)

            if "merge_input_type" in node.attrib:
                merge_input_type = safe_read(node,"merge_input_type", str, "")
                self.merge_input_type = gremlin.input_types.InputType.to_enum(merge_input_type)

            if "merge_mode" in node.attrib:
                mode = node.get("merge_mode")
                try:
                    merge_mode = MergeOperationType.to_enum(mode)
                    self.merge_mode = merge_mode
                except:
                    pass
            if "merge_invert" in node.attrib:
                self.merge_invert = safe_read(node,"merge_invert", bool, False)
            if "merge_min" in node.attrib:
                self.output_range_min = safe_read(node,"merge_min", float, -1.0)
            if "merge_max" in node.attrib:
                self.output_range_max = safe_read(node,"merge_max", float, 1.0)

            if "grid_visible" in node.attrib:
                self.grid_visible = safe_read(node,"grid_visible", bool, True)

            # curve data
            curve_node = util.get_xml_child(node,"response-curve")
            if curve_node is not None:
                self.curve_data = gremlin.curve_handler.AxisCurveData()
                self.curve_data._parse_xml(curve_node)
                self.curve_data.curve_update()


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
        
        node.set(
            InputType.to_string(self.input_type),
            str(self.vjoy_input_id)
        )

        node.set("mode", safe_format(VjoyAction.to_string(self.action_mode), str))
        node.set("input", safe_format(self.vjoy_input_id, int))
        
        match self.action_mode:
            case VjoyAction.VJoyAxis:
                node.set("axis-type", safe_format(self.axis_mode, str))
                node.set("axis-scaling", safe_format(self.axis_scaling, float))
                node.set("axis_start_value", safe_format(self.axis_start_value, float))
                node.set("range_low", safe_format(self.range_low, float))
                node.set("range_high", safe_format(self.range_high, float))
                reverse = safe_format(self.reverse_configured, bool)
                node.set("reverse", reverse)

            case VjoyAction.VJoyButton:
                # button, command or
                node.set("start_pressed", safe_format(self.start_pressed, bool))
                node.set("paired", safe_format(self.paired, bool))
            
            case VjoyAction.VJoySetAxis:
                node.set("target_value", safe_format(self.target_value, float))

            case VjoyAction.VjoyMergeAxis:
                node.set("merge_mode", MergeOperationType.to_string(self.merge_mode))
                if self.merge_device_id:
                    node.set("merge_device_id", self.merge_device_id)
                if self.merge_input_id:
                    node.set("merge_input_id", str(self.merge_input_id))
                node.set("merge_invert", safe_format(self.merge_invert, bool))
                node.set("merge_min", safe_format(self.output_range_min, float))
                node.set("merge_max", safe_format(self.output_range_max, float))
                node.set("merge_input_type", gremlin.input_types.InputType.to_string(self.merge_input_type))
                

            case VjoyAction.VJoyPulse:
                node.set("pulse_delay", safe_format(self.pulse_delay, int))

            case VjoyAction.VJoyAxisToButton:
                node.set("range_low", safe_format(self.range_low, float))
                node.set("range_high", safe_format(self.range_high, float))


        if self.curve_data is not None:
            curve_node =  self.curve_data._generate_xml()
            node.append(curve_node)

        if VjoyAction.is_command(self.action_mode) or self.action_mode:
            node.set("start_pressed", safe_format(self.start_pressed, bool))
            node.set("paired", safe_format(self.paired, bool))

        if save_exec_on_release:
            node.set("exec_on_release", safe_format(self.exec_on_release, bool))

        node.set("grid_visible", safe_format(self.grid_visible, bool))

        return node

    def _is_valid(self):
        """Returns whether or not the action is configured properly.

        :return True if the action is configured correctly, False otherwise
        """
        
        if self.vjoy_device_id is None or self.vjoy_input_id is None:
            return False
        return True

version = 1
name = "Vjoy Remap"
create = VjoyRemap


