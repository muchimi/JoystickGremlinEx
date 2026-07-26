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

from __future__ import annotations  # deprecated with python 3.14+
import logging
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets

import gremlin.actions
import gremlin.base_profile
import gremlin.event_handler
from gremlin.input_types import InputType
from gremlin.util import safe_read, safe_format
import gremlin.ui.ui_common
import gremlin.input_item
from shiboken6 import Shiboken
from gremlin.ui.octavi_device import OctaviButton, OctaviInterface

syslog = logging.getLogger("system")


class MapToOctaviIfr1Widget(gremlin.input_item.AbstractActionWidget):
    """UI widget for mapping inputs to mouse motion or buttons."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        # LED selector

        widget = QtWidgets.QDataComboBox()
        buttons = (OctaviButton.MODEAP, OctaviButton.MODEHDG, OctaviButton.MODENAV, OctaviButton.MODEAPR, OctaviButton.MODEALT, OctaviButton.MODEVS)

        for button in buttons:
            widget.addItem(OctaviButton.to_display_name(button), button)

        button = self.action_data.button
        index = widget.findData(button)
        if index != -1:
            widget.setCurrentIndex(index)
        else:
            self.action_data.button = widget.currentData()

        widget.currentIndexChanged.connect(self._button_changed)

        container = gremlin.ui.ui_common.getHContainer(widget, "LED selection:", widget_only=True)
        self.main_layout.addWidget(container)

        widgets = []

        action = self.action_data.action

        widget = gremlin.ui.ui_common.QDataRadioButton("Turn On", "on")
        widget.setToolTip("Turns the LED on")
        if action == "on":
            widget.setChecked(True)
        widget.clicked.connect(self._action_changed)
        widgets.append(widget)

        widget = gremlin.ui.ui_common.QDataRadioButton("Turn On", "off")
        widget.setToolTip("Turns the LED on")
        if action == "off":
            widget.setChecked(True)
        widget.clicked.connect(self._action_changed)
        widgets.append(widget)

        widget = gremlin.ui.ui_common.QDataRadioButton("Toggle", "toggle")
        widget.setToolTip("Toggle the LED")
        if action == "toggle":
            widget.setChecked(True)
        widget.clicked.connect(self._action_changed)
        widgets.append(widget)

        container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.main_layout.addWidget(container)

    def _populate_ui(self):
        pass

    @QtCore.Slot()
    def _action_changed(self):
        widget = self.sender()
        self.action_data.action = widget.data

    @QtCore.Slot()
    def _button_changed(self):
        widget = self.sender()
        self.action_data.button = widget.currentData()


class MapToOctaviIfr1Functor(gremlin.base_profile.AbstractFunctor):
    """Implements the functionality required to move a mouse cursor.

    This moves the mouse cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    def __init__(self, action: MapToOctaviIfr1, parent=None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)
        self.action_data = action

    def process_event(self, event: gremlin.event_handler.Event, value: gremlin.actions.Value, extra_data=None) -> bool:

        is_pressed = event.is_pressed
        if is_pressed:
            oo = OctaviInterface()
            oo.setLed(self.action_data.button, self.action_data.action)
        return True


class MapToOctaviIfr1(gremlin.input_item.AbstractAction):
    """Action data for the map to OSC (open sound control) - allows the inputs to send an OSC command"""

    name = "Map to Octavi IFR1"
    tag = "map-to-octavi-ifr1"
    hint = "Controls Octavi panel LEDs"

    input_types = [
        InputType.JoystickButton,
    ]

    functor = MapToOctaviIfr1Functor
    widget = MapToOctaviIfr1Widget

    def __init__(self, parent, extra_data: dict = None):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent

        self.button = OctaviButton.MODEAP  # default LED to toggle
        self.action = "on"  # actions ("on" "off" "toggle")

        # config = gremlin.config.Configuration()

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "mdi.led-on"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return False

    def _is_valid(self):
        oo = OctaviInterface()
        return oo.deviceFound()

    def _parse_xml(self, node, data=None, extra_data=None):
        self.button = safe_read(node, "button", int, 0)
        self.action = safe_read(node, "action", str, "on")

    def _generate_xml(self):
        node = ElementTree.Element(MapToOctaviIfr1.tag)
        node.set("button", safe_format(self.button, int))
        node.set("action", self.action)
        return node

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)

        table.addField("Function", f"{self.button}")
        table.addField("Action", self.action)

        return table.to_html()


version = 1
name = "map-to-octavi-ifr1"
create = MapToOctaviIfr1
