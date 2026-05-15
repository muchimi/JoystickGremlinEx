
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# -*- coding: utf-8; -*-
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# from __future__ import annotations # deprecated with python 3.14+
from PySide6 import QtWidgets, QtCore, QtGui
import gremlin
import gremlin.config
import gremlin.joystick_handling
import gremlin.util
from gremlin.util import parse_guid, safe_read, safe_format
from . import ui_common
from gremlin.input_types import InputType
from typing import cast

import gremlin.event_handler
import gremlin.shared_state
from gremlin.ui.qsliderwidget import QSliderWidget
from PySide6.QtGui import QColor
from lxml import etree
import os
import logging
import gremlin.singleton_decorator
import psygnal
from psygnal import Signal
import gremlin.ui.ui_common
from shiboken6 import Shiboken
import gremlin.threading
import queue
import time
import copy


syslog = logging.getLogger("system")


class CalibrationUi(gremlin.ui.ui_common.BaseDialogUi):

    """Dialog to calibrate joystick axes."""

    def __init__(self, parent=None):
        """Creates the calibration UI.

        :param parent the parent widget of this object
        """
        super().__init__(self.__class__.__name__, parent)
        self.devices = gremlin.joystick_handling.physical_devices()
        self.current_selection_id = 0

        # Create the required layouts
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.axes_layout = QtWidgets.QVBoxLayout()
        self.button_layout = QtWidgets.QHBoxLayout()

        self._create_ui()

    def _create_ui(self):
        """Creates all widgets required for the user interface."""
        if not Shiboken.isValid(self):
            return
        # If there are no devices available show a message about this and abort
        if len(self.devices) == 0:
            label = QtWidgets.QLabel("No devices present for calibration")
            label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
            label.setWordWrap(True)
            label.setFrameShape(QtWidgets.QFrame.Box)
            label.setMargin(10)
            self.main_layout.addWidget(label)

            return

        # Device selection drop down
        self.device_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.device_dropdown.currentIndexChanged.connect(
            self._create_axes
        )
        for device in self.devices:
            self.device_dropdown.addItem(device.name)

        # Set the title
        self.setWindowTitle("Calibration")

        # Various buttons
        self.button_close = QtWidgets.QPushButton("Close")
        self.button_close.pressed.connect(self.close)
        self.button_save = QtWidgets.QPushButton("Save")
        self.button_save.pressed.connect(self._save_calibration)
        self.button_centered = QtWidgets.QPushButton("Centered")
        self.button_centered.pressed.connect(self._calibrate_centers)
        self.button_layout.addWidget(self.button_save)
        self.button_layout.addWidget(self.button_close)
        self.button_layout.addStretch(0)
        self.button_layout.addWidget(self.button_centered)

        # Axis widget readout headers
        self.label_layout = QtWidgets.QGridLayout()
        label_spacer = QtWidgets.QLabel()
        label_spacer.setMinimumWidth(200)
        label_spacer.setMaximumWidth(200)
        self.label_layout.addWidget(label_spacer, 0, 0, 0, 3)
        label_current = QtWidgets.QLabel("<b>Current</b>")
        label_current.setAlignment(QtCore.Qt.AlignRight)
        self.label_layout.addWidget(label_current, 0, 3)
        label_minimum = QtWidgets.QLabel("<b>Minimum</b>")
        label_minimum.setAlignment(QtCore.Qt.AlignRight)
        self.label_layout.addWidget(label_minimum, 0, 4)
        label_center = QtWidgets.QLabel("<b>Center</b>")
        label_center.setAlignment(QtCore.Qt.AlignRight)
        self.label_layout.addWidget(label_center, 0, 5)
        label_maximum = QtWidgets.QLabel("<b>Maximum</b>")
        label_maximum.setAlignment(QtCore.Qt.AlignRight)
        self.label_layout.addWidget(label_maximum, 0, 6)

        # Organizing everything into the various layouts
        self.main_layout.addWidget(self.device_dropdown)
        self.main_layout.addLayout(self.label_layout)
        self.main_layout.addLayout(self.axes_layout)
        self.main_layout.addStretch(0)
        self.main_layout.addLayout(self.button_layout)

        # Create the axis calibration widgets
        self.axes = []
        self._create_axes(self.current_selection_id)

        # Connect to the joystick events
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._handle_event)

    def _calibrate_centers(self):
        """Records the centered or neutral position of the current device."""
        for widget in self.axes:
            widget.centered()

    def _save_calibration(self):
        """Saves the current calibration data to the hard drive."""
        cfg = gremlin.config.Configuration()
        cfg.set_calibration(
            self.devices[self.current_selection_id].device_guid,
            [axis.limits for axis in self.axes]
        )
        gremlin.event_handler.EventListener().reload_calibrations()

    def _create_axes(self, index):
        """Creates the axis calibration widget for the current device.

        :param index the index of the currently selected device
            in the dropdown menu
        """
        ui_common.clear_layout(self.axes_layout)
        self.axes = []
        self.current_selection_id = index
        for i in range(self.devices[index].axis_count):
            self.axes.append(AxisCalibrationWidget())
            self.axes_layout.addWidget(self.axes[-1])

    def _handle_event(self, event):
        """Process a single joystick event.

        :param event the event to process
        """
        if event.device_guid == self.devices[self.current_selection_id].device_guid \
                and event.event_type == InputType.JoystickAxis:
            axis_id = gremlin.joystick_handling.linear_axis_index(
                self.devices[self.current_selection_id].axismap_list,
                event.identifier
            )
            self.axes[axis_id-1].set_current(event.raw_value)

    def closeEvent(self, event):
        """Closes the calibration window.

        :param event the close event
        """
        # Only disconnect from the joystick event handler if we have actual
        # devices, as otherwise we never connected to it
        if len(self.devices) > 0:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.disconnect(self._handle_event)
        super().closeEvent(event)


class AxisCalibrationWidget(QtWidgets.QWidget):

    """Widget displaying calibration information about a single axis."""

    def __init__(self, parent=None):
        """Creates a new object.

        :param parent the parent widget of this one
        """
        QtWidgets.QWidget.__init__(self, parent)

        self.main_layout = QtWidgets.QGridLayout(self)
        self.limits = [0, 0, 0]

        # Create slider showing the axis position graphically
        self.slider = QtWidgets.QProgressBar()
        self.slider.setMinimum(-32768)
        self.slider.setMaximum(32767)
        self.slider.setValue(self.limits[1])
        self.slider.setMinimumWidth(200)
        self.slider.setMaximumWidth(200)

        # Create the labels
        self.current = QtWidgets.QLabel("0")
        self.current.setAlignment(QtCore.Qt.AlignRight)
        self.minimum = QtWidgets.QLabel("0")
        self.minimum.setAlignment(QtCore.Qt.AlignRight)
        self.center = QtWidgets.QLabel("0")
        self.center.setAlignment(QtCore.Qt.AlignRight)
        self.maximum = QtWidgets.QLabel("0")
        self.maximum.setAlignment(QtCore.Qt.AlignRight)
        self._update_labels()

        # Populate the layout
        self.main_layout.addWidget(self.slider, 0, 0, 0, 3)
        self.main_layout.addWidget(self.current, 0, 3)
        self.main_layout.addWidget(self.minimum, 0, 4)
        self.main_layout.addWidget(self.center, 0, 5)
        self.main_layout.addWidget(self.maximum, 0, 6)

    def set_current(self, value):
        """Updates the limits of the axis.

        :param value the new value
        """
        self.slider.setValue(value)
        if value > self.limits[2]:
            self.limits[2] = value
        if value < self.limits[0]:
            self.limits[0] = value
        self._update_labels()

    def centered(self):
        """Records the value of the center or neutral position."""
        self.limits[1] = self.slider.value()
        self._update_labels()

    def _update_labels(self):
        """Updates the axis limit values."""
        self.current.setText(f"{self.slider.value(): 5d}")
        self.minimum.setText(f"{self.limits[0]: 5d}")
        self.center.setText(f"{self.limits[1]: 5d}")
        self.maximum.setText(f"{self.limits[2]: 5d}")


class CalibrationData:
    __slots__ = [
        "device_guid",
        "input_id",
        "_is_centered",
        "_calibrated_min",
        "_calibrated_max",
        "_calibrated_center",
        "_deadzone_min",
        "_deadzone_max",
        "_deadzone_center_min",
        "_deadzone_center_max",
        "_trigger_threshold",
        "_trigger_threshold_enabled",
        "_last_value",
        "_inverted",

    ]
    def __init__(self, source = None):
        self.device_guid = None # axis device guid this data applies to
        self.input_id = None # axis input id this data applies to
        self._is_centered = True # true if the axis is centered (has a center calibration value)
        config = gremlin.config.Configuration()
        config.changed.connect(self._configuration_changed)
        self.reset()

        if source:
            self.copyFrom(source)
        

    def reset(self):
        ''' resets calibration data to defaults '''
        # do not reset center option
        config = gremlin.config.Configuration()
        self._calibrated_min = -1.0
        self._calibrated_max = 1.0
        self._calibrated_center = 0.0 # used only if the stick is centered
        self._deadzone_min = -1.0
        self._deadzone_max = 1.0
        self._deadzone_center_min = 0.0 # deadzone center left
        self._deadzone_center_max = 0.0 # deadzone center right
        self._inverted = False # true if inverted
        self._trigger_threshold_enabled = config.filter_axis_events
        self._trigger_threshold = config.filter_axis_threshold
        
        self._last_value = None # last value (normalized)

    
    def copyFrom(self, other : CalibrationData):
        self._calibrated_min = other._calibrated_min
        self._calibrated_max = other._calibrated_max
        self._calibrated_center = other._calibrated_center
        self._deadzone_min = other._deadzone_min
        self._deadzone_max = other._deadzone_max
        self._deadzone_center_min = other._deadzone_center_min
        self._deadzone_center_max = other._deadzone_center_max
        self._inverted = other._inverted
        

    @QtCore.Slot(str)
    def _configuration_changed(self, key : str, value):
        if key == "filter_axis_events":
            self._trigger_threshold_enabled = value
        elif key == "filter_axis_threshold":
            self._trigger_threshold = value
        
        

    def startCalibrate(self):
        ''' starts a recalibration'''
        self._calibrated_min = 0.0
        self._calibrated_max = 0.0
        self._calibrated_center = 0.0 # used only if the stick is centered

    def stopCalibrate(self):
        self._calibrate = False

    def calibrating(self) -> bool:
        return self._calibrating

    @property
    def hasData(self) -> bool:
        ''' True if the calibration data is non default '''
        return self._calibrated_min != -1.0 or \
               self._calibrated_max != 1.0 or \
               self._calibrated_center != 0.0 or \
               self._deadzone_min != -1.0 or \
               self._deadzone_max != 1.0 or \
               self._deadzone_center_min != 0.0 or \
               self._deadzone_center_max != 0.0 or \
               self._inverted 
        
    
    def _update(self):
        ''' updates data flag '''
        # let the UI know the data changed
        el = gremlin.event_handler.EventListener()
        el.calibration_changed.emit(self)

    def compare(self, other : CalibrationData) -> bool:
        ''' compares two calibration objects to see if they map to the same object '''
        if other is None:
            return False
        return gremlin.util.compare_guid(self.device_guid, other.device_guid) and self.input_id == other.input_id
    
    def __eq__(self, other : CalibrationData):
        d1 = gremlin.util.normalize_guid(self.device_guid)
        d2 = gremlin.util.normalize_guid(other.device_guid)
        if d1 != d2:
            return False
        if self.input_id != other.input_id:
            return False
        if self._deadzone_center_min != other._deadzone_center_min:
            return False
        if self._deadzone_center_max != other._deadzone_center_max:
            return False
        if self._calibrated_center != other._calibrated_center:
            return False
        if self._calibrated_max != other._calibrated_max:
            return False
        if self._calibrated_min != other._calibrated_min:
            return False
        if self._inverted != other._inverted:
            return False
        return True
        
        
        
            

    @property
    def inverted(self)-> bool:
        return self._inverted
    @inverted.setter
    def inverted(self, value : bool):
        self._inverted = value
        self._update()

    @property
    def threshold_enabled(self) -> bool:
        return self._trigger_threshold_enabled
    @threshold_enabled.setter
    def threshold_enabled(self, value: bool):
        assert isinstance(value, bool)
        self._trigger_threshold_enabled = value

    @property
    def threshold(self) -> float:
        return self._trigger_threshold
    @threshold.setter
    def threshold(self, value: float):
        self._trigger_threshold = value

        

    @property
    def centered(self)-> bool:
        return self._is_centered
    @centered.setter
    def centered(self, value : bool):
        self._is_centered = value
        self._update()

    @property
    def deadzone(self) -> list:
        if self._is_centered:
            return [self._deadzone_min, self._deadzone_center_min, self._deadzone_center_max, self.deadzone_max]
        return [self._deadzone_min, self._deadzone_max]
    
    @deadzone.setter
    def deadzone(self, value : list):
        if len(value) == 2:
            d_start, d_end = value
            self.deadzone_min = d_start
            self.deadzone_max = d_end
        elif len(value) == 4:
            d_start, d_left, d_right, d_end = value
            self.deadzone_min = d_start
            self.deadzone_max = d_end
            self.deadzone_center_min = d_left
            self.deadzone_center_max = d_right
        self._update()
        


    @property
    def deadzone_min(self):
        return self._deadzone_min
    @deadzone_min.setter
    def deadzone_min(self, value):
        if self._deadzone_min != value:
            self._deadzone_min = value + 0.0
            self._update()

    @property
    def deadzone_max(self):
        return self._deadzone_max
    @deadzone_max.setter
    def deadzone_max(self, value):
        if self._deadzone_max:
            self._deadzone_max = value + 0.0
            self._update()

    @property
    def deadzone_center_min(self):
        return self._deadzone_center_min
    @deadzone_center_min.setter
    def deadzone_center_min(self, value):
        if self._deadzone_center_min != value:
            self._deadzone_center_min = value + 0.0
            self._update()

    @property
    def deadzone_center_max(self):
        return self._deadzone_center_max
    @deadzone_center_max.setter
    def deadzone_center_max(self, value):
        if self._deadzone_center_max != value:
            self._deadzone_center_max = value + 0.0       
            self._update()




    @property
    def calibrated_min(self):
        return self._calibrated_min
    @calibrated_min.setter
    def calibrated_min(self, value):
        if self._calibrated_min != value:
            self._calibrated_min = value + 0.0
            self._update()

    @property
    def calibrated_center(self):
        return self._calibrated_center
    @calibrated_center.setter
    def calibrated_center(self, value):
        if self._calibrated_center != value:
            self._calibrated_center = value + 0.0
            self._update()

    @property
    def calibrated_max(self):
            return self._calibrated_max
    @calibrated_max.setter
    def calibrated_max(self, value):
        if self._calibrated_max != value:
            self._calibrated_max = value + 0.0
            self._update()


    def getValue(self, raw_value, normalize = True, filter = False) -> float | tuple:
        ''' gets the deadzoned, calibrated value for the input value -1.0 to +1.0 - if normalized is enabled, expects a dinput range value, if not, expects a -1 to +1 value
        
        :param raw_value: the raw input value to process
        :param normalize: normalizes the raw input to -1 +1 if coming from RAW data
        :param filter: enables axis filtering (also requires configuration options to enable filtering)
        :returns : single float value, or (value, should_process) flag - if the filter is set - the value exceeds the min deviation threshold
        
        '''

        if normalize:
            normalized_value = gremlin.util.scale_to_range(raw_value, source_min = -32768, source_max = 32767)
        else:
            normalized_value = raw_value

        if self.inverted:
            normalized_value = gremlin.util.scale_to_range(normalized_value, invert = self.inverted) # just handle the inversion
        
        value = 0.0

        if self._is_centered:
            # account for center calibration left/right
            value = gremlin.util.axis_calibration(normalized_value, self._calibrated_min, self.calibrated_center, self._calibrated_max)
        else:
            value = gremlin.util.slider_calibration(normalized_value, self._calibrated_min, self._calibrated_max)

        if self._is_centered:
            if value > self.deadzone_center_min and value < self.deadzone_center_max:
                value = 0.0
            elif value <= self.deadzone_center_min:
                # center deadzone set - update the range as it's been reduced
                value = gremlin.util.scale_to_range(value, source_min = self.deadzone_min, source_max = self.deadzone_center_min, target_max = 0)
            elif value >= self.deadzone_center_max:
                value = gremlin.util.scale_to_range(value, source_min = self.deadzone_center_max, source_max = self.deadzone_max, target_min = 0)
        else:
            value = gremlin.util.scale_to_range(value, source_min=self.deadzone_min, source_max=self.deadzone_max)

        value += 0.0 # flip negative zero in python (why?)
            
        if filter:
            return (value, True)
        return value
    

    def from_xml(self, node, data = None, extra_data = None):
        ''' reads data from XML'''

        if not "device-guid" in node.attrib:
            return # no calibration data
        device_guid = node.get("device-guid")
        if not device_guid or device_guid == 'None':
            return # no calibration data
        self.device_guid = parse_guid(device_guid)
        
        input_id = safe_read(node,"input-id", str, "")
        if input_id and input_id.isnumeric():
            self.input_id = int(input_id)
        else:
            self.input_id = input_id
        
        self.inverted = safe_read(node,"inverted",bool, False)
        
        self.centered = safe_read(node,"centered",bool, False)
        self.calibrated_min = safe_read(node,"calibrate-min", float,-1.0)
        
        self.calibrated_max = safe_read(node,"calibrate-max", float, 1.0)
        self.deadzone_min = safe_read(node,"deadzone-min", float, -1.0)
        self.deadzone_max = safe_read(node,"deadzone-max", float, 1.0)
        self.threshold_enabled = safe_read(node,"threshold-enabled", bool, False)
        self.threshold = safe_read(node,"threshold-value", float, 0.005)
        if self.centered:
            self.calibrated_center = safe_read(node,"calibrate-center", float, 0.0)
            self.deadzone_center_min = safe_read(node,"deadzone-center-min", float, 0.0)
            self.deadzone_center_max = safe_read(node,"deadzone-center-max", float, 0.0)
            

    def to_xml(self):

        node = etree.Element("calibration")
        if self.device_guid is None:
            return node

        node.set("device-guid", str(self.device_guid))
        node.set("input-id",safe_format(self.input_id, int))
        node.set("inverted", safe_format(self.inverted, bool))
        node.set("centered", safe_format(self.centered, bool))
        node.set("calibrate-min", safe_format(self.calibrated_min, float))
        node.set("calibrate-max", safe_format(self.calibrated_max, float))
        node.set("deadzone-min", safe_format(self.deadzone_min, float))
        node.set("deadzone-max", safe_format(self.deadzone_max, float))
        node.set("threshold-value", safe_format(self.threshold, float))
        node.set("threshold-enabled", safe_format(self.threshold_enabled, bool))
        if self.centered:
            node.set("calibrate-center", safe_format(self.calibrated_center, float))
            node.set("deadzone-center-min", safe_format(self.deadzone_center_min, float))
            node.set("deadzone-center-max", safe_format(self.deadzone_center_max, float))
        return node
    
    def clone(self):
        ''' duplicates '''
        import copy
        return copy.deepcopy(self)
    

    def _loadLegacy(self):
        ''' loads legacy calibration data '''
        config = gremlin.config.Configuration()
        data = config.get_calibration(self.device_guid, self.input_id)
        v1, v2, v3 = data
        if v1 != -32768 or v2 != 0 or v3 != 32767:
            v1 = gremlin.util.scale_to_range(v1, -32768, 32767)
            v2 = gremlin.util.scale_to_range(v2, -32768, 32767)
            v3 = gremlin.util.scale_to_range(v3, -32768, 32767)
            self.calibrated_min = v1
            self.calibrated_center = v2
            self.calibrated_max = v3

@gremlin.singleton_decorator.SingletonDecorator
class CalibrationManager():
    ''' manages calibration data '''

    def __init__(self):
        
        current_profile_folder = gremlin.shared_state.data_path
        self.global_calibration_file = os.path.join(current_profile_folder,"calibration.xml")

        #elf.local_calibration_file = 
        self.calibration_map = {}
    

    
    @property
    def profile_calibration_file(self) -> str:
        ''' local calibration file name for the profile'''
        profile = gremlin.shared_state.current_profile
        if profile:
            fname = profile.profile_file
            if fname:
                # swap to a .calib file
                return gremlin.util.swap_ext(fname,".calib")
        return None
    
    @property
    def hasProfileCalibration(self) -> bool:
        ''' true if a calibration file for the current profile exists'''
        fname = self.profile_calibration_file
        return fname and os.path.isfile(fname)

    def reload(self):
        ''' reloads the calibration data '''
        self._load()


    def getCalibration(self, device_guid, input_id) -> CalibrationData:
        ''' gets calibration data for a given device/axis '''
        device_guid = gremlin.util.normalize_guid(device_guid)
  

        if not device_guid in self.calibration_map:
            self.calibration_map[device_guid] = {}
        if not input_id in self.calibration_map[device_guid]:
            calibration = CalibrationData()
            calibration.device_guid = device_guid
            calibration.input_id = input_id
            calibration._loadLegacy() # load old data if present
            self.calibration_map[device_guid][input_id] = calibration

        return self.calibration_map[device_guid][input_id]
    
    def saveCalibration(self, calibration : CalibrationData, to_global = True, to_local = False, callback = None):
        ''' saves calibration data '''
        device_guid =  gremlin.util.normalize_guid(calibration.device_guid)
        device = gremlin.joystick_handling.getDevice(device_guid)

        input_id = calibration.input_id
        if not device_guid in self.calibration_map:
            self.calibration_map[device_guid] = {}
        
        self.calibration_map[device_guid][input_id] = calibration
        self._save(to_global, to_local, callback)


    def clearCalibration(self, data, to_global = True, to_local = False ):
        ''' clears a calibration entry '''
        device_guid = data.device_guid
        input_id = data.input_id
        device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self.calibration_map:
            if input_id in self.calibration_map[device_guid]:
                calibration = self.calibration_map[device_guid][input_id]
                calibration.reset()
                del self.calibration_map[device_guid][input_id]

                self._save(to_global, to_local)
                el = gremlin.event_handler.EventListener()
                el.calibration_changed.emit(calibration)
                                                     
    
    def _load(self, device_guid = None, input_id = None):
        ''' loads calibration data

        :param device_guid: id of device to load if a specific data point is needed
        :param input_id: id of the input to load if a specific data point is needed

        if both params are given, the load will only load that device/input combination.
        to load all the data, leave both to None. 
          
        '''
        fname = self.profile_calibration_file
        verbose = gremlin.config.Configuration().verbose_mode_calib

        # build the list of files to load the data from
        f_list = []
        # try local profile first
        fname = self.profile_calibration_file
        if fname is not None and os.path.isfile(fname):
            f_list.append((fname, "local"))
        # global data second
        f_list.append((self.global_calibration_file,"global"))

        device_map = {}

        if device_guid is not None and input_id is not None:
            # specific device/input
            load_specific = True
            xpath = f"//calibration[@device-guid='{device_guid}' and @input-id='{input_id}']"
        else:
            # regular load
            load_specific = False
            xpath = "//calibration"


        for fname, source in f_list:
            if fname and os.path.isfile(fname):
                

                parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
                try:
                    root = etree.parse(fname, parser=parser)

                    nodes = root.xpath(xpath)
                    
                    for node in nodes:
                        data = CalibrationData()
                        found = True
                        data.from_xml(node)
                        device_guid = gremlin.util.normalize_guid(data.device_guid)
                        input_id = data.input_id
                        if not device_guid in device_map:
                            # not seen
                            device_map[device_guid] = {}
                        
                        if not input_id in device_map[device_guid]:
                            if verbose:  
                                device = gremlin.joystick_handling.getDevice(device_guid)    
                                if device:
                                    syslog.info(f"CALIB: loading calibration data for [{device.name}] axis [{device.getAxisName(input_id)}] from {source}")
                                else:
                                    syslog.info(f"CALIB: loading calibration data for unknown [{device_guid}] axis [{input_id}] from {source}")

                            if not device_guid in self.calibration_map:
                                self.calibration_map[device_guid] = {}

                            device_map[device_guid][input_id] = data
                            self.calibration_map[device_guid][input_id] = data

                    if load_specific and found:
                        # data was found, no need to load the other file
                        return True

                except Exception as ex:
                    syslog.error(f"Error loading calibration data: {ex}")
                    return False    


    def _save(self, to_global = True, to_local = False, callback = None):
        gremlin.util.InvokeUiMethod(self._save_ui, to_global, to_local, callback)

    def _save_ui(self, to_global = True, to_local = False, callback = None):

        ''' saves the calibration data 
        
        :param to_global: saves the calibration globally for all profiles when set, when not set, saves to the local profile only
        
        '''
        verbose = gremlin.config.Configuration().verbose_mode_calib
        root = etree.Element("root")
        for device_guid in self.calibration_map:
            device = gremlin.joystick_handling.getDevice(device_guid)
            if device:
                for input_id in self.calibration_map[device_guid]:
                    data : CalibrationData = self.calibration_map[device_guid][input_id]
                    node_comment = etree.Comment(f"{device.name} axis {input_id}")
                    root.append(node_comment)
                    node = data.to_xml()
                    root.append(node)
            else:
                if verbose: syslog.info(f"Device: {device_guid} not found during saving of calibration data")
        
        tree = etree.ElementTree(root)

        f_list = []

        if to_global:
            f_list.append(self.global_calibration_file)
        
        if to_local:
            f_list.append(self.profile_calibration_file)

        for fname in f_list:
            if fname:
                try:
                    if os.path.isfile(fname):
                        os.unlink(fname)
                    tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
                    if verbose: syslog.info(f"Calibration data saved to [{fname}]")
                except Exception as ex:
                    syslog.error(f"Error saving calibration: {ex}")
                    if callback:
                        callback(False)
                
        if callback:
            callback(True)


class CalibrationListenerWidget(QtWidgets.QFrame):
    def __init__(
            self,
            device_guid,
            input_id,
            callback,
            parent=None
        ):
        super().__init__(parent)

        # Disable ui input selection on joystick input
        gremlin.shared_state.push_suspend_highlighting()

        self.device_guid = device_guid
        self.input_id = input_id
        self.callback = callback # called when the dialog closes

        self.calibrationMin = 0
        self.calibrationMax = 0

        # Create and configure the ui overlay
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(
            QtWidgets.QLabel(f"""<center>Move the axis to its extreme positions.<br/><br/>Press a button or click Ok to accept.<br/>.Press Esc abort.</center>""")
        )
        
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setFrameStyle(QtWidgets.QFrame.Plain | QtWidgets.QFrame.Box)
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.DarkGray)
        self.setPalette(palette)

        self.result = False

        ok_widget = gremlin.ui.ui_common.Buttons.getOkWidget(callback = self._accept_ui)
        self.main_layout.addWidget(ok_widget, alignment= QtCore.Qt.AlignmentFlag.AlignCenter)

        # capture the events
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self.joystick_event_handler)
        el.keyboard_event.connect(self._kb_event_cb)

        # capture the esc key

    def _kb_event_cb(self, event):
        ''' capture a key - esc'''
        gremlin.util.InvokeUiMethod(self._kb_event_ui, event)




    def accept(self):
        gremlin.util.InvokeUiMethod(self._accept_ui)


    def _accept_ui(self):
        self.result = True
        self.close()

    def reject(self):
        gremlin.util.InvokeUiMethod(self._reject_ui)

    def _reject_ui(self):
        self.result = False
        self.close()


    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        ''' called when dialog is closing '''
        gremlin.shared_state.pop_suspend_highlighting()
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self.joystick_event_handler)
        el.keyboard_event.disconnect(self._kb_event_cb)
        if self.callback:
            self.callback()
        return super().closeEvent(event)
    
    def _kb_event_ui(self, event):
        from gremlin.keyboard import key_from_code, key_from_name
        key = key_from_code(
                event.identifier[0],
                event.identifier[1]
        )
        if event.is_pressed and key == key_from_name("esc"):   
            self.reject()
    
    def joystick_event_handler(self, event):
        
        if event.device_guid != self.device_guid:
            return
        if not event.is_axis:
            # see if a button was clicked
            if not event.is_pressed:
                return
            if event.event_type == InputType.JoystickButton:
                self.accept()
            if event.event_type == InputType.JoystickHat:
                if event.value != (0,0):
                    # not centered
                    self.accept()
            return
        
        if event.identifier != self.input_id:
            return
        value = event.value
        if value < self.calibrationMin:
            self.calibrationMin = value
        if value > self.calibrationMax:
            self.calibrationMax = value

         

class CalibrationDialogEx(QtWidgets.QDialog):
    ''' gremlinex single input calibration window '''


    def __init__(self, input_item, parent = None):
        '''
        Setup single real hardware axis calibration data

        Arguments:
            device_guid -- device guid
            input_id -- axis number
        
        '''
        #super().__init__(self.__class__.__name__, parent = parent)
        super().__init__(parent = parent)

        from gremlin.curve_handler import DeadzoneWidget

        self._lock = False
        self._calibrating = False # true if calibrating 

        config = gremlin.config.Configuration()
        self._auto_calibrate = config.auto_calibrate

        self.setModal(True)
        self.input_item = input_item
        input_type = input_item.get_input_type()
        if input_type != InputType.JoystickAxis:
            self.close()
            return
        
        device_guid = input_item.device_guid
        input_id = input_item.input_id
        self.hook_id = gremlin.util.normalize_guid(input_item.id)
        self.calibrated_on_entry = input_item.calibration.hasData # true if the item has calibration data on entry
        self._closing = False 
        self.mgr : CalibrationManager = CalibrationManager()

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.device = gremlin.joystick_handling.device_info_from_guid(device_guid)
        self.source_data : CalibrationData = self.mgr.getCalibration(device_guid, input_id)
        self.action_data = CalibrationData(self.source_data)
        self.cloned_action_data = self.action_data.clone()
        self.action_data.device_guid = device_guid
        self.action_data.input_id = input_id

        

        self.setWindowTitle("Input Axis Calibration")
        info = gremlin.joystick_handling.device_info_from_guid(device_guid)
        axis_id = info.getAxisLinearId(input_id)       
        self.main_layout.addWidget(QtWidgets.QLabel(f"{info.name} Axis: {info.axis_names[axis_id-1]}/L{axis_id}"))
        self.main_layout.addWidget(QtWidgets.QLabel("Note: Calibration options will apply to the computed input data value before any other parts of GremlinEx process the input."))

        # device options
        self._options_container_repeater_widget = QtWidgets.QWidget()
        self._options_container_repeater_layout = QtWidgets.QHBoxLayout(self._options_container_repeater_widget)

        self._centered_widget = QtWidgets.QCheckBox("Centered axis")
        self._centered_widget.setToolTip("Enabled if the input calibration should take into account a center location, usually the case for centered axes, and disabled for a slider.")
        self._centered_widget.setChecked(self.action_data.centered)
        self._centered_widget.clicked.connect(self._centered_changed)

        self._inverted_widget = QtWidgets.QCheckBox("Inverted")
        self._inverted_widget.setToolTip("If enabled, inverts the input.")
        self._inverted_widget.setChecked(self.action_data.inverted)
        self._inverted_widget.clicked.connect(self._inverted_changed)


        self._calibrate_widget = QtWidgets.QPushButton("Calibrate",)
        self._calibrate_widget.setToolTip("Brings up the calibration dialog to calibrate the axis to its bounds.")
        self._calibrate_widget.clicked.connect(self._start_calibration)

        self._bounds_center_widget = QtWidgets.QPushButton("Bounds Center",)
        self._bounds_center_widget.setToolTip("Sets the calibration endpoints to center. After pressing this, move the input axis to its maximum travel positions to automatically set the calibration data.")
        self._bounds_center_widget.clicked.connect(self._bounds_center)

        self._auto_calibrate_widget = gremlin.ui.ui_common.QDataCheckbox(
            label = "Auto Calibrate",
            value = self._auto_calibrate,
            tooltip = "If set, the axis will auto-calibrate to min/max travel as needed as the input is moved.",
            callback = self._auto_calibrate_changed,
        )



        self._threshold_enabled_widget = QtWidgets.QCheckBox("Enable threshold")
        self._threshold_enabled_widget.setToolTip("If set, the input movement will need to exceed the specified delta to trigger an axis event")
        self._threshold_enabled_widget.setChecked(self.action_data.threshold_enabled)
        
        self._threshold_enabled_widget.clicked.connect(self._threshold_enabled_changed)

        self._threshold_value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._threshold_value_widget.setMinimum(0)
        self._threshold_value_widget.setValue(self.action_data.threshold)
        self._threshold_value_widget.valueChanged.connect(self._threshold_value_changed)
        self._threshold_value_widget.setDecimals(4)
        self._threshold_value_widget.setEnabled(self.action_data.threshold_enabled)


        self._center_widget = QtWidgets.QPushButton("Set Center")
        self._center_widget.setToolTip("Sets the center calibration at the current input value.  This is helpful for inputs that do not report the midpoint value while in their center detent or to shift it.")
        self._center_widget.clicked.connect(self._set_center_calibration)

        self._options_container_repeater_layout.addWidget(self._centered_widget)
        self._options_container_repeater_layout.addWidget(self._inverted_widget)
        self._options_container_repeater_layout.addWidget(self._center_widget)
        self._options_container_repeater_layout.addWidget(self._calibrate_widget)
        self._options_container_repeater_layout.addWidget(self._bounds_center_widget)
        
        #self._options_container_repeater_layout.addWidget(self._reset_widget)
        self._options_container_repeater_layout.addWidget(self._auto_calibrate_widget)


        widget = gremlin.ui.ui_common.getHContainer([self._threshold_enabled_widget, self._threshold_value_widget], widget_only = True)

        self._options_container_repeater_layout.addWidget(widget)

        self._options_container_repeater_layout.addStretch()


        # raw axis input repeater
        self._raw_container_repeater_widget = QtWidgets.QWidget()
        self._raw_container_repeater_layout = QtWidgets.QHBoxLayout(self._raw_container_repeater_widget)

        # calibrated axis repeater
        self._calibrated_container_repeater_widget = QtWidgets.QWidget()
        self._calibrated_container_repeater_layout = QtWidgets.QHBoxLayout(self._calibrated_container_repeater_widget)

        self._input_slider_widget = QSliderWidget() # slider showing the input axis
        self._input_slider_widget.valueChanged.connect(self._slider_changed)
        self._input_slider_widget.setToolTip("Calibration slider.<br>The endpoints represent the minimum/maxium values possible for this axis, and the position of the center detent for centered devices.<br>Sliders will not have a center detent.<br>Move the input to the maximum travel positions to set the enpoints.")

        self._calibrated_slider_widget = QSliderWidget() # slider showing the calibrated axis
        self._calibrated_slider_widget.setReadOnly(True)
        self._calibrated_slider_widget.setMarkerVisible(False)
        self._calibrated_slider_widget.desired_height = 20
        self._calibrated_slider_widget.handleColor = QColor("#d6ae3e")
        self._calibrated_slider_widget.setToolTip("Calibrated output value")
        

        self._raw_value_widget = ui_common.QFloatLineEdit()
        self._raw_value_widget.setReadOnly(True)

        self._calibrated_value_widget = ui_common.QFloatLineEdit()
        self._calibrated_value_widget.setReadOnly(True)
        self._calibrated_value_widget.setToolTip("Computed output value based on the current calibration settings.")

        self._calibrated_min_widget = ui_common.QFloatLineEdit()
        self._calibrated_min_widget.valueChanged.connect(self._calibrated_min_changed)
        self._calibrated_min_widget.setToolTip("Minimum value of the axis possible input travel.<br>Move the input to the minimum travel position to set this value after pressing the calibrate button.<br>Can also be set manually.")
        

        self._calibrated_max_widget = ui_common.QFloatLineEdit()
        self._calibrated_max_widget.valueChanged.connect(self._calibrated_max_changed)
        self._calibrated_max_widget.setToolTip("Maximum value of the axis possible input travel.<br>Move the input to the maximum travel position to set this value after pressing the calibrate button.<br>Can also be set manually.")
        

        self._calibrated_center_widget = ui_common.QFloatLineEdit()
        self._calibrated_center_widget.valueChanged.connect(self._calibrated_center_changed)
        self._calibrated_center_widget.setToolTip("For centered inputs, this is the position of the input when it is at the center detent or midpoint of travel.<br>Press the center button to set this value when the axis is in the center position.<br>can also be set manually.")
        

        widgets = [
            QtWidgets.QLabel("Center:"),
            self._calibrated_center_widget
        ]
        self._container_center_widget, _ = ui_common.getHContainer(widgets)

        widgets = [
            QtWidgets.QLabel("Min:"),
            self._calibrated_min_widget,
            "||",
            self._container_center_widget,
            "||",
            QtWidgets.QLabel("Max:"),
            self._calibrated_max_widget
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)


        self._raw_container_repeater_layout.addWidget(QtWidgets.QLabel("Input:"))
        self._raw_container_repeater_layout.addWidget(self._raw_value_widget)
        self._raw_container_repeater_layout.addWidget(QtWidgets.QLabel("Calibrated:"))
        self._raw_container_repeater_layout.addWidget(self._calibrated_value_widget)
        self._raw_container_repeater_layout.addStretch()

        

        self._deadzone_widget = DeadzoneWidget(self.action_data)
        self._deadzone_widget.isCentered = self.action_data.centered
        self._deadzone_widget.changed.connect(self._deadzone_changed)

        self._status_widget = gremlin.ui.ui_common.QTimedLabel()

   
        save_global_widget = gremlin.ui.ui_common.QDataPushButton("Save (Global)",
                                                                  callback = self._handle_save_global,
                                                                  tooltip = "Saves the calibration data to the global default. Note: Profiles that have profile specific calibration data will use that instead. This will close the dialog after saving.")
        
        save_profile_widget = gremlin.ui.ui_common.QDataPushButton("Save (Profile)",
                                                                  callback = self._handle_save_profile,
                                                                  tooltip = "Saves the calibration data to the profile.  The profile will use this data instead of the global calibration if it exists.  This will close the dialog after saving.",
                                                                  enabled = gremlin.shared_state.current_profile.profile_file is not None)
        

        
        delete_calibration_widget = gremlin.ui.ui_common.QDataPushButton("Clear/Reset",
                                                                        callback = self._reset_calibration,
                                                                        tooltip="Clears and resets the calibration data for this axis",
                                                                        )



        close_widget = gremlin.ui.ui_common.QDataPushButton("Close",callback = self._handle_close)
        
        widgets = [
            save_global_widget,
            save_profile_widget,
            delete_calibration_widget,
            close_widget
        ]

        button_container = gremlin.ui.ui_common.getHContainer(widgets, left_stretch=True, widget_only=True)


        self.main_layout.addWidget(self._options_container_repeater_widget)
        self.main_layout.addWidget(self._input_slider_widget)
        self.main_layout.addWidget(self._calibrated_slider_widget)
        self.main_layout.addWidget(widget)
        self.main_layout.addWidget(self._raw_container_repeater_widget)
        self.main_layout.addWidget(self._calibrated_container_repeater_widget)
        

        self.main_layout.addWidget(self._deadzone_widget)
        self.main_layout.addWidget(button_container)
        self.main_layout.addWidget(self._status_widget)
        self.main_layout.addStretch()


        jep = gremlin.event_handler.JoystickEventProcessor()
        description = f"calibration axis position device: [{gremlin.joystick_handling.getDeviceName(self.action_data.device_guid)}] input id: [{self.action_data.input_id}]"
        jep.registerCallback(self.hook_id,
                             self._handle_joystick_event_ui,
                            device_guid = self.action_data.device_guid,
                            input_type = InputType.JoystickAxis,
                            input_id = self.action_data.input_id,
                            ui_only = True,
                            description = description)

        # initial value
        self._update_ui()
    
    def _auto_calibrate_changed(self, checked : bool):
        config = gremlin.config.Configuration()
        config.auto_calibrate = checked
        self._auto_calibrate = checked
        

    def _handle_close(self, widget):
        self.close()

    def _handle_joystick_event_ui(self, event, values):
        ''' handles a joystick axis event '''
        if self._lock:
            return
        if self._calibrating:
            # ignore while calibrating
            return
        
        raw_value = event.value
        if self._auto_calibrate:
            changed = False
            if raw_value < self.action_data.calibrated_min:
                self.action_data.calibrated_min = raw_value
                changed = True
            if raw_value > self.action_data.calibrated_max:
                self.action_data.calibrated_max = raw_value
                changed = True
            if changed:
                self.action_data._update()
                self._update_ui()
            
        calibrated_value = self.action_data.getValue(raw_value, normalize = False)
        self._update_axis_widget_ui(
            raw_value,
            calibrated_value,
            self.action_data.calibrated_min,
            self.action_data.calibrated_center if self.action_data.centered else None,
            self.action_data.calibrated_max     
        )
        


    @QtCore.Slot()
    def _handle_save_global(self, widget):
        ''' saves the global calibration data and close '''
        self._lock = True
        self.mgr.saveCalibration(self.action_data, to_global = True, to_local = False, callback = self._handle_global_result) 
        self.action_data = self.source_data

    def _handle_global_result(self, result : bool):
        try:
            if result:
                self.source_data.copyFrom(self.action_data)
                self._status_widget.setText("Saved to global calibration data")
                self.close()
        finally:
            self._lock = False

    @QtCore.Slot()
    def _handle_save_profile(self, widget):
        ''' saves the calibration to the current profile and close '''
        self._lock = True
        self.mgr.saveCalibration(self.action_data, to_global = False, to_local = True, callback = self._handle_local_result)
        self.action_data = self.source_data

    def _handle_local_result(self, result : bool):

        try:     
            if result:
                self.source_data.copyFrom(self.action_data)
                self._status_widget.setText("Saved to profile calibration data")
                self.close()
        finally:
            self._lock = False


    def closeEvent(self, event):
        ''' save data on dialog close '''

        try:
            # should close?
            if self.source_data != self.action_data:
                # changes not saved
                icon = gremlin.ui.ui_common.Icons.warningIcon()
                pixmap = icon.pixmap(48)
                msgbox = QtWidgets.QMessageBox(parent = self)
                msgbox.setWindowTitle("Notice")
                msgbox.setIconPixmap(pixmap)
                msgbox.setInformativeText("Save changes?")
                msgbox.setText("Calibration data has changed and is not saved.")
                msgbox.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
                result = msgbox.exec()
                

                if result == QtWidgets.QMessageBox.StandardButton.Yes: # QtWidgets.QDialog.Accepted:
                    event.accept()
                else:
                    event.ignore()
                    return
                
            self._closing = True

            jep = gremlin.event_handler.JoystickEventProcessor()
            
            jep.unregisterCallback(self.hook_id)

            self._input_slider_widget.valueChanged.disconnect(self._slider_changed)
            self._deadzone_widget.changed.disconnect(self._deadzone_changed)

            self._calibrated_min_widget.valueChanged.disconnect(self._calibrated_min_changed)
            self._calibrated_max_widget.valueChanged.disconnect(self._calibrated_max_changed)
            self._calibrated_center_widget.valueChanged.disconnect(self._calibrated_center_changed)

            gremlin.util.clear_layout(self.main_layout)

        finally:
            # update input icons to reflect changes, if any
            el = gremlin.event_handler.EventListener()
            el.update_input_icons.emit()
        



    @QtCore.Slot()
    def _slider_changed(self, handle, value):
        ''' slider changed '''

        
        syslog.info("slider changed")
        match handle:
            case 0:
                if value >= self.action_data.calibrated_max:
                    value = self.action_data.calibrated_max - 0.001
                self.action_data.calibrated_min = value
            case 1:
                if self.action_data.centered:
                    self.action_data.calibrated_center = value
                else:
                    if value <= self.action_data.calibrated_min:
                        value = self.action_data.calibrated_min + 0.001
                    self.action_data.calibrated_max = value    
            case 2:
                if value <= self.action_data.calibrated_min:
                    value = self.action_data.calibrated_min + 0.001
                self.action_data.calibrated_max = value

        gremlin.util.InvokeUiMethod(self._update_ui) # ensure on UI thread

    @QtCore.Slot()
    def _reset_calibration(self, widget):
        ''' reset calibration for the axis '''
        self.action_data.reset()
        value = self.action_data.hasData
        self._update_ui()
        self._status_widget.setText("Reset")
        gremlin.ui.ui_common.MessageBoxInfo(prompt = "Calibration reset.", informative_text = "Remember to save the data.", parent = self)        

    @QtCore.Slot()
    def _set_center_calibration(self):
        ''' reset calibration for the axis '''
        raw_value = gremlin.joystick_handling.get_axis(self.action_data.device_guid, self.action_data.input_id)
        self.action_data.calibrated_center = raw_value
        self._update_ui()

    @QtCore.Slot()
    def _start_calibration(self):
        ''' resets the calibration data enpoints'''
        if self._calibrating:
            return
        self._calibrating = True
        # display a dialog box 

        self._listen_ui()

    @QtCore.Slot()
    def _bounds_center(self):
        ''' sets the calibration bounds to center to reset the auto calibration '''
        self.action_data.calibrated_max = 0
        self.action_data.calibrated_min = 0
        self.action_data._update()
        self._update_ui()


    def _listen_ui(self, current_port_only = False):
        ''' listens to an inbound OSC message - runs on UI thread'''

        

        gremlin.util.assert_ui_thread()
        config = gremlin.config.Configuration()
        device_guid = self.action_data.device_guid
        input_type = InputType.JoystickAxis
        input_id = self.action_data.input_id
        self.calibrate_dialog = CalibrationListenerWidget(device_guid = device_guid, input_id = input_id, callback = self._capture_calibration)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.calibrate_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        self.calibrate_dialog.show()

    def _capture_calibration(self):
        result = self.calibrate_dialog.result
        if result:
            # accept calibration data 
            self.action_data._calibrated_max = self.calibrate_dialog.calibrationMax
            self.action_data._calibrated_min = self.calibrate_dialog.calibrationMin

            self.action_data._update()
            self._update_ui()

        self._calibrating = False


    @QtCore.Slot(bool)
    def _threshold_enabled_changed(self, checked : bool):
        self.action_data.threshold_enabled = checked
        self._threshold_value_widget.setEnabled(checked)

    @QtCore.Slot()
    def _threshold_value_changed(self):
        value = self._threshold_value_widget.value()
        self.action_data.threshold = value

    @QtCore.Slot()
    def _calibrated_min_changed(self):
        value = self._calibrated_min_widget.value()
        if value >= self.action_data._calibrated_max:
            # ensure min and max are not the same
            value = self.action_data._calibrated_max - 0.001
        self.action_data._calibrated_min = value
        self._update_ui()

    @QtCore.Slot()
    def _calibrated_max_changed(self):
        value = self._calibrated_max_widget.value()
        if value <= self.action_data._calibrated_min:
            # ensure min and max are not the same
            value = self.action_data._calibrated_min + 0.001
        self.action_data._calibrated_max = value
        self._update_ui()

    @QtCore.Slot()
    def _calibrated_center_changed(self):
        value = self._calibrated_center_widget.value()
        self.action_data._calibrated_center = value
        self._update_ui()
        

    @QtCore.Slot()
    def _deadzone_changed(self):
        ''' deadzone widget changed '''
        values = self._deadzone_widget.values()
        self.action_data.deadzone = values


    @QtCore.Slot(bool)
    def _centered_changed(self, checked : bool):
        self.action_data.centered = checked
        self._update_ui()


    @QtCore.Slot(bool)
    def _inverted_changed(self, checked : bool):
        self.action_data.inverted = checked
        self._update_ui()

    def _getCalibratedValue(self, value : float):
        return self.action_data.getValue(value)
    
  


    def _update_ui(self):
        ''' updates the data  '''
        if self._closing:
            return
        if self._lock:
            return
        is_centered = self.action_data.centered
        auto_calibrate = self._auto_calibrate_widget.isChecked()

        with QtCore.QSignalBlocker(self._inverted_widget):
            self._inverted_widget.setChecked(self.action_data.inverted)

        self._deadzone_widget.isCentered = is_centered
        self._container_center_widget.setVisible(is_centered)
        self._calibrated_center_widget.setVisible(is_centered)

        raw_value = gremlin.joystick_handling.get_axis(self.action_data.device_guid, self.action_data.input_id) # raw value from dinput
        self._raw_value_widget.setValue(raw_value)

        # calibration mode = push the calibration to min/max
        if auto_calibrate:
            if raw_value < self.action_data.calibrated_min:
                self.action_data.calibrated_min = raw_value
            if raw_value > self.action_data.calibrated_max:
                self.action_data.calibrated_max = raw_value



        calibrated_value = self.action_data.getValue(raw_value, normalize = False)

        with QtCore.QSignalBlocker(self._calibrated_min_widget):
            self._calibrated_min_widget.setValue(self.action_data.calibrated_min)
        with QtCore.QSignalBlocker(self._calibrated_max_widget):
            self._calibrated_max_widget.setValue(self.action_data.calibrated_max)
        with QtCore.QSignalBlocker(self._calibrated_center_widget):
            self._calibrated_center_widget.setValue(self.action_data.calibrated_center)

        with QtCore.QSignalBlocker(self._calibrated_value_widget):
            self._calibrated_value_widget.setValue(calibrated_value)

        with QtCore.QSignalBlocker(self._deadzone_widget):
            self._deadzone_widget.isCentered = is_centered
            self._deadzone_widget.setValues(self.action_data.deadzone)
            

        self._update_axis_widget_ui(raw_value,
                                    calibrated_value,
                                    self.action_data.calibrated_min,
                                    self.action_data.calibrated_center if is_centered else None,
                                    self.action_data.calibrated_max)     
        
    def _update_axis_widget(self, raw_value : float, calibrated_value : float, min_value : float, center_value : float, max_value : float): 
        gremlin.util.InvokeUiMethod(self._update_axis_widget_ui, raw_value, calibrated_value, min_value, center_value, max_value)      

    def _update_axis_widget_ui(self, raw_value : float, calibrated_value : float, min_value : float, center_value : float, max_value : float):
        if Shiboken.isValid(self._input_slider_widget) and Shiboken.isValid(self._calibrated_slider_widget):
            self._input_slider_widget.setValue([min_value, center_value, max_value])
            self._input_slider_widget.setMarkerValue(raw_value)
            self._calibrated_slider_widget.setValue(calibrated_value)

                


_calibration_manager = CalibrationManager()