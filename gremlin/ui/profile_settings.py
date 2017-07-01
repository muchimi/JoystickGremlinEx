# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2017 Lionel Ott
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


from PyQt5 import QtWidgets

import gremlin.joystick_handling


class ProfileSettingsWidget(QtWidgets.QWidget):

    """Widget allowing changing profile specific settings."""

    def __init__(self, profile_settings, parent=None):
        """Creates a new UI widget.

        :param profile_settings the settings of the profile
        :param parent the parent widget
        """
        super().__init__(parent)

        self.profile_settings = profile_settings

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._create_ui()

    def _create_ui(self):
        """Creates the UI elements of this widget."""
        # Get list of vjoy devices
        vjoy_devices = []
        for device in gremlin.joystick_handling.joystick_devices():
            if device.is_virtual:
                vjoy_devices.append(device)

        # Create UI elements
        for device in vjoy_devices:
            widget = QtWidgets.QGroupBox(
                "{} #{}".format(device.name, device.vjoy_id)
            )
            box_layout = QtWidgets.QVBoxLayout()
            widget.setLayout(box_layout)
            box_layout.addWidget(VJoyAxisDefaultsWidget(
                device,
                self.profile_settings
            ))

            self.main_layout.addWidget(widget)

        self.main_layout.addStretch(1)

        label = QtWidgets.QLabel(
            "This tab allows setting default initialization of vJoy axis "
            "values. These values  will be used when activating Gremlin."
        )
        label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
        label.setWordWrap(True)
        label.setFrameShape(QtWidgets.QFrame.Box)
        label.setMargin(10)
        self.main_layout.addWidget(label)


class VJoyAxisDefaultsWidget(QtWidgets.QWidget):

    """UI widget allowing modification of axis initialization values."""

    def __init__(self, joy_data, profile_data, parent=None):
        """Creates a new UI widget.

        :param joy_data JoystickDeviceData object containing device information
        :param profile_data profile settings
        """
        super().__init__(parent)

        self.joy_data = joy_data
        self.profile_data = profile_data
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._spin_boxes = []
        self._create_ui()

    def _create_ui(self):
        """Creates the UI elements."""
        # FIXME: this assumes sequential axis are present and is a limitation
        #       of SDL2
        for i in range(self.joy_data.axes):
            layout = QtWidgets.QHBoxLayout()
            layout.addWidget(QtWidgets.QLabel("Axis {:d}".format(i+1)))

            box = QtWidgets.QDoubleSpinBox()
            box.setRange(-1, 1)
            box.setSingleStep(0.05)
            box.setValue(self.profile_data.get_initial_vjoy_axis_value(
                self.joy_data.vjoy_id,
                i+1
            ))
            box.valueChanged.connect(self._create_value_cb(i+1))

            layout.addWidget(box)
            layout.addStretch(1)
            self.main_layout.addLayout(layout)
        self.main_layout.addStretch(1)

    def _create_value_cb(self, axis_id):
        """Creates a callback function which updates axis values.

        :param axis_id id of the axis to change the value of
        :return callback customized for the given axis_id
        """
        return lambda x: self._update_axis_value(axis_id, x)

    def _update_axis_value(self, axis_id, value):
        """Updates an axis' default value.

        :param axis_id id of the axis to update
        :param value the value to update the axis to
        """
        self.profile_data.set_initial_vjoy_axis_value(
            self.joy_data.vjoy_id,
            axis_id,
            value
        )