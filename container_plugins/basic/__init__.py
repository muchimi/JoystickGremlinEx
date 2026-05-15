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

from lxml import etree as ElementTree

import gremlin
import gremlin.config
from gremlin.input_types import InputType
import gremlin.ui.ui_common
import gremlin.types
from gremlin.base_profile import AbstractFunctor
from gremlin.input_item import AbstractContainer
from gremlin.input_item import AbstractContainerWidget
from shiboken6 import Shiboken
import logging
from gremlin.util import safe_format, safe_read, write_guid, get_guid, read_guid

syslog = logging.getLogger("system")
class BasicContainerWidget(AbstractContainerWidget):

    """Basic container which holds a single action."""

    def __init__(self, container, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(container, parent)
        self.container = container


    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info("BasicContainerWidget: create action UI start")
        has_actions = False
        for action_set in self.container.action_sets:
            if action_set:
                has_actions = True
                break

        if has_actions:
            action_sets = [action_set for action_set in self.container.action_sets if action_set]
            assert len(action_sets) == 1, "invalid action set count - expected a single action set"

            self.container.create_or_delete_virtual_button()
            widget = self._create_action_set_widget(
                action_sets[0],
                "Basic",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

            self.action_layout.addWidget(widget)
            
            widget.model.data_changed.connect(self.container_modified.emit)
        else:
            input_item = self.container.input_item
            if self.container.get_device_type() == gremlin.types.DeviceType.VJoy:
                action_selector = gremlin.ui.ui_common.ActionSelector(
                    gremlin.types.DeviceType.VJoy,
                    input_item,
                )
            else:
                action_selector = gremlin.ui.ui_common.ActionSelector(
                    input_item.get_input_type(),
                    input_item,
                )
            action_selector.action_added.connect(self._add_action)
            action_selector.action_paste.connect(self._paste_action)
            action_selector.inputItem = self.container

            self.action_layout.addWidget(action_selector)

        if verbose_ui: syslog.info("BasicContainerWidget: create action UI completed")

    def _create_condition_ui(self):
        if self.container.action_sets:
            widget = self._create_action_set_widget(
                self.container.action_sets[0],
                "Basic",
                gremlin.ui.ui_common.ContainerViewTypes.Conditions
            )
            self.activation_condition_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

            return widget

    def _add_action(self, action_data):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        from gremlin.clipboard import Clipboard
        if action_data is None:
            return
        if not Shiboken.isValid(self):
            return

        gremlin.util.pushCursor()

        try:

            if isinstance(action_data, str):
                action_name = action_data
                plugin_manager = gremlin.plugin_manager.ActionPlugins()
                action_item = plugin_manager.get_class(action_name)(self.container)
            elif isinstance(action_data, Clipboard):
                # paste operation
                if action_data.is_action:
                    # verify the action in the clipboard is appropriate for this input

                    action_item = plugin_manager.duplicate(action_data.data, self.container)

            self.container.add_action(action_item)

            # blows up in QT 6.11
            if Shiboken.isValid(self):
                self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

    def _paste_action(self, action, container):
        ''' paste action'''

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.container)
            self.container.add_action(action_item)
            if Shiboken.isValid(self):
                self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

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
            stub =  ", ".join(a.name for a in self.container.action_sets[0])
            title += stub

        return title


class BasicContainerFunctor(AbstractFunctor):

    """Executes the contents of the associated basic container."""

    def __init__(self, container, parent = None):
        super().__init__(container, parent)


    def process_event(self, event, value, extra_data = None):
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
    hint = '''This is a simple container that contains an action.'''

    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    interaction_types = []

    functor = BasicContainerFunctor
    widget = BasicContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self._basic_container_generating_xml = False


    def add_action(self, action, index=-1):
        assert isinstance(action, gremlin.base_profile.AbstractAction)

        # Make sure if we're dealing with axis with remap and response curve
        # actions that they are arranged sensibly
        if action.get_input_type() == InputType.JoystickAxis:
            remap_sets = []
            curve_sets = []
            for container in self.parent.containers:
                for action_set in container.action_sets:
                    for t_action in action_set:
                        if gremlin.base_profile._is_curve_tag(t_action.tag):
                            curve_sets.append(action_set)
                        elif t_action.tag == "remap":
                            remap_sets.append(action_set)

            if action.tag == "remap" and len(curve_sets) == 1 and \
                    len(remap_sets) == 0:
                curve_sets[0].append(action)
            elif gremlin.base_profile._is_curve_tag(action.tag) and len(remap_sets) == 1 and \
                    len(curve_sets) == 0:
                remap_sets[0].append(action)
            else:
                if index == -1:
                    self.action_sets.append([])
                    index = len(self.action_sets) - 1
                self.action_sets[index].append(action)
        else:
            if index == -1:
                self.action_sets.append([])
                index = len(self.action_sets) - 1
            self.action_sets[index].append(action)

        #self.refresh_conditions()

        self.create_or_delete_virtual_button()

        self.mapping_changed() # tell UI of changes


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
