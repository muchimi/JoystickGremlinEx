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
import gremlin.event_handler
from gremlin.input_types import InputType

from gremlin.profile import read_bool, safe_read, safe_format
from gremlin.util import rad2deg
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput
import gremlin.gamepad_handling
from gremlin import input_devices
from gremlin.types import GamePadOutput



# import vigem.vigem_gamepad as vg
import vigem.vigem_commons as vc

from enum import Enum, auto

import gremlin.util
from gremlin.types import GamePadOutput




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

        el = gremlin.event_handler.EventListener()
        el.gamepad_change_event.connect(self._gamepad_count_changed)

        self.output_widget = QtWidgets.QWidget()
        self.output_layout = QtWidgets.QHBoxLayout(self.output_widget)
        
        self.device_selector = gremlin.ui.ui_common.NoWheelComboBox()
        self.output_selector = gremlin.ui.ui_common.NoWheelComboBox()
        
        self.output_layout.addWidget(QtWidgets.QLabel("Device:"))
        self.output_layout.addWidget(self.device_selector)
        self.output_layout.addWidget(QtWidgets.QLabel("Output:"))
        self.output_layout.addWidget(self.output_selector)
        self.output_layout.addStretch()
        
        self.output_selector.currentIndexChanged.connect(self._output_mode_changed)
        self.device_selector.currentIndexChanged.connect(self._device_changed)
        #self.output_widget.setContentsMargins(0,0,0,0)
        self.output_layout.setContentsMargins(0,0,0,0)

        self.main_layout.addWidget(self.output_widget)

    def _populate_ui(self):
        """Populates the UI components."""
        devices = gremlin.gamepad_handling.gamepadDevices()
        is_enabled = len(devices) > 0
        self.setEnabled(is_enabled)
        with QtCore.QSignalBlocker(self.device_selector):
            self.device_selector.clear()
            for index, device in enumerate(devices):
                self.device_selector.addItem(f"Controller (XBOX 360 For Windows) [{index+1}]", index)
        

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

            index = self.device_selector.findData(self.action_data.device_index)
            if index != -1:
                self.device_selector.setCurrentIndex(index)
            else:
                # pick the first entry
                self.device_selector.setCurrentIndex(0)
                self.action_data.device_index = 0

    @QtCore.Slot()
    def _gamepad_count_changed(self):
        ''' number of devices changed '''
        self._populate_ui()

    @QtCore.Slot()
    def _output_mode_changed(self):
        self.action_data.output_mode = self.output_selector.currentData()

    @QtCore.Slot()
    def _device_changed(self):
        self.action_data.device_index = self.device_selector.currentData()

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
        (is_local, is_remote) = input_devices.remote_state.state
        if event.force_remote:
            # force remote mode on if specified in the event
            is_remote = True
            is_local = False

        if is_local:

            vigem = gremlin.gamepad_handling.getGamepad(self.action_data.device_index)
            if vigem is None:
                return False
            
            
        output_mode = self.action_data.output_mode
        if output_mode == GamePadOutput.NotSet:
            return True # nothing to do
        # vigem : vg.VX360Gamepad
        if event.event_type == InputType.JoystickAxis:
            if is_local:
                vscaled = value.current
                if output_mode == GamePadOutput.LeftStickX:
                    vigem.left_joystick_float_x(vscaled)
                elif output_mode == GamePadOutput.LeftStickY:
                    vigem.left_joystick_float_y(vscaled)
                if output_mode == GamePadOutput.RightStickX:
                    vigem.right_joystick_float_x(vscaled)
                elif output_mode == GamePadOutput.RightStickY:
                    vigem.right_joystick_float_y(vscaled)
                if output_mode == GamePadOutput.LeftTrigger:
                    vscaled = gremlin.util.scale_to_range(value.current,target_min=0.0, target_max=1.0)
                    vigem.left_trigger_float(vscaled)
                if output_mode == GamePadOutput.RightTrigger:
                    vscaled = gremlin.util.scale_to_range(value.current,target_min=0.0, target_max=1.0)
                    vigem.right_trigger_float(vscaled)
            else:
                # remote
                input_devices.remote_client.send_gamepad_axis(self.action_data.device_index, output_mode, vscaled)
                return True
        else:
            if output_mode == GamePadOutput.ButtonA:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_A
            elif output_mode == GamePadOutput.ButtonB:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_B
            elif output_mode == GamePadOutput.ButtonX:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_X
            elif output_mode == GamePadOutput.ButtonY:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_Y
            elif output_mode == GamePadOutput.ButtonStart:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_START
            elif output_mode == GamePadOutput.ButtonBack:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_BACK
            elif output_mode == GamePadOutput.ButtonGuide:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE
            elif output_mode == GamePadOutput.ButtonThumbRight:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB
            elif output_mode == GamePadOutput.ButtonThumbLeft:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB
            elif output_mode == GamePadOutput.ButtonShoulderLeft:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER
            elif output_mode == GamePadOutput.ButtonShoulderRight:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER
            elif output_mode == GamePadOutput.ButtonDpadDown:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN
            elif output_mode == GamePadOutput.ButtonDpadUp:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP
            elif output_mode == GamePadOutput.ButtonDpadLeft:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
            elif output_mode == GamePadOutput.ButtonDpadRight:
                button =vc.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT
            else:
                button = None

            if button is not None:
                if is_local:
                    if value.is_pressed:
                        vigem.press_button(button)
                    else:
                        vigem.release_button(button)
                else:
                    input_devices.remote_client.send_gamepad_button(self.action_data.device_index, button, value.is_pressed)
                    return True

        
        vigem.update() # sends the data to the controller

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

        self.device_index = 0
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

        if "mode" in node.attrib:
            mode = node.get("mode")
            self.output_mode = GamePadOutput.to_enum(mode)

        self.device_index = safe_read(node,"device_index", int, 0)



    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(self.tag)
        mode = GamePadOutput.to_string(self.output_mode)
        if mode == "none":
            pass
        node.set("mode", mode)
        node.set("device_index",str(self.device_index))
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return gremlin.gamepad_handling.gamepadAvailable()
    



version = 1
name = "map-to-gamepad"
create = MapToGamepad
