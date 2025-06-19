# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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
import sys

from PySide6 import QtCore, QtWidgets, QtGui

import gremlin.actions
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.types import MouseButton
from gremlin.profile import read_bool, safe_read, safe_format
import gremlin.util
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput
from gremlin import input_devices
import gremlin.ui.osc_device
from gremlin.ui.osc_device import OscInterface, OscClient
import logging
syslog = logging.getLogger("system")

class OscArg(QtCore.QObject):
    ''' holds a single OSC argument definition '''

    valueChanged = QtCore.Signal(object) # fires when the value changes

    def __init__(self, index : int, value = 0.0, device_id : str = None, input_id = None, enabled : bool = True):
        super().__init__()
        self._id = gremlin.util.get_guid()
        self._index = index # index of the arg starting at 0
        self._value = value
        
        self._data_type = type(value)
        self._enabled = enabled
        self._min_range = 0.0
        self._max_range = 1.0
        self._value_on_release = value
        
        self._source_device_id = device_id # ID of the source device, None for none
        self._source_axis_id = input_id if isinstance(input_id, int) else None # ID of the source axis on the source device, None for none
        self._source_mode = "input" # possible values are "input", "device", "value"

        self._send_on_press = True # if true, emits on press button
        self._send_on_release = True # if true, emits on release button
    
    @property
    def id(self):
        return self._id
    @id.setter
    def id(self, value : str):
        self._id = value

    @property
    def index(self) -> int:
        return self._index
    @index.setter
    def index(self, value : int):
        self._index = value
    
    def value(self):
        ''' press or main value'''
        return self._value
    def setValue(self, value):
        self._data_type = type(value) if value is not None else None
        if self._value != value:
            self._value = value
            self.valueChanged.emit(value)

    def dataType(self) -> type:
        return self._data_type

    def valueOnRelease(self):
        ''' release value, if different from press value '''
        return self._value_on_release
    def setValueOnRelease(self, value):
        self._value_on_release = value

    def setSendOnPress(self, value: bool):
        self._send_on_press = value

    def setSendOnRelease(self, value: bool):
        self._send_on_release = value

    def sendOnPress(self) -> bool:
        return self._send_on_press
    def sendOnRelease(self) -> bool:
        return self._send_on_release
        

    def getPressReleaseValue(self, is_pressed : bool):
        if is_pressed:
            return self._value
        else:
            return self._value_on_release if self._value_on_release is not None else self._value

    def useInput(self) -> bool:
        return self._use_input
    def setUseInput(self, value : bool):
        self._use_input = value

    def sourceDevice(self) -> str:
        return self._source_device_id
    def setSourceDevice(self, value : str):
        self._source_device_id = value

    def sourceAxis(self) -> int:
        return self._source_axis_id
    def setSourceAxis(self, value : int):
        self._source_axis_id = value

    def sourceMode(self) -> str:
        return self._source_mode
    
    def setSourceMode(self, mode : str):
        self._source_mode = mode

    def enabled(self) -> bool:
        return self._enabled
    
    def setEnabled(self, value : bool):
        self._enabled = value

    @property
    def is_integer(self) -> bool:
        return isinstance(self._value, int)
    
    @property
    def is_float(self) -> bool:
        return isinstance(self._value, float)

    @property
    def is_bool(self) -> bool:
        return isinstance(self._value, bool)
    
    @property
    def is_string(self) -> bool:
        return isinstance(self._value, str)
    
    @property
    def min_range(self):
        return self._min_range
    @min_range.setter
    def min_range(self, value):
        self._min_range = value

    @property
    def max_range(self):
        return self._max_range
    
    @max_range.setter
    def max_range(self, value):
        self._max_range = value

    def scaleValue(self, value):
        ''' scales a value to min/max range'''
        if self._min_range is not None and self._max_range is not None:
            return gremlin.util.scale_to_range(value, target_min = self._min_range, target_max = self._max_range)
        return value
    

    def to_xml(self):
        ''' writes the data to xml '''
        node = ElementTree.Element("osc-arg")
        node.set("id", self._id)
        value = self._value
        value_release = self._value_on_release
        is_number = False
        data_type = type(value) if value is not None else self._data_type
        if data_type == str:
            node.set("value", value)
            node.set("type", "str")
            node.set("value-release", value_release)
        elif data_type == float:
            node.set("value", safe_format(value, float))
            node.set("type", "float")
            node.set("value-release", safe_format(value_release, float))
            is_number = True
        elif data_type == int:
            node.set("value", safe_format(value, int))
            node.set("type", "int")
            node.set("value-release", safe_format(value_release, int))
            is_number = True
        elif data_type == bool:
            node.set("value", safe_format(value, bool))
            node.set("type", "bool")
            node.set("value-release", safe_format(value_release, bool))

        node.set("enabled", safe_format(self._enabled, bool))
        node.set("exec-press", safe_format(self._send_on_press, bool))
        node.set("exec-release", safe_format(self._send_on_release, bool))

        node.set("source-mode", self._source_mode)
        if self._source_mode == "device":
            device = gremlin.joystick_handling.device_info_from_guid(self._source_device_id)
            axis_name = device.axis_names[self._source_axis_id-1]
            comment_node = ElementTree.Comment(f" Source device: {device.name} Source axis: {axis_name} ")
            node.append(comment_node)
            if self._source_device_id: node.set("device-guid",self._source_device_id)
            if self._source_axis_id is not None: node.set("axis", safe_format(self._source_axis_id, int))

        if is_number:
            node.set("min-range", safe_format(self._min_range, float))
            node.set("max-range", safe_format(self._max_range, float))
        
        return node
    



    def from_xml(self, node):
        ''' reads a data node '''
        if "id" in node.attrib:
            self._id = node.get("id")   

        is_number = False
        node_type = node.get("type")
        value_release = None
        if node_type == "str":
            value = safe_read(node, "value", str, '')
            if "value-release" in node.attrib:
                value_release = safe_read(node,"value-release", str, '')
        elif node_type == "float":
            value = safe_read(node, "value", float, 1.0)
            if "value-release" in node.attrib:
                value_release = safe_read(node,"value-release", float, 0)
            is_number = True
        elif node_type == "int":
            value = safe_read(node, "value", int, 1)
            if "value-release" in node.attrib:
                value_release = safe_read(node,"value-release", int, 0)
            is_number = True
        elif node_type == "bool":
            value = safe_read(node, "value", bool, True)
            if "value-release" in node.attrib:
                value_release = safe_read(node,"value-release", bool, False)
        else: 
            value = None

        self._value = value
        self._value_on_release = value_release
        self._enabled = safe_read(node,"enabled",bool,True)

        if "source-mode" in node.attrib:
            self._source_mode = node.get("source-mode")

        if self._source_mode == "device":
            if "device-guid" in node.attrib:
                self._source_device_id = node.get("device-guid")
            if "axis" in node.attrib:
                self._source_axis_id = safe_read(node,"axis", int, 1)

        if "exec-press" in node.attrib:
            self._send_on_press = safe_read(node,"exec-press", bool, True)
        if "exec-release" in node.attrib:
            self._send_on_release = safe_read(node,"exec-release", bool, False)
        
        if is_number:
            if "min-range" in node.attrib:
                self._min_range = safe_read(node, "min-range", float, -1.0)
            if "max-range" in node.attrib:
                self._max_range = safe_read(node, "max-range", float, 1.0)



class OscValueWidget(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(object) # fires when the value changes 
    typeChanged = QtCore.Signal() # fires when integer flag changes 
    enableValueOnPressChanged = QtCore.Signal(bool)
    enableValueOnReleaseChanged = QtCore.Signal(bool)
    enabledChanged = QtCore.Signal(bool) # fires when enabled changes
    
    def __init__(self, osc_arg : OscArg, action_data, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        
        self._is_axis = action_data.input_is_axis()
        self._arg = osc_arg
        value = osc_arg.value()
        release_value = osc_arg.valueOnRelease()

        self.press_widget = None
        self.release_widget = None
        self.value_widget = None

        self._action_data = action_data # associated input data for this arg
        
        self._arg.valueChanged.connect(self._value_changed)

        self._type_selector_widget = gremlin.ui.ui_common.QTypeSelectorWidget(data_type = osc_arg.dataType())
        self._type_selector_widget.valueChanged.connect(self._type_changed)

        self.enabled_widget = QtWidgets.QCheckBox("Enabled")
        self.enabled_widget.setChecked(osc_arg.enabled())
        self.enabled_widget.clicked.connect(self._enabled_changed)
        self.enabled_widget.setToolTip("Enables this parameter output")
        
        self._source_widget = gremlin.ui.ui_common.QDataComboBox()
        self._source_widget.addItem("Input","input")

        source_mode = osc_arg.sourceMode()
        if self._is_axis:
            self._source_widget.addItem("Device","device")
            
        self._source_widget.addItem("Fixed Value","value")

        source_mode = osc_arg.sourceMode()
        index = self._source_widget.findData(source_mode)
        if index != -1:
            self._source_widget.setCurrentIndex(index)

        self._source_widget.currentIndexChanged.connect(self._source_mode_changed)

        self.main_layout.addWidget(self.enabled_widget)
        self.main_layout.addWidget(self._type_selector_widget)


        is_integer = osc_arg.is_integer
        is_bool = osc_arg.is_bool
        is_string = osc_arg.is_string
        is_float = osc_arg.is_float

        max_float = sys.float_info.max
        min_float = sys.float_info.min

        # input is an axis 
        self._scale_min_widget = gremlin.ui.ui_common.QFloatLineEdit(value = osc_arg.min_range, min_range= min_float, max_range = max_float)
        self._scale_min_widget.valueChanged.connect(self._scale_min_changed)
        self._scale_max_widget = gremlin.ui.ui_common.QFloatLineEdit(value = osc_arg.max_range, min_range= min_float, max_range = max_float)
        self._scale_min_widget.valueChanged.connect(self._scale_max_changed)

        self._scale_widget, self._scale_layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel("Scale Min:"),
                                                                                     self._scale_min_widget,
                                                                                     QtWidgets.QLabel("Max:"),
                                                                                     self._scale_max_widget,
                                                                                     ])

   
        # float editor for fixed value press
        self._send_on_press_widget = QtWidgets.QCheckBox("Execute on press")
        self._send_on_press_widget.setChecked(self._arg.sendOnPress())
        self._send_on_press_widget.setToolTip("If checked, commands sends on a press event")
        self._send_on_press_widget.clicked.connect(self._send_on_press_changed)


        self._send_on_release_widget = QtWidgets.QCheckBox("Execute on release")
        self._send_on_release_widget.setChecked(self._arg.sendOnRelease())
        self._send_on_release_widget.setToolTip("If checked, commands sends on a release event")
        self._send_on_release_widget.clicked.connect(self._send_on_release_changed)

        self._value_float_widget = gremlin.ui.ui_common.QFloatLineEdit(min_range= min_float, max_range = max_float)
        self._value_float_widget.valueChanged.connect(self._press_value_changed)
        
        # float editor for fixed value release
        self._release_float_widget = gremlin.ui.ui_common.QFloatLineEdit(min_range= min_float, max_range = max_float)
        self._release_float_widget.valueChanged.connect(self._release_value_changed)

        if is_float:
            self._value_float_widget.setValue(value)
            self._release_float_widget.setValue(release_value)
            if self._is_axis:
                self.value_widget = self._value_float_widget
            
                self.press_widget = self._value_float_widget
                self.release_widget = self._release_float_widget
            

        # int editor
        self._value_int_widget = gremlin.ui.ui_common.QIntLineEdit()
        self._release_int_widget = gremlin.ui.ui_common.QIntLineEdit()
        if is_integer:
            self._value_int_widget.setValue(value)
            self._release_int_widget.setValue(release_value)

        # string editor
        self._value_string_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._value_string_widget.textChanged.connect(self._value_string_changed)

        self._release_string_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._release_string_widget.textChanged.connect(self._release_string_changed)
        if is_string:
            self._value_string_widget.setText(value)
            self._release_string_widget.setText(release_value)



        # bool editor 
        widgets = []

        widgets.append(QtWidgets.QLabel("On Press:" ))
        self._value_bool_widget = gremlin.ui.ui_common.QOnOffWidget(value = True)
        widgets.append(self._value_bool_widget)

        self._release_bool_widget = gremlin.ui.ui_common.QOnOffWidget(value = False)
        widgets.append(self._release_bool_widget)

        if is_bool:
            self._value_bool_widget.setValue(value)
            self._release_bool_widget.setValue(release_value)

    
        self._float_widget, self._float_layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel("On press:"),
                                                                                    self._value_float_widget,
                                                                                    QtWidgets.QLabel("On release:"),
                                                                                    self._release_float_widget])
        
        self._int_widget, self._float_layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel("On press:"),
                                                                                    self._value_int_widget,
                                                                                    QtWidgets.QLabel("On release:"),
                                                                                    self._release_int_widget])
        
        self._string_widget, self._string_layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel("On press:"),
                                                                                    self._value_string_widget,
                                                                                    QtWidgets.QLabel("On release:"),
                                                                                    self._release_string_widget])
        
        self._bool_widget, self._bool_layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel("On press:"),
                                                                                    self._value_bool_widget,
                                                                                    QtWidgets.QLabel("On release:"),
                                                                                    self._release_bool_widget])
        

        device_id = osc_arg.sourceDevice()
        input_id = osc_arg.sourceAxis()
        self._selector_widget = gremlin.ui.ui_common.QAxisSourceSelector(device_id = device_id, input_id = input_id, label = None)

        self._selector_widget.valueChanged.connect(self._source_changed)

        self._sync_widget = QtWidgets.QPushButton("Sync")
        self._sync_widget.setToolTip("Synchronize device with current input")
        self._sync_widget.clicked.connect(self._sync_input)
        self._sync_widget.setEnabled(self._action_data is not None)

        self._axis_widget, _ = gremlin.ui.ui_common.getHContainer([self._selector_widget, self._sync_widget])

        widget, _ = gremlin.ui.ui_common.getHContainer(self._source_widget, "Source:")
        self.main_layout.addWidget(widget)

        self._auto_widget = QtWidgets.QLabel("Auto (scaled axis value 0..1)" if self._is_axis else "Auto (1 for press, 0 for release)")
        self._warning_widget = gremlin.ui.ui_common.QWarning()

        widgets = [ 
                   self._auto_widget,
                   self._warning_widget,
                   self._axis_widget,
                   self._float_widget,
                   self._int_widget,
                   self._bool_widget,
                   self._string_widget
        ]

        widget, _ = gremlin.ui.ui_common.getHContainer(widgets, "Output:")
        self.main_layout.addWidget(widget)

        self.main_layout.addWidget(self._scale_widget)

        self._send_widget, _ = gremlin.ui.ui_common.getHContainer([self._send_on_press_widget, self._send_on_release_widget])
        self.main_layout.addWidget(self._send_widget)
        

        #self.main_layout.addWidget(QtWidgets.QLabel(f"Is axis: {self._is_axis}"))
        self._update()

    @QtCore.Slot(bool)
    def _send_on_press_changed(self, checked : bool):
        self._arg.setSendOnPress(checked)

    @QtCore.Slot(bool)
    def _send_on_release_changed(self, checked : bool):
        self._arg.setSendOnRelease(checked)

    @QtCore.Slot()
    def _press_value_changed(self):
        self._arg.setValue(self._value_float_widget.value())

    @QtCore.Slot()
    def _release_value_changed(self):
        self._arg.setValueOnRelease(self._release_float_widget.value())

    @QtCore.Slot()
    def _value_string_changed(self):
        self._arg.setValue(self._value_string_widget.text())

    @QtCore.Slot()
    def _release_string_changed(self):
        self._arg.setValueOnRelease(self._release_string_widget.text())                

    @QtCore.Slot()
    def _sync_input(self):
        ''' syncs the device / axis list to the current input '''
        if self._action_data:
            device_id = self._action_data.hardware_device_id
            input_id = self._action_data.hardware_input_id
            self._selector_widget.sync(device_id, input_id)


    def _set_warning(self, warning : str):
        self._warning_widget.setText(warning)
        self._warning_widget.setVisible(True)
    
    def _update(self):
        ''' updates the UI '''
        
        data_type = self._arg.dataType()
        source_mode = self._arg.sourceMode()
        self._warning_widget.setVisible(False)
        if self._is_axis:
            data_type = self._type_selector_widget.value()
            int_visible = False
            bool_visible = False
            string_visible = False
            float_visible = False
            axis_visible = False
            scale_visible = data_type == float
            send_visible = False
            if source_mode == "device":
                axis_visible = data_type == float
            else:
                float_visible = source_mode == "value"
        else:
            # non axis scale, hide scale and make visible the widgets appropriate for the data type
            axis_visible = False
            int_visible = False
            bool_visible = False
            string_visible = False
            float_visible = False
            scale_visible = False
            send_visible = True
            if source_mode == "value":
                int_visible = data_type == int
                float_visible = data_type == float
                bool_visible = data_type == bool
                string_visible = data_type == str


        auto_visible = source_mode == "input"

        self._auto_widget.setVisible(auto_visible)
        self._int_widget.setVisible(int_visible)
        self._float_widget.setVisible(float_visible)
        self._bool_widget.setVisible(bool_visible)
        self._string_widget.setVisible(string_visible)
        self._scale_widget.setVisible(scale_visible)
        self._axis_widget.setVisible(axis_visible)
        self._send_widget.setVisible(send_visible)
        

    @QtCore.Slot()
    def _source_changed(self, device : gremlin.joystick_handling.DeviceSummary, axis : int):
        self._arg.setSourceDevice(device.device_id)
        self._arg.setSourceAxis(axis)

    @QtCore.Slot()
    def _source_mode_changed(self):
        self._arg.setSourceMode(self._source_widget.currentData())
        self._update()

    @QtCore.Slot()
    def _scale_min_changed(self):
        self._arg._min_range = self._scale_min_widget.value()


    @QtCore.Slot()
    def _scale_max_changed(self):
        self._arg._max_range = self._scale_max_widget.value()


    @QtCore.Slot(bool)
    def _enabled_changed(self, enabled):
        self._arg.setEnabled(enabled)
        self.enabledChanged.emit(enabled)
        self._update()


    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def _value_for_type(self, value, datatype : type, default_value = None):
        if value is None:
            return None
        value_type = type(value)
        
        if datatype == bool:
            if default_value is None:
                default_value = True
            if value_type == int or value_type == float:
                value = value != 0  
            elif value_type != bool:
                value = default_value # default to True
        elif datatype == str:
            value = str(value)
        elif datatype == int:
            if default_value is None:
                default_value = 0
            if value_type == str:
                if value.isnumeric():
                    value = int(value)
            else:
                value = default_value
        elif datatype == float:
            if default_value is None:
                default_value = 0.0
            if value_type == str:
                if value.isnumeric():
                    value = float(value)
            else:
                value = default_value
        else:
            assert True,f"Don't know how to handle data type: {datatype}"

        return value

        


    @QtCore.Slot(type)
    def _type_changed(self, data : type):
        value = self._arg.value()
        release_value = self._arg.valueOnRelease()
        
        # convert based on the prior value if possible

        

        if data == bool:
            value = self._value_for_type(value, data, True)
            release_value = self._value_for_type(release_value, data, False)
            self.press_widget = self._value_bool_widget
            self.release_widget = self._release_bool_widget
            self.value_widget = self.press_widget

        elif data == str:
            value = self._value_for_type(value, data)
            release_value = self._value_for_type(release_value, data)
            self.press_widget = self._value_string_widget
            self.release_widget = self._release_string_widget
            self.value_widget = self.press_widget
        elif data == int:
            value = self._value_for_type(value, data, 1)
            release_value = self._value_for_type(release_value, data, 0)
            self.press_widget = self._value_int_widget
            self.release_widget = self._release_int_widget
            self.value_widget = self.press_widget
        elif data == float:
            value = self._value_for_type(value, data, 1.0)
            release_value = self._value_for_type(release_value, data, 0.0)
            self.press_widget = self._value_float_widget
            self.release_widget = self._release_float_widget
            self.value_widget = self.press_widget
        else:
            assert False,f"Don't know how to handle data type: {data}"

        self._arg.setValue(value)
        self._arg.setValueOnRelease(release_value)
        self._update()


    @QtCore.Slot()
    def _bool_changed(self):
        widget = self.sender()
        self._arg.setValue(widget.data)

    @QtCore.Slot()
    def _int_changed(self):
        self._arg.setValue(self._value_int_widget.value())
        
    @QtCore.Slot()
    def _float_changed(self):
        self._arg.setValue(self._value_float_widget.value())

    @QtCore.Slot()
    def _string_changed(self):
        self._arg.setValue(self._value_string_widget.value())

    @QtCore.Slot(object)
    def _value_changed(self, value):
        self.valueChanged.emit(value)


class OscInputWidget(QtWidgets.QWidget):
    ''' value container for an OSC message '''

    deleteRequested = QtCore.Signal(OscArg) # sends the ID of the arg to delete
    moveRequested = QtCore.Signal(str) # sends a move request, passes the direction "up" "down" "top" "bottom"

    def __init__(self, label : str, arg : OscArg,  action_data, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._arg = arg
        self._frame_widget = gremlin.ui.ui_common.QGroupBox()
        self._frame_widget.setContentsMargins(0,0,0,0)
        self._frame_layout = QtWidgets.QGridLayout(self._frame_widget) # QtWidgets.QGridLayout(self._frame_widget)
        self._is_axis = action_data.input_is_axis() # true if mapping to an axis input
        self._action_data = action_data

        left_content_widget, left_content_layout = gremlin.ui.ui_common.getVContainer()
        right_content_widget, right_content_layout = gremlin.ui.ui_common.getVContainer()
        alignment = QtCore.Qt.AlignmentFlag.AlignTop

        self._frame_widget.setTitle(label)
        self._frame_layout.addWidget(left_content_widget, 0,0, alignment = alignment)
        self._frame_layout.addWidget(QtWidgets.QWidget(), 0,1)
        self._frame_layout.addWidget(right_content_widget, 0,2, alignment = alignment)
        self._frame_layout.setColumnStretch(1,1)

        icon = gremlin.ui.ui_common.Icons.trashIcon() 
        delete_widget = QtWidgets.QPushButton()
        delete_widget.setIcon(icon)
        delete_widget.setToolTip("Delete this parameter")
        delete_widget.clicked.connect(self._delete_cb)

        arg_count = len(action_data.args) if action_data else 0
        toolbar = gremlin.ui.ui_common.QReorderToolbar(index = arg.index, count = arg_count, hide = True)
        toolbar.moveRequested.connect(self._move_requested)
       
        widget, _ = gremlin.ui.ui_common.getHContainer([
            toolbar,
            delete_widget
        ])

        right_content_layout.addWidget(widget)

        self._value_widget = OscValueWidget(arg, action_data = action_data)

        left_content_layout.addWidget(self._value_widget)

        self.main_layout.addWidget(self._frame_widget)

        self._update()

    @QtCore.Slot(str)
    def _move_requested(self, direction : str):
        ''' called when a parameter should move '''
        self.moveRequested.emit(direction)

    def value(self) -> OscArg:
        return self._arg

    @QtCore.Slot()
    def _move(self):
        widget = self.sender()
        direction = widget.data
        self.moveRequested.emit(direction)

    @QtCore.Slot()
    def _delete_cb(self):
        self.deleteRequested.emit(self._arg)


    @QtCore.Slot()
    def _command_changed(self):
        command = self._osc_widget.text()
        self.action_data.command = command

     
    def _update(self):
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

    @QtCore.Slot(bool)
    def _enable_value_on_press_changed(self, checked):
        self.enableValueOnPressChanged.emit(checked)

    @QtCore.Slot(bool)
    def _enable_value_on_release_changed(self, checked):
        self.enableValueOnReleaseChanged.emit(checked)
            
    @QtCore.Slot()
    def _value_press_changed(self):
        ''' value changed'''
        self.valuePressChanged.emit()

    @QtCore.Slot(bool)
    def _enable_press_changed(self, enabled):
        self.enableValueOnPressChanged.emit(enabled)

    @QtCore.Slot(bool)
    def _enable_release_changed(self, enabled):
        self.enableValueOnReleaseChanged.emit(enabled)

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



class MapToOscExWidget(gremlin.ui.input_item.AbstractActionWidget):

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

        self._test_widget = QtWidgets.QPushButton("Test")
        self._test_widget.setToolTip("Test the current configuration")
        self._test_widget.clicked.connect(self._test_command)


        self._server_container_layout.addWidget(QtWidgets.QLabel("Target IP:"))
        self._server_container_layout.addWidget(self._server_ip_widget)
        self._server_container_layout.addWidget(QtWidgets.QLabel("Target Port:"))
        self._server_container_layout.addWidget(self._server_port_widget)
        self._server_container_layout.addWidget(self._server_reset_widget)
        self._server_container_layout.addWidget(self._test_widget)
        self._server_container_layout.addStretch()

        self._list_widget, self._list_layout = gremlin.ui.ui_common.getVContainer()

        icon = gremlin.ui.ui_common.Icons.addIcon()
        self.add_arg_widget = QtWidgets.QPushButton("Add Argument")
        self.add_arg_widget.setIcon(icon)
        self.add_arg_widget.setToolTip("Adds a new OSC argument")
        self.add_arg_widget.clicked.connect(self._add_arg)

        self.clear_args_widget = QtWidgets.QPushButton("Clear Arguments")
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        self.clear_args_widget.setIcon(icon)
        self.clear_args_widget.setToolTip("Clears all argurments")

        self.clear_args_widget.clicked.connect(self._clear_args)


        
        is_axis = self.action_data.input_is_axis()
        if is_axis:
            # hook the input
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event_handler)


        self._osc_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._osc_widget.setToolTip("OSC command")
        if self.action_data.command:
            self._osc_widget.setText(self.action_data.command)
        self._osc_widget.textChanged.connect(self._command_changed)

        self._osc_container_widget, self._osc_container_layout = gremlin.ui.ui_common.getHContainer([
                                                                                QtWidgets.QLabel("Command:"),
                                                                                self._osc_widget,
                                                                                self._server_container_widget
                                                                        ])

        
        self._container_layout.addWidget(self._osc_container_widget)

        self._button_widget, _ = gremlin.ui.ui_common.getHContainer([self.add_arg_widget, self.clear_args_widget], left_stretch=True)

        warning_color = gremlin.ui.ui_common.Color.warningColor()
        self._warning_widget = gremlin.ui.ui_common.QIconLabel("ph.shield-warning-fill",use_qta=True,icon_color=QtGui.QColor(warning_color),text="", use_wrap=False)
        self.main_layout.addWidget(QtWidgets.QLabel("Send OSC command:"))
        self.main_layout.addWidget(self._container_widget)
        self.main_layout.addWidget(self._list_widget)
        self.main_layout.addWidget(self._warning_widget)            
        self.main_layout.addWidget(self._button_widget)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release, label = "Command")
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self.main_layout.addWidget(self._execute_widget)
        
        self._warning_widget.setVisible(False)
        self._update()

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked

    def _populate_ui(self):
        gremlin.util.clear_layout(self._list_layout)
        is_axis = self.action_data.input_is_axis()
        for index, arg in enumerate(self.action_data.args):
            arg.index = index
            widget = OscInputWidget(f"Parameter {index+1}", arg, self.action_data)
            widget.deleteRequested.connect(self._delete_arg)
            widget.moveRequested.connect(self._move_requested)
            self._list_layout.addWidget(widget)

        self._execute_widget.setVisible(not is_axis)


    def _update(self):
        ''' refresh the UI '''
        self._populate_ui()

        self._warning_widget.setVisible(False)
        command = self._osc_widget.text()
        # validation
        if not command:
            self.setWarning("Command must be provided.")
            
        if not command.startswith("/"):
            self.setWarning("OSC commands must start with a '/'")
            
        
    @QtCore.Slot(str)
    def _move_requested(self, direction):
        widget = self.sender()
        arg = widget.value()
        
        args = self.action_data.args
        index = args.index(arg)
        args.pop(index) # remove it from the list
        count = len(args) # how many we have left
        match direction:
            case "up":
                new_index = index-1
                if new_index < 0:
                    new_index = 0
            case "down":
                new_index = index + 1
                if new_index > count :
                    new_index = count
            case "top":
                new_index = 0
            case "bottom":
                new_index = len(args)
            case _:
                syslog.error(f"OSC: Don't know how to handle paramter move direction: [{direction}]")
                return

        # re-insert
        args.insert(new_index, arg)
        # redraw with new parameter order
        self._populate_ui()



    @QtCore.Slot(OscArg)
    def _delete_arg(self, arg : OscArg):
        self.action_data.args.remove(arg)
        self._populate_ui()



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
    def _test_command(self):
        ''' sends a test command '''
        if self.action_data.command:
            self.action_data.profile_start()
            is_axis = self.action_data.input_is_axis()
            if is_axis:
                # get current input value
                device_id = self.action_data.hardware_device_id
                input_id = self.action_data.hardware_input_id
                raw = gremlin.joystick_handling.get_axis(device_id, input_id)
                value = gremlin.actions.Value(raw, raw, True)
                self.action_data.process_event(False, value)
            else:
                # on/off
                self.action_data.process_event(True, None)
                self.action_data.process_event(False, None)

            self.action_data.profile_stop()
            

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
    def _add_arg(self):
        ''' adds an argument '''
        device_id = self._get_device_id()
        input_id = self._get_input_id()
        arg = OscArg(0.0, device_id = device_id, input_id = input_id) # default to float
        self.action_data.args.append(arg)
        self._update()

    @QtCore.Slot()
    def _clear_args(self):
        ''' removes all args '''
        if self.action_data.args:
            msgbox = gremlin.ui.ui_common.ConfirmBox(f"Remove arguments?")
            result = msgbox.show()
            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                self.action_data.args.clear()
                self._update()





    @QtCore.Slot()
    def _server_ip_changed(self):
        self.action_data.server_ip = self._server_ip_widget.text()

    @QtCore.Slot()
    def _server_port_changed(self):
        self.action_data.server_port = self._server_port_widget.value()



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


class MapToOscExFunctor(gremlin.base_profile.AbstractFunctor):

    """Implements the functionality required to move a mouse cursor.

    This moves the mouse cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    def __init__(self, action : MapToOscEx, parent = None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)
        self.action_data = action
        self.config = action
        self.oscInterface = OscInterface()
        self.osc_client = None
        self.valid = True
        
    def latch_extra_inputs(self):
        ''' returns the list of additional latched inputs that should trigger this action 
            list of (device_guid, input_type, input_id) to latch to this action (trigger on change) '''
        latched_list = []
        if self.action_data.input_is_axis():
            device_id = self.hardware_device_id
            input_id = self.hardware_input_id
            arg : OscArg
            args = [arg for arg in self.action_data.args if arg.sourceMode() == "device"]
            for arg in args:
                arg_device_id = arg.sourceDevice()
                arg_input_id = arg.sourceAxis()
                if arg_device_id == device_id and input_id == arg_input_id:
                    continue
                latch_pair = (arg_device_id, InputType.JoystickAxis, arg_input_id)
                if not latch_pair in latched_list:
                    latched_list.append(latch_pair)

        return latched_list
  


    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value, extra_data = None) -> bool:
        ''' processes the event - moved to the main action so we can do testing in the UI at design time '''
        return self.action_data.process_event(event.is_pressed, value)

class MapToOscEx(gremlin.base_profile.AbstractAction):

    """Action data for the map to OSC (open sound control) - allows the inputs to send an OSC command  """

    name = "Map to OSC Ex"
    tag = "map-to-osc-ex"

    
    default_button_activation = (True, True)
    

    functor = MapToOscExFunctor
    widget = MapToOscExWidget

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
        
        self.args = [] # OSC parameters 

        v1 = OscArg(0,1.0, device_id = self.hardware_device_id, input_id = self.hardware_input_id)
        self.args.append(v1)
        
        self.valid = False
        self.oscInterface = OscInterface()
        self.osc_client = None

        self.exec_on_press = True # true if command executes on press (non axis input only)
        self.exec_on_release = True # true if command executes on release (non axis input only)




    def profile_start(self):
        ''' called on profile start '''
        
        self.osc_client = None

        device_name = gremlin.shared_state.get_device_name(self.hardware_device_guid)
        if gremlin.util.validateIp(self.server_ip):
            self.osc_client = self.oscInterface.getClient(self.server_ip,
                                            self.server_port,                                            
                                            name=f"OSC {device_name}/{self.hardware_input_id}")
            self.osc_client.start()
            self.valid = True
        else:
            syslog.error(f"OSC SEND: invalid target IP: {self.action_data.server_ip}")
            self.valid = False
            return

        verbose = gremlin.config.Configuration().verbose_mode_osc
        if verbose:
            syslog.info(f"OSC SEND: target: {self.action_data.server_ip} port: {self.action_data.server_port}")

    def profile_stop(self):
        if self.osc_client is not None:
            self.osc_client.stop()
            self.osc_client = None


    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"OSC [{self.command}]"
    
    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        return f"{prefix}osc.png"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return False

    def _parse_xml(self, node, data = None):
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

        if "press-exec" in node.attrib:
            self.exec_on_press = safe_read(node,"press-exec",bool, False)
        if "release-exec" in node.attrib:
            self.exect_on_release = safe_read(node,"release-exec",bool, False)

        self.args = []
        index = 0
        for child in node:
            if child.tag == "args":
                for node_arg in child:
                    arg = OscArg(index)
                    arg.from_xml(node_arg)
                    self.args.append(arg)
                    index +=1

        

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToOscEx.tag)
        if self.command:
            node.set("command", self.command)
        if self.server_ip:
            node.set("server_ip", self.server_ip)
        if self.server_port is not None:
            node.set("server_port", safe_format(self.server_port, int))
        
        node.set("press-exec", safe_format(self.exec_on_press, bool))
        node.set("release-exec", safe_format(self.exec_on_release, bool))

        arg : OscArg
        if self.args:
            node_args = ElementTree.SubElement(node,"args")
            for arg in self.args:
                child = arg.to_xml()
                node_args.append(child)
        
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True


    def process_event(self, is_pressed, value) -> bool:
        ''' sends a command '''
        if not self.command:
            # command must be set
            return False
        
        verbose = gremlin.config.Configuration().verbose_mode_osc
        is_axis = self.input_is_axis()
        arg : OscArg
        params = []


        if is_axis:
            # axis mode - compute the output values
            raw = value.current
            for arg in self.args:
                data_type = arg.dataType()
                source_mode = arg.sourceMode()
                if source_mode == "input" and data_type == float:
                    # use the input data 
                    arg_value = arg.scaleValue(raw) # input expected -1 to + 1
                elif source_mode == "device":
                    # get data from the specified axis
                    device_id = arg.sourceDevice()
                    input_id = arg.sourceAxis()

                    axis_value = gremlin.joystick_handling.get_axis(device_id, input_id)
                    if axis_value is None:
                        axis_value = 0.0 # default
                        syslog.error(f"OSC: unable to get axis data for device [{device_id}] input [{input_id}] - using 0.0")

                    # scale the value to the output range - input expected -1 to +1 
                    arg_value = arg.scaleValue(axis_value)

                else:
                    # fixed value
                    if data_type == int:
                        arg_value = 0
                    elif data_type == float:
                        arg_value =  0.0
                    elif data_type == bool:
                        arg_value = False
                    elif data_type == str:
                        arg_value = "" 
                
                params.append(arg_value)

        else:              

            if is_pressed and not self.exec_on_press:
                # not enabled for execute on press
                return True
            if not is_pressed and not self.exec_on_release:
                # not enabled for execute on release
                return True

            # button mode - see what to trigger       
            for arg in self.args:
                if is_pressed and not arg.sendOnPress():
                    continue # not enabled for press
                if not is_pressed and not arg.sendOnRelease():
                    continue # not enabled for release
                source_mode = arg.sourceMode()
                if source_mode == "input":
                    # compute the values to send based on the input 
                    data_type = arg.dataType()
                    if data_type == int:
                        arg_value = 1 if is_pressed else 0
                    elif data_type == float:
                        arg_value = 1.0 if is_pressed else 0.0
                    elif data_type == bool:
                        arg_value = is_pressed
                    elif data_type == str:
                        arg_value = "true" if is_pressed else "false"
                else:
                    arg_value = arg.getPressReleaseValue(is_pressed)
                params.append(arg_value)

        if verbose:
            stub = ""
            for value in params:
                stub += f"{value:0.3f} "
            syslog.info(f"OSC SEND: sending {self.command} {stub} ")
        self.osc_client.sendEx(self.command, params)

        return True

version = 1
name = "map-to-osc-ex"
create = MapToOscEx
