
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
        self._comparison = ""


    @property
    def comparison(self):
        return self._comparison
    
    @comparison.setter
    def comparison(self, value):
        self._comparison = value

    @abstractmethod
    def from_xml(self, node):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        pass

    @abstractmethod
    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        pass

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

    def from_xml(self, node):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        self.comparison = safe_read(node, "comparison")
        self.scan_code = safe_read(node, "scan-code", int)
        self.is_extended = parse_bool(safe_read(node, "extended"))
        input_item = None
        for child in node:
            if child.tag=="input":
                from gremlin.keyboard import Key
                from gremlin.ui.keyboard_device import KeyboardInputItem
                input_item = KeyboardInputItem()
                input_item.parse_xml(child)

        
        self.input_item = input_item

                

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        node = ElementTree.Element("condition")
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

    def from_xml(self, node):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        self.comparison = safe_read(node, "comparison")

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
        node = ElementTree.Element("condition")
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

    def from_xml(self, node):
        """Populates the object with data from an XML node.

        Parameters
        ==========
        node : ElementTree.Element
            XML node to parse for data
        """
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
        node = ElementTree.Element("condition")
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

    def from_xml(self, node):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        self.comparison = safe_read(node, "comparison")

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        node = ElementTree.Element("condition")
        node.set("condition-type", "action")
        node.set("input", "action")
        node.set("comparison", str(self.comparison))
        return node
    

    

class AbstractFunctor(metaclass=ABCMeta):

    """Abstract base class defining the interface for functor like classes.

    These classes are used in the internal code execution system.
    """

    def __init__(self, instance):
        """Creates a new instance, extracting needed information.

        :param instance the object which contains the information needed to
            execute it later on
        """
        import gremlin.event_handler
        self._name = instance.name
        self.enabled = True

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.profile_start)
        el.profile_stop.connect(self.profile_stop)

        

    @abstractmethod
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

    def from_xml(self, node):
        """Extracts activation condition data from an XML node.

        :param node the XML node to parse
        """
        self.rule = ActivationCondition.rule_lookup[safe_read(node, "rule")]
        for cond_node in node.findall("condition"):
            condition_type = safe_read(cond_node, "condition-type")
            condition = ActivationCondition.condition_lookup[condition_type]()
            condition.from_xml(cond_node)
            self.conditions.append(condition)

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