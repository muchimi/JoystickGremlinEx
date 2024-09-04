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


import collections
import logging
import os
import pickle
import time
from PySide6 import QtCore, QtGui, QtWidgets

import gremlin.base_profile
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.keyboard
import gremlin.macro
import gremlin.ui.input_item
import gremlin.input_devices
from gremlin.input_devices import VjoyAction
from gremlin.keyboard import key_from_code, key_from_name
import gremlin.types

syslog = logging.getLogger("system")

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
        }

        self.setMinimumWidth(200)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.group_box = QtWidgets.QGroupBox("Action Settings")
        self.group_layout = QtWidgets.QVBoxLayout(self.group_box)
        self.main_layout.addWidget(self.group_box)

        self.blank_label = QtWidgets.QLabel("Please add an action.")
        self.main_layout.addWidget(self.blank_label)


        self.ui_elements = {}
        self._create_ui()
        self._populate_ui()

    def _create_ui(self):
        """Creates the editor UI."""

        if MacroActionEditor.locked:
            return
        
        try:
            MacroActionEditor.locked = True

            self.action_selector = QtWidgets.QComboBox()
            for action_name in sorted(self.action_types):
                self.action_selector.addItem(action_name)
            self.action_selector.currentTextChanged.connect(self._change_action)

            self.group_layout.addWidget(self.action_selector)

            self.action_layout = QtWidgets.QVBoxLayout()
            self.group_layout.addLayout(self.action_layout)
            self.group_layout.addStretch(1)
        finally:
            MacroActionEditor.locked = False

    def _populate_ui(self):
        """Populate the UI elements with data from the model."""

        
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
            self.mode.set_entry(gremlin.macro.RemoteControlAction(), self.index.row)


        # Update the UI elements
        self._update_model()
        self.action_types[value].create_ui()

    def _joystick_ui(self):
        """Creates and populates the JoystickAction editor UI."""
        action = self.model.get_entry(self.index.row())
        if action is None:
            return

        self.ui_elements["input_label"] = QtWidgets.QLabel("Input")
        self.ui_elements["input_button"] = \
            gremlin.ui.ui_common.NoKeyboardPushButton("Press Me")
        self.ui_elements["input_button"].clicked.connect(
            lambda: self._request_user_input([
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ])
        )

        self._create_joystick_inputs_ui(action)

        self.action_layout.addWidget(self.ui_elements["input_label"])
        self.action_layout.addWidget(self.ui_elements["input_button"])

    def _keyboard_ui(self):
        """Creates and populates the KeyAction editor UI."""
        action = self.model.get_entry(self.index.row())
        if action is None:
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

        self.action_layout.addWidget(self.ui_elements["key_label"])
        self.action_layout.addWidget(self.ui_elements["key_input"])
        self.action_layout.addWidget(self.ui_elements["key_press"])
        self.action_layout.addWidget(self.ui_elements["key_release"])

    def _mouse_button_ui(self):
        """Creates and populates the MouseAction editor UI."""
        action = self.model.get_entry(self.index.row())
        if action is None:
            return

        self.ui_elements["mouse_label"] = QtWidgets.QLabel("Button")
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
        self.action_layout.addWidget(self.ui_elements["duration_spinbox"])
        self.action_layout.addWidget(self.ui_elements["duration_max_label"])
        self.action_layout.addWidget(self.ui_elements["duration_spinbox_max"])


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




            # Axis mode configuration
            if action.input_type == InputType.JoystickAxis:
                if not "axis_type_layout" in self.ui_elements.keys():
                    self.ui_elements["axis_type_layout"] = QtWidgets.QHBoxLayout()
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

                    self.ui_elements["axis_type_layout"].addWidget(self.ui_elements["axis_reverse"])
                    self.ui_elements["axis_type_layout"].addWidget(self.ui_elements["axis_absolute"])
                    self.ui_elements["axis_type_layout"].addWidget(self.ui_elements["axis_relative"])
                    
                    self.action_layout.addLayout(self.ui_elements["axis_type_layout"])
                    

                

            self._create_joystick_inputs_ui(action)
        finally:
            MacroActionEditor.locked = False


    def _create_joystick_inputs_ui(self, action):
        # Handle display of value based on the actual input type
        if action.input_type == InputType.JoystickAxis:
            if "axis_value" in self.ui_elements.keys():
                self.ui_elements["axis_value"] = \
                    gremlin.ui.ui_common.DynamicDoubleSpinBox()
                self.ui_elements["axis_value"].setRange(-1.0, 1.0)
                self.ui_elements["axis_value"].setSingleStep(0.1)
                self.ui_elements["axis_value"].setDecimals(3)
                self.ui_elements["axis_value"].setValue(action.value)
                self.ui_elements["axis_value"].valueChanged.connect(
                    self._modify_axis_state
                )

                self.action_layout.addWidget(self.ui_elements["axis_value"])

        elif action.input_type == InputType.JoystickButton:
            if not "button_press" in self.ui_elements.keys():
                self.ui_elements["button_press"] = QtWidgets.QRadioButton("Press")
                self.ui_elements["button_release"] = QtWidgets.QRadioButton("Release")
                if action.value:
                    self.ui_elements["button_press"].setChecked(True)
                else:
                    self.ui_elements["button_release"].setChecked(True)

                self.ui_elements["button_press"].toggled.connect(
                    self._modify_button_state
                )
                self.ui_elements["button_release"].toggled.connect(
                    self._modify_button_state
                )
                self.action_layout.addWidget(self.ui_elements["button_press"])
                self.action_layout.addWidget(self.ui_elements["button_release"])

        elif action.input_type == InputType.JoystickHat:
            if not "hat_direction" in self.ui_elements.keys():
                self.ui_elements["hat_direction"] = QtWidgets.QComboBox()
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
                self.action_layout.addWidget(self.ui_elements["hat_direction"])


    def _remote_control_ui(self):
        self.ui_elements["remote_control_cb_label"] = QtWidgets.QLabel("Remote control command:") 
        cb = QtWidgets.QComboBox()
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

    def _modify_button_state(self, state):
        action = self.model.get_entry(self.index.row())
        action.value = self.ui_elements["button_press"].isChecked()
        self._update_model()

    def _modify_axis_state(self, state):
        action = self.model.get_entry(self.index.row())
        action.value = self.ui_elements["axis_value"].value()
        self._update_model()

    def _modify_hat_state(self, state):
        action = self.model.get_entry(self.index.row())
        action.value = gremlin.common.direction_tuple_lookup[state]
        self._update_model()

    def _modify_key_state(self, state):
        """Updates the key activation state, i.e. press or release of a key.

        :param state the radio button state
        """
        action = self.model.get_entry(self.index.row())
        action.is_pressed = self.ui_elements["key_press"].isChecked()
        self._update_model()

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

    def _request_user_input(self, input_types):
        """Prompts the user for the input to bind to this item."""
        if InputType.Keyboard in input_types:
            callback = self._modify_key
        elif InputType.Mouse in input_types:
            callback = self._modify_mouse
        else:
            callback = self._modify_joystick



        dialog = gremlin.ui.ui_common.InputListenerWidget(
            event_types = input_types,
            return_kb_event=True
        )

        dialog.item_selected.connect(callback)
        self.button_press_dialog = dialog

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

    def _modify_joystick(self, event):
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

    def _modify_key(self, event):
        """Changes which key is mapped.

        :param event the event containing information about the key to use
        """

        self.model.get_entry(self.index.row()).key = gremlin.keyboard.KeyMap.from_event(event)
        self._update_model()
        gremlin.ui.ui_common.clear_layout(self.action_layout)
        self.ui_elements = {}
        self._keyboard_ui()

    def _modify_mouse(self, event):
        self.model.get_entry(self.index.row()).button = event.identifier
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

    def _modify_vjoy_axis(self, data):
        action = self.model.get_entry(self.index.row())
        action.axis_type = "absolute"
        if self.ui_elements["axis_relative"].isChecked():
            action.axis_type = "relative"
        self._update_model()


class MacroListModel(QtCore.QAbstractListModel):

    """Model representing a Macro.

    This model supports model modification.
    """

    gfx_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "gfx"
    )
    icon_lookup = {}
    

    value_format = {
        InputType.JoystickAxis:
            lambda entry: f"{entry.value:.3f}",
        InputType.JoystickButton:
            lambda entry: "pressed" if entry.value else "released",
        InputType.JoystickHat:
            lambda entry: gremlin.common.direction_tuple_lookup[entry.value]
    }

    def __init__(self, data_storage, parent=None):
        """Creates a new instance.

        :param parent parent widget
        """
        QtCore.QAbstractListModel.__init__(self, parent)
        from gremlin.util import load_icon

                  
        MacroListModel.icon_lookup =  {
            "press": load_icon("press.svg"),
            "release": load_icon("release.svg"),
            "pause": load_icon("pause.svg")
        }

        self._data = data_storage

    def rowCount(self, parent=None):
        """Returns the number of rows in the model.

        :param parent the parent of the model
        :return number of rows in the model
        """
        count = len(self._data)
        return count

    def data(self, index, role):
        """Return the data of the index for the specified role.

        :param index the index into the model which is queried
        :param role the role for which the data is to be formatted
        :return data formatted for the given role at the given index
        """

        if not index.isValid():
            return None

        idx = index.row()
        if idx >= len(self._data):
            return ""

        entry = self._data[idx]
        
        if role == QtCore.Qt.SizeHintRole:
            # size hint
            return QtCore.QSize(200, 26)
        elif role == QtCore.Qt.DecorationRole:
            if isinstance(entry, gremlin.macro.PauseAction):
                return MacroListModel.icon_lookup["pause"]
            elif isinstance(entry, gremlin.macro.KeyAction):
                action = "press" if entry.is_pressed else "release"
                return MacroListModel.icon_lookup[action]
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                action = "press" if entry.is_pressed else "release"
                return MacroListModel.icon_lookup[action]
            else:
                return None
        elif role == QtCore.Qt.DisplayRole:
            if isinstance(entry, gremlin.macro.JoystickAction):
                device_name = "Unknown"
                for joy in gremlin.joystick_handling.joystick_devices():
                    if joy.device_guid == entry.device_guid:
                        device_name = joy.name
                display =  f"{device_name} {InputType.to_string(entry.input_type).capitalize()} {entry.input_id} - {MacroListModel.value_format[entry.input_type](entry)}"
            elif isinstance(entry, gremlin.macro.KeyAction):
                display =  f"{'Press' if entry.is_pressed else 'Release'} key {entry.key.name}"
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                if entry.button in [
                    gremlin.types.MouseButton.WheelDown,
                    gremlin.types.MouseButton.WheelUp,
                ]:
                    display =  f"{gremlin.types.MouseButton.to_string(entry.button)}"
                else:
                    display =  f"{'Press' if entry.is_pressed else 'Release'} {gremlin.types.MouseButton.to_string(entry.button)} mouse button"
            elif isinstance(entry, gremlin.macro.MouseMotionAction):
                display =  f"Move mouse by x: {entry.dx:d} y: {entry.dy:d}"
            elif isinstance(entry, gremlin.macro.PauseAction):
                msg = f"Pause for {entry.duration:.3f} s"
                if entry.duration_max != 0:
                    msg += f" to {entry.duration_max:.3f} s"
                if entry.is_random:
                    msg += " (random)"
                display = msg


            elif isinstance(entry, gremlin.macro.VJoyMacroAction):
                display =  f"vJoy {entry.vjoy_id} {InputType.to_string(entry.input_type).capitalize()} {entry.input_id} - {MacroListModel.value_format[entry.input_type](entry)}"

            elif isinstance(entry, gremlin.macro.RemoteControlAction):
                display = f"Remote control: {VjoyAction.to_name(entry.command)}"
            else:
                raise gremlin.error.GremlinError("Unknown macro action")
            
            
            #syslog.debug(display)
            return display
        elif role == QtCore.Qt.FontRole:
            font = QtGui.QFont()
            return font
        elif role == QtCore.Qt.ToolTipRole:
            return "Macro entry"
        elif role == QtCore.Qt.TextAlignmentRole:
            return QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft


        return None
    

    def mimeTypes(self):
        """Returns the MIME types supported by this model for drag & drop.

        :return supported MIME types
        """
        return ["data/macro-action"]

    def mimeData(self, index_list):
        """Returns encoded data for the provided indices.

        :param index_list list of indices to encode
        :return encoded content
        """
        assert len(index_list) == 1
        data = QtCore.QMimeData()
        data.setData(
            "data/macro-action",
            pickle.dumps((self._data[index_list[0].row()], index_list[0].row()))
        )
        return data

    def dropMimeData(self, data, action, row, column, parent):
        """Handles the drop event using the provided MIME encoded data.

        :param data MIME encoded data being dropped
        :param action type of drop action being requested
        :param row the row in which to insert the data
        :param column the column in which to insert the data
        :param parent the parent in the model under which the data is inserted
        :return True if data was processed, False otherwise
        """
        if action != QtCore.Qt.MoveAction:
            return False

        if row == -1:
            return False

        action, old_id = pickle.loads(data.data("data/macro-action"))
        self._data.insert(row, action)

        if old_id > row:
            old_id += 1
        del self._data[old_id]
        return True

    def flags(self, index):
        """Returns the flags of an item.

        :param index the index of the item for which to return the flags
        :return flags of an item
        """
        # Allow dragging of valid entries but disallow dropping on them while
        # invalid indices are valid drop locations, i.e. in between existing
        # entries.
        if index.isValid():
            return super().flags(index) | \
                    QtCore.Qt.ItemIsSelectable | \
                    QtCore.Qt.ItemIsDragEnabled | \
                    QtCore.Qt.ItemIsEnabled | \
                    QtCore.Qt.ItemNeverHasChildren
        else:
            return QtCore.Qt.ItemIsSelectable | \
                    QtCore.Qt.ItemIsDragEnabled | \
                    QtCore.Qt.ItemIsDropEnabled | \
                    QtCore.Qt.ItemIsEnabled | \
                    QtCore.Qt.ItemNeverHasChildren

    def supportedDropActions(self):
        """Return the drop actions supported by this model.

        :return Drop actions supported by this model
        """
        return QtCore.Qt.MoveAction

    def get_entry(self, index):
        """Returns the action entry at the given index.

        :param index the index of the entry to return
        :return entry stored at the given index
        """
        if not 0 <= index < len(self._data):
            logging.getLogger("system").error(
                "Attempted to retrieve macro entry at invalid index"
            )
            return None
        return self._data[index]

    def set_entry(self, entry, index):
        """Sets the entry at the given index to the given value.

        :param entry the new entry object to store
        :param index the index at which to store the entry
        """
        if not 0 <= index < len(self._data):
            logging.getLogger("system").error(
                "Attempted to set an entry with index greater "
                "then number of elements"
            )
            return

        self._data[index] = entry

    def remove_entry(self, index):
        """Removes the entry at the provided index.

        If the index is invalid nothing happens.

        :param index the index of the entry to remove
        """
        if 0 <= index < len(self._data):
            self.beginRemoveRows(self.index(0, 0), index, index)
            del self._data[index]
            self.endRemoveRows()

    def add_entry(self, index, entry):
        """Adds the given entry at the provided index.

        :param index the index at which to insert the new entry
        :param entry the entry to insert
        """
        self.beginInsertRows(QtCore.QModelIndex(), index, index)
        self._data.insert(index + 1, entry)
        self.endInsertRows()

    def swap(self, id1, id2):
        """Swaps the entries pointed to by the two indices.

        If either of the indices is invalid nothing happens.

        :param id1 first index
        :param id2 second index
        """
        if -1 < id1 < len(self._data) and -1 < id2 < len(self._data):
            self._data[id1], self._data[id2] = \
                self._data[id2], self._data[id1]
            self.dataChanged.emit(self.index(id1, 0), self.index(id2, 0))

    def update(self, index):
        """Emits a signal indicating the given index was updated.

        :param index the index which has been updated
        """
        self.dataChanged.emit(index, index)


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
        # # self.setAlternatingRowColors(True)
        # self.setStyleSheet("color: black; background-color: white;")

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


class ToggleRepeatMacroWidget(AbstractRepeatMacroWidget):

    """Repeat UI for a toggle repetition."""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)

    def _create_ui(self):
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


class HoldRepeatMacroWidget(AbstractRepeatMacroWidget):

    """Repeat UI for a hold repetition."""

    def __init__(self, data, parent=None):
        super().__init__(data, parent)

    def _create_ui(self):
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


class MacroSettingsWidget(QtWidgets.QWidget):

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

        self.group_box = QtWidgets.QGroupBox("Macro Settings")
        self.group_layout = QtWidgets.QVBoxLayout()
        self.group_box.setLayout(self.group_layout)
        self.main_layout.addWidget(self.group_box)

        self._create_ui()

    def _create_ui(self):
        """Creates the UI elements"""
        # Create UI elements
        self.exclusive_checkbox = QtWidgets.QCheckBox("Exclusive")
        self.force_remote_checkbox = QtWidgets.QCheckBox("Remote Only")
        self.repeat_dropdown = QtWidgets.QComboBox()
        self.repeat_dropdown.addItems(["None", "Count", "Toggle", "Hold"])
        self.repeat_widget = None
        if type(self.data.repeat) in MacroSettingsWidget.storage_to_name:
            mode_name = MacroSettingsWidget.storage_to_name[
                type(self.data.repeat)
            ]
            self.repeat_widget = MacroSettingsWidget.name_to_widget[mode_name](
                self.data.repeat
            )

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
        widget = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(widget)
        box.addWidget(self.exclusive_checkbox)
        box.addWidget(self.force_remote_checkbox) 
        self.group_layout.addWidget(widget)
        self.group_layout.addWidget(self.repeat_dropdown)
        if self.repeat_widget is not None:
            self.group_layout.addWidget(self.repeat_widget)

    def _update_settings(self, value):
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
            self.data.repeat = None
            self.repeat_widget = None

            old_item = self.group_layout.takeAt(2)
            if old_item is not None:
                old_item.widget().hide()
                old_item.widget().deleteLater()
        elif widget_type is not None and \
                not isinstance(self.repeat_widget, widget_type):
            self.data.repeat = storage_type()
            self.repeat_widget = widget_type(self.data.repeat)

            old_item = self.group_layout.takeAt(2)
            if old_item is not None:
                old_item.widget().hide()
                old_item.widget().deleteLater()
            self.group_layout.addWidget(self.repeat_widget)


class MacroWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows creating and editing of macros."""
    

    from gremlin.util import get_icon_path

    locked = False

    # Path to graphics
    gfx_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "gfx"
    )

    def __init__(self, action_data, parent=None):
        """Creates a new UI widget.

        :param action_data the data of the macro action
        :param parent the parent of the widget
        """
        super().__init__(action_data, parent=parent)

        self._polling_rate = \
            gremlin.config.Configuration().macro_axis_polling_rate
        self._minimum_change_amount = \
            gremlin.config.Configuration().macro_axis_minimum_change_rate
        self._recording_times = {
            None: time.time()
        }
        self._recording_values = {
            None: 0.0
        }

        self._create_ui()
        self._populate_ui()

    def _create_ui(self):
        """Creates the UI of this widget."""
        if MacroWidget.locked:
            return
        
        try:

            MacroWidget.locked = True

            self.model = MacroListModel(self.action_data.sequence)

            # Replace the default vertical with a horizontal layout
            QtWidgets.QWidget().setLayout(self.layout())
            self.main_layout = QtWidgets.QHBoxLayout(self)

            self.editor_settings_layout = QtWidgets.QVBoxLayout()
            self.buttons_layout = QtWidgets.QVBoxLayout()

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


            # Create editor as well as settings place holder widgets
            self.editor_widget = QtWidgets.QWidget()
            self.settings_widget = MacroSettingsWidget(self.action_data)
            self.editor_settings_layout.addWidget(self.editor_widget)
            self.editor_settings_layout.addWidget(self.settings_widget)
            self.editor_settings_layout.addStretch()

            # Create buttons used to modify and interact with the macro actions
            self.button_new_entry = self._create_toolbutton(
                "list_add.svg",
                "Add a new action",
                False
            )
            self.button_new_entry.clicked.connect(self._add_entry)

            self.button_delete = self._create_toolbutton(
                "list_delete.svg",
                "Delete currently selected entry",
                False
            )
            self.button_delete.clicked.connect(self._delete_cb)

            self.button_pause = self._create_toolbutton(
                "pause.svg",
                "Add pause after the currently selected entry",
                False
            )
            self.button_pause.clicked.connect(self._pause_cb)

            self.button_record = self._create_toolbutton(
                [
                    "macro_record.svg",
                    "macro_record_on.svg"
                ],
                "Record keyboard and joystick inputs",
                True,
                False
            )
            self.button_record.clicked.connect(self._record_cb)

            self.record_time = self._create_toolbutton(
                [
                    "time.svg",
                    "time_on.svg"
                ],
                "Record pauses between actions",
                True,
                False
            )

            # Input type recording buttons
            cfg = gremlin.config.Configuration()
            self.record_axis = self._create_toolbutton(
                [
                    "record_axis.svg",
                    "record_axis_on.svg"
                ],
                "Record joystick axis events",
                True,
                cfg.macro_record_axis
            )
            self.record_axis.clicked.connect(self._update_record_settings)
            self.record_button = self._create_toolbutton(
                [
                    "record_button.svg",
                    "record_button_on.svg"
                ],
                "Record joystick button events",
                True,
                cfg.macro_record_button
            )
            self.record_button.clicked.connect(self._update_record_settings)
            self.record_hat = self._create_toolbutton(
                [
                    "record_hat.svg",
                    "record_hat_on.svg"
                ],
                "Record joystick hat events",
                True,
                cfg.macro_record_hat
            )
            self.record_hat.clicked.connect(self._update_record_settings)
            self.record_key = self._create_toolbutton(
                [
                    "record_key.svg",
                    "record_key_on.svg"
                ],
                "Record keyboard events",
                True,
                cfg.macro_record_keyboard
            )
            self.record_key.clicked.connect(self._update_record_settings)
            self.record_mouse = self._create_toolbutton(
                [
                    "record_mouse.svg",
                    "record_mouse_on.svg"
                ],
                "Record mouse events",
                True,
                cfg.macro_record_mouse
            )
            self.record_mouse.clicked.connect(self._update_record_settings)

            # Toolbar
            self.toolbar = QtWidgets.QToolBar()
            self.toolbar.setStyleSheet(
                "QToolBar { border: 1px solid #949494; background-color: #dadada; }"
            )
            self.toolbar.setIconSize(QtCore.QSize(16, 16))
            self.toolbar.setOrientation(QtCore.Qt.Vertical)
            self.toolbar.addWidget(self.button_new_entry)
            self.toolbar.addWidget(self.button_delete)
            self.toolbar.addWidget(self.button_pause)
            self.toolbar.addSeparator()
            self.toolbar.addWidget(self.button_record)
            self.toolbar.addWidget(self.record_time)
            self.toolbar.addWidget(self.record_axis)
            self.toolbar.addWidget(self.record_button)
            self.toolbar.addWidget(self.record_hat)
            self.toolbar.addWidget(self.record_key)
            self.toolbar.addWidget(self.record_mouse)

            #required_height = self.toolbar.frameGeometry().height()
            self.toolbar.setMinimumHeight(260)

            # Assemble the entire widget


            self.main_layout.addWidget(self.list_view)
            self.main_layout.addWidget(self.toolbar)

            self.main_layout.addWidget(self.toolbar)
            self.main_layout.addLayout(self.editor_settings_layout)

            self.main_layout.setContentsMargins(0, 0, 0, 0)
        finally:
            MacroWidget.locked = False

    def _create_toolbutton(self, icon_path, tooltip, is_checkable, default_on=True):
        """Creates a new toolbutton with the provided options.

        :param icon_path the path or list of paths of icons
        :param tooltip the tooltip of the button
        :param is_checkable whether or not the button can be toggled
        :param default_on whether or not to toggle the button by default
        """
        from gremlin.util import load_pixmap, load_icon
        button = QtWidgets.QToolButton()
        
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
        else:
            button.setIcon(load_icon(icon_path))
        button.setToolTip(tooltip)
        button.setCheckable(is_checkable)
        button.setChecked(is_checkable and default_on)
        return button

    def _populate_ui(self):
        """Populate the UI with content from the data."""
        self.model = MacroListModel(self.action_data.sequence)
        self.list_view.setModel(self.model)
        self.list_view.setCurrentIndex(self.model.index(0, 0))
        self._edit_action(self.model.index(0, 0))

    def _edit_action(self, model_index):
        """Enable editing of the current action via a editor widget.

        :param model_index the index of the model entry to edit
        """
        self.editor_widget = MacroActionEditor(self.model, model_index)
        old_item = self.editor_settings_layout.takeAt(0)
        old_item.widget().hide()
        old_item.widget().deleteLater()
        self.editor_settings_layout.insertWidget(0, self.editor_widget)

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

    def _pause_cb(self):
        """Adds a pause macro action to the list."""
        self._insert_entry_at_current_index(gremlin.macro.PauseAction(0.250))
        self._refresh_editor_ui()


    def _add_entry(self):
        self._pause_cb()

    def _delete_cb(self):
        """Callback executed when the delete button is pressed."""
        idx = self.list_view.currentIndex().row()
        if 0 <= idx < len(self.action_data.sequence):
            del self.action_data.sequence[idx]
            new_idx = min(len(self.action_data.sequence), max(0, idx - 1))
            self.list_view.setCurrentIndex(
                self.model.index(new_idx, 0, QtCore.QModelIndex())
            )
            self._refresh_editor_ui()

    def _insert_entry_at_current_index(self, entry):
        """Adds the given entry after current selection.

        :param entry the entry to add to the model
        """
        cur_index = self.list_view.currentIndex().row()
        self.model.add_entry(cur_index, entry)
        self.list_view.setCurrentIndex(self.model.index(cur_index+1, 0))
        self._refresh_editor_ui()

    def _append_entry(self, entry):
        """Adds the given entry at the end of the list.

        :param entry the entry to add to the model
        """
        index = self.model.rowCount()
        self.model.add_entry(index, entry)
        self.list_view.setCurrentIndex(self.model.index(index + 1, 0))
        self._refresh_editor_ui()

