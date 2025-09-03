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


from __future__ import annotations

import copy
import logging
import threading
import time
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore

import gremlin
import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.ui.qsliderwidget
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
from gremlin.input_types import InputType
from gremlin.util import safe_format, safe_read
from shiboken6 import Shiboken
class TickContainerWidget(AbstractContainerWidget):

    """Container with two actions, one for input button is pressed, the other for when the input button is released
    
       While this can be duplicated with conditions - this is a helper container to simplify the profile setup.

       Works with buttons or hats
    
    """

    def __init__(self, action_data : TickContainer, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent)

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_handler)

        self.action_data : TickContainer = self.profile_data
        self.action_data.create_or_delete_virtual_button()

        self.interval_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.interval_widget.setRange(0, 2)
        self.interval_widget.setValue(self.action_data.interval)
        self.interval_widget.valueChanged.connect(self._interval_changed)

        self.tick_count_widget = gremlin.ui.ui_common.QIntLineEdit()
        self.tick_count_widget.setRange(0,100)
        self.tick_count_widget.setValue(self.action_data.getTickCount())
        self.tick_count_widget.valueChanged.connect(self._tick_count_changed)

        self.slider_widget = gremlin.ui.qsliderwidget.QSliderWidget()
        self.slider_widget.setRange(-1,1)
        self.slider_widget.setReadOnly(True)
        self.slider_widget.setDrawHandles(False)

        self.slider_widget.setTickCount(self.action_data.getTickCount())

        self.header_container = QtWidgets.QWidget()
        self.header_layout = QtWidgets.QHBoxLayout(self.header_container)

        self.header_layout.addWidget(QtWidgets.QLabel("Interval:")) 
        self.header_layout.addWidget(self.interval_widget)
        self.header_layout.addWidget(QtWidgets.QLabel("Tick Count:")) 
        self.header_layout.addWidget(self.tick_count_widget)
        self.header_layout.addWidget(self.slider_widget)
        self.header_layout.addStretch()

                                                                       


        self.options_layout = QtWidgets.QHBoxLayout()


        self.action_layout.addWidget(self.header_container)
        self.action_layout.addLayout(self.options_layout)

        if self.profile_data.action_sets[0] is None:
            self._add_action_selector(
                lambda x: self._add_action(0, x),
                "Tick Up",
                lambda x: self._paste_action(0, x),
            )
        else:
            self._create_action_widget(
                0,
                "Tick Up",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

        if self.profile_data.action_sets[1] is None:
            self._add_action_selector(
                lambda x: self._add_action(1, x),
                "Tick Down",
                lambda x: self._paste_action(1, x),
            )
        else:
            self._create_action_widget(
                1,
                "Tick Down",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
        if gremlin.shared_state.is_running:
            return 

        if not event.is_axis:
            return 
        
        value = None
        
        if event.device_guid != self.action_data.hardware_device_guid:
            return
        if event.identifier != self.action_data.hardware_input_id:
            return
        
        value = event.value
        
        
        self._update_axis_widget(value)       

    
    def _update_axis_widget(self, value : float = None):
        self.slider_widget.setMarkerValue(value)
        

    @QtCore.Slot()
    def _interval_changed(self):
        widget = self.sender()
        interval = widget.value()
        self.action_data.interval = interval
        count = self.action_data.getTickCount()
        with QtCore.QSignalBlocker(self.tick_count_widget):
            self.tick_count_widget.setValue(count)
        self.slider_widget.setTickCount(count)
        self.update()

    @QtCore.Slot()
    def _tick_count_changed(self):
        widget = self.sender()
        count = widget.value()
        interval = 2 / (count + 2)
        self.action_data.interval = interval
        with QtCore.QSignalBlocker(self.interval_widget):
            self.interval_widget.setValue(interval)
        self.slider_widget.setTickCount(count)
        self.update()


    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            if self.profile_data.action_sets[0] is not None:
                self._create_action_widget(
                    0,
                    "Axis Increase",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )

            if self.profile_data.action_sets[1] is not None:
                self._create_action_widget(
                    1,
                    "Axis Decrease",
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
        title = "Tick:"
        if self.profile_data.is_valid():
            title += f"({", ".join([a.name for a in self.profile_data.action_sets[0]])}) / ({", ".join([a.name for a in self.profile_data.action_sets[1]])})"
        return title

class TickContainerFunctor(gremlin.base_conditions.AbstractSelfTriggerFunctor):

    def __init__(self, container : TickContainer, parent = None):
        super().__init__(container, parent)
        # self.increase_set = gremlin.execution_graph.ActionSetExecutionGraph(
        #     container.action_sets[0], parent
        # )
        # self.decrease_set = gremlin.execution_graph.ActionSetExecutionGraph(
        #     container.action_sets[1], parent
        # )
        self.action_data = container

    def profile_start(self):
        self.last_value = None

        # current position
        count = self.action_data.getTickCount()
        interval = 2 / (count-1)
        self.last_tick = self.action_data.currentTick()

        # build the ranges for each tick
        self._tick_map = [-1.0 + x * interval for x in range(count)]
        self._last_value = self.action_data._get_value()
      
    def process_event(self, event, value, extra_data = None):
        
        if not event.is_axis:
            return
        
        last_tick = self.last_tick
        
        value = event.value
        last_value = self._last_value
        index = 0
        trigger = False
        for v in self._tick_map:
            if last_value < v and value > v or value < v and last_value > v:
                trigger = True
                break
            elif value == v:
                trigger = True
                break
            index +=1

        tick = index
        trigger = trigger or last_tick != tick
        

        if trigger:
            #print (f"Value: {value:0.3f}  last: {last_value:0.3f} index: {tick}   last tick: {last_tick}  map: {self._tick_map}  trigger: {trigger}")
            
            trigger_count = abs(last_tick - tick)
            event.is_axis = False
            event.is_button = True
            event.is_pressed = True # tell each tick we're pressed
            if  last_value < value:
                # going up 
                #print (f"increase set trigger  value: {value:0.3f} tick: {tick} last tick: {last_tick} count: {trigger_count}")
                for _ in range(trigger_count):
                    self._trigger(0, event, value, extra_data)
                    #self.increase_set.process_event(event, value)
            elif last_value > value:
                # going down
                #print (f"decrease set trigger  value: {value:0.3f} tick: {tick} count: {trigger_count}")
                for _ in range(trigger_count):
                    self._trigger(1, event, value, extra_data)
                    #self.decrease_set.process_event(event, value)

            self.last_tick = tick


        self._last_value = value
        
        return False # stop execution past this container


class TickContainer(AbstractContainer):

    """A container with two actions which are triggered based on the duration
    of the activation.

    A short press will run the fist action while a longer press will run the
    second action.
    """

    name = "Tick"
    tag = "tick_container"
    hint = '''Use this container to split an axis (linear) input and trigger actions at each tick position.
For a more advanced way to split an axis and trigger actions at specific points, look at the Gated Axis action.'''
    functor = TickContainerFunctor
    widget = TickContainerWidget
    # override default allowed inputs here
    input_types = [
        InputType.JoystickAxis,
    ]
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Edit,
    ]

    def getTick(self, value : float) -> int:
        ''' gets the tick number for a given value -1 to +1 '''
        value += 1 # range 0..2
        tick = int(2 / (value + 1))
        print (f"value: {value:0.3f} tick: {tick}")
        return tick

    def _get_value(self) -> float:
        ''' current axis value '''
        return gremlin.joystick_handling.get_axis(self.hardware_device_guid, self.hardware_input_id)
    
    def currentTick(self) -> int:
        value = self._get_value()
        return self.getTick(value)
    
    def getTickCount(self) -> int:
        ''' gets the number of ticks in the container '''
        if self.interval == 0:
            return 2
        count = round(2/self.interval)+1
        print (f"New count: {count}  interval: {self.interval}  {2/self.interval:0.3f}")
        return count
        

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.action_sets = [[], []]
        self.delay = 0.5
        self.activate_on = "release"
        self.interval = 0.2 # interval between ticks

        # override the input type to a button
        self.override_input_id = 1
        self.override_input_type = InputType.JoystickButton

    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.action_sets = []
        self.interval  = safe_read(node,"interval",float,0.2)
        super()._parse_xml(node, data)

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", TickContainer.tag)
        node.set("interval", safe_format(self.interval, float))
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
        return True #  len(self.action_sets) == 2 and None not in self.action_sets


# Plugin definitions
version = 1
name = "tick"
create = TickContainer
