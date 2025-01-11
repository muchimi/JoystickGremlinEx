from __future__ import annotations
from abc import abstractmethod, ABCMeta
import enum
import logging
from lxml import etree as ElementTree
from gremlin.input_types import InputType
from gremlin.util import *


class ActivationRule(enum.Enum):

    """Activation rules for collections of conditions.

    All requires all the conditions in a collection to evaluate to True while
    Any only requires a single condition to be True.
    """

    All = 1
    Any = 2





class AbstractCondition(metaclass=ABCMeta):

    """Base class of all individual condition representations."""

    def __init__(self):
        """Creates a new condition."""
        import gremlin.util
        self._id = gremlin.util.get_guid()
        self._comparison = ""
        self._id = None # unique ID of this condition
        
    @property
    def id(self):
        ''' unique ID for this condition, persisted '''
        if not self._id:
            import gremlin.util
            self._id = gremlin.util.get_guid()
        return self._id

    @property
    def comparison(self):
        return self._comparison
    
    @comparison.setter
    def comparison(self, value):
        self._comparison = value

    
    def from_xml(self, node, data = None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        if "condition_id" in node.attrib:
            str_id = node.get("condition_id")
            if str_id:
                self._id = str_id

        

    
    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        node = ElementTree.Element("condition")
        node.set("condition_id", self._id)
        return node
        

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return self._comparison != ""


class KeyboardCondition(AbstractCondition):

    """Keyboard state based condition.

    The condition is for a single key and as such contains the key's scan
    code as well as the extended flag.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self.input_item = None
        self.scan_code = None
        self.is_extended = None

    def from_xml(self, node, data = None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """

        super().from_xml(node, data)
        self.comparison = safe_read(node, "comparison")
        self.scan_code = safe_read(node, "scan-code", int)
        self.is_extended = parse_bool(safe_read(node, "extended"))
        input_item = None
        for child in node:
            if child.tag=="input":
                from gremlin.keyboard import Key
                from gremlin.ui.keyboard_device import KeyboardInputItem
                input_item = KeyboardInputItem()
                input_item.parse_xml(child, data)

        
        self.input_item = input_item

                

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        node = super().to_xml() #ElementTree.Element("condition")
        node.set("condition-type", "keyboard")
        node.set("input", "keyboard")
        node.set("comparison", str(self.comparison))
        node.set("scan-code", str(self.scan_code))
        node.set("extended", str(self.is_extended))
        
        if self.input_item:
            child = self.input_item.to_xml()
            node.append(child)

        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and \
            self.scan_code is not None and \
            self.is_extended is not None
    




class JoystickCondition(AbstractCondition):

    """Joystick state based condition.

    This condition is based on the state of a joystick axis, button, or hat.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self.device_guid = 0
        self.input_type = None
        self.input_id = 0
        self.range = [0.0, 0.0]
        self.device_name = ""

    def from_xml(self, node, data = None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        self.comparison = safe_read(node, "comparison")

        super().from_xml(node, data)

        self.input_type = InputType.to_enum(safe_read(node, "input"))
        self.input_id = safe_read(node, "id", int)
        self.device_guid = parse_guid(node.get("device-guid"))
        self.device_name = safe_read(node, "device-name")
        if self.input_type == InputType.JoystickAxis:
            self.range = [
                safe_read(node, "range-low", float),
                safe_read(node, "range-high", float)
            ]

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        #node = ElementTree.Element("condition")
        node = super().to_xml() 
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "joystick")
        node.set("input", InputType.to_string(self.input_type))
        node.set("id", str(self.input_id))
        node.set("device-guid", write_guid(self.device_guid))
        node.set("device-name", str(self.device_name))
        if self.input_type == InputType.JoystickAxis:
            node.set("range-low", str(self.range[0]))
            node.set("range-high", str(self.range[1]))
        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and self.input_type is not None

class VJoyCondition(AbstractCondition):

    """vJoy device state based condition.

    This condition is based on the state of a vjoy axis, button, or hat.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self.vjoy_id = 0
        self.input_type = None
        self.input_id = 0
        self.range = [0.0, 0.0]

    def from_xml(self, node, data = None):
        """Populates the object with data from an XML node.

        Parameters
        ==========
        node : ElementTree.Element
            XML node to parse for data
        """

        super().from_xml(node, data)
        self.comparison = safe_read(node, "comparison")

        self.input_type = InputType.to_enum(safe_read(node, "input"))
        self.input_id = safe_read(node, "id", int)
        self.vjoy_id = safe_read(node, "vjoy-id", int)
        if self.input_type == InputType.JoystickAxis:
            self.range = [
                safe_read(node, "range-low", float),
                safe_read(node, "range-high", float)
            ]

    def to_xml(self):
        """Returns an XML node containing the objects data.

        Return
        ======
        ElementTree.Element
            XML node containing the object's data
        """
        #node = ElementTree.Element("condition")
        node = super().to_xml() 
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "vjoy")
        node.set("input", InputType.to_string(self.input_type))
        node.set("id", str(self.input_id))
        node.set("vjoy-id", write_guid(self.vjoy_id))
        if self.input_type == InputType.JoystickAxis:
            node.set("range-low", str(self.range[0]))
            node.set("range-high", str(self.range[1]))
        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and self.input_type is not None

 


class InputActionCondition(AbstractCondition):

    """Input item press / release state based condition.

    The condition is for the current input item, triggering based on whether
    or not the input item is being pressed or released.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()

    def from_xml(self, node, data = None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        super().from_xml(node, data)
        self.comparison = safe_read(node, "comparison")
        

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        #node = ElementTree.Element("condition")
        node = super().to_xml() 
        node.set("condition-type", "action")
        node.set("input", "action")
        node.set("comparison", str(self.comparison))
        return node

   


class AbstractFunctor(QtCore.QObject):

    """Abstract base class defining the interface for functor like classes.

    These classes are used in the internal code execution system.
    """

    functor_complete = QtCore.Signal() # fires when a functor has completed its execution completely

    def __init__(self, action_data, parent = None):
        """Creates a new instance, extracting needed information.

        :param instance the object which contains the information needed to
            execute it later on
        """
        import gremlin.event_handler

        super().__init__()

        self._name = action_data.name
        self.enabled = True
        self.node = parent
        

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.profile_start)
        el.profile_stop.connect(self.profile_stop)
        el.abort.connect(self.profile_stop) # abort also stops the profile

        

    
    def process_event(self, event, value):
        """Processes the functor using the provided event and value data.

        :param event the raw event that caused the functor to be executed
        :param value the possibly modified value

        returns: True to continute the execution sequence, False to abort it

        """
        pass

    def profile_start(self):
        ''' called when the profile starts '''
        pass

    def profile_stop(self):
        ''' called when the profile stops '''
        pass
    

    def latch_extra_inputs(self):
        ''' returns any extra inputs as a list of (device_guid, input_id) to latch to this action (trigger on change) '''
        return []
    
    def getContainerNode(self):
        ''' gets the container node the action belongs to '''
        import gremlin.execution_graph
        if self.node:
            container_node = None
            for node in self.node.ancestors:
                if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.Container:
                    return node
        return None
    
    def getSiblings(self) -> list:
        ''' gets action node siblings'''
        import gremlin.execution_graph
        container_node = self.getContainerNode()
        nodes = []
        if container_node:
            # grab all the curve nodes attached to that container
            for node in container_node.descendants:
                if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.Action:
                    nodes.append(node)
        return nodes


    def _check_for_auto_release(self, action):
        ''' auto release check for functors '''
        activation_condition = None
        if action.parent.activation_condition:
            activation_condition = action.parent.activation_condition
        elif action.activation_condition:
            activation_condition = action.activation_condition

        # If an input action activation condition is present the auto release
        # may have to be disabled
        needs_auto_release = True
        if activation_condition:
            for condition in activation_condition.conditions:
                if isinstance(condition, InputActionCondition):
                    # Remap like actions typically have an always activation
                    # condition associated with them
                    if condition.comparison != "always":
                        needs_auto_release = False

        return needs_auto_release


class AbstractContainerActionFunctor(AbstractFunctor):
    ''' used by action functors for actions that have containers '''
    def process_event(self, event, value):
        ''' Processes the functor using the provided event '''
        result = True
        for functor in self.action_data.functors:
            # only fire the appropriate type
            if functor.enabled:
                # only fire if the functor is enabled (functor is enabled when the plugin is found in the execution structure when a profile starts)
                result = functor.process_event(event, value)
                if not result:
                    break

        return result
    

class ConditionTrackerData():
    def __init__(self, mode, input_item, container, condition):
        self.condition = condition
        self.container = container
        self.input_item = input_item
        self.mode = mode
    
@SingletonDecorator
class ConditionTracker():
    ''' tracks conditions '''
    def __init__(self):
        import gremlin.event_handler
        self._cache = {} # map of known conditions keyed by mode and condition ID
        self._owner_map = {} # map of condition ID to its input item owner so we know which input item has which condition
        self._el = gremlin.event_handler.EventListener()
        self._el.shutdown.connect(self.reset)
        self._el.profile_unloaded.connect(self.reset)
        
    @QtCore.Slot()
    def reset(self):
        ''' triggered on app exit or profile unload '''
        self._cache.clear()
        self._owner_map.clear()



    def registerCondition(self, data : ConditionTrackerData):
        ''' registers a condition and its owner - owner is an input_item'''
        mode = data.mode
        condition = data.condition
        input_item = data.input_item
        if not mode in self._cache:
            self._cache[mode] = {}
        self._cache[mode][condition.id] = data
        self._owner_map[condition.id] = input_item
        self._el.condition_added.emit(input_item, mode, condition)
        self._el.condition_state_changed.emit(data.container)
        syslog = logging.getLogger("system")
        syslog.info(f"creating condition: {condition.id} for input: {data.input_item.display_name} mode: {data.mode}")
        

    def unregisterCondition(self, condition : AbstractCondition):
        ''' unregisters a condition '''
        syslog = logging.getLogger("system")
        syslog.info(f"delete condition: {condition.id}")
        id = condition.id
        for mode in self._cache:
            if id in self._cache[mode]:
                data = self._cache[mode][id]
                del self._cache[mode][id]
                del self._owner_map[id]
                # (input_item, mode, condition)
                self._el.condition_removed.emit(data.input_item, data.mode, data.condition)
                self._el.condition_state_changed.emit(data.container)
                return
            

    def count(self):
        ''' gets a count of registered conditions '''
        return len(self._cache)
    
    def getInputItemConditionCount(self, input_item, mode : str = None):
        ''' gets a count of registered condition for a specific owner - owner is an input_item'''
        import gremlin.shared_state
        if not mode:
            mode = gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [item.condition.id for item in self._cache[mode].values() if item.input_item == input_item]
            return len(id_list)
        return 0
    
    def getContainerConditionCount(self, container, mode : str = None):
        ''' gets a count of registered condition for a specific owner - owner is an input_item'''
        import gremlin.shared_state
        if not mode:
            mode = gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [item.condition.id for item in self._cache[mode].values() if item.container == container]
            return len(id_list)
        return 0

    
    def getConditionInputItem(self, condition : AbstractCondition):
        ''' gets the input item attached to a condition '''
        id = condition.id
        if id in self._owner_map:
            return self._owner_map[id]
        return None
    
    def getConditionsForInputItem(self, input_item, mode : str): 
        ''' checks to see if conditions are defined for this input item'''
        import gremlin.shared_state
        if not mode:
            mode = gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [id for id, item in self._owner_map[mode].items() if item == input_item]
            conditions = [self._cache[mode][id] for id in id_list]
            return conditions
        return None





    
    def owner(self, condition : AbstractCondition):
        ''' what input item owns the condition '''
        if condition.id in self._cache:
            return self._owner_map[condition.id]
        return None

        
        


class ActivationCondition:

    """Dictates under what circumstances an associated code can be executed."""

    rule_lookup = {
        # String to enum
        "all": ActivationRule.All,
        "any": ActivationRule.Any,
        # Enum to string
        ActivationRule.All: "all",
        ActivationRule.Any: "any",
    }

    condition_lookup = {
        "keyboard": KeyboardCondition,
        "joystick": JoystickCondition,
        "vjoy": VJoyCondition,
        "action": InputActionCondition,
    }

    def __init__(self, conditions, rule):
        """Creates a new instance."""
        self.rule = rule
        self.conditions = conditions

    def from_xml(self, node, data = None):
        """Extracts activation condition data from an XML node.

        :param node: the XML node to parse
        :param data: tuple containing (input_item, container) associated with this condition
        """
        import gremlin.base_profile
        self.rule = ActivationCondition.rule_lookup[safe_read(node, "rule")]
        tracker = ConditionTracker()
        mode_node = node
        while mode_node is not None and mode_node.tag != "mode":
            mode_node = mode_node.getparent()
        mode = mode_node.get("name")
        input_item, container = data
        for cond_node in node.findall("condition"):
            condition_type = safe_read(cond_node, "condition-type")
            condition = ActivationCondition.condition_lookup[condition_type]()
            condition.from_xml(cond_node, data)
            self.conditions.append(condition)
            item = ConditionTrackerData(mode, input_item, container, condition)
            tracker.registerCondition(item)
            
            

    def to_xml(self):
        """Returns an XML node containing the activation condition information.

        :return XML node containing information about the activation condition
        """
        node = ElementTree.Element("activation-condition")
        node.set("rule", ActivationCondition.rule_lookup[self.rule])

        for condition in self.conditions:
            if condition.is_valid():
                node.append(condition.to_xml())
        return node