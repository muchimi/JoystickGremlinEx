# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2020 Lionel Ott
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

from enum import Enum, auto, IntFlag, IntEnum, unique

from typing import Tuple, Union

import gremlin.error

import logging
import enum


syslog = logging.getLogger("system")

class VisualizationType(IntEnum):

    """Enumeration of possible visualization types."""

    AxisTemporal = 1
    AxisCurrent = 2
    ButtonHat = 3
    Keyboard = 4 
    State = 5
    Button = 6
    Hat = 7


class KeyboardOutputMode(Enum): # order is that of the display order for keyboard mapper options
    Pulse = 0 # keyboard make and break (press/release) (pulse mode)
    AutoRepeat = 1 # pulse mode - key pulses while the input is held
    Press = 2 # keyboard make only
    Release = 3 # keyboard release only
    Hold = 4 # press while held (default GremlinEx behavior)
    Toggle = 5 # toggles make / break

    @staticmethod
    def to_displayname(value : KeyboardOutputMode):
        match value:
            case  KeyboardOutputMode.Pulse:
                return "Pulse Single"
            case  KeyboardOutputMode.AutoRepeat:
                return "Pulse Repeat"
        return value.name
    
    

    
class ActivationRule(Enum):

    """Activation rules for collections of conditions.

    All requires all the conditions in a collection to evaluate to True while
    Any only requires a single condition to be True.
    """

    All = 1
    Any = 2



class AxisNames(Enum):

    """Names associated with axis indices."""

    X = 1
    Y = 2
    Z = 3
    RX = 4
    RY = 5
    RZ = 6
    SLIDER = 7
    DIAL = 8

    @staticmethod
    def to_string(value: AxisNames) -> str:
        try:
            return _AxisNames_to_string_lookup[value]
        except KeyError:
            syslog.error(f"AxisNames: Don't know how to convert axis to string: '{value}' to a string - defaulting to X (1)")
            return "X"

    @staticmethod
    def to_enum(value: str) -> AxisNames:
        try:
            return _AxisNames_to_enum_lookup[value]
        except KeyError:
            syslog.error(f"AxisNames: Don't know how to convert axis to enum: '{value}' to a string - defaulting to X (1)")
            return AxisNames.X
        
    @staticmethod
    def to_list():
        return [axis for axis in AxisNames]


_AxisNames_to_string_lookup = {
    AxisNames.X: "X Axis (1)",
    AxisNames.Y: "Y Axis (2)",
    AxisNames.Z: "Z Axis (3)",
    AxisNames.RX: "X Rotation (4)",
    AxisNames.RY: "Y Rotation (5)",
    AxisNames.RZ: "Z Rotation (6)",
    AxisNames.SLIDER: "Slider (7)",
    AxisNames.DIAL: "Dial (8)"
}
_AxisNames_to_enum_lookup = {
    "X Axis (1)": AxisNames.X,
    "Y Axis (2)": AxisNames.Y,
    "Z Axis (3)": AxisNames.Z,
    "X Rotation (4)": AxisNames.RX,
    "Y Rotation (5)": AxisNames.RY,
    "Z Rotation (6)": AxisNames.RZ,
    "Slider (7)": AxisNames.SLIDER,
    "Dial (8)": AxisNames.DIAL
}


class AxisButtonDirection(Enum):

    """Possible activation directions for axis button instances."""

    Anywhere = 1
    Below = 2
    Above = 3,
    
    @staticmethod
    def to_string(value: AxisButtonDirection) -> str:
        try:
            return _AxisButtonDirection_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                f"Invalid AxisButtonDirection lookup, {value}"
            )

    @staticmethod
    def to_enum(value: str) -> AxisButtonDirection:
        try:
            return _AxisButtonDirection_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                f"Invalid AxisButtonDirection lookup, {value}"
            )


_AxisButtonDirection_to_string_lookup = {
    AxisButtonDirection.Anywhere: "anywhere",
    AxisButtonDirection.Above: "above",
    AxisButtonDirection.Below: "below",
    

}
_AxisButtonDirection_to_enum_lookup = {
    "anywhere": AxisButtonDirection.Anywhere,
    "above": AxisButtonDirection.Above,
    "below": AxisButtonDirection.Below,
}



class xIntEnum(IntEnum):
    def __eq__(self, other):
        if type(self).__name__ == type(other).__name__:
            return self.value == other.value
        if other is int:
            return self.value == other
        return False
    
    def __hash__(self) -> int:
        return hash(self.value)
    
class ControlAction(IntEnum):
    ''' defines the available control actions for the control plugin'''
    EnableInput = 0 # enables an input
    DisableInput = 1 # disable an input
    ToggleInput = 2 # toggle the input
    TTSAbort = 3 # abort current text to speech (clears queue and aborts current speech if any)
    RemoteEnable = 4 # enable remote output
    RemoteDisable = 5 # disable remote output
    RemoteToggle = 6 # toggle remote control
    LocalEnable = 7 # enable local output
    LocalDisable = 8 # disable local output
    ProfileStop = 9 # stop current profile


    @staticmethod
    def to_string(action):
        return action.name.casefold()
    
    @staticmethod
    def from_string(name):
        name = name.casefold()
        for action in ControlAction:
            if action.name.casefold() == name:
                return action
        return None
    
    
    @staticmethod
    def to_display_name(action):
        return _control_action_display[action]
        
        
_control_action_display = {
    ControlAction.EnableInput: "Enable Input",
    ControlAction.DisableInput: "Disable Input",
    ControlAction.ToggleInput: "Toggle Input",
    ControlAction.TTSAbort: "Stop TTS",
    ControlAction.RemoteEnable: "Enable remote control",
    ControlAction.RemoteDisable: "Disable remote control",
    ControlAction.LocalEnable: "Enable local control",
    ControlAction.LocalDisable: "Disable local control",
    ControlAction.ProfileStop: "Stop profile",
    ControlAction.RemoteToggle: "Toggle Remote",
}


        

class DeviceType(IntEnum):

    """Enumeration of the different possible input types."""
    NotSet = 0 # not set
    Keyboard = 1 # keyboard special device
    Joystick = 2 # joystick or game controller
    VJoy = 3 # vjoy (virtual)
    Midi = 4 # midi special device
    Osc = 5 # open source control special device
    ModeControl = 6 # mode control special device
    Settings = 7 # settings special device
    State = 8 # state special device
    Plugins = 9 # plugins special device
    OctaviIFR1 = 10 # octavi IFR1 special device

    @staticmethod
    def to_string(value):
        if value in _DeviceType_to_string_lookup:
            return _DeviceType_to_string_lookup[value]
        syslog.error(f"DeviceType lookup failed in to_string(): unable to find type: [{value}] - defaulting to NotSet")
        return "invalid"
        

    @staticmethod
    def to_enum(value):
        if isinstance(value, int):
            return DeviceType.VJoy
        value = value.casefold()
        if value in _DeviceType_to_enum_lookup:
            return _DeviceType_to_enum_lookup[value]
        syslog.error(f"DeviceType lookup failed in to_enum(): unable to find type: [{value}] - defaulting to NotSet")
        return DeviceType.NotSet
        
        
    @staticmethod
    def to_display_name(value):
        if value in _DeviceType_to_display_name:
            return _DeviceType_to_display_name[value]
        syslog.error(f"DeviceType lookup failed in to_display_name(): unable to find : [{value}]")
        return f"Unknown device type: [{value}]"

_DeviceType_to_display_name = {
    DeviceType.NotSet: "(invalid)",
    DeviceType.Keyboard: "Keyboard",
    DeviceType.Joystick: "Joystick",
    DeviceType.VJoy: "VJoy",
    DeviceType.Midi: "MIDI",
    DeviceType.Osc: "OSC",
    DeviceType.ModeControl: "Mode Control",
    DeviceType.Settings : "Settings",
    DeviceType.State : "State",
    DeviceType.Plugins : "Plugins",
    DeviceType.OctaviIFR1 : "Octavi IFR1"
}

_DeviceType_to_string_lookup = {
    DeviceType.NotSet: "invalid",
    DeviceType.Keyboard: "keyboard",
    DeviceType.Joystick: "joystick",
    DeviceType.VJoy: "vjoy",
    DeviceType.Midi: "midi",
    DeviceType.Osc: "osc",
    DeviceType.ModeControl: "mode",
    DeviceType.Settings: "settings",
    DeviceType.State: "state",
    DeviceType.Plugins: "plugins",
    DeviceType.OctaviIFR1: "octaviifr1"
}


_DeviceType_to_enum_lookup = {
    "invalid": DeviceType.NotSet,
    "keyboard": DeviceType.Keyboard,
    "joystick": DeviceType.Joystick,
    "vjoy": DeviceType.VJoy,
    "midi": DeviceType.Midi,
    "osc": DeviceType.Osc,
    "mode": DeviceType.ModeControl,
    "settings": DeviceType.Settings,
    "state" : DeviceType.State,
    "plugins" : DeviceType.Plugins,
    "octaviifr1" : DeviceType.OctaviIFR1

}


class PluginVariableType(xIntEnum):

    """Enumeration of all supported variable types."""

    Int = 1
    Float = 2
    String = 3
    Bool = 4
    PhysicalInput = 5
    VirtualInput = 6
    Mode = 7
    Selection = 8

    @staticmethod
    def to_string(value: PluginVariableType) -> str:
        try:
            v = value.value
            data = next((item for item in PluginVariableType if item.value == v),None)
            return _PluginVariableType_to_string_lookup[data]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid PluginVariableType in lookup"
            )

    @staticmethod
    def to_enum(value: str) -> PluginVariableType:
        try:
            return _PluginVariableType_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid PluginVariableType in lookup"
            )
        
    


_PluginVariableType_to_string_lookup = {
    PluginVariableType.Int: "Int",
    PluginVariableType.Float: "Float",
    PluginVariableType.String: "String",
    PluginVariableType.Bool: "Bool",
    PluginVariableType.PhysicalInput: "PhysicalInput",
    PluginVariableType.VirtualInput: "VirtualInput",
    PluginVariableType.Mode: "Mode",
    PluginVariableType.Selection: "Selection"
}
_PluginVariableType_to_enum_lookup = {
    "Int": PluginVariableType.Int,
    "Float": PluginVariableType.Float,
    "String": PluginVariableType.String,
    "Bool": PluginVariableType.Bool,
    "PhysicalInput": PluginVariableType.PhysicalInput,
    "VirtualInput": PluginVariableType.VirtualInput,
    "Mode": PluginVariableType.Mode,
    "Selection": PluginVariableType.Selection
}


class MergeAxisOperation(Enum):

    """Possible merge axis operation modes."""

    Average = 1
    Minimum = 2
    Maximum = 3
    Sum = 4

    @staticmethod
    def to_string(value: MergeAxisOperation) -> str:
        try:
            return _MergeAxisOperation_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid MergeAxisOperation in lookup"
            )

    @staticmethod
    def to_enum(value: str) -> MergeAxisOperation:
        try:
            return _MergeAxisOperation_to_enum_lookup[value.lower()]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid MergeAxisOperation in lookup"
            )


_MergeAxisOperation_to_string_lookup = {
    MergeAxisOperation.Average: "average",
    MergeAxisOperation.Minimum: "minimum",
    MergeAxisOperation.Maximum: "maximum",
    MergeAxisOperation.Sum: "sum"
}
_MergeAxisOperation_to_enum_lookup = {
    "average": MergeAxisOperation.Average,
    "minimum": MergeAxisOperation.Minimum,
    "maximum": MergeAxisOperation.Maximum,
    "sum": MergeAxisOperation.Sum
}


class PropertyType(Enum):

    """Enumeration of all known property types."""

    String = 1
    Int = 2
    Float = 3
    Bool = 4
    AxisValue = 5
    IntRange = 6
    FloatRange = 7
    AxisRange = 8
    InputType = 9
    KeyboardKey = 10
    MouseInput = 11
    GUID = 12
    UUID = 13
    AxisMode = 14
    HatDirection = 15
    List = 16

    @staticmethod
    def to_string(value: PropertyType) -> str:
        try:
            return _PropertyType_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid PropertyType in lookup"
            )

    @staticmethod
    def to_enum(value: str) -> PropertyType:
        try:
            return _PropertyType_to_enum_lookup[value.lower()]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid PropertyType in lookup"
            )

_PropertyType_to_string_lookup = {
    PropertyType.String: "string",
    PropertyType.Int: "int",
    PropertyType.Float: "float",
    PropertyType.Bool: "bool",
    PropertyType.AxisValue: "axis_value",
    PropertyType.IntRange: "int_range",
    PropertyType.FloatRange: "float_range",
    PropertyType.AxisRange: "axis_range",
    PropertyType.InputType: "input_type",
    PropertyType.KeyboardKey: "keyboard_key",
    PropertyType.MouseInput: "mouse_input",
    PropertyType.GUID: "guid",
    PropertyType.UUID: "uuid",
    PropertyType.AxisMode: "axis_mode",
    PropertyType.HatDirection: "hat_direction",
    PropertyType.List: "list",
}
_PropertyType_to_enum_lookup = {
    "string": PropertyType.String,
    "int": PropertyType.Int,
    "float": PropertyType.Float,
    "bool": PropertyType.Bool,
    "axis_value": PropertyType.AxisValue,
    "int_range": PropertyType.IntRange,
    "float_range": PropertyType.FloatRange,
    "axis_range": PropertyType.AxisRange,
    "input_type": PropertyType.InputType,
    "keyboard_key": PropertyType.KeyboardKey,
    "mouse_input": PropertyType.MouseInput,
    "guid": PropertyType.GUID,
    "uuid": PropertyType.UUID,
    "axis_mode": PropertyType.AxisMode,
    "hat_direction": PropertyType.HatDirection,
    "list": PropertyType.List
}


class AxisMode(Enum):

    Absolute = 1
    Relative = 2

    @staticmethod
    def to_string(value: AxisMode) -> str:
        try:
            return _AxisMode_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid AxisMode in lookup"
            )

    @staticmethod
    def to_enum(value: str) -> AxisMode:
        try:
            return _AxisMode_to_enum_lookup[value.lower()]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid AxisMode in lookup"
            )

_AxisMode_to_string_lookup = {
    AxisMode.Absolute: "absolute",
    AxisMode.Relative: "relative"
}
_AxisMode_to_enum_lookup = {
    "absolute": AxisMode.Absolute,
    "relative": AxisMode.Relative
}


class HatDirection(Enum):

    """Represents the possible directions a hat can take on."""

    Center = (0, 0)
    North = (0, 1)
    NorthEast = (1, 1)
    East = (1, 0)
    SouthEast = (1, -1)
    South = (0, -1)
    SouthWest = (-1, -1)
    West = (-1, 0)
    NorthWest = (-1, 1)

    @staticmethod
    def to_string(value: HatDirection) -> str:
        try:
            return _HatDirection_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid HatDirection in lookup"
            )

    @staticmethod
    def to_enum(value: Union[str, Tuple[int, int]]) -> HatDirection:
        try:
            if isinstance(value, HatDirection):
                return value
            elif isinstance(value, str):
                return _HatDirection_to_enum_lookup[value.lower()]
            else:
                return _HatDirection_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid HatDirection in lookup"
            )
        
    @staticmethod
    def to_position(value : HatDirection) -> tuple:
        return value.value
        
    @staticmethod
    def to_display_name(value: HatDirection) -> str:
        return value.name

_HatDirection_to_string_lookup = {
    HatDirection.Center: "center",
    HatDirection.North: "north",
    HatDirection.NorthEast: "north-east",
    HatDirection.East: "east",
    HatDirection.SouthEast: "south-east",
    HatDirection.South: "south",
    HatDirection.SouthWest: "south-west",
    HatDirection.West: "west",
    HatDirection.NorthWest: "north-west",
}

_HatDirection_to_enum_lookup = {
    # String based
    "center": HatDirection.Center,
    "north": HatDirection.North,
    "north-east": HatDirection.NorthEast,
    "east": HatDirection.East,
    "south-east": HatDirection.SouthEast,
    "south": HatDirection.South,
    "south-west": HatDirection.SouthWest,
    "west": HatDirection.West,
    "north-west": HatDirection.NorthWest,
    # Direction tuple based
    (0, 0): HatDirection.Center,
    (0, 1): HatDirection.North,
    (1, 1): HatDirection.NorthEast,
    (1, 0): HatDirection.East,
    (1, -1): HatDirection.SouthEast,
    (0, -1): HatDirection.South,
    (-1, -1): HatDirection.SouthWest,
    (-1, 0): HatDirection.West,
    (-1, 1): HatDirection.NorthWest,
}



class LogicalOperator(Enum):

    """Enumeration of possible condition combinations."""

    Any = 1
    All = 2

    @staticmethod
    def to_display(instance: LogicalOperator) -> str:
        lookup = {
            LogicalOperator.Any: "Any",
            LogicalOperator.All: "All"
        }
        value = lookup.get(instance, None)
        if value is None:
            raise gremlin.error.GremlinError(
                f"Invalid logical operator type: {str(instance)}"
            )
        return value

    @staticmethod
    def to_string(instance: LogicalOperator) -> str:
        lookup = {
            LogicalOperator.Any: "any",
            LogicalOperator.All: "all"
        }
        value = lookup.get(instance, None)
        if value is None:
            raise gremlin.error.GremlinError(
                f"Invalid logical operator type: {str(instance)}"
            )
        return value

    @staticmethod
    def to_enum(string: str) -> LogicalOperator:
        lookup = {
            "any": LogicalOperator.Any,
            "all": LogicalOperator.All
        }
        value = lookup.get(string, None)
        if value is None:
            raise gremlin.error.GremlinError(
                f"Invalid logical operator type: {str(string)}"
            )
        return value


class ConditionType(Enum):

    """Enumeration of possible condition types."""

    Joystick = 1
    Keyboard = 2
    CurrentInput = 3

    @staticmethod
    def to_display(instance: ConditionType) -> str:
        lookup = {
            ConditionType.Joystick: "Joystick",
            ConditionType.Keyboard: "Keyboard",
            ConditionType.CurrentInput: "Current Input",
        }
        value = lookup.get(instance, None)
        if value is None:
            raise gremlin.error.GremlinError(
                f"Invalid condition operator type: {str(instance)}"
            )
        return value

    @staticmethod
    def to_string(instance: ConditionType) -> str:
        lookup = {
            ConditionType.Joystick: "joystick",
            ConditionType.Keyboard: "keyboard",
            ConditionType.CurrentInput: "current_input",
        }
        value = lookup.get(instance, None)
        if value is None:
            raise gremlin.error.GremlinError(
                f"Invalid condition operator type: {str(instance)}"
            )
        return value

    @staticmethod
    def to_enum(string: str) -> ConditionType:
        lookup = {
            "joystick": ConditionType.Joystick,
            "keyboard": ConditionType.Keyboard,
            "current_input": ConditionType.CurrentInput,
        }
        value = lookup.get(string, None)
        if value is None:
            raise gremlin.error.GremlinError(
                f"Invalid condition operator type: {str(string)}"
            )
        return value



class MouseClickMode(Enum):
    Normal = 0 # click on/off
    Press = 1 # press only
    Release = 2 # release only
    DoubleClick = 3 # double click

    @staticmethod
    def to_string(mode):
        return mode.name
    
    def __str__(self):
        return str(self.value)
    
    @classmethod
    def _missing_(cls, name):
        for item in cls:
            if item.name.lower() == name.lower():
                return item
            return cls.Normal
        
    @staticmethod
    def from_string(str):
        ''' converts from a string representation (text or numeric) to the enum, not case sensitive'''
        str = str.casefold().strip()
        if str.isnumeric():
            mode = int(str)
            return MouseClickMode(mode)
        for item in MouseClickMode:
            if item.name.casefold() == str:
                return item

        return None
    
    @staticmethod
    def to_description(action):
        ''' returns a descriptive string for the action '''
        if action == MouseClickMode.Normal:
            return "Normal Click"
        elif action == MouseClickMode.Press:
            return "Mouse button press"
        elif action == MouseClickMode.Release:
            return "Mouse button release"
        elif action == MouseClickMode.DoubleClick:
            return "Double Click"
        return f"Unknown {action}"
    
    
    @staticmethod
    def to_name(action):
        ''' returns the name from the action '''
        if action == MouseClickMode.Normal:
            return "Normal Click"
        elif action == MouseClickMode.Press:
            return "Mouse button press"
        elif action == MouseClickMode.Release:
            return "Mouse button release"
        elif action == MouseClickMode.DoubleClick:
            return "Double click"
        return f"Unknown {action}"
    
class MouseAction(Enum):
    MouseButton = 0 # output a mouse button
    MouseMotion = 1 # output a mouse motion
    MousePosition = 2 # set the exact mouse position (via setcursorposition)
    MouseSetPrecisionPosition = 3 # set the exact mouse position via send input precision

    @staticmethod
    def to_string(mode):
        return mode.name
    
    def __str__(self):
        return str(self.value)
    
    @classmethod
    def _missing_(cls, name):
        for item in cls:
            if item.name.lower() == name.lower():
                return item
            return cls.MouseButton
        
    @staticmethod
    def from_string(str):
        ''' converts from a string representation (text or numeric) to the enum, not case sensitive'''
        str = str.lower().strip()
        if str.isnumeric():
            mode = int(str)
            return MouseAction(mode)
        for item in MouseAction:
            if item.name.lower() == str:
                return item

        return None
    
    @staticmethod
    def to_description(action):
        ''' returns a descriptive string for the action '''
        match action:
            case MouseAction.MouseButton:
                return "Maps a mouse button"
            case MouseAction.MouseMotion:
                return "Maps to a mouse motion axis"
            case MouseAction.MousePosition:
                return "Sets the mouse position"


        return f"Unknown [{action}]"
    
    @staticmethod
    def to_name(action):
        ''' returns the name from the action '''
        match action:
            case MouseAction.MouseButton:
                return "Mouse button"
            case MouseAction.MouseMotion:
                return "Mouse axis"
            case MouseAction.MousePosition:
                return "Mouse position"
            case MouseAction.MouseSetPrecisionPosition:
                return "Mouse position (precision)"
            



                
        return f"Unknown [{action}]"
    
class MouseButton(IntEnum):

    """Enumeration of all possible mouse buttons."""
    NotSet = 0, # not a button
    Left = 1
    Right = 2
    Middle = 3
    DoubleLeft = 0x101 # add 0x100
    DoubleRight = 0x102 # add 0x100
    DoubleMiddle = 0x103 # add 0x100
    Forward = 4
    Back = 5
    WheelUp = 10
    WheelDown = 11
    WheelLeft = 12
    WheelRight = 13
    Wheel = 14 # up down wheel
    HWheel = 15# left right wheel


    @staticmethod
    def to_string(value):
        try:
            return _MouseButton_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")

    @staticmethod
    def to_enum(value):
        if isinstance(value, int):
            return MouseButton(value)
        try:
            return _MouseButton_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")
        
    @staticmethod
    def to_lookup_string(value):
        ''' mouse button to key lookup name'''
        try:
            return _MouseButton_to_lookup_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")
        
    @staticmethod
    def lookup_to_enum(value):
        if isinstance(value, int):
            return MouseButton(value)
        try:
            return _MouseButton_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")
        
    def to_short_name(value):
        if value in _MouseButton_to_enum_lookup:
            value = _MouseButton_to_enum_lookup[value] # to enum
        if value in _MouseButton_to_short_string_lookup:
            return _MouseButton_to_short_string_lookup[value] # to short name
        return value
        
    def is_lookup_valid(value):
        # true if the enum is a mouse button
        return value in _MouseButton_to_enum_lookup



_MouseButton_to_string_lookup = {
    MouseButton.NotSet: "N/A",
    MouseButton.Left: "Mouse 1 (left)",
    MouseButton.Right: "Mouse 2 (right)",
    MouseButton.Middle: "Mouse 3 (middle)",
    MouseButton.Forward: "Mouse 4 (forward)",
    MouseButton.Back: "Mouse 5 (back)",
    MouseButton.WheelUp: "Wheel Up",
    MouseButton.WheelDown: "Wheel Down",
    MouseButton.WheelLeft: "Wheel Left",
    MouseButton.WheelRight: "Wheel Right",
    MouseButton.DoubleLeft: "Mouse DClick Left",
    MouseButton.DoubleRight: "Mouse DClick Right",
    MouseButton.DoubleMiddle: "Mouse DClick Middle",
    MouseButton.Wheel: "Vertical Wheel",
    MouseButton.HWheel: "Horizontal Wheel"
}

_MouseButton_to_short_string_lookup = {
    MouseButton.NotSet: "N/A",
    MouseButton.Left: "M1",
    MouseButton.Right: "M2",
    MouseButton.Middle: "M3",
    MouseButton.Forward: "M4",
    MouseButton.Back: "M5",
    MouseButton.WheelUp: "MWU",
    MouseButton.WheelDown: "MWD",
    MouseButton.WheelLeft: "MWL",
    MouseButton.WheelRight: "MWR",
    MouseButton.DoubleLeft: "DC1",
    MouseButton.DoubleRight: "DC2",
    MouseButton.DoubleMiddle: "DC3",
    MouseButton.Wheel: "VW",
    MouseButton.HWheel: "HW"
}

_MouseButton_to_lookup_string_lookup = {
    MouseButton.NotSet: "null",
    MouseButton.Left: "mouse_1",
    MouseButton.Right: "mouse_2",
    MouseButton.Middle: "mouse_3",
    MouseButton.Forward: "mouse_4",
    MouseButton.Back: "mouse_5",
    MouseButton.WheelUp: "wheel_up",
    MouseButton.WheelDown: "wheel_down",
    MouseButton.WheelLeft: "wheel_left",
    MouseButton.WheelRight: "wheel_right",
    MouseButton.DoubleLeft: "mouse_d_1",
    MouseButton.DoubleRight: "mouse_d_2",
    MouseButton.DoubleMiddle: "mouse_d_3",
    MouseButton.Wheel: "v_wheel",
    MouseButton.HWheel: "h_wheel"
}



_MouseButton_to_enum_lookup = {
    "N/A" : MouseButton.NotSet,
    "null" : MouseButton.NotSet,
    "Mouse Left": MouseButton.Left,
    "Mouse Right": MouseButton.Right,
    "Mouse Middle": MouseButton.Middle,
    "Mouse Forward": MouseButton.Forward,
    "Mouse Back": MouseButton.Back,
    "Mouse Wheel Up": MouseButton.WheelUp,
    "Mouse Wheel Down": MouseButton.WheelDown,
    "Left": MouseButton.Left,
    "Right": MouseButton.Right,
    "Middle": MouseButton.Middle,
    "Forward": MouseButton.Forward,
    "Back": MouseButton.Back,
    "Wheel Up": MouseButton.WheelUp,
    "wheel_up": MouseButton.WheelUp,
    "Wheel Down": MouseButton.WheelDown,
    "wheel_down": MouseButton.WheelDown,
    "Wheel Left": MouseButton.WheelLeft,
    "wheel_left": MouseButton.WheelLeft,
    "Wheel Right": MouseButton.WheelRight,
    "wheel_right": MouseButton.WheelRight,
    "mouse_d_1" : MouseButton.DoubleLeft,
    "mouse_d_2" : MouseButton.DoubleRight,
    "mouse_d_3" : MouseButton.DoubleMiddle,
    "v_wheel": MouseButton.Wheel,
    "h_wheel": MouseButton.HWheel,
    "VW": MouseButton.Wheel,
    "HW": MouseButton.HWheel,

}



@unique
class VerboseMode(IntFlag):
    NotSet = 0
    Keyboard = auto() # keyboard input only
    Joystick = auto() # joystick input
    Inputs = auto() # list inputs
    Mouse = auto() # mouse output
    MouseInput = auto() # mouse input
    SimConnect = auto() # simconnect interface
    Details = auto() # user interface details
    Condition = auto() # conditions diagnostics / execution graph
    OSC = auto() # OSC data 
    Process = auto() # process changes
    Exec = auto() # execution trees
    Midi = auto() # midi mode
    Device = auto() # device change modes
    Macro = auto() # macro 
    Gate = auto() # auto
    Outputs = auto() # list outputs
    UI = auto() # UI mode
    ExecDetails = auto()
    VJoy = auto()
    State = auto() # state management
    Extra = auto() # extra info for any other mode
    Remote = auto() # remote receive
    Container = auto() # container debug mode
    Octavi = auto()
    dinput = auto()
    Curve = auto()
    TTS = auto()
    Sound = auto()
    Filter = auto()
    Perf = auto()
    Events = auto()
    Calib = auto()
    Hooks = auto()
    Merge = auto()
    Sequence = auto()
    Mode = auto()
    InputItems = auto()
    Switch = auto()
    All = Keyboard | Joystick | Inputs | Mouse | MouseInput | Details | \
          SimConnect | Condition | Process | Exec | Midi | \
          Device | Macro | Gate | Outputs | UI | ExecDetails |\
          VJoy | State | Extra | Remote | Container | Octavi |\
          dinput | Curve | TTS | Sound | Filter | Perf | Events |\
          Calib | Hooks | Merge | Sequence | Mode | InputItems | Switch

    def __contains__(self, item):
        return  (self.value & item.value) == item.value


@unique
class TabDeviceType(int, Enum):
    ''' types of devices shown on device tabs '''
    NotSet = 0
    Joystick = 1
    Keyboard = 2
    Midi = 3
    Osc = 4
    VjoyInput = 5
    VjoyOutput = 6
    Settings = 7
    Plugins = 8
    ModeControl = 9
    State = 10
    OctaviIFR1 = 11


class GamePadOutput(Enum):
    ''' outputs for gamepads '''
    NotSet = auto()
    LeftStickX = auto()
    LeftStickY = auto()
    RightStickX = auto()
    RightStickY = auto()
    LeftTrigger = auto()
    RightTrigger = auto()
    ButtonA = auto()
    ButtonB = auto()
    ButtonX = auto()
    ButtonY = auto()
    ButtonStart = auto()
    ButtonBack = auto()
    ButtonThumbLeft = auto()
    ButtonThumbRight = auto()
    ButtonGuide = auto()
    ButtonShoulderLeft = auto()
    ButtonShoulderRight = auto()
    ButtonDpadUp = auto()
    ButtonDpadDown = auto()
    ButtonDpadLeft = auto()
    ButtonDpadRight = auto()

    @staticmethod
    def to_string(value):
        return _gamepad_output_to_string[value]
    
    @staticmethod
    def to_enum(value):
        return _gamepad_output_to_enum[value]
    
    @staticmethod
    def to_display_name(value):
        return _gamepad_output_to_display_name[value]
    
_gamepad_output_to_string = {
    GamePadOutput.NotSet : "none",
    GamePadOutput.LeftStickX: "left_x",
    GamePadOutput.LeftStickY: "left_y",
    GamePadOutput.RightStickX: "right_x",
    GamePadOutput.RightStickY: "right_y",
    GamePadOutput.LeftTrigger: "left_trigger",
    GamePadOutput.RightTrigger: "right_trigger",
    GamePadOutput.ButtonA: "button_a",
    GamePadOutput.ButtonB:"button_b",
    GamePadOutput.ButtonX: "button_x",
    GamePadOutput.ButtonY:"button_y",
    GamePadOutput.ButtonStart:"button_start",
    GamePadOutput.ButtonBack:"button_back",
    GamePadOutput.ButtonThumbLeft:"button_thumb_left",
    GamePadOutput.ButtonThumbRight:"button_thumb_right",
    GamePadOutput.ButtonGuide:"button_guide",
    GamePadOutput.ButtonShoulderLeft:"button_shoulder_left",
    GamePadOutput.ButtonShoulderRight:"button_shoulder_right",
    GamePadOutput.ButtonDpadUp:"button_dpad_up",
    GamePadOutput.ButtonDpadDown:"button_dpad_down",
    GamePadOutput.ButtonDpadLeft:"button_dpad_left",
    GamePadOutput.ButtonDpadRight:"button_dpad_right",
}

_gamepad_output_to_display_name = {
    GamePadOutput.NotSet : "N/A",
    GamePadOutput.LeftStickX: "Left Stick X",
    GamePadOutput.LeftStickY: "Left Stick Y",
    GamePadOutput.RightStickX: "Right Stick X",
    GamePadOutput.RightStickY: "Right Stick Y",
    GamePadOutput.LeftTrigger: "Left Trigger",
    GamePadOutput.RightTrigger: "Right Trigger",
    GamePadOutput.ButtonA: "A",
    GamePadOutput.ButtonB:"B",
    GamePadOutput.ButtonX: "X",
    GamePadOutput.ButtonY:"Y",
    GamePadOutput.ButtonStart:"Start",
    GamePadOutput.ButtonBack:"Back",
    GamePadOutput.ButtonThumbLeft:"Thumb Left",
    GamePadOutput.ButtonThumbRight:"Thumb Right",
    GamePadOutput.ButtonGuide:"Guide",
    GamePadOutput.ButtonShoulderLeft:"Shoulder Left",
    GamePadOutput.ButtonShoulderRight:"Shoulder Right",
    GamePadOutput.ButtonDpadUp:"Dpad Up",
    GamePadOutput.ButtonDpadDown:"Dpad Down",
    GamePadOutput.ButtonDpadLeft:"Dpad Left",
    GamePadOutput.ButtonDpadRight:"Dpad Right",
}

_gamepad_output_to_enum = {
    "none": GamePadOutput.NotSet ,
    "left_x" : GamePadOutput.LeftStickX,
    "left_y": GamePadOutput.LeftStickY ,
    "right_x" : GamePadOutput.RightStickX,
    "right_y": GamePadOutput.RightStickY,
    "left_trigger": GamePadOutput.LeftTrigger,
    "right_trigger": GamePadOutput.RightTrigger,
    "button_a": GamePadOutput.ButtonA,
    "button_b": GamePadOutput.ButtonB,
    "button_x": GamePadOutput.ButtonX,
    "button_y": GamePadOutput.ButtonY,
    "button_start": GamePadOutput.ButtonStart,
    "button_back": GamePadOutput.ButtonBack,
    "button_thumb_left": GamePadOutput.ButtonThumbLeft,
    "button_thumb_right": GamePadOutput.ButtonThumbRight,
    "button_guide": GamePadOutput.ButtonGuide,
    "button_shoulder_left": GamePadOutput.ButtonShoulderLeft,
    "button_shoulder_right": GamePadOutput.ButtonShoulderRight,
    "button_dpad_up": GamePadOutput.ButtonDpadUp,
    "button_dpad_down": GamePadOutput.ButtonDpadDown,
    "button_dpad_left": GamePadOutput.ButtonDpadLeft,
    "button_dpad_right": GamePadOutput.ButtonDpadRight,
}


class ActivationRule(Enum):

    """Activation rules for collections of conditions.

    All requires all the conditions in a collection to evaluate to True while
    Any only requires a single condition to be True.
    """

    All = 1
    Any = 2



class ButtonOutputMode (IntEnum):
    ''' modes for input hats '''
    Hold = 0 # hold while pressed
    Pulse = 1 # pulse once
    Press = 2 # press / on
    Release = 3 # release / off
    NoOp = 4 # do nothing
    Latch = 5 # latch mode (triggers on, sets a timer, an ignores ON retriggers until OFF or until timer lapses)



class SyncMode(IntEnum):
    Ignore = 0 # no sync mode
    Default = 1 # use default value
    Input = 2 # sync to input
    LastOrDefault = 3 # sync to last value if there is one, else to the default state
    LastOrInput = 4 # sync to last value if there is one, else to the input state
    
    @staticmethod
    def to_description(value):
        if value in _syncmode_to_description:
            return _syncmode_to_description[value]
        return f"Unknown mode: {value}"
    
_syncmode_to_description = {
    SyncMode.Ignore : "Do nothing",
    SyncMode.Default : "Use the default value on profile start.",
    SyncMode.Input : "Sync with the current input value",
    SyncMode.LastOrDefault : "Use the last value at profile stop or the default value",
    SyncMode.LastOrInput : "Use the Last value at profile stop or the current input value "
}




class VjoyAction(enum.Enum):
    ''' defines available vjoy actions supported by the vjoy mapper plugins'''
    VJoyButton = 0 # hold state
    VJoyToggle = 1 # toggle function on/off
    VJoyPulse = 2 # pulse function (pulses a button),
    VJoyInvertAxis = 3 # invert axis function
    VJoySetAxis = 4 # set axis value
    VJoyAxis = 5 # normal map to axis
    VJoyHat = 6 #  normal map to hat
    VJoyRangeAxis = 7 # scale axis
    VJoyAxisToButton = 8 # axis to button mapping
    VJoyToggleRemote = 9 # toggle remote control
    VJoyEnableRemoteOnly = 10 # enables remote control, disables local control
    VJoyEnableLocalOnly = 11 # enables local control, disables remote control
    VJoyDisableRemote = 12 # turns remote control off
    VJoyDisableLocal = 13 # turns local control off
    VJoyEnableRemote = 14 # enables remote control (does not impact local control)
    VJoyEnableLocal = 15 # enables local control (does not impact remote control)
    VJoyEnableLocalAndRemote = 16 # enables concurrent local/remote control
    VJoyEnablePairedRemote = 17 # enables primary fire one and two on remote client
    VJoyDisablePairedRemote = 18 # disable primary fire one and two on remote client
    VJoyButtonRelease = 19 # action button release (clear a button if set)
    VJoyMergeAxis = 20 # action to merge another axis
    VJoyHatToButton = 21 # action to map a hat to a button
    VJoySetAxisStepped = 22 # like VjoySetAxis but uses a list of values to bump the index
    VJoyButtonPress = 23 # action on button press
    VJoyButtonInverted = 24 # hold state (inverted = off means pressed, on means released)
    
    @staticmethod
    def is_button_action(mode):
        ''' true if the mode is a button output mode '''
        return mode in (VjoyAction.VJoyButton,
                        VjoyAction.VJoyButtonInverted,
                        VjoyAction.VJoyAxisToButton,
                        VjoyAction.VJoyButtonPress,
                        VjoyAction.VJoyButtonRelease,
                        VjoyAction.VJoyPulse,
                        VjoyAction.VJoyToggle,
        )
                        
  

    @staticmethod
    def to_string(mode):
        return mode.name
    
    def __str__(self):
        return str(self.value)
    
    @classmethod
    def _missing_(cls, name):
        for item in cls:
            if item.name.lower() == name.lower():
                return item
            return cls.VJoyButtonPress

    
    @staticmethod
    def from_string(str):
        ''' converts from a string representation (text or numeric) to the enum, not case sensitive'''
        str = str.lower().strip()
        if str.isnumeric():
            mode = int(str)
            return VjoyAction(mode)
        for item in VjoyAction:
            if item.name.lower() == str:
                return item

        return None
    
    @staticmethod
    def to_description(action):
        ''' returns a descriptive string for the action '''
        match action:
            case VjoyAction.VJoyAxis:
                return "Maps a vjoy axis"
            case VjoyAction.VJoyButtonPress:
                return "Press a vjoy button"
            case VjoyAction.VJoyHat:
                return "Maps to a vjoy hat"
            case VjoyAction.VJoyHatToButton:
                return "Maps a hat position to a vjoy button"
            case VjoyAction.VJoyInvertAxis:
                return "Inverts all output to the specififed axis"
            case VjoyAction.VJoyPulse:
                return "Pulse the vjoy button for a given duration"
            case VjoyAction.VJoySetAxis:
                return "Sets the vjoy axis to a specific value (-1..+1)"
            case VjoyAction.VJoyToggle:
                return "Toggles the vjoy button state"
            case VjoyAction.VJoyRangeAxis:
                return "Sets the vjoy axis active output range"
            case VjoyAction.VJoyAxisToButton:
                return "Maps an axis range to a button value when the axis is in that range"
            case VjoyAction.VJoyEnableLocalOnly:
                return "Enables local output mode and disables remote control"
            case VjoyAction.VJoyEnableRemoteOnly:
                return "Enables remote control and disables local control"
            case VjoyAction.VJoyEnableLocal:
                return "Enables local output (can be concurrent with remote control)"
            case VjoyAction.VJoyEnableRemoteOnly:
                return "Enables remote control (can be concurrent with local control)"
            case VjoyAction.VJoyEnableLocalAndRemote:
                return "Enables local and remote control concurrently"
            case VjoyAction.VJoyToggleRemote:
                return "Toggles between local and remote output modes"
            case VjoyAction.VJoyEnablePairedRemote:
                return "Enables paired remote output mode - remote will echo local"
            case VjoyAction.VJoyDisablePairedRemote:
                return "Disables paired remote output mode"
            case VjoyAction.VJoyEnableRemote:
                return "Enables remote control (remote clients will get inputs)"
            case VjoyAction.VJoyDisableLocal:
                return "Disables local control mode (local input will be disabled)"
            case VjoyAction.VJoyDisableRemote:
                return "Disables remote control mode (remote clients will not get inputs except for paired commands)"
            case VjoyAction.VJoyButtonRelease:
                return "Releases a button"
            case VjoyAction.VJoyMergeAxis:
                return "Merges two (or more) axes into one"
            case VjoyAction.VJoySetAxisStepped:
                return "Steps through set axis values"
            case VjoyAction.VJoyButton:
                return "Presses or releases a button by input state"
            case VjoyAction.VJoyButtonInverted:
                return "Presses or releases a button by inverted input state"

        
        msg  = f"Unknown [{action}]"
        syslog.warning(f"Warning: missing action description mapping: {msg}")
        return msg
        
    @staticmethod
    def to_name(action):
        ''' returns a name string for the action '''
        match action:
            case  VjoyAction.VJoyAxis:
                return "Axis"
            case  VjoyAction.VJoyButtonPress:
                return "Button (Press)"
            case  VjoyAction.VJoyHat:
                return "Hat"
            case  VjoyAction.VJoyHatToButton:
                return "Hat to Button"
            case  VjoyAction.VJoyInvertAxis:
                return "Invert Axis"
            case  VjoyAction.VJoyPulse:
                return "Button (Pulse)"
            case  VjoyAction.VJoySetAxis:
                return "Set Fixed Axis Value"
            case  VjoyAction.VJoyToggle:
                return "Button (Toggle)"
            case VjoyAction.VJoyRangeAxis:
                return "Set Axis Range"
            case  VjoyAction.VJoyAxisToButton:
                return "Axis to Button"
            case  VjoyAction.VJoyEnableLocalOnly:
                return "Enable Local Control (exclusive)"
            case  VjoyAction.VJoyEnableRemoteOnly:
                return "Enable Remote Control (exclusive)"
            case  VjoyAction.VJoyEnableLocal:
                return "Enables Local Control"
            case  VjoyAction.VJoyEnableRemoteOnly:
                return "Enables Remote Control (exclusive)"
            case  VjoyAction.VJoyEnableLocalAndRemote:
                return "Enable Concurrent Local and Remote control"
            case  VjoyAction.VJoyToggleRemote:
                return "Toggle Remote Control"
            case  VjoyAction.VJoyEnablePairedRemote:
                return "Enable remote pairing"
            case  VjoyAction.VJoyDisablePairedRemote:
                return "Disable remote pairing"
            case  VjoyAction.VJoyEnableRemote:
                return "Enable remote control"
            case  VjoyAction.VJoyDisableLocal:
                return "Disable local control"
            case  VjoyAction.VJoyDisableRemote:
                return "Disable remote control"
            case  VjoyAction.VJoyButtonRelease:
                return "Button (Release)"
            case  VjoyAction.VJoyMergeAxis:
                return "Merge Axis"
            case VjoyAction.VJoySetAxisStepped:
                return "Stepped/Linear Axis Value"
            case VjoyAction.VJoyButton:
                return "Button (Hold)"
            case VjoyAction.VJoyButtonInverted:
                return "Button (Inverted)"

        
        msg  = f"Unknown [{action}]"
        syslog.warning(f"Warning: missing action name mapping: {msg}")
        return msg
    

    @staticmethod
    def is_command(value):
        return value in (
        VjoyAction.VJoyDisableLocal,
        VjoyAction.VJoyDisableRemote,
        VjoyAction.VJoyEnableLocalOnly,
        VjoyAction.VJoyEnableRemoteOnly,
        VjoyAction.VJoyEnableLocalAndRemote,
        VjoyAction.VJoyEnableLocal,
        VjoyAction.VJoyEnableRemote,
        VjoyAction.VJoyToggleRemote,
        VjoyAction.VJoyEnablePairedRemote,
        VjoyAction.VJoyDisablePairedRemote,
        )



class SendType(enum.IntEnum):
    ''' send type overrides '''
    Normal = 0 # send normal
    LocalOnly = 1 # local only
    RemoteOnly = 2 # remote only
    LocalAndRemote = 3 # send to both always


    @staticmethod
    def to_description(value):
        match value:
            case SendType.Normal:
                return "Based on profile settings."
            case SendType.LocalOnly:
                return "Local client only regardless of profile setting."
            case SendType.RemoteOnly:
                return "Remote clients only regardless of profile setting."
            case SendType.LocalAndRemote:
                return "Local and remote clients regardless of profile setting."
            case _:
                return f"Don't know how to handle: [{value}]"
            

