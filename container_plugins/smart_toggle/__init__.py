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

import copy
import logging
import threading
import time
from lxml import etree as ElementTree
from gremlin.input_types import InputType
from PySide6 import QtWidgets, QtCore


import gremlin
import gremlin.config
import gremlin.execution_graph
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
from gremlin.util import safe_format, safe_read
from shiboken6 import Shiboken
syslog = logging.getLogger("system")

class SmartToggleContainerWidget(AbstractContainerWidget):

    """SmartToggle container which holds or toggles a single action."""

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

        self.options_layout = QtWidgets.QHBoxLayout()

        # Activation delay
        self.options_layout.addWidget(
            QtWidgets.QLabel("<b>Toggle time: </b>")
        )

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget()
        self.delay_widget.setToolTip("Delay in milliseconds")
        self.delay_widget.setValue(self.profile_data.delay * 1000)
        self.delay_widget.valueChanged.connect(self._delay_changed_cb)

        self.short_widget = QtWidgets.QCheckBox("Toggle on short press")
        self.short_widget.setChecked(self.profile_data.shortPressMode)
        self.short_widget.clicked.connect(self._short_press_mode_changed)

        
        self.options_layout.addWidget(self.delay_widget)
        self.options_layout.addWidget(self.short_widget)
        self.options_layout.addStretch()

        self.action_layout.addLayout(self.options_layout)

        if len(self.profile_data.action_sets) > 0:
            assert len(self.profile_data.action_sets) == 1

            widget = self._create_action_set_widget(
                self.profile_data.action_sets[0],
                "Smart Toggle",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )
            self.action_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)
        else:
            action_selector = gremlin.ui.ui_common.ActionSelector(
                self.profile_data.get_input_type(),
                self.profile_data,
            )
            action_selector.inputItem = self.profile_data
            action_selector.action_added.connect(self._add_action)
            action_selector.action_paste.connect(self._paste_action)
            self.action_layout.addWidget(action_selector)

    @QtCore.Slot(bool)
    def _short_press_mode_changed(self, checked: bool):
        self.profile_data.shortPressMode = checked


    def _create_condition_ui(self):
        if self.profile_data.action_sets:

            widget = self._create_action_set_widget(
                self.profile_data.action_sets[0],
                "Smart Toggle",
                gremlin.ui.ui_common.ContainerViewTypes.Conditions
            )
            self.activation_condition_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.get_class(action_name)(self.profile_data)
            if self.profile_data.action_sets[0] is None:
                self.profile_data.action_sets[0] = []
            self.profile_data.action_sets[0].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
            self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

    def _paste_action(self, action, container):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.profile_data)
            if self.profile_data.action_sets[0] is None:
                self.profile_data.action_sets[0] = []
            self.profile_data.action_sets[0].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
            self.container_modified.emit()        
        finally:
            gremlin.util.popCursor()

    def _delay_changed_cb(self, value):
        self.profile_data.delay = value / 1000 # in seconds

    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_press.isChecked():
            self.profile_data.activate_on = "press"
        else:
            self.profile_data.activate_on = "release"

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
        title = "Smart Toggle: "
        if len(self.profile_data.action_sets) > 0:
            title += ", ".join(a.name for a in self.profile_data.action_sets[0])
        return title


class SmartToggleContainerFunctor(gremlin.base_conditions.AbstractSelfTriggerFunctor):

    """Executes the contents of the associated SmartToggle container."""

    def __init__(self, action_data : SmartToggleContainer, parent = None):
        super().__init__(action_data, parent)
        # self.action_set = gremlin.execution_graph.ActionSetExecutionGraph(
        #     action_data.action_sets[0], parent
        # )
        self.delay = action_data.delay
        self.shortPressMode = action_data.shortPressMode
        self.release_value = None
        self.release_event = None
        self.mode = None
        self.long_press_time = 0.0
        self.is_pressed = False # assume output is not pressed

    def profile_start(self):
        action_data = self.action_data
        self.delay = action_data.delay
        self.shortPressMode = action_data.shortPressMode
        self.release_value = None
        self.release_event = None
        self.mode = None
        self.long_press_time = 0.0
        self.is_pressed = False # assume output is not pressed

    def profile_started(self):
        super().profile_started()        

   
    def process_event(self, event, value, extra_data = None):
        ''' short press = toggle output 
            long press = toggle ON while held, then toggle off 
            
            From original Joystick Gremlin:
            The smart toggle container allows for a single group of actions that are have on and off states, such as remap and map to keyboard to be used in two manners.
            If the input is held down the action will perform as a typical remap action would, i.e. staying active as long as the input is pressed.
            However, when a short button press is detected, specified by the Toggle time then the first such press toggles the down state,
            i.e. holding the action down, and the second short press releases the action again.
            
           
            
            '''
        
        verbose = gremlin.config.Configuration().verbose_mode_outputs
        # verbose = True
        
        if extra_data is None:
            extra_data = {}
        extra_data["autorelease"] = False # disable autorelease on actions regardless of settings

        if event.is_pressed:
            # input is pressed
            
            self.long_press_time = time.time() + self.delay

            if self.mode is None:
                if verbose: syslog.info("press: normal")
                if self.shortPressMode:
                    
                    self.is_pressed = not self.is_pressed # toggle
                    if self.is_pressed:
                        self._execute(event, value, extra_data)
                        #self.action_set.process_event(event, value, extra_data)
                    else:
                        self._execute(event.invert(), value.invert(), extra_data)
                        #self.action_set.process_event(event.invert(), value.invert(), extra_data)

                    if verbose: syslog.info(f"press: toggle {'on' if self.is_pressed else 'off'}")
                else:
                    if verbose: syslog.info("press: normal")
                    self._execute(event, value, extra_data)
                    #self.action_set.process_event(event, value, extra_data)
                    
        
            elif self.mode == "long":
                # long press mode turn off and do not send input press event
                if verbose: syslog.info("long press: send OFF")
                if self.shortPressMode:
                    # release the press 
                    self._execute(event.invert(), value.invert(), extra_data)
                    #self.action_set.process_event(event.invert(), value.invert(), extra_data)
                    self.is_pressed = False
                else:
                    self._execute(self.release_event, self.release_value, extra_data)
                    #self.action_set.process_event(self.release_event, self.release_value, extra_data)

                # reset toggle mode
                self.activation_time = 0.0
                self.mode = None

            
                    
        else:
            # input is released
            
            if self.long_press_time < time.time():
                # long press detect
                if self.shortPressMode:
                    if verbose: syslog.info("long release: toggle OFF")
                    #self.action_set.process_event(event, value, extra_data)
                    self._execute(event, value, extra_data)
                    self.mode = None
                    self.activation_time = 0.0
                    self.is_pressed = False
                else:
                    if verbose: syslog.info("long release: enable long press")
                    self.mode = "long"
                    self.release_event = event.clone()
                    self.release_value = value
                # do not send the input release event in long press mode which effectively keeps the pressed state on

            else:

                if self.shortPressMode:
                    # don't release on short press mode
                    pass
                else:
                    self._execute(event, value, extra_data)
                    #self.action_set.process_event(event, value, extra_data)
                    self.mode = None
                    self.activation_time = 0.0
                    self.is_pressed = False

        return False # stop execution past this container


class SmartToggleContainer(AbstractContainer):
    '''
    smart toggle container - short press = toggle output, long press is press while held and release
    '''

    name = "Smart Toggle"
    tag = "smart_toggle"
    hint = '''This container toggles the action on short press, and works like a regular input on long press.
Each short press will toggle the output on/off.  Each long press will function like a regular input trigger.
The delay between short and long press can be adjusted.
Toggling the action means the action will receive a press input and no release input, or a release input on a short press.
On long press the action receives a press input when the input is pressed, and a release when the input is released if held long enough.
'''

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
    interaction_types = []

    functor = SmartToggleContainerFunctor
    widget = SmartToggleContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.setActionSets([[]])
        self.delay = 0.5 # in seconds
        self.shortPressMode = True # false to toggle on long press


    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        super()._parse_xml(node, data)
        self.delay = safe_read(node, "delay", float, 0.5)
        self.shortPressMode = safe_read(node, "short-press-mode", bool, True)


    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", SmartToggleContainer.tag)
        node.set("delay", safe_format(self.delay, float))
        node.set("short-press-mode", safe_format(self.shortPressMode, bool))

        as_node = ElementTree.Element("action-set")
        for action in self.action_sets[0]:
            as_node.append(action.to_xml())
        node.append(as_node)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) == 1
    
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell

        table = ReportTable(cellpadding=4)
        
        count = sum(len(actions) for actions in self.action_sets)
        table.addField("Count", f"{count}")
        # count = sum(len(actions) for actions in self.action_sets[1])
        # table.addField("Action B Count", f"{count}")
        table.addField("Short press mode", "Yes" if self.shortPressMode else "No")
        table.addField("Delay", f"{self.delay*1000:,} ms")

        return table.to_html()


# Plugin definitions
version = 1
name = "smart_toggle"
create = SmartToggleContainer
