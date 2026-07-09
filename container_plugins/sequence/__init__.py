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


from __future__ import annotations  # deprecated with python 3.14+
from PySide6 import QtWidgets

import logging
import time

from lxml import etree as ElementTree
import threading
import random
import gremlin
import gremlin.actions
import gremlin.input_item
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.input_item
from gremlin.input_item import AbstractContainer, AbstractContainerWidget, ActionSelector, AbstractAction, ActionSet, delete_widget
from gremlin.input_types import InputType
from PySide6 import QtCore
from gremlin.util import safe_format, safe_read, InvokeUiMethod, clear_layout, get_guid
from shiboken6 import Shiboken
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import SyncMode
import gremlin.joystick_handling
from gremlin.types import ContainerViewTypes, Interactions
from enum import IntEnum

syslog = logging.getLogger("system")


class SequenceMode(IntEnum):
    """sequence run mode"""

    Normal = 1
    Toggle = 2
    Step = 4
    Loop = 5
    Wiggle = 6

    @staticmethod
    def toString(mode: SequenceMode) -> str:
        return mode.name.casefold()

    @staticmethod
    def fromString(mode_str: str) -> SequenceMode:
        for mode in SequenceMode:
            if mode.name.casefold() == mode_str.casefold():
                return mode
        raise ValueError(f"Invalid sequence mode string: {mode_str}")


class SequenceRepeatMode(IntEnum):
    """sequence repeat mode"""

    Normal = 1
    Random = 2
    Loop = 3

    @staticmethod
    def toString(mode: SequenceRepeatMode) -> str:
        return mode.name.casefold()

    @staticmethod
    def fromString(mode_str: str) -> SequenceRepeatMode:
        for mode in SequenceRepeatMode:
            if mode.name.casefold() == mode_str.casefold():
                return mode
        raise ValueError(f"Invalid sequence repeat mode string: {mode_str}")


@SingletonDecorator
class GlobalSequence:
    """holds global sequence stats"""

    def __init__(self):
        self.sequence_count = 0  # number of active sequences
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.profile_start)

    def profile_start(self):
        # reset count on profile start
        self.sequence_count = 0

    def canExecute(self):
        max_concurrent = gremlin.config.Configuration().max_concurrent_sequence
        if max_concurrent:
            # concurrency is enabled if > 0
            return self.sequence_count + 1 < max_concurrent
        # concurrency disabled - always succeeed
        return True

    def pushSequence(self):
        self.sequence_count += 1

    def popSequence(self):
        if self.sequence_count:
            self.sequence_count -= 1


# instance
_global_sequence = GlobalSequence()


class StepOptions:
    """step options for each step"""

    def __init__(self):
        self.index = -1  # step index
        self.repeat_count = 2  # number of times the step should repeat
        self.mode = SequenceRepeatMode.Normal  # repeate mode
        self.repeat_min_delay = 250  # delay between repeat steps in ms
        self.repeat_max_delay = 250  # delay between repeat steps in ms
        self.autorelease_max_delay = 250  # delay for autorelease of each pulse in ms
        self.autorelease_min_delay = 250
        self.randomize_delay = False  # true if the interval between repeats is randomized
        self.randomize_autorelease_delay = False  # true if the autorelease delay is randomized

    def getCount(self) -> int:
        """gets the repeat count"""
        if self.mode == SequenceRepeatMode.Random:
            return random.randint(0, self.repeat_count)
        elif self.mode == SequenceRepeatMode.Normal:
            return 1
        return self.repeat_count

    def getDelay(self, default_delay_ms: int = 0) -> float:
        """gets the autorelease delay in seconds"""
        if self.mode == SequenceRepeatMode.Normal:
            return default_delay_ms / 1000

        if self.randomize_delay:
            return random.randint(self.repeat_min_delay, self.repeat_max_delay) / 1000
        return self.repeat_min_delay / 1000

    def getAutoreleaseDelay(self, default_delay_ms: int = 0) -> float:
        """gets the autorelease delay in seconds"""
        if self.mode == SequenceRepeatMode.Normal:
            return default_delay_ms / 1000

        if self.randomize_autorelease_delay:
            return random.randint(self.autorelease_min_delay, self.autorelease_max_delay) / 1000
        return self.autorelease_max_delay / 1000

    def to_xml(self):
        """saves to xml"""
        node = ElementTree.Element("step-option")
        node.set("index", safe_format(self.index, int))
        node.set("repeat-count", safe_format(self.repeat_count, int))
        node.set("mode", SequenceRepeatMode.toString(self.mode))
        node.set("repeat-min", safe_format(self.repeat_min_delay, int))
        node.set("repeat-max", safe_format(self.repeat_max_delay, int))
        node.set("autorelease-min", safe_format(self.autorelease_min_delay, int))
        node.set("autorelease-max", safe_format(self.autorelease_max_delay, int))
        node.set("randomize-delay", safe_format(self.randomize_delay, bool))
        node.set("randomize-autorelease", safe_format(self.randomize_autorelease_delay, bool))

        return node

    def from_xml(self, node):
        """reads xml"""
        if node.tag == "step-option":
            self.index = safe_read(node, "index", int, -1)
            self.repeat_count = safe_read(node, "repeat-count", int, 1)
            self.mode = SequenceRepeatMode.fromString(safe_read(node, "mode", str, "normal"))
            self.repeat_min_delay = safe_read(node, "repeat-min", int, 250)
            self.repeat_max_delay = safe_read(node, "repeat-max", int, 250)
            self.autorelease_min_delay = safe_read(node, "autorelease-min", int, 250)
            self.autorelease_max_delay = safe_read(node, "autorelease-max", int, 250)
            self.randomize_delay = safe_read(node, "randomize-delay", bool, False)
            self.randomize_autorelease_delay = safe_read(node, "randomize-autorelease", bool, False)


class StepOptionsWidget(QtWidgets.QWidget):
    """widget to manage step options"""

    def __init__(self, action_data: SequenceContainer, options: StepOptions, parent=None):  # noqa: F821
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.options = options
        self.action_data = action_data

        modes = [
            ("No Repeat", SequenceRepeatMode.Normal),  # no repeat (default)
            ("Repeat (fixed)", SequenceRepeatMode.Loop),  # repeat fixed count
            ("Repeat (random)", SequenceRepeatMode.Random),  # random repeat
        ]

        margin = 0

        self.repeat_mode_widget = gremlin.ui.ui_common.QDataComboBox(source=modes, value=options.mode, auto_adjust=True, callback=self._handle_mode_changed)

        self.repeat_mode_widget.autoSize()

        self.repeat_count_widget = gremlin.ui.ui_common.QIntLineEdit(
            value=options.repeat_count,
            min_range=2,
            callback=self._handle_repeat_count_changed,
        )

        self.container_repeat_widget = gremlin.ui.ui_common.getHContainer(self.repeat_count_widget, "Count:", widget_only=True)

        self.repeat_delay_min_widget = gremlin.ui.ui_common.QDelayWidget(
            value=options.repeat_min_delay,
            callback=self._handle_repeat_delay_min_changed,
            show_shortcuts=False,
            label="Repeat delay (ms) Min:",
            tooltip="Minimum time between repetitions in milliseconds",
        )
        self.repeat_delay_max_widget = gremlin.ui.ui_common.QDelayWidget(
            value=options.repeat_max_delay,
            callback=self._handle_repeat_delay_max_changed,
            show_shortcuts=False,
            label="Max:",
            tooltip="Maximum time between repetitions in milliseconds",
        )

        self.autorelease_delay_min_widget = gremlin.ui.ui_common.QDelayWidget(
            value=options.autorelease_min_delay,
            callback=self._handle_autorelease_delay_min_changed,
            show_shortcuts=False,
            label="Autorelease delay (ms) Min:",
            tooltip="Minimum time betweeen a press and release for each repeat in milliseconds",
        )
        self.autorelease_delay_max_widget = gremlin.ui.ui_common.QDelayWidget(
            value=options.autorelease_max_delay,
            callback=self._handle_autorelease_delay_max_changed,
            show_shortcuts=False,
            label="Max:",
            tooltip="Maximum time betweeen a press and release for each repeat in milliseconds",
        )

        self.randomize_delay_widget = gremlin.ui.ui_common.QDataCheckbox(
            value=self.options.randomize_delay, label="Randomize", callback=self._handle_randomize_delay_changed
        )

        self.randomize_autorelease_delay_widget = gremlin.ui.ui_common.QDataCheckbox(
            value=self.options.randomize_autorelease_delay, label="Randomize", callback=self._handle_randomize_autorelease_delay_changed
        )

        self.container_delay_widget = gremlin.ui.ui_common.getHContainer(
            [
                self.randomize_delay_widget,
                "|",
                self.repeat_delay_min_widget,
                self.repeat_delay_max_widget,
            ],
            widget_only=True,
            left_margin=margin,
        )

        self.container_autorelease_delay_widget = gremlin.ui.ui_common.getHContainer(
            [
                self.randomize_autorelease_delay_widget,
                "|",
                self.autorelease_delay_min_widget,
                self.autorelease_delay_max_widget,
            ],
            widget_only=True,
            left_margin=margin,
        )

        widgets = [
            "Repeat Mode:",
            self.repeat_mode_widget,
            self.container_repeat_widget,
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.main_layout.addWidget(widget)

        self.main_layout.addWidget(self.container_delay_widget)
        self.main_layout.addWidget(self.container_autorelease_delay_widget)

        self._update_widgets()

    def _update_widgets(self):
        """updates widget setup based on options selected"""
        repeat_visible = False
        delay_visible = False
        repeat_max_visible = False
        auto_max_visible = False

        match self.options.mode:
            case "normal":
                pass
            case "repeat":
                repeat_visible = True
                delay_visible = True
            case "random":
                repeat_visible = True
                delay_visible = True

        self.container_repeat_widget.setVisible(repeat_visible)

        if self.options.randomize_delay:
            self.repeat_delay_min_widget.setLabel("Repeat delay (ms) Min:")
            repeat_max_visible = True
        else:
            self.repeat_delay_min_widget.setLabel("Repeat delay (ms):")

        if self.options.randomize_autorelease_delay:
            self.autorelease_delay_min_widget.setLabel("Autorelease delay (ms) Min:")
            auto_max_visible = True
        else:
            self.autorelease_delay_min_widget.setLabel("Autorelease delay (ms):")

        self.container_delay_widget.setVisible(delay_visible)
        self.container_autorelease_delay_widget.setVisible(delay_visible)
        self.repeat_delay_max_widget.setVisible(repeat_max_visible)
        self.autorelease_delay_max_widget.setVisible(auto_max_visible)

    @QtCore.Slot(int)
    def _handle_repeat_count_changed(self, value: int):
        self.options.repeat_count = value

    @QtCore.Slot()
    def _handle_mode_changed(self, data):
        self.options.mode = data
        self._update_widgets()

    @QtCore.Slot(float)
    def _handle_repeat_delay_min_changed(self, value):
        self.options.repeat_min_delay = value

    @QtCore.Slot(float)
    def _handle_repeat_delay_max_changed(self, value):
        self.options.repeat_max_delay = value

    @QtCore.Slot(float)
    def _handle_autorelease_delay_min_changed(self, value):
        self.options.repeat_min_delay = value

    @QtCore.Slot(float)
    def _handle_autorelease_delay_max_changed(self, value):
        self.options.repeat_max_delay = value

    @QtCore.Slot(bool)
    def _handle_randomize_delay_changed(self, checked: bool):
        self.options.randomize_delay = checked
        self._update_widgets()

    @QtCore.Slot(bool)
    def _handle_randomize_autorelease_delay_changed(self, checked: bool):
        self.options.randomize_autorelease_delay = checked
        self._update_widgets()


class SequenceContainerWidget(AbstractContainerWidget):
    """Container which holds a sequence of actions."""

    def __init__(self, container, parent=None):
        """Creates a new instance.

        :param container:  the container represented by this widget
        :param parent:   the parent of this widget
        """
        super().__init__(container, parent)

    def _create(self, container):
        self.container: SequenceContainer = container

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return

        self._lock = threading.Lock()

        # list of step widgets in the UI
        self.step_widgets = []

        self.widget_layout = QtWidgets.QHBoxLayout()

        self._warning_widget = gremlin.ui.ui_common.QWarningWidget()

        self.container.create_or_delete_virtual_button()
        self.action_selector = ActionSelector(self.container.get_input_type(), self.container.input_item)
        self.action_selector.inputItem = self.container.input_item
        self.action_selector.action_added.connect(self._add_step)
        self.action_selector.add_button.setText("Add Step")
        self.action_selector.action_paste.connect(self._paste_action)

        self.widget_layout.addWidget(self.action_selector)

        self._trigger_widget = gremlin.ui.ui_common.QExecuteWidget(
            self.container.exec_on_press,
            self.container.exec_on_release,
            press_callback=self._execute_on_press_changed,
            release_callback=self._execute_on_release_changed,
        )

        modes = [
            ("Normal (run once)", SequenceMode.Normal),  # normal execution
            ("Toggle", SequenceMode.Toggle),  # toggle execution
            ("Loop (while pressed)", SequenceMode.Loop),  # loop mode - runs while the input is triggered
            ("Wiggle (random)", SequenceMode.Wiggle),  # wiggle execution
            ("Step", SequenceMode.Step),  # execute one step at a time on each trigger
        ]

        widgets = []
        for mode, data in modes:
            rb = gremlin.ui.ui_common.QDataRadioButton(label=mode, data=data, value=self.container.mode == data, callbackEx=self._handle_mode_changed)
            widgets.append(rb)

        self._wiggle_count_enabled_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Random Step Count",
            callback=self._handle_wiggle_count_enabled_change,
            value=self.container.wiggle_count_enabled,
            tooltip="Enable the wiggle count mode to randomize how many steps execute per sequence trigger.",
        )

        widget = gremlin.ui.ui_common.getHContainer(widgets, "Execution mode:", widget_only=True)
        self.action_layout.addWidget(widget)

        # normal mode delay options

        self._normal_step_delay_widget = gremlin.ui.ui_common.QDelayWidget(
            value=self.container.normal_exec_delay, callback=self._handle_normal_step_delay_change
        )

        self._normal_step_autorelease_delay = gremlin.ui.ui_common.QDelayWidget(
            value=self.container.normal_autorelease_delay, callback=self._handle_autorelease_delay_change
        )

        g1 = gremlin.ui.ui_common.getGridContainer(
            self._normal_step_delay_widget,
            "Step Interval Delay (ms):",
            tooltip="Time (ms) between steps.",
            widget_only=True,
        )

        g2 = gremlin.ui.ui_common.getGridContainer(
            self._normal_step_autorelease_delay,
            "Step Autorelease delay (ms):",
            tooltip="Time (ms) between a press and release event sent to individual steps",
            widget_only=True,
        )

        widgets = [g1, g2]

        self.container_normal_options = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
        gremlin.ui.ui_common.synchronize_grids(widgets)

        self.action_layout.addWidget(self.container_normal_options)

        # stepped mode options
        widgets = []

        self._stepped_exec_reset_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Reset step execution on profile start",
            callback=self._handle_step_reset_change,
            value=self.container.stepped_exec_reset,
            tooltip="If enabled, stepped execution will reset to the first step when the profile starts. Otherwise, it will continue from the last step and loop around.",
        )

        widgets.append(self._stepped_exec_reset_widget)
        self.container_stepped_options = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
        self.action_layout.addWidget(self.container_stepped_options)

        # wiggle mode options

        grids = []

        self._wiggle_step_delay_widget = gremlin.ui.ui_common.QDelayWidget(
            value=self.container.wiggle_step_delay, callback=self._handle_wiggle_step_delay_change
        )

        grids.append(
            gremlin.ui.ui_common.getGridContainer(
                self._wiggle_step_delay_widget,
                label="Step Interval Delay (ms):",
                tooltip="Time (ms) between wiggle steps. Set to 0 to disable.\nIf randomize delay is enabled, the interval will use the delay min/max values instead.",
                widget_only=True,
            )
        )

        self._wiggle_exec_delay_widget = gremlin.ui.ui_common.QDelayWidget(
            value=self.container.wiggle_exec_delay, callback=self._handle_wiggle_exec_delay_change
        )

        grids.append(
            gremlin.ui.ui_common.getGridContainer(
                self._wiggle_exec_delay_widget,
                label="Step Autorelease Delay (ms):",
                tooltip="Time (ms) between a press and release event sent to individual wiggle steps",
                widget_only=True,
            )
        )

        self._wiggle_count_min_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=1,
            max_range=1000,
            tooltip="Minimum number of steps to execute in wiggle mode. 0 to disable.<br>If set to 5, up to 5 wiggle steps will run and wiggle will stop after 5.",
            callback=self._handle_wiggle_count_min_change,
            value=self.container.wiggle_count_min,
        )

        self._wiggle_count_max_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=1,
            max_range=1000,
            tooltip="Max number of steps to execute in wiggle mode. 0 to disable.<br>If set to 5, up to 5 wiggle steps will run and wiggle will stop after 5.",
            callback=self._handle_wiggle_count_max_change,
            value=self.container.wiggle_count_max,
        )

        self._wiggle_min_delay_widget = gremlin.ui.ui_common.QDelayWidget(
            5000, callback=self._handle_min_delay_change, invalid_callback=self._handle_min_invalid_value, validation_callback=self._handle_min_validation
        )

        grids.append(
            gremlin.ui.ui_common.getGridContainer(
                self._wiggle_min_delay_widget,
                label="Min Delay (ms):",
                tooltip="Time (ms) between steps, lower bound",
                widget_only=True,
            )
        )

        self._wiggle_max_delay_widget = gremlin.ui.ui_common.QDelayWidget(
            5000, callback=self._handle_max_delay_change, invalid_callback=self._handle_max_invalid_value, validation_callback=self._handle_max_validation
        )

        grids.append(
            gremlin.ui.ui_common.getGridContainer(
                self._wiggle_max_delay_widget,
                label="Max Delay (ms):",
                tooltip="Time (ms) between steps, upper bound",
                widget_only=True,
            )
        )

        # set value separately to avoid trigger of validation callback
        self._wiggle_min_delay_widget.setValue(self.container.wiggle_min_delay, False)
        self._wiggle_max_delay_widget.setValue(self.container.wiggle_max_delay, False)

        self._wiggle_random_widget = QtWidgets.QCheckBox("Random Delay")
        self._wiggle_random_widget.setToolTip("When enabled, the delay between steps will be randomized betweeen min and max delays")
        self._wiggle_random_widget.setChecked(self.container.wiggle_random)
        self._wiggle_random_widget.clicked.connect(self._handle_wiggle_random_change)

        self._wiggle_steps_widget = QtWidgets.QCheckBox("Randomize Steps")
        self._wiggle_steps_widget.setToolTip("When enabled, steps will execute randomly like a pick list when in wiggle mode")
        self._wiggle_steps_widget.setChecked(self.container.wiggle_randomize_steps)
        self._wiggle_steps_widget.clicked.connect(self._handle_wiggle_random_steps_changed)

        self.container_wiggle_count_max_widget = gremlin.ui.ui_common.getHContainer(self._wiggle_count_max_widget, "Max", widget_only=True)

        self.container_wiggle_count_widget = gremlin.ui.ui_common.getHContainer(
            [
                "Wiggle Step Count Min: ",
                self._wiggle_count_min_widget,
                self.container_wiggle_count_max_widget,
            ],
            widget_only=True,
        )

        widgets = [self._wiggle_random_widget, self._wiggle_steps_widget, self._wiggle_count_enabled_widget]

        self.container_wiggle_options_widget = gremlin.ui.ui_common.getHContainer(widgets, "Wiggle mode:", widget_only=True)
        self.action_layout.addWidget(self.container_wiggle_options_widget)

        widgets = []
        widgets.extend(grids)

        widgets.append(self.container_wiggle_count_widget)

        self.container_wiggle_options = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

        gremlin.ui.ui_common.synchronize_grids(grids)

        self.action_layout.addWidget(self.container_wiggle_options)

        self.resume_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Resume at last step",
            value=self.container.resume_mode,
            tooltip="If enabled, the sequence will resume at the last step it stopped at.",
            callback=self._handle_resume_mode_change,
        )

        self.info_widget = gremlin.ui.ui_common.QInfoBox(hide_key="sequence_container")

        widget = gremlin.ui.ui_common.getHContainer([self.resume_widget], widget_only=True)
        self.action_layout.addWidget(widget)

        # sync option
        sync_modes = [SyncMode.Ignore, SyncMode.Input]
        sync_widget = gremlin.ui.ui_common.QSyncModeWidget(
            mode=self.container.sync_mode, label="State on profile start:", callback=self._handle_sync_changed, sync_modes=sync_modes
        )

        self.action_layout.addWidget(sync_widget)

        self.action_layout.addWidget(self.info_widget)

        self.action_layout.addWidget(self._warning_widget)
        self.action_layout.addWidget(self._trigger_widget)

        self.action_layout.addLayout(self.widget_layout)
        self.step_container, self.step_layout = gremlin.ui.ui_common.getVContainer()
        self.action_layout.addWidget(self.step_container)

        # hook UI updates when models change
        self.container.action_sets.addCallback(self._handle_steps_changed)

        self._update_steps()
        self._update_widgets()

    def _handle_steps_changed(self, data):
        InvokeUiMethod(self._update_steps)
        self.container_modified.emit()

    def _update_steps(self):
        """redraws action steps in the sequence - each step is an action set"""

        # cleanup action widgets
        for widget in self._widget_map.values():
            widget.model.data_changed.disconnect(self.container_modified.emit)
            gremlin.util.delete_widget(widget)
        self._widget_map.clear()

        # cleanup step widgets
        for widget in self.step_widgets:
            clear_layout(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

        self.step_widgets.clear()

        # Insert action widgets
        for index, action_set in enumerate(self.container.action_sets):
            # options widget
            size = 24

            options: StepOptions = self.container.getOptions(index)
            options_widget = StepOptionsWidget(self.container, options)
            step_widget = gremlin.ui.ui_common.QFrameBox(f"<b>Step {index + 1}</b>")

            remove_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
                callback=self._handle_delete_step, tooltip=f"Delete Step [{index + 1}]", data=action_set
            )
            remove_widget.setFixedSize(size, size)

            step_up_widget = gremlin.ui.ui_common.Buttons.getMoveUpWidget(callback=self._handle_move_step_up, data=action_set) if index > 0 else None
            if step_up_widget:
                step_up_widget.setFixedSize(size, size)

            step_down_widget = (
                gremlin.ui.ui_common.Buttons.getMoveDownWidget(callback=self._handle_move_step_down, data=action_set)
                if index < len(self.container.action_sets) - 1
                else None
            )
            if step_down_widget:
                step_down_widget.setFixedSize(size, size)

            step_top_widget = gremlin.ui.ui_common.Buttons.getMoveTopWidget(callback=self._handle_move_step_top, data=action_set) if index > 0 else None
            if step_top_widget:
                step_top_widget.setFixedSize(size, size)

            step_bottom_widget = (
                gremlin.ui.ui_common.Buttons.getMoveBottomWidget(callback=self._handle_move_step_bottom, data=action_set)
                if index < len(self.container.action_sets) - 1
                else None
            )
            if step_bottom_widget:
                step_bottom_widget.setFixedSize(size, size)

            move_container = gremlin.ui.ui_common.getHContainer(
                [step_up_widget, step_down_widget, step_top_widget, step_bottom_widget, remove_widget], widget_only=True
            )

            widgets = [
                step_widget,
                # step_container,
                options_widget,
                "||",
                move_container,
            ]

            container_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
            css = f"""
                .QWidget {{
                    background-color: {gremlin.ui.ui_common.Color.headerBarBackgroundColor()};
                    border-radius: 8px;
                  }}

            """
            container_widget.setStyleSheet(css)
            container_widget.setContentsMargins(4, 4, 4, 4)

            # self.step_layout.addWidget(header_widget)
            self.step_layout.addWidget(container_widget)

            action_set = self.container.action_sets[index]
            action_set_widget = self._create_action_set_widget(action_set, "Step", ContainerViewTypes.Action)
            self.step_layout.addWidget(action_set_widget)
            action_set_widget.redraw()
            action_set_widget.model.data_changed.connect(self.container_modified.emit)

            self.step_widgets.append(container_widget)

            self._widget_map[action_set] = action_set_widget

    def _handle_delete_step(self, widget):
        action_set: ActionSet = widget.data  # action set is stored in the button data
        ui = gremlin.shared_state.ui
        result = gremlin.ui.ui_common.ConfirmBox(prompt=f"Delete step [{action_set.index}]?", parent=ui)
        if result:
            self.container.action_sets.remove(action_set)

    def _handle_move_step_up(self, widget):
        # moves an action set up
        action_set: ActionSet = widget.data  # action set is stored in the button data
        index = self.container.action_sets.indexOf(action_set)
        if index > 0:
            self.container.action_sets.pushSuspend()
            self.container.action_sets[index], self.container.action_sets[index - 1] = self.container.action_sets[index - 1], self.container.action_sets[index]
            self.container.action_sets.popSuspend()

    def _handle_move_step_down(self, widget):
        # moves an action set down
        action_set: ActionSet = widget.data  # action set is stored in the button data
        index = self.container.action_sets.indexOf(action_set)
        if index < len(self.container.action_sets) - 1:
            self.container.action_sets.pushSuspend()
            self.container.action_sets[index], self.container.action_sets[index + 1] = self.container.action_sets[index + 1], self.container.action_sets[index]
            self.container.action_sets.popSuspend()

    def _handle_move_step_top(self, widget):
        # moves an action set to the top
        action_set: ActionSet = widget.data  # action set is stored in the button data
        index = self.container.action_sets.indexOf(action_set)
        if index > 0:
            self.container.action_sets.pushSuspend()
            self.container.action_sets.insert(0, self.container.action_sets.pop(index))
            self.container.action_sets.popSuspend()

    def _handle_move_step_bottom(self, widget):
        # moves an action set to the bottom
        action_set: ActionSet = widget.data  # action set is stored in the button data
        index = self.container.action_sets.indexOf(action_set)
        if index < len(self.container.action_sets) - 1:
            self.container.action_sets.pushSuspend()
            self.container.action_sets.append(self.container.action_sets.pop(index))
            self.container.action_sets.popSuspend()

    def _handle_sync_changed(self, mode):
        self.container.sync_mode = mode

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        self.container.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        self.container.exec_on_release = checked

    @QtCore.Slot(bool)
    def _handle_wiggle_mode_change(self, checked: bool):
        self.container.wiggle_mode = checked
        self._update_widgets()

    @QtCore.Slot(bool)
    def _handle_wiggle_random_change(self, checked: bool):
        self.container.wiggle_random = checked
        self._update_widgets()

    @QtCore.Slot(bool)
    def _handle_wiggle_random_steps_changed(self, checked: bool):
        self.container.wiggle_randomize_steps = checked

    def _handle_min_validation(self, value) -> bool:
        if value < 0:
            self.setWarning("Delay must be positive")
            return False
        if self.container.wiggle_random and value > self.container.wiggle_max_delay:
            self.setWarning("Minimnum delay must be less or equal to the maximum delay.")
            return False

        return True  # valid

    def _handle_max_validation(self, value) -> bool:
        if value < 0:
            self.setWarning("Delay must be positive")
            return False
        if self.container.wiggle_random and value < self.container.wiggle_min_delay:
            self.setWarning("Maximum delay must be greater or equal to the minimum delay.")
            return False

        return True  # valid

    @QtCore.Slot(bool)
    def _handle_mode_changed(self, widget, checked):
        mode = widget.data
        self.container.mode = mode
        self._update_widgets()

    @QtCore.Slot(bool)
    def wiggle_count_enabled(self, checked: bool):
        self.container.wiggle_count_enabled = checked
        self._update_widgets()

    @QtCore.Slot(int)
    def _handle_min_delay_change(self, value):
        # avoid re-entrant callbacks
        self.container.wiggle_min_delay = value
        self.setWarning()

    @QtCore.Slot(int)
    def _handle_max_delay_change(self, value):
        self.container.wiggle_max_delay = value
        self.setWarning()

    @QtCore.Slot(bool)
    def _handle_resume_mode_change(self, value):
        self.container.resume_mode = value
        self.setWarning()

    @QtCore.Slot()
    def _handle_min_invalid_value(self):
        self.setWarning("Invalid min delay value")

    @QtCore.Slot()
    def _handle_max_invalid_value(self):
        self.setWarning("Invalid max delay value")

    @QtCore.Slot(bool)
    def _handle_wiggle_count_enabled_change(self, checked: bool):
        self.container.wiggle_count_enabled = checked
        self._update_widgets()

    @QtCore.Slot(int)
    def _handle_wiggle_exec_delay_change(self, value):
        self.container.wiggle_exec_delay = value

    @QtCore.Slot(int)
    def _handle_normal_step_delay_change(self, value):
        self.container.normal_exec_delay = value

    @QtCore.Slot(int)
    def _handle_wiggle_step_delay_change(self, value):
        self.container.wiggle_step_delay = value

    @QtCore.Slot(bool)
    def _handle_step_reset_change(self, checked: bool):
        self.container.stepped_exec_reset = checked

    @QtCore.Slot(int)
    def _handle_normal_exec_delay_change(self, value):
        self.container.normal_exec_delay = value

    @QtCore.Slot(int)
    def _handle_autorelease_delay_change(self, value):
        self.container.normal_autorelease_delay = value

    @QtCore.Slot(int)
    def _handle_wiggle_count_min_change(self, value):
        max_value = self.container.wiggle_count_max
        min_value = self._wiggle_count_max_widget.minimum()

        if value > max_value:
            # bump max
            self._update_count_widget(self._wiggle_count_max_widget, min_value=value, value=value)
            self.container.wiggle_count_max = value

        elif min_value > value:
            self._update_count_widget(self._wiggle_count_max_widget, min_value=value)

        self.container.wiggle_count_min = value
        self._update_widgets()

    @QtCore.Slot(int)
    def _handle_wiggle_count_max_change(self, value):
        min_value = self.container.wiggle_count_min
        if value < min_value:
            value = min_value
            self._update_count_widget(self._wiggle_count_max_widget, min_value=value, value=value)
        self.container.wiggle_count_max = value

    def _update_count_widget(self, widget, value=None, min_value=None, max_value=None):
        if Shiboken.is_valid(widget):
            with QtCore.QSignalBlocker(widget):
                if max_value is not None:
                    widget.setMaximum(max_value)
                if min_value is not None:
                    widget.setMinimum(min_value)
                if value is not None:
                    widget.setValue(value)

    def _update_widgets(self):
        mode = self.container.mode
        wiggle_enabled = mode == SequenceMode.Wiggle
        stepped_enabled = mode == SequenceMode.Step
        normal_enabled = mode == SequenceMode.Normal
        resume_enabled = mode != SequenceMode.Normal and mode != SequenceMode.Step
        self._wiggle_min_delay_widget.setVisible(wiggle_enabled)

        self.container_normal_options.setVisible(normal_enabled)

        self.container_wiggle_options.setVisible(wiggle_enabled)

        self.container_wiggle_options_widget.setVisible(wiggle_enabled)

        self.container_wiggle_options.setVisible(wiggle_enabled)

        max_enabled = wiggle_enabled and self.container.wiggle_random
        self._wiggle_max_delay_widget.setVisible(max_enabled)

        if wiggle_enabled:
            self._wiggle_random_widget.setVisible(wiggle_enabled)
            self._wiggle_steps_widget.setVisible(wiggle_enabled)
            self._wiggle_exec_delay_widget.setVisible(wiggle_enabled)
            count_enabled = self.container.wiggle_count_enabled
            self.container_wiggle_count_widget.setVisible(count_enabled)
            self.container_wiggle_count_max_widget.setVisible(count_enabled)

        self.resume_widget.setVisible(resume_enabled)  # resume can only be used in a loop mode - so wiggle or toggle
        self.container_stepped_options.setVisible(stepped_enabled)

        visible = bool(self._warning_widget.text())
        self._warning_widget.setVisible(visible)

        # info box based on modes
        match self.container.mode:
            case SequenceMode.Wiggle:
                msg = """The sequence will randomly loop while the input is triggered.
<br>In wiggle mode, the timing between steps, how long each step runs and the order of the steps can be randomly generated based on the options selected."""
            case SequenceMode.Toggle:
                msg = "The sequence will loop.  The first trigger with enable the sequence.  It will run continuously in a loop until the second trigger is received."
            case SequenceMode.Loop:
                msg = "The sequence will loop while the input is triggered."
            case SequenceMode.Normal:
                msg = (
                    "The sequence will run once when the input is triggered.<br>If the sequence is triggered while it's still running, the trigger is ignored."
                )
            case SequenceMode.Step:
                msg = "The sequence will execute one step at a time on each trigger."

        if resume_enabled and self.container.resume_mode:
            if msg:
                msg += "<br>"
            msg += "Resume mode is enabled: the next sequence activation will continue at the step where it last stopped."

        self.info_widget.setText(msg)

    def setWarning(self, text=None):
        """sets warning display - send None to clear / hide"""
        visible = bool(text)
        self._warning_widget.setText(text)
        self._warning_widget.setVisible(visible)

    def _create_condition_ui(self):
        if self.container.action_sets:
            for i, action in enumerate(self.container.action_sets):
                widget = self._create_action_set_widget(self.container.action_sets[i], f"Step {i:d}", ContainerViewTypes.Conditions)
                self.activation_condition_layout.addWidget(widget)
                widget.redraw()
                widget.model.data_changed.connect(self.container_modified.emit)

    def _add_step(self, action_name: str = None):
        """Adds a new step to the sequence container. A step is an action set.

        :param action_name: the name of the action to add to the new step, if any
        """
        assert isinstance(action_name, str), "Action name must be a string and provided"
        action_set = gremlin.input_item.ActionSet()
        self.container.action_sets.pushSuspend()
        self.container.add_action_set(action_set)
        if action_name:
            self._add_action(action_name, action_set)
        self.container.action_sets.popSuspend()

    def _remove_step(self, index: int):
        """Removes a step from the sequence container.

        :param index: the index of the step to remove
        """
        assert isinstance(index, int) and index >= 0, "Index must be an integer greater than or equal to 0"
        if self.container.action_sets.itemAt(index) is None:
            raise IndexError(f"No action set found at index {index}")
        self.container.remove_action_set(index)

    def _add_action(self, action_name: str, action_set: gremlin.input_item.ActionSet):
        """Adds a new action to the container.

        :param action_name: the name of the action to add
        :param action_set: the action set to which the action should be added
        """
        assert isinstance(action_name, str), "Action name must be a string"
        assert isinstance(action_set, gremlin.input_item.ActionSet), "Invalid action set"
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.container)
        action_set.add_action(action_item)

    def _remove_action(self, action: AbstractAction, delete=True):
        """Removes an action from the specified action set.

        :param action: the action to remove
        :param delete: if true, deletes the action from the profile
        """
        assert isinstance(action, AbstractAction), "Invalid action"
        action_set = action.parent
        if action_set is None:
            raise ValueError("Action item does not belong to any action set")
        action_set.remove_action(action, delete=delete)

    def _paste_action(self, action: AbstractAction):
        """pastes an action"""

        assert isinstance(action, AbstractAction), "Invalid action"
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.container)
        self.container.add_action(action_item)
        self.container_modified.emit()

    def _handle_interaction(self, widget, action: AbstractAction):
        """Handles interaction icons being pressed on the individual actions.

        :param widget: the action widget on which an action was invoked
        :param action: the action being invoked
        """
        # Find the index of the widget that gets modified
        index = self._get_widget_index(widget)

        if index == -1:
            syslog.warning("Unable to find widget specified for interaction, not doing anything.")
            return

        # Perform action
        match action:
            case Interactions.Up:
                if index > 0:
                    self.container.action_sets[index], self.container.action_sets[index - 1] = (
                        self.container.action_sets[index - 1],
                        self.container.action_sets[index],
                    )
            case Interactions.Down:
                if index < len(self.container.action_sets) - 1:
                    self.container.action_sets[index], self.container.action_sets[index + 1] = (
                        self.container.action_sets[index + 1],
                        self.container.action_sets[index],
                    )
            case Interactions.Delete:
                del self.container.action_sets[index]
            case _:
                return
        if Shiboken.isValid(self):
            self.container_modified.emit()
        self._update_steps()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        return f"Sequence: {' -> '.join([', '.join([a.name for a in actions]) for actions in self.container.action_sets])}"

class SequenceContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):
    def __init__(self, container: SequenceContainer, parent=None):  # noqa: F821
        super().__init__(container, parent)

        self.container = container

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        for cond in container.activation_condition.conditions:
            if isinstance(cond, gremlin.input_item.BaseInputActionCondition):
                if cond.comparison == "press":
                    self.switch_on_press = True

        config = gremlin.config.Configuration()
        self._verbose = config.verbose_mode_container or config.verbose_mode_sequence
        self._verbose_extra = self._verbose and config.verbose_mode_extra

        self._hook_mode_change = False
        self.action_data._thread = None
        self.action_data._is_running = False
        self._started = False

        self._current_step = None  # tracks the next step to execute

    def profile_start(self):
        self.action_data._is_running = False

        config = gremlin.config.Configuration()
        self._verbose = config.verbose_mode_container or config.verbose_mode_sequence
        self._verbose_extra = self._verbose and config.verbose_mode_extra
        gs = GlobalSequence()
        gs.sequence_count = 0

        # stepped mode current step
        if self.container.stepped_exec_reset:
            self._current_step = None

        config = gremlin.config.Configuration()
        if not config.mode_change_aborts_sequence:
            # only hook if mode change while running a sequence is not allowed
            self._hook_mode_change = True
            eh = gremlin.event_handler.EventHandler()
            eh.registerModeChangeHook(self.id, self._mode_change_allowed_callback)

    def profile_started(self):
        # sync input
        if self._started:
            return
        self._started = True
        super().profile_started()
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        input_type = self.action_data.get_input_type()
        match self.action_data.sync_mode:
            case SyncMode.Input:
                match input_type:
                    case InputType.JoystickHat:
                        pass
                    case InputType.JoystickAxis:
                        pass
                    case InputType.JoystickButton:
                        # sync and invert as needed
                        is_pressed = gremlin.joystick_handling.get_button(device_guid, input_id)

                        # construct the input event to sync
                        event = gremlin.event_handler.Event(
                            event_type=input_type,
                            identifier=input_id,
                            value=is_pressed,
                            is_pressed=is_pressed,
                            device_guid=device_guid,
                        )

                        if self._verbose:
                            syslog.info(f"SEQUENCE: auto trigger due to input sync: pressed: [{is_pressed}]")
                        self.process_event(event, is_pressed)

    def _mode_change_allowed_callback(self, id: str) -> bool:
        if id == self.id:
            # ours
            result = not self.action_data._is_running
            # syslog.info(f"MODE CHANGE CHECK: sequence: [{self.id}] mode change allowed: [{result}]")
            return result  # false if sequence is running
        return True  # allowed

    def profile_stop(self):
        # stop wiggling
        self.stop_wiggle()
        self.stop_normal()

        if self._hook_mode_change:
            eh = gremlin.event_handler.EventHandler()
            eh.unregisterModeChangeHook(self.id)
            self._hook_mode_change = False

        self._started = False

    def profile_mode_changed(self, mode: str):
        """called when the runtime mode changes"""

        # kill any executing timers on mode change
        if gremlin.config.Configuration().macro_mode_affinity:
            if self.action_data._is_running:
                if self._verbose:
                    syslog.info("SEQUENCE: affinity: stop sequence runner due to mode change")
                self.action_data._is_running = False
                if self.action_data._thread.is_alive():
                    self.action_data._thread.join()
                self.action_data._thread = None

        # reset
        self.action_data.last_step = None

    def start_wiggle(self):
        """starts the wiggle process"""

        gs = GlobalSequence()
        if gs.canExecute():
            if not self.action_data._is_running:
                self.action_data._is_running = True
                self.action_data._thread = threading.Thread(target=self._wiggle_runner)
                self.action_data._thread.name = "wiggle runner"
                # increase concurrency count
                gs.pushSequence()
                self.action_data._thread.start()
                if self._verbose:
                    syslog.info(f"SEQUENCE: start wiggle sequence runner: concurrency: [{gs.sequence_count}]")

        else:
            syslog.error("SEQUENCE: exceeded concurrent sequence limit")

    def stop_wiggle(self):
        """stops the wiggle process"""
        if self.action_data._is_running:
            if self._verbose:
                syslog.info("SEQUENCE: stop wiggle sequence runner")
            self.action_data._is_running = False
            self.action_data._thread.join()
            self.action_data._thread = None
            # reduce concurrency count
            gs = GlobalSequence()
            gs.popSequence()

    def start_normal(self):
        """starts the normal process"""
        gs = GlobalSequence()
        if gs.canExecute():
            if not self.action_data._is_running:
                self.action_data._is_running = True
                self.action_data._thread = threading.Thread(target=self._normal_runner)
                self.action_data._thread.name = "sequence runner"
                # increase concurrency count
                gs.pushSequence()
                self.action_data._thread.start()
                if self._verbose:
                    syslog.info(f"SEQUENCE: start sequence runner: concurrency: [{gs.sequence_count}]")
        else:
            syslog.error("SEQUENCE: exceeded concurrent sequence limit")

    def stop_normal(self):
        """stops the normal process"""
        if self.action_data._is_running:
            if self._verbose:
                syslog.info("SEQUENCE: stop sequence runner")
            self.action_data._is_running = False
            if self.action_data._thread.is_alive():
                self.action_data._thread.join()
            # reduce concurrency count
            gs = GlobalSequence()
            gs.popSequence()
            self.action_data._thread = None

    def start_stepped(self):
        """starts the stepped process"""
        gs = GlobalSequence()
        if gs.canExecute():
            if not self.action_data._is_running:
                self.action_data._is_running = True
                self.action_data._thread = threading.Thread(target=self._stepped_runner)
                self.action_data._thread.name = "sequence runner"
                # increase concurrency count
                gs.pushSequence()
                self.action_data._thread.start()
                if self._verbose:
                    syslog.info(f"SEQUENCE: start sequence runner: concurrency: [{gs.sequence_count}]")
        else:
            syslog.error("SEQUENCE: exceeded concurrent sequence limit")

    def stop_stepped(self):
        """stops the stepped process"""
        if self.action_data._is_running:
            if self._verbose:
                syslog.info("SEQUENCE: stop sequence runner")
            self.action_data._is_running = False
            if self.action_data._thread.is_alive():
                self.action_data._thread.join()
            # reduce concurrency count
            gs = GlobalSequence()
            gs.popSequence()
            self.action_data._thread = None

    def process_event(self, event: gremlin.event_handler.Event, value: bool | gremlin.actions.Value, extra_data: dict = None) -> bool:
        if not self.valid:
            return False

        is_pressed = event.is_pressed
        mode = self.action_data.mode

        verbose = self._verbose

        if verbose:
            profile_mode = gremlin.shared_state.current_mode
            if self.action_data.comment:
                syslog.info(f"SEQUENCE EVENT: sequence {self.action_data.comment}")

        trigger = (is_pressed and self.container.exec_on_press) or (not is_pressed and self.container.exec_on_release)

        is_pressed = trigger
        is_running = self.action_data._is_running

        match mode:
            case SequenceMode.Wiggle:
                # wiggle mode runner
                if is_pressed and not is_running:
                    # run sequence in wiggle mode
                    if verbose:
                        syslog.info(f"SEQUENCE EVENT: wiggle mode: start - profile mode: {profile_mode}")
                    self.start_wiggle()

                elif not is_pressed and is_running:
                    # stop wiggle mode
                    if verbose:
                        syslog.info(f"SEQUENCE EVENT: wiggle mode: stop - profile mode: {profile_mode}")
                    self.stop_wiggle()
            case SequenceMode.Toggle:
                # toggle mode acts as a switch on the input trigger - first press = turn on, second press = turn off
                if is_pressed:
                    if is_running:
                        # stop loop
                        if verbose:
                            syslog.info(f"SEQUENCE EVENT: toggle mode: stop - profile mode: {profile_mode}")
                        self.stop_normal()
                    else:
                        # start loop
                        if verbose:
                            syslog.info(f"SEQUENCE EVENT: toggle mode: start - profile mode: {profile_mode}")
                        self.start_normal()
            case SequenceMode.Loop:
                # loop mode is on while the input is pressed, off when released
                if is_pressed and not is_running:
                    # run sequence in wiggle mode
                    if verbose:
                        syslog.info(f"SEQUENCE EVENT: loop mode: start - profile mode: {profile_mode}")
                    self.start_normal()

                elif not is_pressed and is_running:
                    # stop wiggle mode
                    if verbose:
                        syslog.info(f"SEQUENCE EVENT: loop mode: stop - profile mode: {profile_mode}")
                    self.stop_normal()

            case SequenceMode.Normal:
                # regular mode - run while pressed
                if is_pressed:
                    if not is_running:
                        # start sequence
                        if verbose:
                            syslog.info(f"SEQUENCE EVENT: normal mode: start - profile mode: {profile_mode}")
                        self.start_normal()
                    else:
                        if verbose:
                            syslog.info(f"SEQUENCE EVENT: normal mode: start ignored because prior sequence is still running  - profile mode: {profile_mode}")
                else:
                    if verbose:
                        syslog.info(f"SEQUENCE EVENT: normal mode: stop - profile mode: {profile_mode}")
                    self.stop_normal()

            case SequenceMode.Step:
                # step mode executes one step per trigger
                if is_pressed:
                    if verbose:
                        syslog.info(f"SEQUENCE EVENT: step mode: next step - profile mode: {profile_mode}")
                    self.start_stepped()
                else:
                    self.stop_stepped()

        return True

    def _normal_runner(self):

        event_press = gremlin.event_handler.Event(InputType.JoystickButton, 1, device_guid=gremlin.shared_state.fake_tab_guid, is_pressed=True)

        event_release = event_press.fake_button(False, True)

        nodes = [node for node in self.action_set_nodes]
        verbose = self._verbose
        verbose_extra = self._verbose_extra

        # no resume mode if running once
        resume = False if self.action_data.mode == "normal" else self.action_data.resume_mode

        if verbose:
            syslog.info(f"SEQUENCE NORMAL: [{self.id}] {self.action_data.mode} mode - runner start - resume mode: {resume}")

        if not nodes:
            # nothing to run
            self.action_data._is_running = False

            if verbose:
                syslog.info("SEQUENCE NORMAL: Trigger Functor: nothing to run")
            return
        index = None
        if resume:
            if verbose:
                syslog.info(f"Resume at step: {self.action_data.last_step}")
            index = self.action_data.last_step

        if index is None:
            # start at the top
            index = 0
        count = len(nodes)

        exec_delay_ms = self.container.normal_exec_delay
        exec_delay_s = exec_delay_ms / 1000
        autorelease_delay_ms = self.container.normal_autorelease_delay

        while self.action_data._is_running:
            node = nodes[index]
            options: StepOptions = self.action_data.getOptions(index)  # execution options for the step

            repeat_count = options.getCount()  # number of times to repeate
            if verbose:
                syslog.info(f"\tstep [{index}] exec start - repeat count: {repeat_count}")

            for repeat_index in range(repeat_count):
                if verbose:
                    syslog.info(f"\t\tTrigger press {index}/{repeat_index}")
                self._ec.execute_node(node, event_press, True, None)  # issue press
                # autorelease delay computation
                delay = options.getAutoreleaseDelay(autorelease_delay_ms)
                if delay > 0:
                    if verbose:
                        syslog.info(f"\t\tstep autorelease delay: {delay:03f}")
                    self._wait(delay)

                if verbose:
                    syslog.info(f"\t\tTrigger release {index}/{repeat_index}")
                self._ec.execute_node(node, event_release, False, None)  # issue release

                if not self.action_data._is_running:
                    break
                if repeat_index < repeat_count - 1:
                    # interval between repeat delay computation
                    delay = options.getDelay(exec_delay_ms)
                    if delay > 0:
                        if verbose:
                            syslog.info(f"\t\tstep repeat interval delay: {delay:03f}")
                        self._wait(delay)
                        if not self.action_data._is_running:
                            break

            # next node to run
            index += 1
            if index == count:
                if self.action_data.mode == "normal":
                    self.action_data._is_running = False

                    break  # only run once
                # loop
                index = 0
                if verbose_extra:
                    syslog.info("\tlooping sequence")

            self.action_data.last_step = index
            if exec_delay_ms > 0:
                if verbose:
                    syslog.info(f"\tstep interval delay: {exec_delay_s:03f}")
                self._wait(exec_delay_s)

        if verbose:
            syslog.info(f"SEQUENCE NORMAL STOP: {self.id}")
        self.action_data._is_running = False

    def _stepped_runner(self):
        """step mode runner thread"""
        event_press = gremlin.event_handler.Event(InputType.JoystickButton, 1, device_guid=gremlin.shared_state.fake_tab_guid, is_pressed=True)

        event_release = event_press.fake_button(False, True)

        nodes = [node for node in self.action_set_nodes]
        verbose = self._verbose
        verbose_extra = self._verbose_extra

        # no resume mode if running once
        resume = False if self.action_data.mode == "normal" else self.action_data.resume_mode

        if verbose:
            syslog.info(f"SEQUENCE STEPPED: [{self.id}] {self.action_data.mode} mode - runner start - resume mode: {resume}")

        if not nodes:
            # nothing to run
            if verbose:
                syslog.info("SEQUENCE STEPPED: Trigger Functor: nothing to run")
            return

        index = self._current_step
        if resume:
            if verbose:
                syslog.info(f"Resume at step: {self.action_data.last_step}")
            index = self.action_data.last_step

        if index is None:
            # start at the top
            index = 0
        count = len(nodes)
        if index >= count:
            # loop back to first step
            index = 0

        exec_delay_ms = self.container.normal_exec_delay
        autorelease_delay_ms = self.container.normal_autorelease_delay

        node = nodes[index]
        options: StepOptions = self.action_data.getOptions(index)  # execution options for the step

        repeat_count = options.getCount()  # number of times to repeat
        if verbose:
            syslog.info(f"\tstep [{index}] exec start - repeat count: {repeat_count}")

        for repeat_index in range(repeat_count):
            if verbose:
                syslog.info(f"\t\tTrigger press {index}/{repeat_index}")
            self._ec.execute_node(node, event_press, True, None)  # issue press
            # autorelease delay computation
            delay = options.getAutoreleaseDelay(autorelease_delay_ms)
            if delay > 0:
                if verbose:
                    syslog.info(f"\t\tstep autorelease delay: {delay:03f}")
                self._wait(delay)

            if verbose:
                syslog.info(f"\t\tTrigger release {index}/{repeat_index}")
            self._ec.execute_node(node, event_release, False, None)  # issue release

            if not self.action_data._is_running:
                break

            if repeat_index < repeat_count - 1:
                # interval between repeat delay computation
                delay = options.getDelay(exec_delay_ms)
                if delay > 0:
                    if verbose:
                        syslog.info(f"\t\tstep repeat interval delay: {delay:03f}")
                    self._wait(delay)
                    if not self.action_data._is_running:
                        break

        # next node to run
        index += 1

        self.action_data.last_step = index
        self._current_step = index

        if verbose:
            syslog.info(f"SEQUENCE STEPPED STOP: {self.id}")

    def _wiggle_runner(self):
        """wiggle mode runner thread"""
        event_press = gremlin.event_handler.Event(InputType.JoystickButton, 1, device_guid=gremlin.shared_state.fake_tab_guid, is_pressed=True)

        event_release = event_press.fake_button(False, True)

        nodes = [node for node in self.action_set_nodes]
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_sequence or config.verbose_mode_container
        verbose_extra = self._verbose_extra
        count_enabled = self.action_data.wiggle_count_enabled

        min_step_count = self.action_data.wiggle_count_min
        max_step_count = self.action_data.wiggle_count_max

        if count_enabled:
            if min_step_count == max_step_count:
                max_count = min_step_count
            else:
                max_count = random.randrange(min_step_count, max_step_count) if count_enabled else 0
        else:
            max_count = 0

        step_count = 0

        if not nodes:
            # nothing to run
            self.action_data._is_running = False
            if verbose:
                syslog.info("SEQUENCE WIGGLE: Trigger Functor: nothing to wiggle")
            return
        index = None
        if self.action_data.resume_mode:
            if verbose:
                syslog.info(f"Resume at step: {self.action_data.last_step}")
            index = self.action_data.last_step

        if index is None:
            # start at the top
            index = 0
        count = len(nodes)

        min_delay = self.container.wiggle_min_delay
        max_delay = self.container.wiggle_max_delay

        wiggle_random = self.container.wiggle_random and min_delay != max_delay
        wiggle_steps = self.container.wiggle_randomize_steps
        exec_delay_ms = self.container.wiggle_exec_delay
        _exec_delay_s = exec_delay_ms / 1000
        step_delay_ms = self.container.wiggle_step_delay
        step_delay_s = step_delay_ms / 1000
        if verbose:
            syslog.info(f"SEQUENCE RUNNER: (wiggle) starting wiggle with  min delay: [{min_delay}] max delay: [{max_delay}] random mode: [{wiggle_random}]")
            if max_count:
                if verbose:
                    syslog.info(f"SEQUENCE RUNNER: (wiggle) max step count [{max_count}]")

        if wiggle_steps:
            # pick a step at random
            index = random.randrange(0, count)
            if verbose:
                syslog.info(f"SEQUENCE RUNNER: (wiggle) randomize step: pick random next step: [{index}]")

        while self.action_data._is_running:
            if verbose:
                syslog.info(f"SEQUENCE RUNNER: (wiggle) - execute step index: [{index}]")
            node = nodes[index]
            options: StepOptions = self.action_data.getOptions(index)  # execution options for the step

            # handle single step repeats
            repeat_count = options.getCount()  # number of times to repeat
            for repeat_index in range(repeat_count):
                if verbose:
                    syslog.info(f"SEQUENCE RUNNER: (wiggle) Trigger Functor: loop [{repeat_index}] executes step [{index}] node: [{node.id}]")
                self._ec.execute_node(node, event_press, True, None)  # issue press
                # autorelease delay
                delay = options.getAutoreleaseDelay(exec_delay_ms)
                if delay > 0:
                    self._wait(delay)
                self._ec.execute_node(node, event_release, False, None)  # issue release

                # delay between steps
                if not self.action_data._is_running:
                    break
                if wiggle_random:
                    # random wiggle delay
                    delay = random.randrange(min_delay, max_delay) / 1000  # to seconds
                else:
                    # step delay
                    if repeat_index < repeat_count - 1:
                        delay = options.getDelay(exec_delay_ms)
                        if verbose_extra:
                            syslog.info(f"step repeat interval delay [{delay}]")
                        if delay > 0:
                            self._wait(delay)
                            if not self.action_data._is_running:
                                break

            if not self.action_data._is_running:
                break

            # handle delay between steps
            delay = random.randrange(min_delay, max_delay) / 1000 if wiggle_random else step_delay_s

            if delay > 0:
                if verbose:
                    syslog.info(f"SEQUENCE RUNNER: (wiggle) step interval delay (s) [{delay:0.3f}]")
                self._wait(delay)
                if not self.action_data._is_running:
                    break

            # next node to run
            if wiggle_steps:
                index = random.randrange(0, count)  # pick the next random step
                if verbose:
                    syslog.info(f"SEQUENCE RUNNER: (wiggle) randomize step: pick random next step: [{index}]")
            else:
                index += 1
                if index == count:
                    # loop
                    index = 0
                if verbose:
                    syslog.info(f"SEQUENCE RUNNER: (wiggle) - next step [{index}]")
            self.action_data.last_step = index

            if max_count:
                # abort after the step count reached if requested
                step_count += 1
                if step_count >= max_count:
                    if verbose:
                        syslog.info(f"SEQUENCE RUNNER: (wiggle) max step count reached ({step_count})")
                    self.action_data._is_running = False
                    break

        if verbose:
            syslog.info(f"SEQUENCE WIGGLE STOP: {self.id}")
        self.action_data._is_running = False

    def _wait(self, delay: float):
        """interruptible delay
        :param delay: time in seconds

        """
        expires = time.time() + delay
        while self.action_data._is_running and expires > time.time():
            time.sleep(0.01)


class SequenceContainer(AbstractContainer):
    """Represents a container which holds sequential actions.

    The actions will trigger one after the other with subsequent activations.

    """

    name = "Sequence"
    tag = "sequence"
    hint = """This container runs all actions sequentially like a macro.
Unlike a macro, any action suitable for the input can be used."""

    # override default allowed inputs here
    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    interaction_types = [
        Interactions.Up,
        Interactions.Down,
        Interactions.Delete,
    ]

    functor = SequenceContainerFunctor
    widget = SequenceContainerWidget

    def __init__(self, parent=None, node=None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.exec_on_release = False  # true if the sequence triggers on input release
        self.exec_on_press = True  # true if the sequence triggers on input press

        self.wiggle_min_delay = 250  # minimum delay for wiggle mode, or default delay if not randomized
        self.wiggle_max_delay = 5000  # maximum delay for wiggle mode, if in random mode
        self.wiggle_random = True  # wiggle random mode
        self.wiggle_exec_delay = 250  # delay between a press trigger and a release trigger for each action executing in wiggle mode
        self.wiggle_step_delay = 250  # delay between steps
        self.wiggle_randomize_steps = False  # if set, randomizes the execution steps
        self.resume_mode = False  # if set, the sequence resumes where it was last stopped
        self.last_step = None  # stores the last step
        self.normal_exec_delay = 0  # wait time between steps when running normally
        self.normal_autorelease_delay = 250  # wait time between autoreleases of each step when running normally
        self.step_options = {}  # map of step options indexed by step number
        self.stepped_exec_reset = True  # true if the stepped execution should reset on profile start, or continue from the last step otherwise
        self.wiggle_count_min = 1  # min number of wiggle steps to take.
        self.wiggle_count_max = 1  # max number of wiggle steps to take.
        self.wiggle_count_enabled = False  # true if wiggle mode count is enabled
        self.sync_mode = SyncMode.Ignore  # default sync mode on profile start

        self.mode = SequenceMode.Normal  # run mode

    def getOptions(self, index):
        """gets the option object for the particular step index"""
        if index not in self.step_options:
            options = StepOptions()
            options.index = index
            self.step_options[index] = options
        return self.step_options[index]

    def _parse_xml(self, node, data=None, extra_data=None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """

        if "trigger_on_press" in node.attrib:
            self.exec_on_press = safe_read(node, "trigger_on_press", bool, True)
        else:
            # new format
            self.exec_on_press = safe_read(node, "trigger-on-press", bool, True)

        self.exec_on_release = safe_read(node, "trigger-on-release", bool, False)

        self.wiggle_min_delay = safe_read(node, "wiggle-min", int, 250)
        self.wiggle_max_delay = safe_read(node, "wiggle-max", int, 5000)
        self.wiggle_exec_delay = safe_read(node, "wiggle-exec", int, 5000)
        self.wiggle_step_delay = safe_read(node, "wiggle-step", int, 5000)
        self.wiggle_random = safe_read(node, "wiggle-random", bool, True)
        self.wiggle_randomize_steps = safe_read(node, "wiggle-random-steps", bool, False)
        value = safe_read(node, "wiggle-count-min", int, 1)
        if value > 0:
            self.wiggle_count_min = value

        value = safe_read(node, "wiggle-count-max", int, 1)
        if value > 0:
            self.wiggle_count_max = value
        self.wiggle_count_enabled = safe_read(node, "wiggle-count-enabled", bool, False)

        self.resume_mode = safe_read(node, "resume-mode", bool, False)
        self.normal_autorelease_delay = safe_read(node, "autorelease-exec", int, 250)
        self.normal_exec_delay = safe_read(node, "normal-exec", int, 0)
        if "mode" not in node.attrib:
            # legacy read
            if "wiggle-mode" in node.attrib:
                wiggle_mode = safe_read(node, "wiggle-mode", bool, False)
                if wiggle_mode:
                    self.mode = SequenceMode.Wiggle
            if "toggle-mode" in node.attrib:
                toggle_mode = safe_read(node, "toggle-mode", bool, False)
                if toggle_mode:
                    self.mode = SequenceMode.Toggle
        else:
            self.mode = SequenceMode.fromString(safe_read(node, "mode", str, "normal"))

        self.stepped_exec_reset = safe_read(node, "stepped-exec-reset", bool, False)

        # load step options
        self.step_options.clear()
        option_nodes = node.xpath("./step-option")
        for o_node in option_nodes:
            option = StepOptions()
            option.from_xml(o_node)
            self.step_options[option.index] = option

        if "sync-mode" in node.attrib:
            self.sync_mode = SyncMode(safe_read(node, "sync-mode", int, 0))

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", SequenceContainer.tag)
        node.set("trigger-on-press", safe_format(self.exec_on_press, bool))
        node.set("trigger-on-release", safe_format(self.exec_on_release, bool))

        node.set("wiggle-min", safe_format(self.wiggle_min_delay, int))
        node.set("wiggle-max", safe_format(self.wiggle_max_delay, int))
        node.set("wiggle-exec", safe_format(self.wiggle_exec_delay, int))
        node.set("wiggle-step", safe_format(self.wiggle_step_delay, int))
        node.set("wiggle-random", safe_format(self.wiggle_random, bool))
        node.set("wiggle-random-steps", safe_format(self.wiggle_randomize_steps, bool))
        node.set("wiggle-count-min", safe_format(self.wiggle_count_min, int))
        node.set("wiggle-count-max", safe_format(self.wiggle_count_max, int))
        node.set("wiggle-count-enabled", safe_format(self.wiggle_count_enabled, bool))
        node.set("resume-mode", safe_format(self.resume_mode, bool))
        node.set("normal-exec", safe_format(self.normal_exec_delay, int))
        node.set("autorelease-exec", safe_format(self.normal_autorelease_delay, int))
        node.set("sync-mode", safe_format(self.sync_mode, int))
        node.set("mode", SequenceMode.toString(self.mode))
        node.set("stepped-exec-reset", safe_format(self.stepped_exec_reset, bool))

        # save step options
        if self.step_options:
            for option in self.step_options.values():
                o_node = option.to_xml()
                node.append(o_node)

        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return True
        # return len(self.action_sets) > 0

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)

        count = sum(len(actions) for actions in self.action_sets)

        table.addField("Steps", f"{count}")

        match self.mode:
            case "normal":
                mode_name = "Run Once"
            case "toggle":
                mode_name = "Toggle"
            case "loop":
                mode_name = "Loop (while pressed)"
            case "wiggle":
                mode_name = "Wiggle"
            case _:
                mode_name = f"unknown: {self.mode}"

        table.addField("Mode:", f"{mode_name}")
        if self.mode == "wiggle":
            table.addField("Wiggle Mode", "Enabled")
            if self.wiggle_random:
                table.addField("Wiggle Random", "Enabled")
                table.addField("Random Steps", "Yes" if self.wiggle_randomize_steps else "No")
                table.addField("Wiggle Min Delay", f"{self.wiggle_min_delay} ms")
                table.addField("Wiggle Max Delay", f"{self.wiggle_max_delay} ms")
                table.addField("Wiggle Exec Delay", f"{self.wiggle_exec_delay} ms")
                table.addField("Wiggle Count Min", f"{self.wiggle_count_min}")
                table.addField("Wiggle Count Max", f"{self.wiggle_count_max}")

        if self.exec_on_press:
            table.addField("Exec (press)", "Yes")
        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()


# Plugin definitions
version = 1
name = "sequence"
create = SequenceContainer
