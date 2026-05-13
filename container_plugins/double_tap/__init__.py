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

import copy
import logging
import threading
import time
from lxml import etree as ElementTree

from PySide6 import QtWidgets

import gremlin
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
from gremlin.input_types import InputType
from shiboken6 import Shiboken
from gremlin.util import safe_format, safe_read, write_guid, get_guid, read_guid

syslog = logging.getLogger("system")

class DoubleTapContainerWidget(AbstractContainerWidget):

    """DoubleTap container for actions for double or single taps."""

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
        self.delay_input = gremlin.ui.ui_common.QDelayWidget(label = "<b>Double-tap delay: </b>",
                                                             callback = self._delay_changed_cb)
        self.delay_input.setValue(self.profile_data.delay)
        self.options_layout.addWidget(self.delay_input)
        self.options_layout.addStretch()

        # Activation moment
        self.options_layout.addWidget(QtWidgets.QLabel("<b>Single/Double Tap: </b>"))
        self.activate_exclusive = QtWidgets.QRadioButton("exclusive")
        self.activate_combined = QtWidgets.QRadioButton("combined")
        if self.profile_data.activate_on == "combined":
            self.activate_combined.setChecked(True)
        else:
            self.activate_exclusive.setChecked(True)

        self.activate_combined.toggled.connect(self._activation_changed_cb)
        self.activate_exclusive.toggled.connect(self._activation_changed_cb)
        self.options_layout.addWidget(self.activate_exclusive)
        self.options_layout.addWidget(self.activate_combined)

        self.action_layout.addLayout(self.options_layout)

        if self.profile_data.action_sets[0] is None:
            self._add_action_selector(
                lambda x: self._add_action(0, x),
                "Single Tap",
                lambda x: self._paste_action(0, x),
            )
        else:
            self._create_action_widget(
                0,
                "Single Tap",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

        if self.profile_data.action_sets[1] is None:
            self._add_action_selector(
                lambda x: self._add_action(1, x),
                "Double Tap",
                lambda x: self._paste_action(1, x),
            )
        else:
            self._create_action_widget(
                1,
                "Double Tap",
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )

    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            if self.profile_data.action_sets[0] is not None:
                self._create_action_widget(
                    0,
                    "Single Tap",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )

            if self.profile_data.action_sets[1] is not None:
                self._create_action_widget(
                    1,
                    "Double Tap",
                    self.activation_condition_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )

    def _add_action_selector(self, add_action_cb, label, paste_action_cb):
        """Adds an action selection UI widget.

        :param add_action_cb function to call when an action is added
        :param label the description of the action selector
        """
        input_item = self.profile_data.input_item
        action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            input_item,
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
        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.get_class(action_name)(self.profile_data)
            if self.profile_data.action_sets[index] is None:
                self.profile_data.action_sets[index] = []
            self.profile_data.action_sets[index].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
            if Shiboken.isValid(self):
                self.container_modified.emit()
        finally:
            gremlin.util.popCursor()


    def _paste_action(self, index, action):
        ''' pastes an action '''
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        if self.profile_data.action_sets[index] is None:
            self.profile_data.action_sets[index] = []
        self.profile_data.action_sets[index].append(action_item)
        self.profile_data.create_or_delete_virtual_button()
        self.container_modified.emit()


    def _delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the double-tap action activates
        """
        self.profile_data.delay = value

    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_combined.isChecked():
            self.profile_data.activate_on = "combined"
        else:
            self.profile_data.activate_on = "exclusive"

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
        if self.profile_data.is_valid():
            return f"Double Tap: ({", ".join([a.name for a in self.profile_data.action_sets[0]])}) / ({", ".join([a.name for a in self.profile_data.action_sets[1]])})"
        else:
            return "Double Tap"


class DoubleTapContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):

    """Executes the contents of the associated DoubleTap container."""

    def __init__(self, container, parent = None):
        super().__init__(container, parent)

    def profile_start(self):
        container = self.action_data

        self.delay = container.delay
        self.activate_on = container.activate_on

        self.start_time = 0
        self.double_action_timer = None
        self.tap_type = None
        self.value_press = None
        self.event_press = None
        self.processed_single_tap = True


    def profile_started(self):
        super().profile_started()

    def _trigger_single_tap(self, event, value, extra_data : dict = None) -> bool:
        ''' triggers a short press '''
        return self._trigger(0, event, value, extra_data)
        

    def _trigger_double_tap(self, event, value, extra_data : dict = None) -> bool:
        ''' triggers a long press '''
        return self._trigger(1, event, value, extra_data)

    def process_event(self, event, value, extra_data = None):
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        elif not isinstance(value.current, bool):
            syslog.warning(
                f"Invalid data type received in DoubleTap container: {type(event.value)}"
            )
            return False
        else:
            is_pressed = value.current

        if self.processed_single_tap:
                
                # Copy state when input is pressed
                if is_pressed:
                    self.value_press = copy.deepcopy(value)
                    self.event_press = event.clone()

                # Execute double tap logic
                if is_pressed:
                    
                    # Second activation within the delay, i.e. second tap
                    if (self.start_time + self.delay) > time.time():
                        # Prevent repeated double taps from repeated button presses
                        self.start_time = 0
                        self.tap_type = "double"
                        if self.activate_on == "exclusive":
                            self.double_action_timer.cancel()
                    # First activation within the delay, i.e. first tap
                    else:
                        self.start_time = time.time()
                        #print ("first activation")
                        self.tap_type = "single"
                        if self.activate_on == "exclusive":
                            self.double_action_timer = \
                                threading.Timer(self.delay, self._single_tap)
                            self.double_action_timer.start()

                # Input is being released at this point
                elif self.double_action_timer and self.double_action_timer.is_alive():
                    # if releasing single tap before delay
                    # we will want to send a short press and release
                    self.double_action_timer.cancel()
                    self.double_action_timer = threading.Timer(
                        (self.start_time + self.delay) - time.time(),
                        lambda: self._single_tap(event, value, extra_data)
                    )
                    self.double_action_timer.start()

                if self.tap_type == "double":
                    #print ("double tap")
                    self._trigger_double_tap(event, value, extra_data)
                    #self.double_tap.process_event(event, value)
                    if self.activate_on == "combined":
                        self._trigger_single_tap(event, value, extra_data)
                        #self.single_tap.process_event(event, value)
                elif self.activate_on != "exclusive":
                    #print ("single tap exclusive")
                    self._trigger_single_tap(event, value, extra_data)
                    #self.single_tap.process_event(event, value)
        
        else:
            #print ("first tap")
            self.start_time = time.time()
            self._trigger_single_tap(event, value, extra_data)
            #self.single_tap.process_event(event, value)
            self.processed_single_tap = True
            
            

        return False # stop execution as the logic is internal to trigger the other nodes

    def _single_tap(self, event_release=None, value_release=None, extra_data : dict = None):
        """Callback executed, when the delay expires."""
        self.processed_single_tap = False
        self._trigger_single_tap(self.event_press, self.value_press, extra_data)
        #self.single_tap.process_event(self.event_press, self.value_press)
        if event_release:
            time.sleep(0.05)
            self._trigger_single_tap(event_release, value_release, extra_data)
            #self.single_tap.process_event(event_release, value_release)
            self.processed_single_tap = True

class DoubleTapContainer(AbstractContainer):

    """A container with two actions which are triggered based on the delay
    between the taps.

    A single tap will run the first action while a double tap will run the
    second action.
    """

    name = "Double Tap"
    tag = "double_tap"
    hint = '''Use this container to trigger an action on single trigger click/tap,
and another action on input double-click (tap)'''
    functor = DoubleTapContainerFunctor
    widget = DoubleTapContainerWidget

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

    interaction_types = [
        #gremlin.ui.input_item.ActionSetView.Interactions.Edit,
        gremlin.ui.input_item.ActionSetView.Interactions.Add,
        gremlin.ui.input_item.ActionSetView.Interactions.Delete
    ]

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.setActionSets([[], []])
        self.delay = 0.5
        self.activate_on = "exclusive"

    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        super()._parse_xml(node, data, extra_data)
        self.delay = gremlin.profile.safe_read(node, "delay", float, 0.5)
        self.activate_on = \
            gremlin.profile.safe_read(node, "activate-on", str, "combined")

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", DoubleTapContainer.tag)
        node.set("delay", str(self.delay))
        node.set("activate-on", self.activate_on)
        for action_set in self.action_sets:
            if action_set:
                as_node = ElementTree.Element("action-set")
                as_node.set("id", write_guid(action_set.id))
                for action in action_set:
                    as_node.append(action.to_xml())
                node.append(as_node)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) == 2 and None not in self.action_sets


# Plugin definitions
version = 1
name = "double_tap"
create = DoubleTapContainer
