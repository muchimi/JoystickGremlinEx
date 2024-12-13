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


import os
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree

import gremlin.actions
import gremlin.base_profile
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.ui.input_item
from enum import IntEnum
from gremlin.profile import safe_format, safe_read, parse_guid, write_guid
import threading
import gremlin.ui.ui_common
import time
import logging

class PauseMode (IntEnum):
    Delay = 0 # delay mode
    PauseAction = 1 # pause action mode

class PauseActionWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the pause action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, PauseAction))


    def display_name(self):
        ''' returns a display string for the current configuration '''
        return "Pause Action"

    def _create_ui(self):

        self.mode_container_widget = QtWidgets.QWidget()
        self.mode_container_layout = QtWidgets.QHBoxLayout(self.mode_container_widget)
        self.mode_delay_widget = gremlin.ui.ui_common.QDataRadioButton("Delay")
        self.mode_delay_widget.data = PauseMode.Delay
        self.mode_pause_widget = gremlin.ui.ui_common.QDataRadioButton("Pause Callback Execution")
        self.mode_pause_widget.data = PauseMode.PauseAction
        self.mode_container_layout.addWidget(QtWidgets.QLabel("Mode:"))
        self.mode_container_layout.addWidget(self.mode_delay_widget)
        self.mode_container_layout.addWidget(self.mode_pause_widget)
        self.mode_container_layout.addStretch()

        if self.action_data.mode == PauseMode.Delay:
            self.mode_delay_widget.setChecked(True)
        else:
            self.mode_pause_widget.setChecked(True)
        self.mode_delay_widget.clicked.connect(self._mode_changed)
        self.mode_pause_widget.clicked.connect(self._mode_changed)
        

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget()
        self.delay_widget.setToolTip("Delay in milliseconds")
        self.delay_widget.valueChanged.connect(self._value_changed)
        self.main_layout.addWidget(self.mode_container_widget)
        self.main_layout.addWidget(self.delay_widget)
        



    def _populate_ui(self):
        with QtCore.QSignalBlocker(self.delay_widget):
            self.delay_widget.setValue(self.action_data.delay)
        self._update()

    @QtCore.Slot()
    def _mode_changed(self):
        cb = self.sender()
        mode = cb.data
        self.action_data.mode = mode

        
    @QtCore.Slot()
    def _value_changed(self):
        self.action_data.delay = self.delay_widget.value()

    def _update(self):
        delay_visible = self.action_data.mode == PauseMode.Delay
        self.delay_widget.setVisible(delay_visible)


class PauseActionFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action_data, parent = None):
        super().__init__(action_data, parent)
        self.action_data = action_data
        

    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value):
        
        syslog = logging.getLogger("system")
        if value.is_pressed:
            match self.action_data.mode:
                case PauseMode.PauseAction:
                    gremlin.control_action.pause()
                    self.functor_complete.emit()
                case PauseMode.Delay:
                    if self.action_data.delay > 0:
                        # delay

                        syslog.info(f"Pause: start waiting {self.action_data.delay} ms")
                        time.sleep(self.action_data.delay/1000)
                        syslog.info(f"Pause: end waiting {self.action_data.delay} ms")
                    self.functor_complete.emit()
        
        return True


class PauseAction(gremlin.base_profile.AbstractAction):

    """Action for pausing the execution of callbacks."""

    name = "Pause"
    tag = "pause"

    default_button_activation = (True, False)

    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = PauseActionFunctor
    widget = PauseActionWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.mode = PauseMode.Delay # delay mode is the default
        self.delay = 250 # default delay in ms


    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        if "mode" in node.attrib:
            mode = node.get("mode")
            match mode:
                case 0:
                    self.mode = PauseMode.Delay
                case 1:
                    self.mode = PauseMode.PauseAction
            if "delay" in node.attrib:
                self.delay = safe_read(node,"delay",int, 250)
                pass
        else:
            # legacy node - use the old mode
            self.mode = PauseMode.PauseAction


    def _generate_xml(self):
        node = ElementTree.Element("pause")
        node.set("mode",str(self.mode))
        if self.mode == PauseMode.Delay:
            node.set("delay",str(self.delay))
        return node

    def _is_valid(self):
        return True


version = 1
name = "pause"
create = PauseAction
