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

import copy
import logging
import threading
import time
from lxml import etree as ElementTree
from gremlin.input_types import InputType
from PySide6 import QtWidgets, QtCore


import gremlin
import gremlin.config
import gremlin.ui.ui_common
import gremlin.event_handler

from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
from gremlin.util import safe_format, safe_read
from shiboken6 import Shiboken
syslog = logging.getLogger("system")

class RepeatContainerWidget(AbstractContainerWidget):

    """ Repeat container optionally repeats the actions provided """

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)
        

    def _create(self, action_data):
        ''' called before create action ui - initialize here'''
        self.action_data : RepeatContainer = action_data

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self.profile_data.create_or_delete_virtual_button()

        self.action_layout.addWidget(QtWidgets.QLabel("Repeat Options:"))

        widget = gremlin.ui.ui_common.QDataCheckbox("Trigger on initial press",
                                                    value = self.action_data.trigger_on_start,
                                                    tooltip = "If set, the repeated action will trigger immediately, wait for the initial delay, and start repeating the actions if the input is pressed.\nIf not set, there is no intitial trigger, and repeated action will only trigger if the input is still held after the initial delay has lapsed.\nHas no effect if the initial delay is disabled (0).",
                                                    callback = self._handle_start_trigger_changed)
        
        self.action_layout.addWidget(widget)


        widgets = []

        widget = gremlin.ui.ui_common.QIntLineEdit(value = self.action_data.repeat_count,
                                                   callback = self._handle_repeat_count_changed,
                                                   tooltip = "Number of times to repeat the actions.  Set to 0 to disable (unlimited).")




        widget = gremlin.ui.ui_common.getHContainer([widget,"(0 for unlimited)"], widget_only=True)
        
        widgets.append(("Repeat Count:", widget))

      

        # activation delay
        widget = gremlin.ui.ui_common.QDelayWidget(
            value = int(self.action_data.initial_pulse_delay * 1000),
            callback = self._handle_delay_changed,
            tooltip = "Initial delay in milliseconds before actions are repeated.  Set to 0 to start repeating immediately."
        )

        widgets.append(("Initial delay (ms):", widget))

        self.action_layout.addWidget(widget)

        # repeat delay
        widget = gremlin.ui.ui_common.QDelayWidget(
            value = int(self.action_data.hold_delay * 1000),
            callback = self._handle_interval_changed,
            
            tooltip = "How long in milliseconds the action is held pressed."
        )

        widgets.append(("Repeat hold time (ms):", widget))
        
        
        # pulse delay
        widget = gremlin.ui.ui_common.QDelayWidget(
            value = int(self.action_data.pulse_interval_delay* 1000),
            callback = self._handle_pulse_changed,
            tooltip = "Delay in milliseconds between repeats."
        )

        widgets.append(("Repeat Interval (ms):", widget))

        # build the table
        row_widgets = []
        for label, widget in widgets:
            row_widget = gremlin.ui.ui_common.getGridContainer(widget, label, widget_only=True)
            self.action_layout.addWidget(row_widget)
            row_widgets.append(row_widget)

        # sync the table column widths
        gremlin.ui.ui_common.synchronize_grids(row_widgets)

        self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())

        if len(self.profile_data.action_sets) > 0:
            assert len(self.profile_data.action_sets) == 1

            widget = self._create_action_set_widget(
                self.profile_data.action_sets[0],
                "Repeat",
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )
            self.action_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)
        else:
            action_selector = gremlin.ui.ui_common.ActionSelector(
                self.profile_data.get_input_type(),
                self.profile_data,
            )
            action_selector.inputItem = self.profile_data
            action_selector.action_added.connect(self._add_action)
            action_selector.action_paste.connect(self._paste_action)
            self.action_layout.addWidget(action_selector)

    def _handle_start_trigger_changed(self, checked : bool):
        self.action_data.trigger_on_start = checked

    def _handle_repeat_count_changed(self, value : int):
        self.action_data.repeat_count = value

    def _handle_delay_changed(self, value : int):
        self.action_data.initial_pulse_delay = value / 1000

    def _handle_pulse_changed(self, value : int):
        self.action_data.pulse_interval_delay = value / 1000

    def _handle_interval_changed(self, value : int):
        self.action_data.hold_delay = value / 1000

    def _create_condition_ui(self):
        if self.profile_data.action_sets:

            widget = self._create_action_set_widget(
                self.profile_data.action_sets[0],
                "Smart Toggle",
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
            if self.profile_data.action_sets[0] is None:
                self.profile_data.action_sets[0] = []
            self.profile_data.action_sets[0].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
            self.container_modified.emit()
        finally:
            gremlin.util.popCursor()

    def _paste_action(self, action, container):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.profile_data)
            if self.profile_data.action_sets[0] is None:
                self.profile_data.action_sets[0] = []
            self.profile_data.action_sets[0].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
            self.container_modified.emit()        
        finally:
            gremlin.util.popCursor()

    def _delay_changed_cb(self, value):
        self.profile_data.delay = value / 1000 # in seconds

    def _activation_changed_cb(self, value):
        """Updates the activation condition state.

        :param value whether or not the selection was toggled - ignored
        """
        if self.activate_press.isChecked():
            self.profile_data.activate_on = "press"
        else:
            self.profile_data.activate_on = "release"

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
        title = "Repeat: "
        if len(self.profile_data.action_sets) > 0:
            title += ", ".join(a.name for a in self.profile_data.action_sets[0])
        return title


class RepeatContainerFunctor(gremlin.base_conditions.AbstractSelfTriggerFunctor):

    """Executes the contents of the associated Repeat container."""

    def __init__(self, action_data : RepeatContainer, parent = None):
        super().__init__(action_data, parent)
        self.pulse_worker_map = {}  # map of (device_id, input_id) to pulse worker object
        self.action_data : RepeatContainer = action_data
        self.verbose = gremlin.config.Configuration().verbose_mode_container
        self._timer = None
        self._lock = threading.Lock()
        self._is_running = False
        self._thread = None
        self._repeat_count = None # number of times to repeat, None = disabled


    def profile_start(self):
        self.verbose = gremlin.config.Configuration().verbose_mode_container

    def profile_stop(self):
        self._stop()

    def _pulse_on(self):
        ''' called when pulse is on '''
        self._execute(self._press_event, self._value, self._extra_data) 

    def _pulse_off(self):
        ''' called when pulse is off '''
        self._execute(self._release_event, self._value, self._extra_data) 


    def pulse_start(self, args, duration : float, interval : float):
        ''' pulse setup '''
        if self.verbose: syslog.info(f"Pulse START repeat container [{self.id}] duration: {duration:0.3f} interval: {interval:0.3f}")
        key = self.id
        worker : gremlin.repeater.PulseWorker 
        if key in self.pulse_worker_map:
            worker = self.pulse_worker_map[key]
            if worker.is_running:
                # worker already running - ignore pulse request
                if self.verbose: syslog.info(f"\talready pulsing - ignored")
                return
        else:
            count = self._repeat_count
            worker = gremlin.repeater.PulseWorker(duration, interval, self._pulse_on, self._pulse_off, data = args, count = count)
            self.pulse_worker_map[key] = worker

        if self.verbose: syslog.info(f"\tactivate")
        worker.start()

    def pulse_stop(self):
        ''' request a pulse abort '''
        if self.verbose: syslog.info(f"Pulse STOP repeat container [{self.id}]")
        key = self.id
        if key in self.pulse_worker_map:
            worker : gremlin.repeater.PulseWorker = self.pulse_worker_map[key]
            worker.stop()
            del self.pulse_worker_map[key]

    def _stop(self):
        ''' stops timer and pulsing '''
        if self._timer:
            # stop the timer
            self._timer.cancel()
            self._timer = None

        # stop pulsing if we were pulsing
        self.pulse_stop() 

        # stop the repeat if in the middle of a pulse cycle
        if self._thread and self._thread.is_alive():
            with self._lock:
                self._is_running = False
            self._thread.join()
            self._thread = None
            
        

    def _initial_pulse(self):
        ''' pulses a single time '''
        if self._is_running:
            return # already running
        
        with self._lock:
            self._is_running = True

        self._thread = threading.Thread(target = self._pulse_runner)
        self._thread.name ="repeater container runner"
        self._thread.start()
        

    def _pulse_runner(self):
        ''' runs a single abortable press/release pulse that is abortable if the input is released'''
        pulse_end = time.time() + self.action_data.hold_delay 
        self._execute(self._press_event, self._value, self._extra_data)
        while self._is_running and time.time() < pulse_end:
            time.sleep(0.001)
        self._execute(self._release_event, self._value, self._extra_data) # execute the first actions

        if self._is_running:
            # initial pulse completed ok, chain the rest 
            wait_time = self.action_data.initial_pulse_delay # wait interval before pulsing the next one
            self._timer = threading.Timer(wait_time, self._handle_repeat_start)
            self._timer.start()

        with self._lock:
            self._is_running = False

   
    def process_event(self, event, value, extra_data = None):
        '''handles functor event''' 
        
        verbose = gremlin.config.Configuration().verbose_mode_outputs
        # verbose = True
        
        if extra_data is None:
            extra_data = {}
        extra_data["autorelease"] = False # disable autorelease on actions regardless of settings

        if event.is_pressed:
            # input is pressed

            delay = self.action_data.initial_pulse_delay

            if verbose: syslog.info("Repeat: initial press")

            # create a fake button press from the source input 
            self._press_event = event.fake_button()
            self._release_event = self._press_event.invert()
            self._value = value
            self._extra_data = extra_data
            self._repeat_count = self.action_data.repeat_count if self.action_data.repeat_count > 0 else None

 
            if delay == 0:
                # go straight to pulsing if we're not delaying the pulse start
                self._handle_repeat_start()

            else:
                if self.action_data.trigger_on_start:
                    self._initial_pulse() # run a separate initial abortable pulse
                else:
                    # start after the timer has lapsed
                    wait_time = self.action_data.initial_pulse_delay # wait interval before pulsing the next one
                    self._timer = threading.Timer(wait_time, self._handle_repeat_start)
                    self._timer.start()



        else:
            # input is released
            self._stop()
        
        return True

    
    def _handle_repeat_start(self):
        ''' timer lapsed - stat the repeat pulse '''
        self.pulse_start(None, duration = self.action_data.hold_delay, interval = self.action_data.pulse_interval_delay)
        self._timer = None


class RepeatContainer(AbstractContainer):
    '''
    smart toggle container - short press = toggle output, long press is press while held and release
    '''

    name = "Repeater"
    tag = "repeat"
    hint = '''This container repeats the given actions after an initial delay if the input is still triggered.'''


    
    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]

    interaction_types = []

    functor = RepeatContainerFunctor
    widget = RepeatContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.setActionSets([[]])
        self.initial_pulse_delay = 0.75 # in seconds # initial repeat
        self.hold_delay = 0.25 # in seconds, repeat hold duration 
        self.pulse_interval_delay = 0.25 # in seconds, interval between repeats
        self.actionsetCustomParseCallback = self._parse_action_set
        self.trigger_on_start = True # true if the the repeat action is triggered on start.  If false, the trigger will only occur after the input has been held for the initial repeat delay.
        self.repeat_count = 0 # number of times to repeat, 0 to disable (unlimited)


    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        super()._parse_xml(node, data)
        self.initial_pulse_delay = safe_read(node, "delay", float, 0.75)
        self.hold_delay = safe_read(node,"interval", float, 0.25)
        self.pulse_interval_delay = safe_read(node,"pulse", float, 0.25)
        self.trigger_on_start = safe_read(node,"trigger-start", bool, True)
        self.repeat_count = safe_read(node, "repeat-count", int, 0)

        self.setActionSets([])

        actionset_nodes = node.xpath(".//action-set")   
        for index, actionset_node in enumerate(actionset_nodes):
            action_set = gremlin.base_profile.ActionSet()
            self._parse_action_xml(actionset_node, action_set, data, extra_data)
            self.action_sets.append(action_set)
            break # only read the first set


   
    def _parse_action_set(elf, node, data = None, extra_data = None):
        pass # do nothing
                


    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", RepeatContainer.tag)
        node.set("delay",safe_format(self.initial_pulse_delay, float))
        node.set("interval", safe_format(self.hold_delay, float))
        node.set("pulse", safe_format(self.pulse_interval_delay, float))
        node.set("trigger-start", safe_format(self.trigger_on_start, bool))
        node.set("repeat-count", safe_format(self.repeat_count, int))

        as_node = ElementTree.Element("action-set")
        for action in self.action_sets[0]:
            as_node.append(action.to_xml())
        node.append(as_node)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) == 1
    
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell

        table = ReportTable(cellpadding=4)
        
        count = sum(len(actions) for actions in self.action_sets)
        table.addField("Count", f"{count}")
        table.addField("Delay", f"{self.initial_pulse_delay*1000:,} ms")
        table.addField("Pulse", f"{self.pulse_interval_delay*1000:,} ms")
        table.addField("Interval", f"{self.hold_delay*1000:,} ms")

        return table.to_html()


# Plugin definitions
version = 1
name = "repeat"
create = RepeatContainer
