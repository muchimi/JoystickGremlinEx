

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
    def from_xml(self, node):
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

    def __init__(self, lower_limit=0.0, upper_limit=0.0):
        """Creates a new instance.

        :param lower_limit the lower limit of the virtual button
        :param upper_limit the upper limit of the virtual button
        """
        from gremlin.types import AxisButtonDirection
        super().__init__()
        self.lower_limit = lower_limit
        self.upper_limit = upper_limit
        self.direction = AxisButtonDirection.Anywhere

    def from_xml(self, node):
        """Populates the virtual button based on the node's data.

        :param node the node containing data for this instance
        """
        from gremlin.types import AxisButtonDirection
        self.lower_limit = safe_read(node, "lower-limit", float)
        self.upper_limit = safe_read(node, "upper-limit", float)
        self.direction = AxisButtonDirection.to_enum(
            safe_read(node, "direction", default_value="anywhere")
        )

    def to_xml(self):
        """Returns an XML node representing the data of this instance.

        :return XML node containing the instance's data
        """
        from gremlin.types import AxisButtonDirection
        node = ElementTree.Element("virtual-button")
        node.set("lower-limit", str(self.lower_limit))
        node.set("upper-limit", str(self.upper_limit))
        node.set(
            "direction",
            AxisButtonDirection.to_string(self.direction)
        )
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

    def __init__(self, directions=()):
        """Creates a instance.

        :param directions list of direction that form the virtual button
        """
        super().__init__()
        self.directions = list(set(directions))

    def from_xml(self, node):
        """Populates the activation condition based on the node's data.

        :param node the node containing data for this instance
        """
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