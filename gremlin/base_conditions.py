from __future__ import annotations
from abc import ABCMeta
import logging
from lxml import etree as ElementTree
import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.util
from gremlin.util import safe_read, parse_bool, parse_guid, write_guid
from PySide6 import QtCore
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import ActivationRule
import dinput

syslog = logging.getLogger("system")


class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass


class AbstractCondition(QtCore.QObject, metaclass=ABCMetaQObject):
    """Base class of all individual condition representations."""

    id_changed = QtCore.Signal(str, str)  # triggers when the ID changes

    def __init__(self):
        """Creates a new condition."""
        super().__init__()
        import gremlin.util

        self._id = gremlin.util.get_guid()
        self._comparison = ""
        self._id = None  # unique ID of this condition

    @property
    def id(self):
        """unique ID for this condition, persisted"""
        if not self._id:
            import gremlin.util

            self._id = gremlin.util.get_guid()
        return self._id

    @id.setter
    def id(self, new_id):
        """changes the ID"""
        old_id = self._id
        if old_id != new_id:
            self._id = new_id
            self.id_changed.emit(old_id, new_id)

    @property
    def comparison(self):
        return self._comparison

    @comparison.setter
    def comparison(self, value):
        self._comparison = value

    def from_xml(self, node, data=None):
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
        self.comparison = "pressed"

    def from_xml(self, node, data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """

        super().from_xml(node, data)
        self.comparison = safe_read(node, "comparison")
        self.scan_code = safe_read(node, "scan-code", int)
        self.is_extended = parse_bool(safe_read(node, "extended"))
        input_item = None
        for child in node:
            if child.tag == "input":
                from gremlin.ui.keyboard_device import KeyboardInputItem

                input_item = KeyboardInputItem()
                input_item.parse_xml(child, data)

        self.input_item = input_item

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        node = super().to_xml()  # ElementTree.Element("condition")
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
        return (
            super().is_valid()
            and self.scan_code is not None
            and self.is_extended is not None
        )

    def __str__(self):
        from gremlin.ui.keyboard_device import Key

        key = Key(scan_code=self.scan_code, is_extended=self.is_extended)
        return f"Keyboard condition: id: {self.id} comparison: {self.comparison} key {key.debug_name}"


class JoystickCondition(AbstractCondition):
    """Joystick state based condition.

    This condition is based on the state of a joystick axis, button, or hat.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self.device_guid = 0  # use this as the invalid GUID
        self.input_type = None
        self.input_id = 0
        self.range = [0.0, 0.0]
        self.device_name = ""
        self.use_calibrated_data = (
            True  # true if the input should use the calibrated data if any
        )

    def from_xml(self, node, data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """

        super().from_xml(node, data)

        self.input_type = InputType.to_enum(safe_read(node, "input", str, ""))
        comparison = safe_read(node, "comparison", str, "")
        if not comparison:
            match self.input_type:
                case InputType.JoystickAxis:
                    comparison = "inside"
                case InputType.JoystickButton:
                    comparison = "pressed"
                case InputType.JoystickHat:
                    comparison = "center"
        self.comparison = comparison

        self.input_id = safe_read(node, "id", int, 1)
        self.device_guid = parse_guid(node.get("device-guid"))
        self.device_name = safe_read(node, "device-name", str, "")
        self.range = [
            safe_read(node, "range-low", float, 0),
            safe_read(node, "range-high", float, 0),
        ]
        self.use_calibrated_data = safe_read(node, "use-calibrated", bool, False)

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        # node = ElementTree.Element("condition")
        node = super().to_xml()
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "joystick")
        node.set("input", InputType.to_string(self.input_type))
        node.set("id", str(self.input_id))
        node.set("device-guid", write_guid(self.device_guid))
        node.set("device-name", str(self.device_name))
        node.set("range-low", str(self.range[0]))
        node.set("range-high", str(self.range[1]))

        node.set("use-calibrated", str(self.use_calibrated_data))
        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return (
            self.input_type is not None
        )  # super().is_valid() and self.input_type is not None

    def __str__(self):
        return f"Joystick Condition: id: {self.id} comparison: {self.comparison} input type: {self.input_type.name} device: {self.device_name} input id: {self.input_id}  range: [{self.range[0]:0.3f},{self.range[0]:0.3f}]  use calibrated: {self.use_calibrated_data}"


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

    def from_xml(self, node, data=None):
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
        self.range = [
            safe_read(node, "range-low", float, 0),
            safe_read(node, "range-high", float, 0),
        ]

    def to_xml(self):
        """Returns an XML node containing the objects data.

        Return
        ======
        ElementTree.Element
            XML node containing the object's data
        """
        # node = ElementTree.Element("condition")
        node = super().to_xml()
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "vjoy")
        node.set("input", InputType.to_string(self.input_type))
        node.set("id", str(self.input_id))
        node.set("vjoy-id", write_guid(self.vjoy_id))
        node.set("range-low", str(self.range[0]))
        node.set("range-high", str(self.range[1]))

        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and self.input_type is not None

    def __str__(self):
        return f"Vjoy Condition: id: {self.id} comparison: {self.comparison} input type: {self.input_type.name} vjoy device: {self.vjoy_id} input id: {self.input_id}  range: [{self.range[0]:0.3f},{self.range[0]:0.3f}]"


class InputActionCondition(AbstractCondition):
    """Input item press / release state based condition.

    The condition is for the current input item, triggering based on whether
    or not the input item is being pressed or released.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()

    def from_xml(self, node, data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        super().from_xml(node, data)
        self.comparison = safe_read(node, "comparison")

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        # node = ElementTree.Element("condition")
        node = super().to_xml()
        node.set("condition-type", "action")
        node.set("input", "action")
        node.set("comparison", str(self.comparison))
        return node

    def __str__(self):
        return f"Input Condition: id: {self.id} comparison: {self.comparison}"


class AbstractFunctor(QtCore.QObject):
    """Abstract base class defining the interface for functor like classes.

    These classes are used in the internal code execution system.
    """

    functor_complete = (
        QtCore.Signal()
    )  # fires when a functor has completed its execution completely

    def __init__(self, action_data, parent=None):
        """Creates a new instance, extracting needed information.

        :param instance the object which contains the information needed to
            execute it later on
        """
        import gremlin.event_handler

        super().__init__()

        self._name = action_data.name
        self.enabled = True
        self.node = parent
        self.action_data = action_data
        self.id = action_data.id
        self.manual_callback = False  # functor uses automatic mode

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.profile_start)
        el.profile_stop.connect(self.profile_stop)
        el.abort.connect(self.profile_stop)  # abort also stops the profile

    def process_event(self, event, value, extra_data=None):
        """Processes the functor using the provided event and value data.

        :param event the raw event that caused the functor to be executed
        :param value the possibly modified value

        returns: True to continute the execution sequence, False to abort it

        """
        pass

    def profile_start(self):
        """called when the profile starts"""
        pass

    def profile_stop(self):
        """called when the profile stops"""
        pass

    @property
    def profile_mode(self) -> str:
        """gets the mode of this action"""
        return self.action_data.get_mode()

    @property
    def hardware_device_guid(self) -> dinput.GUID:
        """gets the currently attached hardware GUID"""
        return self.action_data.hardware_device_guid

    @property
    def hardware_device_id(self) -> str:
        """gets the currently attached hardware GUID"""
        return self.action_data.hardware_device_id

    @property
    def hardware_input_id(self):
        return self.action_data.hardware_input_id

    @property
    def hardware_input_type(self) -> InputType:
        return self.action_data.hardware_input_type

    def latch_extra_inputs(self):
        """returns any extra inputs as a list of (device_guid, input_id) to latch to this action (trigger on change)"""
        return []

    def getContainerNode(self):
        """gets the container node the action belongs to"""
        import gremlin.execution_graph

        if self.node:
            container_node = None
            for node in self.node.ancestors:
                if (
                    node.nodeType
                    == gremlin.execution_graph.ExecutionGraphNodeType.Container
                ):
                    return node
        return None

    def getSiblings(self) -> list:
        """gets action node siblings"""
        import gremlin.execution_graph

        container_node = self.getContainerNode()
        nodes = []
        if container_node:
            # grab all the curve nodes attached to that container
            for node in container_node.descendants:
                if (
                    node.nodeType
                    == gremlin.execution_graph.ExecutionGraphNodeType.Action
                ):
                    nodes.append(node)
        return nodes

    def _check_for_auto_release(self, action):
        """auto release check for functors"""
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

    def __str__(self):
        if self.action_data:
            return str(self.action_data)
        return "Plugin Functor"


class AbstractContainerActionFunctor(AbstractFunctor):
    """used by action functors for actions that have containers"""

    def process_event(self, event, value, extra_data=None):
        """Processes the functor using the provided event"""
        result = True
        for functor in self.action_data.functors:
            # only fire the appropriate type
            if functor.enabled:
                # only fire if the functor is enabled (functor is enabled when the plugin is found in the execution structure when a profile starts)
                result = functor.process_event(event, value)
                if not result:
                    break

        return result


class ConditionTrackerData:
    def __init__(self, mode, input_item, container, condition, rule):
        self.condition = condition
        self.container = container
        self.input_item = input_item
        self.mode = mode
        self.rule = rule


@SingletonDecorator
class ConditionTracker:
    """tracks conditions"""

    def __init__(self):
        import gremlin.event_handler

        self._cache = {}  # map of known conditions keyed by mode and condition ID
        self._owner_map = {}  # map of condition ID to its input item owner so we know which input item has which condition
        self._data_map = {}  # map of condition ID to tracker data
        self._el = gremlin.event_handler.EventListener()
        self._el.shutdown.connect(self.reset)
        self._el.profile_unloaded.connect(self.reset)

    @QtCore.Slot()
    def reset(self):
        """triggered on app exit or profile unload"""
        self._cache.clear()
        self._owner_map.clear()
        self._data_map.clear()

    def registerCondition(self, data: ConditionTrackerData):
        """registers a condition and its owner - owner is an input_item"""
        mode = data.mode
        condition = data.condition
        input_item = data.input_item
        if mode not in self._cache:
            self._cache[mode] = {}
        self._cache[mode][condition.id] = data
        self._owner_map[condition.id] = input_item
        self._data_map[condition.id] = data
        self._el.condition_added.emit(input_item, mode, condition)
        self._el.condition_state_changed.emit(data.container)
        verbose = gremlin.config.Configuration().verbose_mode_condition
        if verbose:
            syslog = logging.getLogger("system")
            syslog.info(
                f"creating condition: {condition.id} for input: {data.input_item.display_name if hasattr(data.input_item,"display_name") else data.input_item} mode: {data.mode}"
            )
        data.condition.id_changed.connect(self._condition_id_changed)

    @QtCore.Slot(str, str)
    def _condition_id_changed(self, old_id, new_id):
        """handle an ID swap for the condition in the tracking objects"""
        if old_id in self._owner_map:
            input_item = self._owner_map[old_id]
            self._owner_map[new_id] = input_item
            del self._owner_map[old_id]
            data = self._data_map[old_id]
            self._data_map[new_id] = data
            del self._data_map[old_id]

    def unregisterCondition(self, condition: AbstractCondition):
        """unregisters a condition"""
        syslog = logging.getLogger("system")
        syslog.info(f"delete condition: {condition.id}")
        id = condition.id
        for mode in self._cache:
            if id in self._cache[mode]:
                data = self._cache[mode][id]
                del self._cache[mode][id]
                del self._owner_map[id]
                # (input_item, mode, condition)
                self._el.condition_removed.emit(
                    data.input_item, data.mode, data.condition
                )
                self._el.condition_state_changed.emit(data.container)
                return

    def count(self):
        """gets a count of registered conditions"""
        return len(self._cache)

    def getInputItemConditionCount(self, input_item, mode: str = None):
        """gets a count of registered condition for a specific owner - owner is an input_item"""
        import gremlin.shared_state

        if not mode:
            mode = gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [
                item.condition.id
                for item in self._cache[mode].values()
                if item.input_item == input_item
            ]
            return len(id_list)
        return 0

    def getContainerConditionCount(self, container, mode: str = None):
        """gets a count of registered condition for a specific owner - owner is an input_item"""
        import gremlin.shared_state

        if not mode:
            mode = gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [
                item.condition.id
                for item in self._cache[mode].values()
                if item.container == container
            ]
            return len(id_list)
        return 0

    def getConditionInputItem(self, condition: AbstractCondition):
        """gets the input item attached to a condition"""
        id = condition.id
        if id in self._owner_map:
            return self._owner_map[id]
        return None

    def getConditionsForInputItem(self, input_item, mode: str):
        """checks to see if conditions are defined for this input item"""
        import gremlin.shared_state

        if not mode:
            mode = gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [
                id for id, item in self._owner_map[mode].items() if item == input_item
            ]
            conditions = [self._cache[mode][id] for id in id_list]
            return conditions
        return None

    def getConditionForAction(self, action):
        """gets a condition for an action"""
        data: ConditionTrackerData = self.getActionData(action)
        if data:
            return data.condition
        return None

    def getRuleForAction(self, action):
        """gets the condition rule for an action"""
        data: ConditionTrackerData = self.getActionData(action)
        if data:
            return data.rule
        return None

    def owner(self, condition: AbstractCondition):
        """what input item owns the condition"""
        if condition.id in self._cache:
            return self._owner_map[condition.id]
        return None

    def getData(self, condition: AbstractCondition):
        """gets the condition tracking data"""
        if condition.id in self._data_map:
            return self._data_map[condition.id]
        return None

    def getActionData(self, action):
        if action.action_id in self._data_map:
            return self._data_map[action.action_id]
        return None


class ActivationCondition(QtCore.QObject):
    """Dictates under what circumstances an associated code can be executed."""

    id_changed = QtCore.Signal(str, str)  # fires when id changes (old_id, new_id)

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
        super().__init__()
        self._rule = rule
        self.conditions = conditions
        self._id = gremlin.util.get_guid()

    @property
    def rule(self) -> ActivationRule:
        # rule for the activation condition
        return self._rule

    @rule.setter
    def rule(self, value: ActivationRule):
        self._rule = value

    @property
    def id(self):
        """unique ID for this condition, persisted"""
        if not self._id:
            import gremlin.util

            self._id = gremlin.util.get_guid()

        return self._id

    @id.setter
    def id(self, new_id):
        old_id = self._id
        if old_id != new_id:
            self._id = new_id
            self.id_changed.emit(old_id, new_id)

    def from_xml(self, node, data=None):
        """Extracts activation condition data from an XML node.

        :param node: the XML node to parse
        :param data: tuple containing (input_item, container) associated with this condition
        """
        import gremlin.base_profile
        import gremlin.ui.ui_common

        if "condition_id" in node.attrib:
            str_id = node.get("condition_id")
            if str_id:
                self._id = str_id

        rule = ActivationCondition.rule_lookup[safe_read(node, "rule")]
        tracker = ConditionTracker()
        mode_node = node
        while mode_node is not None and mode_node.tag != "mode":
            mode_node = mode_node.getparent()
        if mode_node is not None:
            mode = mode_node.get("name")
        else:
            import gremlin.shared_state

            mode = gremlin.shared_state.edit_mode
        assert (
            data is not None
        ), "XML: error: data not provided for activation condition"
        input_item, container = data
        self.rule = rule

        # assert input_item is not None,"XML: error:input_item not provided for activation condition"
        if input_item is None:
            gremlin.ui.ui_common.MessageBox(
                prompt="The source action does not support pasting conditions to the new input."
            )
            return

        for cond_node in node.findall("condition"):
            condition_type = safe_read(cond_node, "condition-type")
            condition = ActivationCondition.condition_lookup[condition_type]()
            condition.from_xml(cond_node, data)
            self.conditions.append(condition)
            item = ConditionTrackerData(mode, input_item, container, condition, rule)
            tracker.registerCondition(item)

    def to_xml(self):
        """Returns an XML node containing the activation condition information.

        :return XML node containing information about the activation condition
        """
        node = ElementTree.Element("activation-condition")
        node.set("rule", ActivationCondition.rule_lookup[self._rule])
        node.set("condition_id", self._id)

        for condition in self.conditions:
            # save the condition, valid or not so the data is saved
            node.append(condition.to_xml())
        return node

    def condition_name(self):
        return f"Activation Condition: [{self.id}] rule: {self._rule.name} contains: {len(self.conditions)} condition(s)"

    def __str__(self):
        return f"Activation Condition: [{self.id}] rule: {self._rule.name} contains: {len(self.conditions)} condition(s)"
