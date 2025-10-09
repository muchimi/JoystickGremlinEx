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
from PySide6 import QtWidgets

import logging
import time
from lxml import etree as ElementTree
import threading
import random
import gremlin
import gremlin.actions
import gremlin.base_conditions
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
import gremlin.macro
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget, AbstractActionWidget
from gremlin.base_profile import AbstractContainer
from gremlin.input_types import InputType
from PySide6 import QtCore
from gremlin.util import safe_format, safe_read
from shiboken6 import Shiboken
syslog = logging.getLogger("system")


class SequenceContainerWidget(AbstractContainerWidget):

    """Container which holds a sequence of actions."""

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
        
        self._lock = threading.Lock()
        
    
        self.widget_layout = QtWidgets.QHBoxLayout()

        self._warning_widget = gremlin.ui.ui_common.QWarningWidget()

        self.profile_data.create_or_delete_virtual_button()
        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            self.profile_data.input_item
        )
        self.action_selector.inputItem = self.profile_data.input_item
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.add_button.setText("Add Step")
        self.action_selector.action_paste.connect(self._paste_action)

        self.widget_layout.addWidget(self.action_selector)

        self._trigger_widget = gremlin.ui.ui_common.QExecuteWidget(self.profile_data.exec_on_press,
                                                                   self.profile_data.exec_on_release,
                                                                   press_callback = self._execute_on_press_changed,
                                                                   release_callback = self._execute_on_release_changed,
                                                                   )

        self._wiggle_mode_widget = QtWidgets.QCheckBox("Enabled")
        self._wiggle_mode_widget.setToolTip("When enabled, the sequence repeats while the input is triggered, optionally using random pauses between actions.")
        self._wiggle_mode_widget.setChecked(self.profile_data.wiggle_mode)
        self._wiggle_mode_widget.clicked.connect(self._handle_wiggle_mode_change)

        self._wiggle_min_delay_widget = gremlin.ui.ui_common.QDelayWidget(5000,
                                                                          label = "Min Delay:",
                                                                          callback = self._handle_min_delay_change,
                                                                          invalid_callback = self._handle_min_invalid_value,
                                                                          validation_callback = self._handle_min_validation)
        self._wiggle_min_delay_widget.setToolTip("Time (ms) between steps")
        self._wiggle_min_delay_widget.setValue(self.profile_data.wiggle_min_delay, False)

        self._wiggle_random_widget = QtWidgets.QCheckBox("Random Delay")
        self._wiggle_random_widget.setToolTip("When enabled, the delay between steps will be randomized betweeen min and max delays")
        self._wiggle_random_widget.setChecked(self.profile_data.wiggle_random)
        self._wiggle_random_widget.clicked.connect(self._handle_wiggle_random_change)

        self._wiggle_steps_widget = QtWidgets.QCheckBox("Randomize Steps")
        self._wiggle_steps_widget.setToolTip("When enabled, steps will execute randomly like a pick list when in wiggle mode")
        self._wiggle_steps_widget.setChecked(self.profile_data.wiggle_randomize_steps)
        self._wiggle_steps_widget.clicked.connect(self._handle_wiggle_random_steps_changed)


        self._wiggle_max_delay_widget = gremlin.ui.ui_common.QDelayWidget(5000,
                                                                          label = "Max Delay:",
                                                                          callback = self._handle_max_delay_change,
                                                                          invalid_callback= self._handle_max_invalid_value,
                                                                          validation_callback = self._handle_max_validation)
        self._wiggle_max_delay_widget.setToolTip("Time (ms) between steps, upper bound")
        self._wiggle_max_delay_widget.setValue(self.profile_data.wiggle_max_delay, False)
        




        widgets = [
            self._wiggle_mode_widget,
            self._wiggle_random_widget,
            self._wiggle_steps_widget
        ]

        widget, _ = gremlin.ui.ui_common.getHContainer(widgets,"Wiggle mode:")
        self.action_layout.addWidget(widget)


        self._wiggle_exec_delay_widget = gremlin.ui.ui_common.QDelayWidget(250, label = "Trigger time:")
        self._wiggle_exec_delay_widget.setToolTip("Time (ms) between a press and release event sent to individual wiggle steps")
        self._wiggle_exec_delay_widget.setValue(self.profile_data.wiggle_exec_delay)
        self._wiggle_exec_delay_widget.valueChanged.connect(self._handle_exec_delay_change)

        self.action_layout.addWidget(self._wiggle_exec_delay_widget)

        widgets = [
            self._wiggle_min_delay_widget,
            self._wiggle_max_delay_widget,
        ]

        self._wiggle_container_widget, _ = gremlin.ui.ui_common.getHContainer(widgets)
                   
        self.action_layout.addWidget(self._wiggle_container_widget)
        self.action_layout.addWidget(self._warning_widget)
        self.action_layout.addWidget(self._trigger_widget)

        # self.widget_layout.addStretch()

        self.action_layout.addLayout(self.widget_layout)


        # Insert action widgets
        for i, action in enumerate(self.profile_data.action_sets):
            widget = self._create_action_set_widget(
                self.profile_data.action_sets[i],
                f"Step {i + 1}",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )
            self.action_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)


        
        self._update_widgets()


    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.profile_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.profile_data.exec_on_release = checked

    @QtCore.Slot(bool)
    def _handle_wiggle_mode_change(self, checked):
        self.profile_data.wiggle_mode = checked
        self._update_widgets()

    @QtCore.Slot(bool)
    def _handle_wiggle_random_change(self, checked):
        self.profile_data.wiggle_random = checked
        self._update_widgets()

    @QtCore.Slot(bool)
    def _handle_wiggle_random_steps_changed(self, checked):
        self.profile_data.wiggle_randomize_steps = checked


    def _handle_min_validation(self, value) -> bool:
        if value < 0:
            self.setWarning("Delay must be positive")
            return False
        if self.profile_data.wiggle_random and value > self.profile_data.wiggle_max_delay:
            self.setWarning("Minimnum delay must be less or equal to the maximum delay.")
            return False
        
        return True # valid
    
    def _handle_max_validation(self, value) -> bool:
        if value < 0:
            self.setWarning("Delay must be positive")
            return False
        if self.profile_data.wiggle_random and value < self.profile_data.wiggle_min_delay:
            self.setWarning("Maximum delay must be greater or equal to the minimum delay.")
            return False

        return True # valid
        

    @QtCore.Slot(int)
    def _handle_min_delay_change(self, value):
        # avoid re-entrant callbacks
        self.profile_data.wiggle_min_delay = value
        self.setWarning()

    @QtCore.Slot(int)
    def _handle_max_delay_change(self, value):
        self.profile_data.wiggle_max_delay = value
        self.setWarning()


    @QtCore.Slot()
    def _handle_min_invalid_value(self):
        self.setWarning("Invalid min delay value")        

    @QtCore.Slot()
    def _handle_max_invalid_value(self):
        self.setWarning("Invalid max delay value")

    @QtCore.Slot(int)
    def _handle_exec_delay_change(self, value):
        self.profile_data.wiggle_exec_delay = value        

        
        


    def _update_widgets(self):
        enabled = self.profile_data.wiggle_mode
        self._wiggle_min_delay_widget.setEnabled(enabled)

        max_enabled = enabled and self.profile_data.wiggle_random
        self._wiggle_max_delay_widget.setVisible(max_enabled)

        self._wiggle_random_widget.setEnabled(enabled)
        self._wiggle_steps_widget.setEnabled(enabled)
        self._wiggle_exec_delay_widget.setEnabled(enabled)

        visible = bool(self._warning_widget.text())
        self._warning_widget.setVisible(visible)

    def setWarning(self, text = None):
        ''' sets warning display - send None to clear / hide'''
        visible = bool(text)
        self._warning_widget.setText(text)
        self._warning_widget.setVisible(visible)


    # @QtCore.Slot(bool)
    # def _trigger_mode_changed(self, checked: bool):
    #     self.profile_data.exec_on_release = checked

    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            for i, action in enumerate(self.profile_data.action_sets):
                widget = self._create_action_set_widget(
                    self.profile_data.action_sets[i],
                    f"Step {i:d}",
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
            self.profile_data.add_action(action_item)
            self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

    def _paste_action(self, action):
        ''' pastes an action '''
        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.profile_data)
            self.profile_data.add_action(action_item)
            self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

    

    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        # Find the index of the widget that gets modified
        index = self._get_widget_index(widget)

        if index == -1:
            syslog.warning(
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
        return f"Sequence: {" -> ".join([", ".join([a.name for a in actions]) for actions in self.profile_data.action_sets])}"


class SequenceContainerFunctor(gremlin.base_conditions.AbstractSelfTriggerFunctor):

    def __init__(self, container : SequenceContainer, parent = None):
        super().__init__(container, parent)


        self.container = container
  
        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        for cond in container.activation_condition.conditions:
            if isinstance(cond, gremlin.base_conditions.InputActionCondition):
                if cond.comparison == "press":
                    self.switch_on_press = True

        self._verbose = gremlin.config.Configuration().verbose_mode_container
        self._verbose_extra = self._verbose
        self._is_running = False

    def profile_start(self):
        self._is_running = False


    def profile_stop(self):
        # stop wiggling
        self.stop_wiggle()


    def start_wiggle(self):
        ''' starts the wiggle process '''
        if not self._is_running:
            syslog.info(f"SEQUENCE: start wiggle runner")
            self._is_running = True
            self._thread = threading.Thread(target = self._wiggle_runner)
            self._thread.name = "wiggle runner"
            self._thread.start()


    def stop_wiggle(self):
        ''' stops the wiggle process '''
        if self._is_running:
            syslog.info(f"SEQUENCE: stop wiggle runner")
            self._is_running = False
            self._thread.join()
            self._thread = None



    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value, extra_data : dict = None) -> bool:
        if not self.valid:
            return False
        
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        elif not isinstance(value.current, bool):
            syslog.warning(f"Invalid data type received in Sequence container: {type(event.value)}")
            return False
        else:
            is_pressed = value.is_pressed

        is_pressed = event.is_pressed
        trigger = (is_pressed and self.container.exec_on_press) or \
                    (not is_pressed and self.container.exec_on_release) 
        
        is_pressed = trigger
        
            
        if self.container.wiggle_mode:
            if is_pressed and not self._is_running:
                # run sequence in wiggle mode
                self.start_wiggle()

            elif not is_pressed and self._is_running:
                # stop wiggle mode
                self.stop_wiggle()




        else:
            # regular mode
            is_pressed = trigger # flip it for containers
            value.is_pressed = is_pressed
            value.current = is_pressed
            event.is_pressed = is_pressed
            event.raw_value = is_pressed
            self._execute(event, value, extra_data, self._verbose)    

        return False # stop execution as the logic is internal to trigger the other nodes
    
    def _wiggle_runner(self):
        ''' wiggle mode runner thread '''
        event_press = gremlin.event_handler.Event(InputType.JoystickButton,
                                            1,
                                            device_guid=gremlin.shared_state.fake_tab_guid,
                                            is_pressed = True)
        
        event_release = event_press.fake_button(False,True)
        
        nodes = [node for node in self.action_set_nodes]
        verbose = self._verbose
        verbose_extra = self._verbose_extra

        if not nodes:
            # nothing to run
            self._is_running = False
            if verbose: syslog.info(f"SEQUENCE WIGGLE: Trigger Functor: nothing to wiggle")
            return
        index = 0
        count = len(nodes)

        
        min_delay = self.container.wiggle_min_delay 
        max_delay = self.container.wiggle_max_delay 
        
        wiggle_random = self.container.wiggle_random and min_delay != max_delay
        wiggle_steps = self.container.wiggle_randomize_steps
        exec_delay = self.container.wiggle_exec_delay / 1000
        if verbose: syslog.info(f"SEQUENCE WIGGLE: starting wiggle with  min delay: [{min_delay}] max delay: [{max_delay}] random mode: [{wiggle_random}]")

        while self._is_running:
            node = nodes[index]
            if verbose: syslog.info(f"SEQUENCE WIGGLE: Trigger Functor: execute node ID: sequence [{index}] [{node.id}]")
            self._ec.execute_node(node, event_press, True, None) # issue press
            # time between executions
            self._wait(exec_delay)
            self._ec.execute_node(node, event_release, False, None) # issue release
            # delay between steps
            if self._is_running:
                if wiggle_random:
                    # random delay
                    delay = random.randrange(min_delay, max_delay) / 1000 # to seconds
                else:
                    # fixed delay
                    delay = min_delay/1000 # to seconds
                if verbose_extra: syslog.info(f"\twait random [{delay}]")
                if delay > 0:
                    self._wait(delay)
            # next node to run
            if wiggle_steps:
                index = random.randrange(0, count) # pick the next random step
            else:
                index += 1
                if index == count:
                    # loop
                    index = 0

            
    def _wait(self, delay : float):
        ''' interruptible delay 
        :param delay: time in seconds
        
        '''
        expires = time.time() + delay
        while self._is_running and expires > time.time():
            time.sleep(0.01)


        





class SequenceContainer(AbstractContainer):

    """Represents a container which holds sequential actions.

    The actions will trigger one after the other with subsequent activations.
    
    """

    name = "Sequence"
    tag = "sequence"
    hint = '''This container runs all actions sequentially like a macro.
Unlike a macro, any action suitable for the input can be used.'''

    #override default allowed inputs here
    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]
    
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Up,
        gremlin.ui.input_item.ActionSetView.Interactions.Down,
        gremlin.ui.input_item.ActionSetView.Interactions.Delete,
    ]

    functor = SequenceContainerFunctor
    widget = SequenceContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.exec_on_release = False # true if the sequence triggers on input release 
        self.exec_on_press = True # true if the sequence triggers on input press 
        self.wiggle_mode = False # wiggle mode off by default
        self.wiggle_min_delay = 250 # minimum delay for wiggle mode, or default delay if not randomized
        self.wiggle_max_delay = 5000 # maximum delay for wiggle mode, if in random mode
        self.wiggle_random = True # wiggle random mode
        self.wiggle_exec_delay = 250 # delay between a press trigger and a release trigger for each action executing in wiggle mode
        self.wiggle_randomize_steps = False # if set, randomizes the execution steps

        

    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """


        if "trigger_on_press" in node.attrib:
            self.exec_on_press = safe_read(node,"trigger_on_press",bool,True)
        else:
            # new format
            self.exec_on_press = safe_read(node,"trigger-on-press",bool,True)
            
        self.exec_on_release = safe_read(node,"trigger-on-release",bool,False)

        self.wiggle_mode = safe_read(node,"wiggle-mode", bool, False)
        self.wiggle_min_delay = safe_read(node,"wiggle-min", int, 250)
        self.wiggle_max_delay = safe_read(node,"wiggle-max", int, 5000)
        self.wiggle_exec_delay = safe_read(node,"wiggle-exec", int, 5000)
        self.wiggle_random = safe_read(node,"wiggle-random", bool, True)
        self.wiggle_randomize_steps = safe_read(node,"wiggle-random-steps", bool, False)


        

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", SequenceContainer.tag)
        node.set("trigger-on-press",safe_format(self.exec_on_press,bool))
        node.set("trigger-on-release",safe_format(self.exec_on_release,bool))
        node.set("wiggle-mode", safe_format(self.wiggle_mode, bool))
        node.set("wiggle-min", safe_format(self.wiggle_min_delay, int))
        node.set("wiggle-max", safe_format(self.wiggle_max_delay, int))
        node.set("wiggle-exec", safe_format(self.wiggle_exec_delay, int))
        node.set("wiggle-random", safe_format(self.wiggle_random, bool))
        node.set("wiggle-random-steps", safe_format(self.wiggle_randomize_steps, bool))


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
        return True
        #return len(self.action_sets) > 0


# Plugin definitions
version = 1
name = "sequence"
create = SequenceContainer
