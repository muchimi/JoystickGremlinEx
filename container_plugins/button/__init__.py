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

import logging
import threading
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore

import gremlin
import gremlin.config
import gremlin.ui.ui_common
import gremlin.input_item
from gremlin.input_item import AbstractContainer, AbstractContainerWidget, ActionSelector
from gremlin.types import ContainerViewTypes, Interactions

from gremlin.util import safe_format, safe_read
from gremlin.input_types import InputType
from shiboken6 import Shiboken
import gremlin.base_profile

syslog = logging.getLogger("system")


class ButtonContainerWidget(AbstractContainerWidget):
    """Container with two actions, one for input button is pressed, the other for when the input button is released

    While this can be duplicated with conditions - this is a helper container to simplify the profile setup.

    Works with buttons or hats

    """

    def __init__(self, input_item : gremlin.input_item.AbstractInputItem, container : "ButtonContainer", parent=None):  # noqa: F821
        """Creates a new instance.

        :param input_item the input item represented by this widget
        :param container the container represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(input_item, container, parent)
        self.container = container
        self.input_item = input_item

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self.container.create_or_delete_virtual_button()

        self.autorelease_widget = QtWidgets.QCheckBox("Auto-release")
        self.autorelease_widget.setChecked(self.container.autorelease)
        self.autorelease_widget.clicked.connect(self._autorelease_changed)
        self.autorelease_widget.setToolTip("When enabled, the actions will automatically receive a release trigger after the specified delay.")

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(label="Autorelease Delay (ms):")
        self.delay_widget.setValue(self.container.autorelease_delay)
        self.delay_widget.valueChanged.connect(self._autorelease_delay_changed_cb)

        widget = gremlin.ui.ui_common.getHContainer([self.autorelease_widget, self.delay_widget], "Options", widget_only=True)

        self.action_layout.addWidget(widget)

        # actions
        self._update_actions()

        self._update_visible()

    def _update_actions(self):

        if self.container.action_sets[0] is None:
            self._add_action_selector(
                lambda x: self._add_action(0, x),
                "Press Actions",
                lambda x: self._paste_action(0, x),
            )
        else:
            self._create_action_widget(0, "Press Actions", self.action_layout, ContainerViewTypes.Action)

        if self.container.action_sets[1] is None:
            self._add_action_selector(
                lambda x: self._add_action(1, x),
                "Release Actions",
                lambda x: self._paste_action(1, x),
            )
        else:
            self._create_action_widget(1, "Release Actions", self.action_layout, ContainerViewTypes.Action)

    def _update_visible(self):
        delay_visible = self.container.autorelease
        self.delay_widget.setVisible(delay_visible)

    @QtCore.Slot(bool)
    def _autorelease_changed(self, checked: bool):
        self.container.autorelease = checked
        self._update_visible()

    @QtCore.Slot(int)
    def _autorelease_delay_changed_cb(self, value):
        """Updates the autorelease delay"""
        self.container.autorelease_delay = value

    def _create_condition_ui(self):
        if self.container.action_sets:
            if self.container.action_sets[0] is not None:
                self._create_action_widget(0, "Button Press", self.activation_condition_layout, ContainerViewTypes.Conditions)

            if self.container.action_sets[1] is not None:
                self._create_action_widget(1, "Button Release", self.activation_condition_layout, ContainerViewTypes.Conditions)

    def _add_action_selector(self, add_action_cb, label, paste_action_cb):
        """Adds an action selection UI widget.

        :param add_action_cb function to call when an action is added
        :param label the description of the action selector
        """
        action_selector = ActionSelector(self.container.get_input_type(), self.container.get_input_item())
        action_selector.inputItem = self.container
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

        layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        step_widget = gremlin.ui.ui_common.QFrameBox(f"<b>{label}</b>")
        widget = gremlin.ui.ui_common.getVContainer([step_widget, QtWidgets.QLabel(" ")], widget_only=True)
        widget = gremlin.ui.ui_common.getHContainer(widget, widget_only=True)
        layout.addWidget(widget)

        widget = self._create_action_set_widget(action_set=self.container.action_sets[index], view_type=view_type)
        layout.addWidget(widget)
        widget.redraw()
        widget.model.data_changed.connect(self._handle_container_changed)

    def _handle_container_changed(self):
        if Shiboken.isValid(self):
            self.container_modified.emit()
            self.redrawActionSets()

    def _add_action(self, index, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.container)
        if self.container.action_sets[index] is None:
            self.container.action_sets[index] = []
        self.container.action_sets[index].append(action_item)
        self.container.create_or_delete_virtual_button()
        if Shiboken.isValid(self):
            self.container_modified.emit()
        self._update_actions()

    def _paste_action(self, index, action):
        """paste action"""

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.container)
        if self.container.action_sets[index] is None:
            self.container.action_sets[index] = []
        self.container.action_sets[index].append(action_item)
        self.container.create_or_delete_virtual_button()
        self._update_actions()

    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        index = self._get_widget_index(widget)
        if index != -1:
            if index == 0 and self.container.action_sets[0] is None:
                index = 1
            self.container.action_sets[index] = None
            if Shiboken.isValid(self):
                self.container_modified.emit()
            self._update_actions()
            self._update_container_ui()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        if self.container.is_valid():
            return f"Press/Release: ({', '.join([a.name for a in self.container.action_sets[0]])}) / ({', '.join([a.name for a in self.container.action_sets[1]])})"
        else:
            return "Press/Release:"


class ButtonContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):
    def __init__(self, container, parent=None):
        super().__init__(container, parent)
        self.container = container
        self.last_trigger = None
        self.autorelease = container.autorelease
        self.verbose = gremlin.config.Configuration().verbose_mode_container
        self.release_timer = None

    def profile_stop(self):
        if self.release_timer:
            self.release_timer.cancel()

    def process_event(self, event, value, extra_data=None):

        event = event.clone()
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0, 0)
        else:
            is_pressed = event.is_pressed

        if is_pressed:
            # button press
            if self.verbose:
                syslog.info("BUTTON CONTAINER: trigger [press]")
            self._trigger(0, event, value, extra_data)
            if self.autorelease:
                # setup autorelease trigger
                event_r = event.clone()
                event_r.is_pressed = False
                if self.release_timer:
                    self.release_timer.cancel()
                self.release_timer = threading.Timer(self.container.autorelease_delay / 1000, lambda: self._trigger(0, event_r, value, extra_data))
                self.release_timer.start()
                self.last_trigger = 0

            # self.press_set.process_event(event, value)
        else:
            # button release
            event.is_pressed = True
            if self.verbose:
                syslog.info("BUTTON CONTAINER: trigger [release]")
            self._trigger(1, event, value, extra_data)
            if self.autorelease:
                # setup autorelease trigger
                event_r = event.clone()
                event_r.is_pressed = False
                if self.release_timer:
                    self.release_timer.cancel()
                self.release_timer = threading.Timer(self.container.autorelease_delay / 1000, lambda: self._trigger(1, event_r, value, extra_data))
                self.release_timer.start()
            self.last_trigger = 1

            # self.release_set.process_event(event, value)

        return True


class ButtonContainer(AbstractContainer):
    """A container with two actions which are triggered based on the duration
    of the activation.

    A short press will run the fist action while a longer press will run the
    second action.
    """

    name = "Press/Release"
    tag = "button_container"
    hint = """This container is used to trigger one action on trigger press,
and another action on trigger release in a single container."""
    functor = ButtonContainerFunctor
    widget = ButtonContainerWidget

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]
    interaction_types = [
        Interactions.Edit,
    ]

    def __init__(self, parent=None, node=None, extra_data: dict = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node, extra_data=extra_data)
        self.delay = 0.5
        self.activate_on = "release"
        self.autorelease = True
        self.autorelease_delay = 250  # delay for autorelease trigger if in autorelease mode
        # self.actionsetCustomParseCallback = self._parse_action_xml
        self.press_action_set = gremlin.input_item.ActionSet(model_description = "press actions")
        self.release_action_set = gremlin.input_item.ActionSet(model_description = "release actions")
        self.action_sets.clear()
        self.action_sets.add(self.press_action_set) # 0
        self.action_sets.add(self.release_action_set) # 1



    def resetActionSets(self):
        """resets actions sets - override in derived class if the action set default should be different"""
        self.press_action_set.clear()
        self.release_action_set.clear()




    def _parse_xml(self, node, data=None, extra_data=None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.resetActionSets()
        super()._parse_xml(node, data)
        if "autorelease" in node.attrib:
            self.autorelease = safe_read(node, "autorelease", bool, True)
        if "delay" in node.attrib:
            self.autorelease_delay = safe_read(node, "delay", int, 250)



    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", ButtonContainer.tag)
        node.set("autorelease", safe_format(self.autorelease, bool))
        node.set("delay", safe_format(self.autorelease_delay, int))

        return node


    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        valid = len(self.action_sets) == 2 and None not in self.action_sets
        return valid


# Plugin definitions
version = 1
name = "button"
create = ButtonContainer
