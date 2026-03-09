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
from enum import Enum, auto
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore
from PySide6.QtCore import Slot

import gremlin.base_conditions
from  gremlin.clipboard import Clipboard
import gremlin
import gremlin.util
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
import gremlin.event_handler
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

        el = gremlin.event_handler.EventListener()
        el.action_delete.connect(self._delete_action)
        
        


    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self._redraw_lock = False
        self.profile_data.create_or_delete_virtual_button()
        self.short_widget, self.short_layout = gremlin.ui.ui_common.getVContainer()
        self.short_widget.setContentsMargins(8,0,0,0)
        

        
        self.long_widget, self.long_layout = gremlin.ui.ui_common.getVContainer()
        self.long_widget.setContentsMargins(8,0,0,0)
        
        self.double_widget, self.double_layout = gremlin.ui.ui_common.getVContainer()
        self.double_widget.setContentsMargins(8,0,0,0)
        
        self.options_widget, self.options_layout = gremlin.ui.ui_common.getVContainer()

        self.longpress_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Long Press Delay (ms):")
        self.longpress_delay_widget.setToolTip("Delay to detect long press, should be greater than double tap delay.\nIf the input is released before this value, a short press is executed.\nIf the input is released on or after this value, a long press is executed.")
        self.longpress_delay_widget.setValue(self.profile_data.delay * 1000)
        self.longpress_delay_widget.valueChanged.connect(self._delay_changed_cb)

        self.dtap_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Double-Tap Delay (ms):")
        self.dtap_delay_widget.setToolTip("Delay to detect double tap.  If the input is pressed twice within this timeframe, a double-tap will be executed.")
        self.dtap_delay_widget.setValue(self.profile_data.doubletap_delay * 1000)
        self.dtap_delay_widget.valueChanged.connect(self._dtap_delay_changed_cb)

        self.autorelease_delay_widget = gremlin.ui.ui_common.QDelayWidget(label = "Autorelease Delay (ms):", tooltip="Time between a press and release trigger.  Set to 0 to disable autoreleases.")
        self.autorelease_delay_widget.setValue(self.profile_data.autorelease_delay * 1000)
        self.autorelease_delay_widget.valueChanged.connect(self._autorelease_delay_changed_cb)
                
        self.warning_widget = gremlin.ui.ui_common.QWarningWidget(text = "")

        widgets = [
            self.longpress_delay_widget,
            self.dtap_delay_widget,
            self.autorelease_delay_widget,
            self.warning_widget,
            #self.info_widget,
        ]

        widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)
        self.options_layout.addWidget(widget)
       

        # Activation moment
        self.activate_press = QtWidgets.QRadioButton("on press")
        self.activate_release = QtWidgets.QRadioButton("on release")

        widgets = ["<b>Activate On:</b",
                   self.activate_press,
                   self.activate_release]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)

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

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.options_layout.addWidget(widget)


        icon = gremlin.ui.ui_common.Icons.chevronIcon()
        widgets = [
            self.options_widget,
            gremlin.ui.ui_common.QHeaderLabel("<b>Short Press Action Sets</b>", icon = icon),
            self.short_widget,
            gremlin.ui.ui_common.QHeaderLabel("<b>Long Press Action Sets</b>", icon = icon),
            self.long_widget,
            gremlin.ui.ui_common.QHeaderLabel("<b>Double Tap Press Action Sets</b>", icon = icon),
            self.double_widget,

        ]

        self.content_widget, self.content_layout = gremlin.ui.ui_common.getVContainer(widgets)
        

        self.short_action_selector = gremlin.ui.ui_common.ActionSelector(
            #self.profile_data.get_input_type(),
            InputType.JoystickButton,
            self.profile_data.input_item
        )
        self.short_action_selector.action_label.setText("Short Press Action(s)")
        

        self.long_action_selector = gremlin.ui.ui_common.ActionSelector(
            #self.profile_data.get_input_type(),
            InputType.JoystickButton,
            self.profile_data.input_item
        )
        self.long_action_selector.action_label.setText("Long Press Action(s)")


        self.double_action_selector = gremlin.ui.ui_common.ActionSelector(
            #self.profile_data.get_input_type(),
            InputType.JoystickButton,
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


        self._update_warnings()

  


    def _create_condition_ui(self):
        ''' creates the condition UI for action sets - called whenever the conditions are refreshed or actions change in the container 
        the layout has alredy been cleared by the time this is called so we recreate the widgets for each action and don't need to worry
        about the ones removed.
        
        '''
        gremlin.util.clear_layout(self.activation_condition_layout)
        short_actions = self.profile_data.short_action_sets
        long_actions =  self.profile_data.long_action_sets
        double_actions =self.profile_data.double_action_sets
        if short_actions:
            for action_set in short_actions:
                if action_set:
                    self._create_action_widget(
                        action_set,
                        "Short Press",
                        self.activation_condition_layout,
                        gremlin.ui.ui_common.ContainerViewTypes.Conditions
                    )

        if long_actions:
            for action_set in long_actions:
                if action_set:
                    self._create_action_widget(
                        action_set,
                        "Long Press",
                        self.activation_condition_layout,
                        gremlin.ui.ui_common.ContainerViewTypes.Conditions
                    )

        if double_actions:
            for action_set in double_actions:
                if action_set:
                    self._create_action_widget(
                        action_set,
                        "Double Tap",
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


    def _delete_action(self, input_item, container, action):
        ''' removes an action '''
        if self.container != container:
            # not ours
            return 
        gremlin.util.InvokeUiMethod(self._update_condition_ui)

    def _create_widgets(self, action_sets, label, layout, widget_list):
        for i, action_set in enumerate(action_sets):
            widget = self._create_action_set_widget(
                action_set if action_set is not None else [],
                f"{label} {i+1:d}",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )
            layout.addWidget(widget)
            widget_list.append(widget)
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

        action_sets = [action_set for action_set in self.profile_data.short_action_sets if action_set]
        self._create_widgets(action_sets,"Chain Short Action", self.short_layout, self.short_layout_widget_list)


    def _paste_short_action(self, action, container):
        ''' called when a paste occurs '''
        syslog.info("Paste short action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        action_item.data = "short"
        self.profile_data.short_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()       

        action_sets = [action_set for action_set in self.profile_data.short_action_sets if action_set]
        self._create_widgets(action_sets,"Chain Short Action", self.short_layout, self.short_layout_widget_list)

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

        action_sets = [action_set for action_set in self.profile_data.long_action_sets if action_set]   
        self._create_widgets(action_sets,"Chain Long Action", self.long_layout, self.long_layout_widget_list)


    
    def _paste_long_action(self, action, container):
        ''' called when a paste occurs '''
        syslog.info("Paste long action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        action_item.data = "long"
        self.profile_data.long_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()    

        action_sets = [action_set for action_set in self.profile_data.long_action_sets if action_set]   
        self._create_widgets(action_sets,"Chain Long Action", self.long_layout, self.long_layout_widget_list)              


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

        action_sets = [action_set for action_set in self.profile_data.double_action_sets if action_set]   
        self._create_widgets(action_sets,"Chain Double Action", self.double_layout, self.double_layout_widget_list)
    
    def _paste_double_action(self, action, container):
        ''' called when a paste occurs '''
        syslog.info("Paste double action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        action_item.data = "double"
        self.profile_data.double_action_sets.append([action_item])
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()     
        for widget in self.double_layout_widget_list:
            widget.redraw()

    @QtCore.Slot()
    def _delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the long press action activates
        """
        # value = value/1000
        # dtap_value = self.profile_data.doubletap_delay
        # if value <= dtap_value:
        self.profile_data.delay = value/1000 # to seconds
        self._update_warnings()

    def _dtap_delay_changed_cb(self, value):
        ''' double tap value change 
        :param value the value after which the long press action activates
        '''
        self.profile_data.doubletap_delay = value/1000 # to seconds
        self._update_warnings()

    @QtCore.Slot()
    def _autorelease_delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the long press action activates
        """
        self.profile_data.autorelease_delay = value / 1000
        self._update_warnings()
        
            

    def _update_warnings(self):
        ''' updates warnings based on configuration '''
        warnings = []
        value = self.profile_data.autorelease_delay
        if value == 0:
            warnings.append("Autorelease when set to zero (0) turns off any release trigger sent to containers or actions.")

        if self.profile_data.activate_on == "press":
            warnings.append('DoubleTap does not trigger when the container is in <u>activate on press mode</u>.')

        if self.profile_data.delay < self.profile_data.doubletap_delay:
            warnings.append("Long press delay should be greater than the double tap delay.")

        if warnings:
            msg = ""
            for warning in warnings:
                msg += warning + "\n"
            self.warning_widget.setText(msg)
            self.warning_widget.setVisible(True)
        else:
            self.warning_widget.setVisible(False)


    
    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_press.isChecked():
            self.profile_data.activate_on = "press"
        else:
            self.profile_data.activate_on = "release"

        self._update_warnings()

    @QtCore.Slot(bool)
    def _chain_short_changed_cb(self, checked : bool):
        ''' occurs when short chain checkbox is changed '''
        self.profile_data.chain_short = checked


    @QtCore.Slot(bool)
    def _chain_long_changed_cb(self, checked : bool):
        ''' occurs when short chain checkbox is changed '''
        self.profile_data.chain_long = checked

    @QtCore.Slot(bool)
    def _chain_double_changed_cb(self, checked : bool):
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
        elif widget in self.double_layout_widget_list:
            data = self.double_layout_widget_list
            action_sets = self.profile_data.double_action_sets
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
        
   

class TempoExContainerFunctor(gremlin.base_profile.AbstractTriggerFunctor):

    def __init__(self, container : TempoExContainer, parent = None):
        super().__init__(container, parent)


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
        self.event_release = None
        

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
        super().profile_started()
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
            syslog.error(f"TEMPOEX: Disabled: Unable to find the container in the execution tree: [{str(self.action_data)}] - missing container ID: [{self.action_data.id}]")
            self.valid = False

        if self.verbose or not self.valid:
            syslog.info("TEMPOEX: Configuration:")
            syslog.info(f"\tContainer ID: {self.action_data.id}")
            input_item : gremlin.base_profile.InputItem = self.action_data._input_item
            syslog.info(f"\tAttached input: {input_item.display_name}")
            syslog.info(f"\tExecution mode: activate on {self.action_data.activate_on}")
            syslog.info(f"\tShort action sets: {len(self.action_data.short_action_sets)}")
            syslog.info(f"\tChain enabled: short: [{self.action_data.chain_short}] long: [{self.action_data.chain_short}] dtap: [{self.action_data.chain_short}]")

            syslog.info(f"\tTimers: double tap delay (s): [{self.action_data.doubletap_delay:0.3f}  long delay: [{self.action_data.delay:0.3f}] autorelease delay: [{self.action_data.autorelease_delay:0.3f}]")
            
            self.action_data.dumpActionSets(self.action_data.short_action_sets,"Short Action Set")
            syslog.info(f"\tLong action sets: {len(self.action_data.long_action_sets)}")
            self.action_data.dumpActionSets(self.action_data.long_action_sets,"Long Action Set")
            syslog.info(f"\tDtap action sets: {len(self.action_data.double_action_sets)}")
            self.action_data.dumpActionSets(self.action_data.double_action_sets,"Dtap Action Set")

 
        if not self.valid:
            return
        
        if not container_node.children:
            # this indicates a build or configuration error
            syslog.warning(f"TEMPOEX: Disabled: The container node has no children: [{str(self.action_data)}] ")
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


    def profile_mode_changed(self, mode : str):
        ''' called when the runtime mode changes '''
        
        # kill any executing timers on mode change
        if self.long_press_timer:
            self.long_press_timer.cancel()
            self.long_press_timer = None

        if self.short_press_timer:
            self.short_press_timer.cancel()
            self.short_press_timer = None

        

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
                node = self.dtap_nodes[self.dtap_index]
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


        if self.verbose:
            if is_pressed:            
                syslog.info("single tap (press)")
            else:
                syslog.info("single tap (release)")
    
        node_count = len(self.short_nodes)
        if node_count:
            if self.short_index < len(self.short_nodes):
                # syslog.info(f"execute short press {self.short_index}")
                ec = gremlin.execution_graph.ExecutionContext()
                node = self.short_nodes[self.short_index]
                ec.execute_node(node, event, value, extra_data)

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
        ''' handle input events 
        
        trigger_mode values:
        None - not set / default
        "short" - short press mode
        "single" - single (short press mode) - short timer not ellapsed
        "double" - double press detected
        "long" = long press detect - long timer ellapsed

        
        
        '''

        if not self.valid:
            return False
        
        input_type = event.getInputType()
        
        if input_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        else:
            is_pressed = event.is_pressed # use new API for GremlinEx

        
        verbose = self.verbose


        self.value_press = copy.deepcopy(value)
        self.value_release = copy.deepcopy(value)

        self.event_press = event.clone()
        self.event_release = event.clone()

        
        self.event_press.is_axis = False
        self.event_release.is_axis = False
        
        self.event_press.is_pressed = True
        self.event_release.is_pressed = False
        
        

        if is_pressed:
            if verbose: syslog.info(f"TEMPOEX: input press processing - trigger mode: [{self.trigger_mode}]")
           

        
            time_now = time.time() # current time
            self.trigger_release = False # press mode
            
            if self.verbose: syslog.info(f"\tpress detected trigger mode: {self.trigger_mode}")

            if self.activate_on == "press":
                # double tap not active in this mode
                if verbose: syslog.info("\tcontainer is in press mode")
                # trigger long press (timers are reset if a release comes)
                if verbose: syslog.info("\tstart long press timer")
                self.long_press_timer = threading.Timer(self.delay, lambda: self._timer_long_press_mode_press(self.event_press, self.value_press, extra_data))
                self.long_press_timer.start()
            else:
                # container is in release mode

                if verbose: syslog.info("\tcontainer is in release mode")
                if self.dtap_enabled:
                    # double tap enabled

                    if verbose: syslog.info("\tdtap enabled processing")
                    if not self.trigger_mode:
                        # no mode yet

                        # assume single tap
                        self.trigger_mode = "single"

                        # trigger short press unless we detect another click or release
                        self.short_press_timer = threading.Timer(self.dtap_offset, lambda: self._timer_short_press(self.event_press, self.value_press, extra_data))
                        self.long_press_timer = threading.Timer(self.delay, lambda: self._timer_long_press(self.event_press, self.value_press, extra_data))

                        if verbose: syslog.info("\tstart short and long press timers")
                        self.short_press_timer.start()
                        self.long_press_timer.start()

                    else:
                        # detected another click while short press timer running
                        if self.short_press_timer:
                            if verbose: syslog.info("\tdouble tap detect \\ stop short press timer")
                            self.short_press_timer.cancel()
                            self.short_press_timer = None
                            self.trigger_mode = "double"

                            if self.long_press_timer:
                                if verbose: syslog.info("\tstop long press timer")
                                self.long_press_timer.cancel()
                                self.long_press_timer = None
                else:
                    # not in double tap mode
                    if verbose: syslog.info("\tdtap disabled processing")
                    self.trigger_mode = "short" # assume a short tap, if the timer lapses, will be set to long tap
                    if self.short_press_timer:
                        if verbose: syslog.info("\tstop short press timer")
                        self.short_press_timer.cancel()
                        self.short_press_timer = None
                    
                    # start long press timer 
                    if verbose: syslog.info("\tstart long press timer")
                    self.long_press_timer = threading.Timer(self.delay, lambda: self._timer_long_press(self.event_press, self.value_press, extra_data))
                    self.long_press_timer.start()

            self.start_time = time_now # reset start

        else:

            # input is released
            if verbose: syslog.info(f"TEMPOEX: input release processing - trigger mode: [{self.trigger_mode}]")
            if self.activate_on == "press":
                
                if self.long_press_timer:
                    # release occured before long press timer finished
                    if verbose: syslog.info("\tstop long press timer")
                    self.long_press_timer.cancel()
                    self.long_press_timer = None

                if not self.trigger_mode:
                    # long press didn't execute, trigger short press release cycle
                    if verbose: syslog.info("\ttrigger short press")
                    self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)

                elif self.trigger_mode == "long":
                    # long press was already triggered, release it on release
                    if verbose: syslog.info("\ttrigger long press")
                    self._trigger_long_press(event, value, extra_data)
                
                self.trigger_mode = None # reset

            else:
                # release mode
            
                
                self.trigger_release = True # indicate a release trigger occured

                if self.long_press_timer:
                    #if self.verbose: syslog.info("stop long press timer")
                    self.long_press_timer.cancel()
                    self.long_press_timer = None


                if self.trigger_mode:
                    # release the corresponding press
                    
                    match self.trigger_mode:
                        case "short":
                            # short release
                            if verbose: syslog.info("\ttrigger short")
                            self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                            self.trigger_mode = None
                        case "double":
                            # double tap
                            if verbose: syslog.info("\ttrigger dtap")
                            self._double_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                            self.trigger_mode = None
                        case "long":
                            # long release
                            if verbose: syslog.info("\ttrigger long")
                            self._long_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                            self.trigger_mode = None

        return False # stop execution because it's handled internally
    

    def _timer_short_press(self, event, value, extra_data):
        ''' short press timer callback '''
        # trigger the short press 
        if self.verbose: syslog.info("TEMPOEX: short press timer lapsed")
        self.trigger_mode = "short"
        self.short_press_timer = None
        # retrigger
        if self.trigger_release:
            self.trigger_mode = None
            self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)


    def _timer_long_press(self, event, value, extra_data):
        ''' short press timer callback '''
        # trigger the long press 
        if self.verbose: syslog.info("TEMPOEX: long press timer lapsed")
        self.trigger_mode = "long"
        self.long_press_timer = None
        # retrigger
        if self.trigger_release:
            self.trigger_mode = None
            self._long_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)


    def _timer_long_press_mode_press(self, event, value, extra_data):
        ''' long press timer callback in pressed mode '''
        # trigger the long press 
        self.long_press_timer = None
        self.trigger_mode = "long"
        if self.verbose: syslog.info("\ttrigger long (in execute on pressed container mode)")
        self._trigger_long_press(event, value, extra_data)


    def _short_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """

        if self.verbose: syslog.info("TEMPOEX: handle short press")

        self._kill_timers()
        self._trigger_short_press(event_p, value_p, extra_data)
        if self.autorelease_delay:
            callback = self._create_callback(self._trigger_short_press, event_r, value_r, extra_data)
            timer = threading.Timer(self.autorelease_delay, callback)
            if self.verbose: syslog.info("\tstart short press release timer")
            timer.start()

    def _handle_short_press_release(self, event, value, extra_data):
        if self.verbose: syslog.info("\tshort press release timer lapsed")
        self._trigger_short_press(event, value, extra_data)
        
    def _create_callback(self, functor, event, value, extra_data):
        return lambda : functor(event, value, extra_data)

    def _double_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """

        if self.verbose: syslog.info("TEMPOEX: handle dtap press")

        self._trigger_double_press(event_p, value_p, extra_data)
        if self.autorelease_delay:
            callback = self._create_callback(self._handle_double_tap_release, event_r, value_r, extra_data)
            timer = threading.Timer(self.autorelease_delay, callback)
            if self.verbose: syslog.info("\tstart double tap release timer")
            timer.start()

    def _handle_double_tap_release(self, event, value, extra_data):
        if self.verbose: syslog.info("\tdouble tap release timer lapsed")
        self._trigger_double_press(event, value, extra_data)



    def _long_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed, when the delay expires."""

        if self.verbose: syslog.info("TEMPOEX: handle long press")
        self._trigger_long_press(event_p, value_p, extra_data)
        if self.autorelease_delay and self.action_data.activate_on == "release":
            callback = self._create_callback(self._trigger_long_press, event_r, value_r, extra_data)
            timer = threading.Timer(self.autorelease_delay, callback)
            if self.verbose: syslog.info("\tstart long press release timer")
            timer.start()

    def _handle_long_press_release(self, event, value, extra_data):
        if self.verbose: syslog.info("\tlong press release timer lapsed")
        self._trigger_long_press(event, value, extra_data)


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
    
    input_types = [
         InputType.JoystickButton,
    ]

    interaction_types = [
    #     gremlin.ui.input_item.ActionSetView.Interactions.Up,
    #     gremlin.ui.input_item.ActionSetView.Interactions.Down,
    #     gremlin.ui.input_item.ActionSetView.Interactions.Delete,
        
     ]

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.short_action_sets = []
        self.long_action_sets = []
        self.double_action_sets = []
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
    
    def get_input_type(self):
        ''' override input type when actions check what input type they are hooked to '''
        return InputType.JoystickButton 
    
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
        # count = len(self.short_action_sets) + len(self.long_action_sets) + len(self.double_action_sets)
        # valid = count > 0
        valid = True
        return valid
    
    def get_action_sets(self):
        """ override method: returns action sets - override because we have custom sets """
        return self.action_sets

    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell

        table = ReportTable(cellpadding=4)
        
        count = sum(len(actions) for actions in self.short_action_sets)
        table.addField("Short Steps", f"{count}")
        count = sum(len(actions) for actions in self.long_action_sets)
        table.addField("Long Steps", f"{count}")
        count = sum(len(actions) for actions in self.double_action_sets)
        table.addField("Double Steps", f"{count}")

        table.addField("Exec on", self.activate_on)
        table.addField("Long delay", f"{self.delay*1000:,} ms")
        table.addField("Double tap delay", f"{self.doubletap_delay * 1000:,} ms")

        return table.to_html()

# Plugin definitions
version = 1
name = "tempoEx"
create = TempoExContainer
