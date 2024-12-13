# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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

import gremlin
import gremlin.actions
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
        self.widget_layout = QtWidgets.QHBoxLayout()

        self.profile_data.create_or_delete_virtual_button()
        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            self.profile_data
        )
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.add_button.setText("Add Step")
        self.action_selector.action_paste.connect(self._paste_action)

        self.widget_layout.addWidget(self.action_selector)

        self.trigger_widget = QtWidgets.QCheckBox("Trigger on release")
        self.trigger_widget.setToolTip("Triggers the sequence on input release instead of input press")
        self.trigger_widget.setChecked(self.profile_data.trigger_on_release)
        self.trigger_widget.clicked.connect(self._trigger_mode_changed)

        self.widget_layout.addWidget(self.trigger_widget)
        self.widget_layout.addStretch()

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

    @QtCore.Slot(bool)
    def _trigger_mode_changed(self, checked: bool):
        self.profile_data.trigger_on_release = checked

    def _create_condition_ui(self):
        if self.profile_data.has_action_conditions:
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
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        self.profile_data.add_action(action_item)
        self.container_modified.emit()

    def _paste_action(self, action):
        ''' pastes an action '''
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        self.profile_data.add_action(action_item)
        self.container_modified.emit()

    

    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        # Find the index of the widget that gets modified
        index = self._get_widget_index(widget)

        if index == -1:
            logging.getLogger("system").warning(
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


class SequenceContainerFunctor(gremlin.base_conditions.AbstractFunctor):

    def __init__(self, container : SequenceContainer, parent = None):
        super().__init__(container, parent)
        self.action_sets = []
        self.container = container
        self.graph_map = {} # holds index to graph
        self.index_map = {} # holds graph to index
        index = 0
        for action_set in container.action_sets:
            graph = gremlin.execution_graph.ActionSetExecutionGraph(action_set, parent)
            self.action_sets.append(graph)        
            self.graph_map[index] = graph
            self.index_map[graph] = index

        self.index = 0
        self.last_execution = 0.0
        self.last_value = None

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        for cond in container.activation_condition.conditions:
            if isinstance(cond, gremlin.base_classes.InputActionCondition):
                if cond.comparison == "press":
                    self.switch_on_press = True


        eh = gremlin.event_handler.EventListener()
        eh.macro_step_completed.connect(self._macro_completed)

    def profile_start(self):
        ''' occurs at profile start '''
        self.index = 0
        self._event = None
        self._value = None
        self._macro_id = None


    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value):
        syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose

        if self._macro_id is not None:
            # ignore events while the sequence is still running
            return True
        
        auto_release = False


        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        elif not isinstance(value.current, bool):
            syslog.warning(f"Invalid data type received in Sequence container: {type(event.value)}")
            return False
        else:
            is_pressed = value.current

        
        if self.container.trigger_on_release:
            if is_pressed:
                # ignore pressed event if we're triggering on input release 
                if verbose: syslog.info(f"SEQUENCE: execute - ignore pressed event")
                return True
            is_pressed = True # flip it for containers
            auto_release = True
            value.is_pressed = is_pressed
            value.current = is_pressed
            event.is_pressed = is_pressed
            event.raw_value = is_pressed

        
        self._macro_id = 0 
       


        count = len(self.action_sets)

        mgr = gremlin.macro.MacroManager()
        macro = gremlin.macro.Macro()
        self._macro_id = macro.id
        for index in range(count):
            graph = self.action_sets[index]
            action = gremlin.macro.GraphAction(graph, event, value)
            action.data = f"Step {index + 1}"
            macro.add_action(action)

            
        # queue the work up
        mgr.queue_macro(macro)
        if verbose: syslog.info(f"SEQUENCE: execute graph sequence - id {self._macro_id}")
        
        return True
    
    @QtCore.Slot(int)
    def _macro_completed(self, id : int):
        ''' occurs when a macro completes - the id is the id of the macro completed '''
        
        if self._macro_id is not None and id == self._macro_id:
            syslog = logging.getLogger("system")
            verbose = gremlin.config.Configuration().verbose
            if verbose: syslog.info(f"SEQUENCE: completed graph sequence - id {self._macro_id}")
            self._macro_id = None


class SequenceContainer(AbstractContainer):

    """Represents a container which holds sequential actions.

    The actions will trigger one after the other with subsequent activations.
    
    """

    name = "Sequence"
    tag = "sequence"

    #override default allowed inputs here
    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
        InputType.OpenSoundControl,
        InputType.Midi,
        InputType.Mouse
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
        self.trigger_on_release = False # true if the sequence triggers on input release instead of input press
        

    def _parse_xml(self, node):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        if "trigger_on_release" in node.attrib:
            self.trigger_on_release = safe_read(node,"trigger_on_release",bool,False)
            # action sets are read by the parent

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", SequenceContainer.tag)
        node.set("trigger_on_release",safe_format(self.trigger_on_release,bool))
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
