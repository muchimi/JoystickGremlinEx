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
from lxml import etree

from PySide6 import QtWidgets, QtCore, QtGui
from gremlin.input_types import InputType
from gremlin.input_devices import CallbackActions

from gremlin.profile import safe_format, safe_read
from gremlin.keyboard import Key, key_from_name, key_from_code
from gremlin.ui.virtual_keyboard import *
import gremlin.config
import logging
import threading
import time
from gremlin.util import log_info
from shiboken6 import Shiboken
import html
from gremlin.types import *
import gremlin.remote
import vjoy.vjoy
import gremlin.process
import win32gui


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
        if not Shiboken.isValid(self):
            return

        self.key_combination = QtWidgets.QLabel("<b>Current key combination:</b>")
        self.key_map = {} # map of key to widgets
        self.keys = [] # list of keys

        self.display_container_widget, self.display_container_layout = gremlin.ui.ui_common.getVContainer()


        self.key_combination_widget, self.key_combination_layout = gremlin.ui.ui_common.getHContainer()

        widget = gremlin.ui.virtual_keyboard.QKeyWidget()
        self._key_height = widget.desiredHeight
        self.display_container_widget.setMinimumHeight(self._key_height + 4)
        self.display_container_layout.addWidget(self.key_combination_widget)
        
        self.listen_multi_widget = gremlin.ui.ui_common.Buttons.getListenWidget(label="Listen (multi)", callback = self._record_multi_keys_cb)
        self.listen_multi_widget.setToolTip("Listen for multiple inputs.  Click on ok when done.  Clicks on the buttons will not be included in the recorded list.")

        self.listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback = self._record_keys_cb)
        self.listen_widget.setToolTip("Listen for a single input.")
        
        self.show_keyboard_widget = QtWidgets.QPushButton("Select...")
        self.show_keyboard_widget.setIcon(load_icon("mdi.keyboard-settings-outline", qta_color = gremlin.ui.ui_common.Color.listenColor()))
        self.show_keyboard_widget.clicked.connect(self._select_keys_cb)
        self.show_keyboard_widget.setToolTip("Select keys using the virtual keyboard")

        self.clear_widget = gremlin.ui.ui_common.Buttons.getClearWidget(callback = self._clear_keys_cb)
        self.clear_widget.setToolTip("Clears the current keys")



        self.delay_box = gremlin.ui.ui_common.QDelayWidget(self.action_data.delay) 
        self.autorepeat_delay_box = gremlin.ui.ui_common.QDelayWidget(self.action_data.autorepeat_delay) 
        
        self.delay_box.setValue(self.action_data.delay)
        self.autorepeat_delay_box.setValue(self.action_data.autorepeat_delay)

        widgets = []
        for mode in KeyboardOutputMode:
            rb = gremlin.ui.ui_common.QDataRadioButton(KeyboardOutputMode.to_displayname(mode), mode)
            rb.setChecked(self.action_data.mode == mode)
            rb.clicked.connect(self._mode_changed)
            widgets.append(rb)

        
        self.description_widget = gremlin.ui.ui_common.QInfoBox(hide_key=self.__class__.__name__)
        


        self.delay_box.valueChanged.connect(self._delay_changed)
        self.autorepeat_delay_box.valueChanged.connect(self._autorepeat_changed)

        self.container_options_widget = gremlin.ui.ui_common.getGridContainer (
            gremlin.ui.ui_common.getGridContainer(widgets, widget_only = True),
            "Output Mode:",
            widget_only = True,
            left_margin = 12
            )


        widgets = [
            gremlin.ui.ui_common.getGridContainer(self.delay_box, "Duration (ms):", widget_only = True),
            gremlin.ui.ui_common.getGridContainer(self.autorepeat_delay_box, "Interval (ms):", widget_only = True),
        ]
        
        self.container_delay_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True, left_margin=12)
        widgets.append(self.container_options_widget)
        gremlin.ui.ui_common.synchronize_grids(widgets)


        widgets = [
            self.clear_widget,
            self.listen_widget,  
            self.listen_multi_widget, 
            self.show_keyboard_widget
        ]

        self.container_action_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)


        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self._sync_widget = gremlin.ui.ui_common.QSyncModeWidget(mode = self.action_data.sync_mode,
                                                                 label = "State on profile start:",
                                                                 sync_modes=[SyncMode.Ignore, SyncMode.Input],
                                                                 callback = self._sync_changed)
        widgets = [self._execute_widget]


        exec_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)

        sync_container = gremlin.ui.ui_common.getHContainer(self._sync_widget, left_margin =12, widget_only = True)
        

        widget = gremlin.ui.ui_common.QIntLineEdit(value = self.action_data.wheel_factor,
                                                   min_range = 1,
                                                   max_range = 100,
                                                callback=self._handle_wheel_factor_changed)
        wheel_factor_container = gremlin.ui.ui_common.getHContainer(
            widget,
            "Mouse Wheel Factor:",
            widget_only=True,
            tooltip = "Mouse wheel motion factor, determines how much the wheel moves per trigger. The default is 1 for 1x.",
            left_margin = 12)



        self.main_layout.addWidget(self.key_combination)
        self.main_layout.addWidget(self.display_container_widget)
        self.main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.main_layout.addWidget(self.container_action_widget)
        self.main_layout.addWidget(self.container_options_widget)
        self.main_layout.addWidget(self.container_delay_widget)
        self.main_layout.addWidget(wheel_factor_container)
        self.main_layout.addWidget(exec_container)
        self.main_layout.addWidget(sync_container)
        self.main_layout.addWidget(self.description_widget)

        # new T183 - remote configuration widget
        self.remote_widget = gremlin.ui.ui_common.RemoteClientWidget(self.action_data.remote_config)
        self.process_widget = gremlin.ui.ui_common.TargetProcessWidget(self.action_data.remote_config)
        self.main_layout.addWidget(self.remote_widget)
        self.main_layout.addWidget(self.process_widget)

        self.warning_widget = gremlin.ui.ui_common.QWarningWidget()
        self.main_layout.addWidget(self.warning_widget)

        self.main_layout.addStretch()
        self._update_ui() # update UI based on mode

    def _handle_sendmode_changed(self, mode : SendType):
        ''' sets the send mode'''
        self.action_data.sendMode = mode        

    def _handle_wheel_factor_changed(self, value : int):
        self.action_data.wheel_factor = value

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked        


    def _sync_changed(self, mode):
        self.action_data.sync_mode = mode        

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
        self._populate_ui()
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
            self.key_combination_layout.addWidget(gremlin.ui.ui_common.QWarningWidget("No input selected. Please select at least one input."))
            self.key_combination_layout.addStretch()
            

    def _add_key(self, key):
        ''' adds a key (must run on UI thread) '''
        gremlin.util.assert_ui_thread()

        widget = gremlin.ui.virtual_keyboard.QKeyWidget()
        widget.key = key
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
        widget.right_clicked.connect(self._handle_key_context)
        index = len(self.keys)
        self.key_combination_layout.insertWidget(index, widget)
        if not self.keys:
            self.key_combination_layout.addStretch()

        self.key_map[key] = widget # remember keys created
        self.keys.append(key)
        

    def _handle_key_context(self, widget):
        gremlin.util.InvokeUiMethod(self._handle_key_context_ui, widget)

    def _handle_key_context_ui(self, widget):
        ''' handle right click '''
        from functools import partial
        actionDelete = QtGui.QAction("Delete", self)
        actionDelete.triggered.connect(partial(self._delete_key, widget))
        menu = QtWidgets.QMenu(self)
        menu.addAction(actionDelete)
        menu.exec_(QtGui.QCursor.pos())

    def _delete_key(self, widget):
        ''' called on context menu delete key '''
        # action: QtGui.QAction = self.sender()
        # widget : gremlin.ui.virtual_keyboard.QKeyWidget = action.data()
        key = widget.key
        self.keys.remove(key)
        self.action_data.keys.remove(key)
        self._populate_ui()


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
            


    def _handle_key_input(self, key : gremlin.keyboard.Key | list[gremlin.keyboard.Key]):
        gremlin.util.InvokeUiMethod(self._handle_key_input_ui, key)

    def _handle_key_input_ui(self, key : gremlin.keyboard.Key | list[gremlin.keyboard.Key]):
        # handles an input key on the UI thread
        if not self.keys:
            gremlin.util.clear_layout(self.key_combination_layout) # clear the prior message
        
        key_list = key if hasattr(key,"__iter__") else [key]
        
        for key in key_list:
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
        warning = None
        match mode:
            case KeyboardOutputMode.Press:
                description = "<b>Press</b> mode will press keys() - the key(s) is not released and should be paired with a release at some point (keyboard 'make')."
            case KeyboardOutputMode.Release:
                description = "<b>Release</b> mode will release keys(s) previously pressed with the Press mode (keyboard 'break'). If no key is sent, the release mode will also clear any auto-repeat actions to cancel them."
            case KeyboardOutputMode.Hold:
                if self.action_data.exec_on_release:
                    warning = "Hold mode cannot be used for execute on release.  The action will not execute at runtime on input release."

                description = "<b>Hold</b> mode will keep the key(s) pressed while the input is on/pressed.  The key(s) will release when the input is off/released.<br>This mode <b>does not</b> autorepeat.  To autorepeat, select autorepeat mode."
            case KeyboardOutputMode.Pulse:
                delay_visible = True
                description = "<b>Pulse</b> mode will press the key(s), wait for the delay, then release the key(s)."
            case KeyboardOutputMode.AutoRepeat:
                if self.action_data.exec_on_release:
                    warning = "Autorepeat mode cannot be used for execute on release.  The action will not execute at runtime on input release."
                delay_visible = True
                autorepeat_visible = True
                description = "<b>AutoRepeat</b> mode will pulse the key(s) repeatedly. The delay is the time between a press/release, interval is the time between pulses."
            case KeyboardOutputMode.Toggle:
                description = "<b>Toggle</b> mode will toggle the key pressed/released."

        self.container_delay_widget.setVisible(delay_visible)
        self.description_widget.setText(description)
        self.autorepeat_delay_box.setVisible(autorepeat_visible)

        warning_visible = warning is not None
        self.warning_widget.setVisible(warning_visible)
        self.warning_widget.setText(warning)



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
            keys = self.keys
        else:
            keys = self.action_data.keys

        self._update_keys_ui(keys)

class MapToKeyboardExFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)

        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        #verbose = True

        self.press_macro = gremlin.macro.Macro()
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
        self.remote_client : gremlin.remote.RemoteClient = gremlin.remote.remote_client
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_keyboard
        self.verbose_extra = self.verbose and config.verbose_mode_extra
        self.pulse_worker_map = {}  # map of (device_id, input_id) to pulse worker object
        self.client_list = [0] # send to all clients by default
        self.target_process = None # no target process by default
        self.target_hwnd = 0 # taget process window handle (0 is the focused window which is the default)
        self.output_enabled = True # true if the functor is enabled (can be disabled if process target is not found)
        self.extra_data = None

        if self.delay < 0:
            self.delay = 0
        if self.autorepeat_delay < 0:
            self.autorepeat_delay = 0

        # order the keys so 

        # build the macro that will play when the action is called
        key: Key
        key_list = [(key, key.weight) for key in action.keys]
        if key_list:
            key_list.sort(key = lambda x: x[1])
            key_list.reverse()

        if self.verbose_extra:
            stub = "".join([f"{key.name} vk: [0x{key.virtual_code:x}] weight: [{w}],  " for key, w in key_list])
            syslog.info(f"Key order: {stub}")

        # remove the weight
        key_list = [key[0] for key in key_list]

        self._press_keys = key_list
        self._release_keys = key_list.copy()
        self._release_keys.reverse()

        
        for key in key_list:
            self.press_macro.press(key)
            

        self.release = gremlin.macro.Macro()

        # Execute release in reverse order
        for key in reversed(key_list):
            self.release.release(key)
     

        self.delay_press_release = gremlin.macro.Macro()

        # execute press/release with a delay before releasing (pulse)
        if verbose:
            if self.use_macros:
                if verbose:  syslog.info(f"KEY ACTION: DelayPressMacro:")
                for key in action.keys:
                    if verbose: syslog.info(f"\tPress: {key}")
                    self.delay_press_release.press(key)
                if self.delay > 0:
                    if verbose: syslog.info(f"\tPause: {self.delay}")
                    self.delay_press_release.pause(self.delay)
                for key in reversed(action.keys):
                    if verbose: syslog.info(f"\tRelease: {key}")
                    self.delay_press_release.release(key)
            else:
                stub = "".join([f"{key.name}, " for key in self._press_keys])
                syslog.info(f"KEY ACTION: Key press: {stub}")
                stub = "".join([f"{key.name}, " for key in self._release_keys])
                syslog.info(f"KEY ACTION: Key release: {stub}")
            

        # tell the time delay or release macros to inform us when they are done running
        self.release.completed_callback = self._macro_completed
        self.delay_press_release.completed_callback = self._macro_completed

        el = gremlin.event_handler.EventListener()
        el.macro_step_completed.connect(self._macro_handler)
        el.autorepeat_clear.connect(self._autorepeat_clear)

        # list of the macros we generate
        self._macro_ids = set()

        # list of held keys we pressed
        self._hold_keys = []






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
        remote_config = self.action_data.remote_config
        self.client_list = remote_config.getClientList()

        
        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        if remote_config.isProcess:
            process_name = remote_config.process
            partial_match = remote_config.partialMatch
            # this extra data is sent to remote clients so they can look for the profile on the remote client

            self.extra_data = {
                'process_name': remote_config.process,
                'partial_match' : remote_config.partialMatch
            }
            if process_name and remote_config.local:
                # look for the process handle to send to
                ph = gremlin.process.ProcessHelper()
                hwnd = ph.findProcessHwnd(process_name, partial_match)
                if not hwnd:
                    # did not find the handle to the process - disable output
                    self.output_enabled = False
                    syslog.error(f"KEYBOARD: Target process: [{self.target_process}] not found.  Output will be disabled.")
                if verbose and hwnd:
                    syslog.info(f"KEYBOARD: found target handle [{hwnd} for [{process_name}]")
                self.target_hwnd = hwnd
        is_pressed = False
        self.debug_count = 0
        self._hold_keys = []
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        input_type = self.action_data.get_input_type()
        match input_type:
            case InputType.JoystickHat:
                value = gremlin.joystick_handling.get_hat(device_guid, input_id)
                if value in vjoy.vjoy.Hat.to_continuous_position:
                    self.hat_position = vjoy.vjoy.Hat.to_continuous_position[value]
                else:
                    self.hat_position = (0,0)
                is_pressed = self.hat_position != (0,0)
                
            case InputType.JoystickButton:
                is_pressed = gremlin.joystick_handling.get_button(device_guid, input_id)

            case InputType.JoystickAxis:
                pass
        
        # determine the startup state 
        match self.action_data.sync_mode:
            case SyncMode.Ignore:
                pass
            case SyncMode.Input:
                if self.verbose: syslog.info(f"\t sync to input : {is_pressed}")
                event = gremlin.event_handler.Event(
                    input_type,
                    input_id,
                    device_guid,
                    value = is_pressed,
                    is_pressed=is_pressed,
                )
                self.process_event(event, is_pressed, extra_data={"virtual":True})


    def profile_stop(self):
        # release all keys
        if self.mode == KeyboardOutputMode.Hold:
            # release any pressed keys on profile stop to avoid stuck keys
            if self._hold_keys:
                verbose = gremlin.config.Configuration().verbose_mode_keyboard
                if self.use_macros:
                    gremlin.macro.MacroManager().queue_macro(self.release)
                else:
                    is_local, is_remote = self.action_data.sendFlags()
                    for key in self._hold_keys:
                        if verbose: syslog.info(f"send key release: {key}")
                        gremlin.keyboard.send_key_up(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)
                self._hold_keys.clear()

        

        # terminate any autorepeat
        self._autorepeat_clear()

        # terminate any pulse
        self.pulse_stop()



    def profile_mode_changed(self, mode : str):
        ''' called when the runtime mode changes '''

        # terminate any autorepeat
        self._autorepeat_clear()

        # terminate any pulse
        self.pulse_stop()


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
        (is_local, is_remote) = self.action_data.sendFlags()
        
        for key in self._release_keys:
            if key.is_mouse:
                gremlin.macro._send_mouse_button(key.mouse_button, False, is_local, is_remote, wheel_factor=self.action_data.wheel_factor)
            else:
                gremlin.keyboard.send_key_up(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)


    def _pulse_on(self, data):
        ''' called when pulse is on '''
        press_keys, release_keys = data
        key : gremlin.keyboard.Key
        (is_local, is_remote) = self.action_data.sendFlags()
        
        for key in press_keys:
            if self.verbose: syslog.info(f"Pulse ON [{key.debug_name}]")
            gremlin.keyboard.send_key_down(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data ) # handles local and remote and special mouse keys

    def _pulse_off(self, data):
        ''' called when pulse is off '''
        press_keys, release_keys = data
        key : gremlin.keyboard.Key
        (is_local, is_remote) = self.action_data.sendFlags()
        
        for key in release_keys:
            if self.verbose: syslog.info(f"Pulse OFF [{key.debug_name}]")
            gremlin.keyboard.send_key_up(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data) # handles local and remote and special mouse keys

    def pulse_start(self, data : tuple, duration : float, interval : float):
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
            args = data
            worker = gremlin.repeater.PulseWorker(duration, interval, self._pulse_on, self._pulse_off, data = args)
            self.pulse_worker_map[key] = worker

        if self.verbose: syslog.info(f"\tactivate")
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
        ''' handles inbound input event to process '''
        
        if not self.output_enabled:
            # ignore if output is disabled
            return


        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        auto_release = False


        #verbose = True
        is_local, is_remote = self.action_data.sendFlags()
        is_pressed = event.is_pressed
        mode = self.action_data.mode
        

        if self.action_data.mode == KeyboardOutputMode.Hold:
            trigger = True # always trigger in hold mode to match the input 
            auto_release = False # disable auto-release for hold mode
        else:
            trigger = (is_pressed and self.action_data.exec_on_press) or \
                    (not is_pressed and self.action_data.exec_on_release)
  
            if trigger and self.action_data.exec_on_release:
                # if exec on release, must use auto-release
                is_pressed = True
                auto_release = True


        
        if is_pressed:
            # joystick values or virtual button
            # verbose = True
            if not trigger:
                # nothing to process
                return True 

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
                        if self.use_macros:
                            id = gremlin.macro.MacroManager().queue_macro(self.release, is_local, is_remote, client_list = self.client_list)
                            self.registerMacro(id)
                        else:
                             for key in self._release_keys:
                                if verbose: syslog.info(f"KEYBOARD: press: send key release: {key}")
                                if key.is_mouse:
                                    gremlin.macro._send_mouse_button(key.mouse_button, False, is_local, is_remote, wheel_factor=self.action_data.wheel_factor, client_list = self.client_list)
                                else:
                                    gremlin.keyboard.send_key_up(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)

                case KeyboardOutputMode.Press:
                    # press mode and not already triggered
                    if self.has_keys:
                        self.is_pressed = True
                        if verbose:
                            syslog.info(f"MapToKeyboardEx: press")
                        if self.use_macros:
                            id = gremlin.macro.MacroManager().queue_macro(self.press_macro, is_local, is_remote, client_list = self.client_list)
                            self.registerMacro(id)
                        else:
                            for key in self._press_keys:
                                if verbose: syslog.info(f"KEYBOARD: press: send key press: {key}")
                                if key.is_mouse:
                                    gremlin.macro._send_mouse_button(key.mouse_button, True, is_local, is_remote, wheel_factor=self.action_data.wheel_factor, client_list = self.client_list)
                                else:
                                    gremlin.keyboard.send_key_down(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)

                case KeyboardOutputMode.Hold:
                    if self.has_keys:
                        
                        if event.is_virtual_button:
                            # if using a virtual button to trigger - disable the auto-release
                            auto_release = False
                        if is_pressed and not auto_release:
                            # press event
                            if self.use_macros:
                                id = gremlin.macro.MacroManager().queue_macro(self.press_macro, is_local, is_remote, client_list = self.client_list)
                                self.registerMacro(id)
                            else:
                                # send direct
                                key : gremlin.keyboard.Key
                                for key in self._press_keys:
                                    if verbose: syslog.info(f"KEYBOARD: hold: send key press: {key}")
                                    if key.is_mouse:
                                        gremlin.macro._send_mouse_button(key.mouse_button, True, is_local, is_remote, wheel_factor=self.action_data.wheel_factor, client_list = self.client_list)
                                    else:
                                        gremlin.keyboard.send_key_down(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)

                            self._hold_keys = self._release_keys.copy() # remember the keys we pressed (in release order)



                        if is_pressed and auto_release: 
                            if self.use_macros:
                                id = gremlin.macro.MacroManager().queue_macro(self.press_macro, is_local, is_remote)
                                self.registerMacro(id)
                                callback = lambda : gremlin.macro.MacroManager().queue_macro(self.release, is_local, is_remote, client_list = self.client_list)
                                CallbackActions().register_callback(callback, event)
                            else:
                                key : gremlin.keyboard.Key
                                for key in self._release_keys:
                                    if verbose: syslog.info(f"send key press (autorelease): {key}")
                                    if key.is_mouse:
                                        gremlin.macro._send_mouse_button(key.mouse_button, True, is_local, is_remote, wheel_factor=self.action_data.wheel_factor, client_list = self.client_list)
                                    else:
                                        gremlin.keyboard.send_key_down(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)

                                callback = self._manual_release
                                CallbackActions().register_callback(callback, event)

                case KeyboardOutputMode.Pulse:
                    # make and break with delay
                    if self.has_keys:
                        if is_pressed:
                            if verbose: syslog.info(f"MapToKeyboardEx: pulse")
                            repeat_interval = -1 # do not repeat
                            self.pulse_start((self._press_keys, self._release_keys), self.action_data.delay/1000, repeat_interval)
                        else:
                            # stop pulsing on release
                            self.pulse_stop()

                case KeyboardOutputMode.Toggle:
                    if self.has_keys:
                        if is_pressed:
                            for key in self._press_keys:
                                if verbose: syslog.info(f"MapToKeyboardEx: toggle")
                                el = gremlin.event_handler.EventListener()
                                state = el.get_key_state(key)
                                if key.is_mouse:
                                    gremlin.macro._send_mouse_button(key.mouse_button, not state, is_local, is_remote, wheel_factor=self.action_data.wheel_factor, client_list = self.client_list )
                                else:
                                    if state:
                                        # key is down, send up
                                        gremlin.keyboard.send_key_up(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)
                                    else:
                                        # key is up, send down
                                        gremlin.keyboard.send_key_down(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)

                               

                case KeyboardOutputMode.AutoRepeat:
                    # setup autorepeat thread
                    repeat_interval =  self.action_data.autorepeat_delay/1000
                    self.pulse_start((self._press_keys, self._release_keys), self.action_data.delay/1000, repeat_interval)
        else:
            # release the keys
            if self.has_keys:
                match mode:
                    case KeyboardOutputMode.Hold:
                        if self.use_macros:
                            if verbose: syslog.info(f"HOLD: send key releases (macro mode)")
                            gremlin.macro.MacroManager().queue_macro(self.release)
                        else:
                            # not using macros
                            for key in self._release_keys:
                                if verbose: syslog.info(f"HOLD: send key release: {key}")
                                gremlin.keyboard.send_key_up(key, is_local, is_remote, client_list = self.client_list, hwnd = self.target_hwnd, extra_data = self.extra_data)

                        self._hold_keys.clear()

                    case KeyboardOutputMode.AutoRepeat:
                        if verbose: syslog.info(f"AUTOREPEAT: stop")
                        self.pulse_stop()
                        self._autorepeat_clear()
                    

        
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
            time.sleep(0.001)
        if verbose:
            log_info("autorepeat stop...")
        macro_mgr.clear_queue()
            
            
        

            


class MapToKeyboardEx(gremlin.base_profile.AbstractAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """

    name = "Map to Keyboard/Mouse Ex"
    tag = "map-to-keyboard-ex"
    hint = '''Enhanced keyboard mapper.
Can also send mouse buttons, mouse wheel events.'''

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
        self.sync_mode = SyncMode.Ignore # ignore by default
        self.exec_on_press = True # true if trigger should execute on input press event
        self.exec_on_release = False # true if trigger should execute on input release event
        self.wheel_factor = 1 # factor for wheel motion

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
        stub = ""
        match self.mode:
            case KeyboardOutputMode.Pulse:
                stub = f" (pulse) delay (ms): [{self._delay}] repeat (ms): [{self._autorepeat_delay}]"  
            
        return f"KeyboardEx: ({self.mode.name}) {self._get_display_keys()}{stub}"


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

    def _parse_xml(self, node, data = None, extra_data = None):
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
                case "toggle":
                    self.mode = KeyboardOutputMode.Toggle
                case _:
                    # default
                    self.mode = KeyboardOutputMode.Hold


        if "delay" in node.attrib:
            self.delay = safe_read(node, "delay", int, 250) # pulse delay in milliseconds

        if "interval" in node.attrib:
            self.autorepeat_delay = safe_read(node, "interval", int, 250) # pulse interval milliseconds

        for child in node.findall("key"):
            key = None
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

        if "sync-mode" in node.attrib:
            self.sync_mode = SyncMode(safe_read(node,"sync-mode", int, 0))

        if "exec_on_press" in node.attrib:
            self.exec_on_press = safe_read(node,"exec_on_press",bool, True)
        if "exec_on_release" in node.attrib:
            self.exec_on_release = safe_read(node,"exec_on_release",bool, False)       

        self.wheel_factor = safe_read(node,"wheel-factor",int, 1)     

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
                comment = f"virtual: {key.name} 0x{key.virtual_code:x}/{key.virtual_code} scan code: 0x{key.scan_code:x}/{key.scan_code} extended: {key.is_extended}"
                key_node = ElementTree.Element("key")
                key_node.set("virtual-code", str(virtual_code))
                key_node.set("scan-code", str(scan_code))
                key_node.set("extended", str(is_extended))
                # useful for xml readability purposes = what scan code is this
                key_node.set("description", key.name)
                node_comment = etree.Comment(comment)
                node.append(node_comment)
                node.append(key_node)

        node.set("sync-mode", safe_format(self.sync_mode, int))     
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))                   
        node.set("wheel-factor", safe_format(self.wheel_factor, int))

        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise

        """
        # return true by default so the action gets saved even if it doesn't do anything
        return True
    
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell

        table = ReportTable(cellpadding=4)

        key_stub = ""
        for key in self.keys:
            name = gremlin.keyboard.KeyMap.get_name(key)
            if key_stub:
                key_stub += " "
            key_stub += name

        table.addField("Key", html.escape(key_stub))
        table.addField("Mode", self.mode.name)
        table.addField("Wheel Factor", str(self.wheel_factor))
        match self.mode:
            case KeyboardOutputMode.Pulse:
                table.addField("Delay", f"{self.delay} ms")
            case KeyboardOutputMode.AutoRepeat:
                table.addField("Delay", f"{self.delay }ms")
                table.addField("Repeat Delay", f"{self._autorepeat_delay} ms")


        return table.to_html()    



version = 1
name = "map-to-keyboard-ex"
create = MapToKeyboardEx
