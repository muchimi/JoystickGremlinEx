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
from PySide6 import QtWidgets
import enum

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


class StepOptions():
    ''' step options for each step '''
    def __init__(self):
        self.index = -1 # step index 
        self.repeat_count = 2 # number of times the step should repeat
        self.mode = "normal" # repeate mode
        self.repeat_min_delay = 250 # delay between repeat steps in ms
        self.repeat_max_delay = 250 # delay between repeat steps in ms
        self.autorelease_max_delay = 250 # delay for autorelease of each pulse in ms
        self.autorelease_min_delay = 250
        self.randomize_delay = False # true if the interval between repeats is randomized
        self.randomize_autorelease_delay = False # true if the autorelease delay is randomized
        
        

    def getCount(self) -> int:
        ''' gets the repeat count '''
        if self.mode == "random":
            return random.randint(0,self.repeat_count)
        elif self.mode == "normal":
            return 1
        return self.repeat_count
    
    def getDelay(self, default_delay_ms : int = 0) -> float: 
        ''' gets the autorelease delay in seconds '''
        if self.mode == "normal":
            return default_delay_ms / 1000
        
        if self.randomize_delay:
            return random.randint(self.repeat_min_delay, self.repeat_max_delay) / 1000
        return self.repeat_min_delay/1000    
    
    def getAutoreleaseDelay(self, default_delay_ms : int = 0) -> float: 
        ''' gets the autorelease delay in seconds '''
        if self.mode == "normal":
            return default_delay_ms / 1000
        
        if self.randomize_autorelease_delay:
            return random.randint(self.autorelease_min_delay, self.autorelease_max_delay) / 1000
        return self.autorelease_max_delay/1000
        

    def to_xml(self):
        ''' saves to xml '''
        node = ElementTree.Element("step-option")
        node.set("index", safe_format(self.index, int))
        node.set("repeat-count", safe_format(self.repeat_count, int))
        node.set("mode",self.mode)
        node.set("repeat-min", safe_format(self.repeat_min_delay, int))
        node.set("repeat-max", safe_format(self.repeat_max_delay, int))
        node.set("autorelease-min", safe_format(self.autorelease_min_delay, int))
        node.set("autorelease-max", safe_format(self.autorelease_max_delay, int))
        node.set("randomize-delay", safe_format(self.randomize_delay, bool))
        node.set("randomize-autorelease", safe_format(self.randomize_autorelease_delay, bool))

        return node
    
    def from_xml(self, node):
        ''' reads xml'''
        if node.tag == "step-option":
            self.index = safe_read(node,"index",int, -1)
            self.repeat_count = safe_read(node,"repeat-count", int, 1)
            self.mode = safe_read(node, "mode", str,"normal")
            self.repeat_min_delay = safe_read(node, "repeat-min", int, 250)
            self.repeat_max_delay = safe_read(node, "repeat-min", int, 250)
            self.autorelease_max_delay = safe_read(node, "autorelease-min", int, 250)
            self.autorelease_max_delay = safe_read(node, "autorelease-max", int, 250)
            self.randomize_delay = safe_read(node,"randomize-delay", bool, False)
            self.randomize_autorelease_delay = safe_read(node,"randomize-autorelease", bool, False)
        
    

class StepOptionsWidget(QtWidgets.QWidget):
    ''' widget to manage step options '''
    def __init__(self, action_data : SequenceContainer, options : StepOptions, parent=None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        
        self.options = options
        self.action_data = action_data

        modes = [
            ("No Repeat","normal"), # no repeat (default)
            ("Repeat (fixed)","repeat"), # repeat fixed count
            ("Repeat (random)","random") # random repeat
                 ]
        
        margin = 0

        self.repeat_mode_widget = gremlin.ui.ui_common.QDataComboBox(
            source = modes, 
            value = options.mode,
            auto_adjust = True,
            callback = self._handle_mode_changed)

        self.repeat_count_widget = gremlin.ui.ui_common.QIntLineEdit(
            value = options.repeat_count,
            min_range = 2,
            callback = self._handle_repeat_count_changed,
            )

        self.container_repeat_widget = gremlin.ui.ui_common.getHContainer(
            self.repeat_count_widget,"Count:",
            widget_only=True)
        
        
        self.repeat_delay_min_widget = gremlin.ui.ui_common.QDelayWidget(
            value = options.repeat_min_delay,
            callback = self._handle_repeat_delay_min_changed,
            show_shortcuts=False,
            label= "Repeat delay (ms) Min:",
            tooltip= "Minimum time between repetitions in milliseconds"
        )
        self.repeat_delay_max_widget = gremlin.ui.ui_common.QDelayWidget(
            value = options.repeat_min_delay,
            callback = self._handle_repeat_delay_max_changed,
            show_shortcuts=False,
            label= "Max:",
            tooltip="Maximum time between repetitions in milliseconds"
        )


        self.autorelease_delay_min_widget = gremlin.ui.ui_common.QDelayWidget(
            value = options.autorelease_min_delay,
            callback = self._handle_autorelease_delay_min_changed,
            show_shortcuts=False,
            label= "Autorelease delay (ms) Min:",
            tooltip = "Minimum time betweeen a press and release for each repeat in milliseconds"
        )
        self.autorelease_delay_max_widget = gremlin.ui.ui_common.QDelayWidget(
            value = options.autorelease_max_delay,
            callback = self._handle_autorelease_delay_max_changed,
            show_shortcuts=False,
            label= "Max:",
            tooltip = "Maximum time betweeen a press and release for each repeat in milliseconds"
        )

        self.randomize_delay_widget = gremlin.ui.ui_common.QDataCheckbox(
            value = self.options.randomize_delay,
            label= "Randomize",
            callback= self._handle_randomize_delay_changed
        )

        self.randomize_autorelease_delay_widget = gremlin.ui.ui_common.QDataCheckbox(
            value = self.options.randomize_autorelease_delay,
            label= "Randomize",
            callback= self._handle_randomize_autorelease_delay_changed
        )
        

        self.container_delay_widget = gremlin.ui.ui_common.getHContainer(
            [
            self.randomize_delay_widget,
            "|",
            self.repeat_delay_min_widget,
            self.repeat_delay_max_widget,
            
            ],
            widget_only=True,
            left_margin=margin
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

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget)

        self.main_layout.addWidget(self.container_delay_widget)
        self.main_layout.addWidget(self.container_autorelease_delay_widget)

        

        self._update_widgets()

    def _update_widgets(self):
        ''' updates widget setup based on options selected '''
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
    def _handle_repeat_count_changed(self, value : int):
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
    def _handle_randomize_delay_changed(self, checked : bool):
        self.options.randomize_delay = checked
        self._update_widgets()

    @QtCore.Slot(bool)
    def _handle_randomize_autorelease_delay_changed(self, checked : bool):
        self.options.randomize_autorelease_delay = checked
        self._update_widgets()

    


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
        

        modes = [
            ("Run Once","normal"), # normal execution
            ("Toggle","toggle"), # toggle execution
            ("Loop (while pressed)","loop"), # loop mode - runs while the input is triggered
            ("Wiggle","wiggle"), # wiggle execution
        ]

        widgets = []
        for mode, data in modes:
            rb = gremlin.ui.ui_common.QDataRadioButton(label=mode, data = data, value = self.profile_data.mode == data, callbackEx = self._handle_mode_changed)
            widgets.append(rb)

        self._wiggle_count_enabled_widget = gremlin.ui.ui_common.QDataCheckbox("Random Step Count",
                                                                               callback = self._handle_wiggle_count_enabled_change,
                                                                               value = self.profile_data.wiggle_count_enabled,
                                                                               tooltip = "Enable the wiggle count mode to randomize how many steps execute per sequence trigger.")
   

        widget = gremlin.ui.ui_common.getHContainer(widgets,"Execution mode:",widget_only=True)
        self.action_layout.addWidget(widget)
            


        widgets = [
            self._wiggle_random_widget,
            self._wiggle_steps_widget, 
            self._wiggle_count_enabled_widget
        ]

        self.container_wiggle_options_widget = gremlin.ui.ui_common.getHContainer(widgets,"Wiggle mode:", widget_only=True)
        self.action_layout.addWidget(self.container_wiggle_options_widget)

        self._wiggle_exec_delay_widget = gremlin.ui.ui_common.QDelayWidget(value = self.profile_data.wiggle_exec_delay,
                                                                           label = "Step Autorelease Delay (ms):",
                                                                           tooltip="Time (ms) between a press and release event sent to individual wiggle steps",
                                                                           callback=self._handle_wiggle_exec_delay_change
        )

        self._wiggle_count_min_widget = gremlin.ui.ui_common.QIntLineEdit(min_range=1,
                                                                      max_range=1000,
                                                                      tooltip="Minimum number of steps to execute in wiggle mode. 0 to disable.<br>If set to 5, up to 5 wiggle steps will run and wiggle will stop after 5.",
                                                                      callback = self._handle_wiggle_count_min_change,
                                                                      value = self.profile_data.wiggle_count_min)
        
        self._wiggle_count_max_widget = gremlin.ui.ui_common.QIntLineEdit(min_range=1,
                                                                      max_range=1000,
                                                                      tooltip="Max number of steps to execute in wiggle mode. 0 to disable.<br>If set to 5, up to 5 wiggle steps will run and wiggle will stop after 5.",
                                                                      callback = self._handle_wiggle_count_max_change,
                                                                      value = self.profile_data.wiggle_count_max)


        self.container_wiggle_count_max_widget = gremlin.ui.ui_common.getHContainer(self._wiggle_count_max_widget,"Max", widget_only = True)

        self.container_wiggle_count_widget = gremlin.ui.ui_common.getHContainer(
            ["Wiggle Step Count Min: ",
             self._wiggle_count_min_widget,
            self.container_wiggle_count_max_widget,
            ],
            widget_only=True)
        self.action_layout.addWidget(self.container_wiggle_count_widget)

        self.action_layout.addWidget(self._wiggle_exec_delay_widget)
        self.action_layout.addWidget(self._wiggle_exec_delay_widget)
        self.action_layout.addWidget(self._wiggle_min_delay_widget)
        self.action_layout.addWidget(self._wiggle_max_delay_widget)



        self.resume_widget = gremlin.ui.ui_common.QDataCheckbox("Resume at last step",
                                                  value = self.profile_data.resume_mode,
                                                  tooltip = "If enabled, the sequence will resume at the last step it stopped at.",
                                                  callback = self._handle_resume_mode_change)
        
        
        self.normal_exec_delay = gremlin.ui.ui_common.QDelayWidget(value = self.profile_data.normal_exec_delay,
                                                            label = "Step Interval delay:",
                                                            tooltip="Time (ms) between executed steps",
                                                            callback=self._handle_normal_exec_delay_change
        )

        self.normal_step_delay = gremlin.ui.ui_common.QDelayWidget(value = self.profile_data.normal_autorelease_delay,
                                                            label = "Step Autorelease delay:",
                                                            tooltip="Time (ms) between a press and release event sent to individual steps",
                                                            callback=self._handle_autorelease_delay_change
        )
        

        self.info_widget = gremlin.ui.ui_common.QInfoBox(hide_key = "sequence_container")
        
        self.action_layout.addWidget(self.normal_exec_delay)
        self.action_layout.addWidget(self.normal_step_delay)

        widget = gremlin.ui.ui_common.getHContainer([self.resume_widget], widget_only = True)
        self.action_layout.addWidget(widget)

        
        self.action_layout.addWidget(self.info_widget)

        self.action_layout.addWidget(self._warning_widget)
        self.action_layout.addWidget(self._trigger_widget)

        # self.widget_layout.addStretch()

        self.action_layout.addLayout(self.widget_layout)


        # Insert action widgets
        for index, action in enumerate(self.profile_data.action_sets):
            # options widget
            
            options : StepOptions = self.container.getOptions(index)
            options_widget = StepOptionsWidget(self.profile_data, options)
            step_widget = gremlin.ui.ui_common.QFrameBox(f"<b>Step {index + 1}</b>")
            step_container  = gremlin.ui.ui_common.getVContainer([step_widget, QtWidgets.QLabel(" ")], widget_only=True)
            widgets = [
                step_container,
                options_widget,
            ]

            options_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True, alignment = QtCore.Qt.AlignmentFlag.AlignTop)
            


            widgets = [
                gremlin.ui.ui_common.QHorizontalLine(),
                options_container,
            ]


            container_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only= True)
            self.action_layout.addWidget(container_widget)

            widget = self._create_action_set_widget(
                self.profile_data.action_sets[index],
                "Step",
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
    

    @QtCore.Slot(bool)
    def _handle_mode_changed(self, widget, checked):
        mode = widget.data
        self.profile_data.mode = mode
        self._update_widgets()
        
    @QtCore.Slot(bool)
    def wiggle_count_enabled(self, checked : bool):
        self.profile_data.wiggle_count_enabled = checked
        self._update_widgets()


    @QtCore.Slot(int)
    def _handle_min_delay_change(self, value):
        # avoid re-entrant callbacks
        self.profile_data.wiggle_min_delay = value
        self.setWarning()

    @QtCore.Slot(int)
    def _handle_max_delay_change(self, value):
        self.profile_data.wiggle_max_delay = value
        self.setWarning()

    @QtCore.Slot(bool)
    def _handle_resume_mode_change(self, value):
        self.profile_data.resume_mode = value
        self.setWarning()



    @QtCore.Slot()
    def _handle_min_invalid_value(self):
        self.setWarning("Invalid min delay value")        

    @QtCore.Slot()
    def _handle_max_invalid_value(self):
        self.setWarning("Invalid max delay value")

    @QtCore.Slot(bool)
    def _handle_wiggle_count_enabled_change(self, checked : bool):
        self.profile_data.wiggle_count_enabled = checked
        self._update_widgets()

    @QtCore.Slot(int)
    def _handle_wiggle_exec_delay_change(self, value):
        self.profile_data.wiggle_exec_delay = value        

    @QtCore.Slot(int)
    def _handle_normal_exec_delay_change(self, value):
        self.profile_data.normal_exec_delay = value        

    @QtCore.Slot(int)
    def _handle_autorelease_delay_change(self, value):
        self.profile_data.normal_autorelease_delay = value        

    @QtCore.Slot(int)
    def _handle_wiggle_count_min_change(self, value):
        max_value = self.profile_data.wiggle_count_max
        min_value = self._wiggle_count_max_widget.minimum()

        if value > max_value:
            # bump max
            self._update_count_widget(self._wiggle_count_max_widget, min_value = value, value = value)
            self.profile_data.wiggle_count_max = value

        elif min_value > value:
            self._update_count_widget(self._wiggle_count_max_widget, min_value = value)

        self.profile_data.wiggle_count_min = value
        self._update_widgets()
        


    @QtCore.Slot(int)
    def _handle_wiggle_count_max_change(self, value):
        min_value = self.profile_data.wiggle_count_min
        if value < min_value:
            value = min_value
            self._update_count_widget(self._wiggle_count_max_widget, min_value = value, value = value)
        self.profile_data.wiggle_count_max = value
        
    def _update_count_widget(self, widget, value = None,  min_value = None, max_value = None):
        if Shiboken.is_valid(widget):
            with QtCore.QSignalBlocker(widget):
                if max_value is not None:
                    widget.setMaximum(max_value)
                if min_value is not None:
                    widget.setMinimum(min_value)
                if value is not None:
                    widget.setValue(value)



    def _update_widgets(self):
        mode = self.profile_data.mode
        wiggle_enabled = mode == "wiggle"
        normal_enabled = not wiggle_enabled
        resume_enabled = mode != "normal"
        self._wiggle_min_delay_widget.setVisible(wiggle_enabled)
       
        self.container_wiggle_options_widget.setVisible(wiggle_enabled)

        if wiggle_enabled:
            count_enabled = self.profile_data.wiggle_count_enabled
            self.container_wiggle_count_widget.setVisible(count_enabled)
            self.container_wiggle_count_max_widget.setVisible(count_enabled)


        max_enabled = wiggle_enabled and self.profile_data.wiggle_random
        self._wiggle_max_delay_widget.setVisible(max_enabled)

        self._wiggle_random_widget.setVisible(wiggle_enabled)
        self._wiggle_steps_widget.setVisible(wiggle_enabled)
        self._wiggle_exec_delay_widget.setVisible(wiggle_enabled)

        self.normal_exec_delay.setVisible(normal_enabled)
        self.normal_step_delay.setVisible(normal_enabled)
        self.resume_widget.setVisible(resume_enabled) # resume can only be used in a loop mode - so wiggle or toggle

        visible = bool(self._warning_widget.text())
        self._warning_widget.setVisible(visible)

        # info box based on modes
        match self.profile_data.mode:
            case "wiggle":
                msg = """The sequence will randomly loop while the input is triggered.
<br>In wiggle mode, the timing between steps, how long each step runs and the order of the steps can be randomly generated based on the options selected."""            
            case "toggle":
                msg = "The sequence will loop.  The first trigger with enable the sequence.  It will run continuously in a loop until the second trigger is received."
            case "loop":
                msg = "The sequence will loop while the input is triggered."
            case "normal":
                msg = "The sequence will run once when the input is triggered.  If the sequence is triggered while it's still running, the trigger is ignored."

        if resume_enabled and self.profile_data.resume_mode:
            if msg:
                msg += "<br>"
            msg += "Resume mode is enabled: the next sequence activation will continue at the step where it last stopped."

        self.info_widget.setText(msg)



    def setWarning(self, text = None):
        ''' sets warning display - send None to clear / hide'''
        visible = bool(text)
        self._warning_widget.setText(text)
        self._warning_widget.setVisible(visible)


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
        self.stop_normal()


    def start_wiggle(self):
        ''' starts the wiggle process '''
        if not self._is_running:
            syslog.info(f"SEQUENCE: start wiggle sequence runner")
            self._is_running = True
            self._thread = threading.Thread(target = self._wiggle_runner)
            self._thread.name = "wiggle runner"
            self._thread.start()


    def stop_wiggle(self):
        ''' stops the wiggle process '''
        if self._is_running:
            syslog.info(f"SEQUENCE: stop wiggle sequence runner")
            self._is_running = False
            self._thread.join()
            self._thread = None

    def start_normal(self):
        ''' starts the wiggle process '''
        if not self._is_running:
            syslog.info(f"SEQUENCE: start sequence runner")
            self._is_running = True
            self._thread = threading.Thread(target = self._normal_runner)
            self._thread.name = "sequence runner"
            self._thread.start()


    def stop_normal(self):
        ''' stops the wiggle process '''
        if self._is_running:
            syslog.info(f"SEQUENCE: stop sequence runner")
            self._is_running = False
            if self._thread.is_alive():
                self._thread.join()
            self._thread = None            



    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value, extra_data : dict = None) -> bool:
        if not self.valid:
            return False
        
        verbose = gremlin.config.Configuration().verbose_mode_container
        
        if event.event_type == InputType.JoystickHat:
            is_pressed = value.current != (0,0)
        elif not isinstance(value.current, bool):
            syslog.warning(f"Invalid data type received in Sequence container: {type(event.value)}")
            return False
        else:
            is_pressed = value.is_pressed

        is_pressed = event.is_pressed
        mode = self.action_data.mode
        
        if verbose:
            profile_mode = gremlin.shared_state.current_mode
            if self.action_data.comment:
                syslog.info(f"SEQUENCE EVENT: sequence {self.action_data.comment}") 
        

        trigger = (is_pressed and self.container.exec_on_press) or \
                    (not is_pressed and self.container.exec_on_release) 
        
        is_pressed = trigger
            
        match mode:
            case "wiggle":
                # wiggle mode runner
                if is_pressed and not self._is_running:
                    # run sequence in wiggle mode
                    if verbose: syslog.info(f"SEQUENCE EVENT: wiggle mode: start - profile mode: {profile_mode}")
                    self.start_wiggle()

                elif not is_pressed and self._is_running:
                    # stop wiggle mode
                    if verbose: syslog.info(f"SEQUENCE EVENT: wiggle mode: stop - profile mode: {profile_mode}")
                    self.stop_wiggle()
            case "toggle":
                # toggle mode acts as a switch on the input trigger - first press = turn on, second press = turn off
                if is_pressed:
                    if self._is_running:
                        # stop loop
                        if verbose: syslog.info(f"SEQUENCE EVENT: toggle mode: stop - profile mode: {profile_mode}")
                        self.stop_normal()
                    else:
                        # start loop
                        if verbose: syslog.info(f"SEQUENCE EVENT: toggle mode: start - profile mode: {profile_mode}")
                        self.start_normal()
            case "loop":
                # loop mode is on while the input is pressed, off when released
                if is_pressed and not self._is_running:
                    # run sequence in wiggle mode
                    if verbose: syslog.info(f"SEQUENCE EVENT: loop mode: start - profile mode: {profile_mode}")
                    self.start_normal()

                elif not is_pressed and self._is_running:
                    # stop wiggle mode
                    if verbose: syslog.info(f"SEQUENCE EVENT: loop mode: stop - profile mode: {profile_mode}")
                    self.stop_normal()
                
            case "normal":
                # regular mode - run while pressed
                if is_pressed:
                    if not self._is_running:
                        # start sequence
                        if verbose: syslog.info(f"SEQUENCE EVENT: normal mode: start - profile mode: {profile_mode}")
                        self.start_normal()
                    else:
                        if verbose: syslog.info(f"SEQUENCE EVENT: normal mode: start ignored because prior sequence is still running  - profile mode: {profile_mode}")

             


        return True 
    
    def _normal_runner(self):
        event_press = gremlin.event_handler.Event(InputType.JoystickButton,
                                            1,
                                            device_guid=gremlin.shared_state.fake_tab_guid,
                                            is_pressed = True)
        
        event_release = event_press.fake_button(False,True)
        
        nodes = [node for node in self.action_set_nodes]
        verbose = self._verbose
        verbose_extra = self._verbose_extra


        # no resume mode if running once
        resume = False if self.action_data.mode == "normal" else self.action_data.resume_mode

        if verbose: syslog.info(f"SEQUENCE RUNNER: {self.action_data.mode} mode - runner start - resume mode: {resume}")

        if not nodes:
            # nothing to run
            self._is_running = False
            if verbose: syslog.info(f"SEQUENCE WIGGLE: Trigger Functor: nothing to wiggle")
            return
        index = None
        if resume:
            if verbose: syslog.info(f"Resume at step: {self.action_data.last_step}")
            index = self.action_data.last_step
        
        if index is None:
            # start at the top
            index = 0
        count = len(nodes)

        
        exec_delay_ms = self.container.normal_exec_delay
        exec_delay_s = exec_delay_ms/1000
        autorelease_delay_ms = self.container.normal_autorelease_delay
        if verbose: syslog.info(f"SEQUENCE: starting sequence")

        while self._is_running:
            node = nodes[index]
            options : StepOptions = self.action_data.getOptions(index) # execution options for the step

            repeat_count = options.getCount() # number of times to repeate
            if verbose: syslog.info(f"\tstep [{index}] exec start - repeat count: {repeat_count}")


            for repeat_index in range(repeat_count):
                if verbose: syslog.info(f"\t\tTrigger press {index}/{repeat_index}")
                self._ec.execute_node(node, event_press, True, None) # issue press
                # autorelease delay computation
                delay = options.getAutoreleaseDelay(autorelease_delay_ms)
                if delay > 0:
                    if verbose: syslog.info(f"\t\tstep autorelease delay: {delay:03f}") 
                    self._wait(delay)
                    
                if verbose: syslog.info(f"\t\tTrigger release {index}/{repeat_index}")                    
                self._ec.execute_node(node, event_release, False, None) # issue release

                if not self._is_running: break
                if repeat_index < repeat_count - 1:
                    # interval between repeat delay computation
                    delay = options.getDelay(exec_delay_ms)
                    if delay > 0:
                        if verbose: syslog.info(f"\t\tstep repeat interval delay: {delay:03f}")
                        self._wait(delay)
                        if not self._is_running: break

            
            # next node to run
            index += 1
            if index == count:
                if self.action_data.mode == "normal":
                    self._is_running = False
                    break # only run once
                # loop
                index = 0
                if verbose_extra: syslog.info("\tlooping sequence")

            self.action_data.last_step = index
            if exec_delay_ms > 0:
                if verbose: syslog.info(f"\tstep interval delay: {exec_delay_s:03f}")
                self._wait(exec_delay_s)

        if verbose: syslog.info("SEQUENCE RUNNER: sequence completed - exiting runner")

        

    
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
        count_enabled = self.action_data.wiggle_count_enabled
        
        min_steps = self.action_data.wiggle_count_min
        max_steps = self.action_data.wiggle_count_max
        max_steps = random.randrange(min_steps, max_steps) if count_enabled else 0

        step_count = 0

        if not nodes:
            # nothing to run
            self._is_running = False
            if verbose: syslog.info(f"SEQUENCE WIGGLE: Trigger Functor: nothing to wiggle")
            return
        index = None
        if self.action_data.resume_mode:
            if verbose: syslog.info(f"Resume at step: {self.action_data.last_step}")
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
        exec_delay_s = exec_delay_ms / 1000
        if verbose: 
            syslog.info(f"SEQUENCE RUNNER: (wiggle) starting wiggle with  min delay: [{min_delay}] max delay: [{max_delay}] random mode: [{wiggle_random}]")
            if max_steps:
                if verbose: syslog.info(f"SEQUENCE RUNNER: (wiggle) max step count [{max_steps}]")


        while self._is_running:
            node = nodes[index]
            options : StepOptions = self.action_data.getOptions(index) # execution options for the step
            repeat_count = options.getCount() # number of times to repeat
            if max_steps and repeat_count < max_steps:
                if verbose: syslog.info(f"SEQUENCE RUNNER: (wiggle) - repeat count adjusted to {max_steps} due to step count mode enabled")
                repeat_count = max_steps

            for repeat_index in range(repeat_count):
                if verbose: syslog.info(f"SEQUENCE RUNNER: (wiggle) Trigger Functor: execute node ID: sequence [{index}] [{node.id}]")
                self._ec.execute_node(node, event_press, True, None) # issue press
                # autorelease delay 
                delay = options.getAutoreleaseDelay(exec_delay_ms)
                if delay > 0:
                    self._wait(delay)
                self._ec.execute_node(node, event_release, False, None) # issue release

                # delay between steps
                if not self._is_running: break
                if wiggle_random:
                    # random wiggle delay
                    delay = random.randrange(min_delay, max_delay) / 1000 # to seconds
                else:
                    # step delay
                    if repeat_index < repeat_count - 1:
                        delay = options.getDelay(exec_delay_ms)
                        if verbose_extra: syslog.info(f"step repeat interval delay [{delay}]")
                        if delay > 0:
                            self._wait(delay)
                            if not self._is_running: break

            if not self._is_running: break



            # delay between steps
            delay = exec_delay_s
            
            if delay > 0:
                if verbose_extra: syslog.info(f"step repeat interval delay [{delay}]")
                self._wait(delay)
                if not self._is_running: break


            # next node to run
            if wiggle_steps:
                index = random.randrange(0, count) # pick the next random step
            else:
                index += 1
                if index == count:
                    # loop
                    index = 0
                    if verbose: syslog.info("SEQUENCE RUNNER: (wiggle) looping sequence")
            self.action_data.last_step = index

            if max_steps:
                # abort after the step count reached if requested
                step_count += 1
                if step_count >= max_steps:
                    if verbose: syslog.info(f"SEQUENCE RUNNER: (wiggle) max step count reached ({step_count})")
                    self._is_running = False
                    break

        if verbose: syslog.info("SEQUENCE RUNNER: (wiggle) sequence completed - exiting runner")
            
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
        
        self.wiggle_min_delay = 250 # minimum delay for wiggle mode, or default delay if not randomized
        self.wiggle_max_delay = 5000 # maximum delay for wiggle mode, if in random mode
        self.wiggle_random = True # wiggle random mode
        self.wiggle_exec_delay = 250 # delay between a press trigger and a release trigger for each action executing in wiggle mode
        self.wiggle_randomize_steps = False # if set, randomizes the execution steps
        self.resume_mode = False # if set, the sequence resumes where it was last stopped
        self.last_step = None # stores the last step
        self.normal_exec_delay = 0 # wait time between steps when running normally
        self.normal_autorelease_delay = 250 # wait time between autoreleases of each step when running normally
        self.step_options = {} # map of step options indexed by step number 
        self.wiggle_count_min = 1 # min number of wiggle steps to take.
        self.wiggle_count_max = 1 # max number of wiggle steps to take.
        self.wiggle_count_enabled = False # true if wiggle mode count is enabled

        self.mode = "normal" # run mode


    def getOptions(self, index):
        ''' gets the option object for the particular step index '''
        if not index in self.step_options:
            options = StepOptions()
            options.index = index
            self.step_options[index] = options
        return self.step_options[index]
    

            

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

        
        self.wiggle_min_delay = safe_read(node,"wiggle-min", int, 250)
        self.wiggle_max_delay = safe_read(node,"wiggle-max", int, 5000)
        self.wiggle_exec_delay = safe_read(node,"wiggle-exec", int, 5000)
        self.wiggle_random = safe_read(node,"wiggle-random", bool, True)
        self.wiggle_randomize_steps = safe_read(node,"wiggle-random-steps", bool, False)
        value = safe_read(node,"wiggle-count-min", int, 1)
        if value > 0:
            self.wiggle_count_min = value

        value = safe_read(node,"wiggle-count-max", int, 1)
        if value > 0:
            self.wiggle_count_max = value
        self.wiggle_count_enabled = safe_read(node,"wiggle-count-enabled", bool, False)

        self.resume_mode = safe_read(node,"resume-mode", bool, False)
        self.normal_autorelease_delay = safe_read(node,"autorelease-exec", int, 250)
        self.normal_exec_delay = safe_read(node,"normal-exec", int, 0)
        if not "mode" in node.attrib:
            # legacy read
            if "wiggle-mode" in node.attrib:
                wiggle_mode = safe_read(node,"wiggle-mode", bool, False)
                if wiggle_mode:
                    self.mode = "wiggle"
            if "toggle-mode" in node.attrib:
                toggle_mode = safe_read(node,"toggle-mode", bool, False)
                if toggle_mode:
                    self.mode = "toggle"
        else:
            self.mode = safe_read(node,"mode",str,"normal")

        # load step options
        self.step_options.clear()
        option_nodes = node.xpath(".//step-option")
        for o_node in option_nodes:
            option = StepOptions()
            option.from_xml(o_node)
            self.step_options[option.index] = option


        

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", SequenceContainer.tag)
        node.set("trigger-on-press",safe_format(self.exec_on_press,bool))
        node.set("trigger-on-release",safe_format(self.exec_on_release,bool))
        
        node.set("wiggle-min", safe_format(self.wiggle_min_delay, int))
        node.set("wiggle-max", safe_format(self.wiggle_max_delay, int))
        node.set("wiggle-exec", safe_format(self.wiggle_exec_delay, int))
        node.set("wiggle-random", safe_format(self.wiggle_random, bool))
        node.set("wiggle-random-steps", safe_format(self.wiggle_randomize_steps, bool))
        node.set("wiggle-count-min", safe_format(self.wiggle_count_min, int))
        node.set("wiggle-count-max", safe_format(self.wiggle_count_max, int))
        node.set("wiggle-count-enabled", safe_format(self.wiggle_count_enabled, bool))
        node.set("resume-mode", safe_format(self.resume_mode, bool))
        node.set("normal-exec", safe_format(self.normal_exec_delay, int))
        node.set("autorelease-exec", safe_format(self.normal_autorelease_delay, int))
        
        node.set("mode", self.mode)

        # save step options
        if self.step_options:
            for option in self.step_options.values():
                o_node = option.to_xml()
                node.append(o_node)
                


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

    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        table = ReportTable(cellpadding=4)  

        count = sum(len(actions) for actions in self.action_sets)

        table.addField("Steps", f"{count}" )

        if self.wiggle_mode:
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
