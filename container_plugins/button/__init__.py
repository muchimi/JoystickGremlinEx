# -*- coding: utf-8; -*-

# Copyright (c) 2024 EMCS
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
#
# this code is build on Gremlin work by Lionel Ott

import copy
import logging
import threading
import time
from lxml import etree as ElementTree

from PySide6 import QtWidgets

import gremlin
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer


class ButtonContainerWidget(AbstractContainerWidget):

    """Container with two actions, one for input button is pressed, the other for when the input button is released
    
       While this can be duplicated with conditions - this is a helper container to simplify the profile setup.

       Works with buttons or hats
    
    """

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)

    def _create_action_ui(self):
        """Creates the UI components."""
        self.profile_data.create_or_delete_virtual_button()

        self.options_layout = QtWidgets.QHBoxLayout()

        self.action_layout.addLayout(self.options_layout)

        if self.profile_data.action_sets[0] is None:
            self._add_action_selector(
                lambda x: self._add_action(0, x),
                "Button Press",
                lambda x: self._paste_action(0, x),
            )
        else:
            self._create_action_widget(
                0,
                "Button Press",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

        if self.profile_data.action_sets[1] is None:
            self._add_action_selector(
                lambda x: self._add_action(1, x),
                "Button Release",
                lambda x: self._paste_action(1, x),
            )
        else:
            self._create_action_widget(
                1,
                "Button Release",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

    def _create_condition_ui(self):
        if self.profile_data.activation_condition_type == "action":
            if self.profile_data.action_sets[0] is not None:
                self._create_action_widget(
                    0,
                    "Button Press",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Condition
                )

            if self.profile_data.action_sets[1] is not None:
                self._create_action_widget(
                    1,
                    "Button Release",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Condition
                )

    def _add_action_selector(self, add_action_cb, label, paste_action_cb):
        """Adds an action selection UI widget.

        :param add_action_cb function to call when an action is added
        :param label the description of the action selector
        """
        action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type()
        )
        action_selector.action_added.connect(add_action_cb)
        action_selector.action_paste.connect(paste_action_cb)

        group_layout = QtWidgets.QVBoxLayout()
        group_layout.addWidget(action_selector)
        group_layout.addStretch(1)
        group_box = QtWidgets.QGroupBox(label)
        group_box.setLayout(group_layout)

        self.action_layout.addWidget(group_box)

    def _create_action_widget(self, index, label, layout, view_type):
        """Creates a new action widget.

        :param index the index at which to store the created action
        :param label the name of the action to create
        """
        widget = self._create_action_set_widget(
            self.profile_data.action_sets[index],
            label,
            view_type
        )
        layout.addWidget(widget)
        widget.redraw()
        widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, index, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        if self.profile_data.action_sets[index] is None:
            self.profile_data.action_sets[index] = []
        self.profile_data.action_sets[index].append(action_item)
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()

    def _paste_action(self, index, action):
        ''' paste action'''
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action)
        if self.profile_data.action_sets[index] is None:
            self.profile_data.action_sets[index] = []
        self.profile_data.action_sets[index].append(action_item)
        self.profile_data.create_or_delete_virtual_button()



    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        index = self._get_widget_index(widget)
        if index != -1:
            if index == 0 and self.profile_data.action_sets[0] is None:
                index = 1
            self.profile_data.action_sets[index] = None
            self.container_modified.emit()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        if self.profile_data.is_valid():
            return f"ButtonContainer: ({", ".join([a.name for a in self.profile_data.action_sets[0]])}) / ({", ".join([a.name for a in self.profile_data.action_sets[1]])})"
        else:
            return "ButtonContainer"


class ButtonContainerFunctor(gremlin.base_classes.AbstractFunctor):

    def __init__(self, container):
        super().__init__(container)
        self.press_set = gremlin.execution_graph.ActionSetExecutionGraph(
            container.action_sets[0]
        )
        self.release_set = gremlin.execution_graph.ActionSetExecutionGraph(
            container.action_sets[1]
        )

    def process_event(self, event, value):
        if not isinstance(value.current, bool):
            logging.getLogger("system").warning(
                f"Invalid data type received in button container: {type(event.value)}"
            )
            return False

        if event.is_pressed:
            # button press
            self.press_set.process_event(event, value)
        else:
            # button release
            # fake press from the container
            value.current = True
            self.release_set.process_event(event, value)

        return True


class ButtonContainer(AbstractContainer):

    """A container with two actions which are triggered based on the duration
    of the activation.

    A short press will run the fist action while a longer press will run the
    second action.
    """

    name = "Button"
    tag = "button_container"
    functor = ButtonContainerFunctor
    widget = ButtonContainerWidget
    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Edit,
    ]

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent)
        self.action_sets = [[], []]
        self.delay = 0.5
        self.activate_on = "release"

    def _parse_xml(self, node):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.action_sets = []
        super()._parse_xml(node)

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", ButtonContainer.tag)
        for actions in self.action_sets:
            as_node = ElementTree.Element("action-set")
            for action in actions:
                as_node.append(action.to_xml())
            node.append(as_node)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) == 2 and None not in self.action_sets


# Plugin definitions
version = 1
name = "button"
create = ButtonContainer
