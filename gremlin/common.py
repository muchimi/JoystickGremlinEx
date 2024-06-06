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

import enum
import logging
import gremlin.error
import os
import sys

from PySide6 import QtGui





class InputType(enum.Enum):

    """Enumeration of possible input types."""

    NotSet = 0
    Keyboard = 1
    JoystickAxis = 2
    JoystickButton = 3
    JoystickHat = 4
    Mouse = 5
    VirtualButton = 6

    @staticmethod
    def to_string(value):
        try:
            return _InputType_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")

    @staticmethod
    def to_enum(value):
        try:
            return _InputType_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError("Invalid type in lookup")


_InputType_to_string_lookup = {
    InputType.NotSet: "none",
    InputType.JoystickAxis: "axis",
    InputType.JoystickButton: "button",
    InputType.JoystickHat: "hat",
    InputType.Keyboard: "key",
}

_InputType_to_enum_lookup = {
    "none": InputType.NotSet,
    "axis": InputType.JoystickAxis,
    "button": InputType.JoystickButton,
    "hat": InputType.JoystickHat,
    "key": InputType.Keyboard
}


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
    AxisNames.X: "X Axis",
    AxisNames.Y: "Y Axis",
    AxisNames.Z: "Z Axis",
    AxisNames.RX: "X Rotation",
    AxisNames.RY: "Y Rotation",
    AxisNames.RZ: "Z Rotation",
    AxisNames.SLIDER: "Slider",
    AxisNames.DIAL: "Dial"
}

_AxisNames_to_enum_lookup = {
    "X Axis": AxisNames.X,
    "Y Axis": AxisNames.Y,
    "Z Axis": AxisNames.Z,
    "X Rotation": AxisNames.RX,
    "Y Rotation": AxisNames.RY,
    "Z Rotation": AxisNames.RZ,
    "Slider": AxisNames.SLIDER,
    "Dial": AxisNames.DIAL
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
    if input_type == InputType.JoystickAxis:
        try:
            return AxisNames.to_string(AxisNames(input_id))
        except gremlin.error.GremlinError:
            return f"Axis {input_id:d}"
    elif input_type == InputType.Keyboard:
        return gremlin.macro.key_from_code(*input_id).name
    else:
        return f"{InputType.to_string(input_type).capitalize()} {input_id}"


class MouseButton(enum.Enum):

    """Enumeration of all possible mouse buttons."""

    Left = 1
    Right = 2
    Middle = 3
    Forward = 4
    Back = 5
    WheelUp = 10
    WheelDown = 11

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


class DeviceType(enum.Enum):

    """Enumeration of the different possible input types."""

    Keyboard = 1
    Joystick = 2
    VJoy = 3

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


_DeviceType_to_string_lookup = {
    DeviceType.Keyboard: "keyboard",
    DeviceType.Joystick: "joystick",
    DeviceType.VJoy: "vjoy"
}


_DeviceType_to_enum_lookup = {
    "keyboard": DeviceType.Keyboard,
    "joystick": DeviceType.Joystick,
    "vjoy": DeviceType.VJoy
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


class MergeAxisOperation(enum.Enum):

    """Possible merge axis operation modes."""

    Average = 1
    Minimum = 2
    Maximum = 3
    Sum = 4

    @staticmethod
    def to_string(value):
        try:
            return _MergeAxisOperation_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                "Invalid MergeAxisOperation in lookup"
            )

    @staticmethod
    def to_enum(value):
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


def get_guid(strip=True):
    ''' generates a reasonably lowercase unique guid string '''
    import uuid
    guid = f"{uuid.uuid4()}"
    if strip:
        return guid.replace("-",'')
    return guid
    


def find_file(icon_path):
    ''' finds a file '''


    from pathlib import Path
    from gremlin.util import get_root_path
    from gremlin.config import Configuration
    verbose = Configuration().verbose

    icon_path = icon_path.lower().replace("/",os.sep)
    sub_folders = None
    folders = []

    root_folder = get_root_path()
    if os.sep in icon_path:
        # we have folders
        splits = icon_path.split(os.sep)
        folders = splits[:-1]
        icon_path = splits[-1]
        sub_folders = os.path.join("", *folders)

    files = []
    if not os.path.isfile(icon_path):
        # path not found 
        file_root, ext = os.path.splitext(icon_path)
        if ext:
            extensions = [ext]
        else:
            extensions = [".svg",".png"]
        circuit_breaker = 1000
        for dirpath, _, filenames in os.walk(root_folder):
            circuit_breaker-=1
            if circuit_breaker == 0:
                break
            if sub_folders and not dirpath.endswith(sub_folders):
                continue
            for filename in [f.lower() for f in filenames]:
                for ext in extensions:
                    if filename.endswith(ext) and filename.startswith(file_root):
                        files.append(os.path.join(dirpath, filename))
                    
    if files:
        files.sort(key = lambda x: len(x)) # shortest to largest
        found_path = files.pop(0) # grab the first one
        if verbose:
            logging.getLogger("system").info(f"Find_files() - found : {found_path} for {icon_path}")
        return found_path
    
    if circuit_breaker == 0:
        logging.getLogger("system").error(f"Find_files() - search exceeded maximum when searching for: {icon_path}")
    
    if verbose or circuit_breaker == 0:
        logging.getLogger("system").error(f"Find_files() failed for: {icon_path}")
    return None




def get_icon_path(*paths):
        ''' 
        gets an icon path
           
        '''

        from gremlin.util import get_root_path
        from gremlin.config import Configuration
        verbose = Configuration().verbose
        

        # be aware of runtime environment
        root_path = get_root_path()
        the_path = os.path.join(*paths)
        icon_file = os.path.join(root_path, the_path).replace("/",os.sep).lower()
        if icon_file:
            if os.path.isfile(icon_file):
                if verbose:
                    logging.getLogger("system").info(f"Icon file (straight) found: {icon_file}")        
                return icon_file
            if not icon_file.endswith(".png"):
                icon_file_png = icon_file + ".png"
                if os.path.isfile(icon_file_png):
                    if verbose:
                        logging.getLogger("system").info(f"Icon file (png) found: {icon_file_png}")        
                    return icon_file_png
            if not icon_file.endswith(".svg"):
                icon_file_svg = icon_file + ".svg"
                if os.path.isfile(icon_file_svg):
                    if verbose:
                        logging.getLogger("system").info(f"Icon file (svg) found: {icon_file_svg}")        
                    return icon_file_svg
            brute_force = find_file(the_path)
            if brute_force and os.path.isfile(brute_force):
                return brute_force
        
        logging.getLogger("system").error(f"Icon file not found: {icon_file}")
    
        return None

def load_pixmap(*paths):
    ''' gets a pixmap from the path '''
    the_path = get_icon_path(*paths)
    if the_path:
        pixmap = QtGui.QPixmap(the_path)
        if pixmap.isNull():
            logging.getLogger("system").warning(f"load_pixmap(): pixmap failed: {the_path}")
            return None
        return pixmap
    
    logging.getLogger("system").error(f"load_pixmap(): invalid path")
    return None

def load_icon(*paths):
    ''' gets an icon (returns a QIcon) '''
    from gremlin.config import Configuration
    verbose = Configuration().verbose
    pixmap = load_pixmap(*paths)
    if not pixmap or pixmap.isNull():
        if verbose:
            logging.getLogger("system").info(f"LoadIcon() using generic icon - failed to locate: {paths}")        
        return get_generic_icon()
    icon = QtGui.QIcon()
    icon.addPixmap(pixmap, QtGui.QIcon.Normal)
    if verbose:
        logging.getLogger("system").info(f"LoadIcon() found icon: {paths}") 
    return icon

def load_image(*paths):
    ''' loads an image '''
    from gremlin.config import Configuration
    verbose = Configuration().verbose
    the_path = get_icon_path(*paths)
    if the_path:
        if verbose:
            logging.getLogger("system").info(f"LoadImage() found image: {paths}") 
        return QtGui.QImage(the_path)
    if verbose:
            logging.getLogger("system").info(f"LoadImage() failed to locate: {paths}")        
    return None
        
    
        

def get_generic_icon():
    ''' gets a generic icon'''
    from gremlin.util import get_root_path
    root_path = get_root_path()
    generic_icon = os.path.join(root_path, "gfx/generic.png")
    if generic_icon and os.path.isfile(generic_icon):
        pixmap = QtGui.QPixmap(generic_icon)
        if pixmap.isNull():
            logging.getLogger("system").warning(f"load_icon(): generic pixmap failed: {generic_icon}")
            return None
        icon = QtGui.QIcon()
        icon.addPixmap(pixmap, QtGui.QIcon.Normal)
        return icon
    logging.getLogger("system").warning(f"load_icon(): generic icon file not found: {generic_icon}")
    return None