# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - Joystick Gremlin Ex is (C) EMCS 2025 
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


from PySide6 import QtWidgets, QtCore, QtGui

import gremlin
import gremlin.shared_state
import gremlin.types
from gremlin.util import load_icon
from gremlin.ui import ui_common
import gremlin.ui.ui_common


class AbstractVirtualButtonWidget(QtWidgets.QGroupBox):

    """Base class for activation condition widgets."""

    virtual_button_modified = QtCore.Signal()
    

    def __init__(self, condition_data, parent=None, layout_direction="vertical"):
        """Creates a new activation condition widget.

        :param condition_data the data managed by the widget
        :param parent the parent of the widget
        :param layout_direction which layout direction to use, vertical or
            horizontal
        """
        super().__init__(parent)
        self.condition_data = condition_data
        if layout_direction == "vertical":
            self.main_layout = QtWidgets.QVBoxLayout(self)
        else:
            self.main_layout = QtWidgets.QHBoxLayout(self)

        self._create_ui()
        self._populate_ui()

    def _create_ui(self):
        """Creates all required UI elements."""
        raise gremlin.error.MissingImplementationError(
            "AbstractVirtualButtonWidget._create_ui not "
            "implemented in subclass."
        )

    def _populate_ui(self):
        """Populates the UI elements with data."""
        raise gremlin.error.MissingImplementationError(
            "AbstractVirtualButtonWidget._populate_ui not "
            "implemented in subclass."
        )


class VirtualAxisButtonWidget(AbstractVirtualButtonWidget):

    """Condition widget for axis, turning an axis area into a button."""

    def __init__(self, condition_data, parent=None):
        """Creates a new axis activation condition widget.

        :param condition_data the data managed by the widget
        :param parent the parent of the widget
        """
        super().__init__(condition_data, parent)

    def _create_ui(self):
        """Creates all required UI elements."""
        VirtualAxisButtonWidget.locked = True

        self.enabled_widget = QtWidgets.QCheckBox("Enable virtual button")
        self.enabled_widget.setToolTip("When enabled, the virtual button will take precedence over any other conditions set for the container or its actions.")
        self.enabled_widget.setChecked(self.condition_data.enabled)
        self.enabled_widget.clicked.connect(self._enabled_changed)

        self.axis_repeater_widget = ui_common.AxisStateWidget(orientation=QtCore.Qt.Orientation.Horizontal, show_percentage=False)
        self.axis_repeater_widget.valueChanged.connect(self._axis_value_changed)

        self.range_status_widget = ui_common.QIconLabel()
        self.range_status_widget.setIcon("fa.check", color= gremlin.ui.ui_common.Color.activeColor())

        self.grab_low_widget = ui_common.QDataPushButton()
        self.grab_low_widget.setIcon(load_icon("mdi.checkbox-blank-circle",qta_color = gremlin.ui.ui_common.Color.recordColor()))
        self.grab_low_widget.setMaximumWidth(20)
        self.grab_low_widget.clicked.connect(self._grab_low)
        self.grab_low_widget.setToolTip("Grab axis value")

        self.grab_high_widget = ui_common.QDataPushButton()
        self.grab_high_widget.setIcon(load_icon("mdi.checkbox-blank-circle",qta_color = gremlin.ui.ui_common.Color.recordColor()))
        self.grab_high_widget.setMaximumWidth(20)
        self.grab_high_widget.clicked.connect(self._grab_high)
        self.grab_high_widget.setToolTip("Grab axis value")


        self.range_layout = QtWidgets.QHBoxLayout()
        self.lower_limit_widget = ui_common.DynamicDoubleSpinBox()
        self.lower_limit_widget.setRange(-1.0, 1.0)
        self.lower_limit_widget.setSingleStep(0.05)
        self.upper_limit_widget = ui_common.DynamicDoubleSpinBox()
        self.upper_limit_widget.setRange(-1.0, 1.0)
        self.upper_limit_widget.setSingleStep(0.05)
        self.direction_widget = ui_common.QComboBox()
        self.direction_widget.addItem("Anywhere")
        self.direction_widget.addItem("Above")
        self.direction_widget.addItem("Below")

        self.setTitle("Virtual Button")
        self.range_layout.addWidget(
            QtWidgets.QLabel("Activate when axis is between: ")
        )
        self.range_layout.addWidget(self.lower_limit_widget)
        self.range_layout.addWidget(self.grab_low_widget)
        self.range_layout.addWidget(QtWidgets.QLabel("and"))
        self.range_layout.addWidget(self.upper_limit_widget)
        self.range_layout.addWidget(self.grab_high_widget)
        self.range_layout.addWidget(QtWidgets.QLabel("when entering the range from"))
        self.range_layout.addWidget(self.direction_widget)
        self.range_layout.addWidget(self.range_status_widget)
        self.range_layout.addStretch()

        self.help_button_widget = QtWidgets.QPushButton(load_icon("gfx/help.png"), "")
        self.help_button_widget.clicked.connect(self._show_hint)
        self.range_layout.addWidget(self.help_button_widget)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self.enabled_widget)
        layout.addWidget(self.axis_repeater_widget)
        layout.addStretch()

        self.main_layout.addLayout(layout)
        self.main_layout.addLayout(self.range_layout)

        self.lower_limit_widget.valueChanged.connect(self._lower_limit_cb)
        self.upper_limit_widget.valueChanged.connect(self._upper_limit_cb)
        self.direction_widget.currentTextChanged.connect(self._direction_changed_cb)

        self.last_value = None

    @QtCore.Slot(bool)
    def _enabled_changed(self, checked):
        self.condition_data.enabled = checked

    @QtCore.Slot()
    def _grab_low(self):
        value = self.axis_repeater_widget.value()
        self.lower_limit_widget.setValue(value) # also updates condition_data
        

    @QtCore.Slot()
    def _grab_high(self):
        value = self.axis_repeater_widget.value()
        self.upper_limit_widget.setValue(value) # also updates condition_data            

    @QtCore.Slot(float, float)
    def _axis_value_changed(self, value : float, curved_value : float):
        self._update_range_state(value)            

    def _update_range_state(self, value):
        if self.range_status_widget:
            visible = False
            
            v1, v2 = self.condition_data.range
            if self.last_value is None:
                self.last_value = value
            
            match self.condition_data.direction:
                case gremlin.types.AxisButtonDirection.Anywhere:
                    if value >= v1 and value <= v2:
                        self.range_status_widget.setText("(in range)")
                        visible = True

                case gremlin.types.AxisButtonDirection.Below:
                    if value < self.last_value:   
                        self.range_status_widget.setText(f"(below)")
                        visible = True
                case gremlin.types.AxisButtonDirection.Above:
                    if value > self.last_value:   
                        self.range_status_widget.setText(f"(below)")
                        visible = True


            self.range_status_widget.setVisible(visible)
            self.last_value = value


    def _populate_ui(self):
        """Populates the UI elements with data."""
        self.lower_limit_widget.setValue(self.condition_data.lower_limit)
        self.upper_limit_widget.setValue(self.condition_data.upper_limit)
        self.axis_repeater_widget.hookDevice(self.condition_data.device_guid,
                                             self.condition_data.input_type,
                                             self.condition_data.input_id)
        self.direction_widget.setCurrentText(
            gremlin.types.AxisButtonDirection.to_string(
                self.condition_data.direction
            ).capitalize()
        )

    def _lower_limit_cb(self, value):
        """Updates the lower limit value.

        :param value the new value of the virtual button's lower limit
        """
        self.condition_data.lower_limit = value
        self.virtual_button_modified.emit()

    def _upper_limit_cb(self, value):
        """Updates the upper limit value.

        :param value the new value of the virtual button's upper limit
        """
        self.condition_data.upper_limit = value
        self.virtual_button_modified.emit()

    def _direction_changed_cb(self, value):
        self.condition_data.direction = \
            gremlin.types.AxisButtonDirection.to_enum(value.lower())
        self.virtual_button_modified.emit()

    def _show_hint(self):
        """Displays a hint explaining the activation condition."""
        QtWidgets.QWhatsThis.showText(
            self.help_button_widget.mapToGlobal(QtCore.QPoint(0, 10)),
            gremlin.hints.hint.get("axis-condition", "")
        )


class VirtualHatButtonWidget(AbstractVirtualButtonWidget):

    """Condition widget for hats, turning a set of directions into a button."""

    locked = False

    def __init__(self, condition_data, parent=None):
        """Creates a new hat activation condition widget.

        :param condition_data the data managed by the widget
        :param parent the parent of the widget
        """
        self._widgets = {}
        super().__init__(condition_data, parent, "horizontal")

    def _create_ui(self):
        """Creates all required UI elements."""

        if VirtualHatButtonWidget.locked:
            return
        
        try:

            VirtualHatButtonWidget.locked = True

            self.setTitle("Virtual Button")

            directions = ["n", "ne", "e", "se", "s", "sw", "w", "nw"]

            for direction in directions:
                self._widgets[direction] = QtWidgets.QCheckBox()
                self._widgets[direction].setIcon(
                    load_icon(f"gfx/hat_{direction}.png")
                )
                self._widgets[direction].toggled.connect(
                    self._create_state_changed_cb(direction)
                )
                self.main_layout.addWidget(self._widgets[direction])

            self.main_layout.addStretch(1)

            prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
            self.help_button = QtWidgets.QPushButton(load_icon(f"gfx/{prefix}help.png"), "")
            self.help_button.clicked.connect(self._show_hint)
            self.main_layout.addWidget(self.help_button)
        finally:
            VirtualHatButtonWidget.locked = False

    def _populate_ui(self):
        """Populates the UI elements with data."""
        direction_map = {
            "north": "n",
            "north-east": "ne",
            "east": "e",
            "south-east": "se",
            "south": "s",
            "south-west": "sw",
            "west": "w",
            "north-west": "nw"
        }

        for direction in self.condition_data.directions:
            self._widgets[direction_map[direction]].setCheckState(
                QtCore.Qt.Checked
            )

    def _state_changed(self, direction, state):
        """Updates the set of directions making up the button.

        :param direction the direction being modified
        :param state the change being performed
        """
        direction_map = {
            "n": "north",
            "ne": "north-east",
            "e": "east",
            "se": "south-east",
            "s": "south",
            "sw": "south-west",
            "w": "west",
            "nw": "north-west"
        }

        name = direction_map[direction]
        if state is False and name in self.condition_data.directions:
            idx = self.condition_data.directions.index(name)
            del self.condition_data.directions[idx]
        elif state is True and name not in self.condition_data.directions:
            self.condition_data.directions.append(name)
        self.condition_data.directions = \
            list(set(self.condition_data.directions))

    def _create_state_changed_cb(self, direction):
        """Creates a state change callback.

        :param direction the direction for which to customize the callback
        :return callback function to update the state of a direction
        """
        return lambda x: self._state_changed(direction, x)

    def _show_hint(self):
        """Displays a hint explaining the activation condition."""
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            gremlin.hints.hint.get("hat-condition", "")
        )
