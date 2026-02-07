# -*- coding: utf-8; -*-

# MaptoMouseEx - enhanced version of MapToMouse

from __future__ import annotations
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
import psygnal
from psygnal import Signal
import gremlin.config
import gremlin.repeater
import gremlin.event_handler
import win32api, win32com, ctypes, win32gui
import gremlin.process
import gremlin.remote

import enum, threading,time, random

import gremlin.util
from shiboken6 import Shiboken

syslog = logging.getLogger("system")


class MapToMouseExWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to mouse motion or buttons."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, QtWidgets.QVBoxLayout, parent=parent)

    def _create(self, action_data):
        self.action_data : MapToMouseEx = action_data
        

    def _create_ui(self):
        """Creates the UI components."""
        # Layouts to use
        if not Shiboken.isValid(self):
            return
        self.mode_layout = QtWidgets.QHBoxLayout()

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QGridLayout(self.button_widget)
        self.motion_widget = QtWidgets.QWidget()
        self.motion_layout = QtWidgets.QGridLayout(self.motion_widget)
        self.release_widget = QtWidgets.QWidget()
        self.options_layout = QtWidgets.QHBoxLayout(self.release_widget)

        self.click_widget = QtWidgets.QWidget()
        self.click_options_layout = QtWidgets.QHBoxLayout(self.click_widget)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.execute_on_press, self.action_data.execute_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)


        self.mode_widget = gremlin.ui.ui_common.QDataComboBox()

        input_type = self.action_data.get_input_type()
        if input_type == InputType.JoystickAxis:
            actions = [MouseAction.MouseMotion]
            self.action_data.action_mode = MouseAction.MouseMotion # force motion for linear input
        else:
         actions = [MouseAction.MouseButton, MouseAction.MouseMotion, MouseAction.MousePosition]
        
        for mode in actions:
            self.mode_widget.addItem(MouseAction.to_name(mode), mode)

        index = self.mode_widget.findData(self.action_data.action_mode)
        if index != -1:
            self.mode_widget.setCurrentIndex(index) # sync correct mode
        else:
            self.action_data.action_mode = self.mode_widget.currentData() # force correct mode

        self.mode_widget.currentIndexChanged.connect(self._action_mode_changed)
        
        self.mode_label = QtWidgets.QLabel("Description")

        

        self.chkb_force_remote_output = QtWidgets.QCheckBox("Force Remote output")
        self.chkb_force_remote_output_only = QtWidgets.QCheckBox("Remote Only")

        self.chkb_force_remote_output.clicked.connect(self._force_remote_output_changed)
        self.chkb_force_remote_output_only.clicked.connect(self._force_remote_output_only_changed)

        
        
        
        self.mode_group = QtWidgets.QButtonGroup()
        self.mode_normal = QtWidgets.QRadioButton("Click")
        self.mode_double_click = QtWidgets.QRadioButton("Double-Click")
        self.mode_press = QtWidgets.QRadioButton("Press Only")
        self.mode_release = QtWidgets.QRadioButton("Release Only")

        self.mode_normal.clicked.connect(self._click_change_mode)
        self.mode_double_click.clicked.connect(self._click_change_mode)
        self.mode_press.clicked.connect(self._click_change_mode)
        self.mode_release.clicked.connect(self._click_change_mode)

        self.mode_group.addButton(self.mode_normal)
        self.mode_group.addButton(self.mode_double_click)
        self.mode_group.addButton(self.mode_press)
        self.mode_group.addButton(self.mode_release)


        self.click_options_layout.addWidget(self.mode_normal)
        self.click_options_layout.addWidget(self.mode_double_click)
        self.click_options_layout.addWidget(self.mode_press)
        self.click_options_layout.addWidget(self.mode_release)
        self.click_options_layout.addStretch()

        
        
        
        self.options_layout.addWidget(self.chkb_force_remote_output)
        self.options_layout.addWidget(self.chkb_force_remote_output_only)
        
        self.options_layout.addStretch()

        self.mode_layout.addWidget(self.mode_widget)
        self.mode_layout.addWidget(self.mode_label)
        self.mode_layout.addStretch()

        self.button_widget.hide()
        self.motion_widget.hide()



        self._monitor_selector_widget = gremlin.ui.ui_common.QDataComboBox(callback = self._handle_monitor_changed)

        
        self.x_widget = gremlin.ui.ui_common.QIntLineEdit(value = self.action_data.mouse_x,
                                                          max_range = None,
                                                          min_range = None,
                                                          callback = self._handle_mouse_x_changed
                                                    )
        self.y_widget = gremlin.ui.ui_common.QIntLineEdit(value = self.action_data.mouse_y,
                                                          max_range = None,
                                                          min_range = None,
                                                          callback = self._handle_mouse_y_changed
                                                        )        
        
        record_widget = gremlin.ui.ui_common.Buttons.getRecordWidget(callback = self._handle_mouse_position_record)

        center_widget = gremlin.ui.ui_common.QDataPushButton("Center", callback = self._handle_mouse_position_center)

        relative_widget = gremlin.ui.ui_common.QDataCheckbox("Position is relative to processs", 
                                                             value = self.action_data.process_position_relative,
                                                             callback = self._handle_process_relative_changed)
        self.focus_widget = gremlin.ui.ui_common.QDataCheckbox("Set focus to window", 
                                                        value = self.action_data.process_focus,
                                                        callback = self._handle_process_focus_changed)
      

        self.process_path_widget = gremlin.ui.ui_common.QProcessSelectorWidget(
                                                path = self.action_data.process_path,
                                                autostart=self.action_data.process_autostart,
                                                timeout = self.action_data.process_timeout,
                                                args = self.action_data.process_args,
                                                callback_path = self._handle_process_path_changed,
                                                callback_args = self._handle_process_args_changed,
                                                callback_autostart = self._handle_process_autostart_changed,
                                                callback_timeout = self._handle_process_timeout_changed,
                                                enable_autostart = True
                                                )
        

        widgets = [
            self.process_path_widget 
        ]

        self.container_process  = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)
        
        self.container_monitor = gremlin.ui.ui_common.getHContainer(self._monitor_selector_widget,"Monitor:", widget_only=True)

        widgets = [
            "Mouse position X:",
            self.x_widget,
            "Y:",
            self.y_widget,
            record_widget,
            center_widget
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        widgets = [
            relative_widget,
            self.focus_widget,
            self.container_process,
            widget,
            
        ]

        self.container_position = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)

     
        self.main_layout.addLayout(self.mode_layout)
        self.main_layout.addWidget(self._execute_widget)
        self.main_layout.addWidget(self.release_widget)
        self.main_layout.addWidget(self.button_widget)
        # self.main_layout.addWidget(wheel_factor_container)
        self.main_layout.addWidget(self.click_widget)
        self.main_layout.addWidget(self.motion_widget)

        self.main_layout.addWidget(self.container_monitor)
        self.main_layout.addWidget(self.container_position)
        self.main_layout.addWidget(self.container_process)
        


        # Create the different UI elements
        self._create_mouse_button_ui()
        if self.action_data.get_input_type() == InputType.JoystickAxis:
            self._create_axis_ui()
        else:
            self._create_button_hat_ui()

        self._populate_monitor_selector()
        self._update_ui()

    @QtCore.Slot(bool)
    def _handle_process_relative_changed(self, checked : bool):
        self.action_data.process_position_relative = checked
        self._update_ui()

    @QtCore.Slot(bool)
    def _handle_process_focus_changed(self, checked : bool):
        self.action_data.process_focus = checked

    def _handle_process_path_changed(self, value : str):
        self.action_data.process_path = value
    
    def _handle_process_args_changed(self, value : str):
        self.action_data.process_args = value

    def _handle_process_autostart_changed(self, value : bool):
        self.action_data.process_autostart = value

    def _handle_process_timeout_changed(self, value : float):
        self.action_data.process_timeout = value

 
    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.execute_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.execute_on_release = checked


    def _populate_monitor_selector(self):
        ''' loads the list of monitors and presents them in a drop down'''
        self._monitors = self.action_data.getMonitors()
        self._monitor_selector_widget.clear()
        for index, info in self._monitors.items():
            x,y,w,h = info["Work"]
            display_data : str = info["Device"]
            name = display_data.split("\\")[-1]
            stub = f"[{index}] {name} ({x:,} {y:,} {w:,} {h:,})"
            self._monitor_selector_widget.addItem(stub, index)

        index = self._monitor_selector_widget.findData(self.action_data.monitor_index)
        if index != -1:
            self._monitor_selector_widget.setCurrentIndex(index)
        else:
            self.action_data.monitor_index = self._monitor_selector_widget.currentData()

    def _update_ui(self):
        visible = self.action_data.action_mode == MouseAction.MousePosition
        self.container_monitor.setVisible(False) # disable monitor selection for now as it's not used
        self.container_position.setVisible(visible)

        visible = self.action_data.process_position_relative
        self.container_process.setVisible(visible)
        self.focus_widget.setEnabled(visible)


    def _handle_mouse_position_record(self, widget):
        ''' records the mouse position '''

        if self.action_data.process_position_relative:
            # verify the process is valid
            hwnd = self.action_data.getProcessWindowHwnd()
            if not hwnd and self.action_data.process_autostart:
                # attempt to autostart the process
                self.action_data.startProcess(self._handle_process_started)
                return 
            self._handle_process_started(True)


    def _handle_process_started(self, started : bool):        
        gremlin.util.InvokeUiMethod(self._handle_process_started_ui, started)

    def _handle_process_started_ui(self, started : bool):
        verbose = gremlin.config.Configuration().verbose_mode_mouse
        if verbose: syslog.info(f"MOUSE: profile start [{'OK' if started else 'FAIL'}]")
        if started:
            hwnd = self.action_data.getProcessWindowHwnd()
            if hwnd:
                self.dialog = gremlin.ui.ui_common.InputListenerWidget(
                        event_types= [InputType.Mouse],
                    )
                self.dialog.closed.connect(self._handle_listen_selection)
                self.dialog.show()
                return
            
        gremlin.ui.ui_common.MessageBoxWarning(prompt = "Process window was not found.  Ensure the window is available.")

        
    def _handle_listen_selection(self, accepted):
        if accepted:
            gremlin.util.InvokeUiMethod(self._handle_listen_selection_ui)

    def _handle_listen_selection_ui(self):        
        # input was not canceled
        verbose = gremlin.config.Configuration().verbose_mode_mouse
        x,y = self.dialog.getMousePosition()
        if self.action_data.process_position_relative:
            # convert the mouse position to a position relative to the dialog
            hwnd = self.action_data.getProcessWindowHwnd()
            if hwnd:
                rx,ry = win32gui.ScreenToClient(hwnd, (x,y))
                if verbose: syslog.info(f"MOUSE: position: {x} {y}, relative to window: {rx} {ry}")
                x,y = rx, ry
        else:
            if verbose: syslog.info(f"MOUSE: position: {x} {y}")
        
        self.x_widget.setValue(x)
        self.y_widget.setValue(y)
        

    def _handle_mouse_position_center(self, widgeT):
        ''' center for the curent monitor selection  '''
        info = self._monitors[self.action_data.monitor_index]
        x,y,w,h = info["Work"]
        cx = (x + w) /2
        cy = (y + h) / 2
        self.x_widget.setValue(cx)
        self.y_widget.setValue(cy)

    @QtCore.Slot(int)
    def _handle_mouse_x_changed(self, value : int):
        self.action_data.mouse_x = value
    
    @QtCore.Slot(int)
    def _handle_mouse_y_changed(self, value : int):
        self.action_data.mouse_y = value

    @QtCore.Slot(int)
    def _handle_monitor_changed(self, value : int):
        self.action_data.monitor_index = value

        
        

    
    @QtCore.Slot(int)
    def _handle_wheel_factor_changed(self, value : int):
        self.action_data.wheel_factor = value

    def _click_change_mode(self):
        if self.mode_normal.isChecked():
            self.action_data.click_mode = MouseClickMode.Normal
        elif self.mode_press.isChecked():
            self.action_data.click_mode = MouseClickMode.Press
        elif self.mode_release.isChecked():
            self.action_data.click_mode = MouseClickMode.Release
        elif self.mode_double_click.isChecked():
            self.action_data.click_mode = MouseClickMode.DoubleClick

    def _create_axis_ui(self):
        """Creates the UI for axis setups."""
        self.x_axis = QtWidgets.QRadioButton("X Axis")
        self.x_axis.setChecked(True)
        self.y_axis = QtWidgets.QRadioButton("Y Axis")
        self.invert_widget = QtWidgets.QCheckBox("Invert")
        self.invert_widget.clicked.connect(self._invert_cb)

        self.motion_layout.addWidget(
            QtWidgets.QLabel("Control"),
            0,
            0,
            QtCore.Qt.AlignLeft
        )
        self.motion_layout.addWidget(self.x_axis, 0, 1, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(self.y_axis, 0, 2, 1, 2, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(self.invert_widget, 0, 3, 1, 2, QtCore.Qt.AlignLeft)

        self.min_speed = QtWidgets.QSpinBox()
        self.min_speed.setRange(0, 1e5)
        self.max_speed = QtWidgets.QSpinBox()
        self.max_speed.setRange(0, 1e5)
        self.motion_layout.addWidget(QtWidgets.QLabel("Minimum speed"), 1, 0, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(self.min_speed, 1, 1, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(QtWidgets.QLabel("Maximum speed"), 1, 2, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(self.max_speed, 1, 3, QtCore.Qt.AlignLeft)
        self.motion_layout.addWidget(QtWidgets.QLabel(" "), 0, 4)
        self.motion_layout.setColumnStretch(4,2)

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


        self.mouse_button_widget = gremlin.ui.ui_common.QDataComboBox()
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


        action_mode = self.action_data.action_mode
        index = self.mode_widget.findData(action_mode)
        if index != -1 and self.mode_widget.currentIndex != index:
            with QtCore.QSignalBlocker(self.mode_widget):
                self.mode_widget.setCurrentIndex(index)

        
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
        elif click_mode == MouseClickMode.DoubleClick:
            with QtCore.QSignalBlocker(self.mode_double_click):
                self.mode_double_click.setChecked(True)

        self._change_mode()


    def _populate_axis_ui(self):
        """Populates axis UI elements with data."""
        self._disconnect_axis()
        if self.action_data.direction == 90:
            self.x_axis.setChecked(True)
        else:
            self.y_axis.setChecked(True)
        self.invert_widget.setChecked(self.action_data.invert)

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

    @QtCore.Slot(bool)
    def _invert_cb(self, checked : bool):
        self.action_data.invert = checked



    @QtCore.Slot()
    def _change_mouse_button_cb(self):
        ''' mouse event drop down selected '''
        self.action_data.button_id = self.mouse_button_widget.currentData()
        self.mouse_button.setText(
            gremlin.types.MouseButton.to_string(self.action_data.button_id)
        )

    @QtCore.Slot(int)
    def _action_mode_changed(self, index):
        ''' called when the action mode drop down value changes '''
        with QtCore.QSignalBlocker(self.mode_widget):
            action = self.mode_widget.itemData(index)
            self.action_data.action_mode = action
            self._change_mode()
        self._update_ui()

    @QtCore.Slot(bool)
    def _exec_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked

    @QtCore.Slot(bool)
    def _force_remote_output_changed(self, checked : bool):
        self.action_data.force_remote_output = checked
        
    @QtCore.Slot(bool)
    def _force_remote_output_only_changed(self, checked : bool):
        self.action_data.force_remote_output_only = checked
                        

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
        gremlin.util.InvokeUiMethod(self._update_mouse_button_ui, event)

    def _update_mouse_button_ui(self, event):
        ''' mouse event - runs on UI thread'''
        if isinstance(event, list):
            key = event.pop()
            self.action_data.button_id = key.mouse_button
        else:
            self.action_data.button_id = event.identifier
        self.mouse_button.setText(gremlin.types.MouseButton.to_string(self.action_data.button_id))
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



    def __init__(self, action : MapToMouseEx, parent = None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)

        self.action_data : MapToMouseEx = action
        self.input_type = action.get_input_type()
        
        
        self.click_mode = action.click_mode
        self.dx = 0 # current mouse motion = x axis
        self.dy = 0 # current mouse motion = y axis
        
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_mouse
        self.verbose_extra = self.verbose and config.verbose_mode_extra

    def profile_start(self):
        ''' occurs on profile start '''
        pass

    def profile_stop(self):
        ''' occurs on profile stop '''
        pass
    


    

    def process_event(self, event, value, extra_data = None):
        ''' processes an input event - must return True on success, False to abort the input sequence '''

        
        trigger = self.action_data.execute_on_press and event.is_pressed or \
                  self.action_data.execute_on_release and not event.is_pressed
        
        match self.action_data.action_mode:
            case MouseAction.MouseMotion:
                # handle motion requests
                if trigger:
                    match event.event_type:
                        case InputType.JoystickAxis: 
                            self._perform_axis_motion(event, value)
                        case InputType.JoystickHat: 
                            self._perform_hat_motion(event, value) 
                        case InputType.JoystickButton:
                            self._perform_button_motion(event, value)
                
            case MouseAction.MouseButton:
                self._perform_mouse_button(event, value, wheel_factor = self.action_data.wheel_factor)

            case MouseAction.MousePosition:
                if trigger:
                    self._perform_mouse_position(self.action_data.mouse_x, self.action_data.mouse_y)

        return True
    
    def get_state(self):
        ''' gets the control state '''
        (is_local, is_remote) = gremlin.remote.remote_state.state
        if self.action_data.force_remote_output:
            is_remote = True
        if self.action_data.force_remote_output_only:
            # force remote only
            is_local = False
        return (is_local, is_remote)

    def _perform_mouse_button(self, event, value, wheel_factor = 1):
        assert self.action_data.motion_input is False
        verbose = gremlin.config.Configuration().verbose_mode_mouse
        (is_local, is_remote) = self.get_state()
        match self.action_data.button_id:
            case MouseButton.WheelDown | MouseButton.WheelUp:
                if value.current:
                    direction = -wheel_factor
                    if self.action_data.button_id == MouseButton.WheelDown:
                        direction = wheel_factor
                    if verbose: syslog.info(f"MOUSE: send wheel up/dn [{direction}]")
                    if is_local:
                        gremlin.sendinput.mouse_wheel(direction)
                    if is_remote:
                        gremlin.remote.remote_client.send_mouse_wheel(direction)
            case MouseButton.WheelLeft | MouseButton.WheelRight:
                if value.current:
                    direction = -wheel_factor
                    if self.action_data.button_id == MouseButton.WheelRight:
                        direction = wheel_factor
                    if verbose: syslog.info(f"MOUSE: send wheel l/r [{direction}]")
                    if is_local:
                        gremlin.sendinput.mouse_h_wheel(direction)
                    if is_remote:
                        gremlin.remote.remote_client.send_mouse_h_wheel(direction)
            case _:
                match self.action_data.click_mode:
                    case MouseClickMode.Normal:
                        if value.current:
                            if verbose: syslog.info(f"MOUSE: press button [{self.action_data.button_id}]")
                            if is_local:
                                gremlin.sendinput.mouse_press(self.action_data.button_id)
                            if is_remote:
                                gremlin.remote.remote_client.send_mouse_button(self.action_data.button_id.value, True)
                        else:
                            if verbose: syslog.info(f"MOUSE: release button [{self.action_data.button_id}]")
                            if is_local:
                                gremlin.sendinput.mouse_release(self.action_data.button_id)
                            if is_remote:
                                gremlin.remote.remote_client.send_mouse_button(self.action_data.button_id.value, False)

                    case MouseClickMode.DoubleClick:
                        if value.current:
                            if verbose: syslog.info(f"MOUSE: press dclick button [{self.action_data.button_id}]")
                            if is_local:
                                gremlin.sendinput.mouse_press_double_click(self.actiaction_dataon.button_id)    
                            if is_remote:
                                gremlin.remote.remote_client.send_mouse_button_double_click(self.action_data.button_id.value, True)
                        else:
                            if verbose: syslog.info(f"MOUSE: release dclick button [{self.action_data.button_id}]")
                            if is_local:
                                gremlin.sendinput.mouse_release(self.action_data.button_id)
                            if is_remote:
                                gremlin.remote.remote_client.send_mouse_button(self.action_data.button_id.value, False)                        

                    case MouseClickMode.Press:
                        if verbose: syslog.info(f"MOUSE: press button [{self.action_data.button_id}]")
                        if is_local:
                            gremlin.sendinput.mouse_press(self.action_data.button_id)
                        if is_remote:
                            gremlin.remote.remote_client.send_mouse_button(self.action_data.button_id.value, True)

                    case MouseClickMode.Release:
                        if verbose: syslog.info(f"MOUSE: release button [{self.action_data.button_id}]")
                        if is_local:
                            gremlin.sendinput.mouse_release(self.action_data.button_id)
                        if is_remote:
                            gremlin.remote.remote_client.send_mouse_button(self.action_data.button_id.value, False)


    def _perform_mouse_position(self, x :int, y : int):
        ''' sets the mouse position '''
        verbose = gremlin.config.Configuration().verbose_mode_mouse
        if self.action_data.process_position_relative:
            # relative to process
            hwnd = self.action_data.getProcessWindowHwnd() # get process window
            if not hwnd:
                # window not found
                if self.action_data.process_autostart:
                    # attemp to start the process
                    self.target_point = (x, y)
                    self.action_data.startProcess(self._handle_process_started)
                    # further action handled by the callback
                    return 
            
                syslog.warning("MOUSE: set position failed - process/window not found.")       
                return
            
            # convert local coords to global coords
            x, y = win32gui.ClientToScreen(hwnd, (x,y))
            if self.action_data.process_focus:
                if verbose: syslog.info(f"MOUSE: set focus to [{hwnd}]")
                gremlin.process.ProcessHelper().setFocus(hwnd)
        
        if verbose: syslog.info(f"MOUSE: set position: {x} {y}")
        win32api.SetCursorPos((x, y))

    def _handle_process_started(self, started : bool):
        ''' callback on process start request '''
        verbose = gremlin.config.Configuration().verbose_mode_mouse
        if verbose: syslog.info(f"MOUSE: profile start [{'OK' if started else 'FAIL'}]")
        if started:
            # convert local coords to global coords
            hwnd = self.action_data.getProcessWindowHwnd()
            x, y = win32gui.ClientToScreen(hwnd, self.target_point)
            if self.action_data.process_focus:
                if verbose: syslog.info(f"MOUSE: set focus to [{hwnd}]")
                gremlin.process.ProcessHelper().setFocus(hwnd)
                
            if verbose: syslog.info(f"MOUSE: set position: {x} {y}")
            win32api.SetCursorPos((x, y))

     

    def _perform_axis_motion(self, event, value):
        """Processes events destined for an axis.

        :param event the event triggering the code execution
        :param value the current value of the event chain
        """
        verbose = gremlin.config.Configuration().verbose_mode_mouse
        raw_value = event.curve_value
        value = abs(raw_value)
        is_x = self.action_data.direction == 90

        mc = gremlin.sendinput.MouseController()
        deadzone = self.action_data.deadzone

        if value <= deadzone:
            # this only sets the value that isn't none
            if is_x:
                mc.set_absolute_motion(0,None)
            else:
                mc.set_absolute_motion(None, 0)
            return

        if self.action_data.invert:
            # invert the input
            inverted_value = gremlin.util.scale_to_range(value, invert=True)
            value = inverted_value
        
        # determine the mouse motion
        motion_value = abs(value) # 0..1
        delta_motion = gremlin.util.scale_to_range(motion_value,
                                                   source_min= deadzone,
                                                   source_max = 1,
                                                   target_min=self.action_data.min_speed,
                                                   target_max=self.action_data.max_speed)

        delta_motion = math.copysign(delta_motion, raw_value)

        if is_x:
            if verbose: syslog.info(f"MOUSE: x motion [{delta_motion}]")
            mc.set_absolute_motion(delta_motion, None)
        else:
            if verbose: syslog.info(f"MOUSE: y motion [{delta_motion}]")
            mc.set_absolute_motion(None, delta_motion)



    def _perform_button_motion(self, event, value):
        (is_local, is_remote) = self.get_state()
        mc = gremlin.sendinput.MouseController()    
        if event.is_pressed:
            if is_local:
                mc.set_accelerated_motion(
                    self.action_data.direction,
                    self.action_data.min_speed,
                    self.action_data.max_speed,
                    self.actiaction_dataon.time_to_max_speed
                )
                
            if is_remote:
                gremlin.remote.remote_client.send_mouse_acceleration(self.action_data.direction,
                                                                    self.action_data.min_speed,
                                                                    self.action_data.max_speed,
                                                                    self.action_data.time_to_max_speed)
     
        else:
            if is_local:
                mc.set_absolute_motion(0, 0)
            if is_remote:
                gremlin.remote.remote_client.send_mouse_motion(0, 0)

    def _perform_hat_motion(self, event, value):
        """Processes events destined for a hat.

        :param event the event triggering the code execution
        :param value the current value of the event chain
        """
        (is_local, is_remote) = self.get_state()
        mc = gremlin.sendinput.MouseController()    
        if value.current == (0, 0):
            if is_local:
                mc.set_absolute_motion(0, 0)
            if is_remote:
                gremlin.remote.remote_client.send_mouse_motion(0, 0)

        else:
            a = rad2deg(math.atan2(-value.current[1], value.current[0])) + 90.0
            if is_local:
                mc.set_accelerated_motion(
                    a,
                    self.action_data.min_speed,
                    self.action_data.max_speed,
                    self.action_data.time_to_max_speed
                )
            if is_remote:
                gremlin.remote.remote_client.send_mouse_acceleration(a,
                                                                    self.action_data.min_speed,
                                                                    self.action_data.max_speed,
                                                                    self.action_data.time_to_max_speed)



class MapToMouseEx(gremlin.base_profile.AbstractAction):

    """Action data for the map to mouse action.

    Map to mouse allows controlling of the mouse cursor using either a joystick
    or a hat.
    """

    name = "Map to Mouse EX"
    tag = "map_to_mouse_ex"
    hint = '''Sends mouse data (enhanced).
Note: Map to Keyboard Ex can also be used to send mouse button and wheel data.'''
    
    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    # input_types = [
    #      InputType.JoystickButton,
    #      InputType.JoystickHat,
    #      InputType.JoystickAxis
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
        # invert motion
        self.invert = False
        # repeat interval for pulses when moving the mouse
        self.repeat_interval = -1 # disabled
        # pulse delay
        self.delay = 0.250
        # deadzone in percent
        self.deadzone = 0.01

        self.wheel_factor = 1 # factor for wheel motion

        # exact mouse position option
        self.monitor_index = 1 # monitor index for exact mouse position set
        self.mouse_x = 0
        self.mouse_y = 0
        self.process_path = None # if specified, the mouse position will be relative to the window of the given process if found
        self.process_args = None # args for autostart process
        self.process_autostart = False # true if process should autostart if not running (no window)
        self.process_timeout = 5.0 # timeout to wait for a process to autostart and get a window
        self.process_focus = True # true if the focus should be set to the target window

        self.process_position_relative : bool = False # true if the position is relative to a specific process window

        if self.get_input_type() == InputType.JoystickAxis:
            self.action_mode = MouseAction.MouseMotion
        else:
            self.action_mode = MouseAction.MouseButton

        self.execute_on_press = True # true if macro executes on input press/change
        self.execute_on_release = False # true if macro executs on input release
        
        self.force_remote_output = False
        self.force_remote_output_only = False

        self.click_mode = MouseClickMode.Normal

        
    def startProcess(self, callback):
        '''
        Docstring for startProcess
        :param callback: callback(bool) called when the process has started, true means ok, false means not started
        '''

        pm = gremlin.process.ProcessHelper()
        pm.executeProcess(self.process_path, callback = callback, args = self.process_args)


    def display_name(self):
        ''' returns a display string for the current configuration '''
        if self.motion_input:
            return f"Map to Mouse Ex: (motion) angle: [{self.direction}] speed: [{self.min_speed}] [{self.max_speed}] TTMS: [{self.time_to_max_speed:0.3f}] invert: [{self.invert}]"    
        else:
            return f"Map to Mouse Ex: (button) [{self.button_id.name}] Mode: [{self.click_mode.name}] Exec on press: [{self.execute_on_press}] Exec on release: [{self.execute_on_release}]"
        

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "mdi.mouse"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        # Need virtual buttons for button inputs on axes and hats
        if self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]:
            return not self.motion_input
        return False

    def _parse_xml(self, node, data = None, extra_data = None):
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
            syslog.warning(f"Invalid mouse identifier in profile: {e:}")
            self.button_id = gremlin.types.MouseButton.Left

        self.direction = safe_read(node, "direction", int, 0)
        self.min_speed = safe_read(node, "min-speed", int, 5)
        self.max_speed = safe_read(node, "max-speed", int, 5)
        self.time_to_max_speed = safe_read(node, "time-to-max-speed", float, 0.0)
        self.execute_on_press = True # true if macro executes on input press/change
        self.execute_on_release = False # true if macro executs on input release
     
        

        # get the type of mapping this is
        
        if "exec_on_release" in node.attrib:
            self.exec_on_release = safe_read(node,"exec_on_release",bool, False)

        if "force_remote" in node.attrib:
            self.force_remote_output = safe_read(node,"force_remote_output",bool, False)

        if "remote_only" in node.attrib:
            self.force_remote_output_only = safe_read(node,"force_remote_output_only",bool, False)

        if "click_mode" in node.attrib:
            self.click_mode = MouseClickMode.from_string(safe_read(node,"click_mode", str, "normal"))

        if "invert" in node.attrib:
            self.invert = safe_read(node,"invert",bool, False)

        self.wheel_factor = safe_read(node,"wheel-factor",int, 1)     

        if "x" in node.attrib:
            self.mouse_x = safe_read(node,"x", int, 0)
        if "y" in node.attrib:
            self.mouse_y = safe_read(node,"y", int, 0)


        if "execute-on-press" in node.attrib:
            self.execute_on_press = safe_read(node,"execute-on-press",bool,True)

        # legacy
        if "exec_on_release" in node.attrib:
            self.execute_on_release = safe_read(node,"exec_on_release",bool,True)            
            
        if "execute-on-release" in node.attrib:
            self.execute_on_release = safe_read(node,"execute-on-release",bool,True)     

        if "target-process" in node.attrib:
            self.process_path = node.get("target-process")
        
        self.process_autostart = safe_read(node,"process-autostart",bool, False)

        if "process-args" in node.attrib:
            args = node.get("process-args")
            if args:
                self.process_args = args

        self.profile_timeout = safe_read(node,"process-timeout", float, 5.0)
        self.process_position_relative = safe_read(node,"position-relative", bool, False)
        self.process_focus = safe_read(node,"process-focus", bool, True)



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
        
        node.set("force_remote_output", safe_format(self.force_remote_output, bool))
        node.set("force_remote_output_only", safe_format(self.force_remote_output_only, bool))
        node.set("click_mode", self.click_mode.name)
        node.set("invert", safe_format(self.invert, bool))
        node.set("wheel-factor", safe_format(self.wheel_factor, int))
        node.set("x", safe_format(self.mouse_x, int))
        node.set("y", safe_format(self.mouse_y, int))
        if self.process_path:
            node.set("target-process", self.process_path)
        if self.process_args:
            node.set("process-args", self.process_args)
        node.set("process-autostart", safe_format(self.process_autostart, bool))
        node.set("process-timeout", safe_format(self.process_timeout, float))
        node.set("position-relative", safe_format(self.process_position_relative, bool))
        node.set("process-focus", safe_format(self.process_focus, bool))


        node.set("execute-on-press",safe_format(self.execute_on_press, bool))
        node.set("execute-on-release",safe_format(self.execute_on_release, bool))
        

        return node
    

    def getMonitors(self):
        ''' gets list of connected monitors indexed by the monitor index (1 based)'''
        # Enumerate all displays
        monitor_list = win32api.EnumDisplayMonitors()
        monitors = {}
        for index, item in enumerate(monitor_list):
            hmonitor = item[0]
            info = win32api.GetMonitorInfo(hmonitor)
            
            #monitors = [win32api.GetMonitorInfo(hmonitor) for hmonitor in win32api.EnumDisplayMonitors()]
            monitors[index+1] = info
        return monitors
    
    def getProcessWindowHwnd(self):
        ''' gets the window handle for the given process '''
        pm = gremlin.process.ProcessHelper()
        return pm.getProcessWindowHwnd(self.process_path)

        


    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True

    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        table = ReportTable(cellpadding=4)    

        if self.action_mode == MouseAction.MousePosition:
            table.addField("Set position", f"{self.direction}")
            table.addField("X", f"{self.mouse_x}")
            table.addField("Y", f"{self.mouse_y}")
        else:
            if self.motion_input:
                # motion
                table.addField("Direction", f"{self.direction}")
                table.addField("Min Speed", f"{self.min_speed}")
                table.addField("Max Speed", f"{self.max_speed}")
                table.addField("Time to speed", f"{self.time_to_max_speed:0.3f} s")
                if self.invert:
                    table.addField("Invert", "Yes")
            else:
                table.addField("Button", f"{self.button_id.value}")
                table.addField("Click Mode", self.click_mode.name)

        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()
    
version = 1
name = "map_to_mouse_ex"
create = MapToMouseEx
