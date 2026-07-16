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
import gremlin.input_item
from gremlin.input_item import AbstractContainer, AbstractContainerWidget, ActionSelector, InputItem
from gremlin.input_types import InputType
from shiboken6 import Shiboken
from gremlin.types import ContainerViewTypes, Interactions

syslog = logging.getLogger("system")


class DoubleTapContainerWidget(AbstractContainerWidget):
    """DoubleTap container for actions for double or single taps."""

    def __init__(self, input_item : gremlin.input_item.AbstractInputItem, container : "DoubleTapContainer", parent=None):  # noqa: F821
        """Creates a new instance.

        :param input_item the input item represented by this widget
        :param container the container represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(input_item, container, parent)

    def _create(self, container : "DoubleTapContainer"):
        self.container = container
        self.input_item : InputItem = self.container.input_item

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self.container.create_or_delete_virtual_button()

        self.options_layout = QtWidgets.QHBoxLayout()

        # Activation delay
        self.delay_input = gremlin.ui.ui_common.QDelayWidget(label="<b>Double-tap delay: </b>", callback=self._delay_changed_cb)
        self.delay_input.setValue(self.container.delay)
        self.options_layout.addWidget(self.delay_input)
        self.options_layout.addStretch()

        # Activation moment
        self.options_layout.addWidget(QtWidgets.QLabel("<b>Single/Double Tap: </b>"))
        self.activate_exclusive = QtWidgets.QRadioButton("exclusive")
        self.activate_combined = QtWidgets.QRadioButton("combined")
        if self.container.activate_on == "combined":
            self.activate_combined.setChecked(True)
        else:
            self.activate_exclusive.setChecked(True)

        self.activate_combined.toggled.connect(self._activation_changed_cb)
        self.activate_exclusive.toggled.connect(self._activation_changed_cb)
        self.options_layout.addWidget(self.activate_exclusive)
        self.options_layout.addWidget(self.activate_combined)

        self.action_layout.addLayout(self.options_layout)

        self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.action_layout.addWidget(gremlin.ui.ui_common.QIconLabel("mdi.gesture-tap", "<b>Single Tap</b>", icon_size=24))
        if self.container.action_sets[0] is None:
            self._add_action_selector(
                lambda x: self._add_action(0, x),
                "Single Tap",
                lambda x: self._paste_action(0, x),
            )
        else:
            self._create_action_widget(0, "Single Tap", self.action_layout, ContainerViewTypes.Action)

        self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.action_layout.addWidget(gremlin.ui.ui_common.QIconLabel("mdi.gesture-double-tap", "<b>Double Tap</b>", icon_size=24))
        if self.container.action_sets[1] is None:
            self._add_action_selector(
                lambda x: self._add_action(1, x),
                "Double Tap",
                lambda x: self._paste_action(1, x),
            )
        else:
            self._create_action_widget(1, "Double Tap", self.action_layout, ContainerViewTypes.Action)

    def _create_condition_ui(self):
        if self.container.action_sets:
            if self.container.action_sets[0] is not None:
                self._create_action_widget(0, "Single Tap", self.activation_condition_layout, ContainerViewTypes.Conditions)

            if self.container.action_sets[1] is not None:
                self._create_action_widget(1, "Double Tap", self.activation_condition_layout, ContainerViewTypes.Conditions)

    def _add_action_selector(self, add_action_cb, label, paste_action_cb):
        """Adds an action selection UI widget.

        :param add_action_cb function to call when an action is added
        :param label the description of the action selector
        """
        input_item = self.container.input_item
        action_selector = ActionSelector(
            self.container.get_input_type(),
            input_item,
        )
        action_selector.inputItem = self.container
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
        widget = self._create_action_set_widget(self.container.action_sets[index], label, view_type)
        layout.addWidget(widget)
        widget.redraw()
        widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, index, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.container)
        if self.container.action_sets[index] is None:
            self.container.action_sets[index] = []
        self.container.action_sets[index].append(action_item)
        self.container.create_or_delete_virtual_button()
        if Shiboken.isValid(self):
            self.container_modified.emit()

    def _paste_action(self, index, action):
        """pastes an action"""
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.container)
        if self.container.action_sets[index] is None:
            self.container.action_sets[index] = []
        self.container.action_sets[index].append(action_item)
        self.container.create_or_delete_virtual_button()
        self.container_modified.emit()

    def _delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the double-tap action activates
        """
        self.container.delay = value

    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_combined.isChecked():
            self.container.activate_on = "combined"
        else:
            self.container.activate_on = "exclusive"

    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        index = self._get_widget_index(widget)
        if index != -1:
            if index == 0 and self.container.action_sets[0] is None:
                index = 1
            self.container.action_sets[index] = None
            self.container_modified.emit()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        if self.container.is_valid():
            return f"Double Tap: ({', '.join([a.name for a in self.container.action_sets[0]])}) / ({', '.join([a.name for a in self.container.action_sets[1]])})"
        else:
            return "Double Tap"


class DoubleTapContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):
    """Executes the contents of the associated DoubleTap container."""

    def __init__(self, container, parent=None):
        super().__init__(container, parent)

    def profile_start(self):
        self.container = self.action_data

        self.delay = self.container.delay
        self.activate_on = self.container.activate_on

        self.start_time = 0
        self.double_action_timer = None
        self.tap_type = None
        self.value_press = None
        self.event_press = None
        self.processed_single_tap = True

    def profile_started(self):
        super().profile_started()

    def _trigger_single_tap(self, event, value, extra_data: dict = None) -> bool:
        """triggers a short press"""
        return self._trigger(0, event, value, extra_data)

    def _trigger_double_tap(self, event, value, extra_data: dict = None) -> bool:
        """triggers a long press"""
        return self._trigger(1, event, value, extra_data)

    def process_event(self, event, value, extra_data=None):
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0, 0)
        elif not isinstance(value.current, bool):
            syslog.warning(f"Invalid data type received in DoubleTap container: {type(value.current)}")
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
                    # print ("first activation")
                    self.tap_type = "single"
                    if self.activate_on == "exclusive":
                        self.double_action_timer = threading.Timer(self.delay, self._single_tap)
                        self.double_action_timer.start()

            # Input is being released at this point
            elif self.double_action_timer and self.double_action_timer.is_alive():
                # if releasing single tap before delay
                # we will want to send a short press and release
                self.double_action_timer.cancel()
                self.double_action_timer = threading.Timer((self.start_time + self.delay) - time.time(), lambda: self._single_tap(event, value, extra_data))
                self.double_action_timer.start()

            if self.tap_type == "double":
                # print ("double tap")
                self._trigger_double_tap(event, value, extra_data)
                # self.double_tap.process_event(event, value)
                if self.activate_on == "combined":
                    self._trigger_single_tap(event, value, extra_data)
                    # self.single_tap.process_event(event, value)
            elif self.activate_on != "exclusive":
                # print ("single tap exclusive")
                self._trigger_single_tap(event, value, extra_data)
                # self.single_tap.process_event(event, value)

        else:
            # print ("first tap")
            self.start_time = time.time()
            self._trigger_single_tap(event, value, extra_data)
            # self.single_tap.process_event(event, value)
            self.processed_single_tap = True

        return False  # stop execution as the logic is internal to trigger the other nodes

    def _single_tap(self, event_release=None, value_release=None, extra_data: dict = None):
        """Callback executed, when the delay expires."""
        self.processed_single_tap = False
        self._trigger_single_tap(self.event_press, self.value_press, extra_data)
        # self.single_tap.process_event(self.event_press, self.value_press)
        if event_release:
            time.sleep(0.05)
            self._trigger_single_tap(event_release, value_release, extra_data)
            # self.single_tap.process_event(event_release, value_release)
            self.processed_single_tap = True


class DoubleTapContainer(AbstractContainer):
    """A container with two actions which are triggered based on the delay
    between the taps.

    A single tap will run the first action while a double tap will run the
    second action.
    """

    name = "Double Tap"
    tag = "double_tap"
    hint = """Use this container to trigger an action on single trigger click/tap,
and another action on input double-click (tap)"""
    functor = DoubleTapContainerFunctor
    widget = DoubleTapContainerWidget

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    interaction_types = [
        # Interactions.Edit,
        Interactions.Add,
        Interactions.Delete,
    ]

    def __init__(self, parent=None, node=None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node, custom_action_sets=True)

        self.delay = 0.5
        self.activate_on = "exclusive"
        self.action_sets.clear()
        self.action_sets.add(gremlin.input_item.ActionSet(self, "Single Tap"), 0)
        self.action_sets.add(gremlin.input_item.ActionSet(self, "Double Tap"), 1)



    def _parse_xml(self, node, data=None, extra_data=None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        super()._parse_xml(node, data, extra_data)
        self.delay = gremlin.profile.safe_read(node, "delay", float, 0.5)
        self.activate_on = gremlin.profile.safe_read(node, "activate-on", str, "combined")


        # read into custom action sets
        index = 0
        for as_node in node.xpath(".//action-set"):
            action_set = self.action_sets[index]
            action_set.clear()
            input_item = self.input_item
            self._parse_action_xml(as_node, action_set, input_item, extra_data)
            index += 1
            if index >= 2:
                break


    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", DoubleTapContainer.tag)
        node.set("delay", str(self.delay))
        node.set("activate-on", self.activate_on)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return True


# Plugin definitions
version = 1
name = "double_tap"
create = DoubleTapContainer
