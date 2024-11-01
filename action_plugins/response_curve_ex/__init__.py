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
import enum
import logging
import os
import time
from PySide6 import QtCore, QtGui, QtWidgets
from lxml import etree as ElementTree

import gremlin
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.joystick_handling
from gremlin.ui.ui_common import DynamicDoubleSpinBox, DualSlider, get_text_width
import gremlin.ui.input_item
import gremlin.ui.ui_common
import gremlin.util
import gremlin.shared_state
import gremlin.curve_handler
import gremlin.input_devices
import gremlin.spline



class ResponseCurveExWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget that allows configuring the response of an axis to
    user inputs."""

    def __init__(self, action_data : ResponseCurveEx, parent=None):
        """Creates a new instance.

        :param action_data the data associated with this specific action.
        :param parent parent widget
        """
        super().__init__(action_data, parent=parent)

        self.is_inverted = False
        self.action_data = action_data

   

    def _create_ui(self):
        """Creates the required UI elements."""
        self.curve_widget = gremlin.curve_handler.AxisCurveWidget(self.action_data.curve_data, self)
        self.main_layout.addWidget(self.curve_widget)

        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_handler)
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)

    def _populate_ui(self):
        pass

    @QtCore.Slot()
    def _profile_start(self):
        # listen to hardware events
        if self.action_data.show_input_axis:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.disconnect(self._joystick_event_handler)

    @QtCore.Slot()
    def _profile_stop(self):
        # listen to hardware events
        if self.action_data.show_input_axis:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event_handler)


    def _joystick_event_handler(self, event):
        ''' handles joystick input '''

        if not event.is_axis:
            # ignore if not an axis event
            return
        
        if gremlin.shared_state.is_running:
            # ignore if profile is running
            return

        if self.action_data.hardware_device_guid != event.device_guid:
            # ignore if a different input device
            return
            
        if self.action_data.hardware_input_id != event.identifier:
            # ignore if a different input axis on the input device
            return
        
        self.curve_widget.update_value(event.value)
        

class ResponseCurveExFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action_data : ResponseCurveEx) :
        super().__init__(action_data)
        self.curve_data = action_data.curve_data
        self.curve_data.curve_update()

    def process_event(self, event, value):
        if event.is_axis:
            value.current = self.curve_data.curve_value(value.current)
        return True


class ResponseCurveEx(gremlin.base_profile.AbstractAction):

    """Represents axis response curve mapping."""

    name = "Response Curve Ex"
    tag = "response-curve-ex"

    default_button_activation = (True, True)
    
    # override allowed input if different from default
    input_types = [
        InputType.JoystickAxis
    ]

    functor = ResponseCurveExFunctor
    widget = ResponseCurveExWidget

    def __init__(self, parent):
        """Creates a new ResponseCurve instance.

        :param parent the parent profile.InputItem of this instance
        """
        super().__init__(parent)
        self.parent = parent
        self.curve_data = gremlin.curve_handler.AxisCurveData()
        self.curve_data.curve_update()
        self.show_input_axis = gremlin.config.Configuration().show_input_axis
        

    def icon(self):
        """Returns the icon representing the action."""
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is needed, False otherwise
        """
        return False

    def _parse_xml(self, node):
        """Parses the XML corresponding to a response curve.

        :param node the XML node to parse
        """

        self.curve_data._parse_xml(node)



    def _generate_xml(self):
        """Generates a XML node corresponding to this object.

        :return XML node representing the object's data
        """

        node = self.curve_data._generate_xml()
        return node

    def _is_valid(self):
        """Returns whether or not the action is configured correctly.

        :return True if the action is configured correctly, False otherwise
        """
        return True


version = 1
name = "response-curve-ex"
create = ResponseCurveEx
