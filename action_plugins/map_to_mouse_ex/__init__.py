# -*- coding: utf-8; -*-

# MaptoMouseEx - enhanced version of MapToMouse


import logging
import math
import os
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets

import gremlin.base_profile
from gremlin.input_types import InputType
from gremlin.types import MouseButton, MouseAction, MouseClickMode
from gremlin.profile import read_bool, safe_read, safe_format
from gremlin.util import rad2deg
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput
from gremlin import input_devices


import enum, threading,time, random


syslog = logging.getLogger("system")


class MapToMouseExWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to mouse motion or buttons."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, QtWidgets.QVBoxLayout, parent=parent)
        

    def _create_ui(self):
        """Creates the UI components."""
        # Layouts to use
        self.mode_layout = QtWidgets.QHBoxLayout()

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QGridLayout(self.button_widget)
        self.motion_widget = QtWidgets.QWidget()
        self.motion_layout = QtWidgets.QGridLayout(self.motion_widget)
        self.release_widget = QtWidgets.QWidget()
        self.options_layout = QtWidgets.QHBoxLayout(self.release_widget)

        self.click_widget = QtWidgets.QWidget()
        self.click_options_layout = QtWidgets.QHBoxLayout(self.click_widget)


        self.mode_widget = gremlin.ui.ui_common.NoWheelComboBox()

        input_type = self._get_input_type()
        if input_type == InputType.JoystickButton:
            actions = (a for a in MouseAction)
        else:
            actions = (MouseAction.MouseButton, MouseAction.MouseMotion)
        
        for mode in actions:
            self.mode_widget.addItem(MouseAction.to_name(mode), mode)

        self.mode_label = QtWidgets.QLabel("Description")

        self.mode_widget.currentIndexChanged.connect(self._action_mode_changed)

        self.chkb_force_remote_output = QtWidgets.QCheckBox("Force Remote output")
        self.chkb_force_remote_output_only = QtWidgets.QCheckBox("Remote Only")

        self.chkb_force_remote_output.clicked.connect(self._force_remote_output_changed)
        self.chkb_force_remote_output_only.clicked.connect(self._force_remote_output_only_changed)

        self.chkb_exec_on_release = QtWidgets.QCheckBox("Exec on release")
        self.chkb_exec_on_release.clicked.connect(self._exec_on_release_changed)
        
        
        self.mode_group = QtWidgets.QButtonGroup()
        self.mode_normal = QtWidgets.QRadioButton("Click")
        self.mode_press = QtWidgets.QRadioButton("Press Only")
        self.mode_release = QtWidgets.QRadioButton("Release Only")

        self.mode_normal.clicked.connect(self._click_change_mode)
        self.mode_press.clicked.connect(self._click_change_mode)
        self.mode_release.clicked.connect(self._click_change_mode)

        self.mode_group.addButton(self.mode_normal)
        self.mode_group.addButton(self.mode_press)
        self.mode_group.addButton(self.mode_release)

        self.click_options_layout.addWidget(self.mode_normal)
        self.click_options_layout.addWidget(self.mode_press)
        self.click_options_layout.addWidget(self.mode_release)
        self.click_options_layout.addStretch()

        
        
        self.options_layout.addWidget(self.chkb_exec_on_release)
        self.options_layout.addWidget(self.chkb_force_remote_output)
        self.options_layout.addWidget(self.chkb_force_remote_output_only)
        
        self.options_layout.addStretch()

        # self.button_group = QtWidgets.QButtonGroup()
        # self.button_radio = QtWidgets.QRadioButton("Button")
        # self.motion_radio = QtWidgets.QRadioButton("Motion")
        # self.wiggle_start_radio = QtWidgets.QRadioButton("Wiggle Start")
        # self.wiggle_stop_radio = QtWidgets.QRadioButton("Wiggle Stop")
        # self.button_group.addButton(self.button_radio)
        # self.button_group.addButton(self.motion_radio)

        self.mode_layout.addWidget(self.mode_widget)
        self.mode_layout.addWidget(self.mode_label)
        self.mode_layout.addStretch()

        # self.mode_layout.addWidget(self.wiggle_start_radio)
        # self.mode_layout.addWidget(self.wiggle_stop_radio)

        # self.button_radio.clicked.connect(self._change_mode)
        # self.motion_radio.clicked.connect(self._change_mode)
        

        self.button_widget.hide()
        self.motion_widget.hide()


        self.main_layout.addLayout(self.mode_layout)
        self.main_layout.addWidget(self.release_widget)
        self.main_layout.addWidget(self.button_widget)
        self.main_layout.addWidget(self.click_widget)
        self.main_layout.addWidget(self.motion_widget)
        


        # Create the different UI elements
        self._create_mouse_button_ui()
        if self.action_data.get_input_type() == InputType.JoystickAxis:
            self._create_axis_ui()
        else:
            self._create_button_hat_ui()


    def _click_change_mode(self):
        if self.mode_normal.isChecked():
            self.action_data.click_mode = MouseClickMode.Normal
        elif self.mode_press.isChecked():
            self.action_data.click_mode = MouseClickMode.Press
        elif self.mode_release.isChecked():
            self.action_data.click_mode = MouseClickMode.Release

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

        self.mouse_container_widget = QtWidgets.QWidget()
        self.mouse_container_layout = QtWidgets.QHBoxLayout()
        self.mouse_container_widget.setLayout(self.mouse_container_layout)

        self.mouse_container_layout.addWidget(QtWidgets.QLabel("Mouse Button"))
        self.mouse_container_layout.addWidget(self.mouse_button)


        self.mouse_button_widget = QtWidgets.QComboBox()
        self.mouse_button_widget.addItem("Left (mouse 1)",gremlin.types.MouseButton.Left)
        self.mouse_button_widget.addItem("Middle (mouse 2)",gremlin.types.MouseButton.Middle)
        self.mouse_button_widget.addItem("Right (mouse 3)",gremlin.types.MouseButton.Right)
        self.mouse_button_widget.addItem("Forward (mouse 4)",gremlin.types.MouseButton.Forward)
        self.mouse_button_widget.addItem("Back (mouse 5)",gremlin.types.MouseButton.Back)
        self.mouse_button_widget.addItem("Wheel up",gremlin.types.MouseButton.WheelUp)
        self.mouse_button_widget.addItem("Wheel down",gremlin.types.MouseButton.WheelDown)


        # update based on the current data
        index = self.mouse_button_widget.findData(self.action_data.button_id)
        self.mouse_button_widget.setCurrentIndex(index)

        self.mouse_button_widget.currentTextChanged.connect(self._change_mouse_button_cb)

        self.mouse_container_layout.addWidget(QtWidgets.QLabel("Selected action:"))
        self.mouse_container_layout.addWidget(self.mouse_button_widget)
        self.mouse_container_layout.addStretch(1)

        # add to main layout
        self.button_layout.addWidget(self.mouse_container_widget, 0,0)

    def _populate_ui(self):
        """Populates the UI components."""
        input_type = self.action_data.get_input_type()
        if input_type == InputType.JoystickAxis:
            self._populate_axis_ui()
        else:
            self._populate_button_hat_ui()
        self._populate_mouse_button_ui()


        with QtCore.QSignalBlocker(self.chkb_exec_on_release):
            self.chkb_exec_on_release.setChecked(self.action_data.exec_on_release)

        action_mode = self.action_data.action_mode
        index = self.mode_widget.findData(action_mode)
        if index != -1 and self.mode_widget.currentIndex != index:
            with QtCore.QSignalBlocker(self.mode_widget):
                self.mode_widget.setCurrentIndex(index)

        # self.motion_radio.setChecked(action_mode == MouseAction.MouseMotion)
        # self.button_radio.setChecked(action_mode == MouseAction.MouseButton)
        
        self.mode_label.setText(MouseAction.to_description(action_mode))

        click_mode = self.action_data.click_mode
        if click_mode == MouseClickMode.Normal:
            with QtCore.QSignalBlocker(self.mode_normal):
                self.mode_normal.setChecked(True)
        elif click_mode == MouseClickMode.Press:
            with QtCore.QSignalBlocker(self.mode_press):
                self.mode_press.setChecked(True)
        elif click_mode == MouseClickMode.Release:
            with QtCore.QSignalBlocker(self.mode_release):
                self.mode_release.setChecked(True)

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

    def _change_mouse_button_cb(self):
        ''' mouse event drop down selected '''
        self.action_data.button_id = self.mouse_button_widget.currentData()
        self.mouse_button.setText(
            gremlin.types.MouseButton.to_string(self.action_data.button_id)
        )


    def _action_mode_changed(self, index):
        ''' called when the action mode drop down value changes '''
        with QtCore.QSignalBlocker(self.mode_widget):
            action = self.mode_widget.itemData(index)
            self.action_data.action_mode = action
            self._change_mode()

    def _exec_on_release_changed(self, value):
        self.action_data.exec_on_release = self.chkb_exec_on_release.isChecked()

    def _force_remote_output_changed(self, value):
        self.action_data.force_remote_output = self.chkb_force_remote_output.isChecked()
        
    def _force_remote_output_only_changed(self, value):
        self.action_data.force_remote_output_only = self.chkb_force_remote_output_only.isChecked()
                        

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
        # update the drop down
        with QtCore.QSignalBlocker(self.mouse_button_widget):
            index = self.mouse_button_widget.findData(self.action_data.button_id)
            self.mouse_button_widget.setCurrentIndex(index)



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
        self.action_data.motion_input = False
        show_button = False
        show_motion = False
        show_release = False
        show_click_mode = False

        if self.action_data.get_input_type() == InputType.JoystickButton:
            show_release = True

        action_mode = self.action_data.action_mode
        if action_mode == MouseAction.MouseButton:
            show_button = True
            if not self.action_data.button_id in [MouseButton.WheelDown, MouseButton.WheelUp]:
                show_click_mode = True
        elif action_mode == MouseAction.MouseMotion:
            show_motion = True

        self.action_data.motion_input = show_motion
        
            
        #show_motion = self.action_data.motion_input
        self.motion_widget.setVisible(show_motion)
        self.button_widget.setVisible(show_button)
        self.click_widget.setVisible(show_click_mode)
        self.chkb_exec_on_release.setVisible(show_release)

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


class MapToMouseExFunctor(gremlin.base_profile.AbstractFunctor):

    """Implements the functionality required to move a mouse cursor.

    This moves the mouse cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    # shared wiggle thread
    _wiggle_local_thread = None
    _wiggle_remote_thread = None
    _wiggle_local_stop_requested = False
    _wiggle_remote_stop_requested = False
    _mouse_controller = None


    def __init__(self, action):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action)

        self.action = action
        if not MapToMouseExFunctor._mouse_controller:
            MapToMouseExFunctor._mouse_controller = gremlin.sendinput.MouseController()
        
        self.input_type = action.input_type
        self.exec_on_release = action.exec_on_release
        self.action_mode = action.action_mode
    

    def process_event(self, event, value):
        ''' processes an input event - must return True on success, False to abort the input sequence '''

        #syslog.debug(f"Process mouse functor event: {self.action_mode.name}  {self.action.action_id} exec on release: {self.action.exec_on_release}")
        if self.input_type == InputType.JoystickButton:
            if self.action_mode == MouseAction.MouseWiggleOnLocal:
                # start the local wiggle thread
                if self.exec_on_release and not event.is_pressed:
                        self._wiggle_start(is_local=True)
                elif not self.exec_on_release and event.is_pressed:
                    self._wiggle_start(is_local=True)
                    
            elif self.action_mode == MouseAction.MouseWiggleOffLocal:
                if self.exec_on_release and not event.is_pressed:
                        self._wiggle_stop(is_local = True)
                elif not self.exec_on_release and event.is_pressed:
                    self._wiggle_stop(is_local=True)

            elif self.action_mode == MouseAction.MouseWiggleOnRemote:
                # start the local wiggle thread
                if self.exec_on_release and not event.is_pressed:
                    self._wiggle_start(is_remote=True)
                elif not self.exec_on_release and event.is_pressed:
                    self._wiggle_start(is_remote=True)
                    
            elif self.action_mode == MouseAction.MouseWiggleOffRemote:
                if self.exec_on_release and not event.is_pressed:
                    self._wiggle_stop(is_remote = True)
                elif not self.exec_on_release and event.is_pressed:
                    self._wiggle_stop(is_remote=True)
            
            elif self.action_mode == MouseAction.MouseMotion:
                if event.event_type == InputType.JoystickAxis:
                    self._perform_axis_motion(event, value)
                elif event.event_type == InputType.JoystickHat:
                    self._perform_hat_motion(event, value)
                else:
                    self._perform_button_motion(event, value)
            elif self.action_mode == MouseAction.MouseButton:
                if self.exec_on_release and not event.is_pressed:
                    self._perform_mouse_button(event, value)
                elif not self.exec_on_release and event.is_pressed:
                    self._perform_mouse_button(event, value)
        return True
    
    def get_state(self):
        ''' gets the control state '''
        (is_local, is_remote) = input_devices.remote_state.state
        if self.action.force_remote_output:
            is_remote = True
        if self.action.force_remote_output_only:
            # force remote only
            is_local = False
        return (is_local, is_remote)

    def _perform_mouse_button(self, event, value):
        assert self.action.motion_input is False
        (is_local, is_remote) = self.get_state()
        if self.action.button_id in [MouseButton.WheelDown, MouseButton.WheelUp]:
            if value.current:
                direction = -16
                if self.action.button_id == MouseButton.WheelDown:
                    direction = 16
                if is_local:
                    gremlin.sendinput.mouse_wheel(direction)
                if is_remote:
                    input_devices.remote_client.send_mouse_wheel(direction)
        elif self.action.button_id in [MouseButton.WheelLeft, MouseButton.WheelRight]:
            if value.current:
                direction = -16
                if self.action.button_id == MouseButton.WheelRight:
                    direction = 16
                if is_local:
                    gremlin.sendinput.mouse_h_wheel(direction)
                if is_remote:
                    input_devices.remote_client.send_mouse_h_wheel(direction)
        else:
            if self.action.click_mode == MouseClickMode.Normal:
                if value.current:
                    if is_local:
                        gremlin.sendinput.mouse_press(self.action.button_id)
                    if is_remote:
                        input_devices.remote_client.send_mouse_button(self.action.button_id.value, True)
                else:
                    if is_local:
                        gremlin.sendinput.mouse_release(self.action.button_id)
                    if is_remote:
                        input_devices.remote_client.send_mouse_button(self.action.button_id.value, False)
            elif self.action.click_mode == MouseClickMode.Press:
                if is_local:
                    gremlin.sendinput.mouse_press(self.action.button_id)
                if is_remote:
                    input_devices.remote_client.send_mouse_button(self.action.button_id.value, True)
            elif self.action.click_mode == MouseClickMode.Release:
                if is_local:
                    gremlin.sendinput.mouse_release(self.action.button_id)
                if is_remote:
                    input_devices.remote_client.send_mouse_button(self.action.button_id.value, False)


        

    def _perform_axis_motion(self, event, value):
        """Processes events destined for an axis.

        :param event the event triggering the code execution
        :param value the current value of the event chain
        """
        delta_motion = self.action.min_speed + abs(value.current) * \
                (self.action.max_speed - self.action.min_speed)
        delta_motion = math.copysign(delta_motion, value.current)
        delta_motion = 0.0 if abs(value.current) < 0.05 else delta_motion

        dx = delta_motion if self.action.direction == 90 else None
        dy = delta_motion if self.action.direction != 90 else None
        (is_local, is_remote) = self.get_state()
        if is_local:
            MapToMouseExFunctor._mouse_controller.set_absolute_motion(dx, dy)
        if is_remote:
            input_devices.remote_client.send_mouse_motion(dx, dy)

    def _perform_button_motion(self, event, value):
        (is_local, is_remote) = self.get_state()
        if event.is_pressed:
            if is_local:
                MapToMouseExFunctor._mouse_controller.set_accelerated_motion(
                    self.action.direction,
                    self.action.min_speed,
                    self.action.max_speed,
                    self.action.time_to_max_speed
                )
            if is_remote:
                input_devices.remote_client.send_mouse_acceleration(self.action.direction, self.action.min_speed, self.action.max_speed, self.action.time_to_max_speed)
     
        else:
            if is_local:
                MapToMouseExFunctor._mouse_controller.set_absolute_motion(0, 0)
            if is_remote:
                input_devices.remote_client.send_mouse_motion(0, 0)

    def _perform_hat_motion(self, event, value):
        """Processes events destined for a hat.

        :param event the event triggering the code execution
        :param value the current value of the event chain
        """
        (is_local, is_remote) = self.get_state()
        if value.current == (0, 0):
            if is_local:
                MapToMouseExFunctor._mouse_controller.set_absolute_motion(0, 0)
            if is_remote:
                input_devices.remote_client.send_mouse_motion(0, 0)

        else:
            a = rad2deg(math.atan2(-value.current[1], value.current[0])) + 90.0
            if is_local:
                MapToMouseExFunctor._mouse_controller.set_accelerated_motion(
                    a,
                    self.action.min_speed,
                    self.action.max_speed,
                    self.action.time_to_max_speed
                )
            if is_remote:
                input_devices.remote_client.send_mouse_acceleration(a, self.action.min_speed, self.action.max_speed, self.action.time_to_max_speed)


    def _wiggle_start(self, is_local = False, is_remote = False):
        ''' starts the wiggle thread, local or remote '''

        if is_local and not MapToMouseExFunctor._wiggle_local_thread:
            syslog.debug("Wiggle start local requested...")
            MapToMouseExFunctor._wiggle_local_stop_requested = False
            MapToMouseExFunctor._wiggle_local_thread = threading.Thread(target=MapToMouseExFunctor._wiggle_local)
            MapToMouseExFunctor._wiggle_local_thread.start()

        if is_remote and not MapToMouseExFunctor._wiggle_remote_thread:
            syslog.debug("Wiggle start remote requested...")
            MapToMouseExFunctor._wiggle_remote_stop_requested = False
            MapToMouseExFunctor._wiggle_remote_thread = threading.Thread(target=MapToMouseExFunctor._wiggle_remote)
            MapToMouseExFunctor._wiggle_remote_thread.start()

    def _wiggle_stop(self, is_local = False, is_remote = False):
        ''' stops the wiggle thread, local or remote '''

        if is_local and MapToMouseExFunctor._wiggle_local_thread:
            syslog.debug("Wiggle stop local requested...")
            MapToMouseExFunctor._wiggle_local_stop_requested = True
            MapToMouseExFunctor._wiggle_local_thread.join()
            syslog.debug("Wiggle thread local exited...")
            MapToMouseExFunctor._wiggle_local_thread = None

        if is_remote and MapToMouseExFunctor._wiggle_remote_thread:
            syslog.debug("Wiggle stop local requested...")
            MapToMouseExFunctor._wiggle_remote_stop_requested = True
            MapToMouseExFunctor._wiggle_remote_thread.join()
            syslog.debug("Wiggle thread remote exited...")
            MapToMouseExFunctor._wiggle_remote_thread = None

    @staticmethod
    def _wiggle_local():
        ''' wiggles the mouse '''
        syslog.debug("Wiggle local start...")
        msg = "local wiggle mode on"
        input_devices.remote_state.say(msg)

        t_wait = time.time()
        while not MapToMouseExFunctor._wiggle_local_stop_requested:
            if time.time() >= t_wait:
                syslog.debug("wiggling local...")
                MapToMouseExFunctor._mouse_controller.set_absolute_motion(1, 1)
                time.sleep(1)
                MapToMouseExFunctor._mouse_controller.set_absolute_motion(-1, -1)
                time.sleep(0.5)
                MapToMouseExFunctor._mouse_controller.set_absolute_motion(0, 0)
                t_wait = time.time() + random.uniform(10,40)
            time.sleep(0.5)
            
        syslog.debug("Wiggle local stop...")
        input_devices.remote_state.say("local wiggle mode off")



    @staticmethod
    def _wiggle_remote():
        ''' wiggles the mouse - remote clients'''
        syslog.debug("Wiggle remote start...")

        msg = "remote wiggle mode on"
        input_devices.remote_state.say(msg)

        t_wait = time.time()
        while not MapToMouseExFunctor._wiggle_remote_stop_requested:
            if time.time() >= t_wait:
                syslog.debug("wiggling remote...")
                input_devices.remote_client.send_mouse_motion(1, 1)
                time.sleep(1)
                input_devices.remote_client.send_mouse_motion(-1, -1)
                time.sleep(0.5)
                input_devices.remote_client.send_mouse_motion(0,0)
                t_wait = time.time() + random.uniform(10,40)
            time.sleep(0.5)
            
        syslog.debug("Wiggle remote stop...")
        input_devices.remote_state.say("remote wiggle mode off")
        

class MapToMouseEx(gremlin.base_profile.AbstractAction):

    """Action data for the map to mouse action.

    Map to mouse allows controlling of the mouse cursor using either a joystick
    or a hat.
    """

    name = "Map to Mouse EX"
    tag = "map_to_mouse_ex"

    default_button_activation = (True, True)
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MapToMouseExFunctor
    widget = MapToMouseExWidget

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

        self.action_mode = MouseAction.MouseButton
        self.exec_on_release = False
        self.force_remote_output = False
        self.force_remote_output_only = False

        self.input_type = InputType.JoystickButton

        self.click_mode = MouseClickMode.Normal


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

        self.action_mode = MouseAction.from_string(safe_read(node, "mode", str, "mousebutton"))

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

        # get the type of mapping this is
        
        if "exec_on_release" in node.attrib:
            self.exec_on_release = safe_read(node,"exec_on_release",bool, False)

        if "force_remote" in node.attrib:
            self.force_remote_output = safe_read(node,"force_remote_output",bool, False)

        if "remote_only" in node.attrib:
            self.force_remote_output_only = safe_read(node,"force_remote_output_only",bool, False)

        if "click_mode" in node.attrib:
            self.click_mode = MouseClickMode.from_string(safe_read(node,"click_mode", str, "normal"))


    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToMouseEx.tag)

        node.set("mode", self.action_mode.name)
        node.set("motion-input", safe_format(self.motion_input, bool))
        node.set("button-id", safe_format(self.button_id.value, int))
        node.set("direction", safe_format(self.direction, int))
        node.set("min-speed", safe_format(self.min_speed, int))
        node.set("max-speed", safe_format(self.max_speed, int))
        node.set("time-to-max-speed", safe_format(self.time_to_max_speed, float))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))
        node.set("force_remote_output", safe_format(self.force_remote_output, bool))
        node.set("force_remote_output_only", safe_format(self.force_remote_output_only, bool))
        node.set("click_mode", self.click_mode.name)

        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True


version = 1
name = "map_to_mouse_ex"
create = MapToMouseEx
