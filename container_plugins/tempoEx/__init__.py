# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2019 Lionel Ott - Modified by Muchimi (C) EMCS 2024 and other contributors
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

import copy
import logging
import threading
import time
from xml.etree import ElementTree

from PySide6 import QtWidgets
from PySide6.QtCore import Slot

from  gremlin.clipboard import Clipboard
import gremlin
import gremlin.base_classes
import gremlin.plugin_manager
import gremlin.ui.common
import gremlin.ui.input_item
from gremlin.profile import safe_format, safe_read


class TempoExContainerWidget(gremlin.ui.input_item.AbstractContainerWidget):

    """Container with two actions, triggered based on activation duration."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)
        


    def _create_action_ui(self):
        """Creates the UI components."""
        self.profile_data.create_or_delete_virtual_button()
        self.short_layout = QtWidgets.QVBoxLayout()
        self.long_layout = QtWidgets.QVBoxLayout()
        self.short_group_widget = QtWidgets.QGroupBox("Short Press Action Sets")
        self.short_group_widget.setStyleSheet("QGroupBox { font-weight: bold; }")
        self.short_group_widget.setLayout(self.short_layout)
        self.long_group_widget = QtWidgets.QGroupBox("Long Press Action Sets")
        self.long_group_widget.setStyleSheet("QGroupBox { font-weight: bold; }")
        self.long_group_widget.setLayout(self.long_layout)
        self.options_layout = QtWidgets.QHBoxLayout()


        # Activation delay
        self.options_layout.addWidget(
            QtWidgets.QLabel("<b>Long press delay: </b>")
        )
        self.delay_input = gremlin.ui.common.DynamicDoubleSpinBox()
        self.delay_input.setRange(0.1, 2.0)
        self.delay_input.setSingleStep(0.1)
        self.delay_input.setValue(0.5)
        self.delay_input.setValue(self.profile_data.delay)
        self.delay_input.valueChanged.connect(self._delay_changed_cb)
        self.options_layout.addWidget(self.delay_input)
        self.options_layout.addStretch()



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

        # chain options
        self.options_layout.addWidget(QtWidgets.QLabel("<b>Chain </b>"))
        self.chain_short_widget = QtWidgets.QCheckBox("short actions")
        self.chain_long_widget = QtWidgets.QCheckBox("long actions")

 
        if self.profile_data.chain_short:
            self.chain_short_widget.setChecked(True)

        if self.profile_data.chain_long:
            self.chain_long_widget.setChecked(True)

        self.chain_short_widget.checkStateChanged.connect(self._chain_short_changed_cb)
        self.chain_long_widget.checkStateChanged.connect(self._chain_long_changed_cb)

        self.options_layout.addWidget(self.chain_short_widget)
        self.options_layout.addWidget(self.chain_long_widget)

        
        # chain timeout
        self.options_layout.addWidget(QtWidgets.QLabel("<b>Chain Timeout:</b> "))
        self.timeout_input = gremlin.ui.common.DynamicDoubleSpinBox()
        self.timeout_input.setRange(0.0, 3600.0)
        self.timeout_input.setSingleStep(0.5)
        self.timeout_input.setValue(0)
        self.timeout_input.setValue(self.profile_data.timeout)
        self.timeout_input.valueChanged.connect(self._timeout_changed_cb)
        self.options_layout.addWidget(self.timeout_input)


        self.action_layout.addLayout(self.options_layout)
        self.action_layout.addWidget(self.short_group_widget)
        self.action_layout.addWidget(self.long_group_widget)
        # self.action_layout.addLayout(self.short_layout)
        # self.action_layout.addLayout(self.long_layout)

        

        self.short_action_selector = gremlin.ui.common.ActionSelector(
            self.profile_data.get_input_type()
        )
        self.short_action_selector.action_label.setText("Short Action")
        

        self.long_action_selector = gremlin.ui.common.ActionSelector(
            self.profile_data.get_input_type()
        )
        self.long_action_selector.action_label.setText("Long Action")


        self.short_layout.addWidget(self.short_action_selector)        
        self.long_layout.addWidget(self.long_action_selector)        


        self.short_action_selector.action_added.connect(self._add_short_action)
        self.short_action_selector.action_paste.connect(self._paste_short_action)
        self.long_action_selector.action_added.connect(self._add_long_action)
        self.long_action_selector.action_paste.connect(self._paste_long_action)

        # remember what widget belongs to what list so we can find things by widget
        self.short_layout_widget_list = []
        self.long_layout_widget_list = []


        # create short press container actions
        for i, action_set in enumerate(self.profile_data.short_action_sets):
            widget = self._create_action_set_widget(
                action_set if action_set is not None else [],
                f"Chain Short Action {i:d}",
                gremlin.ui.common.ContainerViewTypes.Action
            )
            self.short_layout.addWidget(widget)
            self.short_layout_widget_list.append(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

        # create long press container actions
        for i, action_set in enumerate(self.profile_data.long_action_sets):
            widget = self._create_action_set_widget(
                action_set if action_set is not None else [],
                f"Chain Long Action {i:d}",
                gremlin.ui.common.ContainerViewTypes.Action
            )
            self.long_layout.addWidget(widget)
            self.long_layout_widget_list.append(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)



    def _create_condition_ui(self):
        if self.profile_data.activation_condition_type == "action":
            if self.profile_data.action_sets[0] is not None:
                self._create_action_widget(
                    0,
                    "Short Press",
                    self.activation_condition_layout,
                    gremlin.ui.common.ContainerViewTypes.Condition
                )

            if self.profile_data.action_sets[1] is not None:
                self._create_action_widget(
                    1,
                    "Long Press",
                    self.activation_condition_layout,
                    gremlin.ui.common.ContainerViewTypes.Condition
                )

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

    def _add_short_action(self, action_name):
        """Adds a new action to the short action list

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        self.profile_data.short_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                

    def _paste_short_action(self, action):
        ''' called when a paste occurs '''
        logging.getLogger("system").info("Paste short action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action)
        self.profile_data.short_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                

    def _add_long_action(self, action_name):
        """Adds a new action to the long action list

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        self.profile_data.long_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                
    
    def _paste_long_action(self, action):
        ''' called when a paste occurs '''
        logging.getLogger("system").info("Paste long action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action)
        self.profile_data.long_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                

    def _delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the long press action activates
        """
        self.profile_data.delay = value

    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_press.isChecked():
            self.profile_data.activate_on = "press"
        else:
            self.profile_data.activate_on = "release"

    def _chain_short_changed_cb(self, value):
        ''' occurs when short chain checkbox is changed '''
        self.profile_data.chain_short = self.chain_short_widget.isChecked()


    def _chain_long_changed_cb(self, value):
        ''' occurs when short chain checkbox is changed '''
        self.profile_data.chain_long = self.chain_long_widget.isChecked()

    def _timeout_changed_cb(self, value):
        """Stores changes to the timeout element.

        :param value the new value of the timeout field
        """
        self.profile_data.timeout = value        



    def _find_widget(self, widget):
        """Returns the short or long action set and its index of the provided widget as a pair (action_set, index)  or (None, -1) if not found

        :param widget the widget for which to return the index
        :return the index of the provided widget, -1 if not present
        """
        
        if widget in self.short_layout_widget_list:
            data = self.short_layout_widget_list
            action_sets = self.profile_data.short_action_sets
        elif widget in self.long_layout_widget_list:
            data = self.long_layout_widget_list
            action_sets = self.profile_data.long_action_sets
        else:
            return (None, -1)
        
        
        for i, entry in enumerate(data):
            if entry == widget:
                return (action_sets,i)
        
        return (None, -1)

    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """

        # determine which widget this is
        action_sets, index = self._find_widget(widget)
        if index != -1:

            if action ==  gremlin.ui.input_item.ActionSetView.Interactions.Edit:
                action_sets[index] = []
            elif action ==  gremlin.ui.input_item.ActionSetView.Interactions.Up:
                if index > 0:
                    action_sets[index], action_sets[index-1] =  action_sets[index-1], action_sets[index]
            elif action ==  gremlin.ui.input_item.ActionSetView.Interactions.Down:
                if index < len(action_sets) - 1:
                    action_sets[index], action_sets[index + 1] = action_sets[index + 1], action_sets[index]

            self.container_modified.emit()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        if self.profile_data.is_valid():
            return f"TempoEx: {len(self.profile_data.short_action_sets)} short actions,{len(self.profile_data.long_action_sets)} long actions"
        else:
            return "TempoEx"


class TempoExContainerFunctor(gremlin.base_classes.AbstractFunctor):

    def __init__(self, container):
        super().__init__(container)
        self.action_sets = [[],[]]
        for action_set in container.short_action_sets:
            self.action_sets[0].append(
                gremlin.execution_graph.ActionSetExecutionGraph(action_set)
            )
        for action_set in container.long_action_sets:
            self.action_sets[1].append(
                gremlin.execution_graph.ActionSetExecutionGraph(action_set)
            )            
        
        self.short_set = self.action_sets[0]
        self.long_set =  self.action_sets[1]
        self.delay = container.delay
        self.activate_on = container.activate_on

        self.start_time = 0
        self.timer = None
        self.value_press = None
        self.event_press = None
        self.chain_short = True # chain by default
        self.chain_long = True # chain by default
        self.short_index = 0
        self.long_index = 0
        self.last_short_execution = 0.0
        self.last_long_execution = 0.0
        self.last_short_value = None
        self.short_timeout = container.timeout
        self.long_timeout = container.timeout

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        if container.activation_condition_type == "container":
            for cond in container.activation_condition.conditions:
                if isinstance(cond, gremlin.base_classes.InputActionCondition):
                    if cond.comparison == "press":
                        self.switch_on_press = True        


    def _trigger_short_press(self, event, value):
        ''' triggers a short press '''

        if self.short_timeout > 0.0:
            if self.last_short_execution + self.short_timeout < time.time():
                # logging.getLogger("system").info(f"reset short index")
                self.short_index = 0
            self.last_short_execution = time.time()

        if self.short_index < len(self.short_set):
            # logging.getLogger("system").info(f"execute short press {self.short_index}")
            if self.short_index  == 1:
                pass
            self.short_set[self.short_index].process_event(event, value)

        if self.chain_short and (self.switch_on_press and value.current) or not value.current:
            # bump short index if chaining
            self.short_index = (self.short_index + 1) % len(self.short_set)
            # logging.getLogger("system").info(f"bump short index {self.short_index}")

    def _trigger_long_press(self, event, value):
        ''' triggers a long press '''

        if self.long_timeout > 0.0:
            if self.last_long_execution + self.long_timeout < time.time():
                # logging.getLogger("system").info(f"reset long index")
                self.long_index = 0
            self.last_long_execution = time.time()

        if self.long_index < len(self.long_set):
            # logging.getLogger("system").info(f"execute long press {self.long_index}")
            self.long_set[self.long_index].process_event(event, value)

        if self.chain_long and (self.switch_on_press and value.current) or not value.current:
            # bump long index if chaining
            self.long_index = (self.long_index + 1) % len(self.long_set)
            # logging.getLogger("system").info(f"bump long index {self.long_index}")            

    def process_event(self, event, value):
        # TODO: Currently this does not handle hat or axis events, however
        #       virtual buttons created on those inputs is supported
        if not isinstance(value.current, bool):
            logging.getLogger("system").warning(
                f"Invalid data type received in TempoEx container: {type(event.value)}"
            )
            return False

        # Copy state when input is pressed
        if value.current:
            self.value_press = copy.deepcopy(value)
            self.event_press = event.clone()

        # Execute tempoEx logic
        if value.current:
            # raw button was pressed - start timer for long/short press
            self.start_time = time.time()
            self.timer = threading.Timer(self.delay, self._long_press)
            self.timer.start()

            if self.activate_on == "press":
                # logging.getLogger("system").info(f"execute short press (activation mode = press)")
                self._trigger_short_press(self.event_press, self.value_press)

        else:
            # raw button was released
            # Short press (activate on button release)
            if (self.start_time + self.delay) > time.time():
                self.timer.cancel() # kill long press timer - use short press

                if self.activate_on == "release":
                    threading.Thread(target=lambda: self._short_press(
                        self.short_index,                                            
                        self.event_press,
                        self.value_press,
                        event,
                        value
                    )).start()
                else:
                    self._trigger_short_press(event, value)
                
            else:
                # Long press
                self._trigger_long_press(event, value)
                if self.activate_on == "press":
                    # logging.getLogger("system").info(f"execute short press (activation mode = press) in LONG PRESS")
                    self._trigger_short_press(event, value)


            self.timer = None

        return True

    def _short_press(self, index, event_p, value_p, event_r, value_r):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """

        self._trigger_short_press(event_p, value_p)
        time.sleep(0.05)
        self._trigger_short_press(event_r, value_r)


    def _long_press(self):
        """Callback executed, when the delay expires."""

        self._trigger_long_press(self.event_press, self.value_press)

class TempoExContainer(gremlin.base_classes.AbstractContainer):

    """A container with two actions which are triggered based on the duration
    of the activation.

    A short press will run the fist action while a longer press will run the
    second action.
    """

    name = "TempoEx"
    tag = "tempoEx"
    functor = TempoExContainerFunctor
    widget = TempoExContainerWidget
    input_types = [
        gremlin.common.InputType.JoystickAxis,
        gremlin.common.InputType.JoystickButton,
        gremlin.common.InputType.JoystickHat,
        gremlin.common.InputType.Keyboard
    ]
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Up,
        gremlin.ui.input_item.ActionSetView.Interactions.Down,
        gremlin.ui.input_item.ActionSetView.Interactions.Edit,
        
    ]

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent)
        self.short_action_sets = []
        self.long_action_sets = []
        self.delay = 0.5
        self.activate_on = "release"
        self.timeout = 0.0
        self.chain_short = True
        self.chain_long = True
        
        # # setup dummy action set (even if we're not using the default action set, the container won't be executed if it doesn't have at least one action defined)
        # action_name_map = gremlin.plugin_manager.ActionPlugins().tag_map
        # noop = action_name_map["noop"](self)
        # self.action_sets = [[noop]]
    


    def _parse_xml(self, node):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        # setup a noop action set as the only action set as we have a custom set we use
        
        self.short_action_sets = []
        self.long_action_sets = []
        super()._parse_xml(node)
        self.delay = float(node.get("delay", 0.5))
        self.activate_on = node.get("activate-on", "release")
        self.chain_long = safe_read(node, "chain_long", bool)
        self.chain_short = safe_read(node, "chain_short", bool)
        self.timeout = float(node.get("timeout", 0.0))
        # custom read of action sets
        for as_node in node:
            if as_node.tag == "short-action-set":
                action_set = []
                self._parse_action_xml(as_node, action_set)
                self.short_action_sets.append(action_set)
            if as_node.tag == "long-action-set":
                action_set = []
                self._parse_action_xml(as_node, action_set)
                self.long_action_sets.append(action_set)


    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", TempoExContainer.tag)
        node.set("delay", str(self.delay))
        node.set("activate-on", self.activate_on)
        node.set("chain_short",safe_format(self.chain_short, bool))
        node.set("chain_long",safe_format(self.chain_long, bool))
        node.set("timeout", str(self.timeout))
        for actions in self.short_action_sets:
            as_node = ElementTree.Element("short-action-set")
            for action in actions:
                as_node.append(action.to_xml())
            node.append(as_node)
        for actions in self.long_action_sets:
            as_node = ElementTree.Element("long-action-set")
            for action in actions:
                as_node.append(action.to_xml())
            node.append(as_node)

        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.short_action_sets) > 0 or len(self.long_action_sets) > 0
    
    def get_action_sets(self):
        """ returns action sets - override because we have custom sets """
        return self.short_action_sets + self.long_action_sets


# Plugin definitions
version = 1
name = "tempoEx"
create = TempoExContainer
