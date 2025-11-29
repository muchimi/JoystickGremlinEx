# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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
import os
from lxml import etree as ElementTree
from PySide6 import QtWidgets, QtCore, QtGui #QtWebEngineWidgets


from gremlin.input_types import InputType

import gremlin.shared_state

import gremlin.ui.input_item


import gremlin.util
from gremlin.util import *
from gremlin.types import *

from enum import Enum, auto
import gremlin.util
import gremlin.singleton_decorator
from gremlin.util import InvokeUiMethod
import gremlin.util
from itertools import pairwise, groupby 
import gremlin.actions
from shiboken6 import Shiboken
import gremlin.repeater
import psygnal
from psygnal import Signal

import gremlin.ui.ui_common
import gremlin.joystick_handling
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.threading


syslog = logging.getLogger("system")
MAX_UNDO = 20 # number of steps on the UNDO stack

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

    

class GateConditionType(Enum):
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
    GateDecrease = auto() # gate crossed, decreasing
    GateIncrease = auto() # gate crossed, increasing
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
    TriggerMode.GateIncrease: "gate_increase",
    TriggerMode.GateDecrease: "gate_decrease",
    TriggerMode.FixedValue: "fixed_value",
    TriggerMode.RangeEnter: "range_enter",
    TriggerMode.RangeExit: "range_exit",

}

_trigger_mode_to_display_name = {
    TriggerMode.Value: "Value",
    TriggerMode.RangedValue: "Ranged Value",
    TriggerMode.ValueInRange: "In Range",
    TriggerMode.ValueOutOfRange: "Out of Range",
    TriggerMode.GateCrossed: "Gate Crossed",
    TriggerMode.GateDecrease: "Gate Crossed (inc)",
    TriggerMode.GateIncrease: "Gate Crossed (dec)",
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
    "gate_increase": TriggerMode.GateIncrease,
    "gate_decrease": TriggerMode.GateDecrease,
    "fixed_value": TriggerMode.FixedValue,
    "range_enter": TriggerMode.RangeEnter,
    "range_exit": TriggerMode.RangeExit,
}
    

_decimals = 5
_single_step = 0.001
 


_gate_condition_to_name = {
    GateConditionType.InRange: "in_range",
    GateConditionType.OutsideRange: "outside_range",
    GateConditionType.OnCross: "cross",
    GateConditionType.OnCrossIncrease: "cross_inc",
    GateConditionType.OnCrossDecrease: "cross_dec",
    GateConditionType.EnterRange: "enter_range",
    GateConditionType.ExitRange: "exit_range"
}


_gate_condition_to_display_name = {
    GateConditionType.InRange: "In Range",
    GateConditionType.OutsideRange: "Outside of Range",
    GateConditionType.OnCross: "Crossed",
    GateConditionType.OnCrossIncrease: "Cross (inc)",
    GateConditionType.OnCrossDecrease: "Cross (dec)",
    GateConditionType.EnterRange: "Enter Range",
    GateConditionType.ExitRange: "Exit Range"
}

_gate_condition_to_enum = {
    "in_range": GateConditionType.InRange,
    "outside_range": GateConditionType.OutsideRange,
    "cross": GateConditionType.OnCross,
    "cross_inc": GateConditionType.OnCrossIncrease,
    "cross_dec": GateConditionType.OnCrossDecrease,
    "enter_range" : GateConditionType.EnterRange,
    "exit_range" : GateConditionType.ExitRange
}

_gate_condition_description = {
    GateConditionType.InRange: "Triggers whenever the input value is in range",
    GateConditionType.OutsideRange: "Triggers whenever the input value is outside the range",
    GateConditionType.OnCross: "Triggers when the input crosses a gate",
    GateConditionType.OnCrossDecrease: "Triggers when the input crosses a gate (crossing from the right/above)",
    GateConditionType.OnCrossIncrease: "Triggers when the input crosses a gate (crossing from the left/below)",
    GateConditionType.EnterRange: "Triggers when the input value enters the range",
    GateConditionType.ExitRange: "Triggers when the input value exits the range"
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


class GateInfo():
    ''' holds gate data information '''
    


    def __init__(self, slider_index = -1, id = None, value = None, parent = None, delay = 250, used = False):
        ''' holds gate information data 
        :param index: gate index
        :param id: id (str) guid of this gate - unique
        :param value: float, value between -1 and +1
        :param profile_mode: associated profile mode
        :param parent: gate data owner of this gate
        :param delay: delay
        :param slider index: int, index in the slider, should be the same as index in most cases
        :param used: true if the gate is used
        :param validate_callback: validation call back when the gate value is being set - if set, should return True if the value passed is valid for the gate

        
        '''

        assert parent is not None, "Gates must be parented to a GateData object " # = must provide this parameter
        self.parent : GateData = parent

        
        assert value is not None, "Gate must have a value"
        self._id = get_guid() if id is None else id
        
        assert isinstance(self._id,str)
        value = gremlin.util.clamp(value, -1, 1)
        self._value = value
        self._description = None

        self._last_condition = GateConditionType.OnCross
        self.item_data_map = {}
        

        self._used = used
        self._slider_index = slider_index # index of the gate in the slider
        self._delay = delay  # delay in milliseconds for the trigger duration between a press and release
        self._error = False # no error state

        eh = gremlin.event_handler.EventListener()
        eh.mapping_changed.connect(self._item_data_changed)

        self.autorelease_map = {
            GateConditionType.OnCross: True,
            GateConditionType.OnCrossDecrease: True,
            GateConditionType.OnCrossIncrease: True,
        }

    @property
    def description(self) -> str:
        return self._description
    @description.setter
    def description(self, value : str):
        self._description = value

    @property
    def delay(self) -> int:
        return self._delay
    @delay.setter
    def delay(self, value : int):
        if value >= 0:
            self._delay = value

    def to_xml(self):
        ''' generates an xml node from the gate data '''
        node = ElementTree.Element("gate-info")
        node.set("id", self._id)
        node.set("index", str(self.index))
        node.set("value", safe_format(self._value, float))
        node.set("used", str(self._used))
        node.set("delay", safe_format(self.delay, int))
        if self.description:
            node.set("description", self.description)

        for condition, item in self.item_data_map.items():
            condition_node = ElementTree.Element("gate-condition")
            condition_node.set("condition", GateConditionType.to_string(condition))
            item_node = item.to_xml()
            condition_node.append(item_node)
            node.append(condition_node)

        return node

    def from_xml(self, node, extra_data = None):
        self.id = node.get("id")
        self.setIndex(safe_read(node,"index",int,0))
        self.value = safe_read(node,"value",float,0)
        self.used = safe_read(node,"used",bool,False)
        self.delay = safe_read(node,"delay",int,250)
        description = safe_read(node,"description", str, "")
        if description:
            self.description = description
        else:
            self.description = None

        for condition_node in node:
            condition = GateConditionType.to_enum(condition_node.get("condition"))
            item_node = condition[0]
            item = self.parent._new_item_data()
            item.from_xml(item_node)
            self.item_data[condition] = item
            



    @property
    def slider_index(self) -> int:
        return self._slider_index
    @slider_index.setter
    def slider_index(self, value: int):
        self.setIndex(value)

    @property
    def index(self) -> int:
        return self._slider_index
    @index.setter
    def index(self, value : int):
        self.setIndex(value)

    def setIndex(self, value : int, emit = False):
        ''' sets the slider index, optionallyu triggering an update '''
        if value != self._slider_index:
            self._slider_index = value
            if emit:
                gh = GateEventHandler()
                gh.gate_index_changed.emit(self)


    @property
    def isError(self) -> bool:
        return self._error
    @isError.setter
    def isError(self, value : bool):
        self._error = value

    @property
    def condition(self):
        ''' last condition selected '''
        return self._last_condition
    
    def setLastCondition(self, condition : GateConditionType):
        ''' sets the last used condition '''
        self._last_condition = condition

    @property
    def containerCount(self) -> int:
        ''' gets the container count '''
        return sum(len(item_data.containers) for item_data in self.item_data_map.values())
    
    @property
    def used(self):
        return self._used
    
    @used.setter
    def used(self, value):
        if self._used != value:
            self._used = value
            # fire the change event
            eh = GateEventHandler()
            eh.gate_used_changed.emit(self)

    def setUsed(self, value : bool):
        ''' sets the used flag without firing a change event '''
        self._used = value


    
    
    @staticmethod
    def copy_from(other : GateInfo):
        gi = GateInfo(value = other.value,
                      condition = other.condition,
                      parent = other.parent,
                      delay=other.delay,
                      auto_register = False)
        gi.description = other.description
        gi.item_data_map = other.item_data_map
        gi.slider_index = other.slider_index
        return gi


    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, data):
        self.setValue(data, True)

    def setValue(self, value : float, emit : bool = False):
        ''' sets the value '''
        if self._value == value:
            return # nothing to do
        gh = GateEventHandler()
        g1,g2 = self.parent.getGateSiblings(self)
        offset = 0.001
        if g1:
            if value < (g1.value + offset):
                gh.gate_display_changed.emit(self)
                return # ignore
        if g2:
            if value > (g2.value - offset):
                gh.gate_display_changed.emit(self)
                return # ignore
        
        if not gremlin.util.is_close(value,self._value):
            self._value = value
            self.parent._update_ranges()
            
            # self.parent._update_gate_index() # re-index based on value so the gate is always in sequence
          
            if emit:
                # tell listeners the value changed
                gh.gate_value_changed.emit(self)
            gh.gate_display_changed.emit(self)



        

    def itemData(self, condition : GateConditionType):
        ''' gets the inputitem for the given condition '''
        if not condition in self.item_data_map.keys():
            data = self.parent._new_item_data()
            data.input_type = InputType.JoystickButton
            data.input_id = 1
            self.item_data_map[condition] = data
        return self.item_data_map[condition]

    def setItemData(self, condition, value):
        self.item_data_map[condition] = value

    @QtCore.Slot(object)
    def _item_data_changed(self, item_data : gremlin.base_profile.InputItem):
        ''' called on container or action add/remove '''
        for item in self.item_data_map.values():
            if item._id == item_data._id:
                # notify the gate has changed
                eh = GateEventHandler()
                eh.gate_configuration_changed.emit(self)
                break

        

    def hasContainers(self, condition : GateConditionType) -> bool:
        ''' true if the range has any mappings in any mode '''
        if condition in self.item_data_map:
            item_data = self.item_data_map[condition]
            return len(item_data.containers) > 0
        return False
    
    def hasAnyContainers(self):
        ''' true if the gate has conditions defined on at least one condition '''
        for item_data in self.item_data_map.values():
            if len(item_data.containers) > 0:
                return True
        return False
    

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
    def display_value(self) -> float:
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
    
    def gate_display(self) -> str:
        mode = self.parent.display_mode if self.parent is not None else DisplayMode.Normal      
        if mode == DisplayMode.Normal:
            rng = self.parent.display_range_max - self.parent.display_range_min
            decimals = 0 if rng > 2 else 3
        elif mode == DisplayMode.OneOne:
            decimals = 3
        else: # percent
            decimals = 2

        msg = f"Gate {self.slider_index} [{self.display_value:0.{decimals}f}]"
        if self.description:
            msg += f" ({self.description})"
        return msg
    
    def to_display(self) -> str:
        return self.gate_display()
    
    def __str__(self):
        has_crossing = GateConditionType.OnCross in self.item_data_map and bool(self.item_data_map[GateConditionType.OnCross])
        has_crossing_inc = GateConditionType.OnCrossIncrease in self.item_data_map and bool(self.item_data_map[GateConditionType.OnCrossIncrease])
        has_crossing_dec = GateConditionType.OnCrossDecrease in self.item_data_map and bool(self.item_data_map[GateConditionType.OnCrossDecrease])
        map_stub = f" mappings: on cross: {gremlin.util.ansiText(has_crossing)} on crossing inc: {gremlin.util.ansiText(has_crossing_inc)} on cross dec: {gremlin.util.ansiText(has_crossing_dec)}"
        return self.gate_display() + f" gate id: {self.id}{map_stub}"
        
    def __eq__(self, other):
        if other is None:
            return False
        if self.id == other.id:
            return True # same gate
        r1 = round(self.value, 3)
        r2 = round(other.value, 3)
        return r1 == r2
    
    
        

    def __hash__(self):
        return hash(self.id)

class RangeInfo():
    


    def __init__(self,
                 min_gate,
                 max_gate,
                 mode = GateRangeOutputMode.Normal,
                 parent = None,
                 used = False):

        assert parent is not None, "Ranges must be parented to a GateData object " # = must provide this parameter
        #assert min_gate is not None and max_gate is not None, "Gates must be provided on range object"
        self.parent : GateData = parent
        self._id = gremlin.util.get_guid()

        self._output_mode = None
        self._output_range_min = None
        self._output_range_max = None
        self._last_condition = GateConditionType.InRange
        self._description = None
        self.item_data_map = {}
        self.delay = 250 # default delay
        self.g1 = min_gate
        self.g2 = max_gate


        # autorelease map for modes that support autorelease (non-linear modes), key = GateConditionType, value = boolean, true for autorelease
        self.autorelease_map = {
            GateConditionType.EnterRange: True,
            GateConditionType.ExitRange: True,
            GateConditionType.InRange: False,
            GateConditionType.OutsideRange: False
        }
        

        assert id is not None, "ID must be provided"
        assert min_gate is not None,"Min gate must be provided "
        assert max_gate is not None,"Max gate must be provided "
        

        g1 = self._get_gate(min_gate.id)
        assert g1 is not None, "Min gate not registered"

        g2 = self._get_gate(max_gate.id)
        assert g2 is not None, "Max gate not registered"

        self._used = used # this is set later when ranges are activated
   
  
        #self.item_data = item_data
        self.mode = mode # output mode determines what we do with the input data
        self._fixed_value = None # fixed value to output for this range if the condition is Fixed
        self._swap_gates() # flip the gates so the values are always increasing 

    
    @property
    def description(self) -> str:
        return self._description
    @description.setter
    def description(self, value : str):
        self._description = value

    def to_display(self):
        if self.v1 is None or self.v2 is None:
            rr = f"N/A"
        else:
            rr = self.range_display()
        return rr


    def valueInRange(self, value: float) -> bool:
        ''' true if the value is within the current range '''
        if value is None:
            return False
        return value >= self.v1 and value <= self.v2

    @property
    def condition(self):
        ''' last condition selected '''
        return self._last_condition
    
    def setLastCondition(self, condition : GateConditionType):
        ''' sets the last used condition '''
        self._last_condition = condition

    
    @property
    def used(self) -> bool:
        return self._used and self.g1.used and self.g2.used
    
    @used.setter
    def used(self, value):
        if self._used != value:
            self._used = value
            # fire the change event
            eh = GateEventHandler()
            eh.range_used_changed.emit(self)        

    def setUsed(self, value):
        ''' sets the used flag without triggering an event '''
        self._used = value
        

    def hasContainers(self, condition : GateConditionType) -> bool:
        ''' true if the range has any mappings in any mode '''
        if condition in self.item_data_map:
            item_data = self.item_data_map[condition]
            return len(item_data.containers) > 0
        return False
    
    def hasAnyContainers(self):
        ''' true if the range has conditions defined on at least one condition '''
        for item_data in self.item_data_map.values():
            if len(item_data.containers) > 0:
                return True
        return False
    

    def copy_from(self, other : RangeInfo):
        ''' copies data from another range object '''

        self._condition = other._condition
        self._output_mode = other._output_mode
        self._fixed_value = other._fixed_value
        self._output_range_min = other._output_range_min
        self._output_range_max = other._output_range_max
        self.g1 = other.g1
        self.g2 = other.g2
        self.item_data_map = other.item_data_map
        self.description = other.description
        # print (f"Range: copyfrom: {self.range_display()}")
        

    @property
    def containerCount(self) -> int:
        ''' gets the container count '''
        return sum(len(item_data.containers) for item_data in self.item_data_map.values())
    


    def _get_gate(self, id):
        gate = self.parent.getGate(id)
        if gate is None:
            gates =self.parent.getGates(id, used_only = False)
            syslog.info(f"Gate not found: {id}")
            for g in gates:
                syslog.info(f"\tGate {g.id} value: {g.value} used: {g.used}")
            return None
        return gate

    def itemData(self, condition : GateConditionType):
        ''' gets the inputitem for the given condition '''
        if not condition in self.item_data_map.keys():
            item_data = self.parent._new_item_data()
            # use ranged containers/actions for range conditions, buttons for the others
            input_type = InputType.JoystickAxis if condition in (GateConditionType.InRange, GateConditionType.OutsideRange) else InputType.JoystickButton
            item_data.input_type = input_type
            # action_data = self.parent._action_data
            self.item_data_map[condition] = item_data
        return self.item_data_map[condition]

    def setItemData(self, condition, value):
        self.item_data_map[condition] = value


    @property
    def range_min(self):
        ''' current min range '''
        return self.g1.value
    
    @range_min.setter
    def range_min(self, value):
        self.g1.value = value
        
    
    @property
    def range_max(self):
        ''' current max range '''
        return self.g2.value
    
    @range_max.setter
    def range_max(self, value):
        self.g2.value = value
        

    @property
    def output_range_min(self):
        ''' output range min '''
        if self._output_range_min is None:
            return self.g1.value
        return self._output_range_min
    
    @output_range_min.setter
    def output_range_min(self, value):
        self._output_range_min = value
        self._swap_output_ranges()
    
    @property
    def output_range_max(self):
        ''' output range max '''
        if self._output_range_max is None:
            return self.g2.value
        return self._output_range_max
    
    @output_range_max.setter
    def output_range_max(self, value):
        self._output_range_max = value
        self._swap_output_ranges()

    
    def range(self) -> tuple[float, float]:
        ''' returns the tuple of range values '''
        g1 = self.g1
        g2 = self.g2
        if g1 and g2:
            v1 = g1.value
            v2 = g2.value
            if v1 > v2:
                # swap
                v1, v2 = v2, v1
            return (v1,v2)
        return (None, None)
    
    def inRange(self, value : float):
        ''' true if in range '''
        v1,v2 = self.range()
        return gremlin.util.valueInRange(value, v1, v2)
       
    
    
    def output_range(self):
        ''' gets the output range '''
        return (self.output_range_min, self.output_range_max)
    
    @property
    def id(self) -> str:
        ''' unique ID of this range '''
        return self._id
    @id.setter
    def id(self, value : str):
        self._id = value


    @property
    def condition(self) -> GateConditionType:
        return self._last_condition
    
    def setLastCondition(self, value : GateConditionType):
        ''' sets the last condition '''
        assert value in [c for c in GateConditionType]
        self._last_condition = value
        

    @property
    def mode(self) -> GateRangeOutputMode:
        return self._output_mode
    @mode.setter
    def mode(self, value : GateRangeOutputMode):
        assert value in [c for c in GateRangeOutputMode]
        self._output_mode = value

    @property
    def fixed_value(self) -> float:
        ''' output value of the range when in fixed output mode '''
        return self._fixed_value
    
    @fixed_value.setter
    def fixed_value(self, data: float):
        if data is None:
            # not set
            self._fixed_value = data
        else:
            # check range
            if data < -1.0:
                data = -1.0
            elif data > 1.0:
                data = 1.0
            if self._fixed_value is None or data != self._fixed_value:
                self._fixed_value = data

  

    def set_gates(self, g1 : GateInfo, g2 : GateInfo):
        ''' sets both gates for the range '''
        
        assert abs(g1.value - g2.value) >= 0.001,"Ranges require two different gates"
        if self.g1.id != g1.id or self.g2.id != g2.id:
            self.g1 = g1
            self.g2 = g2
            self._swap_gates()
            self.updateWidget()

           

    def _gate_used_changed_cb(self, gate):
        ''' occurs when either gate usage changes '''
        if gate.id == self.g1.id or gate.id == self.g2.id:
            # update the used flag based on the two gates
            self.used = self.g1.used and self.g2.used


    @property
    def v1(self) -> float:
        ''' gets the min value of the range '''
        if self.g1:
            return self.g1.value
        return None
    
    @property
    def v2(self) -> float:
        ''' gets the max value of the range '''
        if self.g2:
            return self.g2.value
        return None
    
    @property
    def v1_display(self) -> str:
        if self.g1.id:
            return self.g1.display_value
        return None
    
    @property
    def v2_display(self) -> str:
        if self.g2.id:
            return self.g2.display_value
        return None
    
    def inrange(self, value : float, inclusive = True):
        ''' true if the value is within the current range,  inclusive = true if bounds are included '''
        v1,v2 = self.v1, self.v2
        return gremlin.util.valueInRange(value,v1,v2, not inclusive)


    def _swap_gates(self):
        ''' ensures gates are in the order min/max '''
        if self.g2.value < self.g1.value:
            self.g1, self.g2 = self.g2, self.g1

        

    def _swap_output_ranges(self):
        ''' ensures output range goes from min to max '''
        if self._output_range_max is not None and self._output_range_min is not None:
            if self._output_range_max < self._output_range_min:
                self._output_range_max, self._output_range_min = self._output_range_min, self._output_range_max
            
                

    def range_gates(self) -> tuple[GateInfo,GateInfo]:
        ''' returns the range gates'''
        return (self.g1, self.g2)
    

    
    def range_display(self) -> str:
        ''' gets a range display string for this range '''
        
        mode = self.parent.display_mode if self.parent is not None else DisplayMode.Normal
        if mode == DisplayMode.Normal:
            rng = self.parent.display_range_max - self.parent.display_range_min
            decimals = 0 if rng > 2 else 3
            
        elif mode == DisplayMode.OneOne:
            decimals = 3
        else: # percent
            decimals = 2

        delta = abs(self.g1.value - self.g2.value)
        msg = f"[{self.v1_display:+0.{decimals}f},{self.v2_display:+0.{decimals}f}]({delta:+0.{decimals}f})"
        if self._description:
            msg += f" ({self._description})"
        return msg
    
    def range_gate_display(self) -> str:
        ''' displays the gate IDs for this range '''
        return f"Range Gates [{self.g1.index}, {self.g2.index}]"
    
    def range_display_ex(self) -> str:
        '''
        displays the complete range info
        '''
        return f"{self.range_gate_display()} {self.range_display()}  Mode: {GateRangeOutputMode.to_display_name(self.mode)} ID: {self.id}]"
    
    def to_percent(self, value) -> float:
        ''' converts the value to a percent for this range 0 to 1'''
        v1 = self.v1
        v2 = self.v2
        if v1 == v2:
            return 10
        return gremlin.util.scale_to_range(value,v1,v2,0,100)

    def __str__(self):
        if self.v1 is None or self.v2 is None:
            rr = f"N/A"
        else:
            rr = f"{self.range_display()} {self.description}"
        fixed_value = f"{self._fixed_value:0.{_decimals}f}" if self._fixed_value else "n/a"
        output_range_min = f"{self._output_range_min:0.{_decimals}f}" if self._output_range_min else "n/a"
        output_range_max = f"{self._output_range_max:0.{_decimals}f}" if self._output_range_max else "n/a"
        has_enter = GateConditionType.EnterRange in self.item_data_map and bool(self.item_data_map[GateConditionType.EnterRange])
        has_exit = GateConditionType.ExitRange in self.item_data_map and bool(self.item_data_map[GateConditionType.ExitRange])
        has_in_range = GateConditionType.InRange in self.item_data_map and bool(self.item_data_map[GateConditionType.InRange])
        has_out_range = GateConditionType.OutsideRange in self.item_data_map and bool(self.item_data_map[GateConditionType.OutsideRange])

        map_stub = f" mappings:  in range: {has_in_range}  outside range: {has_out_range} on enter: {has_enter} on exit: {has_exit}"


        return f"Range [{rr}] mode: {self.mode}  id: {self.id} g1 id: {self.g1.id} g2 id: {self.g2.id} Fixed: {fixed_value} Output range min: {output_range_min} max: {output_range_max}{map_stub}"
    
    def __eq__(self, other):
        ''' compares to range objects by range value '''
        if other is None:
            return False
        return gremlin.util.is_close(self.v1, other.v1) and gremlin.util.is_close(self.v2, other.v2)
    
    def __hash__(self):
        return hash((self.g1.id, self.g2.id))
    


@gremlin.singleton_decorator.SingletonDecorator
class TriggerTracking():
    ''' class that holds trigger information for previously generated triggers by category '''

    def __init__(self):
        self._tracking_map = {} # map of gate or range by generated triggers
        self._triggers = [] # list of triggers

        eh = gremlin.event_handler.EventListener()
        eh.profile_start.connect(self._profile_start)
        

    @QtCore.Slot()
    def _profile_start(self):
        self.clear()


    @property
    def triggers(self) -> list:
        return self._triggers

    def registerTrigger(self, owner, trigger : TriggerData):
        ''' registers/overrides prior trigger '''
        if not owner in self._tracking_map:
            self._tracking_map[owner] = {}
        self._tracking_map[owner][trigger.mode] = trigger
        verbose = gremlin.config.Configuration().verbose_mode_gate
        
        if verbose:
            if isinstance(owner, RangeInfo):
                syslog.info(f"TRIGGER: register range {owner.range_display()}  trigger mode: {trigger.mode} ")
            elif isinstance(owner, GateInfo):
                syslog.info(f"TRIGGER: register gate {owner.slider_index}  trigger mode: {trigger.mode} ")


    def getTrigger(self, owner, mode: TriggerMode):
        ''' gets the registered trigger if present, none if not'''
        if not owner in self._tracking_map:
            return None
        if not mode in self._tracking_map[owner]:
            return None
        return self._tracking_map[owner][mode]
        
    def clearTrigger(self, owner, mode: TriggerMode):
        ''' removes a trigger '''
        if owner in self._tracking_map:
            if mode in self._tracking_map[owner]:
                del self._tracking_map[owner][mode]
                verbose = gremlin.config.Configuration().verbose_mode_gate
                if verbose: syslog.info(f"TRIGGER: clear {str(owner)}  trigger mode: {mode} ")


    def clear(self):
        self._tracking_map.clear()
        self._triggers.clear()

_trigger_tracking = TriggerTracking() # main instance


@gremlin.singleton_decorator.SingletonDecorator
class GateEventHandler(QtCore.QObject):
    ''' handler class for gate axis events '''

 
    display_mode_changed = Signal(DisplayMode) # fires then the display mode changes
    gate_configuration_changed = Signal(GateInfo) # fires when a gate changes its configuration data
    gate_display_changed = Signal(GateInfo) # fires when range display should be updated (sends the gate that was changed)
    gate_index_changed = Signal(GateInfo) # fires when the gate slider index changes
    gate_order_changed = Signal() # fires when the gate order should be updated 
    gate_request_delete = Signal(GateInfo) # fires when a gate delete request is made
    gate_trigger_display = Signal() # adds a gate trigger line to the gate output display
    gate_used_changed = Signal(GateInfo) # fires when the use flag changes on gates
    gate_value_changed = Signal(GateInfo) # fires when a gate value changes (GateInfo)
    gatedata_stepsChanged = Signal(object) # signals that steps (gate counts) have changed  (gatedata)
    gatedata_valueChanged = Signal(object) # signals when the gate data changes (gatedata)
    gates_changed = Signal() # fires when all gates changed
    range_configuration_changed = Signal(RangeInfo) # fires when a range configuration changes
    range_trigger_display = Signal() # adds a range trigger line to the range output display
    range_used_changed = Signal(RangeInfo) # fires when the use flag changes on ranges
    range_value_changed = Signal(RangeInfo) # fires when either of the gate values change
    slider_update_event = Signal(object) # signals a slider to update passes a joystick (event)
    unhook_gate = Signal(object) # fires when the gate is unhooked, object = the gate data object
    visibility_changed = Signal(object, bool) # fires when visibility changes

    
    

    def __init__(self):
        super().__init__()
        self._value_changed_callbacks = {} # tracks value change callbacks
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_gate and config.verbose_mode_extra
        
        if self.verbose: syslog.info("GATEHANDLER: listen start")
        self._event_queue = queue.Queue() # holds the queue of events to process
        
        self._event_thread =  gremlin.threading.AbortableThread(target = self._event_runner)
        self._event_thread.name = "GatedHandler listener"
        self._event_thread.start()

        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_handler)
       
        self._joystick_event_callbacks = {} # tracks callbacks for event changes

        el.shutdown.connect(self._shutdown)


    def _joystick_event_handler(self, event):   
        ''' enqueues the received event for later processing '''
        if self.verbose: syslog.info(f"GATEHANDLER: QUEUE event {event.id}")
        self._event_queue.put(event)

    def _event_runner(self):
        ''' runner for inbound joystick events '''
        while not self._event_thread.stopped():
            if self._event_queue.empty():
                time.sleep(0.01)
                continue
            event = self._event_queue.get()
            if self.verbose: syslog.info(f"GATEHANDLER: DEQUEUE event {event.id} QUEUE size: {self._event_queue.qsize():,}")
            
            for callback in self._joystick_event_callbacks.values():
                callback(event)
            self._event_queue.task_done()


        



    def registerJoystickCallback(self, key, callback):
        ''' registers a joystick callback '''
        self._joystick_event_callbacks[key] = callback
        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose: 
            syslog.info(f"GATE: register callback for action [{key}] callback count: {len(self._joystick_event_callbacks)}")

    def unregisterJoystickCallback(self, key):
        ''' unregisters a joystick callback '''
        verbose = gremlin.config.Configuration().verbose_mode_gate
        if key in self._joystick_event_callbacks:
            del self._joystick_event_callbacks[key]
            if verbose: 
                syslog.info(f"GATE: unregister callback for action [{key}] callback count: {len(self._joystick_event_callbacks)}")
        # else:
        #     syslog.warning(f"GATE: unregister callback for action [{key}]: key not registered.")
        

    def registerValueChangedCallback(self, key, callback):
        ''' registers a value callback '''
        if not key in self._value_changed_callbacks:
            self._value_changed_callbacks[key] = []
        if not callback in self._value_changed_callbacks[key]:
            self._value_changed_callbacks[key].append(callback)

    def unregisterValueChangedCallback(self, key, callback):
        ''' unregisters a value callback '''
        if key in self._value_changed_callbacks:
            if callback in self._value_changed_callbacks[key]:
                self._value_changed_callbacks[key].remove(callback)

    def fireValueChangedCallbacks(self, device_id, input_id, value : float):
        # ensure this is fired on the UI thread
        gremlin.util.InvokeUiMethod(self._fireValueChangedCallbacks, device_id, input_id, value)


    def _fireValueChangedCallbacks(self, device_id, input_id, value : float):
        # update must occur on the UI thread
        gremlin.util.assert_ui_thread()
        for key in self._value_changed_callbacks:
            for callback in self._value_changed_callbacks[key]:
                callback(device_id, input_id, value)

    def _shutdown(self):
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._joystick_event_handler)

        # clear the queue
        if self._event_thread.is_alive():
            if self.verbose: syslog.info("GATEHANDLER: listen stop")
            self._event_thread.stop()
            self._event_thread.join()
            self._event_thread = None

        # mark all events processed
        while not self._event_queue.empty():
            self._event_queue.get_nowait()

        self._joystick_event_callbacks.clear()




class GateData():
    ''' holds gated information for an axis
    
        this object knows how to load and save itself to XML
    '''

    max_gates = 20
    

    def __init__(self,
                 profile_mode, # required - profile mode this applies to (can also be set from XML)
                 action_data : gremlin.base_profile.AbstractAction, # required - action data block (usually the object that contains a functor)
                 min = -1.0,
                 max = 1.0,
                 condition = GateConditionType.OnCross,
                 mode = GateRangeOutputMode.Normal,
                 range_min = -1.0,
                 range_max = 1.0,
                 process_callback = None,  # callback for process changes
                 ):
        ''' GateData constructor '''
        import gremlin.execution_graph


        
        self._process_trigger_lock = threading.Lock()
        self._hooked = False
        self._lock = threading.Lock()
        self._action_data = action_data
        self._input_type = action_data.get_input_type()
        self._device_guid = action_data.hardware_device_guid
        self._device_id = action_data.hardware_device_id
        self._device_name = action_data.hardware_device_name
        self._input_id = action_data.hardware_input_id
        self._ec = gremlin.execution_graph.ExecutionContext()
        self.condition = condition
        self.output_mode = mode
        self.profile_mode = profile_mode # profile mode this gate data applies to (can be set via reading from XML)
        self._valid_mode_list = [] # valid mode list for runtime processing
        self._valid_mode_list_profile_mode = None # profile mode used to check mode branching
        self.fixed_value = 0
        self.range_min = range_min
        self.range_max = range_max
        self.display_range_min = range_min
        self.display_range_max = range_max
        self.macro : gremlin.macro.Macro = None  # macro steps
        self.id = gremlin.util.get_guid()
        
        self.display_mode = DisplayMode.Normal
        self.filter_map = {} # map of conditions to flag - if true, the item is not filtered, if false, filtered - this is for display purposes
        self.range_filter_map = {} # map of range filter

        self._last_value = None # last input value
        self._last_range = None # last range object
        self._last_range_exit_trigger = None # range that triggered the last exit
        self._last_range_enter_trigger = None # range that triggered the last enter
        self._last_in_range_trigger_map = {} # maps the last in-range trigger for a given range



        self._trigger_range_lines = [] # activity triggers
        self._trigger_gate_lines = [] # activity triggers
        self._trigger_line_count = 10 # last 10 triggers max

        self._callbacks = {} # map of containers to their excecution graph callbacks for sub containers
        self._process_callback = process_callback
        self._trigger_callbacks = [] # list of registered trigger callbacks

        self._active_ranges = []
        
        self._axis_value = 0.0

        
        self._ranges : list[RangeInfo] = [] # list of all current computed ranges

        self._gates = [] # list of gates
        self._gate_index_map = {} # map of gate index (smallest to largest) to gate object 
        self._gate_id_map = {} # map of gate ID to gate object
        self._range_item_map = {} # holds the input item data for ranges indexed by range index

        # create the pools of gates and corresponding ranges

        mode = gremlin.shared_state.current_mode


        self.ensureGates()        
        
        
        # hook joystick input for runtime processing of input
        el = gremlin.event_handler.EventListener()

        el.shutdown.connect(self.unhook) # unhook on shutdown
        el.profile_unload.connect(self.unhook) # unkook on profile change



    def ensureGates(self):
        ''' adds at least two gates to the range '''
        gates = self.getGates()
        gate_count = len(gates)
        if gate_count == 1:
            gate = gates[0]
            v1 = gate.value
            v2 = 1 if v1 < 0 else -1
            self.addGate(v2)
        elif gate_count == 0:
            self.addGate(-1, update=False)
            self.addGate(1, update = True)


    def generateGuids(self):
        ''' regenerate all IDs for gates and ranges, such as on a paste operation '''
        self.id = gremlin.util.get_guid()
        
        for gate in self._gates:
            gate.id = gremlin.util.get_guid()
        for rng in self._ranges:
            rng.id = gremlin.util.get_guid()


        #self.updateRanges()
        self._update_ranges()
            

    @property
    def valid_mode_list(self) -> list:
        ''' gets the list of valid profile modes this gate axis can be used for '''
        if not self._valid_mode_list or self._valid_mode_list_profile_mode != self.profile_mode:
            # reload valid profile branches
            self._valid_mode_list = gremlin.shared_state.current_profile.get_mode_branch(self.profile_mode)
            self._valid_mode_list_profile_mode = self.profile_mode
        return self._valid_mode_list




    def hook(self):
        ''' hook events '''
        if not self._hooked:
            self._lock.acquire()
            try:
                self._hooked = True
                verbose = gremlin.config.Configuration().verbose_mode_gate
                if verbose: syslog.info("GATE: hook enabled")

                
                # gh = GateEventHandler()
                # gh.registerJoystickCallback(self.id, self._joystick_event_handler)

                el = gremlin.event_handler.EventListener()
                el.joystick_event.connect(self._joystick_event_handler)


                if self._action_data.input_is_hardware():
                    self._axis_value = gremlin.joystick_handling.get_axis(self._action_data.hardware_device_guid, self._action_data.hardware_input_id)
                else:
                    self._axis_value = self._action_data.hardware_input_id.axis_value
            finally:
                self._lock.release()
            


    def unhook(self):
        ''' unhook events '''
        if self._hooked:
            self._lock.acquire()
            try:
                self._hooked = False
                verbose = gremlin.config.Configuration().verbose_mode_gate
                if verbose: syslog.info("GATE: hook disabled")

                # gh = GateEventHandler()
                # gh.unregisterJoystickCallback(self.id)

                el = gremlin.event_handler.EventListener()
                el.joystick_event.disconnect(self._joystick_event_handler)
            finally:
                self._lock.release()
            


    @property
    def device_guid(self):
        if self._action_data:
            return self._action_data.hardware_device_guid
        return None
    
    @property
    def input_id(self):
        if self._action_data:
            return self._action_data.hardware_input_id
        return None
    

    @property
    def hooked(self) -> bool:
        ''' true if hooks are in place '''
        return self._hooked
  

    def registerTriggerCallback(self, callback):
        ''' registers a trigger callback '''
        if not callback in self._trigger_callbacks:
            self._trigger_callbacks.append(callback)

    def unregisterTriggerCallback(self, callback):
        ''' unregisters a trigger callback '''
        if callback in self._trigger_callbacks:
            self._trigger_callbacks.remove(callback)

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

    def start(self):
        self._profile_start_cb()

    def stop(self):
        self._profile_stop_cb()

    @QtCore.Slot()
    def _profile_start_cb(self):
        ''' profile starts - build execution callbacks by defined container '''
        import gremlin.execution_graph
        import gremlin.event_handler


        # verify the profile mode exists
        profile_mode = self.profile_mode
        if not profile_mode in self.valid_mode_list:
            syslog.error(f"GATE: Mode Error: gated axis is looking for mode: [{profile_mode}] - this mode does not exist in the current profile.  GatedAxis will not trigger.  To fix, call up the gated axis action in the correct mode to reset.")


        
        # build event callback maps from subcontainers in this gated axis
        callbacks_map = {}
        gates = self.getGates()
        self.updateRanges() # ensure we have the latest ranges

        verbose = gremlin.config.Configuration().verbose_mode_detailed
        # verbose = True
        if verbose:
            syslog.info("GateData: Starting profile with ranges:")
            self.dumpActiveRanges()

        self.hook() # ensure hooked

        # build allowed mode list
   

        item_data: gremlin.ui.input_item.InputItemMappingWidget

        eh = gremlin.event_handler.EventHandler()
        ec = gremlin.execution_graph.ExecutionContext()

        # register gate crossings
        for gate in gates:
            callbacks_map[gate] = {}


            for condition, item_data in gate.item_data_map.items():
                if item_data.containers:
                    callbacks = []
                    
                    for container in item_data.containers:
                        callbacks.extend(container.generate_callbacks())
                    if verbose:
                        syslog.info(f"Gate trigger: {gate.gate_display()} condition [{GateConditionType.to_display_name(condition)}] callbacks: {len(callbacks)}")
                    
                    
                    callbacks_map[gate][condition] = callbacks
                

        # range entry/exit/transit
        for range_info in self._active_ranges:
            for condition, item_data in range_info.item_data_map.items():
                if verbose:syslog.info(f"GATE: condition [{GateConditionType.to_display_name(condition)}]")
                if item_data.containers:
                    callbacks = []
                    for container in item_data.containers:
                        callbacks.extend(container.generate_callbacks())
                    if verbose:
                        syslog.info(f"\tadd range triggers: {range_info.range_display()}  callback count: {len(callbacks)}")
                    if not range_info in callbacks_map:
                        callbacks_map[range_info] = {}
                    callbacks_map[range_info][condition] = callbacks
                else:
                    if verbose:syslog.info(f"\tno mappings found")
                
        self._callbacks = callbacks_map


   

 
    @QtCore.Slot()
    def _profile_stop_cb(self):
        ''' profile stops - cleanup '''

        # clean up callback map
        self._callbacks.clear()
        

    def _fire_trigger_callbacks_ui(self, trigger: TriggerData):
        ''' fires the trigger callbacks '''
        gremlin.util.assert_ui_thread()
        for callback in self._trigger_callbacks:
            callback(trigger)

    def _fire_trigger_callbacks(self, trigger: TriggerData):
        ''' fires the trigger callbackes'''
        gremlin.util.InvokeUiMethod(self._fire_trigger_callbacks_ui, trigger) # trigger on the UI thread
   

    @QtCore.Slot(object)
    def _joystick_event_handler(self, event):
        ''' handles joystick input at runtime
        
        To avoid challenges with other GremlinEx functionality - we handle our own hierarchy calls to our subcontainers here.
        For gate crossings, we mimic a button push (for now) so functors get both a press and release call
        
        '''
        import gremlin.execution_graph
        

        self._lock.acquire()

        try:

            if not self._hooked:
                return False
            
            if not event.is_axis:
                # ignore if not an axis event
                return False

            if not self._action_data:
                # not initialized yet
                return  False
            
            if self._input_type != event.event_type:
                # wrong input type
                return
            
            # device_name = self._device_name
            # device = gremlin.joystick_handling.get_device(event.device_id)
            # # if device_name == device.name and not gremlin.util.compare_guid(self._device_id, event.device_id):
            #     test = gremlin.util.compare_guid(self._device_id, event.device_id)
            #     syslog.error(f"Device ID mismatch: {device_name} - expected {device.device_id} got {self._device_id}")
            #     pass

            if not gremlin.util.compare_guid(self._device_id, event.device_id):
                # ignore if a different input device
                return False
            
            if self._input_id != event.identifier:
                # incorrect input
                return False
            
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_gate
            verbose_ui = config.verbose_mode_ui


            is_runtime = gremlin.shared_state.is_running
            if is_runtime:
                runtime_mode = gremlin.shared_state.runtime_mode
                if self.profile_mode != runtime_mode:
                    # wrong mode
                    if verbose: syslog.info(f"GATE Event: ignore joystick input: profile mode: [{self.profile_mode}] current mode: [{runtime_mode}]")

                    return False
                

                
            if hasattr(self._action_data.hardware_input_id, "message_key"):
                if self._action_data.hardware_input_id.message_key != event.identifier.message_key:
                    # ignore if a different input axis on the input device
                    return False
  
            

            # process curved intput
            if not event.is_virtual:
                input_value = gremlin.joystick_handling.get_curved_axis(self._action_data.hardware_device_guid, 
                                                            self._action_data.hardware_input_id)
            else:
                input_value = event.raw_value


            # run mode - execute the functors with the gate data
            
            triggers = self.process_triggers(input_value)
            trigger: TriggerData

            # if triggers and gremlin.shared_state.is_running:
            #     pass

            verbose = gremlin.config.Configuration().verbose_mode_gate

            
            # if verbose:
            #     syslog.info(f"Trigger: raw value: {input_value}  trigger value: {value}")

            if not gremlin.shared_state.is_running:
                # raw input value updates
                self._axis_value = input_value
                gh = GateEventHandler()
                gh.slider_update_event.emit(event)
                gh.fireValueChangedCallbacks(self._device_id, self._input_id, input_value)

            
            if triggers:
                value = gremlin.actions.Value(event.value)
                
                range_event = event.clone()
                range_event.event_type = InputType.JoystickAxis # force linear
                if not range_event.extra_data:
                    range_event.extra_data = {}
                range_event.extra_data["triggers"] = triggers

    
                for trigger in triggers:
                    trigger_event = event.clone()
                    trigger_value = value.clone()
                    
                    if not trigger_event.extra_data:
                        trigger_event.extra_data = {}
                    trigger_event.extra_data["trigger"] = trigger


                    short_press = False
                    delay = trigger.delay
                    if verbose: syslog.info(f"Exec Trigger: got trigger: {trigger.mode.name}")
                    match trigger.mode:
                        case TriggerMode.FixedValue:
                            if verbose: syslog.info(f"Exec Trigger: fixed value: {trigger.range.range_display() if trigger.range else trigger.gate.slider_index} : value {input_value:0.3f}")
                            value.current = trigger.value
                            trigger_event.curve_value = trigger.value

                        case TriggerMode.ValueInRange:
                            if verbose: syslog.info(f"Exec Trigger: value in range: {trigger.range.range_display()} : value {input_value:0.3f}")
                            value.current = trigger.value
                            trigger_event.curve_value = trigger.value
                            trigger_event.is_pressed = True
                            trigger_value.is_pressed = True
                        case TriggerMode.ValueOutOfRange:
                            if verbose: syslog.info(f"Exec Trigger: value out of range: {trigger.range.range_display()} : value {input_value:0.3f}")
                            trigger_value.current = trigger.value
                            trigger_event.curve_value = trigger.value
                            trigger_value.is_pressed = False
                            trigger_event.is_pressed = False
                        case TriggerMode.GateCrossed:
                            # mimic a joystick button press for a gate crossing
                            if verbose: syslog.info(f"Exec Trigger: gate crossing : {trigger.gate.slider_index} : value {input_value:0.3f} ")
                            trigger_event.fake_button()
                            trigger_event.is_pressed = True
                            trigger_value.is_pressed = True
                            
                        case TriggerMode.GateIncrease:
                            # mimic a joystick button press for a gate crossing (increase)
                            if verbose: syslog.info(f"Exec Trigger: gate crossing (inc): {trigger.gate.slider_index} : value {input_value:0.3f} ")
                            trigger_event.fake_button()
                            trigger_event.is_pressed = True
                            trigger_value.is_pressed = True
                            
                        case TriggerMode.GateDecrease:
                            # mimic a joystick button press for a gate crossing (increase)
                            if verbose: syslog.info(f"Exec Trigger: gate crossing (dec): {trigger.gate.slider_index} : value {input_value:0.3f} ")
                            trigger_event.fake_button()
                            trigger_event.is_pressed = True
                            trigger_value.is_pressed = True
                            
                        case TriggerMode.RangeEnter:
                            # enter range
                            if verbose: syslog.info(f"Exec Trigger: range enter: {trigger.range.range_display()} value {input_value:0.3f}")
                            trigger_event.fake_button()
                            trigger_event.is_pressed = True
                            trigger_value.is_pressed = True
                        case TriggerMode.RangeExit:
                            # exit range
                            if verbose: syslog.info(f"Exec Trigger: range exit:  {trigger.range.range_display()} value {input_value:0.3f}")
                            trigger_event.fake_button()
                            trigger_event.is_pressed = True
                            trigger_value.is_pressed = True
                        

                    if not gremlin.shared_state.is_running:
                        # non-runtime trigger updates for the UI
                        # if verbose_ui: syslog.info("GATE Event: before trigger callbacks")
                        self._fire_trigger_callbacks(trigger)
                        # if verbose_ui: syslog.info("GATE Event: after trigger callbacks")

                        # fire the custom joystick event
                        el = gremlin.event_handler.EventListener()
                        el.custom_joystick_event.emit(trigger_event) # have widgets update at design time

                        return True
                    
                    else:
                        # runtime mode


                        if not gremlin.shared_state.runtime_mode in self.valid_mode_list:
                            # incorrect mode or not started yet
                            verbose = gremlin.config.Configuration().verbose_mode_gate
                            if verbose:
                                syslog.info(f"GATED AXIS TRIGGER: FAIL - invalid mode [{gremlin.shared_state.runtime_mode}]")
                                for mode in self.valid_mode_list:
                                    syslog.info(f"\tAvailable modes: [{mode}]")
                                return
     

                        # profile is running - trigger the execution node for the containers
                        # the extra data contains the trigger condition type so the correct execution path is taken
                        if verbose: syslog.info(f"GATED AXIS TRIGGER: {trigger.mode.name}")
                        extra_data = {}
                        extra_data["condition_type"] = trigger.condition
                        extra_data["trigger"] = trigger
                        extra_data["source"] = "Gate Condition"
                        if trigger.condition in (GateConditionType.EnterRange, GateConditionType.ExitRange, GateConditionType.InRange, GateConditionType.OutsideRange):
                        
                            if verbose: syslog.info(f"\tTrigger value: {trigger.value:0.3f} input: {input_value:0.3f}")
                            action_value = gremlin.actions.Value(trigger.value, trigger.raw_value)
                            self._ec.execute_functor_id(self._action_data.id, trigger_event, action_value, extra_data, True)
                        else:
                            # non range trigger (gate crossing or range enter/exit)
                            # use a fake button for momentary event
                            self._ec.execute_functor_id(self._action_data.id, trigger_event, trigger_value, extra_data, True)
                            autorelease = False
                            if trigger.condition in (GateConditionType.OnCross, GateConditionType.OnCrossDecrease, GateConditionType.OnCrossIncrease):
                                # gate condition
                                autorelease = trigger.gate.autorelease_map[trigger.condition]
                            elif trigger.condition in (GateConditionType.EnterRange, GateConditionType.ExitRange):
                                # range condition
                                autorelease = trigger.range.autorelease_map[trigger.condition]
                            if autorelease:
                                # handle autorelease based on trigger delay
                                if verbose: syslog.info(f"GATED AXIS AUTORELEASE TRIGGER: {trigger.mode.name}")
                                button_release_event = trigger_event.clone()
                                button_release_event.is_pressed = False
                                button_release_value = gremlin.actions.Value(input_value, False)
                                delay = trigger.delay/1000 # delay in seconds
                                release = lambda : self._ec.execute_functor_id(self._action_data.id, button_release_event, button_release_value, extra_data, True)
                                worker = gremlin.repeater.PulseWorker(delay, -1, None, release)
                                worker.start()



                
            # if verbose:
            #     syslog.info("Trigger: end")
        finally:
            self._lock.release()


    


    def _short_press(self, functor, event, value, delay = 250):
        ''' triggers a short press of a trigger (gate crossing)'''
        if not hasattr(functor, "process_event"):
            return
        # print ("short press ")
        value.current = event.is_pressed
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




    def populate_condition_widget(self, widget : gremlin.ui.ui_common.QComboBox, default = None, is_range = False):
        ''' populates a condition widget ''' 
        widget.clear()
        if is_range:
            # range conditions
            conditions = ( GateConditionType.EnterRange, GateConditionType.ExitRange, GateConditionType.InRange, GateConditionType.OutsideRange)
        else:
            # gate conditions
            conditions = (GateConditionType.OnCross, GateConditionType.OnCrossIncrease, GateConditionType.OnCrossDecrease)
        current_index = None
        for index, condition in enumerate(conditions):
            widget.addItem(_gate_condition_to_name[condition], condition)
            if default and current_index is None and default == condition:
                current_index = index
        
        if current_index is not None:
            widget.setCurrentIndex(current_index)

    def populate_output_widget(self, widget : gremlin.ui.ui_common.QComboBox, default = None):
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
        eh = GateEventHandler()
        eh.gateddata_valueChanged.emit(self)
    
    def setGateCondition(self, index, condition):
        ''' sets the condition for the given gate index '''
        self._gate_condition_map[index] = condition

    def getGateCondition(self, index):
        ''' gets the condition for the given gate index '''
        if not index in self._gate_condition_map:
            self._gate_condition_map[index] = GateConditionType.OnCross
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
    def steps(self) -> int:
        ''' current number of (non default) gates'''
        return self.gateCount()
    
    def gateCount(self) -> int:
        ''' current number of (non default) gates'''
        return len(self.getGates())

    def getGateValues(self, as_dict = False):
        ''' gets a list of gate values in slider order - the slider order should be set whenever the slider is first populated so we know which index is what gate  '''
        gates = self.getGates()
        if not gates:
            # create a pair of gates for new ranges
            g1 = self.addGate(-1, update = False)
            g2 = self.addGate(1, update = False)
            gates = [g1, g2]
            self._update_gate_index()
            self._update_ranges()
            
        data = [(info.slider_index, info.value) for info in gates]
        data.sort(key = lambda x: x[0])
        gate_values = [d[1] for d in data]
        
        if as_dict:
            values = {}
            for index, value in enumerate(gate_values):
                values[index] = value
        else:
            values = gate_values
        return values
        
    
    def updateGateSliderIndices(self):
        ''' updates slider indices'''
        gates = self.getGates()
        # sorted
        for index, gate in enumerate(gates):
            gate.setIndex(index, False)
        

    
    def getUsedGatesIds(self):
        ''' gets the index of used gates '''
        return self._get_used_gate_ids()

    def getUsedGatesSliderIndices(self):
        ''' gets the gate slider index for all used gates '''
        return [gate.slider_index for gate in self.getGates()]
    
    def getGateValueItems(self):
        ''' gets pairs of index, value for each gate '''
        return self._get_used_items()
    
    
    def getGateSliderIndex(self, index):
        ''' gets the gate corresponding to a given slider index '''
        return next((gate for gate in self.getGates() if gate.slider_index == index), None)
    
    def findGate(self, value, tolerance = 0.001):
        ''' finds an existing gate by value - None if not found '''
        if value is None:
            return False
        return next((gate for gate in self.getGates() if gremlin.util.is_close(gate.value, value, tolerance)), None)
    
    def findGateById(self, id):
        ''' finds an existing gate by id - None if not found '''
        return next((gate for gate in self.getGates() if gate.id == id), None)
    
    def getOverlappingGates(self, tolerance = 0.01):
        ''' returns a list of overlapping gates '''
        overlap = set()
        gates = self.getGates()
        processed = []
        for gate in gates:
            sub_gates = [g for g in gates if gate != g and g not in processed]
            for subgate in sub_gates:
                if gremlin.util.is_close(gate.value, subgate.value, tolerance):
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

    def getUsedRanges(self):
        ''' gets a list of ranges that have valid used gates '''
        return self._ranges
    
    
    def getRequiredRanges(self):
        ''' returns the range pairs required for all the active gates as value pairs (g1,g2)'''
        required_gates = []
        gates = self.getUsedGates()
        g1 : GateInfo = None
        g2 : GateInfo = None
        for gate in gates:
            if g1 is None:
                g1 = gate
                continue
            elif g2 is None:
                g2 = gate
            else:
                g1 = g2
                g2 = gate
            required_gates.append((g1, g2))
        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose:
            syslog.info("Required ranges: ")
            for g1, g2 in required_gates:
                syslog.info(f"\t{g1.display_value:0{_decimals}f} {g2.display_value:0.{_decimals}f}")
        return required_gates
    
    def updateRanges(self):
        ''' synchronizes ranges with gates
         
        Scans used gates in sequence and returns the list of RangeInfo objects corresponding to them.
        RangeInfo objects come from a pool of RangeInfo objects created for each gate pool

        Updates _active_ranges
          
        '''
        return self._update_ranges()

        # required_ranges = self.getRequiredRanges() # returns the gate pairs active (used) ranges for the current gate configuration

        # ranges = self.getUsedRanges()

        # used_list = []
    
        # for range_info in ranges:
        #     # mark any remaining range unused if we didn't use them all
        #     range_info.setUsed(False)

        # verbose_details = gremlin.config.Configuration().verbose_mode_details
        
        # for g1, g2 in required_ranges:
        #     # g1 and g2 are the bounding gates for the range
        #     range_info : RangeInfo = None
        #     if ranges:
        #         # re-use an existing range
        #         range_info = ranges.pop(0)
        #         range_info.g1 = g1
        #         range_info.g2 = g2
        #     else:
        #         # get the next available range
        #         range_info = self.registerRange(g1, g2)
        #     if not range_info:
        #         syslog.warning(f"Range: unable to find an available range for gates {g1} {g2}")
        #         continue
        #     range_info.setUsed(True)
        #     used_list.append(range_info)
        #     if verbose_details:
        #         syslog.info(f"Ranges: sync range for {range_info.range_gate_display()}  {range_info.range_display()}")

        # self._active_ranges = used_list


        # # return the list of ranges 
        # return used_list
    
    def dumpActiveRanges(self):
        '''
        :summary: dumps the active ranges to the log 

        '''
        syslog.info("Active ranges dump:")
        self.dumpRangeList(self._active_ranges)

    def dumpRangeList(self, range_list):
        range_info : RangeInfo
        for range_info in range_list:
            syslog.info(f"\tRange dump: {range_info.range_display_ex()}")
                
    
    def getRanges(self, update = False):
        ''' returns the list of ranges as range info objects'''
        if update:
            self._update_ranges()
        return self._ranges
    
    def getGate(self, id = None):
        ''' returns a gate object for the given index - the item is created if the index does not exist and the gate is marked used '''
        return next((gate for gate in self._gates if gate.id == id), None)
    

    def addGate(self, value : float,  update = True) -> GateInfo:
        ''' registers a gate and marks it as used, return None on error (if the gate count is exceeded)
        If a gate value already exists, the gate is "nudged" to the next gate

        '''
        gate: GateInfo = next((g for g in self._gates if gremlin.util.is_close(g.value, value)), None)
        if gate:
            syslog.warning(f"GATE ADD: value {value:0.3f} already exists - nudging to nearest value ")
            v = gate.value
            offset = 0.01 if v < 1.0 else -0.01
            values = [g.value for g in self._gates]
            while v in values:
                v += offset
                if v <= -1.0 or v >= 1.0:
                    syslog.error("GATE ADD: unable to find a value for the gate")
                    return None
            value = v
            
        # add the gate
        gate = GateInfo(value = value, used = True, parent = self)
        self._gates.append(gate)
        if update:
            self._update_gate_index() # update the gate index and maps

        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose:
            syslog.info(f"Adding gate: [{gate.value:0.{_decimals}f}] {gate.id}")

        if update:
            self._update_ranges() # update range on gate change

        return gate
    
    def setGateCount(self, total_gates):
        ''' sets the required number of gates to the gated axis - gates are added or removed as needed '''


        # ensure we're not exceeding limits
        if total_gates > self.max_gates:
            syslog.error(f"GATE SET: cannot set gate count greater than {self.max_gates}")
            return False
        
        if total_gates < 2:
            syslog.error(f"GATE SET: cannot set gate count below 2.")
            return False
        




        # add the missing steps only (re-use other steps so we don't lose their config)
        gates = self.getGates()
        gate_count = len(gates)
        max_gates = GateData.max_gates
        if gate_count > max_gates:
            gremlin.ui.ui_common.MessageBox(prompt = f"Unable to add the requested gates: The Maximum gate count is reached ({max_gates})")
            return

        verbose = gremlin.config.Configuration().verbose_mode_gate
        if gate_count < total_gates:

            # how many gates to add
            steps = total_gates - gate_count

            if verbose:
                syslog.info(f"Set gate count: add {steps} gates")

            

            # add steps in the middle of existing ranges to spread them
            # if we run out of ranges, repeat with the new steps added
            pair_index = 0
            pairs = list(pairwise(gates))
            if verbose:
                syslog.info("Gate pairs:")
                for (g1,g2) in pairs:
                    syslog.info(f"\t[{g1.index}] {g1.value:0.03f}, [{g2.index}] {g2.value:0.03f}")

            while steps > 0:
                # get gate pairs
                
                if pair_index == len(pairs):
                    # went through initial pairs, restart
                    gates = self.getGates()
                    gate_count = len(gates)
                    pairs = list(pairwise(gates))
                    pair_index = 0
                
                g1,g2 = pairs[pair_index]
                v1,v2 = g1.value, g2.value
                
                if gate_count == 2:
                    # single range, split it
                    distance = abs(v2 - v1)
                    step_size = distance / (steps + 1)
                    if step_size > 0.1:
                        # big enough gap
                        value = v1 + step_size
                        for _ in range(steps):
                            self.addGate(value, update=False)
                            value += step_size
                        steps = 0

                if steps > 0:
                    # split the current range by half
                    distance = abs(v2 - v1)
                    step_size = distance / 2
                    if step_size > 0.01:
                        value = (v1 + v2) / 2
                        self.addGate(value, update=False)
                        steps -= 1
                    else:
                        # nudge the gate next to an existing gate
                        g = self.addGate(v1, update=False)
                        if not g:
                            # error adding gate
                            break
                        steps -= 1


                # next gate pair
                pair_index += 1
    
            if steps > 0:
                # range approach failed, brute force add
                interval = 2.0 / steps
                value = -1 + interval
                while steps > 0:
                    self.addGate(value, update = False)
                    value += interval
                    steps -=1


        elif gate_count > total_gates:
            # how many gates to remove
            steps = gate_count - total_gates


            if verbose:
                syslog.info(f"Set gate count: reduce {steps} gates")

            work_list = [gate for gate in self._gates]
            gate_list = [gate for gate in self._gates]
            work_list.sort(key = lambda x:x.value)
            work_list.pop(0)
            work_list.pop()
            
            triplets = gremlin.util.triplets(work_list)
            triplet_count = len(triplets)
            index = 0
            while work_list and len(gate_list) > total_gates:
                g1,g2,g3 = triplets[index]
                if not g2 or not g3:
                    # remove the prior one
                    gate_list.remove(g1)
                    work_list.remove(g1)
                else:
                    gate_list.remove(g2)
                    work_list.remove(g2)

                index += 1
                if index == triplet_count:
                    index = 0
                    triplets = gremlin.util.triplets(work_list)
                    triplet_count = len(triplets)

            
            self._gates = gate_list
            
            

        self._update() # update gate and range data 

        if verbose: 
            self.dump()

        return True

    def dump(self):
        ''' dumps current gate and range information to the log file '''
        gates = self.getUsedGates()
        syslog.info(f"Updated gates:")
        for gate in gates:
            syslog.info(f"\tGate: {gate.slider_index} {gate.value:0.{_decimals}f}")
        syslog.info("Updated ranges:")
        range_list = self.getRanges()
        if range_list:
            for r in range_list:
                syslog.info(f"\tRange: {str(r)}")
        else:
                syslog.info(f"\tNo ranges found")

        

    def isGateRegistered(self, gate):
        ''' true if a gate is registered'''
        return gate.id in self._gate_index_map
    
    def setUsedGates(self, gate_list, update_index = True, update_ranges = True):
        ''' loads a list of defined gates '''
        # grab the default gates
        if gate_list:
            self._gates = gate_list
            if update_index:
                # re-index
                self._update_gate_index()
            if update_ranges:
                self._update_ranges() # update ranges
    
    def findGateById(self, id : str, used_only = True):
        ''' finds a gate by id, filtering by used gates as an option'''
        if used_only:
            gate = next((g for g in self._gates if g.id == id and g.used), None)
        else:
            gate = next((g for g in self._gates if g.id == id), None)
        return gate
        

    def getGates(self, used_only = True):
        ''' gets all used gates - returns them in sorted order by value  '''
        source = self._gates
        # if used_only:
        #     source = [gate for gate in source if gate.used]
        
        # sort by value 
        source.sort(key = lambda x: x.value)
        return source
        
    def getUsedGates(self):
        ''' gets a sorted list of used gates (gate is used and has a value)'''
        return self.getGates()


    def getPriorGate(self, gate):
        gate_list = self.getGates()
        index = gate_list.index(gate)
        if index == 0:
            return None
        return gate_list[index-1]
    
    def getNextGate(self, gate):
        gate_list = self.getGates()
        gate_count = len(gate_list)
        index = gate_list.index(gate)
        if index + 1 == gate_count:
            return None
        
    def getGateSiblings(self, gate):
        ''' for a given gate, returns the adjoining gates'''
        gate_list = self.getGates()
        gate_count = len(gate_list)
        if gate in gate_list:
            index = gate_list.index(gate)
            
            g1 = gate_list[index-1] if index > 0 else None
            g2 = gate_list[index+1] if index + 1 != gate_count else None
            return g1,g2
        return None, None
    
    def getGateRange(self, gate):
        ''' gets gate valid ranges based on siblings '''
        v = gate.value
        g1,g2 = self.getGateSiblings()
        offset = 0.001
        if g1:
            v1 = g1.value + offset
        else:
            v1 = v
        
        if g2:
            v2 = g2.value - offset
        else:
            v2 = v

        if v1 > v2:
            v1,v2 = v2,v1
        return v1,v2
            


    def findRange(self, g1 : GateInfo, g2: GateInfo) -> RangeInfo | None:
        ''' find the range for the given two gates '''

        rng_list = self.getRanges()
        for rng in rng_list:
            if rng.g1.id == g1.id and rng.g2.id == g2.id:
                return rng
        return None 
    
    def findRangeByValue(self, value : float) -> RangeInfo | None:
        rng_list = self.getUsedRanges()
        rng : RangeInfo
        for rng in rng_list:
            if rng.valueInRange(value):
                return rng
            
        return None

        # gates = self.getGates()
        # gate_count = len(gates)
        # for g1,g2 in pairwise(gates):
        #     if value >= g1.value and value <= g2.value:
        #         rng = self.findRange(g1, g2)
        #         if rng : 
        #             return rng
        return None
    
    def findRangeByGateValue(self, v1 : float, v2: float) -> RangeInfo | None:
        ''' gets the range from two values '''
        g1 = self.findGate(v1)
        if g1:
            g2 = self.findGate(v2)
            if g2:
                return self.findRange(g1, g2)
        return None

    def registerRange(self, g1 : GateInfo, g2 : GateInfo) -> RangeInfo:
        ''' gets the range for the pair of gates '''
        
        rng = self.findRange(g1, g2)
        if not rng:

            # use one of the unused ranges
            rng : RangeInfo = next((r for r in self._ranges if not r.used), None)
            if not rng:
                syslog.error(f"Unable to find an available range: {g1.value} {g2.value}")
                return None
            rng.used = True
            rng.set_gates(g1, g2)
        return rng

    def getUnusedRange(self):
        ''' gets an unused range '''
        rng : RangeInfo = next((r for r in self._ranges if not r.used), None)
        if not rng:
            # no range available, create one
            rng = RangeInfo(self.default_min_gate, self.default_max_gate, parent = self)
            self._ranges.append(rng)

        return rng
    

    def setUsedRanges(self, range_list : list):
        ''' sets the list of used ranged '''
        self._ranges = range_list

    
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
    
    def getRangesForGate(self, gate : GateInfo) -> tuple[RangeInfo]:
        ''' gets the two ranges for a given gate as a tuple (r1,r2) '''
        ranges = self._get_ranges()
        rng : RangeInfo
        left_range = None
        right_range = None
        for rng in ranges:
            if rng.g1 == gate:
                right_range = rng
            if rng.g2 == gate:
                left_range = rng
        return (left_range, right_range)



    
    def deleteGate(self, gate):
        ''' removes a gate '''
        if gate in self._gates:
            self._gates.remove(gate)
            self._update()

        
    def normalize_steps(self, use_current_range = False):
        ''' normalizes gate intervals based on the number of gates
        
        :param: use_current_range = normalize steps over the current min/max range, if false, resets min/max and uses the full range

        '''

        gates = self.getGates() # get gates (ordered by position) - skip default gates
        steps = len(gates)

        if not use_current_range:
            min_value = -1.0
            max_value = 1.0
        else:
            min_value = gates[0].value
            max_value = gates[-1].value

        minmax_range = max_value - min_value
        interval = minmax_range / (steps-1)

        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose:
            syslog.info(f"Normalize {steps} gates, min: {min_value:0.{_decimals}f} max: {max_value:0.{_decimals}f} interval: {interval:0.{_decimals}f}")

        
        current = min_value
        for index, gate in enumerate(gates):
            if verbose:
                syslog.info(f"\tGate [{index}] value: {current:0.{_decimals}f}")
            gate.setValue(current, emit = False) # don't update the UI
            current += interval
            
            if current > max_value:
                current = max_value # clamp for rounding errors
        
        eh = GateEventHandler()
        eh.gates_changed.emit()


    def _get_next_gate_index(self):
        ''' gets the next unused index '''
        used_list = self._get_used_gate_ids()
        for index in range(100):
            if not index in used_list:
                return index
        return None

    def _update_ranges(self):
        ''' updates the list of ranges with updated gate configuration - this should be called whenever a gate is added or removed 
        Range data is copied from prior ranges to prevent data loss
        '''
         
        gates = self.getUsedGates() # gets used gates in ascending order
        gate_pairs = list(pairwise(gates)) # pairwise list of gates - there is a range between each pair
        gate_count = len(gates)

        rng : RangeInfo
        range_list = [] # holds the new range objects
        
        # current ranges that exist in the current gate sequence
        current_range_map = {index:rng for index,rng in enumerate(self._ranges)}

        # remaining gate pairs are gates that were changed        
        for index, (g1, g2) in enumerate(gate_pairs):
            # add any needed ranges
            rng = RangeInfo(g1, g2, parent = self, used = True)
            if index in current_range_map:
                current = current_range_map[index]
                rng.item_data_map = current.item_data_map
                rng.mode = current.mode
                rng.output_range_min = current.output_range_min
                rng.output_range_max = current.output_range_max
                rng.fixed_value = current.fixed_value
                rng.description = current.description
            

            range_list.append(rng)
                

        self._ranges = range_list

        # verbose =  gremlin.config.Configuration().verbose_mode_gate
        # if verbose:
        #     syslog.info("Updated ranges:")
        #     if range_list:
        #         for r in range_list:
        #             syslog.info(f"\tRange: {str(r)}")
        #     else:
        #             syslog.info(f"\tNo ranges found")

        assert len(range_list) == gate_count -1 if gate_count else True, "Range update error: incorrect range count"
        return range_list



    
 

    def _get_used_items(self):
        ''' gates the index/gate pairs for active gates '''
        gates = [(info.slider_index, info) for info in self._gate_index_map.values() if info.used and info.value is not None]
        gates.sort(key = lambda x: x[1].value) # sort ascending
        return gates
    
    def _get_used_values(self):
        ''' gets the position of active gates'''
        gates = [info.value for info in self._gate_index_map.values() if info.used and info.value is not None]
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

        gates = self.getGates()
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
      
    
    def _update_gate_index(self) -> list[GateInfo]:
        ''' updates gate indices so they are in sorted index '''

        # index non default gates
        gates = self.getGates() # this is already sorted

        for index, gate in enumerate(gates):
            gate.setIndex(index, False)
 
        self._gate_index_map = {gate.slider_index: gate for gate in gates}
        self._gate_id_map = {gate.id: gate for gate in gates}

        return gates
    
    def _update(self):
        ''' updates gate index and range information '''
        self._update_gate_index()
        self._update_ranges()

    
    
    def _get_used_gate_ids(self):
        ''' gets the lif of activate gate indices '''
        return [gate.id for gate in self._gates if gate.used]
    

    def _gate_gate_ranges(self, gate):
        ''' gets the two ranges on either side of a gate as a tuple (range1, range2)
            Range will be none if there is no range.
        '''
        range_list = [r for r in self._ranges if r.used]
        top_range = None
        bottom_range = None
        for rng in range_list:
            if gate == rng.g1:
                top_range = rng
            elif gate == rng.g2:
                bottom_range = rng
        
        return (bottom_range, top_range)
            
        
        

    def _get_ranges(self):
        ''' buils a sorted list of gate range objects filtered by used gates and by gate value '''
        range_list = self._ranges
        non_sortable = [r for r in range_list if r.g1.value is None]
        sortable = [r for r in range_list if r.g1.value is not None]
        sortable.sort(key = lambda x: x.g1.value)
        sortable.extend(non_sortable)
        range_list = sortable

        return range_list
    
    def _get_range_values(self):
        range_list = self._get_ranges()
        return [(r.g1.value,r.g2.value) for r in range_list]
    
    def _get_range_for_value(self, value : float):
        ''' returns (v1,v2,idx1,idx12) where v1 = lower range, v2 = higher range, idx1 = gate index for v1, idx2 = gate index for v2 '''
        range_info : RangeInfo
        #print ("------")
        selected = None
        for range_info in self._get_ranges():
            # print (f"{value:0.4f} - range: {range_info.range_display()} {range_info.range_gate_display()} in range: {range_info.inrange(value)}")
            if range_info.inrange(value):
                selected = range_info
        return selected
    
    def _get_range_for_value_from_list(self, value : float, ranges: list[RangeInfo]):
        '''
        Gets the range that contains the value from a list of ranges 
        :param value: the value to look for
        :param ranges: the range list
        :returns: the RangeInfo containing the value or None if not found
        '''

        for range_info in ranges:
            if range_info.inrange(value):
                return range_info
            
        return None

    def _get_range_percent(self, value : float , rv1 : float, rv2 : float ):
        ''' gets the percentage position of the value in the range rv1, rv2 - return floating point 0..1
        
        :param value: the input value
        :param rv1: the left gate value for the range
        :param rv2: the right gate value for the range 

        :returns: a floating point value between 0 and 1 with 1 = 100%
        
        '''
        v = 1 + value
        v1 = 1 + rv1
        v2 = 1 + rv2
        a = v - v1
        d = v2-v1
        p = a / d
        return p

    
    def _get_filtered_range_value(self, range_info : RangeInfo, value : float):
        ''' gets a range filtered value
        
        :param value: value -1 to +1 in the whole range of the axis (not the subrange defined by the range)
        
        '''
        range_info : RangeInfo
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_exec or config.verbose_mode_gate
        
        if value < range_info.v1 or value > range_info.v2:
            # not in range
            if verbose:
                log_info(f"{value} Not in range [{range_info.v1},{range_info.v2}] -> none")
            return None
        else:
            match range_info.mode:
                case GateRangeOutputMode.Normal:
                    # as is
                    # if verbose:
                    #     log_info(f"range [NORMAL]: {v1:0.3f} {v2:0.3f} input: {value:0.3f} as is [{range_info.v1},{range_info.v2}] -> {value}")
                    return value
                case GateRangeOutputMode.FilterOut:
                    if verbose:
                        log_info(f"range [FILTER OUT]: {v1:0.3f} {v2:0.3f} input: {value:0.3f} filtered out -> none")
                    return None # filter the data out
                case GateRangeOutputMode.Fixed:
                    # return the range's fixed value
                    output_value = range_info.fixed_value
                    if verbose:
                        log_info(f"range [FIXED]:  input: {value:0.3f} Fixed  -> {output_value:0.3f}")
                    return output_value
                case GateRangeOutputMode.Ranged:
                    #p = self._get_range_percent(value, range_info.v1, range_info.v2)
                    v1 = range_info.range_min
                    v2 = range_info.range_max
                    output_value = gremlin.util.scale_to_range(value, source_min =v1, source_max = v2, target_min = range_info.output_range_min, target_max = range_info.output_range_max)
                    #output_value = value
                    #output_value = gremlin.util.scale_to_range(value, v1, v2, target_min = range_info.range_min, target_max=range_info.range_max)
                    #output_value = gremlin.util.scale_to_range(value, v1, v2, target_min = range_info.output_range_min, target_max=range_info.output_range_max)
                    if verbose:
                        log_info(f"range [RANGED]: {v1:0.3f} {v2:0.3f} input: {value:0.3f} scaled [{range_info.output_range_min:0.3f},{range_info.output_range_max:0.3f}]-> {output_value:0.3f}")
                    return output_value
                case GateRangeOutputMode.Rebased:
                    # scale to the output range but position the data in the range (lower gate is -1, upper gate is +1)
                    v1 = range_info.range_min
                    v2 = range_info.range_max
                    output_value = gremlin.util.scale_to_range(value, source_min =v1, source_max = v2)
                    if verbose:
                        log_info(f"range [REBASE]: {v1:0.3f} {v2:0.3f} input: {value:0.3f} rebased value: -> {output_value:0.3f}")
                    return output_value

        # use unchanged value
        return value

    def pre_process(self):
        # setup the pre-run activity
        self._last_value = None
        self._last_range = None
        self._last_range_exit_trigger = None # range that triggered the last exit
        self._last_range_enter_trigger = None # range that triggered the last enter
        self._ranges = self._get_ranges()
        self._gate_list = self._get_used_items() # ordered list of gates by index and value

    def _trim_list(self, data, count_max):
        count = len(data)
        
        if count > 0 and count_max < count:
            trim_count = count - count_max
            for _ in range(trim_count):
                data.pop(0)
        return data
        


    def process_triggers(self, current_value : float , update_last = True):
        ''' processes an axis input value and returns all triggers collected since the last call based on the previous value

        **This is a high frequency call whenever an input is changed**
         
        :param value: the input float value -1.0 to +1.0
        :param require_containers: true if the triggers are only container triggers

        :returns:  list of TriggerData objects containing the trigger information based on the gated axis configuration
           

        '''

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_gate
        verbose_detailed = config.verbose_mode_gate and config.verbose_mode_extra
        gh = GateEventHandler()

        
        with self._process_trigger_lock:


            tt = TriggerTracking() # tracking object
            tt.clear() # reset any prior triggers
            ranges = self.getUsedRanges() # list of all ranges

            last_value = self._last_value # last value processed
            if last_value is None:
                # not set, first go at processing - setup initial range triggers
                
                for r in ranges:
                    if r.valueInRange(current_value):
                        # two triggers - in range and enter range
                        modes = (TriggerMode.RangeEnter, TriggerMode.ValueInRange)
                        
                    else:
                        # not in range, two triggers - out of range, 
                        modes = (TriggerMode.RangeExit, TriggerMode.ValueOutOfRange)
                        condition = GateConditionType.ExitRange
                    for mode in modes:
                        td = TriggerData()
                        td.mode = mode
                        
                        match mode:
                            case TriggerMode.RangeEnter:
                                condition = GateConditionType.EnterRange
                            case TriggerMode.RangeExit:
                                condition = GateConditionType.ExitRange
                            case TriggerMode.ValueInRange:
                                condition = GateConditionType.InRange 
                            case TriggerMode.ValueOutOfRange:
                                condition = GateConditionType.OutsideRange

                        td.condition = condition
                        td.value = current_value
                        td.range = r
                        td.delay = r.delay
                        tt.triggers.append(td)
                        tt.registerTrigger(r, td)
                    
            value = None

            value_changed = last_value is None or last_value != current_value

            if not value_changed:
                # nothing changed
                return tt.triggers
            
            
            range_info: RangeInfo
            range_info = self._get_range_for_value_from_list(current_value, ranges)
            
            # the last range we saw            
            last_range = self._last_range
            
            is_running = gremlin.shared_state.is_running
            if last_range is not None:
                v1,v2 = last_range.range()
            
                if current_value < v1 or current_value > v2:
                    # ensure the last range min/max are set if the value is outside the range
                    if last_range.id in self._last_in_range_trigger_map:
                        td : TriggerData = self._last_in_range_trigger_map[last_range.id]
                        
                        if current_value < v1 and td.raw_value != v1:
                            value = self._get_filtered_range_value(last_range, v1)
                            if value is not None:
                                td.raw_value = v1
                                td.value = value
                                td.raw_value = current_value    
                                # re-fire the trigger with the boundary value
                                tt.triggers.append(td)
                
                        elif current_value > v2 and td.raw_value != v2:
                            value = self._get_filtered_range_value(last_range, v2)
                            if value is not None:
                                td.raw_value = v2
                                td.value = value
                                td.raw_value = current_value
                                # re-fire the trigger with the boundary value
                                tt.triggers.append(td)
                
            

            if range_info is not None:

                # print (f"Process triggers for range: {range_info.id} mode: {range_info.range_display_ex()}")
                
                
                if not is_running or range_info.hasContainers(GateConditionType.InRange):
                    # trigger on value in-range
                    if range_info.mode != GateRangeOutputMode.FilterOut:
                        value = self._get_filtered_range_value(range_info, current_value)
                        # always trigger for value in range
                        if value is not None: #  and not tt.getTrigger(range_info, TriggerMode.ValueInRange):
                            td = TriggerData()
                            mode = TriggerMode.ValueInRange
                            if range_info.mode == GateRangeOutputMode.Fixed:
                                mode = TriggerMode.FixedValue
                            td.mode = mode
                            td.condition = GateConditionType.InRange
                            if verbose: syslog.info("RANGE TRIGGER: in range trigger")
                            td.value = value
                            td.raw_value = current_value
                            td.range = range_info
                            td.delay = range_info.delay
                            tt.triggers.append(td)
                            tt.registerTrigger(range_info, td)
                            tt.clearTrigger(range_info, TriggerMode.ValueOutOfRange)
                            self._last_in_range_trigger_map[range_info.id] = td


                

            # process outside range condition ranges - those trigger if the value is outside the range
            outside_trigger_ranges = [rng for rng in self._active_ranges if rng != range_info and rng.hasContainers(GateConditionType.OutsideRange)]
            for outside_range in outside_trigger_ranges:
                if not tt.getTrigger(outside_range, TriggerMode.ValueOutOfRange):
                    if verbose: syslog.info("RANGE TRIGGER: out of range trigger")
                    td = TriggerData()
                    td.mode = TriggerMode.ValueOutOfRange
                    td.value = current_value
                    td.last_value = last_value
                    td.range = outside_range
                    td.last_range = self._last_range
                    td.condition = GateConditionType.OutsideRange
                    td.delay = outside_range.delay
                    tt.triggers.append(td)
                    tt.registerTrigger(outside_range, TriggerMode.ValueOutOfRange)
                    tt.clearTrigger(range_info, TriggerMode.ValueInRange)


            # get the list of crossed gates since last check
            crossed_gates = self._get_gates_for_values(last_value, current_value)


            # process any the gate triggers
            gate : GateInfo

            tt = TriggerTracking() # tracking data to remember what triggers were already issued so we don't issue them multiple times

            for gate in crossed_gates:
                # check for one way gates we passed


                # also trigger a range enter and range exit
                ranges = self.getRangesForGate(gate)
                for r in ranges:
                    if r is None:
                        continue
                    if verbose: syslog.info(f"GATE CROSSED: processing range {r.range_display()}")
                    if r.valueInRange(last_value):
                        # range exited and previously entered
                        if not tt.getTrigger(r,TriggerMode.RangeExit):
                            td = TriggerData()
                            td.mode = TriggerMode.RangeExit
                            td.condition = GateConditionType.ExitRange
                            td.value = current_value
                            td.range = r
                            td.delay = r.delay
                            tt.triggers.append(td)
                            tt.registerTrigger(r, td)
                            tt.clearTrigger(r,TriggerMode.RangeEnter)


                    if r.valueInRange(current_value):
                        if tt.getTrigger(r, TriggerMode.RangeEnter):
                            if verbose: syslog.info(f"\talready has RangeEnter trigger")
                            continue
                        # range enter and previously exited
                        td = TriggerData()
                        td.mode = TriggerMode.RangeEnter
                        td.condition = GateConditionType.EnterRange
                        td.value = current_value
                        td.range = r
                        td.delay = r.delay
                        tt.triggers.append(td)
                        tt.registerTrigger(r, td)
                        tt.clearTrigger(r,TriggerMode.RangeExit)

                v = gate.value

                if not is_running or gate.hasContainers(GateConditionType.OnCross):
                    # add a gate crossing trigger - # always fires
                    td = TriggerData()
                    if verbose: syslog.info("GATE TRIGGER: Gate cross trigger")
                    td.gate = gate
                    td.delay = gate.delay
                    td.value = current_value
                    td.condition = GateConditionType.OnCross
                    td.mode = TriggerMode.GateCrossed
                    tt.triggers.append(td)
                        

                
                if not is_running or gate.hasContainers(GateConditionType.OnCrossDecrease):
                    # add gate cross decrease trigger
                    if last_value > v:
                        has_trigger = tt.getTrigger(gate,TriggerMode.GateDecrease)
                        if not has_trigger:
                            if verbose: syslog.info("GATE TRIGGER: Gate decrease trigger")
                            td = TriggerData()
                            td.gate = gate
                            td.delay = gate.delay
                            td.value = current_value
                            td.condition = GateConditionType.OnCrossDecrease
                            td.mode = TriggerMode.GateDecrease
                            tt.triggers.append(td)
                            tt.registerTrigger(gate, td)
                            tt.clearTrigger(gate, TriggerMode.GateIncrease)

                    
                if not is_running or gate.hasContainers(GateConditionType.OnCrossIncrease):
                    # add gate cross increase trigger
                    if last_value < v:
                        if not tt.getTrigger(gate,TriggerMode.GateIncrease):
                            if verbose: syslog.info("GATE TRIGGER: Gate increase trigger")
                            td = TriggerData()
                            td.gate = gate
                            td.value = current_value
                            td.condition = GateConditionType.OnCrossIncrease
                            td.mode = TriggerMode.GateIncrease
                            tt.triggers.append(td)
                            tt.registerTrigger(gate, td)
                            tt.clearTrigger(gate, TriggerMode.GateDecrease)


            # update last values if requested
            if update_last:
                self._last_range = range_info
                self._last_value = current_value

            if not gremlin.shared_state.is_running:
                # update trigger lines at edit time
                for trigger in tt.triggers:
                    mode = trigger.mode
                    
                    if not mode in self.filter_map.keys():
                        self.filter_map[mode] = True
                    if self.filter_map[mode]:
                        if trigger.is_gate:
                            self._trigger_gate_lines.append(str(trigger))
                            # keep it within max lines
                            self._trigger_gate_lines = self._trim_list(self._trigger_gate_lines, self._trigger_line_count)
                            gh.gate_trigger_display.emit()
                
                        else:
                            self._trigger_range_lines.append(str(trigger))
                            # keep it within max lines
                            self._trigger_range_lines = self._trim_list(self._trigger_range_lines, self._trigger_line_count)
                            gh.range_trigger_display.emit()
                        
                
                

            if verbose_detailed:
                # dump the triggerrs
                syslog.info(f"Trigger results for value {current_value}:")
                for trigger in tt.triggers:
                    syslog.info(f"\t{str(trigger)}")

            return tt.triggers

        
    def _find_input_item(self):
        return gremlin.base_profile._get_input_item(self._action_data)

    def _new_item_data(self, is_action = True):
        ''' creates a new item data from the existing one '''
        current_item_data = self._find_input_item()
        item_data = gremlin.base_profile.InputItem(parent = current_item_data.parent)
        item_data._input_type = current_item_data._input_type
        item_data._device_guid = current_item_data._device_guid
        item_data._input_id = current_item_data._input_id
        item_data._is_action = is_action

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
            mode = safe_read(current, "name", str,"")
        return mode


    

    def ensure_separation(self, g1 : GateInfo, g2 : GateInfo):
        ''' ensures gates that have very close values are separated'''
        v1 = g1.value
        v2 = g2.value
        sep = 0.001
        nv1 = v1
        nv2 = v2
        if abs(nv1 - nv2) < sep:
            while abs(nv1 - nv2) < sep:
                # not separated enough
                if v1 <= v2:
                    nv2 = v1 + sep
                    if nv2 > 1.0:
                        nv2 = 1.0
                        nv1 = nv2 - sep
                elif v1 > v2:
                    nv1 = v2 - sep
                    if nv1 < -1.0:
                        nv1 = -1.0
                        nv2 = nv1 + sep
            g1._value = nv1
            g2._value = nv2

        assert abs(g1.value - g2.value) >= sep
        return g1, g2

        

                


    def to_xml(self):
        ''' export this configuration to XML '''
        node = ElementTree.Element("gate")

        verbose = gremlin.config.Configuration().verbose_mode_gate
        
        node.set("show_mode", DisplayMode.to_string(self.display_mode))

        #node.set("mode", self.profile_mode)

       
        # save gate data
        gate_info : GateInfo
        gate_list = self.getUsedGates()
        for gate_info in gate_list:
            
            if verbose:
                log_info(f"Saving gate {gate_info.id} value: {gate_info.value} containers count: {gate_info.containerCount:,}")
            child = ElementTree.SubElement(node, "gate")
            child.set("condition", _gate_condition_to_name[gate_info.condition]) # last condition selected
            child.set("value", f"{gate_info.value:0.{_decimals}f}")
            child.set("delay", str(gate_info.delay))
            child.set("id", gate_info.id)
            child.set("index", str(gate_info.slider_index))

            
            # description
            if gate_info.description:
                child.set("description", gate_info.description)

            for condition, item_data in gate_info.item_data_map.items():
                if item_data.containers:
                    item_node = item_data.to_xml()
                    if item_node is not None:
                        item_node.set("type", item_node.tag)
                        item_node.set("condition", GateConditionType.to_string(condition))
                        item_node.tag = "action_containers"
                        child.append(item_node)

        # save range data

        self._update_ranges()

        range_info : RangeInfo
        range_list = self.getUsedRanges()
        range_count = len(range_list)
        used_gates = self.getUsedGates()
        gate_count = len(used_gates)
        assert range_count == gate_count -1 if gate_count else True, f"Invalid range count: {range_count} gate count: {gate_count}"
        for range_info in range_list:
            if verbose:
                log_info(f"Saving range {range_info.id} min: {range_info.range_min}  max: {range_info.range_max} containers count: {range_info.containerCount:,}")
            child_comment = ElementTree.Comment(f"Range: [{range_info.v1:0.{_decimals}f},{range_info.v2:0.{_decimals}f}]  Gates: [{range_info.g1.slider_index}/{range_info.g2.slider_index}] Condition: [{_gate_condition_to_display_name[range_info.condition]}] Mode: [{_gate_range_to_display_name[range_info.mode]}]")
            node.append(child_comment)
            child = ElementTree.Element("range")
            node.append(child)

            # delay
            child.set("delay", safe_format(range_info.delay, int))

            # description
            if range_info.description:
                child.set("description", range_info.description)

            child.set("condition",_gate_condition_to_name[range_info.condition])

            mode = range_info.mode
            child.set("mode",_gate_range_to_string[mode])
            
            if mode == GateRangeOutputMode.Fixed:
                child.set("fixed_value", f"{range_info.fixed_value:0.{_decimals}f}")
            elif mode == GateRangeOutputMode.Ranged:
                child.set("range_min",  safe_format(range_info.output_range_min, float))
                child.set("range_max",  safe_format(range_info.output_range_max, float))

            child.set("id", range_info.id)
            child.set("min_id", range_info.g1.id)
            child.set("max_id", range_info.g2.id)

            for condition, item_data in range_info.item_data_map.items():
                if item_data.containers:
                    item_node = item_data.to_xml()
                    if item_node is not None:
                        item_node.set("type", item_node.tag)
                        item_node.set("condition", GateConditionType.to_string(condition))
                        item_node.tag = "range_containers"
                        child.append(item_node)
            
        
        # filter options
        filter_node = ElementTree.SubElement(node,"filter")
        for trigger in self.filter_map.keys():
            filter_node.set(TriggerMode.to_string(trigger), str(self.filter_map[trigger]))

        node.append(filter_node)



        return node
    

                



    def from_xml(self, node, data = None, extra_data = None):
        ''' loads XML data for axis to gate '''
        if not node.tag == "gate":
            syslog.error(f"GateData: Invalid node type {node.tag} {node}")
            return
        
        # determine if we're pasting - if we are - we need to update all GUIDs
        if extra_data and "paste" in extra_data:
            paste_mode = extra_data["paste"]
        else:
            paste_mode = False
        
       
        
        verbose = gremlin.config.Configuration().verbose_mode_gate

        # default mode to use, for paste
        profile_mode = self.profile_mode
        
        # use the node parenting to derive the mode to use
        if not paste_mode:
            # use the mode from the XML
            mode = self.get_xml_mode(node)
            if mode:
                profile_mode = mode

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
        node_gates = node.xpath(".//gate")

        guid_map = {} # map of OLD guid to NEW guid

        if verbose:
            syslog.info("Parsing gates:")

        gate_list = []
        range_list = []
        gate_id_map = {} # holds gate id map to new ID if the ID was changed
        self._gates = [] # remove all gates
        self._ranges = [] # remove all ranges
            
        for child in node_gates:
            
            gate_id = safe_read(child, "id", str,"")
            
            if verbose: 
                syslog.info(f"GATE XML: loading gate {gate_id}:")

            gate_value = safe_read(child, "value", float, 0.0)
            gate_condition = safe_read(child, "condition", str, "")
            gate_delay = safe_read(child, "delay", int, 250)
            
            
            if not gate_condition in _gate_condition_to_enum.keys():
                syslog.error(f"GateData: Invalid condition type {gate_condition} gate id: {gate_id}")
                return
            gate_condition = GateConditionType.to_enum(gate_condition)

            gate_info = self.addGate(value = gate_value) # just add, no range update until all gates are in

            if paste_mode:
                # paste mode = keep new gate ID
                gate_id_map[gate_id] = gate_info.id
            else:
                # keep XML gate ID
                gate_id_map[gate_id] = gate_info.id
                gate_info.id = gate_id

            gate_info.setUsed(True) # indicate the gate is used
            gate_info.value = gate_value
            if "index" in child.attrib:
                gate_index = safe_read(child,"index",int, 0)
                gate_info.slider_index = gate_index

            
            
            
            # gate_info = self.registerGate(gate_value, gate_default)
            gate_info.setLastCondition(gate_condition)
            
            gate_info.delay = gate_delay
            

            description = None
            if "description" in child.attrib:
                description = child.get("description")
                if description:
                    gate_info.description = description

            # read action containers for the gate
            item_nodes = gremlin.util.get_xml_child(child, "action_containers", multiple=True)
            gate_info.item_data_map = {}
            for item_node in item_nodes:
                if item_node is not None:
                    item_data = self._new_item_data()
                    if not "condition" in item_node.attrib:
                        condition = gate_condition
                    else:
                        condition_str = item_node.get("condition")
                        condition = GateConditionType.to_enum(condition_str)
                    item_node.tag = item_node.get("type")
                    item_data.from_xml(item_node, data, extra_data = extra_data)
                    if paste_mode:
                        item_data.generateGuids() 

                    gate_info.item_data_map[condition] = item_data
                    if verbose: 
                        syslog.info(f"\tLoading condition: {condition.name}: {str(item_data)}")
      
            # remember added gate
            gate_list.append(gate_info)

            if verbose:
                syslog.info(f"\t{gate_info}")


        # this updates the used gates and re-indexes them to the correct location on the slider
        self.setUsedGates(gate_list, update_index = True, update_ranges = False)
        
        
        # process range info noting that some ranges may be missing
        if verbose:
            syslog.info("Parsing ranges:")


        # read range configuration
        range_pairs = {}            

        node_ranged = node.xpath(".//range")
        for child in node_ranged:

            
            range_id = safe_read(child, "id", str, "")
            if paste_mode:
                new_guid = gremlin.util.get_guid()
                guid_map[range_id] = new_guid
                range_id = new_guid
            
            if not range_id:
                range_id = get_guid()

            description = None
            if "description" in child.attrib:
                description = child.get("description")

            min_id = safe_read(child, "min_id", str, "")
            max_id = safe_read(child, "max_id", str, "")
            g1 : GateInfo = next((g for g in gate_list if g.id == min_id), None)
            g2 : GateInfo = next((g for g in gate_list if g.id == max_id), None)

            if not g1:
                # continue (bad data)
                syslog.error(f"GATE XML: invalid min gate ID in range data.  Gate [{min_id}] is not a valid gate. ")
                continue

            if not g2:
                # continue (bad data)
                syslog.error(f"GATE XML: invalid max gate ID in range data.  Gate [{max_id}] is not a valid gate. ")
                continue1

            assert min_id != max_id,"XML: invalid range gate IDs detected"
             
  
            if verbose:
                syslog.info (f"\tadding range: (by id) gate [{g1.slider_index}] {g1.value:0.3f} [{g2.slider_index}]  {g2.value:0.3f}")
                
            if g1 == g2:
                g1, g2 = self.ensure_separation(g1, g2)
                assert g1 != g2,"XML: Ranges require two different gates"

            assert g1.id != g2.id, "GATE XML: invalid data = gates for range are identical"


            key = (g1,g2)
            range_info = RangeInfo(g1, g2, used = True, parent = self)
            range_pairs[key] = range_info

            description = safe_read(child, "description", str, "")
            range_info.description = description

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


            range_info.delay = safe_read(child,"delay",int,250)
            range_info.id = range_id
            range_info.setLastCondition(range_condition)
            range_info.mode = range_mode
            
            range_info.setUsed(True)
            range_info.g1 = g1
            range_info.g2 = g2

            if range_mode == GateRangeOutputMode.Ranged:
                range_info.output_range_min = range_min
                range_info.output_range_max = range_max
            elif range_mode == GateRangeOutputMode.Fixed:
                fixed_value = safe_read(child,"fixed_value", float, 0)
                range_info.fixed_value = fixed_value


            self._range_item_map[range_id] = range_info

            # read range mapping data 
            item_nodes = gremlin.util.get_xml_child(child, "range_containers", multiple=True)
            range_info.item_data_map = {}
            for item_node in item_nodes:
                if item_node is not None:
                    item_node.tag = item_node.get("type")
                    if not "condition" in item_node.attrib:
                        condition = range_condition
                    else:
                        condition_str = item_node.get("condition")
                        condition = GateConditionType.to_enum(condition_str)
                    item_data = self._new_item_data()
                    # use ranged containers/actions for range conditions, buttons for the others
                    input_type = InputType.JoystickAxis if condition in (GateConditionType.InRange, GateConditionType.OutsideRange) else InputType.JoystickButton
                    item_data.input_type = input_type
                    item_data.from_xml(item_node, data, extra_data)
                    range_info.item_data_map[condition] = item_data
                
            # remember the created range
            range_list.append(range_info)
            

        # set the new ranges for this gated axis
        self.setUsedRanges(range_list)

        # update any missing ranges
        self._update_ranges()



        # verify range count
        used_range_list = self.getUsedRanges()
        used_gate_list = self.getUsedGates()
        range_count = len(used_range_list)
        gate_count = len(used_gate_list)

        assert range_count == gate_count -1 if gate_count else True, "GATE: XML load: invalid gate/range configuration"


        if verbose:
            
            syslog.info("GATE: loaded gate list:")
            for gate in used_gate_list:
                syslog.info (f"\t{str(gate)}")
            syslog.info("GATE: loaded range list:")
            for rng in used_range_list:
                syslog.info (f"\t{str(rng)}")



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
        self.value = None # the trigger's input value to process as input to containers/actions
        self._raw_value = None # the raw (unfiltered value)
        self.mode : TriggerMode = TriggerMode.Value
        self.gate : GateInfo = None # the gate impacted (for gate triggers only, None for range triggers)
        self.range : RangeInfo = None # current range 
        self.last_range : RangeInfo = None # last range when crossing ranges, None if not crossing
        self.condition : GateConditionType = None # the condition for this trigger
        self.last_value = None # prior value
        self.delay = 250 # default delay
        

    @property
    def is_range(self) -> bool:
        ''' true if the trigger is a linear trigger '''
        return self.condition in (GateConditionType.InRange, GateConditionType.OutsideRange)
    
    @property
    def is_gate(self) -> bool:
        ''' true if the trigger is a gate trigger '''
        return self.mode in (TriggerMode.GateDecrease, TriggerMode.GateCrossed, TriggerMode.GateCrossed)

    @property 
    def raw_value(self) -> float:
        ''' raw value '''
        if self._raw_value is None:
            # return regular value if not set as they are the same in that case
            return self.value
        return self._raw_value
    @raw_value.setter
    def raw_value(self, value : float):
        self._raw_value = value
        

    def __str__(self):
        
        stub = f"[{self.mode.name}]"
        
        if self.mode in (TriggerMode.FixedValue, TriggerMode.ValueInRange, TriggerMode.ValueOutOfRange, TriggerMode.RangeEnter, TriggerMode.RangeExit, TriggerMode.RangedValue):
            value_stub = "n/a" if self.value is None else f"{self.value:0.{_decimals}f} / {self.range.to_percent(self.value):0.2f}%"
            return f"{stub} value: {value_stub}% range [{self.range.range_display()}]"
        else:
            percent = gremlin.util.scale_to_range(self.value,-1,1,0,100)
            value_stub = "n/a" if self.value is None else f"{self.value:0.{_decimals}f} / {percent:0.2f}%"
            return f"{stub} value: {value_stub}% gate: {self.gate.slider_index+1} {self.gate.gate_display()}"
        

class GateWidgetInfo(gremlin.ui.ui_common.QDataWidget):
    ''' holds the data for a single gate '''

    valueChanged = QtCore.Signal(object) # fires when a gate value is changed - sends the gate
    # requestConfigure = QtCore.Signal(object) # fires when the user clicks on the configuration icon - sends the gate 
    deleteConfirm = QtCore.Signal(object) # fires the delete confirm event - sends the gate
    requestGrab =  QtCore.Signal(object) # fires the grab request confirm event - sends the gate

    def __init__(self,
                 gate : GateInfo, 
                 configure_callback,
                 delete_callback,
                 delete_enabled = True,
                 is_container = True,
                 parent = None,

                 ):
        
        super().__init__(parent = parent)
        assert isinstance(gate,GateInfo)
        self.gate = gate
        
        self.setup_icon = None
        self.delete_callback = delete_callback
        self.configure_handler = configure_callback
        self.display_index = 0 # display index for ordering
        self.warning_visible = False # flag for warning label/icon
        self._lock = False
        self._set_value_lock = False

        self._create_widget(gate, 
                            delete_enabled,
                            parent = self
                            )

        # display the default value
        self.update_value(gate.value)
        self.update_icon()
        self._update_tooltip()


    def _handle_delete_confirm(self):
        self.delete_callback()

    def _handle_grab(self):
        self.requestGrab.emit(self.gate)




    def setRange(self, v1 : float, v2: float):
        ''' sets the range of the edit box '''
        self.value_widget.setRange(v1,v2)
        self._update_tooltip()

    def setMaximum(self, value : float):
        self.value_widget.setMaximum(value)

    def setMinimum(self, value: float):
        self.value_widget.setMinimum(value)


    def _update_tooltip(self):
        v1 = self.value_widget.minimum()
        v2 = self.value_widget.maximum()
        self.toolTip = f"Gate [{self.gate.slider_index}] min [{v1:0.03f}] max [{v2:0.3f}]"

    def update_icon(self):
        gremlin.util.InvokeUiMethod(self._update_icon_ui)

    def _update_icon_ui(self):
        ''' updates the icon on the setup button depending on the container state '''
        # syslog.info(f"update icon for gate : {self.gate.to_display()}")
        if self.gate.hasAnyContainers():
            self.setup_widget.setIcon(gremlin.ui.ui_common.Icons.gearIcon(qta_color= gremlin.ui.ui_common.Color().activeContentColor()))
        else:
            self.setup_widget.setIcon(gremlin.ui.ui_common.Icons.gearIcon(qta_color= gremlin.ui.ui_common.Color().inactiveColor()))

        if self.gate.isError:
            warning_color = gremlin.ui.ui_common.Color.warningColor()
            self.setIcon("ph.shield-warning-fill", color = QtGui.QColor(warning_color))
        else:
            self.setIcon(None)


    def cleanup(self):
        self.value_widget.valueChanged.disconnect(self._value_changed_cb) # hook manual changes made to the widget

    
    def _gate_value_changed(self, gate):
        gremlin.util.InvokeUiMethod(self._gate_value_changed_ui, gate)

    def _gate_value_changed_ui(self, gate):
        ''' called when the gate value changes '''
        if Shiboken.isValid(self) and gate.id == self.gate.id:
            verbose = gremlin.config.Configuration().verbose_mode_gate
            if verbose: syslog.info(f"GWI: Gate {self.gate.index} value change to {gate.value}")
            self.update_value(gate.value)
            # indicate the gate order should update
            eh = GateEventHandler()
            eh.gate_order_changed.emit()

            self.update_icon()

    def _gate_configuration_changed(self, gate):
        gremlin.util.InvokeUiMethod(self._gate_configuration_changed_ui, gate)
    
    def _gate_configuration_changed_ui(self, gate):            
        ''' called when a gate changes configuration '''
        if Shiboken.isValid(self) and gate.id == self.gate.id:
            self.update_icon()

    def update_value(self, value):
        gremlin.util.InvokeUiMethod(self.update_value_ui, value)

    def update_value_ui(self, value):
        ''' updates the display gate value on UI thread '''
        if Shiboken.isValid(self):
            with QtCore.QSignalBlocker(self.value_widget):
                # syslog.info(f"GWI: gate {self.gate.index} update display value {value}")
                self.value_widget.setValue(value)
    
    # def _gate_index_changed(self, gate):
    #     gremlin.util.InvokeUiMethod(self._gate_index_changed_ui, gate)

    # def _gate_index_changed_ui(self, gate):
    #     if Shiboken.isValid(self) and gate.id == self.gate.id:
    #         self.update_gate_label()

    # def _display_mode_changed(self, display_mode):
    #     gremlin.util.InvokeUiMethod(self._display_mode_changed_ui, display_mode)

    # def _display_mode_changed_ui(self, display_mode):
    #     ''' set the display mode '''
    #     if Shiboken.isValid(self):
    #         with QtCore.QSignalBlocker(self.value_widget):
    #             # syslog.info(f"GWI: gate {self.gate.index} update display value {value}")
    #             self.value_widget.setValue(self.gate.display_value)

    def update_display(self):
        if Shiboken.isValid(self):
            with QtCore.QSignalBlocker(self.value_widget):
                # syslog.info(f"GWI: gate {self.gate.index} update display value {value}")
                self.value_widget.setValue(self.gate.display_value)

    @property
    def id(self):
        return self.gate.id
    
    @property
    def index(self):
        return self.gate.index

    def is_container(self, value):
        self._is_container = value

    def update_gate_label(self):
        if Shiboken.isValid(self):
            self.label_widget.setText(f"Gate {self.gate.slider_index + 1}:") # the slider index is the ordered gate number

    def _create_widget(self,
                       gate : GateInfo,
                       delete_enabled,
                       parent = None):
        ''' creates a gate widget '''
        range_min = -1.0
        range_max = 1.0

        self.setContentsMargins(0,0,0,0)
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0,0,0,0)

        self.data = gate
    
        # label_width = gremlin.shared_state.char_width * 2

        self.label_widget = QtWidgets.QLabel(f"Gate {gate.slider_index + 1}:") # the slider index is the ordered gate number
        #self.label_widget.setMaximumWidth(label_width)

        self.label_warning = QtWidgets.QLabel(" ")
        self.label_warning.setMaximumWidth(20)
        self.label_warning.setMinimumWidth(20)
        #self.label_warning.setVisible(False)
        
        self.value_widget = gremlin.ui.ui_common.QFloatLineEdit(gate, range_min, range_max)
        self.value_widget.setValue(gate.value)
        self.value_widget.valueChanged.connect(self._value_changed_cb) # hook manual changes made to the widget

        self.grab_widget = gremlin.ui.ui_common.QDataPushButton()
        self.grab_widget.setIcon(load_icon("mdi.checkbox-blank-circle",qta_color = gremlin.ui.ui_common.Color.recordColor()))
        self.grab_widget.setMaximumWidth(20)
        self.grab_widget.clicked.connect(self._handle_grab)
        self.grab_widget.setToolTip("Grab axis value")
        self.grab_widget.data = (gate, self.value_widget)
        

        self.setup_widget = gremlin.ui.ui_common.QDataPushButton()
        self.setup_widget.setMaximumWidth(20)
        self.setup_widget.clicked.connect(self.configure_handler)
        self.setup_widget.setToolTip(f"Setup actions for gate {gate.gate_display()}")
        self.setup_widget.data = gate
        

        self.clear_widget = gremlin.ui.ui_common.QDataPushButton()
        self.clear_widget.setIcon(load_icon("mdi.delete"))
        self.clear_widget.setMaximumWidth(20)

        
        self.clear_widget.clicked.connect(self.delete_callback)
        self.clear_widget.setToolTip("Removes this gate")
        self.clear_widget.setEnabled(delete_enabled)
        self.clear_widget.data = gate

        main_layout.addWidget(self.label_warning)
        main_layout.addWidget(self.label_widget)
        main_layout.addWidget(self.value_widget)
        main_layout.addWidget(self.grab_widget)
        main_layout.addWidget(self.setup_widget)
        main_layout.addWidget(self.clear_widget)
        main_layout.addStretch()

    # def _handle_configure_request(self):
    #     self.configure_handler()


    def update_warning(self):
        ''' updates the visibility of the warning - this is done out of band because visible immediatley causes a redraw causing UI artifacts '''
        self.label_warning.setVisible(self.warning_visible)
    

    def setValue(self, value : float, emit=True):
        ''' sets the gate value on the widget'''
        if self._set_value_lock:
            return
        self._set_value_lock = True
        try:
            if value != self.value_widget.value():
                with QtCore.QSignalBlocker(self.value_widget):
                    self.value_widget.setValue(value)
            self.gate.setValue(value, emit=False)
        except:
            self._set_value_lock = False

    def setUsed(self, value : bool):
        ''' sets the used state of the widget and associated gate '''
        self.setVisible(value)
        self.gate.setUsed(value)


    def _value_changed_cb(self, value):
        ''' called to record a value changed when the gate value widget is manually changed '''
        #value = gremlin.util.scale_to_range(value, self.value_widget.minimum(), self.value_widget.maximum(), -1.0, 1.0)
        # syslog.info(f"value: {value:0.3f} min: {self.value_widget.minimum():0.3f} max: {self.value_widget.maximum():0.3f}")
        self.gate.setValue(value, emit=False)
        gh = GateEventHandler()
        gh.gate_value_changed.emit(self.gate)
        self.valueChanged.emit(self.gate)
        
        
        

    def setIcon(self, icon, color = None):
        ''' sets the icon, pass a None value to clear it'''
        if icon is not None:
            icon = gremlin.util.load_icon(icon, qta_color = color)
            self.label_warning.setPixmap(icon.pixmap(16,16))
            self.warning_visible = True
        else:
            self.label_warning.setPixmap(QtGui.QPixmap())
            self.warning_visible = False
            

    def display_name(self):
        if self.gate:
            return self.gate.gate_display()
        return "n/a"

        
class RangeWidgetInfo(QtWidgets.QWidget):
    ''' range widget '''
    # requestConfigure = QtCore.Signal(object) # fires when the user clicks on the configuration icon - sends the range 

    def __init__(self, display_index, rng : RangeInfo, decimals, configure_handler, parent = None):
        super().__init__(parent = parent)
        
        self.configure_handler = configure_handler
        self._range : RangeInfo = rng
        self.decimals : int = decimals
        #id : str = rng.id

        self.label_warning = QtWidgets.QLabel(" ")
        self.label_warning.setMaximumWidth(20)
        self.label_warning.setMinimumWidth(20)

        self.label_widget = QtWidgets.QLabel(f"Range {display_index}:")


        self.range_widget = gremlin.ui.ui_common.QDataLabel() #  gremlin.ui.ui_common.QDataLineEdit()

        #self.range_widget.setStyleSheet("background: red;")
        
        #self.range_widget.setReadOnly(True)
        self.range_widget.data = (rng, self.range_widget)
        self.setup_widget = gremlin.ui.ui_common.QDataPushButton(data = rng)
        
        

        self.setup_widget.setMaximumWidth(20)
        self.setup_widget.clicked.connect(self._handle_configure)
        self.setup_widget.setToolTip(f"Setup actions for range [{self.display_name()}]")

        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0,0,0,0)

        main_layout.addWidget(self.label_warning)
        main_layout.addWidget(self.label_widget)
        main_layout.addWidget(self.range_widget)
        main_layout.addWidget(self.setup_widget)
        main_layout.addStretch()


        self.setContentsMargins(0,0,0,0)

        self.setMinimumWidth(200)

        self.setVisible(rng.used)


        # display default value
        self.update_value()
        self.update_icon()

    @QtCore.Slot()
    def _handle_configure(self):
        self.configure_handler(self._range)


    def update_icon(self):
        has_containers = self._range.hasAnyContainers()
        if has_containers:
            self.setup_widget.setIcon(gremlin.ui.ui_common.Icons.gearIcon(qta_color=gremlin.ui.ui_common.Color.activeContentColor()))
        else:
            self.setup_widget.setIcon(gremlin.ui.ui_common.Icons.gearIcon(qta_color=gremlin.ui.ui_common.Color.inactiveColor()))


    def set_decimals(self, value):
        self.decimals = value

    @property
    def range_info(self):
        return self._range
    
    def _gate_value_changed(self, gate):
        gremlin.util.InvokeUiMethod(self._gate_value_changed_ui, gate)
    
    def _gate_value_changed_ui(self, gate):
        ''' respond to gate value changes if the range is mapped to the gate changing value '''
        if Shiboken.isValid(self):
            if gate == self._range.g1 or gate == self._range.g2: 
                self.update_value()
            

    def _range_used_changed(self, rng):
        gremlin.util.InvokeUiMethod(self._range_used_changed_ui, rng)
    
    def _range_used_changed_ui(self, rng):
        if Shiboken.isValid(self) and self._range.id == rng.id:
            syslog.info(f"RWI: Range {self._range.range_gate_display()} usage changed to {rng.used}")
            self.setVisible(rng.used)

    def update_value(self):
        gremlin.util.InvokeUiMethod(self.update_value_ui)

    def update_value_ui(self):
        char_width = gremlin.shared_state.char_width
        g1 : GateInfo = self._range.g1
        g2 : GateInfo= self._range.g2
        g1v = g1.display_value
        g2v = g2.display_value
        decimals = self.decimals      
        delta = abs(g1.value - g2.value)  
        txt = f"[{g1v:+0.{decimals}f},{g2v:+0.{decimals}f}]({delta:0.{decimals}f})"
        self.range_widget.setText(txt)
        self.range_widget.setMinimumWidth(char_width * 8)
        self.setup_widget.setToolTip(f"Setup actions for range [{self.display_name()}]")

    def display_name(self):
        if self.range_info:
            return self.range_info.range_display()
        return "n/a"




class GatedAxisGateCondition(gremlin.actions.AbstractCondition):
    ''' condition that applies to gates and ranges '''

    def __init__(self, gate_data : GateData, gate_info: GateInfo, condition_type : GateConditionType):
        self.comparison = "always"
        super().__init__(self.comparison)
        self.gate_data = gate_data
        self.gate_info = gate_info
        self.ranges = gate_data.getUsedRanges()
        # starting value
        self._last_value = gremlin.joystick_handling.get_axis(gate_data.device_guid, gate_data.input_id) 
        self._condition_type = condition_type

    @property
    def condition_type(self) -> GateConditionType:
        return self._condition_type        

    def __call__(self, event, value, extra_data  : dict = None):
        # default call
        return self.process_event(event, value, extra_data)
    

    def process_event(self, event, value, extra_data : dict = None):
        verbose = gremlin.config.Configuration().verbose_mode_gate


        trigger = extra_data["trigger"]
        condition_type = extra_data["condition_type"]
        
        
        result = False
        if trigger.gate:
            if self.gate_info.id != trigger.gate.id:
                # not the correct gate
                return False
            result = self._condition_type == condition_type
            if verbose: 
                logTabs = gremlin.shared_state.logTabs()
                syslog.info(f"{logTabs}GATED AXIS: gate condition [{self.gate_info.id}] [{self.gate_info.index}] value: [{self.gate_info.value:0.03f} TRIGGER {self._condition_type.name}:  result: {result}")
        return result
        

        
    def condition_name(self) -> str:
        return f"Gated Axis Gate Condition: condition: {self._condition_type.name} range: {self.gate_info.to_display()}"        
        
    
class GatedAxisRangeCondition(gremlin.actions.AbstractCondition):
    ''' condition that applies to gates and ranges '''

    def __init__(self, gate_data : GateData, range_info : RangeInfo, condition_type : GateConditionType):
        self.comparison = "always"
        super().__init__(self.comparison)
        self.gate_data = gate_data
        self.range_info = range_info
        # starting value
        self._last_value = gremlin.joystick_handling.get_axis(gate_data.device_guid, gate_data.input_id) 
        self._condition_type = condition_type

    @property
    def condition_type(self) -> GateConditionType:
        return self._condition_type

    def __call__(self, event, value, extra_data  : dict = None):
        # default call
        return self.process_event(event, value, extra_data)

    def process_event(self, event, value, extra_data : dict = None):
        verbose = gremlin.config.Configuration().verbose_mode_gate

      
        condition_type = extra_data["condition_type"]
        trigger = extra_data["trigger"]

        
        result = False
        if trigger.range:
            r1 = self.range_info
            r2 = trigger.range
            result = self._condition_type == condition_type and r1.g1 == r2.g1 and r1.g2 == r2.g2
            if verbose: 
                logTabs = gremlin.shared_state.logTabs()
                syslog.info(f"{logTabs}GATED AXIS: range condition compare trigger range [{trigger.range.to_display()}] to [{self.range_info.to_display()}] TRIGGER {self._condition_type.name}:  result: {result}")
        return result



     

        
    def condition_name(self) -> str:
        return f"Gated Axis Range Condition: condition: {self._condition_type.name} range: {self.range_info.to_display()}"
        