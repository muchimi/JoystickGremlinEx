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


import logging
import math
import os
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets, QtGui

import gremlin.base_profile
from gremlin.input_types import InputType
from gremlin.types import MouseButton
from gremlin.profile import read_bool, safe_read, safe_format
from gremlin.util import rad2deg
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput
from gremlin import input_devices

class MapToMouseWidget(gremlin.ui.input_item.AbstractActionWidget):

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
        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)

        self.mode_widget = QtWidgets.QWidget()
        self.mode_layout = QtWidgets.QHBoxLayout(self.mode_widget)

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QGridLayout(self.button_widget)
        self.motion_widget = QtWidgets.QWidget()
        self.motion_layout = QtWidgets.QGridLayout(self.motion_widget)

        self.container_layout.addWidget(self.mode_widget)
        self.container_layout.addWidget(self.button_widget)
        self.container_layout.addWidget(self.motion_widget)

        self.button_group = QtWidgets.QButtonGroup()
        self.button_radio = QtWidgets.QRadioButton("Button")
        self.motion_radio = QtWidgets.QRadioButton("Motion")
        self.button_group.addButton(self.button_radio)
        self.button_group.addButton(self.motion_radio)
        self.mode_layout.addWidget(self.button_radio)
        self.mode_layout.addWidget(self.motion_radio)
        self.button_radio.clicked.connect(self._change_mode)
        self.motion_radio.clicked.connect(self._change_mode)

        self.button_widget.hide()
        self.motion_widget.hide()

        # Create the different UI elements
        self._create_mouse_button_ui()
        if self.action_data.get_input_type() == InputType.JoystickAxis:
            self._create_axis_ui()
        else:
            self._create_button_hat_ui()

        
        warning_widget = gremlin.ui.ui_common.QIconLabel("fa.warning",use_qta=True,icon_color=QtGui.QColor("yellow"),text="Legacy mapper - consider using <i>Map to Mouse Ex</i> for additional functionality", use_wrap=False)
        self.main_layout.addWidget(self.container_widget)
        self.main_layout.addWidget(warning_widget)            

    def _create_axis_ui(self):
        """Creates the UI for axis setups."""
        self.x_axis = QtWidgets.QRadioButton("X Axis")
        self.x_axis.setChecked(True)
        self.y_axis = QtWidgets.QRadioButton("Y Axis")

        self.motion_layout.addWidget(
            QtWidgets.QLabel("Control"),
            0,
            0,
            QtCore.Qt.AlignLeft
        )
        self.motion_layout.addWidget(self.x_axis, 0, 1, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(self.y_axis, 0, 2, 1, 2, QtCore.Qt.AlignLeft)

        self.min_speed = QtWidgets.QSpinBox()
        self.min_speed.setRange(0, 1e5)
        self.max_speed = QtWidgets.QSpinBox()
        self.max_speed.setRange(0, 1e5)
        self.motion_layout.addWidget(
            QtWidgets.QLabel("Minimum speed"), 1, 0, QtCore.Qt.AlignLeft
        )
        self.motion_layout.addWidget(self.min_speed, 1, 1, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(
            QtWidgets.QLabel("Maximum speed"), 1, 2, QtCore.Qt.AlignLeft
        )
        self.motion_layout.addWidget(self.max_speed, 1, 3, QtCore.Qt.AlignLeft)

        self._connect_axis()

    def _create_button_hat_ui(self):
        """Creates the UI for button setups."""
        self.min_speed = QtWidgets.QSpinBox()
        self.min_speed.setRange(0, 1e5)
        self.max_speed = QtWidgets.QSpinBox()
        self.max_speed.setRange(0, 1e5)
        self.time_to_max_speed = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.time_to_max_speed.setRange(0.0, 100.0)
        self.time_to_max_speed.setValue(0.0)
        self.time_to_max_speed.setDecimals(2)
        self.time_to_max_speed.setSingleStep(0.1)
        self.direction = QtWidgets.QSpinBox()
        self.direction.setRange(0, 359)

        self.motion_layout.addWidget(QtWidgets.QLabel("Minimum speed"), 0, 0)
        self.motion_layout.addWidget(self.min_speed, 0, 1, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(QtWidgets.QLabel("Maximum speed"), 0, 2)
        self.motion_layout.addWidget(self.max_speed, 0, 3, QtCore.Qt.AlignLeft)

        self.motion_layout.addWidget(
            QtWidgets.QLabel("Time to maximum speed"), 1, 0
        )
        self.motion_layout.addWidget(
            self.time_to_max_speed, 1, 1, QtCore.Qt.AlignLeft
        )
        if self.action_data.get_input_type() in [
            InputType.JoystickButton, InputType.Keyboard
        ]:
            self.motion_layout.addWidget(QtWidgets.QLabel("Direction"), 1, 2)
            self.motion_layout.addWidget(
                self.direction, 1, 3, QtCore.Qt.AlignLeft
            )

        self._connect_button_hat()

    def _create_mouse_button_ui(self):
        self.mouse_button = gremlin.ui.ui_common.NoKeyboardPushButton(
            gremlin.types.MouseButton.to_string(self.action_data.button_id)
        )
        self.mouse_button.clicked.connect(self._request_user_input)

        self.button_layout.addWidget(QtWidgets.QLabel("Mouse Button"), 0, 0)
        self.button_layout.addWidget(self.mouse_button, 0, 1)

    def _populate_ui(self):
        """Populates the UI components."""
        if self.action_data.get_input_type() == InputType.JoystickAxis:
            self._populate_axis_ui()
        else:
            self._populate_button_hat_ui()
        self._populate_mouse_button_ui()

        self.motion_radio.setChecked(self.action_data.motion_input)
        self.button_radio.setChecked(not self.action_data.motion_input)
        self._change_mode()

    def _populate_axis_ui(self):
        """Populates axis UI elements with data."""
        self._disconnect_axis()
        if self.action_data.direction == 90:
            self.x_axis.setChecked(True)
        else:
            self.y_axis.setChecked(True)

        self.min_speed.setValue(self.action_data.min_speed)
        self.max_speed.setValue(self.action_data.max_speed)
        self._connect_axis()

    def _populate_button_hat_ui(self):
        """Populates button UI elements with data."""
        self._disconnect_button_hat()
        self.min_speed.setValue(self.action_data.min_speed)
        self.max_speed.setValue(self.action_data.max_speed)
        self.time_to_max_speed.setValue(self.action_data.time_to_max_speed)
        self.direction.setValue(self.action_data.direction)
        self._connect_button_hat()

    def _populate_mouse_button_ui(self):
        self.mouse_button.setText(
            gremlin.types.MouseButton.to_string(self.action_data.button_id)
        )

    def _update_axis(self):
        """Updates the axis data with UI information."""
        self._disconnect_axis()

        # Update speed values
        min_speed = self.min_speed.value()
        max_speed = self.max_speed.value()
        if min_speed > max_speed:
            # Maximum value was decreased below minimum
            if max_speed != self.action_data.max_speed:
                min_speed = max_speed
            # Minimum value was increased above maximum
            elif min_speed != self.action_data.min_speed:
                max_speed = min_speed
        self.min_speed.setValue(min_speed)
        self.max_speed.setValue(max_speed)

        self.action_data.direction = 90 if self.x_axis.isChecked() else 0
        self.action_data.min_speed = min_speed
        self.action_data.max_speed = max_speed

        self._connect_axis()

    def _update_button_hat(self):
        """Updates the button data with UI information."""
        self._disconnect_button_hat()

        # Update speed values
        min_speed = self.min_speed.value()
        max_speed = self.max_speed.value()
        if min_speed > max_speed:
            # Maximum value was decreased below minimum
            if max_speed != self.action_data.max_speed:
                min_speed = max_speed
            # Minimum value was increased above maximum
            elif min_speed != self.action_data.min_speed:
                max_speed = min_speed
        self.min_speed.setValue(min_speed)
        self.max_speed.setValue(max_speed)

        self.action_data.min_speed = min_speed
        self.action_data.max_speed = max_speed
        self.action_data.time_to_max_speed = self.time_to_max_speed.value()
        self.action_data.direction = self.direction.value()

        self._connect_button_hat()

    def _update_mouse_button(self, event):
        self.action_data.button_id = event.identifier
        self.mouse_button.setText(
            gremlin.types.MouseButton.to_string(self.action_data.button_id)
        )

    def _connect_axis(self):
        """Connects all axis input elements to their callbacks."""
        self.x_axis.toggled.connect(self._update_axis)
        self.y_axis.toggled.connect(self._update_axis)
        self.min_speed.valueChanged.connect(self._update_axis)
        self.max_speed.valueChanged.connect(self._update_axis)

    def _disconnect_axis(self):
        """Disconnects all axis input elements from their callbacks."""
        self.x_axis.toggled.disconnect(self._update_axis)
        self.y_axis.toggled.disconnect(self._update_axis)
        self.min_speed.valueChanged.disconnect(self._update_axis)
        self.max_speed.valueChanged.disconnect(self._update_axis)

    def _connect_button_hat(self):
        """Connects all button input elements to their callbacks."""
        self.min_speed.valueChanged.connect(self._update_button_hat)
        self.max_speed.valueChanged.connect(self._update_button_hat)
        self.time_to_max_speed.valueChanged.connect(self._update_button_hat)
        self.direction.valueChanged.connect(self._update_button_hat)

    def _disconnect_button_hat(self):
        """Disconnects all button input elements to their callbacks."""
        self.min_speed.valueChanged.disconnect(self._update_button_hat)
        self.max_speed.valueChanged.disconnect(self._update_button_hat)
        self.time_to_max_speed.valueChanged.disconnect(self._update_button_hat)
        self.direction.valueChanged.disconnect(self._update_button_hat)

    def _change_mode(self):
        self.action_data.motion_input = self.motion_radio.isChecked()
        if self.action_data.motion_input:
            self.button_widget.hide()
            self.motion_widget.show()
        else:
            self.button_widget.show()
            self.motion_widget.hide()

        # Emit modification signal to ensure virtual button settings
        # are updated correctly
        self.action_modified.emit()

    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""
        self.button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Mouse],
            return_kb_event=False
        )
        self.button_press_dialog.item_selected.connect(self._update_mouse_button)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        self.button_press_dialog.show()


class MapToMouseFunctor(gremlin.base_profile.AbstractFunctor):

    """Implements the functionality required to move a mouse cursor.

    This moves the mouse cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    def __init__(self, action, parent = None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)

        self.config = action
        self.mouse_controller = gremlin.sendinput.MouseController()

    def process_event(self, event, value):
        if self.config.motion_input:
            if event.event_type == InputType.JoystickAxis:
                self._perform_axis_motion(event, value)
            elif event.event_type == InputType.JoystickHat:
                self._perform_hat_motion(event, value)
            else:
                self._perform_button_motion(event, value)
        else:
            self._perform_mouse_button(event, value)

    def _perform_mouse_button(self, event, value):
        assert self.config.motion_input is False
        (is_local, is_remote) = input_devices.remote_state.state
        if self.config.button_id in [MouseButton.WheelDown, MouseButton.WheelUp]:
            if value.current:
                direction = -16
                if self.config.button_id == MouseButton.WheelDown:
                    direction = 1
                if is_local:
                    gremlin.sendinput.mouse_wheel(direction)
                if is_remote:
                    input_devices.remote_client.send_mouse_wheel(direction)
        elif self.config.button_id in [MouseButton.WheelLeft, MouseButton.WheelRight]:
            if value.current:
                direction = -16
                if self.config.button_id == MouseButton.WheelRight:
                    direction = 16
                if is_local:
                    gremlin.sendinput.mouse_h_wheel(direction)
                if is_remote:
                    input_devices.remote_client.send_mouse_h_wheel(direction)                      
        else:
            if value.current:
                if is_local:
                    gremlin.sendinput.mouse_press(self.config.button_id)
                if is_remote:
                    input_devices.remote_client.send_mouse_button(self.config.button_id.value, True)
            else:
                if is_local:
                    gremlin.sendinput.mouse_release(self.config.button_id)
                if is_remote:
                    input_devices.remote_client.send_mouse_button(self.config.button_id.value, False)

    def _perform_axis_motion(self, event, value):
        """Processes events destined for an axis.

        :param event the event triggering the code execution
        :param value the current value of the event chain
        """
        delta_motion = self.config.min_speed + abs(value.current) * \
                (self.config.max_speed - self.config.min_speed)
        delta_motion = math.copysign(delta_motion, value.current)
        delta_motion = 0.0 if abs(value.current) < 0.05 else delta_motion

        dx = delta_motion if self.config.direction == 90 else None
        dy = delta_motion if self.config.direction != 90 else None
        (is_local, is_remote) = input_devices.remote_state.state
        if is_local:
            self.mouse_controller.set_absolute_motion(dx, dy)
        if is_remote:
            input_devices.remote_client.send_mouse_motion(dx, dy)

    def _perform_button_motion(self, event, value):
        (is_local, is_remote) = input_devices.remote_state.state
        if event.is_pressed:
            if is_local:
                self.mouse_controller.set_accelerated_motion(
                    self.config.direction,
                    self.config.min_speed,
                    self.config.max_speed,
                    self.config.time_to_max_speed
                )
            if is_remote:
                input_devices.remote_client.send_mouse_acceleration(self.config.direction, self.config.min_speed, self.config.max_speed, self.config.time_to_max_speed)
     
        else:
            if is_local:
                self.mouse_controller.set_absolute_motion(0, 0)
            if is_remote:
                input_devices.remote_client.send_mouse_motion(0, 0)

    def _perform_hat_motion(self, event, value):
        """Processes events destined for a hat.

        :param event the event triggering the code execution
        :param value the current value of the event chain
        """
        is_local = input_devices.remote_client.is_local
        is_remote = input_devices.remote_client.is_remote
        if value.current == (0, 0):
            if is_local:
                self.mouse_controller.set_absolute_motion(0, 0)
            if is_remote:
                input_devices.remote_client.send_mouse_motion(0, 0)

        else:
            a = rad2deg(math.atan2(-value.current[1], value.current[0])) + 90.0
            if is_local:
                self.mouse_controller.set_accelerated_motion(
                    a,
                    self.config.min_speed,
                    self.config.max_speed,
                    self.config.time_to_max_speed
                )
            if is_remote:
                input_devices.remote_client.send_mouse_acceleration(a, self.config.min_speed, self.config.max_speed, self.config.time_to_max_speed)


class MapToMouse(gremlin.base_profile.AbstractAction):

    """Action data for the map to mouse action.

    Map to mouse allows controlling of the mouse cursor using either a joystick
    or a hat.
    """

    name = "Map to Mouse"
    tag = "map-to-mouse"

    default_button_activation = (True, True)
    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MapToMouseFunctor
    widget = MapToMouseWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent
        # Flag whether or not this is mouse motion or button press
        self.motion_input = False
        # Mouse button enum
        self.button_id = MouseButton.Left
        # Angle of motion, 0 is up and 90 is right, etc.
        self.direction = 0
        # Minimum motion speed in pixels / sec
        self.min_speed = 5
        # Maximum motion speed in pixels / sec
        self.max_speed = 15
        # Time to reach maximum speed in sec
        self.time_to_max_speed = 1.0

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"[{self.button_id.name}]"
    
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
        # Need virtual buttons for button inputs on axes and hats
        if self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]:
            return not self.motion_input
        return False

    def _parse_xml(self, node):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        self.motion_input = read_bool(node, "motion-input", False)
        try:
            self.button_id = gremlin.types.MouseButton(
                safe_read(node, "button-id", int, 1)
            )
        except ValueError as e:
            logging.getLogger("system").warning(
                f"Invalid mouse identifier in profile: {e:}"
            )
            self.button_id = gremlin.types.MouseButton.Left
        self.direction = safe_read(node, "direction", int, 0)
        self.min_speed = safe_read(node, "min-speed", int, 5)
        self.max_speed = safe_read(node, "max-speed", int, 5)
        self.time_to_max_speed = safe_read(node, "time-to-max-speed", float, 0.0)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element("map-to-mouse")

        node.set("motion-input", safe_format(self.motion_input, bool))
        node.set("button-id", safe_format(self.button_id.value, int))
        node.set("direction", safe_format(self.direction, int))
        node.set("min-speed", safe_format(self.min_speed, int))
        node.set("max-speed", safe_format(self.max_speed, int))
        node.set("time-to-max-speed", safe_format(self.time_to_max_speed, float))

        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True


version = 1
name = "map-to-mouse"
create = MapToMouse
