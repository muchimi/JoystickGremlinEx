# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - Joystick Gremlin Ex is (C) EMCS 2025 
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
import gremlin.gated_handler
from gremlin.input_types import InputType
import gremlin.actions
import gremlin.error
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.plugin_manager
import gremlin.base_conditions
import gremlin.shared_state
import anytree
from enum import Enum,auto

from gremlin.singleton_decorator import SingletonDecorator
from PySide6 import QtCore
from threading import Event

syslog = logging.getLogger("system")

class ExecutionGraphNodeType(Enum):
    ''' types of tree nodes in an execution graph '''
    Root = auto()
    Container = auto()
    ActionSet = auto()
    Action = auto()
    Mode = auto() 
    Device = auto()
    InputItem = auto()
    Gate = auto() # gate type for gated data
    Range = auto() # range type for gated data
    Condition = auto() # node is a condition (has a list of activation conditions)
    ActivationCondition = auto() # node is an activation condition (has a functor to evaluate)
    Functor = auto() # node is a functor node 
    
class ExecutionModeNode(anytree.NodeMixin):
    ''' holds a mode node '''
    def __init__(self, mode: str = None):
        super().__init__()
        self.mode = mode # mode name
        self._display = None # display name for the mode

    def _update(self):
        display = ""
        node = self
        while node.mode:
            if display:
                display = f"/{node.mode}{display}"
            else:
                display = f"/{node.mode}"
            node = node.parent
        self._display = display
        
    @property
    def display(self):
        if not self._display and self.mode:
            self._update()
        return self._display

        

class ExecutionGraphNode(anytree.NodeMixin):
    ''' execution tree node '''
    def __init__(self, node_type : ExecutionGraphNodeType):
        import gremlin.util
        super().__init__()
        self.id = gremlin.util.get_guid() # node id, will be the container ID or the action ID for container or action nodes
        self.action : gremlin.base_profile.AbstractAction = None # holds any action at this node
        self.functors = [] # list of functors
        self.functor = None # holds the functor to execute for this node (functor must have process_events(event, value) as a method)
        self.sequence = [] # list of sequence codes (action, condition) for the functor by index
        self.container : gremlin.base_profile.AbstractContainer = None  # holds the container object
        self.condition : gremlin.actions.ActivationCondition = None # holds the condition if a condition node
        self.priority : int = 0 # execution priority of nodes at the same tree level
        self.nodeType : ExecutionGraphNodeType = node_type
        self.action_set: list[gremlin.base_profile.AbstractAction] = [] # list of actions
        self.mode : str = None
        self.input_type : InputType = InputType.NotSet
        self.device = None # mapped device if a device node
        self.input_item = None
        self.gate = None # holds the gate info
        self.range = None # holds the range info
        self.description = ""

    def __str__(self):
        msg = self.nodeType.name
        stub = ""
        match self.nodeType:
            case ExecutionGraphNodeType.Root:
                pass
            case ExecutionGraphNodeType.Container:
                container = self.container
                device_name = container.get_device_name()
                condition : gremlin.base_profile.AbstractCondition = container.activation_container_condition
                condition_stub = f"True id: {condition.id}" if condition else ""
                stub = f"Container: {self.container.name} Device: {device_name} Input {container.input_display_name}  Condition: {condition_stub}"

            case ExecutionGraphNodeType.ActionSet:
                stub = f"Action Count: {len(self.action_set)}"
            case ExecutionGraphNodeType.Action:
                condition : gremlin.base_profile.AbstractCondition = self.action.activation_condition
                condition_stub = f"True id: {condition.id}" if condition else ""
                stub = f"Action: {self.action.name} Condition: {condition_stub}"
            case ExecutionGraphNodeType.Mode:
                stub = f"Mode: {self.mode}"
            case ExecutionGraphNodeType.InputItem:
                stub = f"InputItem: {self.input_item.display_name}"
            case ExecutionGraphNodeType.Device:
                stub = self.device.name
            case ExecutionGraphNodeType.Gate:
                stub = str(self.gate)
            case ExecutionGraphNodeType.Range:
                stub = str(self.range)
            case ExecutionGraphNodeType.Condition:
                stub = str(self.condition)
            case ExecutionGraphNodeType.ActivationCondition:
                stub = str(self.condition)
            case _:
                stub = f"Don't know how to display type: {self.nodeType}"
        return f"{msg}: {self.description} {stub}  (node {self.id})"
                

class ExecutionContextInputData():
    ''' holds an input item configuration '''
    def __init__(self, input_item, mode : str, modes: list):
        self.input_item = input_item # the input item
        self.mode = mode # mode the input is referenced by
        self.modes = modes # modes referencing this input item



@SingletonDecorator
class ExecutionContext():
    ''' holds the current execution context '''
    def __init__(self):
       
       el = gremlin.event_handler.EventListener()
       el.edit_mode_changed.connect(self.reset) # reload data on mode changes
       el.profile_start.connect(self._profile_start) # reload data on profile start
       el.profile_changed.connect(self.reset) # reload data on profile change
       el.profile_modes_changed.connect(self.reset) # modes changed
       self._mode_tree = None
       self.root = None
       self._last_hash = None
       self._condition_map = {} # map of node ID to conditions that have conditions
       self._functor_map = {} # map of node ID to action nodes to execute for condition checking

    @property
    def functor_map(self) -> dict:
        ''' map of container condition functors '''
        return self._functor_map
    

    @property
    def condition_map(self) -> dict:
        ''' map of container condition functors '''
        return self._condition_map
    

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
        
            

    def reset(self):
        ''' reloads the execution context to capture changes '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_exec
        if verbose: syslog.info("CONTEXT: reload")
        if not gremlin.shared_state.current_profile:
            # no profile loaded
            return 
        self.root = ExecutionGraphNode(ExecutionGraphNodeType.Root) # root node
        

        profile = gremlin.shared_state.current_profile

        # detect changes
        profile_hash = profile.getMappingHash()
        rebuild = self._last_hash is None or self._last_hash != profile_hash

        # builds the tree
        if rebuild:
            self._last_hash = profile_hash
            self._rebuild()
            
            

    def _rebuild(self):
        
        verbose = gremlin.config.Configuration().verbose_mode_exec
        if verbose: syslog.info("CONTEXT: rebuild")
        self._functor_map = {} # quick access to functor IDs
        self._build_execution_tree(self.root)

        

        tree = gremlin.shared_state.current_profile.build_inheritance_tree()
        root_mode = ExecutionModeNode()
        self._walk_mode_tree(root_mode, tree)
        self._mode_tree = root_mode

        # tell the ui the execution context changed
        el = gremlin.event_handler.EventListener()
        el.execution_context_changed.emit()

       
        if verbose:
            self.dump()
            

    def _profile_start(self):
        ''' profile start - rebuild the execution tree '''
        verbose = gremlin.config.Configuration().verbose_mode_exec
        if verbose: syslog.info("CONTEXT: rebuild on profile start")
        self._rebuild()


    def _walk_mode_tree(self, node, branch):
        ''' walks a mode tree manually to build the mode hierarchy (recursive)'''
        for mode, sub_branch in branch.items():
            if not mode:
                # must but be valid
                continue
            child = ExecutionModeNode(mode)
            child.parent = node
            self._walk_mode_tree(child, sub_branch)

    @property
    def modeTree(self):
        ''' gets the mode tree '''
        if not self._mode_tree:
            self.reset()
        return self._mode_tree
    
    def searchModeTree(self, mode : str) -> ExecutionModeNode:
        ''' find the node for a mode in the mode tree '''
        # syslog = logging.getLogger("system")
        try:
            nodes = anytree.search.findall_by_attr(self.modeTree, mode, name="mode")
        except Exception as err:
            syslog.warning(f"SearchModeTree: tree exception: {err}")
            nodes = None
        if nodes:
            if len(nodes) > 1:
                syslog.warning(f"CONTEXT: More than one mode named {mode} detected - returning the first one")
                for node in nodes:
                    syslog.warning(f"\t{node.display} [{node.mode}]")
            return nodes[0]
        return None
    
    
    def getModeNames(self, as_tuple = False, include_current = True) -> list:
        ''' gets the mode names as a list of tuples
            as_tuple: returns as a tuple of data (mode_key, display_name)

            include_current: if true, includes the current mode in the list, false excludes it which may cause an empty list to be returned

            '''
        
        current_mode = gremlin.shared_state.edit_mode # current edit mode
        mode_tree = self.modeTree
        if not mode_tree:
            return []
        if as_tuple:
            if include_current:
                return [(node.mode, node.display) for node in anytree.PreOrderIter(mode_tree) if node.mode]
            return [(node.mode, node.display) for node in anytree.PreOrderIter(mode_tree) if node.mode and node.mode != current_mode]

        if include_current:       
            return [node.mode for node in anytree.PreOrderIter(mode_tree) if node.mode]
        return [node.mode for node in anytree.PreOrderIter(mode_tree) if node.mode if node.mode != current_mode]


        
    def getNode(self, id):
        ''' gets the node matching the corresponding id - nodes that have an ID are container and action nodes '''
        node = next((node for node in anytree.PreOrderIter(self.root) if node.id == id), None)
        return node
    
    def getNodeActivationConditions(self, id) -> list:
        ''' gets a list of activation condition nodes for a given node ID (container or action)'''
        activation_conditions = []
        verbose = gremlin.config.Configuration().verbose_mode_exec
        node = self.getNode(id)
        if node:
            # traverse the tree and find all conditions until the next action or container
            for n in node.descendants:
                match n.nodeType:
                    case ExecutionGraphNodeType.ActivationCondition:
                        activation_conditions.append(n)
                    case ExecutionGraphNodeType.Condition:
                        pass
                        #activation_conditions.append(n)
                    case ExecutionGraphNodeType.Container:
                        break
                    case ExecutionGraphNodeType.Action:
                        break
                
            #activation_conditions = [n for n in node.descendants if n.nodeType == ExecutionGraphNodeType.ActivationCondition]
            if verbose:
                if activation_conditions:
                    syslog.info(f"Activation condition functors for node {node.description}  (node {node.id}):")
                    for n in activation_conditions:
                        syslog.info(f"\tFunctor node: {n.description}  (node {n.id})")

        return activation_conditions


    
    def getModes(self) -> list:
        ''' returns the list of defined modes in the execution tree '''
        return [node.mode for node in anytree.PreOrderIter(self.root) if node.nodeType == ExecutionGraphNodeType.Mode and node.mode]
        
    
    def getCallbacks(self, callbacks, key, mode):
        callback_list = []
        verbose = gremlin.config.Configuration().verbose_mode_inputs
        # syslog = logging.getLogger("system")
        node = self.searchModeTree(mode)
            
        if node:
            # starting point
            while not callback_list and node is not None:
                mode = node.mode
                if not mode:
                    # reached the top level
                    break
                if verbose: syslog.info(f"CONTEXT: Search callbacks for mode : {mode} {key}")
                callback_list = callbacks.get(mode, {}).get(key, [])
                if callback_list:
                    if verbose: syslog.info(f"\tFound callbacks for mode : {mode} key: {key}")
                    break
                # bump to parent node if not found
                node = node.parent
                if verbose: syslog.info(f"\tNot found, using parent node: {node.name}")
        return callback_list

    def getModeHierarchy(self, mode):
        ''' gets a list of parent modes for the given mode '''
        modes = []

        nodes = anytree.search.findall_by_attr(self.modeTree, mode, "mode")
        for node in nodes:
            while node.mode:
                modes.append(node.mode)
                node = node.parent
            break # use only the first node returned by the search

        return modes

    def getMappedInputs(self, input_type : InputType) -> list[ExecutionContextInputData]:
        ''' gets a list of all inputs in the execution tree of that current type that have a container defined'''
        input_items = []
        node: ExecutionGraphNode
        for node in anytree.PreOrderIter(self.root):
            if node.nodeType == ExecutionGraphNodeType.InputItem:
                input_item = node.input_item
                if input_item.input_type == input_type:
                    mode = node.mode
                    modes = self.getModeHierarchy(mode)
                    item = ExecutionContextInputData(input_item, mode, modes)
                    input_items.append(item)

        return input_items
    
    def deviceHasMappings(self, device_guid):
        ''' true if a device has inputs defined '''
        node: ExecutionGraphNode
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if self.root is None:
            self._rebuild()
        if self.root:
            for node in anytree.PreOrderIter(self.root):
                if node.nodeType == ExecutionGraphNodeType.Device and node.device.device_id == device_guid:
                    # found the device
                    if anytree.find(node, filter_ = lambda n: n.nodeType == ExecutionGraphNodeType.Container):
                        return True
        return False

    

    def find(self, item):
        ''' looks for a container, action or action set in the execution tree node '''
        for node in anytree.PreOrderIter(self.root):
            if node.container == item or node.action == item or node.action_set == item or item in node.functors:
                return node
            
        return None
    
    def findActionPlugin(self, plugin_name):
        ''' gets a list of nodes that have a specific class
         
        :param plugin_name: matches the name property of an action plugin
        '''
        nodes = []
        if self.root is None:
            self.reset()
        for node in anytree.PreOrderIter(self.root):
            if node.nodeType == ExecutionGraphNodeType.Action:
                if node.action.name == plugin_name:
                    nodes.append(node)

        return nodes
    
    def findInputItem(self, device_guid, input_id):
        ''' finds the input item corresponding to the device and id specififed, None if not found '''
        ''' true if the execution tree contains mappings with input types of the specified type  '''
        node : ExecutionGraphNode
        for node in anytree.PreOrderIter(self.root):
            if node.nodeType == ExecutionGraphNodeType.InputItem:
                input_item = node.input_item
                if input_item.device_guid == device_guid and input_item.input_id == input_id:
                    return input_item
                
        return None

    def hasInputType(self, input_type):
        ''' true if the execution tree contains mappings with input types of the specified type  '''
        node : ExecutionGraphNode
        for node in anytree.PreOrderIter(self.root):
            if node.nodeType == ExecutionGraphNodeType.InputItem:
                input_item = node.input_item
                if input_item.input_type == input_type:
                    return True
        return False

    def dump(self, exclude_empty = True):
        self.dumpExecTree(exclude_empty)
        self.dumpModeTree()    

    def dumpExecTree(self, exclude_empty = True):
        # dumps the execution tree
        # syslog = logging.getLogger("system")
        syslog.info(f"Execution Tree:")
        if self.root:
            for pre, fill, node in anytree.RenderTree(self.root, style=anytree.AsciiStyle()):
                if exclude_empty:
                    if node.nodeType == ExecutionGraphNodeType.InputItem:
                        if node.is_leaf:
                            continue # skip blank node
                syslog.info(f"{pre}{str(node)}")

    def dumpActive(self):
        ''' dumps active execution nodes ONLY'''
        # syslog = logging.getLogger("system")
        syslog.info(f"Execution Tree:")
        if self.root:
            for pre, fill, node in anytree.RenderTree(self.root, style=anytree.AsciiStyle()):
                if anytree.search.findall_by_attr(node, ExecutionGraphNodeType.Action, "nodeType"):
                    syslog.info(f"{pre}{str(node)}")
        

    def dumpModeTree(self):
        # syslog = logging.getLogger("system")
        syslog.info(f"Mode Tree:")
        if self.modeTree:
            for pre, fill, node in anytree.RenderTree(self.modeTree, style=anytree.AsciiStyle()):
                syslog.info(f"{pre}{node.display} [{node.mode}]")



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

    def _create_activation_condition(self, activation_condition, target, is_container_condition = False):
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
            target,
            is_container_condition =is_container_condition
        )        

    def _get_condition_node(self, container, parent):
        ''' gets a condition node'''
        condition_node = ExecutionGraphNode(ExecutionGraphNodeType.Condition)
        condition_node.container = container
        condition_node.parent = parent
        condition_node.description = f"Condition node: {str(container)}"
        conditions = None
        if isinstance(container, gremlin.base_profile.AbstractContainer):
            conditions = container.activation_container_condition.conditions
            condition_node.condition =  container.activation_container_condition
        elif isinstance(container, gremlin.base_profile.AbstractAction):
            if container.activation_condition:
                conditions = container.activation_condition.conditions
            condition_node.condition = container.activation_condition
        else:
            assert False,f"don't know how to handle: {container.__class__.__name__}"

        node = condition_node # node to return
        if conditions:
            for condition in conditions:
                sub_node = ExecutionGraphNode(ExecutionGraphNodeType.ActivationCondition)
                sub_node.condition = condition
                sub_node.description =  f"ActivationCondition node: {str(condition)}"
                sub_node.parent = node
                sub_node.functor = self._convert_condition(condition)
                node = sub_node
        return node
    
    def _get_functor_node(self, container, functor, parent):
        ''' gets a functor node for a given functor '''
        functor_node = ExecutionGraphNode(ExecutionGraphNodeType.Functor)
        functor_node.container = container
        functor_node.functors = [functor]
        functor_node.parent = parent

        functor_node.condition = container.activation_container_condition
        return functor_node
    
    def _register_condition(self, parent_node, node):
        ''' registers a condition in the condition map '''
        node_id = parent_node.id
        if not node_id in self._condition_map:
            self._condition_map[node_id] = []
        if not node in self._condition_map[node_id]:
            self._condition_map[node_id].append(node)
        syslog.info(f"Register condition: {node_id} {parent_node.description} -> {node.description}")
        

    def _build_execution_tree(self, root):
        ''' builds the execution tree 
        
        The exec tree contains the hierarchy and execution path as follows:

        root
            device
                mode
                    container
                        container condition 
                            action condition
                                action
                                    action container
                                        action container condition
                                            action container action condition
                                                action container action
                                

        The condition nodes are evaluated and if the condition fails, the subtree of the condition is not executed
        
        '''
        profile = gremlin.shared_state.current_profile


        mode_source = gremlin.shared_state.current_profile.traverse_mode()
        mode_source.sort(key = lambda x: x[0]) # sort parent to child
        mode_list = [mode for (_,mode) in mode_source if mode] # parent mode first
        # syslog = logging.getLogger("system")

        tracker = gremlin.base_profile.ConditionTracker()
        eh = gremlin.event_handler.EventHandler()



        mode_nodes = {}
        for mode in mode_list:
            if not mode:
                syslog.error("Execution Tree: error: found a blank mode.")
                continue
            mode_item = gremlin.execution_graph.ExecutionGraphNode(ExecutionGraphNodeType.Mode)
            mode_item.parent = self.root
            mode_item.mode = mode
            mode_nodes[mode] = mode_item


        for device in profile.devices.values():
            device_node = ExecutionGraphNode(ExecutionGraphNodeType.Device)
            device_node.device = device
            device_node.parent = root
            for mode in device.modes.values():
                if not mode.name in mode_nodes:
                    syslog.error(f"Execution Tree: error: mode: {mode.name} is not found in the device node: {device_node.name}")
                    continue
                mode_item = mode_nodes[mode.name]
                mode_node = ExecutionGraphNode(ExecutionGraphNodeType.Mode)
                
                mode_node.mode = mode.name
                mode_node.parent = device_node
                for input_items in mode.config.values():
                    for input_item in input_items.values():
                        # Only add callbacks for input items that actually
                        # contain actions

                        input_node = ExecutionGraphNode(ExecutionGraphNodeType.InputItem)
                        input_node.parent = mode_node
                        input_node.input_item = input_item
                        input_node.mode = mode.name
                        
                        if len(input_item.containers) == 0:
                            # no containers = no actions = skip
                            continue

                        container : gremlin.base_profile.AbstractContainer
                        for container in input_item.containers:
                            if not container.is_valid():
                                test = container.is_valid()
                                syslog.warning("Incomplete container ignored")
                                continue
                            container.refresh_conditions() # refresh any conditions for this container
                            container_node = ExecutionGraphNode(ExecutionGraphNodeType.Container)
                            container_node.id = container.id
                            container_node.parent = input_node
                            container_node.container = container
                            container_node.mode = mode.name
                            condition_node = self._get_condition_node(container, container_node)


                            for action_set in container.action_sets:
                                action_set_node = ExecutionGraphNode(ExecutionGraphNodeType.ActionSet)
                                action_set_node.parent = condition_node
                                action_set_node.mode = mode.name
                                action_set_node.action_set = action_set
                                action_set_node.container = container
                                for action in action_set:
                                    action_condition = tracker.getConditionForAction(action)
                                    action_condition_node = self._get_condition_node(action, action_set_node)

                                    action_node = ExecutionGraphNode(ExecutionGraphNodeType.Action)
                                    action_node.id = action.id
                                    action_node.parent = action_condition_node
                                    action_node.action = action
                                    action_node.mode = mode.name
                                    action_node.condition = action_condition
                                    action_node.container = container
                                    functor = action.functor(action, action_node)
                                    action_node.functor = functor
                           


                                    # build gate action subtree
                                    if action.name == "Gated Axis":
                                        gate_data : gremlin.gated_handler.GateData = action.gate_data
                                        gates = gate_data.getUsedGates()
                                        gate_info: gremlin.gated_handler.GateInfo
                                        for gate_info in gates:
                                            gate_node = ExecutionGraphNode(ExecutionGraphNodeType.Gate)
                                            gate_node.description = f"Gate {gate_info.gate_display()}"
                                            gate_node.parent = action_node
                                            gate_node.gate = gate_info

                                            for condition, item_data in gate_info.item_data_map.items():
                                                for container in item_data.containers:
                                                    gate_container_node = ExecutionGraphNode(ExecutionGraphNodeType.Container)
                                                    gate_container_node.id = container.id
                                                    gate_container_node.parent = gate_node
                                                    gate_container_node.container = container
                                                    gate_container_node.description = f"Gate container node: gate: {gate_info.gate_display()} container: {str(container)}"
                                                    container.refresh_conditions()
                                              

                                                    # add a condition to trigger the gate 
                                                    functor = gremlin.gated_handler.GatedAxisGateCondition(gate_data, gate_info)
                                                    gate_trigger_node = ExecutionGraphNode(ExecutionGraphNodeType.ActivationCondition)
                                                    gate_trigger_node.functor = functor
                                                    gate_trigger_node.parent = gate_container_node
                                                    gate_trigger_node.description = f"Gate Trigger Node for gate : {gate_info.gate_display()}"
                                                    gate_trigger_node.container = container


                                                    gate_condition_node = self._get_condition_node(container, gate_trigger_node)

                                                    # build gate container subtree
                                                    for action_set in container.action_sets:
                                                        action_set_node = ExecutionGraphNode(ExecutionGraphNodeType.ActionSet)
                                                        action_set_node.parent = gate_condition_node
                                                        action_set_node.mode = mode.name
                                                        action_set_node.container = container
                                                        action_set_node.description = f"Action set node for gate: {gate_info.gate_display()}"
                                                        for gate_action in action_set:
                                                            action_condition = tracker.getConditionForAction(gate_action)
                                                            action_condition_node = self._get_condition_node(gate_action, action_set_node)
                                                            
                                                            gate_action_node = ExecutionGraphNode(ExecutionGraphNodeType.Action)
                                                            gate_action_node.id = gate_action.id
                                                            gate_action_node.parent = action_condition_node
                                                            gate_action_node.action = gate_action
                                                            gate_action_node.mode = mode.name
                                                            gate_action_node.container = container
                                                            gate_action_node.condition = action_condition
                                                            gate_action_node.description = f"Gate Action node for gate : {gate_info.gate_display()} : action: {str(gate_action)}"
                                              


                                        # build gate range subtree
                                        range_info : gremlin.gated_handler.RangeInfo
                                        for range_info in gate_data.getUsedRanges():
                                            range_node = ExecutionGraphNode(ExecutionGraphNodeType.Range)
                                            range_node.parent = action_node
                                            range_node.description = f"Range {range_info.to_display()}"
                                            for condition, item_data in range_info.item_data_map.items():
                                                for container in item_data.containers:
                                                    range_container_node = ExecutionGraphNode(ExecutionGraphNodeType.Container)
                                                    range_container_node.id = container.id
                                                    range_container_node.parent = range_node
                                                    range_container_node.container = container
                                                    range_container_node.description = f"Range container for range: {range_info.to_display()}: {str(container)}"
                                                    container.refresh_conditions()

                                                    # add a condition to trigger the gate 
                                                    functor = gremlin.gated_handler.GatedAxisRangeCondition(gate_data, range_info)
                                                    range_trigger_node = ExecutionGraphNode(ExecutionGraphNodeType.ActivationCondition)
                                                    range_trigger_node.functor = functor
                                                    range_trigger_node.parent = range_container_node
                                                    range_trigger_node.description = f"Range trigger node for range: {range_info.to_display()}"
                                                    range_trigger_node.container = container

                
                                                    
                                                    range_condition_node = self._get_condition_node(container, range_trigger_node)


                                                    for action_set in container.action_sets:
                                                        range_action_set_node = ExecutionGraphNode(ExecutionGraphNodeType.ActionSet)
                                                        range_action_set_node.parent = range_condition_node
                                                        range_action_set_node.mode = mode.name
                                                        for range_action in action_set:
                                                            action_condition = tracker.getConditionForAction(range_action)
                                                            action_condition_node = self._get_condition_node(range_action, action_set_node)
                                                            range_action_node = ExecutionGraphNode(ExecutionGraphNodeType.Action)
                                                            range_action_node.id = range_action.id
                                                            range_action_node.parent = action_condition_node
                                                            range_action_node.action = range_action
                                                            range_action_node.mode = mode.name
                                                            range_action_node.container = container
                                                            range_action_node.condition = action_condition
                                                            

        # build a mapping of all actions and their conditions
        self._functor_map = {}
        action_nodes = [node for node in root.descendants if node.nodeType == ExecutionGraphNodeType.Action]
        for node in action_nodes:
            functors = []
            if node.condition:
                functors.append(self._convert_condition(node.condition))
            # grab parent container condition
            container = node.container
            if container:
                if container.activation_condition:
                    condition = container.activation_condition
                    if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                        condition = self._create_activation_condition(condition, container, True)
                    else:
                        condition = self._convert_condition(container.activation_condition)
                    functors.append(condition)
                if container.activation_container_condition:
                    condition = container.activation_container_condition
                    if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                        condition = self._create_activation_condition(condition, container, True)
                    else:
                        condition = self._convert_condition(container.activation_container_condition)
                    functors.append(condition)

            if functors:
                functors.reverse()
                self._functor_map[node.id] = functors
        container_nodes = [node for node in root.descendants if node.nodeType == ExecutionGraphNodeType.Container]
        for node in container_nodes:
            functors = []
            container = node.container
            if container.activation_condition:
                condition = container.activation_condition
                if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                    condition = self._create_activation_condition(condition, container, True)
                else:
                    condition = self._convert_condition(container.activation_condition)
                functors.append(condition)
            if container.activation_container_condition:
                condition = container.activation_container_condition
                if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                    condition = self._create_activation_condition(condition, container, True)
                else:
                    condition = self._convert_condition(container.activation_container_condition)
                functors.append(condition)

            if functors:
                functors.reverse()
                self._functor_map[node.id] = functors

        # # pre-build container condition functors list
        # for id in self._condition_map.keys():
        #     functors = []
        #     nodes = self.getNodeActivationConditions(id)
        #     for condition_node in nodes:
        #         if condition_node.functor:
        #             functor = condition_node.functor
        #             if isinstance(functor, gremlin.base_conditions.AbstractCondition):
        #                 functor = self._convert_condition(functor)
        #             if not functor in functors:
        #                 functors.append(functor)
        #     if functors:
        #         self._functor_map[id] = functors

        # pass








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
            InputType.VirtualButton,
            InputType.ModeControl,
        ]:
            value = gremlin.actions.Value(event.is_pressed)
        else:
            raise gremlin.error.GremlinError("Invalid event type")

        # Containers representing a virtual button get their individual
        # value instance, all others share one to propagate changes across
        shared_value = copy.deepcopy(value)

        if event == InputType.VirtualButton:
            # TODO: remove this at a future stage
            syslog.error(
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

        event.is_virtual_button = True # tell the functors this is a virtual button
        event.is_axis = False
        print (f"Send virtual button {event.is_pressed} ---------------------------------------------------------------------------")
        return self._execution_graph.process_event(event,value)


class VirtualButtonProcess:

    """Callback that is responsible for emitting press and release events
    for a virtual button."""

    def __init__(self, data):
        """Creates a new instance for the given container.

        :param container the container using a virtual button configuration
        """
        self.virtual_button = None

        if isinstance(data, gremlin.base_buttons.VirtualAxisButton):
            self.virtual_button = gremlin.actions.AxisButton(data.lower_limit, data.upper_limit, data.direction)
        elif isinstance(data, gremlin.base_buttons.VirtualHatButton):
            self.virtual_button = gremlin.actions.HatButton(data.directions)
        else:
            raise gremlin.error.GremlinError("Invalid virtual button data provided")

    def __call__(self, event, value = None):
        """Processes the provided event through the virtual button instance.

        :param event the input event being processed
        """
        self.virtual_button.process_event(event)


class AbstractExecutionGraph(QtCore.QObject):

    """Abstract base class for all execution graph type classes.

    An execution graph consists of nodes which represent actions to execute and
    links which are transitions between nodes. Each node's execution returns
    a boolean value, indicating success or failure. The links allow skipping
    of nodes based on the outcome of a node's execution.

    When there is no link for a given node and outcome combination the
    graph terminates.
    """

    graph_completed = QtCore.Signal(object) # fires when the process events have been all processed - parameter - the grap object just completed

    def __init__(self, instance, parent = None):
        """Creates a new execution graph based on the provided data.

        :param instance the object to use in order to generate the graph
        """
        super().__init__()
        self.functors = [] # functors for actions and action conditions
        self.transitions = {}
        self.current_index = 0
        self.run_event = Event()
        self.ec = ExecutionContext()
        if parent is None:
            parent = self.ec.root
        self._build_graph(instance, parent)
        el = gremlin.event_handler.EventListener()
        el.profile_stop.connect(self._profile_stop)

    @QtCore.Slot()
    def _profile_stop(self):
        # abort if running
        self.run_event.set()
    

    def process_event(self, event, value):
        """Executes the graph with the provided data.


        #### CRITICAL EXECUTION PATH ####

        :param event the raw event that caused the execution of this graph
        :param value the possibly modified value extracted from the event
        """
        

        # Processing an event twice is needed when a virtual axis button has
        # "jumped" over it's activation region without triggering it. Once
        # this is detected the "press" event is sent and the second run ensures
        # a "release" event is sent.
        process_again = False
        self.run_event.clear()

        ec = ExecutionContext()
        functor_map = ec.functor_map
        condition_map = ec.condition_map
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_condition
        verbose_detailed = False
        if verbose_detailed:
            gremlin.shared_state.pushLog()

        try:
        
            
            verbose_input = config.verbose_mode_inputs
            # syslog = logging.getLogger("system")
            logTabs = gremlin.shared_state.logTabs(True)

            if verbose_input: syslog.info(f"{logTabs}{str(event)}")
            
            if verbose_detailed: syslog.info (f"{logTabs}Execution plan:")
            # functor_names = []
            # functor_pass_list = []

                
 
            # regular functors
            while self.current_index is not None and len(self.functors) > 0 and not self.run_event.is_set():
                index = self.current_index
                functor = self.functors[index]
                processed_functors = []

                result = True
                id = functor.id
                verbose_id = False

                if id in functor_map:
                    # cache hit
                    if verbose_id: syslog.info(f"{logTabs}\t\t\t Functor ID found")
                    processed_functors.append(functor)
                    is_condition = isinstance(functor, gremlin.actions.ActivationCondition)
                    if is_condition:
                        if verbose_id: 
                            condition_name = functor.condition_name()
                            syslog.info(f"{logTabs}\t\tIndex {index} -> executing condition {condition_name}")
                        result = functor.process_event(event, value)
                        if not result:
                            # condition failed - abort chain
                            if verbose_id: syslog.info(f"{logTabs}\t\t\t FAIL")
                            break
                        if verbose_id: syslog.info(f"{logTabs}\t\t\t PASS")

                    for action_functor in functor_map[id]:
                        if not action_functor in processed_functors:
                            processed_functors.append(action_functor)
                            if verbose_id: condition_name = action_functor.condition_name()
                            if isinstance(action_functor, gremlin.actions.ActivationCondition):
                                if verbose_id: 
                                    condition_name = action_functor.condition_name()
                                    syslog.info(f"{logTabs}\t\tIndex {index} -> executing action condition {condition_name}")
                                result = action_functor.process_event(event, value)
                            else:
                                result = action_functor(event, value)
                            if not result:
                                # condition failed - abort chain
                                if verbose_id: syslog.info(f"{logTabs}\t\t\t FAIL")
                                break
                            if verbose_id: syslog.info(f"{logTabs}\t\t\t PASS")

                    if result and not is_condition:
                        if verbose_id: syslog.info(f"{logTabs}\t\t{index} -> executing action {functor}")
                        result = functor.process_event(event, value)
                        if not result:
                            if verbose_id: syslog.info(f"{logTabs}\t\t\t FAIL")
                        else:
                            syslog.info(f"{logTabs}\t\t\t PASS")

                else:
                    if id in condition_map:
                        node = condition_map[id]
                        if verbose_id: syslog.ifo(f"{logTabs}\t\t\t Found {node.description}")
                        pass
                    if verbose_id: syslog.info(f"{logTabs}\t\t\t Functor ID not found")

                self.current_index = self.transitions.get((index, result),None)
                if verbose_detailed: syslog.info (f"{logTabs}\t\tNext step: {(index, result)} -> {self.current_index}")

            self.current_index = 0

            if process_again and not self.run_event.is_set():
                time.sleep(0.05)
                self.process_event(event, value)
            return True
        finally:
            self.graph_completed.emit(self)
            if verbose_detailed:
                gremlin.shared_state.popLog()

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
        

    def _create_activation_condition(self, activation_condition, target, is_container_condition = False):
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
            target,
            is_container_condition =is_container_condition
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
            if seq != "Action":  # container 
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

        # tree node for this container
        node = ExecutionGraphNode(ExecutionGraphNodeType.Container)
        node.container = container
        node.parent = parent
        node.mode = container.profile_mode

        container_plugins = gremlin.plugin_manager.ContainerPlugins()


        # If container based conditions exist add them before any actions
        if container.has_conditions: 
            functor = self._create_activation_condition(container.activation_container_condition, container, is_container_condition = True)
            self.functors.append(functor)
            node.functors.append(functor)
            container_plugins.register_functor(functor)
            sequence.append("ContainerCondition")
            node.sequence.append("ContainerCondition")


        functor = container.functor(container, node)
        node.functors.append(functor)
        
        if verbose:
            syslog.info(f"Enable container functor: {type(functor).__name__}")

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
            syslog.info("Ordering action sets:")
        for action in action_set:


            action_set_node = ExecutionGraphNode(ExecutionGraphNodeType.ActionSet)
            action_set_node.parent = parent

            # if not isinstance(action, action_plugins.remap.Remap):
            priority = 0
            if hasattr(action, "priority"):
                priority = action.priority
            ordered_action_set.append((priority, action))
            if verbose:
                syslog.info(f"\tadding action: {type(action)} priority: {priority} data: {str(action)}" )

            node = ExecutionGraphNode(ExecutionGraphNodeType.Action)
            node.parent = action_set_node
            node.action = action
            node.priority = priority
            nodes[action] = node


        if len(ordered_action_set) > 1:
            ordered_action_set.sort(key = lambda x: x[0])
        ordered_action_set = [x[1] for x in ordered_action_set]


        if verbose:
            syslog.info("Action order:")
            for index, action in enumerate(ordered_action_set):
                input_item = action.input_item # get_input_item()
                input_id = input_item.input_id
                input_stub = str(input_id)
                syslog.info(f"\t{index}: input type: {input_item.input_type} {input_stub} action: {type(action)}  data: {str(action)} ")


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
                    # device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
                    # print (f"Added extra functor: {device_name} mode: {mode} event: {str(event)} ")
                    eh.add_latched_functor(device_guid, mode, event, functor)
                

            action.setEnabled(True)
            self.functors.append(functor)
            sequence.append("Action")
            nodes[action].functors.append(functor)
            nodes[action].sequence.append("Action")


        self._create_transitions(sequence)



