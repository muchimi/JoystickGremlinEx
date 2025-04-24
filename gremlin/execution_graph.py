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

from abc import abstractmethod, ABCMeta, ABC
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
import queue
from enum import Enum,auto

from gremlin.singleton_decorator import SingletonDecorator
from PySide6 import QtCore
from threading import Event

syslog = logging.getLogger("system")

class ExecutionGraphNodeType(Enum):
    ''' types of tree nodes in an execution graph '''
    ExecRoot = auto() # root node of the execution graph
    InputRoot = auto() # root node of the input graph
    Container = auto() # container node
    ActionSet = auto() # action set node
    Action = auto() # action node
    Mode = auto() # mode node
    Device = auto() # device node
    InputItem = auto() # input item node
    Gate = auto() # gate type for gated data
    Range = auto() # range type for gated data
    Condition = auto() # node is a condition (has a list of activation conditions)
    ActivationCondition = auto() # node is an activation condition (has a functor to evaluate)
    ActivationConditionNexus = auto() # node is an ANY activation node nexus (any node under the nexus that evaluates to True means the result is valid)
    Functor = auto() # node is a functor node 
    Group = auto() # group node - generic grouping node, all functors in this are evaluated regardless of the outcome of sub nodes
    GatedAxisGateCondition = auto() # gated axis condition checker for gate conditions
    GatedAxisRangeCondition = auto() # gated axis condition checker for range conditions
    
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

        
class ExecutionGraphNode(ABC, anytree.NodeMixin):
    ''' execution tree node '''
    def __init__(self, node_type : ExecutionGraphNodeType):
        import gremlin.util
        super().__init__()
        self.id = gremlin.util.get_guid() # unique node id, will be the container ID or the action ID for container or action nodes
        self.functors = [] # list of functors
        self.sequence = [] # list of sequence codes (action, condition) for the functor by index
       
        
        self.priority : int = 0 # execution priority of nodes at the same tree level
        self.nodeType : ExecutionGraphNodeType = node_type
        
        self.mode : str = None # mode the node is defined in
        self.exec_modes = [] # list of mode this node can execute in
        self.device = None # mapped device if a device node
        self.description = ""
        self.has_actions = False # assume the node has no child action somewhere down the tree
        self.link = None # link to another node
        self.device_link = None # link to the device node
        self.comment = None # comment asociated with this node

    def node_string(self):
         return f"{self.nodeType.name}: (node {self.id}) {self.description} has actions: {self.has_actions}"
    
    def getFunctors(self):
        ''' gets the functors in the node '''
        return [] if self.functors is None else (self.functors if  isinstance(self.functors, list) else [self.functors])
    
    def getConditionFunctors(self):
        ''' gets the list of condition functors in the node '''
        functor_list = self.getFunctors()
        return [functor for functor in functor_list if isinstance(functor, gremlin.actions.ActivationCondition) or isinstance(functor, gremlin.actions.AbstractCondition)]
    
    def getActionFunctors(self):
        functor_list = self.getFunctors()
        return [functor for functor in functor_list if isinstance(functor, gremlin.base_conditions.AbstractFunctor)]
        
    @property
    def is_condition(self) -> bool:
        ''' true if the node is a condition node '''
        return self.nodeType in (ExecutionGraphNodeType.ActivationCondition,
                                 ExecutionGraphNodeType.ActivationConditionNexus,
                                 ExecutionGraphNodeType.Condition,
                                 ExecutionGraphNodeType.GatedAxisGateCondition,
                                 ExecutionGraphNodeType.GatedAxisRangeCondition)
    
    @abstractmethod
    def to_string(self):
        return self.node_string()
    
    def __str__(self):
        return self.to_string()
    
    def __hash__(self):
        return hash(self.id)

class ExecutionGraphRootNode(ExecutionGraphNode):
    ''' holds a mode in the execution graph '''
    def __init__(self):
        super().__init__(ExecutionGraphNodeType.ExecRoot)

    def to_string(self):
        stub = "Root node"
        return f"{self.node_string()} {stub}"  

class ExecutionGraphDeviceNode(ExecutionGraphNode):
    ''' holds a device in the execution graph '''
    def __init__(self):
        super().__init__(ExecutionGraphNodeType.Device)
        self.device = None

    def to_string(self):
        stub = self.device.name
        return f"{self.node_string()} {stub}"

class ExecutionGraphModeNode(ExecutionGraphNode):
    ''' holds a mode in the execution graph '''
    def __init__(self, mode : str = None):
        super().__init__(ExecutionGraphNodeType.Mode)
        self.mode = mode

    def to_string(self):
        stub = f"Mode: [{self.mode}]"
        return f"{self.node_string()} {stub}"

class ExecutionGraphGroupNode(ExecutionGraphNode):
    ''' holds a mode in the execution graph '''
    def __init__(self):
        super().__init__(ExecutionGraphNodeType.Group)

    def to_string(self):
        stub = "Group"
        return f"{self.node_string()} {stub}"      

class ExecutionGraphActivationConditionNexusNode(ExecutionGraphNode):
    ''' holds an input item in the execution graph '''
    def __init__(self, condition = None):
        super().__init__(ExecutionGraphNodeType.ActivationConditionNexus)
        self.condition : gremlin.actions.ActivationCondition = condition # holds the condition 

    def to_string(self):
        stub = "Activation Condition"
        return f"{self.node_string()} {stub}"  

class ExecutionGraphInputNode(ExecutionGraphNode):
    ''' holds an input item in the execution graph '''
    def __init__(self):
        super().__init__(ExecutionGraphNodeType.InputItem)
        self.input_item = None

    def to_string(self):
        stub = f"{self.input_item.display_name}"
        return f"{self.node_string()} {stub}"
    
class ExecutionGraphConditionNode(ExecutionGraphNode):
    ''' holds an input item in the execution graph '''
    def __init__(self, condition = None):
        super().__init__(ExecutionGraphNodeType.Condition)
        self.condition : gremlin.actions.ActivationCondition = condition # holds the condition 
        

    def to_string(self):
        stub = self.condition.condition_name()
        return f"{self.node_string()} {stub}"
    
class ExecutionGraphActivationConditionNode(ExecutionGraphNode):
    ''' holds an input item in the execution graph '''
    def __init__(self, condition = None):
        super().__init__(ExecutionGraphNodeType.ActivationCondition)
        self.condition : gremlin.actions.ActivationCondition = condition # holds the condition 

    def to_string(self):
        stub = str(self.condition)
        return f"{self.node_string()} {stub}"
    


class ExecutionGraphFunctorNode(ExecutionGraphNode):
    ''' holds an input item in the execution graph '''
    def __init__(self, functor = None):
        super().__init__(ExecutionGraphNodeType.Functor)
        self.functors = functor

    def to_string(self):
        return f"{self.node_string()}"

class ExecutionGraphActionSetNode(ExecutionGraphNode):
    ''' holds an input item in the execution graph '''
    def __init__(self, action_set : gremlin.base_profile.ActionSet = []):
        super().__init__(ExecutionGraphNodeType.ActionSet)
        self.action_set = action_set

    def to_string(self):
        stub = f"Action Count: {len(self.action_set)}"
        return f"{self.node_string()} {stub}"
    
class ExecutionGraphActivationGroup(ExecutionGraphNode):
    ''' holds an input item in the execution graph '''
    def __init__(self, condition = None):
        super().__init__(ExecutionGraphNodeType.Group)
        self.condition : gremlin.actions.ActivationCondition = condition # holds the condition 

    def to_string(self):
        stub = str(self.condition)
        return f"{self.node_string()} {stub}"      
    
class ExecutionGraphContainerNode(ExecutionGraphNode):
    ''' holds a container in the execution graph '''
    def __init__(self, container : gremlin.base_profile.AbstractContainer = None):
        super().__init__(ExecutionGraphNodeType.Container)
        self.container : gremlin.base_profile.AbstractContainer = container

    def to_string(self):
        container = self.container
        device_name = container.get_device_name()
        condition : gremlin.base_profile.AbstractCondition = container.activation_condition
        condition_stub = f"True id: {condition.id}" if condition else ""
        stub = f"Container: {self.container.name} Device: {device_name} Input {container.input_display_name}  Condition: {condition_stub}  Comment: {self.container.comment}"
        return f"{self.node_string()} {stub}"
        

class ExecutionGraphActionNode(ExecutionGraphNode):
    ''' holds an action in the execution graph '''
    def __init__(self, action = None ):
        super().__init__(ExecutionGraphNodeType.Action)
        self.action = action

    def to_string(self):
        functor : gremlin.base_profile.AbstractAction
        stub = ""
        if isinstance(self.functors, list):
            for functor in self.functors:
                comment = f"Input: {functor.action_data.input_item.device_name} id: {functor.action_data.input_item.input_id} mode: {functor.action_data.input_item.profile_mode} {functor.action_data.comment if functor.action_data.comment else ''} | "
                stub += f"Action: [{functor.__class__.__name__}] {comment}"
        else:
            functor = self.functors
            if functor is not None:
                comment = f"Input: {functor.action_data.input_item.device_name} id: {functor.action_data.input_item.input_id} mode: {functor.action_data.input_item.profile_mode} {functor.action_data.comment if functor.action_data.comment else ''} | "
                stub += f"Action: [{functor.__class__.__name__}] {comment}"
            else:
                stub += "Action: no action found"
        return f"{self.node_string()} {stub}"


class ExecutionGraphGateConditionNode(ExecutionGraphNode):
    ''' holds a gated axis gate condition in the execution graph '''
    def __init__(self, functor = None):
        super().__init__(ExecutionGraphNodeType.GatedAxisGateCondition)
        if not self.functors:
            self.functors = []
        self.functors.append(functor)

    def to_string(self):
        exec_functor = self.functors[0] if self.functors else None
        stub = f"Gated Axis GATE Condition type: {exec_functor.condition_type.name if exec_functor else 'n/a'}"
        return f"{self.node_string()} {stub}"
    
class ExecutionGraphRangeConditionNode(ExecutionGraphNode):
    ''' holds a gated axis gate condition in the execution graph '''
    def __init__(self, functor = None):
        super().__init__(ExecutionGraphNodeType.GatedAxisRangeCondition)
        if not self.functors:
            self.functors = []
        self.functors.append(functor)

    def to_string(self):
        exec_functor = self.functors[0] if self.functors else None
        stub = f"Gated Axis GATE Condition type: {exec_functor.condition_type.name if exec_functor else 'n/a'}"
        return f"{self.node_string()} {stub}"      
    


class ExecutionGraphGateNode(ExecutionGraphNode):
    ''' holds a gated axis gate in the execution graph '''
    def __init__(self, gate_info = None):
        super().__init__(ExecutionGraphNodeType.Gate)
        self.gate = gate_info # holds the gateInfo object for a gated axis action

    def to_string(self):
        stub = str(self.gate)
        return f"{self.node_string()} {stub}"     
    
class ExecutionGraphRangeNode(ExecutionGraphNode):
    ''' holds a gated axis range in the execution graph '''
    def __init__(self, range_info = None):
        super().__init__(ExecutionGraphNodeType.Range)
        self.range = range_info # holds the rangeInfo object for a gated axis action

    def to_string(self):
        stub = str(self.range)
        return f"{self.node_string()} {stub}"         


class ExecutionContextInputData():
    ''' holds an input item configuration '''
    def __init__(self, input_item, mode : str, modes: list):
        self.input_item = input_item # the input item
        self.mode = mode # mode the input is referenced by
        self.modes = modes # modes referencing this input item


class LatchedData():
    def __init__(self):
        self.functor = None
        self.container_node = None
        self.condition_node = None
        self.action_node = None # action node to latch
        self.extra_inputs = None # list of (device_guid, input_type, input_id) inputs to latch
        self.mode = None # mode the latching applies to


@SingletonDecorator
class ExecutionContext():
    ''' holds the current execution context '''
    def __init__(self):
       
        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.connect(self.reset) # reload data on mode changes
        #el.runtime_mode_changed.connect(self._runtime_mode_changed)
        el.profile_start.connect(self._profile_start) # reload data on profile start
        el.profile_changed.connect(self.reset) # reload data on profile change
        el.profile_modes_changed.connect(self.reset) # modes changed

        self._mode_tree = None
        self._mode_ancestors = {}  # map of mode branches by mode
        self._mode_descendants = {} # map of mode children by mode
        self.graph = None # root node of execution tree
        self.graph_input_root = None # root node of the input / action tree - maps individual inputs to modes and actions  unique input->mode->actions for that mode (only actions, not conditions)
        self.graph_input_map = {} # map of input nodes keyed by callbackKey of input graph input nodes for fast lookup
        self._last_hash = None
        self._condition_map = {} # map of node ID to conditions that have conditions
        self._functor_map = {} # map of node ID to action nodes to execute for condition checking
        self._node_map = {} # map of node ID to node
        self._processed_events = []
        self._processed_functors = {}
        config = gremlin.config.Configuration()
        self._verbose_exec = config.verbose_mode_execution
        self._verbose_detailed = config.verbose_mode_exec_detailed
        self._verbose_condition = config.verbose_mode_condition
        self.used_items = {}  # nodes can only be used once
        

    @property
    def functor_map(self) -> dict:
        ''' map of container condition functors '''
        return self._functor_map
    
    @property
    def node_map(self) -> dict:
        return self._node_map
    

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
        
    def reset(self, force_rebuild = False):
        ''' reloads the execution context to capture changes '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_exec
        if verbose: syslog.info("CONTEXT: reload")
        if not gremlin.shared_state.current_profile:
            # no profile loaded
            return 

        profile = gremlin.shared_state.current_profile

        # detect changes
        profile_hash = profile.getMappingHash()
        rebuild = force_rebuild or self._last_hash is None or self._last_hash != profile_hash

        # builds the tree
        if rebuild:
            self._last_hash = profile_hash
            self._rebuild()
            
            

    def _rebuild(self):
        
        verbose = gremlin.config.Configuration().verbose_mode_exec
        if verbose: syslog.info("CONTEXT: rebuild")
        
        self.used_items = {}  # nodes can only be used once
        self._build_error = False # true if a build error occurred
        #self._functor_map = {} # quick access to functor IDs
        self._build_execution_tree()
        assert len(self.graph.children) > 0

        # tell the ui the execution context changed
        el = gremlin.event_handler.EventListener()
        el.execution_context_changed.emit()

    def getLastBuildError(self) -> bool:
        ''' true if build errored out'''
        return self._build_error
            

    def _profile_start(self):
        # ''' profile start - rebuild the execution tree '''
        # verbose = gremlin.config.Configuration().verbose_mode_exec
        # if verbose: syslog.info("CONTEXT: rebuild on profile start")
        # self._rebuild()
        
        # update debug vars on start
        config = gremlin.config.Configuration() 
        self._verbose_exec = config.verbose_mode_execution
        self._verbose_condition = config.verbose_mode_condition
        pass


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
        if not self._mode_tree or not self._mode_tree.children:
            self.reset()
        return self._mode_tree
    
    def searchModeTree(self, mode : str) -> ExecutionModeNode:
        ''' find the node for a mode in the mode tree '''
        # syslog = logging.getLogger("system")
        tree = self._mode_tree
        node = anytree.find(tree, lambda m: m.mode == mode)
        return node
    

    def getModeHierarchy(self, mode: str):
        ''' gets the mode hierarchy for a given profile mode - returns the current mode and all its parent modes '''
        return gremlin.shared_state.current_profile.getModeHiearchy(mode)
    
    def getModeNames(self, as_tuple = False, include_current = True) -> list:
        ''' gets the mode names as a list of tuples
            as_tuple: returns as a tuple of data (mode_key, display_name)

            include_current: if true, includes the current mode in the list, false excludes it which may cause an empty list to be returned

            '''
        
        current_mode = gremlin.shared_state.edit_mode # current edit mode
        
        if as_tuple:
            mode_list = gremlin.shared_state.current_profile.get_mode_display_list()
            if include_current:
                return [(mode, display) for (mode, display) in mode_list]
            return [(mode, display) for (mode, display) in mode_list if mode != current_mode]

        mode_list = gremlin.shared_state.current_profile.get_modes()
        if include_current:
            return mode_list
        return [mode for mode in mode_list if mode != current_mode]


        
    def getNode(self, id):
        ''' gets the node matching the corresponding id - nodes that have an ID are container and action nodes '''
        node = next((node for node in anytree.PreOrderIter(self.graph) if node.id == id), None)
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
                    syslog.info(f"(node {node.id} type: {node.nodeType.name}) Activation condition functors for node {node.description}  :")
                    for n in activation_conditions:
                        syslog.info(f"\t(node {node.id} type: {node.nodeType.name}) Functor node: {n.description}")

        return activation_conditions


    
    def getModes(self) -> list:
        ''' returns the list of defined modes in the execution tree '''
        return [node.mode for node in anytree.PreOrderIter(self.graph) if node.nodeType == ExecutionGraphNodeType.Mode and node.mode]
        
    
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

    def getMappedInputs(self, input_type : InputType) -> list[ExecutionContextInputData]:
        ''' gets a list of all inputs in the execution tree of that current type that have a container defined'''
        input_items = []
        node: ExecutionGraphNode
        for node in anytree.PreOrderIter(self.graph):
            if node.nodeType == ExecutionGraphNodeType.InputItem:
                input_item = node.input_item
                if input_item.input_type == input_type:
                    mode = node.mode
                    modes  = gremlin.shared_state.current_profile.getModeHierarchy(mode)
                    item = ExecutionContextInputData(input_item, mode, modes)
                    input_items.append(item)

        return input_items
    
    def deviceHasMappings(self, device_guid):
        ''' true if a device has inputs defined '''
        node: ExecutionGraphNode
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if self.graph is None:
            self._rebuild()
        if self.graph:
            for node in anytree.PreOrderIter(self.graph):
                if node.nodeType == ExecutionGraphNodeType.Device and node.device.device_id == device_guid:
                    # found the device
                    if anytree.find(node, filter_ = lambda n: n.nodeType == ExecutionGraphNodeType.Container):
                        return True
        return False

    

    def find(self, item):
        ''' looks for a container, action or action set in the execution tree node '''
        for node in anytree.PreOrderIter(self.graph):
            if hasattr(node,"container"):
                if node.container == item:
                    return node
            if hasattr(node,"functor"):
                if node.functor == item:
                    return node
            if hasattr(node,"action_set"):
                if node.action_set == item:
                    return node
            if hasattr(node,"functor"):
                if item in node.functors:
                    return node
        return None
    
    
    def findNodeById(self, id):
        ''' looks for a container or action by functor ID '''
        for node in anytree.PreOrderIter(self.graph):
            if node.id == id:
                return node
        return None
    
    def findActionPlugin(self, plugin_name):
        ''' gets a list of nodes that have a specific class
         
        :param plugin_name: matches the name property of an action plugin
        '''
        nodes = []
        if self.graph is None:
            self.reset()
        for node in anytree.PreOrderIter(self.graph):
            if node.nodeType == ExecutionGraphNodeType.Action:
                if node.action.name == plugin_name:
                    nodes.append(node)

        return nodes
    
    def findInputItem(self, device_guid, input_type, input_id, mode : str):
        ''' finds the input item corresponding to the device and id specififed, None if not found 
            true if the execution tree contains mappings with input types of the specified type  
        '''
        
        mode_node = self.findModeNode(device_guid, mode)
        if not mode_node:
            return None
        input_node = next((n for n in mode_node.children if n.nodeType == ExecutionGraphNodeType.InputItem and n.input_item.device_guid == device_guid and n.input_item.input_id == input_id and n.input_item.input_type == input_type), None)
        return input_node
    
    def findDeviceNode(self, device_guid):
        ''' gets the device node for the given device guid '''
        device_node = next((n for n in self.graph.children if n.nodeType == ExecutionGraphNodeType.Device and n.device.device_guid == device_guid), None)
        return device_node
    
    def findModeNode(self, device_guid, mode : str):
        ''' gets the mode node for the given device guid '''
        device_node = self.findDeviceNode(device_guid)
        if device_node is not None:
            mode_node = next((n for n in device_node.children if n.nodeType == ExecutionGraphNodeType.Mode and n.mode == mode), None)
            return mode_node
        return None



    def hasInputType(self, input_type):
        ''' true if the execution tree contains mappings with input types of the specified type  '''
        node : ExecutionGraphNode
        for node in anytree.PreOrderIter(self.graph):
            if node.nodeType == ExecutionGraphNodeType.InputItem:
                input_item = node.input_item
                if input_item.input_type == input_type:
                    return True
        return False

    def dump(self, root = None, exclude_empty = True, conditions_only = False, input_tree = False):
        self.dumpModeTree()
        self.dumpExecTree(root, exclude_empty, conditions_only)
        if input_tree: self.dumpInputTree()

    def dumpExecTree(self, root = None, exclude_empty = True, conditions_only = False):
        # dumps the execution tree
        # syslog = logging.getLogger("system")
        if root is None:
            root = self.graph
        syslog.info(f"Execution Tree:")
        if root:
            for pre, fill, node in anytree.RenderTree(root, style=anytree.AsciiStyle()):
                if exclude_empty:
                    if node.nodeType == ExecutionGraphNodeType.InputItem:
                        if node.is_leaf:
                            continue # skip blank node
                if conditions_only:
                    if node.nodeType != ExecutionGraphNodeType.ActivationCondition:
                        continue # activation conditions only
                msg = node.to_string()
                syslog.info(f"{pre}{msg}")

    def dumpInputTree(self):
        ''' dumps the input tree '''
        syslog.info(f"Input Tree:")
        root = self.graph_input_root
        if root:
            node : ExecutionGraphNode
            for pre, fill, node in anytree.RenderTree(root, style=anytree.AsciiStyle()):
                if node.has_actions:
                    syslog.info(f"{pre}{str(node)} {node.comment}")


    def dumpActive(self):
        ''' dumps active execution nodes ONLY'''
        # syslog = logging.getLogger("system")
        syslog.info(f"Execution Tree:")
        if self.graph:
            for pre, fill, node in anytree.RenderTree(self.graph, style=anytree.AsciiStyle()):
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
        
        elif isinstance(condition, gremlin.actions.VirtualButtonCondition):
            return condition
   
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

    def _get_condition_node(self, owner, parent):
        ''' gets a condition node'''
        condition_node = ExecutionGraphConditionNode()
        condition_node.container = owner
        condition_node.parent = parent
        condition_node.description = f"Condition node for parent owner: {str(owner)} "
        conditions = None
        root_node = condition_node
        if isinstance(owner, gremlin.base_profile.AbstractContainer):
            conditions = owner.activation_condition.conditions
            condition_node.condition =  owner.activation_condition
            
        elif isinstance(owner, gremlin.base_profile.AbstractAction):
            if owner.activation_condition:
                conditions = owner.activation_condition.conditions
            condition_node.condition = owner.activation_condition
        else:
            assert False,f"don't know how to handle: {owner.__class__.__name__}"

        rule = owner.activation_condition.rule
        condition_nexus = None # for all conditions, don't use a nexus node
        match rule:
            case gremlin.actions.ActivationRule.Any:
                # create a condition nexus node for the ANY rule (any condition that passes means the action is good to go)
                condition_nexus = ExecutionGraphActivationConditionNexusNode()
                condition_nexus.parent = condition_node
                condition_nexus.description = f"ActivationConditionNexus: {str(owner)}"
                node = condition_nexus
            case gremlin.actions.ActivationRule.All:
                # no nexus created for the all condition - conditions in ALL mode are nested so they are all evaluated
                node = root_node #
        
        if conditions:
            for condition in conditions:
                sub_node = ExecutionGraphActivationConditionNode()
                sub_node.condition = condition
                sub_node.description =  f"(sub) ActivationCondition node: {str(condition)}"
                sub_node.container = owner
                sub_node.parent = node
                functor = self._convert_condition(condition)
                sub_node.functors.append(functor)
                if not condition_nexus:
                    # all rule = nest conditions so they are all evaluated
                    node = sub_node
        
        return node
    
    def _get_functor_node(self, container, functor, parent):
        ''' gets a functor node for a given functor '''
        functor_node = ExecutionGraphFunctorNode()
        functor_node.container = container
        functor_node.functors = [functor]
        functor_node.parent = parent

        functor_node.condition = container.activation_condition
        return functor_node
    
    def _register_condition(self, parent_node, node):
        ''' registers a condition in the condition map '''
        node_id = parent_node.id
        if not node_id in self._condition_map:
            self._condition_map[node_id] = []
        if not node in self._condition_map[node_id]:
            self._condition_map[node_id].append(node)
        syslog.info(f"Register condition: {node_id} {parent_node.description} -> {node.description}")


    def _traverse_node_functors(self, node, functors : list):
        ''' recursive forward looking functor tree builder '''
        gremlin.shared_state.pushLog()
        try:
            logTabs = gremlin.shared_state.logTabs(True)
            if self._verbose_detailed: syslog.info(f"{logTabs}EXEC: [{node.id}] {node.description}")
            match node.nodeType:
                case ExecutionGraphNodeType.Group:
                    # group node
                    if self._verbose_detailed: syslog.info(f"{logTabs}\tGroup node")
                    group_functors = []
                    functors.append(group_functors)
                    for child in node.children:
                        self._traverse_node_functors(child, group_functors)
                    node.functors = [] 
                    return
                    


                case ExecutionGraphNodeType.ActivationConditionNexus:
                    # nexus node used for ANY conditions
                    # this node contains a bunch of conditions and non-conditions
                    # group the conditions together in a list for evaluation, then add the other functors normally
                    # so the list becomes 
                    if self._verbose_detailed: syslog.info(f"{logTabs}\tprocessing ANY rule")
                    
                    condition_nodes = [n for n in node.children if n.nodeType == ExecutionGraphNodeType.ActivationCondition]
                    other_nodes = [n for n in node.children if n.nodeType != ExecutionGraphNodeType.ActivationCondition]
                    any_functors = []
                    for child in condition_nodes:
                        self._traverse_node_functors(child, any_functors)
                    if self._verbose_detailed: syslog.info(f"{logTabs}Added {len(any_functors)} condition functors")
                    functors.append(any_functors)
                    for child in other_nodes:
                        # add to the functor chain after conditions
                        self._traverse_node_functors(child, functors)
                    node.functors = []
                    return
                
                case ExecutionGraphNodeType.ActivationCondition:
                    if node.condition:
                        condition  = node.condition
                        container = node.container
                        node_functors = []
                        
                        if condition and container:
                            if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                                if self._verbose_detailed: syslog.info(f"{logTabs}\tprocessing ALL rule")
                                for child in node.children:
                                    self._traverse_node_functors(child, node_functors)
                                functors.extend(node_functors)
                                node.functors = node_functors
                                # done processing that branch
                                return
                            elif isinstance(condition, gremlin.base_conditions.AbstractCondition):
                                if self._verbose_detailed: syslog.info(f"{logTabs}\tadding functor for condition: {str(condition)}")
                                functor = self._convert_condition(condition)
                                node_functors.append(functor)
                                functors.append([functors])
                                node.functors = node_functors
                            elif isinstance(condition, gremlin.actions.VirtualButtonCondition):
                                functor = condition
                                node_functors.append(functor)
                                functors.append([functors])
                                node.functors = node_functors

                            else:
                                assert False, f"invalid condition type: [{condition.__class__.__name__}]"

                case ExecutionGraphNodeType.Condition:
                    # condition node
                    pass
                    # functor_list = node.functors
                    # node.functors = functor_list

                case ExecutionGraphNodeType.GatedAxisGateCondition:
                    # gated condition node
                    pass
                    # functor_list = node.functors
                    # node.functors = functor_list

                case ExecutionGraphNodeType.GatedAxisRangeCondition:
                    # gated condition node
                    pass
                    # node.functors = functor_list

                case ExecutionGraphNodeType.Action:
                    pass

            # traverse children
            for child in node.children:
                self._traverse_node_functors(child, functors)

        finally:
            gremlin.shared_state.popLog()
        

    def _get_node_functors(self, node):
        ''' gets containers and returns a list of conditions for these containers '''
        functors = []
        n = node.parent
        while n:
            if n.nodeType in (ExecutionGraphNodeType.ActivationCondition, ExecutionGraphNodeType.Condition):
                # execution condition 
                if n.condition:
                    condition  = n.condition
                    container = n.container
                    if condition and container:
                        if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                            functor = self._create_activation_condition(condition, container, True)
                        else:
                            functor = self._convert_condition(condition)
                        logtabs = gremlin.shared_state.logTabs()
                        if self._verbose_exec: syslog.info(f"{logtabs}\tAdding activation container condition: {str(condition)}")                            
                        functors.append(functor)

            if n.nodeType == ExecutionGraphNodeType.InputItem:
                break # stop at input type
            n = n.parent

        if functors:
            # reverse the list to go down the tree, so evaluate parent functors first
            functors.reverse()


        # add the forward functors for the node
        self._traverse_node_functors(node, functors)

        # if hasattr(node, "functors"):
        #     functors.extend(node.functors)

        return functors
    

    def _get_container_functor(self, container, node):
        ''' creates a functor instance of a container '''
        functor : gremlin.base_conditions.AbstractFunctor = container.functor(container, node)
        return functor

    def _get_action_functor(self, action, node):
        ''' creates a functor instance for an action '''
        functor : gremlin.base_conditions.AbstractFunctor = action.functor(action, node)
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
        return functor
    
    def _get_gate_action_functor(self, action, node):
        functor : gremlin.base_conditions.AbstractFunctor = self._get_action_functor()
        event = gremlin.event_handler.Event(
                    event_type= gremlin.input_types.InputType.VirtualButton,
                    device_guid = gremlin.shared_state.virtual_device_guid,
                    identifier = 1
            )
        

    def _build_container_tree(self, container, parent_group, mode_name, device_node, input_item, m_input_node ) -> bool:
        ''' builds a tree branch for the given container '''
        if not container.is_valid():
            syslog.warning("Incomplete container ignored")
            return True

        if container.id in self.used_items:
            syslog.error(f"Container already used: {container.id}")
            self._build_error = True
            return False
        self.used_items[container.id] = container
        
        assert isinstance(container, gremlin.base_profile.AbstractContainer), f"invalid node type: {container.__class__.__name__} encountered"


        container_parent_node = parent_group
        
        container_node = ExecutionGraphContainerNode(container)
        container_node.id = container.id
        container_node.mode = mode_name
        container_node.description = f"Container type: [{container.__class__.__name__}] ID: [{container.id}]"

        # container functor - this is what calls the process_events() method on container functors
        container_node.functors = self._get_container_functor(container, container_node)

        # container condition

        if container.has_virtual_button:
            condition = gremlin.actions.VirtualButtonCondition(container.virtual_button)
            virtual_condition_node = ExecutionGraphActivationConditionNode(condition)
            virtual_condition_node.container = container
            virtual_condition_node.functors = condition
            virtual_condition_node.parent = container_parent_node
            container_parent_node = virtual_condition_node

        if container.has_conditions:
            condition_node = self._get_condition_node(container, container_node)
            condition_node.parent = container_parent_node
            container_node.parent = condition_node
        else:
            container_node.parent = container_parent_node

        container_group = ExecutionGraphGroupNode()
        container_group.parent = container_node

        for action_set in container.action_sets:

            # a container usually has a single action set, but some like tempo/tempoEx have multipe action sets so each is grouped by an action set
            # sort actions by priority low to high

            action_set_node = ExecutionGraphActionSetNode(action_set)
            action_set_group_node = ExecutionGraphGroupNode()
            action_set_node.parent = container_group
            action_set_group_node.parent = action_set_node


            action_list = [((action.priority, index),action) for index, action in enumerate(action_set)]
            if not action_list:
                # empty set
                continue
            action_list.sort(key = lambda x : x[0]) # sort by priority, order of appearance
            for index, action in action_list:

                if action.id in self.used_items:
                    syslog.error(f"Action already used: {action.id}")
                    self._build_error = True
                    return False
                self.used_items[action.id] = action

                # action node
                action_node = ExecutionGraphActionNode(action)
                action_node.id = action.id
                
                action_node.mode = mode_name
                action_node.comment = action.comment
                action_node.device_link = device_node
                action_node.input_item = input_item

                if action.has_conditions:
                    action_condition_node = self._get_condition_node(action, action_set_group_node)
                    action_node.parent = action_condition_node # action node is owned by its condition node
                else:
                    action_node.parent = action_set_group_node

                m_action_node = ExecutionGraphActionNode(action)
                m_action_node.id = action.id
                m_action_node.parent = m_input_node # action node is owned by its condition node
                m_action_node.mode = mode_name
                m_action_node.link = action_node # link the input tree action node to the execution tree action node
                action_node.link = m_action_node # link the execution tree action node to the input tree action node

                action_node.container = container
                functor = self._get_action_functor(action, action_node)
                action_node.functors.append(functor)
                action_node.description = f"Action node: [{str(action)}]"

                # build gate action execution subtree
                if action.name == "Gated Axis":
    
                    # build gate subtree
                    gate_data : gremlin.gated_handler.GateData = action.gate_data
                    gates = gate_data.getUsedGates()
                    gate_info: gremlin.gated_handler.GateInfo

                    # gates hold a group of conditions (increase/decrease/cross)
                    gate_group = ExecutionGraphGroupNode()
                    gate_group.parent = action_node

                    for gate_info in gates:

                        for condition_type, item_data in gate_info.item_data_map.items():
                            if not item_data.containers:
                                # no containers to process for this condition
                                continue

                            # gate activation condition node
                            exec_functors = gremlin.gated_handler.GatedAxisGateCondition(gate_data, gate_info, condition_type)
                            gate_condition_node = ExecutionGraphGateConditionNode(exec_functors)
                            gate_condition_node.parent = gate_group

                            gate_node = ExecutionGraphGateNode(gate_info)
                            gate_node.description = f"Gate for condition: {condition_type.name} {gate_info.to_display()}"
                            gate_node.parent = gate_condition_node # gate node is owned by its parent action
 
                            group_node = ExecutionGraphGroupNode()
                            group_node.parent = gate_node


                            for container in item_data.containers:
                                self._build_container_tree(container, group_node, mode_name, device_node, input_item, m_input_node)

                    # build range subtree
                    range_group = gate_group # use the same group
                    range_info : gremlin.gated_handler.RangeInfo
                    for range_info in gate_data.getUsedRanges():
                        for condition_type, item_data in range_info.item_data_map.items():

                            if not item_data.containers:
                                # no containers to process for this condition
                                continue

                            # range condition (condition applied to the range)
                            exec_functors = gremlin.gated_handler.GatedAxisRangeCondition(gate_data, range_info, condition_type)
                            range_condition_node = ExecutionGraphRangeConditionNode(exec_functors)
                            range_condition_node.parent = range_group

                            range_node = ExecutionGraphRangeNode(range_info)
                            range_node.parent = range_condition_node
                            range_node.description = f"Range for condition: {condition_type.name} {range_info.to_display()}"

                            # holds the containers for the range
                            group_node = ExecutionGraphGroupNode()
                            group_node.parent = range_node

                            for container in item_data.containers:
                                self._build_container_tree(container, group_node, mode_name, device_node, input_item, m_input_node)


    def _build_execution_tree(self):
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
        if self._build_error:
            return False
        
        profile = gremlin.shared_state.current_profile
        self._functor_map = {}
        self._node_map = {}
        verbose = gremlin.config.Configuration().verbose_mode_execution
        mode_source = gremlin.shared_state.current_profile.traverse_mode()
        mode_source.sort(key = lambda x: x[0]) # sort parent to child
        mode_list = [mode for (_,mode) in mode_source if mode] # parent mode first
        # syslog = logging.getLogger("system")

        tracker = gremlin.base_profile.ConditionTracker()
        eh = gremlin.event_handler.EventHandler()


        # build the mode tree
        self._mode_tree = ExecutionModeNode()
        mode_nodes = {}

        for mode in mode_list:
            if not mode:
                syslog.error("Execution Tree: error: found a blank mode.")
                continue
            mode_item = ExecutionModeNode()
            mode_item.mode = mode
            mode_nodes[mode] = mode_item
        
        mode_tree = gremlin.shared_state.current_profile.modeTree()
        gremlin.shared_state.current_profile.dumpModeTree()
        tree_nodes = {}
        for node in anytree.PreOrderIter(mode_tree):
            mode_name = node.name
            if not mode_name in tree_nodes:
                tree_node = ExecutionModeNode(mode_name)
                tree_node.parent = self._mode_tree
                tree_nodes[mode_name] = tree_node
            else:
                tree_node = tree_nodes[mode_name]

            if mode_name and node.parent and node.parent.name:
                parent_mode_name = node.parent.name
                mode_nodes[mode_name].parent = mode_nodes[parent_mode_name]
                if not parent_mode_name in tree_nodes:
                    parent_tree_node = ExecutionModeNode(parent_mode_name)
                    parent_tree_node.parent = self._mode_tree
                    tree_nodes[parent_mode_name] = parent_tree_node
                else:
                    parent_tree_node = tree_nodes[parent_mode_name]

                tree_node.parent = parent_tree_node
            else:
                tree_node.parent = self._mode_tree    
            

            



            

        current_profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        m_input_nodes = {} # holds the input nodes created for the input/mode hiearchy tree - keyed by the input
        self._mode_ancestors = {} # ancestor looking list, keyed by mode name
        self._mode_descendants = {} # descendant looking list, keyed by mode name


        # build the execution tree
        self.graph = ExecutionGraphRootNode() # root node
        self.graph_input_root = ExecutionGraphRootNode() # root node for the device/input replacement graph for nested modes

        ''' mode tree setup 
        
            root
            +-- input_node (mapped input device/input_type/input_id)
                +-- action_node
                    -> mode property holds the mode the action is mapped to
                    -> link property holds the action_node in the execution tree
        
        
        
        '''
        
        for device in profile.devices.values():
            device_node = ExecutionGraphDeviceNode()
            device_node.device = device
            device_node.parent = self.graph

            for mode in device.modes.values():
                mode_name = mode.name
                if not mode_name in mode_nodes:
                    syslog.error(f"Execution Tree: error: mode: {mode_name} is not found in the device node: {device_node.name}")
                    continue

                

                mode_item = mode_nodes[mode_name]
                mode_node = ExecutionGraphModeNode()
                mode_node.mode = mode_name

                # build list of parent modes - contains the current mode if a root mode, or the list of current and parent modes if nested
                if not mode_name in self._mode_ancestors:
                    self._mode_ancestors[mode_name] = current_profile.get_mode_ancestors(mode_name)
                    self._mode_descendants[mode_name] = current_profile.get_mode_descendants(mode_name)

                mode_node.mode = mode_name
                mode_node.parent = device_node
                for input_items in mode.config.values():
                    for input_item in input_items.values():
                        # Only add callbacks for input items that actually
                        # contain actions

                        input_node = ExecutionGraphInputNode()
                        input_node.parent = mode_node
                        input_node.input_item = input_item
                        input_node.mode = mode_name

                        # setup a map of input nodes by their callback keys so they are fast to locate - the key is unique by device_id, input_id and input_type
                        input_key = input_item.callbackKey()
                        if not input_key in m_input_nodes:
                            m_input_node = ExecutionGraphInputNode()
                            m_input_node.parent = self.graph_input_root
                            m_input_node.input_item = input_item
                            m_input_node.mode = mode_name
                            m_input_nodes[input_key] = m_input_node
                        else:
                            m_input_node = m_input_nodes[input_key]

                        if len(input_item.containers) == 0:
                            # no containers = no actions = skip
                            continue

                        # node holding all the containers in this input - this allows a container to fail while letting the others execute
                        input_container_group = ExecutionGraphGroupNode()
                        input_container_group.parent = input_node

                        container : gremlin.base_profile.AbstractContainer
                        for container in input_item.containers:
                            self._build_container_tree(container, input_container_group, mode_name, device_node, input_item, m_input_node)
                                


        # tell parent nodes if they have an action down each branch so only nodes with mappings get executed
        action_nodes = anytree.findall_by_attr(self.graph, value = ExecutionGraphNodeType.Action, name= "nodeType")
        for action_node in action_nodes:
            # mark ancestors as having actions
            action_node.has_actions = True # action itself
            for node in action_node.ancestors:
                node.has_actions = True # parent branch


        self._input_graph_map = m_input_nodes
            
        
        if verbose:
            self.dump()
            pass
        


    def registerCallbacks(self, callbacks):
        ''' registers execution callbacks 
        
            callbacks for each functor are mapped to the execution tree and a list of condition functors are added
        
        '''
        
        verbose = gremlin.config.Configuration().verbose
        if verbose: syslog.info("Register callbacks in execution tree")
        for device_guid in callbacks:
            for mode in callbacks[device_guid]:
                for key in callbacks[device_guid][mode]:
                    callback : ContainerCallback
                    for callback, _ in callbacks[device_guid][mode][key]:
                        # script based 
                        if hasattr(callback, "id"):
                            id = callback.id
                        else:
                            if self._verbose_exec: syslog.warning(f"EC: cannot find execution node for callback: {callback}")
                            continue

                        if self._verbose_exec: syslog.info(f"Looking for id: {id}")
                        node = next((n for n in anytree.PreOrderIter(self.graph) if  n.nodeType == ExecutionGraphNodeType.Container and n.id == id), None)
                        if node:
                            self.registerNode(node)


        for node in anytree.PreOrderIter(self.graph):
            if node.id in self._functor_map:
                continue # already processed
            if node.nodeType in (ExecutionGraphNodeType.Container,ExecutionGraphNodeType.Action):
                self.registerNode(node)

    def registerNode(self, node):
        ''' registers functors for a given node '''
        functors = self._get_node_functors(node)
        assert isinstance(functors, list),"Functors have to be a list"
        self.functor_map[node.id] = functors
        self._node_map[node.id] = node
        if self._verbose_detailed: 
            logtabs = gremlin.shared_state.logTabs()
            syslog.info(f"{logtabs}Register container node functors node id {node.id} {node.description} : {len(functors)} functors")





    def dumpFunctors(self, functor_list):
        ''' dumps functors to the log file for debug purposes '''
        syslog.info("Functor dump:")
        for item in functor_list:
            syslog.info(f"\t{item}")


    def process_functor(self, functor, event, value, extra_data : dict = None, manual = False) -> bool:
        ''' processes a single functor or a list of functors  - first one to fail fails the group '''
        if isinstance(functor, list):
            for item in functor:
                result = self.process_functor(item, event, value, extra_data, manual)
                if not result:
                    return False
        else:
            if functor.manual_callback and not manual:
                return False
                
            return functor.process_event(event, value, extra_data)

        
    def has_action_for_mode(self, input_item : gremlin.base_profile.InputItem, mode : str):
        ''' true if the input item has a defined action for the given mode '''
        key = input_item.callbackKey()
        if key in self.graph_input_map:
            node = self.graph_input_map[key]


    def execute_node(self, node : ExecutionGraphNode, event, value, extra_data : dict = None,  manual = False) -> bool:
        ''' executes a single node '''

        if not node.has_actions:
            return True # nodes with no actions return PASS

        verbose_exec = self._verbose_exec
        verbose_condition = self._verbose_condition
        try:
            gremlin.shared_state.pushLog()
            logTabs = gremlin.shared_state.logTabs()
            
            if isinstance(node, ExecutionGraphContainerNode):
                pass

           

                
            # abort if the mode changed and the event was fired in a different mode
            if event.mode and event.mode != gremlin.shared_state.runtime_mode:
                if verbose_exec: syslog.info(f"{logTabs}EXEC:[{node.id}] [{node.nodeType.name}] {node.description} - ignoring event due to wrong mode {event.mode} current runtime: {gremlin.shared_state.runtime_mode} ")    
                return False

            result = True

            if not extra_data:
                extra_data = {}
            extra_data["node"] = node

            if verbose_exec:  syslog.info(f"{logTabs}EXEC:[{node.id}] [{node.nodeType.name}] {node.description}")
            
            if node.nodeType in (ExecutionGraphNodeType.Group,ExecutionGraphNodeType.Gate, ExecutionGraphNodeType.Range):
                # group type nodes: every subnode is executed regardless of the return value
                for child in node.children:
                    result = self.execute_node(child, event, value, extra_data, manual)
                    # dont care if result fails for individual groups
                return True # groups always pass 


            elif node.nodeType == ExecutionGraphNodeType.ActivationConditionNexus:
                # activation condition group - pass on the first ok
                for child in node.children:
                    result = self.execute_node(child, event, value, extra_data, manual)
                    if result:
                        # pass the whole group on first group that doesn't fail
                        return True
                return False # all failed

            elif node.nodeType in (ExecutionGraphNodeType.Container, 
                                   ExecutionGraphNodeType.ActivationCondition,
                                   ExecutionGraphNodeType.Condition,
                                   ExecutionGraphNodeType.GatedAxisGateCondition,
                                   ExecutionGraphNodeType.GatedAxisRangeCondition):
                # nodes that have conditions
                condition_functors = node.getConditionFunctors()
                for functor in condition_functors:
                    result =  self.process_functor(functor, event, value, extra_data, manual)
                    if verbose_condition:
                        condition_name = functor.condition_name()
                        if isinstance(functor, gremlin.actions.ActivationCondition):
                            syslog.info(f"{logTabs}>Executed activation condition {condition_name} result: {'PASS' if result else 'FAIL'}")
                        elif isinstance(functor, gremlin.actions.AbstractCondition):
                            syslog.info(f"{logTabs}>Executed condition {condition_name} result: {'PASS' if result else 'FAIL'}")
                if not result:
                    # condition failed
                    return result
                
                
                # if container - execute the container functor if any
                container_functors = node.getActionFunctors()
                result = True
                for functor in container_functors:
                    result = self.process_functor(functor, event, value, extra_data, manual)
                    if isinstance(functor, gremlin.base_conditions.AbstractSelfTriggerFunctor):
                        # do not execute other items because the functor self triggers subsequent nodes as needed
                        return True
                    if not result:
                        # stop execution if the container fires the events internally
                        return result
                    
            elif node.nodeType == ExecutionGraphNodeType.ActionSet:
                # for action sets and go straigh to process children
                pass

            else:
                # action node - if in manual mode - run the children of that node directly
                # any other node - execute the functor list - first one that fails fails the complete branch to this point
                functor_list = node.getActionFunctors()
                if functor_list:
                    for functor in functor_list:
                        action_result =  self.process_functor(functor, event, value, extra_data, manual)
                        description = str(functor.action_data)
                        if verbose_exec: syslog.info(f"{logTabs}>!!! Executed action {functor.__class__.__name__} {description} action result: {'PASS' if action_result else 'FAIL'}")
                            
            # execute children nodes
            if node.children and (node.nodeType != ExecutionGraphNodeType.Action or manual):
                for child in node.children:
                    # if child.nodeType == ExecutionGraphNodeType.ActionSet:
                    #     continue # skip activation sets as the actions are in the container node already
                    result = self.execute_node(child, event, value, extra_data, manual)
                    if not result:
                        break # FAIL

                if not result:
                    # return failure
                    return result
    

            return result
        
        finally:
            if verbose_condition: syslog.info(f"{logTabs}>Overall Result: {'PASS' if result else 'FAIL'}")
            gremlin.shared_state.popLog()


    def execute_functor_id(self, id, event, value, extra_data : dict = None, manual = False) -> bool:
        ''' executes a functor chain 
        
        id = id of the node to execute, the id is also the id of the action or container

        the execution runs through all conditions at that level and returns True on all functors PASS, False on condition (or action) FAIL
        
        '''

        result = True # assume pass
        functor_map = self._functor_map

        if id in functor_map:
            # cache hit
            root = self._node_map[id]

            parent_node = root.parent
            if self.isConditionNode(parent_node):
                root = parent_node # bump to the condition node in case we inserted a condition on the primary node
            result = self.execute_node(root, event, value, extra_data, manual)
        return result
    
    def isConditionNode(self, node : ExecutionGraphNode):
        return node is not None and node.is_condition

class ContainerCallback:

    """Callback object that can perform the actions associated with an input.

    The object uses the concept of a execution graph to handle conditional
    and chained actions.
    """

    def __init__(self, container, parent = None):
        """Creates a new instance based according to the given input item.

        :param container the container instance for which to build th
            execution graph base callback
        """
        if parent is None:
            ec = ExecutionContext()
            parent = ec.graph
        self.container = container
        self.node = None # entry point for this container - set on first call
        self.first_run = True
        self.execution_graph = ContainerExecutionGraph(container, parent)

    def __call__(self, event, value = None, extra_data : dict = None):
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
            InputType.Mouse,
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
            syslog.error("Virtual button code path being used")
        else:
            ec = ExecutionContext()

            if self.first_run and not self.node:
                node = ec.find(self.container)
                if node:
                    # check if container node has an activation condition tied to it at the container level, and use that as the entry point.
                    if node.parent and node.is_condition:
                        node = node.parent
                    self.node = node
                self.first_run = False
            if self.node:
                ec.execute_node(self.node, event, shared_value)


class VirtualButtonCallback(ContainerCallback):

    """VirtualButton event based callback class."""

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        #self._execution_graph = ContainerExecutionGraph(container, parent)

    def __call__(self, event, value = None, extra_data : dict = None):
        if value is None:
            value = gremlin.actions.Value(event.is_pressed)

        event.is_virtual_button = True # tell the functors this is a virtual button
        event.is_axis = False
        return super().__call__(event, value, extra_data)


class VirtualButtonProcess(ContainerCallback):

    """Callback that is responsible for emitting press and release events
    for a virtual button."""

    def __init__(self, container, data):
        """Creates a new instance for the given container.

        :param container the container using a virtual button configuration
        """
        super().__init__(container)
        self.virtual_button = None

        #self.execution_graph = ContainerExecutionGraph(container, parent)

        if isinstance(data, gremlin.base_buttons.VirtualAxisButton):
            self.virtual_button = gremlin.actions.AxisButton(data.lower_limit, data.upper_limit, data.direction)
        elif isinstance(data, gremlin.base_buttons.VirtualHatButton):
            self.virtual_button = gremlin.actions.HatButton(data.directions)
        else:
            raise gremlin.error.GremlinError("Invalid virtual button data provided")

    def __call__(self, event, value = None, extra_data = None):
        """Processes the provided event through the virtual button instance.

        :param event the input event being processed
        """
        verbose = gremlin.config.Configuration().verbose_mode_condition

        if not extra_data:
            extra_data = {}
        if value is None:
            value = gremlin.actions.Value(event.value)
        # verify the virtual button should process based on the event
        result = self.virtual_button._do_process(event)
        if result:
            if verbose: syslog.info("VIRTUALBUTTON: execute PASS")
            extra_data["virtual_button"] = self.virtual_button
            # convert to a fake button
            event.fake_button(self.virtual_button.is_pressed) # issue press or release
            syslog.info(f"VIRTUAL TRIGGER:  pressed: {event.is_pressed}")
            self.__call__(event, value, extra_data)
            return
        #self.virtual_button.process_event(event)

        if verbose: syslog.info("VIRTUALBUTTON: execute FAIL")


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
        self.instance = instance
        if parent is None:
            parent = self.ec.graph
        self._build_graph(instance, parent)
        el = gremlin.event_handler.EventListener()
        el.profile_stop.connect(self._profile_stop)

    @QtCore.Slot()
    def _profile_stop(self):
        # abort if running
        self.run_event.set()


  

    def process_event(self, event, value, extra_data : dict = None):
        """
        
        Runs the execution graph for the input.


        #### CRITICAL EXECUTION PATH ####

        :param event the raw event that caused the execution of this graph
        :param value the possibly modified value extracted from the event


        The list of functors is precomputed by ExecutionContext() when the profile is started as a sequence of functors that each take (event, value) as parameters and return True
        if the execution should continue.  A graph is used to represent all possible execution paths for a profile, including any nested items and dependencies as needed.

        The build phase when the profile starts constructs the execution list in the correct order of evaluation for each bound input.  The hierarchy is observed, so high level conditions get evaluated before lower level conditions.

        Execution list contains functors, which can be grouped.  Grouped functors are evaluated as "any", or "on of" so any PASS (true) value means PASS for the whole group.
        The build phase constructs the groups as needed based on "any" or "all" condition states.
        
        If that at any point a functor returns False, the chain aborts (unless the functor is part of a group of functors, in which case all functors in the group would need to FAIL to fail the whole evaluation).

        The tail end of the functor chain are the actions to execute.  

        This means execution follows the short-cut model if conditions fail.

        """
        return True
    
        self.run_event.clear()

        ec = ExecutionContext()
        # functor_map = ec.functor_map
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_condition
        # validate = verbose
        # verbose_detailed = False
        if verbose:
            gremlin.shared_state.pushLog()

        try:
     
            
            # regular functors
            for functor in self.functors:

                #result = True # assume pass

                if isinstance(functor, gremlin.actions.ActivationCondition):
                    # if not event.is_pressed:
                    #     pass
                    result = functor.process_event(event, value, extra_data)
                    if not result:
                        return False
                    continue # next functor

                id = functor.id
                result = ec.execute_functor_id(id, event, value, extra_data)
                if not result:
                    break
             
            return result
        finally:
            self.graph_completed.emit(self)
            if verbose:
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
        node = ExecutionGraphContainerNode()
        node.container = container
        node.parent = parent
        node.mode = container.profile_mode
    

        container_plugins = gremlin.plugin_manager.ContainerPlugins()

        # If container based conditions exist add them before any actions
        if container.has_conditions: 
            functor = self._create_activation_condition(container.activation_condition, container, is_container_condition = True)
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
        # ec = ExecutionContext()
        # ec.registerNode(node)
        

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
        
        ec = ExecutionContext()
        
        verbose = gremlin.config.Configuration().verbose_mode_details

        sequence = []

        add_default_activation = False

        nodes = {} # list of tree nodes at this level created for each action in the actions sets
        #node_list = []

        # Reorder action set entries such that if any remap action is
        # present it is executed last (after a curving action for example) (unless it's a mode switch action - mode switching must happen last because it changes the action list)
        ordered_action_set = []
        if verbose:
            syslog.info("Ordering action sets:")
        for action in action_set:


            action_set_node = ExecutionGraphActionSetNode()
            action_set_node.parent = parent

            # if not isinstance(action, action_plugins.remap.Remap):
            priority = 0
            if hasattr(action, "priority"):
                priority = action.priority
            ordered_action_set.append((priority, action))
            if verbose:
                syslog.info(f"\tadding action: {type(action)} priority: {priority} data: {str(action)}" )

            node = ExecutionGraphActionNode()
            node.parent = action_set_node
            node.action = action
            functor = ec._get_action_functor(action, node)
            node.functors.append(functor)
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
                functor = self._create_activation_condition(action.activation_condition,action)
                self.functors.append(functor)
                sequence.append("Condition")
                nodes[action].functors.append(functor)

            # Create default activation condition if needed
            has_input_action = self._contains_input_action_condition(action.activation_condition)

            if add_default_activation and not has_input_action:
                condition = gremlin.base_conditions.InputActionCondition()
                condition.comparison = ActionSetExecutionGraph.comparison_map[action.default_button_activation]

                activation_condition = gremlin.base_conditions.ActivationCondition([condition], gremlin.actions.ActivationRule.All)
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
        # ec = ExecutionContext()
        # for node in node_list:
        #     ec.registerNode(node)




