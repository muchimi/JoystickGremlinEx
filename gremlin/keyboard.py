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
import enum
import win32api
import win32con

# from gremlin.base_classes import TraceableList
from gremlin.types import MouseButton
# from gremlin.singleton_decorator import SingletonDecorator
import gremlin.config

user32 = ctypes.WinDLL("user32")

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
 



class Key():

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


        
        
        if scan_code is None:
            scan_code = 0
        if virtual_code is None:
            virtual_code = 0
        if is_extended  is None:
            is_extended = False
        if is_mouse is None:
            is_mouse = False

        self._lookup_name = None
        self._latched_code = ""
        self._latched_name = ""
        
        self._latched_keys = [] # TraceableList() #[] # list of keys latched to this keystroke (modifiers)
        # self._latched_keys.add_callback(self._changed_cb)            

        if not name:
            self._load(scan_code, is_extended, virtual_code, is_mouse)

        self._scan_code = scan_code
        self._is_extended = is_extended
        self._virtual_code = virtual_code            


        self._name = name
        self._is_mouse = is_mouse
        self._update()


    @property
    def virtual_code(self):
        return self._virtual_code


    @property
    def scan_code(self):
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


    def _load(self, scan_code, is_extended, virtual_code, is_mouse):
        self._mouse_button = None
        name = None
        
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
            self._lookup_name = name

            if name and len(name)==1:
                name = name.upper()
            self._name = name

            is_mouse = True
            self._mouse_button = mouse_button
            

        else:
            # regular key

            if virtual_code > 0 and scan_code == 0:
                # get scan code from VK
                scan_code, is_extended = KeyMap.find_virtual(virtual_code)

            if scan_code > 0:
                key = KeyMap.find(scan_code, is_extended)
                if key is not None:
                    self._name = key.name
                    self._lookup_name = key.lookup_name

        self._scan_code = scan_code
        self._is_extended = is_extended
        self._virtual_code = virtual_code
        
        self._update()


    # duplicate
    def duplicate(self):
        '''' creates a copy of this key '''
        import copy
        new_key = copy.deepcopy(self)
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
    def mouse_button(self):
        ''' returns a mouse button if the key is a virtual mouse button or mouse wheel '''
        return self._mouse_button
    
    @mouse_button.setter
    def mouse_button(self, button):
        ''' sets a mouse button '''
        scan_code = button.value + 0x1000
        self._mouse_button = button
        self._is_mouse = True
        self.scan_code = scan_code
        self._update()

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
            code  = ""
            for key in keys:
                if result:
                    result += " + "
                if code:
                    code += " + "
                result += key._name
                code += f"0x{key._scan_code:X}{'_EX' if key._is_extended else ''}"
            self._latched_name = result
        else: 
            code = f"0x{self._scan_code:X}{'_EX' if self._is_extended else ''}"
            self._latched_name = ""
        self._latched_code = code
        




        

    @property
    def name(self):
        return self._name
    
    @property
    def latched_name(self):
        return self._latched_name if self._latched_name else self._name

    @property
    def latched_code(self):
        return self._latched_code


    @property
    def lookup_name(self):
        if self._lookup_name is not None:
            return self._lookup_name
        else:
            return self._name    

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
    def is_latched(self):
        ''' returns true if the key has latched components '''
        return len(self._latched_keys) > 0
    
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
    def message_key(self):
        return {self._scan_code, self._is_extended}


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
    def latched_keys(self):
        ''' list of key objects that are latched to this key (modifiers)'''
        return self._latched_keys
    
    @latched_keys.setter
    def latched_keys(self, value):
        self._latched_keys.clear()
        self._latched_keys.extend(value)
        self._update()
    
    @property
    def is_latched(self):
        ''' true if this key is latched '''
        return len(self._latched_keys) > 0
    
    @property
    def is_modifier(self):
        ''' true if the key is a modifier '''
        return self._lookup_name in KeyMap._keyboard_modifiers
    
    def modifier_order(self):
        ''' returns the order of the modifier '''
        lookup_name = self.lookup_name
        modifiers = KeyMap._keyboard_modifiers
        if lookup_name in modifiers:
            return modifiers.index(lookup_name)
        return -1 # not found
    
    def key_order(self):
        ''' gets a unique and predictable key index for ordering a key sequence
         
        Modifiers will be a lower index than normal character which will be lower than special keys
           
        '''
        lookup_name = self.lookup_name.lower()
        if lookup_name in KeyMap._keyboard_modifiers:
            return self.modifier_order()
        
        # bump to next index
        start_index = 100
        
        if len(lookup_name) == 1:
            # single keys - use the ascii sequence
            value = ord(lookup_name)
            return start_index + value
        
        start_index = 1000
        # special keys
        special = KeyMap._keyboard_special
        if lookup_name in special:
            value = special.index(lookup_name)
            return start_index + value
        
        # no clue
        return -1
    
    


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
    if name in ("mouse_1", "mouse_left", MouseButton.to_string(MouseButton.Left).lower()): 
        mouse_button = MouseButton.Left
    elif name in ("mouse_2", "mouse_right", MouseButton.to_string(MouseButton.Middle).lower()):
        mouse_button = MouseButton.Middle
    elif name in ("mouse_3", "mouse_middle", MouseButton.to_string(MouseButton.Right).lower()):
        mouse_button = MouseButton.Right
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
        key_name = MouseButton.to_string(mouse_button)
        scan_code = 0x1000 + mouse_button.value
        is_extended = False
        key = Key(key_name, scan_code, is_extended, 0, is_mouse=True)
        return key    

    # Attempt to located the key in our database and return it if successful
    key_name = name.lower().replace(" ", "")

       
    key = KeyMap.find_by_name(key_name)
    if key is not None:
        return key

    # Attempt to create the key to store and return if successful
    key = KeyMap.unicode_to_key(name)
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
        KeyMap.register(key) 
        return key


def sort_keys(keys):
    ''' sorts a list of keys so the keys are in a predictable order '''
    key: Key
    sequence = []
    for key in keys:
        index = key.key_order()
        sequence.append((key, index))
    
    sequence.sort(key = lambda x: x[1])
    keys_list = [pair[0] for pair in sequence]
    return keys_list

def key_name_from_code(scan_code, is_extended):
    ''' gets the key name '''


    if scan_code >= 0x1000:
        scan_code -= 0x1000
        return MouseButton.to_string(scan_code)
    
 
    
    # Attempt to located the key in our database and return it if successful
    key = KeyMap.find(scan_code, is_extended)
    if key:
        return key.name
    
    # Attempt to create the key to store and return if successful

    virtual_code = KeyMap.scan_code_to_virtual_code(scan_code, is_extended)
    name = KeyMap.virtual_input_to_unicode(virtual_code)
    return name




def key_from_code(scan_code, is_extended):
    """Returns the key corresponding to the provided scan code.

    If no key exists with the provided scan code None is returned.

    :param scan_code the scan code of the desired key
    :param is_extended flag indicating if the key is extended
    :return Key instance or None
    """
    
    import copy

    if scan_code >= 0x1000:
        # mouse special code
        key = Key(scan_code = scan_code, is_mouse = True)
        return key
    
    # Attempt to located the key in our database and return it if successful
    key = KeyMap.find(scan_code, is_extended)
    if key is not None:
        return copy.deepcopy(key)
        
    
    # Attempt to create the key to store and return if successful
    virtual_code = KeyMap.scan_code_to_virtual_code(scan_code, is_extended)
    name = KeyMap.virtual_input_to_unicode(virtual_code)
    
    if virtual_code == 0xFF or name is None:
        logging.getLogger("system").warning(
            f"Invalid scan code specified ({scan_code} (0x{scan_code:x}), {is_extended})"
        )
        # raise error.KeyboardError(
        #     f"Invalid scan code specified ({scan_code}, {is_extended})"
        # )
        return None
    else:
        key = Key(name, scan_code, is_extended, virtual_code)
        KeyMap.register(key)
        return key
    



class scan_codes(enum.Enum):
    ''' windows scan codes lookup '''
    sc_escape = 0x01
    sc_1 = 0x02
    sc_2 = 0x03
    sc_3 = 0x04
    sc_4 = 0x05
    sc_5 = 0x06
    sc_6 = 0x07
    sc_7 = 0x08
    sc_8 = 0x09
    sc_9 = 0x0A
    sc_0 = 0x0B
    sc_minus = 0x0C
    sc_equals = 0x0D
    sc_backspace = 0x0E
    sc_tab = 0x0F
    sc_q = 0x10
    sc_w = 0x11
    sc_e = 0x12
    sc_r = 0x13
    sc_t = 0x14
    sc_y = 0x15
    sc_u = 0x16
    sc_i = 0x17
    sc_o = 0x18
    sc_p = 0x19
    sc_bracketLeft = 0x1A
    sc_bracketRight = 0x1B
    sc_enter = 0x1C
    sc_controlLeft = 0x1D
    sc_a = 0x1E
    sc_s = 0x1F
    sc_d = 0x20
    sc_f = 0x21
    sc_g = 0x22
    sc_h = 0x23
    sc_j = 0x24
    sc_k = 0x25
    sc_l = 0x26
    sc_semicolon = 0x27
    sc_apostrophe = 0x28
    sc_grave = 0x29
    sc_shiftLeft = 0x2A
    sc_backslash = 0x2B
    sc_z = 0x2C
    sc_x = 0x2D
    sc_c = 0x2E
    sc_v = 0x2F
    sc_b = 0x30
    sc_n = 0x31
    sc_m = 0x32
    sc_comma = 0x33
    sc_preiod = 0x34
    sc_slash = 0x35
    sc_shiftRight = 0x36
    sc_numpad_multiply = 0x37
    sc_altLeft = 0x38
    sc_space = 0x39
    sc_capsLock = 0x3A
    sc_f1 = 0x3B
    sc_f2 = 0x3C
    sc_f3 = 0x3D
    sc_f4 = 0x3E
    sc_f5 = 0x3F
    sc_f6 = 0x40
    sc_f7 = 0x41
    sc_f8 = 0x42
    sc_f9 = 0x43
    sc_f10 = 0x44
    sc_numLock = 0x45
    sc_scrollLock = 0x46
    sc_numpad_7 = 0x47
    sc_numpad_8 = 0x48
    sc_numpad_9 = 0x49
    sc_numpad_minus = 0x4A
    sc_numpad_4 = 0x4B
    sc_numpad_5 = 0x4C
    sc_numpad_6 = 0x4D
    sc_numpad_plus = 0x4E
    sc_numpad_1 = 0x4F
    sc_numpad_2 = 0x50
    sc_numpad_3 = 0x51
    sc_numpad_0 = 0x52
    sc_numpad_period = 0x53
    sc_alt_printScreen = 0x54 # Alt + print screen. MapVirtualKeyEx( VK_SNAPSHOT MAPVK_VK_TO_VSC_EX 0 ) returns scancode 0x54. */
    sc_bracketAngle = 0x56 # Key between the left shift and Z. */
    sc_f11 = 0x57
    sc_f12 = 0x58
    sc_oem_1 = 0x5a # VK_OEM_WSCTRL */
    sc_oem_2 = 0x5b # VK_OEM_FINISH */
    sc_oem_3 = 0x5c # VK_OEM_JUMP */
    sc_eraseEOF = 0x5d
    sc_oem_4 = 0x5e # VK_OEM_BACKTAB */
    sc_oem_5 = 0x5f # VK_OEM_AUTO */
    sc_zoom = 0x62
    sc_help = 0x63
    sc_f13 = 0x64
    sc_f14 = 0x65
    sc_f15 = 0x66
    sc_f16 = 0x67
    sc_f17 = 0x68
    sc_f18 = 0x69
    sc_f19 = 0x6a
    sc_f20 = 0x6b
    sc_f21 = 0x6c
    sc_f22 = 0x6d
    sc_f23 = 0x6e
    sc_oem_6 = 0x6f # VK_OEM_PA3 */
    sc_katakana = 0x70
    sc_oem_7 = 0x71 # VK_OEM_RESET */
    sc_f24 = 0x76
    sc_sbcschar = 0x77
    sc_convert = 0x79
    sc_nonconvert = 0x7B # VK_OEM_PA1 */

    sc_media_previous = 0xE010
    sc_media_next = 0xE019
    sc_numpad_enter = 0xE01C
    sc_controlRight = 0xE01D
    sc_volume_mute = 0xE020
    sc_launch_app2 = 0xE021
    sc_media_play = 0xE022
    sc_media_stop = 0xE024
    sc_volume_down = 0xE02E
    sc_volume_up = 0xE030
    sc_browser_home = 0xE032
    sc_numpad_divide = 0xE035
    sc_printScreen = 0xE037
    #
    # sc_printScreen:
    # - make: 0xE02A 0xE037
    # - break: 0xE0B7 0xE0AA
    # - MapVirtualKeyEx( VK_SNAPSHOT MAPVK_VK_TO_VSC_EX 0 ) returns scancode 0x54;
    # - There is no VK_KEYDOWN with VK_SNAPSHOT.
    
    sc_altRight = 0xE038
    sc_cancel = 0xE046 # CTRL + Pause */
    sc_home = 0xE047
    sc_arrowUp = 0xE048
    sc_pageUp = 0xE049
    sc_arrowLeft = 0xE04B
    sc_arrowRight = 0xE04D
    sc_end = 0xE04F
    sc_arrowDown = 0xE050
    sc_pageDown = 0xE051
    sc_insert = 0xE052
    sc_delete = 0xE053
    sc_metaLeft = 0xE05B
    sc_metaRight = 0xE05C
    sc_application = 0xE05D
    sc_power = 0xE05E
    sc_sleep = 0xE05F
    sc_wake = 0xE063
    sc_browser_search = 0xE065
    sc_browser_favorites = 0xE066
    sc_browser_refresh = 0xE067
    sc_browser_stop = 0xE068
    sc_browser_forward = 0xE069
    sc_browser_back = 0xE06A
    sc_launch_app1 = 0xE06B
    sc_launch_email = 0xE06C
    sc_launch_media = 0xE06D

    sc_pause = 0xE11D45
    
    # sc_pause:
    # - make: 0xE11D 45 0xE19D C5
    # - make in raw input: 0xE11D 0x45
    # - break: none
    # - No repeat when you hold the key down
    # - There are no break so I don't know how the key down/up is expected to work. Raw input sends "keydown" and "keyup" messages and it appears that the keyup message is sent directly after the keydown message (you can't hold the key down) so depending on when GetMessage or PeekMessage will return messages you may get both a keydown and keyup message "at the same time". If you use VK messages most of the time you only get keydown messages but some times you get keyup messages too.
    # - when pressed at the same time as one or both control keys generates a 0xE046 (sc_cancel) and the string for that scancode is "break".
    



class KeyMap:

    _g_virtual_code_to_key = {} # map of keyboard virtual codes to the key
    _g_scan_code_to_key = {} # map of (scancode, extended) to the key
    _key_map = {}

   
    @staticmethod
    def register(key):
        assert key.lookup_name
        
        if key.virtual_code > 0:
            KeyMap._g_virtual_code_to_key[key.virtual_code] = key
        
        index = (key.scan_code, key.is_extended)
        if not index in KeyMap._g_scan_code_to_key.keys():
            KeyMap._g_scan_code_to_key[index] = key
        if key.name:
            name = key.lookup_name.lower().replace(" ", "")
            if name:
                KeyMap._key_map[name] = key

    @staticmethod
    def find(scan_code, is_extended):
        ''' does a key lookup by scan code and extended key status '''
        index = (scan_code, is_extended)
        if not index in KeyMap._g_scan_code_to_key.keys():
            # see if we can add it
            key = KeyMap.get_key(scan_code, is_extended)
            if key:
               KeyMap._g_scan_code_to_key[index] = key
               return key.duplicate()
            return None
        key = KeyMap._g_scan_code_to_key.get((scan_code, is_extended), None)
        if key:
            return key.duplicate()
        return None
    
    @staticmethod
    def find_virtual(virtual_code):
        if virtual_code in KeyMap._g_virtual_code_to_key.keys():
            return KeyMap._g_virtual_code_to_key[virtual_code].duplicate()
        return None
            

    @staticmethod
    def find_by_name(name):
        name = name.replace(" ","").lower()
        if name in KeyMap._key_map:
            return KeyMap._key_map[name].duplicate()
        return None
    
    @staticmethod
    def from_event(event):
        ''' returns a key based on a keyboard event '''
        key = None
        if event.virtual_code > 0:
            key = KeyMap.find_virtual(event.virtual_code)
        if not key :
            key = KeyMap.find(event.identifier[0], event.identifier[1])
        if key is None:
            logging.getLogger("system").warning(f"Don't know how to handle key event: {event}")
        return key

    
     
    @staticmethod
    def scan_code_to_virtual_code(scan_code, is_extended):
        """Returns the virtual code corresponding to the given scan code.

        :param scan_code scan code value to translate
        :param is_extended whether or not the scan code is extended
        :return virtual code corresponding to the given scan code

        https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-mapvirtualkeyexw

        """

        if scan_code: 
            value = scan_code
            if is_extended:
                value = 0xe0 << 8 | scan_code

            virtual_code = _map_virtual_key_ex(value, 3, _get_keyboard_layout(0))
            return virtual_code
        return None
    
    @staticmethod
    def virtual_code_to_scan_code(virtual_code):
        scan_code = _map_virtual_key_ex(virtual_code, 4,_get_keyboard_layout(0))
        return scan_code

    @staticmethod
    def virtual_input_to_unicode(virtual_code, scan_code = 0):
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
        for _ in range (5):
            state = _to_unicode_ex(
                virtual_code,
                scan_code,
                state_buffer,
                output_buffer,
                8,
                0,
                keyboard_layout
            )
            if state > 0:
                break

        if state == 0:
            name = f"Key 0x{scan_code:X} (0x{virtual_code:X}))"
            return name
        return output_buffer.value.upper()
    
    @staticmethod
    def get_key(scan_code, is_extended):
        virtual_code = KeyMap.scan_code_to_virtual_code(scan_code, is_extended)
        if virtual_code != 0:
            name = KeyMap.virtual_input_to_unicode(virtual_code, scan_code)
            return Key(name, scan_code, is_extended, virtual_code)
        return None
        

    @staticmethod
    def unicode_to_key(character):
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
    



    @staticmethod
    def get_latched_key(keys):
        ''' derives a single latched key from a set of keys'''

        modifier_map = {}
        modifiers = gremlin.keyboard.KeyMap._keyboard_modifiers # ["leftshift","leftcontrol","leftalt","rightshift","rightcontrol","rightalt","leftwin","rightwin"]
        for key_name in modifiers:
            modifier_map[key_name] = []

        # primary keys
        primary_keys = []
        modifier_keys = []
        data = []
        # create output - place modifiers up front
        for key in keys:
            item = (key.scan_code, key.is_extended)
            lookup_name = key.lookup_name
            if lookup_name in modifiers:
                modifier_map[lookup_name].append(item)
                modifier_keys.append(key)
            else:
                data.append(item)
                primary_keys.append(key)

        # latched key - pick one
        if primary_keys:
            return_key = primary_keys[0]
        elif modifier_keys:
            return_key = modifier_keys[0]
        else:
            return_key = None

        if return_key:
            latched = list(set(keys)) # remove any duplicates
            latched.remove(return_key) # remove self
            return_key.latched_keys = latched

        return return_key
    

    @staticmethod
    def translate(keyid) -> tuple:
        ''' translates a key id and returns a list of equivalent keys
            this is to map similar keys together 
            :param keyid (scan_code, is_extended)
            :returns ((scan_code, is_extended), virtual_code)
        '''
        # flip the extended bit to force numlock OFF for numeric keypad so we always get the numeric keys
        scan_code, is_extended = keyid
        if keyid in KeyMap._g_translate_map.keys():
            return KeyMap._g_translate_map[keyid]
        vk = KeyMap.scan_code_to_virtual_code(scan_code, is_extended)
        return (keyid, vk)
    
    
    @staticmethod
    def keyid_tostring(keyid):
        scan_code, is_extended = keyid
        return f"({scan_code} 0x{scan_code:X}, {is_extended})"
    
    @staticmethod
    def get_vk_keyboard_state(virtual_code):
        ''' get the hardware keyboard state by virtual key '''
        return (user32.GetAsyncKeyState(virtual_code) & 1) != 0 # true if the key is pressed
    
    @staticmethod
    def get_keyboard_state(scan_code, is_extended):
        ''' gets the hardware keyboard state by scan code '''
        virtual_code = KeyMap.scan_code_to_virtual_code(scan_code, is_extended)
        return KeyMap.get_vk_keyboard_state(virtual_code)
    
    @staticmethod
    def numlock_state():
        ''' gets the state of the numlock key '''
        return KeyMap.get_vk_keyboard_state(win32con.VK_NUMLOCK)
    
    @staticmethod
    def set_numlock_state(value):
        state = KeyMap.numlock_state()
        if state != value:
            KeyMap.toggle_numlock()

    @staticmethod
    def toggle_numlock():
        import gremlin.sendinput
        # key down
        flags = win32con.KEYEVENTF_EXTENDEDKEY 
        gremlin.sendinput.send_key(win32con.VK_NUMLOCK, 0x45, flags)

        # key up
        flags |= win32con.KEYEVENTF_KEYUP
        gremlin.sendinput.send_key(win32con.VK_NUMLOCK, 0x45, flags)

    
    # holds the number pad scan codes
    _g_numpad_codes = (win32con.VK_NUMPAD0,
                       win32con.VK_NUMPAD1,
                       win32con.VK_NUMPAD2,
                       win32con.VK_NUMPAD3,
                       win32con.VK_NUMPAD4,
                       win32con.VK_NUMPAD5,
                       win32con.VK_NUMPAD6,
                       win32con.VK_NUMPAD7,
                       win32con.VK_NUMPAD8,
                       win32con.VK_NUMPAD9,
                       )
    
    _g_translate_map = {
        (0x52,True): ((0x52, False), win32con.VK_NUMPAD0), # make all numpad keys report as numpad
        (0x4F,True): ((0x4F, False), win32con.VK_NUMPAD1),
        (0x50,True): ((0x50, False), win32con.VK_NUMPAD2),
        (0x51,True): ((0x51, False), win32con.VK_NUMPAD3),
        (0x4B,True): ((0x4B, False), win32con.VK_NUMPAD4),
        (0x4C,True): ((0x4C, False), win32con.VK_NUMPAD5),
        (0x4D,True): ((0x4D, False), win32con.VK_NUMPAD6),
        (0x47,True): ((0x47, False), win32con.VK_NUMPAD7),
        (0x48,True): ((0x48, False), win32con.VK_NUMPAD8),
        (0x49,True): ((0x49, False), win32con.VK_NUMPAD9),

        (0x52,False): ((0x52, False), win32con.VK_NUMPAD0), 
        (0x4F,False): ((0x4F, False), win32con.VK_NUMPAD1),
        (0x50,False): ((0x50, False), win32con.VK_NUMPAD2),
        (0x51,False): ((0x51, False), win32con.VK_NUMPAD3),
        (0x4B,False): ((0x4B, False), win32con.VK_NUMPAD4),
        (0x4C,False): ((0x4C, False), win32con.VK_NUMPAD5),
        (0x4D,False): ((0x4D, False), win32con.VK_NUMPAD6),
        (0x47,False): ((0x47, False), win32con.VK_NUMPAD7),
        (0x48,False): ((0x48, False), win32con.VK_NUMPAD8),
        (0x49,False): ((0x49, False), win32con.VK_NUMPAD9),

        (0x36,True): ((0x36, False), win32con.VK_RSHIFT),  # combine rshift and rshift 2


    }

    _g_name_map = {
        # Function keys
        "f1": ("F1", 0x3b, False, win32con.VK_F1),
        "f2": ("F2", 0x3c, False, win32con.VK_F2),
        "f3": ("F3", 0x3d, False, win32con.VK_F3),
        "f4": ("F4", 0x3e, False, win32con.VK_F4),
        "f5": ("F5", 0x3f, False, win32con.VK_F5),
        "f6": ("F6", 0x40, False, win32con.VK_F6),
        "f7": ("F7", 0x41, False, win32con.VK_F7),
        "f8": ("F8", 0x42, False, win32con.VK_F8),
        "f9": ("F9", 0x43, False, win32con.VK_F9),
        "f10": ("F10", 0x44, False, win32con.VK_F10),
        "f11": ("F11", 0x57, False, win32con.VK_F11),
        "f12": ("F12", 0x58, False, win32con.VK_F12),
        "f13": ("F13", 0x64, False, win32con.VK_F13),
        "f14": ("F14", 0x65, False, win32con.VK_F14),
        "f15": ("F15", 0x66, False, win32con.VK_F15),
        "f16": ("F16", 0x67, False, win32con.VK_F16),
        "f17": ("F17", 0x68, False, win32con.VK_F17),
        "f18": ("F18", 0x69, False, win32con.VK_F18),
        "f19": ("F19", 0x6a, False, win32con.VK_F19),    
        "f20": ("F20", 0x6b, False, win32con.VK_F20),    
        "f21": ("F21", 0x6c, False, win32con.VK_F21),    
        "f22": ("F22", 0x6d, False, win32con.VK_F22),    
        "f23": ("F23", 0x6e, False, win32con.VK_F23),    
        "f24": ("F24", 0x76, False, win32con.VK_F24),   
        # Control keys
        "printscreen": ("Print Screen", 0x37, True, win32con.VK_PRINT),
        "scrolllock": ("Scroll Lock", 0x46, False, win32con.VK_SCROLL),
        "pause": ("Pause", 0x45, False, win32con.VK_PAUSE),
        # 6 control block
        "insert": ("Insert", 0x52, True, win32con.VK_INSERT),
        "home": ("Home", 0x47, True, win32con.VK_HOME),
        "pageup": ("PageUp", 0x49, True, win32con.VK_PRIOR),
        "delete": ("Delete", 0x53, True, win32con.VK_DELETE),
        "end": ("End", 0x4f, True, win32con.VK_END),
        "pagedown": ("PageDown", 0x51, True, win32con.VK_NEXT),
        # Arrow keys
        "up": ("Up", 0x48, True, win32con.VK_UP),
        "left": ("Left", 0x4b, True, win32con.VK_LEFT),
        "down": ("Down", 0x50, True, win32con.VK_DOWN),
        "right": ("Right", 0x4d, True, win32con.VK_RIGHT),
        # Numpad
        "numlock": ("NumLock", 0x45, True, win32con.VK_NUMLOCK),
        "npdivide": ("Numpad /", 0x35, True, win32con.VK_DIVIDE),
        "npmultiply": ("Numpad *", 0x37, False, win32con.VK_MULTIPLY),
        "npminus": ("Numpad -", 0x4a, False, win32con.VK_SUBTRACT),
        "npplus": ("Numpad +", 0x4e, False, win32con.VK_ADD),
        "npenter": ("Numpad Enter", 0x1c, True, win32con.VK_SEPARATOR),
        "npdelete": ("Numpad Delete", 0x53, False, win32con.VK_DECIMAL),
        "np0": ("Numpad 0", 0x52, False, win32con.VK_NUMPAD0),
        "np1": ("Numpad 1", 0x4f, False, win32con.VK_NUMPAD1),
        "np2": ("Numpad 2", 0x50, False, win32con.VK_NUMPAD2),
        "np3": ("Numpad 3", 0x51, False, win32con.VK_NUMPAD3),
        "np4": ("Numpad 4", 0x4b, False, win32con.VK_NUMPAD4),
        "np5": ("Numpad 5", 0x4c, False, win32con.VK_NUMPAD5),
        "np6": ("Numpad 6", 0x4d, False, win32con.VK_NUMPAD6),
        "np7": ("Numpad 7", 0x47, False, win32con.VK_NUMPAD7),
        "np8": ("Numpad 8", 0x48, False, win32con.VK_NUMPAD8),
        "np9": ("Numpad 9", 0x49, False, win32con.VK_NUMPAD9),
        # Misc keys
        "backspace": ("Backspace", 0x0e, False, win32con.VK_BACK),
        "space": ("Space", 0x39, False, win32con.VK_SPACE),
        "tab": ("Tab", 0x0f, False, win32con.VK_TAB),
        "capslock": ("CapsLock", 0x3a, False, win32con.VK_CAPITAL),
        "leftshift": ("Left Shift", 0x2a, False, win32con.VK_LSHIFT),
        "leftcontrol": ("Left Control", 0x1d, False, win32con.VK_LCONTROL),
        "leftwin": ("Left Win", 0x5b, True, win32con.VK_LWIN),
        "leftalt": ("Left Alt", 0x38, False, win32con.VK_LMENU),
        # Right shift key appears to exist in both extended and
        # non-extended version
        "rightshift": ("Right Shift", 0x36, False, win32con.VK_RSHIFT),
        "rightshift2": ("Right Shift", 0x36, True, win32con.VK_RSHIFT),
        "rightcontrol": ("Right Control", 0x1d, True, win32con.VK_RCONTROL),
        "rightwin": ("Right Win", 0x5c, True, win32con.VK_RWIN),
        "rightalt": ("Right Alt", 0x38, True, win32con.VK_RMENU),
        "rightalt2": ("Right Alt", 0x38, True, win32con.VK_RMENU),
        "apps": ("Apps", 0x5d, True, win32con.VK_APPS),
        "enter": ("Enter", 0x1c, False, win32con.VK_RETURN),
        "esc": ("Esc", 0x01, False, win32con.VK_ESCAPE)
    }

    _keyboard_special = list(_g_name_map.keys())
    _keyboard_modifiers = ["leftshift","leftcontrol","leftalt","rightshift","rightshift2","rightcontrol","rightalt","rightalt2","leftwin","rightwin"]

# populate special mouse keys
for mouse_button in MouseButton:
    code = mouse_button.value
    scan_code = 0x1000 + code
    is_extended = False
    name = MouseButton.to_string(mouse_button)
    lookup_name = MouseButton.to_lookup_string(mouse_button)
    key = Key(name, scan_code, is_extended, 0, True)
    key._lookup_name = lookup_name
    KeyMap.register(key)


# Populate the scan code based lookup table
for name_, data in KeyMap._g_name_map.items():
    key = Key(*data)
    key._lookup_name = name_
    KeyMap.register(key)


# register regular scan codes
for enum_code_value in scan_codes:
    code_value = enum_code_value.value
    scan_code = code_value & 0xFF
    is_extended = False
    if code_value << 8 & 0xE0 or code_value << 8 & 0xE1:
        is_extended = True
    if not (scan_code, is_extended) in KeyMap._g_scan_code_to_key:
        virtual_code = KeyMap.scan_code_to_virtual_code(scan_code, is_extended)
        if virtual_code > 0:
            # only store keys that have a virtual key code
            name = KeyMap.virtual_input_to_unicode(virtual_code, scan_code)
            key = Key(name, scan_code, is_extended, virtual_code)
            KeyMap.register(key)
        else:
            name = enum_code_value.name
            key = Key(name, scan_code, is_extended, 0)
            KeyMap.register(key)
            

