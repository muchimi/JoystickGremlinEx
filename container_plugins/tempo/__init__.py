# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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

from PySide6 import QtWidgets, QtCore

import gremlin
import gremlin.ui.ui_common
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
from gremlin.input_types import InputType
from gremlin.util import safe_read, safe_format
import gremlin.execution_graph
import gremlin.base_profile

syslog = logging.getLogger("system")
class TempoContainerWidget(AbstractContainerWidget):

    """Container with two actions, triggered based on activation duration."""

    def __init__(self, profile_data : TempoContainer, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)

    def _create_action_ui(self):
        """Creates the UI components."""
        self.profile_data.create_or_delete_virtual_button()

        self.options_layout = QtWidgets.QHBoxLayout()
        self.options2_layout = QtWidgets.QHBoxLayout()

        self.longpress_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Long Press Delay (ms):")
        self.longpress_delay_widget.setValue(self.profile_data.delay * 1000)
        self.longpress_delay_widget.valueChanged.connect(self._delay_changed_cb)
        self.options_layout.addWidget(self.longpress_delay_widget)
        self.options_layout.addStretch()

        self.autorelease_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Autorelease Delay (ms):")
        self.autorelease_delay_widget.setValue(self.profile_data.autorelease_delay * 1000)
        self.autorelease_delay_widget.valueChanged.connect(self._autorelease_delay_changed_cb)
        self.options2_layout.addWidget(self.autorelease_delay_widget)
        self.options2_layout.addStretch()


        # Activation moment
        self.options_layout.addWidget(QtWidgets.QLabel("<b>Activate on: </b>"))
        self.activate_press = QtWidgets.QRadioButton("on press")
        self.activate_release = QtWidgets.QRadioButton("on release")
        if self.profile_data.activate_on == "press":
            self.activate_press.setChecked(True)
        else:
            self.activate_release.setChecked(True)
        self.activate_press.toggled.connect(self._activation_changed_cb)
        self.activate_release.toggled.connect(self._activation_changed_cb)
        self.options_layout.addWidget(self.activate_press)
        self.options_layout.addWidget(self.activate_release)

        self.action_layout.addLayout(self.options_layout)
        self.action_layout.addLayout(self.options2_layout)

        if self.profile_data.action_sets[0] is None:
            self._add_action_selector(
                lambda x: self._add_action(0, x),
                "Short Press",
                lambda x: self._paste_action(0, x),
            )
        else:
            self._create_action_widget(
                0,
                "Short Press",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

        if self.profile_data.action_sets[1] is None:
            self._add_action_selector(
                lambda x: self._add_action(1, x),
                "Long Press",
                lambda x: self._paste_action(1, x),
            )
        else:
            self._create_action_widget(
                1,
                "Long Press",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            if self.profile_data.action_sets[0] is not None:
                self._create_action_widget(
                    0,
                    "Short Press",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )

            if self.profile_data.action_sets[1] is not None:
                self._create_action_widget(
                    1,
                    "Long Press",
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
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        if self.profile_data.action_sets[index] is None:
            self.profile_data.action_sets[index] = []
        self.profile_data.action_sets[index].append(action_item)
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()

    def _paste_action(self, index, action):
        """paste action into the container """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        if self.profile_data.action_sets[index] is None:
            self.profile_data.action_sets[index] = []
        self.profile_data.action_sets[index].append(action_item)
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()
        

    @QtCore.Slot()
    def _delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the long press action activates
        """
        self.profile_data.delay = value / 1000

    @QtCore.Slot()
    def _autorelease_delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the long press action activates
        """
        self.profile_data.autorelease_delay = value / 1000

    @QtCore.Slot()
    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_press.isChecked():
            self.profile_data.activate_on = "press"
        else:
            self.profile_data.activate_on = "release"

    def _handle_interaction(self, widget, action : gremlin.ui.input_item.ActionSetView.Interactions):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Delete:
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
        if self.profile_data.is_valid() \
            and len(self.profile_data.action_sets) == 2 \
                and None not in self.profile_data.action_sets:
            return f"Tempo: ({", ".join([a.name for a in self.profile_data.action_sets[0]])}) / ({", ".join([a.name for a in self.profile_data.action_sets[1]])})"
        else:
            return "Tempo"


class TempoContainerFunctor(gremlin.base_conditions.AbstractTriggerFunctor):

    def __init__(self, container : TempoContainer, parent = None):
        super().__init__(container, parent)


        self.delay = container.delay
        self.activate_on = container.activate_on

        self.start_time = 0
        self.timer = None
        self.value_press = None
        self.event_press = None
        self.delay = container.delay
        self.autorelease_delay = container.autorelease_delay
        self.long_nodes = []
        self.short_nodes = []

        # el = gremlin.event_handler.EventListener()
        # el.profile_start.connect(self._profile_start)

    def profile_started(self):
        # reset any prior values before start
        self.start_time = 0
        self.timer = None
        self.value_press = None
        self.event_press = None

        ec = gremlin.execution_graph.ExecutionContext()
        container_node = ec.find(self.action_data, gremlin.execution_graph.ExecutionGraphNodeType.Container)

        if not container_node:
            syslog.error(f"Unable to find this action in the execution tree: {str(self.action_data)}")
            self.valid = False
            return

        group_node = container_node.children[0] # group node is the only child of the container node
        self.action_set_nodes = [node for node in group_node.children if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.ActionSet]
        self.short_nodes = [self.action_set_nodes[0]]
        self.long_nodes = [self.action_set_nodes[1]]


    def _trigger_short_press(self, event, value, extra_data : dict = None):
        ''' triggers a short press '''

        # syslog.info(f"execute short press {self.short_index}")
        ec = gremlin.execution_graph.ExecutionContext()
        node = self.short_nodes[0]
        ec.execute_node(node, event, value, extra_data)
        

    def _trigger_long_press(self, event, value, extra_data : dict = None):
        ''' triggers a long press '''
        # syslog.info(f"execute long press {self.long_index}")
        ec = gremlin.execution_graph.ExecutionContext()
        node = self.long_nodes[0]
        ec.execute_node(node, event, value, extra_data)


    def process_event(self, event, value, extra_data = None):
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        else:
            is_pressed = event.is_pressed # use new API for GremlinEx

     
        # Copy state when input is pressed
        if is_pressed:
            self.value_press = copy.deepcopy(value)
            self.event_press = event.clone()
        

        # Execute tempo logic
        if is_pressed:
            # input press event
            self.start_time = time.time()
            self.timer = threading.Timer(self.delay, self._long_press)
            self.timer.start()

            if self.activate_on == "press":
                #print ("tempo short (activate on press)")
                #self.short_set.process_event(event, value)
                self._trigger_short_press(event, value, extra_data)

                
        else:
            # input release event
            
            if (self.start_time + self.delay) > time.time():
                if self.timer:
                    self.timer.cancel()

                if self.activate_on == "release":
                    #print ("tempo short (activate on release)")

                    threading.Thread(target=lambda: self._short_press(
                        self.event_press, # send a press event to the functors
                        self.value_press,
                        event,
                        value
                    ), daemon=False).start()
                else:
                    #self.short_set.process_event(event, value)
                    self._trigger_short_press(event, value, extra_data)

            # Long press
            else:
                #self.long_set.process_event(event, value)
                self._trigger_long_press(event, value, extra_data)
                if self.activate_on == "press":
                    #self.short_set.process_event(event, value)
                    self._trigger_short_press(event, value, extra_data)

            self.timer = None

        return False # stop execution as the logic is internal to trigger the other nodes

    def _short_press(self, event_p, value_p, event_r, value_r):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """
        self._trigger_short_press(event_p, value_p)
        time.sleep(self.autorelease_delay)
        self._trigger_short_press(event_r, value_r)




    def _long_press(self):
        self._trigger_long_press(self.event_press, self.value_press)


class TempoContainer(AbstractContainer):

    """A container with two actions which are triggered based on the duration
    of the activation.

    A short press will run the fist action while a longer press will run the
    second action.
    """

    name = "Tempo"
    tag = "tempo"
    functor = TempoContainerFunctor
    widget = TempoContainerWidget

    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Delete,
    ]

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.action_sets = []
        self.delay = 0.5 # delay for long press
        self.autorelease_delay = 0.250 # delay between press and autorelease 
        self.activate_on = "release"
        self.short_action_sets = []
        self.long_action_sets = []

    

    def _parse_xml(self, node, data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        
        super()._parse_xml(node, data)
        
        for index, as_node in enumerate(node):
            if as_node.tag == "action-set":
                if index == 0:
                    action_set = gremlin.base_profile.ActionSet("short")
                    self.short_action_sets.append(action_set)
                else:
                    action_set = gremlin.base_profile.ActionSet("long")
                    self.long_action_sets.append(action_set)
                self._parse_action_xml(as_node, action_set, data)
                
          

        self.delay = float(node.get("delay", 0.5))
        self.autorelease_delay = float(node.get("autorelease-delay", 0.25))
        self.activate_on = node.get("activate-on", "release")
        

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", TempoContainer.tag)
        node.set("delay", safe_format(self.delay, float))
        node.set("autorelease-delay", safe_format(self.autorelease_delay, float))

        node.set("activate-on", self.activate_on)
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
        return True # len(self.action_sets) == 2 and None not in self.action_sets
    



# Plugin definitions
version = 1
name = "tempo"
create = TempoContainer
