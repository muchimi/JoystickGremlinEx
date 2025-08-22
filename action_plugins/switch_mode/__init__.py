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


import os
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree

import gremlin.base_profile
import gremlin.event_handler
import gremlin.execution_graph
from gremlin.input_types import InputType
import gremlin.profile
import gremlin.shared_state
import gremlin.ui.input_item
import gremlin.ui.ui_common
import gremlin.util
import gremlin.shared_state
import gremlin.config
import anytree
import logging
import psygnal
from psygnal import Signal


syslog = logging.getLogger("system")


class SwitchModeWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of a mode to switch to."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, SwitchMode)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.mode_selector_widget = gremlin.ui.ui_common.QComboBox()
        self.mode_selector_widget.currentIndexChanged.connect(self._mode_selected_changed)
        self.main_layout.addWidget(self.mode_selector_widget)
        self.ec = gremlin.execution_graph.ExecutionContext()
        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.connect(self._update_modes)
        el.execution_context_changed.connect(self._update_modes)
        self._update_modes()

            

    @QtCore.Slot()
    def _update_modes(self):
        ''' called when mode list needs to be updated '''
        # update the list of available modes 
        with QtCore.QSignalBlocker(self.mode_selector_widget):
            current_mode = self.action_data.mode # current mode
            self.mode_selector_widget.clear()
            

            # remove the current mode so we cannot switch to ourselves
            
            modes = self.ec.getModeNames(as_tuple=True, include_current = False) # (display, mode)
            if not modes:
                # allow to select self if that's the only option (display, mode)
                modes = self.ec.getModeNames(as_tuple=True)
                
            index = 0
            select_index = None
            for display, mode in modes:
                print (f"Mode: {display} -> {mode}")
                self.mode_selector_widget.addItem(display, mode)
                if select_index is None and mode == current_mode and current_mode is not None:
                    select_index = index
                index += 1
            if select_index is not None:
                self.mode_selector_widget.setCurrentIndex(select_index)
        

    def _mode_selected_changed(self):
        mode = self.mode_selector_widget.currentData()
        self.action_data.mode = mode

    def _populate_ui(self):
        assert self.mode_selector_widget.count() > 0
        mode = self.action_data.mode
        if mode is None:
            index = 0
        else:
            index = self.mode_selector_widget.findData(mode)
            if index == -1:
                index = 0

        self.mode_selector_widget.setCurrentIndex(index)
            
        


class SwitchModeFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.action_data = action

    def process_event(self, event, value, extra_data = None):
        import gremlin.control_action
        import gremlin.config        
        import logging
        
        if event.is_pressed or value.current:
            verbose =  gremlin.config.Configuration().verbose
            mode = self.action_data.mode
            current_mode =  gremlin.shared_state.runtime_mode
            if mode and current_mode and mode != current_mode:
                if verbose: syslog.info(f"ACTION SWITCH: mode switch from [{current_mode}] to [{mode}] requested")
                gremlin.control_action.switch_mode(mode)
        return True



class SwitchMode(gremlin.base_profile.AbstractAction):

    """Action representing the change of mode."""

    name = "Switch Mode"
    tag = "switch-mode"

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, False)

    functor = SwitchModeFunctor
    widget = SwitchModeWidget

    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]    

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setPriority(999)
        profile = gremlin.shared_state.current_profile
        current_mode = gremlin.shared_state.edit_mode
        root = profile.modeTree()
        node = anytree.find(root, lambda node: node.name == current_mode)
        mode = current_mode
        if node:
            if node.children:
                mode = node.children[0].name
            elif node.parent:
                mode = node.parent.name
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode
    
    @mode.setter
    def mode(self, value: str):
        if value != self._mode:
            self._mode = value
            syslog = logging.getLogger("system")
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                input_item = self.get_input_item()
                syslog.info(f"SWITCHMODE: mode set to: {value}  input: {str(input_item)}")

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Switch to: {self.mode}"

    def icon(self):
        return "ei.fork"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"
    

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):
        self._mode = node.get("name")
        verbose = gremlin.config.Configuration().verbose_mode_outputs
        if verbose: syslog.info(f"Read mode: {self._mode} from XML - edit mode: {gremlin.shared_state.edit_mode}")

    def _generate_xml(self):
        node = ElementTree.Element("switch-mode")
        node.set("name", self._mode)
        return node

    def _is_valid(self):
        return True
        


version = 1
name = "switch-mode"
create = SwitchMode
