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


class VisualizationType(Enum):

    """Enumeration of possible visualization types."""

    AxisTemporal = 1
    AxisCurrent = 2
    ButtonHat = 3

class KeyboardOutputMode(Enum):
    Both = 0 # keyboard make and break (press/release) (pulse mode)
    Press = 1 # keyboard make only
    Release = 2 # keyboard release only
    Hold = 3 # press while held (default Gremlin behavior)
    AutoRepeat = 4 # repeated pulse mode - key pulses while the input is held

    
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
            logging.getLogger("system").error(f"AxisNames: Don't know how to convert axis to string: '{value}' to a string - defaulting to X (1)")
            return "X"

    @staticmethod
    def to_enum(value: str) -> AxisNames:
        try:
            return _AxisNames_to_enum_lookup[value]
        except KeyError:
            logging.getLogger("system").error(f"AxisNames: Don't know how to convert axis to enum: '{value}' to a string - defaulting to X (1)")
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
    Above = 3

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
    AxisButtonDirection.Below: "below"
}
_AxisButtonDirection_to_enum_lookup = {
    "anywhere": AxisButtonDirection.Anywhere,
    "above": AxisButtonDirection.Above,
    "below": AxisButtonDirection.Below
}


class MouseButton(Enum):

    """Enumeration of all possible mouse buttons."""

    Left = 1
    Right = 2
    Middle = 3
    Forward = 4
    Back = 5
    WheelUp = 10
    WheelDown = 11

    @staticmethod
    def to_string(value: MouseButton) -> str:
        try:
            return _MouseButton_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")

    @staticmethod
    def to_enum(value: str) -> MouseButton:
        try:
            return _MouseButton_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")


_MouseButton_to_string_lookup = {
    MouseButton.Left: "Left",
    MouseButton.Right: "Right",
    MouseButton.Middle: "Middle",
    MouseButton.Forward: "Forward",
    MouseButton.Back: "Back",
    MouseButton.WheelUp: "Wheel Up",
    MouseButton.WheelDown: "Wheel Down",
}
_MouseButton_to_enum_lookup = {
    "Left": MouseButton.Left,
    "Right": MouseButton.Right,
    "Middle": MouseButton.Middle,
    "Forward": MouseButton.Forward,
    "Back": MouseButton.Back,
    "Wheel Up": MouseButton.WheelUp,
    "Wheel Down": MouseButton.WheelDown,
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
        

class DeviceType(IntEnum):

    """Enumeration of the different possible input types."""

    Keyboard = 1 # keyboard
    Joystick = 2 # game controller
    VJoy = 3 # vjoy (virtual)
    Midi = 4 # midi
    Osc = 5 # open source control
    ModeControl = 6 # mode control

    @staticmethod
    def to_string(value):
        try:
            return _DeviceType_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")

    @staticmethod
    def to_enum(value):
        try:
            return _DeviceType_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")
        
    @staticmethod
    def to_display_name(value):
        return _DeviceType_to_display_name[value]




_DeviceType_to_display_name = {
    DeviceType.Keyboard: "Keyboard",
    DeviceType.Joystick: "Joystick",
    DeviceType.VJoy: "VJoy",
    DeviceType.Midi: "MIDI",
    DeviceType.Osc: "OSC",
    DeviceType.ModeControl: "Mode Control"
}

_DeviceType_to_string_lookup = {
    DeviceType.Keyboard: "keyboard",
    DeviceType.Joystick: "joystick",
    DeviceType.VJoy: "vjoy",
    DeviceType.Midi: "midi",
    DeviceType.Osc: "osc",
    DeviceType.ModeControl: "mode",
}


_DeviceType_to_enum_lookup = {
    "keyboard": DeviceType.Keyboard,
    "joystick": DeviceType.Joystick,
    "vjoy": DeviceType.VJoy,
    "midi": DeviceType.Midi,
    "osc": DeviceType.Osc,
    "mode": DeviceType.ModeControl,

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
            if isinstance(value, str):
                return _HatDirection_to_enum_lookup[value.lower()]
            else:
                return _HatDirection_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid HatDirection in lookup"
            )

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
    MouseWiggleOnLocal = 2 # enable mouse wiggle - local machine only
    MouseWiggleOffLocal = 3 # disable mouse wiggle - locla machine only
    MouseWiggleOnRemote = 4 # enable mouse wiggle - remote machines only
    MouseWiggleOffRemote = 5 # disable mouse wiggle - remote machines only

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
        if action == MouseAction.MouseButton:
            return "Maps a mouse button"
        elif action == MouseAction.MouseMotion:
            return "Maps to a mouse motion axis"
        elif action == MouseAction.MouseWiggleOffLocal:
            return "Turns wiggle mode off (local only)"
        elif action == MouseAction.MouseWiggleOnLocal:
            return "Turns wiggle mode on (local only)"
        elif action == MouseAction.MouseWiggleOffRemote:
            return "Turns wiggle mode off (remote only)"
        elif action == MouseAction.MouseWiggleOnRemote:
            return "Turns wiggle mode on (remote only)"

        return f"Unknown {action}"
    
    @staticmethod
    def to_name(action):
        ''' returns the name from the action '''
        if action == MouseAction.MouseButton:
            return "Mouse button"
        elif action == MouseAction.MouseMotion:
            return "Mouse axis"
        elif action == MouseAction.MouseWiggleOffLocal:
            return "Wiggle Disable (local)"
        elif action == MouseAction.MouseWiggleOnLocal:
            return "Wiggle Enable (local)"
        elif action == MouseAction.MouseWiggleOffRemote:
            return "Wiggle Disable (remote)"
        elif action == MouseAction.MouseWiggleOnRemote:
            return "Wiggle Enable (remote)"

                
        return f"Unknown {action}"
    
class MouseButton(Enum):

    """Enumeration of all possible mouse buttons."""

    Left = 1
    Right = 2
    Middle = 3
    Forward = 4
    Back = 5
    WheelUp = 10
    WheelDown = 11
    WheelLeft = 12
    WheelRight = 13

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
            return _MouseButton_lookup_to_button_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")



_MouseButton_to_string_lookup = {
    MouseButton.Left: "Mouse Left",
    MouseButton.Right: "Mouse Right",
    MouseButton.Middle: "Mouse Middle",
    MouseButton.Forward: "Mouse Forward",
    MouseButton.Back: "Mouse Back",
    MouseButton.WheelUp: "Wheel Up",
    MouseButton.WheelDown: "Wheel Down",
    MouseButton.WheelLeft: "Wheel Left",
    MouseButton.WheelRight: "Wheel Right"
}

_MouseButton_to_lookup_string_lookup = {
    MouseButton.Left: "mouse_1",
    MouseButton.Right: "mouse_2",
    MouseButton.Middle: "mouse_3",
    MouseButton.Forward: "mouse_4",
    MouseButton.Back: "mouse_5",
    MouseButton.WheelUp: "wheel_up",
    MouseButton.WheelDown: "wheel_down",
    MouseButton.WheelLeft: "wheel_left",
    MouseButton.WheelRight: "wheel_right"
}



_MouseButton_to_enum_lookup = {
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
    "Wheel Down": MouseButton.WheelDown,
    "Wheel Left": MouseButton.WheelLeft,
    "Wheel Right": MouseButton.WheelRight
}

_MouseButton_lookup_to_button_lookup = {
    "mouse_1": MouseButton.Left,
    "mouse_2": MouseButton.Right,
    "mouse_3": MouseButton.Middle,
    "mouse_4": MouseButton.Forward,
    "mouse_5": MouseButton.Back,
    "wheel_up": MouseButton.WheelUp,
    "wheel_down": MouseButton.WheelDown,
    "wheel_left": MouseButton.WheelLeft,
    "wheel_right": MouseButton.WheelRight
}


@unique
class VerboseMode(IntFlag):
    NotSet = 0
    Keyboard = auto() # keyboard input only
    Joystick = auto() # joystick input
    Inputs = auto() # list inputs
    Mouse = auto() # mouse input
    SimConnect = auto() # simconnect interface
    Details = auto() # user interface details
    Condition = auto() # conditions diagnostics / execution graph
    OSC = auto() # OSC data 
    Process = auto() # process changes
    All = Keyboard | Joystick | Inputs | Mouse | Details | SimConnect | Condition | Process

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
