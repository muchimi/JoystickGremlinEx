# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2019 Lionel Ott - Modified by Muchimi (C) EMCS 2024 and other contributors
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

import collections
import ctypes
from ctypes import wintypes
import functools
import logging
import time
from threading import Event, Lock, Thread
from xml.etree import ElementTree

from PySide6 import QtCore

import win32con
import win32api

import gremlin
import gremlin.input_devices
from gremlin.singleton_decorator import SingletonDecorator




MacroEntry = collections.namedtuple(
    "MacroEntry",
    ["macro", "state", "is_local", "is_remote"]
)


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
        logging.getLogger("system").error(
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
    return Key(character, scan_code, is_extended, virtual_code)


def _send_key_down(key, is_local = True, is_remote = False, force_remote = False):
    """Sends the KEYDOWN event for a single key.

    :param key the key for which to send the KEYDOWN event
    """
    
    flags = win32con.KEYEVENTF_EXTENDEDKEY if key.is_extended else 0

    if is_local:
        win32api.keybd_event(key.virtual_code, key.scan_code, flags, 0)
    if is_remote:
        gremlin.input_devices.remote_client.send_key(key.virtual_code, key.scan_code, flags, force_remote)
    


def _send_key_up(key, is_local = True, is_remote = False, force_remote = False):
    """Sends the KEYUP event for a single key.

    :param key the key for which to send the KEYUP event
    """
    flags = win32con.KEYEVENTF_EXTENDEDKEY if key.is_extended else 0
    flags |= win32con.KEYEVENTF_KEYUP
    if is_local:
        win32api.keybd_event(key.virtual_code, key.scan_code, flags, 0)
    if is_remote:
        gremlin.input_devices.remote_client.send_key(key.virtual_code, key.scan_code, flags, force_remote )


@SingletonDecorator
class MacroManager:

    """Manages the proper dispatching and scheduling of macros."""

    def __init__(self):
        """Initializes the instance."""
        self._active = {}
        self._queue = []
        self._flags = {}
        self._flags_lock = Lock()
        self._queue_lock = Lock()

        # Default delay between subsequent message dispatch. This is to get
        # around some games not picking up messages if they are sent in too
        # quick a succession.
        self.default_delay = 0.05

        self._is_executing_exclusive = False
        self._is_running = False
        self._schedule_event = Event()

        self._run_scheduler_thread = None

    def start(self):
        """Starts the scheduler."""
        self._active = {}
        self._flags = {}
        self._is_running = True
        if self._run_scheduler_thread is None:
            self._run_scheduler_thread = Thread(target=self._run_scheduler)
        if not self._run_scheduler_thread.is_alive():
            self._run_scheduler_thread.start()

    def stop(self):
        """Stops the scheduler."""
        self._is_running = False
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

    def queue_macro(self, macro, is_local = None, is_remote = None):
        """Queues a macro in the schedule taking the repeat type into account.

        :param macro the macro to add to the scheduler
        """
        if isinstance(macro.repeat, ToggleRepeat) and macro.id in self._active:
            self.terminate_macro(macro)
        else:
            # Preprocess macro to contain pauses as necessary
            if not is_local:
                is_local = macro.is_local
            if not is_remote:
                is_remote = macro.is_remote

            self._preprocess_macro(macro)
            with self._queue_lock:
                self._queue.append(MacroEntry(macro, True, is_local, is_remote))
            self._schedule_event.set()

    def terminate_macro(self, macro):
        """Adds a termination request for a macro to the execution queue.

        :param macro the macro to terminate
        """
        self._queue.append(MacroEntry(macro, False, macro.is_local, macro.is_remote))
        self._schedule_event.set()

    def _run_scheduler(self):
        """Dispatches macros as required."""
        while self._is_running:
            # Wake up when the event triggers and reset it
            self._schedule_event.wait()
            self._schedule_event.clear()

            # Run scheduled macros and ensure exclusive ones run separately
            # from all other macros
            with self._queue_lock:
                entries_to_remove = []
                has_exclusive = False
                for i, entry in enumerate(self._queue):
                    # Terminate macro if needed
                    if entry.state is False:
                        if entry.macro.id in self._flags \
                                and self._flags[entry.macro.id]:
                            # Terminate currently running macro
                            with self._flags_lock:
                                self._flags[entry.macro.id] = False
                            # del self._queue[i]

                            # Remove all queued up macros with the same id as
                            # they should have been impossible to queue up
                            # in the first place
                            removal_list = []
                            for queue_entry in self._queue:
                                if queue_entry.macro.id == entry.macro.id:
                                    removal_list.append(queue_entry)
                            for queue_entry in removal_list:
                                self._queue.remove(queue_entry)
                    # Don't run a queued macro if the same instance is already
                    # running
                    elif entry.macro.id in self._active:
                        continue
                    # Handle exclusive macros
                    elif entry.macro.exclusive:
                        has_exclusive = True
                        if len(self._active) == 0:
                            self._dispatch_macro(entry.macro, entry.is_local, entry.is_remote)
                            self._is_executing_exclusive = True
                            entries_to_remove.append(entry)
                    # Start a queued up macro
                    elif not has_exclusive and not self._is_executing_exclusive:
                        self._dispatch_macro(entry.macro, entry.is_local, entry.is_remote)
                        entries_to_remove.append(entry)

                # Remove all entries we've processed
                for entry in entries_to_remove:
                    if entry in self._queue:
                        self._queue.remove(entry)

    def _dispatch_macro(self, macro, is_local = None, is_remote = None):
        """Dispatches a single macro to be run.

        :param macro the macro to dispatch
        :param is_local true if local control, set to None to use the macro flag
        :param is_remote true if remote control, set to None to use the macro flag
        """
        if macro.id not in self._active:
            self._active[macro.id] = macro
            Thread(target=functools.partial(self._execute_macro, macro, is_local, is_remote)).start()
        else:
            logging.getLogger("system").warning(
                "Attempting to dispatch an already running macro"
            )

    def _execute_macro(self, macro, is_local = None, is_remote = None):
        """Executes a given macro in a separate thread.

        This method will run all provided actions and once they all have been
        executed will remove the macro from the set of active macros and
        inform the scheduler of the completion.

        The macro flags is_local/is_remote control where the macro actions are sent

        :param macro the macro object to be executed
        """
        # Handle macros with a repeat mode
        # if not is_local:
        #     is_local = macro.is_local
        # if not is_remote:
        #     is_remote = macro.is_remote


        (state_is_local, state_is_remote) = gremlin.input_devices.remote_state.state
        if not is_remote:
            is_remote = state_is_remote
        if not is_local:
            is_local = state_is_local
        
        if macro.force_remote:
            is_remote = True
            is_local = False


        if macro.repeat is not None:
            delay = macro.repeat.delay

            with self._flags_lock:
                self._flags[macro.id] = True

            # Handle count repeat mode
            if isinstance(macro.repeat, CountRepeat):
                count = 0
                while count < macro.repeat.count and self._flags[macro.id]:
                    for action in macro.sequence:
                        action(is_local, is_remote)
                    count += 1
                    time.sleep(delay)

            # Handle continuous repeat modes
            elif type(macro.repeat) in [HoldRepeat, ToggleRepeat]:
                while self._flags[macro.id]:
                    for action in macro.sequence:
                        action(is_local, is_remote)
                    time.sleep(delay)

        # Handle simple one shot macros
        else:
            for action in macro.sequence:
                action(is_local, is_remote, macro.force_remote)
            # indicate the macro is done
            if macro.completed_callback:
                macro.completed_callback()

        # Remove macro from active set, notify manager, and remove any
        # potential callbacks
        del self._active[macro.id]
        if macro.exclusive:
            self._is_executing_exclusive = False
        with self._flags_lock:
            if macro.id in self._flags:
                self._flags[macro.id] = False
        self._schedule_event.set()

    def _preprocess_macro(self, macro):
        """Inserts pauses as necessary into the macro."""
        new_sequence = [macro.sequence[0]]
        for a1, a2 in zip(macro.sequence[:-1], macro.sequence[1:]):
            if isinstance(a1, PauseAction) or isinstance(a2, PauseAction):
                new_sequence.append(a2)
            else:
                new_sequence.append(PauseAction(self.default_delay))
                new_sequence.append(a2)
        macro._sequence = new_sequence


class Macro:

    """Represents a macro which can be executed."""

    

    # Unique identifier for each macro
    _next_macro_id = 0

    def __init__(self, is_local = None, is_remote = None, force_remote = None):
        """Creates a new macro instance.
        
        :is_local: if set, sends the macro output to the local client
        :is_remote: if set, sends the macro output to the remote client
        :force_remote: if set, forces the output to remote only
        
        """
        self._sequence = []
        self._id = Macro._next_macro_id
        Macro._next_macro_id += 1
        self.repeat = None
        self.exclusive = False
        self.completed_callback = None # callback called when macro completes
        

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
    def id(self):
        """Returns the unique id of this macro.

        :return unique id of this macro
        """
        return self._id
    
    @property
    def force_remote(self):
        return self._force_remote
    @force_remote.setter
    def force_remote(self, value):
        self._force_remote = value

    
    @property
    def is_local(self):
        ''' local control flag'''
        return self._is_local
    @is_local.setter
    def is_local(self, value):
        self._is_local = value

    @property
    def is_remote(self):
        ''' remote control flag'''
        return self._is_remote
    @is_remote.setter
    def is_remote(self, value):
        self._is_remote = value

    @property
    def sequence(self):
        """Returns the action sequence of this macro.

        :return action sequence
        """
        return self._sequence

    def add_action(self, action):
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
        if isinstance(key, str):
            key = key_from_name(key)
        elif isinstance(key, Key):
            pass
        else:
            raise gremlin.error.KeyboardError("Invalid key specified")

        self._sequence.append(KeyAction(key, is_pressed))


class AbstractAction:

    """Base class for all macro action."""

    def __call__(self, is_local = True, is_remote = False, force_remote = False):
        raise gremlin.error.MissingImplementationError(
            "AbstractAction.__call__ not implemented in derived class."
        )
    
    def _update_flags(self, is_local = None, is_remote = None, force_remote = None):
        # updates flags based on local/remote overrides
        (state_is_local, state_is_remote) = gremlin.input_devices.remote_state.state
        if is_local is None:
            is_local = state_is_local
        if is_remote is None:
            is_remote = state_is_remote
        if force_remote is not None and force_remote:
            is_local = False
            is_remote = True  
        return (is_local, is_remote)


class JoystickAction(AbstractAction):

    """Joystick input action for a macro."""

    def __init__(self, device_guid, input_type, input_id, value, axis_type="absolute"):
        """Creates a new JoystickAction instance for use in a macro.

        :param device_guid GUID of the device generating the input
        :param input_type type of input being generated
        :param input_id id of the input being generated
        :param value the value of the generated input
        :param axis_type if an axis is used, how to interpret the value
        """
        self.device_guid = device_guid
        self.input_type = input_type
        self.input_id = input_id
        self.value = value
        self.axis_type = axis_type

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        """Emits an Event instance through the EventListener system."""
        el = gremlin.event_handler.EventListener()
        if self.input_type == gremlin.common.InputType.JoystickAxis:
            event = gremlin.event_handler.Event(
                event_type=self.input_type,
                device_guid=self.device_guid,
                identifier=self.input_id,
                value=self.value,
                force_remote = force_remote
            )
        elif self.input_type == gremlin.common.InputType.JoystickButton:
            event = gremlin.event_handler.Event(
                event_type=self.input_type,
                device_guid=self.device_guid,
                identifier=self.input_id,
                is_pressed=self.value,
                force_remote = force_remote
            )
        elif self.input_type == gremlin.common.InputType.JoystickHat:
            event = gremlin.event_handler.Event(
                event_type=self.input_type,
                device_guid=self.device_guid,
                identifier=self.input_id,
                value=self.value,
                force_remote = force_remote
            )

        el.joystick_event.emit(event)




class KeyAction(AbstractAction):

    """Key to press or release by a macro."""

    def __init__(self, key, is_pressed):
        """Creates a new KeyAction object for use in a macro.

        :param key the key to use in the action
        :param is_pressed True if the key should be pressed, False otherwise
        """
        if not isinstance(key, Key):
            raise gremlin.error.KeyboardError("Invalid Key instance provided")
        self.key = key
        self.is_pressed = is_pressed

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        if self.is_pressed:
            _send_key_down(self.key, is_local, is_remote, force_remote)
        else:
            _send_key_up(self.key, is_local, is_remote, force_remote)
        


class MouseButtonAction(AbstractAction):

    """Mouse button action."""

    def __init__(self, button, is_pressed):
        """Creates a new MouseButtonAction object for use in a macro.

        :param button the button to use in the action
        :param is_pressed True if the button should be pressed, False otherwise
        """
        if not isinstance(button, gremlin.common.MouseButton):
            raise gremlin.error.MouseError("Invalid mouse button provided")

        self.button = button
        self.is_pressed = is_pressed

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        if self.button == gremlin.common.MouseButton.WheelDown:
            if is_local:
                gremlin.sendinput.mouse_wheel(1)
            if is_remote:
                gremlin.input_devices.remote_client.send_mouse_wheel(1, force_remote)

        elif self.button == gremlin.common.MouseButton.WheelUp:
            if is_local:
                gremlin.sendinput.mouse_wheel(-1)
            if is_remote:
                gremlin.input_devices.remote_client.send_mouse_wheel(-1, force_remote)
        else:
            if is_local:
                if self.is_pressed:
                    if is_remote:
                        gremlin.sendinput.mouse_press(self.button)
                else:
                    gremlin.sendinput.mouse_release(self.button)
            if is_remote:
                gremlin.input_devices.remote_client.send_mouse_button(self.button, self.is_pressed, force_remote)


class MouseMotionAction(AbstractAction):

    """Mouse motion action."""

    def __init__(self, dx, dy):
        """Creates a new MouseMotionAction object for use in a macro.

        :param dx change along the X axis
        :param dy change along the Y axis
        """
        self.dx = int(dx)
        self.dy = int(dy)

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        if is_local:
            gremlin.sendinput.mouse_relative_motion(self.dx, self.dy)
        if is_remote:
            gremlin.input_devices.remote_client.send_mouse_motion(self.dx, self.dy, force_remote)


class PauseAction(AbstractAction):

    """Represents the pause in a macro between pressed."""

    def __init__(self, duration, duration_max = 0, is_random = False):
        """Creates a new Pause object for use in a macro.

        :param duration the duration in seconds of the pause
        """
        self.duration = duration
        self.duration_max = duration_max
        self.is_random = is_random

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        import random
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

        time.sleep(duration)


class VJoyMacroAction(AbstractAction):

    """VJoy input action for a macro."""

    def __init__(self, vjoy_id, input_type, input_id, value, axis_type="absolute"):
        """Creates a new JoystickAction instance for use in a macro.

        :param vjoy_id id of the vjoy device which is to be modified
        :param input_type type of input being generated
        :param input_id id of the input being generated
        :param value the value of the generated input
        :param axis_type if an axis is used, how to interpret the value
        """
        self.vjoy_id = vjoy_id
        self.input_type = input_type
        self.input_id = input_id
        self.value = value
        self.axis_type = axis_type

    def __call__(self, is_local = None, is_remote = None, force_remote = None):
        # ignore passed local/remote states
        
        is_local, is_remote = self._update_flags(is_local, is_remote, force_remote)
        vjoy = gremlin.joystick_handling.VJoyProxy()[self.vjoy_id]
        if self.input_type == gremlin.common.InputType.JoystickAxis:
            if self.axis_type == "absolute":
                if is_local:
                    vjoy.axis(self.input_id).value = self.value
                if is_remote:
                    gremlin.input_devices.remote_client.send_axis(self.vjoy_id, self.input_id, self.value, force_remote)

            elif self.axis_type == "relative":

                if is_local:
                    vjoy.axis(self.input_id).value = max(
                        -1.0,
                        min(1.0, vjoy.axis(self.input_id).value + self.value)
                    )
                if is_remote:
                    gremlin.input_devices.remote_client.send_relative_axis(self.vjoy_id, self.input_id, self.value, force_remote)
        elif self.input_type == gremlin.common.InputType.JoystickButton:
            if is_local:
                vjoy.button(self.input_id).is_pressed = self.value
            if is_remote:
                gremlin.input_devices.remote_client.send_button(self.vjoy_id, self.input_id, self.value, force_remote)
        elif self.input_type == gremlin.common.InputType.JoystickHat:
            if is_local:
                vjoy.hat(self.input_id).direction = self.value
            if is_remote:
                gremlin.input_devices.remote_client.send_hat(self.vjoy_id, self.input_id, self.value, force_remote)


class RemoteControlAction(AbstractAction):
    ''' remote control actions for a macro '''
    

    def __init__(self):
        self.command =  gremlin.input_devices.VjoyAction.VJoyEnableRemoteOnly

    def __call__(self, is_local = True, is_remote = False, force_remote= False):
        ''' execute the mode change '''
        gremlin.input_devices.remote_state.mode = self.command
    




class Key:

    """Represents a single key on the keyboard together with its
    different representations.
    """

    def __init__(self, name, scan_code, is_extended, virtual_code):
        """Creates a new Key instance.

        :param name the name used to refer to this key
        :param scan_code the scan code set 1 value corresponding
            to this key
        :param is_extended boolean indicating if the key is an
            extended scan code or not
        :param virtual_code the virtual key code assigned to this
            key by windows
        """
        self._name = name
        self._scan_code = scan_code
        self._is_extended = is_extended
        self._virtual_code = virtual_code
        self._lookup_name = None

    @staticmethod
    def from_key(k : gremlin.keyboard.Key):
        ''' converts a keyboard key to a macro key '''
        if k:
            return Key(k.name, k.scan_code, k.is_extended, k.virtual_code)
        return None
        

    @property
    def name(self):
        return self._name

    @property
    def scan_code(self):
        return self._scan_code

    @property
    def is_extended(self):
        return self._is_extended

    @property
    def virtual_code(self):
        return self._virtual_code

    @property
    def lookup_name(self):
        if self._lookup_name is not None:
            return self._lookup_name
        else:
            return self._name

    @lookup_name.setter
    def lookup_name(self, name):
        if self._lookup_name is not None:
            raise gremlin.error.KeyboardError("Setting lookup name repeatedly")
        self._lookup_name = name

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        if self._is_extended:
            return (0x0E << 8) + self._scan_code
        else:
            return self._scan_code


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

    def from_xml(self, node):
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

    def from_xml(self, node):
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

    def from_xml(self, node):
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

    def from_xml(self, node):
        """Populates the instance's data from the provided XML node.

        :param node XML node containing data with which to populate the instance
        """
        self.delay = float(node.get("delay"))


def key_from_name(name, validate = False):
    """Returns the key corresponding to the provided name.

    If no key exists with the provided name None is returned.

    :param name the name of the key to return
    :return Key instance or None
    """
    global g_scan_code_to_key, g_name_to_key

    # Attempt to located the key in our database and return it if successful
    key_name = name.lower().replace(" ", "")
    key = g_name_to_key.get(key_name, None)
    if key is not None:
        return key

    # Attempt to create the key to store and return if successful
    key = _unicode_to_key(name)
    if key is None:
        if validate:
            # skip error reporting on validation
            return None
        
        logging.getLogger("system").warning(
            f"Invalid key name specified \"{name}\""
        )
        raise gremlin.error.KeyboardError(
            f"Invalid key specified, {name}"
        )
    else:
        g_scan_code_to_key[(key.scan_code, key.is_extended)] = key
        g_name_to_key[key_name] = key
        return key


def key_from_code(scan_code, is_extended):
    """Returns the key corresponding to the provided scan code.

    If no key exists with the provided scan code None is returned.

    :param scan_code the scan code of the desired key
    :param is_extended flag indicating if the key is extended
    :return Key instance or None
    """
    global g_scan_code_to_key, g_name_to_key

    # Attempt to located the key in our database and return it if successful
    key = g_scan_code_to_key.get((scan_code, is_extended), None)
    if key is not None:
        return key

    # Attempt to create the key to store and return if successful
    virtual_code = _scan_code_to_virtual_code(scan_code, is_extended)
    name = _virtual_input_to_unicode(virtual_code)

    if virtual_code == 0xFF or name is None:
        logging.getLogger("system").warning(
            f"Invalid scan code specified ({scan_code}, {is_extended})"
        )
        raise gremlin.error.KeyboardError(
            f"Invalid scan code specified ({scan_code}, {is_extended})"
        )
    else:
        key = Key(name, scan_code, is_extended, virtual_code)
        g_scan_code_to_key[(scan_code, is_extended)] = key
        g_name_to_key[name.lower()] = key
        return key


# Storage for the various keys, prepopulated with non alphabetical keys
g_scan_code_to_key = {}
g_name_to_key = {
    # Function keys
    "f1": Key("F1", 0x3b, False, win32con.VK_F1),
    "f2": Key("F2", 0x3c, False, win32con.VK_F2),
    "f3": Key("F3", 0x3d, False, win32con.VK_F3),
    "f4": Key("F4", 0x3e, False, win32con.VK_F4),
    "f5": Key("F5", 0x3f, False, win32con.VK_F5),
    "f6": Key("F6", 0x40, False, win32con.VK_F6),
    "f7": Key("F7", 0x41, False, win32con.VK_F7),
    "f8": Key("F8", 0x42, False, win32con.VK_F8),
    "f9": Key("F9", 0x43, False, win32con.VK_F9),
    "f10": Key("F10", 0x44, False, win32con.VK_F10),
    "f11": Key("F11", 0x57, False, win32con.VK_F11),
    "f12": Key("F12", 0x58, False, win32con.VK_F12),
    # Control keys
    "printscreen": Key("Print Screen", 0x37, True, win32con.VK_PRINT),
    "scrolllock": Key("Scroll Lock", 0x46, False, win32con.VK_SCROLL),
    "pause": Key("Pause", 0x45, False, win32con.VK_PAUSE),
    # 6 control block
    "insert": Key("Insert", 0x52, True, win32con.VK_INSERT),
    "home": Key("Home", 0x47, True, win32con.VK_HOME),
    "pageup": Key("PageUp", 0x49, True, win32con.VK_PRIOR),
    "delete": Key("Delete", 0x53, True, win32con.VK_DELETE),
    "end": Key("End", 0x4f, True, win32con.VK_END),
    "pagedown": Key("PageDown", 0x51, True, win32con.VK_NEXT),
    # Arrow keys
    "up": Key("Up", 0x48, True, win32con.VK_UP),
    "left": Key("Left", 0x4b, True, win32con.VK_LEFT),
    "down": Key("Down", 0x50, True, win32con.VK_DOWN),
    "right": Key("Right", 0x4d, True, win32con.VK_RIGHT),
    # Numpad
    "numlock": Key("NumLock", 0x45, True, win32con.VK_NUMLOCK),
    "npdivide": Key("Numpad /", 0x35, True, win32con.VK_DIVIDE),
    "npmultiply": Key("Numpad *", 0x37, False, win32con.VK_MULTIPLY),
    "npminus": Key("Numpad -", 0x4a, False, win32con.VK_SUBTRACT),
    "npplus": Key("Numpad +", 0x4e, False, win32con.VK_ADD),
    "npenter": Key("Numpad Enter", 0x1c, True, win32con.VK_SEPARATOR),
    "npdelete": Key("Numpad Delete", 0x53, False, win32con.VK_DECIMAL),
    "np0": Key("Numpad 0", 0x52, False, win32con.VK_NUMPAD0),
    "np1": Key("Numpad 1", 0x4f, False, win32con.VK_NUMPAD1),
    "np2": Key("Numpad 2", 0x50, False, win32con.VK_NUMPAD2),
    "np3": Key("Numpad 3", 0x51, False, win32con.VK_NUMPAD3),
    "np4": Key("Numpad 4", 0x4b, False, win32con.VK_NUMPAD4),
    "np5": Key("Numpad 5", 0x4c, False, win32con.VK_NUMPAD5),
    "np6": Key("Numpad 6", 0x4d, False, win32con.VK_NUMPAD6),
    "np7": Key("Numpad 7", 0x47, False, win32con.VK_NUMPAD7),
    "np8": Key("Numpad 8", 0x48, False, win32con.VK_NUMPAD8),
    "np9": Key("Numpad 9", 0x49, False, win32con.VK_NUMPAD9),
    # Misc keys
    "backspace": Key("Backspace", 0x0e, False, win32con.VK_BACK),
    "space": Key("Space", 0x39, False, win32con.VK_SPACE),
    "tab": Key("Tab", 0x0f, False, win32con.VK_TAB),
    "capslock": Key("CapsLock", 0x3a, False, win32con.VK_CAPITAL),
    "leftshift": Key("Left Shift", 0x2a, False, win32con.VK_LSHIFT),
    "leftcontrol": Key("Left Control", 0x1d, False, win32con.VK_LCONTROL),
    "leftwin": Key("Left Win", 0x5b, True, win32con.VK_LWIN),
    "leftalt": Key("Left Alt", 0x38, False, win32con.VK_LMENU),
    # Right shift key appears to exist in both extended and
    # non-extended version
    "rightshift": Key("Right Shift", 0x36, False, win32con.VK_RSHIFT),
    "rightshift2": Key("Right Shift", 0x36, True, win32con.VK_RSHIFT),
    "rightcontrol": Key("Right Control", 0x1d, True, win32con.VK_RCONTROL),
    "rightwin": Key("Right Win", 0x5c, True, win32con.VK_RWIN),
    "rightalt": Key("Right Alt", 0x38, True, win32con.VK_RMENU),
    "apps": Key("Apps", 0x5d, True, win32con.VK_APPS),
    "enter": Key("Enter", 0x1c, False, win32con.VK_RETURN),
    "esc": Key("Esc", 0x01, False, win32con.VK_ESCAPE)
}


# Populate the scan code based lookup table
for name_, key_ in g_name_to_key.items():
    assert isinstance(key_, Key)
    key_.lookup_name = name_
    g_scan_code_to_key[(key_.scan_code, key_.is_extended)] = key_
