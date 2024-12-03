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

from __future__ import annotations

from abc import abstractmethod, ABCMeta
from collections import namedtuple
import copy
import logging
import time

import gremlin.base_buttons
import gremlin.base_classes
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.actions
import gremlin.error
import gremlin.input_types
import gremlin.plugin_manager
import gremlin.base_conditions
import gremlin.shared_state
import anytree
from enum import Enum,auto

from gremlin.singleton_decorator import SingletonDecorator


class ExecutionGraphNodeType(Enum):
    ''' types of tree nodes in an execution graph '''
    Root = auto()
    Container = auto()
    ActionSet = auto()
    Action = auto()
    Mode = auto() 
    

class ExecutionGraphNode(anytree.NodeMixin):
    ''' tree node '''
    def __init__(self, node_type : ExecutionGraphNodeType):
        super().__init__()

        self.action : gremlin.base_profile.AbstractAction = None # holds any action at this node
        self.functors : list[gremlin.base_profile.AbstractFunctor] = [] # holds the functors to execute in this node
        self.sequence = [] # list of sequence codes (action, condition) for the functor by index
        self.container : gremlin.base_profile.AbstractContainer = None  # holds the container object
        self.priority : int = 0 # execution priority of nodes at the same tree level
        self.nodeType : ExecutionGraphNodeType = node_type
        self.mode : str = None


    def __str__(self):
        msg = self.nodeType.name
        stub = ""
        match self.nodeType:
            case ExecutionGraphNodeType.Root:
                pass
            case ExecutionGraphNodeType.Container:
                container = self.container
                device_name = container.get_device_name()
                stub = f"{self.container.name} Device: {device_name} input {container.input_display_name}"
            case ExecutionGraphNodeType.ActionSet:
                pass
            case ExecutionGraphNodeType.Action:
                stub = self.action.name
            case ExecutionGraphNodeType.Mode:
                stub = self.mode
        return f"{msg} {stub}"
                



@SingletonDecorator
class ExecutionContext():
    ''' holds the current execution context '''
    def __init__(self):
        self.root = ExecutionGraphNode(ExecutionGraphNodeType.Root) # root node

    def reset(self):
        self.root = ExecutionGraphNode(ExecutionGraphNodeType.Root) # root node

    def find(self, item):
        ''' looks for a container, action or action set in the execution tree node '''
        for node in anytree.PreOrderIter(self.root):
            if node.container == item or node.action == item or node.action_set == item or item in node.functors:
                return node
            
        return None
            

    def dump(self):
        # dumps the execution tree
        syslog = logging.getLogger("system")
        syslog.info(f"Execution Tree:")

        for pre, fill, node in anytree.RenderTree(self.root, style=anytree.AsciiStyle()):
            syslog.info(f"{pre}{str(node)}")
        



class ContainerCallback:

    """Callback object that can perform the actions associated with an input.

    The object uses the concept of a execution graph to handle conditional
    and chained actions.
    """

    def __init__(self, container, parent):
        """Creates a new instance based according to the given input item.

        :param container the container instance for which to build th
            execution graph base callback
        """
        if parent is None:
            ec = ExecutionContext()
            parent = ec.root
        self.execution_graph = ContainerExecutionGraph(container, parent)

    def __call__(self, event):
        """Executes the callback based on the event's content.

        Creates a Value object from the event and passes the two through the
        execution graph until every entry has run or it is aborted.
        """
        if event.is_axis:
            input_type = event.event_type
            match input_type:
                case InputType.JoystickAxis:
                    value = gremlin.actions.Value(event.curve_value)
                case InputType.Midi:
                    value = gremlin.actions.Value(event.value)
                case InputType.OpenSoundControl:
                    value = gremlin.actions.Value(event.value)
                case _:
                    # nothing to do
                    return 


        elif event.event_type == InputType.JoystickHat:
            value = gremlin.actions.Value(event.value)
        elif event.event_type in [
            InputType.JoystickButton,
            InputType.Midi,
            InputType.OpenSoundControl,
            InputType.Keyboard,
            InputType.VirtualButton
        ]:
            value = gremlin.actions.Value(event.is_pressed)
        else:
            raise gremlin.error.GremlinError("Invalid event type")

        # Containers representing a virtual button get their individual
        # value instance, all others share one to propagate changes across
        shared_value = copy.deepcopy(value)

        if event == InputType.VirtualButton:
            # TODO: remove this at a future stage
            logging.getLogger("system").error(
                "Virtual button code path being used"
            )
        else:
            self.execution_graph.process_event(event, shared_value)


class VirtualButtonCallback:

    """VirtualButton event based callback class."""

    def __init__(self, container, parent = None):
        """Creates a new instance.

        :param container the container to execute when called
        """
        self._execution_graph = ContainerExecutionGraph(container, parent)

    def __call__(self, event, value = None):
        """Executes the container's content when called.

        :param event the event triggering the callback
        """
        if value is None:
            value = gremlin.actions.Value(event.is_pressed)
        self._execution_graph.process_event(
            event,
            value
        )


class VirtualButtonProcess:

    """Callback that is responsible for emitting press and release events
    for a virtual button."""

    def __init__(self, data):
        """Creates a new instance for the given container.

        :param container the container using a virtual button configuration
        """
        self.virtual_button = None

        if isinstance(data, gremlin.base_buttons.VirtualAxisButton):
            self.virtual_button = gremlin.actions.AxisButton(
                data.lower_limit,
                data.upper_limit,
                data.direction
            )
        elif isinstance(data, gremlin.base_buttons.VirtualHatButton):
            self.virtual_button = gremlin.actions.HatButton(
                data.directions
            )
        else:
            raise gremlin.error.GremlinError("Invalid virtual button data provided")

    def __call__(self, event, value = None):
        """Processes the provided event through the virtual button instance.

        :param event the input event being processed
        """
        self.virtual_button.process_event(event)


class AbstractExecutionGraph(metaclass=ABCMeta):

    """Abstract base class for all execution graph type classes.

    An execution graph consists of nodes which represent actions to execute and
    links which are transitions between nodes. Each node's execution returns
    a boolean value, indicating success or failure. The links allow skipping
    of nodes based on the outcome of a node's execution.

    When there is no link for a given node and outcome combination the
    graph terminates.
    """

    def __init__(self, instance, parent = None):
        """Creates a new execution graph based on the provided data.

        :param instance the object to use in order to generate the graph
        """
        self.functors = []
        self.transitions = {}
        self.current_index = 0
        ec = ExecutionContext()
        if parent is None:
            parent = ec.root
        self._build_graph(instance, parent)

                                                      
    

    def process_event(self, event, value):
        """Executes the graph with the provided data.

        :param event the raw event that caused the execution of this graph
        :param value the possibly modified value extracted from the event
        """
        

        # Processing an event twice is needed when a virtual axis button has
        # "jumped" over it's activation region without triggering it. Once
        # this is detected the "press" event is sent and the second run ensures
        # a "release" event is sent.
        process_again = False

        
        verbose = gremlin.config.Configuration().verbose_mode_condition
        syslog = logging.getLogger("system")
        
        if verbose: syslog.info (f"Execution plan:")
        functor_names = []
        for index, functor in enumerate(self.functors):
            functor_names.append(type(functor).__name__)
            if hasattr(functor, "condition_name"):
                condition_name = functor.condition_name()
            else:
                condition_name = ""
            if verbose: syslog.info(f"\t{index} -> {functor_names[index]} {condition_name}")
        
        if verbose:
            # output the transition plan
            syslog.info("Transition plan:")
            for key, next_index in self.transitions.items():
                syslog.info(f"\t{key} -> {next_index}")
        

        if verbose: syslog.info (f"Execution start:")
        while self.current_index is not None and len(self.functors) > 0:
            index = self.current_index
            functor = self.functors[index]
            if isinstance(functor, gremlin.actions.ActivationCondition):
                if verbose: syslog.info(f"\t\tIndex {index} -> executing condition {functor_names[index]} {functor.condition_name()}")
                result = functor.process_event(event, value)
                if verbose: syslog.info (f"\t\t\t{index} -> condition result: {result}")
                if result is None or not result:
                    # condition is not met
                    if verbose: syslog.info (f"\t\t\t{index} -> condition failed")
                    # get the next item
            else:
                if verbose: syslog.info(f"\t\t{index} -> executing action {functor_names[index]}")
                result = functor.process_event(event, value)
                if verbose: syslog.info (f"\t\t\t{index} -> action result: {result}")
                if result is None or not result:
                    return False
                #     logging.getLogger("system").warning(f"Process event returned no data or FALSE - functor: {type(functor).__name__}")

                if isinstance(functor, gremlin.actions.AxisButton):
                    process_again = functor.forced_activation

            self.current_index = self.transitions.get((index, result),None)
            if verbose: syslog.info (f"\t\tNext step: {(index, result)} -> {self.current_index}")

        self.current_index = 0

        if process_again:
            time.sleep(0.05)
            self.process_event(event, value)
        return True

    @abstractmethod
    def _build_graph(self, instance, parent_node = None):
        """Builds the graph structure based on the given object's content.

        :param instance the object to use in order to generate the graph
        """
        pass

    def _convert_condition(self, condition):
        ''' converts a base condition to an action condition '''
        if isinstance(condition, gremlin.base_conditions.KeyboardCondition):
                return gremlin.actions.KeyboardCondition(
                        condition.scan_code,
                        condition.is_extended,
                        condition.comparison
                    )
                
        elif isinstance(condition, gremlin.base_conditions.JoystickCondition):
            return gremlin.actions.JoystickCondition(condition)
            
        elif isinstance(condition, gremlin.base_conditions.VJoyCondition):
            return gremlin.actions.VJoyCondition(condition)
            
        elif isinstance(condition, gremlin.base_conditions.InputActionCondition):
            return gremlin.actions.InputActionCondition(condition.comparison)
        
        assert False, f"Invalid base condition to convert: {type(condition).__name__}"
        

    def _create_activation_condition(self, activation_condition, target):
        """Creates activation condition objects base on the given data.

        :param activation_condition data about activation condition to be
            used in order to generate executable nodes
        """
        conditions = []
        for condition in activation_condition.conditions:
            if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                for sub_condition in condition.conditions:
                    conditions.append(self._convert_condition(sub_condition))
            else:
                conditions.append(self._convert_condition(condition))

        return gremlin.actions.ActivationCondition(
            conditions,
            activation_condition.rule,
            target
        )

    def _contains_input_action_condition(self, activation_condition):
        """Returns whether or not an input action condition is present.

        :param activation_condition condition data to check for the existence
            of an input action
        :return return True if an input action is present, False otherwise
        """
        if activation_condition:
            return any([
                isinstance(cond, gremlin.base_conditions.InputActionCondition)
                for cond in activation_condition.conditions
            ])
        else:
            return False

    def _create_transitions(self, sequence):
        """Creates node transition based on the node type sequence information.

        :param sequence the sequence of nodes
        """
        seq_count = len(sequence)
        self.transitions = {}
        for i, seq in enumerate(sequence):
            if seq != "Action":
                # On success, transition to the next node of any type in line
                self.transitions[(i, True)] = i+1 if i+1 < seq_count else None
                offset = i + 1
                # On failure, transition to the condition node after the
                # next action node
                while offset < seq_count:
                    if sequence[offset] == "Action":
                        if offset+1 < seq_count:
                            self.transitions[(i, False)] = offset+1
                            break
                    offset += 1
            elif seq == "Action" and i+1 < seq_count:
                # Transition to the next node irrespective of failure or success
                self.transitions[(i, True)] = i+1
                self.transitions[(i, False)] = i+1

        

class ContainerExecutionGraph(AbstractExecutionGraph):

    """Execution graph for the content of a single container."""

    def __init__(self, container, parent = None):
        """Creates a new instance for a specific container.

        :param container the container data from which to generate the
            execution graph
        """
        assert isinstance(container, gremlin.base_profile.AbstractContainer)
        super().__init__(container, parent)

    def _build_graph(self, container, parent = None):
        """Builds the graph structure based on the container's content.

        :param container data to use in order to generate the graph
        """


        verbose = gremlin.config.Configuration().verbose_mode_details

        sequence = []


        # Add virtual button transform as the first functor if present
        # if container.virtual_button:
        #     self.functors.append(self._create_virtual_button(container))
        #     sequence.append("Condition")

        # tree node for this container
        node = ExecutionGraphNode(ExecutionGraphNodeType.Container)
        node.container = container
        node.parent = parent


        # If container based conditions exist add them before any actions
        if container.has_conditions: 
            functor = self._create_activation_condition(container.activation_container_condition, container)
            self.functors.append(functor)
            node.functors.append(functor)
            sequence.append("ContainerCondition")
            node.sequence.append("ContainerCondition")

        # if container.has_action_conditions:
        #     self.functors.append(self._create_activation_condition(container.activation_condition, container))
        #     sequence.append("ActionCondition")

        functor = container.functor(container, node)
        node.functors.append(functor)
        
        if verbose:
            logging.getLogger("system").info(f"Enable container functor: {type(functor).__name__}")

        extra_inputs = functor.latch_extra_inputs()
        if extra_inputs:
            # register the extra inputs for this functor
            eh = gremlin.event_handler.EventHandler()
            mode = container.profile_mode
            for device_guid, input_type, input_id in extra_inputs:
                
                event = gremlin.event_handler.Event(
                        event_type= input_type,
                        device_guid = device_guid,
                        identifier= input_id
                )
                eh.add_latched_functor(device_guid, mode, event, functor)
                
        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_plugins.register_functor(functor)
        self.functors.append(functor)
        sequence.append("Action")

        node.functors.append(functor)
        node.sequence.append("Action")

        self._create_transitions(sequence)
        

class ActionSetExecutionGraph(AbstractExecutionGraph):

    """Execution graph for the content of a set of actions."""

    comparison_map = {
        (True, True): "always",
        (True, False): "pressed",
        (False, True): "released"
    }

    def __init__(self, action_set, parent = None):
        """Creates a new instance for a specific set of actions.

        :param action_set the set of actions from which to generate the
            execution graph
        """
        super().__init__(action_set, parent)

    def _build_graph(self, action_set, parent = None):
        """Builds the graph structure based on the content of the action set.

        :param action_set data to use in order to generate the graph
        """
        # The action set shouldn't be empty, but in case this happens
        # nonetheless we abort
        if len(action_set) == 0:
            return
        
        verbose = gremlin.config.Configuration().verbose_mode_details

        sequence = []

        add_default_activation = True

        nodes = {} # list of tree nodes at this level created for each action in the actions sets
        

        # Reorder action set entries such that if any remap action is
        # present it is executed last (after a curving action for example) (unless it's a mode switch action - mode switching must happen last because it changes the action list)
        ordered_action_set = []
        if verbose:
            logging.getLogger("system").info("Ordering action sets:")
        for action in action_set:


            action_set_node = ExecutionGraphNode(ExecutionGraphNodeType.ActionSet)
            action_set_node.parent = parent

            # if not isinstance(action, action_plugins.remap.Remap):
            priority = 0
            if hasattr(action, "priority"):
                priority = action.priority
            ordered_action_set.append((priority, action))
            if verbose:
                logging.getLogger("system").info(f"\tadding action: {type(action)} priority: {priority} data: {str(action)}" )

            node = ExecutionGraphNode(ExecutionGraphNodeType.Action)
            node.parent = action_set_node
            node.action = action
            node.priority = priority
            nodes[action] = node


        if len(ordered_action_set) > 1:
            ordered_action_set.sort(key = lambda x: x[0])
        ordered_action_set = [x[1] for x in ordered_action_set]


        if verbose:
            logging.getLogger("system").info("Action order:")
            for index, action in enumerate(ordered_action_set):
                input_item = action.input_item # get_input_item()
                input_id = input_item.input_id
                input_stub = str(input_id)
                logging.getLogger("system").info(f"\t{index}: input type: {input_item.input_type} {input_stub} action: {type(action)}  data: {str(action)} ")


        # Create functors
        for action in ordered_action_set:
            # Create conditions for each action if needed
            if action.has_conditions:
                functor = self._create_activation_condition(
                        action.activation_condition,
                        action
                    )
                self.functors.append(functor)
                sequence.append("Condition")
                nodes[action].functors.append(functor)

            # Create default activation condition if needed
            has_input_action = self._contains_input_action_condition(
                action.activation_condition
            )

            if add_default_activation and not has_input_action:
                condition = gremlin.base_conditions.InputActionCondition()
                condition.comparison = ActionSetExecutionGraph.comparison_map[
                    action.default_button_activation
                ]
                activation_condition = gremlin.base_conditions.ActivationCondition(
                    [condition],
                    gremlin.base_conditions.ActivationRule.All
                )
                functor = self._create_activation_condition(activation_condition, action)
                self.functors.append(functor)
                sequence.append("Condition")
                nodes[action].functors.append(functor)
                nodes[action].sequence.append("Condition")
                

            # Create action functor
            functor : gremlin.base_conditions.AbstractFunctor = action.functor(action, nodes[action])
            extra_inputs = functor.latch_extra_inputs()
            if extra_inputs:
                # register the extra inputs for this functor
                eh = gremlin.event_handler.EventHandler()
                # add_latched_functor(self, device_guid, mode, event, functor):
                mode = action.profile_mode
                for device_guid, input_type, input_id in extra_inputs:
                    
                    event = gremlin.event_handler.Event(
                            event_type= input_type,
                            device_guid = device_guid,
                            identifier= input_id
                    )
                    eh.add_latched_functor(device_guid, mode, event, functor)
                

            action.setEnabled(True)
            self.functors.append(functor)
            sequence.append("Action")
            nodes[action].functors.append(functor)
            nodes[action].sequence.append("Action")


        self._create_transitions(sequence)
