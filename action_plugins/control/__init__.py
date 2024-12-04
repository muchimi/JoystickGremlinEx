from __future__ import annotations
import logging
import threading
import time
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.actions
import gremlin.base_conditions
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.types
from gremlin.util import load_icon

from gremlin.base_conditions import InputActionCondition
from gremlin.input_types import InputType
from gremlin import input_devices, joystick_handling, util
from gremlin.error import ProfileError
from gremlin.util import safe_format, safe_read
import gremlin.ui.ui_common
import gremlin.ui.input_item
import os
import enum
from gremlin.input_devices import ControlAction, remote_state
from gremlin.util import *
import gremlin.util


syslog = logging.getLogger("system")

class ControlWidget(gremlin.ui.input_item.AbstractActionWidget):
    ''' control plugin UI '''

    def __init__(self, action_data, parent=None):
        """Creates a new VjoyRemapWidget.

        :param action_data profile data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, Control))


    def _create(self, action_data):
        ''' initialization '''
        self.profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        el = gremlin.event_handler.EventListener()
        el.modes_changed.connect(self._profile_modes_changed)
        
    def _create_ui(self):
        """Creates the UI components."""
        self.action_widget = gremlin.ui.ui_common.NoWheelComboBox()
        index = 0
        set_index = None
        for index, action in enumerate(ControlAction):
            self.action_widget.addItem(ControlAction.to_display_name(action), action)
            if set_index is None and action == self.action_data.action:
                set_index = index
            index+=1

        if set_index:
            self.action_widget.setCurrentIndex(set_index)

        self.action_widget.currentIndexChanged.connect(self._action_changed_cb)

        # list of modes the action applies to
        self.mode_selector = gremlin.ui.ui_common.NoWheelComboBox()
        self.mode_selector.currentIndexChanged.connect(self._mode_changed_cb)


        # list of input widgets/devices
        self.device_widget = gremlin.ui.ui_common.NoWheelComboBox()
        self.device_widget.currentIndexChanged.connect(self._device_changed_cb)

        # list of inputs for a given device
        self.input_widget = gremlin.ui.ui_common.NoWheelComboBox()
        self.input_widget.currentIndexChanged.connect(self._input_changed_cb)
        

        # update the device list
        self._update_mode_list()
        self._update_device_list()
        self.action_data.device_guid = self.device_widget.currentData().device_guid
        self._update_input_list()

        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)

        row = 0
        self.grid_layout.addWidget(QtWidgets.QLabel("Action:"), row, 0)
        self.grid_layout.addWidget(self.action_widget, row, 1)
        row +=1
        self.grid_layout.addWidget(QtWidgets.QLabel("Mode:"), row, 0)
        self.grid_layout.addWidget(self.mode_selector, row, 1)
        row +=1
        self.grid_layout.addWidget(QtWidgets.QLabel("Device:"), row, 0)
        self.grid_layout.addWidget(self.device_widget, row, 1)
        row +=1
        self.grid_layout.addWidget(QtWidgets.QLabel("Input:"), row, 0)
        self.grid_layout.addWidget(self.input_widget, row, 1)

        self.grid_layout.addWidget(QtWidgets.QLabel(),row, 2)
        self.grid_layout.setColumnStretch(3,1)

        self.main_layout.addWidget(self.grid_widget)

        
        
        
        

    def _populate_ui(self):
        pass

    def _update_mode_list(self):
        ''' updates the mode display'''

        with QtCore.QSignalBlocker(self.mode_selector):
            self.mode_selector.clear()
        
            # Create mode name labels visualizing the tree structure
            inheritance_tree = self.profile.build_inheritance_tree()
            labels = []
            gremlin.ui.ui_common._inheritance_tree_to_labels(labels, inheritance_tree, 0)

            # Filter the mode names such that they only occur once below
            # their correct parent
            mode_names = []
            display_names = []
            mode_list = []
            for entry in labels:
                if entry[0] in mode_names:
                    idx = mode_names.index(entry[0])
                    if len(entry[1]) > len(display_names[idx]):
                        del mode_names[idx]
                        del display_names[idx]
                        mode_names.append(entry[0])
                        display_names.append(entry[1])
                else:
                    mode_names.append(entry[0])
                    display_names.append(entry[1])

            mode = self.action_data.mode        
            index = 1
            set_index = None
            self.mode_selector.addItem("Any Mode", None)
            for display_name, mode_name in zip(display_names, mode_names):
                self.mode_selector.addItem(display_name, mode_name)
                if set_index is None and mode_name == mode:
                    set_index = index

            if set_index:
                self.mode_selector.setCurrentIndex(set_index)
            

    def _update_device_list(self):
        # device list
        device_list : list [gremlin.base_profile.Device] = self.profile.get_ordered_device_list()
        device_guid = self.action_data.device_guid

        with QtCore.QSignalBlocker(self.device_widget):
            self.device_widget.clear()
            index = 0
            set_index = None
            for index, device in enumerate(device_list):
                self.device_widget.addItem(device.name, device)
                if set_index is None and device_guid is not None and device.device_guid == device_guid:
                    set_index = index

            if set_index:
                self.device_widget.setCurrentIndex(set_index)

    def _update_input_list(self):
        # updates the list of inputs for the current device
        device = self.device_widget.currentData()
        device_profile = self.profile.get_device_modes(
                    device.device_guid,
                    device.type,
                    device.name
                )
        use_prefix = False
        if self.action_data.mode is None:
            mode_list = device_profile.modes.keys()
            use_prefix = True
        else:
            mode_list = [self.action_data.mode]

        self._index_map = {} # map of index to value
        self._item_map = {}  # map of values to their index
        index = 0
        self.input_widget.clear()   
        processed = []
        for mode in mode_list:
            input_items = device_profile.modes[mode]
            input_item = self.action_data.target_input_item
            
            with QtCore.QSignalBlocker(self.device_widget):
                set_index = None
                for input_type in input_items.config.keys():
                    sorted_keys = sorted(input_items.config[input_type].keys())
                    for data_key in sorted_keys:
                        data = input_items.config[input_type][data_key]
                        data.device_guid = device.device_guid
                        # identifier = gremlin.ui.input_item.InputIdentifier(
                        #     data.input_type,
                        #     data.device_guid,
                        #     data.input_id,
                        #     data.device_type,
                        #     data.input_name
                        # )
                        if not data in processed:  
                            if use_prefix and input_type not in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
                                self.input_widget.addItem(f"[{mode}] {data.input_name}", data)
                            else:
                                self.input_widget.addItem(data.input_name, data)
                            if set_index is None and input_item is not None and data.input_id == input_item:
                                set_index = index
                            index += 1
                            processed.append(data)
                if set_index:
                    self.input_widget.setCurrentIndex(set_index)


    @QtCore.Slot()
    def _action_changed_cb(self):
        action = self.action_widget.currentData()
        self.action_data.action = action

                    
    @QtCore.Slot()
    def _mode_changed_cb(self):
        mode = self.mode_selector.currentData()
        self.action_data.mode = mode # None means an mode
        self._update_device_list()
        self._update_input_list()

    @QtCore.Slot()
    def _profile_modes_changed(self):
        ''' called when the list of modes changes in the profile '''
        modes = self.profile.get_modes()
        if self.action_data.mode in modes:
            # nothing to do
            return
        # mode no longer exists
        self.action_data.mode = None
        self._update_mode_list()
        self._update_device_list()
        self._update_input_list()


                            
    @QtCore.Slot()
    def _device_changed_cb(self):
        device = self.device_widget.currentData()
        self.action_data.device_guid = device.device_guid
        self._update_input_list()

    @QtCore.Slot()
    def _input_changed_cb(self):
        input_item = self.input_widget.currentData()
        self.action_data.target_input_item = input_item
        
        

class ControlFunctor(gremlin.base_conditions.AbstractFunctor):
    ''' control functor '''
    
    def __init__(self, action_data, parent = None):
        super().__init__(action_data, parent)
        self.action_data = action_data


    def process_event(self, event, action_value : gremlin.actions.Value):
    
        if event.is_pressed is None:
            return
        is_pressed = event.is_pressed
        if is_pressed:
            # find the actionable input
            verbose = gremlin.config.Configuration().verbose
            profile = gremlin.shared_state.current_profile
            device_guid = self.action_data.device_guid
            input_item = self.action_data.target_input_item
            input_id = input_item.input_id
            action = self.action_data.action
            if device_guid in profile.devices:
                dev = profile.devices[device_guid]
                for mode_name in dev.modes.keys():
                    mode = dev.modes[mode_name]
                    for input_type in mode.config.keys():
                        item : gremlin.base_profile.InputItem
                        for item in mode.config[input_type].values():
                            if item.input_id == input_id:
                                match action:
                                    case ControlAction.DisableInput:
                                        if verbose: syslog.info(f"Control: disable input {item.display_name}")
                                        item.enabled = False
                                    case ControlAction.EnableInput:
                                        if verbose: syslog.info(f"Control: enable input {item.display_name}")
                                        item.enabled = True
                                    case ControlAction.ToggleInput:
                                        item.enabled = not item.enabled
                                        if verbose: syslog.info(f"Control: toggle input {item.display_name} -> {item.enabled}")
                                return True
                            
            return True

                            






class Control(gremlin.base_profile.AbstractAction):

    """Action remapping physical joystick inputs to vJoy inputs."""

    name = "Control"
    tag = "gremlin-control"

    default_button_activation = (True, True)

    functor = ControlFunctor
    widget = ControlWidget
    
    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
        InputType.KeyboardLatched,
        InputType.OpenSoundControl,
        InputType.Midi,
        
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.action : ControlAction = ControlAction.ToggleInput
        self.mode = gremlin.shared_state.edit_mode # selected mode
        self.device_guid = None
        self.target_input_item = None

    def icon(self):
        return "fa.gears"
    
    def requires_virtual_button(self):
        return False
    
  
    
    def _parse_xml(self, node):
        self.mode = None
        self.device_guid = None
        self.target_input_item = None

        #input_items = self._get_input_items()
        
        if "mode" in node.attrib:
            self.mode = node.get("mode")
        if "device_guid" in node.attrib:
            self.device_guid = parse_guid(node.get("device_guid"))
            #device_type = gremlin.types.DeviceType.to_enum(node.get("device_type"))
        for node_target in node:
            input_item = gremlin.base_profile.InputItem()
            input_item.from_xml(node_target)
            self.target_input_item = input_item
            break


    
    def _generate_xml(self):
        node = ElementTree.Element(Control.tag)
        if self.mode is not None:
            node.set("mode", self.mode)
        if self.device_guid is not None:
            node.set("device_guid", str(self.device_guid))
            device_type = self.get_device_type()
            node.set("device_type", gremlin.types.DeviceType.to_string(device_type))


        if self.target_input_item is not None:
            node_target = self.target_input_item.to_xml()
            node_target.set("target_type", type(self.target_input_item).__name__)
            node.append(node_target)

        return node
    

    def _is_valid(self):
        if self.device_guid is not None and self.target_input_item is not None:
            return True
        return False



version = 1
name = "Control"
create = Control