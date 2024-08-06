

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
    FilterOut = auto() # sends no data


    @staticmethod
    def to_description(range):
        return _gate_range_description[range]
    
    @staticmethod
    def to_string(range):
        return _gate_range_to_name[range]
    
    @staticmethod
    def from_string(value):
        return _gate_range_from_name[value]
    
    @staticmethod
    def to_display_name(range):
        return _gate_range_to_display_name[range]    


class TriggerMode(Enum):
    ''' values returned in a Trigger data object when a trigger is being sent '''
    Value = auto() # value output - passthrough - use the value in the value field
    RangedValue = auto() # value output - scaled 
    ValueInRange = auto() # value is in range of the gate
    ValueOutOfRange = auto() # value is out of range of the gate
    GateCrossed = auto() # gate crossed - the gate_index contains the gate index crossed, the gate_value member contains the gate value that was crossed
    FixedValue = auto() # fixed value output

_decimals = 5
 


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
    GateCondition.OnCross: "Crossed",
    GateCondition.OnCrossIncrease: "Cross (inc)",
    GateCondition.OnCrossDecrease: "Cross (dec)"
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
    GateCondition.OnCross: "Triggers when the input crosses a gate in any direction",
    GateCondition.OnCrossDecrease: "Triggers when the input crosses a gate while decreasing (crossing from the right/above)",
    GateCondition.OnCrossIncrease: "Triggers when the input crosses a gate while increasing (crossing from the left/below)"
}

_gate_range_to_name = {
    GateRangeOutputMode.Normal: "normal",
    GateRangeOutputMode.Fixed: "fixed",
    GateRangeOutputMode.Ranged: "ranged",
    GateRangeOutputMode.FilterOut: "filter",
}

_gate_range_to_display_name = {
    GateRangeOutputMode.Normal: "Normal",
    GateRangeOutputMode.Fixed: "Fixed Value",
    GateRangeOutputMode.Ranged: "Ranged",
    GateRangeOutputMode.FilterOut: "Filtered (no output)",
}


_gate_range_from_name = {
    "normal": GateRangeOutputMode.Normal ,
    "fixed": GateRangeOutputMode.Fixed,
    "ranged": GateRangeOutputMode.Ranged,
    "filter": GateRangeOutputMode.FilterOut,
   
}

_gate_range_description = {
    GateRangeOutputMode.Normal: "Sends the input value",
    GateRangeOutputMode.Fixed: "Sends a fixed value",
    GateRangeOutputMode.Ranged: "Sends a ranged value based on the input position inside the gate",
    GateRangeOutputMode.FilterOut: "Sends no data (ignore)",
}

_gate_range_name = {
    GateRangeOutputMode.Normal: "Normal",
    GateRangeOutputMode.Fixed: "Fixed Value",
    GateRangeOutputMode.Ranged: "New Range",
    GateRangeOutputMode.FilterOut: "Filter Out",
}

def _is_close(a, b):
    ''' compares two floating point numbers with approximate precision'''
    return math.isclose(a, b, abs_tol=0.0001)

class GateData(QtCore.QObject):
    ''' holds gated information for an axis 
    
        this object knows how to load and save itself to XML
    '''

    stepsChanged = QtCore.Signal() # signals that steps (gate counts) have changed 
    valueChanged = QtCore.Signal() # signals when the gate data changes

    class GateInfo(QtCore.QObject):
        ''' holds gate data information '''

        valueChanged = QtCore.Signal() # fires when the value changes

        def __init__(self, index, value = None, item_data = None, condition = GateCondition.OnCross, parent = None):
            super().__init__()

            self.parent : GateData = parent
            self.index = index
            self.display_index = index # the display index is usually sequential
            self._value = value
            self.condition = condition
            self.item_data = item_data
            self.used = True


        @property
        def value(self):
            return self._value
        
        @value.setter
        def value(self, data):
            if data < -1.0:
                data = -1.0
            if data > 1.0:
                data = 1.0
            if data != self._value:
                self._value = data
                self.valueChanged.emit()

        @property
        def condition(self):
            return self._condition
        @condition.setter
        def condition(self, value):
            assert value in [c for c in GateCondition]
            self._condition = value

        def __lt__(self, other):
            return self._value < other._value
        
        def __str__(self):
            return f"Gate {self.display_index} [{self.index}]  {self.value:0.{_decimals}f} cond: {self.condition} used: {self.used}"

    class RangeInfo(QtCore.QObject):
        valueChanged = QtCore.Signal() # fires when either of the gate values change

        def __init__(self, index, min_gate, max_gate, item_data = None, condition = GateCondition.InRange, 
                     mode = GateRangeOutputMode.Normal, range_min = -1, range_max = 1, parent = None):
            super().__init__()

            self.parent = parent
            self.index = index
            self._output_mode = None
            self._condition = None
            self.condition = condition
            self._min_gate : GateData.GateInfo = min_gate
            if self._min_gate is not None:
                self._min_gate.valueChanged.connect(self._gate_value_changed_cb)
                
            self._max_gate : GateData.GateInfo = max_gate
            if self._max_gate is not None:
                self._max_gate.valueChanged.connect(self._gate_value_changed_cb)

            self.item_data = item_data
            self.mode = mode # output mode determines what we do with the input data 
            self._fixed_value = None # fixed value to output for this range if the condition is Fixed
            self.range_min = range_min # ranged mode output min
            self.range_max = range_max  # ranged mode output max
            self._swap_gates()

        @property
        def condition(self):
            return self._condition
        @condition.setter
        def condition(self, value):
            assert value in [c for c in GateCondition]
            self._condition = value

        @property
        def mode(self):
            return self._output_mode
        @mode.setter
        def mode(self, value):
            assert value in [c for c in GateRangeOutputMode]
            self._output_mode = value

        @property
        def fixed_value(self):
            return self._fixed_value
        
        @fixed_value.setter
        def fixed_value(self, data):
            if data < -1.0:
                data = -1.0
            if data > 1.0:
                data = 1.0
            if self._fixed_value is None or data != self._fixed_value:
                self._fixed_value = data


        @property
        def g1(self):
            return self._min_gate
        @g1.setter
        def g1(self, value):
            if self._min_gate != value:
                if self._min_gate is not None:
                    self._min_gate.valueChanged.disconnect(self._gate_value_changed_cb)
                self._min_gate = value
                self._swap_gates()
                if self._min_gate is not None:
                    self._min_gate.valueChanged.connect(self._gate_value_changed_cb)
                self._gate_value_changed_cb()
        @property
        def g2(self):
            return self._max_gate
        @g2.setter
        def g2(self, value):
            if self._max_gate != value:
                if self._max_gate is not None:
                        self._max_gate.valueChanged.disconnect(self._gate_value_changed_cb)
                self._max_gate = value
                self._swap_gates()
                if self._max_gate is not None:
                    self._max_gate.valueChanged.connect(self._gate_value_changed_cb)
                self._gate_value_changed_cb()

        @QtCore.Slot()
        def _gate_value_changed_cb(self):
            ''' occurs when either gate values change or gates are changed '''
            self.valueChanged.emit()


        @property
        def v1(self):
            ''' gets the min value of the range '''
            if self._min_gate:
                return self._min_gate.value
            return None
        
        @property
        def v2(self):
            ''' gets the max value of the range '''
            if self._max_gate:
                return self._max_gate.value
            return None
        
        def inrange(self, value):
            v1,v2 = self.v1, self.v2
            if value > v1 and value < v2:
                return True
            if _is_close(value,v1) or _is_close(value,v2):
                return True
            return False
        

        def _swap_gates(self):
            ''' ensures gates are in the order min/max '''
            if self._max_gate is not None and self._min_gate is not None:
                if self._max_gate.value < self._min_gate.value:
                    g1, g2 = self._min_gate, self._max_gate
                    g1, g2 = g2, g1
                    self._min_gate = g1
                    self._max_gate = g2
                    

        def range(self):
            ''' gets the distance between gates'''
            if self._max_gate and self._min_gate:
                return self._max_gate.value - self._min_gate.value
            return 0
        
        def range_values(self):
            ''' returns the tuple of range values '''
            if self._max_gate and self._min_gate:
                return (self._max_gate.value, self._min_gate.value)
            return (None, None)

        def __str__(self):
            if self._min_gate is None or self._max_gate is None:
                rr = "N/A"
            else:
                rr = f"{self._min_gate.value} {self._max_gate.value}"
            return f"Range {self.index} [{rr}] mode: {self.output_mode}"
        
        def __hash__(self):
            return hash(self.range_values())



    def __init__(self,
                 action_data,
                 min = -1.0,
                 max = 1.0,
                 condition = GateCondition.OnCross,
                 mode = GateRangeOutputMode.Normal,
                 range_min = -1.0,
                 range_max = 1.0):
        super().__init__()
        self._action_data = action_data
        self._min = min # gate min range
        self._max = max # gate max range
        self.condition = condition
        self.output_mode = mode
        self.fixed_value = 0
        self.range_min = range_min
        self.range_max = range_max
        self.macro : gremlin.macro.Macro = None  # macro steps
        self.id = gremlin.util.get_guid()

        self._last_value = None # last input value
        self._last_range = None # last range object

        # default gates
        min_gate = GateData.GateInfo(0,min,self._new_item_data())
        max_gate = GateData.GateInfo(1,max,self._new_item_data())
        range_info = GateData.RangeInfo(0, min_gate, max_gate, self._new_item_data(), condition= GateCondition.InRange, mode= GateRangeOutputMode.Normal)
        min_gate.valueChanged.connect(self._value_changed_cb)
        max_gate.valueChanged.connect(self._value_changed_cb)
        self._gate_item_map = {0: min_gate, 1: max_gate} # holds the input item data for gates index by gate index
        self._range_item_map = {0: range_info} # holds the input item data for ranges indexed by range index

        self._trigger_range_lines = [] # activity triggers
        self._trigger_gate_lines = [] # activity triggers
        self._trigger_line_count = 10 # last 10 triggers max
        
    @property
    def trigger_range_text(self):
        text = ""
        for line in self._trigger_range_lines:
            text += line + "\n"
        return text

    @property
    def trigger_gate_text(self):
        text = ""
        for line in self._trigger_gate_lines:
            text += line + "\n"
        return text        




    def populate_condition_widget(self, widget : QtWidgets.QComboBox, default = None, is_range = False):
        ''' populates a condition widget '''
        widget.clear()
        if is_range:
            # range conditions
            conditions = (GateCondition.InRange, GateCondition.OutsideRange)
        else:
            # gate conditions
            conditions = (GateCondition.OnCross, GateCondition.OnCrossIncrease, GateCondition.OnCrossDecrease)
        current_index = None
        for index, condition in enumerate(conditions):
            widget.addItem(_gate_condition_to_name[condition], condition)
            if default and current_index is None and default == condition:
                current_index = index
        
        if current_index is not None:
            widget.setCurrentIndex(current_index)

    def populate_output_widget(self, widget : QtWidgets.QComboBox, default = None):
        ''' populates a range widget '''
        current_index = None
        for index, output in enumerate(GateRangeOutputMode):
            widget.addItem(_gate_range_to_name[output], output)
            if default and current_index is None and default == output:
                current_index = index

        if current_index is not None:
            widget.setCurrentIndex(current_index)

    @property
    def decimals(self):
        ''' preferred decimals for displays '''
        return _decimals

    @property
    def gates(self):
        # number of gates
        return len(self._get_used_indices())

    def _value_changed_cb(self):
        self.valueChanged.emit()
    
    def setGateCondition(self, index, condition):
        ''' sets the condition for the given gate index '''
        self._gate_condition_map[index] = condition
    def getGateCondition(self, index):
        ''' gets the condition for the given gate index '''
        if not index in self._gate_condition_map:
            self._gate_condition_map[index] = GateCondition.OnCross
        return self._gate_condition_map[index]


    @property
    def min(self):
        return self._min
    @min.setter
    def min(self, value):
        if value < -1.0:
            value = -1.0
        if self._min != value:
            self._min = value
            
    
    @property
    def max(self):
        return self._max
    @max.setter
    def max(self, value):
        if value > 1.0:
            value = 1.0
        if self._max != value:
            self._max = value
            

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
        if gate.value != value:
            gate.value = value
            

    def setGateUsed(self, index, value):
        ''' enables or disables a gate '''
        gate = self.getGate(index)
        gate.used = value

    def getGateRanges(self):
        ''' returns the list of ranges as range info objects'''
        return self._get_ranges()
    
    def getGate(self, index):
        ''' returns a gate object for the given index - the item is created if the index does not exist and the gate is marked used '''
        if not index in self._gate_item_map.keys():
            item_data = self._new_item_data()
            gate_info = GateData.GateInfo(index, value = 0, item_data=item_data, parent = self)
            self._gate_item_map[index] = gate_info
        return self._gate_item_map[index]
    
    def getRange(self, index):
        ''' returns a range object for the given index - the item is created if the index does not exist but gates are not initialized'''
        if not index in self._range_item_map.keys():
            item_data = self._new_item_data()
            range_info = GateData.RangeInfo(index, None, None, item_data=item_data, parent = self)
            self._range_item_map[index] = range_info
        return self._range_item_map[index]    

    def getRangeForValue(self, value):
        ''' gets the range for the specified value '''
        ranges = self._get_ranges()
        for range in ranges:
            if range.inrange(value):
                return range
            
        return None
    
    def deleteGate(self, data):
        ''' removes a gate '''
        index = data.index
        del self._gate_item_map[index]


        
    def normalize_steps(self, use_current_range = False):
        ''' normalizes gate intervals based on the number of gates 
        
        :param: use_current_range = normalize steps over the current min/max range, if false, resets min/max and uses the full range

        '''

        if not use_current_range:
            self._min = -1.0
            self._max = 1.0

        assert self.gates >= 2

        minmax_range = self._max - self._min
        interval = minmax_range / (self._steps-1)
        current = self._min
        for index in range(self._steps):
            self._gate_value_map[index] = current
            self.getGate(index).value = current
            current += interval
        


    def _get_next_index(self):
        ''' gets the next unused index '''
        used_list = self._get_used_indices()
        for index in range(100):
            if not index in used_list:
                return index
        return None

    def update_ranges(self):
        ''' updates the list of ranges with updated gate configuration '''
        value_list = self._get_used_gates()
        value_list.sort(key = lambda g: g.value) # sort by gate value, keep the gate index the same

        for index in range(len(value_list)-1):
            g1 = value_list[index]
            g2 = value_list[index+1]
            info = self.getRange(index)
            info._min_gate = g1
            info._max_gate = g2
        
        self._range_list = self._get_ranges()

    def update_steps(self, value):
        ''' updates the stepped data when the range changes or when the number of gate change
        :param: value = number of gates

        '''

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
                info = self.getGate(index)
                info.used = True
                info.value = min_value
                min_value += interval
        elif current_steps > value:
            # mark the items at unused
            for index in range(value, current_steps):
                self.setGateUsed(index, False)

        print (f"Updated steps: {self.getGateValueItems()}")

        self.update_ranges()
        self.stepsChanged.emit() # indicate step data changed

    def _update_gate_sequence(self, gates):
        for index, gate in enumerate(gates):
            # update display index in the sequence it was found
            if isinstance(gate, tuple):
                gate[1].display_index = index
            else:
                gate.display_index = index
        return gates

    def _get_used_items(self):
        ''' gates the index/gate pairs for active gates '''
        gates = [(info.index, info) for info in self._gate_item_map.values() if info.used]
        gates.sort(key = lambda x: x[1].value) # sort ascending
        gates = self._update_gate_sequence(gates)
        return gates
    
    def _get_used_values(self):
        ''' gets the position of active gates'''
        gates = [info.value for info in self._gate_item_map.values() if info.used]
        gates.sort()
        return gates
    
    def _get_gates_for_values(self, old_value, new_value):
        ''' gets the list of sorted list of gates between two values '''
        v1, v2 = old_value, new_value
        if v1 is None or v2 is None:
            return []
        if v1 > v2:
            # swap
            v1, v2 = v2, v1

        gates = self._get_used_gates()
        result = set()
        # get the low gate
        for gate in gates:
            v = gate.value
            if v >= v1 and v < v2:
                # v1 is on the gate or below a the gate
                result.add(gate)
            if v == v2:
                # v2 is on the gate
                result.add(gate)
            if v > v2:
                # gate is outside the range - stop processing gates
                break
        return list(result)
    
    def _get_ranges_for_values(self, old_value, new_value):
        ''' gets the list of sorted list of gates between two values '''
        v1, v2 = old_value, new_value
        if v1 is None or v2 is None:
            return []
        if v1 > v2:
            # swap
            v1, v2 = v2, v1

        ranges = self._get_ranges()
        result = set()
        range : GateData.RangeInfo
        for range in ranges:
            if range.inrange(v1):
                result.add(range)
            if range.inrange(v2):
                result.add(range)
            
        return list(result)
    
    def _get_used_gates(self):
        ''' gets the list of active gates '''
        gates = [info for info in self._gate_item_map.values() if info.used]
        gates.sort(key = lambda x: x.value) # sort ascending
        gates = self._update_gate_sequence(gates)
        return gates
    
    def _get_used_indices(self):
        ''' gets the lif of activate gate indices '''
        return [info.index for info in self._gate_item_map.values() if info.used]

    def _get_ranges(self):
        ''' buils a sorted list of gate range objects filtered by used gates and by gate value '''
        range_list = [r for r in self._range_item_map.values() if r.g1 and r.g2 and r.g1.used and r.g2.used]
        range_list.sort(key = lambda x: x.g1.value)
        return range_list
    
    def _get_range_values(self):
        range_list = self._get_ranges()
        return [(r.g1.value,r.g2.value) for r in range_list]
    
    def _get_range_for_value(self, value):
        ''' returns (v1,v2,idx1,idx12) where v1 = lower range, v2 = higher range, idx1 = gate index for v1, idx2 = gate index for v2 '''
        info : GateData.RangeInfo
        #print ("------")
        for info in self._get_ranges():
            #print (f"{value:0.4f} - range: {info.index} {info.v1:0.4f} {info.v2:0.4f} in range: {info.inrange(value)}")
            if info.inrange(value):
                return info
        return None        
    
    def _get_filtered_range_value(self, range_info, value):
        ''' gets a range filtered value '''
        range_info : GateData.RangeInfo
        if value < range_info.v1 or value > range_info.v2:
            # not in range
            return None
        elif range_info.mode == GateRangeOutputMode.FilterOut:
            return None # filter the data out
        elif range_info.mode == GateRangeOutputMode.Fixed:
            # return the range's fixed value
            return range_info.fixed_value
        elif range_info.mode == GateRangeOutputMode.Ranged:
            # scale the value based on the range 
            range_value = gremlin.util.scale_to_range(value, target_min = range_info.v1, target_max=range_info.v2)
            return gremlin.util.scale_to_range(range_value, target_min = range_info.range_min, target_max=range_info.range_max)
        # use unchanged value
        return value

    def pre_process(self):
        # setup the pre-run activity
        self._last_value = None
        self._last_range = None 
        self._range_list = self._get_ranges()
        self._gate_list = self._get_used_items() # ordered list of gates by index and value

    def _trim_list(self, data, count_max):
        count = len(data)
        
        if count > 0 and count_max < count:
            trim_count = count - count_max
            for _ in range(trim_count):
                data.pop(0)
        return data
        


    def process_value(self, current_value):
        ''' processes an axis input value and returns all triggers collected since the last call based on the previous value
         
        :param: value - the input float value -1 to +1

        :returns: list of TriggerData objects containing the trigger information based on the gated axis configuration
           
        '''

        triggers = [] # returns all the triggers from the value since the last update
        last_value = self._last_value # last value processed 

        value_changed = last_value is None or last_value != current_value
        if not value_changed:
            return # nothing to do if the axix didn't move
        

        # figure out if we changed ranges
        current_range : GateData.RangeInfo = self._get_range_for_value(current_value) # gets the range of the current value
        last_range = self._last_range


        # get the list of crossed gates
        crossed_gates = self._get_gates_for_values(last_value, current_value)


        # process any the gate triggers
        gate : GateData.GateInfo

        for gate in crossed_gates:
            # check for one way gates we passed
            v = gate.value
            if gate.condition == GateCondition.OnCross:
                # process the gate
                pass
            elif gate.condition == GateCondition.OnCrossDecrease:
                # see if the gate was crossed with a value decrease
                if last_value < v:
                    continue # skip
            elif gate.condition == GateCondition.OnCrossIncrease:
                # see if the gate was crossed with a value increase
                if last_value > v:
                    continue # skip 

            td = TriggerData()
            td.gate = gate
            td.value = current_value
            td.mode = TriggerMode.GateCrossed
            triggers.append(td)
        
        # process the any range triggers
        if last_range and last_range.condition == GateCondition.OutsideRange:
            # trigger because the value left the prior range
            value = self._get_filtered_range_value(last_range, last_value)
            td = TriggerData()
            td.mode = TriggerMode.ValueOutOfRange
            td.value = value
            td.previous_value = last_value
            td.range = last_range
            td.is_range = True
            triggers.append(td)

        if current_range and current_range.condition == GateCondition.InRange:
            # trigger because value entered the range
            value = self._get_filtered_range_value(current_range, current_value)
            if value:
                td = TriggerData()
                td.mode = TriggerMode.ValueInRange
                td.value = value
                td.range = current_range
                td.is_range = True
                triggers.append(td)


        # update last values
        self._last_range = current_range
        self._last_value = current_value

        # update trigger lines
        for trigger in triggers:
            if trigger.is_range:
                self._trigger_range_lines.append(str(trigger))
            else:
                self._trigger_gate_lines.append(str(trigger))
        
        # keep it within max lines
        self._trigger_range_lines = self._trim_list(self._trigger_range_lines, self._trigger_line_count)
        self._trigger_gate_lines = self._trim_list(self._trigger_gate_lines, self._trigger_line_count)
        
        return triggers

        

    def to_xml(self):
        ''' export this configuration to XML '''
        node = ElementTree.Element("gate")

        # save gate data
        for info in self._get_used_gates():
            child = ElementTree.SubElement(node, "handle")
            child.set("condition", _gate_condition_to_name[info.condition])
            child.set("value", f"{info.value:0.{_decimals}f}")
            child.set("index", str(info.index))

        # save range data
        range_info : GateData.RangeInfo
        for range_info in self._range_item_map.values():
            child = ElementTree.SubElement(node,"range")
            child.set("index", str(range_info.index))
            child.set("condition",_gate_condition_to_name[range_info.condition])
            child.set("min_index", str(range_info._min_gate.index))
            child.set("max_index", str(range_info._max_gate.index))
            child.set("mode",_gate_range_to_name[range_info.mode])
            if range_info.range_max is not None:
                child.set("range_min",  f"{range_info.range_max:0.{_decimals}f}")
            if range_info.range_min is not None:
                child.set("range_max",  f"{range_info.range_min:0.{_decimals}f}")
            if range_info.fixed_value is not None:
                child.set("fixed_value", f"{range_info.fixed_value:0.{_decimals}f}")
            
            



        return node
    
    def _find_input_item(self):
        current = self._action_data
        while current and not isinstance(current, gremlin.base_profile.InputItem):
            current = current.parent
        return current

    def _new_item_data(self, is_action = True):
        ''' creates a new item data from the existing one '''
        current_item_data = self._find_input_item()
        item_data = gremlin.base_profile.InputItem(current_item_data)
        item_data._input_type = current_item_data._input_type
        item_data._device_guid = current_item_data._device_guid
        item_data._input_id = current_item_data._input_id
        item_data._is_action = is_action
        return item_data

    def from_xml(self, node):
        if not node.tag == "gate":
            syslog.error(f"GateData: Invalid node type {node.tag} {node}")
            return
    
        # read gate configurations 
        node_handles = gremlin.util.get_xml_child(node, "handle", multiple=True)
        gate_count = len(node_handles)
        for child in node_handles:

            gate_index = safe_read(child, "index", int, 0)
            gate_value = safe_read(child, "value", float, 0.0)
            gate_condition = safe_read(child, "condition", str, "")
            if not gate_condition in _gate_condition_from_name.keys():
                syslog.error(f"GateData: Invalid condition type {gate_condition} handle index: {gate_index}")
                return
            gate_condition = GateCondition.from_string(gate_condition)
            
            item_node = gremlin.util.get_xml_child(child, "action_containers")
            item_data = self._new_item_data()
            if item_node:
                item_node.tag = item_node.get("type")
                item_data.from_xml(item_node)

            gate_info = GateData.GateInfo(gate_index, gate_value, item_data, gate_condition, parent = self)
            self._gate_item_map[gate_index] = gate_info

        # read range configuration
        node_ranged = gremlin.util.get_xml_child(node, "range", multiple=True)
        for child in node_ranged:
            range_index = safe_read(child, "index", int, 0)
            range_condition = safe_read(child, "condition", str, "")
            if not range_condition in _gate_condition_from_name.keys():
                syslog.error(f"GateData: Invalid condition type {range_condition} range index: {range_index}")
                return
            range_condition = _gate_condition_from_name[range_condition]

            range_mode = safe_read(child, "mode", str, "")
            if not range_mode in _gate_range_from_name.keys():
                syslog.error(f"GateData: Invalid mode {range_mode} range index: {range_index}")
                return
            range_mode = _gate_range_from_name[range_mode]

            range_min_index = safe_read(child, "min_index", int, 0)
            range_max_index = safe_read(child, "max_index", int, 0)

            item_node = gremlin.util.get_xml_child(child, "range_containers")
            item_data = self._new_item_data()
            if item_node:
                item_node.tag = item_node.get("type")
                item_data.from_xml(item_node)

            min_gate = self._gate_item_map[range_min_index] 
            max_gate = self._gate_item_map[range_max_index] 
            range_min = safe_read(child,"range_min", float, -1.0)
            range_max = safe_read(child,"range_max", float, 1.0)

            if "fixed_value" in child.attrib:
                fixed_value = safe_read(child,"fixed_value", float, 0)
            else:
                fixed_value = None
            

            range_info = GateData.RangeInfo(range_index, min_gate, max_gate, item_data, range_condition, range_mode, range_min, range_max)
            if fixed_value is not None:
                range_info.fixed_value = fixed_value

            self._range_item_map[gate_index] = range_info
        

        # update the data
        self.update_steps(gate_count)
        

            
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
        self.gate = None 
        self.range = None
        self.previous_value = None # prior value
        self.is_range = False # true if a range trigger, false if a gate trigger

    def __str__(self):
        stub = f"[{self.mode.name}]"
        if self.mode in (TriggerMode.FixedValue, TriggerMode.ValueInRange, TriggerMode.ValueOutOfRange):
            return f"{stub} value: {self.value:0.{_decimals}f} range: {self.range.index+1}" #min: {self.range.v1:0.{_decimals}f} max: {self.range.v2:0.{_decimals}f}"
        elif self.mode == TriggerMode.RangedValue:
            return f"{stub} value: {self.value:0.{_decimals}f} range: {self.range.index+1}" # min: {self.range.v1:0.{_decimals}f} max: {self.range.v2:0.{_decimals}f} range min: {self.range.range_min:0.{_decimals}f} max: {self.range.range_max:0.{_decimals}f}"
        else:
            return f"{stub} value: {self.value:0.{_decimals}f} gate: {self.gate.display_index+1}" # gate value: {self.gate.value:0.{_decimals}f}"
        


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
        self.gate_data.stepsChanged.connect(self._update_steps)
        self.gate_data.valueChanged.connect(self._update_values)

        self.action_data = action_data
        self._range_readout_widgets = {} # holds reference to range widgets by index

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
        #self.slider.setValue([self.gate_data.min,self.gate_data.max]) # first value is the axis value
        self.slider.setMarkerValue(value)
        self.slider.valueChanged.connect(self._slider_value_changed_cb)
        self.slider.setMinimumWidth(200)
        self.slider.setStyleSheet("QSlider::active:{background: #8FBC8F;}")
        self.slider.handleRightClicked.connect(self._slider_handle_clicked_cb)
        self.slider.handleGrooveClicked.connect(self._slider_groove_clicked_cb)
        #self.slider.setStyleSheet(self.slider_css)

      
        self.container_slider_widget = QtWidgets.QWidget()
        self.container_slider_layout = QtWidgets.QGridLayout(self.container_slider_widget)
        self.container_slider_layout.addWidget(self.slider,0,0,-1,1)
        #self.container_slider_layout.addWidget(self.test)


        self.container_slider_layout.addWidget(QtWidgets.QLabel(" "),0,6)

        self.container_slider_layout.setColumnStretch(0,3)
        
        self.container_slider_widget.setContentsMargins(0,0,0,0)

      

        # configure trigger button
        self._configure_trigger_widget = QtWidgets.QPushButton("Configure")
        self._configure_trigger_widget.setIcon(gremlin.util.load_icon("fa.gear"))
        self._configure_trigger_widget.clicked.connect(self._trigger_cb)
    
        # self.clear_button_widget = ui_common.QDataPushButton()
        # self.clear_button_widget.setIcon(load_icon("mdi.delete"))
        # self.clear_button_widget.setMaximumWidth(20)
        # self.clear_button_widget.data = self.gate_data
        # self.clear_button_widget.clicked.connect(self._delete_cb)
        # self.clear_button_widget.setToolTip("Removes this entry")
        


        # self.duplicate_button_widget = ui_common.QDataPushButton()
        # self.duplicate_button_widget.setIcon(load_icon("mdi.content-duplicate"))
        # self.duplicate_button_widget.setMaximumWidth(20)
        # self.duplicate_button_widget.data = self.gate_data
        # self.duplicate_button_widget.clicked.connect(self._duplicate_cb)
        # self.duplicate_button_widget.setToolTip("Duplicates this entry")

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

        # self.container_description_widget = QtWidgets.QWidget()
        # self.container_description_layout = QtWidgets.QVBoxLayout(self.container_description_widget)
        # self.container_description_layout.addWidget(self.action_description_widget)
        # self.container_description_layout.addWidget(self.condition_description_widget)
        # self.container_description_widget.setContentsMargins(0,0,0,0)


        # self.container_selector_layout.addWidget(self.clear_button_widget)
        # self.container_selector_layout.addWidget(self.duplicate_button_widget)

        # self.main_layout.addWidget(self.container_selector_widget,0,0)
        
        
        # self.main_layout.addWidget(self.container_description_widget,1,0)

        self.main_layout.addWidget(self.container_slider_widget,1,0)
        # self.main_layout.addWidget(self.duplicate_button_widget,1,1)
        # self.main_layout.addWidget(self.clear_button_widget,1,2)

        self.main_layout.addWidget(self.container_gate_widget,2,0)
        self.main_layout.addWidget(self.container_range_widget,3,0)
        self.main_layout.addWidget(self.container_steps_widget,4,0)
        self.main_layout.addWidget(self.container_output_widget,5,0)
   
        self.main_layout.setVerticalSpacing(0)

        # hook the joystick input for axis input repeater
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)

        # update visible container for the current mode
        #self._update_conditions()
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
            
            label_widget = QtWidgets.QLabel(f"Gate {info.display_index+1}:")
            sb_widget = ui_common.DynamicDoubleSpinBox(data = index)
            sb_widget.setMinimum(-1.0)
            sb_widget.setMaximum(1.0)
            sb_widget.setDecimals(self.decimals)
            sb_widget.setSingleStep(self.single_step)
            sb_widget.setValue(info.value)
            sb_widget.valueChanged.connect(self._gate_value_changed_cb)
            self._gate_value_widget_list.append(sb_widget)

            grab_widget = ui_common.QDataPushButton()
            grab_widget.data = (info, sb_widget) # gate and control to update
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
        max_col = self.container_gate_layout.columnCount() + 1
        self.container_gate_layout.addWidget(QtWidgets.QLabel(" "), 0,max_col)            
        self.container_gate_layout.setColumnStretch(max_col, 3)

        # ranges between the gates
        gremlin.util.clear_layout(self.container_range_layout)
        range_list = self.gate_data.getGateRanges()
        col = 0
        row = 0
        self._range_readout_widgets = {}
        range_info : GateData.RangeInfo
        count = 0
        for range_info in range_list:
            index = range_info.index
            g1 : GateData.GateInfo = range_info.g1
            g2 : GateData.GateInfo= range_info.g2
            
            label_widget = QtWidgets.QLabel(f"Range {index+1}:")

            range_widget = ui_common.QDataLineEdit()
            range_widget.setReadOnly(True)
            range_widget.setText(f"[{g1.index+1}:{g2.index+1}] {g1.value:0.{self.decimals}f} to {g2.value:0.{self.decimals}f}")
            self._range_readout_widgets[index] = range_widget
            range_widget.data = (range_info, range_widget)
            range_info.valueChanged.connect(self._range_changed_cb)
            
            
            setup_widget = ui_common.QDataPushButton()
            setup_widget.data = index
            setup_widget.setIcon(setup_icon)
            setup_widget.setMaximumWidth(20)
            setup_widget.clicked.connect(self._setup_range_cb)
            setup_widget.setToolTip(f"Setup actions for range {index}")

            self.container_range_layout.addWidget(label_widget, row, col)
            self.container_range_layout.addWidget(range_widget, row, col + 1)
            self.container_range_layout.addWidget(setup_widget, row, col + 2)

            count += 1

            col += 3
            if count > 4:
                row+=1
                col = 0
                count = 0

        max_col = self.container_range_layout.columnCount()
        self.container_range_layout.addWidget(QtWidgets.QLabel(" "), 0,max_col)            
        self.container_range_layout.setColumnStretch(max_col, 3)


    def _range_changed_cb(self):
        ''' called when range data changes '''
        range_info = self.sender()
        range_widget = self._range_readout_widgets[range_info.index]
        g1 : GateData.GateInfo = range_info.g1
        g2 : GateData.GateInfo= range_info.g2
        ''' updates the display for a range item '''
        range_widget.setText(f"[{g1.index+1}:{g2.index+1}] {g1.value:0.{self.decimals}f} to {g2.value:0.{self.decimals}f}")
        
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

    @QtCore.Slot(float)
    def _slider_groove_clicked_cb(self, value):
        ''' fired when the user clicked on the groove - adds a gate at that location '''
        gates_indices = self.gate_data.getUsedGatesIndices()
        for index in range(20):
            if not index in gates_indices:
                break
        gate = self.gate_data.getGate(index)
        gate.value = value
        
        self._update_gates_ui()
        self._update_ui()



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
        # update ui
        self._update_gates_ui()

    def _set_slider_gate_value(self, index, value):
        ''' sets a gate value on the slider '''
        values = list(self.slider.value())
        if value != values[index]:
            values[index] = value
            self.slider.setValue(values)


    @QtCore.Slot()
    def _grab_cb(self):
        ''' grab the min value from the axis position '''
        info : GateData.GateInfo
        info, widget = self.sender().data  # the button's data field contains the widget to update
        value = self._axis_value
        info.value = value
        self._set_slider_gate_value(info.index, value)
        

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

    QtCore.Slot()
    def _delete_cb(self):
        ''' delete requested '''
        self.delete_requested.emit(self.gate_data)

    QtCore.Slot()
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

        # holds the output value
        self.output_range_trigger_widget = QtWidgets.QPlainTextEdit()
        self.output_range_trigger_widget.setReadOnly(True)
        self.output_gate_trigger_widget = QtWidgets.QPlainTextEdit()
        self.output_gate_trigger_widget.setReadOnly(True)
        
        self.container_output_widget = QtWidgets.QWidget()
        self.container_output_widget.setContentsMargins(0,0,0,0)
        self.container_output_layout = QtWidgets.QGridLayout(self.container_output_widget)

        self.container_output_layout.addWidget(QtWidgets.QLabel("Range events:"),0,0)
        self.container_output_layout.addWidget(QtWidgets.QLabel("Gate events:"),0,1)
        self.container_output_layout.addWidget(self.output_range_trigger_widget,1,0)
        self.container_output_layout.addWidget(self.output_gate_trigger_widget,1,1)


    def _create_steps_ui(self):
        ''' creates the steps UI '''
        self.sb_steps_widget = QtWidgets.QSpinBox()
        self.sb_steps_widget.setRange(1, 20)
        self.sb_steps_widget.setValue(self.gate_data.gates)
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

        self.container_steps_layout.addWidget(QtWidgets.QLabel("Number of gates:"))
        self.container_steps_layout.addWidget(self.sb_steps_widget)
        self.container_steps_layout.addWidget(self.set_steps_widget)
        self.container_steps_layout.addWidget(self.normalize_widget)
        self.container_steps_layout.addWidget(self.normalize_reset_widget)
        self.container_steps_layout.addWidget(QtWidgets.QLabel("Right-click range to add new gate, right click gate for configuration"))
        self.container_steps_layout.addStretch()

    @QtCore.Slot()
    def _set_steps_cb(self):
        ''' sets the number of steps '''
        value = self.sb_steps_widget.value()
        if self.gate_data.gates != value:
            self._update_steps()


    @QtCore.Slot()
    def _normalize_cb(self):
        ''' normalize button  '''
        value = self.sb_steps_widget.value()
        self.gate_data.gates = value        
        self.gate_data.normalize_steps(True)


    def _normalize_reset_cb(self):
        ''' normalize reset button  '''
        value = self.sb_steps_widget.value()
        self.gate_data.gates = value         
        self.gate_data.normalize_steps(False)       


    @QtCore.Slot()
    def _update_steps(self):
        ''' updates gate steps on the widget and their positions '''
        self._update_gates_ui() # update gate manual update UI
        self._update_values()
        

    @QtCore.Slot()
    def _update_values(self):
        ''' called when gate data values are changed '''
        values = self.gate_data.getGateValues()
        if values != self.slider.value():
            with QtCore.QSignalBlocker(self.slider):
                self.slider.setValue(values)

    def _update_output_value(self):
        triggers = self.gate_data.process_value(self._axis_value)
        self.output_range_trigger_widget.setPlainText(self.gate_data.trigger_range_text)
        # scroll to bottom
        vbar = self.output_range_trigger_widget.verticalScrollBar()
        vbar.setValue(vbar.maximum())

        self.output_gate_trigger_widget.setPlainText(self.gate_data.trigger_gate_text)
        # scroll to bottom
        vbar = self.output_gate_trigger_widget.verticalScrollBar()
        vbar.setValue(vbar.maximum())
        




    QtCore.Slot()
    def _min_changed_cb(self):
        value = self.sb_min_widget.value()
        self.gate_data.min = value
        lv = list(self.slider.value())
        lv[0] = value
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setValue(lv)
        
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


    def _update_ui(self):
        ''' updates visibility of UI components based on the active options '''
        # update the slider configuration 
        self.slider.setValue(self.gate_data.getGateValues())

        self._update_output_value()


    def deleteGate(self, data):
        ''' remove the gat fromt his widget '''
        self.gate_data.deleteGate(data)
        self._update_ui()

 
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
        
            
        
            

class ActionContainerUi(QtWidgets.QDialog):
    """UI to setup the individual action trigger containers and sub actions """

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz

    def __init__(self, gate_data, index, is_range = False, parent=None):
        '''
        :param: gate_data = the gate data block 
        :item_data: the InputItem data block holding the container and input device configuration for this gated input
        :index: the gate number of the gated input - there will at least be two for low and high - index is an integer 
        '''
        
        super().__init__(parent)

        self._index = index
        self._gate_data : GateData = gate_data
        if is_range:
            self._info = gate_data.getRange(index)
        else:
            self._info = gate_data.getGate(index)
    
        self._item_data = self._info.item_data
        self._is_range = is_range

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        min_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Minimum
        )
        exp_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Minimum
        )        

        # Actual configuration object being managed
        self.setMinimumWidth(600)
        self.setMinimumWidth(800)

        

        if is_range:
            # range has an output mode for how to handle the output value for the range
            self.output_widget = QtWidgets.QComboBox()
            self.output_container_widget = QtWidgets.QWidget()
            self.output_container_widget.setContentsMargins(0,0,0,0)
            self.output_container_layout = QtWidgets.QHBoxLayout(self.output_container_widget)
            self.output_container_layout.addWidget(QtWidgets.QLabel("Mode:"))
            self.output_container_layout.addWidget(self.output_widget)
            self.output_container_layout.addStretch()
            

            self._gate_data.populate_output_widget(self.output_widget, default = self._info.output_mode)
            self.output_widget.currentIndexChanged.connect(self._output_mode_changed_cb)

            # ranged data
            self.container_output_range_widget = QtWidgets.QWidget()
            self.container_output_range_layout = QtWidgets.QHBoxLayout(self.container_output_range_widget)
            self.container_output_range_widget.setContentsMargins(0,0,0,0)
            
            self.sb_range_min_widget = ui_common.DynamicDoubleSpinBox()
            self.sb_range_min_widget.setMinimum(-1.0)
            self.sb_range_min_widget.setMaximum(1.0)
            self.sb_range_min_widget.setDecimals(gate_data.decimals)
            self.sb_range_min_widget.setSingleStep(self.single_step)
            self.sb_range_min_widget.setValue(gate_data.range_min)
            self.sb_range_min_widget.valueChanged.connect(self._range_min_changed_cb)

            self.sb_range_max_widget = ui_common.DynamicDoubleSpinBox()
            self.sb_range_max_widget.setMinimum(-1.0)
            self.sb_range_max_widget.setMaximum(1.0)        
            self.sb_range_max_widget.setDecimals(self.decimals)
            self.sb_range_max_widget.setSingleStep(self.single_step)
            self.sb_range_max_widget.setValue(gate_data.range_max)

            self.sb_range_max_widget.valueChanged.connect(self._range_max_changed_cb)

            self.sb_fixed_value_widget = ui_common.DynamicDoubleSpinBox()
            self.sb_fixed_value_widget.setMinimum(-1.0)
            self.sb_fixed_value_widget.setMaximum(1.0)        
            self.sb_fixed_value_widget.setDecimals(gate_data.decimals)
            self.sb_fixed_value_widget.setSingleStep(self.single_step)
            self.sb_fixed_value_widget.setValue(gate_data.fixed_value)

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


        self.condition_widget = QtWidgets.QComboBox()
        self.condition_description_widget = QtWidgets.QLabel()

        self.trigger_container_widget = QtWidgets.QWidget()
        self.trigger_condition_layout = QtWidgets.QHBoxLayout(self.trigger_container_widget)

        if is_range:
            self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Range {index + 1} Configuration:"))
        else:
            self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Gate {index + 1} Configuration:"))

            # gates can be deleted (ranges cannot since they are defined by gates)
            self.clear_button_widget = ui_common.QDataPushButton()
            self.clear_button_widget.setIcon(load_icon("mdi.delete"))
            self.clear_button_widget.setMaximumWidth(20)
            self.clear_button_widget.data = self._info
            self.clear_button_widget.clicked.connect(self._delete_cb)
            self.clear_button_widget.setToolTip("Removes this entry")
        
        #self.trigger_condition_layout.addWidget(self.action_widget)
        self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Condition:"))
        self.trigger_condition_layout.addWidget(self.condition_widget)
        self.trigger_condition_layout.addWidget(self.condition_description_widget)
        self.trigger_condition_layout.addStretch()

        if not is_range:
            self.trigger_condition_layout.addWidget(self.clear_button_widget)

        from gremlin.ui.device_tab import InputItemConfiguration
        self.container_widget = InputItemConfiguration(self._item_data)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(self.trigger_container_widget)
        if is_range:
            self.main_layout.addWidget(self.output_container_widget)
        self.main_layout.addWidget(self.container_widget)   
        

        self._update_ui()

    QtCore.Slot()
    def _delete_cb(self):
        ''' delete requested '''
        self._remove_gate(self._info)

    def _remove_gate(self, data):
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
        self.delete_requested.emit(self._info)
        self.close()

    


    QtCore.Slot()
    def _range_min_changed_cb(self):
        value = self.sb_range_min_widget.value()
        self._info.range_min = value
        

    QtCore.Slot()
    def _range_max_changed_cb(self):
        self._info.range_max = self.sb_range_max_widget.value()

    @QtCore.Slot()
    def _output_mode_changed_cb(self):
        ''' change the output mode of a range'''
        value = self.output_widget.currentData()
        self._info.output_mode = value


    
    @QtCore.Slot()
    def _condition_changed_cb(self):
        self._info.condition = self.condition_widget.currentData()

    def _update_ui(self):
        ''' updates controls based on the options '''
        if self._is_range:
            # range conditions
            conditions = (GateCondition.InRange, GateCondition.OutsideRange)

            fixed_visible = self._info.output_mode == GateRangeOutputMode.Fixed
            range_visible = self._info.output_mode == GateRangeOutputMode.Ranged

            self.container_fixed_widget.setVisible(fixed_visible)
            self.container_output_range_widget.setVisible(range_visible)


        else:
            # gate conditions
            conditions = (GateCondition.OnCross, GateCondition.OnCrossIncrease, GateCondition.OnCrossDecrease)
        
        with QtCore.QSignalBlocker(self.condition_widget):
            self.condition_widget.clear()
            for condition in conditions:
                self.condition_widget.addItem(GateCondition.to_display_name(condition), condition)
            condition = self._info.condition
            index = self.condition_widget.findData(condition)
            self.condition_widget.setCurrentIndex(index)
            self.condition_description_widget.setText(GateCondition.to_description(condition))

