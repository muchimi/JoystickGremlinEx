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

from __future__ import annotations
import logging
import math
import os
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets, QtGui

import gremlin.actions
import gremlin.base_profile
import gremlin.event_handler
from gremlin.input_types import InputType
from gremlin.types import MouseButton
from gremlin.profile import read_bool, safe_read, safe_format
import gremlin.util
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput
from gremlin import input_devices
import gremlin.ui.osc_device
from gremlin.ui.osc_device import OscInterface


class OscValueWidget(QtWidgets.QWidget):
    ''' value container for an OSC message '''

    valueChanged = QtCore.Signal() # fires when the value changes
    enabledChanged = QtCore.Signal(bool) # fires when enabled status changes
    typeChanged = QtCore.Signal() # fires when the type change

    def __init__(self, enabled = False, label = None, value = None, is_integer = False, parent = None):
        super().__init__(parent)


        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._frame_widget = QtWidgets.QFrame()
        self._frame_widget.setFrameStyle(QtWidgets.QFrame.Box)
        self._frame_layout = QtWidgets.QHBoxLayout(self._frame_widget)

        self._is_integer = is_integer
        self._is_enabled = enabled if enabled is not None else False

        self.label_widget = QtWidgets.QLabel("Value:")
        if label:
            self.label_widget.setText(label)
        if not value:
            value = 1.0
        

        self._value_float_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._value_int_widget = gremlin.ui.ui_common.QIntLineEdit()

        self._value_float_widget.setValue(value)
        self._value_int_widget.setValue(int(value))

        
        self._is_enabled_widget = QtWidgets.QCheckBox("Enabled")
        self._is_enabled_widget.setToolTip("Enables this parameter")
        self._is_enabled_widget.clicked.connect(self._enabled_changed)
        self._is_int_widget = QtWidgets.QRadioButton("Integer")
        self._is_float_widget = QtWidgets.QRadioButton("Float")
        self._is_float_widget.setChecked(True)

        self._is_int_widget.clicked.connect(self._int_selected)
        self._is_float_widget.clicked.connect(self._float_selected)

        self._value_float_widget.valueChanged.connect(self._value_changed)
        self._value_float_widget.setRange(0, 1)
        self._value_int_widget.valueChanged.connect(self._value_changed)
        self._value_int_widget.setMinimum(0)

        self._container_widget = QtWidgets.QWidget()
        self._container_widget.setContentsMargins(0,0,0,0)
        self._container_layout = QtWidgets.QHBoxLayout(self._container_widget)

        self._container_layout.addWidget(self._value_float_widget)
        self._container_layout.addWidget(self._value_int_widget)
        self._container_layout.addWidget(self._is_int_widget)
        self._container_layout.addWidget(self._is_float_widget)

        self._frame_layout.addWidget(self.label_widget)
        self._frame_layout.addWidget(self._is_enabled_widget) 
        self._frame_layout.addWidget(self._container_widget) 

        self.main_layout.addWidget(self._frame_widget)
        self.main_layout.addStretch()

        self._update()
 

    
    def _update(self):
        self._container_widget.setEnabled(self._is_enabled)
        if self._is_integer:
            with QtCore.QSignalBlocker(self._is_int_widget):
                self._is_int_widget.setChecked(True)
            with QtCore.QSignalBlocker(self._is_float_widget):
                self._is_float_widget.setChecked(False)
            self._value_int_widget.setVisible(True)
            self._value_float_widget.setVisible(False)
        else:
            with QtCore.QSignalBlocker(self._is_int_widget):
                self._is_int_widget.setChecked(False)
            with QtCore.QSignalBlocker(self._is_float_widget):
                self._is_float_widget.setChecked(True)
            self._value_int_widget.setVisible(False)
            self._value_float_widget.setVisible(True)

            
    @property
    def label(self):
        return self.label_widget.text()
    
    @label.setter
    def label(self, value):
        self.label_widget.setText(value)

    @property 
    def is_integer(self)-> bool:
        return self._is_integer
    
    @is_integer.setter
    def is_integer(self, value : bool):
        if self._is_integer != value:
            self._is_integer = value
            self._update()

            
    @property 
    def is_enabled(self)-> bool:
        return self._is_enabled
    
    @is_enabled.setter
    def is_enabled(self, value : bool):
        if self._is_enabled != value:
            self._is_enabled = value
            self._update()
            

    @QtCore.Slot(bool)
    def _enabled_changed(self, checked):
        self._is_enabled = checked
        self._update()
        self.enabledChanged.emit(checked)

    
    @QtCore.Slot(bool)
    def _int_selected(self, checked):
        self._is_integer = True
        self._update()
        self.typeChanged.emit()

    @QtCore.Slot(bool)
    def _float_selected(self, checked):
        self._is_integer = False
        self._update()
        self.typeChanged.emit()


            
    @QtCore.Slot()
    def _value_changed(self):
        ''' value changed'''
        self.valueChanged.emit()

        
    def value(self):
        if self._is_integer:
            with QtCore.QSignalBlocker(self._value_int_widget):
                return self._value_int_widget.value()
        else:
            with QtCore.QSignalBlocker(self._value_float_widget):
                return self._value_float_widget.value()

    def setValue(self, value):
        if self.is_integer:
            if value < 0:
                value = 0
            self._value_int_widget.setValue(value)
        else:
            value = gremlin.util.clamp(value, 0, 1)
            self._value_float_widget.setValue(value)

    @property
    def enabled(self) -> bool:
        return self.is_enabled
    
    @enabled.setter
    def enabled(self, value : bool):
        if self._is_enabled != value:
            self._is_enabled = value
            self._update()



class MapToOscWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to mouse motion or buttons."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)

    def _create_ui(self):
        """Creates the UI components."""
        # Layouts to use
        self._container_widget = QtWidgets.QWidget()
        self._container_layout = QtWidgets.QVBoxLayout(self._container_widget)

        self._osc_container_widget = QtWidgets.QWidget()
        self._osc_container_layout = QtWidgets.QVBoxLayout(self._osc_container_widget)

        self._trigger_on_release_widget = QtWidgets.QCheckBox("Trigger on release")
        self._trigger_on_release_widget.clicked.connect(self._trigger_on_release_cb)

        self._v1_widget = OscValueWidget(label = "Parameter 1:", value = self.action_data.v1, enabled = self.action_data.v1_enabled, is_integer = self.action_data.v1_is_integer)
        self._v1_widget.valueChanged.connect(self._v1_value_changed)
        self._v1_widget.enabledChanged.connect(self._v1_enabled_changed)
        self._v1_widget.typeChanged.connect(self._v1_type_changed)
        self._v2_widget = OscValueWidget(label = "Parameter 2:", value = self.action_data.v2, enabled = self.action_data.v2_enabled, is_integer = self.action_data.v2_is_integer)
        

        self._v2_widget.valueChanged.connect(self._v2_value_changed)
        self._v1_widget.enabledChanged.connect(self._v2_enabled_changed)
        self._v1_widget.typeChanged.connect(self._v2_type_changed)

        self._container_layout.addWidget(self._osc_container_widget)

        self._osc_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._osc_widget.setToolTip("OSC command")
        if self.action_data.command:
            self._osc_widget.setText(self.action_data.command)
        self._osc_widget.textChanged.connect(self._command_changed)

        self._osc_container_layout.addWidget(QtWidgets.QLabel("Command:"))
        self._osc_container_layout.addWidget(self._osc_widget)
        self._osc_container_layout.addStretch()

        self._container_layout.addWidget(self._osc_container_widget)

        self._value_container_widget = QtWidgets.QWidget()
        self._value_container_layout = QtWidgets.QHBoxLayout(self._value_container_widget)
        self._value_container_layout.addWidget(self._v1_widget)
        self._value_container_layout.addWidget(self._v2_widget)
        self._value_container_layout.addStretch()

        self._warning_widget = gremlin.ui.ui_common.QIconLabel("fa.warning",use_qta=True,icon_color=QtGui.QColor("yellow"),text="", use_wrap=False)
        self.main_layout.addWidget(QtWidgets.QLabel("Send OSC command:"))
        self.main_layout.addWidget(self._container_widget)
        self.main_layout.addWidget(self._value_container_widget)
        self.main_layout.addWidget(self._trigger_on_release_widget)
        self.main_layout.addWidget(self._warning_widget)            
        
        self._warning_widget.setVisible(False)
        self._update()

    def _populate_ui(self):
        """Populates the UI components."""
        pass

    @QtCore.Slot(bool)
    def _trigger_on_release_cb(self, checked):
        self.action_data.trigger_on_release = checked

    @QtCore.Slot(bool)        
    def _v1_enabled_changed(self, enabled):
        self.action_data.v1_enabled = enabled

    @QtCore.Slot()        
    def _v1_value_changed(self):
        self.action_data.v1 = self._v1_widget.value()
    
    @QtCore.Slot()        
    def _v1_type_changed(self):
        self.action_data.v1_is_integer = self._v1_widget.is_integer

    @QtCore.Slot()        
    def _v2_value_changed(self):
        self.action_data.v2 = self._v2_widget.value()        

    @QtCore.Slot(bool)        
    def _v2_enabled_changed(self, enabled):
        self.action_data.v2_enabled = enabled

    @QtCore.Slot()        
    def _v2_type_changed(self):
        self.action_data.v2_is_integer = self._v2_widget.is_integer

    def _update(self):
        command = self._osc_widget.text()
        # validation
        if not command:
            self.setWarning("Command must be provided.")
            return
        if not command.startswith("/"):
            self.setWarning("OSC commands must start with a '/'")
            return
        self._warning_widget.setVisible(False)



    @QtCore.Slot()
    def _command_changed(self):
        command = self._osc_widget.text()
        self.action_data.command = command
        self._update()


    def setWarning(self, warning):
        if warning:
            self._warning_widget.setText(warning)
            self._warning_widget.setVisible(True)
        else:
            self._warning_widget.setVisible(False)


class MapToOscFunctor(gremlin.base_profile.AbstractFunctor):

    """Implements the functionality required to move a mouse cursor.

    This moves the mouse cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    def __init__(self, action : MapToOsc, parent = None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)
        self.action_data = action
        self.config = action
        self.oscInterface = OscInterface()

    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value):
        is_trigger = event.is_pressed and not self.action_data.trigger_on_release or \
            not event.is_pressed and self.action_data.trigger_on_release
        if is_trigger:
            # send the command
            if self.action_data.v1_enabled:
                v1 = int(self.action_data.v1) if self.action_data.v1_is_integer else v1
            else:
                v1 = None
            if self.action_data.v2_enabled:
                v2 = int(self.action_data.v2) if self.action_data.v2_is_integer else v2
            else:
                v2 = None

            self.oscInterface.send(self.action_data.command, v1, v2)
        

        

class MapToOsc(gremlin.base_profile.AbstractAction):

    """Action data for the map to OSC (open sound control) - allows the inputs to send an OSC command  """

    name = "Map to OSC"
    tag = "map-to-osc"

    default_button_activation = (True, True)
    # override allowed input types if different from default
    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
        InputType.KeyboardLatched,
        InputType.OpenSoundControl,
        InputType.Midi

    ]

    functor = MapToOscFunctor
    widget = MapToOscWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent

        self.command = None
        self.v1 = 1.0 # default v1 value
        self.v2 = 1.0 # default v2 value
        self.v1_enabled = False
        self.v2_enabled = False
        self.v1_is_integer = False
        self.v2_is_integer = False
        self.trigger_on_release = False # trigger on release

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"OSC [{self.command}]"
    
    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return f"osc.png"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return False

    def _parse_xml(self, node):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        if "command" in node.attrib:
            self.command = safe_read(node, "command", str, "")
        if "v1" in node.attrib:
            self.v1 = safe_read(node,"v1", float, 0)
        if "v1_enabled" in node.attrib:
            self.v1_enabled = safe_read(node,"v1_enabled", bool, False)
        if "v1_integer" in node.attrib:
            self.v1_is_integer = safe_read(node,"v1_integer", bool, False)
        if "v2" in node.attrib:
            self.v2 = safe_read(node,"v2", float, 0)
        if "v2_enabled" in node.attrib:
            self.v2_enabled = safe_read(node,"v2_enabled", bool, False)
        if "v2_integer" in node.attrib:
            self.v2_is_integer = safe_read(node,"v2_integer", bool, False)

        self.trigger_on_release = safe_read(node,"trigger_on_release", bool, False)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToOsc.tag)
        if self.command:
            node.set("command", self.command)
        if self.v1:
            node.set("v1", safe_format(self.v1, float))
        if self.v1_enabled:
            node.set("v1_enabled", safe_format(self.v1_enabled, bool))
        if self.v1_is_integer:
            node.set("v1_integer", safe_format(self.v1_integer, bool))
        if self.v2:
            node.set("v2", safe_format(self.v2, float))
        if self.v2_enabled:
            node.set("v1_enabled", safe_format(self.v2_enabled, bool))
        if self.v2_is_integer:
            node.set("v2_integer", safe_format(self.v2_integer, bool))
        
        node.set("trigger_on_release", safe_format(self.trigger_on_release, bool))

        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True


version = 1
name = "map-to-osc"
create = MapToOsc
