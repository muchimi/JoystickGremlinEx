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
import time

from sympy.physics import sho


import gremlin
import gremlin.ui.ui_common
import gremlin.input_item
from gremlin.input_item import AbstractContainer, AbstractContainerWidget, ActionSelector, InputItem
from gremlin.input_types import InputType
from shiboken6 import Shiboken
from gremlin.types import ContainerViewTypes, Interactions
import copy
from gremlin.util import safe_read, safe_format, ansiYellow, ansiMagenta,  ansiResult, ansiRed

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
        self._actionset_widget_map = {}

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self.container.create_or_delete_virtual_button()

        # Activation delay
        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(
            label="Double-tap delay:",
            callback=self._delay_changed_cb,
            value=self.container.doubletap_delay * 1000,
            tooltip="Set the delay for double-tap detection in milliseconds.  This is the time window within which two taps must occur to be considered a double-tap.",
        )

        widget = gremlin.ui.ui_common.getHContainer([self.delay_widget, "||"], widget_only=True)
        self.action_layout.addWidget(widget)

        # autorelease
        self.auto_release_checkbox = gremlin.ui.ui_common.QDataCheckbox(
            "Auto Release",
            value=self.container.auto_release,
            callback=self._auto_release_changed_cb,
            tooltip="Enable or disable trigger auto release.  If enabled, the trigger will automatically release after the specified delay.",
        )

        self.auto_release_delay_widget = gremlin.ui.ui_common.QDelayWidget(
            label="Auto Release Delay:",
            callback=self._auto_release_delay_changed_cb,
            value=self.container.autorelease_delay,
            tooltip="Set the delay for auto release in milliseconds.",
        )

        self.auto_release_delay_widget.setValue(self.container.autorelease_delay)
        widget = gremlin.ui.ui_common.getHContainer([self.auto_release_checkbox, "|", self.auto_release_delay_widget, "||"], widget_only=True)
        self.action_layout.addWidget(widget)


        # chain options
        self.chain_short_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Short Actions",
            value = self.container.chain_short,
            callback = self._handle_chain_short_changed_cb,
            tooltip="Enable or disable short action chaining.\nWhen chained, a single action executes per trigger in roundrobin fashion."
        )

        self.chain_double_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Double Tap Actions",
            value = self.container.chain_double,
            callback = self._handle_chain_double_changed_cb,
            tooltip="Enable or disable double tap action chaining.\nWhen chained, a single action executes per trigger in roundrobin fashion."
        )

        shortcut_map = {"0s":0,
                        "1s":1,
                        "2s":2,
                        "5s":5,
                        "10s":10}

        self.chain_timeout_widget = gremlin.ui.ui_common.QDelayWidget(
            value = self.container.chain_timeout, # to ms
            callback = self._chain_timeout_changed_cb,
            tooltip="Set the chain delay timeout value in seconds.  When chaining, if this time elapses, the chain will reset.",
            min_value_seconds   = 0,
            max_value_seconds = 3600,
            display_in_seconds=True,
            is_seconds=True,
            shortcut_map=shortcut_map,

        )

        widgets = [
            "Chaining Options:",
            self.chain_short_widget,
            self.chain_double_widget,
            "|",
            "Chain Timeout:",
            self.chain_timeout_widget,
            "||"
        ]


        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.action_layout.addWidget(widget)


        widget = gremlin.ui.ui_common.QExecuteWidget(
            self.container.execute_on_press,
            self.container.execute_on_release,
            press_callback=self._execute_on_press_changed,
            release_callback=self._execute_on_release_changed,
        )
        self.action_layout.addWidget(widget)


        self.short_widget, self.short_layout = gremlin.ui.ui_common.getVContainer()
        self.short_widget.setContentsMargins(8, 0, 0, 0)

        self.double_widget, self.double_layout = gremlin.ui.ui_common.getVContainer()
        self.double_widget.setContentsMargins(8, 0, 0, 0)

        self.action_layout.addWidget(self.short_widget)
        self.action_layout.addWidget(self.double_widget)

        self.short_layout_widget_list = []
        self.double_layout_widget_list = []

        action_set = self.container.short_action_set

        #  syslog.info(f"short actions: {len(action_set) if action_set is not None else 0}")
        widget = self._create_action_set_widget(
            action_set=action_set if action_set is not None else [],
            label="Short Action(s)",
            view_type=ContainerViewTypes.Action,
        )
        self.short_layout.addWidget(widget)
        self.short_layout_widget_list.append(widget)
        widget.redraw()
        widget.model.data_changed.connect(self.container_modified.emit)

        # create double tap  container actions
        action_set = self.container.double_action_set
        # syslog.info(f"double actions: {len(action_set) if action_set is not None else 0}")
        widget = self._create_action_set_widget(
            action_set=action_set if action_set is not None else [],
            label="Double Tap Action(s)",
            view_type=ContainerViewTypes.Action,
        )
        self.double_layout.addWidget(widget)
        self.double_layout_widget_list.append(widget)
        widget.redraw()
        widget.model.data_changed.connect(self.container_modified.emit)




        self._update_ui()

    def _chain_timeout_changed_cb(self, value: float):
        self.container.chain_timeout = value # in seconds


    def _handle_chain_short_changed_cb(self, value: bool):
        self.container.chain_short = value
        self._update_ui()

    def _handle_chain_double_changed_cb(self, value: bool):
        self.container.chain_double = value
        self._update_ui()

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        self.container.execute_on_press = checked
        self._update_ui()

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        self.container.execute_on_release = checked
        self._update_ui()

    def _auto_release_delay_changed_cb(self, value: bool):
        self.container.autorelease_delay = value
        self._update_ui()

    def _auto_release_changed_cb(self, value: bool):
        self.container.auto_release = value
        self._update_ui()

    def _update_ui(self):
        visible = self.container.auto_release
        self.auto_release_delay_widget.setVisible(visible)

        self.auto_release_delay_widget.setEnabled(self.container.auto_release)
        self.chain_timeout_widget.setEnabled(self.container.chain_short or self.container.chain_double)

    def _create_condition_ui(self):

        gremlin.util.clear_layout(self.activation_condition_layout)
        short_action_set = self.container.short_action_set
        double_action_set = self.container.double_action_set
        self._actionset_widget_map["short"] = self._create_action_widget(
            short_action_set, "Short Press", self.activation_condition_layout, ContainerViewTypes.Conditions
        )
        self._actionset_widget_map["double"] = self._create_action_widget(
            double_action_set, "Double Tap", self.activation_condition_layout, ContainerViewTypes.Conditions
        )

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

    def _create_action_widget(self, action_set, label, layout, view_type):
        """Creates a new action widget.

        :param action_set the action set to create the widget for
        :param label the name of the action to create
        :param layout the layout to add the widget to
        :param view_type the type of view for the widget
        :returns the created widget
        """
        widget = self._create_action_set_widget(action_set, label, view_type)
        layout.addWidget(widget)
        widget.redraw()
        widget.model.data_changed.connect(self.container_modified.emit)
        return widget

    def _delete_action(self, input_item, container, action):
        """removes an action"""
        if self.container != container:
            # not ours
            return
        gremlin.util.InvokeUiMethod(self._update_condition_ui)

    def _add_action(self, index, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.container)

        match index:
            case 0:
                action_item.data = "single"
                self.container.single_action_set.append([action_item])
            case 1:
                action_item.data = "double"
                self.container.double_action_set.append([action_item])
            case _:
                raise ValueError(f"Invalid action index: {index}")

        self.container.create_or_delete_virtual_button()
        if Shiboken.isValid(self):
            self.container_modified.emit()

    def _paste_action(self, index, action):
        """Pastes an action into the container.

        :param index the index at which to paste the action
        :param action the action to paste
        """
        """called when a paste occurs"""
        syslog.info("Paste short action")
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.container)

        match index:
            case 0:
                action_item.data = "single"
                self.container.single_action_set.append([action_item])
                for widget in self.short_layout_widget_list:
                    if Shiboken.isValid(widget):
                        widget.redraw()

            case 1:
                action_item.data = "double"
                self.container.double_action_set.append([action_item])
                for widget in self.double_layout_widget_list:
                    if Shiboken.isValid(widget):
                        widget.redraw()

            case _:
                raise ValueError(f"Invalid action index: {index}")

    def _delay_changed_cb(self, value):
        """Updates the activation delay value.

        :param value the value after which the double-tap action activates
        """
        self.container.doubletap_delay = value / 1000  # convert milliseconds to seconds

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

    def __init__(self, container: "DoubleTapContainer", parent=None):
        super().__init__(container, parent)

        self.container = container
        self.delay = container.doubletap_delay  # in seconds
        self.autorelease_delay = container.autorelease_delay  # in seconds
        self.activate_on = container.activate_on

        assert len(container.action_sets) == 2, "Double Tap container must have exactly 2 action sets: short, and double."

        self.start_time = 0

        self.short_press_timer = None
        self.last_trigger_time = None  # last event time

        self.value_press = None
        self.event_press = None
        self.chain_short = self.container.chain_short  # chain by default
        self.chain_double = self.container.chain_double  # chain by default
        self.short_index = 0
        self.double_index = 0

        self.last_short_execution = 0.0
        self.last_double_execution = 0.0
        self.last_short_value = None
        self.dtap_delay = self.container.doubletap_delay * 1000  # to seconds
        self.dtap_time = None
        self.waiting_second_tap = False
        self.first_tap_release_time = 0.0
        self.second_tap_press_time = 0.0

        self.short_nodes = []  # list of short action set nodes
        self.double_nodes = []  # list of double tap actions
        self.event_release = None

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        if container.has_conditions:
            for cond in container.activation_condition.conditions:
                if isinstance(cond, gremlin.input_item.BaseInputActionCondition):
                    if cond.comparison == "press":
                        self.switch_on_press = True


        self.autorelease_enabled = container.auto_release
        self.autorelease_delay = container.autorelease_delay / 1000  # in seconds

        self.last_trigger = None
        self._valid = False

    def profile_started(self):
        super().profile_started()
        # reset any prior values before start
        self.start_time = time.time()
        self.last_trigger_time = None

        self.short_press_timer = None
        self.value_press = None
        self.event_press = None
        
        self.short_index = 0 # index of the first short action when chaining
        self.dtap_index = 0 # index of the first double tap action when chaining

        self.short_index_time = None # time when the last chain index change occured
        self.dtap_index_time = None # time when the last double tap chain index change occured

        self.chain_short = self.container.chain_short  # chain by default
        self.chain_double = self.container.chain_double  # chain by default

        self.last_short_execution = 0.0
        self.last_short_value = None
        self.waiting_second_tap = False
        self.first_tap_release_time = 0.0
        self.second_tap_press_time = 0.0
        self._short_press_timer = None
        self._double_tap_timer = None
        self._first_tap_timer = None

        self.verbose = gremlin.config.Configuration().verbose_mode_container
        # self.verbose = True

        assert len(self.container.action_sets) == 2, "Double Tap container must have exactly 2 action sets: short, and double."
        short_count = len(self.container.short_action_set)
        double_count = len(self.container.double_action_set)
        if short_count + double_count == 0:
            syslog.warning("DOUBLETAP: Disabled: No actions found for short or double - disabling the container.")
            self._valid = False
            return

        self.last_trigger = None
        self.trigger_mode = None  # what to trigger



        ec = gremlin.execution_graph.ExecutionContext()
        container_node = ec.find(self.container, gremlin.execution_graph.ExecutionGraphNodeType.Container)
        if not container_node:
            # if we get here it usually means an instance of the functor is still in memory and hooked to the execution graph which should not happen
            syslog.error(
                f"DOUBLETAP: Disabled: Unable to find the container in the execution tree: [{str(self.container)}] - missing container ID: [{self.container.id}]"
            )
            self._valid = False


        self.dtap_enabled = double_count > 0 # enable double tap detect if nodes are found


        if not container_node.children:
            # this indicates a build or configuration error
            syslog.warning(f"DOUBLETAP: Disabled: The container node has no children: [{str(self.container)}] ")
            self._valid = False
            return

        assert container_node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.Container, "Logic error: Node is not a container node"

        # if self.verbose:
        #     syslog.info("DOUBLETAP: dumping container node")
        #     ec.dump(container_node)

        group_node = container_node.children[0]  # group node is the only child of the container node
        self.action_set_nodes = [node for node in group_node.children if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.ActionSet]

        action_set_node_count = len(self.action_set_nodes)
        assert action_set_node_count == 2, f"DOUBLETAP: Logic error: Expected 2 action set nodes in the group node - found [{action_set_node_count}]"

        self.short_nodes = [] # holds the execution nodes for the short actions
        self.dtap_nodes = [] # holds the execution nodes for the double tap actions
        self.short_enabled = False

        # get short action nodes
        action_set_node = self.action_set_nodes[0]
        if action_set_node.has_actions:
            self.short_enabled = True
            action_nodes = ec.getChainNodes(action_set_node)
            self.short_nodes.extend(action_nodes)
            self.next_short_index = 1 if len(action_nodes) > 1 else 0  # next short action index when chaining

        # get double tap action nodes
        action_set_node = self.action_set_nodes[1]
        if action_set_node.has_actions:
            action_nodes = ec.getChainNodes(action_set_node)
            self.dtap_nodes.extend(action_nodes)
            self.dtap_enabled = True
            self.next_dtap_index = 1 if len(action_nodes) > 1 else 0  # next double tap action index when chaining



        self.next_dtap_index = 0 # next double tap action index when chaining


        active_nodes = self.short_nodes + self.dtap_nodes

        self.has_actions = bool(active_nodes)


        if self.verbose:
            syslog.info("DOUBLETAP: profile start node counts:")
            syslog.info(f"\tShort nodes: {len(self.short_nodes)}")
            syslog.info(f"\tDouble tap nodes: {len(self.dtap_nodes)}")
            syslog.info(f"\tTotal nodes: {len(active_nodes)}")

        if not active_nodes:
            syslog.warning(f"DOUBLETAP: warning: {ansiRed('No action nodes found')} to execute for container [{self.container.id}].")
            self._valid = False
            return

        self.trigger_release = False  # press mode

        if self.dtap_enabled and self.container.doubletap_delay >= self.container.autorelease_delay:
            syslog.warning(f"DOUBLETAP: warning: {ansiRed('double tap delay exceeds autorelease delay')}  DoubleTap function disabled.")
            self.dtap_enabled = False


        if self.verbose or not self._valid:
            syslog.info("DOUBLETAP: Profile start Configuration:")
            syslog.info(f"\tContainer ID: {self.container.id}")
            syslog.info(f"\tProfile mode: {gremlin.shared_state.current_mode}")
            input_item: gremlin.input_item.InputItem = self.action_data._input_item
            syslog.info(f"\tAttached to input: {input_item.display_name}")
            syslog.info(f"\tExecution mode: activate on {self.container.activate_on}")
            syslog.info(f"\tShort action sets: {len(self.container.short_action_set)}")
            syslog.info(f"\tDouble tap action sets: {len(self.container.double_action_set)}")
            syslog.info(f"\tChain enabled: short: [{self.container.chain_short}] dtap: [{self.container.chain_double}]")
            syslog.info(f"\tDouble tap enabled: {ansiResult(self.dtap_enabled)}")
            syslog.info(f"\tTimers: double tap delay (s): [{self.container.doubletap_delay:0.3f}] autorelease delay: [{self.container.autorelease_delay:0.3f}]")



    def _trigger_double_press(self, event, value, extra_data: dict = None):
        """called on double tap trigger"""

        if event is None:
            # can happen if a queued timer/thread callback fires after a mode
            # change already cleared the pending event reference
            return

        is_pressed = event.is_pressed

        # double tap processing
        if self.verbose:
            if is_pressed:
                syslog.info(f"\tTrigger: {gremlin.util.ansiText('double press (press)', 'red', True)} {self._debug_stub()}")
            else:
                syslog.info(f"\tTrigger: {gremlin.util.ansiText('double press (release)', 'red', True)} {self._debug_stub()}")


        if self.chain_double:
            node_count = len(self.dtap_nodes)
            if node_count:
                if self.verbose:
                    syslog.info(f"(chaining) execute double tap action index [{self.dtap_index}] is pressed: [{is_pressed}]")
                ec = gremlin.execution_graph.ExecutionContext()
                node = self.dtap_nodes[self.dtap_index]
                ec.execute_node(node, event, value, extra_data)


                if not is_pressed and node_count > 1:
                    # bump to next double action but only on press
                    self.dtap_index = self.next_dtap_index
                    time_now = time.time()  # record the current time for the index change
                    if self.dtap_index_time is None or time_now - self.dtap_index_time < self.container.chain_timeout:
                        self.dtap_index_time = time_now
                        index = self.dtap_index + 1
                        if index >= node_count:
                            index = 0
                        self.dtap_index = index

                    else:
                        if self.verbose:
                            syslog.info("\tReset double tap index due to chain timeout")
                        self.dtap_index = 0 # reset



        else:
            # not chaining
            for node in self.dtap_nodes:
                ec = gremlin.execution_graph.ExecutionContext()
                ec.execute_node(node, event, value, extra_data)

    def _debug_stub(self) -> str:
        input_item: gremlin.input_item.InputItem = self.action_data._input_item
        return f"Input: {input_item.display_name} Profile mode: {gremlin.shared_state.current_mode}"

    def _trigger_short_press(self, event, value, extra_data: dict = None):
        """triggers a short press"""

        if event is None:
            # can happen if a queued timer/thread callback fires after a mode
            # change already cleared the pending event reference
            return

        is_pressed = event.is_pressed
        if is_pressed:
            if self.last_trigger:
                return  # wrong mode
            self.last_trigger = "short"
        else:
            if not self.last_trigger or self.last_trigger != "short":
                # wrong mode
                return
            self.last_trigger = None  # reset

        if self.verbose:
            if is_pressed:
                syslog.info(f"\tTrigger: {gremlin.util.ansiText('short press (press)', 'yellow', True)} {self._debug_stub()}")
            else:
                syslog.info(f"\tTrigger: {gremlin.util.ansiText('short press (release)', 'yellow', True)} {self._debug_stub()}")

        if self.chain_short:
            node_count = len(self.short_nodes)
            if node_count:
                if self.verbose:
                    syslog.info(f"(chaining) execute short press, index [{self.short_index}] is pressed: [{is_pressed}]")
                ec = gremlin.execution_graph.ExecutionContext()
                node = self.short_nodes[self.short_index]
                ec.execute_node(node, event, value, extra_data)

                if not is_pressed and node_count > 1:
                    # bump short index if chaining (on trigger only)
                    time_now = time.time()  # record the current time for the index change
                    if self.verbose:
                        if self.short_index_time is not None:
                            delay = time_now - self.short_index_time
                            syslog.info(f"Time since last short index bump (s): [{delay}]  Timeout (s): [{self.container.chain_timeout}] Elapsed: [{delay < self.container.chain_timeout}]")
                        else:
                            syslog.info(f"Timeout (s): [{self.container.chain_timeout}]")

                    elapsed = self.short_index_time is None or (time_now - self.short_index_time) < self.container.chain_timeout
                    if elapsed:
                        index = self.short_index + 1
                        if index >= node_count:
                            index = 0
                        self.short_index = index
                        self.short_index_time = time_now
                        if self.verbose:
                            syslog.info(f"\tBump short index to [{self.short_index}]")

                    else:
                        self.short_index = 0  # reset if chain timeout has passed
                        if self.verbose:
                            syslog.info("\tReset short index due to chain timeout")




        else:
            # not chaining
            for node in self.short_nodes:
                ec = gremlin.execution_graph.ExecutionContext()
                ec.execute_node(node, event, value, extra_data)



    def _reset_first_tap_timer(self):
        if self._first_tap_timer:
            if self.verbose:
                syslog.info("\tstop first tap timer")
            self._first_tap_timer.cancel()
            self._first_tap_timer = None

    def _reset_timers(self):
        self._reset_first_tap_timer()
        self.first_tap_release_time = 0.0
        self.second_tap_press_time = 0.0

    def process_event(self, event, value, extra_data=None) -> bool:
        """handle input events

        trigger_mode values:
        None - not set / default
        "short" - short press mode
        "single" - single (short press mode) - short timer not ellapsed
        "double" - double press detected

        """

        if not self._valid:
            return False

        input_type = event.getInputType()

        if input_type == InputType.JoystickHat:
            is_pressed = value.current != (0, 0)
        else:
            is_pressed = event.is_pressed  # use new API for GremlinEx

        verbose = self.verbose

        # setup the press and release events regardless of trigger

        trigger = self.container.execute_on_press and is_pressed or self.container.execute_on_release and not is_pressed

        if verbose:
            syslog.info(f"DOUBLETAP: input press processing - trigger [{trigger}]")

        if trigger:
            if verbose:
                syslog.info("\tpressed mode processing")

            self.value_press = copy.deepcopy(value)
            self.value_release = copy.deepcopy(value)

            self.event_press = event.clone()
            self.event_release = event.clone()

            self.event_press.is_axis = False
            self.event_release.is_axis = False

            self.event_press.is_pressed = True
            self.event_release.is_pressed = False

            time_now = time.time()  # current time
            self.trigger_release = False  # press mode

            if self.dtap_enabled:
                # double tap enabled
                if verbose:
                    syslog.info("processing double tap")

                if self.waiting_second_tap:
                    if verbose:
                        syslog.info("second (or multi) tap processing")
                    self.waiting_second_tap = False # no longer waiting for second tap

                    elapsed = time_now - self.last_trigger_time
                    if elapsed <= self.dtap_delay:
                        # trigger received within double tap delay window - trigger double tap
                        if verbose:
                            syslog.info(f"\t{ansiYellow('double tap detect', True)}")
                        self.second_tap_press_time = time_now

                        if self.autorelease_enabled:
                            # autorelease mode
                            self._reset_timers()
                            self._double_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                        else:
                            # manual auto-release
                            self.trigger_mode = "double" # trigger double tap
                            self._trigger_double_press(self.event_press, self.value_press, extra_data)



                    else:
                        # tap occured after the double tap detection window - trigger single tap

                        if verbose:
                            syslog.info(f"\t{ansiYellow('single tap detect', True)}")
                        if self.autorelease_enabled:
                            # auto release mode
                            self._reset_timers()
                            self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)
                        else:
                            # manual release mode
                            self.trigger_mode = "single" # trigger single tap
                            self._trigger_short_press(self.event_press, self.value_press, extra_data)
                else:
                    # indicate we're waiting on the next tap
                    if verbose:
                        syslog.info("first tap processing")
                    self.waiting_second_tap = True # wait for the second tap
                    # triger the short press timer
                    self._first_tap_timer = threading.Timer(self.container.doubletap_delay, self._handle_tap_timeout)
                    self._first_tap_timer.start()

            else:
                # single tap only mode (no double tap actions or not enabled) - trigger single tap only
                if self.verbose:
                    syslog.info(f"\t{ansiYellow('single tap detect', True)}")
                self._reset_timers()
                self.trigger_mode = "single" # trigger single tap
                if self.autorelease_enabled:
                    self._trigger_short_press(self.event_press, self.value_press, extra_data)
                else:
                    self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, extra_data)


            self.last_trigger_time = time_now  # time of last trigger event

        else:
            # input is released


            if self.waiting_second_tap:
                # release while the first tap timer is running
                pass # ignore the release
            else:
                # not waiting for second tap
                if verbose:
                    syslog.info(f"DOUBLETAP: release mode processing - trigger mode: [{self.trigger_mode}]")
                self.trigger_release = True  # indicate a release trigger occured
                # process the current mode
                if not self.autorelease_enabled:
                    # manually release (autorelease has timers that do this)
                    self._reset_timers()
                    match self.trigger_mode:
                        case "single" | "short":
                            if verbose:
                                syslog.info(f"\ttrigger {ansiMagenta('short press release', True)}")
                            self._trigger_short_press(self.event_release, self.value_press, extra_data)

                        case "double":
                            if verbose:
                                syslog.info(f"\ttrigger {ansiMagenta('double tap release', True)}")
                            self._trigger_double_press(self.event_release, self.value_press, extra_data)

                    self.trigger_mode = None



        return False  # stop execution because it's handled internally



    def _handle_tap_timeout(self):
        """ called when the timeout occurs after the first tap"""
        if self.verbose:
            syslog.info(f"first tap timer lapsed: {ansiYellow("trigger short press")}")
        self.waiting_second_tap = False
        self._reset_timers()
        if self.autorelease_enabled:
            # autorelease mode
            self._short_press(self.event_press, self.value_press, self.event_release, self.value_release, None)
        else:
            # manual mode
            self._trigger_short_press(self.event_release, self.value_press, None)


    def _short_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """

        if self.verbose:
            syslog.info("DOUBLETAP: handle short press")

        if self.short_enabled:
            self._reset_timers()
            self._trigger_short_press(event_p, value_p, extra_data)
            if self.autorelease_enabled:
                # queue autorelease callback
                callback = self._create_callback(self._trigger_short_press, event_r, value_r, extra_data)
                if self.autorelease_delay > 0:
                    timer = threading.Timer(self.autorelease_delay, callback)
                    if self.verbose:
                        syslog.info("\tstart short press release timer")
                    timer.start()
                else:
                    # trigger immediately
                    callback()

        self.trigger_mode = None  # reset mode

    def _handle_short_press_release(self, event, value, extra_data):
        if self.short_enabled:
            if self.verbose:
                syslog.info("\tshort press release timer lapsed")
            self._trigger_short_press(event, value, extra_data)

    def _create_callback(self, functor, event, value, extra_data):
        return lambda: functor(event, value, extra_data)

    def _double_press(self, event_p, value_p, event_r, value_r, extra_data):
        """Callback executed for a short press action.

        :param event_p event to press the action
        :param value_p value to press the action
        :param event_r event to release the action
        :param value_r value to release the action
        """

        if self.verbose:
            syslog.info("DOUBLETAP: handle dtap press")

        if self.dtap_enabled:
            self._trigger_double_press(event_p, value_p, extra_data)
            if self.autorelease_enabled:
                if self.autorelease_delay > 0:
                    callback = self._create_callback(self._handle_double_tap_release, event_r, value_r, extra_data)
                    timer = threading.Timer(self.autorelease_delay, callback)
                    if self.verbose:
                        syslog.info("\tstart double tap release timer")
                    timer.start()
                else:
                    # trigger immediately
                    callback()

        self.trigger_mode = None  # reset mode

    def _handle_double_tap_release(self, event, value, extra_data):
        if self.dtap_enabled:
            if self.verbose:
                syslog.info("\tdouble tap release timer lapsed")
            self._trigger_double_press(event, value, extra_data)


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

        self.doubletap_delay = 0.5
        self.activate_on = (
            "exclusive"  # determines if the double tap should be exclusive or combined - combined means both single and double taps can triggered on double tap
        )
        self.execute_on_press = True  # true if trigger should execute on input press event
        self.execute_on_release = False  # true if trigger should execute on input release event
        self.auto_release = True  # true if the action should auto release
        self.autorelease_delay = 250  # autorelease delay after a trigger in ms
        self.verbose = gremlin.config.Configuration().verbose_mode_container
        # self.verbose = True

        # chaining:
        # if set, short, long, and double tap actions are chained.
        # When chained, each action in the group executes, the index is bumped in roundrobin fashion.  Only one action executes per trigger.
        # When not chained, all actions in the group are executed in sequence at every trigger based on their priority.

        self.chain_short = False # dot not chain short actions
        self.chain_double = False # do not chain double actions

        self.chain_timeout : float = 2  # default chain timeout in seconds

        self.short_action_set = gremlin.input_item.ActionSet(model_description="Single Tap")
        self.double_action_set = gremlin.input_item.ActionSet(model_description="Double Tap")

        self.ensureActionSets()

        if self.verbose:
            self.action_sets.addOnItemChangedCallback(self._action_set_changed)
            self.short_action_set.addOnItemChangedCallback(self._single_action_set_changed)
            self.double_action_set.addOnItemChangedCallback(self._double_action_set_changed)

    def _action_set_changed(self, source, index, old_value, new_value, operation):
        """Callback for when any action set changes."""
        syslog.info(f"Action set changed: source={source}, index={index}, old_value={old_value}, new_value={new_value}, operation={operation}")
        pass

    def _double_action_set_changed(self, source, index, old_value, new_value, operation):
        """Callback for when the double action set changes."""
        syslog.info(f"Double action set changed: source={source}, index={index}, old_value={old_value}, new_value={new_value}, operation={operation}")
        pass

    def _single_action_set_changed(self, source, index, old_value, new_value, operation):
        """Callback for when the single action set changes."""
        syslog.info(f"Single action set changed: source={source}, index={index}, old_value={old_value}, new_value={new_value}, operation={operation}")
        pass

    def ensureActionSets(self):
        self.action_sets.clear(False)
        self.action_sets.add(self.short_action_set, 0)  # 0
        self.action_sets.add(self.double_action_set, 1)  # 1

    def resetActionSets(self):
        """resets actions sets - override in derived class if the action set default should be different"""
        self.short_action_set.clear()
        self.double_action_set.clear()

    def _parse_actionset_xml(self, node, data=None, extra_data=None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.resetActionSets()

        as_nodes = node.xpath(".//action-set")
        for index, as_node in enumerate(as_nodes):
            if index == 0:
                self._parse_action_xml(as_node, self.short_action_set, extra_data=extra_data)
            elif index == 1:
                self._parse_action_xml(as_node, self.double_action_set, extra_data=extra_data)

            syslog.info("Parsed action sets for double tap container")
        if self.verbose:
            syslog.info(f"\tSingle tap action actions set: {len(self.short_action_set)}")
            syslog.info(f"\tDouble tap action actions set: {len(self.double_action_set)}")

    def _parse_xml(self, node, input_item=None, extra_data=None):
        super()._parse_xml(node, input_item, extra_data)

        self.execute_on_press = True  # true if macro executes on input press/change
        self.execute_on_release = False  # true if macro executs on input release

        self.doubletap_delay = safe_read(node, "delay", float, 0.5)
        self.activate_on = safe_read(node, "activate-on", str, "combined")
        # old style
        if "exec-on-press" in node.attrib:
            self.execute_on_press = safe_read(node, "exec-on-press", bool, True)
        else:
            self.execute_on_press = safe_read(node, "execute-on-press", bool, True)
        if "exec-on-release" in node.attrib:
            self.execute_on_release = safe_read(node, "exec-on-release", bool, False)
        else:
            self.execute_on_release = safe_read(node, "execute-on-release", bool, False)

        self.auto_release = safe_read(node, "auto-release", bool, True)
        self.autorelease_delay = safe_read(node, "auto-release-delay", int, 250)
        self.chain_short = safe_read(node, "chain_short", bool, True)
        self.chain_double = safe_read(node, "chain_double", bool, True)
        self.chain_timeout = safe_read(node, "chain_timeout", float, 2)
    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", DoubleTapContainer.tag)
        node.set("delay", safe_format(self.doubletap_delay, float))
        node.set("activate-on", safe_format(self.activate_on, str))
        node.set("execute-on-press", safe_format(self.execute_on_press, bool))
        node.set("execute-on-release", safe_format(self.execute_on_release, bool))
        node.set("auto-release", safe_format(self.auto_release, bool))
        node.set("auto-release-delay", safe_format(self.autorelease_delay, int))
        node.set("chain_short", safe_format(self.chain_short, bool))
        node.set("chain_double", safe_format(self.chain_double, bool))
        node.set("chain_timeout", safe_format(self.chain_timeout, float))
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
