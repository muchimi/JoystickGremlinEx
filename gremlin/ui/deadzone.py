


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
import os
from lxml import etree as ElementTree
from PySide6 import QtWidgets, QtCore, QtGui #QtWebEngineWidgets

import gremlin.base_profile
import gremlin.config
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
from gremlin.input_types import InputType
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.macro
from gremlin.ui import ui_common
import gremlin.ui.axis_calibration
import gremlin.ui.device_tab
import gremlin.ui.input_item
import gremlin.ui.ui_common
from gremlin.ui.qsliderwidget import QSliderWidget
import gremlin.util
from gremlin.util import *
from gremlin.types import *
import gremlin.clipboard

from enum import Enum, auto
from gremlin.macro_handler import *
import gremlin.util
import gremlin.singleton_decorator
from gremlin.util import InvokeUiMethod
import gremlin.util
from itertools import pairwise

from gremlin.ui.ui_common import DynamicDoubleSpinBox, DualSlider, get_text_width
import enum
from lxml import etree



class DeadzonePreset(enum.IntEnum):
    center_zero = 0
    center_two = 1
    center_five = 2
    center_ten = 3
    end_two = 4
    end_five = 5
    end_ten = 6
    reset = 7

    @staticmethod
    def to_display(value : DeadzonePreset) -> str:
        return _deadzone_preset_string_lookup[value]

_deadzone_preset_string_lookup = {    
    DeadzonePreset.center_zero : "Center 0%",
    DeadzonePreset.center_two : "Center 2%",
    DeadzonePreset.center_five : "Center 5%",
    DeadzonePreset.center_ten : "Center 10%",
    DeadzonePreset.end_two : "End 2%",
    DeadzonePreset.end_five : "End 5%",
    DeadzonePreset.end_ten : "End 10%",
    DeadzonePreset.reset : "Reset"
}

class DeadzoneWidget(QtWidgets.QWidget):
    ''' deadzone widget '''

    changed = QtCore.Signal() # indicates the data has changed
    

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the data of this response curve
        :param parent the parent widget
        """
        super().__init__(parent)
        self.profile_data = profile_data
        self.main_layout = QtWidgets.QGridLayout(self)
        self.event_lock = False
        self._centered = False

        # Create the two sliders for centered deadzones
        self.left_slider = QSliderWidget()

        # use a single slider for non-centered axes
        self.slider = QSliderWidget()


        self.slider.desired_height = 20
        self.slider.setRange(-1.0, 1.0)
        self.slider.setMarkerVisible(False)

        # double slider for centered axes
        self.left_slider.setMarkerVisible(False)
        self.left_slider.desired_height = 20
        self.left_slider.setRange(-1.0, 0.0)

        self.right_slider = QSliderWidget()
        self.right_slider.setMarkerVisible(False)
        self.right_slider.setRange(0.0, 1.0)
        self.right_slider.desired_height = 20

        # Create spin boxes for the left slider
        self.left_lower = ui_common.QFloatLineEdit()
        self.left_lower.setMinimum(-1.0)
        self.left_lower.setMaximum(0.0)
        self.left_lower.setSingleStep(0.05)
        self.left_lower.setValue(-1)
        self.left_lower.setToolTip("Low (-1.0) deadzone")

        self.left_upper = ui_common.QFloatLineEdit()
        self.left_upper.setMinimum(-1.0)
        self.left_upper.setMaximum(0.0)
        self.left_upper.setSingleStep(0.05)
        self.left_upper.setValue(0)
        self.left_upper.setToolTip("Center left deadzone")

        # Create spin boxes for the right slider
        self.right_lower = ui_common.QFloatLineEdit()
        self.right_lower.setSingleStep(0.05)
        self.right_lower.setMinimum(0.0)
        self.right_lower.setMaximum(1.0)
        self.right_lower.setValue(0)
        self.right_lower.setToolTip("Center right deadzone")

        self.right_upper = ui_common.QFloatLineEdit()
        self.right_lower.setToolTip("High (+1.0) deadzone")
        self.right_upper.setSingleStep(0.05)
        self.right_upper.setMinimum(0.0)
        self.right_upper.setMaximum(1.0)
        self.right_upper.setValue(1)

        # Hook up all the required callbacks
        self.slider.valueChanged.connect(self._update_center)
        self.left_slider.valueChanged.connect(self._update_left)
        self.right_slider.valueChanged.connect(self._update_right)

        self.left_lower.valueChanged.connect(
            lambda value: self._update_from_spinner(value,0)
        )
        self.left_upper.valueChanged.connect(
            lambda value: self._update_from_spinner(value,1)
        )
        self.right_lower.valueChanged.connect(
            lambda value: self._update_from_spinner(value,2)
        )
        self.right_upper.valueChanged.connect(
            lambda value: self._update_from_spinner(value,3)
        )




        self.container_preset_widget = QtWidgets.QWidget()
        self.container_preset_layout = QtWidgets.QHBoxLayout(self.container_preset_widget)
        self.container_preset_layout.addWidget(QtWidgets.QLabel("Deadzone"))

        from gremlin.curve_handler import DeadzonePreset
        self._center_presets = []
        for preset in DeadzonePreset:
            name = DeadzonePreset.to_display(preset)
            button = ui_common.QDataPushButton(name)
            button.data = preset
            button.clicked.connect(self._deadzone_preset_cb)
            self.container_preset_layout.addWidget(button)
            if self._is_center_preset(preset):
                self._center_presets.append(button)

        self.container_preset_layout.addStretch()

        # Put everything into the layout
        row = 0
        self.main_layout.addWidget(self.container_preset_widget, row, 0, 1, 4)
        row += 1
        self.main_layout.addWidget(self.slider, row, 0, 1, 4)
        self.main_layout.addWidget(self.left_slider, row, 0, 1, 2)
        self.main_layout.addWidget(self.right_slider, row, 2, 1, 2)
        row += 1
        widget = gremlin.ui.ui_common.QDataWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.addWidget(QtWidgets.QLabel("Min:"))
        layout.addWidget(self.left_lower)
        layout.addStretch()
        self.main_layout.addWidget(widget, row, 0)

        widget = gremlin.ui.ui_common.QDataWidget()
        widget.data = DeadzonePreset.center_five # this is so it gets hidden when in slider mode
        layout = QtWidgets.QHBoxLayout(widget)
        layout.addStretch()
        layout.addWidget(QtWidgets.QLabel("Ctr Min:"))
        layout.addWidget(self.left_upper)
        
        self.main_layout.addWidget(widget, row, 1)
        self._center_presets.append(widget)

        widget = gremlin.ui.ui_common.QDataWidget()
        widget.data = DeadzonePreset.center_five # this is so it gets hidden when in slider mode
        layout = QtWidgets.QHBoxLayout(widget)
        
        layout.addWidget(QtWidgets.QLabel("Ctr Max:"))
        layout.addWidget(self.right_lower)
        layout.addStretch()
        
        self.main_layout.addWidget(widget, row, 2)
        self._center_presets.append(widget)
        widget = gremlin.ui.ui_common.QDataWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.addStretch()
        layout.addWidget(QtWidgets.QLabel("Max:"))
        layout.addWidget(self.right_upper)
        
        self.main_layout.addWidget(widget, row, 3)

        self._update()

    def _is_center_preset(self, preset):
        ''' true if a center preset '''
        return preset in (DeadzonePreset.center_zero, DeadzonePreset.center_two, DeadzonePreset.center_five, DeadzonePreset.center_ten)

    @QtCore.Slot() 
    def _deadzone_preset_cb(self):
        ''' handles deadzone presets '''
        from gremlin.curve_handler import DeadzonePreset
        widget = self.sender()
        preset = widget.data

        d_start, d_left, d_right, d_end = self.values()
        if d_start is None:
            d_start = -1
        if d_end is None:
            d_end = 1
        if d_left is None:
            d_left = 0
        if d_right is None:
            d_right = 0
        
        match preset:
            case DeadzonePreset.center_two :
                d_left = -0.02 * 2
                d_right = 0.02 * 2
            case DeadzonePreset.center_five :
                d_left = -0.05 * 2
                d_right = 0.05 * 2
            case DeadzonePreset.center_ten :
                d_left = -0.1 * 2
                d_right = 0.1 * 2
            case DeadzonePreset.end_two : 
                d_start = -1 + 0.02 * 2
                d_end = 1 - 0.02 * 2
            case DeadzonePreset.end_five :
                d_start = -1 + 0.05 * 2
                d_end = 1 - 0.05 * 2
            case DeadzonePreset.end_ten : 
                d_start = -1 + 0.1 * 2
                d_end = 1 - 0.1 * 2

            case DeadzonePreset.reset : 
                d_start = -1
                d_left = 0
                d_right = 0
                d_end = 1

        self._update_deadzone([d_start, d_left, d_right, d_end])


    @property
    def isCentered(self) -> bool:
        return self._centered
    @isCentered.setter
    def isCentered(self, value: bool):
        if value != self._centered:
            self._centered = value
            self._update()

    # def setValues(self, values):
    #     v1,v2,v3,v4 = values
    #     self.left_lower.setValue(v1),
    #     self.left_upper.setValue(v2),
    #     self.right_lower.setValue(v3),
    #     self.right_upper.setValue(v4)


    def setValues(self, values):
        """Sets the deadzone values.

        :param values the new deadzone values [min, min center, max center, max]
        """

        current = self.values()
        if current == values:
            # no change
            return

        v1,v2,v3,v4 = values

        with QtCore.QSignalBlocker(self.left_slider):
            self.left_slider.setValue((v1,v2))
        with QtCore.QSignalBlocker(self.left_lower):
            self.left_lower.setValue(v1)
        with QtCore.QSignalBlocker(self.left_upper):            
            self.left_upper.setValue(v2)
        with QtCore.QSignalBlocker(self.right_slider):
            self.right_slider.setValue((v3,v4))
        with QtCore.QSignalBlocker(self.right_lower):
            self.right_lower.setValue(v3)
        with QtCore.QSignalBlocker(self.right_upper):
            self.right_upper.setValue(v4)
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setValue((v1,v4))

        self._update()
       

        self.changed.emit()


    def values(self):
        """Returns the current deadzone values.

        :return current deadzone values
        """
        return [
            self.left_lower.value(),
            self.left_upper.value(),
            self.right_lower.value(),
            self.right_upper.value()
            ]
        
    
    def get_min(self) -> float:
        return self.left_lower.value()

    def get_max(self) -> float:
        return self.right_upper.value()
    
    def get_center_left(self) -> float:
        return self.left_upper.value()
    def get_center_right(self) -> float:
        return self.right_lower.value()
    
    def _update_center(self, handle, value):
        ''' updates the main slider when in non centered mode'''
        if not self.event_lock:
            self.event_lock = True
            if handle == 0:
                self.left_lower.setValue(value)
                self.profile_data.deadzone[0] = value
            elif handle == 1:
                self.right_upper.setValue(value)
                self.profile_data.deadzone[-1] = value

            self.changed.emit()
            self.event_lock = False

    def _update_left(self, handle, value):
        """Updates the left spin boxes.

        :param handle the handle which was moved
        :param value the new value
        """
        if not self.event_lock:
            self.event_lock = True
            if handle == 0:
                self.left_lower.setValue(value)
                self.profile_data.deadzone[0] = value
            elif handle == 1:
                self.left_upper.setValue(value)
                self.profile_data.deadzone[1] = value

            self.changed.emit()
            self.event_lock = False

    def _update_right(self, handle, value):
        """Updates the right spin boxes.

        :param handle the handle which was moved
        :param value the new value
        """
        if not self.event_lock:
            self.event_lock = True
            if handle == 0:
                self.right_lower.setValue(value)
                self.profile_data.deadzone[2] = value
            elif handle == 1:
                self.right_upper.setValue(value)
                self.profile_data.deadzone[3] = value

            self.changed.emit()
            self.event_lock = False

        

    def _update_from_spinner(self, value, index):
        """Updates the slider position.

        :param value the new value
        :param handle the handle to move
        :param widget which slider widget to update
        """

        values = self.values()
        if index > len(values):
            # two handle situation
            index = 1

        current = values[index]
        if current != value:
            values[index] = value
            self.setValues(values)

        

            

    def _update_deadzone(self, data : list):
        ''' updates the deadzone text values '''
        self.setValues(data)
        self.profile_data.deadzone = data
        self.changed.emit() # notify we changed
            


    def _update(self):
        is_centered = self._centered
        if is_centered:
            self.slider.setVisible(False)
            self.left_slider.setVisible(True)
            self.right_slider.setVisible(True)
            self.left_upper.setVisible(True)
            self.right_lower.setVisible(True)
        else:
            self.slider.setVisible(True)
            self.left_slider.setVisible(False)
            self.right_slider.setVisible(False)
            self.left_upper.setVisible(False)
            self.right_lower.setVisible(False)

        for button in self._center_presets:
            preset = button.data
            if self._is_center_preset(preset):
                button.setVisible(is_centered)

