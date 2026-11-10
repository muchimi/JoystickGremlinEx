# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
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


import logging
import os
from PySide6 import QtCore, QtWidgets
from lxml import etree as ElementTree

import gremlin.base_profile
from gremlin.input_types import InputType
from gremlin.util import safe_read, safe_format
from gremlin import util
import gremlin.ui.ui_common
import gremlin.input_item
from shiboken6 import Shiboken

syslog = logging.getLogger("system")


class SplitAxisWidget(gremlin.input_item.AbstractActionWidget):
    def __init__(self, action_data, parent=None):
        """Creates a new RemapWidget.

        :param action_data profile.InputItem data for this widget
        :param parent of this widget
        """
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, SplitAxis)

    def _create_ui(self):
        # Slider and readout setup
        if not Shiboken.isValid(self):
            return
        self.split_slider_layout = QtWidgets.QHBoxLayout()
        self.split_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.split_slider.setRange(-100000, 100000)
        self.split_slider.setTickInterval(10000)
        self.split_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.split_readout = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.split_readout.setRange(-1, 1)
        self.split_readout.setSingleStep(0.1)
        self.split_slider_layout.addWidget(self.split_slider)
        self.split_slider_layout.addWidget(self.split_readout)

        # Connect slider and spinner
        self.split_slider.valueChanged.connect(self._update_readout)
        self.split_readout.valueChanged.connect(self._update_slider)

        # Device selection
        self.split_device_layout = QtWidgets.QHBoxLayout()
        self.vjoy_selector_1 = gremlin.ui.ui_common.VJoySelector(self._create_vjoy_selector_callback(1), [InputType.JoystickAxis])
        self.vjoy_selector_2 = gremlin.ui.ui_common.VJoySelector(self._create_vjoy_selector_callback(2), [InputType.JoystickAxis])
        self.split_device_layout.addWidget(self.vjoy_selector_1)
        self.split_device_layout.addWidget(self.vjoy_selector_2)

        # Assemble complete UI
        self.main_layout.addLayout(self.split_slider_layout)
        self.main_layout.addLayout(self.split_device_layout)

    def _populate_ui(self):
        self.split_slider.setValue(round(self.action_data.center_point * 1e5))
        self.split_readout.setValue(self.action_data.center_point)
        try:
            if self.action_data.device_low_vjoy_id is None or self.action_data.device_low_axis is None:
                self.vjoy_selector_1.set_selection(InputType.JoystickAxis, -1, -1)
            else:
                self.vjoy_selector_1.set_selection(InputType.JoystickAxis, self.action_data.device_low_vjoy_id, self.action_data.device_low_axis)
            if self.action_data.device_high_vjoy_id is None or self.action_data.device_high_axis is None:
                self.vjoy_selector_2.set_selection(InputType.JoystickAxis, -1, -1)
            else:
                self.vjoy_selector_2.set_selection(InputType.JoystickAxis, self.action_data.device_high_vjoy_id, self.action_data.device_high_axis)

            # Restoring an unavailable saved output must not select another device.
        except gremlin.error.GremlinError as e:
            # FIXME: This error here should only have been needed due to the
            #        vJoy selector attempting to acquire a vJoy device, this
            #        should no longer occur, check if this here is still needed
            util.display_error(
                f"A needed vJoy device is not accessible: {e}\n\n" + "Default values have been set for the input, but they are not what has been specified."
            )
            syslog.error(str(e))

    def save_vjoy_selection(self, axis_id, data):
        """Stores the data of a vJoy selector.

        A separate method to handle saving the vJoy selection changes is needed
        to prevent overwriting of valid data when updating center point data.

        Parameters
        ----------
        axis_id : int
            Identifier of the axis to save the data of
        """
        if not data or data.get("device_id") is None or data.get("input_id") is None:
            return
        if axis_id == 1:
            self.action_data.device_low_vjoy_id = data["device_id"]
            self.action_data.device_low_axis = data["input_id"]
        elif axis_id == 2:
            self.action_data.device_high_vjoy_id = data["device_id"]
            self.action_data.device_high_axis = data["input_id"]

    def save_center_point(self):
        self.action_data.center_point = self.split_readout.value()

    def _update_readout(self, value):
        self.split_readout.setValue(value / 1e5)
        self.save_center_point()

    def _update_slider(self, value):
        self.split_slider.setValue(round(value * 1e5))
        self.save_center_point()

    def _create_vjoy_selector_callback(self, axis_id):
        """Returns a lambda expression updating the specified axis.

        Parameters
        ----------
        axis_id : int
            Identifier of the axis to save the data of
        Returns
        -------
        lambda
            Callable lambda expression which will update the specified axis
            information
        """
        return lambda data: self.save_vjoy_selection(axis_id, data)


class SplitAxisFunctor(gremlin.base_profile.AbstractFunctor):
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self.action = action

    def process_event(self, event, value, extra_data=None):
        current, center = float(value.current), self.action.center_point
        if current < center:
            low = (center - current) / max(1.0 + center, 0.001) * 2.0 - 1.0
            high = -1.0
        else:
            high = (current - center) / max(1.0 - center, 0.001) * 2.0 - 1.0
            low = -1.0
        gremlin.joystick_handling.set_axis(self.action.device_low_vjoy_id, self.action.device_low_axis, max(-1.0, min(1.0, low)))
        gremlin.joystick_handling.set_axis(self.action.device_high_vjoy_id, self.action.device_high_axis, max(-1.0, min(1.0, high)))
        return True


class SplitAxis(gremlin.input_item.AbstractAction):
    name = "Split Axis"
    tag = "split-axis"
    hint = """Splits an input axis into regions.
For advanced axis splitting options, please use Gated Axis instead."""

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)
    # override default allowed inputs here
    input_types = [InputType.JoystickAxis]

    functor = SplitAxisFunctor
    widget = SplitAxisWidget

    def __init__(self, parent, extra_data: dict = None):
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent
        self.center_point = 0.0
        self.device_low_axis = None
        self.device_low_vjoy_id = None
        self.device_high_axis = None
        self.device_high_vjoy_id = None

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node, data=None, extra_data=None):
        self.center_point = float(node.get("center-point"))
        self.device_low_vjoy_id = gremlin.joystick_handling.parse_virtual_device_key(node.get("device-low-vjoy-id", "1"))
        self.device_high_vjoy_id = gremlin.joystick_handling.parse_virtual_device_key(node.get("device-high-vjoy-id", "1"))
        self.device_low_axis = safe_read(node, "device-low-axis", int, 1)
        self.device_high_axis = safe_read(node, "device-high-axis", int, 1)

    def _generate_xml(self):
        node = ElementTree.Element("split-axis")
        node.set("center-point", safe_format(self.center_point, float, 0))
        node.set("device-low-vjoy-id", str(self.device_low_vjoy_id or 1))
        node.set("device-high-vjoy-id", str(self.device_high_vjoy_id or 1))
        node.set("device-low-axis", safe_format(self.device_low_axis, int, 1))
        node.set("device-high-axis", safe_format(self.device_high_axis, int, 1))

        return node

    def _is_valid(self):
        return all(key is not None and (not isinstance(key, int) or key > 0) and axis is not None and axis > 0
                   for key, axis in ((self.device_low_vjoy_id, self.device_low_axis),
                                     (self.device_high_vjoy_id, self.device_high_axis)))


version = 1
name = "split-axis"
create = SplitAxis
