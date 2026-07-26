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

from __future__ import annotations
from PySide6 import QtWidgets

import logging
import time
from lxml import etree as ElementTree

import gremlin
import gremlin.input_item
import gremlin.config
import gremlin.ui.ui_common
import gremlin.input_item
from gremlin.input_item import AbstractContainer, AbstractContainerWidget, ActionSelector, InputItem, ActionSetView, ActionSet
from gremlin.types import ContainerViewTypes, Interactions

from gremlin.input_types import InputType
from shiboken6 import Shiboken

syslog = logging.getLogger("system")


class ChainContainerWidget(AbstractContainerWidget):
    """Container which holds a sequence of actions."""

    def __init__(self, input_item : InputItem, container : "ChainContainer", parent=None):  # noqa: F821
        """Creates a new instance.

        :param input_item the input item represented by this widget
        :param container the container represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(input_item, container, parent=parent)


    def _create(self, container):
        assert isinstance(container, ChainContainer), "invalid container"
        assert len(container.action_sets) > 0, "container missing action sets"
        self.container: ChainContainer = container
        self.input_item = self.container.input_item

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return

        self.widget_layout = QtWidgets.QHBoxLayout()
        self._action_set_widgets = {}

        self.container.create_or_delete_virtual_button()

        input_item = self.container.input_item
        self.action_selector = ActionSelector(
            self.container.get_input_type(),
            input_item,
        )
        self.action_selector.inputItem = input_item
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.add_button.setText("Add Step")
        self.action_selector.action_paste.connect(self._paste_action)

        self.widget_layout.addWidget(QtWidgets.QLabel("<b>Timeout:</b> "))
        self.timeout_input = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.timeout_input.setRange(0.0, 3600.0)
        self.timeout_input.setSingleStep(0.5)
        self.timeout_input.setValue(0)
        self.timeout_input.setValue(self.container.timeout)
        self.timeout_input.valueChanged.connect(self._timeout_changed_cb)
        self.widget_layout.addWidget(self.timeout_input)

        self.action_layout.addLayout(self.widget_layout)

        self.action_set_layout = QtWidgets.QVBoxLayout()
        self.action_layout.addLayout(self.action_set_layout)

        self._update_action_sets()
        self.widget_layout.addWidget(self.action_selector)

    def _update_action_sets(self):
        """Updates the action sets in the UI."""
        if not Shiboken.isValid(self):
            return

        # Clear existing action set widgets
        for widget in self._action_set_widgets.values():
            widget.hide()
            self.action_set_layout.removeWidget(widget)
            gremlin.util.delete_widget(widget)
        self._action_set_widgets.clear()

        # Recreate action set widgets
        action_sets = [action_set for action_set in self.container.action_sets if action_set]
        for i, action_set in enumerate(action_sets):
            widget = self._create_action_set_widget(action_set,
                                                    f"Step {i + 1:d}",
                                                    ContainerViewTypes.Action,
                                                    interact_callback=self._handle_interaction,
                                                    allowed_interactions=self.container.interaction_types,
                                                    index = i)
            self._action_set_widgets[i] = widget
            self.action_set_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

    def _create_condition_ui(self):
        if self.container.action_sets:
            for i, action_set in enumerate(self.container.action_sets):
                widget = self._create_action_set_widget(action_set, f"Action {i + 1:d}", ContainerViewTypes.Conditions, index = i)
                self.activation_condition_layout.addWidget(widget)
                widget.redraw()
                widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.container)
        self.container.add_action(action_item)
        if Shiboken.isValid(self):
            self.container_modified.emit()

    def _paste_action(self, action, container):
        """pastes an action"""

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.container)
        self.container.add_action(action_item)
        if Shiboken.isValid(self):
            self.container_modified.emit()

    def _timeout_changed_cb(self, value):
        """Stores changes to the timeout element.

        :param value the new value of the timeout field
        """
        self.container.timeout = value

    def _handle_interaction(self, interaction : Interactions, index : int, widget : ActionSetView):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param index the index of the action widget
        :param interaction the type of action being invoked
        """
        # Find the index of the widget that gets modified
        # index = self._get_widget_index(widget)

        if index == -1:
            syslog.warning("Unable to find widget specified for interaction, not doing anything.")
            return

        # Perform action
        match interaction:
            case Interactions.Up:
                if index > 0:
                    self.container.action_sets.swap(index, index - 1)
            case Interactions.Down:
                if index < len(self.container.action_sets) - 1:
                    self.container.action_sets.swap(index, index + 1)
            case Interactions.Top:
                if index > 0:
                    self.container.action_sets.swap(index, 0)

            case Interactions.Bottom:
                if index < len(self.container.action_sets) - 1:
                    self.container.action_sets.swap(index, len(self.container.action_sets) - 1)

            case Interactions.Delete:
                del self.container.action_sets[index]
        if interaction == Interactions.Up:
            if index > 0:
                self.container.action_sets.swap(index, index - 1)
        if interaction == Interactions.Down:
            if index < len(self.container.action_sets) - 1:
                self.container.action_sets.swap(index, index + 1)

        if interaction == Interactions.Delete:
            self.container.action_sets.removeAt(index)

        if Shiboken.isValid(self):
            self.container_modified.emit()

        self._update_action_sets()


    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        return f"Chain: {' -> '.join([', '.join([a.name for a in actions]) for actions in self.container.action_sets])}"


class ChainContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):
    def __init__(self, container, parent=None):
        super().__init__(container, parent)

        self.timeout = container.timeout

        self.index = 0
        self.last_execution = 0.0
        self.last_value = None
        self.container = container

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        for cond in container.activation_condition.conditions:
            if isinstance(cond, gremlin.input_item.InputActionCondition):
                if cond.comparison == "press":
                    self.switch_on_press = True

    def process_event(self, event, value, extra_data=None):
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0, 0)
        elif not isinstance(value.current, bool):
            syslog.warning(f"Invalid data type received in Chain container: {type(value.current)}")
            return False
        else:
            is_pressed = value.current

        if self.timeout > 0.0:
            if self.last_execution + self.timeout < time.time():
                self.index = 0
            self.last_execution = time.time()

        verbose = gremlin.config.Configuration().verbose_mode_container
        if verbose:
            syslog.info(f"Chain: index {self.index}")
        self._trigger(self.index, event, value, extra_data)
        # result = self.container.action_sets[self.index].process_event(event, value)

        if (self.switch_on_press and is_pressed) or not is_pressed:
            self.index = (self.index + 1) % len(self.container.action_sets)

        return False  # stop execution as the logic is internal to trigger the other nodes


class ChainContainer(AbstractContainer):
    """Represents a container which holds multiplier actions.

    The actions will trigger one after the other with subsequent activations.
    A timeout, if set, will reset the sequence to the beginning.
    """

    name = "Chain"
    tag = "chain"
    hint = """This container runs all actions one after the other on each trigger.
A trigger executes the step, and moves to the next step in roundrobin fashion.
Unlike a macro or sequence container, only one step is executed for each trigger."""

    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    interaction_types = [
        Interactions.Up,
        Interactions.Down,
        Interactions.Top,
        Interactions.Bottom,
        Interactions.Delete,
    ]

    functor = ChainContainerFunctor
    widget = ChainContainerWidget

    def __init__(self, parent=None, node=None, extra_data: dict = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node, extra_data=extra_data)

        self.timeout = 0.0

    def _parse_xml(self, node, data=None, extra_data=None):
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
        return node




    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        # return len(self.action_sets) > 0
        return True


# Plugin definitions
version = 1
name = "chain"
create = ChainContainer
