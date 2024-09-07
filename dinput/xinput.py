# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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

# xinput support based on https://github.com/Zuzu-Typ/XInput-Python


import ctypes, ctypes.util

from ctypes import Structure, POINTER

from math import sqrt

import time

from threading import Thread, Lock

import logging
from enum import Enum, auto

class XInputEventType(Enum):
    NotSet = auto() # not set
    Button = auto() # button event
    Trigger = auto() # trigger event
    Axis = auto() # axis event
    State = auto() # connection event

class XInputButtonType(Enum):
    NotSet = auto() # not set
    DPadUp = auto()
    DPadDown = auto()
    DPadLeft = auto()
    DPadRight = auto()
    Back = auto()
    Start = auto()
    Stop = auto()
    ShoulderLeft = auto()
    ShoulderRight = auto()
    ThumbLeft = auto()
    ThumbRight = auto()
    A = auto()
    B = auto()
    X = auto()
    Y = auto()

class XInputAxisType(Enum):
    NotSet = auto() # not set
    Left = auto()
    Right = auto()

class XInputTriggerType(Enum):
    NotSet = auto() # not set
    Left = auto()
    Right = auto()





class XInputEvent():
    def __init__(self):
        self.type= XInputEventType.NotSet
        self.button = XInputButtonType.NotSet
        self.trigger = XInputTriggerType.NotSet
        self.axis = XInputAxisType.NotSet
        self.x = 0
        self.y = 0
        self.value = 0
        self.is_pressed = False # true if the button is pressed, false if the button is released





# loading the DLL #
XINPUT_DLL_NAMES = (
    "XInput1_4.dll",
    "XInput9_1_0.dll",
    "XInput1_3.dll",
    "XInput1_2.dll",
    "XInput1_1.dll"
)

libXInput = None

for name in XINPUT_DLL_NAMES:
    found = ctypes.util.find_library(name)
    if found:
        libXInput = ctypes.WinDLL(found)
        break

if not libXInput:
    raise IOError("XInput library was not found.")

#/loading the DLL #

# defining static global variables #
WORD    = ctypes.c_ushort
BYTE    = ctypes.c_ubyte
SHORT   = ctypes.c_short
DWORD   = ctypes.c_ulong

ERROR_SUCCESS               = 0
ERROR_BAD_ARGUMENTS         = 160
ERROR_DEVICE_NOT_CONNECTED  = 1167

XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE  = 7849
XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE = 8689
XINPUT_GAMEPAD_TRIGGER_THRESHOLD    = 30

BATTERY_DEVTYPE_GAMEPAD         = 0x00
BATTERY_TYPE_DISCONNECTED       = 0x00
BATTERY_TYPE_WIRED              = 0x01
BATTERY_TYPE_ALKALINE           = 0x02
BATTERY_TYPE_NIMH               = 0x03
BATTERY_TYPE_UNKNOWN            = 0xFF
BATTERY_LEVEL_EMPTY             = 0x00
BATTERY_LEVEL_LOW               = 0x01
BATTERY_LEVEL_MEDIUM            = 0x02
BATTERY_LEVEL_FULL              = 0x03

BUTTON_DPAD_UP                  = 0x000001
BUTTON_DPAD_DOWN                = 0x000002
BUTTON_DPAD_LEFT                = 0x000004
BUTTON_DPAD_RIGHT               = 0x000008
BUTTON_START                    = 0x000010
BUTTON_BACK                     = 0x000020
BUTTON_LEFT_THUMB               = 0x000040
BUTTON_RIGHT_THUMB              = 0x000080
BUTTON_LEFT_SHOULDER            = 0x000100
BUTTON_RIGHT_SHOULDER           = 0x000200
BUTTON_A                        = 0x001000
BUTTON_B                        = 0x002000
BUTTON_X                        = 0x004000
BUTTON_Y                        = 0x008000

STICK_LEFT                      = 0x010000
STICK_RIGHT                     = 0x020000
TRIGGER_LEFT                    = 0x040000
TRIGGER_RIGHT                   = 0x080000

FILTER_PRESSED_ONLY                = 0x100000
FILTER_RELEASED_ONLY                  = 0x200000
FILTER_NONE                     = 0xffffff-FILTER_PRESSED_ONLY-FILTER_RELEASED_ONLY

DEADZONE_LEFT_THUMB             = 0
DEADZONE_RIGHT_THUMB            = 1
DEADZONE_TRIGGER                = 2

DEADZONE_DEFAULT                = -1

EVENT_CONNECTED         = 1
EVENT_DISCONNECTED      = 2
EVENT_BUTTON_PRESSED    = 3
EVENT_BUTTON_RELEASED   = 4
EVENT_TRIGGER_MOVED     = 5
EVENT_STICK_MOVED       = 6

LEFT    = 0
RIGHT   = 1
#/defining static global variables #

# defining XInput compatible structures #
class XINPUT_GAMEPAD(Structure):
    _fields_ = [("wButtons", WORD),
                ("bLeftTrigger", BYTE),
                ("bRightTrigger", BYTE),
                ("sThumbLX", SHORT),
                ("sThumbLY", SHORT),
                ("sThumbRX", SHORT),
                ("sThumbRY", SHORT),
                ]

class XINPUT_STATE(Structure):
    _fields_ = [("dwPacketNumber", DWORD),
                ("Gamepad", XINPUT_GAMEPAD),
                ]

State = XINPUT_STATE

class XINPUT_VIBRATION(Structure):
    _fields_ = [("wLeftMotorSpeed", WORD),
                ("wRightMotorSpeed", WORD),
                ]

class XINPUT_BATTERY_INFORMATION(Structure):
    _fields_ = [("BatteryType", BYTE),
                ("BatteryLevel", BYTE),
                ]

libXInput.XInputGetState.argtypes = [DWORD, POINTER(XINPUT_STATE)]
libXInput.XInputGetState.restype = DWORD

def XInputGetState(dwUserIndex, state):
    return libXInput.XInputGetState(dwUserIndex, ctypes.byref(state))

libXInput.XInputSetState.argtypes = [DWORD, POINTER(XINPUT_VIBRATION)]
libXInput.XInputSetState.restype = DWORD

def XInputSetState(dwUserIndex, vibration):
    return libXInput.XInputSetState(dwUserIndex, ctypes.byref(vibration))

libXInput.XInputGetBatteryInformation.argtypes = [DWORD, BYTE, POINTER(XINPUT_BATTERY_INFORMATION)]
libXInput.XInputGetBatteryInformation.restype = DWORD

def XInputGetBatteryInformation(dwUserIndex, devType, batteryInformation):
    return libXInput.XInputGetBatteryInformation(dwUserIndex, devType, ctypes.byref(batteryInformation))
#/defining XInput compatible structures #

# defining file-local variables #
_battery_type_dict = {BATTERY_TYPE_DISCONNECTED : "DISCONNECTED",
                      BATTERY_TYPE_WIRED : "WIRED",
                      BATTERY_TYPE_ALKALINE : "ALKALINE",
                      BATTERY_TYPE_NIMH : "NIMH",
                      BATTERY_TYPE_UNKNOWN : "UNKNOWN"}

_battery_level_dict = {BATTERY_LEVEL_EMPTY : "EMPTY",
                       BATTERY_LEVEL_LOW : "LOW",
                       BATTERY_LEVEL_MEDIUM : "MEDIUM",
                       BATTERY_LEVEL_FULL : "FULL"}

_last_states = (State(), State(), State(), State())

_last_norm_values = [None, None, None, None]

_connected = [False, False, False, False]

_last_checked = 0

_deadzones = [{DEADZONE_RIGHT_THUMB : XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE,
               DEADZONE_LEFT_THUMB : XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE,
               DEADZONE_TRIGGER : XINPUT_GAMEPAD_TRIGGER_THRESHOLD},
              {DEADZONE_RIGHT_THUMB : XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE,
               DEADZONE_LEFT_THUMB : XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE,
               DEADZONE_TRIGGER : XINPUT_GAMEPAD_TRIGGER_THRESHOLD},
              {DEADZONE_RIGHT_THUMB : XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE,
               DEADZONE_LEFT_THUMB : XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE,
               DEADZONE_TRIGGER : XINPUT_GAMEPAD_TRIGGER_THRESHOLD},
              {DEADZONE_RIGHT_THUMB : XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE,
               DEADZONE_LEFT_THUMB : XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE,
               DEADZONE_TRIGGER : XINPUT_GAMEPAD_TRIGGER_THRESHOLD}]

_button_dict = {0x0001 : "DPAD_UP",
                0x0002 : "DPAD_DOWN",
                0x0004 : "DPAD_LEFT",
                0x0008 : "DPAD_RIGHT",
                0x0010 : "START",
                0x0020 : "BACK",
                0x0040 : "LEFT_THUMB",
                0x0080 : "RIGHT_THUMB",
                0x0100 : "LEFT_SHOULDER",
                0x0200 : "RIGHT_SHOULDER",
                0x1000 : "A",
                0x2000 : "B",
                0x4000 : "X",
                0x8000 : "Y",
        }
#/defining file-local variables #

# defining custom classes and methods #
class XInputNotConnectedError(Exception):
    pass

class XInputBadArgumentError(ValueError):
    pass

def set_deadzone(dzone, value):
    """Sets the deadzone <dzone> to <value>.
Any raw value retruned by the respective stick or trigger
will be clamped to 0 if it's lower than <value>.
The supported deadzones are:
DEADZONE_RIGHT_THUMB (default value is 8689, max is 32767)
DEADZONE_LEFT_THUMB  (default value is 7849, max is 32767)
DEADZONE_TRIGGER     (default value is 30,   max is 255  )"""
    global XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE, XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE, XINPUT_GAMEPAD_TRIGGER_THRESHOLD
    
    assert dzone >= 0 and dzone <= 2, "invalid deadzone"
    
    if value == DEADZONE_DEFAULT:
        value = 7849 if dzone == DEADZONE_LEFT_THUMB else \
                8689 if dzone == DEADZONE_RIGHT_THUMB else \
                30

    if dzone == DEADZONE_LEFT_THUMB:
        assert value >= 0 and value <= 32767
        if value == DEADZONE_DEFAULT: XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE = 7849
        else: XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE = value

    elif dzone == DEADZONE_RIGHT_THUMB:
        assert value >= 0 and value <= 32767
        if value == DEADZONE_DEFAULT: XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE = 8689
        else: XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE = value

    else:
        assert value >= 0 and value <= 255
        if value == DEADZONE_DEFAULT: XINPUT_GAMEPAD_TRIGGER_THRESHOLD = 30
        else: XINPUT_GAMEPAD_TRIGGER_THRESHOLD = value

def get_connected():
    """get_connected() -> (bool, bool, bool, bool)
Returns wether or not the controller at each index is
connected.
You shouldn't check this too frequently."""
    state = XINPUT_STATE()
    out = [False] * 4
    for i in range(4):
        out[i] = (XInputGetState(i, state) == 0)

    return tuple(out)

def get_state(user_index):
    """get_state(int) -> XINPUT_STATE
Returns the raw state of the controller."""
    state = XINPUT_STATE()
    res = XInputGetState(user_index, state)
    if res == ERROR_DEVICE_NOT_CONNECTED:
        raise XInputNotConnectedError("Controller [{}] appears to be disconnected.".format(user_index))

    if res == ERROR_BAD_ARGUMENTS:
        raise XInputBadArgumentError("Controller [{}] doesn't exist. IDs range from 0 to 3.".format(user_index))
    
    assert res == 0, "Couldn't get the state of controller [{}]. Is it disconnected?".format(user_index)

    return state

def get_battery_information(user_index):
    """get_battery_information(int) -> (str, str)
Returns the battery information for controller <user_index>.
The return value is formatted as (<battery_type>, <battery_level>)"""
    battery_information = XINPUT_BATTERY_INFORMATION()
    XInputGetBatteryInformation(user_index, BATTERY_DEVTYPE_GAMEPAD, battery_information)
    return (_battery_type_dict[battery_information.BatteryType], _battery_level_dict[battery_information.BatteryLevel])

def set_vibration(user_index, left_speed, right_speed):
    """Sets the vibration motor speed for controller <user_index>.
The speed ranges from 0.0 to 1.0 (float values) or
0 to 65535 (int values)."""
    if type(left_speed) == float and left_speed <= 1.0:
        left_speed = (round(65535 * left_speed, 0))

    if type(right_speed) == float and right_speed <= 1.0:
        right_speed = (round(65535 * right_speed, 0))
        
    vibration = XINPUT_VIBRATION()
    
    vibration.wLeftMotorSpeed = int(left_speed)
    vibration.wRightMotorSpeed = int(right_speed)

    return XInputSetState(user_index, vibration) == 0

def get_button_values(state):
    """get_button_values(XINPUT_STATE) -> dict
Returns a dict with string keys and boolean values,
representing the button and it's value respectively.
You can get the required state using get_state()"""
    wButtons = state.Gamepad.wButtons
    return {"DPAD_UP" : bool(wButtons & 0x0001),
            "DPAD_DOWN" : bool(wButtons & 0x0002),
            "DPAD_LEFT" : bool(wButtons & 0x0004),
            "DPAD_RIGHT" : bool(wButtons & 0x0008),
            "START" : bool(wButtons & 0x0010),
            "BACK" : bool(wButtons & 0x0020),
            "LEFT_THUMB" : bool(wButtons & 0x0040),
            "RIGHT_THUMB" : bool(wButtons & 0x0080),
            "LEFT_SHOULDER" : bool(wButtons & 0x0100),
            "RIGHT_SHOULDER" : bool(wButtons & 0x0200),
            "A" : bool(wButtons & 0x1000),
            "B" : bool(wButtons & 0x2000),
            "X" : bool(wButtons & 0x4000),
            "Y" : bool(wButtons & 0x8000),
        }

def get_trigger_values(state):
    """get_trigger_values(XINPUT_STATE) -> (float, float)
Returns the normalized left and right trigger values.
You can get the required state using get_state()"""
    LT = state.Gamepad.bLeftTrigger
    RT = state.Gamepad.bRightTrigger

    normLT = 0
    normRT = 0

    if LT > XINPUT_GAMEPAD_TRIGGER_THRESHOLD:
        LT -= XINPUT_GAMEPAD_TRIGGER_THRESHOLD
        normLT = LT / (255. - XINPUT_GAMEPAD_TRIGGER_THRESHOLD)
    else:
        LT = 0

    if RT > XINPUT_GAMEPAD_TRIGGER_THRESHOLD:
        RT -= XINPUT_GAMEPAD_TRIGGER_THRESHOLD
        normRT = RT / (255. - XINPUT_GAMEPAD_TRIGGER_THRESHOLD)
    else:
        RT = 0

    return (normLT, normRT)

def get_thumb_values(state):
    """get_thumb_values(XINPUT_STATE) -> ((float, float), (float, float))
Returns the normalized left and right thumb stick values,
represented as X and Y values.
You can get the required state using get_state()"""
    LX = state.Gamepad.sThumbLX
    LY = state.Gamepad.sThumbLY
    RX = state.Gamepad.sThumbRX
    RY = state.Gamepad.sThumbRY

    magL = sqrt(LX*LX + LY*LY)
    magR = sqrt(RX*RX + RY*RY)

    if magL != 0:
        normLX = LX / magL
        normLY = LY / magL
    else: # if magL == 0 the stick is centered, there is no direction
        normLX = 0
        normLY = 0
    
    if magR != 0:
        normRX = RX / magR
        normRY = RY / magR
    else: # if magR == 0 the stick is centered, there is no direction
        normRX = 0
        normRY = 0


    normMagL = 0
    normMagR = 0

    if (magL > XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE):
        magL = min(32767, magL)

        magL -= XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE

        normMagL = magL / (32767. - XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE)
    else:
        magL = 0

    if (magR > XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE):
        magR = min(32767, magR)

        magR -= XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE

        normMagR = magR / (32767. - XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE)
    else:
        magR = 0

    return ((normLX * normMagL, normLY * normMagL), (normRX * normMagR, normRY * normMagR))






class Event:
    def __init__(self, user_index, type_):
        self.user_index = user_index
        self.type = type_

    def __str__(self):
        return str(self.__dict__)
        
def get_events():
    """get_events() -> generator
Returns a generator that yields events for each change that
occured since this function was last called.
Each event has a <type> and <user_index> associated.
The other variables vary."""
    global _last_states, _connected, _last_checked, _button_dict, _last_norm_values
    this_time = time.time()
    these_states = (State(), State(), State(), State())
    if _last_checked + 1 < this_time:
        _last_checked = this_time
        for i in range(4):
            is_connected = (XInputGetState(i, these_states[i]) == 0)
            if is_connected != _connected[i]:
                yield Event(i, EVENT_CONNECTED if is_connected else EVENT_DISCONNECTED)
                _connected[i] = is_connected
    else:
        for i in range(4):
            was_connected = _connected[i]
            if not was_connected:
                continue
            is_connected = (XInputGetState(i, these_states[i]) == 0)

            if not is_connected:
                yield Event(i, EVENT_DISCONNECTED)
                _connected[i] = False
                continue

    for i in range(4):
        is_connected = _connected[i]
        if not is_connected: continue

        if these_states[i].Gamepad.wButtons != _last_states[i].Gamepad.wButtons:
            changed = these_states[i].Gamepad.wButtons ^ _last_states[i].Gamepad.wButtons
            if changed:
                for button in _button_dict:
                    if changed & button:
                        event = Event(i, EVENT_BUTTON_PRESSED if changed & button & these_states[i].Gamepad.wButtons else EVENT_BUTTON_RELEASED)
                        event.button = _button_dict[button]
                        event.button_id = button
                        yield event

        if these_states[i].Gamepad.bLeftTrigger != _last_states[i].Gamepad.bLeftTrigger:
            LT = these_states[i].Gamepad.bLeftTrigger

            normLT = 0

            if LT > XINPUT_GAMEPAD_TRIGGER_THRESHOLD:
                LT -= XINPUT_GAMEPAD_TRIGGER_THRESHOLD
                normLT = LT / (255. - XINPUT_GAMEPAD_TRIGGER_THRESHOLD)
            else:
                LT = 0

            if normLT != _last_norm_values[0]:
                event = Event(i, EVENT_TRIGGER_MOVED)
                event.trigger = LEFT
                event.value = normLT
                yield event

            _last_norm_values[0] = normLT

        if these_states[i].Gamepad.bRightTrigger != _last_states[i].Gamepad.bRightTrigger:
            RT = these_states[i].Gamepad.bRightTrigger

            normRT = 0

            if RT > XINPUT_GAMEPAD_TRIGGER_THRESHOLD:
                RT -= XINPUT_GAMEPAD_TRIGGER_THRESHOLD
                normRT = RT / (255. - XINPUT_GAMEPAD_TRIGGER_THRESHOLD)
            else:
                RT = 0

            if normRT != _last_norm_values[1]:
                event = Event(i, EVENT_TRIGGER_MOVED)
                event.trigger = RIGHT
                event.value = normRT
                yield event

            _last_norm_values[1] = normRT

        if these_states[i].Gamepad.sThumbLX != _last_states[i].Gamepad.sThumbLX or these_states[i].Gamepad.sThumbLY != _last_states[i].Gamepad.sThumbLY:
            LX = these_states[i].Gamepad.sThumbLX
            LY = these_states[i].Gamepad.sThumbLY

            magL = sqrt(LX*LX + LY*LY)

            if magL != 0:
                normLX = LX / magL
                normLY = LY / magL
            else: # if magL == 0 the stick is centered, there is no direction
                normLX = 0
                normLY = 0

            normMagL = 0

            if (magL > XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE):
                magL = min(32767, magL)

                magL -= XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE

                normMagL = magL / (32767. - XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE)
            else:
                magL = 0

            out = (normLX * normMagL, normLY * normMagL)

            if out != _last_norm_values[2]:
                event = Event(i, EVENT_STICK_MOVED)
                event.stick = LEFT
                event.x = out[0]
                event.y = out[1]
                event.value = normMagL
                event.dir = (normLX, normLY) if event.value else (0.0, 0.0)
                yield event

            _last_norm_values[2] = out

        if these_states[i].Gamepad.sThumbRX != _last_states[i].Gamepad.sThumbRX or these_states[i].Gamepad.sThumbRY != _last_states[i].Gamepad.sThumbRY:
            RX = these_states[i].Gamepad.sThumbRX
            RY = these_states[i].Gamepad.sThumbRY

            magR = sqrt(RX*RX + RY*RY)

            if magR != 0:
                normRX = RX / magR
                normRY = RY / magR
            else:   # if magR == 0 the stick is centered, there is no direction
                normRX = 0
                normRY = 0

            normMagR = 0

            if (magR > XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE):
                magR = min(32767, magR)

                magR -= XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE

                normMagR = magR / (32767. - XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE)
            else:
                magR = 0

            out = (normRX * normMagR, normRY * normMagR)

            if out != _last_norm_values[3]:
                event = Event(i, EVENT_STICK_MOVED)
                event.stick = RIGHT
                event.x = out[0]
                event.y = out[1]
                event.value = normMagR
                event.dir = (normRX, normRY) if event.value else (0.0, 0.0)
                yield event

            _last_norm_values[3] = out

    _last_states = these_states
    
class EventHandler:
    def __init__(self, *controllers, filter = FILTER_NONE):
        self.set_controllers(*controllers)
        
        self.filter = filter
    
    def process_button_event(self, event):
        raise NotImplementedError("Method not implemented. Must be implemented in the child class")

    def process_stick_event(self, event):
        raise NotImplementedError("Method not implemented. Must be implemented in the child class")

    def process_trigger_event(self, event):
        raise NotImplementedError("Method not implemented. Must be implemented in the child class")

    def process_connection_event(self, event):
        raise NotImplementedError("Method not implemented. Must be implemented in the child class")


    def add_controller(self, user_index):
        """Adds a given controller to the ones that are processed"""
        assert 0 <= user_index <= 3, "controllers must have a user_index between 0 and 3"

        self.controllers.add(user_index)

    def set_controllers(self, *controllers):
        """Sets the controllers that are processed"""
        if not controllers:
            raise ValueError("You need to specify at least one controller")
        
        for user_index in controllers:
            assert 0 <= user_index <= 3, "controllers must have a user_index between 0 and 3"

        self.controllers = set(controllers)

    def remove_controller(self, user_index):
        """Removes a given controller from the ones that are processed"""
        assert 0 <= user_index <= 3, "controllers must have a user_index between 0 and 3"

        assert len(self.controllers) >= 2, "you have to keep at least one controller"
    
        try:
            self.controllers.remove(user_index)
            return True
        except KeyError:
            return False

    def has_controller(self, user_index):
        """Checks, wether or not this handler handles controller <user_index>"""
        assert 0 <= user_index <= 3, "controllers must have a user_index between 0 and 3"

        return user_index in self.controllers
    
    def set_filter(self, filter_):
        """Applies a new filter mask to this handler.
A filter can be any combination of filters, such as
(BUTTON_A | BUTTON_B) to only get events for buttons A and B or
(FILTER_RELEASED_ONLY | BUTTON_Y) to get an event when Y is released."""
        self.filter = filter_
    
    # remove any filter
    # the "controller" attribute remove the filter only for the selected controller. By default will remove every filter
    def clear_filter(self):
        """Removes all filters"""
        self.filter = FILTER_NONE


class GamepadThread:
    def __init__(self, *event_handlers, auto_start=True):
        for event_handler in event_handlers:
            if (event_handler is None or not issubclass(type(event_handler), EventHandler)):
                raise TypeError("The event handler must be a subclass of XInput.EventHandler")
            
        self.handlers = set(event_handlers)

        self.lock = Lock()

        self.queued_new_handlers = []
        self.queued_removed_handlers = []
        
        if auto_start:
            self.start()

    def __tfun(self):           # thread function
        while(self.running):  # polling
            self.lock.acquire()
            for new_handler in self.queued_new_handlers:
                self.handlers.add(new_handler)
                
            for removed_handler in self.queued_removed_handlers:
                if removed_handler in self.handlers:
                    self.handlers.remove(removed_handler)
            self.queued_new_handlers.clear()
            self.queued_removed_handlers.clear()
            self.lock.release()
            
            events = get_events()
            for event in events:    # filtering events
                if event.type == EVENT_CONNECTED or event.type == EVENT_DISCONNECTED:
                    for handler in self.handlers:
                        if handler.has_controller(event.user_index):
                            handler.process_connection_event(event)
                            
                elif event.type == EVENT_BUTTON_PRESSED or event.type == EVENT_BUTTON_RELEASED:
                    for handler in self.handlers:
                        if handler.has_controller(event.user_index):
                            if not((handler.filter & (FILTER_PRESSED_ONLY+FILTER_RELEASED_ONLY)) and not(handler.filter & (FILTER_PRESSED_ONLY << (event.type - EVENT_BUTTON_PRESSED)))):
                                if event.button_id & handler.filter:
                                    handler.process_button_event(event)
                elif event.type == EVENT_TRIGGER_MOVED:
                    for handler in self.handlers:
                        if handler.has_controller(event.user_index):
                            if (TRIGGER_LEFT << event.trigger) & handler.filter:
                                handler.process_trigger_event(event)
                elif event.type == EVENT_STICK_MOVED:
                    for handler in self.handlers:
                        if handler.has_controller(event.user_index):
                            if (STICK_LEFT << event.stick) & handler.filter:
                                handler.process_stick_event(event)
                else:
                    raise ValueError("Event type not recognized")
                

    def start(self):     # starts the thread
        self.running = True
        if(not hasattr(self,"__thread")):
            self.__thread = Thread(target=self.__tfun, args=())
            self.__thread.daemon = True
        self.__thread.start()

    def stop(self):      # stops the thread
        self.running = False
        self.__thread.join()
    
    def add_event_handler(self, event_handler):
        if (event_handler is None or not issubclass(type(event_handler), EventHandler)):
            raise TypeError("The event handler must be a subclass of XInput.EventHandler")
        self.lock.acquire()
        self.queued_new_handlers.append(event_handler)
        self.lock.release()

    def remove_event_handler(self, event_handler):
        if (event_handler is None or not issubclass(type(event_handler), EventHandler)):
            raise TypeError("The event handler must be a subclass of XInput.EventHandler")
        self.lock.acquire()
        self.queued_removed_handlers.append(event_handler)
        self.lock.release()

    def __del__(self):
        if hasattr(self, "__thread"):
            self.stop()
#/defining custom classes and methods #


class XInput(EventHandler):
    ''' game controller input interface '''
    def __init__(self, callback):
        ''' callback: function to callback on events (index, event_type)'''
        super().__init__([0,1,2,3])
        
        if callback is None:
            logging.getLogger("system").error("XInput: invalid callback provided")
            return
        self._callback = callback
        self._is_running = True

        self._listener = GamepadThread(self)
        self._listener.start()

    def stop(self):
        ''' stops the event loop '''
        if not self._is_running:
            return
        self._is_running = False
        self._listener.stop()
        self._listener = None

    def process_button_event(self,event):
        # map input
        e = XInputEvent()
        e.is_pressed = event.type == EVENT_BUTTON_PRESSED
        
        e.type = XInputEventType.Button
        if event.button == "LEFT_THUMB":
            e.button == XInputButtonType.ThumbLeft
        elif event.button == "RIGHT_THUMB":
            e.button == XInputButtonType.ThumbRight
        elif event.button == "LEFT_SHOULDER":
            e.button == XInputButtonType.ShoulderLeft
        elif event.button == "RIGHT_SHOULDER":
            e.button == XInputButtonType.ShoulderRight
        elif event.button == "BACK":
            e.button == XInputButtonType.Back
        elif event.button == "START":
            e.button == XInputButtonType.Start
        elif event.button == "DPAD_LEFT":
            e.button == XInputButtonType.DPadLeft
        elif event.button == "DPAD_RIGHT":
            e.button == XInputButtonType.DPadRight
        elif event.button == "DPAD_UP":
            e.button == XInputButtonType.DPadUp
        elif event.button == "DPAD_DOWN":
            e.button == XInputButtonType.DPadDown
        elif event.button == "A":
            e.button == XInputButtonType.A
        elif event.button == "B":
            e.button == XInputButtonType.B
        elif event.button == "Y":
            e.button == XInputButtonType.Y
        elif event.button == "X":
            e.button == XInputButtonType.X
        self._callback(e)

    def process_stick_event(self, event):
        e = XInputEvent()
        e.type = XInputEventType.Axis
        e.x = event.x
        e.y = event.y
        self._callback(e)

    def process_trigger_event(self, event):
        e = XInputEvent()
        e.type = XInputEventType.Trigger
        if e.trigger == LEFT:
            e.trigger = XInputTriggerType.Left
        elif e.trigger == RIGHT:
            e.trigger = XInputTriggerType.Right
        e.value = event.value
        self._callback(e)


    def process_connection_event(self, event):
        pass
    