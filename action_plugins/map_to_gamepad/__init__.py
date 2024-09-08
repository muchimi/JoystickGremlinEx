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


import logging
import math
import os
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets

import gremlin.base_profile
from gremlin.input_types import InputType

from gremlin.profile import read_bool, safe_read, safe_format
from gremlin.util import rad2deg
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput


from . import vigem_commons as vcom
from . import vigem_gamepad as gamepad

from enum import Enum, auto

class GamePadOutput(Enum):
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


class MapToGamepadWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to mouse motion or buttons."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, QtWidgets.QVBoxLayout, parent=parent)
        self.action_data = action_data

    def _create_ui(self):
        """Creates the UI components."""

        
        self.output_selector = QtWidgets.QComboBox()
        self.output_widget = QtWidgets.QWidget()
        self.output_layout = QtWidgets.QHBoxLayout(self.output_widget)
        self.output_layout.addWidget(QtWidgets.QLabel("Output:"))
        self.output_layout.addWidget(self.output_selector)
        self.output_layout.addStretch()
        
        self.output_selector.currentIndexChanged.connect(self._output_mode_changed)
        #self.output_widget.setContentsMargins(0,0,0,0)
        self.output_layout.setContentsMargins(0,0,0,0)

        self.main_layout.addWidget(self.output_widget)

    def _populate_ui(self):
        """Populates the UI components."""
        with QtCore.QSignalBlocker(self.output_selector):
            self.output_selector.clear()
            if self.action_data.get_input_type() == InputType.JoystickAxis:
                # axis or trigger
                self.output_selector.addItem("Left Stick X Axis", GamePadOutput.LeftStickX)
                self.output_selector.addItem("Left Stick Y Axis", GamePadOutput.LeftStickY)
                self.output_selector.addItem("Right Stick X Axis", GamePadOutput.RightStickX)
                self.output_selector.addItem("Right Stick Y Axis", GamePadOutput.RightStickY)
                self.output_selector.addItem("Left Trigger", GamePadOutput.LeftTrigger)
                self.output_selector.addItem("Right Trigger", GamePadOutput.RightTrigger)
            else:
                #button
                self.output_selector.addItem("Button A", GamePadOutput.ButtonA)
                self.output_selector.addItem("Button B", GamePadOutput.ButtonB)
                self.output_selector.addItem("Button X", GamePadOutput.ButtonX)
                self.output_selector.addItem("Button Y", GamePadOutput.ButtonY)
                self.output_selector.addItem("Button Start", GamePadOutput.ButtonStart)
                self.output_selector.addItem("Button Back", GamePadOutput.ButtonBack)
                self.output_selector.addItem("Button Guide", GamePadOutput.ButtonGuide)
                self.output_selector.addItem("Button Left Thumb", GamePadOutput.ButtonThumbLeft)
                self.output_selector.addItem("Button Right Thumb", GamePadOutput.ButtonThumbRight)
                self.output_selector.addItem("Button Shoulder Left", GamePadOutput.ButtonShoulderLeft)
                self.output_selector.addItem("Button Shoulder Right", GamePadOutput.ButtonShoulderRight)
                self.output_selector.addItem("Button DPad Left", GamePadOutput.ButtonDpadLeft)
                self.output_selector.addItem("Button DPad Right", GamePadOutput.ButtonDpadRight)
                self.output_selector.addItem("Button DPad Up", GamePadOutput.ButtonDpadUp)
                self.output_selector.addItem("Button DPad Down", GamePadOutput.ButtonDpadDown)

            index = self.output_selector.findData(self.action_data.output_mode)
            if index != -1:
                self.output_selector.setCurrentIndex(index)

    def _output_mode_changed(self):
        self.action_data.output_mode = self.output_selector.currentData()

class MapToGamepadFunctor(gremlin.base_profile.AbstractFunctor):

    """Implements the functionality required to move a mouse cursor.

    This moves the mouse cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    def __init__(self, action_data):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action_data)
        self.action_data = action_data
        

    def process_event(self, event, value):
        if not self.action_data.available:
            return False
        output_mode = self.action_data.output_mode
        if output_mode == GamePadOutput.NotSet:
            return True # nothing to do
        vigem = self.action_data.vigem
        if event.event_type == InputType.JoystickAxis:
            if output_mode == GamePadOutput.LeftStickX:
                vigem.left_joystick_float_x(value.current)
            elif output_mode == GamePadOutput.LeftStickY:
                vigem.left_joystick_float_y(value.current)
            if output_mode == GamePadOutput.RightStickX:
                vigem.right_joystick_float_x(value.current)
            elif output_mode == GamePadOutput.RightStickY:
                vigem.right_joystick_float_y(value.current)
            if output_mode == GamePadOutput.LeftTrigger:
                vigem.left_trigger_float(value.current)
            if output_mode == GamePadOutput.RightTrigger:
                vigem.right_trigger_float(value.current)
        else:
            if output_mode == GamePadOutput.ButtonA:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_A
            elif output_mode == GamePadOutput.ButtonB:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_B
            elif output_mode == GamePadOutput.ButtonX:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_X
            elif output_mode == GamePadOutput.ButtonY:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_Y
            elif output_mode == GamePadOutput.ButtonStart:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_START
            elif output_mode == GamePadOutput.ButtonBack:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_BACK
            elif output_mode == GamePadOutput.ButtonGuide:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE
            elif output_mode == GamePadOutput.ButtonThumbRight:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB
            elif output_mode == GamePadOutput.ButtonThumbLeft:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB
            elif output_mode == GamePadOutput.ButtonShoulderLeft:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER
            elif output_mode == GamePadOutput.ButtonShoulderRight:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER
            elif output_mode == GamePadOutput.ButtonDpadDown:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN
            elif output_mode == GamePadOutput.ButtonDpadUp:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP
            elif output_mode == GamePadOutput.ButtonDpadLeft:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
            elif output_mode == GamePadOutput.ButtonDpadRight:
                button =vcom.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT
            else:
                button = None

            if button is not None:
                if value.is_pressed:
                    vigem.press_button(button)
                else:
                    vigem.release_button(button)

        return True


class MapToGamepad(gremlin.base_profile.AbstractAction):

    """Action data for the map to mouse action.

    Map to mouse allows controlling of the mouse cursor using either a joystick
    or a hat.
    """

    name = "Map to GamePad"
    tag = "map-to-gamepad"
    

    default_button_activation = (True, True)
    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MapToGamepadFunctor
    widget = MapToGamepadWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent


        # ensure a device is available
        self.available = False
        self.vigem = None
        try:
            self.vigem =  gamepad.VX360Gamepad()
            self.available = True # mark available
        except:
            pass

        self.output_mode = GamePadOutput.NotSet



 
    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"[{GamePadOutput.to_display_name(self.output_mode)}]"
    
    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "fa.gamepad"
        

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        # Need virtual buttons for button inputs on axes and hats
        # if self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]:
        #     return True
        return False

    def _parse_xml(self, node):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """

        mode = None
        if "mode" in node.attrib:
            mode = node.get("mode")
            self.output_mode = GamePadOutput.to_enum(mode)


    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(self.tag)
        node.set("mode", GamePadOutput.to_string(self.output_mode))
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return self.available


version = 1
name = "map-to-gamepad"
create = MapToGamepad
