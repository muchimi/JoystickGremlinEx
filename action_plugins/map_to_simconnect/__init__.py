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


import os
from xml.etree import ElementTree

from PySide6 import QtWidgets, QtCore, QtGui

from gremlin.base_classes import AbstractAction, AbstractFunctor
from gremlin.common import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.ui.common
import gremlin.ui.input_item
import enum
from gremlin.profile import safe_format, safe_read
from .SimConnectData import *


class MapToSimConnectWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to keyboard key combinations - adds extra functionality to the base module ."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        self.action_data = action_data

    def _create_ui(self):
        """Creates the UI components."""

        self._sm_data = SimConnectData()

        self.action_widget = QtWidgets.QWidget()
        self.action_layout = QtWidgets.QVBoxLayout()
        self.action_selector_widget = QtWidgets.QWidget()
        self.action_selector_layout = QtWidgets.QHBoxLayout()
        
        self.action_selector_widget.setLayout(self.action_selector_layout)
        self.action_widget.setLayout(self.action_layout)


        # event categories
        self.category_widget = QtWidgets.QComboBox()
        for name, value in SimConnectEventCategory.to_list_tuple():
            self.category_widget.addItem(name, value)

        # list of possible events to trigger
        self.command_widget = QtWidgets.QComboBox()
        self.command_list = self._sm_data.get_command_name_list()
        self.command_widget.setEditable(True)
        self.command_widget.addItems(self.command_list)
        self.command_widget.currentIndexChanged.connect(self._command_changed_cb)
        self.command_description_widget = QtWidgets.QLabel()

        # setup auto-completer for the command 
        command_completer = QtWidgets.QCompleter(self.command_list, self)
        command_completer.setCaseSensitivity(QtGui.Qt.CaseSensitivity.CaseInsensitive)

        self.command_widget.setCompleter(command_completer)

        self.action_selector_layout.addWidget(self.category_widget)
        self.action_selector_layout.addWidget(self.command_widget)
        self.action_selector_layout.addWidget(self.command_description_widget)
        

        # output section
        self.output_widget = QtWidgets.QWidget()
        self.output_layout = QtWidgets.QGridLayout()
        self.output_widget.setLayout(self.output_layout)

        self.output_mode_widget = QtWidgets.QWidget()
        self.output_mode_layout = QtWidgets.QGridLayout()
        self.output_mode_widget.setLayout(self.output_mode_layout)

        self.output_mode_axis_widget = QtWidgets.QRadioButton("Axis")
        self.output_mode_number_widget = QtWidgets.QRadioButton("Value")
        self.output_mode_layout.addWidget(self.output_mode_axis_widget)
        self.output_mode_layout.addWidget(self.output_mode_number_widget)


        self.output_layout.addWidget(QtWidgets.QLabel("Output data:"),0,0)
        self.output_layout.addWidget(self.output_mode_widget, 0, 1)

        self.output_data_type_widget = QtWidgets.QLabel()
        self.output_layout.addWidget(self.output_data_type_widget, 1,0)

        self.output_value_type_widget = QtWidgets.QLabel()
        self.output_layout.addWidget(self.output_value_type_widget, 1,1)


        self.action_layout.addWidget(self.action_selector_widget)
        self.action_layout.addWidget(self.output_widget)

        # hide output layout by default until we have a valid command
        self.output_widget.setVisible(False)


        self.main_layout.addWidget(self.action_widget)

        self.main_layout.addStretch(1)


    def _command_changed_cb(self, index):
        ''' called when selected command changes '''
        command = self.command_widget.currentText()
        category = SimConnectEventCategory.NotSet
        self.action_data.command = command
        data = self._sm_data.get_command_data(command)
        if not data:
            # no data
            self.output_widget.setVisible(False)

        else:
            self.output_widget.setVisible(True)
            if data[0] == "e":
                # event type data
                description = data[1][2]
                request_type = "Event"
                value = "N/A"
                category = self._sm_data.get_command_category(command)
            elif data[0] == "r":
                # request type data  "NUMBER_OF_ENGINES": ["Number of engines (minimum 0, maximum 4)", b'NUMBER OF ENGINES', b'Number', 'N'],
                description = data[1][0]
                request_type = data[1][2].decode('ascii')
                value = data[1][3]
                

            self.command_description_widget.setText(description)
            self.output_data_type_widget.setText(request_type)
            self.output_value_type_widget.setText(value)

        index = self.category_widget.findData(category)
        with QtCore.QSignalBlocker(self.category_widget):
            self.category_widget.setCurrentIndex(index)

    def _populate_ui(self):
        """Populates the UI components."""

        command = self.action_data.command
        index = self.command_widget.findText(command)
        self.command_widget.setCurrentIndex(index)
        


    

class MapToSimConnectFunctor(AbstractFunctor):

    def __init__(self, action):
        super().__init__(action)
        self.command = None # the command to execute
        self.value = None # the value to send
    
    def process_event(self, event, value):

        if event.event_type == InputType.JoystickAxis or value.current:
            # joystick values or virtual button
            pass
        return True


class MapToSimConnect(AbstractAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """

    name = "Map to SimConnect"
    tag = "map-to-simconnect"

    default_button_activation = (True, True)
    input_types = [
        InputType.JoystickAxis,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard
    ]

    functor = MapToSimConnectFunctor
    widget = MapToSimConnectWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.sm = SimConnectData()
        self.category = SimConnectEventCategory.NotSet
        self.command = None
        self.value = None

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        # if 
        # value  = safe_read(node,"category", str)
        # self.category = SimConnectEventCategory.to_enum(value, validate=False)
        command = safe_read(node,"command", str)
        if not command:
            command = self.sm.get_default_command()
        self.command = command
        self.value = safe_read(node,"value", float)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToSimConnect.tag)

        command = self.command if self.command else ""
        node.set("command",safe_format(command, str) )

        value = self.value if self.value else 0.0
        node.set("value",safe_format(value, float))
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True


    def __getstate__(self):
        ''' serialization override '''
        state = self.__dict__.copy()
        # sm is not serialized, remove it
        del state["sm"]
        return state

    def __setstate__(self, state):
        ''' serialization override '''
        self.__dict__.update(state)
        # sm is not serialized, add it
        self.sm = SimConnectData()

version = 1
name = "map-to-simconnect"
create = MapToSimConnect
