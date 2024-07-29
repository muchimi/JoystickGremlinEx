

# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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


import os
import lxml
from lxml import etree

from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.macro
from gremlin.ui import ui_common
import gremlin.ui.input_item
import gremlin.util
from gremlin.util import *
from gremlin.types import *

from enum import Enum, auto
from gremlin.macro_handler import *


class GateAction(Enum):
    ''' action when the axis is in the gate range '''
    NoAction = auto() # passthru (no change)
    Macro = auto() # trigger a macro
    SendKey = auto() # sends a key
    Ranged = auto() # send a ranged value determined by the Ranged output mode

class GateCondition(Enum):
    ''' gate action trigger conditions'''
    OnRangeEnter = auto() # triggers on entry in the gate range
    OnRangeEnterRepeat = auto() # triggers whenever the value changes while inside the range
    OnRangeExit = auto() # triggers on exit from the gate range
    OnEnterMin = auto() # trigger only when entering from the low range
    OnEnterMax = auto() # trigger only when entering from above the range
    OnExitMin = auto() # trigger only when existing the low end of the range
    OnExitMax = auto() # trigger only when exiting the high end of the range
    OnSteps = auto() # trigger for a given number of step values

class GateRangeOutputMode(Enum):
    ''' controls for ranged outputs what range is output given the gate range '''
    Normal = auto() # output range is the same as the input value
    Ranged = auto() # scales the output to a new range based on the min/max specified for the gate
    Fixed = auto() # output a fixed value
    Nothing = auto() # sends no data


 
_gate_action_from_name = {
    "no_action" : GateAction.NoAction,
    "macro" : GateAction.Macro,
    "keys": GateAction.SendKey,
    "ranged" : GateAction.Ranged
}

_gate_action_to_name = {
    GateAction.NoAction: "no_action",
    GateAction.Macro: "macro",
    GateAction.SendKey: "keys",
    GateAction.Ranged: "ranged"
}

_gate_action_description = {
    GateAction.NoAction: "Passtrhu (no action)",
    GateAction.Macro: "Executes a macro when triggered",
    GateAction.SendKey: "Sends the key when the intput enters the gate",
    GateAction.Ranged: "Sends ranged data based on the range output mode"
}

_gate_action_name = {
    GateAction.NoAction: "No Action",
    GateAction.Macro: "Macro",
    GateAction.SendKey: "Send Key",
    GateAction.Ranged: "Ranged"
}

_gate_condition_to_name = {
    GateCondition.OnRangeEnter: "range_enter",
    GateCondition.OnRangeEnterRepeat: "range_enter_repeat",
    GateCondition.OnRangeExit: "range_exit",
    GateCondition.OnEnterMin: "range_enter_low",
    GateCondition.OnEnterMax: "range_enter_high",
    GateCondition.OnExitMin: "range_exit_low",
    GateCondition.OnExitMax: "range_exit_high",
    GateCondition.OnSteps: "steps"
}

_gate_condition_from_name = {
    "range_enter": GateCondition.OnRangeEnter ,
    "range_enter_repeat": GateCondition.OnRangeEnterRepeat ,
    "range_exit": GateCondition.OnRangeExit ,
    "range_enter_low": GateCondition.OnEnterMin,
    "range_enter_high": GateCondition.OnEnterMax,
    "range_exit_low": GateCondition.OnExitMin,
    "range_exit_high": GateCondition.OnExitMax ,
    "steps": GateCondition.OnSteps 
}

_gate_condition_description = {
    GateCondition.OnRangeEnter: "Triggers once when the input value is within the gate",
    GateCondition.OnRangeEnterRepeat: "Triggers whenever the value changes while the input value is within the gate",
    GateCondition.OnRangeExit: "Triggers when the input leaves the gate",
    GateCondition.OnEnterMin: "Triggers when the input enters the gate from below",
    GateCondition.OnEnterMax: "Triggers when the input enters the gate from above",
    GateCondition.OnExitMin: "Triggers when the input leaves the gate lower range",
    GateCondition.OnExitMax: "Triggers when the input leaves the gate upper range",
    GateCondition.OnSteps: "Triggers when crossing equally divided steps"
}

_gate_condition_name = {
    GateCondition.OnRangeEnter: "Range Enter",
    GateCondition.OnRangeEnterRepeat: "Range Enter (repeat)",
    GateCondition.OnRangeExit: "Range Exit",
    GateCondition.OnEnterMin: "Enter Low",
    GateCondition.OnEnterMax: "Enter High",
    GateCondition.OnExitMin: "Exit Low",
    GateCondition.OnExitMax: "Exit High",
    GateCondition.OnSteps: "Steps",
}

_gate_range_to_name = {
    GateRangeOutputMode.Normal: "normal",
    GateRangeOutputMode.Fixed: "fixed",
    GateRangeOutputMode.Ranged: "ranged",
    GateRangeOutputMode.Nothing: "filter",
}

_gate_range_from_name = {
    "normal": GateRangeOutputMode.Normal ,
    "fixed": GateRangeOutputMode.Fixed,
    "ranged": GateRangeOutputMode.Ranged,
    "filter": GateRangeOutputMode.Nothing,
}

_gate_range_description = {
    GateRangeOutputMode.Normal: "Sends the input value",
    GateRangeOutputMode.Fixed: "Sends a fixed value",
    GateRangeOutputMode.Ranged: "Sends a ranged value based on the input position inside the gate",
    GateRangeOutputMode.Nothing: "Sends no data (ignore)",
}

_gate_range_name = {
    GateRangeOutputMode.Normal: "Normal",
    GateRangeOutputMode.Fixed: "Fixed Value",
    GateRangeOutputMode.Ranged: "New Range",
    GateRangeOutputMode.Nothing: "Filter Out",
}

class GateData():
    ''' holds gated information for an axis 
    
        this object knows how to load and save itself to XML
    
    
    '''
    def __init__(self,
                 min = -1.0,
                 max = 1.0,
                 action = GateAction.NoAction,
                 condition = GateCondition.OnRangeEnter,
                 mode = GateRangeOutputMode.Normal,
                 range_min = -1.0,
                 range_max = 1.0):
        self.min = min # gate min range
        self.max = max # gate max range
        self.action = action
        self.condition = condition
        self.output_mode = mode
        self.range_min = range_min
        self.range_max = range_max
        self.macro : gremlin.macro.Macro = None  # macro steps
        self.id = gremlin.util.get_guid()
        self.keys = [] # output keys (single or macro)
        self.key_mode : KeyboardOutputMode = KeyboardOutputMode.Both
        self.delay = 250 # delay in milliseconds for key presses
        self.sequence = [] # macro sequence
        self.exclusive = False # macro exclusive
        self.repeat = None # macro repeat
        self.force_remote = False # macro force remote


    def to_xml(self):
        ''' export this configuration to XML '''
        node = etree.Element("gate")
        node.set("action", _gate_action_to_name[self.action])
        node.set("condition", _gate_condition_to_name[self.condition])
        node.set("mode", _gate_range_to_name[self.output_mode])
        if self.action == GateAction.Ranged:
            node.extend(self.range_to_xml(self.min, self.max,"input_range"))
            node.extend(self.range_to_xml(self.range_min, self.range_max,"output_range"))

        elif self.action == GateAction.Macro:
            child = self.macro_to_xml()
            node.extend(child)
        elif self.action == GateAction.SendKey:
            child = self.keyboard_to_xml()
            node.extend(child)

        return node

    def from_xml(self, node):
        if not node.tag == "gate":
            syslog.error(f"GateData: Invalid node type {node.tag}")
            return
        self.action = _gate_action_from_name(node.get("action"))
        self.condition = _gate_condition_from_name(node.get("condition"))
        self.output_mode = _gate_range_from_name(node.get("mode"))

        if self.action == GateAction.Macro:
            # read macro node
            child = get_xml_child(node, "macro")
            if child is not None:
                self.macro_from_xml(child)
        elif self.action == GateAction.SendKey:
            child = get_xml_child(node, "key")
            if child is not None:
                self.keyboard_from_xml_from_xml(child)
        elif self.action == GateAction.Ranged:
            child = get_xml_child("input_range")
            self.min, self.max = self.range_from_xml(child)
            child = get_xml_child("output_range")
            self.range_min, self.range_max = self.range_from_xml(child)

            

        
            
    def range_to_xml(self, min, max, tag = "range"):
        node = etree.Element(tag)
        node.set("min", f"{min:0.5f}")
        node.set("max", f"{max:0.5f}")
        return node

    def range_from_xml(self, node) -> tuple:
        ''' reads min/max range node - return (min, max)'''
        min = safe_read(node, "min", float, -1.0)
        max = safe_read(node, "max", float, 1.0)
        return (min, max)

        

    def keyboard_to_xml(self):
        ''' saves data to XML '''
        node = etree.Element("key")
        if self.key_mode == KeyboardOutputMode.Both:
            mode = "both"
        elif self.key_mode == KeyboardOutputMode.Press:
            mode = "make"
        elif self.key_mode == KeyboardOutputMode.Release:
            mode = "break"
        elif self.key_mode == KeyboardOutputMode.Hold:
            mode = "hold"

        node.set("mode",safe_format(mode, str) )

        node.set("delay",safe_format(self.delay, int))
        
        for code in self.keys:
            if isinstance(code, tuple): # key ID (scan_code, extended)
                scan_code = code[0]
                is_extended = code[1]
                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
                virtual_code = key.virtual_code
            elif isinstance(code, int): # single virtual code
                key = gremlin.keyboard.KeyMap.find_virtual(code)
                scan_code = key.scan_code
                is_extended = key.is_extended
                virtual_code = code
            elif isinstance(code, gremlin.keyboard.Key):
                # key
                key = code
                scan_code = key.scan_code
                is_extended = key.is_extended
                virtual_code = key.virtual_code
            else:
                assert True, f"Don't know how to handle: {code}"
            
            key_node = etree.Element("key")
            key_node.set("virtual-code", str(virtual_code))
            key_node.set("scan-code", str(scan_code))
            key_node.set("extended", str(is_extended))
            # useful for xml readability purposes = what scan code is this
            key_node.set("description", key.name)
            node.append(key_node)
        return node
    
    def keyboard_from_xml(self, node):
        keys = []
        if "mode" in node.attrib:
            mode = safe_read(node, "mode", str)
            if mode == "make":
                self.key_mode = KeyboardOutputMode.Press
            elif mode == "break":
                self.key_mode = KeyboardOutputMode.Release
            elif mode == "both":
                self.key_mode = KeyboardOutputMode.Both
            elif mode == "hold":
                self.key_mode = KeyboardOutputMode.Hold
            
        if "delay" in node.attrib:
            self.delay = safe_read(node, "delay", int) # delay in milliseconds


        for child in node.findall("key"):
            virtual_code = safe_read(child, "virtual-code", int, 0)
            if virtual_code > 0:
                key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)         
            else:
                scan_code = safe_read(child, "scan-code", int, 0)
                is_extended = safe_read(child, "extended", bool, False)
                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
            if key:
                keys.append(key)

        # sort the keys for display purposes
        self.keys = gremlin.keyboard.sort_keys(keys)

    
    def macro_to_xml(self, tag = "macro"):
        node = etree.Element(tag)
        properties = etree.Element("properties")
        if self.exclusive:
            prop_node = etree.Element("exclusive")
            properties.append(prop_node)
        if self.repeat:
            properties.append(self.repeat.to_xml())
        if self.force_remote:
            prop_node = etree.Element("force_remote")
            properties.append(prop_node)


        node.append(properties)

        action_list = etree.Element("actions")
        for entry in self.sequence:
            if isinstance(entry, gremlin.macro.JoystickAction):
                joy_node = etree.Element("joystick")
                joy_node.set("device-guid", write_guid(entry.device_guid))
                joy_node.set(
                    "input-type",
                    InputType.to_string(entry.input_type)
                )
                joy_node.set("input-id", str(entry.input_id))
                joy_node.set("value", self._joy_value_to_str(entry))
                action_list.append(joy_node)
            elif isinstance(entry, gremlin.macro.KeyAction):
                action_node = etree.Element("key")
                action_node.set("scan-code", str(entry.key.scan_code))
                action_node.set("extended", str(entry.key.is_extended))
                action_node.set("press", str(entry.is_pressed))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                action_node = etree.Element("mouse")
                action_node.set("button", str(entry.button.value))
                action_node.set("press", str(entry.is_pressed))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.MouseMotionAction):
                action_node = etree.Element("mouse-motion")
                action_node.set("dx", str(entry.dx))
                action_node.set("dy", str(entry.dy))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.PauseAction):
                pause_node = etree.Element("pause")
                pause_node.set("duration", str(entry.duration))
                pause_node.set("duration_max", str(entry.duration_max))
                pause_node.set("is_random", str(entry.is_random))
                action_list.append(pause_node)
            elif isinstance(entry, gremlin.macro.VJoyMacroAction):
                vjoy_node = etree.Element("vjoy")
                vjoy_node.set("vjoy-id", str(entry.vjoy_id))
                vjoy_node.set(
                    "input-type",
                    InputType.to_string(entry.input_type)
                )
                vjoy_node.set("input-id", str(entry.input_id))
                vjoy_node.set("value", self._joy_value_to_str(entry))
                if entry.input_type == InputType.JoystickAxis:
                    vjoy_node.set("axis-type", safe_format(entry.axis_type, str))
                action_list.append(vjoy_node)
            elif isinstance(entry, gremlin.macro.RemoteControlAction):
                action_node = etree.Element("remote_control")
                action_node.set("command",entry.command.name)
                action_list.append(action_node)

        node.append(action_list)
        return node

    def macro_from_xml(self, node):
        ''' reads macro data from xml '''
        self.sequence = []
        self.exclusive = False
        self.repeat = None
        self.force_remote = False

        # Read properties
        for child in node.find("properties"):
            if child.tag == "exclusive":
                self.exclusive = True
            elif child.tag == "force_remote":
                self.force_remote = True
            elif child.tag == "repeat":
                repeat_type = child.get("type")
                if repeat_type == "count":
                    self.repeat = gremlin.macro.CountRepeat()
                elif repeat_type == "toggle":
                    self.repeat = gremlin.macro.ToggleRepeat()
                elif repeat_type == "hold":
                    self.repeat = gremlin.macro.HoldRepeat()
                else:
                    logging.getLogger("system").warning(
                        f"Invalid macro repeat type: {repeat_type}"
                    )

                if self.repeat:
                    self.repeat.from_xml(child)

        # Read macro actions
        for child in node.find("actions"):
            if child.tag == "joystick":
                joy_action = gremlin.macro.JoystickAction(
                    parse_guid(child.get("device-guid")),
                    InputType.to_enum(
                        safe_read(child, "input-type")
                    ),
                    safe_read(child, "input-id", int),
                    safe_read(child, "value"),
                )
                self._str_to_joy_value(joy_action)
                self.sequence.append(joy_action)
            elif child.tag == "key":
                key_action = gremlin.macro.KeyAction(
                    key_from_code(
                        int(child.get("scan-code")),
                        gremlin.profile.parse_bool(child.get("extended"))
                    ),
                    gremlin.profile.parse_bool(child.get("press"))
                )
                self.sequence.append(key_action)
            elif child.tag == "mouse":
                mouse_action = gremlin.macro.MouseButtonAction(
                    gremlin.types.MouseButton(safe_read(child, "button", int)),
                    gremlin.profile.parse_bool(child.get("press"))
                )
                self.sequence.append(mouse_action)
            elif child.tag == "mouse-motion":
                mouse_motion = gremlin.macro.MouseMotionAction(
                    safe_read(child, "dx", int, 0),
                    safe_read(child, "dy", int, 0)
                )
                self.sequence.append(mouse_motion)
            elif child.tag == "pause":
                self.sequence.append (
                    gremlin.macro.PauseAction(
                                        float(child.get("duration")),
                                        safe_read(child, "duration_max", float, 0),
                                        gremlin.profile.parse_bool(child.get("is_random"))
                                        )
                )
            elif child.tag == "vjoy":
                vjoy_action = gremlin.macro.VJoyMacroAction(
                    safe_read(child, "vjoy-id", int),
                    InputType.to_enum(
                        safe_read(child, "input-type")
                    ),
                    safe_read(child, "input-id", int),
                    safe_read(child, "value"),
                    safe_read(child, "axis-type", str, "absolute")
                )
                self._str_to_joy_value(vjoy_action)
                self.sequence.append(vjoy_action)

            elif child.tag == "remote_control":
                remote_control_action = gremlin.macro.RemoteControlAction()
                cmd = safe_read(child, "command", str, "VJoyEnableLocalOnly")
                remote_control_action.command = VjoyAction.from_string(cmd)
                self.sequence.append(remote_control_action)

        


class GatedOutput():
    ''' handles gated joystick output based on a linear input '''

    def __init__(self, gate : GateData,  action_data):
        self._data = action_data
        self._gate = gate

    @property
    def gate(self) -> GateAction:
        return self._gate
    @gate.setter
    def gate(self, value):
        self._gate = value


    def gate_execute(self, gate : GateData, value : float):
        ''' executes a gated output based on a value input -1 to +1 
        
        :param: gate - the gate configuration 
        :param: value - the input value to gate, expected values -1 to +1 
        
        '''

        # compute the value of the gate based on the intput axis 
        if value < gate.min or value > gate.max:
            return # value is not in the gate range
        if gate.action == GateAction.NotAction:
            # pass through
            return value
        elif gate.action == GateAction.Macro:
            # execute the macro
            if gate.macro:
                manager = gremlin.macro.MacroManager()
                manager.queue_macro(self.macro)
        elif gate.action == GateAction.SendMin:
            # send min value
            output_value = self.scale_output(gate.min)
            self.block.execute(output_value)
        elif gate.action == GateAction.SendMax:
            # send max value
            output_value = self.scale_output(gate.max)
            self.block.execute(output_value)
        elif gate.action == GateAction.SendKey:
            # sends a key
            if self._data.keys is not None:
                pass
    

class GateWidget(QtWidgets.QWidget):
    ''' a widget that represents a single gate on an axis input and what should happen in that gate
    
        a gate has a min/max value, an optional output range and can trigger different actions based on conditions applied to the input axis value 
    
    '''

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz
    duplicate_requested = QtCore.Signal(object) # fired when the duplicate button is clicked - passes the GateData to duplicate

    def __init__(self, action_data, gate_data, parent = None):

        import gremlin.event_handler

        super().__init__(parent)
        self.gate_data : GateData = gate_data
        self.action_data = action_data


        # axis input repeater
        self._input_axis_widget = ui_common.AxisStateWidget(show_label = False, orientation=QtCore.Qt.Orientation.Horizontal, show_percentage=False, show_value=True)

        self.sb_min_widget = ui_common.DynamicDoubleSpinBox()
        self.sb_min_widget.setMinimum(-1.0)
        self.sb_min_widget.setMaximum(1.0)
        self.sb_min_widget.setDecimals(3)
        self.sb_min_widget.valueChanged.connect(self._range_min_changed_cb)
        self.sb_max_widget = ui_common.DynamicDoubleSpinBox()
        self.sb_max_widget.setMinimum(-1.0)
        self.sb_max_widget.setMaximum(1.0)        
        self.sb_max_widget.setDecimals(3)
        self.sb_max_widget.valueChanged.connect(self._range_max_changed_cb)

        self.sb_range_min_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_range_min_widget.setMinimum(-1.0)
        self.sb_range_min_widget.setMaximum(1.0)
        self.sb_range_min_widget.setDecimals(3)
        self.sb_range_min_widget.valueChanged.connect(self._range_min_changed_cb)
        self.sb_range_max_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_range_max_widget.setMinimum(-1.0)
        self.sb_range_max_widget.setMaximum(1.0)        
        self.sb_range_max_widget.setDecimals(3)
        self.sb_range_max_widget.valueChanged.connect(self._range_max_changed_cb)

        grab_icon = load_icon("mdi.record-rec",qta_color = "red")
        self.sb_min_grab_widget = ui_common.QDataPushButton()
        self.sb_min_grab_widget.data = self.sb_min_widget # control to update
        self.sb_min_grab_widget.setIcon(grab_icon)
        self.sb_min_grab_widget.setMaximumWidth(20)
        self.sb_min_grab_widget.clicked.connect(self._grab_cb)

        self.sb_max_grab_widget = ui_common.QDataPushButton()
        self.sb_max_grab_widget.data = self.sb_max_widget # control to update
        self.sb_max_grab_widget.setIcon(grab_icon)
        self.sb_max_grab_widget.setMaximumWidth(20)
        self.sb_max_grab_widget.clicked.connect(self._grab_cb)

        self.sb_range_min_grab_widget = ui_common.QDataPushButton()
        self.sb_range_min_grab_widget.data = self.sb_range_min_widget
        self.sb_range_min_grab_widget.setIcon(grab_icon)
        self.sb_range_min_grab_widget.setMaximumWidth(20)
        self.sb_range_min_grab_widget.clicked.connect(self._grab_cb)

        self.sb_range_max_grab_widget = ui_common.QDataPushButton()
        self.sb_range_max_grab_widget.data = self.sb_range_max_widget
        self.sb_range_max_grab_widget.setIcon(grab_icon)
        self.sb_range_max_grab_widget.setMaximumWidth(20)
        self.sb_range_max_grab_widget.clicked.connect(self._grab_cb)

        # action drop down
        self.action_selector_widget = QtWidgets.QComboBox()
        for action in GateAction:
            self.action_selector_widget.addItem(_gate_action_name[action], action)
        self.action_selector_widget.currentIndexChanged.connect(self._action_changed_cb)

        # condition drop down
        self.condition_selector_widget = QtWidgets.QComboBox()
        for condition in GateCondition:
            self.condition_selector_widget.addItem(_gate_condition_name[condition], condition)
        self.condition_selector_widget.currentIndexChanged.connect(self._condition_changed_cb)

        # range mode drop down
        self.range_mode_selector_widget = QtWidgets.QComboBox()
        for mode in GateRangeOutputMode:
            self.range_mode_selector_widget.addItem(_gate_range_name[mode], mode)
        self.range_mode_selector_widget.currentIndexChanged.connect(self._range_mode_changed_cb)


        self.container_selector_widget = QtWidgets.QWidget()
        self.container_selector_layout = QtWidgets.QHBoxLayout(self.container_selector_widget)

        self.container_selector_layout.addWidget(self.action_selector_widget)
        self.container_selector_layout.addWidget(self.condition_selector_widget)
        self.container_selector_layout.addWidget(self.range_mode_selector_widget)
        self.container_selector_layout.addStretch()

     
        clear_button = ui_common.QDataPushButton()
        clear_button.setIcon(load_icon("mdi.delete"))
        clear_button.setMaximumWidth(20)
        clear_button.data = self.gate_data
        clear_button.clicked.connect(self._delete_cb)
        clear_button.setToolTip("Removes this entry")
        


        duplicate_button = ui_common.QDataPushButton()
        duplicate_button.setIcon(load_icon("mdi.content-duplicate"))
        duplicate_button.setMaximumWidth(20)
        duplicate_button.data = self.gate_data
        duplicate_button.clicked.connect(self._duplicate_cb)
        duplicate_button.setToolTip("Duplicates this entry")
       
        self.container_range_widget = QtWidgets.QWidget()
        self.container_range_layout = QtWidgets.QGridLayout(self.container_range_widget)
        
        self.container_range_layout.addWidget(QtWidgets.QLabel("Gate Min:"), 0,0)
        self.container_range_layout.addWidget(self.sb_min_widget,1,0)
        self.container_range_layout.addWidget(self.sb_min_grab_widget,1,1
                                              )
        self.container_range_layout.addWidget(QtWidgets.QLabel("Gate Max:"),0,2)
        self.container_range_layout.addWidget(self.sb_max_widget, 1,2)
        self.container_range_layout.addWidget(self.sb_max_grab_widget,1,3)

        self.container_range_layout.addWidget(QtWidgets.QLabel("Output Min:"),0,4)
        self.container_range_layout.addWidget(self.sb_range_min_widget,1,4)
        self.container_range_layout.addWidget(self.sb_range_min_grab_widget,1,5)

        self.container_range_layout.addWidget(QtWidgets.QLabel("Output Max:"),0,6)
        self.container_range_layout.addWidget(self.sb_range_max_widget,1,6)
        self.container_range_layout.addWidget(self.sb_range_min_grab_widget,1,8)

        self.container_range_layout.addWidget(clear_button, 0, 7)
        self.container_range_layout.addWidget(duplicate_button, 1, 7)


        self.container_range_layout.addWidget(QtWidgets.QLabel(" "),0,7)
        self.container_range_layout.setColumnStretch(7,3)
        

        # macro container
        self._macro_widget = None
        self._create_macro_ui()

        # key container
        self._create_keyboard_ui()

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(self.container_selector_widget)
        self.main_layout.addWidget(self.container_macro_widget)
        self.main_layout.addWidget(self.container_key_widget)
        self.main_layout.addWidget(self.container_range_widget)


        # hook the joystick input for axis input repeater
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)

        # update visible container for the current mode
        self._update_ui()


    @QtCore.Slot()
    def _grab_cb(self):
        ''' grab the min value from the axis position '''
        widget = self.sender().data  # the button's data field contains the widget to update
        value = self._input_axis_widget.value()
        widget.setValue(value)

    def _delete_cb(self):
        ''' delete requested '''
        self.delete_requested.emit(self.gate_data)

    def _duplicate_cb(self):
        ''' duplicate requested '''
        self.duplicate_requested.emit(self.gate_data)
            
    @property
    def is_running(self):
        ''' true if the profile is running '''
        return gremlin.shared_state.is_running
    
    @QtCore.Slot(object)
    def _joystick_event_cb(self, event):
        if self.is_running or not event.is_axis:
            # ignore if not an axis event and if the profile is running, or input for a different device
            return
        
        if self.action_data.hardware_device_guid != event.device_guid:
            # print (f"device mis-match: {str(self._data.hardware_device_guid)}  {str(event.device_guid)}")
            return
            
        if self.action_data.hardware_input_id != event.identifier:
            # print (f"input mismatch: {self._data.hardware_input_id} {event.identifier}")
            return
        

        raw_value = event.raw_value
        input_value = gremlin.util.scale_to_range(raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1) + 0 # removes negative zero in python
        self._input_axis_widget.setValue(input_value)


    def _create_macro_ui(self):
        ''' creates the macro ui '''

        self.container_macro_widget = QtWidgets.QWidget()
        self.container_macro_layout = QtWidgets.QHBoxLayout(self.container_macro_widget)
        # delay load macro widget because it is VERY slow to load
        self._macro_widget = None
    


    def _create_keyboard_ui(self):
        ''' creates the keyboard UI '''
        self.container_key_widget = QtWidgets.QWidget()
        self.container_key_layout = QtWidgets.QHBoxLayout(self.container_key_widget)

        self.key_combination = QtWidgets.QLabel()

        self.action_widget = QtWidgets.QWidget()
        self.action_layout = QtWidgets.QHBoxLayout()
        self.action_widget.setLayout(self.action_layout)

        self.record_button = QtWidgets.QPushButton("Listen")
        self.record_button.clicked.connect(self._record_keys_cb)

        self._options_widget = QtWidgets.QWidget()
        self._options_layout = QtWidgets.QHBoxLayout()
        self._options_widget.setLayout(self._options_layout)


        self.rb_press = QtWidgets.QRadioButton("Press")
        self.rb_release = QtWidgets.QRadioButton("Release")
        self.rb_both = QtWidgets.QRadioButton("Pulse")
        self.rb_hold = QtWidgets.QRadioButton("Hold")

        self.delay_container_widget = QtWidgets.QWidget()
        self.delay_container_layout = QtWidgets.QHBoxLayout()
        self.delay_container_widget.setLayout(self.delay_container_layout)

        delay_label = QtWidgets.QLabel("Delay(ms)")
        self.delay_box = QtWidgets.QSpinBox()
        self.delay_box.setRange(0, 20000)

        quarter_sec_button = QtWidgets.QPushButton("1/4s")
        half_sec_button = QtWidgets.QPushButton("1/2s")
        sec_button = QtWidgets.QPushButton("1s")

        quarter_sec_button.clicked.connect(self._quarter_sec_delay)
        half_sec_button.clicked.connect(self._half_sec_delay)
        sec_button.clicked.connect(self._sec_delay)

        self.delay_box.setValue(self.gate_data.delay)

        if self.gate_data.key_mode == KeyboardOutputMode.Press:
            self.rb_press.setChecked(True)
        elif self.gate_data.key_mode == KeyboardOutputMode.Release:
            self.rb_release.setChecked(True)
        elif self.gate_data.key_mode == KeyboardOutputMode.Hold:
            self.rb_hold.setChecked(True)
        elif self.gate_data.key_mode == KeyboardOutputMode.Both:            
            self.rb_both.setChecked(True)
            

        self.rb_press.clicked.connect(self._keyboard_mode_changed)
        self.rb_release.clicked.connect(self._keyboard_mode_changed)
        self.rb_both.clicked.connect(self._keyboard_mode_changed)
        self.rb_hold.clicked.connect(self._keyboard_mode_changed)

        self.delay_box.valueChanged.connect(self._delay_changed)

        self._options_layout.addWidget(QtWidgets.QLabel("Mode:"))
        self._options_layout.addWidget(self.rb_hold)
        self._options_layout.addWidget(self.rb_both)
        self._options_layout.addWidget(self.rb_press)
        self._options_layout.addWidget(self.rb_release)
        
        self._options_layout.addStretch(1)


        self.delay_container_layout.addWidget(delay_label)
        self.delay_container_layout.addWidget(self.delay_box)
        self.delay_container_layout.addWidget(quarter_sec_button)
        self.delay_container_layout.addWidget(half_sec_button)
        self.delay_container_layout.addWidget(sec_button)
        self.delay_container_layout.addStretch(1)

        self.show_keyboard_widget = QtWidgets.QPushButton("Select Keys")
        self.show_keyboard_widget.setIcon(load_icon("mdi.keyboard-settings-outline"))
        self.show_keyboard_widget.clicked.connect(self._select_keys_cb)

        self.action_layout.addWidget(self.record_button)
        self.action_layout.addWidget(self.show_keyboard_widget)
        self.action_layout.addStretch(1)


        self.container_key_layout.addWidget(self.key_combination)
        self.container_key_layout.addWidget(self.action_widget)
        self.container_key_layout.addWidget(self._options_widget)
        self.container_key_layout.addWidget(self.delay_container_widget)

    def _select_keys_cb(self):
        ''' display the keyboard input dialog '''
        import gremlin.shared_state
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        gremlin.shared_state.push_suspend_ui_keyinput()
        self._keyboard_dialog = InputKeyboardDialog(sequence = self.gate_data.keys, parent = self)
        self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._keyboard_dialog_closed_cb)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.showNormal()
        
    def _keyboard_dialog_closed_cb(self):
        import gremlin.shared_state
        gremlin.shared_state.pop_suspend_ui_keyinput()
        
    def _keyboard_dialog_ok_cb(self):
        ''' callled when the virtual dialog completes '''

        # grab the new data
        self.gate_data.keys = gremlin.keyboard.sort_keys(self._keyboard_dialog.keys)
        self.action_modified.emit()
        gremlin.shared_state.pop_suspend_ui_keyinput()        
        

    QtCore.Slot()
    def _range_min_changed_cb(self):
        self.gate_data.min = self.sb_axis_min.value()

    QtCore.Slot()
    def _range_max_changed_cb(self):
        self.gate_data.min = self.sb_axis_max.value()

    QtCore.Slot(int)
    def _action_changed_cb(self):
        self.gate_data.action = self.action_selector_widget.currentData()
        self._update_ui()

    QtCore.Slot(int)
    def _condition_changed_cb(self):
        self.gate_data.conditon = self.condition_selector_widget.currentData()
        self._update_ui()

    QtCore.Slot(int)
    def _range_mode_changed_cb(self):
        self.gate_data.output_mode = self.range_mode_selector_widget.currentData()
        self._update_ui()


    def _update_ui(self):
        macro_visible = False
        range_visible = False  
        key_visible = False
        if self.gate_data.action == GateAction.NoAction:
            range_visible = True
        elif self.gate_data.action == GateAction.Macro:
            # delay load macro widget 
            if self._macro_widget is None:
                self._macro_widget = MacroWidget(data = self.gate_data)
                self.container_macro_layout.addWidget(self._macro_widget)

            macro_visible = True
        elif self.gate_data.action == GateAction.Ranged:
            range_visible = True
        elif self.gate_data.action == GateAction.SendKey:
            key_visible = True

        self.container_macro_widget.setVisible(macro_visible)
        self.container_range_widget.setVisible(range_visible)
        self.container_key_widget.setVisible(key_visible)

        
    def _keyboard_mode_changed(self):
        delay_enabled = False
        if self.rb_press.isChecked():
            mode = KeyboardOutputMode.Press
        elif self.rb_release.isChecked():
            mode = KeyboardOutputMode.Release
        elif self.rb_hold.isChecked():
            mode = KeyboardOutputMode.Hold
        elif self.rb_both.isChecked():
            mode = KeyboardOutputMode.Both
            delay_enabled = True
        else:
            # default
            mode = KeyboardOutputMode.Hold 
        self.gate_data.key_mode = mode
        self.delay_container_widget.setEnabled(delay_enabled)

    def _delay_changed(self):
        self.gate_data.delay = self.delay_box.value()
        
    def _quarter_sec_delay(self):
        self.delay_box.setValue(250)


    def _half_sec_delay(self):
        self.delay_box.setValue(500)

    def _sec_delay(self):
        self.delay_box.setValue(1000)

    def _record_keys_cb(self):
        """Prompts the user to press the desired key combination."""
        button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=True
        )

        button_press_dialog.item_selected.connect(self._update_keys)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        button_press_dialog.show()

class GatedAxisWidget(QtWidgets.QWidget):
    ''' a scrolling widget container that allows to define one or more gates on an axis input
    
        contains: GateWidget 
    
    '''

    def __init__(self, action_data, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.action_data = action_data

        self._gate_widgets = [] # holds the gate widgets in this map

        # toolbar for gates
        self.container_bar_widget = QtWidgets.QWidget()
        self.container_bar_layout = QtWidgets.QHBoxLayout(self.container_bar_widget)
        self.container_bar_layout.setContentsMargins(0,0,0,0)

        # add gate button
        self.add_gate_button = QtWidgets.QPushButton("Add Gate")
        self.add_gate_button.setIcon(load_icon("fa.plus"))
        self.add_gate_button.clicked.connect(self._add_gate_cb)
        self.container_bar_layout.addWidget(self.add_gate_button)
        self.container_bar_layout.addStretch()

        # start scrolling container widget definition

        self.container_map_widget = QtWidgets.QWidget()
        self.container_map_widget.setMinimumHeight(200)
        self.container_map_layout = QtWidgets.QVBoxLayout(self.container_map_widget)
        self.container_map_layout.setContentsMargins(0,0,0,0)

        # add aircraft map items
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        self.scroll_area.setMinimumWidth(300)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.map_widget = QtWidgets.QWidget()
        self.map_layout = QtWidgets.QGridLayout(self.map_widget)
        self.map_layout.setContentsMargins(0,0,0,0)
        

        self.scroll_layout.addWidget(self.map_widget)
        self.scroll_layout.setContentsMargins(6,0,6,0)
        self.scroll_layout.addStretch()
        self.container_map_layout.addWidget(self.scroll_area)

        # end scrolling container widget definition
        self.main_layout.addWidget(self.container_bar_widget)
        self.main_layout.addWidget(self.container_map_widget)

        self._populate_ui()

    @property
    def gates(self):
        return self.action_data.gates

    @QtCore.Slot()
    def _add_gate_cb(self):
        
        self.gates.append(GateData())
        self._populate_ui()

    

    @QtCore.Slot(GateData)
    def _remove_gate(self, data):
        if not data in self.gates:
            return
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText("This will delete this entry.\nAre you sure?")
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_confirmed_cb(data)

    def _delete_confirmed_cb(self, data):
        self.gates.remove(data)
        self._populate_ui()


    @QtCore.Slot(GateData)
    def _duplicate_gate(self, data):
        import copy
        new_data = copy.deepcopy(data)
        new_data.id = gremlin.util.get_guid()
        index = self.gates.index(data)
        self.gates.insert(index, new_data)
        self._populate_ui()

    def _populate_ui(self):
        ''' updates the container map '''

        # clear the widgets
        ui_common.clear_layout(self.map_layout)
        self._gate_widgets = [] # holds all the gate widgets

        if not self.gates:
            # no item
            missing = QtWidgets.QLabel("Please add a gate definition.")
            missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
            self.map_layout.addWidget(missing)
            return


        for gate_data in self.gates:
            widget = GateWidget(action_data = self.action_data, gate_data=gate_data)
            widget.delete_requested.connect(self._remove_gate)
            widget.duplicate_requested.connect(self._duplicate_gate)
            self._gate_widgets.append(widget)
            self.map_layout.addWidget(widget)

    

        
