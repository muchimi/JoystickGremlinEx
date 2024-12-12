# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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

from PySide6 import QtWidgets

import logging
import time
from lxml import etree as ElementTree

import gremlin
import gremlin.config
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget, AbstractActionWidget
from gremlin.base_profile import AbstractContainer
from gremlin.input_types import InputType

class ChainContainerWidget(AbstractContainerWidget):

    """Container which holds a sequence of actions."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)

    def _create_action_ui(self):
        """Creates the UI components."""
        self.widget_layout = QtWidgets.QHBoxLayout()

        self.profile_data.create_or_delete_virtual_button()
        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type()
        )
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.add_button.setText("Add Step")
        self.action_selector.action_paste.connect(self._paste_action)
        self.action_selector.container = self.profile_data

        self.widget_layout.addWidget(self.action_selector)

        self.widget_layout.addStretch(1)

        self.widget_layout.addWidget(QtWidgets.QLabel("<b>Timeout:</b> "))
        self.timeout_input = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.timeout_input.setRange(0.0, 3600.0)
        self.timeout_input.setSingleStep(0.5)
        self.timeout_input.setValue(0)
        self.timeout_input.setValue(self.profile_data.timeout)
        self.timeout_input.valueChanged.connect(self._timeout_changed_cb)
        self.widget_layout.addWidget(self.timeout_input)

        self.action_layout.addLayout(self.widget_layout)

        # Insert action widgets
        for i, action in enumerate(self.profile_data.action_sets):
            widget = self._create_action_set_widget(
                self.profile_data.action_sets[i],
                f"Action {i:d}",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )
            self.action_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

    def _create_condition_ui(self):
        if self.profile_data.has_action_conditions:
            for i, action in enumerate(self.profile_data.action_sets):
                widget = self._create_action_set_widget(
                    self.profile_data.action_sets[i],
                    f"Action {i:d}",
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )
                self.activation_condition_layout.addWidget(widget)
                widget.redraw()
                widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        self.profile_data.add_action(action_item)
        self.container_modified.emit()

    def _paste_action(self, action):
        ''' pastes an action '''
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        self.profile_data.add_action(action_item)
        self.container_modified.emit()

    def _timeout_changed_cb(self, value):
        """Stores changes to the timeout element.

        :param value the new value of the timeout field
        """
        self.profile_data.timeout = value

    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        # Find the index of the widget that gets modified
        index = self._get_widget_index(widget)

        if index == -1:
            logging.getLogger("system").warning(
                "Unable to find widget specified for interaction, not doing "
                "anything."
            )
            return

        # Perform action
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Up:
            if index > 0:
                self.profile_data.action_sets[index],\
                    self.profile_data.action_sets[index-1] = \
                    self.profile_data.action_sets[index-1],\
                    self.profile_data.action_sets[index]
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Down:
            if index < len(self.profile_data.action_sets) - 1:
                self.profile_data.action_sets[index], \
                    self.profile_data.action_sets[index + 1] = \
                    self.profile_data.action_sets[index + 1], \
                    self.profile_data.action_sets[index]
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Delete:
            del self.profile_data.action_sets[index]

        self.container_modified.emit()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        return f"Chain: {" -> ".join([", ".join([a.name for a in actions]) for actions in self.profile_data.action_sets])}"


class ChainContainerFunctor(gremlin.base_conditions.AbstractFunctor):

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        self.action_sets = []
        for action_set in container.action_sets:
            self.action_sets.append(
                gremlin.execution_graph.ActionSetExecutionGraph(action_set, parent)
            )
        self.timeout = container.timeout

        self.index = 0
        self.last_execution = 0.0
        self.last_value = None

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        for cond in container.activation_condition.conditions:
            if isinstance(cond, gremlin.base_classes.InputActionCondition):
                if cond.comparison == "press":
                    self.switch_on_press = True

    def process_event(self, event, value):
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        elif not isinstance(value.current, bool):
            logging.getLogger("system").warning(
                f"Invalid data type received in Chain container: {type(event.value)}"
            )
            return False
        else:
            is_pressed = value.current


        if self.timeout > 0.0:
            if self.last_execution + self.timeout < time.time():
                self.index = 0
            self.last_execution = time.time()

        verbose = gremlin.config.Configuration().verbose
        if verbose:
            logging.getLogger("system").info(f"Chain: index {self.index}")
        result = self.action_sets[self.index].process_event(event, value)

        if (self.switch_on_press and is_pressed) or not is_pressed:
            self.index = (self.index + 1) % len(self.action_sets)
        return result


class ChainContainer(AbstractContainer):

    """Represents a container which holds multiplier actions.

    The actions will trigger one after the other with subsequent activations.
    A timeout, if set, will reset the sequence to the beginning.
    """

    name = "Chain"
    tag = "chain"

    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Up,
        gremlin.ui.input_item.ActionSetView.Interactions.Down,
        gremlin.ui.input_item.ActionSetView.Interactions.Delete,
    ]

    functor = ChainContainerFunctor
    widget = ChainContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.timeout = 0.0

    def _parse_xml(self, node):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.timeout = float(node.get("timeout", 0.0))

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", ChainContainer.tag)
        node.set("timeout", str(self.timeout))
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
        #return len(self.action_sets) > 0
        return True


# Plugin definitions
version = 1
name = "chain"
create = ChainContainer
