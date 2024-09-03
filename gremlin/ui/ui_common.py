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

import enum
import time
import threading
import os
from typing import Optional
import logging
from PySide6 import QtWidgets, QtCore, QtGui
import PySide6.QtGui
import PySide6.QtWidgets
import gremlin.config
import gremlin.error
import qtawesome as qta
import gremlin.event_handler
from gremlin.input_types import InputType
from  gremlin.clipboard import Clipboard
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
from qtpy.QtCore import (
    Qt, QSize, QPoint, QPointF, QRectF,
    QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
    Slot, Property)

from qtpy.QtWidgets import QCheckBox
from qtpy.QtGui import QColor, QBrush, QPaintEvent, QPen, QPainter

from .ui_sliders import QDoubleRangeSlider



from gremlin.util import load_pixmap, load_icon
import gremlin.util



class ContainerViewTypes(enum.Enum):

    """Enumeration of view types used by containers."""

    Action = 1
    Condition = 2
    VirtualButton = 3

    @staticmethod
    def to_string(value):
        try:
            return _ContainerView_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                f"Invalid type in container lookup, {value}"
            )

    @staticmethod
    def to_enum(value):
        try:
            return _ContainerView_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                f"Invalid type in container lookup, {value}"
            )


_ContainerView_to_enum_lookup = {
    "action": ContainerViewTypes.Action,
    "condition": ContainerViewTypes.Condition,
    "virtual button": ContainerViewTypes.VirtualButton
}


_ContainerView_to_string_lookup = {
    ContainerViewTypes.Action: "Action",
    ContainerViewTypes.Condition: "Condition",
    ContainerViewTypes.VirtualButton: "Virtual Button"
}


class AbstractModel(QtCore.QObject):

    """Base class for MVC models."""

    data_changed = QtCore.Signal()

    def __init__(self, parent=None):
        """Creates a new model.

        :param parent the parent of this model
        """
        super().__init__(parent)

    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows
        """
        pass

    def data(self, index):
        """Returns the data entry stored at the provided index.

        :param index the index for which to return data
        :return data stored at the given index
        """
        pass


class AbstractView(QtWidgets.QWidget):

    """Base class for MVC views."""

    # Signal emitted when a entry is selected
    item_selected = QtCore.Signal(int) # index of the item being selected
    item_edit = QtCore.Signal(object, int, object)  # widget, index, model data object
    item_closed = QtCore.Signal(object, int, object)  # widget, index, model data object

    def __init__(self, parent=None):
        """Creates a new view instance.

        :param parent the parent of this view widget
        """
        super().__init__(parent)
        self.model = None

    def set_model(self, model):
        """Sets the model to display with this view.

        :param model the model to visualize
        """
        if self.model is not None:
            self.model.data_changed.disconnect(self.redraw)
        self.model = model
        self._model_changed()
        self.model.data_changed.connect(self.redraw)

    def select_item(self, index):
        """Selects the item at the provided index

        :param index the index of the item to select
        """
        pass

    def redraw(self):
        """Redraws the view."""
        pass

    def _model_changed(self):
        """Called when a model is added or updated to allow user code to run."""
        pass


class LeftRightPushButton(QtWidgets.QPushButton):

    """Implements a push button that distinguishes between left and right
    mouse clicks."""

    # Signal emitted when the button is pressed using the right mouse button
    clicked_right = QtCore.Signal()

    def __init__(self, label, parent=None):
        """Creates a new button instance.

        :param label the text to display on the button
        :param parent the parent of this button
        """
        super().__init__(label, parent)

    def mousePressEvent(self, event):
        """Handles mouse press events.

        :param event the mouse press event to handle
        """
        if event.button() == QtCore.Qt.RightButton:
            self.clicked_right.emit()
        else:
            super().mousePressEvent(event)


class NoKeyboardPushButton(QtWidgets.QPushButton):

    """Standard PushButton which does not react to keyboard input."""

    def __init__(self, *args, **kwargs):
        """Creates a new instance."""
        super().__init__(*args, **kwargs)

    def keyPressEvent(self, event):
        """Handles key press events by ignoring them.

        :param event the key event to handle
        """
        pass


class QFloatLineEdit(QtWidgets.QLineEdit):
    ''' double input validator with optional range limits for input axis
    
        this line edit behaves like a spin box so it's interchangeable
    
    '''

    valueChanged = QtCore.Signal(float) # fires when the value changes

    def __init__(self, data = None, min_range = -1.0, max_range = 1.0, decimals = 3, step = 0.01, parent = None):
        super().__init__(parent)
        self._min_range = min_range
        self._max_range = max_range
        self._step = step
        self._decimals = decimals

        self._validator = QtGui.QDoubleValidator(bottom=min_range, top=max_range)
        self._validator.setLocale(self.locale()) # handle correct floating point separator
        self._validator.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        self.setValidator(self._validator)
        self.textChanged.connect(self._validate)
        self.installEventFilter(self)
        self.setText("0")
        self.setValue(0.0)
        self._data = data

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self.data = value

    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            # handle wheel up/down change
            v = self.value()
            if v is not None:
                if event.angleDelta().y() > 0:
                    # up
                    v += self._step
                else:
                    # down
                    v -= self._step
                v = gremlin.util.clamp(v, self._min_range, self._max_range)
                self.setValue(v)
                self.valueChanged.emit(v)
        elif t == QtCore.QEvent.Type.FocusAboutToChange:
            if not self.hasAcceptableInput():
                return True # skip the event
        elif t == QtCore.QEvent.Type.FocusOut:
            if not self.hasAcceptableInput():
                return True # skip the event
            # format the input to the correct decimals
            self.setValue(self.value())
        return False

        
    def _update_value(self, value):
        other = self.value()
        if value is None or other is None:
            return
        s_value = f"{value:0.{self._decimals}f}"
        if s_value != self.text():
            self.setText(s_value)
        if other != value:
            self.valueChanged.emit(value)


        
    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        if self.hasAcceptableInput():
            self.valueChanged.emit(self.value())

    def setValue(self, value : float):
        ''' sets the value '''
        self._update_value(value)

    def value(self) -> float:
        ''' current value, None if not a valid input'''
        if self.hasAcceptableInput():
            return float(self.text())
        return None
    
    def isValid(self):
        ''' true if the input in the box is currently valid'''
        return self.hasAcceptableInput()
    
    def step(self):
        ''' mouse wheel step value'''
        return self._step
    
    def setStep(self, step):
        self._step = step

    def setSingleStep(self, step):
        self._step = step

    def decimals(self):
        return self._decimals
    
    def setDecimals(self, decimals):
        if decimals < 0:
            decimals = 0
        if self._decimals != decimals:
            self._decimals = decimals
            v = self.value()
            if v is not None:
                # correct to the new number of decimals
                self.setValue(v)

    def setRange(self, bottom, top):
        if top < bottom:
            bottom, top = top, bottom
        self._min_range = bottom
        self._max_range = top
        self._validator.setBottom(bottom)
        self._validator.setTop(top)
        self._update_value(self.value())

    def setMaximum(self, top):
        self._max_range = top
        self._validator.setTop(top)
        self._update_value(self.value())

    def setMinimum(self, bottom):
        self._min_range = bottom
        self._validator.setBottom(bottom)
        self._update_value(self.value())
        
    def minimum(self):
        return self._min_range

    def maximum(self):
        return self._max_range

class QIntLineEdit(QtWidgets.QLineEdit):
    ''' integer input validator with optional range limits for input axis
    
        this line edit behaves like a spin box so it's interchangeable
    
    '''

    valueChanged = QtCore.Signal(float) # fires when the value changes

    def __init__(self, data = None, min_range = -1.0, max_range = 1.0, step = 1, parent = None):
        super().__init__(parent)
        self._min_range = min_range
        self._max_range = max_range
        self._step = step
        

        self._validator = QtGui.QIntValidator(bottom=min_range, top=max_range)
        self._validator.setLocale(self.locale()) # handle correct floating point separator
        self.setValidator(self._validator)
        self.textChanged.connect(self._validate)
        self.installEventFilter(self)
        self.setText("0")
        self.setValue(0)
        self._data = data

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self.data = value

    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            # handle wheel up/down change
            v = self.value()
            if v is not None:
                if event.angleDelta().y() > 0:
                    # up
                    v += self._step
                else:
                    # down
                    v -= self._step
                v = gremlin.util.clamp(v, self._min_range, self._max_range)
                self.setValue(v)
                self.valueChanged.emit(v)
        elif t == QtCore.QEvent.Type.FocusAboutToChange:
            if not self.hasAcceptableInput():
                return True # skip the event
        elif t == QtCore.QEvent.Type.FocusOut:
            if not self.hasAcceptableInput():
                return True # skip the event
            # format the input to the correct decimals
            self.setValue(self.value())
        return False

        
    def _update_value(self, value):
        other = self.value()
        if value is None or other is None:
            return
        s_value = str(value)
        if s_value != self.text():
            self.setText(s_value)
        if other != value:
            self.valueChanged.emit(value)


        
    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        if self.hasAcceptableInput():
            self.valueChanged.emit(self.value())

    def setValue(self, value : int):
        ''' sets the value '''
        self._update_value(value)

    def value(self) -> int:
        ''' current value, None if not a valid input'''
        if self.hasAcceptableInput():
            return int(self.text())
        return None
    
    def isValid(self):
        ''' true if the input in the box is currently valid'''
        return self.hasAcceptableInput()
    
    def step(self):
        ''' mouse wheel step value'''
        return self._step
    
    def setStep(self, step):
        self._step = step

    def setSingleStep(self, step: int):
        self._step = step

    def setRange(self, bottom, top):
        if top < bottom:
            bottom, top = top, bottom
        self._min_range = bottom
        self._max_range = top
        self._validator.setBottom(bottom)
        self._validator.setTop(top)
        self._update_value(self.value())

    def setMaximum(self, top):
        self._max_range = top
        self._validator.setTop(top)
        self._update_value(self.value())

    def setMinimum(self, bottom):
        self._min_range = bottom
        self._validator.setBottom(bottom)
        self._update_value(self.value())

    def minimum(self):
        return self._min_range

    def maximum(self):
        return self._max_range
                


class DynamicDoubleSpinBox(QFloatLineEdit):
    pass

    @property
    def decimal_point(self):
        return self.locale().decimalPoint

class DynamicDoubleSpinBox_legacy(QtWidgets.QDoubleSpinBox):

    """Implements a double spin box which dynamically overwrites entries."""

    valid_chars = [str(v) for v in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]] + ["-"]
    decimal_point = "."

    def __init__(self, parent=None, data = None):
        """Create a new instance with the specified parent.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        DynamicDoubleSpinBox.decimal_point = self.locale().decimalPoint()
        if DynamicDoubleSpinBox.decimal_point not in DynamicDoubleSpinBox.valid_chars:
            DynamicDoubleSpinBox.valid_chars.append(
                DynamicDoubleSpinBox.decimal_point
            )

        self._data = data

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self.data = value

    def validate(self, text, pos):
        """Validates the provided string.

        This takes the pre-validation string and formats it as a float of fixed
        length before submitting it for validation.

        :param text the input to be validated
        :param pos the position in the string
        """
        try:
            # Discard invalid characters
            if 0 <= pos-1 < len(text):
                if text[pos-1] not in DynamicDoubleSpinBox.valid_chars:
                    text = text[:pos-1] + text[pos:]
                    pos -= 1

            # Replace empty parts with the value 0
            point = self.locale().decimalPoint()
            if point in text:
                parts = text.split(point)
                for part in parts:
                    if len(part) == 0:
                        part = "0"
                value_string = f"{parts[0]}.{parts[1]}"
            else:
                value_string = text

            # Convert number to a string representation we can convert to
            # a float so we can truncate the decimal places as required
            
            format_string = f"{{:.{self.decimals():d}f}}"
    
            try:
                value_string = format_string.format(float(value_string))
            except:
                return False

            # Use decimal place separator dictated by the locale settings
            text = value_string.replace(".", DynamicDoubleSpinBox.decimal_point)

            return super().validate(text, pos)
        except (ValueError, IndexError):
            return super().validate(text, pos)



class AbstractInputSelector(QtWidgets.QWidget):


    def __init__(self, change_cb, valid_types, parent=None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.change_cb = change_cb
        self.valid_types = valid_types
        self.device_list = []

        self.device_dropdown = None
        self.input_item_dropdowns = []
        self._device_id_registry = []
        self._input_type_registry = []

        self._initialize()
        self._create_device_dropdown()
        self._create_input_dropdown()

    def get_selection(self):
        device_id = None
        input_id = None
        input_type = None

        device_index = self.device_dropdown.currentIndex()
        if device_index != -1:
            device_id = self._device_id_registry[device_index]
            input_index = self.input_item_dropdowns[device_index].currentIndex()

            if input_index == -1:
                input_index = 0
                input_value = self.input_item_dropdowns[device_index].itemText(
                    input_index)
            else:
                input_value = self.input_item_dropdowns[device_index].currentText()
            input_type = self._input_type_registry[device_index][input_index]

            if input_type == InputType.JoystickAxis:
                input_id = gremlin.types.AxisNames.to_enum(input_value).value
            else:
                input_id = int(input_value.split()[-1])

        return {
            "device_id": device_id,
            "input_id": input_id,
            "input_type": input_type
        }

    def set_selection(self, input_type, device_id, input_id):
        if device_id not in self._device_id_registry:
            return

        # Get the index of the combo box associated with this device
        dev_id = self._device_id_registry.index(device_id)

        # Retrieve the index of the correct entry in the combobox
        input_name = gremlin.common.input_to_ui_string(input_type, input_id)
        entry_id = self.input_item_dropdowns[dev_id].findText(input_name)

        # Select and display correct combo boxes and entries within
        with QtCore.QSignalBlocker(self.device_dropdown):
            self.device_dropdown.setCurrentIndex(dev_id)

            
            for entry in self.input_item_dropdowns:
                with QtCore.QSignalBlocker(entry):
                    entry.setVisible(False)

            entry = self.input_item_dropdowns[dev_id]
            with QtCore.QSignalBlocker(entry):
                entry.setVisible(True)
                entry.setCurrentIndex(entry_id)



    def _update_device(self, index):
        # Hide all selection dropdowns

        for entry in self.input_item_dropdowns:
            with QtCore.QSignalBlocker(entry):
                entry.setVisible(False)

        # Show correct dropdown
        entry = self.input_item_dropdowns[index]
        with QtCore.QSignalBlocker(entry):
            entry.setVisible(True)
            entry.setCurrentIndex(0)
        self._execute_callback()

    def _initialize(self):
        raise gremlin.error.MissingImplementationError(
            "Missing implementation of AbstractInputSelector._initialize"
        )

    def _format_device_name(self, device):
        raise gremlin.error.MissingImplementationError(
            "Missing implementation of AbstractInputSelector._format_device_name"
        )

    def _device_identifier(self, device):
        raise gremlin.error.MissingImplementationError(
            "Missing implementation of AbstractInputSelector._device_identifier"
        )

    def _create_device_dropdown(self):
        self.device_dropdown = QtWidgets.QComboBox(self)
        for device in self.device_list:
            self.device_dropdown.addItem(self._format_device_name(device))
            self._device_id_registry.append(self._device_identifier(device))
        self.main_layout.addWidget(self.device_dropdown)
        self.device_dropdown.activated.connect(self._update_device)
        

    def _create_input_dropdown(self):
        count_map = {
            InputType.JoystickAxis: lambda x: x.axis_count,
            InputType.JoystickButton: lambda x: x.button_count,
            InputType.JoystickHat: lambda x: x.hat_count
        }

        self.input_item_dropdowns = []
        self._input_type_registry = []

        # Create input item selections for the devices. Each selection
        # will be invisible unless it is selected as the active device
        for device in self.device_list:
            selection = QtWidgets.QComboBox(self)
            # selection.setEditable(True)
            # selection.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
            selection.setMaxVisibleItems(20)
            self._input_type_registry.append([])
            self.selection_widget = selection
            

            # Add items based on the input type
            max_col = 32
         
            for input_type in self.valid_types:
                for i in range(count_map[input_type](device)):
                    input_id = i+1
                    if input_type == InputType.JoystickAxis:
                        input_id = device.axis_map[i].axis_index

                    s_ui = gremlin.common.input_to_ui_string(
                        input_type,
                        input_id
                    )
                    selection.addItem(s_ui)
                    
                    self._input_type_registry[-1].append(input_type)

            # Add the selection and hide it
            selection.setVisible(False)
            selection.activated.connect(self._execute_callback)
            self.main_layout.addWidget(selection)
            self.input_item_dropdowns.append(selection)

            selection.currentIndexChanged.connect(self._execute_callback)

        # Show the first entry by default
        if len(self.input_item_dropdowns) > 0:
            self.input_item_dropdowns[0].setVisible(True)
   

    def _execute_callback(self):
        self.change_cb(self.get_selection())

    def sync(self):
        ''' forces the change cb to be called to update dependents based on values '''
        self._execute_callback()



class JoystickSelector(AbstractInputSelector):

    """Widget allowing the selection of input items on a physical joystick."""


    def __init__(self, change_cb, valid_types, parent=None):
        """Creates a new JoystickSelector instance.

        :param change_cb function to call when changes occur
        :param valid_types valid input types for selection
        :param parent the parent of this widget
        """
        super().__init__(change_cb, valid_types, parent)
        

    def _initialize(self):
        potential_devices = sorted(
            gremlin.joystick_handling.joystick_devices(),
            key=lambda x: (x.name, x.device_guid)
        )
        for dev in potential_devices:
            input_counts = {
                InputType.JoystickAxis: dev.axis_count,
                InputType.JoystickButton: dev.button_count,
                InputType.JoystickHat: dev.hat_count
            }

            has_inputs = False
            for valid_type in self.valid_types:
                if input_counts.get(valid_type, 0) > 0:
                    has_inputs = True

            if has_inputs:
                self.device_list.append(dev)

    def _format_device_name(self, device):
        return device.name

    def _device_identifier(self, device):
        return device.device_guid


class VJoySelector(AbstractInputSelector):

    """Widget allowing the selection of vJoy inputs."""





    def __init__(self, change_cb, valid_types, invalid_ids={}, parent=None):
        """Creates a widget to select a vJoy output.

        :param change_cb callback to execute when the widget changes
        :param valid_types the input type to present in the selection
        :param invalid_ids list of vid values of vjoy devices to not consider
        :param parent of this widget
        """
        self.invalid_ids = invalid_ids
        super().__init__(change_cb, valid_types, parent)

    def _initialize(self):
        potential_devices = sorted(
            gremlin.joystick_handling.vjoy_devices(),
            key=lambda x: x.vjoy_id
        )
        for dev in potential_devices:
            input_counts = {
                InputType.JoystickAxis: dev.axis_count,
                InputType.JoystickButton: dev.button_count,
                InputType.JoystickHat: dev.hat_count
            }

            has_inputs = False
            for valid_type in self.valid_types:
                if input_counts.get(valid_type, 0) > 0:
                    has_inputs = True

            if not self.invalid_ids.get(dev.vjoy_id, False) and has_inputs:
                self.device_list.append(dev)

    def _format_device_name(self, device):
        return device.name
        #return f"{device.name} ({device.vjoy_id:d})"
        #return f"vJoy Device {device.vjoy_id:d}"

    def _device_identifier(self, device):
        return device.vjoy_id



class ActionSelector(QtWidgets.QWidget):

    """Widget permitting the selection of actions."""

    # Signal emitted when an action is going to be added
    action_added = QtCore.Signal(str)
    action_paste = QtCore.Signal(object)
    

    def __init__(self, input_type, parent=None):
        """Creates a new selector instance.

        :param input_type the input type for which the action selector is
            being created
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.input_type = input_type

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.action_label = QtWidgets.QLabel("Action")
        self.main_layout.addWidget(self.action_label)
 
        self.action_dropdown = QtWidgets.QComboBox()

        for name in self._valid_action_list():
            self.action_dropdown.addItem(name)
        cfg = gremlin.config.Configuration()
        self.action_dropdown.setCurrentText(cfg.last_action)
        self.action_dropdown.currentIndexChanged.connect(self._action_changed)
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.clicked.connect(self._add_action)

        # clipboard
        self.paste_button = QtWidgets.QPushButton()
        icon = gremlin.util.load_icon("button_paste.svg")
        self.paste_button.setIcon(icon)
        self.paste_button.clicked.connect(self._paste_action)
        self.paste_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.paste_button.setToolTip("Paste Action")

        #clipboard = Clipboard()
        #clipboard.clipboard_changed.connect(self._clipboard_changed)
        #self._clipboard_changed(clipboard)

        self.main_layout.addWidget(self.action_dropdown)
        self.main_layout.addWidget(self.add_button)
        self.main_layout.addWidget(self.paste_button)
        self.main_layout.addStretch(1)

        eh = gremlin.event_handler.EventHandler()
        eh.last_action_changed.connect(self._last_action_changed)

    @QtCore.Slot(object, str)
    def _last_action_changed(self, widget, name):
        if widget != self.action_dropdown:
            with QtCore.QSignalBlocker(self.action_dropdown):
                self.action_dropdown.setCurrentText(name)

    def _action_changed(self):
        ''' remember the last selection '''
        name = self.action_dropdown.currentText()
        config = gremlin.config.Configuration()
        config.last_action = name
        if config.sync_last_selection:
            eh = gremlin.event_handler.EventHandler()
            eh.last_action_changed.emit(self.action_dropdown, name)

    def _valid_action_list(self):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        action_list = []
        # if self.input_type == InputType.JoystickAxis:
        #     action_list.append("Response Curve")
        # else:
        for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
            if self.input_type in entry.input_types:
                action_list.append(entry.name)
        return sorted(action_list)
    

    def _add_action(self, clicked=False):
        """Handles selecting of an action to be added.

        :param clicked flag indicating whether or not the action resulted from
            a click
        """
        self.action_added.emit(self.action_dropdown.currentText())

    def _paste_action(self):
        ''' handle paste action '''
        clipboard = Clipboard()
        # validate the clipboard data is an action and is of the correct type for the input/container
        if clipboard.is_action:
            action_name = clipboard.data.name
            if action_name in self._valid_action_list():
                # valid action - clone it and add it
                # logging.getLogger("system").info("Clipboard paste action trigger...")
                self.action_paste.emit(clipboard.data)
            else:
                # dish out a message
                message_box = QtWidgets.QMessageBox(
                    QtWidgets.QSystemTrayIcon.MessageIcon.Warning,
                    f"Invalid Action type ({action_name})",
                    "Unable to paste action because it is not valid for the current input")
                message_box.showNormal()

    def _clipboard_changed(self, clipboard):
        ''' handles paste button state based on clipboard data '''
        self.paste_button.setEnabled(clipboard.is_action)
        ''' updates the paste button tooltip with the current clipboard contents'''
        if clipboard.is_action:
            self.paste_button.setToolTip(f"Paste action ({clipboard.data.name})")
        else:
            self.paste_button.setToolTip(f"Paste action (not available)")
    
        

class BaseDialogUi(QtWidgets.QWidget):

    """Base class for all UI dialogs.

    The main purpose of this class is to provide the closed signal to dialogs
    so that the main application can react to the dialog being closed if
    desired.
    """

    # Signal emitted when the dialog is being closed
    closed = QtCore.Signal()

    def __init__(self, parent=None):
        """Creates a new options UI instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

    def closeEvent(self, event):
        """Closes the calibration window.

        :param event the close event
        """
        if hasattr(self, "confirmClose"):
            self.confirmClose(event)
        if event.isAccepted():
            self.closed.emit()


def _inheritance_tree_to_labels(labels, tree, level):
    """Generates labels to use in the dropdown menu indicating inheritance.

    :param labels the list containing all the labels
    :param tree the part of the tree to be processed
    :param level the indentation level of this tree
    """
    for mode, children in sorted(tree.items()):
        labels.append((mode,
            f"{"  " * level}{"" if level == 0 else " "}{mode}"))
        _inheritance_tree_to_labels(labels, children, level+1)

def get_mode_list(profile_data):
    profile = profile_data
    mode_list = []

    # Create mode name labels visualizing the tree structure
    inheritance_tree = profile.build_inheritance_tree()
    labels = []
    _inheritance_tree_to_labels(labels, inheritance_tree, 0)

    # Filter the mode names such that they only occur once below
    # their correct parent
    mode_names = []
    display_names = []
    for entry in labels:
        if entry[0] in mode_names:
            idx = mode_names.index(entry[0])
            if len(entry[1]) > len(display_names[idx]):
                del mode_names[idx]
                del display_names[idx]
                mode_names.append(entry[0])
                display_names.append(entry[1])
        else:
            mode_names.append(entry[0])
            display_names.append(entry[1])

    # Add properly arranged mode names to the drop down list
    for display_name, mode_name in zip(display_names, mode_names):
        mode_list.append((display_name, mode_name))


    return mode_list



class ModeWidget(QtWidgets.QWidget):

    """Displays the ui for mode selection and management of a device."""

    # Signal emitted when the mode changes
    edit_mode_changed = QtCore.Signal(str) # when the edit mode changes
    

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent widget
        """
        QtWidgets.QWidget.__init__(self, parent)

        self.mode_list = []

        self.profile = None
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self._create_widget()


    def setRuntimeDisabled(self, value):
        ''' enables or disables profile runtime behavior'''

        el = gremlin.event_handler.EventListener()
        try:
            if value:
                # hook the profile start/stop to enable/disable at runtime
                el.profile_start.connect(self._profile_start_cb)
                el.profile_stop.connect(self._profile_stop_cb)
            else:
                el.profile_start.disconnect(self._profile_start_cb)
                el.profile_stop.disconnect(self._profile_stop_cb)
        except:
            pass
    

    @QtCore.Slot()
    def _profile_start_cb(self):
        self.setEnabled(False)
    @QtCore.Slot()
    def _profile_stop_cb(self):
        self.setEnabled(True)


    def populate_selector(self, profile_data, current_mode=None, emit = False):
        """Adds entries for every mode present in the profile.

        :param profile_data the device for which the mode selection is generated
        :param current_mode the currently active mode
        """
        # To prevent emitting lots of change events the slot is first
        # disconnected and then at the end reconnected again.
        with QtCore.QSignalBlocker(self.edit_mode_selector):
            self.profile = profile_data

            # Remove all existing items in QT6 clear() doesn't always work
            #self.edit_mode_selector.clear()
            while self.edit_mode_selector.count() > 0:
                    self.edit_mode_selector.removeItem(0)
            
            mode_list = get_mode_list(profile_data)
            self.mode_list = [x[1] for x in mode_list]
            # Create mode name labels visualizing the tree structure
            inheritance_tree = self.profile.build_inheritance_tree()
            labels = []
            _inheritance_tree_to_labels(labels, inheritance_tree, 0)

            # Filter the mode names such that they only occur once below
            # their correct parent
            mode_names = []
            display_names = []
            for entry in labels:
                if entry[0] in mode_names:
                    idx = mode_names.index(entry[0])
                    if len(entry[1]) > len(display_names[idx]):
                        del mode_names[idx]
                        del display_names[idx]
                        mode_names.append(entry[0])
                        display_names.append(entry[1])
                else:
                    mode_names.append(entry[0])
                    display_names.append(entry[1])

            # # Select currently active mode
            # if len(mode_names) > 0:
            #     if current_mode is None or current_mode not in self.mode_list:
            #         # pick the first one
            #         current_mode = mode_names[0]

            # Add properly arranged mode names to the drop down list
            index = 0
            current_index = 0
            last_edit_mode = gremlin.config.Configuration().get_profile_last_edit_mode()
            for display_name, mode_name in zip(display_names, mode_names):
                self.edit_mode_selector.addItem(display_name, mode_name)
                self.mode_list.append(mode_name)
                if mode_name == last_edit_mode:
                    current_index = index
                index += 1

            self.edit_mode_selector.setCurrentIndex(current_index)
            if emit:
                self._edit_mode_changed_cb(current_index)


    @QtCore.Slot(int)
    def _edit_mode_changed_cb(self, idx):
        """Callback function executed when the mode selection changes.

        :param idx id of the now selected entry
        """
        # save the setup
        new_mode = self.mode_list[idx]
        self.edit_mode_changed.emit(new_mode)




    def _create_widget(self):
        """Creates the mode selection and management dialog."""
        # Size policies used
        from gremlin.util import load_icon
        min_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Minimum
        )
        exp_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Minimum
        )

        self.profile_options_button_widget = QtWidgets.QPushButton()
        self.profile_options_button_widget.setIcon(load_icon("fa.gear"))
        self.profile_options_button_widget.setToolTip("Profile Options")
        self.profile_options_button_widget.clicked.connect(self._profile_options_cb)



        # Create mode selector and related widgets
        self.edit_label = QtWidgets.QLabel("Profile Edit Mode")
        self.edit_label.setSizePolicy(min_min_sp)
        self.edit_mode_selector = QtWidgets.QComboBox()
        self.edit_mode_selector.setSizePolicy(exp_min_sp)
        self.edit_mode_selector.setMinimumContentsLength(20)
        self.edit_mode_selector.setToolTip("Selects the active profile mode being edited")
        

        # add the mode change button
        self.mode_change = QtWidgets.QPushButton()
        self.mode_change.setIcon(load_icon("manage_modes.svg"))
        self.mode_change.setToolTip("Manage Profile Modes")
        self.mode_change.clicked.connect(self._manage_modes_cb)

        # Connect signal
        self.edit_mode_selector.currentIndexChanged.connect(self._edit_mode_changed_cb)

        # Add widgets to the layout
        self.main_layout.addStretch(10)
                
        self.main_layout.addWidget(self.edit_label)
        self.main_layout.addWidget(self.edit_mode_selector)
        self.main_layout.addWidget(self.mode_change)
        self.main_layout.addWidget(self.profile_options_button_widget)

    def _manage_modes_cb(self):
        ''' calls up the mode change dialog '''
        import gremlin.shared_state
        ui = gremlin.shared_state.ui
        ui.manage_modes()

    def _profile_options_cb(self):
        import gremlin.ui.dialogs
        dialog = gremlin.ui.dialogs.ProfileOptionsUi()
        dialog.exec()

    def currentIndex(self):
        return self.edit_mode_selector.currentIndex()
    
    def setCurrentIndex(self, index):
        self.edit_mode_selector.setCurrentIndex(index)

    def setCurrentMode(self, current_mode):
        index = self.edit_mode_selector.findData(current_mode)
        if index != -1:
            with QtCore.QSignalBlocker(self):
                self.setCurrentIndex(index)
        else:
            logging.getLogger("system").error(f"SetModeError: mode '{current_mode}' is not defined")

    def setShowModeEdit(self, value):
        ''' determines if the mode edit button is visible or not '''
        self.mode_change.setVisible(value)

    def setShowProfileOptions(self, value):
        ''' determines if the profile option button is visible or not '''
        self.profile_options_button_widget.setVisible(value)

    def setLabelText(self, text):
        ''' changes the label text if needed '''
        self.edit_label.setText(text)


class InputListenerWidget(QtWidgets.QFrame):

    """Widget overlaying the main gui while waiting for the user
    to press a key."""

    item_selected = QtCore.Signal(object) # called when the items are selected

    def __init__(
            self,
            event_types,
            return_kb_event=False,
            multi_keys=False,
            filter_func=None,
            parent=None
    ):
        """Creates a new instance.

        :param callback the function to pass the key pressed by the
            user to
        :param event_types the events to capture and return
        :param return_kb_event whether or not to return the kb event (True) or
            the key itself (False)
        :param multi_keys whether or not to return multiple key presses (True)
            or return after the first initial press (False)
        :param filter_func function applied to inputs which filters out more
            complex unwanted inputs
        :param parent the parent widget of this widget
        """
        super().__init__(parent)
        from gremlin.keyboard import key_from_code, key_from_name
        self._event_types = event_types
        self._return_kb_event = return_kb_event
        self._multi_keys = multi_keys
        self.filter_func = filter_func
        self._aborting = False
        self._closing = False
        self._abort_timer = threading.Timer(1.0, self._abort_request)
        self._multi_key_storage = []

        self._close_on_key = not (InputType.Keyboard in event_types or InputType.KeyboardLatched in event_types)
        self._esc_key = key_from_name("esc")

        # Create and configure the ui overlay
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(
            QtWidgets.QLabel(f"""<center>Please press the desired {self._valid_event_types_string()}.<br/><br/>Hold ESC{'' if self._close_on_key else ' for one second'} to abort.</center>""")
        )

        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setFrameStyle(QtWidgets.QFrame.Plain | QtWidgets.QFrame.Box)
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.DarkGray)
        self.setPalette(palette)
        

        # Disable ui input selection on joystick input
        gremlin.shared_state.push_suspend_highlighting()

        # Start listening to user key presses
        event_listener = gremlin.event_handler.EventListener()
        event_listener.keyboard_event.connect(self._kb_event_cb)
        if InputType.JoystickAxis in self._event_types or \
                InputType.JoystickButton in self._event_types or \
                InputType.JoystickHat in self._event_types:
            event_listener.joystick_event.connect(self._joy_event_cb)
        elif InputType.Mouse in self._event_types:
            if not event_listener.mouseEnabled():
                # hook mouse
                event_listener.enableMouse()

            gremlin.windows_event_hook.MouseHook().start()
            event_listener.mouse_event.connect(self._mouse_event_cb)


    def _joy_event_cb(self, event):
        """Passes the pressed joystick event to the provided callback
        and closes the overlay.

        This only passes on joystick button presses.

        :param event the keypress event to be processed
        """
        # Only react to events we're interested in
        if event.event_type not in self._event_types:
            return
        if self.filter_func is not None and not self.filter_func(event):
            return

        # Ensure the event corresponds to a significant enough change in input
        process_event = gremlin.input_devices.JoystickInputSignificant().should_process(event)
        if event.event_type == InputType.JoystickButton:
            process_event &= not event.is_pressed

        if process_event:
            gremlin.input_devices.JoystickInputSignificant().reset()
            self.item_selected.emit(event)
            self.close()

    def _kb_event_cb(self, event):
        """Passes the pressed key to the provided callback and closes
        the overlay.

        :param event
        the keypress event to be processed
        """

        if self._aborting:
            self.close()

        key = gremlin.keyboard.KeyMap.from_event(event)

        # print (f"Head event: {event}  {key}")

        if self._close_on_key:
            if key == self._esc_key:
                self.close()
            return # ignore keys otherwise

        # Return immediately once the first key press is detected
        if not self._multi_keys:
            if event.is_pressed and key == self._esc_key:
                if not self._abort_timer.is_alive():
                    self._abort_timer.start()
            elif not event.is_pressed and \
                    InputType.Keyboard in self._event_types:
                if not self._return_kb_event:
                    self.item_selected.emit(key)
                else:
                    self.item_selected.emit(event)
                self._abort_timer.cancel()
                self.close()
        # Record all key presses and return on the first key release
        else:
            if event.is_pressed:
                if InputType.Keyboard in self._event_types:
                    if not self._return_kb_event:
                        self._multi_key_storage.append(key)
                    else:
                        self._multi_key_storage.append(event)
                if key == self._esc_key:
                    # Start a timer and close if it expires, aborting the
                    # user input request
                    if not self._abort_timer.is_alive():
                        self._abort_timer.start()
            else:
                
                self._abort_timer.cancel()
                if not self._aborting:
                    self.item_selected.emit(self._multi_key_storage)
                self.close()

        # Ensure the timer is cancelled and reset in case the ESC is released
        # and we're not looking to return keyboard events
        if key == self._esc_key and not event.is_pressed:
            self._abort_timer.cancel()
            self._abort_timer = threading.Timer(1.0, self._abort_request)

    def _mouse_event_cb(self, event):
        self.item_selected.emit(event)
        self.close()

    def _abort_request(self):
        import time
        self._aborting = True
        if self._abort_timer.is_alive():
            self._abort_timer.cancel()
            time.sleep(0.1)

    
    def closeEvent(self, evt):
        """Closes the overlay window."""
        event_listener = gremlin.event_handler.EventListener()
        event_listener.keyboard_event.disconnect(self._kb_event_cb)
        if InputType.JoystickAxis in self._event_types or \
                InputType.JoystickButton in self._event_types or \
                InputType.JoystickHat in self._event_types:
            event_listener.joystick_event.disconnect(self._joy_event_cb)
        elif InputType.Mouse in self._event_types:
            event_listener.mouse_event.disconnect(self._mouse_event_cb)

        # Stop mouse hook in case it is running
        gremlin.windows_event_hook.MouseHook().stop()

        # restore highlighting
        gremlin.shared_state.pop_suspend_highlighting()

        # print ("input widget close")
        super().closeEvent(evt)
        


    def _valid_event_types_string(self):
        """Returns a formatted string containing the valid event types.

        :return string representing the valid event types
        """
        valid_str = []
        if InputType.JoystickAxis in self._event_types:
            valid_str.append("Axis")
        if InputType.JoystickButton in self._event_types:
            valid_str.append("Button")
        if InputType.JoystickHat in self._event_types:
            valid_str.append("Hat")
        if InputType.Keyboard in self._event_types:
            valid_str.append("Key")

        return ", ".join(valid_str)


def clear_layout(layout):
    """Removes all items from the given layout.

    :param layout the layout from which to remove all items
    """
    while layout.count() > 0:
        child = layout.takeAt(0)
        if child.layout():
            clear_layout(child.layout())
        elif child.widget():
            child.widget().hide()
            child.widget().deleteLater()
        layout.removeItem(child)


class NoWheelComboBox (QtWidgets.QComboBox):
    ''' implements a combo box with no-wheel scrolling to avoid inadvertent switching of entries while scolling containers '''

    def __init__(self, parent = None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        # blitz wheel events if the box is not in focus
        if self.hasFocus():
            return super().wheelEvent(event)
        
    
class ConfirmPushButton(QtWidgets.QPushButton):
    ''' confirmation push button '''

    confirmed = QtCore.Signal(object)

    def __init__(self, text = None, title = "Confirmation Required", prompt = "Are you sure?", show_callback = None, parent = None ) -> None:
        ''' shows a confirm dialog box on click
        
        :param text button text
        :param title dialog title
        :param prompt dialog body (question)
        :param show_callback boolean callback that determines if the dialog should show (return true if it should)
        '''
        super().__init__(parent)

        if text:
            self.setText(text)

        self.prompt = prompt
        self.title = title
        self.show_callback = show_callback

        self.clicked.connect(self._clicked_cb)


    def _clicked_cb(self):
        if self.show_callback is not None:
            result = self.show_callback()
            if not result:
                return
        
        from gremlin.util import load_pixmap
        message_box = QtWidgets.QMessageBox()
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setText(self.title)
        message_box.setInformativeText(self.prompt)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self.confirmed.emit(self)
        
class ConfirmBox():
    def __init__(self, title = "Confirmation Required", prompt = "Are you sure?", parent = None):

        from gremlin.util import load_pixmap
        self._message_box = QtWidgets.QMessageBox(parent = parent)
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        self._message_box.setIconPixmap(pixmap)
        self._message_box.setText(title)
        self._message_box.setInformativeText(prompt)
        self._message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        self._message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(self._message_box)

    def show(self):
        return self._message_box.exec()

class MessageBox():
    def __init__(self, title = "Notice", prompt = "Operation", parent = None):

        from gremlin.util import load_pixmap
        self._message_box = QtWidgets.QMessageBox(parent = parent)
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        self._message_box.setIconPixmap(pixmap)
        self._message_box.setText(title)
        self._message_box.setInformativeText(prompt)
        self._message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok
            )
        self._message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(self._message_box)
        self._message_box.exec()
    



class QHLine(QtWidgets.QFrame):
    ''' horizontal line '''
    def __init__(self, parent = None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        
class QWrapableLabel(QtWidgets.QLabel):
    ''' wrappable label '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setWordWrapAt(self, char):
        ''' sets the word wrap on a given character '''
        newtext = self.text().replace(char, f"{char}\u200b")
        self.setText(newtext)
        self.setWordWrap(True)

class QIconLabel(QtWidgets.QWidget):
    ''' label with an icon using the QAWESEOME lib '''

    IconSize = QtCore.QSize(16, 16)
    HorizontalSpacing = 2

    def __init__(self, icon_path = None, text = None, stretch=True, use_qta = False, icon_color = None, parent = None):
        super().__init__(parent)

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self._icon_widget = QtWidgets.QLabel()
        if icon_path:
            self.setIcon(icon_path, use_qta, color = icon_color)
            
        layout.addWidget(self._icon_widget)
        layout.addSpacing(self.HorizontalSpacing)

        self._label_widget =  QWrapableLabel(text)
        self._label_widget.setWordWrap(True)
        layout.addWidget(self._label_widget)

        if stretch:
            layout.addStretch()

    def setIcon(self, icon_path = None, use_qta = True, color = None):
        ''' sets the icon of the label, pass a blank or None path to clear the icon'''
        if icon_path:
            if use_qta:
                if color:
                    pixmap = qta.icon(icon_path, color=color).pixmap(self.IconSize)
                else:
                    pixmap = qta.icon(icon_path).pixmap(self.IconSize)
            else:
                pixmap = load_pixmap(icon_path) if icon_path else None
        else:
            pixmap = None
        if pixmap:
            pixmap = pixmap.scaled(QIconLabel.IconSize, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._icon_widget.setPixmap(pixmap)
        else:
            # clear the pixmap
            self._icon_widget.setPixmap(QtGui.QPixmap())
        
    def setText(self, text = None):
        ''' sets the text of the label '''
        if text:
            self._label_widget.setText(text)
        else:
            self._label_widget.setText("")

    def setTextMinWidth(self, value):
        self._label_widget.setMinimumWidth(value)

    def showIcon(self):
        ''' hides the icon '''
        self._icon_widget.setVisible(True)

    def hideIcon(self):
        ''' shows the icon '''
        self._icon_widget.setVisible(False)

    def text(self):
        ''' gets the text of the widget '''
        return self._icon_widget.text()
    
class QDataCheckbox(QtWidgets.QCheckBox):
    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, parent)
        self._data = data

    @property
    def data(self):
        return self._data
    
    @data.setter
    def data(self, value):
        self._data = value


class QDataPushButton(QtWidgets.QPushButton):
    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, parent)
        self._data = data

    @property
    def data(self):
        return self._data
    
    @data.setter
    def data(self, value):
        self._data = value


class QDataLineEdit(QtWidgets.QLineEdit):
    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, parent)
        self._data = data
        self.setStyleSheet("QLineEdit{border: #8FBC8F;}")

    @property
    def data(self):
        return self._data
    
    @data.setter
    def data(self, value):
        self._data = value


class QDataComboBox(QtWidgets.QComboBox):
    ''' a combo box that has a data property to track an object associated with the checkbox '''
    def __init__(self, data = None, parent = None):
        super().__init__(parent)
        self._data = data

    @property
    def data(self):
        return self._data
    
    @data.setter
    def data(self, value):
        self._data = value


class QPathLineItem(QtWidgets.QWidget):
    ''' An editable text input line with a file selector button '''

    open = QtCore.Signal(object) # event that fires when the open button is clicked, and passes the control
    pathChanged = QtCore.Signal(object, str) # fires when the line item changes

    IconSize = QtCore.QSize(16, 16)

    def __init__(self, header = None, text = None, data = None, dir_mode = False, parent = None, open_tooltip_text = "Browse"):
        '''
        displays the path to a file or a folder
        :param: header - the header text
        :param: text - the default content
        :data: optional data parameters
        :dir_mode: true if the entry is a folder, false if it's a file
        
        '''
        super().__init__(parent)

        self._text = text
        self._header = header
        self._dir_mode = dir_mode
        

        self._file_widget = QtWidgets.QLineEdit()
        self._file_widget.installEventFilter(self)
        self._file_widget.setText(text)
        self._file_widget.textChanged.connect(self._file_changed)
        self._open_button = QtWidgets.QPushButton("...")
        self._open_button.setMaximumWidth(20)
        self._open_button.clicked.connect(self._open_button_cb)
        if open_tooltip_text:
            self._open_button.setToolTip(open_tooltip_text)
        self._icon_widget = QtWidgets.QLabel()
        self._icon_widget.setMaximumWidth(20)
        self._layout = QtWidgets.QHBoxLayout()

        if header:
            self._header_widget = QtWidgets.QLabel(header)
            self._layout.addWidget(self._header_widget)

        self._layout.addWidget(self._icon_widget)
        self._layout.addWidget(self._file_widget)
        self._layout.addWidget(self._open_button)
        self._layout.setContentsMargins(0,0,0,0)

        self._data = data

        self._file_changed()
        
        self.setLayout(self._layout)

    @property
    def header_width(self):
        return self._header_widget.frameGeometry().width()
    
    @header_width.setter
    def header_width(self, value):
        self._header_widget.setMaximumWidth(value)
        self._header_widget.setMinimumWidth(value)

    def _open_button_cb(self):
        self.open.emit(self)

    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            new_text = self._file_widget.text()
            if self._text != new_text:
                self._text = new_text
                self.pathChanged.emit(self, self._text)
        return False

    def _setIcon(self, icon_path = None, use_qta = True, color = None):
        ''' sets the icon of the label, pass a blank or None path to clear the icon'''
        if icon_path:
            if use_qta:
                if color:
                    pixmap = qta.icon(icon_path, color=color).pixmap(self.IconSize)
                else:
                    pixmap = qta.icon(icon_path).pixmap(self.IconSize)
            else:
                pixmap = load_pixmap(icon_path) if icon_path else None
        else:
            pixmap = None
        if pixmap:
            pixmap = pixmap.scaled(QIconLabel.IconSize, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._icon_widget.setPixmap(pixmap)
        else:
            # clear the pixmap
            self._icon_widget.setPixmap(QtGui.QPixmap())
        
    def setText(self, text = None):
        ''' sets the text of the label '''
        with QtCore.QSignalBlocker(self._file_widget):
            if text:
                self._text = text
                self._file_widget.setText(text)
            else:
                self._text = ""
                self._file_widget.setText("")
        self._file_changed()
    

    def text(self):
        return self._text

    def showIcon(self):
        ''' hides the icon '''
        self._icon_widget.setVisible(True)

    def hideIcon(self):
        ''' shows the icon '''
        self._icon_widget.setVisible(False)


    def _file_changed(self):
        fname = self._file_widget.text()

        valid = os.path.isdir(fname) if self._dir_mode else os.path.isfile(fname)
        if valid:
            self._setIcon("fa.check", color="green")
        else:
            self._setIcon("fa.exclamation-circle", color="red")
        self._text = fname
        self.pathChanged.emit(self, self._text)

    @property
    def valid(self):
        ''' true if the file exists '''
        return os.path.isfile(self._text)
    
    @property
    def data(self):
        ''' object reference for this widget '''
        return self._data
    
    @data.setter
    def data(self, value):
        self._data = value


class ButtonStateWidget(QtWidgets.QWidget):
    ''' visualizes the state of a button '''
    
    def __init__(self, parent = None):
        super().__init__(parent)
        icon_size = QtCore.QSize(16,16)
        self._button_widget = QtWidgets.QLabel()
        self._button_widget.setContentsMargins(0,0,0,0)
        on_icon = load_icon("mdi.record",use_qta=True,qta_color="red")
        self._on_pixmap = on_icon.pixmap(icon_size)
        off_icon = load_icon("mdi.record",use_qta=True,qta_color="#979EA8")
        self._off_pixmap = off_icon.pixmap(icon_size)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.addWidget(self._button_widget)
        self.setContentsMargins(0,0,0,0)

        
    def hookDevice(self, device_guid, input_id):
        ''' hooks an axis '''
        self._device_guid = device_guid
        self._input_id = input_id
        

        # read the current value
        is_pressed = gremlin.joystick_handling.dinput.DILL().get_button(device_guid, input_id)
        eh = gremlin.event_handler.EventListener()
        eh.joystick_event.connect(self._event_handler)
        self._update_value(is_pressed)

    def unhookDevice(self):
        eh = gremlin.event_handler.EventListener()
        eh.joystick_event.disconnect(self._event_handler)

    def _event_handler(self, event):
        if gremlin.shared_state.is_running or event.is_axis:
            return
        if self._device_guid != event.device_guid or self._input_id != event.identifier:
            return
        self._update_value(event.is_pressed)

    def _update_value(self, is_pressed):
        if is_pressed:
            self._button_widget.setPixmap(self._on_pixmap)
            #self._button_widget.setText("pressed")
        else:
            self._button_widget.setPixmap(self._off_pixmap)
            #self._button_widget.setText(" ")




class AxisStateWidget(QtWidgets.QWidget):

    """Visualizes the current state of an axis."""
    
    css_vertical = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 1, y2: 0,stop: 0 #78d,stop: 0.4999 #46a,stop: 0.5 #45a,stop: 1 #238 ); border-radius: 7px; border: 1px solid black;}"
    #css_horizontal = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 0, y2: 1,stop: 0 #78d,stop: 0.4999 #46a,stop: 0.5 #45a,stop: 1 #238 ); border-radius: 7px; border: 1px solid black;}"
    css_horizontal = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 0, y2: 1,stop: 0 #77a ,stop: 0.4999 #477,stop: 0.5 #45a,stop: 1 #238 ); border-radius: 7px; border: 1px solid black;}"
    
    valueChanged = QtCore.Signal(float)

    def __init__(self, axis_id = None, show_percentage = True, show_value = True, show_label = True, orientation = QtCore.Qt.Orientation.Vertical, parent=None):
        """Creates a new instance.

        :param axis_id id of the axis, used in the label
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._scale_factor = 1000
        if orientation == QtCore.Qt.Orientation.Vertical:
            self.main_layout = QtWidgets.QVBoxLayout(self)
        else:
            self.main_layout = QtWidgets.QHBoxLayout(self)

        self._progress_widget = QtWidgets.QProgressBar()
        self._progress_widget.setOrientation(orientation)
        self._progress_widget.setTextVisible(False)

        self._orientation = orientation
        self._show_percentage = show_percentage
        self._show_value = show_value
        self._show_label = show_label

        self._readout_widget = QtWidgets.QLabel()
        #self._readout_widget.setVisible(show_percentage or show_label)

        self._label_widget = QtWidgets.QLabel()
        self._label_widget.setVisible(show_label)
        if axis_id:
            self.setLabel(f"Axis {axis_id}")

        self.main_layout.addWidget(self._label_widget)
        self.main_layout.addWidget(self._progress_widget)
        self.main_layout.addWidget(self._readout_widget)
        self.main_layout.addStretch()
        self._min_range = -1.0
        self._max_range = 1.0
        self._device_guid = None
        self._input_id = None
        self._value = 0
        self._raw_value = 0
        self._reverse = False
        self_decimals = 3
        
        self._width = 10
        self._update_css()
        self._update_range()

    
    
    

    def _create_primitives(self):
        self._marker = [
            QtCore.QPoint(0,0),
            QtCore.QPoint(-10,-5),
            QtCore.QPoint(-5,10)
        ]

    def setPercentageVisible(self, value: bool):
        ''' shows or hides the percentage value on the axis '''
        self._show_percentage = value
        self._readout_widget.setVisible(value or self._show_value)

    def setValueVisible(self, value: bool):
        self._show_value = value
        self._readout_widget.setVisible(value or self._show_percentage)

    def _update_css(self):
        if self._orientation == QtCore.Qt.Orientation.Vertical:
            css = AxisStateWidget.css_vertical + f";width {self._width}px"
            self._progress_widget.setMaximumWidth(self._width)
            
        elif self._orientation == QtCore.Qt.Orientation.Horizontal:
            css = AxisStateWidget.css_horizontal+ f";height {self._width}px"
            self._progress_widget.setMaximumHeight(self._width)

        self._progress_widget.setStyleSheet(css)

    def setLabel(self, value : str):
        ''' sets the label for the axis '''
        self._label_widget.setText(value)

    def setLabelVisible(self, value: bool):
        self._show_label = value
        self._label_widget.setVisible(value)

    def setWidth(self, value):
        if value > 0:
            self._width = value
            self._update_css()

    def value(self):
        return self._value

    def setValue(self, value):
        """Sets the value shown by the widget.

        :param value new value to show
        """
        if value < self._min_range:
            value = self._min_range
        if value > self._max_range:
            value = self._max_range
        value += 0   # avoid negative 0 (WHY?)
        self._value = value

        if self._reverse:
            value = gremlin.util.scale_to_range(value, invert=True)

        scaled_value = self._scale_factor * value
        #print (f"{scaled_value}")
        self._progress_widget.setValue(scaled_value)
        self._progress_widget.update()
        readout = ""
        if self._show_value:
            readout = f"{value:+0.3f}"
        if self._show_percentage:
            percent = int(round(100 * value / (self._max_range - self._min_range)))
            if readout:
                readout += " "
            readout += f"{percent:d} %"
        self._readout_widget.setText(readout)
        self.valueChanged.emit(self._value)

    def value(self):
        ''' gets the current value '''
        return self._value

    def setRange(self, min = -1.0, max = 1.0, decimals = 3):
        ''' sets the range of the widget '''
        if min > max:
            max, min = min, max
        self._min_range = min
        self._max_range = max
        self._decimals = decimals
        self._update_range()

    def _update_range(self):
        self._progress_widget.setRange(
            self._scale_factor * self._min_range,
            self._scale_factor * self._max_range
        )
        self.setValue(self._value)

    def setMaximum(self, value):
        ''' sets the upper range value '''
        self.setRange(self._min_range, value)

    def setMinimum(self, value):
        ''' sets the lower range value'''
        self.setRange(value, self._max_range)

    def setReverse(self, value):
        self._reverse = value
        self.setValue(self._value)

    def reverse(self):
        ''' reverse flag '''
        return self._reverse

    def hookDevice(self, device_guid, input_id):
        ''' hooks an axis '''
        self._device_guid = device_guid
        self._input_id = input_id
        self._scale_factor = 1000
        self._value = -1
        self.setRange(-1, 1)

        # read the current value
        raw_value = gremlin.joystick_handling.dinput.DILL().get_axis(device_guid, input_id)
        eh = gremlin.event_handler.EventListener()
        eh.joystick_event.connect(self._event_handler)
        self._update_value(raw_value)

    def unhookDevice(self):
        eh = gremlin.event_handler.EventListener()
        eh.joystick_event.disconnect(self._event_handler)

    def _event_handler(self, event):
        if gremlin.shared_state.is_running or not event.is_axis:
            return
        
        if self._device_guid != event.device_guid or self._input_id != event.identifier:
            return
        self._update_value(event.raw_value)

    def _update_value(self, raw_value):
        # invert the input if needed
        value = gremlin.util.scale_to_range(raw_value, source_min = -32767, source_max = 32767, target_min = self._min_range, target_max = self._max_range)
        self.setValue(value)
        

        
class AxesCurrentState(QtWidgets.QGroupBox):

    """Displays the current state of all axes on a device."""

    def __init__(self, device, parent=None):
        """Creates a new instance.

        :param device the device of which to display the axes sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.device = device
        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Axes")
        else:
            self.setTitle(f"{device.name} - Axes")

        self.axes = [None]
        axes_layout = QtWidgets.QHBoxLayout()
        for i in range(device.axis_count):
            axis = AxisStateWidget(i+1)
            axis.setValue(0.0)
            self.axes.append(axis)
            axes_layout.addWidget(axis)
        axes_layout.addStretch()
        self.setLayout(axes_layout)

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if event.event_type == InputType.JoystickAxis:
            axis_id = gremlin.joystick_handling.linear_axis_index(
                self.device.axis_map,
                event.identifier
            )
            self.axes[axis_id].setValue(event.value)


class HatWidget(QtWidgets.QWidget):

    """Widget visualizing the state of a hat."""

    # Polygon path for a triangle
    triangle = QtGui.QPolygon(
        [QtCore.QPoint(-10, 0), QtCore.QPoint(10, 0), QtCore.QPoint(0, 15)]
    )

    # Mapping from event values to rotation angles
    lookup = {
        (0, 0): -1,
        (0, 1): 180,
        (1, 1): 225,
        (1, 0): 270,
        (1, -1): 315,
        (0, -1): 0,
        (-1, -1): 45,
        (-1, 0): 90,
        (-1, 1): 135
    }

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.angle = -1

    def minimumSizeHint(self):
        """Returns the minimum size of the widget.

        :return the widget's minimum size
        """
        return QtCore.QSize(120, 120)

    def set_angle(self, state):
        """Sets the current direction of the hat.

        :param state the direction of the hat
        """
        self.angle = HatWidget.lookup.get(state, -1)
        self.update()

    def paintEvent(self, event):
        """Draws the entire hat state visualization.

        :param event the paint event
        """
        # Define pens and brushes
        pen_default = QtGui.QPen(QtGui.QColor("#8f8f91"))
        pen_default.setWidth(2)
        pen_active = QtGui.QPen(QtGui.QColor("#661714"))
        pen_active.setWidth(2)
        brush_default = QtGui.QBrush(QtGui.QColor("#f6f7fa"))
        brush_active = QtGui.QBrush(QtGui.QColor("#b22823"))

        # Prepare painter instance
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        painter.setPen(pen_default)
        painter.setBrush(brush_default)

        painter.translate(50, 50)

        # Center dot
        if self.angle == -1:
            painter.setBrush(brush_active)
        painter.drawEllipse(-8, -8, 16, 16)
        painter.setBrush(brush_default)
        # Directions
        for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
            painter.save()
            painter.rotate(angle)
            painter.translate(0, 35)

            if angle == self.angle:
                painter.setBrush(brush_active)
                painter.setPen(pen_active)

            painter.drawPolygon(HatWidget.triangle)
            painter.restore()


class HatState(QtWidgets.QGroupBox):

    """Visualizes the sate of a device's hats."""

    def __init__(self, device, parent=None):
        """Creates a new instance.

        :param device the device of which to display the hat sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._event_times = {}

        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Hats")
        else:
            self.setTitle(f"{device.name} - Hats")

        self.hats = [None]
        hat_layout = QtWidgets.QGridLayout()
        for i in range(device.hat_count):
            hat = HatWidget()
            self.hats.append(hat)
            hat_layout.addWidget(hat, int(i / 2), int(i % 2))

        self.setLayout(hat_layout)

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if event.event_type == InputType.JoystickHat:
            self.hats[event.identifier].set_angle(event.value)
            self._event_times[event.identifier] = time.time()


class AxesTimeline(QtWidgets.QGroupBox):

    """Visualizes axes state as a timeline."""

    color_list = {
        1: "#e41a1c",
        2: "#377eb8",
        3: "#4daf4a",
        4: "#984ea3",
        5: "#ff7f00",
        6: "#ffff33",
        7: "#a65628",
        8: "#f781bf"
    }

    def __init__(self, device, parent=None):
        """Creates a new instance.

        :param device the device of which to display the axes sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Axes")
        else:
            self.setTitle(f"{device.name} - Axes")

        self.setLayout(QtWidgets.QVBoxLayout())
        self.plot_widget = TimeLinePlotWidget()
        self.legend_layout = QtWidgets.QHBoxLayout()
        self.legend_layout.addStretch()
        for i in range(device.axis_count):
            label = QtWidgets.QLabel(f"Axis {device.axis_map[i].axis_index:d}")
            label.setStyleSheet(
                f"QLabel {{ color: {AxesTimeline.color_list.get(device.axis_map[i].axis_index,"#000000")}; font-weight: bold }}"
            )
            self.legend_layout.addWidget(label)
        self.layout().addWidget(self.plot_widget)
        self.layout().addLayout(self.legend_layout)

    def add_point(self, value, series_id):
        """Adds a new point to the timline.

        :param value the value to add
        :param series_id id of the axes to which to add the value
        """
        self.plot_widget.add_point(value, series_id)






class TimeLinePlotWidget(QtWidgets.QWidget):

    """Visualizes temporal data as a line graph."""

    # Pre-defined colors for eight time series
    pens = {
        1: QtGui.QPen(QtGui.QColor("#e41a1c")),
        2: QtGui.QPen(QtGui.QColor("#377eb8")),
        3: QtGui.QPen(QtGui.QColor("#4daf4a")),
        4: QtGui.QPen(QtGui.QColor("#984ea3")),
        5: QtGui.QPen(QtGui.QColor("#ff7f00")),
        6: QtGui.QPen(QtGui.QColor("#ffff33")),
        7: QtGui.QPen(QtGui.QColor("#a65628")),
        8: QtGui.QPen(QtGui.QColor("#f781bf")),
    }
    for pen in pens.values():
        pen.setWidth(2)
    pens[0] = QtGui.QPen(QtGui.QColor("#c0c0c0"))
    pens[0].setWidth(1)

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._render_flags = QtGui.QPainter.Antialiasing |  QtGui.QPainter.SmoothPixmapTransform

        # Plotting canvas
        self._pixmap = QtGui.QPixmap(1000, 200)
        self._pixmap.fill()

        # Grid drawing variables
        self._horizontal_steps = 0
        self._vertical_timestep = time.time()

        # Last recorded value for a data series
        self._series = {}

        # Step size per update
        self._step_size = 1

        interval = int(1000/60)

        # Update the plot
        self._update_timer = QtCore.QTimer(self)
        self._update_timer.timeout.connect(self._update_pixmap)
        self._update_timer.start(interval)

        # Redrawing of the widget
        self._repaint_timer = QtCore.QTimer(self)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start(interval)

    def resizeEvent(self, event):
        """Handles resizing this widget.

        :param event the resize event
        """
        self._pixmap = QtGui.QPixmap(event.size())
        self._pixmap.fill()
        self._horizontal_steps = 0
        self._vertical_timestep = time.time()

    def minimumSizeHint(self):
        """Returns the minimum size of this widget.

        :return the widget's minimum size
        """
        return QtCore.QSize(400, 150)

    def paintEvent(self, event):
        """Refreshes the timeline view.

        :param event the paint event
        """
        widget_painter = QtGui.QPainter(self)
        widget_painter.drawPixmap(0, 0, self._pixmap)

    def add_point(self, value, series_id=0):
        """Adds a data point to a time series.

        :param value the value to add
        :param series_id the series to which to add the value
        """
        if series_id not in self._series:
            self._series[series_id] = [value, value]
        self._series[series_id][1] = value

    def _update_pixmap(self):
        """Updates the pixmap that contains the moving timeline."""
        pixmap_painter = QtGui.QPainter(self._pixmap)
        pixmap_painter.setRenderHint(self._render_flags)

        self._pixmap.scroll(
            -self._step_size,
            0,
            QtCore.QRect(0, 0, self._pixmap.width(), self._pixmap.height())
        )
        pixmap_painter.eraseRect(
            self._pixmap.width() - self._step_size,
            0,
            1,
            self._pixmap.height()
        )

        # Draw vertical line in one second intervals
        pixmap_painter.setPen(TimeLinePlotWidget.pens[0])
        if self._vertical_timestep < time.time()-1:
            pixmap_painter.drawLine(
                self._pixmap.width()-1,
                0,
                self._pixmap.width() - 1,
                self._pixmap.height()
            )
            self._vertical_timestep = time.time()
        self._horizontal_steps += 1
        if self._horizontal_steps <= 5:
            quarter = int(self._pixmap.height() / 4)
            x = self._pixmap.width()-1
            pixmap_painter.drawPoint(x, quarter)
            pixmap_painter.drawPoint(x, 2*quarter)
            pixmap_painter.drawPoint(x, 3*quarter)
        elif self._horizontal_steps > 10:
            self._horizontal_steps = 0

        # Draw onto the pixmap all series data that has been accumulated
        for key, value in self._series.items():
            pixmap_painter.setPen(TimeLinePlotWidget.pens[key])
            pixmap_painter.drawLine(
                self._pixmap.width()-self._step_size-1,
                int(2 + (self._pixmap.height()-4) * (value[0] + 1) / 2.0),
                self._pixmap.width()-1,
                int(2 + (self._pixmap.height()-4) * (value[1] + 1) / 2.0)
            )
            value[0] = value[1]



class JoystickDeviceWidget(QtWidgets.QWidget):

    """ joystick visualization widget  """

    def __init__(self, device_data, vis_type, parent=None):
        """Creates a new instance.

        :param device_data information about the device itself
        :param vis_type the visualization type to use
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.device_data = device_data
        self.device_guid = device_data.device_guid
        self.vis_type = vis_type
        self.widgets = []
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)
        

        
        el = gremlin.event_handler.EventListener()
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            self._create_current_axis()
            el.joystick_event.connect(self._current_axis_update)
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            self._create_temporal_axis()
            el.joystick_event.connect(self._temporal_axis_update)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            self._create_button_hat()
            el.joystick_event.connect(self._button_hat_update)

    def minimumSizeHint(self):
        """Returns the minimum size of this widget.

        :return minimum size of this widget
        """
        width = 0
        height = 0
        for widget in self.widgets:
            hint = widget.minimumSizeHint()
            height = max(height, hint.height())
            width += hint.width()
        return QtCore.QSize(width, height)

    def _create_button_hat(self):
        """Creates display for button and hat data."""
        self.widgets = [
            ButtonState(self.device_data),
            HatState(self.device_data)
        ]
        for widget in self.widgets:
            self.layout().addWidget(widget)
        self.layout().addStretch(1)

    def _create_current_axis(self):
        """Creates display for current axes data."""
        self.widgets = [AxesCurrentState(self.device_data)]
        for widget in self.widgets:
            self.layout().addWidget(widget)

    def _create_temporal_axis(self):
        """Creates display for temporal axes data."""
        self.widgets = [AxesTimeline(self.device_data)]
        for widget in self.widgets:
            self.layout().addWidget(widget)

    def _button_hat_update(self, event):
        """Updates the button and hat display.

        :param event the event to use in the update
        """
        if self.device_guid != event.device_guid:
            return

        for widget in self.widgets:
            widget.process_event(event)

    def _current_axis_update(self, event):
        if self.device_guid != event.device_guid:
            return

        for widget in self.widgets:
            widget.process_event(event)

    def _temporal_axis_update(self, event):
        """Updates the temporal axes display.

        :param event the event to use in the update
        """
        if self.device_guid != event.device_guid:
            return

        if event.event_type == InputType.JoystickAxis:
            for widget in self.widgets:
                widget.add_point(event.value, event.identifier)


class ButtonState(QtWidgets.QGroupBox):

    """Widget representing the state of a device's buttons."""

    style_sheet = """
        QPushButton {
            border: 2px solid #8f8f91;
            border-radius: 15px;
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                              stop: 0 #f6f7fa, stop: 1 #dadbde);
            min-width: 30px;
            min-height: 30px;
            max-width: 30px;
            max-height: 30px;
        }

        QPushButton:pressed {
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                              stop: 0 #e5342d, stop: 1 #b22823);
            border-color: #661714;
        }

        QPushButton:flat {
            border: none; /* no border for a flat push button */
        }
        
        QPushButton:!enabled
        {
             color: #000000;
        }
        """

    def __init__(self, device, parent=None):
        """Creates a new instance.

        :param device the device of which to display the button sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._event_times = {}

        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Buttons")
        else:
            self.setTitle(f"{device.name} - Buttons")

        self.buttons = [None]
        button_layout = QtWidgets.QGridLayout()
        for i in range(device.button_count):
            btn = QtWidgets.QPushButton(str(i+1))
            btn.setStyleSheet(ButtonState.style_sheet)
            btn.setDisabled(True)
            self.buttons.append(btn)
            button_layout.addWidget(btn, int(i / 10), int(i % 10))
        button_layout.setColumnStretch(10, 1)
        self.setLayout(button_layout)

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if event.event_type == InputType.JoystickButton:
            state = event.is_pressed if event.is_pressed is not None else False
            self.buttons[event.identifier].setDown(state)
            self._event_times[event.identifier] = time.time()




class QRowSelectorFrame(QtWidgets.QFrame):

    selected_changed = QtCore.Signal(object)

    def __init__(self, data = None, parent = None, selected = False):
        super().__init__(parent)
        self._emit = False
        self._selected = not selected # force an update to the stylesheet
        self.selected = selected
        self._data = data
        self._emit = True
        self.installEventFilter(self)
        self._selectable = True


    def setSelectable(self, value):
        self._selectable = value
    
    def getSelectable(self):
        return self._selectable

    def eventFilter(self, widget, event):
        ''' ensure line changes are saved '''
        t = event.type()
        if self._selectable and t == QtCore.QEvent.Type.MouseButtonPress:
            self.selected = not self.selected
        return False

    @property
    def selected(self):
        return self._selected
    
    @selected.setter
    def selected(self, value):
        # change selection mode
        if value != self._selected:
            self._selected = value
            if value:
                style = "QRowSelectorFrame{background-color: #8FBC8F; }"
            else:
                style = "QRowSelectorFrame{background-color: #E8E8E8; }"

            self.setStyleSheet(style)
            if self._emit:
                self.selected_changed.emit(self)

    @property
    def data(self):
        return self._data
    
    @data.setter
    def data(self, value):
        self._data = value

                             
def get_text_width(text):
    ''' gets the average text width '''
    lbl = QtWidgets.QLabel("w")
    char_width = lbl.fontMetrics().averageCharWidth()
    return char_width * len(text)

def get_char_width(count = 1):
    return get_text_width("w") * count

class QMarkerDoubleRangeSlider(QDoubleRangeSlider):

    icon_size = QtCore.QSize(16, 16)

    # background: #8FBC8F;  add-page is the background color of the groove
    
    css = '''

QSlider::groove:vertical { background: white; position: absolute; left: 8px; right: 7px; }

QMarkerDoubleRangeSlider::handle:horizontal {
    background: #8FBC8F;
    border: 2px solid #565a5e;
    width: 8px;
    height: 8px;
    border-radius: 4px;
}

QMarkerDoubleRangeSlider::sub-page:vertical { background: #8FBC8F; border-style:solid; border-color: grey;border-width:1px;border-radius:2px;}
QMarkerDoubleRangeSlider::sub-page:horizontal { background: #8FBC8F; border-style:solid; border-color: grey;border-width:1px;border-radius:2px;}
QMarkerDoubleRangeSlider::add-page:vertical { background: #979EA8; border-style:solid; border-color: grey;border-width:1px;border-radius:2px;}
QMarkerDoubleRangeSlider::add-page:horizontal { background: #979EA8; border-style:solid; border-color: grey;border-width:1px;border-radius:2px;}
   
'''

    class PixmapData():
        ''' holds a pixmap definition '''
        def __init__(self, pixmap : QtGui.QPixmap = None, offset_x = None, offset_y = None):
            self.pixmap = pixmap
            self.offset_x = offset_x
            self.offset_y = offset_y
            if pixmap is not None:
                self.width = pixmap.width()
                self.height = pixmap.height()
            else:
                self.width = 0
                self.height = 0

    def __init__(self, *args):
        super().__init__(*args)
        self._marker_pos = []
        self._internal_pixmaps = [] # default marker object
        self._pixmaps = [] # list of pixmap data marker definition objects

        # setup a single default marker
        self._update_pixmaps()
        self._update_targets()
        self.setMarkerValue(0)

        #self.setStyleSheet(self.css)

    def _get_pixmaps(self):
        if self._pixmaps: return self._pixmaps
        return self._internal_pixmaps
    
    def _update_pixmaps(self):
        orientation = self.orientation()
        if orientation == QtCore.Qt.Orientation.Horizontal:
            icon = gremlin.util.load_icon("ei.chevron-up")
            pixmap = icon.pixmap(self.icon_size)
            center = self.height() / 2
            if pixmap.height() > center:
                pixmap = pixmap.scaledToHeight(center)
            pd = QMarkerDoubleRangeSlider.PixmapData(pixmap = pixmap, offset_x = -pixmap.width()/2, offset_y=0)
        else:
            # vertical
            icon = gremlin.util.load_icon("ei.chevron-right")
            pixmap = icon.pixmap(self.icon_size)
            center = self.width() / 2
            if pixmap.width() > center:
                pixmap = pixmap.scaledToWidth(center)
            pd = QMarkerDoubleRangeSlider.PixmapData(pixmap = pixmap, offset_x = 0, offset_y = -pixmap.height()/2)
        
        self._internal_pixmaps = [pd]
        

    def setOrientation(self, orientation : QtCore.Qt.Orientation):
        ''' sets the widget's orientation '''
        super().setOrientation(orientation)
        self._update_pixmaps()


    def setMarkerValue(self, value):
        ''' sets the marker(s) value - single float is one marker, passing a tuple creates multiple markers'''
        if isinstance(value, float) or isinstance(value, int):
            list_value = [value]
        else:
            list_value = value
        self._marker_pos = list_value
        # compute the positions relative to the size of the widget
        source_min = self._minimum
        source_max = self._maximum
        target_min = self._to_qinteger_space(self._minimum)
        target_max = self._to_qinteger_space(self._maximum)
        self._int_marker_pos = [((v - source_min) * (target_max - target_min)) / (source_max - source_min) + target_min for v in list_value]
        
        # force a repaint to update to the new positions
        self.repaint()

    def minimum(self) -> float:  # type: ignore
        ''' gets the slider's minimum value '''
        return self._minimum

    def setMinimum(self, value: float) -> None:
        ''' sets the slider's minimum value '''
        super().setMinimum(value)
        self._update_targets()

    def maximum(self) -> float:  # type: ignore
        ''' gets the slider's maximum value '''
        return self._maximum

    def setMaximum(self, value: float) -> None:
        ''' sets the slider's maximum value '''
        super().setMaximum(value)
        self._update_targets()

    def setRange(self, range_min, range_max):
        ''' sets the slider's min/max values'''
        super().setRange(range_min, range_max)
        self._update_targets()

    def _update_targets(self):
        self._target_min = self._to_qinteger_space(self._minimum)
        self._target_max = self._to_qinteger_space(self._maximum)


    def setMarkerPixmaps(self, pixmaps):
        ''' sets the marker pixmaps if not using the default

        :param: pixmaps - a single pixmadata object, or a tuple of pixmapdata objects if multiple markers
        
        '''
        if isinstance(pixmaps, tuple):
            self._pixmaps = list(pixmaps)
        elif isinstance(pixmaps, list):
            self._pixmaps = pixmaps
        elif isinstance(pixmaps,QMarkerDoubleRangeSlider.PixmapData):
            self._pixmaps = [pixmaps]


    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:
        # draw the main widget
        super().paintEvent(ev)

        # draw markers on top of the main widget
        
        painter = QtGui.QPainter(self)
        orientation = self.orientation()
        if orientation == QtCore.Qt.Orientation.Horizontal:
            positions = [QtWidgets.QStyle.sliderPositionFromValue(self._target_min, self._target_max, v, self.width(), False) for v in self._int_marker_pos]
            center = self.height() / 2
        else:
            # vertical
            positions = [QtWidgets.QStyle.sliderPositionFromValue(self._target_min, self._target_max, v, self.height(), False) for v in self._int_marker_pos]
            center = self.width() / 2
        pixmaps = self._get_pixmaps()
        p_count = len(pixmaps)
        for index, value in enumerate(positions):
            if index < p_count:
                pd = pixmaps[index]
                if orientation == QtCore.Qt.Orientation.Horizontal:
                    painter.drawPixmap(value + pd.offset_x, center + pd.offset_y, pd.pixmap)
                else:
                    # vertical
                    painter.drawPixmap(center + pd.offset_x, value + pd.offset_y, pd.pixmap)

      








class QToggle(QCheckBox):

    _transparent_pen = QPen(Qt.transparent)
    _light_grey_pen = QPen(Qt.lightGray)

    def __init__(self,
        parent=None,
        bar_color=Qt.gray,
        checked_color="#8FBC8F",
        handle_color=Qt.white,
        ):
        super().__init__(parent)

        # Save our properties on the object via self, so we can access them later
        # in the paintEvent.
        self._bar_brush = QBrush(bar_color)
        self._bar_checked_brush = QBrush(QColor(checked_color).lighter())

        self._handle_brush = QBrush(handle_color)
        self._handle_checked_brush = QBrush(QColor(checked_color))

        # Setup the rest of the widget.

        self.setContentsMargins(8, 0, 8, 0)
        self._handle_position = 0

        self.stateChanged.connect(self.handle_state_change)

    def sizeHint(self):
        return QSize(48, 32)

    def hitButton(self, pos: QPoint):
        return self.contentsRect().contains(pos)

    def paintEvent(self, e: QPaintEvent):

        contRect = self.contentsRect()
        handleRadius = round(0.24 * contRect.height())

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.setPen(self._transparent_pen)
        barRect = QRectF(
            0, 0,
            contRect.width() - handleRadius, 0.40 * contRect.height()
        )
        barRect.moveCenter(contRect.center())
        rounding = barRect.height() / 2

        # the handle will move along this line
        trailLength = contRect.width() - 2 * handleRadius
        xPos = contRect.x() + handleRadius + trailLength * self._handle_position

        if self.isChecked():
            p.setBrush(self._bar_checked_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setBrush(self._handle_checked_brush)

        else:
            p.setBrush(self._bar_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setPen(self._light_grey_pen)
            p.setBrush(self._handle_brush)

        p.drawEllipse(
            QPointF(xPos, barRect.center().y()),
            handleRadius, handleRadius)

        p.end()

    @Slot(int)
    def handle_state_change(self, value):
        self._handle_position = 1 if value else 0

    @Property(float)
    def handle_position(self):
        return self._handle_position

    @handle_position.setter
    def handle_position(self, pos):
        """change the property
        we need to trigger QWidget.update() method, either by:
            1- calling it here [ what we're doing ].
            2- connecting the QPropertyAnimation.valueChanged() signal to it.
        """
        self._handle_position = pos
        self.update()

    @Property(float)
    def pulse_radius(self):
        return self._pulse_radius

    @pulse_radius.setter
    def pulse_radius(self, pos):
        self._pulse_radius = pos
        self.update()



class QAnimatedToggle(QToggle):

    _transparent_pen = QPen(Qt.transparent)
    _light_grey_pen = QPen(Qt.lightGray)

    def __init__(self, *args, pulse_unchecked_color="#44999999",
        pulse_checked_color="#4400B0EE", **kwargs):

        self._pulse_radius = 0

        super().__init__(*args, **kwargs)

        self.animation = QPropertyAnimation(self, b"handle_position", self)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.setDuration(200)  # time in ms

        self.pulse_anim = QPropertyAnimation(self, b"pulse_radius", self)
        self.pulse_anim.setDuration(350)  # time in ms
        self.pulse_anim.setStartValue(10)
        self.pulse_anim.setEndValue(20)

        self.animations_group = QSequentialAnimationGroup()
        self.animations_group.addAnimation(self.animation)
        self.animations_group.addAnimation(self.pulse_anim)

        self._pulse_unchecked_animation = QBrush(QColor(pulse_unchecked_color))
        self._pulse_checked_animation = QBrush(QColor(pulse_checked_color))



    @Slot(int)
    def handle_state_change(self, value):
        self.animations_group.stop()
        if value:
            self.animation.setEndValue(1)
        else:
            self.animation.setEndValue(0)
        self.animations_group.start()

    def paintEvent(self, e: QPaintEvent):

        contRect = self.contentsRect()
        handleRadius = round(0.24 * contRect.height())

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.setPen(self._transparent_pen)
        barRect = QRectF(
            0, 0,
            contRect.width() - handleRadius, 0.40 * contRect.height()
        )
        barRect.moveCenter(contRect.center())
        rounding = barRect.height() / 2

        # the handle will move along this line
        trailLength = contRect.width() - 2 * handleRadius

        xPos = contRect.x() + handleRadius + trailLength * self._handle_position

        if self.pulse_anim.state() == QPropertyAnimation.Running:
            p.setBrush(
                self._pulse_checked_animation if
                self.isChecked() else self._pulse_unchecked_animation)
            p.drawEllipse(QPointF(xPos, barRect.center().y()),
                          self._pulse_radius, self._pulse_radius)

        if self.isChecked():
            p.setBrush(self._bar_checked_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setBrush(self._handle_checked_brush)

        else:
            p.setBrush(self._bar_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setPen(self._light_grey_pen)
            p.setBrush(self._handle_brush)

        p.drawEllipse(
            QPointF(xPos, barRect.center().y()),
            handleRadius, handleRadius)

        p.end()



class QToggleText(QtWidgets.QWidget):
    ''' switched checkbox  '''
    clicked = QtCore.Signal()
    
    def __init__(self, text = None, parent = None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self._button = QToggle()
        self.main_layout.addWidget(self._button)
        self._label = QtWidgets.QLabel()
        self.main_layout.addWidget(self._label)
        self.main_layout.addStretch()
        if text is not None:
            self._label.setText(text)
        self._button.clicked.connect(self._clicked_cb)
        

    @QtCore.Slot()
    def _clicked_cb(self):
        self.clicked.emit()

    def text(self):
        return self._label.text()
    def setText(self, value):
        self._label.setText(value)

    def isChecked(self):
        return self._button.isChecked()
    def setChecked(self, value):
        self._button.setChecked(value)

    @property
    def value(self):
        return self._button.isChecked()
    @value.setter
    def value(self, checked):
        self._button.setChecked(checked)

import gremlin.singleton_decorator
@gremlin.singleton_decorator.SingletonDecorator
class QHelper():
    
    def __init__(self, show_percent = False, decimals = 3, single_step = 0.01):
        self._show_percent = show_percent
        self._decimals = decimals
        self._single_step = single_step
        self._min_range = -1.0
        self._max_range = 1.0


    @property
    def decimals(self):
        if self.show_percent:
            return 2
        return self._decimals
    
    @decimals.setter
    def decimals(self, value):
        self._decimals = value
    
    @property
    def single_step(self):
        if self.show_percent:
            return 0.1
        return self._single_step
    
    @property
    def min_range(self):
        ''' current min range '''
        return self._min_range
    
    @min_range.setter
    def min_range(self, value):
        self._min_range = value
    
    @property
    def max_range(self):
        ''' current max range '''
        return self._max_range
    
    @max_range.setter
    def max_range(self, value):
        self._max_range = value
    
    @property
    def show_percent(self):
        return self._show_percent
    @show_percent.setter
    def show_percent(self, value):
        self._show_percent = value
    
    def get_double_spinbox(self, id, value, min_range = -1.0, max_range = 1.0) -> DynamicDoubleSpinBox:
        ''' creates a double spin box formatted for the display mode '''
        show_percent = self.show_percent
        assert isinstance(id, str)
        sb_widget = DynamicDoubleSpinBox(data = id)
        if show_percent:
            sb_widget.setMinimum(0)
            sb_widget.setMaximum(100)
            sb_widget.setDecimals(2)
            sb_widget.setSingleStep(0.1)
        else:
            sb_widget.setRange(min_range, max_range)
            sb_widget.setDecimals(self.decimals)
            sb_widget.setSingleStep(self.single_step)

        sb_widget.setValue(value)

        return sb_widget
    
    def to_value(self, value):
        ''' returns a [-1,+1] value converted to the range output'''
        if self.show_percent:
            return gremlin.util.scale_to_range(value, target_min = 0, target_max = 100)
        else:
            return gremlin.util.scale_to_range(value, target_min = self.min_range, target_max = self.max_range)
    

class QDoubleClickSpinBox(QtWidgets.QSpinBox):
    ''' double click to reset spinbox '''
    doubleClick = QtCore.Signal()

    def __init__(self, parent = None):
        super().__init__(parent = None)
        self.installEventFilter(self)

    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.MouseButtonDblClick:
            self.doubleClick.emit()
        return False


class DualSlider(QtWidgets.QWidget):

    """Slider widget which provides two sliders to define a range. The
    lower and upper slider cannot pass through each other."""

    # Signal emitted when a value changes. (Handle, Value)
    valueChanged = QtCore.Signal(int, int)
    # Signal emitted when a handle is pressed (Handle)
    sliderPressed = QtCore.Signal(int)
    # Signal emitted when a handle is moved (Handle, Value)
    sliderMoved = QtCore.Signal(int, int)
    # Signal emitted when a handle is released (Handle)
    sliderReleased = QtCore.Signal(int)

    # Enumeration of handle codes used by the widget
    LowerHandle = 1
    UpperHandle = 2

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent widget
        """
        super().__init__(parent)

        self._lower_position = 0
        self._upper_position = 100
        self._range = [0, 100]
        self._active_handle = None

    def setRange(self, min_val, max_val):
        """Sets the range of valid values of the slider.

        :param min_val the minimum value any slider can take on
        :param max_val the maximum value any slider can take on
        """
        if min_val > max_val:
            min_val, max_val = max_val, min_val
        self._range = [min_val, max_val]
        self._lower_position = min_val
        self._upper_position = max_val

    def range(self):
        """Returns the range, i.e. minimum and maximum of accepted
        values.

        :return pair containing (minimum, maximum) allowed values
        """
        return self._range

    def setPositions(self, lower, upper):
        """Sets the position of both handles.

        :param lower value of the lower handle
        :param upper value of the upper handle
        """
        lower = self._constrain_value(self.LowerHandle, lower)
        upper = self._constrain_value(self.UpperHandle, upper)
        self._lower_position = lower
        self._upper_position = upper
        self.valueChanged.emit(self.LowerHandle, lower)
        self.valueChanged.emit(self.UpperHandle, upper)
        self.update()

    def positions(self):
        """Returns the positions of both handles.

        :return tuple containing the values of (lower, upper) handle
        """
        return [self._lower_position, self._upper_position]

    def setLowerPosition(self, value):
        """Sets the position of the lower handle.

        :param value the new value of the lower handle
        """
        value = self._constrain_value(self.LowerHandle, value)
        self._lower_position = value
        self.valueChanged.emit(self.LowerHandle, value)
        self.update()

    def setUpperPosition(self, value):
        """Sets the position of the upper handle.

        :param value the new value of the upper handle
        """
        value = self._constrain_value(self.UpperHandle, value)
        self._upper_position = value
        self.valueChanged.emit(self.UpperHandle, value)
        self.update()

    def lowerPosition(self):
        """Returns the position of the lower handle.

        :return position of the lower handle
        """
        return self._lower_position

    def upperPosition(self):
        """Returns the position of the upper handle.

        :return position of the upper handle
        """
        return self._upper_position

    def _get_common_option(self):
        """Returns a QStyleOptionSlider object with the common options
        already specified.

        :return pre filled options object
        """
        option = QtWidgets.QStyleOptionSlider()
        option.initFrom(self)
        option.minimum = self._range[0]
        option.maximum = self._range[1]
        return option

    def _constrain_value(self, handle, value):
        """Returns a value constraint such that it is valid in the given
        setting.

        :param handle the handle for which this value is intended
        :param value the desired value for the handle
        :return a value constrained such that it is valid for the
            slider's current state
        """
        slider = self.style().subControlRect(
            QtWidgets.QStyle.CC_Slider,
            self._get_common_option(),
            QtWidgets.QStyle.SC_SliderHandle
        )

        if handle == self.LowerHandle:
            return gremlin.util.clamp(
                value,
                self._range[0],
                self._upper_position - self._width_to_logical(slider.width())
            )
        else:
            return gremlin.util.clamp(
                value,
                self._lower_position + self._width_to_logical(slider.width()),
                self._range[1]
            )

    def _width_to_logical(self, value):
        """Converts a width in pixels to the logical representation.

        :param value the width in pixels
        :return logical value corresponding to the provided width
        """
        groove_rect = self.style().subControlRect(
            QtWidgets.QStyle.CC_Slider,
            self._get_common_option(),
            QtWidgets.QStyle.SC_SliderGroove
        )
        return int(round(
            (value / groove_rect.width()) * (self._range[1] - self._range[0])
        ))

    def _position_to_logical(self, pos):
        """Converts a pixel position on a slider to it's logical
        representation.

        :param pos the pixel position on the slider
        :return logical representation of the position on the slider
        """
        groove_rect = self.style().subControlRect(
            QtWidgets.QStyle.CC_Slider,
            self._get_common_option(),
            QtWidgets.QStyle.SC_SliderGroove
        )

        return QtWidgets.QStyle.sliderValueFromPosition(
            self._range[0],
            self._range[1],
            pos - groove_rect.left(),
            groove_rect.right() - groove_rect.left()
        )

    def sizeHint(self):
        """Returns the size hint for the widget in its current state.

        :return hint about the correct size of this widget
        """
        return QtWidgets.QSlider().sizeHint()

    def minimumSizeHint(self):
        """Returns the minimal size of this widget.

        :return minimal size of this widget
        """
        return QtCore.QSize(31, 17)

    def mousePressEvent(self, evt):
        """Tracks active state of the handles.

        :param evt the mouse event
        """
        position = QtCore.QPoint(evt.pos().x(), evt.pos().y())
        option = QtWidgets.QStyleOptionSlider(self._get_common_option())
        option.sliderPosition = self._lower_position
        option.sliderValue = self._lower_position
        option.subControls = QtWidgets.QStyle.SC_SliderHandle

        control = self.style().hitTestComplexControl(
            QtWidgets.QStyle.CC_Slider,
            option,
            position
        )
        lower_clicked = False
        if control == QtWidgets.QStyle.SC_SliderHandle:
            lower_clicked = True

        option.sliderPosition = self._upper_position
        option.sliderValue = self._upper_position
        control = self.style().hitTestComplexControl(
            QtWidgets.QStyle.CC_Slider,
            option,
            position
        )
        upper_clicked = False
        if control == QtWidgets.QStyle.SC_SliderHandle:
            upper_clicked = True

        if lower_clicked:
            self._active_handle = self.LowerHandle
            self.sliderPressed.emit(self.LowerHandle)
        elif upper_clicked:
            self._active_handle = self.UpperHandle
            self.sliderPressed.emit(self.UpperHandle)
        else:
            self._active_handle = None

        self.update()

    def mouseReleaseEvent(self, evt):
        """Ensures active handles get released.

        :param evt the mouse event
        """
        if self._active_handle is not None:
            self.sliderReleased.emit(self._active_handle)
            self._active_handle = None
            self.update()

    def mouseMoveEvent(self, evt):
        """Updates the position of the active slider if applicable.

        :param evt the mouse event
        """
        if self._active_handle:
            value = self._position_to_logical(evt.pos().x())
            if self._active_handle == self.LowerHandle:
                self._lower_position =\
                    self._constrain_value(self.LowerHandle, value)
                value = self._lower_position
            elif self._active_handle == self.UpperHandle:
                self._upper_position =\
                    self._constrain_value(self.UpperHandle, value)
                value = self._upper_position
            self.valueChanged.emit(self._active_handle, value)
            self.sliderMoved.emit(self._active_handle, value)
            self.update()

    def paintEvent(self, evt):
        """Repaints the entire widget.

        :param evt the paint event
        """
        painter = QtWidgets.QStylePainter(self)

        common_option = self._get_common_option()

        # Draw the groove for the handles to move on
        option = QtWidgets.QStyleOptionSlider(common_option)
        option.subControls = QtWidgets.QStyle.SC_SliderGroove
        painter.drawComplexControl(QtWidgets.QStyle.CC_Slider, option)

        # Draw lower handle
        option_lower = QtWidgets.QStyleOptionSlider(common_option)
        option_lower.sliderPosition = self._lower_position
        option_lower.sliderValue = self._lower_position
        option_lower.subControls = QtWidgets.QStyle.SC_SliderHandle

        # Draw upper handle
        option_upper = QtWidgets.QStyleOptionSlider(common_option)
        option_upper.sliderPosition = self._upper_position
        option_upper.sliderValue = self._upper_position
        option_upper.subControls = QtWidgets.QStyle.SC_SliderHandle

        if self._active_handle:
            if self._active_handle == self.LowerHandle:
                option = option_lower
            else:
                option = option_upper
            option.activeSubControls = QtWidgets.QStyle.SC_SliderHandle
            option.state |= QtWidgets.QStyle.State_Sunken

        painter.drawComplexControl(QtWidgets.QStyle.CC_Slider, option_lower)
        painter.drawComplexControl(QtWidgets.QStyle.CC_Slider, option_upper)

class QFlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, margin=-1, hspacing=-1, vspacing=-1):
        super().__init__(parent)
        self._hspacing = hspacing
        self._vspacing = vspacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        del self._items[:]

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        if self._hspacing >= 0:
            return self._hspacing
        else:
            return self.smartSpacing(
                QtWidgets.QStyle.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self):
        if self._vspacing >= 0:
            return self._vspacing
        else:
            return self.smartSpacing(
                QtWidgets.QStyle.PM_LayoutVerticalSpacing)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QtCore.QSize(left + right, top + bottom)
        return size

    def doLayout(self, rect, testonly):
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(+left, +top, -right, -bottom)
        x = effective.x()
        y = effective.y()
        lineheight = 0
        for item in self._items:
            widget = item.widget()
            hspace = self.horizontalSpacing()
            if hspace == -1:
                hspace = widget.style().layoutSpacing(
                    QtWidgets.QSizePolicy.PushButton,
                    QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Horizontal)
            vspace = self.verticalSpacing()
            if vspace == -1:
                vspace = widget.style().layoutSpacing(
                    QtWidgets.QSizePolicy.PushButton,
                    QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Vertical)
            nextX = x + item.sizeHint().width() + hspace
            if nextX - hspace > effective.right() and lineheight > 0:
                x = effective.x()
                y = y + lineheight + vspace
                nextX = x + item.sizeHint().width() + hspace
                lineheight = 0
            if not testonly:
                item.setGeometry(
                    QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
            x = nextX
            lineheight = max(lineheight, item.sizeHint().height())
        return y + lineheight - rect.y() + bottom

    def smartSpacing(self, pm):
        parent = self.parent()
        if parent is None:
            return -1
        elif parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        else:
            return parent.spacing()

class QBubble(QtWidgets.QLabel):
    def __init__(self, text):
        super(QBubble, self).__init__(text)
        self.word = text
        self.setContentsMargins(5, 5, 5, 5)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.drawRoundedRect(
            0, 0, self.width() - 1, self.height() - 1, 5, 5)
        super(QBubble, self).paintEvent(event)



    
