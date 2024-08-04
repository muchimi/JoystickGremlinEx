

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
from xml.etree import ElementTree
from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.macro
from gremlin.ui import ui_common
import gremlin.ui.input_item
import gremlin.util
from gremlin.util import *
from gremlin.types import *

from enum import Enum, auto
from gremlin.macro_handler import *
import gremlin.util



class GateAction(Enum):
    ''' action when the axis is in the gate range '''
    NoAction = auto() # passthru (no change)
    Ranged = auto() # send a ranged value determined by the Ranged output mode
    Gate = auto() # split the input into steps and fire an event at gate crossings

    @staticmethod
    def to_description(action):
        return _gate_action_description[action]
    
    @staticmethod
    def to_string(action):
        return _gate_action_to_name[action]
    
    @staticmethod
    def from_string(value):
        return _gate_action_from_name[value]
    
    @staticmethod
    def to_display_name(action):
        return _gate_action_display_name[action]

class GateCondition(Enum):
    ''' gate action trigger conditions'''
    # RANGE specific conditions (between gates)
    InRange = auto() # triggers when the value is in range
    OutsideRange = auto() # triggers when the value is outside the range
    # GATE specific conditions (when crossing a gate)
    OnCross = auto() # value crosses a gate boundary in any direction
    OnCrossIncrease = auto() # value crosses the gate and increased in value
    OnCrossDecrease = auto() # value crosses the gate and decreased in value

    @staticmethod
    def to_description(condition):
        return _gate_condition_description[condition]
    
    @staticmethod
    def to_string(condition):
        return _gate_condition_to_name[condition]
    
    @staticmethod
    def from_string(value):
        return _gate_condition_from_name[value]
    
    @staticmethod
    def to_display_name(condition):
        return _gate_condition_to_display_name[condition]
    

class GateRangeOutputMode(Enum):
    ''' controls for ranged outputs what range is output given the gate range '''
    Normal = auto() # output range is the same as the input value
    Ranged = auto() # scales the output to a new range based on the min/max specified for the gate
    Fixed = auto() # output a fixed value
    Nothing = auto() # sends no data


class TriggerMode(Enum):
    ''' values returned in a Trigger data object when a trigger is being sent '''
    Value = auto() # value output - passthrough - use the value in the value field
    RangedValue = auto() # value output - scaled 
    ValueInRange = auto() # value is in range of the gate
    ValueOutOfRange = auto() # value is out of range of the gate
    GateCrossed = auto() # gate crossed - the gate_index contains the gate index crossed, the gate_value member contains the gate value that was crossed
    FixedValue = auto() # fixed value output

_decimals = 5
 
_gate_action_from_name = {
    "no_action" : GateAction.NoAction,
    "ranged" : GateAction.Ranged,
    "gate" : GateAction.Gate,
}

_gate_action_to_name = {
    GateAction.NoAction: "no_action",
    GateAction.Ranged: "ranged",
    GateAction.Gate: "gate"
}

_gate_action_description = {
    GateAction.NoAction: "Do Nothing",
    GateAction.Ranged: "Sends ranged data based on the range output mode",
    GateAction.Gate: "Triggers when input crosses a gate",
}


_gate_action_display_name = {
    GateAction.NoAction: "No Action",
    GateAction.Ranged: "Ranged",
    GateAction.Gate: "Steps",
}

_gate_condition_to_name = {
    GateCondition.InRange: "in_range",
    GateCondition.OutsideRange: "outside_range",
    GateCondition.OnCross: "cross",
    GateCondition.OnCrossIncrease: "cross_inc",
    GateCondition.OnCrossDecrease: "cross_dec"
}


_gate_condition_to_display_name = {
    GateCondition.InRange: "In Range",
    GateCondition.OutsideRange: "Outside of Range",
    GateCondition.OnCross: "cross",
    GateCondition.OnCrossIncrease: "cross_inc",
    GateCondition.OnCrossDecrease: "cross_dec"
}

_gate_condition_from_name = {
    "in_range": GateCondition.InRange,
    "outside_range": GateCondition.OutsideRange,
    "cross": GateCondition.OnCross,
    "cross_inc": GateCondition.OnCrossIncrease,
    "cross_dec": GateCondition.OnCrossDecrease
}

_gate_condition_description = {
    GateCondition.InRange: "Triggers whenever the input value is in range",
    GateCondition.OutsideRange: "Triggers whenever the input value is outside the range",
    GateCondition.OnCross: "Triggers when crossing the gate"
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

class GateData(QtCore.QObject):
    ''' holds gated information for an axis 
    
        this object knows how to load and save itself to XML
    '''

    class GateInfo():
        def __init__(self, index, value = None, item_data = None, condition = GateCondition.OnCross):
            self.id = None
            self.index = index
            self.value = value
            self.condition = condition
            self.item_data = item_data
            self.used = True

        def __lt__(self, other):
            return self.value < other.value

    class RangeInfo():
        def __init__(self, index, min_gate, max_gate, item_data = None, condition = GateCondition.InRange, mode = GateRangeOutputMode.Normal):
            self.id = None
            self.index = index
            self.condition = condition
            self.min_gate : GateData.GateInfo = min_gate
            self.max_gate : GateData.GateInfo = max_gate
            self.item_data = item_data
            self.output_mode = mode
            self.fixed_value = 0 # fixed value to output for this range if the condition is Fixed


        def __str__(self):
            if self.min_gate is None or self.max_gate is None:
                return "N/A"
            return f"{self.min_gate.value} {self.max_gate.value}"


    steps_changed = QtCore.Signal() # signals that steps (gate counts) have changed 
    values_changed = QtCore.Signal() # signals that values have changed (not step/gate counts)

    def __init__(self,
                 action_data,
                 min = -1.0,
                 max = 1.0,
                 action = GateAction.NoAction,
                 condition = GateCondition.OnCross,
                 mode = GateRangeOutputMode.Normal,
                 range_min = -1.0,
                 range_max = 1.0):
        super().__init__()
        self._action_data = action_data
        self._min = min # gate min range
        self._max = max # gate max range
        self._action = action # primary action mode
        self.condition = condition
        self._action_map = {} # list of individual gate actions
        self._gate_condition_map = {} # list of individual gate conditions
        self._gate_value_map = {} # list of individual gate values, floating point range -1 to +1
        self._used_map = {} # flags to track which gate is used as the widget is edited
        self.output_mode = mode
        self.fixed_value = 0
        self.range_min = range_min
        self.range_max = range_max
        self.macro : gremlin.macro.Macro = None  # macro steps
        self.id = gremlin.util.get_guid()
        self._last_value = None # last input value - this is set whenever a profile is activated or when it is triggered

        # default gates
        min_gate = GateData.GateInfo(0,min,self._new_item_data())
        max_gate = GateData.GateInfo(1,max,self._new_item_data())
        range_info = GateData.RangeInfo(0,min_gate, max_gate,  GateCondition.InRange, GateRangeOutputMode.Normal)
        self._gate_item_map = {0: min_gate, 1: max_gate} # holds the input item data for gates index by gate index
        self._range_item_map = {0: range_info} # holds the input item data for ranges indexed by range index
        


    @property
    def steps(self):
        # number of gates
        return len(self._gate_item_map.keys())

    def setGateAction(self, index, action):
        ''' sets the action for the given gate index '''
        self._action_map[index] = action
    def getGateAction(self, index):
        ''' gets the action for the given gate index '''
        if not index in self._action_map:
            self._action_map[index] = GateAction.Gate
        return self._action_map[index]
    
    def setGateCondition(self, index, condition):
        ''' sets the condition for the given gate index '''
        self._gate_condition_map[index] = condition
    def getGateCondition(self, index):
        ''' gets the condition for the given gate index '''
        if not index in self._gate_condition_map:
            self._gate_condition_map[index] = GateCondition.OnCross
        return self._gate_condition_map[index]
    
    def _valid_condition_for_action(self, action):
        if action == GateAction.Gate:
            # only one condition for steps
            return [GateCondition.OnCross, GateCondition.OnCrossIncrease, GateCondition.OnCrossDecrease]
        else:
             # all others
             return [GateCondition.InRange, GateCondition.OutsideRange]
        
    def getGateValidConditions(self, index):
        ''' gets the valid conditions for the given gate index '''
        return self._valid_condition_for_action(self.getGateAction(index))

    def valid_conditions(self):
        ''' returns the list of valid conditions for the given action '''
        return self._valid_condition_for_action(self.action)
    

    @property
    def action(self):
        return self._action
    
    @action.setter
    def action(self, value):
        self._action = value
        self.update_steps()

    @property
    def min(self):
        return self._min
    @min.setter
    def min(self, value):
        self._min = value
        self.update_steps()
    
    @property
    def max(self):
        return self._max
    @max.setter
    def max(self, value):
        self._max = value
        self.update_steps()
   
    @steps.setter
    def steps(self, value):
        if value < 2:
            # must have at least two gates
            value = 2
        self._steps = value
        self.update_steps()

    def getGateValues(self):
        ''' gets a list of gate values '''
        return self._get_used_values()
    
    def getUsedGatesIndices(self):
        ''' gets the index of used gates '''
        return self._get_used_indices()
    
    def getGateValueItems(self):
        ''' gets pairs of index, value for each gate '''
        return self._get_used_items()
    
    def setGateValue(self, index, value):
        ''' sets the value of a gate '''
        gate = self.getGate(index)
        gate.value = value
        if gate.value != value:
            gate.value = value
            self.values_changed.emit() # indicate step data changed

    def getGateRanges(self):
        ''' returns the list of ranges [(v1,v2), (v2,v3), ...] '''
        return self._get_gate_ranges()
    
    def getGate(self, index):
        if not index in self._gate_item_map.keys():
            item_data = self._new_item_data()
            gate_info = GateData.GateInfo(index, item_data)
            self._gate_item_map[index] = gate_info
        return self._gate_item_map[index]

        
    def normalize_steps(self, use_current_range = False):
        ''' normalizes gate intervals based on the number of gates 
        
        :param: use_current_range = normalize steps over the current min/max range, if false, resets min/max and uses the full range

        '''

        if not use_current_range:
            self._min = -1.0
            self._max = 1.0

        assert self.steps >= 2

        minmax_range = self._max - self._min
        interval = minmax_range / (self._steps-1)
        current = self._min
        for index in range(self._steps):
            self._gate_value_map[index] = current
            self.getGate(index).value = current
            current += interval
        

        self.values_changed.emit() # indicate step data changed


    def _get_next_index(self):
        ''' gets the next unused index '''
        used_list = self._get_used_indices()
        for index in range(100):
            if not index in used_list:
                return index
        return None

        

    def update_steps(self):
        ''' updates the stepped data when the range changes '''
        value = self.steps

        # add the missing steps only (re-use other steps so we don't lose their config)
        current_steps = len(self.getUsedGatesIndices())
        if current_steps < value:
            min_value = max([g.value for g in self._gate_item_map.values()]) if current_steps else self._min
            minmax_range = self._max - min_value
            interval = minmax_range / (1 + value - current_steps)
            if min_value > -1:
                min_value += interval
            steps = value - current_steps
            
            for _ in range(steps):
                index = self._get_next_index()
                if not index in self._action_map.keys():
                    self._action_map[index] = GateAction.Gate
                if not index in self._gate_condition_map.keys():
                    self._gate_condition_map[index] = GateCondition.OnCross
                if not index in self._gate_value_map.keys():
                    self._gate_value_map[index] = min_value
                info = self.getGate(index)
                info.used = True
                info.value = min_value
                self._used_map[index] = True
                min_value += interval
        elif current_steps > value:
            # mark the items at unused
            for index in range(value, current_steps):
                self._used_map[index] = False

        print (f"Updated steps: {self.getGateValueItems()}")

        self._range_list = self._get_gate_ranges() # update the range data
        self.steps_changed.emit() # indicate step data changed

    def _get_used_items(self):
        return [(info.index, info) for info in self._gate_item_map.values() if info.used]
    
    def _get_used_values(self):
        return [info.index for info in self._gate_item_map.values() if info.used]
    
    def _get_used_indices(self):
        return [info.index for info in self._gate_item_map.values() if info.used]

    def _get_gate_ranges(self):
        ''' buils a list of gate ranges based on all the gates as a list of [(gate_1,gate_2), (gate_2,gate_3), ...] '''
        range_list = []
        value_list = self._get_used_items()
        value_list.sort(key = lambda x: x[1]) # sort by value, keep the gate index the same
        
        for index in range(len(value_list)-1):
            range_list.append((value_list[index], value_list[index+1]))

        return range_list

    def _get_range_for_value(self, value):
        ''' returns (v1,v2,idx1,idx12) where v1 = lower range, v2 = higher range, idx1 = gate index for v1, idx2 = gate index for v2 '''
        for index in range(len(self._range_list)):
            ((idx1,v1),(idx2,v2)) = self._range_list[index]
            if value >= v1 and value <= v2:
                return (v1,v2,idx1,idx2)
        return (None, None, None, None)
        
    




    def pre_process(self):
        # setup the pre-run activity
        self._last_value = None
        self._range_list = self._get_gate_ranges()

    def process_value(self, value):
        ''' processes an axis input value 
         
        :param: value - the input float value -1 to +1
           
        '''

        triggers = []
        
        # this gate is a trigger mode
        last_value = self._last_value
        value_changed = last_value is None or last_value != value
        if not value_changed:
            return # nothing to report 
        
        last_in_range = False if last_value is None else last_value >= self.min and last_value <= self.max
        in_range =  value >= self.min and value <= self.max
        
        # get gate crossings
        trigger = False            
        if self.condition == GateCondition.InRange:
            # the value entered the range since the last check
            trigger =  in_range and not last_in_range
            if trigger:
                data = TriggerData()
                if self.output_mode == GateRangeOutputMode.Fixed:
                    data.mode = TriggerMode.FixedValue
                    data.value = self.fixed_value
                elif self.output_mode == GateRangeOutputMode.Normal:
                    data.mode = TriggerMode.Value
                    data.value = value
                elif self.output_mode == GateRangeOutputMode.Ranged:
                    data.mode = TriggerMode.RangedValue
                    # double scale the input - to the range, then to the output range
                    range_value = gremlin.util.scale_to_range(value, target_min = self.min, target_max=self.max)
                    data.value = gremlin.util.scale_to_range(range_value, target_min = self.range_min, target_max=self.range_max)
                else:
                    data.mode = TriggerMode.ValueInRange
                    data.value = value
                triggers.append(data)
        if self.condition == GateCondition.OutsideRange:
            trigger = not in_range
            if trigger:
                data = TriggerData()
                data.mode = TriggerMode.ValueOutOfRange
                data.value = value
                triggers.append(data)

        # check gate crossings                
        if last_value is not None:
            v1,v2,idx1,idx2 = self._get_range_for_value(value)
            gate_value = None
            gate_index = None
            if v1 is not None:
                # found a range
                if self.condition == GateCondition.OnCross:
                    # crossing either way
                    trigger =  last_value < v1 or last_value > v2
                    gate_value = (v1, v2)
                    gate_index = (idx1, idx2)

                elif self.condition == GateCondition.OnCrossIncrease:
                    trigger = last_value < v1
                    gate_value = (v1)
                    gate_index = (idx1)
                elif self.condition == GateCondition.OnCrossDecrease:
                    trigger = last_value > v2
                    gate_value = (v2)
                    gate_index = (idx2)

        self._last_value = value

        if trigger:
            data = TriggerData()
            data.mode = TriggerMode.GateCrossed
            data.gate_value = gate_value
            data.gate_index = gate_index
            data.value = value
            triggers.append(data)
        
        return triggers

        

    def to_xml(self):
        ''' export this configuration to XML '''
        node = ElementTree.Element("gate")

        node.set("action", _gate_action_to_name[self.action])
        node.set("condition", _gate_condition_to_name[self.condition])
        node.set("mode", _gate_range_to_name[self.output_mode])
        node.set("steps", str(self.steps))

        gate_info : GateData.GateInfo
        for gate_info in self._gate_item_data_map.values():
            child = ElementTree.SubElement(node,"handle")
            gate_value = f"{gate_info.value:0.{_decimals}f}"
            child.set("value", gate_value)
            child.set("index", str(index))
            child.set("action",_gate_action_to_name(gate_info.action))
            child.set("condition",_gate_condition_to_name(gate_info.condition))

        range_info : GateData.RangeInfo
        for range_info in self._range_item_map.values():
            child = ElementTree.SubElement(node,"range")
            child.set("index", str(index))
            child.set("condition",_gate_condition_to_name(range_info.condition))
            child.set("min_index", str(range_info.min_gate.index))
            child.set("max_index", str(range_info.max_gate.index))
            child.set("mode",_gate_range_to_name(range_info.output_mode))
            

        # output handle configuration
        for index in range(len(self._action_map.keys())):
            child = ElementTree.SubElement(node, "handle")
            action_name = _gate_action_to_name[self._action_map[index]]
            child.set("action", action_name)
            condition_name = _gate_condition_to_name[self._gate_condition_map[index]]
            child.set("condition", condition_name )
            gate_value = f"{self._gate_value_map[index]:0.{_decimals}f}"
            child.set("value", gate_value)
            child.set("index", str(index))

        if self.action == GateAction.Ranged:
            node.append(self.range_to_xml(self.min, self.max,"input_range"))
            node.append(self.range_to_xml(self.range_min, self.range_max,"output_range"))
            node_fixed = ElementTree.SubElement(node,"fixed_value")
            node_fixed.text = str(self.fixed_value)




        return node
    
    def _find_input_item(self):
        current = self._action_data
        while current and not isinstance(current, gremlin.base_profile.InputItem):
            current = current.parent
        return current

    def _new_item_data(self):
        ''' creates a new item data from the existing one '''
        current_item_data = self._find_input_item()
        item_data = gremlin.base_profile.InputItem(current_item_data)
        item_data._input_type = current_item_data._input_type
        item_data._device_guid = current_item_data._device_guid
        item_data._input_id = current_item_data._input_id
        return item_data

    def from_xml(self, node):
        if not node.tag == "gate":
            syslog.error(f"GateData: Invalid node type {node.tag} {node}")
            return
        action = safe_read(node, "action", str, "")
        if not action in _gate_action_from_name.keys():
            syslog.error(f"GateData: Invalid action type {action} {node}")
            return
        self.action = _gate_action_from_name[action]

        condition = safe_read(node, "condition", str, "")
        if not condition in _gate_condition_from_name.keys():
            syslog.error(f"GateData: Invalid condition type {condition} {node}")
            return
        condition = _gate_condition_from_name[condition]
        valid_conditions = self.valid_conditions()
        if not condition in valid_conditions:
            condition = valid_conditions[0]
        self.condition = condition


            
        mode = safe_read(node,"mode",str,"")
        if not mode in _gate_range_from_name.keys():
            syslog.error(f"GateData: Invalid mode type {mode} {node}")
            return
        self.output_mode = _gate_range_from_name[mode]


        # read individual handle configurations 
        node_handles = gremlin.util.get_xml_child(node, "handle", multiple=True)
        for child in node_handles:
            gate_index = safe_read(child, "index", int, 0)
            gate_value = safe_read(child, "value", float, 0.0)
            gate_action = safe_read(node, "action", str, "")
            if not gate_action in _gate_action_from_name.keys():
                syslog.error(f"GateData: Invalid action type {action} handle index {gate_index}")
                return
            gate_condition = safe_read(node, "condition", str, "")
            if not gate_condition in _gate_condition_from_name.keys():
                syslog.error(f"GateData: Invalid condition type {condition} handle index: {gate_index}")
                return
            
            item_node = gremlin.util.get_xml_child(child, "action_containers")
            item_data = self._new_item_data()
            if item_node:
                item_node.tag = item_node.get("type")
                item_data.from_xml(item_node)
            
            self._action_map[gate_index] = _gate_action_from_name[gate_action]
            self._gate_condition_map[gate_index] = _gate_condition_from_name[gate_condition]
            self._gate_value_map[gate_index] = gate_value

            gate_info = GateData.GateInfo(gate_index, gate_value, item_data, gate_condition)
            self._gate_item_map[gate_index] = gate_info

        node_ranged = gremlin.util.get_xml_child(node, "range", multiple=True)
        for child in node_ranged:
            range_index = safe_read(child, "index", int, 0)
            range_condition = _gate_condition_from_name[safe_read(node, "condition", str, "")]
            range_mode = _gate_range_from_name(safe_read(node, "mode", str, ""))
            range_min_index = safe_read(child, "min_index", int, 0)
            range_max_index = safe_read(child, "min_index", int, 0)

            item_node = gremlin.util.get_xml_child(child, "range_containers")
            item_data = self._new_item_data()
            if item_node:
                item_node.tag = item_node.get("type")
                item_data.from_xml(item_node)

            min_gate = self._gate_item_map[range_min_index] 
            max_gate = self._gate_item_map[range_max_index]
            range_info = GateData.RangeInfo(range_index, min_gate, max_gate, item_data, range_condition, range_mode)
            self._range_item_map[gate_index] = range_info
        
        if self.action == GateAction.Ranged:
            child = get_xml_child(node, "input_range")
            self.min, self.max = self.range_from_xml(child)
            child = get_xml_child(node, "output_range")
            self.range_min, self.range_max = self.range_from_xml(child)
            child = get_xml_child(node, "fixed_value")
            if child:
                self.fixed_value = float(child.text)

        self.steps = safe_read(node,"steps",int,0)

            
    def range_to_xml(self, min, max, tag = "range"):
        node = ElementTree.Element(tag)
        node.set("min", f"{min:0.5f}")
        node.set("max", f"{max:0.5f}")
        return node

    def range_from_xml(self, node) -> tuple:
        ''' reads min/max range node - return (min, max)'''
        min = safe_read(node, "min", float, -1.0)
        max = safe_read(node, "max", float, 1.0)
        return (min, max)

      
class TriggerData():
    ''' holds a trigger data point'''


    def __init__(self):
        self.value = None
        self.mode : TriggerMode = TriggerMode.Value
        self.gate_index = None
        self.gate_value = None

    def __str__(self):
        return f"Trigger: mode: {self.mode.name} value: {self.value}  gate: {self.gate_index} gate value: {self.gate_value}"


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

        data = TriggerData()

        # compute the value of the gate based on the intput axis 
        if value < gate.min or value > gate.max:
            return None # value is not in the gate range
        if gate.action == GateAction.NoAction:
            # pass through
            data.value = value
            data.mode = TriggerMode.Value
            return data
            
        elif gate.action == GateAction.Ranged:
            # send min value
            data.value = self.scale_output(gate.min)
            data.mode = TriggerMode.Value
            return data
        
    
        return None
        

class GateWidget(QtWidgets.QWidget):
    ''' a widget that represents a single gate on an axis input and what should happen in that gate
    
        a gate has a min/max value, an optional output range and can trigger different actions based on conditions applied to the input axis value 
    
    '''

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz
    duplicate_requested = QtCore.Signal(object) # fired when the duplicate button is clicked - passes the GateData to duplicate
    configure_requested = QtCore.Signal(object) # configure clicked
    configure_range_requested = QtCore.Signal(object, int) # configure range - gatedata, range index
    configure_gate_requested = QtCore.Signal(object, int) # fires when a slider handle is right clicked, sends the GateData and the index of the handle

    slider_css = """
QSlider::groove:horizontal {
    border: 1px solid #565a5e;
    height: 10px;
    background: #eee;
    margin: 0px;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: #8FBC8F;
    border: 1px solid #565a5e;
    width: 8pxpx;
    height: 8px;
    border-radius: 4px;
}
"""


    def __init__(self, action_data, gate_data, parent = None):

        import gremlin.event_handler
        import gremlin.joystick_handling
        
        super().__init__(parent)
        self.gate_data : GateData = gate_data
        self.gate_data.steps_changed.connect(self._update_steps)
        self.gate_data.values_changed.connect(self._update_values)

        self.action_data = action_data


        self.single_step = 0.001 # amount of a single step when scrolling 
        self.decimals = 3 # number of decimals
        self._output_value = 0

        self.main_layout = QtWidgets.QGridLayout(self)

        if action_data.hardware_input_type != InputType.JoystickAxis:
            missing = QtWidgets.QLabel("Invalid input type - joystick axis expected")
            self.main_layout.addWidget(missing)
            return
        
        # get the curent axis normalized value -1 to +1
        value = gremlin.joystick_handling.get_axis(action_data.hardware_device_guid, action_data.hardware_input_id)
        self._axis_value = value 

        # axis input repeater
        #self.slider = QDoubleRangeSlider()
        self.slider = ui_common.QMarkerDoubleRangeSlider()
        self.slider.setOrientation(QtCore.Qt.Horizontal)
        self.slider.setRange(-1,1)
        self.slider.setValue([self.gate_data.min,self.gate_data.max]) # first value is the axis value
        self.slider.setMarkerValue(value)
        self.slider.valueChanged.connect(self._slider_value_changed_cb)
        self.slider.setMinimumWidth(200)
        self.slider.setStyleSheet("QSlider::active:{background: #8FBC8F;}")
        self.slider.handleRightClicked.connect(self._slider_handle_clicked_cb)
        #self.slider.setStyleSheet(self.slider_css)

        
        


      
        self.container_slider_widget = QtWidgets.QWidget()
        self.container_slider_layout = QtWidgets.QGridLayout(self.container_slider_widget)
        self.container_slider_layout.addWidget(self.slider,0,0,-1,1)
        #self.container_slider_layout.addWidget(self.test)


        self.container_slider_layout.addWidget(QtWidgets.QLabel(" "),0,6)

        self.container_slider_layout.setColumnStretch(0,3)
        
        self.container_slider_widget.setContentsMargins(0,0,0,0)

        # action drop down
        self.action_selector_widget = QtWidgets.QComboBox()
        for action in GateAction:
            self.action_selector_widget.addItem(GateAction.to_display_name(action), action)
        index = self.action_selector_widget.findData(self.gate_data.action)
        self.action_selector_widget.setCurrentIndex(index)
        self.action_selector_widget.currentIndexChanged.connect(self._action_changed_cb)
        

        self.action_description_widget = QtWidgets.QLabel()


        # condition drop down
        self.condition_selector_widget = QtWidgets.QComboBox()
        self.condition_selector_widget.setCurrentIndex(index)
        self.condition_selector_widget.currentIndexChanged.connect(self._condition_changed_cb)
                

        self.condition_description_widget = QtWidgets.QLabel()

        
        # range mode drop down
        self.range_mode_selector_widget = QtWidgets.QComboBox()
        for mode in GateRangeOutputMode:
            self.range_mode_selector_widget.addItem(_gate_range_name[mode], mode)
        index = self.range_mode_selector_widget.findData(self.gate_data.output_mode)
        self.range_mode_selector_widget.setCurrentIndex(index)

        self.range_mode_selector_widget.currentIndexChanged.connect(self._range_mode_changed_cb)


        self.container_selector_widget = QtWidgets.QWidget()
        self.container_selector_layout = QtWidgets.QHBoxLayout(self.container_selector_widget)
        self.container_selector_widget.setContentsMargins(0,0,0,0)

        # configure trigger button
        self._configure_trigger_widget = QtWidgets.QPushButton("Configure")
        self._configure_trigger_widget.setIcon(gremlin.util.load_icon("fa.gear"))
        self._configure_trigger_widget.clicked.connect(self._trigger_cb)


        self.container_selector_layout.addWidget(QtWidgets.QLabel("Action:"))
        self.container_selector_layout.addWidget(self.action_selector_widget)
        self.container_selector_layout.addWidget(QtWidgets.QLabel("Condition:"))
        self.container_selector_layout.addWidget(self.condition_selector_widget)
        self.container_selector_layout.addWidget(QtWidgets.QLabel("Output Mode:"))
        self.container_selector_layout.addWidget(self.range_mode_selector_widget)
        self.container_selector_layout.addWidget(self._configure_trigger_widget)

        self.container_selector_layout.addStretch()

     
        self.clear_button_widget = ui_common.QDataPushButton()
        self.clear_button_widget.setIcon(load_icon("mdi.delete"))
        self.clear_button_widget.setMaximumWidth(20)
        self.clear_button_widget.data = self.gate_data
        self.clear_button_widget.clicked.connect(self._delete_cb)
        self.clear_button_widget.setToolTip("Removes this entry")
        


        self.duplicate_button_widget = ui_common.QDataPushButton()
        self.duplicate_button_widget.setIcon(load_icon("mdi.content-duplicate"))
        self.duplicate_button_widget.setMaximumWidth(20)
        self.duplicate_button_widget.data = self.gate_data
        self.duplicate_button_widget.clicked.connect(self._duplicate_cb)
        self.duplicate_button_widget.setToolTip("Duplicates this entry")

        # manual and grab value widgets
        self.container_gate_widget = QtWidgets.QWidget()
        self.container_gate_layout = QtWidgets.QGridLayout(self.container_gate_widget)
        self.container_gate_widget.setContentsMargins(0,0,0,0)

        self.container_range_widget = QtWidgets.QWidget()
        self.container_range_layout = QtWidgets.QGridLayout(self.container_range_widget)
        self.container_range_widget.setContentsMargins(0,0,0,0)
        

        self._update_gates_ui()
    
        # ranged container
        self._create_output_ui()

        # steps container
        self._create_steps_ui()

        self.container_description_widget = QtWidgets.QWidget()
        self.container_description_layout = QtWidgets.QVBoxLayout(self.container_description_widget)
        self.container_description_layout.addWidget(self.action_description_widget)
        self.container_description_layout.addWidget(self.condition_description_widget)
        self.container_description_widget.setContentsMargins(0,0,0,0)


        self.container_selector_layout.addWidget(self.clear_button_widget)
        self.container_selector_layout.addWidget(self.duplicate_button_widget)

        self.main_layout.addWidget(self.container_selector_widget,0,0)
        
        
        self.main_layout.addWidget(self.container_description_widget,1,0)
        self.main_layout.addWidget(self.container_slider_widget,2,0)
        self.main_layout.addWidget(self.container_gate_widget,3,0)
        self.main_layout.addWidget(self.container_range_widget,5,0)
        self.main_layout.addWidget(self.container_steps_widget,4,0)
        self.main_layout.addWidget(self.container_output_range_widget,6,0)
        self.main_layout.addWidget(self.container_fixed_widget,6,0)
        self.main_layout.addWidget(self.container_output_widget,7,0)
   
        self.main_layout.setVerticalSpacing(0)

        # hook the joystick input for axis input repeater
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)

        # update visible container for the current mode
        self._update_conditions()
        self._update_ui()
        self._update_values()

    def _update_gates_ui(self):
        ''' creates the gate data for each gate '''
        row = 0
        col = 0
        grab_icon = load_icon("mdi.record-rec",qta_color = "red")
        setup_icon = load_icon("fa.gear")
        self._gate_value_widget_list = []
        gremlin.util.clear_layout(self.container_gate_layout)
        items = self.gate_data.getGateValueItems()
        for index, info in items:
            
            label_widget = QtWidgets.QLabel(f"Gate {index+1}:")
            sb_widget = ui_common.DynamicDoubleSpinBox(data = index)
            sb_widget.setMinimum(-1.0)
            sb_widget.setMaximum(1.0)
            sb_widget.setDecimals(self.decimals)
            sb_widget.setSingleStep(self.single_step)
            sb_widget.setValue(info.value)
            sb_widget.valueChanged.connect(self._gate_value_changed_cb)
            self._gate_value_widget_list.append(sb_widget)

            grab_widget = ui_common.QDataPushButton()
            grab_widget.data = sb_widget # control to update
            grab_widget.setIcon(grab_icon)
            grab_widget.setMaximumWidth(20)
            grab_widget.clicked.connect(self._grab_cb)
            grab_widget.setToolTip("Grab axis value")

            setup_widget = ui_common.QDataPushButton()
            setup_widget.data = index
            setup_widget.setIcon(setup_icon)
            setup_widget.setMaximumWidth(20)
            setup_widget.clicked.connect(self._setup_cb)
            setup_widget.setToolTip(f"Setup actions for gate {index}")


            self.container_gate_layout.addWidget(label_widget,row,col + 0)
            self.container_gate_layout.addWidget(sb_widget,row,col + 1)
            self.container_gate_layout.addWidget(grab_widget,row,col + 2)
            self.container_gate_layout.addWidget(setup_widget,row,col + 3)
            
            col += 4
            if col > 4*5:
                row+=1
                col = 0

        # pad the grid so controls are aligned left
        max_col = self.container_gate_layout.columnCount()
        self.container_gate_layout.addWidget(QtWidgets.QLabel(" "), 0,max_col)            
        self.container_gate_layout.setColumnStretch(max_col, 3)


        # ranges between the gates
        gremlin.util.clear_layout(self.container_range_layout)
        range_list = self.gate_data.getGateRanges()
        col = 0
        row = 0
        for index, range in enumerate(range_list):
            (_,g1,),(_, g2) = range
            
            label_widget = QtWidgets.QLabel(f"Range {index+1}:")

            range_widget = QtWidgets.QLineEdit()
            range_widget.setReadOnly(True)
            range_widget.setText(f"[{g1.index+1}:{g2.index+1}] {g1.value:0.{self.decimals}f} to {g2.value:0.{self.decimals}f}")
            
            setup_widget = ui_common.QDataPushButton()
            setup_widget.data = index
            setup_widget.setIcon(setup_icon)
            setup_widget.setMaximumWidth(20)
            setup_widget.clicked.connect(self._setup_range_cb)
            setup_widget.setToolTip(f"Setup actions for range {index}")

            self.container_range_layout.addWidget(label_widget, row, col)
            self.container_range_layout.addWidget(range_widget, row, col + 1)
            self.container_range_layout.addWidget(setup_widget, row, col + 2)


            col += 3
            if col > 4*5:
                row+=1
                col = 0

        max_col = self.container_range_layout.columnCount()
        self.container_range_layout.addWidget(QtWidgets.QLabel(" "), 0,max_col)            
        self.container_range_layout.setColumnStretch(max_col, 3)

        
    @QtCore.Slot()
    def _gate_value_changed_cb(self):
        widget = self.sender()
        index = widget.data
        #with QtCore.QSignalBlocker(self.gate_data):
        self.gate_data.setGateValue(index, widget.value())


    @QtCore.Slot()
    def _trigger_cb(self):
        ''' configure clicked '''
        self.configure_requested.emit(self.gate_data)

    @QtCore.Slot(int)
    def _slider_handle_clicked_cb(self, handle_index):
        ''' handle right clicked - pass event along '''
        self.configure_gate_requested.emit(self.gate_data, handle_index)

    @QtCore.Slot()
    def _slider_value_changed_cb(self):
        ''' occurs when the slider values change '''
        values = list(self.slider.value())
        
        # update the gate data
        for index, value in enumerate(values):
            self.gate_data.setGateValue(index, value)
            widget = self._gate_value_widget_list[index]
            with QtCore.QSignalBlocker(widget):
                widget.setValue(value)

        


    @QtCore.Slot()
    def _grab_cb(self):
        ''' grab the min value from the axis position '''
        widget = self.sender().data  # the button's data field contains the widget to update
        value = self._axis_value
        widget.setValue(value)

    @QtCore.Slot()
    def _setup_cb(self):
        ''' open the configuration dialog '''
        widget = self.sender()  # the button's data field contains the widget to update
        handle_index = widget.data
        self.configure_gate_requested.emit(self.gate_data, handle_index)
        
    @QtCore.Slot()
    def _setup_range_cb(self):
        ''' open the configuration dialog for ranges '''
        widget = self.sender()  # the button's data field contains the widget to update
        range_index = widget.data
        self.configure_range_requested.emit(self.gate_data, range_index)

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
        input_value = gremlin.joystick_handling.scale_to_range(raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1) 
        self._axis_value = input_value
        self.slider.setMarkerValue(input_value)
        self._update_output_value()


    def _create_output_ui(self):
        ''' creates the output line ui options '''

        

        self.container_output_range_widget = QtWidgets.QWidget()
        self.container_output_range_layout = QtWidgets.QHBoxLayout(self.container_output_range_widget)
        self.container_output_range_widget.setContentsMargins(0,0,0,0)
        
        self.sb_range_min_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_range_min_widget.setMinimum(-1.0)
        self.sb_range_min_widget.setMaximum(1.0)
        self.sb_range_min_widget.setDecimals(self.decimals)
        self.sb_range_min_widget.setSingleStep(self.single_step)
        self.sb_range_min_widget.setValue(self.gate_data.range_min)
        self.sb_range_min_widget.valueChanged.connect(self._range_min_changed_cb)

        self.sb_range_max_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_range_max_widget.setMinimum(-1.0)
        self.sb_range_max_widget.setMaximum(1.0)        
        self.sb_range_max_widget.setDecimals(self.decimals)
        self.sb_range_max_widget.setSingleStep(self.single_step)
        self.sb_range_max_widget.setValue(self.gate_data.range_max)

        # holds the output value
        self.output_value_widget = QtWidgets.QLineEdit()
        self.output_value_widget.setReadOnly(True)
        self.output_gate_crossed_widget = QtWidgets.QLineEdit()
        self.output_gate_crossed_widget.setReadOnly(True)
        

        self.sb_range_max_widget.valueChanged.connect(self._range_max_changed_cb)

        self.sb_fixed_value_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.sb_fixed_value_widget.setMinimum(-1.0)
        self.sb_fixed_value_widget.setMaximum(1.0)        
        self.sb_fixed_value_widget.setDecimals(self.decimals)
        self.sb_fixed_value_widget.setSingleStep(self.single_step)
        self.sb_fixed_value_widget.setValue(self.gate_data.fixed_value)

        self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range options:"))
        self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Min:"))
        self.container_output_range_layout.addWidget(self.sb_range_min_widget)
        self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Max:"))
        self.container_output_range_layout.addWidget(self.sb_range_max_widget)
        
        self.container_fixed_widget = QtWidgets.QWidget()
        self.container_fixed_widget.setContentsMargins(0,0,0,0)
        self.container_fixed_layout = QtWidgets.QHBoxLayout(self.container_fixed_widget)
        self.container_fixed_layout.addWidget(QtWidgets.QLabel("Fixed Value:"))
        self.container_fixed_layout.addWidget(self.sb_fixed_value_widget)
        
        self.container_output_widget = QtWidgets.QWidget()
        self.container_output_widget.setContentsMargins(0,0,0,0)
        self.container_output_layout = QtWidgets.QHBoxLayout(self.container_output_widget)
        


        self.container_output_layout.addWidget(self.output_gate_crossed_widget)
        self.container_output_layout.addStretch()
        self.container_output_layout.addWidget(QtWidgets.QLabel("Output Value:"))
        self.container_output_layout.addWidget(self.output_value_widget)
        

    def _create_steps_ui(self):
        ''' creates the steps UI '''
        self.sb_steps_widget = QtWidgets.QSpinBox()
        self.sb_steps_widget.setRange(1, 20)
        self.sb_steps_widget.setValue(self.gate_data.steps)
        # self.sb_steps_widget.valueChanged.connect(self._steps_changed_cb)

        self.set_steps_widget = QtWidgets.QPushButton("Set")
        self.set_steps_widget.setToolTip("Sets the number of gates")
        self.set_steps_widget.clicked.connect(self._set_steps_cb)

        self.normalize_widget = QtWidgets.QPushButton("Normalize")
        self.normalize_widget.setToolTip("Normalizes the position of gates evenly on the existing range")
        self.normalize_widget.clicked.connect(self._normalize_cb)

        self.normalize_reset_widget = QtWidgets.QPushButton("Normalize (reset)")
        self.normalize_reset_widget.setToolTip("Normalizes the position of gates evenly using the full range and resets to min/max to full range")
        self.normalize_reset_widget.clicked.connect(self._normalize_reset_cb)

        self.container_steps_widget = QtWidgets.QWidget()
        self.container_steps_layout = QtWidgets.QHBoxLayout(self.container_steps_widget)
        self.container_steps_widget.setContentsMargins(0,0,0,0)

        self.container_steps_layout.addWidget(QtWidgets.QLabel("Number of steps:"))
        self.container_steps_layout.addWidget(self.sb_steps_widget)
        self.container_steps_layout.addWidget(self.set_steps_widget)
        self.container_steps_layout.addWidget(self.normalize_widget)
        self.container_steps_layout.addWidget(self.normalize_reset_widget)
        self.container_steps_layout.addStretch()

    @QtCore.Slot()
    def _set_steps_cb(self):
        ''' sets the number of steps '''
        value = self.sb_steps_widget.value()
        self.gate_data.steps = value
        self._update_steps()

    # @QtCore.Slot()
    # def _steps_changed_cb(self):
    #     ''' called when the number of steps or position of steps has changed '''
    #     self._update_steps()


    @QtCore.Slot()
    def _normalize_cb(self):
        ''' normalize button  '''
        value = self.sb_steps_widget.value()
        self.gate_data.steps = value        
        self.gate_data.normalize_steps(True)


    def _normalize_reset_cb(self):
        ''' normalize reset button  '''
        value = self.sb_steps_widget.value()
        self.gate_data.steps = value         
        self.gate_data.normalize_steps(False)       


    @QtCore.Slot()
    def _update_steps(self):
        ''' updates gate steps on the widget and their positions '''
        self._update_gates_ui() # update gate manual update UI
        self._update_values()
        

    @QtCore.Slot()
    def _update_values(self):
        ''' called when gate data values are changed '''
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setValue(self.gate_data.getGateValues())

    def _update_output_value(self):
        triggers = self.gate_data.process_value(self._axis_value)
        trigger : TriggerData
       
        for trigger in triggers:
            log_info(trigger)
            # self.output_value_widget.setText(f"No Output")
            if trigger.mode == TriggerMode.FixedValue:
                self.output_value_widget.setText(f"(Fixed output) {trigger.value:0.{self.decimals}f}")
            elif trigger.mode == TriggerMode.Value:
                self.output_value_widget.setText(f"{trigger.value:0.{self.decimals}f}")
            elif trigger.mode == TriggerMode.RangedValue:
                self.output_value_widget.setText(f"(Scaled output) {trigger.value:0.{self.decimals}f}")
            elif trigger.mode == TriggerMode.ValueInRange:
                self.output_value_widget.setText(f"(In range) {trigger.value:0.{self.decimals}f}")
            elif trigger.mode == TriggerMode.ValueOutOfRange:
                self.output_value_widget.setText(f"(Out of range) {trigger.value:0.{self.decimals}f}")
            elif trigger.mode == TriggerMode.GateCrossed:
                self.output_gate_crossed_widget.setText(f"Gate {trigger.gate_index}) crossed {trigger.value:0.{self.decimals}f}")
            self.output_value_widget.setText(f"{trigger.value:0.{self.decimals}f}")
    QtCore.Slot()
    def _range_min_changed_cb(self):
        value = self.sb_range_min_widget.value()
        self.gate_data.range_min = value
        self._update_output_value()

    QtCore.Slot()
    def _range_max_changed_cb(self):
        self.gate_data.range_max = self.sb_range_max_widget.value()
        self._update_output_value()

    QtCore.Slot()
    def _min_changed_cb(self):
        value = self.sb_min_widget.value()
        self.gate_data.min = value
        lv = list(self.slider.value())
        lv[0] = value
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setValue(lv)
        self.gate_data.update_steps()
        self._update_steps()
        self._update_output_value()            

    QtCore.Slot()
    def _max_changed_cb(self):
        value = self.sb_max_widget.value()
        self.gate_data.max = value
        lv = list(self.slider.value())
        lv[1] = value
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setValue(lv)
        self._update_steps()
        self._update_output_value()


    QtCore.Slot(int)
    def _action_changed_cb(self):
        self.gate_data.action = self.action_selector_widget.currentData()
        self._update_conditions()
        self._update_ui()

    QtCore.Slot(int)
    def _condition_changed_cb(self):
        self.gate_data.conditon = self.condition_selector_widget.currentData()
        self._update_ui()

    QtCore.Slot(int)
    def _range_mode_changed_cb(self):
        self.gate_data.output_mode = self.range_mode_selector_widget.currentData()
        self._update_ui()


    def _update_conditions(self):
        ''' updates the condition selector for conditions appropriate for the current action mode'''
        self.condition_selector_widget.currentIndexChanged.disconnect(self._condition_changed_cb)
        self.condition_selector_widget.clear()
        conditions = self.gate_data.valid_conditions()
        current_index = 0
        for index, condition in enumerate(conditions):
            self.condition_selector_widget.addItem(GateCondition.to_display_name(condition), condition) 
            if condition == self.gate_data.condition:
                current_index = index
        self.condition_selector_widget.setCurrentIndex(current_index)
        self.condition_selector_widget.currentIndexChanged.connect(self._condition_changed_cb)

    def _update_ui(self):
        ''' updates visibility of UI components based on the active options '''
        self.action_description_widget.setText(_gate_action_description[self.gate_data.action])
        self.condition_description_widget.setText(_gate_condition_description[self.gate_data.condition])
        range_visible = False  
        fixed_visible = False
        

            
        if self.gate_data.action in (GateAction.NoAction, GateAction.Ranged):

            if self.gate_data.output_mode == GateRangeOutputMode.Fixed:
                fixed_visible = True
                range_visible = False
            else:
                fixed_visible = False
                range_visible = True

            # update the slider configuration 
            self.slider.setValue(self.gate_data.getGateValues())

        self.container_fixed_widget.setVisible(fixed_visible)
        self.container_output_range_widget.setVisible(range_visible)
        

        self._update_output_value()

 
class GatedAxisWidget(QtWidgets.QWidget):
    ''' a scrolling widget container that allows to define one or more gates on an axis input
    
        contains: GateWidget 
    
    '''

    configure_requested = QtCore.Signal(object) # fired when the general gate needs to be configured - sends the gate data
    configure_handle_requested = QtCore.Signal(object, int) # fired when the gate handle needs to be configured - sends the gate data and the index of the handle to configure
    configure_range_requested = QtCore.Signal(object, int)  # fired when the range needs to be configured - sends the gate data and the index of the range to configure

    def __init__(self, action_data, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.action_data = action_data
        self.setMinimumHeight(500)

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
        self.container_map_layout = QtWidgets.QVBoxLayout(self.container_map_widget)
        self.container_map_layout.setContentsMargins(0,0,0,0)

        # add aircraft map items
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Expanding)
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
        ''' defined gates - list of GateData items'''
        return self.action_data.gates
    
    @property
    def gate_count(self):
        ''' number of gates defined '''
        return len(self.action_data.gates) 

    @QtCore.Slot()
    def _add_gate_cb(self):
        self.gates.append(GateData(action_data = self.action_data))
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

    @QtCore.Slot(GateData)
    def _configure_gate(self, data):
        self.configure_requested.emit(data)

    @QtCore.Slot(GateData, int)
    def _configure_gate_handle(self, data, index):
        self.configure_handle_requested.emit(data, index)

    @QtCore.Slot(GateData, int)
    def _configure_range(self, data, index):
        self.configure_range_requested.emit(data, index)


    def _populate_ui(self):
        ''' updates the container map '''

        # clear the widgets
        ui_common.clear_layout(self.map_layout)
        self._gate_widgets = [] # holds all the gate widgets
        gate_count = len(self.gates)

        # self.container_map_widget.setMinimumHeight(200 * gate_count + 1)

        if not self.gates:
            # no item
            missing = QtWidgets.QLabel("Please add a gate definition.")
            missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
            self.map_layout.addWidget(missing)
            return

        
        # default size
        for gate_data in self.gates:
            widget = GateWidget(action_data = self.action_data, gate_data=gate_data)
            widget.delete_requested.connect(self._remove_gate)
            widget.duplicate_requested.connect(self._duplicate_gate)
            widget.configure_requested.connect(self._configure_gate)
            widget.configure_gate_requested.connect(self._configure_gate_handle)
            widget.configure_range_requested.connect(self._configure_range)
            self._gate_widgets.append(widget)
            self.map_layout.addWidget(widget)
            if gate_count > 1:
                self.map_layout.addWidget(ui_common.QHLine())

    
    def pre_process(self):
        ''' before run time - pre-processes the gates to set up processing order '''
        if self.gates:
                
            self._gate_low_order = [gate for gate in self.gates].sort(lambda x: x.min)
            self._gate_high_order = [gate for gate in self.gates].sort(lambda x: x.max).reverse()
            self._gate_min = self._gate_low_order[0]
            self._gate_max = self._gate_high_order[0]

            # reset the last gate value for a new run
            for gate in self.gates:
                gate.pre_process()

    def process(self, value):
        ''' processes a value through all the gates 
        
        Gates are additive, meaning that if one gate rejects a value, but another gate accepts the value, the accepted value will be returned.
        Processing is in order of range, ordered by where the value is vs the gates
        
        '''

        if value <= self._gate_max:
            # proceed using the gate order by min gate setup
            gates = self._gate_low_order
        else:
            # proceed by high order
            gates = self._gate_high_order

        processed_list = [gate.process_value(value) for gate in gates]
        
            
        
            
