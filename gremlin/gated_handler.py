

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
_single_step = 0.001
 


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
    GateCondition.OnCross: "Triggers when the input crosses a gate",
    GateCondition.OnCrossDecrease: "Triggers when the input crosses a gate (crossing from the right/above)",
    GateCondition.OnCrossIncrease: "Triggers when the input crosses a gate (crossing from the left/below)"
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

def _is_close(a, b, tolerance = 0.0001):
    ''' compares two floating point numbers with approximate precision'''
    return math.isclose(a, b, abs_tol=tolerance)

class GateData(QtCore.QObject):
    ''' holds gated information for an axis 
    
        this object knows how to load and save itself to XML
    '''

    stepsChanged = QtCore.Signal() # signals that steps (gate counts) have changed 
    valueChanged = QtCore.Signal() # signals when the gate data changes

    class GateInfo(QtCore.QObject):
        ''' holds gate data information '''

        valueChanged = QtCore.Signal() # fires when the value changes

        def __init__(self, value = None, profile_mode = None, item_data = None, condition = GateCondition.OnCross, parent = None, is_default = False):
            super().__init__()

            self.parent : GateData = parent
            self.is_default = is_default # default gate setups (not saved)
            self._id = get_guid()
            self._value = value
            self.condition = condition
            self.profile_mode = profile_mode
            self.item_data : gremlin.base_profile.InputItem = item_data
            # force the item data to mimic a joystick button as gates are trigger actions - this will configure actions int he container correctly for this type of input
            self.item_data.input_type = InputType.JoystickButton
            self.item_data.input_id = 1
            
            self.used = True
            self.slider_index =  None # index of the gate in the slider 
            self.delay = 250  # delay in milliseconds for the trigger duration between a press and release


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

        @property
        def id(self):
            return self._id
        @id.setter
        def id(self, value):
            self._id = value

        def __lt__(self, other):
            return self._value < other._value
        
        def __str__(self):
            return f"Gate {self.display_index} [{self.index}]  {self.value:0.{_decimals}f} cond: {self.condition} used: {self.used}"

    class RangeInfo(QtCore.QObject):
        valueChanged = QtCore.Signal() # fires when either of the gate values change

        def __init__(self, min_gate, max_gate, profile_mode = None, item_data = None, condition = GateCondition.InRange, 
                     mode = GateRangeOutputMode.Normal, range_min = -1, range_max = 1, parent = None,  is_default = False):
            super().__init__()

            self.parent = parent
            self._id = get_guid()
            self.is_default = is_default
            self.profile_mode = profile_mode
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
        def id(self):
            return self._id
        @id.setter
        def id(self, value):
            self._id = value            

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

        def pair(self):
            return (self.v1, self.v2)

        def __str__(self):
            if self.v1 is None or self.v2 is None:
                rr = f"N/A"
            else:
                rr = f"{self.v1:0.{_decimals}f},{self.v2:0.{_decimals}f}"
            return f"Range [{rr}] mode: {self.mode}  id: {self.id}"
        
        def __hash__(self):
            return hash(self.range_values())



    def __init__(self,
                 profile_mode, # required - profile mode this applies to (can also be set from XML)
                 action_data, # required - action data block (usually the object that contains a functor)
                 min = -1.0,
                 max = 1.0,
                 condition = GateCondition.OnCross,
                 mode = GateRangeOutputMode.Normal,
                 range_min = -1.0,
                 range_max = 1.0,
                 process_callback = None):
        ''' GateData constructor '''
        super().__init__()

        self._action_data = action_data
        self._min = min # gate min range
        self._max = max # gate max range
        self.condition = condition
        self.output_mode = mode
        self.profile_mode = profile_mode # profile mode this gate data applies to (can be set via reading from XML)
        self.fixed_value = 0
        self.range_min = range_min
        self.range_max = range_max
        self.macro : gremlin.macro.Macro = None  # macro steps
        self.id = gremlin.util.get_guid()
        self.use_default_range = True # if true, the default range is used to drive the output on the overall axis size
        self.show_percent = False # if true, displays data as percentages

        self._last_value = None # last input value
        self._last_range = None # last range object

        # default gates and range
        min_gate = GateData.GateInfo(min, profile_mode = profile_mode, item_data = self._new_item_data(), is_default = True)
        max_gate = GateData.GateInfo(max, profile_mode = profile_mode, item_data = self._new_item_data(), is_default = True)
        range_info = GateData.RangeInfo(min_gate, max_gate, profile_mode=profile_mode, item_data = self._new_item_data(), condition= GateCondition.InRange, mode= GateRangeOutputMode.Normal, is_default = True)
        self.default_range = range_info
        self.default_min_gate = min_gate
        self.default_max_gate = max_gate
        self._gate_item_map = {} # holds the input item data for gates index by gate index
        self._range_item_map = {} # holds the input item data for ranges indexed by range index

        self._trigger_range_lines = [] # activity triggers
        self._trigger_gate_lines = [] # activity triggers
        self._trigger_line_count = 10 # last 10 triggers max


        self._callbacks = {} # map of containers to their excecution graph callbacks for sub containers
        self._process_callback = process_callback

        
        # hook joystick input for runtime processing of input
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)
        el.profile_start.connect(self._profile_start_cb)
        el.profile_stop.connect(self._profile_stop_cb)

    @property
    def process_callback(self):
        ''' the callback object '''
        return self._process_callback
    @process_callback.setter
    def process_callback(self, value):
        self._process_callback = value

    @QtCore.Slot()
    def _profile_start_cb(self):
        ''' profile starts - build execution callbacks by defined container '''
        callbacks_map = {}

        # get all the sub containers defined by this widget
        gates = self.getGates()
        ranges = self.getRanges()
        for gate in gates:
            for container in gate.item_data.containers:
                callbacks_map[container] = container.generate_callbacks()
        for rng in ranges:
            for container in rng.item_data.containers:
                callbacks_map[container] = container.generate_callbacks()

        self._callbacks = callbacks_map  # holds the callbacks for each container found

 
    @QtCore.Slot()
    def _profile_stop_cb(self):
        ''' profile stops - cleanup '''
        self._callbacks.clear()


    @QtCore.Slot(object)
    def _joystick_event_cb(self, event):
        ''' handles joystick input 
        
        To avoid challenges with other GremlinEx functionality - we handle our own calls to our subcontainers here.
        The idea is that we duplicate the behavior of normal actions/containers receiving data.

        For gate crossings, we mimic a button push (for now) in case containers need to have a press and release
        
        '''

        if not gremlin.shared_state.is_running:
            return # profile is not running - nothing to do
        
        if not event.is_axis:
            # ignore if not an axis event 
            return

        # mode check
        

        if self._action_data.hardware_device_guid != event.device_guid:
            # ignore if a different input device
            return
            
        if self._action_data.hardware_input_id != event.identifier:
            # ignore if a different input axis on the input device
            return

        raw_value = event.raw_value
        input_value = gremlin.joystick_handling.scale_to_range(raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1) 
        self._axis_value = input_value


        # run mode - execute the functors with the gate data
        value = gremlin.actions.Value(event.value)
        triggers = self.gate_data.process_value(self._axis_value)
        trigger: TriggerData
        for trigger in triggers:
            short_press = False
            if trigger.mode == TriggerMode.FixedValue:
                value.current = trigger.value
                containers = trigger.range.item_data.containers
            elif trigger.mode == TriggerMode.ValueInRange:
                containers = trigger.range.item_data.containers
                
            elif trigger.mode == TriggerMode.ValueOutOfRange:
                containers = trigger.range.item_data.containers
            elif trigger.mode == TriggerMode.GateCrossed:
                # mimic a joystick button press for a gate crossing
                delay = trigger.gate.delay
                event.is_axis = False
                event.event_type = InputType.JoystickButton
                containers = trigger.gate.item_data.containers
                short_press = True # send a key up in 250ms
            

            # process container execution graphs
            container: gremlin.base_profile.AbstractContainer
            for container in containers:
                if container in self._callbacks.keys():
                    callbacks = self._callbacks[container]
                    for cb in callbacks:
                        for functor in cb.callback.execution_graph.functors:
                            if short_press:
                                thread = threading.Thread(target=lambda: self._short_press(functor, event, value, delay))
                                thread.start()
                            else:
                                # not a momentary trigger
                                functor.process_event(event, value)
            
                                
            # process other functor callback for the action owning this gated output 
            if self._process_callback is not None:
                if short_press:
                    thread = threading.Thread(target=lambda: self._short_press(self._process_callback, event, value, delay))
                    thread.start()
                else:
                    self._process_callback(event, value)


    def _short_press(self, functor, event, value, delay = 250):
        ''' triggers a short press of a trigger (gate crossing)'''
        print ("short press ")
        value.current = True
        value.is_pressed = True
        functor.process_event(event, value)
        time.sleep(delay/1000) # ms to seconds
        value.current = False
        value.is_pressed = False
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
    def single_step(self):
        ''' preferred stepping value'''
        return _single_step

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
            
    @property
    def steps(self):
        ''' gets the number of used gates '''
        return len(self._get_used_gates(force_index = False))

    def getGateValues(self, ):
        ''' gets a list of gate values in slider order - the slider order should be set whenever the slider is first populated so we know which index is what gate  '''
        gates = self._get_used_gates()
        if not gates:
            # create a pair of gates for new ranges
            g1 = GateData.GateInfo(-1.0, profile_mode = self.profile_mode, item_data = self._new_item_data())
            g2 = GateData.GateInfo(1.0, profile_mode = self.profile_mode, item_data = self._new_item_data())
            self._gate_item_map[g1.id] = g1
            self._gate_item_map[g2.id] = g2
            g1.slider_index = 0
            g2.slider_index = 1
            gates = [g1, g2]
        data = [(info.slider_index, info.value) for info in gates]
        data.sort(key = lambda x: x[0])
        return [d[1] for d in data]
    
    def updateGateSliderIndices(self):
        ''' updates slider indices'''
        return self._get_used_gates(force_index=True)

    
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



    

    def setGateValue(self, index, value):
        ''' sets the value of a gate '''
        gate = self.getGate(index)
        if gate.value != value:
            gate.value = value
            

    def setGateUsed(self, index, value):
        ''' enables or disables a gate '''
        gate = self.getGate(index)
        gate.used = value

    def getRanges(self, include_default = True, update = False):
        ''' returns the list of ranges as range info objects'''
        if update:
            self._update_ranges()
        return self._get_ranges(include_default)
    
    def getGate(self, id = None, value = -2.0):
        ''' returns a gate object for the given index - the item is created if the index does not exist and the gate is marked used '''
        if id is None or not id in self._gate_item_map.keys():
            if id is None:
                id = get_guid()
            item_data = self._new_item_data()
            gate = GateData.GateInfo(value = value, profile_mode = gremlin.shared_state.current_mode, item_data=item_data, parent = self)
            gate.id = id
            self._gate_item_map[id] = gate
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"Added gate: {value:0.{_decimals}f} {gate.id}")
        return self._gate_item_map[id]
    
    def getGates(self):
        ''' gets all used gates '''
        return self._get_used_gates()

    
    def getRange(self, id = None):
        ''' returns a range object for the given index - the item is created if the index does not exist but gates are not initialized'''
        if id is None:
            id = get_guid()
        if not id in self._range_item_map.keys():
            item_data = self._new_item_data()
            range_info = GateData.RangeInfo(None, None, profile_mode = gremlin.shared_state.current_mode, item_data=item_data, parent = self)
            range_info.id = id
            self._range_item_map[id] = range_info
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
        index = data.index
        del self._gate_item_map[index]


        
    def normalize_steps(self, use_current_range = False):
        ''' normalizes gate intervals based on the number of gates 
        
        :param: use_current_range = normalize steps over the current min/max range, if false, resets min/max and uses the full range

        '''

        if not use_current_range:
            self._min = -1.0
            self._max = 1.0

        gates = self.getGates()
        steps = len(gates)

        minmax_range = self._max - self._min
        interval = minmax_range / (steps-1)
        current = self._min
        for gate in gates:
            gate.value = current
            current += interval
        


    def _get_next_gate_index(self):
        ''' gets the next unused index '''
        used_list = self._get_used_gate_ids()
        for index in range(100):
            if not index in used_list:
                return index
        return None

    def _update_ranges(self):
        ''' updates the list of ranges with updated gate configuration - this should be called whenever a gate is added or removed  '''
        value_list = self._get_used_gates()
        # save the current range data
        data = [r.item_data for r in self._range_item_map.values()]
        self._range_item_map.clear()

        for index in range(len(value_list)-1):
            g1 = value_list[index]
            g2 = value_list[index+1]
            info = self.getRange()
            info._min_gate = g1
            info._max_gate = g2
            if index < len(data):
                info.item_data = data[index]

        ranges = self._get_ranges(include_default = False)
        self._range_list = ranges
        verbose =  gremlin.config.Configuration().verbose
        if verbose:
            syslog.info("Updated ranges:")
            for r in ranges:
                syslog.info(f"\tRange: {str(r)}")


    def update_steps(self, value):
        ''' updates the stepped data when the range changes or when the number of gate change
        :param: value = number of gates

        '''

        # add the missing steps only (re-use other steps so we don't lose their config)
        current_steps = len(self.getGates())
        verbose = gremlin.config.Configuration().verbose
        if current_steps < value:

            # how many gates to add
            steps = value - current_steps

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
            for index in range(value, current_steps):
                self.setGateUsed(index, False)


        # reoder the gate slider index based on the values 
        gates = self.updateGateSliderIndices()
    
        if verbose:
            syslog.info(f"Updated gates:")
            for gate in gates:
                syslog.info(f"\tGate: {gate.slider_index} {gate.value:0.{_decimals}f}")


        self._update_ranges()
        self.stepsChanged.emit() # indicate step data changed

 

    def _get_used_items(self):
        ''' gates the index/gate pairs for active gates '''
        gates = [(info.slider_index, info) for info in self._gate_item_map.values() if info.used]
        gates.sort(key = lambda x: x[1].value) # sort ascending
        return gates
    
    def _get_used_values(self):
        ''' gets the position of active gates'''
        gates = [info.value for info in self._gate_item_map.values() if info.used]
        gates.sort()
        return gates
    
    def _gate_used_gates(self):
        ''' gets used gates '''
        return [info for info in self._gate_item_map.values() if info.used]

        
    
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
        rng : GateData.RangeInfo
        for rng in ranges:
            if rng.inrange(v1):
                result.add(rng)
            if rng.inrange(v2):
                result.add(rng)
            
        return list(result)
    
    def _get_used_gates(self, force_index = False):
        ''' gets the list of active gates '''
        gates = [info for info in self._gate_item_map.values() if info.used] 
        gates.sort(key = lambda x: x.value) # sort gate ascending
        needs_index = [gate for gate in gates if gate.slider_index is None]
        if needs_index or force_index:
            for index, gate in enumerate(gates):
                gate.slider_index = index
        return gates
    
    def _get_used_gate_ids(self):
        ''' gets the lif of activate gate indices '''
        return [info.id for info in self._gate_item_map.values() if info.used and not info.is_default]

    def _get_ranges(self, include_default = True):
        ''' buils a sorted list of gate range objects filtered by used gates and by gate value '''
        
        range_list = [r for r in self._range_item_map.values() if r.g1 and r.g2 and r.g1.used and r.g2.used]
        range_list.sort(key = lambda x: x.g1.value)

        if self.use_default_range and include_default:
            range_list.insert(0, self.default_range)
        
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
        
        current_range : GateData.RangeInfo = self._get_range_for_value(current_value) # gets the range of the current value

        if self.use_default_range:
            # using default range for the value trigger
            value = self._get_filtered_range_value(self.default_range, current_value)
            if value:
                td = TriggerData()
                td.mode = TriggerMode.ValueInRange
                td.value = value
                td.range = self.default_range
                td.is_range = True
                triggers.append(td)
        else:
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


        
        # figure out if we changed ranges
        
        last_range = self._last_range

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

        # # process the triggers at runtime 
        # if triggers and gremlin.shared_state.is_running:
        #     el = gremlin.event_handler.EventListener()
        #     for trigger in triggers:
        #         event = trigger.event()
        #         el.trigger_event.emit(event)
        
        return triggers

        
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

        node.set("use_default_range",str(self.use_default_range))
        node.set("show_percent", str(self.show_percent))

        # save gate data
        for gate in self.getGates():
            child = ElementTree.SubElement(node, "gate")
            if gate.is_default:
                child.set("default",str(gate.is_default))
            child.set("condition", _gate_condition_to_name[gate.condition])
            child.set("value", f"{gate.value:0.{_decimals}f}")
            child.set("id", gate.id)
            if gate.item_data.containers:
                item_node = gate.item_data.to_xml()
                if item_node is not None:
                    item_node.set("type", item_node.tag)
                    item_node.tag = "action_containers"
                    child.append(item_node)

        # save range data
        rng : GateData.RangeInfo
        for rng in self.getRanges():
            child = ElementTree.SubElement(node,"range")
            if rng.is_default:
                child.set("default", str(rng.is_default))
            child.set("id", rng.id)
            if not rng.is_default:
                child.set("min_id", rng.g1.id)
                child.set("max_id", rng.g2.id)
            child.set("condition",_gate_condition_to_name[rng.condition])
            child.set("mode",_gate_range_to_name[rng.mode])
            if rng.range_max is not None:
                child.set("range_min",  f"{rng.range_max:0.{_decimals}f}")
            if rng.range_min is not None:
                child.set("range_max",  f"{rng.range_min:0.{_decimals}f}")
            if rng.fixed_value is not None:
                child.set("fixed_value", f"{rng.fixed_value:0.{_decimals}f}")
            if rng.item_data.containers:
                item_node = rng.item_data.to_xml()
                if item_node is not None:
                    item_node.set("type", item_node.tag)
                    item_node.tag = "range_containers"
                    child.append(item_node)
            
            



        return node
    


    def from_xml(self, node):
        if not node.tag == "gate":
            syslog.error(f"GateData: Invalid node type {node.tag} {node}")
            return
    
        self.use_default_range = safe_read(node, "use_default_range", bool, True)
        self.show_percent = safe_read(node,"show_percent", bool, False)

        # read gate configurations 
        node_gates = gremlin.util.get_xml_child(node, "gate", multiple=True)
        gate_count = len(node_gates)
        profile_mode = self.get_xml_mode(node) # get the profile mode from the XML tree
        self.profile_mode = profile_mode
        for child in node_gates:
            gate_id = safe_read(child, "id", str, get_guid())
            gate_default = safe_read(child, "default", bool, False)
            gate_value = safe_read(child, "value", float, 0.0)
            gate_condition = safe_read(child, "condition", str, "")
            if not gate_condition in _gate_condition_from_name.keys():
                syslog.error(f"GateData: Invalid condition type {gate_condition} gate id: {gate_id}")
                return
            gate_condition = GateCondition.from_string(gate_condition)
            
            item_node = gremlin.util.get_xml_child(child, "action_containers")
            item_data = self._new_item_data()
            if item_node:
                item_node.tag = item_node.get("type")
                item_data.from_xml(item_node)

            gate = GateData.GateInfo(gate_value, profile_mode, item_data, gate_condition, parent = self)
            gate.id = gate_id
            gate.is_default = gate_default
            if gate_default:
                if gate.value == -1.0:
                    self.default_min_gate.id = gate
                elif gate.value == 1.0:
                    self.default_max_gate.id = gate
            else:
                self._gate_item_map[gate_id] = gate

        # read range configuration
        node_ranged = gremlin.util.get_xml_child(node, "range", multiple=True)
        for child in node_ranged:
            range_id = safe_read(child, "id", str, get_guid())
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


            range_condition = safe_read(child, "condition", str, "")
            if not range_condition in _gate_condition_from_name.keys():
                syslog.error(f"GateData: Invalid condition type {range_condition} range: {range_id}")
                return
            range_condition = _gate_condition_from_name[range_condition]

            range_mode = safe_read(child, "mode", str, "")
            if not range_mode in _gate_range_from_name.keys():
                syslog.error(f"GateData: Invalid mode {range_mode} range: {range_id}")
                return
            range_mode = _gate_range_from_name[range_mode]
       
            item_node = gremlin.util.get_xml_child(child, "range_containers")
            item_data = self._new_item_data()
            if item_node:
                item_node.tag = item_node.get("type")
                item_data.from_xml(item_node)


            range_min = safe_read(child,"range_min", float, -1.0)
            range_max = safe_read(child,"range_max", float, 1.0)

            if "fixed_value" in child.attrib:
                fixed_value = safe_read(child,"fixed_value", float, 0)
            else:
                fixed_value = None

            range_info = GateData.RangeInfo(min_gate, max_gate, 
                                            profile_mode = profile_mode,
                                            item_data = item_data,
                                            condition = range_condition, 
                                            mode = range_mode,
                                            range_min= range_min,
                                            range_max=range_max,
                                            is_default = range_default)
            range_info.id = range_id
            if fixed_value is not None:
                range_info.fixed_value = fixed_value

            if range_default:
                # default range data
                self.default_range = range_info
            else:
                self._range_item_map[range_id] = range_info
        

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
            return f"{stub} value: {self.value:0.{_decimals}f} range [{self.range.v1:0.{_decimals}f},{self.range.v2:0.{_decimals}f}]"
        elif self.mode == TriggerMode.RangedValue:
            return f"{stub} value: {self.value:0.{_decimals}f} range:[{self.range.v1:0.{_decimals}f},{self.range.v2:0.{_decimals}f}]"
        else:
            return f"{stub} value: {self.value:0.{_decimals}f} gate: {self.gate.slider_index+1}" 
        


class GateWidget(QtWidgets.QWidget):
    ''' a widget that represents a single gate on an axis input and what should happen in that gate
    
        a gate has a min/max value, an optional output range and can trigger different actions based on conditions applied to the input axis value 
    
    '''

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz
    duplicate_requested = QtCore.Signal(object) # fired when the duplicate button is clicked - passes the GateData to duplicate
    configure_requested = QtCore.Signal(object) # configure clicked
    configure_range_requested = QtCore.Signal(object) # configure range - data = range object
    configure_gate_requested = QtCore.Signal(object) # configure gate - data = gate object


    def __init__(self, action_data, gate_data, parent = None):
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
        

        self._grab_icon = load_icon("mdi.record-rec",qta_color = "red")
        self._setup_icon = load_icon("fa.gear")
        
        # get the curent axis normalized value -1 to +1
        value = gremlin.joystick_handling.get_axis(action_data.hardware_device_guid, action_data.hardware_input_id)
        self._axis_value = value 

        # axis input gate widget
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
      
        self.container_slider_widget = QtWidgets.QWidget()
        self.container_slider_layout = QtWidgets.QGridLayout(self.container_slider_widget)
        self.container_slider_layout.addWidget(self.slider,0,0,-1,1)

        self.container_slider_layout.addWidget(QtWidgets.QLabel(" "),0,6)

        self.container_slider_layout.setColumnStretch(0,3)
        
        self.container_slider_widget.setContentsMargins(0,0,0,0)

      

        # configure trigger button
        self._configure_trigger_widget = QtWidgets.QPushButton("Configure")
        self._configure_trigger_widget.setIcon(self._setup_icon)
        self._configure_trigger_widget.clicked.connect(self._trigger_cb)

        # manual and grab value widgets
        self.container_gate_widget = QtWidgets.QWidget()
        self.container_gate_layout = QtWidgets.QGridLayout(self.container_gate_widget)
        self.container_gate_widget.setContentsMargins(0,0,0,0)

        self.container_range_widget = QtWidgets.QWidget()
        self.container_range_layout = QtWidgets.QGridLayout(self.container_range_widget)
        self.container_range_widget.setContentsMargins(0,0,0,0)


        self.container_options_widget = QtWidgets.QWidget()
        self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
        self.container_options_widget.setContentsMargins(0,0,0,0)

        self._use_default_range_widget = QtWidgets.QCheckBox("Use default range for axis output")
        self._use_default_range_widget.setChecked(self.gate_data.use_default_range)
        self._use_default_range_widget.clicked.connect(self._use_default_range_changed_cb)
        self._use_default_range_widget.setToolTip("When set, the axis output uses the default range setting for value output, sub-ranges can still be used to trigger actions based on entry/exit of ranges")

        self._display_percent_widget = QtWidgets.QCheckBox("Show as percent")
        self._display_percent_widget.setChecked(self.gate_data.show_percent)
        self._display_percent_widget.clicked.connect(self._show_percent_cb)
        self._display_percent_widget.setToolTip("Display values as percentages")


        self.container_options_layout.addWidget(self._use_default_range_widget)
        self.container_options_layout.addWidget(self._display_percent_widget)
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
        self.main_layout.addWidget(self.container_gate_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_options_widget,row,0,1,-1)
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


        # update visible container for the current mode
        #self._update_conditions()
        self._update_ui()
        self._update_values()



    def _helper(self):
        helper = ui_common.QHelper()
        helper.show_percent = self.gate_data.show_percent
        return helper
    
    def _update_gates_ui(self):
        ''' creates the gate data for each gate '''
        
        
        
        self._gate_value_widget_map = {}
        gremlin.util.clear_layout(self.container_gate_layout)
        items = self.gate_data.getGateValueItems()


        gate_count_widget = QtWidgets.QLabel(f"Defined gates: {len(items)}")
        self.container_gate_layout.addWidget(gate_count_widget,0,0)
        row = 1
        col = 0

        label_width = ui_common.get_text_width("Range MM")
        value_width = ui_common.get_text_width("1234567 MM")
        helper = self._helper()

        for id, info in items:
            label_widget = QtWidgets.QLabel(f"Gate {info.slider_index + 1}:")
            label_widget.setMaximumWidth(label_width)
            sb_widget = helper.get_double_spinbox(id, info.value)
            sb_widget.valueChanged.connect(self._gate_value_changed_cb)
            sb_widget.setMaximumWidth(value_width)
            self._gate_value_widget_map[info.id] = sb_widget

            grab_widget = ui_common.QDataPushButton()
            grab_widget.data = (info, sb_widget) # gate and control to update
            grab_widget.setIcon(self._grab_icon)
            grab_widget.setMaximumWidth(20)
            grab_widget.clicked.connect(self._grab_cb)
            grab_widget.setToolTip("Grab axis value")

            setup_widget = ui_common.QDataPushButton()
            setup_widget.data = id
            setup_widget.setIcon(self._setup_icon)
            setup_widget.setMaximumWidth(20)
            setup_widget.clicked.connect(self._setup_cb)
            setup_widget.setToolTip(f"Setup actions for gate {id}")

            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QHBoxLayout(container_widget)



            container_layout.addWidget(label_widget)
            container_layout.addWidget(sb_widget)
            container_layout.addWidget(grab_widget)
            container_layout.addWidget(setup_widget)
            container_widget.setContentsMargins(0,0,0,0)

            self.container_gate_layout.addWidget(container_widget, row, col)
            
            col += 1
            if col > 5:
                row+=1
                col = 0

        # pad the grid so controls are aligned left
        max_col = self.container_gate_layout.columnCount() + 2
        self.container_gate_layout.addWidget(QtWidgets.QLabel(" "), 0,max_col)            
        self.container_gate_layout.setColumnStretch(max_col, 3)

        # ranges between the gates
        gremlin.util.clear_layout(self.container_range_layout)
        range_list = self.gate_data.getRanges(include_default = self.gate_data.use_default_range)
        range_count_widget = QtWidgets.QLabel(f"Defined ranges: {len(range_list)}")
        self.container_range_layout.addWidget(range_count_widget,0,0)
        row = 1
        col = 0
        self._range_readout_widgets = {}
        rng : GateData.RangeInfo
        
        edit_width = ui_common.get_text_width("[+0.000 to +0.000]M")
        display_index = 0
        for rng in range_list:
            id = rng.id
            g1 : GateData.GateInfo = rng.g1
            g2 : GateData.GateInfo= rng.g2
            if rng.is_default:
                # default range
                label_widget = QtWidgets.QLabel(f"Default:")
            else:
                display_index += 1
                label_widget = QtWidgets.QLabel(f"Range {display_index}:")

            label_widget.setMaximumWidth(label_width)

            range_widget = ui_common.QDataLineEdit()
            range_widget.setReadOnly(True)
            g1v = helper.to_value(g1.value)
            g2v = helper.to_value(g2.value)
            range_widget.setText(f"[{g1v:0.{helper.decimals}f} to {g2v:0.{helper.decimals}f}]")
            range_widget.setMaximumWidth(edit_width)

            self._range_readout_widgets[id] = range_widget
            range_widget.data = (rng, range_widget)
            rng.valueChanged.connect(self._range_changed_cb)
            
            
            setup_widget = ui_common.QDataPushButton(data = rng)
            setup_widget.setIcon(self._setup_icon)
            setup_widget.setMaximumWidth(20)
            setup_widget.clicked.connect(self._setup_range_cb)
            setup_widget.setToolTip(f"Setup actions for range {id}")

            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QHBoxLayout(container_widget)

            container_layout.addWidget(label_widget)
            container_layout.addWidget(range_widget)
            container_layout.addWidget(setup_widget)
            container_widget.setContentsMargins(0,0,0,0)

            self.container_range_layout.addWidget(container_widget, row, col)
            
            col += 1
            if col > 4:
                row+=1
                col = 0


        # look for any warnings - updated: slider won't allow overlaps so this check is not needed
        # overlaps = self.gate_data.getOverlappingGates()                
        # if overlaps:
        #     self.warning_widget.setText("Overlapping gates detected")
        #     self.warning_widget.setVisible(True)
        # else:
        #     self.warning_widget.setVisible(False)
            
        max_col = self.container_range_layout.columnCount() + 2
        self.container_range_layout.addWidget(QtWidgets.QLabel(" "), 0,max_col)            
        self.container_range_layout.setColumnStretch(max_col, 3)


    def _range_changed_cb(self):
        ''' called when range data changes '''
        range_info = self.sender()
        range_widget = self._range_readout_widgets[range_info.id]
        g1 : GateData.GateInfo = range_info.g1
        g2 : GateData.GateInfo= range_info.g2
        ''' updates the display for a range item '''
        
        helper = self._helper()
        g1v = helper.to_value(g1.value)
        g2v = helper.to_value(g2.value)
        range_widget.setText(f"[{g1v:0.{helper.decimals}f} to {g2v:0.{helper.decimals}f}]")
        
    @QtCore.Slot()
    def _gate_value_changed_cb(self):
        widget = self.sender()
        id = widget.data
        helper = self._helper()
        value = helper.from_value(widget.value())
        self.gate_data.setGateValue(id, value )

    @QtCore.Slot(bool)
    def _use_default_range_changed_cb(self, checked):
        self.gate_data.use_default_range = checked
        self._update_gates_ui()
    
    @QtCore.Slot(bool)
    def _show_percent_cb(self, checked):
        self.gate_data.show_percent = checked
        self._update_gates_ui()


    @QtCore.Slot()
    def _trigger_cb(self):
        ''' configure clicked '''
        self.configure_requested.emit(self.gate_data)

    @QtCore.Slot(int)
    def _slider_handle_clicked_cb(self, handle_index):
        ''' handle right clicked - pass event along '''
        gate = self.gate_data.getGateSliderIndex(handle_index)
        self.configure_gate_requested.emit(gate)

    @QtCore.Slot(float)
    def _slider_groove_clicked_cb(self, value):
        ''' fired when the user clicked on the groove - adds a gate at that location '''
        gates_indices = self.gate_data.getUsedGatesIds()
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
            gate = self.gate_data.getGateSliderIndex(index)
            if gate:
                gate.value = value
                # if gate.id in self._gate_value_widget_map.keys():
                #     # exists
                #     widget = self._gate_value_widget_map[gate.id]
                #     with QtCore.QSignalBlocker(widget):
                #         widget.setValue(value)

        # update ui
        self._update_gates_ui()                    
        

    def _set_slider_gate_value(self, index, value):
        ''' sets a gate value on the slider '''
        values = list(self.slider.value())
        if value != values[index]:
            values[index] = value
        self._set_slider(values)

    def _set_slider(self, values):
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            sv = "Slider: "
            for idx, v in enumerate(values):
                sv += f"[{idx}] {v:0.{_decimals}f} "
            syslog.info(sv)
        self.slider.setValue(values)

    @QtCore.Slot()
    def _grab_cb(self):
        ''' grab the min value from the axis position '''
        info : GateData.GateInfo
        info, widget = self.sender().data  # the button's data field contains the widget to update
        value = self._axis_value
        info.value = value
        self._set_slider_gate_value(info.slider_index, value)
        

    @QtCore.Slot()
    def _setup_cb(self):
        ''' open the configuration dialog '''
        widget = self.sender()  # the button's data field contains the widget to update
        gate = widget.data
        self.configure_gate_requested.emit(gate)
        
    @QtCore.Slot()
    def _setup_range_cb(self):
        ''' open the configuration dialog for ranges '''
        widget = self.sender()  # the button's data field contains the widget to update
        rng = widget.data
        self.configure_range_requested.emit(rng)

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


        self.container_steps_layout.addWidget(QtWidgets.QLabel("Number of gates:"))
        self.container_steps_layout.addWidget(self.sb_steps_widget)
        self.container_steps_layout.addWidget(self.add_gate_widget)
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
            message_box.exec()
            return
        
        # add the gate
        gate = self.gate_data.getGate(value = value)
        self._update_ui()


    @QtCore.Slot()
    def _set_steps_cb(self):
        ''' sets the number of steps to set/reset when the set step button is clicked'''
        value = self.sb_steps_widget.value()
        if self.gate_data.steps != value:
            self.gate_data.update_steps(value)
            #self._update_steps()


    @QtCore.Slot()
    def _normalize_cb(self):
        ''' normalize button  '''
        value = self.sb_steps_widget.value()
        #self.gate_data.gates = value        
        self.gate_data.normalize_steps(True)
        #self._update_gates_ui()
        self._update_values()


    def _normalize_reset_cb(self):
        ''' normalize reset button  '''
        value = self.sb_steps_widget.value()
        #self.gate_data.gates = value         
        self.gate_data.normalize_steps(False)       
        self._update_values()


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
                self._set_slider(values)
                

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
            self._set_slider(lv)
            
        
        self._update_steps()
        self._update_output_value()            

    QtCore.Slot()
    def _max_changed_cb(self):
        value = self.sb_max_widget.value()
        self.gate_data.max = value
        lv = list(self.slider.value())
        lv[1] = value
        with QtCore.QSignalBlocker(self.slider):
            self._set_slider(lv)
        self._update_steps()
        self._update_output_value()


    def _update_ui(self):
        ''' updates visibility of UI components based on the active options '''
        # update the slider configuration 
        self._set_slider(self.gate_data.getGateValues())
        self._update_output_value()


    def deleteGate(self, data):
        ''' remove the gat fromt his widget '''
        self.gate_data.deleteGate(data)
        self._update_ui()

  

class ActionContainerUi(QtWidgets.QDialog):
    """UI to setup the individual action trigger containers and sub actions """

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz

    def __init__(self, gate_data, data, parent=None):
        '''
        :param: data = the gate or range data block
        :item_data: the InputItem data block holding the container and input device configuration for this gated input
        :index: the gate number of the gated input - there will at least be two for low and high - index is an integer 
        '''
        
        super().__init__(parent)

        is_range = isinstance(data, GateData.RangeInfo)
        self._info = data
    
        self._item_data = data.item_data
        self._gate_data = gate_data
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

        
        decimals = gate_data.decimals
        single_step = gate_data.single_step


        self.trigger_container_widget = QtWidgets.QWidget()
        self.trigger_condition_layout = QtWidgets.QHBoxLayout(self.trigger_container_widget)        

    
        if is_range:
            # range has an output mode for how to handle the output value for the range

            self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Range Configuration:"))

            self.output_widget = QtWidgets.QComboBox()
            self.output_container_widget = QtWidgets.QWidget()
            self.output_container_widget.setContentsMargins(0,0,0,0)
            self.output_container_layout = QtWidgets.QHBoxLayout(self.output_container_widget)
            self.output_container_layout.addWidget(QtWidgets.QLabel("Mode:"))
            self.output_container_layout.addWidget(self.output_widget)
            self.output_container_layout.addStretch()
            

            self._gate_data.populate_output_widget(self.output_widget, default = self._info.mode)
            self.output_widget.currentIndexChanged.connect(self._output_mode_changed_cb)

            # ranged data
            self.container_output_range_widget = QtWidgets.QWidget()
            self.container_output_range_layout = QtWidgets.QHBoxLayout(self.container_output_range_widget)
            self.container_output_range_widget.setContentsMargins(0,0,0,0)
            
            self.sb_range_min_widget = ui_common.DynamicDoubleSpinBox()
            self.sb_range_min_widget.setMinimum(-1.0)
            self.sb_range_min_widget.setMaximum(1.0)
            self.sb_range_min_widget.setDecimals(decimals)
            self.sb_range_min_widget.setSingleStep(single_step)
            self.sb_range_min_widget.setValue(data.range_min)
            self.sb_range_min_widget.valueChanged.connect(self._range_min_changed_cb)

            self.sb_range_max_widget = ui_common.DynamicDoubleSpinBox()
            self.sb_range_max_widget.setMinimum(-1.0)
            self.sb_range_max_widget.setMaximum(1.0)        
            self.sb_range_max_widget.setDecimals(decimals)
            self.sb_range_max_widget.setSingleStep(single_step)
            self.sb_range_max_widget.setValue(data.range_max)

            self.sb_range_max_widget.valueChanged.connect(self._range_max_changed_cb)

            self.sb_fixed_value_widget = ui_common.DynamicDoubleSpinBox()
            self.sb_fixed_value_widget.setMinimum(-1.0)
            self.sb_fixed_value_widget.setMaximum(1.0)        
            self.sb_fixed_value_widget.setDecimals(decimals)
            self.sb_fixed_value_widget.setSingleStep(single_step)
            if data.fixed_value is None:
                data.fixed_value = data.v1
            self.sb_fixed_value_widget.setValue(data.fixed_value)

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
            self.clear_button_widget.clicked.connect(self._delete_cb)
            self.clear_button_widget.setToolTip("Removes this entry")

            self.trigger_condition_layout.addWidget(self.clear_button_widget)

        from gremlin.ui.device_tab import InputItemConfiguration
        self.container_widget = InputItemConfiguration(self._info.item_data)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(self.trigger_container_widget)
        if is_range:
            self.main_layout.addWidget(self.output_container_widget)
        self.main_layout.addWidget(self.container_widget)   
        

        self._update_ui()

    QtCore.Slot()
    def _delay_changed_cb(self):
        ''' delay value changed for gates '''
        self._info.delay = self.delay_widget.value()

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

