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

from abc import abstractmethod, ABCMeta
from functools import partial
import logging

import dinput

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.types import ActivationRule, AxisButtonDirection


import gremlin.input_types
import gremlin.joystick_handling

import gremlin.shared_state
import gremlin.util
import gremlin.fsm

import math


syslog = logging.getLogger("system")

def smart_all(conditions):
    """Returns True if all conditions are True, False otherwise.

    Employs short circuiting in order to prevent unnecessary evaluations.

    :param conditions the conditions to check
    :return True if all conditions are True, False otherwise
    """
    for condition in conditions:
        if not condition():
            return False
    return True


def smart_any(conditions):
    """Returns True if any conditions is True, False if none is True.

    Employs short circuiting in order to prevent unnecessary evaluations.

    :param conditions the conditions to check
    :return True if at least one condition is True, False otherwise
    """
    for condition in conditions:
        if condition():
            return True
    return False


class Value:

    """Represents an input value, keeping track of raw and "seen" value."""

    def __init__(self, value : float, raw : float = None, is_pressed : bool = None):
        """Creates a new value and initializes it.

        :param raw the initial raw data
        """
        self._raw = raw if raw is not None else value
        self._current = value
        self._is_pressed = is_pressed
        

    @property
    def raw(self):
        """Returns the raw unmodified value.

        :return raw unmodified value
        """
        return self._raw
    @raw.setter
    def raw(self, value : float):
        self._raw = value

    @property
    def current(self) -> float: 
        """Returns the current, potentially, modified value.

        :return current and potentially modified value
        """
        return self._current

    @current.setter
    def current(self, current : float):
        """Sets the current value which may differ from the raw one.

        :param current the new current value
        """
        self._current = current

    @property
    def is_pressed(self) -> bool:
        if self._is_pressed is not None:
            return self._is_pressed
        return isinstance(self._current, bool) and self.current

    @is_pressed.setter
    def is_pressed(self, value: bool):
        self._is_pressed = value

    def clone(self):
        ''' clones this value '''
        import copy
        return copy.deepcopy(self)
    
    def invert(self):
        ''' inverts itself for pressed state '''
        e = self.clone()
        e.is_pressed = not self.is_pressed
        if isinstance(self._current,bool):
            e._current = not e._current
        return e
        

    
class ActivationCondition:

    """Represents a set of conditions dictating the activation of actions.

    This class contains a set of functions which evaluate to either True or
    False which is used to indicate whether or not the entire condition is
    True or False.
    """

    
    rule_function = {
        ActivationRule.All: smart_all,
        ActivationRule.Any: smart_any
    }

    def __init__(self, conditions, rule, target, is_container_condition = False):
        self._conditions = conditions
        self._rule = rule
        self.enabled = True # always enabled
        self.target = target # the target this condition applies to (container or action)
        self.id = target.id # the id of this node is the same as the one for the container or action
        self.is_container_condition = is_container_condition
        self.manual_callback = False
        
        
    @property
    def is_container(self) -> bool:
        if self.target:
            return isinstance(self.target, gremlin.base_profile.AbstractContainer)
        return False
    
    @property 
    def isAny(self) -> bool:
        ''' true if the activiation condition is any sub condition '''
        return self._rule == ActivationRule.Any

    def process_event(self, event, value, extra_data = None):
        """Returns whether or not a condition is satisfied, i.e. true.

        :param event the event this condition was triggered through
        :param value process event value
        :return True if all conditions are satisfied, False otherwise
        """
        if not self._conditions:
            # no conditions, always succeeds
            return True
        return ActivationCondition.rule_function[self._rule](
            [partial(c, event, value, extra_data) for c in self._conditions]
        )


    def condition_name(self)->str:
        ''' returns a condition name for diagnostics purposes '''
        rule_name = "all" if self._rule == ActivationRule.All else "any"
        condition_name = ""
        for index, c in enumerate(self._conditions):
            condition_name += f"[C{index}] {c.condition_name()}"
        return f"Rule: [{rule_name}] Is container: [{self.is_container}] Is container condition: [{self.is_container_condition}] Conditions: [{condition_name}] "
    
    def __str__(self):
        return self.condition_name()

class AbstractCondition(metaclass=ABCMeta):

    """Represents an abstract condition.

    Conditions evaluate to either True or False and are given an event as well
    as possibly processed Value when being evaluated.
    """

    def __init__(self, comparison = None):
        """Creates a new condition with a specific comparision operation.

        :param comparison the comparison operation to perform when evaluated
        """
        self.comparison = comparison
        self.id = gremlin.util.get_guid()
        self.manual_callback = False

    @abstractmethod
    def __call__(self, event, value, extra_data = None):
        """Evaluates the condition using the condition and provided data.

        :param event raw event that caused the condition to be evaluated
        :param value the possibly modified value
        :return True if the condition is satisfied, False otherwise
        """
        pass

    @abstractmethod
    def process_event(self, event, value, extra_data = None):
        pass

    def condition_name(self)->str:
        return "condition_name() member not implemented: Condition not set"
    

class KeyboardCondition(AbstractCondition):

    """Condition verifying the state of keyboard keys.

    The conditions that can be checked on a keyboard is whether or not a
    particular key is pressed or released.
    """

    def __init__(self, scan_code, is_extended, comparison, input_item = None):
        """Creates a new instance.

        :param scan_code the scan code of the key to evaluate
        :param is_extended whether or not the key code is extended
        :param comparison the comparison operation to perform when evaluated
        """
        import gremlin.macro
        super().__init__(comparison)
        from gremlin.ui.keyboard_device import KeyboardInputItem
         
        if not input_item:
            input_item = KeyboardInputItem()
            key = gremlin.macro.key_from_code(scan_code, is_extended)
            input_item.key = key

        self.input_item = input_item
       
    def __call__(self, event, value, extra_data = None):
        # default call
        return self.process_event(event, value, extra_data)

    def process_event(self, event, value, extra_data = None):
        """Evaluates the condition using the condition and provided data.

        :param event raw event that caused the condition to be evaluated
        :param value the possibly modified value
        :return True if the condition is satisfied, False otherwise
        """
        # key_pressed = gremlin.input_devices.Keyboard().is_pressed(self.key)
        verbose = gremlin.config.Configuration().verbose_mode_condition
        syslog = logging.getLogger("system")

        if verbose:
            logtabs = gremlin.shared_state.logTabs(True)

        key_pressed = self.input_item.latched
        if self.comparison == "pressed":
            state = key_pressed
        else:
            state =  not key_pressed

        if verbose: syslog.info(f"{logtabs}KeyboardCondition: key: {self.input_item.display_name} pressed {key_pressed} - condition return state: {"OK" if state else "FAILED"}")
        return state
        
        
    def condition_name(self)->str:
        return f"KeyboardCondition {self.input_item.display_name}"
    
    def __str__(self):
        return self.condition_name()


class JoystickCondition(AbstractCondition):

    """Condition verifying the state of a joystick input.

    Joysticks have three possible input types: axis, button, or hat and each
    have their corresponding possibly sates. An axis can be inside or outside
    a specific range. Buttons can be pressed or released and hats can be in
    one of eight possible directions.
    """

    def __init__(self, condition):
        """Creates a new instance.

        :param condition the condition to check against
        """
        super().__init__(condition.comparison)
        self.device_guid = condition.device_guid
        self.input_type = condition.input_type
        self.input_id = condition.input_id
        # hat number or 0 for axis and buttons
        self.input_index = condition.input_index if hasattr(condition,"input_index") else 0
        self.condition = condition


    def __call__(self, event, value, extra_data = None):
        # default call
        return self.process_event(event, value, extra_data)

    def process_event(self, event, value, extra_data = None):
        """Evaluates the condition using the condition and provided data.

        :param event raw event that caused the condition to be evaluated
        :param value the possibly modified value
        :return True if the condition is satisfied, False otherwise
        """

        

        verbose = gremlin.config.Configuration().verbose_mode_condition
        

        if verbose:
            logtabs = gremlin.shared_state.logTabs(True)
            info = gremlin.joystick_handling.device_info_from_guid(self.device_guid)

        joy = gremlin.input_devices.JoystickProxy()[self.device_guid]
        if joy is None:
            # device not found - ignore
            return False
        




        if self.input_type == InputType.JoystickAxis:
            retval = False
            
            if self.condition.use_calibrated_data:
                # calibrated value
                value = gremlin.joystick_handling.get_curved_axis(self.device_guid, self.input_id)
                if verbose: 
                    raw = gremlin.joystick_handling.get_axis(self.device_guid, self.input_id)
                    syslog.info(f"{logtabs}condition input value (filtered): raw: {raw:0.3f} filtered: {value:0.3f}")
            else:
                # raw value
                value = gremlin.joystick_handling.get_axis(self.device_guid, self.input_id)
                if verbose: syslog.info(f"{logtabs}condition input value (raw): {value:0.3f}")
                #value = joy.axis(self.input_id).value
            r1 = self.condition.range[0]
            r2 = self.condition.range[1]
            in_range = gremlin.util.valueInRange(value, r1, r2)
            # if r1 > r2:
            #     r1,r2 = r2,r1
            # if r1 == r2:
            #     in_range = math.isclose(value, r1, 0.0001)
            # else:
            #     in_range = value >= r1 and value <= r2

            if self.condition.comparison in ["inside", "outside"]:
                retval = in_range if self.comparison == "inside" else not in_range
            if verbose: syslog.info(f"{logtabs}JoystickCondition: Axis range comparison: [{self.comparison}]: device {info.name} input: {self.input_id} range: {self.condition.range[0]:0.3f} to {self.condition.range[1]:0.3f} read value: {joy.axis(self.input_id).value:0.3f} return: {"OK" if retval else "FAILED"}")
            return retval
        
        elif self.input_type == InputType.JoystickButton:

            retval = False
            is_pressed = gremlin.joystick_handling.get_button(self.device_guid, self.input_id)
            if self.comparison == "pressed":
                retval = is_pressed
            elif self.comparison == "released":
                retval = not is_pressed
            else:
                syslog.error(f"Don't know how to handle joystick condition: {self.comparison}")
                return False
            if verbose: syslog.info(f"{logtabs}JoystickCondition: Button {self.comparison}: device {info.name} input: {self.input_id} pressed: {is_pressed} return: {"OK" if retval else "FAILED"}")
            return retval
            
        elif self.input_type == InputType.JoystickHat:
            direction = gremlin.joystick_handling.get_hat(self.device_guid, self.input_id)
            retval = direction == gremlin.util.hat_direction_to_tuple(self.comparison)
            if verbose: syslog.info(f"{logtabs}JoystickCondition: Hat Device {info.name} input: {self.input_id} comparison: {self.comparison} direction: {direction} return: {"OK" if retval else "FAILED"}")
            return retval
        else:
            syslog.warning(f"{logtabs}JoystickCondition: Invalid input_type {self.input_type} received")
            return False
        
    def condition_name(self)->str:
        info = gremlin.joystick_handling.device_info_from_guid(self.device_guid)
        match self.input_type:
            case InputType.JoystickButton:
                state = gremlin.joystick_handling.get_button(self.device_guid, self.input_id)
            case InputType.JoystickHat:
                state = gremlin.joystick_handling.get_hat(self.device_guid, self.input_id)
            case InputType.JoystickAxis:
                state = f"{gremlin.joystick_handling.get_axis(self.device_guid, self.input_id):0.3f}"
            case _:
                state = "N/A"
        logtabs = gremlin.shared_state.logTabs()
        return f"{logtabs}\tJoystickCondition: mode: {self.comparison} type: {gremlin.input_types.InputType.to_display_name(self.input_type)} input: {self.input_id} device: [{info.name if info else 'ID not found:' + str(self.device_guid)}] state: {state} "

    def __str__(self):
        return self.condition_name()

class VJoyCondition(AbstractCondition):

    """Condition verifying the state of a vJoy input.

    vJoy devices have three possible input types: axis, button, or hat and each
    have their corresponding possibly sates. An axis can be inside or outside
    a specific range. Buttons can be pressed or released and hats can be in
    one of eight possible directions.
    """

    def __init__(self, condition):
        """Creates a new instance.

        :param condition the condition to check against
        """
        super().__init__(condition.comparison)



        self.vjoy_id = condition.vjoy_id
        self.device_guid = None
        for dev in gremlin.joystick_handling.vjoy_devices():
            if dev.vjoy_id == self.vjoy_id:
                self.device_guid = dev.device_guid
                break
        self.input_type = condition.input_type
        self.input_id = condition.input_id
        
        self.input_index = condition.input_index if hasattr(condition,"input_index") else 0
        
        self.condition = condition

    def __call__(self, event, value, extra_data = None):
        # default call
        return self.process_event(event, value, extra_data)

    def process_event(self, event, value, extra_data = None):
        """Evaluates the condition using the condition and provided data.

        :param event raw event that caused the condition to be evaluated
        :param value the possibly modified value
        :return True if the condition is satisfied, False otherwise
        """

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_condition or config.verbose_mode_vjoy
        syslog = logging.getLogger("system")

        if verbose:
            logtabs = gremlin.shared_state.logTabs(True)

        if self.device_guid is None:
            syslog.warning(f"VJoyCondition: GUID for vJoy {self.vjoy_id} not found")
            return False
        joy = gremlin.input_devices.JoystickProxy()[self.device_guid]
        if joy is None:
            # device not found - ignore
            if verbose: syslog.warning(f"{logtabs}VjoyCondition: device not found: {self.device_guid} {gremlin.joystick_handling.device_name_from_guid(self.device_guid)}")
            return False
        
        
        if verbose:
            info = gremlin.joystick_handling.device_info_from_guid(self.device_guid)


        if self.input_type == InputType.JoystickAxis:
            retval = False
            current_value = joy.axis(self.input_id).value + 0.0
            r1 = self.condition.range[0]
            r2 = self.condition.range[1]
            in_range = gremlin.util.valueInRange(current_value, r1, r2)
            # if r1 > r2:
            #     r1,r2 = r2,r1
            # if r1 == r2:
            #     in_range = math.isclose(current_value, r1, abs_tol = 0.0001)
            # else:
            #     in_range = r1 <= current_value <= r2

            if self.comparison in ["inside", "outside"]:
                retval =  in_range if self.comparison == "inside" else not in_range
            if verbose: syslog.info(f"{logtabs}VjoyCondition: Axis {self.comparison}: device {info.name} input: {self.input_id} range: {self.condition.range[0]:0.3f} to {self.condition.range[1]:0.3f} read value: {joy.axis(self.input_id).value:0.3f} return: {"OK" if retval else "FAILED"}")
            return retval

            
        elif self.input_type == InputType.JoystickButton:
            retval = False
            is_pressed = gremlin.joystick_handling.get_button(self.device_guid, self.input_id)
            if self.comparison == "pressed":
                retval = is_pressed # true if the vjoy button is pressed
            elif self.comparison == "released":
                retval = not is_pressed # true if the vjoy button is not pressed
            else:
                syslog.error(f"{logtabs}VjoyCondition: Button {self.comparison} is not a valid condition for a button")
                
            if verbose: syslog.info(f"{logtabs}VjoyCondition: Button {self.comparison}: device {info.name} input: {self.input_id} return: {"OK" if retval else "FAILED"}")

            return retval
            
        elif self.input_type == InputType.JoystickHat:
            direction = gremlin.joystick_handling.get_hat(self.device_guid, self.input_id)
            retval =  direction == gremlin.util.hat_direction_to_tuple(self.comparison)
            if verbose: syslog.info(f"{logtabs}VjoyCondition: Hat Device {info.name} input: {self.input_id} comparison: {self.comparison} direction: {direction} return: {"OK" if retval else "FAILED"}")
        else:
            syslog.warning(f"VjoyCondition: Invalid input_type {self.input_type} received")
            return False

    def condition_name(self)->str:
        info = gremlin.joystick_handling.device_info_from_guid(self.device_guid)
        return f"VJoyCondition: mode: {self.comparison} type: {gremlin.input_types.InputType.to_display_name(self.input_type)} input: {self.input_id} device: {info.name if info else '(device not found)'} "


    def __str__(self):
        return self.condition_name()
    

class VirtualButtonCondition(AbstractCondition):
    ''' condition testing container virtual buttons '''
    def __init__(self, data):
        import gremlin.base_buttons
        super().__init__()
        if isinstance(data, gremlin.base_buttons.VirtualAxisButton):    
            # convert to the processing button
            self.virtual_button = AxisButton(data.lower_limit, data.upper_limit, data.direction)
        elif isinstance(data, gremlin.base_buttons.VirtualHatButton):
            self.virtual_button = HatButton(data.directions)
        else:
            self.virtual_button = data


    def __call__(self, event, value, extra_data : dict = None):
        # default call
        return self.process_event(event, value, extra_data)
    
    def process_event(self, event, value, extra_data : dict = None): 
        if extra_data is None:
            extra_data = {}
        extra_data["virtual_button"] = self.virtual_button
        result = self.virtual_button.process_event(event)
        if result:
            # convert the vent to a fake event button from a joystick axis event
            is_pressed = self.virtual_button.is_pressed
            value.current = is_pressed
            event.fake_button(is_pressed) # issue press or release depending
        return result
    
    def condition_name(self)->str:
        return f"VirtualButtonCondition: {str(self.virtual_button)}]"
    
    def __str__(self):
        return self.condition_name()

class ModeCondition(AbstractCondition):
    ''' condition verifying the runtime mode '''
    def __init__(self, mode):
        """Creates a new instance.

        :param comparison the comparison operation to perform when evaluated
        """
        super().__init__(mode)

    def __call__(self, event, value, extra_data = None):
        # default call
        return self.process_event(event, value, extra_data)
    
    def process_event(self, event, value, extra_data = None):
        return self.comparison == gremlin.shared_state.runtime_mode

    def condition_name(self)->str:
        return f"ModeCondition: mode: [{self.comparison}]"
        
    
    
class InputActionCondition(AbstractCondition):

    """Condition verifying the state of the triggering input itself. (ActionActivationCondition)

    This checks the state of the input that triggered the event in the first
    place.
    """

    def __init__(self, comparison):
        """Creates a new instance.

        :param comparison the comparison operation to perform when evaluated
        """
        super().__init__(comparison)

    def __call__(self, event, value, extra_data = None):
        # default call
        return self.process_event(event, value, extra_data)

    def process_event(self, event, value, extra_data = None):
        """Evaluates the condition using the condition and provided data.

        :param event raw event that caused the condition to be evaluated
        :param value the possibly modified value
        :return True if the condition is satisfied, False otherwise
        """

        verbose = gremlin.config.Configuration().verbose_mode_condition
        verbose = True

        

        syslog = logging.getLogger("system")
        retval = False
        is_pressed = event.is_pressed
        if not is_pressed:
            # not a pressed type input
            is_pressed = False
        if self.comparison == "pressed":
            retval = is_pressed
        elif self.comparison == "released":
            retval = not is_pressed
            if retval:
                # flip the event to a press event so the item executes
                event.is_pressed = True
                if value is not None:
                    value.is_pressed = True

        elif self.comparison == "always":
            retval = True
            event.is_pressed = True
            if value is not None:
                value.is_pressed = True

        if verbose: 
            logtabs = gremlin.shared_state.logTabs(True)
            syslog.info(f"{logtabs}InputActionCondition: comparison {self.comparison}: return: {'PASS' if retval else 'FAIL'}")
        return retval

    def condition_name(self)->str:
        return f"InputActionCondition: condition: {self.comparison}"

class VirtualButton(metaclass=ABCMeta):

    """Implements a button like interface."""

    
    # Next identifier ID to use
    next_id = 1

    def __init__(self):
        """Creates a new instance."""
        self._fsm = self._initialize_fsm()
        self._is_pressed = False
        self._identifier = VirtualButton.next_id
        VirtualButton.next_id += 1

    @property
    def identifier(self):
        return self._identifier

    def _initialize_fsm(self):
        """Initializes the state of the button FSM."""
        states = ["up", "down"]
        actions = ["press", "release"]
        transitions = {
            ("up", "press"): gremlin.fsm.Transition(self._press, "down"),
            ("up", "release"): gremlin.fsm.Transition(self._noop, "up"),
            ("down", "release"): gremlin.fsm.Transition(self._release, "up"),
            ("down", "press"): gremlin.fsm.Transition(self._noop, "down")
        }
        return gremlin.fsm.FiniteStateMachine("up", states, actions, transitions)

    def process_event(self, event):
        """Process the input event and updates the value as needed.

        :param event the input event that triggered this virtual button
        :return True if a state transition occurred, False otherwise
        """
        state_transition = self._do_process(event)
        return state_transition

    @abstractmethod
    def _do_process(self, event):
        """Implementation of the virtual button logic.

        This method has to be implemented in subclasses to provide the logic
        deciding when a state transition, i.e. button press or release
        occurs.

        :param event the input event that is used to decide on the state
        :return True if a state transition occurred, False otherwise
        """
        pass

    @property
    def is_pressed(self) -> bool:
        return self._is_pressed
    
    @is_pressed.setter
    def is_pressed(self, value : bool):
        self._is_pressed = value

    def _press(self):
        """Executes the "press" action."""
        self._is_pressed = True
        event = gremlin.event_handler.Event(
            InputType.VirtualButton,
            self._identifier,
            device_guid=dinput.GUID_Virtual,
            is_pressed=self._is_pressed,
            raw_value=self._is_pressed
        )
        eh = gremlin.event_handler.EventListener()
        eh.virtual_event.emit(event)
        return True

    def _release(self):
        """Executes the "release" action."""
        self._is_pressed = False
        event = gremlin.event_handler.Event(
            InputType.VirtualButton,
            self._identifier,
            device_guid=dinput.GUID_Virtual,
            is_pressed=self._is_pressed,
            raw_value=self._is_pressed
        )
        eh = gremlin.event_handler.EventListener()
        eh.virtual_event.emit(event)
        return True

    def _noop(self):
        """Performs no action."""
        return False

 

class AxisButton(VirtualButton):

    """Virtual button based around an axis."""

    def __init__(self, v1, v2, direction):
        """Creates a new instance.

        :param v1 lower axis value where the button range starts
        :param v2 upper axis value where the button range stops
        """
        super().__init__()
        if v1 > v2:
            v1, v2 = v2, v1
        self._min_range = v1
        self._max_range = v2
        self._direction = direction
        self._last_value = None
        self._pressed_issued = False # true if a press event was issued
        self.forced_activation = False
       


    def _do_process(self, event):
        """Implementation of the virtual button logic.

        :param event the input event that is used to decide on the state
        :return True if a state transition occurred, False otherwise
        """
        
        result = False # assume failed

        crossed = False
        direction = AxisButtonDirection.Anywhere
        v1 = self._min_range
        v2 = self._max_range
        last_value = self._last_value
        v = event.value
        is_pressed = False 

        if last_value is None:
            # first time 
            last_value = event.value
            last_inside_range = False
        else:
            # Check if we moved over the activation region between two
            # consecutive measurements
   
            
            if last_value < v1 and v >= v2:
                crossed = True
            elif last_value > v2 and v < v1:
                crossed = True
            

            # Determine direction in which the axis is moving
            if last_value < v:
                direction = AxisButtonDirection.Below
            elif last_value > v:
                direction = AxisButtonDirection.Above
            

        inside_range = gremlin.util.valueInRange(v, v1, v2)
        
        last_inside_range = gremlin.util.valueInRange(last_value, v1, v2)

        if self._pressed_issued and last_inside_range != inside_range:
            # button should be released because it was pressed before
            syslog.info(f"issue release {v:0.3f}")
            is_pressed = False
            result = True
            self._pressed_issued = False # reset press event

        if not result:
            self._last_value = v
            self.forced_activation = crossed

            if crossed or (inside_range and not last_inside_range):
                is_pressed = True
                result = True
    
            if direction != AxisButtonDirection.Anywhere and self._direction != AxisButtonDirection.Anywhere:
                # Ensure we can only press a button by moving in the desired
                # direction, however, allow releasing in any direction
                if inside_range and direction != self._direction:
                    pass
                elif crossed and direction != self._direction:
                    pass
                else:
                    result = False
                    is_pressed = False

        if result and is_pressed:
            syslog.info(f"issue press: {v:0.3f}")
            self._pressed_issued = True

        self.is_pressed = is_pressed
        
        verbose = gremlin.config.Configuration().verbose_mode_condition
        if verbose: syslog.info(f"Virtual button: range: {v1:0.3f} {v2:0.3f} crossed: {crossed} in range: {inside_range} last value: {last_value:0.3f} current value: {v:0.3f} pressed: {is_pressed} direction: {direction} result: {'PASS' if result else 'FAIL'}")
        return result
    
    def __str__(self):
        return f"AxisButton: range: {self._min_range:0.3f} {self._max_range:0.3f}"

        
class HatButton(VirtualButton):

    """Virtual button based around a hat."""

    def __init__(self, directions : list):
        """Creates a new instance.

        :param directions hat directions used with this button
        """
        super().__init__()
        self._directions = directions

    def _do_process(self, event):
        """Implementation of the virtual button logic.

        :param event the input event that is used to decide on the state
        :return True if a state transition occurred, False otherwise
        """
        
        self.is_pressed = gremlin.util.hat_tuple_to_direction(event.value) in self._directions
        return True
    
    def __str__(self):
        return f"AxisButton: directions: {self._directions}"
