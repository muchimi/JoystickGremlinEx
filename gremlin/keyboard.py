# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2022 Lionel Ott
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


import ctypes
import logging
from ctypes import wintypes

import win32api
import win32con

from gremlin.base_classes import TraceableList
from gremlin.types import MouseButton


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
 


_keyboard_modifiers = ["leftshift","leftcontrol","leftalt","rightshift","rightcontrol","rightalt","leftwin","rightwin"]


class Key:

    """Represents a single key on the keyboard or mouse together with its different representations and latching (multiple keys) 
     
    If in mouse mode, the virtual code contains the MouseButton enum value for which mouse button this key corresponds to.  
       
        
    """

    def __init__(self, name = None, scan_code = None, is_extended = None, virtual_code = None, is_mouse = False):
        """Creates a new Key instance.

        :param name the name used to refer to this key
        :param scan_code the scan code set 1 value corresponding
            to this key
        :param is_extended boolean indicating if the key is an
            extended scan code or not
        :param virtual_code the virtual key code assigned to this
            key by windows
        :param is_mouse True if the key is a mouse button instead of a key - if set only the name is used
        """


        
        lookup_name = None
        if not name:
            name = "Not configured"
        if not scan_code:
            scan_code = 0
        if not virtual_code:
            virtual_code = 0
        if not is_extended:
            is_extended = False


        self._mouse_button = None
        if is_mouse or scan_code >= 0x1000:
            if scan_code >= 0x1000:
                # convert fake scan code to convert to a mouse button
                mouse_button = MouseButton(scan_code - 0x1000)
            else:
                # use the given name
                mouse_button = mouse_from_name(name)
            if not mouse_button:
                raise ValueError(f"Don't know how to handle mouse button name: {name}")
            scan_code = mouse_button.value + 0x1000 # makes it unique in the tuple
            virtual_code = scan_code
            name = MouseButton.to_string(mouse_button)
            lookup_name = name
            is_mouse = True
            self._mouse_button = mouse_button

            

        else:
            # regular key
            if scan_code > 0:
                if not virtual_code:
                    virtual_code = _scan_code_to_virtual_code(scan_code, is_extended)
                    k = key_from_code(scan_code, is_extended)
                    name = k.name
                    

        self._is_mouse = is_mouse
        self._scan_code = scan_code
        self._is_extended = is_extended
        self._name = name
        self._latched_name = ""
        
        self._virtual_code = virtual_code
        self._lookup_name = lookup_name
        self._latched_keys = TraceableList() #[] # list of keys latched to this keystroke (modifiers)
        # self._latched_keys.add_callback(self._changed_cb)
        self._update()

    # duplicate
    def duplicate(self):
        '''' creates a copy of this key '''
        new_key = Key(scan_code = self.scan_code, is_extended=self.is_extended, is_mouse = self.is_mouse)
        return new_key

    @property
    def sequence(self):
        ''' returns a list of (scan_code, extended) tuples for all latched keys in this sequence '''
        sequence = [self.index_tuple()]
        lk: Key
        for lk in self._latched_keys:
            sequence.append(lk.index_tuple())
        return sequence

    @property
    def mouse_button(self) -> MouseButton:
        ''' returns a mouse button if the key is a virtual mouse button or mouse wheel '''
        return self._mouse_button
    
    @mouse_button.setter
    def mouse_button(self, button : MouseButton):
        ''' sets a mouse button '''
        scan_code = button.value + 0x1000
        self._mouse_button = button
        self._is_mouse = True
        self.scan_code = scan_code

    # def _changed_cb(self, owner , action, index, value):
    #     logging.getLogger("system").info(f"Key {self.name} latch change: {action} index: {index} value: {value}")
    #     self._update()

    def _update(self):
        if len(self._latched_keys) > 0:
            keys = [self]
            keys.extend(self._latched_keys)
            # order the key by modifier 
            keys = sort_keys(keys)
            result = ""
            for key in keys:
                if result:
                    result += " + "
                result += key._name
            name = result
        else: 
            name = ""
        self._latched_name = name



    @property
    def name(self):
        return self._latched_name if self._latched_name else self._name

    @property
    def scan_code(self):
        if self._scan_code == 20:
            pass
        return self._scan_code
    
    @property
    def is_extended(self):
        return self._is_extended
    
    def index_tuple(self):
        ''' returns the gremlin index key for this key '''
        return  (self._scan_code, self._is_extended)
    
    @property
    def is_mouse(self):
        return self._is_mouse
    

    @property
    def latched(self):
        ''' returns true if the current latch keys are pressed (runtime only) '''
        from gremlin.event_handler import EventListener
        el = EventListener()
        # assume the current key is pressed
        latched = el.get_key_state(self)
        if latched and len(self._latched_keys) > 0:
            # check the latched keys
            for key in self._latched_keys:
                if not el.get_key_state(key):
                    # one key isn't pressed = not latched
                    return False

        #logging.getLogger("system").info(f"latch check: key {self.name} latched: {latched}")
        return latched
    
    @property
    def state(self):
        ''' returns the pressed state of the current key '''
        from gremlin.event_handler import EventListener
        el = EventListener()
        return el.get_key_state(self)
        
    @property
    def data(self):
        # unique key for this key
        return self.__hash__()



    @property
    def virtual_code(self):
        return self._virtual_code

    @property
    def lookup_name(self):
        if self._lookup_name is not None:
            return self._lookup_name
        else:
            return self._name
        
    @property
    def message_key(self):
        return {self._scan_code, self._is_extended}

    @lookup_name.setter
    def lookup_name(self, name):
        from gremlin import error
        if self._lookup_name is not None:
            raise error.KeyboardError("Setting lookup name repeatedly")
        self._lookup_name = name

        self._update()

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        # computes the hash value for this key combination
        #if self._latched_keys:
        data = f"{self._scan_code:x}{1 if self._is_extended else 0}"
        for key in self._latched_keys:
            data += f"|{key._scan_code:x}{1 if key._is_extended else 0}"
        return data.__hash__()

        # if self._is_extended:
        #     return (0x0E << 8) + self._scan_code
        # else:
        #     return self._scan_code
        
    def __lt__(self, other):
        return self.name < other.name
    
    def __le__(self, other):
        return self.name <= other.name
    
    def __gt__(self, other):
        return self.name > other.name
    
    def __ge__(self, other):
        return self.name > other.name
    
    def __str__(self):
        return self.name
    

    
    
    
    @property
    def latched_keys(self) -> TraceableList:
        ''' list of key objects that are latched to this key (modifiers)'''
        return self._latched_keys
    @latched_keys.setter
    def latched_keys(self, value):
        self._latched_keys.clear()
        self._latched_keys.extend(value)
    
    @property
    def is_latched(self):
        ''' true if this key is latched '''
        return len(self._latched_keys) > 0
    
    @property
    def is_modifier(self):
        ''' true if the key is a modifier '''
        return self._lookup_name in _keyboard_modifiers
    
    def modifier_order(self):
        ''' returns the order of the modifier '''
        lookup_name = self.lookup_name
        if lookup_name in _keyboard_modifiers:
            return _keyboard_modifiers.index(lookup_name)
        return -1 # not found
    
    def key_order(self):
        ''' gets a unique and predictable key index for ordering a key sequence
         
        Modifiers will be a lower index than normal character which will be lower than special keys
           
        '''
        lookup_name = self.lookup_name
        if lookup_name in _keyboard_modifiers:
            return self.modifier_order()
        
        # bump to next index
        start_index = 100
        
        if len(lookup_name) == 1:
            # single keys - use the ascii sequence
            value = ord(lookup_name)
            return start_index + value
        
        start_index = 1000
        # special keys
        special_names = [g_name_to_key.keys()]

        if self._lookup_name in special_names:
            value = special_names.index(lookup_name)
            return start_index + value
        
        # no clue
        return -1
    
         

def _scan_code_to_virtual_code(scan_code, is_extended):
    """Returns the virtual code corresponding to the given scan code.

    :param scan_code scan code value to translate
    :param is_extended whether or not the scan code is extended
    :return virtual code corresponding to the given scan code
    """

    if scan_code: 
        value = scan_code
        if is_extended:
            value = 0xe0 << 8 | scan_code

        virtual_code = _map_virtual_key_ex(value, 3, _get_keyboard_layout(0))
        return virtual_code
    return None


def _virtual_input_to_unicode(virtual_code):
    """Returns the unicode character corresponding to a given virtual code.

    :param virtual_code virtual code for which to return a unicode character
    :return unicode character corresponding to the given virtual code
    """

    if not virtual_code:
        return None

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


def send_key_down(key):
    """Sends the KEYDOWN event for a single key.

    :param key the key for which to send the KEYDOWN event
    """
    flags = win32con.KEYEVENTF_EXTENDEDKEY if key.is_extended else 0

    from gremlin import input_devices
    (is_local, is_remote) = input_devices.remote_state.state
    if is_local:
        win32api.keybd_event(key.virtual_code, key.scan_code, flags, 0)
    if is_remote:
        input_devices.remote_client.send_key(key.virtual_code, key.scan_code, flags )


def send_key_up(key):
    """Sends the KEYUP event for a single key.

    :param key the key for which to send the KEYUP event
    """

    from gremlin import input_devices
    flags = win32con.KEYEVENTF_EXTENDEDKEY if key.is_extended else 0
    flags |= win32con.KEYEVENTF_KEYUP


    (is_local, is_remote) = input_devices.remote_state.state
    if is_local:
        win32api.keybd_event(key.virtual_code, key.scan_code, flags, 0)
    if is_remote:
        input_devices.remote_client.send_key(key.virtual_code, key.scan_code, flags )

def mouse_from_name(name):
    ''' validates if this is a special mouse key - returns None if it is not'''
    from gremlin.types import MouseButton
    mouse_button = None
    name = name.lower()
    if name in ("mouse_1", "mouse_left", MouseButton.to_string(MouseButton.Left).lower()): # left button
        mouse_button = MouseButton.Left
    elif name in ("mouse_2", "mouse_right", MouseButton.to_string(MouseButton.Right).lower()): # right button
        mouse_button = MouseButton.Right
    elif name in ("mouse_3", "mouse_middle", MouseButton.to_string(MouseButton.Middle).lower()):
        mouse_button = MouseButton.Middle
    elif name in ("mouse_4", "mouse_forward", MouseButton.to_string(MouseButton.Forward).lower()):
        mouse_button = MouseButton.Forward
    elif name in ("mouse_5", "mouse_back", MouseButton.to_string(MouseButton.Back).lower()):
        mouse_button = MouseButton.Back
    elif name in ("mouse_up", "wheel_up", MouseButton.to_string(MouseButton.WheelUp).lower()):
        mouse_button = MouseButton.WheelUp
    elif name in ("mouse_down", "wheel_down", MouseButton.to_string(MouseButton.WheelDown).lower()):
        mouse_button = MouseButton.WheelDown
    elif name in ("mouse_wleft", "wheel_left", MouseButton.to_string(MouseButton.WheelLeft).lower()):
        mouse_button = MouseButton.WheelLeft
    elif name in ("mouse_wright", "wheel_right", MouseButton.to_string(MouseButton.WheelRight).lower()):
        mouse_button = MouseButton.WheelRight
    
    return mouse_button

def key_from_name(name, validate = False):
    """Returns the key corresponding to the provided name.

    If no key exists with the provided name None is returned.

    :param name the name of the key to return
    :return Key instance or None
    """
    global g_scan_code_to_key, g_name_to_key
    from gremlin import error


    # see if it's a mouse key
    mouse_button = mouse_from_name(name)
    if mouse_button:
        key = Key(name, is_mouse=True)
        return key    

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
        raise error.KeyboardError(
            f"Invalid key specified, {name}"
        )
    else:
        g_scan_code_to_key[(key.scan_code, key.is_extended)] = key
        g_name_to_key[key_name] = key
        return key


def sort_keys(keys):
    ''' sorts a list of keys so the keys are in a predictable order '''
    key: Key
    sequence = []
    for key in keys:
        index = key.key_order()
        sequence.append((key, index))
    
    sequence.sort(key = lambda x: x[1])
    keys_list = [k for (k, _) in sequence]
    return keys_list




def key_from_code(scan_code, is_extended):
    """Returns the key corresponding to the provided scan code.

    If no key exists with the provided scan code None is returned.

    :param scan_code the scan code of the desired key
    :param is_extended flag indicating if the key is extended
    :return Key instance or None
    """
    global g_scan_code_to_key, g_name_to_key
    from gremlin import error


    if scan_code >= 0x1000:
        # mouse special code
        key = Key(scan_code = scan_code, is_mouse = True)
        return key

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
        raise error.KeyboardError(
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
    "f13": Key("F13", 0x64, False, win32con.VK_F13),
    "f14": Key("F14", 0x65, False, win32con.VK_F14),
    "f15": Key("F15", 0x66, False, win32con.VK_F15),
    "f16": Key("F16", 0x67, False, win32con.VK_F16),
    "f17": Key("F17", 0x68, False, win32con.VK_F17),
    "f18": Key("F18", 0x69, False, win32con.VK_F18),
    "f19": Key("F19", 0x6a, False, win32con.VK_F19),    
    "f20": Key("F20", 0x6b, False, win32con.VK_F20),    
    "f21": Key("F21", 0x6c, False, win32con.VK_F21),    
    "f22": Key("F22", 0x6d, False, win32con.VK_F22),    
    "f23": Key("F23", 0x6e, False, win32con.VK_F23),    
    "f24": Key("F24", 0x76, False, win32con.VK_F24),   
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
