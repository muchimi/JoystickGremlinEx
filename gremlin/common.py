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
import logging
import gremlin.error
import os
import sys

from PySide6 import QtGui

from gremlin.input_types import InputType
import gremlin.keyboard


class AxisNames(enum.Enum):

    X = 1
    Y = 2
    Z = 3
    RX = 4
    RY = 5
    RZ = 6
    SLIDER = 7
    DIAL = 8

    @staticmethod
    def to_string(value):
        try:
            return _AxisNames_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(f"Invalid AxisName lookup, {value}")

    @staticmethod
    def to_enum(value):
        try:
            return _AxisNames_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(f"Invalid AxisName lookup, {value}")


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


class AxisButtonDirection(enum.Enum):

    """Possible activation directions for axis button instances."""

    Anywhere = 1
    Below = 2
    Above = 3

    @staticmethod
    def to_string(value):
        try:
            return _AxisButtonDirection_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                f"Invalid AxisButtonDirection lookup, {value}"
            )

    @staticmethod
    def to_enum(value):
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


def input_to_ui_string(input_type, input_id):
    """Returns a string for UI usage of an input.

    :param input_type the InputType being shown
    :param input_id the corresponding id
    :return string for UI usage of the given data
    """
    
    from gremlin.keyboard import key_from_code
    

    if hasattr(input_id, "display_name"):
        # use the built-in function
        return input_id.display_name


    if input_type == InputType.JoystickAxis:
        try:
            return AxisNames.to_string(AxisNames(input_id))
        except gremlin.error.GremlinError:
            return f"Axis {input_id:d}"
    elif input_type == InputType.KeyboardLatched:
        # input ID contains a Key object
        return input_id.name
    elif input_type in (InputType.Keyboard, InputType.KeyboardLatched):
        if isinstance(input_id, gremlin.keyboard.Key):
            return  key_from_code(input_id.scan_code, input_id.is_extended).name
        
        return key_from_code(*input_id).name
    else:
        return f"{InputType.to_string(input_type).capitalize()} {input_id}"



def index_to_direction(direction):
    """Returns a direction index to a direction name.

    :param direction index of the direction to convert
    :return text representation of the direction index
    """
    lookup = {
        1: "Up",
        2: "Up & Right",
        3: "Right",
        4: "Down & Right",
        5: "Down",
        6: "Down & Left",
        7: "Left",
        8: "Up & Left"
    }
    return lookup[int(direction)]


# Mapping from hat direction tuples to their textual representation
direction_tuple_lookup = {
    (0, 0): "Center",
    (0, 1): "North",
    (1, 1): "North East",
    (1, 0): "East",
    (1, -1): "South East",
    (0, -1): "South",
    (-1, -1): "South West",
    (-1, 0): "West",
    (-1, 1): "North West",
    "Center": (0, 0),
    "North": (0, 1),
    "North East": (1, 1),
    "East": (1, 0),
    "South East": (1, -1),
    "South": (0, -1),
    "South West": (-1, -1),
    "West": (-1, 0),
    "North West": (-1, 1)
}



class PluginVariableType(enum.Enum):

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
    def to_string(value):
        try:
            return _PluginVariableType_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid PluginVariableType in lookup"
            )

    @staticmethod
    def to_enum(value):
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
