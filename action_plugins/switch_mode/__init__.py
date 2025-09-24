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
from shiboken6 import Shiboken
from gremlin.profile import safe_format, safe_read


syslog = logging.getLogger("system")


class SwitchModeWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of a mode to switch to."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        self.mode_selector_widget = gremlin.ui.ui_common.QComboBox()
        self.mode_selector_widget.currentIndexChanged.connect(self._mode_selected_changed)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self._warning_widget = gremlin.ui.ui_common.QWarningWidget("Mode must not be empty and cannot be the current mode.")

        widget, _ = gremlin.ui.ui_common.getHContainer(self.mode_selector_widget,"Switch to mode:")


        self.main_layout.addWidget(widget)

        self.main_layout.addWidget(self._execute_widget)

        self.main_layout.addWidget(self._warning_widget)

        self.ec = gremlin.execution_graph.ExecutionContext()
        el = gremlin.event_handler.EventListener()
        el.profile_modes_changed.connect(self._update_modes)
        el.execution_context_changed.connect(self._update_context_modes)
        el.mode_list_update.connect(self._update_modes)
        self._update_modes_ui()


    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked        

    def _update_modes(self):
        gremlin.util.InvokeUiMethod(self._update_modes_ui) # ensure on UI thread
    
    def _update_modes_ui(self):
        ''' called when mode list needs to be updated '''
        # update the list of available modes 
        if not Shiboken.isValid(self.mode_selector_widget):
            return
        profile = gremlin.shared_state.current_profile
        mode_list = gremlin.ui.ui_common.get_mode_list(profile)
        is_warning = False

        with QtCore.QSignalBlocker(self.mode_selector_widget):
            current_mode = self.mode_selector_widget.currentData()
            edit_mode = gremlin.shared_state.edit_mode
            self.mode_selector_widget.clear()
            for display, mode in mode_list:
                if mode != edit_mode:
                    # can't switch to the mode we're in
                    self.mode_selector_widget.addItem(display, mode)

            if current_mode:
                index = self.mode_selector_widget.findData(current_mode)
                if index != -1:
                    self.mode_selector_widget.setCurrentIndex(index)
         

        if not self.mode_selector_widget.count():
            is_warning = True

        if self.action_data.mode == edit_mode:
            is_warning = True

        self._warning_widget.setVisible(is_warning)
   
    def _update_context_modes(self):
        gremlin.util.InvokeUiMethod(self._update_context_modes_ui) # ensure on UI thread
    
    def _update_context_modes_ui(self):
        ''' called when mode list needs to be updated '''
        # update the list of available modes 
        if not Shiboken.isValid(self.mode_selector_widget):
            return
        with QtCore.QSignalBlocker(self.mode_selector_widget):
            current_mode = self.action_data.mode # current mode
            self.mode_selector_widget.clear()
            edit_mode = gremlin.shared_state.edit_mode
            

            # remove the current mode so we cannot switch to ourselves
            
            modes = self.ec.getModeNames(as_tuple=True, include_current = False) # (display, mode) = exclude current mode
            if not modes:
                # allow to select self if that's the only option (display, mode)
                modes = self.ec.getModeNames(as_tuple=True)

            for display, mode in modes:
                self.mode_selector_widget.addItem(display, mode)

            if modes:
                if current_mode:
                    index = self.mode_selector_widget.findData(current_mode)
                    if index != -1:
                        self.mode_selector_widget.setCurrentIndex(index)
                else:
                    # pick the default
                    self.action_data.mode = self.mode_selector_widget.currentData()
        

    def _mode_selected_changed(self):
        if not Shiboken.isValid(self.mode_selector_widget):
            return
        mode = self.mode_selector_widget.currentData()
        if mode == gremlin.shared_state.edit_mode:
            syslog.error(f"Invalid mode selected: {mode} selected mode cannot be the current mode")
            return
        if not mode:
            syslog.error(f"Invalid mode selected: selected mode cannot be NULL")
            return
        
        self.action_data.mode = mode

    def _populate_ui(self):
        
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
        self._last_mode = None

    def profile_start(self):
        ''' occurs on profile start '''
        self._last_mode = None

    def process_event(self, event, value, extra_data = None):
        import gremlin.control_action
        import gremlin.config        
        
        trigger = (event.is_pressed and self.action_data.exec_on_press) \
            or (not event.is_pressed and self.action_data.exec_on_release)
        if trigger:
            verbose =  gremlin.config.Configuration().verbose
            new_mode = self.action_data.mode
            assert new_mode, "Invalid mode configured in mode switch - mode is not specified"
            current_mode =  gremlin.shared_state.runtime_mode
            if verbose: syslog.info(f"ACTION SWITCH: [{self.id}] requesting mode switch from [{current_mode}] to [{new_mode}]")
            switch = self._last_mode is None or new_mode != self._last_mode or current_mode != new_mode
            if switch:
                if verbose: syslog.info(f"\tswitch to [{new_mode}]")
                gremlin.control_action.switch_mode(new_mode)
            else:
                if verbose: syslog.info(f"\tno action")

            self._last_mode = new_mode
                
        return True



class SwitchMode(gremlin.base_profile.AbstractAction):

    """Action representing the change of mode."""

    name = "Switch Mode"
    tag = "switch-mode"
    hint = '''This action changes the profile mode to the specified mode.
To change the mode temporarily, use the temporary mode switch action.'''

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

        # default is the first mode in the profile list that is NOT the current mode
        current_mode = gremlin.shared_state.edit_mode
        profile = gremlin.shared_state.current_profile
        mode_list = profile.get_modes()
        if current_mode in mode_list:
            mode_list.remove(current_mode)
        mode = mode_list[0] if mode_list else None
        if mode and mode == current_mode:
            mode = None
        self.exec_on_press = True # true if the mode should execute on input press
        self.exec_on_release = False # true if the mode should execute on input release
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode
    
    @mode.setter
    def mode(self, value: str):
        if value != self._mode and value is not None:
            self._mode = value
            syslog = logging.getLogger("system")
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                input_item = self.get_input_item()
                syslog.info(f"SWITCHMODE: mode set to: {value}  input: {str(input_item)}")

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Switch Mode: [{self._mode}]"

    def icon(self):
        return "ei.fork"
        
    

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):
        mode = safe_read(node, "name",str,"")
        self.mode = mode

        parent_mode = None
        mode_node = node
        while mode_node is not None and mode_node.tag != "mode":
            mode_node = mode_node.getparent()
        if mode_node is not None:
            parent_mode = mode_node.get("name")

        assert parent_mode is not None,"XML error: missing parent mode tag"
        assert bool(mode) and self.mode != parent_mode,"logic error: switch mode cannot be the same as the current edit mode" # cannot be the same as edit mode

        self.exec_on_press = safe_read(node,"exec-on-press", bool, True)
        self.exec_on_release = safe_read(node,"exec-on-release", bool, False)

        # verbose = gremlin.config.Configuration().verbose_mode_outputs
        # if verbose: syslog.info(f"Read mode: {self._mode} from XML - edit mode: {gremlin.shared_state.edit_mode}")



    def _generate_xml(self):
        node = ElementTree.Element("switch-mode")
        node.set("name", self._mode)
        node.set("exec-on-press", safe_format(self.exec_on_press, bool))
        node.set("exec-on-release", safe_format(self.exec_on_release, bool))
        return node

    def _is_valid(self):
        return True
        


version = 1
name = "switch-mode"
create = SwitchMode
