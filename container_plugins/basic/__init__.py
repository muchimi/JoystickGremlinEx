# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
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


import gremlin
import gremlin.config
from gremlin.input_types import InputType

import gremlin.ui.ui_common
import gremlin.types
from gremlin.types import ContainerViewTypes, Interactions
from gremlin.base_profile import AbstractFunctor
from gremlin.input_item import AbstractContainer, AbstractAction, AbstractContainerWidget, InputItem, ActionSelector
from shiboken6 import Shiboken
from gremlin.worker import WorkManager, WorkTask
import logging

syslog = logging.getLogger("system")


class BasicContainerWidget(AbstractContainerWidget):
    """Basic container which holds a single action."""

    def __init__(self, input_item: InputItem, container: AbstractContainer, parent=None):
        """Creates a new instance.

        :param input_item the input item represented by this widget
        :param container the container represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(input_item, container, parent, view=True)
        self.container = container
        self.input_item = input_item


    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        pass

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        title = "Basic: "
        if len(self.container.action_sets) > 0:
            stub = ", ".join(a.name for a in self.container.action_sets[0])
            title += stub

        return title


class BasicContainerFunctor(AbstractFunctor):
    """Executes the contents of the associated basic container."""

    def __init__(self, container, parent=None):
        super().__init__(container, parent)

    def process_event(self, event, value, extra_data=None):
        """Executes the content with the provided data.

        :param event the event to process
        :param value the value received with the event
        :return True if execution was successful, False otherwise
        """
        return True


class BasicContainer(AbstractContainer):
    """Represents a container which holds exactly one action."""

    name = "Basic"
    tag = "basic"
    hint = """This is a simple container that contains an action."""

    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    interaction_types = []

    functor = BasicContainerFunctor
    widget = BasicContainerWidget

    def __init__(self, parent=None, node=None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self._basic_container_generating_xml = False

    # def add_action(self, action, index=-1):
    #     assert isinstance(action, AbstractAction)

    #     # Make sure if we're dealing with axis with remap and response curve
    #     # actions that they are arranged sensibly
    #     if action.get_input_type() == InputType.JoystickAxis:
    #         remap_sets = []
    #         curve_sets = []
    #         for container in self.parent.containers:
    #             for action_set in container.action_sets:
    #                 for t_action in action_set:
    #                     if gremlin.input_item._is_curve_tag(t_action.tag):
    #                         curve_sets.append(action_set)
    #                     elif t_action.tag == "remap":
    #                         remap_sets.append(action_set)

    #         if action.tag == "remap" and len(curve_sets) == 1 and \
    #                 len(remap_sets) == 0:
    #             curve_sets[0].append(action)
    #         elif gremlin.input_item._is_curve_tag(action.tag) and len(remap_sets) == 1 and \
    #                 len(curve_sets) == 0:
    #             remap_sets[0].append(action)
    #         else:
    #             if index == -1:
    #                 self.action_sets.append([])
    #                 index = len(self.action_sets) - 1
    #             self.action_sets[index].append(action)
    #     else:
    #         if index == -1:
    #             self.action_sets.append([])
    #             index = len(self.action_sets) - 1
    #         self.action_sets[index].append(action)

    #     #self.refresh_conditions()

    #     self.create_or_delete_virtual_button()

    #     self.mapping_changed() # tell UI of changes

    # def _parse_xml(self, node, data = None, extra_data = None):
    #     """Populates the container with the XML node's contents.

    #     :param node the XML node with which to populate the container
    #     """
    #     pass

    # def _generate_xml(self):
    #     """Returns an XML node representing this container's data.

    #     :return XML node representing the data of this container
    #     """
    #     if self._basic_container_generating_xml:
    #         syslog.error("BASIC CONTAINER XML: recursion detected")
    #         return None
    #     self._basic_container_generating_xml = True
    #     try:

    #         node = super().to_xml()
    #         node.set("type", "basic")
    #         if self.action_sets:
    #             as_node = ElementTree.Element("action-set")
    #             as_node.set("id", write_guid(self.action_sets[0].id))
    #             for action in self.action_sets[0]:
    #                 as_node.append(action.to_xml())
    #             node.append(as_node)
    #         return node
    #     finally:
    #         self._basic_container_generating_xml = False

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) == 1


# Plugin definitions
version = 1
name = "basic"
create = BasicContainer
