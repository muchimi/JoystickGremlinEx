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
from enum import Enum, auto
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore
from PySide6.QtCore import Slot

import gremlin.base_conditions
from  gremlin.clipboard import Clipboard
import gremlin
import gremlin.base_classes
import gremlin.config
import gremlin.plugin_manager
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.profile import safe_format, safe_read
from gremlin.ui.input_item import AbstractContainerWidget, AbstractActionWidget
from gremlin.base_profile import AbstractContainer
import gremlin.execution_graph
import gremlin.base_profile
from gremlin.input_types import InputType
from shiboken6 import Shiboken
syslog = logging.getLogger("system")
class TempoExContainerWidget(AbstractContainerWidget):

    """Container with two actions, triggered based on activation duration."""

    def __init__(self, profile_data : TempoExContainer, parent=None):
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
        self.short_widget, self.short_layout = gremlin.ui.ui_common.getVContainer()
        self.short_widget.setContentsMargins(8,0,0,0)
        self.long_widget, self.long_layout = gremlin.ui.ui_common.getVContainer()
        self.long_widget.setContentsMargins(8,0,0,0)
        self.double_widget, self.double_layout = gremlin.ui.ui_common.getVContainer()
        self.double_widget.setContentsMargins(8,0,0,0)
        self.options_widget, self.options_layout = gremlin.ui.ui_common.getVContainer()

        self.longpress_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Long Press Delay (ms):")
        self.longpress_delay_widget.setToolTip("Delay to detect long press, should be greater than double tap delay")
        self.longpress_delay_widget.setValue(self.profile_data.delay * 1000)
        self.longpress_delay_widget.valueChanged.connect(self._delay_changed_cb)

        self.dtap_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Double-Tap Delay (ms):")
        self.dtap_delay_widget.setToolTip("Delay to detect double tap")
        self.dtap_delay_widget.setValue(self.profile_data.doubletap_delay * 1000)
        self.dtap_delay_widget.valueChanged.connect(self._dtap_delay_changed_cb)

        self.autorelease_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Autorelease Delay (ms):")
        self.autorelease_delay_widget.setValue(self.profile_data.autorelease_delay * 1000)
        self.autorelease_delay_widget.valueChanged.connect(self._autorelease_delay_changed_cb)
                

        widgets = [
            self.longpress_delay_widget,
            self.dtap_delay_widget,
            self.autorelease_delay_widget,
        ]

        widget, _ = gremlin.ui.ui_common.getVContainer(widgets)
        self.options_layout.addWidget(widget)
       

        # Activation moment
        self.activate_press = QtWidgets.QRadioButton("on press")
        self.activate_release = QtWidgets.QRadioButton("on release")

        widgets = ["<b>Activate On:</b",
                   self.activate_press,
                   self.activate_release]

        widget, _ = gremlin.ui.ui_common.getHContainer(widgets)

        self.options_layout.addWidget(widget)


        if self.profile_data.activate_on == "press":
            self.activate_press.setChecked(True)
        else:
            self.activate_release.setChecked(True)        


        self.activate_press.toggled.connect(self._activation_changed_cb)
        self.activate_release.toggled.connect(self._activation_changed_cb)

        # chain options
        self.chain_short_widget = QtWidgets.QCheckBox("short actions")
        self.chain_short_widget.setChecked(self.profile_data.chain_short)
        self.chain_short_widget.clicked.connect(self._chain_short_changed_cb)

        self.chain_long_widget = QtWidgets.QCheckBox("long actions")
        self.chain_long_widget.setChecked(self.profile_data.chain_long)
        self.chain_long_widget.clicked.connect(self._chain_long_changed_cb)

        self.chain_double_widget = QtWidgets.QCheckBox("double tap actions")
        self.chain_double_widget.setChecked(self.profile_data.chain_double)
        self.chain_double_widget.clicked.connect(self._chain_double_changed_cb)

        widgets = [
            self.chain_short_widget,
            self.chain_long_widget, 
            self.chain_double_widget,
        ]
        
        # chain timeout



        self.timeout_input = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.timeout_input.setRange(0.0, 3600.0)
        self.timeout_input.setSingleStep(0.5)
        self.timeout_input.setValue(0)
        self.timeout_input.setValue(self.profile_data.timeout)
        self.timeout_input.valueChanged.connect(self._timeout_changed_cb)
        

        widgets = ["<b>Chain Timeout:</b>",
                   self.timeout_input,
                   ]

        widget, _ = gremlin.ui.ui_common.getHContainer(widgets)
        self.options_layout.addWidget(widget)



        widgets = [
            self.options_widget,
            gremlin.ui.ui_common.QHeaderLabel("Short Press Action Sets"),
            self.short_widget,
            gremlin.ui.ui_common.QHeaderLabel("Long Press Action Sets"),
            self.long_widget,
            gremlin.ui.ui_common.QHeaderLabel("Double Tap Press Action Sets"),
            self.double_widget,

        ]

        self.content_widget, self.content_layout = gremlin.ui.ui_common.getVContainer(widgets)
        

        self.short_action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            self.profile_data.input_item
        )
        self.short_action_selector.action_label.setText("Short Press Action(s)")
        

        self.long_action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            self.profile_data.input_item
        )
        self.long_action_selector.action_label.setText("Long Press Action(s)")


        self.double_action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            self.profile_data.input_item
        )
        self.double_action_selector.action_label.setText("Double Tap Action(s)")


        self.short_layout.addWidget(self.short_action_selector)        
        self.long_layout.addWidget(self.long_action_selector)        
        self.double_layout.addWidget(self.double_action_selector)


        self.short_action_selector.action_added.connect(self._add_short_action)
        self.short_action_selector.action_paste.connect(self._paste_short_action)
        self.long_action_selector.action_added.connect(self._add_long_action)
        self.long_action_selector.action_paste.connect(self._paste_long_action)
        self.double_action_selector.action_added.connect(self._add_double_action)
        self.double_action_selector.action_paste.connect(self._paste_double_action)
        


        # remember what widget belongs to what list so we can find things by widget
        self.short_layout_widget_list = []
        self.long_layout_widget_list = []
        self.double_layout_widget_list = []


        # create short press container actions
        
        action_sets = [action_set for action_set in self.profile_data.short_action_sets if action_set]
        for i, action_set in enumerate(action_sets):
            widget = self._create_action_set_widget(
                action_set if action_set is not None else [],
                f"Chain Short Action {i+1:d}",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )
            self.short_layout.addWidget(widget)
            self.short_layout_widget_list.append(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

        # create long press container actions
        action_sets = [action_set for action_set in self.profile_data.long_action_sets if action_set]
        for i, action_set in enumerate(action_sets):
            if action_set is not None:
                widget = self._create_action_set_widget(
                    action_set,
                    f"Chain Long Action {i+1:d}",
                    gremlin.ui.ui_common.ContainerViewTypes.Action
                )
            self.long_layout.addWidget(widget)
            self.long_layout_widget_list.append(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

    
        # create double tap  container actions
        action_sets = [action_set for action_set in self.profile_data.double_action_sets if action_set]
        for i, action_set in enumerate(action_sets):
            if action_set is not None:
                widget = self._create_action_set_widget(
                    action_set,
                    f"Chain DoubleTap Action {i+1:d}",
                    gremlin.ui.ui_common.ContainerViewTypes.Action
                )
            self.double_layout.addWidget(widget)
            self.double_layout_widget_list.append(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

        self.action_layout.addWidget(self.content_widget)
    

    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            if self.profile_data.short_action_sets:
                action_set = self.profile_data.short_action_sets[0]
                if action_set is not None:
                    self._create_action_widget(
                        action_set,
                        "Short Press",
                        self.activation_condition_layout,
                        gremlin.ui.ui_common.ContainerViewTypes.Conditions
                    )

            if self.profile_data.long_action_sets:
                action_set = self.profile_data.long_action_sets[0]
                if action_set is not None:
                    self._create_action_widget(
                        action_set,
                        "Long Press",
                        self.activation_condition_layout,
                        gremlin.ui.ui_common.ContainerViewTypes.Conditions
                    )

    def _create_action_widget(self, action_set, label, layout, view_type):
        """Creates a new action widget.

        :param index the index at which to store the created action
        :param label the name of the action to create
        """
        widget = self._create_action_set_widget(
            action_set,
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
        action_item.data = "short"
        self.profile_data.short_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                

    def _paste_short_action(self, action, container):
        ''' called when a paste occurs '''
        syslog.info("Paste short action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        action_item.data = "short"
        self.profile_data.short_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                

    def _add_long_action(self, action_name):
        """Adds a new action to the long action list

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        action_item.data = "long"
        self.profile_data.long_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                
    
    def _paste_long_action(self, action, container):
        ''' called when a paste occurs '''
        syslog.info("Paste long action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        action_item.data = "long"
        self.profile_data.long_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                


    def _add_double_action(self, action_name):
        """Adds a new action to the double action list

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        action_item.data = "double"
        self.profile_data.double_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                
    
    def _paste_double_action(self, action, container):
        ''' called when a paste occurs '''
        syslog.info("Paste double action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        action_item.data = "double"
        self.profile_data.double_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()                        

    @QtCore.Slot()
    def _delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the long press action activates
        """
        # value = value/1000
        # dtap_value = self.profile_data.doubletap_delay
        # if value <= dtap_value:
        self.profile_data.delay = value/1000 # to seconds

    def _dtap_delay_changed_cb(self, value):
        ''' double tap value change 
        :param value the value after which the long press action activates
        '''
        self.profile_data.doubletap_delay = value/1000 # to seconds

    @QtCore.Slot()
    def _autorelease_delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the long press action activates
        """
        self.profile_data.autorelease_delay = value / 1000

    
    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_press.isChecked():
            self.profile_data.activate_on = "press"
        else:
            self.profile_data.activate_on = "release"

    @QtCore.Slot(bool)
    def _chain_short_changed_cb(self, checked):
        ''' occurs when short chain checkbox is changed '''
        self.profile_data.chain_short = checked


    @QtCore.Slot(bool)
    def _chain_long_changed_cb(self, checked):
        ''' occurs when short chain checkbox is changed '''
        self.profile_data.chain_long = checked

    @QtCore.Slot(bool)
    def _chain_double_changed_cb(self, checked):
        ''' occurs when double chain checkbox is changed '''
        self.profile_data.chain_double = checked


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
        title = "TempoEx: "
        if self.profile_data.is_valid() \
            and len(self.profile_data.action_sets) == 2 \
                and None not in self.profile_data.action_sets:
            title += f"({", ".join([a.name for a in self.profile_data.action_sets[0]])}) / ({", ".join([a.name for a in self.profile_data.action_sets[1]])})"
        return title
        
   

class TempoExContainerFunctor(gremlin.base_conditions.AbstractTriggerFunctor):

    def __init__(self, container : TempoExContainer, parent = None):
        super().__init__(container, parent)


        # self.action_sets = [[],[]]
        # for action_set in container.short_action_sets:
        #     self.action_sets[0].append(
        #         gremlin.execution_graph.ActionSetExecutionGraph(action_set, parent)
        #     )
        # for action_set in container.long_action_sets:
        #     self.action_sets[1].append(
        #         gremlin.execution_graph.ActionSetExecutionGraph(action_set, parent)
        #     )            
        
        # self.short_set = self.action_sets[0]
        # self.long_set =  self.action_sets[1]


        self.delay = container.delay
        self.autorelease_delay = container.autorelease_delay
        self.activate_on = container.activate_on

        self.start_time = 0
        self.long_press_timer = None
        self.short_press_timer = None
        self.value_press = None
        self.event_press = None
        self.chain_short = True # chain by default
        self.chain_long = True # chain by default
        self.short_index = 0
        self.long_index = 0
        self.double_index = 0
        self.last_short_execution = 0.0
        self.last_long_execution = 0.0
        self.last_short_value = None
        self.short_timeout = container.timeout
        self.long_timeout = container.timeout
        self.dtap_offset = container.doubletap_delay

        self.short_nodes = [] # list of short action set nodes
        self.long_nodes = [] # list of long action set nodes
        self.double_nodes = [] # list of double tap actions
        

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        if container.has_conditions:
            for cond in container.activation_condition.conditions:
                if isinstance(cond, gremlin.base_conditions.InputActionCondition):
                    if cond.comparison == "press":
                        self.switch_on_press = True       

        self.dtap_enabled = False
        
        self.last_trigger = None
        self.valid = False # validated during profile start

    def profile_started(self):
        # reset any prior values before start
        self.start_time = time.time()
        self.long_press_timer = None
        self.short_press_timer = None
        self.value_press = None
        self.event_press = None
        self.chain_short = True # chain by default
        self.chain_long = True # chain by default
        self.chain_double = True # chain by default
        self.short_index = 0
        self.long_index = 0
        self.dtap_index = 0
        self.last_short_execution = 0.0
        self.last_long_execution = 0.0
        self.last_short_value = None
        self.dtap_timeout = None
        self.verbose = gremlin.config.Configuration().verbose_mode_container
        self.last_trigger = None
        self.trigger_mode = None # what to trigger (short or long press)

        self.valid = True

        
        ec = gremlin.execution_graph.ExecutionContext()
        container_node = ec.find(self.action_data, gremlin.execution_graph.ExecutionGraphNodeType.Container)

        if not container_node:
            # if we get here it usually means an instance of the functor is still in memory and hooked to the execution graph which should not happen
            syslog.error(f"Unable to find a container in the execution tree: {str(self.action_data)} - missing container ID: [{self.action_data.id}]")
            self.valid = False
            return
        
        assert container_node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.Container,"Logic error: Node is not a container node"

        group_node = container_node.children[0] # group node is the only child of the container node
        action_set_nodes = [node for node in group_node.children if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.ActionSet and node.action_set and node.has_actions]
        self.short_nodes = []
        self.long_nodes = []
        self.dtap_nodes = []
        for node in action_set_nodes:
            if node.has_actions:
                for action in node.action_set:
                    match action.data:
                        case "short":
                            self.short_nodes.append(node)
                        case "long":
                            self.long_nodes.append(node)
                        case "double":
                            self.dtap_nodes.append(node)
        
        # true if double tap enabled if we have double tap nodes to execute and not running in release mode

        active_nodes = self.short_nodes + self.long_nodes + self.dtap_nodes
        if not active_nodes:
            syslog.warning(f"TEMPOEX: warning: no action nodes found to execute for container [{self.action_data.id}].")
            self.valid = False
            return


        self.dtap_enabled =  len(self.dtap_nodes) > 0 
        if self.dtap_enabled and self.activate_on != "release":
            syslog.warning("TEMPOEX: warning: double tap requires 'release' mode for TempoEx. DoubleTap function disabled.")
            self.dtap_enabled = False

        self.trigger_release = False # press mode

        if self.dtap_enabled and self.action_data.doubletap_delay >= self.delay:
            syslog.warning("TEMPOEX: warning: double tap delay exceeds long delay.  DoubleTap function disabled.")
            self.dtap_enabled = False
        

    def _trigger_double_press(self, event, value, extra_data :dict = None):
        ''' called on double tap trigger '''

        is_pressed = event.is_pressed

        if is_pressed:
            if self.last_trigger:
                return # wrong mode
            self.last_trigger = "double"
        else:
            if not self.last_trigger or self.last_trigger != "double":
                # wrong mode
                return
            self.last_trigger = None # reset

        # double tap processing
        if self.verbose:
            if event.is_pressed:            
                syslog.info("double tap (press)")
            else:
                syslog.info("double tap (release)")
        node_count = len(self.dtap_nodes)
        if node_count:
            if self.dtap_index < node_count:
                ec = gremlin.execution_graph.ExecutionContext()
                node = self.short_nodes[self.dtap_index]
                ec.execute_node(node, event, value, extra_data)

            # index
            if self.chain_double and (self.switch_on_press and is_pressed) or not is_pressed:
                self.dtap_index = (self.dtap_index + 1) % node_count


    def _trigger_short_press(self, event, value, extra_data : dict = None):
        ''' triggers a short press '''
        
        
        is_pressed = event.is_pressed
        if is_pressed:
            if self.last_trigger:
                return # wrong mode
            self.last_trigger = "short"
        else:
            if not self.last_trigger or self.last_trigger != "short":
                # wrong mode
                return
            self.last_trigger = None # reset
        
        
        time_now = time.time()
        

        if self.verbose:
            if is_pressed:            
                syslog.info("single tap (press)")
            else:
                syslog.info("single tap (release)")

        event_clone = event.clone()
        self.long_press_timer = threading.Timer(self.dtap_offset, lambda: self._trigger_double_tap(event_clone, value, extra_data))

        # regular short press processing
        if self.short_timeout and self.short_timeout > 0.0:
            if self.last_short_execution + self.short_timeout < time_now:
                # syslog.info(f"reset short index")
                self.short_index = 0
            self.last_short_execution = time_now

    
        node_count = len(self.short_nodes)
        if node_count:
            if self.short_index < len(self.short_nodes):
                # syslog.info(f"execute short press {self.short_index}")
                ec = gremlin.execution_graph.ExecutionContext()
                node = self.short_nodes[self.short_index]
                ec.execute_node(node, event, value, extra_data)
                #self.short_set[self.short_index].process_event(event, value)

        
            if self.chain_short and (self.switch_on_press and is_pressed) or not is_pressed:
                # bump short index if chaining
                self.short_index = (self.short_index + 1) % node_count
                # syslog.info(f"bump short index {self.short_index}")
    



    def _trigger_long_press(self, event, value, extra_data : dict = None):
        ''' triggers a long press '''

        is_pressed = event.is_pressed
        if is_pressed:
            if self.last_trigger:
                return # wrong mode
            self.last_trigger = "long"
        else:
            if not self.last_trigger or self.last_trigger != "long":
                # wrong mode
                return
            self.last_trigger = None # reset
            

        if self.verbose:
            if is_pressed:            
                syslog.info("long tap (press)")
            else:
                syslog.info("long tap (release)")

        if self.long_timeout > 0.0:
            if self.last_long_execution + self.long_timeout < time.time():
                # syslog.info(f"reset long index")
                self.long_index = 0
            self.last_long_execution = time.time()

        if self.long_index < len(self.long_nodes):
            # syslog.info(f"execute long press {self.long_index}")
            ec = gremlin.execution_graph.ExecutionContext()
            node = self.long_nodes[self.long_index]
            ec.execute_node(node, event, value, extra_data)
            #self.long_set[self.long_index].process_event(event, value)

        node_count = len(self.long_nodes)
        if node_count > 0:
            if self.chain_long and (self.switch_on_press and value.current) or not value.current:
                # bump long index if chaining
                self.long_index = (self.long_index + 1) % node_count
                # syslog.info(f"bump long index {self.long_index}")       

    def process_event(self, event, value, extra_data = None) -> bool:

        if not self.valid:
            return False

        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        else:
            is_pressed = event.is_pressed # use new API for GremlinEx

        
        verbose = self.verbose

        #if verbose: syslog.info(f"tempoex pressed: {is_pressed}")

        # Copy state when input is pressed
        if is_pressed:
            self.value_press = copy.deepcopy(value)
            self.event_press = event.clone()
            self.event_release = event.clone()
            self.event_release.is_pressed = False
            self.value_release = copy.deepcopy(value)
        
            time_now = time.time() # current time
            self.trigger_release = False # press mode
            
            if self.verbose: syslog.info(f"press detected trigger mode: {self.trigger_mode}")

            if self.activate_on == "press":
                # double tap not active in this mode

                # trigger long press (timers are reset if a release comes)
                if verbose: syslog.info("start long press timer")
                self.long_press_timer = threading.Timer(self.delay, lambda: self._timer_long_press_mode_press(self.event_press, self.value_press, extra_data))
                self.long_press_timer.start()



            else:
                # activate on release mode


                if self.dtap_enabled:
                    if not self.trigger_mode:

                        # assume single tap
                        self.trigger_mode = "single" # single tap detected

                        # trigger short press unless we detect another click or release
                        #if verbose: syslog.info("start short press timer")
                        self.short_press_timer = threading.Timer(self.dtap_offset, lambda: self._timer_short_press(self.event_press, self.value_press, extra_data))
                        self.short_press_timer.start()


                        # trigger long press (timers are reset if a release comes)
                        if verbose: syslog.info("start long press timer")
                        self.long_press_timer = threading.Timer(self.delay, lambda: self._timer_long_press(self.event_press, self.value_press, extra_data))
                        self.long_press_timer.start()

                    else:
                        # detected another click while short press timer running
                        if self.short_press_timer:
                            self.short_press_timer.cancel()
                            self.short_press_timer = None
                        
                        #if self.trigger_mode == "single":
                            # double tap trigger
                            #if verbose: syslog.info("double tap detect")
                        self.trigger_mode = "double"
                    
                        
                        
                else:
                    # single tap
                    #if verbose: syslog.info("single tap detect")
                    self.trigger_mode = "short" # assume a short tap, if the timer lapses, will be set to long tap
                    if self.short_press_timer:
                        self.short_press_timer.cancel()
                        self.short_press_timer = None
                    
                    # trigger long press (timers are reset if a release comes)
                    #if verbose: syslog.info("start long press timer")
                    self.long_press_timer = threading.Timer(self.delay, lambda: self._timer_long_press(self.event_press, self.value_press, extra_data))
                    self.long_press_timer.start()

            self.start_time = time_now # reset start

        else:
            # release

            if self.activate_on == "press":
                # kill long press timer
                
                if self.long_press_timer:
                    # release occured before long press timer finished
                    self.long_press_timer.cancel()
                    self.long_press_timer = None

                if not self.trigger_mode:
                    # long press didn't execute, trigger short press release cycle
                    self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)

                elif self.trigger_mode == "long":
                    # long press was already triggered, release it on release
                    self._trigger_long_press(event, value, extra_data)
                
                self.trigger_mode = None # reset

            else:
                # release mode
            

                self.trigger_release = True # indicate a release trigger occured

                if self.long_press_timer:
                    #if self.verbose: syslog.info("stop long press timer")
                    self.long_press_timer.cancel()
                    self.long_press_timer = None

                if self.verbose: syslog.info(f"release detected: {self.trigger_mode}")

                if self.trigger_mode:
                    # release the corresponding press
                    
                    match self.trigger_mode:
                        case "short":
                            # short release
                            self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                            self.trigger_mode = None
                        case "double":
                            # double tap
                            self._double_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                            self.trigger_mode = None
                        case "long":
                            # long release
                            self._long_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                            self.trigger_mode = None

        return False # stop execution because it's handled internally
    

    def _timer_short_press(self, event, value, extra_data):
        ''' short press timer callback '''
        # trigger the short press 
        if self.verbose: syslog.info("short press timer lapsed")
        self.trigger_mode = "short"
        self.short_press_timer = None
        # retrigger
        if self.trigger_release:
            self.trigger_mode = None
            self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)


    def _timer_long_press(self, event, value, extra_data):
        ''' short press timer callback '''
        # trigger the long press 
        #if self.verbose: syslog.info("long press timer lapsed")
        self.trigger_mode = "long"
        self.long_press_timer = None
        # retrigger
        if self.trigger_release:
            self.trigger_mode = None
            self._long_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)


    def _timer_long_press_mode_press(self, event, value, extra_data):
        ''' short press timer callback for pressed mode '''
        # trigger the long press 
        self.long_press_timer = None
        self.trigger_mode = "long"
        self._trigger_long_press(event, value, extra_data)


    def _short_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """

        if self.verbose: syslog.info("trigger short press")

        self._kill_timers()
        self._trigger_short_press(event_p, value_p, extra_data)
        time.sleep(self.autorelease_delay)
        self._trigger_short_press(event_r, value_r, extra_data)

    def _double_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """

        if self.verbose: syslog.info("trigger double press")

        self._trigger_double_press(event_p, value_p, extra_data)
        time.sleep(self.autorelease_delay)
        self._trigger_double_press(event_r, value_r, extra_data)        


    def _long_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed, when the delay expires."""
        if self.verbose: syslog.info("trigger long press")
        self._trigger_long_press(event_p, value_p, extra_data)
        time.sleep(self.autorelease_delay)
        self._trigger_long_press(event_r, value_r, extra_data)        


    def _kill_timers(self):
        if self.long_press_timer:
            if self.verbose: syslog.info("stop long press timer")
            self.long_press_timer.cancel()
            self.long_press_timer = None
        if self.short_press_timer:
            if self.verbose: syslog.info("stop short press timer")
            self.short_press_timer.cancel()
            self.short_press_timer = None



class TempoExContainer(AbstractContainer):

    """A container with two actions which are triggered based on the duration
    of the activation.

    A short press will run the fist action while a longer press will run the
    second action.
    """

    name = "TempoEx"
    tag = "tempoEx"
    hint = '''Use this container to trigger actions based on short press or long press.
The delay between short and long press is customizable.
More than one action per short press or long press can be added.'''

    functor = TempoExContainerFunctor
    widget = TempoExContainerWidget
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
    #     gremlin.ui.input_item.ActionSetView.Interactions.Up,
    #     gremlin.ui.input_item.ActionSetView.Interactions.Down,
         gremlin.ui.input_item.ActionSetView.Interactions.Delete,
        
     ]

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.short_action_sets = [gremlin.base_profile.ActionSet("short")]
        self.long_action_sets = [gremlin.base_profile.ActionSet("long")]
        self.double_action_sets = [gremlin.base_profile.ActionSet("double")]
        self.delay = 0.5 # default long press delay in seconds
        self.doubletap_delay = 0.25 # default double tap delay in seconds
        self.autorelease_delay = 0.25 # autorelease in seconds
        self.activate_on = "release"
        self.timeout = 0.0
        self.chain_short = True
        self.chain_long = True
        self.chain_double = True
        self.custom_action_sets = True # indicate we use custom action sets

    @property
    def action_sets(self):
        ''' gets the action sets for this container '''
        return self.short_action_sets + self.long_action_sets + self.double_action_sets
    
    @action_sets.setter
    def action_sets(self, value):
        pass


    def _parse_xml(self, node, input_item = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        # setup a noop action set as the only action set as we have a custom set we use
        
        self.short_action_sets = []
        self.long_action_sets = []
        self.double_action_sets = []
        super()._parse_xml(node, input_item)
        self.delay = safe_read(node,"delay", float, 0.5)
        self.doubletap_delay = safe_read(node,"tap-delay",float,0.25)
        self.autorelease_delay = float(node.get("autorelease-delay", 0.25))
        self.activate_on = node.get("activate-on", "release")
        self.chain_long = safe_read(node, "chain_long", bool, False)
        self.chain_short = safe_read(node, "chain_short", bool, False)
        self.chain_double = safe_read(node, "chain_double", bool, False)
        self.timeout = float(node.get("timeout", 0.0))
        # custom read of action sets
        for as_node in node:
            if as_node.tag == "short-action-set":
                action_set = gremlin.base_profile.ActionSet("short")
                self._parse_action_xml(as_node, action_set, input_item, extra_data, "short")
                self.short_action_sets.append(action_set)
                self.action_sets.append(action_set)
            if as_node.tag == "long-action-set":
                action_set = gremlin.base_profile.ActionSet("long")
                self._parse_action_xml(as_node, action_set, input_item, extra_data, "long")
                self.long_action_sets.append(action_set)
                self.action_sets.append(action_set)
            if as_node.tag == "double-action-set":
                action_set = gremlin.base_profile.ActionSet("double")
                self._parse_action_xml(as_node, action_set, input_item, extra_data, "double")
                self.double_action_sets.append(action_set)
                self.action_sets.append(action_set)                


    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", TempoExContainer.tag)
        node.set("delay", safe_format(self.delay, float))
        node.set("tap-delay", safe_format(self.doubletap_delay, float))
        node.set("autorelease-delay", safe_format(self.autorelease_delay, float))
        node.set("activate-on", self.activate_on)
        node.set("chain_short",safe_format(self.chain_short, bool))
        node.set("chain_long",safe_format(self.chain_long, bool))
        node.set("chain_double",safe_format(self.chain_double, bool))
        node.set("timeout", str(self.timeout))
        
        for action_set in self.short_action_sets:
            if action_set:
                as_node = ElementTree.Element("short-action-set")
                for action in action_set:
                    as_node.append(action.to_xml())
                node.append(as_node)
        for action_set in self.long_action_sets:
            if action_set:
                as_node = ElementTree.Element("long-action-set")
                for action in action_set:
                    as_node.append(action.to_xml())
                node.append(as_node)
        for action_set in self.double_action_sets:
            if action_set:
                as_node = ElementTree.Element("double-action-set")
                for action in action_set:
                    as_node.append(action.to_xml())
                node.append(as_node)
        

        return node
    
    def is_valid_for_save(self):
        # indicate always valid for saving
        return True

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        valid =  len(self.short_action_sets) > 0 or len(self.long_action_sets) > 0
        return valid
    
    def get_action_sets(self):
        """ override method: returns action sets - override because we have custom sets """
        return self.short_action_sets + self.long_action_sets


# Plugin definitions
version = 1
name = "tempoEx"
create = TempoExContainer
