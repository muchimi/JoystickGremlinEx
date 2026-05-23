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
from gremlin.input_item import AbstractContainer, AbstractContainerWidget
import gremlin.base_profile

from shiboken6 import Shiboken
from gremlin.util import safe_format, safe_read
import logging
from PySide6 import QtCore, QtWidgets
import gremlin.ui.state_device

syslog = logging.getLogger("system")
class StateContainerWidget(AbstractContainerWidget):

    """
    State container which holds one or more actions conditions by a state.
    Actions in the container execute if a particular state is set, or not set depending on the options.
    This avoids the need to setup a condition checking for a state on a particular group of actions or container.

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

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui:
            syslog.info("StateContainerWidget: create action UI start")
        

        self.state_selector_widget = gremlin.ui.ui_common.QDataComboBox()
        self.state_selector_widget.currentIndexChanged.connect(self._handle_state_changed)
        desired_height = self.state_selector_widget.sizeHint().height()
        self.state_selector_widget.setFixedHeight(desired_height) # fix for layout issue in QT causing the box to expand vertically for some odd reason
        
        widgets = ["State:", self.state_selector_widget]
        widget = gremlin.ui.ui_common.getGridContainer(widgets, widget_only=True)
        self.action_layout.addWidget(widget)
        w1 = widget

        self.state_description_widget = QtWidgets.QLabel()
        widgets = ["Description:", self.state_description_widget]
        widget = gremlin.ui.ui_common.getGridContainer(widgets, widget_only=True)
        w2 = widget
        
        widgets = []
        rb = gremlin.ui.ui_common.QDataRadioButton(value = self.container.required_value, label = "On/Pressed", data = True, callbackEx = self._handle_execute_changed,
                                                   tooltip = "The container actions execute if the state exists and is on/pressed." )
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataRadioButton(value = not self.container.required_value, label = "Off/Released", data = False, callbackEx = self._handle_execute_changed,
                                                   tooltip = "The container actions execute if the state exists and is off/released." )
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataRadioButton(value = not self.container.required_value, label = "Any value", data = None, callbackEx = self._handle_execute_changed,
                                                   tooltip = "The container actions execute if the state exists and is either on/pressed or off/released." )
        widgets.append(rb)
        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        widget = gremlin.ui.ui_common.getGridContainer(["Execute when state is:",widget], widget_only=True)
        self.action_layout.addWidget(widget)
        w3 = widget
        

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
                "State",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

            self.action_layout.addWidget(widget)
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

            self.action_layout.addWidget(action_selector)


        self.populate_selector()

        gremlin.ui.ui_common.synchronize_grids([w1, w2, w3]) 

        if verbose_ui:
            syslog.info("StateContainerWidget: create action UI completed")


    def _handle_execute_changed(self, widget, checked : bool):
        if checked:
            self.container.required_value = widget.data
    
    def _handle_state_changed(self):
        if Shiboken.isValid(self.state_selector_widget):
            self.container.state = self.state_selector_widget.currentText()
            data = self.state_selector_widget.currentData()
            if data:
                description = data.description
            else:
                description = "No state selected"
            self.setDescription(description)

    def setDescription(self, value):
        if Shiboken.isValid(self.state_description_widget):
            self.state_description_widget.setText(value if value else "n/a")


    def populate_selector(self):
        ''' updates the available states '''
        if Shiboken.isValid(self.state_selector_widget):
            with QtCore.QSignalBlocker(self.state_selector_widget):
                self.state_selector_widget.clear()
                sd = gremlin.ui.state_device.StateData()
                # add a not set value
                self.state_selector_widget.addItem("[Not Set]", None)
                for key, data in sd.getStates().items():
                    self.state_selector_widget.addItem(key, data)
            
                key = self.container.state
                if key:
                    index = self.state_selector_widget.findText(key)
                    if index >= 0:
                        self.state_selector_widget.setCurrentIndex(index)
                
                    data = self.state_selector_widget.currentData()
                    description = data.description if data else "N/A"
                else:
                    description = "No state selected"

                self.setDescription(description)        

    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            widget = self._create_action_set_widget(
                self.profile_data.action_sets[0],
                "State",
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
        # blows up in QT 6.11
        if Shiboken.isValid(self):
            self.container_modified.emit()
        

    def _paste_action(self, action, container):
        ''' paste action'''

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        self.profile_data.add_action(action_item)
        if Shiboken.isValid(self):
            self.container_modified.emit()
        

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
        title = "State: "
        if len(self.profile_data.action_sets) > 0:
            stub =  ", ".join(a.name for a in self.profile_data.action_sets[0])
            title += stub
        
        return title


class StateContainerFunctor(gremlin.base_profile.AbstractFunctor):

    """Executes the contents of the associated basic container."""

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        self.sd = gremlin.ui.state_device.StateData()
        self.verbose = False

    def profile_start(self):
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_container or config.verbose_mode_state

    def process_event(self, event, value, extra_data = None):
        """Executes the content with the provided data.

        :param event the event to process
        :param value the value received with the event
        :return True if execution was successful, False otherwise
        """
        
        
        key = self.action_data.state
        if not key:
            # state not provided = succeed
            if self.verbose:
                syslog.info("STATE CONTAINER: no state provided: SUCCESS")
            return True
        
        state = self.sd.getState(key)
        if state is None:
            # state does not exist = FAIL
            if self.verbose:
                syslog.info(f"STATE CONTAINER: state [{key}] does not exist: FAIL")
            return False
        
        required_value = self.action_data.required_value
        if required_value is None:
            if self.verbose:
                syslog.info("STATE CONTAINER: required value ANY:  SUCCESS")
            return True
        
        state_value = state.value
        result = state_value == required_value
        if self.verbose:
            syslog.info(f"STATE CONTAINER: required value [{required_value}] state [{key}] value [{state_value}]: {'SUCCESS' if result else 'FAIL'}")
        return result
        



class StateContainer(AbstractContainer):

    """Represents a container which holds exactly one action."""

    name = "State"
    tag = "state"
    hint = '''This container executes its contents based on a current state.'''

    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]
    
    interaction_types = []

    functor = StateContainerFunctor
    widget = StateContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.state = None # the state
        self.required_value = True # execute on state set by default

    
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
                        if gremlin.input_item._is_curve_tag(t_action.tag): 
                            curve_sets.append(action_set)
                        elif t_action.tag == "remap":
                            remap_sets.append(action_set)

            if action.tag == "remap" and len(curve_sets) == 1 and \
                    len(remap_sets) == 0:
                curve_sets[0].append(action)
            elif gremlin.input_item._is_curve_tag(action.tag) and len(remap_sets) == 1 and \
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
        if "state" in node.attrib:
            self.state = node.get("state")
        self.required_value = safe_read(node,"value",bool,True)
        

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", "state")
        if self.state:
            node.set("state", self.state)
        node.set("value", safe_format(self.required_value, bool))

        # as_node = ElementTree.Element("action-set")
        # as_node.set("id", write_guid(self.action_sets[0].id))
        # if self.action_sets:
        #     for action in self.action_sets[0]:
        #         as_node.append(action.to_xml())
        # node.append(as_node)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) == 1


# Plugin definitions
version = 1
name = "state"
create = StateContainer
