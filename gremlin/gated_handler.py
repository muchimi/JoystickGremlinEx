

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
from lxml import etree as ElementTree
from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
from gremlin.input_types import InputType
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.macro
from gremlin.ui import ui_common
import gremlin.ui.input_item
import gremlin.ui.ui_common
import gremlin.util
from gremlin.util import *
from gremlin.types import *

from enum import Enum, auto
from gremlin.macro_handler import *
import gremlin.util

class DisplayMode(Enum):
    ''' display mode for ranges and gate data '''
    Normal = 0
    Percent = 1
    OneOne = 2

    @staticmethod
    def to_string(mode):
        if mode in _display_mode_to_string.keys():
            return _display_mode_to_string[mode]
        return "normal"
    
    @staticmethod
    def to_enum(mode):
        if mode in _display_mode_to_enum.keys():
            return _display_mode_to_enum[mode]
        return DisplayMode.Normal
    

_display_mode_to_string = {
    DisplayMode.Normal: "normal",
    DisplayMode.Percent: "percent",
    DisplayMode.OneOne: "oneone"
}

_display_mode_to_enum = {
    "normal" : DisplayMode.Normal,
    "percent" : DisplayMode.Percent,
    "oneone" : DisplayMode.OneOne
}

    

class GateCondition(Enum):
    ''' gate action trigger conditions'''
    # RANGE specific conditions (between gates)
    InRange = auto() # triggers when the value is in range
    OutsideRange = auto() # triggers when the value is outside the range
    # GATE specific conditions (when crossing a gate)
    OnCross = auto() # value crosses a gate boundary in any direction
    OnCrossIncrease = auto() # value crosses the gate and increased in value
    OnCrossDecrease = auto() # value crosses the gate and decreased in value
    EnterRange = auto() # value enters the range
    ExitRange = auto() # value exits the range

    @staticmethod
    def to_description(condition):
        return _gate_condition_description[condition]
    
    @staticmethod
    def to_string(condition):
        return _gate_condition_to_name[condition]
    
    @staticmethod
    def to_enum(value):
        return _gate_condition_to_enum[value]
    
    @staticmethod
    def to_display_name(condition):
        return _gate_condition_to_display_name[condition]
    

class GateRangeOutputMode(Enum):
    ''' controls for ranged outputs what range is output given the gate range '''
    Normal = auto() # output range is the same as the input value
    Ranged = auto() # scales the output to a new range based on the min/max specified for the gate
    Fixed = auto() # output a fixed value
    FilterOut = auto() # sends no data
    # Scaled = auto() # the input value is rescaled to the output range - using the input value as the start value
    Rebased = auto() # rebased, the range is always -1 to +1 within the range, output is scaled as normal based on the output range


    @staticmethod
    def to_description(range):
        return _gate_range_description[range]
    
    @staticmethod
    def to_string(range):
        return _gate_range_to_string[range]
    
    @staticmethod
    def from_string(value):
        return _gate_range_to_enum[value]
    
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
    RangeEnter = auto() # fires when the value enters the range
    RangeExit = auto() # fires when the value exits the range

    @staticmethod
    def to_string(value):
        return _trigger_mode_to_string[value]
    
    @staticmethod
    def to_enum(value):
        return _trigger_mode_to_enum[value]
    
        
    @staticmethod
    def to_display_name(value):
        return _trigger_mode_to_display_name[value]

_trigger_mode_to_string = {
    TriggerMode.Value: "value",
    TriggerMode.RangedValue: "ranged_value",
    TriggerMode.ValueInRange: "value_in_range",
    TriggerMode.ValueOutOfRange: "value_out_of_range",
    TriggerMode.GateCrossed: "gate_crossed",
    TriggerMode.FixedValue: "fixed_value",
    TriggerMode.RangeEnter: "range_enter",
    TriggerMode.RangeExit: "range_exit"
}

_trigger_mode_to_display_name = {
    TriggerMode.Value: "Value",
    TriggerMode.RangedValue: "Ranged Value",
    TriggerMode.ValueInRange: "In Range",
    TriggerMode.ValueOutOfRange: "Out of Range",
    TriggerMode.GateCrossed: "Gate Crossed",
    TriggerMode.FixedValue: "Fixed Value",
    TriggerMode.RangeEnter: "Range Enter",
    TriggerMode.RangeExit: "Range Exit"
}


_trigger_mode_to_enum = {
     "value" : TriggerMode.Value,
    "ranged_value": TriggerMode.RangedValue ,
    "value_in_range": TriggerMode.ValueInRange,
    "value_out_of_range": TriggerMode.ValueOutOfRange,
    "gate_crossed": TriggerMode.GateCrossed,
    "fixed_value": TriggerMode.FixedValue,
    "range_enter": TriggerMode.RangeEnter,
    "range_exit": TriggerMode.RangeExit,
}
    

_decimals = 5
_single_step = 0.001
 


_gate_condition_to_name = {
    GateCondition.InRange: "in_range",
    GateCondition.OutsideRange: "outside_range",
    GateCondition.OnCross: "cross",
    GateCondition.OnCrossIncrease: "cross_inc",
    GateCondition.OnCrossDecrease: "cross_dec",
    GateCondition.EnterRange: "enter_range",
    GateCondition.ExitRange: "exit_range"
}


_gate_condition_to_display_name = {
    GateCondition.InRange: "In Range",
    GateCondition.OutsideRange: "Outside of Range",
    GateCondition.OnCross: "Crossed",
    GateCondition.OnCrossIncrease: "Cross (inc)",
    GateCondition.OnCrossDecrease: "Cross (dec)",
    GateCondition.EnterRange: "Enter Range",
    GateCondition.ExitRange: "Exit Range"
}

_gate_condition_to_enum = {
    "in_range": GateCondition.InRange,
    "outside_range": GateCondition.OutsideRange,
    "cross": GateCondition.OnCross,
    "cross_inc": GateCondition.OnCrossIncrease,
    "cross_dec": GateCondition.OnCrossDecrease,
    "enter_range" : GateCondition.EnterRange,
    "exit_range" : GateCondition.ExitRange
}

_gate_condition_description = {
    GateCondition.InRange: "Triggers whenever the input value is in range",
    GateCondition.OutsideRange: "Triggers whenever the input value is outside the range",
    GateCondition.OnCross: "Triggers when the input crosses a gate",
    GateCondition.OnCrossDecrease: "Triggers when the input crosses a gate (crossing from the right/above)",
    GateCondition.OnCrossIncrease: "Triggers when the input crosses a gate (crossing from the left/below)",
    GateCondition.EnterRange: "Triggers when the input value enters the range",
    GateCondition.ExitRange: "Triggers when the input value exits the range"
}

_gate_range_to_string = {
    GateRangeOutputMode.Normal: "normal",
    GateRangeOutputMode.Fixed: "fixed",
    GateRangeOutputMode.Ranged: "ranged",
    GateRangeOutputMode.FilterOut: "filter",
    #GateRangeOutputMode.Scaled: "scale",
    GateRangeOutputMode.Rebased: "rebase"
}

_gate_range_to_enum = {
    "normal": GateRangeOutputMode.Normal ,
    "fixed": GateRangeOutputMode.Fixed,
    "ranged": GateRangeOutputMode.Ranged,
    "filter": GateRangeOutputMode.FilterOut,
    #"scale" : GateRangeOutputMode.Scaled,
    "rebase" : GateRangeOutputMode.Rebased
}


_gate_range_to_display_name = {
    GateRangeOutputMode.Normal: "Normal",
    GateRangeOutputMode.Fixed: "Output Fixed Value",
    GateRangeOutputMode.Ranged: "Ranged",
    GateRangeOutputMode.FilterOut: "Filtered (no output)",
    #GateRangeOutputMode.Scaled: "Scaled to Interval",
    GateRangeOutputMode.Rebased: "Rebased to [-1,1]"
}



_gate_range_description = {
    GateRangeOutputMode.Normal: "The output value is unchanged",
    GateRangeOutputMode.Fixed: "Sends a fixed value while the input is in range",
    GateRangeOutputMode.Ranged: "The output is scaled based on the min/max defined for this range",
    GateRangeOutputMode.FilterOut: "Filters the output data, no data will be sent while the input is in this range)",
    #GateRangeOutputMode.Scaled: "Scales the input to the specified output range of the current interval",
    GateRangeOutputMode.Rebased: "The interval defines a new -1 +1 range and the output value is scaled within that interval"
}

def _is_close(a, b, tolerance = 0.0001):
    ''' compares two floating point numbers with approximate precision'''
    return math.isclose(a, b, abs_tol=tolerance)


class GateInfo():
    ''' holds gate data information '''
    

    def __init__(self, id = None, value = None, profile_mode = None, item_data = None, condition = GateCondition.OnCross, parent = None, is_default = False, delay = 250, slider_index = None):

        assert parent is not None, "Gates must be parented to a GateData object " # = must provide this parameter
        self.parent : GateData = parent

        assert value is not None, "Gate must have a value"
        self.is_default = is_default # default gate setups (not saved)
        self._id = get_guid() if id is None else id
        assert isinstance(self._id,str)
        value = gremlin.util.clamp(value, -1, 1)
        self._value = value
        self.condition = condition
        self.profile_mode = profile_mode

        self.item_data_map = {}
        if item_data is not None:
            self.item_data_map[condition] = item_data

        self.used = True
        self.slider_index = slider_index # index of the gate in the slider
        self.delay = delay  # delay in milliseconds for the trigger duration between a press and release

    @property
    def has_containers(self):
        ''' true if the gate has any mappings in any mode '''
        return self.container_count > 0

    @property
    def container_count(self) -> int:
        ''' gets the container count '''
        return sum(len(item_data.containers) for item_data in self.item_data_map.values())

    @staticmethod
    def copy_from(info):
        gi = GateInfo(value = info.value,
                      profile_mode = info.profile_mode,
                      condition = info.condition,
                      parent = info.parent,
                      is_default = info.is_default,
                      delay=info.delay,
                      auto_register = False)
        gi.item_data_map = info.item_data_map
        return gi


    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, data):
        self.setValue(data, True)

    def setValue(self, data, emit = False):
        ''' sets the value '''
        if data == -1:
            pass
        if data < self.parent.range_min:
            data = self.parent.range_min
        if data > self.parent.range_max:
            data = self.parent.range_max
        if data != self._value:
            self._value = data
            self.parent._update_gate_index() # re-index based on value so the gate is always in sequence
            if emit:
                eh = GateAxisEventHandler()
                eh.gateinfo_valueChanged.emit(self)


        

    def itemData(self, condition : GateCondition):
        ''' gets the inputitem for the given condition '''
        if not condition in self.item_data_map.keys():
            data = self.parent._new_item_data()
            data.input_type = InputType.JoystickButton
            data.input_id = 1
            self.item_data_map[condition] = data
        return self.item_data_map[condition]

    def setItemData(self, condition, value):
        self.item_data_map[condition] = value
            


    @property
    def condition(self):
        return self._condition
    @condition.setter
    def condition(self, value):
        assert value in [c for c in GateCondition]
        self._condition = value

    @property
    def id(self):
        return self._id
    @id.setter
    def id(self, value):
        assert isinstance(value,str)
        self._id = value


    def __lt__(self, other):
        return self._value < other._value
    
    @property
    def display_value(self):
        mode = self.parent.display_mode if self.parent is not None else DisplayMode.Normal
        if mode == DisplayMode.Normal:
            value = gremlin.util.scale_to_range(self.value,
                                                self.parent.range_min,
                                                self.parent.range_max,
                                                self.parent.display_range_min,
                                                self.parent.display_range_max
                                                )
        elif mode == DisplayMode.Percent:
            value = (self.value + 1) / 2.0 * 100.0
        elif mode == DisplayMode.OneOne:
            value = gremlin.util.scale_to_range(self.value,
                                                self.parent.range_min,
                                                self.parent.range_max,
                                                -1.0,
                                                1.0
                                                )
        return value
    
    def __str__(self):
        
        mode = self.parent.display_mode if self.parent is not None else DisplayMode.Normal
        if mode == DisplayMode.Normal:
            rng = self.parent.display_range_max - self.parent.display_range_min
            decimals = 0 if rng > 2 else 3
        elif mode == DisplayMode.OneOne:
            decimals = 3
        else: # percent
            decimals = 2

        return f"Gate {self.display_index} [{self.index}]  {self.display_value():0.{decimals}f} cond: {self.condition} used: {self.used}"



class RangeInfo():
    

    def __init__(self, id, min_gate, max_gate, profile_mode = None, item_data = None, condition = GateCondition.EnterRange,
                    mode = GateRangeOutputMode.Normal, parent = None,  is_default = False):
        

        assert parent is not None, "Ranges must be parented to a GateData object " # = must provide this parameter
        #assert min_gate is not None and max_gate is not None, "Gates must be provided on range object"
        self.parent : GateData = parent
        self._id = id
        self._is_default = is_default
        self.profile_mode = profile_mode
        self._output_mode = None
        self._output_range_min = None
        self._output_range_max = None
        self._condition = None
        self.condition = condition
        


        self.item_data_map = {}
        if item_data is not None:
            self.item_data_map[condition] = item_data

        assert id is not None, "ID must be provided"
        assert min_gate is not None,"Min gate must be provided "
        assert max_gate is not None,"Max gate must be provided "
        

        g1 = self._get_gate(min_gate.id)
        assert g1 is not None, "Min gate not registered"

        g2 = self._get_gate(max_gate.id)
        assert g2 is not None, "Max gate not registered"
        
        self._min_gate_id = min_gate.id
        self._max_gate_id = max_gate.id


        

        eh = GateAxisEventHandler()
        eh.gateinfo_valueChanged.connect(self._gate_value_changed_cb)
        self.item_data_map = {}
        if item_data is not None:
            self.item_data_map[condition] = item_data
        #self.item_data = item_data
        self.mode = mode # output mode determines what we do with the input data
        self._fixed_value = None # fixed value to output for this range if the condition is Fixed
        self._swap_gates()

    @property
    def has_containers(self):
        ''' true if the range has any mappings in any mode '''
        return self.container_count > 0
    
    @property
    def container_count(self) -> int:
        ''' gets the container count '''
        return sum(len(item_data.containers) for item_data in self.item_data_map.values())

    def copy_from(self, rng):
        ''' copies data from another range object '''
        self.profile_mode = rng.profile_mode
        self._condition = rng._condition
        self._output_mode = rng._output_mode
        self._fixed_value = rng._fixed_value
        self.is_default = rng.is_default
        self._max_gate_id = rng._max_gate_id
        self._min_gate_id = rng._min_gate_id
        self.item_data_map = rng.item_data_map


    def _get_gate(self, id):
        gate = self.parent.getGate(id)
        if gate is None:
            gates =self.parent.getGates(id)
            syslog.info(f"Gate not found: {id}")
            for g in gates:
                syslog.info(f"\tGate {g.id} {g.value}")
            return None
        return gate

    def itemData(self, condition : GateCondition):
        ''' gets the inputitem for the given condition '''
        if not condition in self.item_data_map.keys():
            data = self.parent._new_item_data()
            # action_data = self.parent._action_data
            self.item_data_map[condition] = data
        return self.item_data_map[condition]

    def setItemData(self, condition, value):
        self.item_data_map[condition] = value
            
    
    @property
    def _gate_min(self):
        return self._get_gate(self._min_gate_id)
    
    @property
    def _gate_max(self):
        return self._get_gate(self._max_gate_id)

            
    @property
    def range_min(self):
        ''' current min range '''
        return self._gate_min.value
    
    @range_min.setter
    def range_min(self, value):
        self._gate_min.value = value
    
    @property
    def range_max(self):
        ''' current max range '''
        return self._gate_max.value
    
    @range_max.setter
    def range_max(self, value):
        self._gate_max.value = value

    @property
    def output_range_min(self):
        ''' output range min '''
        if self._output_range_min is None:
            return self._gate_min.value
        return self._output_range_min
    
    @output_range_min.setter
    def output_range_min(self, value):
        self._output_range_min = value
    
    @property
    def output_range_max(self):
        ''' output range max '''
        if self._output_range_max is None:
            return self._gate_max.value
        return self._output_range_max
    
    @output_range_max.setter
    def output_range_max(self, value):
        self._output_range_max = value

    def range(self):
        ''' gets the current range'''
        return (self._gate_min.value,self._gate_max.value)
    
    def output_range(self):
        ''' gets the output range '''
        return (self.output_range_min, self.output_range_max)
    
    @property
    def id(self):
        return self._id
    @id.setter
    def id(self, value):
        self._id = value

    @property
    def is_default(self):
        return self._is_default
    
    @is_default.setter
    def is_default(self, value):
        self._is_default = value

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
        return self._gate_min
    @g1.setter
    def g1(self, value):
        if self._min_gate_id is None or self._min_gate_id != value.id:
            self._min_gate_id = value.id
            self._swap_gates()
            self._gate_value_changed_cb(self._gate_min)
    @property
    def g2(self):
        return self._gate_max
    @g2.setter
    def g2(self, value):
        if self._max_gate_id is None or self._max_gate_id != value.id:
            self._max_gate_id = value.id
            self._swap_gates()
            self._gate_value_changed_cb(self._gate_max)

    @QtCore.Slot(GateInfo)
    def _gate_value_changed_cb(self, gate):
        ''' occurs when either gate values change or gates are changed '''
        if gate.id == self._min_gate_id or gate.id == self._max_gate_id:
            eh = GateAxisEventHandler()
            eh.rangeinfo_valueChanged.emit(self)



    @property
    def v1(self):
        ''' gets the min value of the range '''
        if self._min_gate_id:
            return self._gate_min.value
        return None
    
    @property
    def v2(self):
        ''' gets the max value of the range '''
        if self._max_gate_id:
            return self._gate_max.value
        return None
    
    @property
    def v1_display(self):
        if self._min_gate_id:
            return self._gate_min.display_value
        return None
    
    @property
    def v2_display(self):
        if self._max_gate_id:
            return self._gate_max.display_value
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
        if self._gate_max and self._gate_min:
            if self._gate_max.value < self._gate_min.value:
                self._min_gate_id, self._max_gate_id = self._min_gate_id, self._max_gate_id

        if self._output_range_max is not None and self._output_range_min is not None:
            if self._output_range_max < self._output_range_min:
                self._output_range_max, self._output_range_min = self._output_range_min, self._output_range_max
            
                

    def range_gates(self):
        ''' returns the range gates'''
        return (self._gate_min, self._gate_max)
    
    def range_values(self):
        ''' returns the tuple of range values '''
        if self._gate_max and self._gate_min:
            return (self._gate_max.value, self._gate_min.value)
        return (None, None)
    
    def range_display(self):
        ''' gets a range display string for this range '''
        
        mode = self.parent.display_mode if self.parent is not None else DisplayMode.Normal
        if mode == DisplayMode.Normal:
            rng = self.parent.display_range_max - self.parent.display_range_min
            decimals = 0 if rng > 2 else 3
            
        elif mode == DisplayMode.OneOne:
            decimals = 3
        else: # percent
            decimals = 2

        return f"{self.v1_display:0.{decimals}f},{self.v2_display:0.{decimals}f}"

    def pair(self):
        return (self.v1, self.v2)
    
    def to_percent(self, value):
        ''' converts the value to a percent for this range '''
        v1 = self.v1
        v2 = self.v2
        return gremlin.util.scale_to_range(value,v1,v2,0,100)

    def __str__(self):
        if self.v1 is None or self.v2 is None:
            rr = f"N/A"
        else:
            rr = self.range_display()
        return f"Range [{rr}] mode: {self.mode}  id: {self.id}"
    
    def __eq__(self, other):
        ''' compares to range objects by range value '''
        if other is None:
            return False
        return _is_close(self.v1, other.v1) and _is_close(self.v2, other.v2)
    
    def __hash__(self):
        return hash(self.range_values())
    

@gremlin.singleton_decorator.SingletonDecorator
class GateAxisEventHandler(QtCore.QObject):
    ''' handler class for gate axis events '''
    gatedata_stepsChanged = QtCore.Signal(object) # signals that steps (gate counts) have changed  (gatedata)
    gateddata_valueChanged = QtCore.Signal(object) # signals when the gate data changes (gatedata)

    gateinfo_valueChanged = QtCore.Signal(object) # fires when the value changes
    rangeinfo_valueChanged = QtCore.Signal(object) # fires when either of the gate values change

    def __init__(self):
        super().__init__()
    

class GateData():
    ''' holds gated information for an axis
    
        this object knows how to load and save itself to XML
    '''


    def __init__(self,
                 profile_mode, # required - profile mode this applies to (can also be set from XML)
                 action_data, # required - action data block (usually the object that contains a functor)
                 min = -1.0,
                 max = 1.0,
                 condition = GateCondition.OnCross,
                 mode = GateRangeOutputMode.Normal,
                 range_min = -1.0,
                 range_max = 1.0,
                 process_callback = None
                 ):
        ''' GateData constructor '''

        self._action_data = action_data
        self.condition = condition
        self.output_mode = mode
        self.profile_mode = profile_mode # profile mode this gate data applies to (can be set via reading from XML)
        self.fixed_value = 0
        self.range_min = range_min
        self.range_max = range_max
        self.display_range_min = range_min
        self.display_range_max = range_max
        self.macro : gremlin.macro.Macro = None  # macro steps
        self.id = gremlin.util.get_guid()
        self.use_default_range = True # if true, the default range is used to drive the output on the overall axis size
        self.display_mode = DisplayMode.Normal
        self.filter_map = {} # map of conditions to flag - if true, the item is not filtered, if false, filtered - this is for display purposes

        self._last_value = None # last input value
        self._last_range = None # last range object
        self._last_range_exit_trigger = None # range that triggered the last exit

        self._gate_item_map = {} # holds the input item data for gates index by gate index
        self._range_item_map = {} # holds the input item data for ranges indexed by range index

        self._trigger_range_lines = [] # activity triggers
        self._trigger_gate_lines = [] # activity triggers
        self._trigger_line_count = 10 # last 10 triggers max

        self._callbacks = {} # map of containers to their excecution graph callbacks for sub containers
        self._process_callback = process_callback

        # default gates and range
        min_gate = GateInfo(value = -1.0, profile_mode = profile_mode, item_data = self._new_item_data(), is_default = True, parent = self, slider_index = 0)
        max_gate = GateInfo(value = 1.0, profile_mode = profile_mode, item_data = self._new_item_data(), is_default = True, parent = self, slider_index = 1)
        self.registerGate(min_gate)
        self.registerGate(max_gate)
        def_range = RangeInfo(id = get_guid(), min_gate = min_gate, max_gate = max_gate, profile_mode=profile_mode,
                              condition= GateCondition.InRange, mode= GateRangeOutputMode.Normal, parent = self, is_default=True)

        self.default_range = def_range
        self.default_min_gate = min_gate
        self.default_max_gate = max_gate

        self.registerGate(self.default_min_gate)
        self.registerGate(self.default_max_gate)

        # non default gates - all maps have at least two gates defined
        g1 = GateInfo(value = -1.0, profile_mode = self.profile_mode, item_data = self._new_item_data(), parent=self, slider_index = 0)
        g2 = GateInfo(value = 1.0, profile_mode = self.profile_mode, item_data = self._new_item_data(), parent=self, slider_index = 1)
        self.registerGate(g1)
        self.registerGate(g2)
        r1 = RangeInfo(id = get_guid(), min_gate = g1, max_gate = g2, profile_mode=profile_mode,
                       condition= GateCondition.InRange, mode= GateRangeOutputMode.Normal, parent = self)
        self._range_item_map[r1.id] = r1

        
        # hook joystick input for runtime processing of input
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start_cb)
        el.profile_stop.connect(self._profile_stop_cb)

 

    @property
    def process_callback(self):
        ''' the callback object '''
        return self._process_callback
    
    @process_callback.setter
    def process_callback(self, value):
        self._process_callback = value

    
    @property
    def decimals(self):
        mode = self.display_mode
        if mode == DisplayMode.Normal:
            rng = self.display_range_max - self.display_range_min
            decimals = 0 if rng > 2 else 3
        elif mode == DisplayMode.OneOne:
            decimals = 3
        else: # percent
            decimals = 2
        if self.show_percent:
            return 2
        return decimals
    
    @property
    def show_percent(self):
        return self.display_mode == DisplayMode.Percent
    
    @property
    def show_oneone(self):
        return self.display_mode == DisplayMode.OneOne


    @QtCore.Slot()
    def _profile_start_cb(self):
        ''' profile starts - build execution callbacks by defined container '''
        
        # build event callback maps from subcontainers in this gated axis
        callbacks_map = {}
        gates = self.getGates()
        ranges = self.getRanges()

        # gate crossings
        for gate in gates:
            for item_data in gate.item_data_map.values():
                for container in item_data.containers:
                    callbacks_map[container] = container.generate_callbacks()

        # range entry/exit/transit
        for rng in ranges:
            for item_data in rng.item_data_map.values():
                for container in item_data.containers:
                    callbacks_map[container] = container.generate_callbacks()

        self._callbacks = callbacks_map

        # listen to hardware events
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)

 
    @QtCore.Slot()
    def _profile_stop_cb(self):
        ''' profile stops - cleanup '''

        # stop listening to hardware events
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._joystick_event_cb)

        # clean up callback map
        self._callbacks.clear()


    @QtCore.Slot(object)
    def _joystick_event_cb(self, event):
        ''' handles joystick input
        
        To avoid challenges with other GremlinEx functionality - we handle our own hierarchy calls to our subcontainers here.
        For gate crossings, we mimic a button push (for now) so functors get both a press and release call
        
        '''

        if not gremlin.shared_state.is_running:
            # not running - don't process containers
            return
        
        if not event.is_axis:
            # ignore if not an axis event
            return

        if self._action_data.hardware_device_guid != event.device_guid:
            # ignore if a different input device
            return
            
        if self._action_data.hardware_input_id != event.identifier:
            # ignore if a different input axis on the input device
            return

        raw_value = event.raw_value
        input_value = gremlin.joystick_handling.scale_to_range(raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1)

        # run mode - execute the functors with the gate data
        value = gremlin.actions.Value(event.value)
        triggers = self.process_triggers(input_value)
        trigger: TriggerData

        for trigger in triggers:
            short_press = False
            if trigger.is_range:
                containers = trigger.range.itemData(trigger.condition).containers
            else:
                containers = trigger.gate.itemData(trigger.condition).containers
            if trigger.mode == TriggerMode.FixedValue:
                value.current = trigger.value
            elif trigger.mode == TriggerMode.ValueInRange:
                value.current = trigger.value
                event.is_pressed = True
                value.is_pressed = True
            elif trigger.mode == TriggerMode.ValueOutOfRange:
                value.current = trigger.value
                value.is_pressed = False
                event.is_pressed = False
            elif trigger.mode == TriggerMode.GateCrossed:
                # mimic a joystick button press for a gate crossing
                delay = trigger.gate.delay
                event.is_axis = False
                event.event_type = InputType.JoystickButton
                short_press = True # send a key up in 250ms
            elif trigger.mode == TriggerMode.RangeEnter:
                # enter range
                print ("range enter")
                value.current = trigger.value
                value.is_pressed = True
                event.is_pressed = True
            elif trigger.mode == TriggerMode.RangeExit:
                
                # exit range
                print ("range exit")
                value.current = trigger.value
                is_pressed = trigger.condition == GateCondition.ExitRange # flip pressed mode depending on if we are releasing previously pressed event on range enter, or just triggering on the exit gate condition
                value.is_pressed = is_pressed
                event.is_pressed = is_pressed

            if self.filter_map[trigger.mode]:
                syslog.info(f"Trigger: {str(trigger)}  value: {value.current}")
        
            
            if value.current is not None:

                # process container execution graphs
                container: gremlin.base_profile.AbstractContainer
                for container in containers:
                    if container in self._callbacks.keys():
                        callbacks = self._callbacks[container]
                        for cb in callbacks:
                            if not hasattr(cb.callback,"execution_graph"):
                                # skip items that do not implement execution graph functors
                                if not value.is_pressed:
                                    pass
                                cb.callback(event, value)
                            else:
                                for functor in cb.callback.execution_graph.functors:
                                    if functor.enabled:
                                        if short_press:
                                            thread = threading.Thread(target=lambda: self._short_press(functor, event, value, delay))
                                            thread.start()
                                        else:
                                            # not a momentary trigger
                                            #print (f"trigger mode: {trigger.mode} sending event value: {value.current}")
                                            functor.process_event(event, value)
            
                                
                # process user provided functor callback if set (this is used by actions that must act on the modified output of the gated axis rather than the raw hardware input - example: simconnect action)
                if self._process_callback is not None:
                    if short_press:
                        thread = threading.Thread(target=lambda: self._short_press(self._process_callback, event, value, delay))
                        thread.start()
                    else:
                        self._process_callback(event, value)


    def _short_press(self, functor, event, value, delay = 250):
        ''' triggers a short press of a trigger (gate crossing)'''
        if not hasattr(functor, "process_event"):
            return
        # print ("short press ")
        value.current = True
        functor.process_event(event, value)
        time.sleep(delay/1000) # ms to seconds
        value.current = False
        functor.process_event(event, value)

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
            conditions = ( GateCondition.EnterRange, GateCondition.ExitRange, GateCondition.InRange, GateCondition.OutsideRange)
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
            widget.addItem(_gate_range_to_display_name[output], output)
            if default and current_index is None and default == output:
                current_index = index

        if current_index is not None:
            widget.setCurrentIndex(current_index)

    

    
    @property
    def single_step(self):
        ''' preferred stepping value'''
        return _single_step

    def _value_changed_cb(self):
        eh = GateAxisEventHandler()
        eh.gateddata_valueChanged.emit(self)
    
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
        gates = self.getGates()
        return gates[0].value
    
    
    @property
    def max(self):
        gates = self.getGates()
        return gates[-1].value
    
    def setDisplayRange(self, range_min, range_max):
        ''' sets the values for display range '''
        if range_min > range_max:
            range_min, range_max = range_max, range_min

        self.display_range_min = range_min
        self.display_range_max = range_max

            
    @property
    def steps(self):
        ''' gets the number of used gates '''
        return len(self._get_used_gates())

    def getGateValues(self):
        ''' gets a list of gate values in slider order - the slider order should be set whenever the slider is first populated so we know which index is what gate  '''
        gates = self._get_used_gates(include_default=False)
        if not gates:
            # create a pair of gates for new ranges
            g1 = GateInfo(value = -1.0, profile_mode = self.profile_mode, item_data = self._new_item_data(), parent=self, slider_index = 0)
            g2 = GateInfo(value = 1.0, profile_mode = self.profile_mode, item_data = self._new_item_data(), parent=self, slider_index = 1)
            self.registerGate(g1)
            self.registerGate(g2)
            gates = [g1, g2]
        data = [(info.slider_index, info.value) for info in gates]
        data.sort(key = lambda x: x[0])
        return [d[1] for d in data]
    
    def updateGateSliderIndices(self):
        ''' updates slider indices'''
        return self._get_used_gates()

    
    def getUsedGatesIds(self):
        ''' gets the index of used gates '''
        return self._get_used_gate_ids()

    def getUsedGatesSliderIndices(self):
        ''' gets the gate slider index for all used gates '''
        return [gate.slider_index for gate in self._get_used_gates()]
    
    def getGateValueItems(self):
        ''' gets pairs of index, value for each gate '''
        return self._get_used_items()
    
    def getGateSliderIndex(self, index):
        ''' gets the gate corresponding to a given slider index '''
        return next((gate for gate in self._get_used_gates() if gate.slider_index == index), None)
    
    def findGate(self, value, tolerance = 0.01):
        ''' finds an existing gate by value - None if not found '''
        if value is None:
            return False
        return next((gate for gate in self._get_used_gates() if _is_close(gate.value, value, tolerance)), None)
    
    def getOverlappingGates(self, tolerance = 0.01):
        ''' returns a list of overlapping gates '''
        overlap = set()
        gates = self._get_used_gates()
        processed = []
        for gate in gates:
            sub_gates = [g for g in gates if gate != g and g not in processed]
            for subgate in sub_gates:
                if _is_close(gate.value, subgate.value, tolerance):
                    overlap.add(gate)
                    overlap.add(subgate)
                    processed.append(subgate)
            processed.append(gate)

        return list(overlap)



    

    def setGateValue(self, id, value):
        ''' sets the value of a gate '''
        gate = self.getGate(id)
        if gate.value != value:
            gate.value = value
    
    def getRanges(self, include_default = False, update = False):
        ''' returns the list of ranges as range info objects'''
        if update:
            self._update_ranges()
        return self._get_ranges(include_default)
    
    def getGate(self, id = None):
        ''' returns a gate object for the given index - the item is created if the index does not exist and the gate is marked used '''
        if id is None or not id in self._gate_item_map.keys():
            return None
        return self._gate_item_map[id]
    
    def registerGate(self, gate):
        ''' registers a gate'''
        is_replace = gate.id in self._gate_item_map.keys()
        self._gate_item_map[gate.id] = gate

        if not is_replace:
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"Adding gate: [{gate.value:0.{_decimals}f}] {gate.id}  default: {gate.is_default}")

        self._update_gate_index() # update index on gate change
        self._update_ranges() # update range on gate change

    def isGateRegistered(self, gate):
        ''' true if a gate is registered'''
        return gate.id in self._gate_item_map.keys()
        
    
    def getGates(self, include_default = True):
        ''' gets all used gates '''
        return self._get_used_gates(include_default)



    
    def getRange(self, id = None):
        ''' returns a range object for the given index - the item is created if the index does not exist but gates are not initialized'''
        if id is None or not id in self._range_item_map.keys():
            return None
        return self._range_item_map[id]

    def getRangeForValue(self, value):
        ''' gets the range for the specified value '''
        ranges = self._get_ranges()
        for rng in ranges:
            if rng.inrange(value):
                return rng
            
        return None
    
    def deleteGate(self, data):
        ''' removes a gate '''
        id = data.id
        if not id in self._gate_item_map.keys():
            syslog.error(f"Error: unable to find gate {id}")
            return
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Deleting gate: {id} value: {self._gate_item_map[id].value:0.{_decimals}f}")
        self._gate_item_map[id] = None
        del self._gate_item_map[id]
        self._update_gate_index()


        
    def normalize_steps(self, use_current_range = False):
        ''' normalizes gate intervals based on the number of gates
        
        :param: use_current_range = normalize steps over the current min/max range, if false, resets min/max and uses the full range

        '''

        gates = self.getGates(include_default = False) # get gates (ordered by position) - skip default gates
        steps = len(gates)

        if not use_current_range:
            min_value = -1.0
            max_value = 1.0
        else:
            min_value = gates[0].value
            max_value = gates[-1].value

        minmax_range = max_value - min_value
        interval = minmax_range / (steps-1)

        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Normalize {steps} gates, min: {min_value:0.{_decimals}f} max: {max_value:0.{_decimals}f} interval: {interval:0.{_decimals}f}")

        
        current = min_value
        for index, gate in enumerate(gates):
            if verbose:
                syslog.info(f"\tGate [{index}] value: {current:0.{_decimals}f}")
            gate.value = current
            current += interval
            
            if current > max_value:
                current = max_value # clamp for rounding errors
        


    def _get_next_gate_index(self):
        ''' gets the next unused index '''
        used_list = self._get_used_gate_ids()
        for index in range(100):
            if not index in used_list:
                return index
        return None

    def _update_ranges(self):
        ''' updates the list of ranges with updated gate configuration - this should be called whenever a gate is added or removed  '''
        value_list = self._get_used_gates(False)
        # save the current range data
        range_item_data = []
        range_condition = []
        range_is_default = []
        range_mode = []
        for r in self._range_item_map.values():
            range_item_data.append(r.item_data_map)
            range_condition.append(r.condition)
            range_is_default.append(r.is_default)
            range_mode.append(r.mode)

        range_list = self._get_ranges(include_default = False) # current config
        self._range_item_map.clear()

        pairs = []

        for index in range(len(value_list)-1):
            g1 = value_list[index]
            g2 = value_list[index+1]
            pair = (g1.value, g2.value)
            if pair in pairs:
                continue
            pairs.append(pair)
            info = RangeInfo(id=get_guid(), min_gate = g1, max_gate = g2, profile_mode = self.profile_mode, parent = self)
            self._range_item_map[info.id] = info
            info.condition
            if index < len(range_item_data):
                info.item_data_map = range_item_data[index]
                info.condition = range_condition[index]
                info.is_default = range_is_default[index]
                info.mode = range_mode[index]
            
                
                

        ranges = self._get_ranges(include_default = False)
        # copy data over
        for rng in ranges:
            r_match = next((r for r in range_list if r == rng), None)
            if r_match:
                rng.copy_from(r_match)



        self._range_list = ranges
        verbose =  gremlin.config.Configuration().verbose_mode_details
        if verbose:
            syslog.info("Updated ranges:")
            if ranges:
                for r in ranges:
                    syslog.info(f"\tRange: {str(r)}")
            else:
                    syslog.info(f"\tNo ranges found")

            pass


    def setGateCount(self, value):
        ''' updates the stepped data when the range changes or when the number of gate change
        :param: value = number of gates

        '''

        # add the missing steps only (re-use other steps so we don't lose their config)
        gates = self.getGates()
        current_steps = len(gates)
        verbose = gremlin.config.Configuration().verbose
        if current_steps < value:

            # how many gates to add
            steps = value - current_steps

            if verbose:
                syslog.info(f"Set gate count: add {steps} gates")

            # add steps in the middle of existing ranges to spread them
            # if we run out of ranges, repeat with the new steps added
            while steps > 0:
                ranges = self.getRanges(include_default=False, update = True)
                if not ranges:
                    # include default
                    ranges = self.getRanges(update = True)
                    if not ranges:
                        break

                if verbose:
                    for rng in ranges:
                        syslog.info(f"Range: {str(rng)}")

                pairs = [r.pair() for r in ranges]
                for pair in pairs:
                    v1,v2 =pair
                    value = (v1 + v2) / 2
                    info = self.getGate()
                    info.used = True
                    info.value = value
                    if verbose:
                        syslog.info(f"Adding gate at: {value:0.{_decimals}f}")
                    steps -=1
                    if steps == 0:
                        break
            if steps > 0:
                # range approach failed, brute force add
                interval = 2.0 / steps
                value = -1 + interval
                while steps > 0:
                    info = self.getGate()
                    info.used = True
                    info.value = value
                    value += interval
                    steps -=1


        elif current_steps > value:
            # mark the items at unused
            # how many gates to add
            steps = current_steps - value

            if verbose:
                syslog.info(f"Set gate count: reduce {steps} gates")

            for index in range(value, current_steps):
                gate = gates[index]
                gate.used = False

    
        if verbose:
            gates = self.getGates()
            syslog.info(f"Updated gates:")
            for gate in gates:
                syslog.info(f"\tGate: {gate.slider_index} {gate.value:0.{_decimals}f}")


        self._update_gate_index()
        self._update_ranges()
        eh = GateAxisEventHandler()
        eh.gatedata_stepsChanged.emit(self) # indicate step data changed

 

    def _get_used_items(self):
        ''' gates the index/gate pairs for active gates '''
        gates = [(info.slider_index, info) for info in self._gate_item_map.values() if info.used and info.value is not None]
        gates.sort(key = lambda x: x[1].value) # sort ascending
        return gates
    
    def _get_used_values(self):
        ''' gets the position of active gates'''
        gates = [info.value for info in self._gate_item_map.values() if info.used and info.value is not None]
        gates.sort()
        return gates
    
    def _gate_used_gates(self):
        ''' gets used gates '''
        return [info for info in self._gate_item_map.values() if info.used and info.value is not None and not info.is_default]
    
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
        rng : RangeInfo
        for rng in ranges:
            if rng.inrange(v1):
                result.add(rng)
            if rng.inrange(v2):
                result.add(rng)
            
        return list(result)
    
    def _get_used_gates(self, include_default = True):
        ''' gets the list of active gates '''
        if include_default:
            gates = [info for info in self._gate_item_map.values() if info.used]
        else:
            gates = [info for info in self._gate_item_map.values() if info.used and not info.is_default]
        gates.sort(key = lambda x: x.value) # sort gate ascending
        return gates
    
    def _update_gate_index(self):
        ''' updates gate indices so they are in sorted index '''

        # index non default gates
        gates = [info for info in self._gate_item_map.values() if info.used and not info.is_default]
        gates.sort(key = lambda x: x.value) # sort gate ascending
        for index, gate in enumerate(gates):
            gate.slider_index = index

        # index default gates
        gates = [info for info in self._gate_item_map.values() if info.used and info.is_default]
        gates.sort(key = lambda x: x.value) # sort gate ascending
        for index, gate in enumerate(gates):
            gate.slider_index = index
    
    def _get_used_gate_ids(self):
        ''' gets the lif of activate gate indices '''
        return [info.id for info in self._gate_item_map.values() if info.used and not info.is_default]
    

    def _gate_gate_ranges(self, gate, include_default = False):
        ''' gets the two ranges on either side of a gate as a tuple (range1, range2)
            Range will be none if there is no range.
        '''
        range_list = [r for r in self._range_item_map.values()]
        top_range = None
        bottom_range = None
        for rng in range_list:
            if rng.is_default and not include_default:
                continue
            if gate == rng.g1:
                top_range = rng
            elif gate == rng.g2:
                bottom_range = rng
        
        return (bottom_range, top_range)
            
        
        

    def _get_ranges(self, include_default = True):
        ''' buils a sorted list of gate range objects filtered by used gates and by gate value '''
        
        range_list = [r for r in self._range_item_map.values()]
        range_list = [r for r in range_list if r.g1 and r.g2 and r.g1.used and r.g2.used and r.g1.value is not None and r.g2.value is not None]
        range_list.sort(key = lambda x: x.g1.value)

        if self.use_default_range and include_default:
            range_list.insert(0, self.default_range)
        
        return range_list
    
    def _get_range_values(self):
        range_list = self._get_ranges()
        return [(r.g1.value,r.g2.value) for r in range_list]
    
    def _get_range_for_value(self, value, include_default = False):
        ''' returns (v1,v2,idx1,idx12) where v1 = lower range, v2 = higher range, idx1 = gate index for v1, idx2 = gate index for v2 '''
        info : RangeInfo
        #print ("------")
        for info in self._get_ranges(include_default = include_default):
            #print (f"{value:0.4f} - range: {info.index} {info.v1:0.4f} {info.v2:0.4f} in range: {info.inrange(value)}")
            if info.inrange(value):
                return info
        return None

    def _get_range_percent(self, value, rv1, rv2):
        ''' gets the percentage position of the value in the range rv1, rv2 - return floating point 0..1'''
        v = 1 + value
        v1 = 1 + rv1
        v2 = 1 + rv2
        a = v - v1
        d = v2-v1
        p = a / d
        return p

    
    def _get_filtered_range_value(self, range_info, value):
        ''' gets a range filtered value '''
        range_info : RangeInfo
        verbose = gremlin.config.Configuration().verbose_mode_details

        if value < range_info.v1 or value > range_info.v2:
            # not in range
            if verbose:
                log_info(f"{value} Not in range [{range_info.v1},{range_info.v2}] -> none")
            return None
        elif range_info.mode == GateRangeOutputMode.Normal:
            # as is
            if verbose:
                log_info(f"{value} as is [{range_info.v1},{range_info.v2}] -> {value}")
            return value
        elif range_info.mode == GateRangeOutputMode.FilterOut:
            if verbose:
                log_info(f"{value} filtered out [{range_info.v1},{range_info.v2}] -> none")
            return None # filter the data out
        elif range_info.mode == GateRangeOutputMode.Fixed:
            # return the range's fixed value
            if verbose:
                log_info(f"{value} Fixed  -> {range_info.fixed_value}")
            return range_info.fixed_value
        elif range_info.mode == GateRangeOutputMode.Ranged:
            p = self._get_range_percent(value, range_info.v1, range_info.v2)
            output_value = gremlin.util.scale_to_range(p, source_min = 0, source_max = 1, target_min = range_info.output_range_min, target_max=range_info.output_range_max)
            if verbose:
                log_info(f"{value} scaled [{range_info.output_range_min},{range_info.output_range_max}]-> {output_value}")
            return output_value

        elif range_info.mode == GateRangeOutputMode.Rebased:
            # scale to the output range but position the data in the range (lower gate is -1, upper gate is +1)
            p = self._get_range_percent(value, range_info.v1, range_info.v2)
            output_value = gremlin.util.scale_to_range(p, source_min = 0, source_max = 1)
            if verbose:
                log_info(f"{value} rebased value: -> {output_value}")
            return output_value

        # use unchanged value
        return value

    def pre_process(self):
        # setup the pre-run activity
        self._last_value = None
        self._last_range = None
        self._last_range_exit_trigger = None # range that triggered the last exit
        self._range_list = self._get_ranges()
        self._gate_list = self._get_used_items() # ordered list of gates by index and value

    def _trim_list(self, data, count_max):
        count = len(data)
        
        if count > 0 and count_max < count:
            trim_count = count - count_max
            for _ in range(trim_count):
                data.pop(0)
        return data
        


    def process_triggers(self, current_value, require_containers = False):
        ''' processes an axis input value and returns all triggers collected since the last call based on the previous value
         
        :param: value - the input float value -1 to +1

        :returns: list of TriggerData objects containing the trigger information based on the gated axis configuration
           
        '''

        triggers = [] # returns all the triggers from the value since the last update
        last_value = self._last_value # last value processed

        value_changed = last_value is None or last_value != current_value
        if not value_changed:
            return # nothing to do if the axix didn't move
        current_range: RangeInfo
        current_range = self._get_range_for_value(current_value, include_default=False) # gets the range of the current value
        if current_range is None or not current_range.itemData(current_range.condition).containers:
            # no range container found - use default
            current_range = self._get_range_for_value(current_value, include_default=True) # gets the range of the current value

        if current_range is not None:
            if current_range.condition == GateCondition.InRange:
                if not require_containers or current_range.itemData(current_range.condition).containers:
                    # trigger because value entered the range and there are containers to trigger on range
                    value = self._get_filtered_range_value(current_range, current_value)
                    if value:
                        #print (f"Found range: mode: {current_range.mode} {current_range} value: {value}")
                        td = TriggerData()
                        if current_range.mode == GateRangeOutputMode.Fixed:
                            mode = TriggerMode.FixedValue
                        else:
                            mode = TriggerMode.ValueInRange
                        td.mode = mode
                        td.condition = GateCondition.InRange
                        td.value = value
                        td.range = current_range
                        td.is_range = True
                        triggers.append(td)
        
        # figure out if we changed ranges
        
        last_range = self._last_range

        # process the any range triggers
        if last_range:
            
            if last_range.condition == GateCondition.OutsideRange and last_range.item_data.containers:
                # trigger because the value left the prior range
                value = self._get_filtered_range_value(last_range, last_value)
                td = TriggerData()
                td.mode = TriggerMode.ValueOutOfRange
                td.value = value
                td.previous_value = last_value
                td.range = last_range
                td.condition = GateCondition.OutsideRange
                td.is_range = True
                triggers.append(td)


        # get the list of crossed gates
        crossed_gates = self._get_gates_for_values(last_value, current_value)


        # process any the gate triggers
        gate : GateInfo

        for gate in crossed_gates:
            # check for one way gates we passed

            v = gate.value
            # figure out the two ranges on either side of the gate
            enter_range = None
            exit_range = None
            bottom_range, top_range = self._gate_gate_ranges(gate)
            if last_value < v:
                # leaving bottom and entering top
                exit_range, enter_range  = bottom_range, top_range
            elif last_value > v:
                # leaving top and entering bottom
                enter_range, exit_range  = bottom_range, top_range

            # add range enter trigger
            if enter_range is not None:
                td = TriggerData()
                td.mode = TriggerMode.RangeEnter
                td.condition = GateCondition.EnterRange
                td.value = current_value
                td.previous_value = last_value
                td.range = enter_range
                td.is_range = True
                triggers.append(td)

            # add range exit trigger
            if exit_range is not None:
                # send a trigger to the range being exited for the enter container to automatically trigger releases
                td = TriggerData()
                td.mode = TriggerMode.RangeExit
                td.condition = GateCondition.EnterRange
                td.value = current_value
                td.previous_value = last_value
                td.range = exit_range
                td.is_range = True
                triggers.append(td)
                
                # send another trigger to the range being exited for the exit containers
                td = TriggerData()
                td.mode = TriggerMode.RangeExit
                td.condition = GateCondition.ExitRange
                td.value = current_value
                td.previous_value = last_value
                td.range = exit_range
                td.is_range = True
                triggers.append(td)
        
            # add gate crossing trigger
            td = TriggerData()
            td.gate = gate
            td.value = current_value
            td.condition = GateCondition.OnCross
            td.mode = TriggerMode.GateCrossed
            triggers.append(td)
                
            # add gate cross decrease trigger
            if last_value > v:
                td = TriggerData()
                td.gate = gate
                td.value = current_value
                td.condition = GateCondition.OnCrossDecrease
                td.mode = TriggerMode.GateCrossed
                triggers.append(td)
            
            # add gate cross increase trigger
            if last_value < v:
                td = TriggerData()
                td.gate = gate
                td.value = current_value
                td.condition = GateCondition.OnCrossIncrease
                td.mode = TriggerMode.GateCrossed
                triggers.append(td)

        # update last values
        self._last_range = current_range
        self._last_value = current_value

        # update trigger lines
        for trigger in triggers:
            mode = trigger.mode
            if not mode in self.filter_map.keys():
                self.filter_map[mode] = True
            if self.filter_map[mode]:
                if trigger.is_range:
                    self._trigger_range_lines.append(str(trigger))
                else:
                    self._trigger_gate_lines.append(str(trigger))
        
        # keep it within max lines
        self._trigger_range_lines = self._trim_list(self._trigger_range_lines, self._trigger_line_count)
        self._trigger_gate_lines = self._trim_list(self._trigger_gate_lines, self._trigger_line_count)

        return triggers

        
    def _find_input_item(self):
        return gremlin.base_profile._get_input_item(self._action_data)

    def _new_item_data(self, is_action = True):
        ''' creates a new item data from the existing one '''
        current_item_data = self._find_input_item()
        item_data = gremlin.base_profile.InputItem()
        item_data._input_type = current_item_data._input_type
        item_data._device_guid = current_item_data._device_guid
        item_data._input_id = current_item_data._input_id
        item_data._is_action = is_action
        item_data._profile_mode = current_item_data._profile_mode
        item_data._device_name = current_item_data._device_name

        # add the input data to the profile

        return item_data
    
    def get_xml_mode(self, node):
        ''' walks the xml tree up to get the mode for this gate data object '''
        current : ElementTree.Element = node
        while current is not None:
            current = current.getparent()
            if current is None or current.tag == 'mode':
                break
        if current is not None:
            mode = safe_read(current,"name")
        return mode


    def to_xml(self):
        ''' export this configuration to XML '''
        node = ElementTree.Element("gate")

        verbose = gremlin.config.Configuration().verbose

        node.set("use_default_range",str(self.use_default_range))
        node.set("show_mode", DisplayMode.to_string(self.display_mode))
        node.set("mode", self.profile_mode)

        # save gate data
        gate : GateInfo
        gates = self.getGates(include_default=True)
        # reorder so default gates are first and are listed by value
        gates.sort(key = lambda x: (x.is_default, x.value))
        for gate in gates:
            
            
            if verbose:
                log_info(f"Saving gate {gate.id} value: {gate.value} containers count: {gate.container_count:,}")
            child = ElementTree.SubElement(node, "gate")
            if gate.is_default:
                child.set("default",str(gate.is_default))
            child.set("condition", _gate_condition_to_name[gate.condition])
            child.set("value", f"{gate.value:0.{_decimals}f}")
            child.set("delay", str(gate.delay))
            child.set("id", gate.id)

            for condition, item_data in gate.item_data_map.items():
                if item_data.containers:
                    item_node = item_data.to_xml()
                    if item_node is not None:
                        item_node.set("type", item_node.tag)
                        item_node.set("condition", GateCondition.to_string(condition))
                        item_node.tag = "action_containers"
                        child.append(item_node)

        # save range data
        rng : RangeInfo
        for rng in self.getRanges(include_default = True):
            if verbose:
                log_info(f"Saving range {rng.id} default: {rng.is_default} min: {rng.range_min}  max: {rng.range_max} containers count: {rng.container_count:,}")
            child_comment = ElementTree.Comment(f"Range: [{rng.v1:0.{_decimals}f},{rng.v2:0.{_decimals}f}]  Gates: [{rng.g1.slider_index}/{rng.g2.slider_index}] Condition: [{_gate_condition_to_display_name[rng.condition]}] Mode: [{_gate_range_to_display_name[rng.mode]}]")
            node.append(child_comment)
            child = ElementTree.SubElement(node,"range")
            

            if rng.is_default:
                child.set("default", str(rng.is_default))
            child.set("condition",_gate_condition_to_name[rng.condition])
            child.set("mode",_gate_range_to_string[rng.mode])
            mode = rng.mode
            if mode == GateRangeOutputMode.Fixed:
                child.set("fixed_value", f"{rng.fixed_value:0.{_decimals}f}")
            elif mode == GateRangeOutputMode.Ranged:
                child.set("range_min",  f"{rng.range_max:0.{_decimals}f}")
                child.set("range_max",  f"{rng.range_min:0.{_decimals}f}")

            child.set("id", rng.id)
            if not rng.is_default:
                child.set("min_id", rng.g1.id)
                child.set("max_id", rng.g2.id)

            for condition, item_data in rng.item_data_map.items():
                if item_data.containers:
                    item_node = item_data.to_xml()
                    if item_node is not None:
                        item_node.set("type", item_node.tag)
                        item_node.set("condition", GateCondition.to_string(condition))
                        item_node.tag = "range_containers"
                        child.append(item_node)
            
        
        # filter options
        filter_node = ElementTree.SubElement(node,"filter")
        for trigger in self.filter_map.keys():
            filter_node.set(TriggerMode.to_string(trigger), str(self.filter_map[trigger]))

        node.append(filter_node)



        return node
    


    def from_xml(self, node):
        if not node.tag == "gate":
            syslog.error(f"GateData: Invalid node type {node.tag} {node}")
            return
    
        self.use_default_range = safe_read(node, "use_default_range", bool, True)

        assert self.isGateRegistered(self.default_min_gate)
        assert self.isGateRegistered(self.default_max_gate)

        if "show_percent" in node.attrib:
            show_percent = safe_read(node,"show_percent", bool, False)
            if show_percent:
                self.display_mode = DisplayMode.Percent
            else:
                self.display_mode = DisplayMode.Normal
        else:
            mode = safe_read(node,"show_mode", str, "")
            self.display_mode = DisplayMode.to_enum(mode)
        

        # read gate configurations
        node_gates = gremlin.util.get_xml_child(node, "gate", multiple=True)

        profile_mode = safe_read(node,"mode", str,"")
        if not profile_mode:
            profile_mode = self.get_xml_mode(node)
        self.profile_mode = profile_mode

        # read values from file
        self._gate_item_map.clear()
        self._range_item_map.clear()

        for child in node_gates:
            gate_id = safe_read(child, "id", str,"")
            gate_default = safe_read(child, "default", bool, False)
            gate_value = safe_read(child, "value", float, 0.0)
            gate_condition = safe_read(child, "condition", str, "")
            gate_delay = safe_read(child, "delay", int, 250)
            if not gate_condition in _gate_condition_to_enum.keys():
                syslog.error(f"GateData: Invalid condition type {gate_condition} gate id: {gate_id}")
                return
            gate_condition = GateCondition.to_enum(gate_condition)
            
            gate = GateInfo(id = gate_id,
                            value = gate_value,
                            profile_mode = profile_mode,
                            condition =gate_condition,
                            is_default = gate_default,
                            delay = gate_delay,
                            parent = self)
            

            
            item_nodes = gremlin.util.get_xml_child(child, "action_containers", multiple=True)
            for item_node in item_nodes:
                if item_node is not None:
                    item_data = self._new_item_data()
                    if not "condition" in item_node.attrib:
                        condition = gate_condition
                    else:
                        condition_str = item_node.get("condition")
                        condition = GateCondition.to_enum(condition_str)
                    item_node.tag = item_node.get("type")
                    item_data.from_xml(item_node)
                    gate.item_data_map[condition] = item_data

            
            self.registerGate(gate)
            if gate_default:
                if gate.value == -1.0:
                    self.default_min_gate.id = gate.id
                elif gate.value == 1.0:
                    self.default_max_gate.id = gate.id

        # read range configuration
        self._range_item_map.clear()
        node_ranged = gremlin.util.get_xml_child(node, "range", multiple=True)
        for child in node_ranged:
            range_id = safe_read(child, "id", str, "")
            if not range_id:
                range_id = get_guid()
            range_default = safe_read(child, "default", bool, False)
            if range_default:
                min_gate = self.default_min_gate
                max_gate = self.default_max_gate
            else:
                min_id = safe_read(child, "min_id", str, "")
                max_id = safe_read(child, "max_id", str, "")
                min_gate = self._gate_item_map[min_id] if min_id in self._gate_item_map.keys() else None
                max_gate = self._gate_item_map[max_id] if max_id in self._gate_item_map.keys() else None

            if not min_gate or not max_gate:
                # continue (bad data)
                continue

            if not self.isGateRegistered(min_gate):
                self.registerGate(min_gate)
            if not self.isGateRegistered(max_gate):
                self.registerGate(max_gate)

            range_condition = safe_read(child, "condition", str, "")
            if not range_condition in _gate_condition_to_enum.keys():
                syslog.error(f"GateData: Invalid condition type {range_condition} range: {range_id}")
                return
            range_condition = _gate_condition_to_enum[range_condition]

            range_mode = safe_read(child, "mode", str, "")
            if not range_mode in _gate_range_to_enum.keys():
                syslog.error(f"GateData: Invalid mode {range_mode} range: {range_id}")
                return
            range_mode = _gate_range_to_enum[range_mode]
       
            range_min = safe_read(child,"range_min", float, -1.0)
            range_max = safe_read(child,"range_max", float, 1.0)
            
            range_info = RangeInfo(id = range_id,
                                    min_gate = min_gate,
                                    max_gate = max_gate,
                                    profile_mode = profile_mode,
                                    condition = range_condition,
                                    mode = range_mode,
                                    is_default = range_default,
                                    parent = self,
                                    )

            item_nodes = gremlin.util.get_xml_child(child, "range_containers", multiple=True)
            for item_node in item_nodes:
                if item_node is not None:
                    item_node.tag = item_node.get("type")
                    if not "condition" in item_node.attrib:
                        condition = range_condition
                    else:
                        condition_str = item_node.get("condition")
                        condition = GateCondition.to_enum(condition_str)
                    item_data = self._new_item_data()
                    item_data.from_xml(item_node)
                    range_info.item_data_map[condition] = item_data
                
            
            if range_mode == GateRangeOutputMode.Ranged:
                range_info.range_min = range_min
                range_info.range_max = range_max
            elif range_mode == GateRangeOutputMode.Fixed:
                fixed_value = safe_read(child,"fixed_value", float, 0)
                range_info.fixed_value = fixed_value

            if range_default:
                # default range data
                self.default_range = range_info
            else:
                self._range_item_map[range_id] = range_info


        # update the ranges based on the new gates
        self._update_ranges()

        # filter
        filter_node = gremlin.util.get_xml_child(node, "filter")
        if filter_node is not None:
            for _, trigger in enumerate(TriggerMode):
                trigger_str = TriggerMode.to_string(trigger)
                value = safe_read(filter_node, trigger_str, bool, True)
                self.filter_map[trigger] = value

            
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
        self.condition : GateCondition = None
        self.previous_value = None # prior value
        self.is_range = False # true if a range trigger, false if a gate trigger
        

    def __str__(self):
        
        stub = f"[{self.mode.name}]"
        if self.mode in (TriggerMode.FixedValue, TriggerMode.ValueInRange, TriggerMode.ValueOutOfRange, TriggerMode.RangeEnter, TriggerMode.RangeExit):
            return f"{stub} value: {self.value:0.{_decimals}f} / {self.range.to_percent(self.value):0.2f}% range [{self.range.v1:0.{_decimals}f},{self.range.v2:0.{_decimals}f}]"
        elif self.mode == TriggerMode.RangedValue:
            return f"{stub} value: {self.value:0.{_decimals}f} / {self.range.to_percent(self.value):0.2f}% range:[{self.range.v1:0.{_decimals}f},{self.range.v2:0.{_decimals}f}]"
        else:
            percent = gremlin.util.scale_to_range(self.value,-1,1,0,100)
            return f"{stub} value: {self.value:0.{_decimals}f} / {percent:0.2f}% gate: {self.gate.slider_index+1}"
        


class GatedAxisWidget(QtWidgets.QWidget):
    ''' a widget that represents a single gate on an axis input and what should happen in that gate
    
        a gate has a min/max value, an optional output range and can trigger different actions based on conditions applied to the input axis value
    
    '''

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz
    duplicate_requested = QtCore.Signal(object) # fired when the duplicate button is clicked - passes the GateData to duplicate
    configure_requested = QtCore.Signal(object) # configure clicked
    configure_range_requested = QtCore.Signal(object) # configure range - data = range object
    configure_gate_requested = QtCore.Signal(object) # configure gate - data = gate object


    def __init__(self, action_data, show_configuration = False, show_output_mode = False, parent = None):
        '''
        
        :param: action_data = the AbstractContainerAction derived object holding the configuration data for the action
        :param: gate_data = the gated axis configuration object
        :param: process_callback = the optional callback executed when the gated axis receives input at runtime (similar to process_events for functors)


        The callback is necessary because the gate widget does not use the usual event handler method for GremlinEx because it has special handling of sub-actions specific to an axis input.
        The control will automatically process input from the hardware axis it's attached do and call the callback because it may have different values based on the options setup on the gated axis.

        
        '''

        import gremlin.event_handler
        import gremlin.joystick_handling
        
        super().__init__(parent)

        self.action_data = action_data
        gate_data = action_data.gate_data
        eh = GateAxisEventHandler()
        eh.gatedata_stepsChanged.connect(self._update_steps_cb)
        eh.gateddata_valueChanged.connect(self._update_values_cb)

        
        self._range_readout_widgets = {} # holds reference to range widgets by index

        self.single_step = 0.001 # amount of a single step when scrolling
        
        self._output_value = 0

        self.main_layout = QtWidgets.QGridLayout(self)

        if action_data.hardware_input_type != InputType.JoystickAxis:
            missing = QtWidgets.QLabel("Invalid input type - joystick axis expected")
            self.main_layout.addWidget(missing)
            return
        

        self._grab_icon = load_icon("mdi.record-rec",qta_color = "red")
        self._setup_icon = load_icon("fa.gear")
        #self._setup_container_icon = load_icon("fa.gears")
        self._setup_container_icon = load_icon("ei.cog-alt",qta_color="#365a75")
        

        # get the curent axis normalized value -1 to +1
        value = gremlin.joystick_handling.get_axis(action_data.hardware_device_guid, action_data.hardware_input_id)
        self._axis_value = value

        # axis input gate widget

        self.slider_frame_widget = QtWidgets.QFrame()
        self.slider_frame_layout = QtWidgets.QVBoxLayout(self.slider_frame_widget)
        self.slider_frame_widget.setStyleSheet('.QFrame{background-color: lightgray;}')
        self.slider = ui_common.QMarkerDoubleRangeSlider()
     
        self.slider.setOrientation(QtCore.Qt.Horizontal)
        self.slider.setRange(-1,1)
        self.slider.setMarkerValue(value)
        self.slider.valueChanged.connect(self._slider_value_changed_cb)
        self.slider.setMinimumWidth(200)
        self.slider.handleRightClicked.connect(self._slider_handle_clicked_cb)
        self.slider.handleGrooveClicked.connect(self._slider_groove_clicked_cb)
        
        self.warning_widget = ui_common.QIconLabel("fa.warning", text="", use_qta = True,  icon_color="red")
        self.warning_widget.setVisible(False)

        self.slider_frame_layout.addWidget(self.slider)
      
        self.container_slider_widget = QtWidgets.QWidget()
        self.container_slider_layout = QtWidgets.QGridLayout(self.container_slider_widget)

        self.slider_frame_widget

        self.container_slider_layout.addWidget(self.slider_frame_widget,0,0,-1,1)

        self.container_slider_layout.addWidget(QtWidgets.QLabel(" "),0,6)

        self.container_slider_layout.setColumnStretch(0,3)
        
        self.container_slider_widget.setContentsMargins(0,0,0,0)

      

        # configure trigger button
        self._configure_trigger_widget = QtWidgets.QPushButton("Configure")
        self._configure_trigger_widget.setIcon(self._setup_icon)
        self._configure_trigger_widget.clicked.connect(self._trigger_cb)
        self._show_configuration = show_configuration
        self._configure_trigger_widget.setVisible(show_configuration)

        # manual and grab value widgets

        self.container_gate_count_widget = QtWidgets.QWidget()
        #self.container_gate_count_widget.setContentsMargins(0,0,0,0)

        self.container_gate_count_layout = QtWidgets.QHBoxLayout(self.container_gate_count_widget)
        #self.container_gate_count_layout.setContentsMargins(0,0,0,0)

        self.container_gate_widget = QtWidgets.QWidget()
        self.container_gate_widget.setContentsMargins(0,0,0,0)
        #self.container_gate_layout = QtWidgets.QGridLayout(self.container_gate_widget)
        self.container_gate_layout = ui_common.QFlowLayout(self.container_gate_widget)
        self.container_gate_layout.setContentsMargins(0,0,0,0)

        self.container_range_count_widget = QtWidgets.QWidget()
        self.container_range_count_layout = QtWidgets.QHBoxLayout(self.container_range_count_widget)

        self.container_range_widget = QtWidgets.QWidget()
        self.container_range_layout = ui_common.QFlowLayout(self.container_range_widget)
        # self.container_range_layout = QtWidgets.QGridLayout(self.container_range_widget)
        self.container_range_widget.setContentsMargins(0,0,0,0)
        self.container_range_layout.setContentsMargins(0,0,0,0)

        self.container_options_widget = QtWidgets.QWidget()
        self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
        self.container_options_widget.setContentsMargins(0,0,0,0)

        self._use_default_range_widget = QtWidgets.QCheckBox("Use default range for axis output")
        self._use_default_range_widget.setChecked(gate_data.use_default_range)
        self._use_default_range_widget.clicked.connect(self._use_default_range_changed_cb)
        self._use_default_range_widget.setToolTip("When set, the axis output uses the default range setting for value output, sub-ranges can still be used to trigger actions based on entry/exit of ranges")

        self._display_label_widget = QtWidgets.QLabel("Display Mode:")
        self._display_mode_widget = QtWidgets.QComboBox()
        self._show_output_mode = show_output_mode
        if show_output_mode:
            self._display_mode_widget.addItem("Output range", userData = DisplayMode.Normal)
            self._display_mode_widget.addItem("[-1, +1]", userData = DisplayMode.OneOne)
        else:
            self._display_mode_widget.addItem("Normal", userData = DisplayMode.OneOne)
        self._display_mode_widget.addItem("Percent", userData = DisplayMode.Percent)
        index = self._display_mode_widget.findData(gate_data.display_mode)
        if index == -1:
            self.gate_data.display_mode = DisplayMode.OneOne
            index = self._display_mode_widget.findData(gate_data.display_mode)
        self._display_mode_widget.setCurrentIndex(index)
        self._display_mode_widget.currentIndexChanged.connect(self._display_mode_changed_cb)

        self.container_options_layout.addWidget(self._configure_trigger_widget)
        self.container_options_layout.addWidget(self._use_default_range_widget)
        self.container_options_layout.addWidget(self._display_label_widget)
        self.container_options_layout.addWidget(self._display_mode_widget)
        self.container_options_layout.addStretch()

        self._update_gates_ui()
    
        # ranged container
        self._create_output_ui()

        # steps container
        self._create_steps_ui()
        row = 1
        self.main_layout.addWidget(self.container_slider_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_steps_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_gate_count_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_gate_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_options_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_range_count_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_range_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_output_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.warning_widget,row,0,1,-1)
        self.main_layout.setVerticalSpacing(0)
        self.main_layout.setRowStretch(row, 3)
        

        # hook the joystick input for axis input repeater
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)

        el.profile_start.connect(self._profile_start_cb)
        el.profile_stop.connect(self._profile_stop_cb)


        # update visible container for the current mode
        #self._update_conditions()
        self._update_ui()
        self._update_values_cb(self.gate_data)

    @property
    def gate_data(self):
        return self.action_data.gate_data
    
    def ConfigurationVisible(self):
        return self._show_configuration
    
    def setConfigurationVisible(self, value):
        self._show_configuration = value
        self._configure_trigger_widget.setVisible(value)

    @QtCore.Slot()
    def _profile_stop_cb(self):
        ''' profile stops - reconnect widget '''
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)

    @QtCore.Slot()
    def _profile_start_cb(self):
        ''' profile stops - disconnect widget '''
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._joystick_event_cb)

    def setDisplayRange(self, range_min, range_max):
        ''' sets/updates the slider's range - updates any existing gates to the new range based on prior position'''
        if range_min > range_max:
            range_max, range_min = range_min, range_max
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            logging.getLogger("system").info(f"Gate widget: set display range {range_min, range_max}")
        
        #self.slider.setRange(range_min, range_max)
        self.gate_data.setDisplayRange(range_min, range_max)
        #self._update_values_cb() # update slider gate positions
        self._update_gates_ui() # update gate data

    @property
    def min_range(self):
        return self.slider.minimum()
    
    @property
    def max_range(self):
        return self.slider.maximum()

    def _helper(self):
        helper = ui_common.QHelper()
        helper.min_range = self.min_range
        helper.max_range = self.max_range
        helper.decimals = self.gate_data.decimals
        helper.show_percent = self.gate_data.show_percent
        
        return helper
    
    def _update_gates_ui(self):
        ''' creates the gate data for each gate '''
        
        self._gate_value_widget_map = {}
        gremlin.util.clear_layout(self.container_gate_layout)
        gate_list = self.gate_data.getGateValueItems()

        gremlin.util.clear_layout(self.container_gate_count_layout)
        gate_count_widget = QtWidgets.QLabel(f"Gates ({len(gate_list)}):")
        self.container_gate_count_layout.addWidget(gate_count_widget)
        #self.container_gate_layout.addWidget(gate_count_widget,0,0)
        # row = 1
        # col = 0

        label_width = ui_common.get_text_width("Range MM")
        helper = self._helper()
        delete_enabled = len(gate_list) > 2 # keep at least 2 gates
        mode = self.gate_data.display_mode
        if mode == DisplayMode.Normal:
            range_min = self.gate_data.display_range_min
            range_max = self.gate_data.display_range_max
        elif mode == DisplayMode.Percent:
            range_min = 0.0
            range_max = 100.0
        else:
            range_min = -1.0
            range_max = 1.0

        for _, gate in gate_list:
            if gate.is_default:
                # don't display default gates - they are internal for the default range
                continue
            id = gate.id
            label_widget = QtWidgets.QLabel(f"Gate {gate.slider_index + 1}:")
            label_widget.setMaximumWidth(label_width)
            sb_widget = helper.get_double_spinbox(id, gate.display_value, range_min, range_max)
            sb_widget.valueChanged.connect(self._gate_value_changed_cb)
            
            self._gate_value_widget_map[gate.id] = sb_widget

            grab_widget = ui_common.QDataPushButton()
            grab_widget.data = (gate, sb_widget) # gate and control to update
            grab_widget.setIcon(self._grab_icon)
            grab_widget.setMaximumWidth(20)
            grab_widget.clicked.connect(self._grab_cb)
            grab_widget.setToolTip("Grab axis value")

            setup_widget = ui_common.QDataPushButton()
            setup_widget.data = gate
            has_containers = gate.has_containers
            if has_containers:
                setup_widget.setIcon(self._setup_container_icon)
            else:
                setup_widget.setIcon(self._setup_icon)
            setup_widget.setMaximumWidth(20)
            setup_widget.clicked.connect(self._configure_gate_cb)
            setup_widget.setToolTip(f"Setup actions for gate {id}")

            clear_widget = ui_common.QDataPushButton()
            clear_widget.setIcon(load_icon("mdi.delete"))
            clear_widget.setMaximumWidth(20)
            clear_widget.data = gate
            clear_widget.clicked.connect(self._delete_gate_confirm_cb)
            clear_widget.setToolTip("Removes this gate")
            clear_widget.setEnabled(delete_enabled)

            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QHBoxLayout(container_widget)



            container_layout.addWidget(label_widget)
            container_layout.addWidget(sb_widget)
            container_layout.addWidget(grab_widget)
            container_layout.addWidget(setup_widget)
            container_layout.addWidget(clear_widget)
            container_widget.setContentsMargins(0,0,0,0)

            self.container_gate_layout.addWidget(container_widget)

        # ranges between the gates
        gremlin.util.clear_layout(self.container_range_layout)
        range_list = self.gate_data.getRanges(include_default = self.gate_data.use_default_range)
        range_count_widget = QtWidgets.QLabel(f"Ranges ({len(range_list)}):")
        
        gremlin.util.clear_layout(self.container_range_count_layout)
        self.container_range_count_layout.addWidget(range_count_widget)
        
        self._range_readout_widgets = {}
        rng : RangeInfo

        eh = GateAxisEventHandler()
        eh.rangeinfo_valueChanged.connect(self._range_changed_cb)

        char_width = ui_common.get_text_width("M")

        if self.gate_data.use_default_range:
            # only show the default range as the output range to configure
            range_list = [rng for rng in range_list if rng.is_default]
        
        display_index = 0
        decimals = self.gate_data.decimals
        for rng in range_list:
            id = rng.id
            g1 : GateInfo = rng.g1
            if g1 is None:
                continue
            g2 : GateInfo= rng.g2
            if g2 is None:
                continue

            if rng.is_default:
                # default range
                label_widget = QtWidgets.QLabel(f"Default:")
            else:
                display_index += 1
                label_widget = QtWidgets.QLabel(f"Range {display_index}:")

            label_widget.setMaximumWidth(label_width)

            range_widget = ui_common.QDataLineEdit()
            range_widget.setReadOnly(True)
            g1v = g1.display_value
            g2v = g2.display_value
            txt = f"[{g1v:0.{decimals}f} to {g2v:0.{decimals}f}]"
            range_widget.setText(txt)
            range_widget.setMinimumWidth(char_width * len(txt))

            self._range_readout_widgets[id] = range_widget
            range_widget.data = (rng, range_widget)
            
            
 
            setup_widget = ui_common.QDataPushButton(data = rng)
            setup_widget.setIcon(self._setup_icon)
            has_containers = rng.has_containers
            if has_containers:
                setup_widget.setIcon(self._setup_container_icon)
            else:
                setup_widget.setIcon(self._setup_icon)
            setup_widget.setMaximumWidth(20)
            setup_widget.clicked.connect(self._configure_range_cb)
            setup_widget.setToolTip(f"Setup actions for range {id}")

            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QHBoxLayout(container_widget)

            container_layout.addWidget(label_widget)
            container_layout.addWidget(range_widget)
            container_layout.addWidget(setup_widget)
            container_widget.setContentsMargins(0,0,0,0)
            
            self.container_range_layout.addWidget(container_widget)


    @QtCore.Slot(RangeInfo)
    def _range_changed_cb(self, range_info):
        ''' called when range data changes '''
        #range_info = self.sender()
        if range_info.id in self._range_readout_widgets.keys():
            range_widget = self._range_readout_widgets[range_info.id]
            g1 : GateInfo = range_info.g1
            g2 : GateInfo= range_info.g2
            ''' updates the display for a range item '''
            
            helper = self._helper()
            g1v = helper.to_value(g1.value)
            g2v = helper.to_value(g2.value)
            range_widget.setText(f"[{g1v:0.{helper.decimals}f} to {g2v:0.{helper.decimals}f}]")
        
    @QtCore.Slot()
    def _gate_value_changed_cb(self):
        widget = self.sender()
        id = widget.data
        value = widget.value()
        value = gremlin.util.scale_to_range(value, widget.minimum(), widget.maximum(), -1.0, 1.0)
        self.gate_data.setGateValue(id, value)
        self._update_values_cb(self.gate_data)

    @QtCore.Slot(bool)
    def _use_default_range_changed_cb(self, checked):
        self.gate_data.use_default_range = checked
        self._update_gates_ui()

    @QtCore.Slot()
    def _display_mode_changed_cb(self):
        self.gate_data.display_mode = self._display_mode_widget.currentData()
        self._update_gates_ui()

    @QtCore.Slot()
    def _trigger_cb(self):
        ''' configure clicked '''
        self.configure_requested.emit(self.gate_data)


        

    @QtCore.Slot(float)
    def _slider_groove_clicked_cb(self, value):
        ''' fired when the user clicked on the groove - adds a gate at that location '''
        count = len(self.gate_data.getGates())
        gate = self.gate_data.findGate(value)
        if not gate and count < 20:
            gate = GateInfo(id = get_guid(), value = value, parent = self.gate_data)
            self.gate_data.registerGate(gate)
            
        self._update_gates_ui()
        self._update_ui()



    @QtCore.Slot()
    def _slider_value_changed_cb(self):
        ''' occurs when the slider values change '''
        values = list(self.slider.value())
        
        # update the gate data
        for index, value in enumerate(values):
            gate : GateInfo = self.gate_data.getGateSliderIndex(index)
            if gate is not None:
                gate.setValue(value)
        # update ui
        self._update_gates_ui()
        

    def _set_slider_gate_value(self, index, value):
        ''' sets a gate value on the slider '''
        values = list(self.slider.value())
        if value != values[index]:
            values[index] = value
        self._set_slider(values)

    def _set_slider(self, values):
        verbose = gremlin.config.Configuration().verbose_mode_details
        if verbose:
            sv = "Slider: "
            for idx, v in enumerate(values):
                sv += f"[{idx}] {v:0.{self.gate_data.decimals}f} "
            syslog.info(sv)
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setValue(values)

    @QtCore.Slot()
    def _grab_cb(self):
        ''' grab the min value from the axis position '''
        info : GateInfo
        info, widget = self.sender().data  # the button's data field contains the widget to update
        value = self._axis_value
        info.value = value
        self._set_slider_gate_value(info.slider_index, value)
        



    QtCore.Slot(object, GateInfo)
    def _delete_gate_confirm_cb(self):
        ''' delete requested '''
        widget = self.sender()
        gate = widget.data
        self._remove_gate(gate)

    def _remove_gate(self, gate):

        # ensure there are at least two gates left
        count = len(self.gate_data._gate_used_gates())
        if count <= 2:
            syslog.warn("Unable to delete gate: at least two gates must be defined.")
            return # do not allow fewer than 2 gates

        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText("This will delete this gate.\nAre you sure?")
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_confirmed_cb(gate)

    def _delete_confirmed_cb(self, gate):
         self.deleteGate(gate)

    QtCore.Slot(object, GateInfo)
    def _delete_gate_cb(self, gate):
        ''' delete the gate '''
        self.deleteGate(gate)
        
        
    @QtCore.Slot()
    def _configure_range_cb(self):
        ''' open the configuration dialog for ranges '''
        widget = self.sender()  # the button's data field contains the widget to update
        rng = widget.data
        connected = gremlin.util.isSignalConnected(self,"configure_range_requested")
        if connected:
            self.configure_range_requested.emit(rng)
        else:
            dialog = ActionContainerUi(gate_data = self.gate_data, info_object = rng, action_data = self.action_data)
            dialog.exec()
            self._update_gates_ui()

    @QtCore.Slot(int)
    def _slider_handle_clicked_cb(self, handle_index):
        ''' handle right clicked - pass event along '''
        connected = gremlin.util.isSignalConnected(self, "configure_gate_requested")
        if connected:
            # event is connected
            self.configure_gate_requested.emit(gate)
        else:
            # default action = show dialog
            gate = self.gate_data.getGateSliderIndex(handle_index)
            dialog = ActionContainerUi(gate_data = self.gate_data, info_object = gate, action_data=self.action_data)
            # gates can be deleted
            dialog.delete_requested.connect(self._delete_gate_cb)
            dialog.exec()
            self._update_gates_ui()

    @QtCore.Slot()
    def _configure_gate_cb(self):
        ''' gate configure button clicked '''
        widget = self.sender()  # the button's data field contains the widget to update
        gate = widget.data
        connected = gremlin.util.isSignalConnected(self,"configure_gate_requested")
        if connected:
            # call the handler
            self.configure_gate_requested.emit(gate)
        else:
            dialog = ActionContainerUi(gate_data = self.gate_data, info_object = gate, action_data = self.action_data)
            dialog.delete_requested.connect(self._delete_gate_cb)
            dialog.exec()
            self._update_gates_ui()
        

    QtCore.Slot()
    def _delete_cb(self):
        ''' delete requested '''
        self.delete_requested.emit(self.gate_data)

    QtCore.Slot()
    def _duplicate_cb(self):
        ''' duplicate requested '''
        self.duplicate_requested.emit(self.gate_data)
            
    
    @QtCore.Slot(object)
    def _joystick_event_cb(self, event):
        ''' handles joystick input
        
        grab real time hardware input to update the widget
        
        '''
        
        if not event.is_axis:
            # ignore if not an axis event and if the profile is running, or input for a different device
            return
        
        if self.action_data.hardware_device_guid != event.device_guid:
            # print (f"device mis-match: {str(self._data.hardware_device_guid)}  {str(event.device_guid)}")
            return
            
        if self.action_data.hardware_input_id != event.identifier:
            # print (f"input mismatch: {self._data.hardware_input_id} {event.identifier}")
            return

        raw_value = event.raw_value
        input_value = gremlin.joystick_handling.scale_to_range(raw_value,
                                                               source_min = -32767,
                                                               source_max = 32767,
                                                               target_min = self.slider.minimum(),
                                                               target_max = self.slider.maximum())
        self._axis_value = input_value
        self.slider.setMarkerValue(input_value)
        self._update_output_value()


    def _create_filter_widgets(self):
        gremlin.util.clear_layout(self.container_filter_layout)
        
        for _, trigger in enumerate(TriggerMode):
            widget = gremlin.ui.ui_common.QDataCheckbox(TriggerMode.to_display_name(trigger), data = trigger)
            if not trigger in self.gate_data.filter_map.keys():
                self.gate_data.filter_map[trigger] = True
            widget.setChecked(self.gate_data.filter_map[trigger])
            widget.clicked.connect(self._filter_cb)
            self.container_filter_layout.addWidget(widget)
        self.container_filter_layout.addStretch()

    @QtCore.Slot(bool)
    def _filter_cb(self, checked):
        widget = self.sender()
        trigger : TriggerMode = widget.data
        self.gate_data.filter_map[trigger] = checked

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

        self.container_filter_widget = QtWidgets.QWidget()
        self.container_filter_widget.setContentsMargins(0,0,0,0)
        self.container_filter_layout = QtWidgets.QHBoxLayout(self.container_filter_widget)
        self.container_filter_layout.setContentsMargins(0,0,0,0)

        self._create_filter_widgets()
        
        row = 0
        self.container_output_layout.addWidget(self.container_filter_widget,row,0,1,-1)
        row+=1
        self.container_output_layout.addWidget(QtWidgets.QLabel("Range events:"),row,0)
        self.container_output_layout.addWidget(QtWidgets.QLabel("Gate events:"),row,1)
        row+=1
        self.container_output_layout.addWidget(self.output_range_trigger_widget,row,0)
        self.container_output_layout.addWidget(self.output_gate_trigger_widget,row,1)


    def _create_steps_ui(self):
        ''' creates the steps UI '''
        self.sb_steps_widget = QtWidgets.QSpinBox()
        self.sb_steps_widget.setRange(2, 20) # min steps is 2
        count = self.gate_data.steps
        if count < 2:
            # gates may not be created yet
            count = 2
        self.sb_steps_widget.setValue(count)

        self.add_gate_widget = QtWidgets.QPushButton("Add")
        self.add_gate_widget.setToolTip("Adds a gate at the current input position")
        self.add_gate_widget.setIcon(self._grab_icon)
        self.add_gate_widget.clicked.connect(self._add_gate_cb)

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


        self.container_steps_layout.addWidget(self.add_gate_widget)
        self.container_steps_layout.addWidget(QtWidgets.QLabel("Set gate count:"))
        self.container_steps_layout.addWidget(self.sb_steps_widget)
        
        self.container_steps_layout.addWidget(self.set_steps_widget)
        self.container_steps_layout.addWidget(self.normalize_widget)
        self.container_steps_layout.addWidget(self.normalize_reset_widget)
        self.container_steps_layout.addWidget(QtWidgets.QLabel("Right-click range to add new gate, right click gate for configuration"))
        self.container_steps_layout.addStretch()


    @QtCore.Slot()
    def _add_gate_cb(self):
        ''' adds a new gate at the current input position '''
        value = self._axis_value
        gate = self.gate_data.findGate(value)
        if gate:
            # display a warning a gate is already there
            message_box = QtWidgets.QMessageBox()
            message_box.setText("A gate already exists at this location")
            pixmap = load_pixmap("warning.svg")
            pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
            message_box.setIconPixmap(pixmap)
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            gremlin.util.centerDialog(message_box)
            message_box.exec()
            return
        
        # add the gate
        gate = GateInfo(value = value, parent = self.gate_data)
        self.gate_data.registerGate(gate)
        self._update_ui()


    @QtCore.Slot()
    def _set_steps_cb(self):
        ''' sets the number of steps to set/reset when the set step button is clicked'''
        value = self.sb_steps_widget.value()
        gate_count = self.gate_data.steps
        if gate_count > value:
            # if reducing - warn
            message_box = QtWidgets.QMessageBox()
            message_box.setText("Reduce gate confirmation")
            message_box.setInformativeText("This will reduce gates, delete gate configurations and normalize gates.\nAre you sure?")
            pixmap = load_pixmap("warning.svg")
            pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
            message_box.setIconPixmap(pixmap)
            message_box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Ok |
                QtWidgets.QMessageBox.StandardButton.Cancel
                )
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            gremlin.util.centerDialog(message_box)
            result = message_box.exec()
            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                self._set_steps_confirm_cb(value)
            return

        if gate_count < value:
            self.gate_data.setGateCount(value)
            self._update_gates_ui() # update for changes
    
    def _set_steps_confirm_cb(self, value):
        self.gate_data.setGateCount(value)
        self._update_gates_ui()
        self._normalize_cb()
            

    @QtCore.Slot()
    def _normalize_cb(self):
        ''' normalize button  '''
        value = self.sb_steps_widget.value()
        #self.gate_data.gates = value
        self.gate_data.normalize_steps(True)
        self._update_gates_ui()
        self._update_values_cb(self.gate_data)


    def _normalize_reset_cb(self):
        ''' normalize reset button  '''
        value = self.sb_steps_widget.value()
        #self.gate_data.gates = value
        self.gate_data.normalize_steps(False)
        self._update_gates_ui()
        self._update_values_cb(self.gate_data)


    @QtCore.Slot(object)
    def _update_steps_cb(self, gate_data):
        ''' updates gate steps on the widget and their positions '''
        if self.gate_data == gate_data:
            self._update_gates_ui() # update gate manual update UI
            self._update_values_cb(self.gate_data)
        

    @QtCore.Slot(object)
    def _update_values_cb(self, gate_data):
        ''' called when gate data values are changed '''
        if self.gate_data == gate_data:
            values = self.gate_data.getGateValues()
            if values != self.slider.value():
                with QtCore.QSignalBlocker(self.slider):
                    self._set_slider(values)
                

    def _update_output_value(self):
        triggers = self.gate_data.process_triggers(self._axis_value)

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
            self._set_slider(lv)
            
        
        self._update_steps_cb()
        self._update_output_value()

    QtCore.Slot()
    def _max_changed_cb(self):
        value = self.sb_max_widget.value()
        self.gate_data.max = value
        lv = list(self.slider.value())
        lv[1] = value
        with QtCore.QSignalBlocker(self.slider):
            self._set_slider(lv)
        self._update_steps_cb()
        self._update_output_value()


    def _update_ui(self):
        ''' updates visibility of UI components based on the active options '''
        # update the slider configuration
        self._set_slider(self.gate_data.getGateValues())
        self._update_output_value()


    def deleteGate(self, data):
        ''' remove the gat fromt his widget '''
        self.gate_data.deleteGate(data)
        self._update_gates_ui()
        self._update_ui()

  

class ActionContainerUi(QtWidgets.QDialog):
    """UI to setup the individual action trigger containers and sub actions """

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz

    def __init__(self, gate_data, info_object, action_data, parent=None):
        '''
        :param: data = the gate or range data block
        
        '''
        
        super().__init__(parent)

        is_range = isinstance(info_object, RangeInfo)
        self._info = info_object
    
        self._gate_data : GateData = gate_data
        self._is_range = is_range
        self._action_data = action_data

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        # Actual configuration object being managed
        self.setMinimumWidth(600)
        self.setMinimumHeight(800)
        
        self.trigger_container_widget = QtWidgets.QWidget()
        self.trigger_condition_layout = QtWidgets.QHBoxLayout(self.trigger_container_widget)

        if is_range:
            # range has an output mode for how to handle the output value for the range

            self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Range Configuration: {info_object.range_display()}"))

            
            self.slider_frame_widget = QtWidgets.QFrame()
            self.slider_frame_layout = QtWidgets.QVBoxLayout(self.slider_frame_widget)
            self.slider_frame_widget.setStyleSheet('.QFrame{background-color: lightgray;}')
            self.slider = ui_common.QMarkerDoubleRangeSlider()
            self.slider.setOrientation(QtCore.Qt.Horizontal)
            self.slider.setRange(-1,1)
            self.slider_frame_layout.addWidget(self.slider)
            values = self._gate_data.getGateValues()
            self.slider.setValue(values)
            self.slider.setReadOnly(True)


            self.axis_widget = ui_common.AxisStateWidget(orientation = QtCore.Qt.Orientation.Horizontal, show_percentage=False)
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event_cb)

            self.output_mode_widget = QtWidgets.QComboBox()
            self.output_container_widget = QtWidgets.QWidget()
            self.output_container_widget.setContentsMargins(0,0,0,0)
            self.output_container_layout = QtWidgets.QHBoxLayout(self.output_container_widget)
            self.output_container_layout.addWidget(QtWidgets.QLabel("Output Mode:"))
            self.output_container_layout.addWidget(self.output_mode_widget)
            self.output_container_layout.addWidget(QtWidgets.QLabel("Output Value:"))
            self.output_container_layout.addWidget(self.axis_widget)
            self.output_container_layout.addStretch()
            

            # populates and picks the default mode
            self._gate_data.populate_output_widget(self.output_mode_widget, default = self._info.mode)
            self.output_mode_widget.currentIndexChanged.connect(self._output_mode_changed_cb)

            # ranged data
            self.container_output_range_widget = QtWidgets.QWidget()
            self.container_output_range_layout = QtWidgets.QHBoxLayout(self.container_output_range_widget)
            self.container_output_range_widget.setContentsMargins(0,0,0,0)
            
            self.sb_range_min_widget = ui_common.QFloatLineEdit()
            self.sb_range_min_widget.setValue(info_object.range_min)
            self.sb_range_min_widget.valueChanged.connect(self._range_min_changed_cb)

            self.sb_range_max_widget = ui_common.QFloatLineEdit()
            self.sb_range_max_widget.setValue(info_object.range_max)

            self.sb_range_max_widget.valueChanged.connect(self._range_max_changed_cb)

            self.sb_fixed_value_widget = ui_common.QFloatLineEdit()
            if info_object.fixed_value is None:
                info_object.fixed_value = info_object.v1
            self.sb_fixed_value_widget.setValue(info_object.fixed_value)
            self.sb_fixed_value_widget.valueChanged.connect(self._fixed_value_changed_cb)

            self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range options:"))
            self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Min:"))
            self.container_output_range_layout.addWidget(self.sb_range_min_widget)
            self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Max:"))
            self.container_output_range_layout.addWidget(self.sb_range_max_widget)
            self.container_output_range_layout.addStretch()
            
            self.container_fixed_widget = QtWidgets.QWidget()
            self.container_fixed_widget.setContentsMargins(0,0,0,0)
            self.container_fixed_layout = QtWidgets.QHBoxLayout(self.container_fixed_widget)
            self.container_fixed_layout.addWidget(QtWidgets.QLabel("Fixed Value:"))
            self.container_fixed_layout.addWidget(self.sb_fixed_value_widget)
            self.container_fixed_layout.addStretch()

            self.container_range_data_widget = QtWidgets.QWidget()
            self.container_range_data_widget.setContentsMargins(0,0,0,0)
            self.container_range_data_layout = QtWidgets.QVBoxLayout(self.container_range_data_widget)
            self.container_range_data_layout.addWidget(self.slider_frame_widget)
            self.container_range_data_layout.addWidget(self.container_output_range_widget)
            self.container_range_data_layout.addWidget(self.container_fixed_widget)
            
            

        else:
            # gate configuration
            self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Gate {self._info.slider_index + 1} Configuration:"))

            # delay
            self.delay_widget = QtWidgets.QSpinBox()
            self.delay_widget.setRange(0,5000)
            self.delay_widget.setValue(self._info.delay)
            self.delay_widget.setToolTip("Delay in milliseconds between a press and release event for gate crossings")
            self.delay_widget.valueChanged.connect(self._delay_changed_cb)
            self.trigger_condition_layout.addWidget(QtWidgets.QLabel("Trigger Delay:"))
            self.trigger_condition_layout.addWidget(self.delay_widget)

                

        

        self.condition_widget = QtWidgets.QComboBox()
        self.condition_description_widget = QtWidgets.QLabel()
        self.condition_widget.currentIndexChanged.connect(self._condition_changed_cb)
        
        self.container_widget = None


        #self.trigger_condition_layout.addWidget(self.action_widget)
        self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Condition:"))
        self.trigger_condition_layout.addWidget(self.condition_widget)
        self.trigger_condition_layout.addWidget(self.condition_description_widget)
        self.trigger_condition_layout.addStretch()

        if not is_range:

            # gates can be deleted (ranges cannot since they are defined by gates)
            self.clear_button_widget = ui_common.QDataPushButton()
            self.clear_button_widget.setIcon(load_icon("mdi.delete"))
            self.clear_button_widget.setMaximumWidth(20)
            self.clear_button_widget.data = self._info
            self.clear_button_widget.clicked.connect(self._delete_gate_confirm_cb)
            self.clear_button_widget.setToolTip("Removes this entry")

            self.trigger_condition_layout.addWidget(self.clear_button_widget)
       
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(self.trigger_container_widget)
        if is_range:
            self.main_layout.addWidget(self.output_container_widget)
            self.main_layout.addWidget(self.container_range_data_widget)
        
        self._update_ui()
        self._condition_changed_cb()


    @QtCore.Slot(object)
    def _joystick_event_cb(self, event):
        ''' updates axis output based on input '''

        if not self._is_range:
            # not a range input
            return
        
        if gremlin.shared_state.is_running:
            # not running - don't process containers
            return
        
        if not event.is_axis:
            # ignore if not an axis event
            return

        if self._action_data.hardware_device_guid != event.device_guid:
            # ignore if a different input device
            return
            
        if self._action_data.hardware_input_id != event.identifier:
            # ignore if a different input axis on the input device
            return
      
        # scale the raw hardware value
        if not event.is_virtual:
            # input is -1 to + 1 for virtual inputs, but -32767 to 32767 for raw hardware
            value = scale_to_range(event.raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1)

        # update the marker position
        self.slider.setMarkerValue(value)
        
        value = self._gate_data._get_filtered_range_value(self._info, value)
        if value is not None:
            self.axis_widget.setValue(value)

    QtCore.Slot()
    def _delay_changed_cb(self):
        ''' delay value changed for gates '''
        self._info.delay = self.delay_widget.value()

    QtCore.Slot()
    def _delete_gate_confirm_cb(self):
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
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_confirmed_cb(data)

    def _delete_confirmed_cb(self, data):
        self.delete_requested.emit(self._info)
        self.close()

    


    QtCore.Slot()
    def _range_min_changed_cb(self):
        value = self.sb_range_min_widget.value()
        self._info.output_range_min = value
        

    QtCore.Slot()
    def _range_max_changed_cb(self):
        self._info.output_range_max = self.sb_range_max_widget.value()

    QtCore.Slot()
    def _fixed_value_changed_cb(self):
        self._info.fixed_value = self.sb_fixed_value_widget.value()

    @QtCore.Slot()
    def _output_mode_changed_cb(self):
        ''' change the output mode of a range'''
        value = self.output_mode_widget.currentData()
        self._info.mode = value
        self._update_ui()
    
    @QtCore.Slot()
    def _condition_changed_cb(self):
        condition = self.condition_widget.currentData()
        self._info.condition = condition
        self._update_containers()
        
    def _update_containers(self):
        from gremlin.ui.device_tab import InputItemConfiguration
        if self.container_widget is not None:
            self.main_layout.removeWidget(self.container_widget)
            self.container_widget.deleteLater()
        
        item_data = self._info.itemData(self._info.condition)
        self.container_widget = InputItemConfiguration(item_data)
        self.main_layout.addWidget(self.container_widget)
        

    def _update_ui(self):
        ''' updates controls based on the options '''
        if self._is_range:
            # range conditions
            conditions = (GateCondition.EnterRange, GateCondition.ExitRange, GateCondition.InRange, GateCondition.OutsideRange)

            fixed_visible = self._info.mode == GateRangeOutputMode.Fixed
            range_visible = self._info.mode == GateRangeOutputMode.Ranged

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

