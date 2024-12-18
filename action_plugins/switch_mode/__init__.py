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

import gremlin.base_profile
import gremlin.event_handler
import gremlin.execution_graph
from gremlin.input_types import InputType
import gremlin.profile
import gremlin.ui.input_item
import gremlin.ui.ui_common
import gremlin.util
import gremlin.shared_state


class SwitchModeWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of a mode to switch to."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, SwitchMode)

    def _create_ui(self):
        self.mode_selector_widget = gremlin.ui.ui_common.QComboBox()
        self._update_modes()
        self.mode_selector_widget.currentIndexChanged.connect(self._mode_selected_changed)
        self.main_layout.addWidget(self.mode_selector_widget)
        el = gremlin.event_handler.EventListener()
        el.modes_changed.connect(self._update_modes)

    @QtCore.Slot()
    def _update_modes(self):
        ''' called when mode list needs to be updated '''
        # update the list of available modes 
        with QtCore.QSignalBlocker(self.mode_selector_widget):
            mode = self.action_data.mode_name # current mode
            self.mode_selector_widget.clear()
            index = 0
            select_index = None
            ec = gremlin.execution_graph.ExecutionContext()
            modes = ec.getModeNames(as_tuple=True)
            #modes = gremlin.shared_state.current_profile.get_modes()
            for entry, display in modes:
                self.mode_selector_widget.addItem(display, entry)
                if mode and select_index is None and entry == mode:
                    select_index = index
            if select_index is not None:
                self.mode_selector_widget.setCurrentIndex(select_index)
            elif self.mode_selector_widget.count():
                self.mode_selector_widget.setCurrentIndex(0)
        self._mode_selected_changed()

    def _mode_selected_changed(self):
        mode = self.mode_selector_widget.currentData()
        if mode:
            if self.action_data.mode_name != mode:
                self.action_data.mode_name = mode
                #self.action_modified.emit()

    def _populate_ui(self):
        index = self.mode_selector_widget.findData(self.action_data.mode_name)
        self.mode_selector_widget.setCurrentIndex(index)


class SwitchModeFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.mode_name = action.mode_name

    def process_event(self, event, value):
        import gremlin.control_action
        import logging
        if event.is_pressed or value.current:
            logging.getLogger("system").info(f"ACTION SWITCH: mode switch to [{self.mode_name}] requested")
            if self.mode_name:
                gremlin.control_action.switch_mode(self.mode_name)
        else:
            logging.getLogger("system").info(f"ACTION SWITCH: mode switch to [{self.mode_name}] ignored - not pressed")
        return True



class SwitchMode(gremlin.base_profile.AbstractAction):

    """Action representing the change of mode."""

    name = "Switch Mode"
    tag = "switch-mode"

    default_button_activation = (True, False)

    functor = SwitchModeFunctor
    widget = SwitchModeWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.mode_name = ""

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Switch to: {self.mode_name}"

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"
    
    @property
    def priority(self):
        # priority relative to other actions in this sequence - 0 is the default for all actions unless specified - higher numbers run last
        return 999

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        self.mode_name = node.get("name")

    def _generate_xml(self):
        node = ElementTree.Element("switch-mode")
        node.set("name", self.mode_name)
        return node

    def _is_valid(self):
        return True
        


version = 1
name = "switch-mode"
create = SwitchMode
