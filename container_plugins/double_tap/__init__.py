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

import logging
import threading


from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore, QtGui


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

    def __init__(self, input_item: gremlin.input_item.AbstractInputItem, container: "DoubleTapContainer", parent=None):  # noqa: F821
        """Creates a new instance.

        :param input_item the input item represented by this widget
        :param container the container represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(input_item, container, parent)

    def _create(self, container: "DoubleTapContainer"):
        self.container = container
        self.action_data = container
        self.input_item: InputItem = self.container.input_item

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self.container.create_or_delete_virtual_button()

        # Activation delay
        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(label="<b>Double-tap delay: </b>", callback=self._delay_changed_cb, value=self.action_data.delay)

        widget = gremlin.ui.ui_common.getHContainer([self.delay_widget, "||"], widget_only=True)
        self.action_layout.addWidget(widget)

        # autorelease
        self.auto_release_checkbox = QtWidgets.QCheckBox("Auto Release")
        self.auto_release_checkbox.setChecked(self.container.auto_release)
        self.auto_release_checkbox.stateChanged.connect(self._auto_release_changed_cb)
        self.action_layout.addWidget(self.auto_release_checkbox)
        self.auto_release_checkbox.setEnabled(False)
        self.container.auto_release = True # force True

        self.auto_release_delay_widget = gremlin.ui.ui_common.QDelayWidget(
            label="<b>Auto Release Delay: </b>", callback=self._auto_release_delay_changed_cb, value=self.action_data.auto_release_delay
        )
        self.auto_release_delay_widget.setValue(self.container.auto_release_delay)
        widget = gremlin.ui.ui_common.getHContainer([self.auto_release_checkbox, self.auto_release_delay_widget], widget_only=True)
        self.action_layout.addWidget(widget)

        # Activation moment
        self._activate_exclusive_widget = QtWidgets.QRadioButton("exclusive")
        self._activate_combined_widget = QtWidgets.QRadioButton("combined")
        if self.container.activate_on == "combined":
            self._activate_combined_widget.setChecked(True)
        else:
            self._activate_exclusive_widget.setChecked(True)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self._activate_combined_widget.toggled.connect(self._activation_changed_cb)
        self._activate_exclusive_widget.toggled.connect(self._activation_changed_cb)

        widget = gremlin.ui.ui_common.getHContainer(
            [self._execute_widget, "||", "<b>Single/Double Tap: </b>", self._activate_exclusive_widget, self._activate_combined_widget], widget_only=True
        )
        self.action_layout.addWidget(widget)

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

        self._update_ui()

    def _auto_release_delay_changed_cb(self, value: bool):
        self.action_data.auto_release_delay = value
        self._update_ui()

    def _auto_release_changed_cb(self, value: bool):
        self.action_data.auto_release = value

    def _update_ui(self):
        visible = self.action_data.auto_release
        self.auto_release_delay_widget.setVisible(visible)

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
        if self._activate_combined_widget.isChecked():
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
            return (
                f"Double Tap: ({', '.join([a.name for a in self.container.action_sets[0]])}) / ({', '.join([a.name for a in self.container.action_sets[1]])})"
            )
        else:
            return "Double Tap"

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        self.action_data.exec_on_release = checked


class DoubleTapContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):
    """Executes the contents of the associated DoubleTap container."""

    def __init__(self, container, parent=None):
        super().__init__(container, parent)
        self.container = container
        self.delay = 250
        self._tap_count = 0  # number of taps
        self._single_tap_timer = None  # timer for single tap
        self._autorelease_timer = None  # timer for auto releases
        self._autorelease_event = None  # event for auto releases
        self._single_triggered = False  # true if single tap triggered
        self._double_triggered = False  # true if double tap triggered

    def profile_start(self):
        self.container = self.action_data
        self.delay = self.container.delay / 1000  # to ms
        self._tap_count = 0  # number of taps
        self._single_tap_timer = None  # timer for single tap
        self._autorelease_timer = None  # timer for auto releases
        self._autorelease_event = None  # event for auto releases

    def profile_stop(self):
        self._reset_tap()
        self._reset_autorelease()

    def _trigger_single_tap(self, event, value, extra_data: dict = None) -> bool:
        """triggers a short press"""
        self._reset_tap()
        self._ensure_autorelease_event(event, value, extra_data)
        return self._trigger(0, event, value, extra_data)

    def _trigger_double_tap(self, event, value, extra_data: dict = None) -> bool:
        """triggers the double tap actions"""
        self._reset_tap()
        self._ensure_autorelease_event(event, value, extra_data)
        return self._trigger(1, event, value, extra_data)

    def _reset_tap(self):
        # resets taps to 0
        if self._single_tap_timer:
            self._single_tap_timer.cancel()
            self._single_tap_timer = None
        if self._autorelease_timer:
            self._autorelease_timer.cancel()
            self._autorelease_timer = None
        self._tap_count = 0

    def _reset_autorelease(self):
        if self._autorelease_event:
            self._autorelease_event.cancel()
            self._autorelease_event = None

    def _ensure_autorelease_event(self, event, value, extra_data):
        release_event = event.release_event()
        self._reset_autorelease()
        self._autorelease_timer = threading.Timer(self.action_data.auto_release_delay / 1000, lambda: self._trigger_auto_release(release_event, value, extra_data))
        self._autorelease_timer.start()

    def process_event(self, event, value, extra_data=None):
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0, 0)
        elif not isinstance(value.current, bool):
            syslog.warning(f"Invalid data type received in DoubleTap container: {type(value.current)}")
            return False
        else:
            is_pressed = value.current

        verbose = gremlin.config.Configuration().verbose_mode_container
        # verbose = True

        trigger = self.action_data.exec_on_press and is_pressed or self.action_data.exec_on_release and not is_pressed

        if trigger:
            if verbose:
                syslog.info("DTAP: trigger")
            match self._tap_count:
                case 0:
                    self._reset_tap()
                    self._tap_count += 1

                    if verbose:
                        syslog.info("DTAP:first tap")

                    self._single_tap_timer = threading.Timer(self.delay, lambda: self._single_tap_callback(event, value, extra_data))
                    self._single_tap_timer.start()

                case 1:
                    # second tap detected
                    self._ensure_autorelease_event(event, value, extra_data)
                    if self.action_data.activate_on == "exclusive":
                        syslog.info("DTAP:double tap exclusive")
                        self._double_triggered = True
                        self._trigger_double_tap(event, value, extra_data)
                    else:
                        if verbose:
                            syslog.info("DTAP:double tap combo")
                        self._single_triggered = True
                        self._trigger_single_tap(event, value, extra_data)

                        # still waiting for single tab
                        self._double_triggered = True
                        self._trigger_double_tap(event, value, extra_data)
        else:
            # release event
            if verbose:
                syslog.info("DTAP: release event")


        return False  # stop execution as the logic is internal to trigger the other nodes

    def _single_tap_callback(self, event, value, extra_data):
        self._single_triggered = True
        self._ensure_autorelease_event(event, value, extra_data)
        self._trigger_single_tap(event, value, extra_data)

    def _trigger_auto_release(self, event, value, extra_data):
        self._reset_autorelease()  # reset the auto-release state on release event
        verbose = gremlin.config.Configuration().verbose_mode_container
        # verbose = True

        if self._single_triggered:
            if verbose:
                syslog.info("DTAP: release single tap")
            self._trigger_single_tap(event, value, extra_data)
            self._single_triggered = False
        if self._double_triggered:
            if verbose:
                syslog.info("DTAP: release double tap")
            self._trigger_double_tap(event, value, extra_data)
            self._double_triggered = False



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

    def __init__(self, parent=None, node=None, extra_data: dict = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node, extra_data=extra_data, custom_action_sets=True, custom_parse_callback=self._parse_actionset_xml)

        self.delay = 0.5
        self.activate_on = (
            "exclusive"  # determines if the double tap should be exclusive or combined - combined means both single and double taps can triggered on double tap
        )
        self.exec_on_press = True  # true if trigger should execute on input press event
        self.exec_on_release = False  # true if trigger should execute on input release event
        self.auto_release = True  # true if the action should auto release
        self.auto_release_delay = 250  # autorelease delay after a trigger in ms

        self.single_tap_set = gremlin.input_item.ActionSet(model_description="Single Tap")
        self.double_tap_set = gremlin.input_item.ActionSet(model_description="Double Tap")

        self._ensure_action_sets()

    def _ensure_action_sets(self):
        self.action_sets.clear()
        self.action_sets.add(self.single_tap_set, 0)  # 0
        self.action_sets.add(self.double_tap_set, 1)  # 1

    def resetActionSets(self):
        """resets actions sets - override in derived class if the action set default should be different"""
        self.single_tap_set.clear()
        self.double_tap_set.clear()

    def _parse_actionset_xml(self, node, data=None, extra_data=None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.resetActionSets()

        as_nodes = node.xpath(".//action-set")
        for index, as_node in enumerate(as_nodes):
            if index == 0:
                self._parse_action_xml(as_node, self.single_tap_set, extra_data=extra_data)
            elif index == 1:
                self._parse_action_xml(as_node, self.double_tap_set, extra_data=extra_data)

    def _parse_xml(self, node, input_item=None, extra_data=None):
        super()._parse_xml(node, input_item, extra_data)

        self.delay = gremlin.profile.safe_read(node, "delay", float, 0.5)
        self.activate_on = gremlin.profile.safe_read(node, "activate-on", str, "combined")
        self.exec_on_press = gremlin.profile.safe_read(node, "exec-on-press", bool, True)
        self.exec_on_release = gremlin.profile.safe_read(node, "exec-on-release", bool, False)
        self.auto_release = True # force enabled  # gremlin.profile.safe_read(node, "auto-release", bool, True)
        self.auto_release_delay = gremlin.profile.safe_read(node, "auto-release-delay", int, 250)

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", DoubleTapContainer.tag)
        node.set("delay", str(self.delay))
        node.set("activate-on", self.activate_on)
        node.set("exec-on-press", str(self.exec_on_press))
        node.set("exec-on-release", str(self.exec_on_release))
        node.set("auto-release", str(self.auto_release))
        node.set("auto-release-delay", str(self.auto_release_delay))
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
