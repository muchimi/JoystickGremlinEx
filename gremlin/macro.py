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
import collections
import ctypes
from ctypes import wintypes
import functools
import logging
import time
from threading import Event, Lock, Thread
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets

import win32con
import win32api

import gremlin
import gremlin.config
import gremlin.event_handler
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.input_types import InputType
import gremlin.error
import gremlin.keyboard
import gremlin.sendinput
import gremlin.types
import gremlin.remote

import gremlin.util
import enum
from enum import auto
from psygnal import Signal

syslog = logging.getLogger("system")


class MacroEntry():
    __slots__ = ["macro", "state", "is_local", "is_remote","mode"]
    def __init__(self, macro, state, is_local, is_remote, mode):
        self.macro = macro
        self.state = state
        self.is_local = is_local
        self.is_remote = is_remote
        self.mode = mode


class MacroState(enum.Enum):
    ''' macro scheduling states '''
    Idle = auto() # macro is not running and not scheduled
    Running = auto() # macro is actively running
    Scheduled = auto() # macro is schedule to run
    Abort = auto() # macro abort




def _create_function(lib_name, fn_name, param_types, return_type):
    """Creates a handle to a windows dll library function.

    :param lib_name name of the library to retrieve a function handle from
    :param fn_name name of the function
    :param param_types input parameter types
    :param return_type return parameter type
    :return function handle
    """
    fn = getattr(ctypes.WinDLL(lib_name), fn_name)
    fn.argtypes = param_types
    fn.restype = return_type
    return fn


# https://msdn.microsoft.com/en-us/library/windows/desktop/ms646296(v=vs.85).aspx
_get_keyboard_layout = _create_function(
    "user32",
    "GetKeyboardLayout",
    [wintypes.DWORD],
    wintypes.HKL
)


# https://msdn.microsoft.com/en-us/library/windows/desktop/ms646299(v=vs.85).aspx
_get_keyboard_state = _create_function(
    "user32",
    "GetKeyboardState",
    [ctypes.POINTER(ctypes.c_char)],
    wintypes.BOOL
)


# https://msdn.microsoft.com/en-us/library/windows/desktop/ms646307(v=vs.85).aspx
_map_virtual_key_ex = _create_function(
    "user32",
    "MapVirtualKeyExW",
    [ctypes.c_uint, ctypes.c_uint, wintypes.HKL],
    ctypes.c_uint
)


# https://msdn.microsoft.com/en-us/library/windows/desktop/ms646322(v=vs.85).aspx
_to_unicode_ex = _create_function(
    "user32",
    "ToUnicodeEx",
    [
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_char),
        ctypes.POINTER(ctypes.c_wchar),
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_void_p
    ],
    ctypes.c_int
)


# https://msdn.microsoft.com/en-us/library/windows/desktop/ms646332(v=vs.85).aspx
_vk_key_scan_ex = _create_function(
    "user32",
    "VkKeyScanExW",
    [ctypes.c_wchar, wintypes.HKL],
    ctypes.c_short
)


def _scan_code_to_virtual_code(scan_code, is_extended):
    """Returns the virtual code corresponding to the given scan code.

    :param scan_code scan code value to translate
    :param is_extended whether or not the scan code is extended
    :return virtual code corresponding to the given scan code
    """
    value = scan_code
    if is_extended:
        value = 0xe0 << 8 | scan_code

    virtual_code = _map_virtual_key_ex(value, 3, _get_keyboard_layout(0))
    return virtual_code


def _virtual_input_to_unicode(virtual_code):
    """Returns the unicode character corresponding to a given virtual code.

    :param virtual_code virtual code for which to return a unicode character
    :return unicode character corresponding to the given virtual code
    """
    keyboard_layout = _get_keyboard_layout(0)
    output_buffer = ctypes.create_unicode_buffer(8)
    state_buffer = ctypes.create_string_buffer(256)

    if virtual_code == 0x7c:
        pass


    # Translate three times to get around dead keys showing up in funny ways
    # as the translation takes them into account for future keys
    state = _to_unicode_ex(
        virtual_code,
        0x00,
        state_buffer,
        output_buffer,
        8,
        0,
        keyboard_layout
    )
    state = _to_unicode_ex(
        virtual_code,
        0x00,
        state_buffer,
        output_buffer,
        8,
        0,
        keyboard_layout
    )
    state = _to_unicode_ex(
        virtual_code,
        0x00,
        state_buffer,
        output_buffer,
        8,
        0,
        keyboard_layout
    )

    if state == 0:
        syslog.error(
            f"No translation for key {hex(virtual_code)} available"
        )
        return str(hex(virtual_code))
    return output_buffer.value.upper()


def _unicode_to_key(character):
    """Returns a Key instance corresponding to the given character.

    :param character the character for which to generate a Key instance
    :return Key instance for the given character, or None if an error occurred
    """
    if len(character) != 1:
        return None

    virtual_code = _vk_key_scan_ex(character, _get_keyboard_layout(0)) & 0x00FF
    if virtual_code == 0xFF:
        return None

    code_value = _map_virtual_key_ex(virtual_code, 4, _get_keyboard_layout(0))
    scan_code = code_value & 0xFF
    is_extended = False
    if code_value << 8 & 0xE0 or code_value << 8 & 0xE1:
        is_extended = True
    return gremlin.keyboard.Key(character, scan_code, is_extended, virtual_code)


def _send_mouse_button(button_id, is_pressed, is_local = True, is_remote = False, force_remote = False, dbl_click = False, wheel_factor = 1):
        from gremlin.types import MouseButton
        import gremlin.sendinput
        import gremlin.input_devices

        if force_remote:
            is_remote = True
        if button_id in [MouseButton.WheelDown, MouseButton.WheelUp]:
            if is_pressed:
                direction = -wheel_factor
                if button_id == MouseButton.WheelDown:
                    direction = wheel_factor
                if is_local:
                    gremlin.sendinput.mouse_wheel(direction)
                if is_remote:
                    gremlin.remote.remote_client.send_mouse_wheel(direction)
        elif button_id in [MouseButton.WheelLeft, MouseButton.WheelRight]:
            if is_pressed:
                direction = -wheel_factor
                if button_id == MouseButton.WheelRight:
                    direction = wheel_factor
                if is_local:
                    gremlin.sendinput.mouse_h_wheel(direction)
                if is_remote:
                    gremlin.remote.remote_client.send_mouse_h_wheel(direction)                    
        else:
            if is_pressed:
                if is_local:
                    if dbl_click:
                        gremlin.sendinput.mouse_press_double_click(button_id)    
                    else:
                        gremlin.sendinput.mouse_press(button_id)
                if is_remote:
                    gremlin.remote.remote_client.send_mouse_button(button_id, True)
            else:
                if not dbl_click: # double click always releases - no need to release again
                    if is_local:
                        gremlin.sendinput.mouse_release(button_id)
                    if is_remote:
                        gremlin.remote.remote_client.send_mouse_button(button_id.value, False)


def _send_key_down(key, is_local = True, is_remote = False, force_remote = False):
    """Sends the KEYDOWN event for a single key.

    :param key the key for which to send the KEYDOWN event
    """
    assert key.virtual_code and key.scan_code, f"Invalid key: {key}"


    if key.is_mouse:
        # special handling of virtual keys for mouse buttons
        _send_mouse_button(key.mouse_button, True, is_local, is_remote, force_remote )
        return

    if force_remote:
        is_remote = True
    flags = win32con.KEYEVENTF_EXTENDEDKEY if key.is_extended else 0

    if is_local:
        gremlin.sendinput.send_key(key.virtual_code, key.scan_code, flags)

        # win32api.keybd_event(key.virtual_code, key.scan_code, flags, 0)
    if is_remote:
        gremlin.remote.remote_client.send_key(key.virtual_code, key.scan_code, flags, force_remote)
    


def _send_key_up(key, is_local = True, is_remote = False, force_remote = False):
    """Sends the KEYUP event for a single key.
    :param key the key for which to send the KEYUP event
    """
    if key.is_mouse:
        # special handling of virtual keys for mouse buttons
        _send_mouse_button(key.mouse_button, False, is_local, is_remote, force_remote )
        return

    flags = win32con.KEYEVENTF_EXTENDEDKEY if key.is_extended else 0
    flags |= win32con.KEYEVENTF_KEYUP
    if is_local:
        gremlin.sendinput.send_key(key.virtual_code, key.scan_code, flags)
    if is_remote:
        gremlin.remote.remote_client.send_key(key.virtual_code, key.scan_code, flags, force_remote )

def key_from_code(scan_code, is_extended):
    ''' returns a key from a code '''
    return gremlin.keyboard.key_from_code(scan_code, is_extended)

def key_from_name(name, validate = False):
    ''' returns a key from a lookup name '''
    return gremlin.keyboard.key_from_name(name, validate)



@SingletonDecorator
class MacroManager(QtCore.QObject):

    """Manages the proper dispatching and scheduling of macros."""

    def __init__(self):
        """Initializes the instance."""
        super().__init__()
        self.id = "8cdd6c7503cf40c0a8c99375489cfd51"
        self._active = {}
        self._queue = collections.deque()
        self._flags = {}
        self._flags_lock = Lock()
        self._queue_lock = Lock()

        self.el = gremlin.event_handler.EventListener()

        # Default delay between subsequent message dispatch. This is to get
        # around some games not picking up messages if they are sent in too
        # quick a succession.
        self.default_delay = 0.025

        self._is_executing_exclusive = False
        self._is_running = False
        self._schedule_event = Event() # used to step through macro executions

        self._run_scheduler_thread = None
        self.el.profile_stop.connect(self._profile_stop)
        self.el.profile_start.connect(self._profile_start)
        self.el.runtime_mode_changed.connect(self._handle_mode_changed)
    
        
        config = gremlin.config.Configuration()
        self._max_concurrent = config.max_concurrent_macro
        self._mode_affinity = config.macro_mode_affinity
        self._hook_mode_change = False # true if mode change allowed hook enabled


    @QtCore.Slot()
    def _profile_stop(self):
        ''' triggered when profiles stop '''
        self.stop()

    @QtCore.Slot()
    def _profile_start(self):
        self.start()

    def _clear_queue(self):
        ''' clears the macro queue '''
        with self._queue_lock:
            self._queue.clear()

    def _handle_mode_changed(self, mode : str):
        ''' called when the runtime mode has changed '''
        if self._mode_affinity:
            verbose = gremlin.config.Configuration().verbose_mode_macro
            with self._queue_lock:
                # remove any queued macros that do not match the new runtime mode
                remove_list = [m.macro for m in self._queue if m.mode != mode]
                run_list = [m for m in self._queue if m.mode == mode]
                self._queue = collections.deque(run_list)
                
                for macro in remove_list:
                    if macro.id in self._active:
                        if verbose: syslog.info(f"MACRO: terminating macro: {macro.id}")
                        self.terminate_macro(macro)

    def _mode_change_allowed_callback(self, id : str) -> bool:
        ''' called when a mode change is requested to see if the mode change should go through '''
        if id == self.id:
            # ours
            result = len(self._active) == 0
            # syslog.info(f"MODE CHANGE CHECK: macro: [{self.id}] mode change allowed: {result}")
            return result # true if no macros are running right now
        return True # allowed

    def start(self):
        """Starts the scheduler."""
        
        self._active = {}
        self._flags = {}
        config = gremlin.config.Configuration()
        self._max_concurrent = config.max_concurrent_macro
        self._mode_affinity = config.macro_mode_affinity

        config = gremlin.config.Configuration()
        if not config.mode_change_aborts_sequence:
            self._hook_mode_change = True
            eh = gremlin.event_handler.EventHandler()
            eh.registerModeChangeHook(self.id, self._mode_change_allowed_callback)

        self._is_running = True
        self._clear_queue()
        if self._run_scheduler_thread is None:
            self._run_scheduler_thread = Thread(target=self._run_scheduler)
            self._run_scheduler_thread.setName("Macro scheduler")
        if not self._run_scheduler_thread.is_alive():
            self._run_scheduler_thread.start()
        


    def stop(self):
        """Stops the scheduler."""
        self._clear_queue()
        self._is_running = False

        if self._hook_mode_change:
            eh = gremlin.event_handler.EventHandler()
            eh.unregisterModeChangeHook(self.id)
            self._hook_mode_change = False

        if self._run_scheduler_thread is not None and \
                self._run_scheduler_thread.is_alive():

            # Terminate the scheduler
            self._schedule_event.set()
            self._run_scheduler_thread.join()
            self._run_scheduler_thread = None

            # Terminate any macro that is still active
            with self._flags_lock:
                for key, value in self._flags.items():
                    self._flags[key] = False

    def queue_macro(self, macro : Macro, is_local : bool = None, is_remote : bool = None):
        """Queues a macro in the schedule taking the repeat type into account.

        :param macro: the macro to add to the scheduler
        :param is_local: local flag (leave default for local execution or set to True)
        :param is_remote: remote flag (set to True for remote execution or set to )
        :param completion_callback: callback to call when the step completes, optional params(id) where ID is the macro step id returned by the call
        :returns id: a unique ID for the macro step
        """
        
        verbose = gremlin.config.Configuration().verbose_mode_macro
        mode = gremlin.shared_state.current_mode # current profile mode
        

        if isinstance(macro.repeat, ToggleRepeat) and macro.id in self._active:
            self.terminate_macro(macro)
            return

        if macro.state != MacroState.Idle:
            if verbose: syslog.info(f"MACRO: QUEUE: skipping queuing of macro [{macro.id}] owner: [{macro.ownerId}] because the state [{macro.state.name} is not idle.")
            return
        
        macro.state = MacroState.Scheduled


        # syslog = logging.getLogger("system")
        
        if verbose:
            syslog.info(f"MACRO: queue macro ID [{macro.id}]")
            action : MacroAbstractAction
            for action in macro.sequence:
                syslog.info(f"\t{str(action)}")
                
        if isinstance(macro.repeat, ToggleRepeat) and macro.id in self._active:
            self.terminate_macro(macro)
        else:

            # ensure we are not executing too many macros
            if self._max_concurrent:
                count = len(self._queue)
                if count > self._max_concurrent:
                    syslog.error(f"MACRO: exceeded concurrent macro: {self._max_concurrent}")
                    return None


            # Preprocess macro to contain pauses as necessary
            if not is_local:
                is_local = macro.is_local
            if not is_remote:
                is_remote = macro.is_remote

            self._preprocess_macro(macro)
            with self._queue_lock:
                self._queue.append(MacroEntry(macro, True, is_local, is_remote, mode))
            self._schedule_event.set()

        return macro.id

    
    def clear_queue(self):
        ''' clears the current macro queue '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_macro
        if verbose: syslog.info("MACRO: clear queue")
        with self._queue_lock:
            self._queue.clear()
            self._schedule_event.set()
            

    def terminate_macro(self, macro : Macro):
        """Adds a termination request for a macro to the execution queue.

        :param macro the macro to terminate
        """
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_macro
        if verbose: syslog.info(f"MACRO: macro [{macro.id}] owner [{macro.ownerId}] terminate requested.")
        
        with self._queue_lock:
            mode = gremlin.shared_state.current_mode
            self._queue.append(MacroEntry(macro, False, macro.is_local, macro.is_remote,mode))
            macro.abort() # abort the macro
        self._schedule_event.set()

        # wait for it to terminate
        while macro.id in self._active:
            time.sleep(0.01)

        # mark it terminated
        if verbose: syslog.info(f"MACRO: macro [{macro.id}] owner [{macro.ownerId}] terminated.")
        macro.state = MacroState.Idle

    def _run_scheduler(self):
        """Dispatches macros as required."""

        while self._is_running:
            # Wake up when the event triggers and reset it
            # while not self._queue or not self._schedule_event.is_set():
            #     time.sleep(0.01)
            #     continue
            self._schedule_event.wait()
            self._schedule_event.clear()

            # Run scheduled macros and ensure exclusive ones run separately
            # from all other macros
            with self._queue_lock:
                entries_to_remove = []
                has_exclusive = False
                for entry in self._queue:
                    # Terminate macro if needed
                    if entry.state is False:
                        # entry marked as completed 
                        if entry.macro.id in self._flags and self._flags[entry.macro.id]:
                            # Terminate currently running macro
                            with self._flags_lock:
                                self._flags[entry.macro.id] = False
                                
                            removal_list = [e for e in self._queue if e.macro.id == e.macro.id]
             
                            for queue_entry in removal_list:
                                self._queue.remove(queue_entry)
                    elif entry.macro.id in self._active:
                        # don't dispatch a macro that is already scheduled and running
                        continue
                    # Handle exclusive macros
                    elif entry.macro.exclusive:
                        has_exclusive = True
                        if len(self._active) == 0:
                            if self._dispatch_macro(entry.macro, entry.is_local, entry.is_remote):
                                self._is_executing_exclusive = True
                                entries_to_remove.append(entry)
                    # Start a queued up macro
                    elif not has_exclusive and not self._is_executing_exclusive:
                        if self._dispatch_macro(entry.macro, entry.is_local, entry.is_remote):
                            entries_to_remove.append(entry)

                # Remove all entries we've processed
                for entry in entries_to_remove:
                    if entry in self._queue:
                     
                        self._queue.remove(entry)

    def _dispatch_macro(self, macro : Macro, is_local : bool = None, is_remote : bool = None) -> bool:
        """Dispatches a single macro to be run.

        :param macro the macro to dispatch
        :param is_local true if local control, set to None to use the macro flag
        :param is_remote true if remote control, set to None to use the macro flag
        """

        if macro.id not in self._active and not macro.state == MacroState.Running:
            if self._mode_affinity:
                mode = gremlin.shared_state.runtime_mode
                if macro.mode and macro.mode != mode:
                    syslog.warning(f"MACRO: affinity: discard macro due to mode change: [{macro.id}] macro mode: [{macro.mode}] current profile mode [{mode}] ")    
                    macro.state = MacroState.Idle # return to idle
                    return False

            # add the macro to the active queue
            self._active[macro.id] = macro 
            macro.state = MacroState.Running
            Thread(target=functools.partial(self._execute_macro, macro, is_local, is_remote)).start()
        else:
            syslog.warning(f"Attempting to dispatch an already running macro: ID: {macro.id}")
            return False
        return True

    def _execute_macro(self, macro : Macro, is_local : bool = None, is_remote : bool = None):
        """Executes a given macro in a separate thread.

        This method will run all provided actions and once they all have been
        executed will remove the macro from the set of active macros and
        inform the scheduler of the completion.

        The macro flags is_local/is_remote control where the macro actions are sent

        :param macro the macro object to be executed
        """
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_macro
        if verbose: syslog.info(f"MACRO: execute [{macro.id}]")
        (state_is_local, state_is_remote) = gremlin.remote.remote_state.state
        if not is_remote:
            is_remote = state_is_remote
        if not is_local:
            is_local = state_is_local
        
        if macro.force_remote:
            is_remote = True
            is_local = False


        if macro.repeat is not None:
            delay = macro.repeat.delay

            # mark the macro as repeating
            with self._flags_lock:
                self._flags[macro.id] = True

            # Handle count repeat mode
            if isinstance(macro.repeat, CountRepeat):
                count = 0
                if verbose: syslog.info(f"\tMACRO: autorepeat id [{macro.id}]")
                while count < macro.repeat.count and self._flags[macro.id] and not macro.aborted:
                    for action in macro.sequence:
                        if macro.aborted: break
                        if verbose: syslog.info(f"\tAction: {str(action)}")
                        action(is_local, is_remote)
                    count += 1
                    time.sleep(delay)

            # Handle continuous repeat modes
            elif type(macro.repeat) in [HoldRepeat, ToggleRepeat]:
                while self._flags[macro.id] and not macro.aborted:
                    for action in macro.sequence:
                        if macro.aborted: break
                        action(is_local, is_remote)
                    time.sleep(delay)


        # Handle simple one shot macros
        else:
            if verbose: 
                msg = "".join(f"{str(a)} " for a in macro.sequence)
                syslog.info(f"\tMACRO: single shot: id: [{macro.id} {len(macro.sequence)} {msg}")
            for action in macro.sequence:
                if macro.aborted:
                    break
                action(is_local, is_remote, macro.force_remote)


        macro.state = MacroState.Idle
        if verbose: syslog.info(f"MACRO: [{macro.id}] owner [{macro.ownerId}] completed.")

        # indicate the macro is done
        if macro.completed_callback:
            macro.completed_callback()

        self.el.macro_step_completed.emit(macro.id) # indicate the macro has been completed
        

        # Remove macro from active set, notify manager, and remove any
        # potential callbacks
        try:
            if macro.id in self._active:
                del self._active[macro.id]
            else:
                syslog.error(f"MACRO: attempt to delete macro id [{macro.id}] that no longer exists in active macro list")
            if macro.exclusive:
                self._is_executing_exclusive = False
            with self._flags_lock:
                if macro.id in self._flags:
                    self._flags[macro.id] = False
        except:
            pass

        # trigger next step
        self._schedule_event.set()

    def _preprocess_macro(self, macro):
        """Inserts pauses as necessary into the macro."""
        if macro._sequence:
            new_sequence = [macro._sequence[0]]
            a1 = a2 = None
            for a1, a2 in zip(macro._sequence[:-1], macro._sequence[1:]):
                if isinstance(a1, PauseAction) or isinstance(a2, PauseAction) or \
                    isinstance(a1, ProcessEventsAction) or isinstance(a2, ProcessEventsAction):
                    new_sequence.append(a2)
                else:
                    new_sequence.append(ProcessEventsAction())
                    #new_sequence.append(PauseAction(self.default_delay))
                    new_sequence.append(a2)
            # add a process step after the last step
            if isinstance(a2, ProcessEventsAction):
                new_sequence.append(ProcessEventsAction())
            macro._sequence = new_sequence


class Macro:

    """Represents a macro which can be executed."""

    # Unique identifier for each macro - bumps by one for each new macro
    _next_macro_id = 0

    def __init__(self, owner_id : str = None, is_local = None, is_remote = None, force_remote = None, mode = None):
        """Creates a new macro instance.
        
        :is_local: if set, sends the macro output to the local client
        :is_remote: if set, sends the macro output to the remote client
        :force_remote: if set, forces the output to remote only
        
        """
        self._sequence = []
        self._owner_id = owner_id # who owns this macro
        self._id = Macro._next_macro_id
        Macro._next_macro_id += 1
        self.repeat = None
        self.exclusive = False
        self.completed_callback = None # callback called when macro completes
        self._state = MacroState.Idle
        self.mode = mode
        


        # flag set if we're forcing remote mode execution
        if force_remote:
            self._force_remote = force_remote
        else:
            self._force_remote = False

        # flag if the macro runs locally (default)
        if not is_local:
            self._is_local = True
        else:
            self._is_local = is_local

        # flag if macro runs remotely 
        if not is_remote:
            self._is_remote = False
        else:
            self._is_remote = is_remote

    @property
    def id(self) -> int:
        ''' unique macro id'''
        return self._id
    
    @property 
    def aborted(self):
        return self._state == MacroState.Abort
    
    def abort(self):
        ''' tell the macro to abort '''
        self._state = MacroState.Abort
    
    @property
    def state(self) -> MacroState:
        return self._state
    @state.setter
    def state(self, value : MacroState):
        self._state = value
    
    @property
    def ownerId(self) -> str:
        return self._owner_id
    @ownerId.setter
    def ownerId(self, value : str):
        self._owner_id = value
    
    @property
    def force_remote(self) -> bool:
        return self._force_remote
        
    @force_remote.setter
    def force_remote(self, value : bool):
        self._force_remote = value

    
    @property
    def is_local(self) -> bool:
        ''' local control flag'''
        return self._is_local
    @is_local.setter
    def is_local(self, value : bool):
        self._is_local = value

    @property
    def is_remote(self) -> bool:
        ''' remote control flag'''
        return self._is_remote
    @is_remote.setter
    def is_remote(self, value : bool):
        self._is_remote = value

    @property
    def sequence(self) -> list:
        """Returns the action sequence of this macro.

        :return action sequence
        """
        return self._sequence

    def add_action(self, action : MacroAbstractAction):
        """Adds an action to the list of actions to perform.

        :param action the action to add
        """
        self._sequence.append(action)

    def pause(self, duration):
        """Adds a pause of the given duration to the macro.

        :param duration the duration of the pause in seconds
        """
        self._sequence.append(PauseAction(duration))

    def press(self, key):
        """Presses the specified key down.

        :param key the key to press
        """
        self.action(key, True)

    def release(self, key):
        """Releases the specified key.

        :param key the key to release
        """
        self.action(key, False)

    def tap(self, key):
        """Taps the specified key.

        :param key the key to tap
        """
        self.action(key, True)
        self.action(key, False)

    def action(self, key, is_pressed):
        """Adds the specified action to the sequence.

        :param key the key involved in the action
        :param is_pressed boolean indicating if the key is pressed
            (True) or released (False)
        """
        from gremlin.keyboard import Key, KeyMap
        if isinstance(key, str):
            key = KeyMap.find_by_name(key)
        elif isinstance(key, Key):
            pass
        elif isinstance(key, int):
            key = KeyMap.find_virtual(key)
        elif isinstance(key, tuple):
            key = KeyMap.find(key[0],key[1])
        else:
            raise gremlin.error.KeyboardError("Invalid key specified")

        self._sequence.append(KeyAction(key, is_pressed))


class MacroAbstractAction(QtCore.QObject):

    """Base class for all macro action."""

    changed = Signal() # fires when the action changes
    idChanged = Signal() # fires if the ID changed

    def __init__(self, data = None):
        super().__init__()    
        self._data = data
        self._id = gremlin.util.get_guid() # unique ID of the macro

    @property
    def id(self):
        return self._id
    @id.setter
    def id(self, value):
        if self._id != value:
            self._id = value
            self.idChanged.emit()
   

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value

    def __getstate__(self):
        state = {}
        state['id'] = self._id
        return state

    def __setstate__(self, state):
        self._id = state['id']



    def __call__(self, is_local = True, is_remote = False, force_remote = False):
        raise gremlin.error.MissingImplementationError(
            "AbstractAction.__call__ not implemented in derived class."
        )
    
    def _update_flags(self, is_local = None, is_remote = None, force_remote = None):
        # updates flags based on local/remote overrides
        (state_is_local, state_is_remote) = gremlin.remote.remote_state.state
        if is_local is None:
            is_local = state_is_local
        if is_remote is None:
            is_remote = state_is_remote
        if force_remote is not None and force_remote:
            is_local = False
            is_remote = True  
        return (is_local, is_remote)


class JoystickAction(MacroAbstractAction):

    """Joystick input action for a macro."""

    def __init__(self, device_guid, input_type, input_id, value, axis_type="absolute"):
        """Creates a new JoystickAction instance for use in a macro.

        :param device_guid GUID of the device generating the input
        :param input_type type of input being generated
        :param input_id id of the input being generated
        :param value the value of the generated input
        :param axis_type if an axis is used, how to interpret the value
        """
        super().__init__()
        self.device_guid = device_guid
        self.input_type = input_type
        self.input_id = input_id
        if isinstance(value, bool):
            value = "pressed" if value else "release"
        self.value = value
        self.axis_type = axis_type

    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        state['device_guid'] = self.device_guid
        state['input_type'] = self.input_type
        state['input_id'] = self.input_id
        state['axis_type'] = self.axis_type
        state['value'] = self.value
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        self.device_guid = state['device_guid']
        self.input_type = state['input_type']
        self.input_id = state['input_id']
        self.axis_type = state['axis_type']
        self.value = state['value']
        

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        """Emits an Event instance through the EventListener system."""
        import gremlin.joystick_handling
        el = gremlin.event_handler.EventListener()
        extra_data = {"macro": True} # indicate the source of the event is a macro
        if self.input_type == InputType.JoystickAxis:
            event = gremlin.event_handler.Event(
                event_type=self.input_type,
                device_guid=self.device_guid,
                identifier=self.input_id,
                value=self.value,
                is_axis = True,
                force_remote = force_remote,
                extra_data = extra_data
            )
        elif self.input_type == InputType.JoystickButton:

            match self.value:
                case "toggle":
                    current = gremlin.joystick_handling.get_button(self.device_guid, self.input_id)
                    if current is not None:
                        is_pressed = not current
                case "press":
                    is_pressed = True
                case "release":
                    is_pressed = False
                case _:
                    syslog.error(f"VJOY MACRO ACTION: don't know how to handle button mode: [{self.value}]")
                    return # nothing to do
                
            event = gremlin.event_handler.Event(
                event_type=self.input_type,
                device_guid=self.device_guid,
                identifier=self.input_id,
                is_pressed= is_pressed,
                force_remote = force_remote,
                extra_data = extra_data
            )
        elif self.input_type == InputType.JoystickHat:
            event = gremlin.event_handler.Event(
                event_type=self.input_type,
                device_guid=self.device_guid,
                identifier=self.input_id,
                value=self.value,
                force_remote = force_remote,
                extra_data = extra_data
            )

        event.is_virtual = True
        
        el.joystick_event.emit(event)




class KeyAction(MacroAbstractAction):

    """Key to press or release by a macro."""

    def __init__(self, key, is_pressed):
        """Creates a new KeyAction object for use in a macro.

        :param key the key to use in the action
        :param is_pressed True if the key should be pressed, False otherwise
        """
        from gremlin.keyboard import Key
        super().__init__()

        if not isinstance(key, Key):
            raise gremlin.error.KeyboardError("Invalid Key instance provided")
        self.key = key
        self.is_pressed = is_pressed

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_macro        
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        if self.is_pressed:
            if verbose: syslog.info(f"MACRO: send key make: {self.key}")
            if self.key.is_mouse:
                _send_mouse_button(self.key.mouse_button, True, is_local, is_remote, force_remote)
                
            else:
                _send_key_down(self.key, is_local, is_remote, force_remote)
        else:
            if verbose: syslog.info(f"MACRO: send key break: {self.key}")
            if self.key.is_mouse:
                _send_mouse_button(self.key.mouse_button, False, is_local, is_remote, force_remote)
            else:
                _send_key_up(self.key, is_local, is_remote, force_remote)

    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        state['extended'] = self.key.is_extended
        state['scancode'] = self.key.scan_code
        state['is_pressed'] = self.is_pressed
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        is_extended = state['extended']
        scan_code = state['scancode']
        self.key = gremlin.keyboard.KeyMap.from_message_key(scan_code, is_extended)
        self.is_pressed = state['is_pressed']


    def __str__(self):
        if self.key:
            return f"KeyAction: {self.key.debug_name}"
        return "KeyAction: (no key)"
        


class MouseButtonAction(MacroAbstractAction):

    """Mouse button action."""

    def __init__(self, button, is_pressed):
        """Creates a new MouseButtonAction object for use in a macro.

        :param button the button to use in the action
        :param is_pressed True if the button should be pressed, False otherwise
        """
        super().__init__()
        if not isinstance(button, gremlin.types.MouseButton):
            raise gremlin.error.MouseError("Invalid mouse button provided")

        self.button = button
        self.is_pressed = is_pressed


    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        state['button'] = self.button
        state['is_pressed'] = self.is_pressed
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        self.button = state['button']
        self.is_pressed = state['is_pressed']

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_macro        
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        if self.button == gremlin.types.MouseButton.WheelDown:
            if is_local:
                if verbose: syslog.info(f"MACRO: mouse wheel up")
                gremlin.sendinput.mouse_wheel(1)
            if is_remote:
                gremlin.remote.remote_client.send_mouse_wheel(1, force_remote)

        elif self.button == gremlin.types.MouseButton.WheelUp:
            if is_local:
                if verbose: syslog.info(f"MACRO: mouse wheel down")
                gremlin.sendinput.mouse_wheel(-1)
            if is_remote:
                gremlin.remote.remote_client.send_mouse_wheel(-1, force_remote)
        else:
            if is_local:
                if self.is_pressed:
                    if verbose: syslog.info(f"MACRO: mouse press {self.button}")
                    gremlin.sendinput.mouse_press(self.button)
                else:
                    if verbose: syslog.info(f"MACRO: mouse release {self.button}")
                    gremlin.sendinput.mouse_release(self.button)
            if is_remote:
                gremlin.remote.remote_client.send_mouse_button(self.button, self.is_pressed, force_remote)


class MouseMotionAction(MacroAbstractAction):

    """Mouse motion action."""

    def __init__(self, dx, dy):
        """Creates a new MouseMotionAction object for use in a macro.

        :param dx change along the X axis
        :param dy change along the Y axis
        """
        super().__init__()
        self.dx = int(dx)
        self.dy = int(dy)

    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        state['dx'] = self.dx
        state['dy'] = self.dy
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        self.dx = state['dx']
        self.dy = state['dy']

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_macro        
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        if is_local:
            if verbose: syslog.info(f"MACRO: mouse motion {self.dx}, {self.dy}")
            gremlin.sendinput.mouse_relative_motion(self.dx, self.dy)
        if is_remote:
            gremlin.remote.remote_client.send_mouse_motion(self.dx, self.dy, force_remote)

class ProcessEventsAction(MacroAbstractAction):
    ''' process event action - allows queued events to complete '''
    def __init__(self):
        super().__init__()

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        verbose = gremlin.config.Configuration().verbose_mode_macro
        if verbose: syslog.info("MACRO: Process Events")
        QtWidgets.QApplication.processEvents()

class PauseAction(MacroAbstractAction):

    """Represents the pause in a macro between pressed."""

    def __init__(self, duration, duration_max = 0, is_random = False):
        """Creates a new Pause object for use in a macro.

        :param duration the duration in seconds of the pause
        """
        super().__init__()
        self.duration = duration
        self.duration_max = duration_max
        self.is_random = is_random

    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        state['duration'] = self.duration
        state['duration_max'] = self.duration_max
        state['is_random'] = self.is_random
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        self.duration = state['duration']
        self.duration_max = state['duration_max']
        self.is_random = state['is_random']


    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        import random
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_macro        
        # is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        if self.is_random:
            # random pause
            duration_min = self.duration
            duration_max = self.duration if self.duration_max == 0 else duration_min
            if duration_max != duration_min:
                # duration varies between min and max
                duration = random.uniform(duration_min, duration_max)
            else:
                # duration varies up to min
                duration = random.uniform(0, duration_min)
        else:
            duration = self.duration
        if verbose: syslog.info(f"MACRO: Pause action for {duration}")
        time.sleep(duration)

class GraphAction(MacroAbstractAction):
    ''' macro to execute an execution graph - used for sequencing/queuing functors in some containers '''
    def __init__(self, graph, event, value):
        ''' 
        :param graph: the execution graph to run
        :param event: the event to pass to the execution graph (will get cloned and stored)
        :param value: the action value to pass to the execution graph (will get cloned and stored)
        '''
        super().__init__()
        assert graph is not None,"GraphAction: graph cannot be null"

        self._graph = graph
        self._graph.graph_completed.connect(self._graph_completed)
        self._event = event.clone()
        self._value = value.clone()
        self._complete_event = None
        el = gremlin.event_handler.EventListener()
        el.profile_stop.connect(self._profile_stop)
        self._complete_event = Event()


    @QtCore.Slot()
    def _profile_stop(self):
        # kill any active macro if a profile terminates
        if self._complete_event is not None and not self._complete_event.is_set():
            # syslog = logging.getLogger("system")
            verbose = gremlin.config.Configuration().verbose_mode_condition
            if verbose: syslog.info("GraphAction: profile stop received - stopping execution")
            self._complete_event.set()
            time.sleep(0.01)


    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_condition
        if verbose: syslog.info(f"GraphAction: call {self.data}")
        if self._graph is not None:
            self._complete_event.clear()
            if verbose: syslog.info(f"GraphAction: execute {self.data}")
            self._graph.process_event(self._event, self._value)
            self._complete_event.wait()
            if verbose: syslog.info(f"GraphAction: completed {self.data}")
        

    @QtCore.Slot(object)
    def _graph_completed(self, graph):
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_condition
        if verbose: syslog.info(f"GraphAction: event: graph completed {self.data}")
        if graph == self._graph:
            if verbose: syslog.info(f"GraphAction: event: set {self.data}")
            self._complete_event.set()

class VJoyMacroAction(MacroAbstractAction):

    """VJoy input action for a macro."""

    def __init__(self, vjoy_id, input_type, input_id, value, axis_type="absolute"):
        """Creates a new JoystickAction instance for use in a macro.

        :param vjoy_id id of the vjoy device which is to be modified
        :param input_type type of input being generated
        :param input_id id of the input being generated
        :param value the value of the generated input
        :param axis_type if an axis is used, how to interpret the value
        """
        super().__init__()
        self.vjoy_id = vjoy_id
        self.input_type = input_type
        self.input_id = input_id
        self.value = value
        self.axis_type = axis_type

    @property
    def value(self):
        return self._value
    @value.setter
    def value(self, new_value):
        if self.input_type == InputType.JoystickButton:
            # convert boolean if provided
            if isinstance(new_value, bool):
                self._value = "press" if new_value else "release"
                return
            # handle case values
            new_value = new_value.casefold()
            match new_value:
                case "press":
                    self._value = "press"
                case "release":
                    self._value = "release"
                case "true":
                    self._value = "press"
                case "false":
                    self._value = "release"
                case "toggle":
                    self._value = "toggle"
                case _:
                    syslog.error(f"VJOY MACRO ACTION: don't know how to handle value: [{new_value}]")
        else:
            self._value = new_value
        
    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        # state['device_guid'] = self.device_guid
        state['vjoy_id'] = self.vjoy_id
        state['input_type'] = self.input_type
        state['input_id'] = self.input_id
        state['axis_type'] = self.axis_type
        state['value'] = self.value
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        # self.device_guid = state["device_guid"]
        self.vjoy_id = state['vjoy_id']
        self.input_type = state['input_type']
        self.input_id = state['input_id']
        self.axis_type = state['axis_type']
        self.value = state['value']

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        verbose = gremlin.config.Configuration().verbose_mode_macro
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        vjoy = gremlin.joystick_handling.VJoyProxy()[self.vjoy_id]
        if self.input_type == InputType.JoystickAxis:
            if self.axis_type == "absolute":
                if is_local:
                    vjoy.axis(self.input_id).value = self.value
                if is_remote:
                    gremlin.remote.remote_client.send_axis(self.vjoy_id, self.input_id, self.value, force_remote)

            elif self.axis_type == "relative":

                if is_local:
                    vjoy.axis(self.input_id).value = max(
                        -1.0,
                        min(1.0, vjoy.axis(self.input_id).value + self.value)
                    )
                if is_remote:
                    gremlin.remote.remote_client.send_relative_axis(self.vjoy_id, self.input_id, self.value, force_remote)
        elif self.input_type == InputType.JoystickButton:
            if is_local:
                if verbose: syslog.info(f"MACRO: vjoy {self.vjoy_id} button: {self.input_id} press: {self.value}")
                match self.value:
                    case "press":
                        is_pressed = True
                    case "release":
                        is_pressed = False
                    case "toggle":
                        is_pressed = not vjoy.button(self.input_id).is_pressed
                    case _:
                        syslog.error(f"VJOY MACRO BUTTON ACTION: don't know how to handle: [{self.value}]")
                        return

            vjoy.button(self.input_id).is_pressed = is_pressed
            if is_remote:
                gremlin.remote.remote_client.send_button(self.vjoy_id, self.input_id, is_pressed, force_remote)
        elif self.input_type == InputType.JoystickHat:
            if is_local:
                vjoy.hat(self.input_id).direction = self.value
            if is_remote:
                gremlin.remote.remote_client.send_hat(self.vjoy_id, self.input_id, self.value, force_remote)


class RemoteControlAction(MacroAbstractAction):
    ''' remote control actions for a macro '''
    

    def __init__(self):
        super().__init__()
        self.command =  gremlin.types.VjoyAction.VJoyEnableRemoteOnly

    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        state['command'] = self.command
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        self.command = state['command']
        
    

    def __call__(self, is_local = True, is_remote = False, force_remote= False):
        ''' execute the mode change '''
        verbose = gremlin.config.Configuration().verbose_mode_macro
        if verbose: syslog.info(f"MACRO: set remote control: {self.command.name}")
        gremlin.remote.remote_state.mode = self.command


class MacroDescriptionAction(MacroAbstractAction):
    '''description action for a macro'''
    def __init__(self):
        super().__init__()
        self.description = None
        self.log = False # true if the log is enabled


    def __call__(self, is_local = True, is_remote = False, force_remote= False):
        ''' execute '''
        if self.log or gremlin.config.Configuration().verbose_mode_macro:
            syslog.info(f"MACRO: description: {self.description}")


    def __getstate__(self):
        ''' serialize '''
        state = super().__getstate__()
        state['description'] = self.description
        state["log"] = self.log
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        super().__setstate__(state)
        self.description = state['description']
        self.log = state["log"]
                

class StateAction(MacroAbstractAction):
    ''' state action for a macro '''
    def __init__(self):
        import gremlin.ui.state_device
        super().__init__()
        self._state = None
        self._state_id = None
        self._register_check = True
        self.action = "press" # action requested 
        self.value = True # press by default
        sd = gremlin.ui.state_device.StateData()
        sd.crud.connect(self._data_changed)


    def __getstate__(self):
        ''' serialize '''
        
        state = super().__getstate__()
        #state['state'] = self._state
        state['state_id'] = self._state_id
        state['register_check'] = self._register_check
        state['value'] = self.value
        state['action'] = self.action
        return state

    def __setstate__(self, state):
        ''' deserialize '''
        import gremlin.ui.state_device
        super().__setstate__(state)
        #self._state  = state['state']
        self._state_id =  state['state_id']
        self._register_check = state['register_check']
        self.action = state['action']
        self.value = state['value'] 
        sd = gremlin.ui.state_device.StateData()
        self._state = sd.getStateById(self._state_id)
        # sd.crud.connect(self._data_changed)

    

    @property
    def key(self):
        if self._state:
            return self._state.key
        return None
    
    @key.setter
    def key(self, value):
        if self._state:
            self._state.key = value
    
    @property
    def description(self):
        if self._state:
            return self._state.description
        return None
    
    @property
    def state(self):
        return self._state
    @state.setter
    def state(self, data):
        if self._state_id != data.id:
            self._state = data
            self._state_id = data.id
            self.changed.emit() # indicate the action changed

    def _data_changed(self):
        self.changed.emit()
    
    


    def __call__(self, is_local = True, is_remote = False, force_remote= False):
        import gremlin.ui.state_device
        import gremlin.config
        sd = gremlin.ui.state_device.StateData()
        if self._register_check:
            # first time check for the state to exist
            if not sd.exists(self.key):
                sd.register(self.key, False, self.description)
            self._register_check = False

        verbose = gremlin.config.Configuration().verbose_mode_macro
        
        match self.action:
            case "press":
                sd.setValue(self.key, True)
                if verbose: syslog.info(f"MACRO: set state [Pressed]")
            case "release":
                sd.setValue(self.key, False)
                if verbose: syslog.info(f"MACRO: set state [Released]")
            case "toggle":
                sd.toggle(self.key)
                if verbose: syslog.info(f"MACRO: set state [Toggle] (new state: [{'Pressed' if sd.value(self.key) else 'Released'}])")
        






class AbstractRepeat:

    """Base class for all macro repeat modes."""

    def __init__(self, delay):
        """Creates a new instance.

        :param delay the delay between repetitions
        """
        self.delay = delay

    def to_xml(self):
        """Returns an XML node encoding the repeat information.

        :return XML node containing the instance's information
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractRepeat.to_xml not implemented in subclass."
        )

    def from_xml(self, node, data = None, extra_data = None):
        """Populates the instance's data from the provided XML node.

        :param node XML node containing data with which to populate the instance
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractRepeat.from_xml not implemented in subclass"
        )


class CountRepeat(AbstractRepeat):

    """Repeat mode which repeats the macro a fixed number of times."""

    def __init__(self, count=1, delay=0.1):
        """Creates a new instance.

        :param count the number of times to repeat the macro
        :param delay the delay between repetitions
        """
        super().__init__(delay)
        self.count = count

    def to_xml(self):
        """Returns an XML node encoding the repeat information.

        :return XML node containing the instance's information
        """
        node = ElementTree.Element("repeat")
        node.set("type", "count")
        node.set("count", str(self.count))
        node.set("delay", str(self.delay))
        return node

    def from_xml(self, node, data = None, extra_data = None):
        """Populates the instance's data from the provided XML node.

        :param node XML node containing data with which to populate the instance
        """
        self.delay = float(node.get("delay"))
        self.count = int(node.get("count"))


class ToggleRepeat(AbstractRepeat):

    """Repeat mode which repeats the macro as long as it hasn't been toggled
    off again after being toggled on."""

    def __init__(self, delay=0.1):
        """Creates a new instance.

        :param delay the delay between repetitions
        """
        super().__init__(delay)

    def to_xml(self):
        """Returns an XML node encoding the repeat information.

        :return XML node containing the instance's information
        """
        node = ElementTree.Element("repeat")
        node.set("type", "toggle")
        node.set("delay", str(self.delay))
        return node

    def from_xml(self, node, data = None, extra_data = None):
        """Populates the instance's data from the provided XML node.

        :param node XML node containing data with which to populate the instance
        """
        self.delay = float(node.get("delay"))


class HoldRepeat(AbstractRepeat):

    """Repeat mode which repeats the macro as long as the activation condition
    is being fulfilled or held down."""

    def __init__(self, delay=0.1):
        """Creates a new instance.

        :param delay the delay between repetitions
        """
        super().__init__(delay)

    def to_xml(self):
        """Returns an XML node encoding the repeat information.

        :return XML node containing the instance's information
        """
        node = ElementTree.Element("repeat")
        node.set("type", "hold")
        node.set("delay", str(self.delay))
        return node

    def from_xml(self, node, data = None, extra_data = None):
        """Populates the instance's data from the provided XML node.

        :param node XML node containing data with which to populate the instance
        """
        self.delay = float(node.get("delay"))

