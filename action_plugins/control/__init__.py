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
from gremlin.types import ControlAction
from gremlin.util import *
import gremlin.util
import psygnal
from psygnal import Signal


syslog = logging.getLogger("system")

class ControlWidget(gremlin.ui.input_item.AbstractActionWidget):
    ''' control plugin UI '''

    def __init__(self, action_data, parent=None):
        """Creates a new system control widget.

        :param action_data profile data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, Control))


    def _create(self, action_data):
        ''' initialization '''
        pass

        
    def _create_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self.action_widget = gremlin.ui.ui_common.QDataComboBox()

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

 

        self.grid_action_widget, grid_action_layout = gremlin.ui.ui_common.getGridContainer()

        row = 0
        grid_action_layout.addWidget(QtWidgets.QLabel("Action:"), row, 0)
        grid_action_layout.addWidget(self.action_widget, row, 1)
        grid_action_layout.addWidget(QtWidgets.QWidget(),row, 2)


        grid_action_layout.setColumnStretch(2,2)

        self.main_layout.addWidget(self.grid_action_widget)

        

    def _populate_ui(self):
        pass

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
        gremlin.config.Configuration().last_control_action = action
        

class ControlFunctor(gremlin.base_profile.AbstractFunctor):
    ''' control functor '''
    
    def __init__(self, action_data, parent = None):
        super().__init__(action_data, parent)
        self.action_data = action_data
     


    def process_event(self, event, action_value : gremlin.actions.Value, extra_data = None):
    
        if event.is_pressed is None:
            return
        is_pressed = event.is_pressed
        el = gremlin.event_handler.EventListener()
        if is_pressed:
            match self.action_data.action:
                case ControlAction.TTSAbort:
                    tts = gremlin.tts.TextToSpeech()
                    tts.abort()
                    return True
                case ControlAction.ProfileStop:
                    # stop the profile
                    el.request_profile_stop.emit(None)
                    return True
                case ControlAction.LocalDisable:
                    # disable local output
                    gremlin.remote.remote_control.setLocal(False)
                    return True
                case ControlAction.LocalEnable:
                    # disable local output
                    gremlin.remote.remote_control.setLocal(True)
                    return True
                case ControlAction.RemoteDisable:
                    # disable local output
                    gremlin.remote.remote_control.setRemote(False)
                    return True
                case ControlAction.RemoteEnable:
                    # disable local output
                    gremlin.remote.remote_control.setRemote(True)
                    return True
                case ControlAction.RemoteToggle:
                    # disable local output
                    gremlin.remote.remote_control.toggleRemote()
                    return True



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
    hint = "Maps to a GremlinEx control option."

    default_button_activation = (True, True)

    functor = ControlFunctor
    widget = ControlWidget
    
    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat
    ]


    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.action : ControlAction = ControlAction.TTSAbort
        self.setPriority(899) # run ahead of other actions in the same content but before mode change 
      

    def icon(self):
        return "fa6s.gears"
    
    def requires_virtual_button(self):
        return False
    
    def _parse_xml(self, node, data = None, extra_data = None):
        self.mode = None
        self.device_guid = None
        self.target_input_item = None

        #input_items = self._get_input_items()
        if "action" in node.attrib:
            action = safe_read(node,"action", str, 0)
            action = ControlAction.from_string(action)
            if action:
                self.action = action

    
    def _generate_xml(self):
        node = ElementTree.Element(Control.tag)

        node.set("action", safe_format(self.action.name.casefold(), str))

        return node
    

    def _is_valid(self):
        return True
        # if self.device_guid is not None and self.target_input_item is not None:
        #     return True
        # return False

    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        import html
        table = ReportTable(cellpadding=4)    
        table.addField("Control", f"{self.action.name}")
        return table.to_html()

version = 1
name = "Control"
create = Control