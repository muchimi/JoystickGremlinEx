

from abc import abstractmethod, ABCMeta
import enum
import logging
from lxml import etree as ElementTree
from gremlin.input_types import InputType

from gremlin.util import *

class AbstractVirtualButton(metaclass=ABCMeta):

    """Base class of all virtual buttons."""

    def __init__(self):
        """Creates a new instance."""
        pass

    @abstractmethod
    def from_xml(self, node, data = None):
        """Populates the virtual button based on the node's data.

        :param node the node containing data for this instance
        """
        pass

    @abstractmethod
    def to_xml(self):
        """Returns an XML node representing the data of this instance.

        :return XML node containing the instance's data
        """
        pass


class VirtualAxisButton(AbstractVirtualButton):

    """Virtual button which turns an axis range into a button."""

    def __init__(self, container = None): #, lower_limit=-1.0, upper_limit=1.0, device_guid = None, input_type = None, input_id = None, mode = None, enabled = False):
        """Creates a new instance.

        :param lower_limit the lower limit of the virtual button
        :param upper_limit the upper limit of the virtual button
        """
        from gremlin.types import AxisButtonDirection
        from gremlin.base_profile import AbstractContainer
        import gremlin.shared_state
        container: AbstractContainer = container
        super().__init__()
        self.lower_limit = -1
        self.upper_limit = 1
        self.direction = AxisButtonDirection.Anywhere
        self.device_guid = container.device_guid # associated device
        self.input_id = container.get_input_id()
        self.mode = gremlin.shared_state.current_mode
        self.input_type = container.get_input_type()
        self.container = container

    @property
    def enabled(self) -> bool:
        return self.container.virtual_button_enabled
    @enabled.setter
    def enabled(self, value : bool):
        import gremlin.event_handler
        self.container.virtual_button_user_enabled = value
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.emit(self.container) # updates the UI status flags

    @property
    def range(self):
        return [self.lower_limit, self.upper_limit]
    
    def from_xml(self, node, data = None):
        """Populates the virtual button based on the node's data.

        :param node the node containing data for this instance
        """

        # grab the device GUID this applies to
        device_guid, input_type, input_id, mode = get_xml_input_data(node)
        self.device_guid = device_guid
        self.input_type = input_type
        self.mode = mode
        self.input_id = input_id


        from gremlin.types import AxisButtonDirection
        self.lower_limit = safe_read(node, "lower-limit", float, -1.0)
        self.upper_limit = safe_read(node, "upper-limit", float, 1.0)
        self.direction = AxisButtonDirection.to_enum(
            safe_read(node, "direction", default_value="anywhere")
        )
        self.enabled = safe_read(node,"enabled", bool, False)

    def to_xml(self):
        """Returns an XML node representing the data of this instance.

        :return XML node containing the instance's data
        """
        from gremlin.types import AxisButtonDirection
        node = ElementTree.Element("virtual-button")
        node.set("lower-limit", str(self.lower_limit))
        node.set("upper-limit", str(self.upper_limit))
        node.set("direction",AxisButtonDirection.to_string(self.direction))
        node.set("enabled", str(self.enabled))
        return node


class VirtualHatButton(AbstractVirtualButton):

    """Virtual button which combines hat directions into a button."""

    # Mapping from event directions to names
    direction_to_name = {
        ( 0,  0): "center",
        ( 0,  1): "north",
        ( 1,  1): "north-east",
        ( 1,  0): "east",
        ( 1, -1): "south-east",
        ( 0, -1): "south",
        (-1, -1): "south-west",
        (-1,  0): "west",
        (-1,  1): "north-west"
    }

    # Mapping from names to event directions
    name_to_direction = {
        "center": (0, 0),
        "north": (0, 1),
        "north-east": (1, 1),
        "east": (1, 0),
        "south-east": (1, -1),
        "south": (0, -1),
        "south-west": (-1, -1),
        "west": (-1, 0),
        "north-west": (-1, 1)
    }

    def __init__(self, container,  directions=()): #, device_guid = None, input_type = None, input_id = None, mode = None):
        """Creates a instance.

        :param directions list of direction that form the virtual button
        """
        super().__init__()
        from gremlin.base_profile import AbstractContainer
        import gremlin.shared_state
        container: AbstractContainer = container
        self.directions = list(set(directions))
        self.device_guid =  container.device_guid
        self.input_type = InputType.JoystickHat
        self.input_id = container.get_input_id()
        self.mode = gremlin.shared_state.current_mode
        self.input_type = container.get_input_type()
        self.container = container

    def from_xml(self, node, data = None):
        """Populates the activation condition based on the node's data.

        :param node the node containing data for this instance
        """

        device_guid, input_type, input_id, mode = get_xml_input_data(node)
        self.device_guid = device_guid
        self.input_type = input_type
        self.mode = mode
        self.input_id = input_id

        for key, value in node.items():
            if key in VirtualHatButton.name_to_direction and \
                            parse_bool(value):
                self.directions.append(key)

    def to_xml(self):
        """Returns an XML node representing the data of this instance.

        :return XML node containing the instance's data
        """
        node = ElementTree.Element("virtual-button")
        for direction in self.directions:
            if direction in VirtualHatButton.name_to_direction:
                node.set(direction, "1")
        return node