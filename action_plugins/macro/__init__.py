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


import collections
import logging
import os
import pickle
import time
from PySide6 import QtCore, QtGui, QtWidgets
from lxml import etree as ElementTree

from PySide6.QtGui import QIcon

import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.keyboard
import gremlin.macro
from gremlin.profile import safe_format, safe_read, parse_guid, write_guid
import gremlin.ui.input_item
import gremlin.input_devices
from gremlin.input_devices import VjoyAction
from gremlin.keyboard import key_from_code, key_from_name
import gremlin.types
from gremlin.macro_handler import *

syslog = logging.getLogger("system")

class MacroFunctor(gremlin.base_profile.AbstractFunctor):

    manager = gremlin.macro.MacroManager()

    def __init__(self, action):
        super().__init__(action)
        self.macro = gremlin.macro.Macro()
        for seq in action.sequence:
            self.macro.add_action(seq)
        self.macro.exclusive = action.exclusive
        self.macro.repeat = action.repeat

    def process_event(self, event, value):
        MacroFunctor.manager.queue_macro(self.macro)
        if isinstance(self.macro.repeat, gremlin.macro.HoldRepeat):
            gremlin.input_devices.ButtonReleaseActions().register_callback(
                lambda: MacroFunctor.manager.terminate_macro(self.macro),
                event
            )
        return True


class Macro(gremlin.base_profile.AbstractAction):

    """Represents a macro action."""

    name = "Macro"
    tag = "macro"

    default_button_activation = (True, False)

    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MacroFunctor
    widget = MacroWidget

    def __init__(self, parent):
        """Creates a new Macro instance.

        :param parent the parent profile.ItemAction of this macro action
        """
        super().__init__(parent)
        self.sequence = []
        self.exclusive = False
        self.repeat = None
        self.force_remote = False

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        """Parses the XML node corresponding to a macro action.

        :param node the XML node to parse.
        """
        # Reset storage
        self.sequence = []
        self.exclusive = False
        self.repeat = None
        self.force_remote = False

        # Read properties
        for child in node.find("properties"):
            if child.tag == "exclusive":
                self.exclusive = True
            elif child.tag == "force_remote":
                self.force_remote = True
            elif child.tag == "repeat":
                repeat_type = child.get("type")
                if repeat_type == "count":
                    self.repeat = gremlin.macro.CountRepeat()
                elif repeat_type == "toggle":
                    self.repeat = gremlin.macro.ToggleRepeat()
                elif repeat_type == "hold":
                    self.repeat = gremlin.macro.HoldRepeat()
                else:
                    logging.getLogger("system").warning(
                        f"Invalid macro repeat type: {repeat_type}"
                    )

                if self.repeat:
                    self.repeat.from_xml(child)

        # Read macro actions
        for child in node.find("actions"):
            if child.tag == "joystick":
                joy_action = gremlin.macro.JoystickAction(
                    parse_guid(child.get("device-guid")),
                    InputType.to_enum(
                        safe_read(child, "input-type")
                    ),
                    safe_read(child, "input-id", int),
                    safe_read(child, "value"),
                )
                self._str_to_joy_value(joy_action)
                self.sequence.append(joy_action)
            elif child.tag == "key":
                key_action = gremlin.macro.KeyAction(
                    key_from_code(
                        int(child.get("scan-code")),
                        gremlin.profile.parse_bool(child.get("extended"))
                    ),
                    gremlin.profile.parse_bool(child.get("press"))
                )
                self.sequence.append(key_action)
            elif child.tag == "mouse":
                mouse_action = gremlin.macro.MouseButtonAction(
                    gremlin.types.MouseButton(safe_read(child, "button", int)),
                    gremlin.profile.parse_bool(child.get("press"))
                )
                self.sequence.append(mouse_action)
            elif child.tag == "mouse-motion":
                mouse_motion = gremlin.macro.MouseMotionAction(
                    safe_read(child, "dx", int, 0),
                    safe_read(child, "dy", int, 0)
                )
                self.sequence.append(mouse_motion)
            elif child.tag == "pause":
                self.sequence.append (
                    gremlin.macro.PauseAction(
                                        float(child.get("duration")),
                                        safe_read(child, "duration_max", float, 0),
                                        gremlin.profile.parse_bool(child.get("is_random"))
                                        )
                )
            elif child.tag == "vjoy":
                vjoy_action = gremlin.macro.VJoyMacroAction(
                    safe_read(child, "vjoy-id", int),
                    InputType.to_enum(
                        safe_read(child, "input-type")
                    ),
                    safe_read(child, "input-id", int),
                    safe_read(child, "value"),
                    safe_read(child, "axis-type", str, "absolute")
                )
                self._str_to_joy_value(vjoy_action)
                self.sequence.append(vjoy_action)

            elif child.tag == "remote_control":
                remote_control_action = gremlin.macro.RemoteControlAction()
                cmd = safe_read(child, "command", str, "VJoyEnableLocalOnly")
                remote_control_action.command = VjoyAction.from_string(cmd)
                self.sequence.append(remote_control_action)


    def _generate_xml(self):
        """Generates a XML node corresponding to this object.

        :return XML node representing the object's data
        """
        node = ElementTree.Element("macro")
        properties = ElementTree.Element("properties")
        if self.exclusive:
            prop_node = ElementTree.Element("exclusive")
            properties.append(prop_node)
        if self.repeat:
            properties.append(self.repeat.to_xml())
        if self.force_remote:
            prop_node = ElementTree.Element("force_remote")
            properties.append(prop_node)


        node.append(properties)

        action_list = ElementTree.Element("actions")
        for entry in self.sequence:
            if isinstance(entry, gremlin.macro.JoystickAction):
                joy_node = ElementTree.Element("joystick")
                joy_node.set("device-guid", write_guid(entry.device_guid))
                joy_node.set(
                    "input-type",
                    InputType.to_string(entry.input_type)
                )
                joy_node.set("input-id", str(entry.input_id))
                joy_node.set("value", self._joy_value_to_str(entry))
                action_list.append(joy_node)
            elif isinstance(entry, gremlin.macro.KeyAction):
                action_node = ElementTree.Element("key")
                action_node.set("scan-code", str(entry.key.scan_code))
                action_node.set("extended", str(entry.key.is_extended))
                action_node.set("press", str(entry.is_pressed))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                action_node = ElementTree.Element("mouse")
                action_node.set("button", str(entry.button.value))
                action_node.set("press", str(entry.is_pressed))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.MouseMotionAction):
                action_node = ElementTree.Element("mouse-motion")
                action_node.set("dx", str(entry.dx))
                action_node.set("dy", str(entry.dy))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.PauseAction):
                pause_node = ElementTree.Element("pause")
                pause_node.set("duration", str(entry.duration))
                pause_node.set("duration_max", str(entry.duration_max))
                pause_node.set("is_random", str(entry.is_random))
                action_list.append(pause_node)
            elif isinstance(entry, gremlin.macro.VJoyMacroAction):
                vjoy_node = ElementTree.Element("vjoy")
                vjoy_node.set("vjoy-id", str(entry.vjoy_id))
                vjoy_node.set(
                    "input-type",
                    InputType.to_string(entry.input_type)
                )
                vjoy_node.set("input-id", str(entry.input_id))
                vjoy_node.set("value", self._joy_value_to_str(entry))
                if entry.input_type == InputType.JoystickAxis:
                    vjoy_node.set("axis-type", safe_format(entry.axis_type, str))
                action_list.append(vjoy_node)
            elif isinstance(entry, gremlin.macro.RemoteControlAction):
                action_node = ElementTree.Element("remote_control")
                action_node.set("command",entry.command.name)
                action_list.append(action_node)

        node.append(action_list)
        return node

    def _is_valid(self):
        return len(self.sequence) > 0

    def _joy_value_to_str(self, entry):
        """Converts a joystick input value to a string.

        :param entry the entry whose value to convert
        :return string representation of the entry's value
        """
        if entry.input_type == InputType.JoystickAxis:
            return str(entry.value)
        elif entry.input_type == InputType.JoystickButton:
            return str(entry.value)
        elif entry.input_type == InputType.JoystickHat:
            return gremlin.util.hat_tuple_to_direction(entry.value)

    def _str_to_joy_value(self, action):
        if action.input_type == InputType.JoystickAxis:
            action.value = float(action.value)
        elif action.input_type == InputType.JoystickButton:
            action.value = gremlin.profile.parse_bool(action.value)
        elif action.input_type == InputType.JoystickHat:
            action.value = gremlin.util.hat_direction_to_tuple(action.value)


version = 1
name = "macro"
create = Macro
