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
import re


class CommandValidator(QtGui.QValidator):
    ''' validator for command selection '''
    def __init__(self):
        super().__init__()
        self.commands = SimConnectData().get_command_name_list()
        
        
    def validate(self, value, pos):
        clean_value = value.upper().strip()
        if not clean_value or clean_value in self.commands:
            # blank is ok
            return QtGui.QValidator.State.Acceptable
        # match all values starting with the text given
        r = re.compile(clean_value + "*")
        for _ in filter(r.match, self.commands):
            return QtGui.QValidator.State.Intermediate
        return QtGui.QValidator.State.Invalid

class MapToSimConnectWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to keyboard key combinations - adds extra functionality to the base module ."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        
        self.action_data = action_data
        self.block = None

        # call super last because it will call create_ui and populate_ui so the vars must exist
        super().__init__(action_data, parent=parent)

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

        self.command_widget.setValidator(CommandValidator())

        # setup auto-completer for the command 
        command_completer = QtWidgets.QCompleter(self.command_list, self)
        command_completer.setCaseSensitivity(QtGui.Qt.CaseSensitivity.CaseInsensitive)

        self.command_widget.setCompleter(command_completer)

        self.action_selector_layout.addWidget(self.category_widget)
        self.action_selector_layout.addWidget(self.command_widget)
        self.action_selector_layout.addWidget(self.command_description_widget)
        

        # output section
        self.output_widget = QtWidgets.QWidget()
        self.output_layout = QtWidgets.QVBoxLayout()
        self.output_widget.setLayout(self.output_layout)

        self.output_mode_widget = QtWidgets.QWidget()
        self.output_mode_layout = QtWidgets.QHBoxLayout()
        self.output_mode_widget.setLayout(self.output_mode_layout)

        # set range of values output mode (axis input only)
        self.output_mode_axis_widget = QtWidgets.QRadioButton("Axis")
        self.output_mode_axis_widget.clicked.connect(self._mode_axis_cb)

        # set value output mode (output value only)
        self.output_mode_set_value_widget = QtWidgets.QRadioButton("Value")
        self.output_mode_set_value_widget.clicked.connect(self._mode_value_cb)

        # trigger output mode (event trigger only)
        self.output_mode_trigger_widget = QtWidgets.QRadioButton("Trigger")
        self.output_mode_trigger_widget.clicked.connect(self._mode_trigger_cb)

        self.output_mode_description_widget = QtWidgets.QLabel()
        self.output_mode_layout.addWidget(QtWidgets.QLabel("Output mode:"))
        self.output_mode_layout.addWidget(self.output_mode_axis_widget)
        self.output_mode_layout.addWidget(self.output_mode_trigger_widget)
        self.output_mode_layout.addWidget(self.output_mode_set_value_widget)
        self.output_mode_layout.addWidget(self.output_mode_description_widget)

        self.output_readonly_widget = QtWidgets.QCheckBox("Read only")
        self.output_readonly_widget.clicked.connect(self._readonly_cb)
        self.output_mode_layout.addWidget(self.output_readonly_widget)

        self.output_block_type_description_widget = QtWidgets.QLabel()
        self.output_mode_layout.addWidget(self.output_block_type_description_widget)
        self.output_mode_layout.addStretch(1)


        self.output_layout.addWidget(QtWidgets.QLabel("Output data:"))
        self.output_layout.addWidget(self.output_mode_widget)

        # output data type UI 
        self.output_data_type_widget = QtWidgets.QWidget()
        self.output_data_type_layout = QtWidgets.QHBoxLayout()
        self.output_data_type_widget.setLayout(self.output_data_type_layout)
        self.output_data_type_label_widget = QtWidgets.QLabel("Not Set")

        self.output_data_type_layout.addWidget(QtWidgets.QLabel("Output type:"))
        self.output_data_type_layout.addWidget(self.output_data_type_label_widget)

        
        self.output_layout.addWidget(self.output_data_type_widget)

        # output range UI
        self.output_range_container_widget = QtWidgets.QWidget()
        self.output_range_container_layout = QtWidgets.QHBoxLayout()
        self.output_range_container_widget.setLayout(self.output_range_container_layout)

        self.output_min_range_widget = QtWidgets.QSpinBox()
        self.output_min_range_widget.setRange(-16383,16383)
        self.output_min_range_widget.setReadOnly(True)

        self.output_max_range_widget = QtWidgets.QSpinBox()
        self.output_max_range_widget.setRange(-16383,16383)
        self.output_max_range_widget.setReadOnly(True)

        self.output_min_range_custom_widget = QtWidgets.QSpinBox()
        self.output_min_range_custom_widget.setRange(-16383,16383)
        self.output_min_range_custom_widget.valueChanged.connect(self._min_range_changed_cb)

        self.output_max_range_custom_widget = QtWidgets.QSpinBox()
        self.output_max_range_custom_widget.setRange(-16383,16383)
        self.output_max_range_custom_widget.valueChanged.connect(self._max_range_changed_cb)

        # holds the output value if the output value is a fixed value
        self.output_value_container_widget =QtWidgets.QWidget()
        self.output_value_container_layout = QtWidgets.QHBoxLayout()
        self.output_value_widget = gremlin.ui.common.DynamicDoubleSpinBox()
        self.output_value_widget.valueChanged.connect(self._output_value_changed_cb)
        self.output_value_description_widget = QtWidgets.QLabel()

        self.output_value_container_layout.addWidget(QtWidgets.QLabel("Output value:"))
        self.output_value_container_layout.addWidget(self.output_value_widget)
        self.output_value_container_layout.addWidget(self.output_value_description_widget)
        self.output_value_container_layout.addStretch(1)

        
        self.output_range_container_layout.addWidget(QtWidgets.QLabel("Simconnect output range:"))
        self.output_range_container_layout.addWidget(QtWidgets.QLabel("Command min:"))
        self.output_range_container_layout.addWidget(self.output_min_range_widget)
        self.output_range_container_layout.addWidget(QtWidgets.QLabel("max:"))
        self.output_range_container_layout.addWidget(self.output_max_range_widget)
        self.output_range_container_layout.addWidget(QtWidgets.QLabel("Custom range min:"))
        self.output_range_container_layout.addWidget(self.output_min_range_custom_widget)
        self.output_range_container_layout.addWidget(QtWidgets.QLabel("max:"))
        self.output_range_container_layout.addWidget(self.output_max_range_custom_widget)
        self.output_range_container_layout.addStretch(1)


        self.output_layout.addWidget(self.output_range_container_widget)
        self.output_layout.addWidget(self.output_value_container_widget)
        self.output_layout.addStretch(1)

        
        self.action_layout.addWidget(self.action_selector_widget)


        # hide output layout by default until we have a valid command
        self.output_widget.setVisible(False)


        self.main_layout.addWidget(self.action_widget)
        self.main_layout.addWidget(self.output_widget)

        self.main_layout.addStretch(1)


    def _output_value_changed_cb(self):
        ''' occurs when the output value has changed '''
        value = self.output_value_widget.value()
        block: SimConnectBlock
        block = self.block
        if block:
            block.disable_notifications()
            block.value = value
            block.enable_notifications()
            # store to profile
            self.action_data.value = value


    def _min_range_changed_cb(self):
        value = self.output_min_range_custom_widget.value()
        block: SimConnectBlock
        block = self.block
        if block:
            block.disable_notifications()
            block.min_range_custom = value
            block.enable_notifications()
            # store to profile
            self.action_data.min_range = block.max_range_custom

    def _max_range_changed_cb(self):
        value = self.output_max_range_custom_widget.value()
        block: SimConnectBlock
        block = self.block
        if block:
            block.disable_notifications()
            block.max_range_custom = value
            block.enable_notifications()
            # store to profile
            self.action_data.max_range = block.max_range_custom
        

    def _command_changed_cb(self, index):
        ''' called when selected command changes '''
        command = self.command_widget.currentText()
        
        block = SimConnectBlock(command)
        self._update_block_ui(block)

        # store command to profile
        self.action_data.command = command

    def _update_block_ui(self, block : SimConnectBlock):
        ''' updates the UI with a data block '''
        if self.block and self.block != block:
            # unhook block events
            self.block.range_changed.disconnect(self._range_changed_cb)

        self.block = block

        
        if block and block.valid:
            self.output_widget.setVisible(True)

            # hook block events
            block.range_changed.connect(self._range_changed_cb)   

            # update UI based on block information 
            self.output_block_type_description_widget.setText(block.display_block_type)
            self.command_description_widget.setText(block.description)
            self.output_data_type_label_widget.setText(block.display_data_type)
            self.output_readonly_widget.setChecked(block.is_readonly)
            index = self.category_widget.findData(block.category)
            with QtCore.QSignalBlocker(self.category_widget):
                self.category_widget.setCurrentIndex(index)  
            is_ranged = block.is_ranged
            if is_ranged:
                self.output_min_range_widget.setValue(block.min_range)  
                self.output_max_range_widget.setValue(block.max_range)
                with QtCore.QSignalBlocker(self.output_min_range_custom_widget):
                    self.output_min_range_custom_widget.setValue(block.min_range_custom)  
                with QtCore.QSignalBlocker(self.output_max_range_custom_widget):
                    self.output_max_range_custom_widget.setValue(block.max_range_custom)  

            # only show range widget if the command supports it
            self.output_range_container_widget.setVisible(is_ranged)

            # update the output data type
            if block.output_data_type == SimConnectBlock.OutputType.FloatNumber:
                self.output_data_type_label_widget.setText("Number (float)")
            elif block.output_data_type == SimConnectBlock.OutputType.IntNumber:
                self.output_data_type_label_widget.setText("Number (int)")
            else:
                self.output_data_type_label_widget.setText("N/A")



            return
        
        # clear the data
        self.output_widget.setVisible(False)
        self.output_block_type_description_widget.setText("N/A")
        self.command_description_widget.setText("N/A")
        self.output_data_type_label_widget.setText("N/A")
        self.output_readonly_widget.setChecked(True)
        self.output_min_range_widget.setValue(0)  
        self.output_max_range_widget.setValue(0)



    def _range_changed_cb(self, event : SimConnectBlock.RangeEvent):
        ''' called when range information changes on the current simconnect command block '''
        self.output_min_range_widget.setValue(event.min)
        self.output_max_range_widget.setValue(event.max)
        self.output_min_range_custom_widget.setValue(event.min_custom)
        self.output_max_range_custom_widget.setValue(event.max_custom)

    def _mode_axis_cb(self):
        value = self.output_mode_axis_widget.isChecked()
        if value:
            self.action_data.mode = SimConnectActionMode.Ranged

    def _mode_value_cb(self):
        value = self.output_mode_set_value_widget.isChecked()
        if value:
            self.action_data.mode = SimConnectActionMode.SetValue
        
    def _mode_trigger_cb(self):
        value = self.output_mode_trigger_widget.isChecked()
        if value:
            self.action_data.mode = SimConnectActionMode.Trigger

    def _readonly_cb(self):
        block : SimConnectBlock
        block = self.block
        
        readonly = block is not None and block.is_readonly
        checked = self.output_readonly_widget.isChecked() 
        if readonly != checked:
            with QtCore.QSignalBlocker(self.output_readonly_widget):
                self.output_readonly_widget.setChecked(readonly)
        
        self.action_data.is_readonly = readonly

    def _populate_ui(self):
        """Populates the UI components."""
        current_command = self.command_widget.currentText()
        command = self.action_data.command
        if current_command != command:
            index = self.command_widget.findText(command)
            self.command_widget.setCurrentIndex(index)

        block = SimConnectBlock(command)
        self._update_block_ui(block)

        if self.action_data.input_type == InputType.JoystickAxis:
            # input drives the outputs
            self.output_value_widget.setVisible(False)
        else:
            # button or event intput
            self.output_value_widget.setVisible(block.is_value)


class MapToSimConnectFunctor(AbstractFunctor):

    def __init__(self, action):
        super().__init__(action)
        self.command = action.command # the command to execute
        self.value = action.value # the value to send (None if no data to send)
        self.block = SimConnectBlock(self.command)
    
    def process_event(self, event, value):

        if not self.block.valid:
            # invalid command
            return False

        if event.event_type == InputType.JoystickAxis:
            # axis
            min = 163
            
            
        elif value.current:
            # button
            return self.block.execute(self.value)
        
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

        # the current command category if the command is an event
        self.category = SimConnectEventCategory.NotSet

        # the current command name
        self.command = None

        # the value to output if any
        self.value = None

        # the block for the command
        self.min_range = -16383
        self.max_range = 16383

        # output mode
        self.mode = SimConnectActionMode.NotSet

        # readonly mode
        self.is_readonly = False

        # mapped input type
        self.input_type = self.get_input_type()

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
        #return False
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
