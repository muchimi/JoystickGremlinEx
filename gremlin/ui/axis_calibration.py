# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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
from PySide6 import QtWidgets, QtCore
import gremlin
import gremlin.config
import gremlin.joystick_handling
import gremlin.util
from gremlin.util import parse_guid, safe_read, safe_format
from . import ui_common
from gremlin.input_types import InputType
import gremlin.ui.ui_common
import gremlin.event_handler
import gremlin.shared_state
from gremlin.util import axis_calibration, create_calibration_function
from gremlin.ui.qsliderwidget import QSliderWidget
from PySide6.QtGui import QColor
from lxml import etree
import os
import logging
import gremlin.singleton_decorator

syslog = logging.getLogger("system♂")

class CalibrationUi(ui_common.BaseDialogUi):

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
        self.device_dropdown = gremlin.ui.ui_common.QComboBox()
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
                self.devices[self.current_selection_id].axis_map,
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
    def __init__(self):
        self.device_guid = None # axis device guid this data applies to
        self.input_id = None # axis input id this data applies to
        self._is_centered = True # true if the axis is centered (has a center calibration value)
        self.reset()
        

    def reset(self):
        ''' resets calibration data to defaults '''
        # do not reset center option
        self._calibrated_min = -1.0
        self._calibrated_max = 1.0
        self._calibrated_center = 0.0 # used only if the stick is centered
        self._deadzone_min = -1.0
        self._deadzone_max = 1.0
        self._deadzone_center_min = 0.0 # deadzone center left
        self._deadzone_center_max = 0.0 # deadzone center right
        self._inverted = False # true if inverted
        self._has_data = False # true if the calibration is non default (modifies the output value)
        
        

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
        return self._has_data
        
    
    def _update(self):
        ''' updates data flag '''
        self._has_data = not self._is_centered or \
            self._inverted or \
            self._calibrated_min != -1.0 or \
            self._calibrated_max != 1.0 or \
            self.calibrated_center != 0.0 or \
            self._deadzone_min != -1.0 or \
            self._deadzone_max  != 1.0 or \
            self._deadzone_center_min != 0.0 or \
            self._deadzone_center_max != 0.0 
        
        # let the UI know the data changed
        el = gremlin.event_handler.EventListener()
        el.calibration_changed.emit(self)

    def compare(self, other : CalibrationData) -> bool:
        ''' compares two calibration objects to see if they map to the same object '''
        if other is None:
            return False
        return self.device_guid == other.device_guid and self.input_id == other.input_id
            

    @property
    def inverted(self)-> bool:
        return self._inverted
    @inverted.setter
    def inverted(self, value : bool):
        self._inverted = value
        self._update()

        

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


    def getValue(self, raw_value, normalize = True):
        ''' gets the deadzoned, calibrated value for the input value -1.0 to +1.0 - if normalized is enabled, expects a dinput range value, if not, expects a -1 to +1 value'''
        if normalize:
            normalized_value = gremlin.util.scale_to_range(raw_value, source_min = -32768, source_max = 32767, invert = self.inverted)
        elif self.inverted:
            normalized_value = gremlin.util.scale_to_range(raw_value, invert = self.inverted) # just handle the inversion
        else:
            normalized_value = raw_value
        if self._is_centered:
            # account for center calibration left/right
            value = gremlin.util.axis_calibration(normalized_value, self._calibrated_min, self.calibrated_center, self._calibrated_max)
        
        else:
            value = gremlin.util.slider_calibration(normalized_value, self._calibrated_min, self._calibrated_max)

        # apply deadzone data
        if value < self.deadzone_min:
            value = -1.0
        elif value > self.deadzone_max:
            value = 1.0
        if self._is_centered:
            if value > self.deadzone_center_min and value < self.deadzone_center_max:
                value = 0.0
            elif value <= self.deadzone_center_min:
                # center deadzone set - update the range as it's been reduced
                value = gremlin.util.scale_to_range(value, source_min = self.deadzone_min, source_max = self.deadzone_center_min, target_max = 0)
            elif value >= self.deadzone_center_max:
                value = gremlin.util.scale_to_range(value, source_min = self.deadzone_center_max, source_max = self.deadzone_max, target_min = 0)
            
            


        return value + 0.0

        
    

    def from_xml(self, node):
        ''' reads data from XML'''

        if not "device-guid" in node.attrib:
            return # no calibration data
        device_guid = node.get("device-guid")
        if not device_guid or device_guid == 'None':
            return # no calibration data
        self.device_guid = parse_guid(device_guid)
        self.input_id = safe_read(node,"input-id", int)
        self.inverted = safe_read(node,"inverted",bool, False)
        
        self.centered = safe_read(node,"centered",bool)
        self.calibrated_min = safe_read(node,"calibrate-min", float)
        
        self.calibrated_max = safe_read(node,"calibrate-max", float)
        self.deadzone_min = safe_read(node,"deadzone-min", float)
        self.deadzone_max = safe_read(node,"deadzone-max", float)
        if self.centered:
            self.calibrated_center = safe_read(node,"calibrate-center", float)
            self.deadzone_center_min = safe_read(node,"deadzone-center-min", float)
            self.deadzone_center_max = safe_read(node,"deadzone-center-max", float)
            

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
        current_profile_folder = gremlin.util.userprofile_path().lower()
        self.calibration_file = os.path.join(current_profile_folder,"calibration.xml")
        self.calibration_map = {}
        self._load()


    def getCalibration(self, device_guid, input_id) -> CalibrationData:
        ''' gets calibration data for a given device/axis '''
        if not device_guid in self.calibration_map:
            self.calibration_map[device_guid] = {}
        if not input_id in self.calibration_map[device_guid]:
            calibration = CalibrationData()
            calibration.device_guid = device_guid
            calibration.input_id = input_id
            calibration._loadLegacy() # load old data if present
            self.calibration_map[device_guid][input_id] = calibration

        return self.calibration_map[device_guid][input_id]
    
    def saveCalibration(self, calibration : CalibrationData):
        device_guid = calibration.device_guid
        input_id = calibration.input_id
        if not device_guid in self.calibration_map:
            self.calibration_map[device_guid] = {}
        
        self.calibration_map[device_guid][input_id] = calibration
        self._save()



            
    

    def _load(self):
        ''' loads calibration data '''
        if os.path.isfile(self.calibration_file):
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            try:
                tree = etree.parse(self.calibration_file, parser=parser)

                nodes = tree.findall(f".//calibration")
                for node in nodes:
                    data = CalibrationData()
                    data.from_xml(node)
                    device_guid = data.device_guid
                    input_id = data.input_id

                    if not device_guid in self.calibration_map:
                        self.calibration_map[device_guid] = {}
                    self.calibration_map[device_guid][input_id] = data

            except Exception as ex:
                syslog.error(f"Error loading calibration data: {ex}")
                return False    
            
    def _save(self):
        
            root = etree.Element("root")
            for device_guid in self.calibration_map.keys():
                for input_id in self.calibration_map[device_guid]:
                    data = self.calibration_map[device_guid][input_id]
                    node = data.to_xml()
                    root.append(node)

            try:
                tree = etree.ElementTree(root)
                tree.write(self.calibration_file, pretty_print=True,xml_declaration=True,encoding="utf-8")
                syslog.info(f"Calibration data saved.")
            except Exception as ex:
                syslog.error(f"Error saving calibration: {ex}")


class CalibrationDialogEx(gremlin.ui.ui_common.QRememberDialog):
    ''' gremlinex single input calibration window '''
    def __init__(self, device_guid, input_id, parent = None):
        '''
        Setup single real hardware axis calibration data

        Arguments:
            device_guid -- device guid
            input_id -- axis number
        
        '''
        super().__init__(self.__class__.__name__, parent)

        from gremlin.curve_handler import DeadzoneWidget

        self.setModal(True)
        
        

        self.mgr : CalibrationManager = CalibrationManager()

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.device = gremlin.joystick_handling.device_info_from_guid(device_guid)
        self.action_data = self.mgr.getCalibration(device_guid, input_id)
        self.cloned_action_data = self.action_data.clone()
        self.action_data.device_guid = device_guid
        self.action_data.input_id = input_id
        

        self.setWindowTitle("Input Axis Calibration")
        info = gremlin.joystick_handling.device_info_from_guid(device_guid)
        
        self.main_layout.addWidget(QtWidgets.QLabel(f"{info.name} Axis: {info.axis_names[input_id-1]}"))
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

        self._reset_widget = QtWidgets.QPushButton("Reset")
        self._reset_widget.setToolTip("Resets the calibration information to default and removes any filtering.")
        self._reset_widget.clicked.connect(self._reset_calibration)

        self._calibrate_widget = QtWidgets.QPushButton("Calibrate")
        self._calibrate_widget.setToolTip("Sets the calibration endpoints to center. After pressing this, move the input axis to its maximum travel positions to automatically set the calibration data.")
        self._calibrate_widget.clicked.connect(self._start_calibration)

        self._auto_calibrate_widget = QtWidgets.QCheckBox("Auto Calibrate")
        self._auto_calibrate_widget.setChecked(True)
        self._auto_calibrate_widget.clicked.connect(self._update)


        self._center_widget = QtWidgets.QPushButton("Set Center")
        self._center_widget.setToolTip("Sets the center calibration at the current input value.  This is helpful for inputs that do not report the midpoint value while in their center detent or to shift it.")
        self._center_widget.clicked.connect(self._set_center_calibration)

        self._options_container_repeater_layout.addWidget(self._centered_widget)
        self._options_container_repeater_layout.addWidget(self._inverted_widget)
        self._options_container_repeater_layout.addWidget(self._center_widget)
        self._options_container_repeater_layout.addWidget(self._calibrate_widget)
        self._options_container_repeater_layout.addWidget(self._reset_widget)
        self._options_container_repeater_layout.addWidget(self._auto_calibrate_widget)

        self._options_container_repeater_layout.addStretch()


        # raw axis input repeater
        self._raw_container_repeater_widget = QtWidgets.QWidget()
        self._raw_container_repeater_layout = QtWidgets.QHBoxLayout(self._raw_container_repeater_widget)

        # calibrated axis repeater
        self._calibrated_container_repeater_widget = QtWidgets.QWidget()
        self._calibrated_container_repeater_layout = QtWidgets.QHBoxLayout(self._calibrated_container_repeater_widget)

        self._slider = QSliderWidget()
        self._slider.valueChanged.connect(self._slider_changed)
        self._slider.setToolTip("Calibration slider.<br>The endpoints represent the minimum/maxium values possible for this axis, and the position of the center detent for centered devices.<br>Sliders will not have a center detent.<br>Move the input to the maximum travel positions to set the enpoints.")

        self._repeater = QSliderWidget()
        self._repeater.setReadOnly(True)
        self._repeater.setMarkerVisible(False)
        self._repeater.desired_height = 20
        self._repeater.handleColor = QColor("#d6ae3e")
        self._repeater.setToolTip("Calibrated output value")
        

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
        

        self._calibration_container_widget = QtWidgets.QWidget()
        self._calibration_container_layout = QtWidgets.QGridLayout(self._calibration_container_widget)



        self._calibration_container_layout.addWidget(QtWidgets.QLabel("Min:"),0,0)
        self._calibration_container_layout.addWidget(self._calibrated_min_widget, 0,1)
        self._center_label = QtWidgets.QLabel("Center:")
        self._calibration_container_layout.addWidget(self._center_label,0,2)
        self._calibration_container_layout.addWidget(self._calibrated_center_widget, 0,3)
        self._calibration_container_layout.addWidget(QtWidgets.QLabel("Max:"),0,4)
        self._calibration_container_layout.addWidget(self._calibrated_max_widget, 0,5)
        

        self._raw_container_repeater_layout.addWidget(QtWidgets.QLabel("Input:"))
        self._raw_container_repeater_layout.addWidget(self._raw_value_widget)
        self._raw_container_repeater_layout.addWidget(QtWidgets.QLabel("Calibrated:"))
        self._raw_container_repeater_layout.addWidget(self._calibrated_value_widget)
        self._raw_container_repeater_layout.addStretch()

        

        self._deadzone_widget = DeadzoneWidget(self.action_data)
        self._deadzone_widget.isCentered = self.action_data.centered
        self._deadzone_widget.changed.connect(self._deadzone_changed)


        self.main_layout.addWidget(self._options_container_repeater_widget)
        self.main_layout.addWidget(self._slider)
        self.main_layout.addWidget(self._repeater)
        self.main_layout.addWidget(self._calibration_container_widget)
        self.main_layout.addWidget(self._raw_container_repeater_widget)
        self.main_layout.addWidget(self._calibrated_container_repeater_widget)
        

        self.main_layout.addWidget(self._deadzone_widget)
        self.main_layout.addStretch()

        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_handler)

        self.setResizable(False)

        # initial value
        self._update()

    def closeEvent(self, event):
        ''' save data on dialog close '''
        if not os.path.isfile(self.mgr.calibration_file):
            # never saved
            self.mgr.saveCalibration(self.action_data)
        else:
            is_changed = self.action_data != self.cloned_action_data
            if is_changed:
                self.mgr.saveCalibration(self.action_data)
        return super().closeEvent(event)




    @QtCore.Slot()
    def _slider_changed(self, handle, value):
        ''' slider changed '''

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
        self._update()

    @QtCore.Slot()
    def _reset_calibration(self):
        ''' reset calibration for the axis '''
        self.action_data.reset()
        self._update()

    @QtCore.Slot()
    def _set_center_calibration(self):
        ''' reset calibration for the axis '''
        raw_value = gremlin.joystick_handling.get_axis(self.action_data.device_guid, self.action_data.input_id)
        self.action_data.calibrated_center = raw_value
        self._update()

    @QtCore.Slot()
    def _start_calibration(self):
        ''' resets the calibration data enpoints'''
        self.action_data._calibrated_min = 0
        self.action_data._calibrated_max = 0
        self.action_data._update()
        self._update()

    

    @QtCore.Slot()
    def _calibrated_min_changed(self):
        value = self._calibrated_min_widget.value()
        if value >= self.action_data._calibrated_max:
            # ensure min and max are not the same
            value = self.action_data._calibrated_max - 0.001
        self.action_data._calibrated_min = value
        self._update()

    @QtCore.Slot()
    def _calibrated_max_changed(self):
        value = self._calibrated_max_widget.value()
        if value <= self.action_data._calibrated_min:
            # ensure min and max are not the same
            value = self.action_data._calibrated_min + 0.001
        self.action_data._calibrated_max = value
        self._update()

    @QtCore.Slot()
    def _calibrated_center_changed(self):
        value = self._calibrated_center_widget.value()
        self.action_data._calibrated_center = value
        self._update()
        

    @QtCore.Slot()
    def _deadzone_changed(self):
        ''' deadzone widget changed '''
        values = self._deadzone_widget.get_values()
        self.action_data.deadzone = values


    @QtCore.Slot(bool)
    def _centered_changed(self, checked):
        self.action_data.centered = checked
        self._update()


    @QtCore.Slot(bool)
    def _inverted_changed(self, checked):
        self.action_data.inverted = checked
        self._update()

    def _getCalibratedValue(self, value : float):
        return self.action_data.getValue(value)
    
    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
        if gremlin.shared_state.is_running:
            return 

        if not event.is_axis:
            return 
        
        if event.device_guid != self.action_data.device_guid:
            return
        
        if event.identifier != self.action_data.input_id:
            return

        self._update()
        


    def _update(self):
        ''' updates the data  '''

        is_centered = self.action_data.centered
        auto_calibrate = self._auto_calibrate_widget.isChecked()
       

        self._deadzone_widget.isCentered = is_centered
        self._center_label.setVisible(is_centered)
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
            self._deadzone_widget.set_values(self.action_data.deadzone)
            

        self._update_axis_widget(raw_value,
                                 calibrated_value,
                                 self.action_data.calibrated_min,
                                 self.action_data.calibrated_center if is_centered else None,
                                 self.action_data.calibrated_max)     

    def _update_axis_widget(self, raw_value : float, calibrated_value : float, min_value : float, center_value : float, max_value : float):
        with QtCore.QSignalBlocker(self._slider):
            self._slider.setValue([min_value, center_value, max_value])
            self._slider.setMarkerValue(raw_value)
            self._repeater.setValue(calibrated_value)

            #print (f"{raw_value} -> {calibrated_value:0.3f}")

_calibration_manager = CalibrationManager()