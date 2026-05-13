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

from lxml import etree as ElementTree

import gremlin
import gremlin.config
from gremlin.input_types import InputType

import gremlin.ui.ui_common

import gremlin.types
from gremlin.base_profile import AbstractContainer
import gremlin.execution_graph
from gremlin.ui.input_item import AbstractContainerWidget
from shiboken6 import Shiboken
import logging
from PySide6 import QtWidgets, QtCore, QtGui
from gremlin.util import safe_format, safe_read
import threading

syslog = logging.getLogger("system")
class TriggerContainerWidget(AbstractContainerWidget):

    """Trigger container which holds a single action."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        
        super().__init__(profile_data, parent)
        

    def _create(self, action_data):
        self.action_data : TriggerContainer = action_data

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        

        # trigger delay

        delay_widget = gremlin.ui.ui_common.QFloatLineEdit(value = self.action_data.trigger_delay,
                                                           callback = self._handle_delay_changed,
                                                           tooltip="Delay trigger in seconds.  Set to 0 to disable.")
        
        execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        execute_widget.pressChanged.connect(self._execute_on_press_changed)
        execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        widgets = [
            delay_widget,
            execute_widget,
        ]
        delay_container = gremlin.ui.ui_common.getHContainer(widgets,"Trigger delay (s):", widget_only=True, left_margin = 12)


        msg = '''This container will execute the contained actions on input trigger if the defined condition succeeds.
If the condition fails when the timer lapses, the actions will not be executed.
If there is no condition defined, the condition will succeeed and the actions will executed.
If the timer is set to 0, the actions get executed immediately if the condition passes (or is not set)
'''

        info_widget = gremlin.ui.ui_common.QInfoBox(msg, hide_key = "TriggerContainer")
        self.action_layout.addWidget(info_widget)

        self.action_layout.addWidget(QtWidgets.QLabel("Trigger Configuration:"))
        self.action_layout.addWidget(delay_container)

        # create two tabs - one for the action sets, one for the conditions to check
        action_tab_widget, self.action_tab_layout = gremlin.ui.ui_common.getVContainer()
        condition_tab_widget, self.condition_tab_layout = gremlin.ui.ui_common.getVContainer()

        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.addTab(action_tab_widget, "Trigger Actions")
        self.tab_widget.addTab(condition_tab_widget, "Trigger Conditions")

        self.action_layout.addWidget(self.tab_widget)

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info("TriggerContainerWidget: create action UI start")
        has_actions = False
        for action_set in self.profile_data.action_sets:
            if action_set:
                has_actions = True
                break
         
        if has_actions:
            action_sets = [action_set for action_set in self.profile_data.action_sets if action_set]
            assert len(action_sets) == 1, "invalid action set count - expected a single action set"

            self.profile_data.create_or_delete_virtual_button()
            widget = self._create_action_set_widget(
                action_sets[0],
                "Trigger",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

            self.action_tab_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)
        else:
            input_item = self.profile_data.input_item
            if self.profile_data.get_device_type() == gremlin.types.DeviceType.VJoy:
                action_selector = gremlin.ui.ui_common.ActionSelector(
                    gremlin.types.DeviceType.VJoy,
                    input_item,
                )
            else:
                action_selector = gremlin.ui.ui_common.ActionSelector(
                    input_item.get_input_type(),
                    input_item,
                )
            action_selector.action_added.connect(self._add_action)
            action_selector.action_paste.connect(self._paste_action)
            action_selector.inputItem = self.profile_data

            self.action_tab_layout.addWidget(action_selector)
            self.action_tab_layout.addStretch()


        # create the condition tab data 
        
        widget = gremlin.ui.ui_activation_condition.ActivationConditionWidget(self.action_data.condition_data)
        self.condition_tab_layout.addWidget(widget)
        self.condition_tab_layout.addStretch()
        


        if verbose_ui: syslog.info("TriggerContainerWidget: create action UI completed")




    

    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            widget = self._create_action_set_widget(
                self.profile_data.action_sets[0],
                "Trigger",
                gremlin.ui.ui_common.ContainerViewTypes.Conditions
            )
            self.activation_condition_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

            return widget

    def _add_action(self, action_data):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        from gremlin.clipboard import Clipboard
        if action_data is None:
            return
        
        gremlin.util.pushCursor()

        try:

            if isinstance(action_data, str):
                action_name = action_data
                plugin_manager = gremlin.plugin_manager.ActionPlugins()
                action_item = plugin_manager.get_class(action_name)(self.profile_data)
            elif isinstance(action_data, Clipboard):
                # paste operation
                if action_data.is_action:
                    # verify the action in the clipboard is appropriate for this input

                    action_item = plugin_manager.duplicate(action_data.data, self.profile_data)

            self.profile_data.add_action(action_item)
            if Shiboken.isValid(self):
                self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

    def _paste_action(self, action, container):
        ''' paste action'''

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.profile_data)
            self.profile_data.add_action(action_item)
            if Shiboken.isValid(self):
                self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

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
        title = "Trigger: "
        if len(self.profile_data.action_sets) > 0:
            stub =  ", ".join(a.name for a in self.profile_data.action_sets[0])
            title += stub
        
        return title

    @QtCore.Slot(float)    
    def _handle_delay_changed(self, value):
        self.action_data.trigger_delay = value

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked        



class TriggerContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):

    ''' functor is a trigger functor as we need to trigger the content only if some conditions are met '''

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        

    def profile_started(self):
        super().profile_started()

        self._timer = None # trigger timer

        # preprocessd conditions to check
        
        ac = self.action_data.getActivationCondition()
        self.rule = ac.rule
        ec = gremlin.execution_graph.ExecutionContext()
        
        # convert the conditions to the executable versions
        self.conditions = [ec._convert_condition(condition) for condition in ac.conditions]
        config = gremlin.config.Configuration()
        self.verbose_condition = config.verbose_mode_condition
        self.verbose = config.verbose_mode_container



    def process_event(self, event, value, extra_data = None):
        """Executes the content with the provided data.

        :param event the event to process
        :param value the value received with the event
        :return True if execution was successful, False otherwise
        """

        is_pressed = event.is_pressed
        trigger = (is_pressed and self.action_data.exec_on_press) or \
                (not is_pressed and self.action_data.exec_on_release)
        
        if trigger:
            if self._timer:
                # abort curent timer
                self._timer.cancel()

            if self.verbose:
                syslog.info("TRIGGER CONTAINER: scheduling trigger")
            self._timer = threading.Timer(self.action_data.trigger_delay, self._handle_trigger)
            self._timer.start()
        return False # do not do further processing

    def _handle_trigger(self):
        ''' triggers when the timer runs out'''
        import gremlin.event_handler
        import gremlin.shared_state
        import gremlin.config 

        # come up with our own trigger event
        event = gremlin.event_handler.Event(
            InputType.JoystickButton,
            identifier = 1,
            device_guid = gremlin.shared_state.fake_tab_guid,
            is_pressed = True,
            value = True
        )
        
        # evaluate the conditions
    
        result = True
        if self.conditions:
            for condition in self.conditions:
                result = condition.process_event(event, True)
                if self.verbose_condition:
                    gremlin.shared_state.pushLog()
                    logTabs = gremlin.shared_state.logTabs(True)
                    condition_name = condition.condition_name()
                    if isinstance(condition, gremlin.actions.ActivationCondition):
                        syslog.info(f"{logTabs}>Executed latched activation condition {condition_name} result: {'PASS' if result else 'FAIL'}")
                    elif isinstance(condition, gremlin.actions.AbstractCondition):
                        syslog.info(f"{logTabs}>Executed latched condition {condition_name} result: {'PASS' if result else 'FAIL'}") 
                    gremlin.shared_state.popLog()

                match self.rule:
                    case gremlin.actions.ActivationRule.Any:
                        if result:
                            # one condition succeeded
                            break
                    case gremlin.actions.ActivationRule.All:
                        if not result:
                            # any one condition failed failes the whole stack
                            break

    
        if self.verbose: 
            syslog.info(f"TRIGGER CONTAINER: evaluate conditions: {'PASS' if result else 'FAIL'}")

        if result:
            # conditions succeeded - run the functors 
            if self.verbose: syslog.info("TRIGGER CONTAINER: trigger event")
            self._execute(event, True, None)
                    
  




class TriggerContainer(AbstractContainer):

    """Represents a container which holds exactly one action."""

    name = "Delay Trigger"
    tag = "trigger"
    hint = '''This container can delay trigger delayed actions.'''
    
    interaction_types = []

    functor = TriggerContainerFunctor
    widget = TriggerContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        import gremlin.base_profile
        super().__init__(parent, node)

        self.trigger_delay = 0 # delay in seconds to wait for the contents to execute
        self.condition_data = gremlin.base_profile.ConditionContainer() # conditions for the trigger release
        self.condition_data.setContainer(self)
        self.exec_on_press = True # true if trigger should execute on input press event
        self.exec_on_release = False # true if trigger should execute on input release event
     
    def getActivationCondition(self):
        return self.condition_data.activation_condition
    
    def add_action(self, action, index=-1):
        assert isinstance(action, gremlin.base_profile.AbstractAction)

        # Make sure if we're dealing with axis with remap and response curve
        # actions that they are arranged sensibly
        if action.get_input_type() == InputType.JoystickAxis:
            remap_sets = []
            curve_sets = []
            for container in self.parent.containers:
                for action_set in container.action_sets:
                    for t_action in action_set:
                        if gremlin.base_profile._is_curve_tag(t_action.tag): 
                            curve_sets.append(action_set)
                        elif t_action.tag == "remap":
                            remap_sets.append(action_set)

            if action.tag == "remap" and len(curve_sets) == 1 and \
                    len(remap_sets) == 0:
                curve_sets[0].append(action)
            elif gremlin.base_profile._is_curve_tag(action.tag) and len(remap_sets) == 1 and \
                    len(curve_sets) == 0:
                remap_sets[0].append(action)
            else:
                if index == -1:
                    self.action_sets.append([])
                    index = len(self.action_sets) - 1
                self.action_sets[index].append(action)
        else:
            if index == -1:
                self.action_sets.append([])
                index = len(self.action_sets) - 1
            self.action_sets[index].append(action)

        #self.refresh_conditions()

        self.create_or_delete_virtual_button()

        self.mapping_changed() # tell UI of changes
        

    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        import gremlin.util


        self.trigger_delay = safe_read(node,"delay", float, 0.0)

        
        if "exec_on_press" in node.attrib:
            self.exec_on_press = safe_read(node,"exec_on_press",bool, True)
        if "exec_on_release" in node.attrib:
            self.exec_on_release = safe_read(node,"exec_on_release",bool, False)            


        # load the condition data
        condition_node = gremlin.util.get_xml_child(node,"trigger-condition")
        if condition_node is not None:
            self.condition_data.activation_condition.from_xml(condition_node, data = (None, self))


    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", "trigger")
        as_node = ElementTree.Element("action-set")
        as_node.set("id", write_guid(action_sets[0].id))
        for action in self.action_sets[0]:
            as_node.append(action.to_xml())
        node.append(as_node)

        node.set("delay", safe_format(self.trigger_delay, float))
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))    

        # save trigger condition data
        condition_node = self.condition_data.activation_condition.to_xml()
        condition_node.tag = "trigger-condition"
        node.append(condition_node)
        

        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) == 1


# Plugin definitions
version = 1
name = "trigger"
create = TriggerContainer
