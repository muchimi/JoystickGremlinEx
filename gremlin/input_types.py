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

from __future__ import annotations  # deprecated with python 3.14+
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
    KeyboardLatched = 7  # latched keyboard input
    OpenSoundControl = 8  # open sound control button input
    Midi = 9  # midi input
    ModeControl = 10  # mode actions
    State = 11  # state input
    OctaviIfr1 = 12  # octavi IFR1
    StreamDeck = 13  # Elgato Stream Deck via plugin bridge


    @staticmethod
    def to_string(value) -> str:
        if value is None:
            value = InputType.NotSet
        try:
            return _InputType_to_string_lookup[value]
        except KeyError:
            raise ValueError("Invalid type in lookup")

    def toInt(self):
        return int(self)

    @staticmethod
    def from_string(value) -> "InputType":
        return InputType.to_enum(value)

    @staticmethod
    def to_enum(value) -> "InputType":
        try:
            if value is None:
                return InputType.NotSet
            if isinstance(value, int):
                return InputType(value)
            else:
                return _InputType_to_enum_lookup[value]
        except KeyError:
            raise ValueError("Invalid type in lookup")

    @staticmethod
    def to_name(value) -> str:
        match value:
            case InputType.NotSet:
                return "n/a"
            case InputType.Keyboard | InputType.KeyboardLatched:
                return "Kbd"
            case InputType.JoystickAxis:
                return "Axis"
            case InputType.JoystickButton:
                return "Button"
            case InputType.JoystickHat:
                return "Hat"
            case InputType.Mouse:
                return "Mouse"
            case InputType.VirtualButton:
                return "VButton"
            case InputType.OpenSoundControl:
                return "OSC"
            case InputType.Midi:
                return "MIDI"
            case InputType.ModeControl:
                return "ModeCtrl"
            case InputType.State:
                return "State"
            case InputType.OctaviIfr1:
                return "IFR1"
            case InputType.StreamDeck:
                return "StreamDeck"
            case _:
                return f"Don't know how to handle {value}"

    @staticmethod
    def to_list(include_notset=False, include_mouse=False, include_virtualbutton=False) -> list:
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

    @staticmethod
    def convert(value) -> InputType:
        try:
            if isinstance(value, int):
                input_type = InputType(value)
                return input_type
            if value in _InputType_to_enum_lookup:
                input_type = _InputType_to_enum_lookup[value]
                return input_type

        except Exception:
            pass
        return None

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
    InputType.ModeControl: "mode-control",
    InputType.State: "state",
    InputType.OctaviIfr1: "ifr1",
    InputType.StreamDeck: "streamdeck",
    InputType.Mouse: "mouse",
}

_InputType_to_display_lookup = {
    InputType.NotSet: "N/A",
    InputType.JoystickAxis: "Axis",
    InputType.JoystickButton: "Button",
    InputType.JoystickHat: "Hat",
    InputType.Keyboard: "Key",
    InputType.KeyboardLatched: "Latched Key",
    InputType.OpenSoundControl: "OSC Button",
    InputType.Midi: "MIDI",
    InputType.ModeControl: "Mode Control",
    InputType.State: "State",
    InputType.OctaviIfr1: "Octavi IFR1",
    InputType.StreamDeck: "Stream Deck",
    InputType.Mouse: "Mouse",
}


_InputType_to_enum_lookup = {
    "none": InputType.NotSet,
    "axis": InputType.JoystickAxis,
    "mouse": InputType.Mouse,
    "button": InputType.JoystickButton,
    "hat": InputType.JoystickHat,
    "key": InputType.KeyboardLatched,
    "keyboard": InputType.KeyboardLatched,
    "keylatched": InputType.KeyboardLatched,
    "osc": InputType.OpenSoundControl,
    "midi": InputType.Midi,
    "modecontrol": InputType.ModeControl,
    "mode-control": InputType.ModeControl,
    "state": InputType.State,
    "ifr1": InputType.OctaviIfr1,
    "streamdeck": InputType.StreamDeck,
    "NotSet": InputType.NotSet,
    "JoystickAxis": InputType.JoystickAxis,
    "Mouse": InputType.Mouse,
    "JoystickButton": InputType.JoystickButton,
    "JoystickHat": InputType.JoystickHat,
    "Keyboard": InputType.Keyboard,
    "KeyboardLatched": InputType.KeyboardLatched,
    "OpenSoundControl": InputType.OpenSoundControl,
    "Midi": InputType.Midi,
    "ModeControl": InputType.ModeControl,
    "State": InputType.State,
    "OctaviIfr1": InputType.OctaviIfr1,
    "StreamDeck": InputType.StreamDeck,
}
