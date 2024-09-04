
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


import enum

class InputType(enum.IntEnum):

    """Enumeration of possible input types."""

    NotSet = 0
    Keyboard = 1
    JoystickAxis = 2
    JoystickButton = 3
    JoystickHat = 4
    Mouse = 5
    VirtualButton = 6
    KeyboardLatched = 7 # latched keyboard input
    OpenSoundControl = 8 # open sound control
    Midi = 9 # midi input


    @staticmethod
    def to_string(value):
        if value is None:
            value = InputType.NotSet
        try:
            return _InputType_to_string_lookup[value]
        except KeyError:
            raise ValueError("Invalid type in lookup")

    @staticmethod
    def to_enum(value):
        try:
            if value is None:
                return InputType.NotSet
            return _InputType_to_enum_lookup[value]
        except KeyError:
            raise ValueError("Invalid type in lookup")
        
    @staticmethod
    def to_list(include_notset = False, include_mouse = False, include_virtualbutton = False) -> list:
        data = [it for it in InputType]
        if not include_notset:
            data.remove(InputType.NotSet)
        if not include_mouse:
            data.remove(InputType.Mouse)
        if not include_virtualbutton:
            data.remove(InputType.VirtualButton)
        return data
    
    @staticmethod
    def to_display_name(value) -> str:
        if value in _InputType_to_display_lookup.keys():
            return _InputType_to_string_lookup[value]
        return f"Unknown type: {value}"
    
    # JSON serializer


_InputType_to_string_lookup = {
    InputType.NotSet: "none",
    InputType.JoystickAxis: "axis",
    InputType.JoystickButton: "button",
    InputType.JoystickHat: "hat",
    InputType.Keyboard: "key",
    InputType.KeyboardLatched: "keylatched",
    InputType.OpenSoundControl: "osc",
    InputType.Midi: "midi",
}

_InputType_to_display_lookup = {
    InputType.JoystickAxis: "Axis",
    InputType.JoystickButton: "Button",
    InputType.JoystickHat: "Hat",
    InputType.Keyboard: "Key",
    InputType.KeyboardLatched: "Latched Key",
    InputType.OpenSoundControl: "OSC",
    InputType.Midi: "MIDI",
}


_InputType_to_enum_lookup = {
    "none": InputType.NotSet,
    "axis": InputType.JoystickAxis,
    "button": InputType.JoystickButton,
    "hat": InputType.JoystickHat,
    "key": InputType.Keyboard,
    "keylatched": InputType.KeyboardLatched,
    "osc": InputType.OpenSoundControl,
    "midi": InputType.Midi
}

