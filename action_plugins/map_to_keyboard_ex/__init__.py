# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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


import os
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.base_profile

import gremlin.config
import gremlin.config
import gremlin.config
import gremlin.event_handler
import gremlin.input_devices
from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.config
import gremlin.keyboard
import gremlin.macro
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.ui.input_item
import enum
import gremlin.config
from gremlin.profile import safe_format, safe_read
from gremlin.keyboard import Key, key_from_name, key_from_code
from gremlin.ui.virtual_keyboard import *
from gremlin.types import MouseButton, MouseAction, MouseClickMode, KeyboardOutputMode
import logging
import threading
import time
import gremlin.ui.virtual_keyboard
from gremlin.util import log_info
import gremlin.util
from gremlin import input_devices
import gremlin.repeater
import gremlin.windows_event_hook

syslog = logging.getLogger("system")

class MapToKeyboardExWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to keyboard key combinations - adds extra functionality to the base module ."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        self.action_data = action_data
        

    def _create_ui(self):
        """Creates the UI components."""


        self.key_combination = QtWidgets.QLabel("<b>Current key combination:</b>")
        self.key_map = {} # map of key to widgets
        self.keys = [] # list of keys

        self.display_container_widget, self.display_container_layout = gremlin.ui.ui_common.getVContainer()


        self.key_combination_widget, self.key_combination_layout = gremlin.ui.ui_common.getHContainer()

        widget = gremlin.ui.virtual_keyboard.QKeyWidget()
        self._key_height = widget.desiredHeight
        self.display_container_widget.setMinimumHeight(self._key_height)
        self.display_container_layout.addWidget(self.key_combination_widget)
        
        self.listen_multi_widget = gremlin.ui.ui_common.Buttons.getListenWidget(label="Listen (multi)", callback = self._record_multi_keys_cb)
        self.listen_multi_widget.setToolTip("Listen for multiple inputs.  Click on ok when done.  Clicks on the buttons will not be included in the recorded list.")

        self.listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback = self._record_keys_cb)
        self.listen_widget.setToolTip("Listen for a single input.")
        
        self.show_keyboard_widget = QtWidgets.QPushButton("Select...")
        self.show_keyboard_widget.setIcon(load_icon("mdi.keyboard-settings-outline", qta_color = gremlin.ui.ui_common.Color.listenColor()))
        self.show_keyboard_widget.clicked.connect(self._select_keys_cb)

        self.clear_widget = gremlin.ui.ui_common.Buttons.getClearWidget(callback = self._clear_keys_cb)



        self.delay_box = gremlin.ui.ui_common.QDelayWidget(self.action_data.delay) 
        self.autorepeat_delay_box = gremlin.ui.ui_common.QDelayWidget(self.action_data.autorepeat_delay,label="Interval (ms)") 
        
        self.delay_box.setValue(self.action_data.delay)
        self.autorepeat_delay_box.setValue(self.action_data.autorepeat_delay)

        widgets = []
        for mode in KeyboardOutputMode:
            rb = gremlin.ui.ui_common.QDataRadioButton(mode.name, mode)
            rb.setChecked(self.action_data.mode == mode)
            rb.clicked.connect(self._mode_changed)
            widgets.append(rb)

        
        self.description_widget = QtWidgets.QLabel()
        self.description_widget.setWordWrap(True)


        self.delay_box.valueChanged.connect(self._delay_changed)
        self.autorepeat_delay_box.valueChanged.connect(self._autorepeat_changed)

        self.container_options_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, "Mode:")

        widgets = [
            self.delay_box,
            self.autorepeat_delay_box
        ]
        
        self.container_delay_widget, _ = gremlin.ui.ui_common.getHContainer(widgets)


        widgets = [
            self.clear_widget,
            self.listen_widget,  
            self.listen_multi_widget, 
            self.show_keyboard_widget
        ]

        self.container_action_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, "Actions:")


        self.main_layout.addWidget(self.key_combination)
        self.main_layout.addWidget(self.display_container_widget)
        self.main_layout.addWidget(self.container_action_widget)
        self.main_layout.addWidget(self.container_options_widget)
        self.main_layout.addWidget(self.description_widget)
        self.main_layout.addWidget(self.container_delay_widget)
        


        self.main_layout.addStretch()
        self._update_ui() # update UI based on mode

    def _select_keys_cb(self):
        ''' display the keyboard input dialog '''
        import gremlin.shared_state
        gremlin.shared_state.push_suspend_ui_keyinput()
        self._keyboard_dialog = InputKeyboardDialog(sequence = self.action_data.keys, parent = self)
        self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._keyboard_dialog_closed_cb)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.showNormal()

    def _keyboard_dialog_closed_cb(self):
        import gremlin.shared_state
        gremlin.shared_state.pop_suspend_ui_keyinput()

    def _keyboard_dialog_ok_cb(self):
        ''' callled when the virtual dialog completes '''

        # grab the new data
        self.action_data.keys = gremlin.keyboard.sort_keys(self._keyboard_dialog.keys)
        self.action_modified.emit()
        gremlin.shared_state.pop_suspend_ui_keyinput()


    def _populate_ui(self):
        """Populates the UI components."""

        gremlin.util.clear_layout(self.key_combination_layout)
        


        keys = self.action_data._get_keys()
        self.key_map.clear()
        self.keys.clear()
        if keys:

            key : gremlin.keyboard.Key
            for key in keys:
                assert key.name,"Invalid key provided"
                if not key in self.keys:
                    self._add_key(key)
                
        else:
            self.key_combination_layout.addWidget(gremlin.ui.ui_common.QWarning("No input selected. Please select at least one input."))
            self.key_combination_layout.addStretch()
            

    def _add_key(self, key):
        ''' adds a key (must run on UI thread) '''
        gremlin.util.assert_ui_thread()

        widget = gremlin.ui.virtual_keyboard.QKeyWidget()
        icon = gremlin.keyboard.KeyMap.icon(key)
        name = gremlin.keyboard.KeyMap.get_name(key)
        tooltip = gremlin.keyboard.KeyMap.get_description(key)
        if icon:
            widget.setIcon(icon)
        if name:
            widget.setText(name)
        if tooltip:
            widget.setToolTip(tooltip)
        widget.keySize = 2
        widget.autoSize = True
        
        index = len(self.keys)
        self.key_combination_layout.insertWidget(index, widget)
        if not self.keys:
            self.key_combination_layout.addStretch()

        self.key_map[key] = widget # remember keys created
        self.keys.append(key)

            
    def _update_keys(self, keys):
        gremlin.util.InvokeUiMethod(self._update_keys_ui, keys)

    

    def _update_keys_ui(self, keys):
        """Updates the storage with a new set of keys.

        :param keys the keys to use in the key combination
        """

        if isinstance(keys, gremlin.windows_event_hook.MouseEvent):
            # if not keys.is_pressed:
            #     return # ignore releases 
            # mouse input
            key = gremlin.keyboard.key_from_mousebutton(keys.button_id)
            syslog.info(f"keyboard <- mouse: {keys.button_id}")
            if not key:
                return
            keys = [key]

        

        data = []
        for code in keys:
            if isinstance(code, tuple):
                key = gremlin.keyboard.KeyMap.find(code[0], code[1])
            elif isinstance(code, int):
                key = gremlin.keyboard.KeyMap.find_virtual(code)
            elif isinstance(code, Key):
                key = code
            else:
                assert True, f"Don't know how to handle: {code}"
            data.append(key)

        self.action_data.keys = gremlin.keyboard.sort_keys(data)
        gremlin.util.InvokeUiMethod(self._populate_ui) # reload new keys

        self.action_modified.emit()

    def _clear_selection(self):
        ''' clears all keys '''
        if self.key_map:
            gremlin.util.InvokeUiMethod(self._clear_selection_ui)

    def _clear_selection_ui(self):
        ''' clears keys (ui thread)'''
        if self.key_map:
            self.key_map.clear()
            self.keys.clear()
            gremlin.util.clear_layout(self.key_combination_layout)
            # note: this does not clear the action data so it can be restored 
            


    def _handle_key_input(self, key):
        gremlin.util.InvokeUiMethod(self._handle_key_input_ui, key)

    def _handle_key_input_ui(self, key : gremlin.keyboard.Key):
        # handles an input key on the UI thread
        if not key in self.keys:
            self._add_key(key)
        


    def _mode_changed(self):
        ''' output mode changed '''
        widget = self.sender()
        self.action_data.mode = widget.data
        self._update_ui()

    def _update_ui(self):
        ''' updates the data based on the current mode'''
        delay_visible = False
        autorepeat_visible = False
        mode = self.action_data.mode
        match mode:
            case KeyboardOutputMode.Press:
                description = "<b>Press</b> mode will press keys() - the key(s) is not released and should be paired with a release at some point (keyboard 'make')."
            case KeyboardOutputMode.Release:
                description = "<b>Release</b> mode will release keys(s) previously pressed with the Press mode (keyboard 'break'). If no key is sent, the release mode will also clear any auto-repeat actions to cancel them."
            case KeyboardOutputMode.Hold:
                description = "<b>Hold</b> mode will keep the key(s) pressed until the input is released."
            case KeyboardOutputMode.Pulse:
                delay_visible = True
                description = "<b>Pulse</b> mode will press the key(s), wait for the delay, then release the key(s)."
            case KeyboardOutputMode.AutoRepeat:
                delay_visible = True
                autorepeat_visible = True
                description = "<b>AutoRepeat</b> mode will pulse the key(s) repeatedly. The delay is the time between a press/release, interval is the time between pulses."

        self.container_delay_widget.setVisible(delay_visible)
        self.description_widget.setText(description)
        self.autorepeat_delay_box.setVisible(autorepeat_visible)

    def _delay_changed(self):
        self.action_data.delay = self.delay_box.value()
        

    def _autorepeat_changed(self):
        self.action_data.autorepeat_delay = self.autorepeat_delay_box.value()
        

    def _quarter_sec_delay(self):
        self.delay_box.setValue(250)
        

    def _half_sec_delay(self):
        self.delay_box.setValue(500)
        

    def _sec_delay(self):
        self.delay_box.setValue(1000)

    def _clear_keys_cb(self):
        gremlin.util.InvokeUiMethod(self._clear_keys_ui)

    def _clear_keys_ui(self):
        self.action_data.keys.clear()
        self._populate_ui()
        
    def _record_keys_cb(self):
        gremlin.util.InvokeUiMethod(self._record_keys_ui, False)

    def _record_multi_keys_cb(self):
        gremlin.util.InvokeUiMethod(self._record_keys_ui, True)


    def _record_keys_ui(self, multi_keys):
        """Prompts the user to press the desired key combination. - runs on UI thread"""

        button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=multi_keys
        )

        button_press_dialog.item_selected.connect(self._update_keys)
        button_press_dialog.keyInput.connect(self._handle_key_input)
        button_press_dialog.closed.connect(self._handle_closed)

        self._clear_selection() # clear current selection


        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        button_press_dialog.show()

    def _handle_closed(self, accepted):
        ''' occurs when the listen dialog closes, passes the close state'''
        if accepted:
            ''' accept all the keys '''
            keys = self.key_map.values()
        else:
            keys = self.action_data.keys

        self._update_keys_ui(keys)

class MapToKeyboardExFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)

        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        #verbose = True

        self.press = gremlin.macro.Macro()
        self.needs_auto_release = True
        self.action_data = action
        self.mode = action.mode
        self.delay = action.delay / 1000
        self.autorepeat_delay = action.autorepeat_delay / 1000
        self.is_pressed = False
        self._ar_thread = None
        self._ar_running = False
        self._ar_event = threading.Event()
        self.has_keys = bool(action.keys)
        self.use_macros = False # true to use macros, false to send direct keys
        self._press_keys = []
        self._release_keys = []
        self.remote_client : gremlin.input_devices.RemoteClient = input_devices.remote_client
        self.verbose = gremlin.config.Configuration().verbose_mode_keyboard
        self.pulse_worker_map = {}  # map of (device_id, input_id) to pulse worker object


        if self.delay < 0:
            self.delay = 0
        if self.autorepeat_delay < 0:
            self.autorepeat_delay = 0

        # build the macro that will play when the action is called
        key: Key
        for key in action.keys:
            self.press.press(key)
            self._press_keys.append(key)

        self.release = gremlin.macro.Macro()

        # Execute release in reverse order
        for key in reversed(action.keys):
            self.release.release(key)
            self._release_keys.append(key)

        self.delay_press_release = gremlin.macro.Macro()

        # execute press/release with a delay before releasing (pulse)
        if verbose:  syslog.info(f"DelayPressMacro:")
        for key in action.keys:
            if verbose: syslog.info(f"\tPress: {key}")
            self.delay_press_release.press(key)
        if self.delay > 0:
            if verbose: syslog.info(f"\tPause: {self.delay}")
            self.delay_press_release.pause(self.delay)
        for key in reversed(action.keys):
            if verbose: syslog.info(f"\tRelease: {key}")
            self.delay_press_release.release(key)

        # tell the time delay or release macros to inform us when they are done running
        self.release.completed_callback = self._macro_completed
        self.delay_press_release.completed_callback = self._macro_completed

        el = gremlin.event_handler.EventListener()
        el.macro_step_completed.connect(self._macro_handler)
        el.autorepeat_clear.connect(self._autorepeat_clear)

        # list of the macros we generate
        self._macro_ids = set()



    def registerMacro(self, id : int):
        self._macro_ids.add(id)

    def unregisterMacro(self, id : int):
        if id in self._macro_ids:
            self._macro_ids.remove(id)

    def isMacroOurs(self, id : int):
        ''' true if the macro is one of ours '''
        return gremlin.macro.MacroManager()

    @QtCore.Slot(int)
    def _macro_handler(self, id):
        ''' called when a macro completes '''
        if self.isMacroOurs(id):
            self.unregisterMacro(id)
            self.functor_complete.emit()

    def _macro_completed(self):
        ''' called when a macro is done running '''
        self.is_pressed = False

    def profile_start(self):
        self._ar_running = False

    def profile_stop(self):
        # release all keys
        if self.mode == KeyboardOutputMode.Hold:
            gremlin.macro.MacroManager().queue_macro(self.release)
        self._ar_running = False

    @QtCore.Slot()
    def _autorepeat_clear(self):
        if self._ar_thread is not None:
            self._ar_event.set()
            self._ar_running = False
            self._ar_thread.join()
            self._ar_thread = None
            # ensure the keys are released
            gremlin.macro.MacroManager().queue_macro(self.release)

    def _manual_release(self):
        ''' callback for manual releases '''
        for key in self._release_keys:
            if key.is_mouse:
                (is_local, is_remote) = input_devices.remote_state.state
                gremlin.macro._send_mouse_button(key.mouse_button, False, is_local, is_remote)
            else:
                gremlin.keyboard.send_key_up(key)


    def _pulse_on(self, data):
        ''' called when pulse is on '''
        keys = data
        key : gremlin.keyboard.Key
        for key in keys:
            if self.verbose: syslog.info(f"Pulse ON [{key.debug_name}]")
            gremlin.keyboard.send_key_down(key) # handles local and remote and special mouse keys

    def _pulse_off(self, data):
        ''' called when pulse is off '''
        keys = data
        key : gremlin.keyboard.Key
        for key in keys:
            if self.verbose: syslog.info(f"Pulse OFF [{key.debug_name}]")
            gremlin.keyboard.send_key_up(key) # handles local and remote and special mouse keys

    def pulse_start(self, keys : list, duration : float, interval : float):
        ''' pulse setup '''
        if self.verbose: syslog.info(f"Pulse START keyboard [{self.id}] duration: {duration:0.3f} interval: {interval:0.3f}")
        key = self.id
        worker : gremlin.repeater.PulseWorker 
        if key in self.pulse_worker_map:
            worker = self.pulse_worker_map[key]
            if worker.is_running:
                # worker already running - ignore pulse request
                if self.verbose: syslog.info(f"\talready pulsing - ignored")
                return
        else:
            args = keys
            worker = gremlin.repeater.PulseWorker(duration, interval, self._pulse_on, self._pulse_off, data = args)
            self.pulse_worker_map[key] = worker

        if self.verbose: syslog.info(f"\activate")
        worker.start()

    def pulse_stop(self):
        ''' request a pulse abort '''
        if self.verbose: syslog.info(f"Pulse STOP keyboard [{self.id}]")
        key = self.id
        if key in self.pulse_worker_map:
            worker : gremlin.repeater.PulseWorker = self.pulse_worker_map[key]
            worker.stop()
            del self.pulse_worker_map[key]





    def process_event(self, event, value, extra_data = None):
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        (is_local, is_remote) = input_devices.remote_state.state
        is_pressed = event.is_pressed
        mode = self.action_data.mode
        #if event.is_axis or value.current or is_pressed:
        if is_pressed:
            # joystick values or virtual button
            # verbose = True
            match mode:
                case KeyboardOutputMode.Release:
                    if verbose:
                        syslog.info(f"MapToKeyboardEx: release")
                    # kill off any auto-repeat as well
                    if not self.has_keys:
                        # clear autorepeat if no keys are provided 
                        if verbose:
                            syslog.info(f"MapToKeyboardEx: clear autorepeat")
                        eh = gremlin.event_handler.EventListener()
                        eh.autorepeat_clear.emit() # clear auto-repeats
                    else:
                        self.is_pressed = False
                        id = gremlin.macro.MacroManager().queue_macro(self.release, is_local, is_remote)
                        self.registerMacro(id)
                case KeyboardOutputMode.Press:
                    # press mode and not already triggered
                    if self.has_keys:
                        self.is_pressed = True
                        if verbose:
                            syslog.info(f"MapToKeyboardEx: press")
                        id = gremlin.macro.MacroManager().queue_macro(self.press, is_local, is_remote)
                        self.registerMacro(id)

           

                case KeyboardOutputMode.Hold:
                    if self.has_keys:
                        auto_release = self.needs_auto_release
                        if event.is_virtual_button:
                            # if using a virtual button to trigger - disable the auto-release
                            auto_release = False
                        if event.is_pressed and not auto_release:
                            # press event
                            if verbose:
                                syslog.info(f"MapToKeyboardEx: hold (press)")

                            if self.use_macros:
                                id = gremlin.macro.MacroManager().queue_macro(self.press, is_local, is_remote)
                                self.registerMacro(id)
                            else:
                                # send direct
                                key : gremlin.keyboard.Key
                                for key in self._press_keys:
                                    if verbose: syslog.info(f"send key press: {key}")
                                    if key.is_mouse:
                                        gremlin.macro._send_mouse_button(key.mouse_button, True, is_local, is_remote)
                                    else:
                                        gremlin.keyboard.send_key_down(key)


                        if event.is_pressed and auto_release: 
                            if self.use_macros:
                                id = gremlin.macro.MacroManager().queue_macro(self.press, is_local, is_remote)
                                self.registerMacro(id)
                                callback = lambda : gremlin.macro.MacroManager().queue_macro(self.release, is_local, is_remote)
                                ButtonReleaseActions().register_callback(callback, event)
                            else:
                                key : gremlin.keyboard.Key
                                for key in self._press_keys:
                                    if verbose: syslog.info(f"send key press (autorelease): {key}")
                                    if key.is_mouse:
                                        gremlin.macro._send_mouse_button(key.mouse_button, True, is_local, is_remote)
                                    else:
                                        gremlin.keyboard.send_key_down(key)

                                callback = self._manual_release
                                ButtonReleaseActions().register_callback(callback, event)

                case KeyboardOutputMode.Pulse:
                    # make and break with delay
                    if self.has_keys:
                        if is_pressed:
                            if verbose: syslog.info(f"MapToKeyboardEx: pulse")
                            repeat_interval = -1 # do not repeat
                            self.pulse_start(self.action_data.keys, self.action_data.delay/1000, repeat_interval)
                        else:
                            # stop pulsing on release
                            self.pulse_stop()
        
                            # id = gremlin.macro.MacroManager().queue_macro(self.delay_press_release, is_local, is_remote)
                            # self.is_pressed = True
                            # self.registerMacro(id)                                

                case KeyboardOutputMode.AutoRepeat:
                    # setup autorepeat thread
                    repeat_interval =  self.action_data.autorepeat_delay/1000
                    self.pulse_start(self.action_data.keys, self.action_data.delay/1000, repeat_interval)
                                  
                    # if verbose:
                    #         syslog.info(f"MapToKeyboardEx: autorepeat")
                    # if self.has_keys:

                    #     if self._ar_thread is None:
                    #         self._ar_thread = threading.Thread(target=self._ar_execute) #threading.Thread(target=self._ar_execute, daemon=False)
                    #         self._ar_running = True
                    #         self._ar_event.clear()
                    #         self._ar_thread.start()




                    

        else:
            # release
            if self.has_keys:
                match mode:
                    case KeyboardOutputMode.Hold:
                        # release keys
                        if self.use_macros:
                            gremlin.macro.MacroManager().queue_macro(self.release)
                        else:
                            # not using macros
                            for key in self._release_keys:
                                if verbose: syslog.info(f"send key release: {key}")
                                gremlin.keyboard.send_key_up(key)
                    case KeyboardOutputMode.AutoRepeat:
                        self.pulse_stop()
                    

            # self._ar_running = False
            # self._ar_event.set()
            # if self._ar_thread is not None:
            #     self._ar_thread.join()
            #     self._ar_thread = None
        
        return True
    


    def _ar_execute(self):
        ''' autorepeat run thread '''
        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        macro_mgr = gremlin.macro.MacroManager()
        if verbose:
            log_info("autorepeat start...")
        trigger_time = time.time()-1
        while self._ar_running and not self._ar_event.is_set():
            if time.time() > trigger_time:
                macro_mgr.queue_macro(self.delay_press_release)
                trigger_time = time.time() + self.autorepeat_delay + self.delay
            time.sleep(0.01)
        if verbose:
            log_info("autorepeat stop...")
        macro_mgr.clear_queue()
            
            
        

            


class MapToKeyboardEx(gremlin.base_profile.AbstractAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """

    name = "Map to Keyboard Ex"
    tag = "map-to-keyboard-ex"

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)
    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]

    functor = MapToKeyboardExFunctor
    widget = MapToKeyboardExWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent
        self.keys = []
        self.mode = KeyboardOutputMode.Hold # hold by default
        #self._mode = KeyboardOutputMode.Both # pulse by default
        config = gremlin.config.Configuration()
        self._delay = config.last_keyboard_mapper_pulse_value # delay between make/break in milliseconds
        self._autorepeat_delay = config.last_keyboard_mapper_interval_value # delay between autorepeats in milliseconds

    @property
    def delay(self):
        return self._delay
    @delay.setter
    def delay(self, value):
        if value < 0:
            value = 0
        self._delay = value
        gremlin.config.Configuration().last_keyboard_mapper_pulse_value = value

    @property
    def autorepeat_delay(self):
        return self._autorepeat_delay
    @autorepeat_delay.setter
    def autorepeat_delay(self, value):
        if value < 0:
            value = 0
        self._autorepeat_delay = value
        gremlin.config.Configuration().last_keyboard_mapper_interval_value = value

    def _update_config(self):
        config = gremlin.config.Configuration()
        
        config.last_keyboard_mapper_interval_value =self.autorepeat_delay_box.value()
        
    def _get_keys(self) -> list:
        ''' gets the list of keys for the action (Key)'''
        keys = []
        for code in self.keys:
            key = None
            if isinstance(code, tuple):
                key = gremlin.keyboard.KeyMap.find(code[0], code[1])
            elif isinstance(code, int):
                key = gremlin.keyboard.KeyMap.find_virtual(code)
            elif isinstance(code, Key):
                key = code
            else:
                assert True, f"Don't know how to handle: {code}"
            
            if not key.name:
                syslog.error(f"Invalid key: {code}")
                continue
            keys.append(key)
        return keys

    def _get_display_keys(self, as_list = False):
        text = ''
        names = []

        for code in self.keys:
            key = None
            if isinstance(code, tuple):
                key = gremlin.keyboard.KeyMap.find(code[0], code[1])
            elif isinstance(code, int):
                key = gremlin.keyboard.KeyMap.find_virtual(code)
            elif isinstance(code, Key):
                key = code
            else:
                assert True, f"Don't know how to handle: {code}"
            if key:
                names.append(key.name)
        if as_list:
            return names
        text += " + ".join(names)
        return text

    def display_name(self):
        return self._get_display_keys()


    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "fa6s.keyboard"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        keys = []

        if "mode" in node.attrib:
            mode = safe_read(node, "mode", str, "")
            match mode:
                case  "make":
                    # legacy
                    self.mode = KeyboardOutputMode.Press
                case "press":
                    self.mode = KeyboardOutputMode.Press
                case "break":
                    # legacy
                    self.mode = KeyboardOutputMode.Release
                case "release":
                    self.mode = KeyboardOutputMode.Release
                case "both":
                    # legacy
                    self.mode = KeyboardOutputMode.Pulse
                case "pulse":
                    self.mode = KeyboardOutputMode.Pulse
                case "hold":
                    self.mode = KeyboardOutputMode.Hold
                case "autorepeat":
                    self.mode = KeyboardOutputMode.AutoRepeat
                case _:
                    # default
                    self.mode = KeyboardOutputMode.Hold


        if "delay" in node.attrib:
            self.delay = safe_read(node, "delay", int, 250) # pulse delay in milliseconds

        if "interval" in node.attrib:
            self.autorepeat_delay = safe_read(node, "interval", int, 250) # pulse interval milliseconds

        for child in node.findall("key"):
            virtual_code = safe_read(child, "virtual-code", int, 0)
            if virtual_code > 0:
                key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)
            else:
                scan_code = safe_read(child, "scan-code", int, 0)
                is_extended = safe_read(child, "extended", bool, False)
                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
            if key:
                keys.append(key)

        # sort the keys for display purposes
        self.keys = gremlin.keyboard.sort_keys(keys)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToKeyboardEx.tag)
        node.set("mode",safe_format(self.mode.name.casefold(), str) )

        node.set("delay",safe_format(self.delay, int))
        node.set("interval", safe_format(self.autorepeat_delay, int))

        for code in self.keys:
            if isinstance(code, tuple): # key ID (scan_code, extended)
                scan_code = code[0]
                is_extended = code[1]
                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
                virtual_code = key.virtual_code
            elif isinstance(code, int): # single virtual code
                key = gremlin.keyboard.KeyMap.find_virtual(code)
                scan_code = key.scan_code
                is_extended = key.is_extended
                virtual_code = code
            elif isinstance(code, Key):
                # key
                key = code
                scan_code = key.scan_code
                is_extended = key.is_extended
                virtual_code = key.virtual_code
            else:
                assert True, f"Don't know how to handle: {code}"

            if key.name:
                key_node = ElementTree.Element("key")
                key_node.set("virtual-code", str(virtual_code))
                key_node.set("scan-code", str(scan_code))
                key_node.set("extended", str(is_extended))
                # useful for xml readability purposes = what scan code is this
                key_node.set("description", key.name)
                node.append(key_node)
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise

        """
        # return true by default so the action gets saved even if it doesn't do anything
        return True


version = 1
name = "map-to-keyboard-ex"
create = MapToKeyboardEx
