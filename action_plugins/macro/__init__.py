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
import collections
from lxml import etree as ElementTree

import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.macro
from gremlin.profile import safe_format, safe_read, parse_guid, write_guid

from gremlin.input_devices import VjoyAction
from gremlin.keyboard import key_from_code, key_from_name
import gremlin.base_profile
from PySide6 import QtWidgets, QtCore, QtGui
import os
import time
import gremlin.util
import gremlin.ui.state_device
import gremlin.ui.ui_common
import gremlin.keyboard
import gremlin.joystick_handling
import gremlin.input_devices
import gremlin.config
import gremlin.macro_handler
import psygnal
from psygnal import Signal
from shiboken6 import Shiboken

syslog = logging.getLogger("system")


class AbstractRepeatMacroWidget(QtWidgets.QWidget):

    """Abstract base class for all repeat UI widgets."""

    def __init__(self, data, parent=None):
        """Creates a new instance.

        :param data the data shown and managed by the widget
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.data = data
        self.main_layout = QtWidgets.QGridLayout(self)

        self._create_ui()
        self._populate_ui()

    def _create_ui(self):
        """Creates the UI components."""
        raise gremlin.error.MissingImplementationError(
            "AbstractRepeatMacroWidget::_create_ui not implemented in subclass"
        )

    def _populate_ui(self):
        """Populates the UI components."""
        raise gremlin.error.MissingImplementationError(
            "AbstractRepeatMacroWidget::_populate_ui not "
            "implemented in subclass"
        )

    def _update_data(self):
        """Updates the managed data based on the UI contents."""
        raise gremlin.error.MissingImplementationError(
            "AbstractRepeatMacroWidget::_populate_ui not "
            "implemented in subclass"
        )


class CountRepeatMacroWidget(AbstractRepeatMacroWidget):

    """Repeat UI to specify a number of times to repeat a macro."""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.delay = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.delay.setMaximum(3600)
        self.delay.setSingleStep(0.1)
        self.delay.setValue(0.1)

        self.count = QtWidgets.QSpinBox()
        self.count.setMaximum(1e9)
        self.count.setSingleStep(1)
        self.count.setValue(1)

        self.main_layout.addWidget(QtWidgets.QLabel("Delay"), 0, 0)
        self.main_layout.addWidget(self.delay, 0, 1)
        self.main_layout.addWidget(QtWidgets.QLabel("Count"), 1, 0)
        self.main_layout.addWidget(self.count, 1, 1)

    def _populate_ui(self):
        self.delay.setValue(self.data.delay)
        self.count.setValue(self.data.count)

        self.delay.valueChanged.connect(self._update_data)
        self.count.valueChanged.connect(self._update_data)

    def _update_data(self):
        self.data.delay = self.delay.value()
        self.data.count = self.count.value()



class MacroListView(QtWidgets.QListView):

    """Implements a specialized list view.

    The purpose of this class is to properly emit a "clicked" event when
    the selected index is changed via keyboard interaction. In addition to
    this the view also handles item deletion via the keyboard.

    The reason this is needed is that for some reason the correct way,
    i.e. using the QItemSelectionModel signals is not working.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # enable multiple selection
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)

    def keyPressEvent(self, evt):
        """Process key events.

        :param evt the keyboard event
        """
        # Check if the active index changed, and if so emit the clicked signal
        old_index = self.currentIndex()
        super().keyPressEvent(evt)
        new_index = self.currentIndex()
        if old_index.row() != new_index.row():
            self.clicked.emit(new_index)

        # Handle deleting entries via the keyboard
        if evt.matches(QtGui.QKeySequence.Delete):
            self.model().remove_entry(new_index.row())
            if new_index.row() >= self.model().rowCount():
                new_index = self.model().index(
                    self.model().rowCount()-1,
                    0,
                    QtCore.QModelIndex()
                )
            self.setCurrentIndex(new_index)
            self.clicked.emit(new_index)


class ToggleRepeatMacroWidget(AbstractRepeatMacroWidget):

    """Repeat UI for a toggle repetition."""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.delay = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.delay.setMaximum(3600)
        self.delay.setSingleStep(0.1)
        self.delay.setValue(0.1)

        self.main_layout.addWidget(QtWidgets.QLabel("Delay"), 0, 0)
        self.main_layout.addWidget(self.delay, 0, 1)

    def _populate_ui(self):
        self.delay.setValue(self.data.delay)
        self.delay.valueChanged.connect(self._update_data)

    def _update_data(self):
        self.data.delay = self.delay.value()


class MacroActionEditor(QtWidgets.QWidget):

    """Widget displaying macro action settings and permitting their change."""

    ActionTypeData = collections.namedtuple(
        "ActionTypeData",
        ["name", "create_ui", "action_type"]
    )

    locked = False

    def __init__(self, model, index, parent=None):
        """Creates a new editor widget.

        :param model the model storing the content
        :param index the index of the model entry being edited
        :param parent the parent of this widget
        """
        
        super().__init__(parent)
        self.model = model
        self.index = index
        

        self.action_types = {
            "Joystick": MacroActionEditor.ActionTypeData(
                "Joystick",
                self._joystick_ui,
                gremlin.macro.JoystickAction
            ),
            "Keyboard": MacroActionEditor.ActionTypeData(
                "Keyboard",
                self._keyboard_ui,
                gremlin.macro.KeyAction
            ),
            "Mouse Button": MacroActionEditor.ActionTypeData(
                "Mouse Button",
                self._mouse_button_ui,
                gremlin.macro.MouseButtonAction
            ),
            "Mouse Motion": MacroActionEditor.ActionTypeData(
                "Mouse Motion",
                self._mouse_motion_ui,
                gremlin.macro.MouseMotionAction
            ),
            "Pause": MacroActionEditor.ActionTypeData(
                "Pause",
                self._pause_ui,
                gremlin.macro.PauseAction
            ),
            "vJoy": MacroActionEditor.ActionTypeData(
                "vJoy",
                self._vjoy_ui,
                gremlin.macro.VJoyMacroAction
            ),
            "Remote Control": MacroActionEditor.ActionTypeData(
                "Remote Control",
                self._remote_control_ui,
                gremlin.macro.RemoteControlAction
            ),
            "State" : MacroActionEditor.ActionTypeData(
                "State",
                self._state_ui,
                gremlin.macro.StateAction
            ),
        }


        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)

        
        self.main_layout.addWidget(QtWidgets.QLabel("Action Settings"))
        self.main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.group_box, self.group_layout = gremlin.ui.ui_common.getVContainer()

        
        self.main_layout.addWidget(self.group_box)

        self.blank_label = QtWidgets.QLabel("Please add an action.")
        self.main_layout.addWidget(self.blank_label)


        self.ui_elements = {}
        self._create_ui()
        self._populate_ui()

    def hook(self, widget):
        widget.rightPanelResize.connect(self._handle_panel_resize)

    def _handle_panel_resize(self, width):
        if Shiboken.isValid(self):
            self.setFixedWidth(width)

    def _create_ui(self):
        """Creates the editor UI."""
        if not Shiboken.isValid(self):
            return

        if MacroActionEditor.locked:
            return
        
        try:
            MacroActionEditor.locked = True

            self.action_selector = gremlin.ui.ui_common.QDataComboBox(auto_adjust=True)
            for action_name in sorted(self.action_types):
                self.action_selector.addItem(action_name)
            self.action_selector.currentTextChanged.connect(self._change_action)

            widget = gremlin.ui.ui_common.getHContainer(self.action_selector, "Step Action:", widget_only = True)
            self.group_layout.addWidget(widget)
            self.group_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())

            self.action_layout = QtWidgets.QVBoxLayout()
            self.group_layout.addLayout(self.action_layout)
            
        finally:
            MacroActionEditor.locked = False

    def _populate_ui(self):
        """Populate the UI elements with data from the model."""
        if not Shiboken.isValid(self):
            return
        
        # ensure there's a selected item in the model
        if self.model.rowCount() == 0:
            # no entries in the list
            self.group_box.setVisible(False)
            self.blank_label.setVisible(True)
            return
        
        # at least one entry in the list
        self.group_box.setVisible(True)
        self.blank_label.setVisible(False)
        
        self.action_selector.currentTextChanged.disconnect(self._change_action)

        entry = self.model.get_entry(self.index.row())
        for data in self.action_types.values():
            if isinstance(entry, data.action_type):
                self.action_selector.setCurrentText(data.name)
                data.create_ui()

        self.action_selector.currentTextChanged.connect(self._change_action)

    def _change_action(self, value):
        """Handle changing the action type.

        :param value the name of the new action type for the currently selected
            entry
        """
        
        # Clear the current editor widget ui components
        gremlin.ui.ui_common.clear_layout(self.action_layout)
        self.ui_elements = {}

        # Update the model data to match the new type
        if value == "Joystick":
            self.model.set_entry(
                gremlin.macro.JoystickAction(
                    0,
                    InputType.JoystickButton,
                    1,
                    True
                ),
                self.index.row()
            )
        elif value == "Keyboard":
            self.model.set_entry(
                gremlin.macro.KeyAction(
                    key_from_name("enter"),
                    True
                ),
                self.index.row()
            )
        elif value == "Mouse Button":
            self.model.set_entry(
                gremlin.macro.MouseButtonAction(
                    gremlin.types.MouseButton.Left,
                    True
                ),
                self.index.row()
            )
        elif value == "Mouse Motion":
            self.model.set_entry(
                gremlin.macro.MouseMotionAction(0, 0),
                self.index.row()
            )
        elif value == "Pause":
            self.model.set_entry(
                gremlin.macro.PauseAction(0.2),
                self.index.row()
            )
        elif value == "vJoy":
            self.model.set_entry(
                gremlin.macro.VJoyMacroAction(
                    1,
                    InputType.JoystickButton,
                    1,
                    True
                ),
                self.index.row()
            )
        elif value == "Remote Control":
            self.model.set_entry(gremlin.macro.RemoteControlAction(), self.index.row())
        elif value == "State":
            self.model.set_entry(gremlin.macro.StateAction(), self.index.row())


        # Update the UI elements
        self._update_model()
        self.action_types[value].create_ui()

    def _joystick_ui(self):
        """Creates and populates the JoystickAction editor UI."""
        action = self.model.get_entry(self.index.row())
        if action is None:
            return
        
        virtual_only = isinstance(action, gremlin.macro.VJoyMacroAction)

        self.ui_elements["input_label"] = QtWidgets.QLabel("Input")
        self.ui_elements["input_button"] = gremlin.ui.ui_common.NoKeyboardPushButton("Select...")
        self.ui_elements["input_button"].setToolTip("Select the output device")
        self.ui_elements["input_button"].clicked.connect(
            lambda: self._request_user_input([
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ], virtual_only)
        )

        self._create_joystick_inputs_ui(action)

        self.action_layout.addWidget(self.ui_elements["input_label"])
        widget = gremlin.ui.ui_common.getHContainer(self.ui_elements["input_button"], widget_only = True)
        self.action_layout.addWidget(widget)

    def _keyboard_ui(self):
        """Creates and populates the KeyAction editor UI."""

        config = gremlin.config.Configuration()
        action = self.model.get_entry(self.index.row())
        if action is None or action.key is None:
            return
        self.ui_elements["key_label"] = QtWidgets.QLabel("Key")
        self.ui_elements["key_input"] = \
            gremlin.ui.ui_common.NoKeyboardPushButton(action.key.name)
        self.ui_elements["key_input"].clicked.connect(
            lambda: self._request_user_input([InputType.Keyboard])
        )
        self.ui_elements["key_press"] = QtWidgets.QRadioButton("Press")
        self.ui_elements["key_release"] = QtWidgets.QRadioButton("Release")
        
        if action.is_pressed:
            self.ui_elements["key_press"].setChecked(True)
        else:
            self.ui_elements["key_release"].setChecked(True)

        self.ui_elements["key_press"].toggled.connect(self._modify_key_state)
        self.ui_elements["key_release"].toggled.connect(self._modify_key_state)

        self.ui_elements["key_add_press"] = gremlin.ui.ui_common.QDataPushButton("Add Press", data = action)
        self.ui_elements["key_add_press"].clicked.connect(self._add_key_press)
        
        self.ui_elements["key_add_release"] = gremlin.ui.ui_common.QDataPushButton("Add Release", data = action)
        self.ui_elements["key_add_release"].clicked.connect(self._add_key_release)

        delay_widget = gremlin.ui.ui_common.QIntLineEdit()
        delay_widget.setRange(0, 20000)
        delay_widget.setValue(config.macro_key_delay)
        delay_widget.valueChanged.connect(self._key_delay_changed)

        add_widget = gremlin.ui.ui_common.QDataPushButton("Add Press/Delay/Release", data = action)
        add_widget.clicked.connect(self._add_key_full)
        
        container = gremlin.ui.ui_common.getHContainer((delay_widget, add_widget),"Delay (ms):", widget_only = True)

        self.ui_elements["key_container"] = container
        self.ui_elements["key_delay"] = delay_widget

        self.action_layout.addWidget(self.ui_elements["key_label"])
        self.action_layout.addWidget(self.ui_elements["key_input"])
        self.action_layout.addWidget(self.ui_elements["key_press"])
        self.action_layout.addWidget(self.ui_elements["key_release"])

        widget = gremlin.ui.ui_common.getHContainer((self.ui_elements["key_add_press"], self.ui_elements["key_add_release"]), widget_only = True)
        self.action_layout.addWidget(widget)
        self.action_layout.addWidget(container)


    @QtCore.Slot()
    def _key_delay_changed(self):
        value = self.ui_elements["key_delay"].value()
        gremlin.config.Configuration().macro_key_delay = value

    def _mouse_button_ui(self):
        """Creates and populates the MouseAction editor UI."""
        action = self.model.get_entry(self.index.row())
        if action is None:
            return

        self.ui_elements["mouse_label"] = QtWidgets.QLabel("Mouse Button")
        self.ui_elements["mouse_input"] = \
            gremlin.ui.ui_common.NoKeyboardPushButton(
                gremlin.types.MouseButton.to_string(action.button)
            )
        self.ui_elements["mouse_input"].clicked.connect(
            lambda: self._request_user_input([InputType.Mouse])
        )
        self.ui_elements["mouse_press"] = QtWidgets.QRadioButton("Press")
        self.ui_elements["mouse_release"] = QtWidgets.QRadioButton("Release")

        # Mouse wheel directions cannot be pressed or released, as such they
        # are set to "press" with the inputs disabled
        if action.button in [
            gremlin.types.MouseButton.WheelDown,
            gremlin.types.MouseButton.WheelUp
        ]:
            self.ui_elements["mouse_press"].setChecked(True)
            self.ui_elements["mouse_press"].setEnabled(False)
            self.ui_elements["mouse_release"].setChecked(False)
            self.ui_elements["mouse_release"].setEnabled(False)
        else:
            if action.is_pressed:
                self.ui_elements["mouse_press"].setChecked(True)
            else:
                self.ui_elements["mouse_release"].setChecked(True)

            self.ui_elements["mouse_press"].toggled.connect(
                self._modify_mouse_button
            )
            self.ui_elements["mouse_release"].toggled.connect(
                self._modify_mouse_button
            )

        self.action_layout.addWidget(self.ui_elements["mouse_label"])
        self.action_layout.addWidget(self.ui_elements["mouse_input"])
        self.action_layout.addWidget(self.ui_elements["mouse_press"])
        self.action_layout.addWidget(self.ui_elements["mouse_release"])

    def _mouse_motion_ui(self):
        self.ui_elements["dx_label"] = QtWidgets.QLabel("Change in X")
        self.ui_elements["dx_spinbox"] = QtWidgets.QSpinBox()
        self.ui_elements["dx_spinbox"].setRange(-1e5, 1e5)
        self.ui_elements["dx_spinbox"].setValue(0)
        self.ui_elements["dy_label"] = QtWidgets.QLabel("Change in Y")
        self.ui_elements["dy_spinbox"] = QtWidgets.QSpinBox()
        self.ui_elements["dy_spinbox"].setRange(-1e5, 1e5)
        self.ui_elements["dy_spinbox"].setValue(0)

        # Populate boxes with values
        if self.model.get_entry(self.index.row()) is not None:
            self.ui_elements["dx_spinbox"].setValue(
                self.model.get_entry(self.index.row()).dx
            )
        if self.model.get_entry(self.index.row()) is not None:
            self.ui_elements["dy_spinbox"].setValue(
                self.model.get_entry(self.index.row()).dy
            )

        self.ui_elements["dx_spinbox"].valueChanged.connect(
            self._modify_mouse_motion
        )
        self.ui_elements["dy_spinbox"].valueChanged.connect(
            self._modify_mouse_motion
        )

        self.action_layout.addWidget(self.ui_elements["dx_label"])
        self.action_layout.addWidget(self.ui_elements["dx_spinbox"])
        self.action_layout.addWidget(self.ui_elements["dy_label"])
        self.action_layout.addWidget(self.ui_elements["dy_spinbox"])

    def _pause_ui(self):
        """Creates and populates the PauseAction editor UI."""


        self.ui_elements["duration_label"] = QtWidgets.QLabel("Duration")
        self.ui_elements["duration_spinbox"] = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.ui_elements["duration_spinbox"].setSingleStep(0.1)
        self.ui_elements["duration_spinbox"].setMaximum(3600)

        self.ui_elements["duration_is_random"] = QtWidgets.QCheckBox("Random")

        self.ui_elements["duration_max_label"] = QtWidgets.QLabel("Max duration (0 to disable)")

        self.ui_elements["duration_spinbox_max"] = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.ui_elements["duration_spinbox_max"].setSingleStep(0.1)
        self.ui_elements["duration_spinbox_max"].setMaximum(3600)

        widgets = []
        widget = gremlin.ui.ui_common.QDataPushButton("250",0.25,tooltip = "250 ms")
        widget.clicked.connect(self._set_delay)
        widgets.append(widget)
        widget = gremlin.ui.ui_common.QDataPushButton("500",0.5,tooltip = "500 ms")
        widget.clicked.connect(self._set_delay)
        widgets.append(widget)
        widget = gremlin.ui.ui_common.QDataPushButton("750",0.75,tooltip = "750 ms")
        widget.clicked.connect(self._set_delay)
        widgets.append(widget)
        widget = gremlin.ui.ui_common.QDataPushButton("1",1.0,tooltip = "1 second")
        widget.clicked.connect(self._set_delay)
        widgets.append(widget)



        duration = 0.5
        duration_max = 0
        is_random = False
        if self.model.get_entry(self.index.row()) is not None:
            model : gremlin.macro.PauseAction = self.model.get_entry(self.index.row()) # PauseAction model
            duration = model.duration
            duration_max = model.duration_max
            is_random = model.is_random

    

        self.ui_elements["duration_spinbox"].setValue(duration)
        self.ui_elements["duration_spinbox"].valueChanged.connect(self._update_pause)

        self.ui_elements["duration_spinbox_max"].setValue(duration_max)
        self.ui_elements["duration_spinbox_max"].valueChanged.connect(self._update_pause_max)

        self.ui_elements["duration_is_random"].setChecked(is_random)
        self.ui_elements["duration_is_random"].clicked.connect(self._update_pause_is_random)


        self.action_layout.addWidget(self.ui_elements["duration_is_random"])
        self.action_layout.addWidget(self.ui_elements["duration_label"])
        widget, layout = gremlin.ui.ui_common.getHContainer(widgets)
        self.action_layout.addWidget(widget)
        
        widget, layout = gremlin.ui.ui_common.getHContainer(self.ui_elements["duration_spinbox"],"Pause (seconds):")
        self.action_layout.addWidget(widget)
        self.action_layout.addWidget(self.ui_elements["duration_max_label"])
        self.action_layout.addWidget(self.ui_elements["duration_spinbox_max"])

    @QtCore.Slot()
    def _set_delay(self):
        widget = self.sender()
        delay = widget.data
        self.ui_elements["duration_spinbox"].setValue(delay)
        #self._update_pause(delay)


    def _vjoy_ui(self):
        """Creates and populates the vJoyAction editor UI."""

        if MacroActionEditor.locked:
            return
        
        action = self.model.get_entry(self.index.row())
        if action is None:
            return
        
        try:

            MacroActionEditor.locked = True
            
            if not "vjoy_selector" in self.ui_elements:
                # vJoy input selection
                self.ui_elements["vjoy_selector"] = gremlin.ui.ui_common.VJoySelector(
                    self._modify_vjoy,
                    [
                        InputType.JoystickAxis,
                        InputType.JoystickButton,
                        InputType.JoystickHat
                    ]
                )


            self.action_layout.addWidget(self.ui_elements["vjoy_selector"])

            
            self.ui_elements["vjoy_selector"].set_selection(
                action.input_type,
                action.vjoy_id,
                action.input_id
            )

            self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())

            self._create_joystick_inputs_ui(action)

            self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())

            # listen button
            listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback = self._handle_listen_request)

            self.action_layout.addWidget(listen_widget)
                    
                    
                


        finally:
            MacroActionEditor.locked = False

    def _handle_listen_request(self):
        ''' calls up a listen box to select the input '''
        dialog = gremlin.ui.ui_common.InputListenerWidget(
                return_kb_event = True,
                callback = self._handle_listen_selection,
                virtual_only = True
            )
        
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()
    
        dialog.setGeometry(
                int(geom.x() + geom.width() / 2 - 150),
                int(geom.y() + geom.height() / 2 - 75),
                300,
                150
            )
        
        dialog.show()

    def _handle_listen_selection(self, event):
        gremlin.util.InvokeUiMethod(self._handle_listen_selection_ui, event)

    def _handle_listen_selection_ui(self, event):
        dev = gremlin.joystick_handling.device_info_from_guid(event.device_guid)
        if not dev.is_virtual:
            return
        self._modify_joystick(event)
          


    def _create_joystick_inputs_ui(self, action):
        ''' creates the joystick macro UI when joystick is the selected type '''
        import gremlin.joystick_handling
        if hasattr(action,"device_guid"):
            device = gremlin.joystick_handling.device_info_from_guid(action.device_guid)
        elif hasattr(action, "vjoy_id"):
            device = gremlin.joystick_handling.vjoy_info_from_vjoy_id(action.vjoy_id)
            
        if device:
                
            if action.input_type == InputType.JoystickAxis:

                self.ui_elements["axis_reverse"] = QtWidgets.QCheckBox("Reverse")
                self.ui_elements["axis_absolute"] = QtWidgets.QRadioButton("Absolute")
                self.ui_elements["axis_relative"] = QtWidgets.QRadioButton("Relative")

                if action.axis_type == "absolute":
                    self.ui_elements["axis_absolute"].setChecked(True)
                    self.ui_elements["axis_relative"].setChecked(False)
                elif action.axis_type == "relative":
                    self.ui_elements["axis_absolute"].setChecked(False)
                    self.ui_elements["axis_relative"].setChecked(True)
                
                self.ui_elements["axis_absolute"].clicked.connect(
                    self._modify_vjoy_axis
                )
                self.ui_elements["axis_relative"].clicked.connect(
                    self._modify_vjoy_axis
                )                

                self.ui_elements["axis_value"] = gremlin.ui.ui_common.QFloatLineEdit()
                self.ui_elements["axis_value"].valueChanged.connect(self._modify_axis_state)
                self.ui_elements["axis_value"].setValue(action.value)

                axis_name = gremlin.joystick_handling.get_axis_name(action.input_id)
                widget = QtWidgets.QLabel(f"{device.name} Axis {action.input_id} {axis_name}")
                self.action_layout.addWidget(widget)

                self.action_layout.addWidget(self.ui_elements["axis_reverse"])

                widget, _= gremlin.ui.ui_common.getHContainer([
                            self.ui_elements["axis_absolute"],
                            self.ui_elements["axis_relative"]
                            ],"Type:")

                self.action_layout.addWidget(widget)


                widget = gremlin.ui.ui_common.getHContainer(self.ui_elements["axis_value"],"Set Value:", widget_only = True)
                self.action_layout.addWidget(widget)
                

            elif action.input_type == InputType.JoystickButton:
                if not "button_press" in self.ui_elements.keys():
                    self.ui_elements["button_press"] = gremlin.ui.ui_common.QDataRadioButton("Press", data = "press", callback = self._modify_button_state)
                    self.ui_elements["button_release"] = gremlin.ui.ui_common.QDataRadioButton("Release", data = "release", callback = self._modify_button_state)
                    self.ui_elements["button_toggle"] = gremlin.ui.ui_common.QDataRadioButton("Toggle", data = "toggle", callback = self._modify_button_state)
                    if isinstance(action.value, bool):
                        action.value = "press" if action.value else "release"
                    
                    match action.value:
                        case "press":
                            self.ui_elements["button_press"].setChecked(True)
                        case "release":
                            self.ui_elements["button_release"].setChecked(True)
                        case "toggle":
                            self.ui_elements["button_toggle"].setChecked(True)
                        case _:
                            # default if changing from a different value type
                            action.value = "press"
                            self.ui_elements["button_press"].setChecked(True)

                    widget = QtWidgets.QLabel(f"{device.name} Button [{action.input_id}]")
                    self.action_layout.addWidget(widget)
                    self.action_layout.addWidget(self.ui_elements["button_press"])
                    self.action_layout.addWidget(self.ui_elements["button_release"])
                    self.action_layout.addWidget(self.ui_elements["button_toggle"])


            elif action.input_type == InputType.JoystickHat:
                if not "hat_direction" in self.ui_elements.keys():
                    self.ui_elements["hat_direction"] = gremlin.ui.ui_common.QComboBox()
                    directions = [
                        "Center", "North", "North East", "East", "South East",
                        "South", "South West", "West", "North West"
                    ]
                    for val in directions:
                        self.ui_elements["hat_direction"].addItem(val)
                    self.ui_elements["hat_direction"].currentTextChanged.connect(
                        self._modify_hat_state
                    )
                    hat_direction = (0, 0)
                    if isinstance(action.value, tuple):
                        hat_direction = action.value
                    self.ui_elements["hat_direction"].setCurrentText(
                        gremlin.common.direction_tuple_lookup[hat_direction]
                    )
                    widget = QtWidgets.QLabel(f"{device.name} Hat [{action.input_id}]")
                    self.action_layout.addWidget(widget)
                    self.action_layout.addWidget(self.ui_elements["hat_direction"])


    def _remote_control_ui(self):
        self.ui_elements["remote_control_cb_label"] = QtWidgets.QLabel("Remote control command:") 
        cb = gremlin.ui.ui_common.QComboBox()
        self.ui_elements["remote_control_cb"] = cb
        self.ui_elements["remote_control_label"] = QtWidgets.QLabel()
        commands = [
            VjoyAction.VJoyEnableLocalOnly, 
            VjoyAction.VJoyEnableRemoteOnly,
            VjoyAction.VJoyDisableLocal, 
            VjoyAction.VJoyEnableLocal, 
            VjoyAction.VJoyEnableRemote, 
            VjoyAction.VJoyDisableRemote, 
            VjoyAction.VJoyEnableLocalAndRemote,
        ]
         
        for cmd in commands:
            cb.addItem(VjoyAction.to_name(cmd), cmd)


        self.ui_elements["remote_control_label"].setText(VjoyAction.to_description(commands[0]))
        cb.currentIndexChanged.connect(self._modify_remote_control)

        self.action_layout.addWidget(self.ui_elements["remote_control_cb_label"])
        self.action_layout.addWidget(cb)
        self.action_layout.addWidget(self.ui_elements["remote_control_label"])

    def _state_ui(self):
        action = self.model.get_entry(self.index.row())
        self.state_selector = gremlin.ui.ui_common.QComboBox(width=None)
        self.state_selector.currentIndexChanged.connect(self._state_changed)
        self.state_description_widget = QtWidgets.QLabel()
        widget,layout = gremlin.ui.ui_common.getHContainer(["State:", self.state_selector])
        self.action_layout.addWidget(widget)
        widget,layout = gremlin.ui.ui_common.getHContainer(["Description:", self.state_description_widget])
        self.action_layout.addWidget(widget)

        widgets = []
        rb = gremlin.ui.ui_common.QDataRadioButton("Press",data = (action, "press"))
        rb.setToolTip("Sets the state")
        if action.value is None:
            action.action = "press"
        if action.action == "press":
            rb.setChecked(True)
        rb.clicked.connect(self._state_mode_changed)
        widgets.append(rb)
        self.ui_elements["state_press"] = rb
        
        rb = gremlin.ui.ui_common.QDataRadioButton("Release",data = (action, "release"))
        rb.setToolTip("Releases the state")
        if action.action == "release":
            rb.setChecked(True)
        rb.clicked.connect(self._state_mode_changed)
        widgets.append(rb)
        self.ui_elements["state_release"] = rb

        rb = gremlin.ui.ui_common.QDataRadioButton("Toggle", data = (action, "toggle"))
        rb.setToolTip("Toggles the state")
        if action.action == "toggle":
            rb.setChecked(True)
        rb.clicked.connect(self._state_mode_changed)
        widgets.append(rb)
        self.ui_elements["state_toggle"] = rb


        widget, layout = gremlin.ui.ui_common.getVContainer(widgets,"Action:")
        self.action_layout.addWidget(widget)

        self.populate_state_selector(action)

    @QtCore.Slot()
    def _state_mode_changed(self):
        widget = self.sender()
        action, value = widget.data
        action.action = value
        self._update_model()

    def populate_state_selector(self, action):
        ''' updates the available states '''
        import gremlin.ui.state_device
        with QtCore.QSignalBlocker(self.state_selector):
            self.state_selector.clear()
            sd = gremlin.ui.state_device.StateData()
            items = sd.getStates().items()
            if items:
                for key, state in items:
                    self.state_selector.addItem(key, (action, state)) # store the associated action and the state
                state = action.state
                key = action.state.key if state else None
                if key:
                    index = self.state_selector.findText(key)
                    if index >= 0:
                        self.state_selector.setCurrentIndex(index)
                else:
                    _, action.state = self.state_selector.currentData()
                    
                if self.state_selector.count():
                    action, state = self.state_selector.currentData()
                    self.setStateDescription(state.description)

    def setStateDescription(self, value):
        self.state_description_widget.setText(value if value else "n/a")

    @QtCore.Slot()
    def _state_changed(self):
        verbose = gremlin.config.Configuration().verbose_mode_macro
        action, state = self.state_selector.currentData() # data field contains the MacroAction the state applies to, and the state
        self.setStateDescription(state.description)
        action.state = state
        if verbose: syslog.info(f"MACRO: set state [{state.key}] for entry [{action.id}]")
        self._update_model()


    @QtCore.Slot(bool)
    def _modify_button_state(self, state):
        widget = self.sender()
        action = self.model.get_entry(self.index.row())
        action.value = widget.data
        self._update_model()

    @QtCore.Slot(bool)
    def _modify_axis_state(self, state):
        action = self.model.get_entry(self.index.row())
        action.value = self.ui_elements["axis_value"].value()
        self._update_model()

    @QtCore.Slot(bool)
    def _modify_hat_state(self, state):
        action = self.model.get_entry(self.index.row())
        action.value = gremlin.common.direction_tuple_lookup[state]
        self._update_model()

 

    @QtCore.Slot(bool)
    def _modify_key_state(self, state):
        """Updates the key activation state, i.e. press or release of a key.

        :param state the radio button state
        """
        action = self.model.get_entry(self.index.row())
        action.is_pressed = self.ui_elements["key_press"].isChecked()
        self._update_model()

    @QtCore.Slot(bool)
    def _modify_mouse_button(self, state):
        action = self.model.get_entry(self.index.row())
        action.is_pressed = self.ui_elements["mouse_press"].isChecked()
        self._update_model()

    
    def _modify_mouse_motion(self, _):
        action = self.model.get_entry(self.index.row())
        action.dx = self.ui_elements["dx_spinbox"].value()
        action.dy = self.ui_elements["dy_spinbox"].value()
        self._update_model()

    def _update_pause(self, value):
        """Update the model data when editor changes occur.

        :param value the pause duration in seconds
        """
        self.model.get_entry(self.index.row()).duration = value
        self._update_model()

    def _update_pause_max(self, value):
        """Update the model data when editor changes occur.

        :param value the pause max duration in seconds
        """
        self.model.get_entry(self.index.row()).duration_max= value
        self._update_model()

    def _update_pause_is_random(self, data):
        """Update the model data when editor changes occur.

        :param value the pause random function
        """
        self.model.get_entry(self.index.row()).is_random= self.ui_elements["duration_is_random"].isChecked()
        self._update_model()


    def _modify_remote_control(self, index):
        ''' occurs when the remote control command changes '''
        command = self.ui_elements["remote_control_cb"].itemData(index)
        self.ui_elements["remote_control_label"].setText(gremlin.input_devices.VjoyAction.to_description(command))
        self.model.get_entry(self.index.row()).command = command
        self._update_model()


    def _update_model(self):
        """Forces an update of the model at the current index."""
        self.model.update(self.index)

    def _request_user_input(self, input_types, virtual_only = False):
        """Prompts the user for the input to bind to this item."""
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        import gremlin.joystick_handling
        import gremlin.ui.ui_common

        
        if InputType.Keyboard in input_types:
            dialog = InputKeyboardDialog(parent = self, select_single=True, index = -1)
            dialog.accepted.connect(self._keyboard_dialog_cb)
            dialog.setModal(True)
            dialog.showNormal()
        elif InputType.Mouse in input_types:
            dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Mouse],
            return_kb_event=False
            )
            dialog.closed.connect(self._handle_mouse_button_selected)
            root = self
            while root.parent():
                root = root.parent()
            geom = root.geometry()

            dialog.setGeometry(
                int(geom.x() + geom.width() / 2 - 150),
                int(geom.y() + geom.height() / 2 - 75),
                300,
                150
            )
            dialog.show()

            
        else:

            
            config = gremlin.config.Configuration()
            device_id = config.macro_last_device_id
            dev = gremlin.joystick_handling.device_info_from_guid(device_id) if device_id else None
            input_type = config.macro_last_input_type if dev else None
            input_id = config.macro_last_input_id if dev else None
            


            dialog = gremlin.ui.ui_common.QJoystickSelectorDialog(
                default_device = dev,
                default_input_type = input_type,
                default_input_id = input_id,
                virtual_only = virtual_only
                )
            
            dialog.dialog_closed.connect(self._handle_input_selected)


            self.button_press_dialog = dialog
            dialog.exec()

    def _handle_mouse_button_selected(self, accepted):
        if accepted:
            dialog = self.sender()
            if dialog.selection:
                key = dialog.selection[0]
                mouse_button = gremlin.types.MouseButton(key.mouse_button)
                self.model.set_entry(
                    gremlin.macro.MouseButtonAction(mouse_button, True),
                    self.index.row()
                )
                self._update_model()
                gremlin.ui.ui_common.clear_layout(self.action_layout)
                self.ui_elements = {}
                self._mouse_button_ui()

    def _handle_input_selected(self, dialog):
        ''' occurs when macro input selection is made '''
        if dialog.selectedData:
            dev, input_type, input_id = dialog.selectedData
            if dev is not None and input_type is not None and input_id is not None:
                self.model.set_entry(
                        gremlin.macro.JoystickAction(
                            dev.device_guid,
                            input_type,
                            input_id,
                            0.0
                        ),
                        self.index.row()
                    )
                
                self._update_model()
                gremlin.ui.ui_common.clear_layout(self.action_layout)
                self.ui_elements = {}
                self._joystick_ui()

                config = gremlin.config.Configuration()
                config.macro_last_device_id = dev.device_id
                config.macro_last_input_type = input_type
                config.macro_last_input_id = input_id





    def _keyboard_dialog_cb(self):
        ''' callled when the dialog completes '''

        
        # grab a new data index as this is a new entry
        # index = self._keyboard_dialog.index
        # keys = self._keyboard_dialog.keys
        dialog = self.sender()
        latched_key = dialog.latched_key
        self.model.get_entry(self.index.row()).key = latched_key
        self._update_model()
        gremlin.ui.ui_common.clear_layout(self.action_layout)
        self.ui_elements = {}
        self._keyboard_ui()

    @QtCore.Slot()
    def _add_key_press(self):
        
        key = self.model.get_entry(self.index.row()).key
        new_key = key.duplicate()
        entry = gremlin.macro.KeyAction(new_key,True)
        self.model.add_entry(self.index.row(), entry)


    @QtCore.Slot()
    def _add_key_full(self):
        
        key = self.model.get_entry(self.index.row()).key
        

        # key press
        new_key = key.duplicate()
        entry = gremlin.macro.KeyAction(new_key, False)
        self.model.add_entry(self.index.row(), entry)

        # pause
        delay = gremlin.config.Configuration().macro_key_delay
        entry = gremlin.macro.PauseAction(delay/1000) # to ms
        self.model.add_entry(self.index.row(), entry)

        # key release
        new_key = key.duplicate()
        entry = gremlin.macro.KeyAction(new_key, True)
        self.model.add_entry(self.index.row(), entry)



    @QtCore.Slot()
    def _add_key_release(self):
        
        key = self.model.get_entry(self.index.row()).key
        new_key = key.duplicate()
        entry = gremlin.macro.KeyAction(new_key,False)
        self.model.add_entry(self.index.row(), entry)


    def _modify_joystick(self, event):
        gremlin.util.InvokeUiMethod(self._modify_joystick_ui, event)

    def _modify_joystick_ui(self, event):
        ''' runs on UI thread '''
        self.model.set_entry(
            gremlin.macro.JoystickAction(
                event.device_guid,
                event.event_type,
                event.identifier,
                event.value
            ),
            self.index.row()
        )
        self._update_model()
        gremlin.ui.ui_common.clear_layout(self.action_layout)
        self.ui_elements = {}
        self._joystick_ui()

    def _modify_key(self, key):
        gremlin.util.InvokeUiMethod(self._modify_key_ui, key)

    def _modify_key_ui(self, key):
        """Changes which key is mapped.

        :param event the event containing information about the key to use
        """

        self.model.get_entry(self.index.row()).key = key # gremlin.keyboard.KeyMap.from_event(event)
        self._update_model()
        gremlin.ui.ui_common.clear_layout(self.action_layout)
        self.ui_elements = {}
        self._keyboard_ui()

    def _modify_mouse(self, key):
        gremlin.util.InvokeUiMethod(self._modify_mouse_ui, key)

    def _modify_mouse_ui(self, key):
        entry = self.model.get_entry(self.index.row())
        mouse_button = gremlin.types.MouseButton(key.mouse_button)
        entry.button = mouse_button # event.identifier
        self._update_model()
        gremlin.ui.ui_common.clear_layout(self.action_layout)
        self.ui_elements = {}
        self._mouse_button_ui()

    def _modify_vjoy(self, data):
        action = self.model.get_entry(self.index.row())
        action.vjoy_id = data["device_id"]
        action.input_type = data["input_type"]
        action.input_id = data["input_id"]

        if action.input_type == InputType.JoystickAxis:
            action.value = 0.0
        elif action.input_type == InputType.JoystickButton:
            action.value = True
        elif action.input_type == InputType.JoystickHat:
            action.value = (0, 0)

        self._update_model()
        gremlin.ui.ui_common.clear_layout(self.action_layout)
        self.ui_elements = {}
        self._vjoy_ui()

    @QtCore.Slot(object)
    def _modify_vjoy_axis(self, data):
        action = self.model.get_entry(self.index.row())
        action.axis_type = "absolute"
        if self.ui_elements["axis_relative"].isChecked():
            action.axis_type = "relative"
        self._update_model()

    @QtCore.Slot()
    def _modify_vjoy_value(self):
        action = self.model.get_entry(self.index.row())
        action.value = self.ui_elements["axis_value"]
        self._update_model()



class HoldRepeatMacroWidget(AbstractRepeatMacroWidget):

    """Repeat UI for a hold repetition."""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.delay = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.delay.setMaximum(3600)
        self.delay.setSingleStep(0.1)
        self.delay.setValue(0.1)

        self.main_layout.addWidget(QtWidgets.QLabel("Delay"), 0, 0)
        self.main_layout.addWidget(self.delay, 0, 1)

    def _populate_ui(self):
        self.delay.setValue(self.data.delay)
        self.delay.valueChanged.connect(self._update_data)

    def _update_data(self):
        self.data.delay = self.delay.value()


class MacroSettingsWidget(gremlin.ui.ui_common.QContentWidget):

    """Widget presenting macro settings."""

    # Lookup tables mapping between display name and enum name
    name_to_widget = {
        "Count": CountRepeatMacroWidget,
        "Toggle": ToggleRepeatMacroWidget,
        "Hold": HoldRepeatMacroWidget
    }
    name_to_storage = {
        "Count": gremlin.macro.CountRepeat,
        "Toggle": gremlin.macro.ToggleRepeat,
        "Hold": gremlin.macro.HoldRepeat
    }
    storage_to_name = {
        gremlin.macro.CountRepeat: "Count",
        gremlin.macro.ToggleRepeat: "Toggle",
        gremlin.macro.HoldRepeat: "Hold"
    }

    def __init__(self, action_data, parent=None):
        """Creates a new UI widget instance.

        :param action_data the data presented by the UI
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.data = action_data
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.group_box = gremlin.ui.ui_common.QGroupBox("Macro Settings")
        self.group_layout = QtWidgets.QVBoxLayout()
        self.group_layout.setContentsMargins(0,0,0,0)
        self.group_box.setLayout(self.group_layout)
        self.main_layout.addWidget(self.group_box)

        self._create_ui()

    def _create_ui(self):
        """Creates the UI elements"""
        if not Shiboken.isValid(self):
            return
        # Create UI elements
        self.exclusive_checkbox = QtWidgets.QCheckBox("Exclusive")
        self.force_remote_checkbox = QtWidgets.QCheckBox("Remote Only")
        self.repeat_dropdown = gremlin.ui.ui_common.QDataComboBox(auto_adjust=True)
        self.repeat_dropdown.addItems(["None", "Count", "Toggle", "Hold"])
        self.repeat_widget = None
        self.container_repeat_widget, self.container_repeat_layout = gremlin.ui.ui_common.getVContainer()

        if type(self.data.repeat) in MacroSettingsWidget.storage_to_name:
            mode_name = MacroSettingsWidget.storage_to_name[type(self.data.repeat)]
            self.repeat_widget = MacroSettingsWidget.name_to_widget[mode_name](self.data.repeat)

        # Populate UI elements
        self.exclusive_checkbox.setChecked(self.data.exclusive)
        self.force_remote_checkbox.setChecked(self.data.force_remote)
        if self.data.repeat is not None:
            mode_name = MacroSettingsWidget.storage_to_name[
                type(self.data.repeat)
            ]
            self.repeat_widget = MacroSettingsWidget.name_to_widget[mode_name](
                self.data.repeat
            )
            self.repeat_dropdown.setCurrentText(mode_name)

        # Connect signals
        self.exclusive_checkbox.clicked.connect(self._update_settings)
        self.force_remote_checkbox.clicked.connect(self._update_settings)
        self.repeat_dropdown.currentTextChanged.connect(self._update_settings)

        # Place UI elements
        widget = gremlin.ui.ui_common.getHContainer([self.exclusive_checkbox, self.force_remote_checkbox], widget_only = True)
        self.group_layout.addWidget(widget)

        widget = gremlin.ui.ui_common.getHContainer(self.repeat_dropdown, "Repeat Mode:", widget_only = True)
        self.group_layout.addWidget(widget)

        self.group_layout.addWidget(self.container_repeat_widget)
        
        if self.repeat_widget is not None:
            widget = gremlin.ui.ui_common.getHContainer(self.repeat_widget, widget_only = True)
            self.container_repeat_layout.addWidget(widget)

    def _update_settings(self, value = None):
        """Updates the action data based on UI content.

        :param value the value of a change (ignored)
        """
        self.data.exclusive = self.exclusive_checkbox.isChecked()
        self.data.force_remote = self.force_remote_checkbox.isChecked()

        # Only create a new repeat widget if it changed
        widget_type = MacroSettingsWidget.name_to_widget.get(
            self.repeat_dropdown.currentText(),
            None
        )
        storage_type = MacroSettingsWidget.name_to_storage.get(
            self.repeat_dropdown.currentText(),
            None
        )
        if widget_type is None and self.repeat_widget is not None:

            gremlin.util.clear_layout(self.container_repeat_layout)
            self.data.repeat = None
            self.repeat_widget = None

        elif widget_type is not None and  not isinstance(self.repeat_widget, widget_type):
            self.data.repeat = storage_type()
            self.repeat_widget = widget_type(self.data.repeat)
            gremlin.util.clear_layout(self.container_repeat_layout)
            widget = gremlin.ui.ui_common.getHContainer(self.repeat_widget, widget_only = True)
            self.container_repeat_layout.addWidget(widget)

class MacroWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows creating and editing of macros."""
    

    from gremlin.util import get_icon_path

    rightPanelResize = QtCore.Signal(int) # occurs when right panel content should resize

    locked = False

    # Path to graphics
    gfx_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "gfx"
    )

    def __init__(self, action_data, parent=None):
        """Creates a new UI widget.

        :param action_data the data of the macro action  type: Macro
        :param parent the parent of the widget
        """
        super().__init__(action_data, parent=parent)
        config = gremlin.config.Configuration()

        self._polling_rate = config.macro_axis_polling_rate
        self._minimum_change_amount = config.macro_axis_minimum_change_rate
        self._recording_times = {None: time.time()}
        self._recording_values = {None: 0.0}



        self._create_ui()
        self._populate_ui()


    def _update_state(self):
        # update the sequence
        self._populate_ui()


    def _create_ui(self):
        """Creates the UI of this widget."""
        
        if not Shiboken.isValid(self):
            return
        if MacroWidget.locked:
            return
        
        try:

            MacroWidget.locked = True

            self.model = gremlin.macro_handler.MacroListModel(self.action_data.sequence)

            sd = gremlin.ui.state_device.StateData()
            sd.crud.connect(self._update_state)

            # Replace the default vertical with a horizontal layout
            QtWidgets.QWidget().setLayout(self.layout())
            self.main_layout = QtWidgets.QVBoxLayout(self)

            
            # header

            execute_label = QtWidgets.QLabel("Execute macro on:")
            self.execute_on_press_widget = QtWidgets.QCheckBox("Press")
            self.execute_on_press_widget.setChecked(self.action_data.execute_on_press)
            self.execute_on_press_widget.clicked.connect(self._execute_on_press_changed)

            self.execute_on_release_widget = QtWidgets.QCheckBox("Release")
            self.execute_on_release_widget.setChecked(self.action_data.execute_on_release)
            self.execute_on_release_widget.clicked.connect(self._execute_on_release_changed)


            self.autorestart_widget = QtWidgets.QCheckBox("Auto-restart")
            self.autorestart_widget.setToolTip("When set, the macro will abort if it's executing and restart from the start on any re-trigger while it's running.\nIf not set, macro will not retrigger if it's already running.")
            self.autorestart_widget.setChecked(self.action_data.auto_restart)
            self.autorestart_widget.clicked.connect(self._autorestart_changed)

            self.autostop_widget = QtWidgets.QCheckBox("Stop on release")
            self.autostop_widget.setToolTip("When set, the macro will abort on an input release even if it's not finished.")
            self.autostop_widget.setChecked(self.action_data.auto_stop)
            self.autostop_widget.clicked.connect(self._autostop_changed)

            widgets = [execute_label,
                       self.execute_on_press_widget,
                       self.execute_on_release_widget,
                       self.autorestart_widget,
                       self.autostop_widget
                       ]
            self.execute_container_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
            
            self.main_layout.addWidget(self.execute_container_widget)

            #self.delegate = MacroItemDelegate(self)

            # Create list view for macro actions and setup drag & drop support
            self.list_view = MacroListView()
            self.list_view.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
            self.list_view.setDefaultDropAction(QtCore.Qt.MoveAction)
            self.list_view.setModel(self.model)
            self.list_view.setModelColumn(0)
            #self.list_view.setCurrentIndex(self.model.index(0, 0))
            self.list_view.clicked.connect(self._edit_action)
            #self.list_view.setItemDelegate(self.delegate)

            

    
            
            self.editor_widget = QtWidgets.QWidget()
            self.editor_container_widget, self.editor_container_layout = gremlin.ui.ui_common.getHContainer(self.editor_widget)

            
            self.settings_widget = MacroSettingsWidget(self.action_data)
            # self.settings_widget.resized.connect(self._handle_settings_resized)
            
     

            prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""

            # Macro toolbar setup
            # Create buttons used to modify and interact with the macro actions
            self.button_new_entry = self._create_toolbutton(
                f"{prefix}list_add.svg",
                "Add a new action",
                False
            )
            self.button_new_entry.clicked.connect(self._add_entry)

            self.button_duplicate_entry = self._create_toolbutton(
                "mdi.content-duplicate",
                "Duplicate the selected action(s)",
                False
            )
            self.button_duplicate_entry.clicked.connect(self._duplicate_entry)

            self.button_delete_widget = self._create_toolbutton(
                f"{prefix}list_delete.svg",
                "Delete currently selected action(s)",
                False
            )
            self.button_delete_widget.clicked.connect(self._delete_cb)

            self.button_pause = self._create_toolbutton(
                f"{prefix}pause.svg",
                "Add pause after the currently selected action(s)",
                False
            )
            self.button_pause.clicked.connect(self._pause_cb)

            self.button_record = self._create_toolbutton(
                [
                    f"{prefix}macro_record.svg",
                    f"{prefix}macro_record_on.svg"
                ],
                "Start/Stop recording",
                True,
                False
            )
            self.button_record.clicked.connect(self._record_cb)

            self.record_time = self._create_toolbutton(
                [
                    f"{prefix}time.svg",
                    f"{prefix}time_on.svg"
                ],
                "Record pauses between actions",
                True,
                False
            )

            # Input type recording buttons
            cfg = gremlin.config.Configuration()
            self.record_axis = self._create_toolbutton(
                [
                    f"{prefix}record_axis.svg",
                    f"{prefix}record_axis_on.svg"
                ],
                "Record joystick axis events",
                True,
                cfg.macro_record_axis
            )
            self.record_axis.clicked.connect(self._update_record_settings)
            self.record_button = self._create_toolbutton(
                [
                    f"{prefix}record_button.svg",
                    f"{prefix}record_button_on.svg"
                ],
                "Record joystick button events",
                True,
                cfg.macro_record_button
            )
            self.record_button.clicked.connect(self._update_record_settings)
            self.record_hat = self._create_toolbutton(
                [
                    f"{prefix}record_hat.svg",
                    f"{prefix}record_hat_on.svg"
                ],
                "Record joystick hat events",
                True,
                cfg.macro_record_hat
            )
            self.record_hat.clicked.connect(self._update_record_settings)
            self.record_key = self._create_toolbutton(
                [
                    f"{prefix}record_key.svg",
                    f"{prefix}record_key_on.svg"
                ],
                "Record keyboard events",
                True,
                cfg.macro_record_keyboard
            )
            self.record_key.clicked.connect(self._update_record_settings)
            self.record_mouse = self._create_toolbutton(
                [
                    f"{prefix}record_mouse.svg",
                    f"{prefix}record_mouse_on.svg"
                ],
                "Record mouse events",
                True,
                cfg.macro_record_mouse
            )
            self.record_mouse.clicked.connect(self._update_record_settings)

            # delete button
            self.delete_button = self._create_toolbutton(gremlin.ui.ui_common.Icons.trashIcon(),"Delete selection",False)
            self.delete_button.clicked.connect(self._delete_cb)

            # Toolbar
            self.toolbar = QtWidgets.QToolBar()

            background_color = gremlin.ui.ui_common.Color.backgroundColor()
            border_color = gremlin.ui.ui_common.Color.borderColor()
            self.toolbar.setStyleSheet(f"QToolBar {{border: 1px solid {border_color}; background-color: {background_color};}} ::separator {{background-color: {border_color};}}")
            self.toolbar.setIconSize(QtCore.QSize(16, 16))
            self.toolbar.setOrientation(QtCore.Qt.Vertical)
            self.toolbar.addWidget(self.button_new_entry)
            self.toolbar.addWidget(self.button_duplicate_entry)
            self.toolbar.addWidget(self.button_delete_widget)
            self.toolbar.addWidget(self.button_pause)
            self.toolbar.addSeparator()
            self.toolbar.addWidget(self.button_record)
            self.toolbar.addWidget(self.record_time)
            self.toolbar.addWidget(self.record_axis)
            self.toolbar.addWidget(self.record_button)
            self.toolbar.addWidget(self.record_hat)
            self.toolbar.addWidget(self.record_key)
            self.toolbar.addWidget(self.record_mouse)
            self.toolbar.addSeparator()
            self.toolbar.addWidget(self.delete_button)

            #required_height = self.toolbar.frameGeometry().height()
            height = self.toolbar.sizeHint().height()
            self.toolbar.setMinimumHeight(height) # 260)

            self._last_sizes = None

            # Assemble left panel
            self.macro_widget, self.macro_layout = gremlin.ui.ui_common.getHContainer()
            self.macro_layout.addWidget(self.list_view)
            self.macro_layout.addWidget(self.toolbar)
            self.macro_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
            self.list_view.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
            
            # assemble panels in a grid (splitter will not currently work for some reason in QT)
            self.left_panel_widget, self._left_panel_layout = gremlin.ui.ui_common.getVContainer(self.macro_widget)
            self.right_panel_widget, self._right_panel_layout = gremlin.ui.ui_common.getVContainer([self.editor_container_widget, self.settings_widget])

            grid_layout = QtWidgets.QGridLayout()
            grid_layout.addWidget(self.left_panel_widget, 0, 0)
            grid_layout.addWidget(self.right_panel_widget, 0, 1)
            grid_layout.setColumnMinimumWidth(0,200)
            grid_layout.setColumnMinimumWidth(1,200)
            self.main_layout.addLayout(grid_layout)

            
        finally:
            MacroWidget.locked = False

    @QtCore.Slot(QtCore.QSize)
    def _handle_settings_resized(self, size):
        # resize the splitter to the container's size as it doesn't happen by itself for some reason
        width = self.settings_widget.frameGeometry().width()
        #height = self.settings_widget.frameGeometry().height()
        self.rightPanelResize.emit(width)
        


    @QtCore.Slot(QtCore.QSize)
    def _content_resized(self, size : QtCore.QSize):
        ''' called when the container object is resized '''

        # resize the splitter to the container's size as it doesn't happen by itself for some reason
        width = self._content_widget.frameGeometry().width()
        height = self._content_widget.frameGeometry().height()
        if width > 400:
            self._splitter.setFixedWidth(width)
        self._splitter.setFixedHeight(height)          

    @QtCore.Slot(int, int)
    def _splitter_moved(self, pos, index):
        sizes = self._splitter.sizes()
        if pos < 0:
            # QT bug - position should never be negative
            if self._last_sizes:
                sizes = self._last_sizes
            else:
                width = self._content_widget.frameGeometry().width()
                sizes = [200, width - 200]
            self._splitter.setSizes(sizes)        
        self._last_sizes = sizes          

    def _create_toolbutton(self, icon_path, tooltip, is_checkable, default_on=True):
        """Creates a new toolbutton with the provided options.

        :param icon_path the path or list of paths of icons or an icon object
        :param tooltip the tooltip of the button
        :param is_checkable whether or not the button can be toggled
        :param default_on whether or not to toggle the button by default
        """
        from gremlin.util import load_pixmap, load_icon
        button = QtWidgets.QToolButton()

        # prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        
        if isinstance(icon_path, list):
            pixmap_0 = load_pixmap(icon_path[0])
            pixmap_1 = load_pixmap(icon_path[1])
            icon = QtGui.QIcon()
            icon.addPixmap(pixmap_0, QtGui.QIcon.Normal)
            icon.addPixmap(
                pixmap_1,
                QtGui.QIcon.Active,
                QtGui.QIcon.On
            )
            button.setIcon(icon)
        elif isinstance(icon_path, QtGui.QIcon):
            button.setIcon(icon_path)
        else:
            button.setIcon(load_icon(icon_path))
        if tooltip:
            button.setToolTip(tooltip)
        button.setCheckable(is_checkable)
        button.setChecked(is_checkable and default_on)
        return button

    def _populate_ui(self):
        """Populate the UI with content from the data."""
        if Shiboken.isValid(self.execute_container_widget) and Shiboken.isValid(self.list_view):
            self.model = gremlin.macro_handler.MacroListModel(self.action_data.sequence)
            input_type = self._get_input_type()
            execution_mode_visible = input_type != InputType.JoystickAxis
            self.execute_container_widget.setVisible(execution_mode_visible)
            self.list_view.setModel(None)
            self.list_view.setModel(self.model)
            self.list_view.setCurrentIndex(self.model.index(0, 0))
            self._edit_action(self.model.index(0, 0))

    def _edit_action(self, model_index):
        """Enable editing of the current action via a editor widget.

        :param model_index the index of the model entry to edit
        """

        # ignore if there is more than one item selected
        if len(self.list_view.selectedIndexes()) > 1:
            self.editor_widget = QtWidgets.QLabel("Please select a single action")
        else:
            self.editor_widget = MacroActionEditor(self.model, model_index)
            self.editor_widget.hook(self)
 
        gremlin.util.clear_layout(self.editor_container_layout)
        self.editor_container_layout.addWidget(self.editor_widget)
        


    def _update_record_settings(self):
        """Store user preferences of inputs to record."""
        cfg = gremlin.config.Configuration()
        cfg.macro_record_axis = self.record_axis.isChecked()
        cfg.macro_record_button = self.record_button.isChecked()
        cfg.macro_record_hat = self.record_hat.isChecked()
        cfg.macro_record_keyboard = self.record_key.isChecked()
        cfg.macro_record_mouse = self.record_mouse.isChecked()

    def _refresh_editor_ui(self):
        """Forcibly refresh the editor widget content."""
        self.list_view.clicked.emit(self.list_view.currentIndex())

    def _create_joystick_action(self, event):
        # Check whether or not to record a specific type of input
        if event.event_type == InputType.JoystickAxis and \
                not self.record_axis.isChecked():
            return
        if event.event_type == InputType.JoystickButton and \
                not self.record_button.isChecked():
            return
        if event.event_type == InputType.JoystickHat and \
                not self.record_hat.isChecked():
            return

        # If this is an axis motion do some checks such that we don't spam
        # the ui with entries
        add_new_entry = True
        if event.event_type == InputType.JoystickAxis:
            cur_index = self.list_view.currentIndex().row()
            entry = self.model.get_entry(cur_index)

            if event in self._recording_times:
                if time.time() - self._recording_times[event] < self._polling_rate:
                    add_new_entry = False
                elif abs(event.value - self._recording_values[event]) < \
                        self._minimum_change_amount:
                    add_new_entry = False

        if add_new_entry:
            if self.record_time.isChecked():
                self._append_entry(gremlin.macro.PauseAction(
                    time.time() - max(self._recording_times.values())
                ))
            value = event.is_pressed
            if event.event_type != InputType.JoystickButton:
                value = event.value
            action = gremlin.macro.JoystickAction(
                event.device_guid,
                event.event_type,
                event.identifier,
                value
            )
            self._recording_times[event] = time.time()
            self._recording_values[event] = event.value
            self._append_entry(action)

    def _create_key_action(self, event):
        """Creates a new macro.KeyAction instance from the given event.

        :param event the event for which to create a KeyAction object
        """
        # Abort if we should not record keyboard inputs
        if not self.record_key.isChecked():
            return

        if self.record_time.isChecked():
            self._append_entry(gremlin.macro.PauseAction(
                time.time() - max(self._recording_times.values())
            ))
        action = gremlin.macro.KeyAction(
            key_from_code(
                event.identifier[0],
                event.identifier[1]
            ),
            event.is_pressed
        )
        self._recording_times["keyboard"] = time.time()
        self._append_entry(action)

    def _create_mouse_action(self, event):
        # Abort if we should not record mouse inputs
        if not self.record_mouse.isChecked():
            return

        if self.record_time.isChecked():
            self._append_entry(gremlin.macro.PauseAction(
                time.time() - max(self._recording_times.values())
            ))

        action = gremlin.macro.MouseButtonAction(event.identifier, event.is_pressed)
        self._recording_times["mouse"] = time.time()
        self._append_entry(action)

    @QtCore.Slot()
    def _record_cb(self):
        """Starts the recording of key presses."""
        if self.button_record.isChecked():
            # Enable mouse event hooking
            event_listener = gremlin.event_handler.EventListener()
            if not event_listener.mouseEnabled():
                # hook mouse
                event_listener.enableMouse()
            gremlin.windows_event_hook.MouseHook().start()

            # Record keystrokes
            gremlin.shared_state.push_suspend_highlighting()
            self._recording = True
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._create_joystick_action)
            el.keyboard_event.connect(self._create_key_action)
            el.mouse_event.connect(self._create_mouse_action)
        else:
            # Stop recording keystrokes
            gremlin.shared_state.pop_suspend_highlighting()
            self._recording = False
            el = gremlin.event_handler.EventListener()
            el.joystick_event.disconnect(self._create_joystick_action)
            el.keyboard_event.disconnect(self._create_key_action)
            el.mouse_event.disconnect(self._create_mouse_action)

            # Disable mouse event hooking
            gremlin.windows_event_hook.MouseHook().stop()







    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.execute_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.execute_on_release = checked

    @QtCore.Slot(bool)
    def _autorestart_changed(self, checked : bool):
        self.action_data.auto_restart = checked

    @QtCore.Slot(bool)
    def _autostop_changed(self, checked : bool):
        self.action_data.auto_stop = checked

    @QtCore.Slot()
    def _pause_cb(self):
        """Adds a pause macro action to the list."""
        self._insert_entry_at_current_index(gremlin.macro.PauseAction(0.250))
        self._refresh_editor_ui()

    @QtCore.Slot()
    def _add_entry(self):
        self._pause_cb()

    @QtCore.Slot()
    def _duplicate_entry(self):
        ''' duplicate '''
        gremlin.util.InvokeUiMethod(self._duplicate_entry_ui) # on UI thread

    def _duplicate_entry_ui(self):
        ''' duplicates an entry (on UI thread)'''
        import copy
        actions = []
        selected_indices = []
        for idx in self.list_view.selectedIndexes():
            action = self.model.data(idx, QtCore.Qt.UserRole)
            new_action = copy.deepcopy(action)
            new_action.id = gremlin.util.get_guid() # setup new ID for the entry
            actions.append(new_action)
            
        if actions:
            # add the actions to the model
            for action in actions:
                index = self.model.rowCount()
                self.model.add_entry(index, action)
                selected_indices.append(self.model.index(index, 0))

            # select what was added
            for model_index in selected_indices:
                self.list_view.setCurrentIndex(model_index)

            self._refresh_editor_ui()

    @QtCore.Slot()
    def _delete_cb(self):
        """Callback executed when the delete button is pressed."""

        indices = self.list_view.selectedIndexes()
        if indices:

            # warn box 
            msgbox = gremlin.ui.ui_common.ConfirmBox(f"Delete selected entries?")
            result = msgbox.show()

            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                rows = [idx.row() for idx in indices]
                keep = []
                for index, item in enumerate(self.action_data.sequence):
                    if index in rows:
                        continue
                    keep.append(item)
                
                self.action_data.sequence = keep
                self._populate_ui()


                # select the first item kept
                if keep:
                    self.list_view.setCurrentIndex(self.model.index(0,0))
                
                
    @QtCore.Slot()
    def _insert_entry_at_current_index(self, entry):
        """Adds the given entry after current selection.

        :param entry the entry to add to the model
        """
        cur_index = self.list_view.currentIndex().row()
        self.model.add_entry(cur_index, entry)
        self.list_view.setCurrentIndex(self.model.index(cur_index+1, 0))
        self._refresh_editor_ui()

    @QtCore.Slot()
    def _append_entry(self, entry):
        """Adds the given entry at the end of the list.

        :param entry the entry to add to the model
        """
        index = self.model.rowCount()
        self.model.add_entry(index, entry)
        self.list_view.setCurrentIndex(self.model.index(index, 0))
        self._refresh_editor_ui()



class MacroFunctor(gremlin.base_profile.AbstractFunctor):

    manager = gremlin.macro.MacroManager()

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.macro = gremlin.macro.Macro(self.id)
        for seq in action.sequence:
            self.macro.add_action(seq)
        self.macro.exclusive = action.exclusive
        self.macro.repeat = action.repeat
        
        

    def process_event(self, event, value, extra_data = None):

        trigger = self.action_data.execute_on_press and event.is_pressed or \
                  self.action_data.execute_on_release and not event.is_pressed
        
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_macro
        
        if verbose: syslog.info(f"MACROFUNCTOR: {self.action_data.comment if self.action_data.comment else ''} {str(event)}")        


        if not event.is_pressed:
            if self.action_data.auto_stop and self.macro.state == gremlin.macro.MacroState.Running:
                MacroFunctor.manager.terminate_macro(self.macro) # terminate existing running macro on release
        
        if not trigger:
            # do not execute
            return True
        
        if verbose: syslog.info(f"\texecute")
        
        
        if self.action_data.auto_restart and self.macro.state == gremlin.macro.MacroState.Running:
            MacroFunctor.manager.terminate_macro(self.macro) # terminate existing running macro for restart

        # queue the macro        
        MacroFunctor.manager.queue_macro(self.macro)
        if isinstance(self.macro.repeat, gremlin.macro.HoldRepeat):
            # gremlin.input_devices.ButtonReleaseActions().register_callback(
            #     lambda: MacroFunctor.manager.terminate_macro(self.macro),
            #     event
            # )
            release_event = event.release_event()
            gremlin.input_devices.ButtonReleaseActions().register_callback(
                lambda: self.process_event(release_event, value, extra_data),
                event, release_event)
        return True


class Macro(gremlin.base_profile.AbstractAction):

    """Represents a macro action."""

    name = "Macro"
    tag = "macro"
    hint = '''Creates macros.
All steps in a macro execute on trigger.
To send complex sequences, please look at the sequence container.'''

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)

    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MacroFunctor
    widget = MacroWidget

    def __init__(self, parent):
        """Creates a new Macro instance.

        :param parent the parent profile.ItemAction of this macro action
        """
        super().__init__(parent)
        self.parent = parent
        self.sequence = []
        self.exclusive = False
        self.repeat = None

        self.force_remote = False
        self.execute_on_press = True # true if macro executes on input press/change
        self.execute_on_release = False # true if macro executs on input release
        self.auto_restart = False # true if the macro an auto-restart if retriggered before it finishes
        self.auto_stop = False # true if the macro should stop when the input is released

    def display_name(self):
        ''' returns a display string for the current configuration '''
        stub = ""
        if self.repeat:
            stub = f" (repeat)"
        return f"Macro sequence: steps: [{len(self.sequence)}] exclusive: [{self.exclusive}] EOR: [{self.execute_on_release}] AutoRestart: [{self.auto_restart}] AutoStop: [{self.auto_stop}]{stub}"

    def icon(self):
        return "ei.cogs"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):
        """Parses the XML node corresponding to a macro action.

        :param node the XML node to parse.
        """
        # Reset storage
        self.sequence = []
        self.exclusive = False
        
        
        self.force_remote = False
        self.execute_on_press = True # true if macro executes on input press/change
        self.execute_on_release = False # true if macro executs on input release
        self.auto_restart = False
        self.auto_stop = False

        import gremlin.ui.state_device
        sd = gremlin.ui.state_device.StateData()

        if "execute-on-press" in node.attrib:
            self.execute_on_press = safe_read(node,"execute-on-press",bool,True)
        if "execute-on-release" in node.attrib:
            self.execute_on_release = safe_read(node,"execute-on-release",bool,True)
        if "autorestart" in node.attrib:
            self.auto_restart = safe_read(node, "autorestart", bool, False)
        if "autostop" in node.attrib:
            self.auto_stop = safe_read(node, "autostop", bool, False)

        # Read properties
        for child in node.find("properties"):
            if child.tag == "exclusive":
                self.exclusive = True
            elif child.tag == "force_remote":
                self.force_remote = True
            elif child.tag == "repeat":

                repeat_type = child.get("type")
                if repeat_type == "count":
                    self.repeat = gremlin.macro.CountRepeat()
                elif repeat_type == "toggle":
                    self.repeat = gremlin.macro.ToggleRepeat()
                elif repeat_type == "hold":
                    self.repeat = gremlin.macro.HoldRepeat()
                else:
                    syslog.warning(
                        f"Invalid macro repeat type: {repeat_type}"
                    )

                if self.repeat:
                    self.repeat.from_xml(child, data)

        # Read macro actions
        for child in node.find("actions"):
            if child.tag == "joystick":
                device_id = child.get("device-guid")
                parse_guid(device_id)
                if device_id:
                    joy_action = gremlin.macro.JoystickAction(
                        parse_guid(device_id),
                        InputType.to_enum(safe_read(child, "input-type", str, "")),
                        safe_read(child, "input-id", int, 1),
                        safe_read(child, "value", str, ""),
                    )
                self._str_to_joy_value(joy_action)
                self.sequence.append(joy_action)
            elif child.tag == "key":
                key_action = gremlin.macro.KeyAction(
                    key_from_code(
                        int(child.get("scan-code")),
                        gremlin.profile.parse_bool(child.get("extended"))
                    ),
                    gremlin.profile.parse_bool(child.get("press"))
                )
                self.sequence.append(key_action)
            elif child.tag == "mouse":
                mouse_action = gremlin.macro.MouseButtonAction(
                    gremlin.types.MouseButton(safe_read(child, "button", int, 1)),
                    gremlin.profile.parse_bool(child.get("press"))
                )
                self.sequence.append(mouse_action)
            elif child.tag == "mouse-motion":
                mouse_motion = gremlin.macro.MouseMotionAction(
                    safe_read(child, "dx", int, 0),
                    safe_read(child, "dy", int, 0)
                )
                self.sequence.append(mouse_motion)
            elif child.tag == "pause":
                self.sequence.append (
                    gremlin.macro.PauseAction(
                                        float(child.get("duration")),
                                        safe_read(child, "duration_max", float, 0),
                                        gremlin.profile.parse_bool(child.get("is_random"))
                                        )
                )
            elif child.tag == "vjoy":
                vjoy_action = gremlin.macro.VJoyMacroAction(
                    safe_read(child, "vjoy-id", int, 1),
                    InputType.to_enum(
                        safe_read(child, "input-type", str, "")
                    ),
                    safe_read(child, "input-id", int, 1),
                    safe_read(child, "value", str, ""),
                    safe_read(child, "axis-type", str, "absolute")
                )
                self._str_to_joy_value(vjoy_action)
                self.sequence.append(vjoy_action)

            elif child.tag == "remote_control":
                remote_control_action = gremlin.macro.RemoteControlAction()
                cmd = safe_read(child, "command", str, "VJoyEnableLocalOnly")
                remote_control_action.command = VjoyAction.from_string(cmd)
                self.sequence.append(remote_control_action)

            elif child.tag == "state":
                state_action = gremlin.macro.StateAction()
                state = None
                id = None
                if "id" in child.attrib:
                    id = safe_read(child, "id", str, "")
                    state = sd.getStateById(id)
                
                key = child.get("key")
                if "description" in child.attrib:
                    description = child.get("description")

                if not state:
                    if id:
                        # use ID as primary
                        state = sd.getStateById(id)
                    elif key:
                        # use key as secondary (legacy profiles)
                        state = sd.getState(key)
                    description = None

                value = False
                if "action" in child.attrib:          
                    action = safe_read(child,"action", str, "press")
                else:
                    value = safe_read(child,"value", bool, False)
                    action = "press" if value else "release"

                if not state and key:
                    state = sd.register(key, value, description)

                state_action.action = action
                state_action.state = state
                self.sequence.append(state_action)



    def _generate_xml(self):
        """Generates a XML node corresponding to this object.

        :return XML node representing the object's data
        """
        node = ElementTree.Element("macro")
        properties = ElementTree.Element("properties")
        if self.exclusive:
            prop_node = ElementTree.Element("exclusive")
            properties.append(prop_node)
        if self.repeat:
            properties.append(self.repeat.to_xml())
        if self.force_remote:
            prop_node = ElementTree.Element("force_remote")
            properties.append(prop_node)

        node.set("execute-on-press",safe_format(self.execute_on_press, bool))
        node.set("execute-on-release",safe_format(self.execute_on_release, bool))
        node.set("autorestart", safe_format(self.auto_restart, bool))
        node.set("autostop", safe_format(self.auto_stop, bool))

        node.append(properties)

        action_list = ElementTree.Element("actions")
        for entry in self.sequence:

            if isinstance(entry, gremlin.macro.JoystickAction):
                if not entry.device_guid:
                    continue
                joy_node = ElementTree.Element("joystick")
                joy_node.set("device-guid", write_guid(entry.device_guid))
                joy_node.set(
                    "input-type",
                    InputType.to_string(entry.input_type)
                )
                joy_node.set("input-id", str(entry.input_id))
                joy_node.set("value", self._joy_value_to_str(entry))
                action_list.append(joy_node)
            elif isinstance(entry, gremlin.macro.KeyAction):
                action_node = ElementTree.Element("key")
                action_node.set("scan-code", str(entry.key.scan_code))
                action_node.set("extended", str(entry.key.is_extended))
                action_node.set("press", str(entry.is_pressed))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                action_node = ElementTree.Element("mouse")
                action_node.set("button", str(entry.button.value))
                action_node.set("press", str(entry.is_pressed))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.MouseMotionAction):
                action_node = ElementTree.Element("mouse-motion")
                action_node.set("dx", str(entry.dx))
                action_node.set("dy", str(entry.dy))
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.PauseAction):
                pause_node = ElementTree.Element("pause")
                pause_node.set("duration", str(entry.duration))
                pause_node.set("duration_max", str(entry.duration_max))
                pause_node.set("is_random", str(entry.is_random))
                action_list.append(pause_node)
            elif isinstance(entry, gremlin.macro.VJoyMacroAction):
                vjoy_node = ElementTree.Element("vjoy")
                vjoy_node.set("vjoy-id", str(entry.vjoy_id))
                vjoy_node.set(
                    "input-type",
                    InputType.to_string(entry.input_type)
                )
                vjoy_node.set("input-id", str(entry.input_id))
                vjoy_node.set("value", self._joy_value_to_str(entry))
                if entry.input_type == InputType.JoystickAxis:
                    vjoy_node.set("axis-type", safe_format(entry.axis_type, str))
                action_list.append(vjoy_node)
            elif isinstance(entry, gremlin.macro.RemoteControlAction):
                action_node = ElementTree.Element("remote_control")
                action_node.set("command",entry.command.name)
                action_list.append(action_node)
            elif isinstance(entry, gremlin.macro.StateAction):
                state_node = ElementTree.Element("state")
                state_node.set("id", entry._state_id)
                state_node.set("key", entry.key)
                state_node.set("action", entry.action)
                action_list.append(state_node)

        node.append(action_list)
        return node

    def _is_valid(self):
        return len(self.sequence) > 0

    def _joy_value_to_str(self, entry):
        """Converts a joystick input value to a string.

        :param entry the entry whose value to convert
        :return string representation of the entry's value
        """
        if entry.input_type == InputType.JoystickAxis:
            return str(entry.value)
        elif entry.input_type == InputType.JoystickButton:
            return str(entry.value)
        elif entry.input_type == InputType.JoystickHat:
            return gremlin.util.hat_tuple_to_direction(entry.value)

    def _str_to_joy_value(self, action):
        if action.input_type == InputType.JoystickAxis:
            action.value = float(action.value)
        elif action.input_type == InputType.JoystickButton:
            pass # use as-is
        elif action.input_type == InputType.JoystickHat:
            action.value = gremlin.util.hat_direction_to_tuple(action.value)
        
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell


        table = ReportTable(cellpadding=4)
        for entry in self.sequence:

            if isinstance(entry, gremlin.macro.JoystickAction):
                device_name = gremlin.joystick_handling.device_name_from_guid(entry.device_guid)
                if not entry.device_guid or not device_name:
                    table.addField("Joystick", "N/A")    
                    continue
                value_stub = f" Value: {entry.value:0.3f}" if  entry.input_type == InputType.JoystickAxis else ""
                table.addField("Joystick", f"[{device_name}] Type: [{entry.input_type.name}] ID: [{entry.id}]{value_stub}")

            elif isinstance(entry, gremlin.macro.KeyAction):
                table.addField("Key", f"{gremlin.keyboard.KeyMap.get_name(entry.key)} Action: {'press' if entry.is_pressed else 'release'}")
                
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                table.addField("Mouse", f"Button {entry.button.value} Action: {'press' if entry.is_pressed else 'release'}")
                
            elif isinstance(entry, gremlin.macro.MouseMotionAction):
                table.addField("Mouse Motion", f"Dx {entry.dx} Dy {entry.dy}")
                
            elif isinstance(entry, gremlin.macro.PauseAction):
                random_stub = f" Random: Yes Max Duration: {entry.duration_max:0.2f}" if entry.is_random else "" 
                table.addField("Pause", f"Duration: {entry.duration:0.2f}{random_stub}")
                
            elif isinstance(entry, gremlin.macro.VJoyMacroAction):
                table.addField("VJoy", f"Vjoy ID: {entry.vjoy_id}] Input Type: {entry.input_type.name} Value: {self._joy_value_to_str(entry)}")
                
            elif isinstance(entry, gremlin.macro.RemoteControlAction):
                table.addField("Control",entry.command.name )
                
            elif isinstance(entry, gremlin.macro.StateAction):
                sd = gremlin.ui.state_device.StateData()
                state = sd.getState(entry.key)
                if state:
                    table.addField("State", state.to_html())
                else:
                    table.addField("State", "N/A")


        return table.to_html()   

version = 1
name = "macro"
create = Macro
