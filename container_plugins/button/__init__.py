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

from PySide6 import QtWidgets, QtCore

import gremlin
import gremlin.config
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
from gremlin.util import safe_read, safe_format
from gremlin.input_types import InputType
from shiboken6 import Shiboken

syslog = logging.getLogger("system")

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
        if not Shiboken.isValid(self):
            return
        self.profile_data.create_or_delete_virtual_button()

        self.autorelease_widget = QtWidgets.QCheckBox("Auto-release")
        self.autorelease_widget.setChecked(self.profile_data.autorelease)
        self.autorelease_widget.clicked.connect(self._autorelease_changed)
        self.autorelease_widget.setToolTip("When enabled, the actions will automatically receive a release trigger after the specified delay.")

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Autorelease Delay (ms):")
        self.delay_widget.setValue(self.profile_data.autorelease_delay)
        self.delay_widget.valueChanged.connect(self._autorelease_delay_changed_cb)

        widget, _ = gremlin.ui.ui_common.getHContainer([self.autorelease_widget, self.delay_widget],"Options")

        self.action_layout.addWidget(widget)

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

        self._update_visible()

    def _update_visible(self):
        delay_visible = self.profile_data.autorelease
        self.delay_widget.setVisible(delay_visible)
            
    @QtCore.Slot(bool)
    def _autorelease_changed(self, checked):
        self.profile_data.autorelease = checked
        self._update_visible()

    @QtCore.Slot(int)
    def _autorelease_delay_changed_cb(self, value):
        ''' Updates the autorelease delay '''
        self.profile_data.autorelease_delay = value

    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            if self.profile_data.action_sets[0] is not None:
                self._create_action_widget(
                    0,
                    "Button Press",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )

            if self.profile_data.action_sets[1] is not None:
                self._create_action_widget(
                    1,
                    "Button Release",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )

    def _add_action_selector(self, add_action_cb, label, paste_action_cb):
        """Adds an action selection UI widget.

        :param add_action_cb function to call when an action is added
        :param label the description of the action selector
        """
        action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            self.profile_data,
        )
        action_selector.inputItem = self.profile_data
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

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.get_class(action_name)(self.profile_data)
            if self.profile_data.action_sets[index] is None:
                self.profile_data.action_sets[index] = []
            self.profile_data.action_sets[index].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
            self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

    def _paste_action(self, index, action):
        ''' paste action'''

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.profile_data)
            if self.profile_data.action_sets[index] is None:
                self.profile_data.action_sets[index] = []
            self.profile_data.action_sets[index].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
        finally:
            gremlin.util.popCursor()



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
            return f"Button: ({", ".join([a.name for a in self.profile_data.action_sets[0]])}) / ({", ".join([a.name for a in self.profile_data.action_sets[1]])})"
        else:
            return "Button:"


class ButtonContainerFunctor(gremlin.base_conditions.AbstractSelfTriggerFunctor):

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        self.profile_data = container
        self.last_trigger = None
        self.autorelease = container.autorelease
        self.verbose = gremlin.config.Configuration().verbose
        self.release_timer = None

    def profile_stop(self):
        if self.release_timer:
            self.release_timer.cancel()

    def process_event(self, event, value, extra_data = None):

        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        else:
            is_pressed = event.is_pressed

        if is_pressed:
            # button press
            if self.verbose: syslog.info("trigger 0")
            self._trigger(0, event, value, extra_data)
            if self.autorelease:
                # setup autorelease trigger
                event_r = event.clone()
                event_r.is_pressed = False
                if self.release_timer:
                    self.release_timer.cancel()
                self.release_timer = threading.Timer(self.profile_data.autorelease_delay/1000, lambda: self._trigger(0, event_r, value, extra_data))
                self.release_timer.start()
                self.last_trigger = 0

            #self.press_set.process_event(event, value)
        else:
            # button release
            event.is_pressed = True
            if self.verbose: syslog.info("trigger 1")
            self._trigger(1, event, value, extra_data)
            if self.autorelease:
                # setup autorelease trigger
                event_r = event.clone()
                event_r.is_pressed = False
                if self.release_timer:
                    self.release_timer.cancel()
                self.release_timer = threading.Timer(self.profile_data.autorelease_delay/1000, lambda: self._trigger(1, event_r, value, extra_data))
                self.release_timer.start()
            self.last_trigger = 1                


            #self.release_set.process_event(event, value)

        return False # stop execution as the logic is internal to trigger the other nodes


class ButtonContainer(AbstractContainer):

    """A container with two actions which are triggered based on the duration
    of the activation.

    A short press will run the fist action while a longer press will run the
    second action.
    """

    name = "Button"
    tag = "button_container"
    hint = '''This container is used to trigger one action on trigger press,
and another action on trigger release in a single container.'''
    functor = ButtonContainerFunctor
    widget = ButtonContainerWidget
    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]
    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Edit,
    ]

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.action_sets = [[], []]
        self.delay = 0.5
        self.activate_on = "release"
        self.autorelease = True
        self.autorelease_delay = 250 # delay for autorelease trigger if in autorelease mode

    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.action_sets = []
        super()._parse_xml(node, data)
        if "autorelease" in node.attrib:
            self.autorelease = safe_read(node,"autorelease",bool, True)
        if "delay" in node.attrib:
            self.autorelease_delay = safe_read(node,"delay",int, 250)


    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", ButtonContainer.tag)
        node.set("autorelease", safe_format(self.autorelease,bool))
        node.set("delay", safe_format(self.autorelease_delay, int))

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
