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
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.joystick_handling
from gremlin.types import MouseButton
from gremlin.profile import read_bool, safe_read, safe_format
import gremlin.util
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput
from gremlin import input_devices
import gremlin.ui.osc_device
from gremlin.ui.osc_device import OscInterface, OscClient


class OscValueWidget(QtWidgets.QWidget):
    valueChanged = QtCore.Signal() # fires when the value changes 
    typeChanged = QtCore.Signal() # fires when integer flag changes 
    
    def __init__(self, label = "Set Value:", value = None, is_integer = False, parent = None):
        super().__init__(parent)


        self.main_layout = QtWidgets.QGridLayout(self)

        self._frame_widget = QtWidgets.QFrame()
        self._frame_widget.setContentsMargins(0,0,0,0)
        self._frame_widget.setFrameStyle(QtWidgets.QFrame.Box)
        self._frame_layout = QtWidgets.QHBoxLayout(self._frame_widget)
        self._is_axis = False # true if mapping to an axis input

        self._is_integer = is_integer
        

        self.label_widget = QtWidgets.QLabel("Value:")
        if label:
            self.label_widget.setText(label)
        if not value:
            value = 1.0

            
        self.label_widget = QtWidgets.QLabel("Value:")
        if label:
            self.label_widget.setText(label)
        if not value:
            value = 1.0
        
        self._value_float_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._value_int_widget = gremlin.ui.ui_common.QIntLineEdit()

        self._value_float_widget.setValue(value)
        self._value_int_widget.setValue(int(value))

        self._is_int_widget = QtWidgets.QRadioButton("Integer")
        self._is_float_widget = QtWidgets.QRadioButton("Float")
        self._is_float_widget.setChecked(True)


        self._is_int_widget.clicked.connect(self._int_selected)
        self._is_float_widget.clicked.connect(self._float_selected)

        self._value_float_widget.valueChanged.connect(self._value_changed)
        self._value_float_widget.setRange(0, 1)

        self._value_int_widget.valueChanged.connect(self._value_changed)
        self._value_int_widget.setMinimum(0)   

        self._value_container_widget = QtWidgets.QWidget()
        self._value_container_widget.setContentsMargins(0,0,0,0)
        self._value_container_layout = QtWidgets.QHBoxLayout(self._value_container_widget)
        self._value_container_layout.setContentsMargins(0,0,0,0)

        self._value_container_layout.addWidget(QtWidgets.QLabel("Value:"))
        self._value_container_layout.addWidget(self._value_float_widget)
        self._value_container_layout.addWidget(self._value_int_widget)
        self._value_container_layout.addWidget(self._is_int_widget)
        self._value_container_layout.addWidget(self._is_float_widget)
        self._value_container_layout.addStretch()


        self.main_layout.addWidget(QtWidgets.QLabel(label),0,0)
        self.main_layout.addWidget(self._value_container_widget,1,0)
        self.main_layout.addWidget(QtWidgets.QWidget())
        self.main_layout.setColumnStretch(1,2)
        

        self._update()
    
    def _update(self):
        int_visible = self._is_integer
        if int_visible:
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

          
    @QtCore.Slot()
    def _value_changed(self):
        ''' value changed'''
        self.valueChanged.emit()

    def setValue(self, value):
        if self.is_integer:
            if value < 0:
                value = 0
            self._value_int_widget.setValue(value)
        else:
            value = gremlin.util.clamp(value, 0, 1)
            self._value_float_widget.setValue(value)        
    @property 
    def is_integer(self)-> bool:
        return self._is_integer
    
    @is_integer.setter
    def is_integer(self, value : bool):
        if self._is_integer != value:
            self._is_integer = value
            self._update()
            self.typeChanged.emit()

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




class OscInputWidget(QtWidgets.QWidget):
    ''' value container for an OSC message '''

    valuePressChanged = QtCore.Signal() # fires when the value changes (press)
    valueReleaseChanged = QtCore.Signal() # fires when the value changes (release)
    rangeChanged = QtCore.Signal() # fires when the axis range changes
    enabledChanged = QtCore.Signal(bool) # fires when enabled status changes
    typePressChanged = QtCore.Signal() # fires when the type change
    typeReleaseChanged = QtCore.Signal() # fires when the type change
    

    def __init__(self, label = None, 
                 enabled = False, 
                 value_press = None, 
                 value_release = None,
                 is_press_integer = False, 
                 is_release_integer = False, 
                 is_axis = False, 
                 min_value = 0, 
                 max_value = 1.0, 
                 parent = None):
        super().__init__(parent)


        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._frame_widget = QtWidgets.QFrame()
        self._frame_widget.setContentsMargins(0,0,0,0)
        self._frame_widget.setFrameStyle(QtWidgets.QFrame.Box)
        self._frame_layout = QtWidgets.QGridLayout(self._frame_widget)
        self._is_axis = False # true if mapping to an axis input

        self._is_axis = is_axis
        self._is_enabled = enabled if enabled is not None else False

        
        # this value should be updated when the axis value changes via setRepeaterValue() if in axis mode
        self._repeater_value = -1.0

        


        
        self._is_enabled_widget = QtWidgets.QCheckBox("Enabled")
        self._is_enabled_widget.setToolTip("Enables this parameter")
        self._is_enabled_widget.setChecked(self.enabled)
        self._is_enabled_widget.clicked.connect(self._enabled_changed)

        
        self._axis_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._axis_min_widget.setMinimum(0)
        self._axis_min_widget.setValue(min_value)
        self._axis_min_widget.valueChanged.connect(self._range_changed)
        self._axis_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._axis_max_widget.setMinimum(0)
        self._axis_max_widget.setValue(max_value)
        self._axis_max_widget.valueChanged.connect(self._range_changed)
        self._axis_repeater_widget = gremlin.ui.ui_common.AxisStateWidget(show_percentage=False,orientation=QtCore.Qt.Orientation.Horizontal, show_curve=False)
        self._axis_repeater_widget.setRange(min_value, max_value)
        

        
        self._axis_container_widget = QtWidgets.QWidget()
        self._axis_container_widget.setContentsMargins(0,0,0,0)
        self._axis_container_layout = QtWidgets.QHBoxLayout(self._axis_container_widget)

        
        self._axis_container_layout.addWidget(QtWidgets.QLabel("Range Min:"))
        self._axis_container_layout.addWidget(self._axis_min_widget)
        self._axis_container_layout.addWidget(QtWidgets.QLabel("Max:"))
        self._axis_container_layout.addWidget(self._axis_max_widget)
        self._axis_container_layout.addWidget(self._axis_repeater_widget)
        self._axis_container_layout.addStretch()

        self._container_widget = QtWidgets.QWidget()
        self._container_widget.setContentsMargins(0,0,0,0)
        self._container_layout = QtWidgets.QHBoxLayout(self._container_widget)

        self._value_press_widget = OscValueWidget(label = "Press Value:", is_integer= is_press_integer)
        self._value_release_widget = OscValueWidget(label = "Release Value:", is_integer = is_release_integer)
        
        self._value_press = value_press if value_press is not None else 1.0
        self._value_release = value_release if value_release is not None else 0.0

        self._value_press_widget.setValue(value_press)
        self._value_release_widget.setValue(value_release)


        self._value_press_widget.valueChanged.connect(self._value_press_changed)
        self._value_press_widget.typeChanged.connect(self._press_type_changed)
        self._value_release_widget.valueChanged.connect(self._value_release_changed)
        self._value_release_widget.typeChanged.connect(self._release_type_changed)

        self._container_layout.addWidget(self._value_press_widget)
        self._container_layout.addWidget(self._value_release_widget)
        self._container_layout.addWidget(self._axis_container_widget)

        self._frame_layout.setSpacing(0)
        row = 0
        if label:
            self._frame_layout.addWidget(QtWidgets.QLabel(label), row, 0) 
            row+=1
        self._frame_layout.addWidget(self._is_enabled_widget,row,0) 
        self._frame_layout.addWidget(self._container_widget,row,1) 
        self._frame_layout.addWidget(QtWidgets.QWidget(),row, 2)
        self._frame_layout.setColumnStretch(2,2)


       
        self.main_layout.addWidget(self._frame_widget)
        self.main_layout.addStretch()

        self._update()
 

    
    def _update(self):
        # mapped to axis?
        axis_visible = self._is_axis
        self._axis_container_widget.setVisible(axis_visible)
        self._value_press_widget.setVisible(not axis_visible)
        self._value_release_widget.setVisible(not axis_visible)
       
        
        self._container_widget.setEnabled(self._is_enabled)
        self._axis_container_widget.setEnabled(self._is_enabled)

        if not axis_visible:
            pass


    def setRepeaterValue(self, value : float):
        ''' sets the axis repeater value - expecting an input -1 to +1 '''
        self._repeater_value = value
        self._update_repeater()

    def _update_repeater(self):
        ''' updates the repeater '''
        value = gremlin.util.scale_to_range(self._repeater_value, target_min = self.min_range, target_max = self.max_range)
        self._axis_repeater_widget.setValue(value)


    @QtCore.Slot()
    def _range_changed(self):
        # tell UI range changed
        self._axis_repeater_widget.setRange(self.min_range, self.max_range)
        self._update_repeater()
        self.rangeChanged.emit()

    @property
    def min_range(self) -> float:
        return self._axis_min_widget.value()
    
    @min_range.setter
    def min_range(self, value : float):
        if value >= 0:
            self._axis_min_widget.setValue(value)

    @property
    def max_range(self) -> float:
        return self._axis_max_widget.value()
    
    @max_range.setter
    def max_range(self, value : float):
        if value >= 0:
            self._axis_max_widget.setValue(value)

    @property
    def label(self):
        return self.label_widget.text()
    
    @label.setter
    def label(self, value):
        self.label_widget.setText(value)

    @property 
    def is_press_integer(self)-> bool:
        return self._value_press_widget.is_integer
    
    @is_press_integer.setter
    def is_press_integer(self, value : bool):
        self._value_press_widget.is_integer = value

    @property 
    def is_release_integer(self)-> bool:
        return self._value_release_widget.is_integer
    
    @is_release_integer.setter
    def is_release_integer(self, value : bool):
        self._value_release_widget.is_integer = value        
            
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

            
    @QtCore.Slot()
    def _value_press_changed(self):
        ''' value changed'''
        self.valuePressChanged.emit()

    @QtCore.Slot()
    def _press_type_changed(self):        
        self.typePressChanged.emit(0)        

    @QtCore.Slot()
    def _release_type_changed(self):        
        self.typeReleaseChanged.emit(1)        

    @QtCore.Slot()
    def _value_release_changed(self):
        ''' value changed'''
        self.valueReleaseChanged.emit()
        
    def valuePressed(self):
        return self._value_press_widget.value()
    
    def valueReleased(self):
        return self._value_release_widget.value()
    
    def setValuePressed(self, value):
        self._value_press_widget.setValue(value)
    def setValueRelease(self, value):
        self._value_release_widget.setValue(value)

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
        self._osc_container_layout = QtWidgets.QHBoxLayout(self._osc_container_widget)

        self._server_container_widget = QtWidgets.QWidget()
        self._server_container_widget.setContentsMargins(0,0,0,0)
        self._server_container_layout = QtWidgets.QHBoxLayout(self._server_container_widget)

        self._server_ip_widget = gremlin.ui.ui_common.QDataIPLineEdit(self.action_data.server_ip)
        self._server_ip_widget.textChanged.connect(self._server_ip_changed)
        self._server_port_widget = gremlin.ui.ui_common.QIntLineEdit()
        
        self._server_port_widget.setRange(4096, 65535)
        self._server_port_widget.setValue(self.action_data.server_port)
        self._server_port_widget.valueChanged.connect(self._server_port_changed)
        self._server_reset_widget = QtWidgets.QPushButton("Reset")
        self._server_reset_widget.setToolTip("Resets to default")
        self._server_reset_widget.clicked.connect(self._reset_server)

        self._server_container_layout.addWidget(QtWidgets.QLabel("Target IP:"))
        self._server_container_layout.addWidget(self._server_ip_widget)
        self._server_container_layout.addWidget(QtWidgets.QLabel("Target Port:"))
        self._server_container_layout.addWidget(self._server_port_widget)
        self._server_container_layout.addWidget(self._server_reset_widget)
        self._server_container_layout.addStretch()

        # self._trigger_on_release_widget = QtWidgets.QCheckBox("Trigger on release")
        # self._trigger_on_release_widget.setToolTip("When enabled, the action will trigger when the input is released.")
        # self._trigger_on_release_widget.clicked.connect(self._trigger_on_release_cb)

        is_axis = self.action_data.input_is_axis()
        if is_axis:
            # hook the input
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event_handler)

        # # trigger is only used when the input is not an axis
        # self._trigger_on_release_widget.setVisible(not is_axis)

        self._v1_widget = OscInputWidget(label = "Parameter 1:",
                                         value_press = self.action_data.v1_press, 
                                         value_release = self.action_data.v1_release,
                                         enabled = self.action_data.v1_enabled, 
                                         is_press_integer = self.action_data.v1_is_press_integer, 
                                         is_release_integer = self.action_data.v1_is_release_integer, 
                                         is_axis = is_axis,
                                         min_value = self.action_data.v1_min_range,
                                         max_value = self.action_data.v1_max_range,
                                         )
        self._v1_widget.valuePressChanged.connect(self._v1_value_press_changed)
        self._v1_widget.valuePressChanged.connect(self._v1_value_release_changed)
        self._v1_widget.enabledChanged.connect(self._v1_enabled_changed)
        self._v1_widget.typePressChanged.connect(self._v1_press_type_changed)
        self._v1_widget.typeReleaseChanged.connect(self._v1_release_type_changed)
        self._v1_widget.rangeChanged.connect(self._v1_range_changed)
        

        self._v2_widget = OscInputWidget(label = "Parameter 2:",
                                         value_press = self.action_data.v2_press, 
                                         value_release = self.action_data.v2_release,
                                         enabled = self.action_data.v2_enabled, 
                                         is_press_integer = self.action_data.v2_is_press_integer, 
                                         is_release_integer = self.action_data.v2_is_release_integer, 
                                         is_axis = is_axis,
                                         min_value = self.action_data.v2_min_range,
                                         max_value = self.action_data.v2_max_range,
                                         )
        

        self._v2_widget.valuePressChanged.connect(self._v2_value_press_changed)
        self._v2_widget.valuePressChanged.connect(self._v2_value_release_changed)
        self._v2_widget.enabledChanged.connect(self._v2_enabled_changed)
        self._v2_widget.typePressChanged.connect(self._v2_press_type_changed)
        self._v2_widget.typeReleaseChanged.connect(self._v2_release_type_changed)
        self._v2_widget.rangeChanged.connect(self._v2_range_changed)

        self._container_layout.addWidget(self._osc_container_widget)

        self._osc_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._osc_widget.setToolTip("OSC command")
        if self.action_data.command:
            self._osc_widget.setText(self.action_data.command)
        self._osc_widget.textChanged.connect(self._command_changed)

        self._osc_container_layout.addWidget(QtWidgets.QLabel("Command:"))
        self._osc_container_layout.addWidget(self._osc_widget)
        self._osc_container_layout.addWidget(self._server_container_widget)
        self._osc_container_layout.addStretch()

        self._container_layout.addWidget(self._osc_container_widget)

        self._value_container_widget = QtWidgets.QWidget()
        self._value_container_layout = QtWidgets.QVBoxLayout(self._value_container_widget)
        self._value_container_layout.addWidget(self._v1_widget)
        self._value_container_layout.addWidget(self._v2_widget)
        self._value_container_layout.addStretch()

        self._warning_widget = gremlin.ui.ui_common.QIconLabel("fa.warning",use_qta=True,icon_color=QtGui.QColor("yellow"),text="", use_wrap=False)
        self.main_layout.addWidget(QtWidgets.QLabel("Send OSC command:"))
        self.main_layout.addWidget(self._container_widget)
        self.main_layout.addWidget(self._value_container_widget)
        #self.main_layout.addWidget(self._trigger_on_release_widget)
        self.main_layout.addWidget(self._warning_widget)            
        
        self._warning_widget.setVisible(False)
        self._update()

        # get the current joystick value so repeaters are correct for start position
        if is_axis:
            value = gremlin.joystick_handling.get_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
            self._v1_widget.setRepeaterValue(value)
            self._v2_widget.setRepeaterValue(value)


    def _populate_ui(self):
        """Populates the UI components."""
        pass


    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
        if gremlin.shared_state.is_running:
            return 

        if not event.is_axis:
            return 
        
        value = event.value
        
        if event.device_guid != self.action_data.hardware_device_guid:
            return
        if event.identifier != self.action_data.hardware_input_id:
            return

        self._v1_widget.setRepeaterValue(value)
        self._v2_widget.setRepeaterValue(value)

    @QtCore.Slot()
    def _reset_server(self):
        ''' reset IP and port to configured defaults '''
        msgbox = gremlin.ui.ui_common.ConfirmBox(f"Reset server data to defaults?")
        result = msgbox.show()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            config = gremlin.config.Configuration()
            self._server_ip_widget.setText(config.osc_host) # also updates action_data
            self._server_port_widget.setValue(config.osc_output_port) # also updates action_data
    


    @QtCore.Slot()
    def _server_ip_changed(self):
        self.action_data.server_ip = self._server_ip_widget.text()

    @QtCore.Slot()
    def _server_port_changed(self):
        self.action_data.server_port = self._server_port_widget.value()

    # @QtCore.Slot(bool)
    # def _trigger_on_release_cb(self, checked):
    #     self.action_data.trigger_on_release = checked

    @QtCore.Slot(bool)        
    def _v1_enabled_changed(self, enabled):
        self.action_data.v1_enabled = enabled

    @QtCore.Slot()        
    def _v1_value_press_changed(self):
        self.action_data.v1_press = self._v1_widget.valuePress()        
    @QtCore.Slot()        
    def _v1_value_release_changed(self):
        self.action_data.v1_release = self._v1_widget.valueRelease()        

    @QtCore.Slot()        
    def _v1_press_type_changed(self, index):
        self.action_data.v1_is_press_integer = self._v1_widget.is_press_integer

    @QtCore.Slot()        
    def _v2_press_type_changed(self, index):
        self.action_data.v2_is_press_integer = self._v2_widget.is_press_integer

    @QtCore.Slot()        
    def _v1_release_type_changed(self, index):
        self.action_data.v1_is_release_integer = self._v1_widget.is_release_integer

    @QtCore.Slot()        
    def _v2_release_type_changed(self, index):
        self.action_data.v2_is_release_integer = self._v2_widget.is_release_integer
      

    @QtCore.Slot()        
    def _v1_range_changed(self):
        self.action_data.v1_min_range = self._v1_widget.min_range
        self.action_data.v1_max_range = self._v1_widget.max_range        

    @QtCore.Slot()        
    def _v2_value_press_changed(self):
        self.action_data.v2_press = self._v2_widget.valuePress()        
    @QtCore.Slot()        
    def _v2_value_release_changed(self):
        self.action_data.v2_release = self._v2_widget.valueRelease()        

    @QtCore.Slot(bool)        
    def _v2_enabled_changed(self, enabled):
        self.action_data.v2_enabled = enabled


    @QtCore.Slot()        
    def _v2_range_changed(self):
        self.action_data.v2_min_range = self._v2_widget.min_range
        self.action_data.v2_max_range = self._v2_widget.max_range
        

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
        

    def profile_start(self):
        ''' occurs when process starts '''
        device_name = gremlin.shared_state.get_device_name(self.action_data.hardware_device_guid)
        self.osc_client = self.oscInterface.getClient(self.action_data.server_ip,
                                            self.action_data.server_port,                                            
                                            name=f"OSC {device_name}/{self.action_data.hardware_input_id}")
        self.osc_client.start()

    def profile_stop(self):
        if self.osc_client is not None:
            self.osc_client.stop()
            self.osc_client = None


    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value):

        is_axis = self.action_data.input_is_axis()
        if is_axis:
            # axis mode - compute the output values
            raw = value.current
            if self.action_data.v1_enabled:
                v1 = gremlin.util.scale_to_range(raw, target_min = self.action_data.v1_min_range,
                                             target_max = self.action_data.v1_max_range)
            else:
                v1 = None
            if self.action_data.v2_enabled:
                v2 = gremlin.util.scale_to_range(raw, target_min = self.action_data.v2_min_range,
                                             target_max = self.action_data.v2_max_range)
            else:
                v2 = None

            self.osc_client.send(self.action_data.command, v1, v2)
            
        else:                                      
            # button mode - see what to trigger       

            if event.is_pressed:
                # send the command
                if self.action_data.v1_enabled:
                    v1 = int(self.action_data.v1_press) if self.action_data.v1_is_press_integer else self.action_data.v1_press
                else:
                    v1 = None
                if self.action_data.v2_enabled:
                    v2 = int(self.action_data.v2_press) if self.action_data.v2_is_press_integer else self.action_data.v1_press
                else:
                    v2 = None
            else:
                # send the command
                if self.action_data.v1_enabled:
                    v1 = int(self.action_data.v1_release) if self.action_data.v1_is_release_integer else self.action_data.v1_release
                else:
                    v1 = None
                if self.action_data.v2_enabled:
                    v2 = int(self.action_data.v2_release) if self.action_data.v2_is_release_integer else self.action_data.v2_release
                else:
                    v2 = None


            self.osc_client.send(self.action_data.command, v1, v2)
        

        

class MapToOsc(gremlin.base_profile.AbstractAction):

    """Action data for the map to OSC (open sound control) - allows the inputs to send an OSC command  """

    name = "Map to OSC"
    tag = "map-to-osc"

    default_button_activation = (True, True)
    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard,
    #     InputType.KeyboardLatched,
    #     InputType.OpenSoundControl,
    #     InputType.Midi

    # ]

    functor = MapToOscFunctor
    widget = MapToOscWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent

        config = gremlin.config.Configuration()
        self.command = None
        self.server_ip = config.osc_host
        self.server_port = config.osc_output_port
        self.v1_press = 1.0 # default v1 value
        self.v2_press = 1.0 # default v2 value
        self.v1_release = 0.0 # default v1 value
        self.v2_release = 0.0 # default v2 value
        self.v1_enabled = False
        self.v2_enabled = False
        self.v1_is_press_integer = False
        self.v1_is_release_integer = False
        self.v2_is_press_integer = False
        self.v2_is_release_integer = False
        self.trigger_on_release = False # trigger on release
        self.v1_map_to_axis = False
        self.v2_map_to_axis = False
        self.v1_min_range = 0.0 # min range when mapping to an axis
        self.v1_max_range = 1.0 # max range whem mapping to an axis
        self.v2_min_range = 0.0 # min range when mapping to an axis
        self.v2_max_range = 1.0 # max range whem mapping to an axis

    

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
        if "server_ip" in node.attrib:
            self.server_ip = node.get("server_ip")
        if "server_port" in node.attrib:
            self.server_port = safe_read(node, "server_port", int, 8000)

        if "v1" in node.attrib:
            # old version
            self.v1_press = safe_read(node,"v1", float, 1)
        if "v1_press" in node.attrib:
            self.v1_press = safe_read(node,"v1_press", float, 1)
        if "v1_release" in node.attrib:
            self.v1_release = safe_read(node,"v1_release", float, 0)                        


        if "v1_enabled" in node.attrib:
            self.v1_enabled = safe_read(node,"v1_enabled", bool, False)
        if "v1_integer" in node.attrib:
            self.v1_is_press_integer = safe_read(node,"v1_integer", bool, False)
        if "v1_press_integer" in node.attrib:
            self.v1_is_press_integer = safe_read(node,"v1_press_integer", bool, False)
        if "v1_release_integer" in node.attrib:
            self.v1_is_release_integer = safe_read(node,"v1_release_integer", bool, False)

        if "v2" in node.attrib:
            # old version
            self.v2_press = safe_read(node,"v2", float, 1)
        if "v2_press" in node.attrib:
            self.v2_press = safe_read(node,"v2_press", float, 1)            
        if "v2_release" in node.attrib:
            self.v2_release = safe_read(node,"v2_release", float, 0)                        

        if "v2_enabled" in node.attrib:
            self.v2_enabled = safe_read(node,"v2_enabled", bool, False)
        if "v2_integer" in node.attrib:
            self.v2_is_press_integer = safe_read(node,"v2_integer", bool, False)
        if "v2_press_integer" in node.attrib:
            self.v1_is_press_integer = safe_read(node,"v2_press_integer", bool, False)
        if "v2_release_integer" in node.attrib:
            self.v2_is_release_integer = safe_read(node,"v2_release_integer", bool, False)
            
        if "v1_min_range" in node.attrib:
            self.v1_min_range = safe_read(node,"v1_min_range", float, 0)
        if "v1_max_range" in node.attrib:
            self.v1_max_range = safe_read(node,"v1_max_range", float, 1)

        if "v2_min_range" in node.attrib:
            self.v2_min_range = safe_read(node,"v2_min_range", float, 0)
        if "v2_max_range" in node.attrib:
            self.v2_max_range = safe_read(node,"v2_max_range", float, 1)            
        

        self.trigger_on_release = safe_read(node,"trigger_on_release", bool, False)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToOsc.tag)
        if self.command:
            node.set("command", self.command)
        if self.server_ip:
            node.set("server_ip", self.server_ip)
        if self.server_port is not None:
            node.set("server_port", safe_format(self.server_port, int))
        if self.v1_press:
            node.set("v1_press", safe_format(self.v1_press, float))
        if self.v1_release:
            node.set("v1_release", safe_format(self.v1_release, float))
        if self.v1_enabled:
            node.set("v1_enabled", safe_format(self.v1_enabled, bool))
        if self.v1_is_press_integer:
            node.set("v1_press_integer", safe_format(self.v1_is_press_integer, bool))
        if self.v1_is_release_integer:
            node.set("v1_release_integer", safe_format(self.v1_is_release_integer, bool))
        if self.v2_press:
            node.set("v2_press", safe_format(self.v2_press, float))
        if self.v2_release:
            node.set("v2_release", safe_format(self.v2_release, float))            
        if self.v2_enabled:
            node.set("v1_enabled", safe_format(self.v2_enabled, bool))
        if self.v2_is_press_integer:
            node.set("v2_press_integer", safe_format(self.v2_is_press_integer, bool))
        if self.v2_is_release_integer:
            node.set("v2_release_integer", safe_format(self.v2_is_release_integer, bool))
        is_axis = self.hardware_input_type == InputType.JoystickAxis
        if is_axis:
            node.set("v1_min_range", safe_format(self.v1_min_range, float))
            node.set("v1_max_range", safe_format(self.v1_max_range, float))
            node.set("v2_min_range", safe_format(self.v2_min_range, float))
            node.set("v1_max_range", safe_format(self.v2_max_range, float))
        
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
