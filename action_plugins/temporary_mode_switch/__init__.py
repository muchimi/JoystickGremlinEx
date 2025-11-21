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
import gremlin.config
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.profile
import gremlin.shared_state
import gremlin.ui.input_item
import gremlin.ui.ui_common
import anytree
import logging
import gremlin.execution_graph
import psygnal
from psygnal import Signal
from shiboken6 import Shiboken
import gremlin.util
from gremlin.util import safe_format, safe_read

syslog = logging.getLogger("system")


class TemporaryModeSwitchWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of a mode to switch to."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TemporaryModeSwitch)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.mode_selector_widget = gremlin.ui.ui_common.QComboBox()
        self.mode_selector_widget.currentIndexChanged.connect(self._mode_selected_changed)
        
        self.ec = gremlin.execution_graph.ExecutionContext()
        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.connect(self._update_modes)
        el.execution_context_changed.connect(self._update_modes)

        self.return_mode_widget = QtWidgets.QCheckBox("Return to specific mode:")
        self.return_mode_widget.setToolTip("If enabled, the return mode will be the specified mode instead of the last mode.")
        self.return_mode_widget.clicked.connect(self._change_enable_return_mode)

        self.return_mode_selector_widget =  gremlin.ui.ui_common.QComboBox()
        self.return_mode_selector_widget.currentIndexChanged.connect(self._return_mode_selected_changed)

        widget = gremlin.ui.ui_common.getHContainer(self.mode_selector_widget,"Mode:", widget_only = True)
        self.main_layout.addWidget(widget)

        widget = gremlin.ui.ui_common.getHContainer([self.return_mode_widget, self.return_mode_selector_widget], widget_only = True)
        self.main_layout.addWidget(widget)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self.main_layout.addWidget(self._execute_widget)


        self._update_modes_ui()

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked  

    @QtCore.Slot(bool)
    def _change_enable_return_mode(self, checked : bool):
        self.action_data.enable_return_mode = checked
        self.return_mode_selector_widget.setEnabled(checked)

    def _update_modes(self):
        gremlin.util.InvokeUiMethod(self._update_modes_ui) # ensure on UI method
    
    def _update_modes_ui(self):
        ''' called when mode list needs to be updated '''
        # update the list of available modes 
        if not Shiboken.isValid(self.mode_selector_widget):
            return
        with QtCore.QSignalBlocker(self.return_mode_widget):
            self.return_mode_widget.setChecked(self.action_data.enable_return_mode)

        with QtCore.QSignalBlocker(self.mode_selector_widget):
            with QtCore.QSignalBlocker(self.return_mode_selector_widget):
                current_mode = self.action_data.mode # current mode
                self.mode_selector_widget.clear()
                self.return_mode_selector_widget.clear()
                

                # remove the current mode so we cannot switch to ourselves
                
                modes = self.ec.getModeNames(as_tuple=True, include_current = False) # (display, mode)
                if not modes:
                    # allow to select self if that's the only option (display, mode)
                    modes = self.ec.getModeNames(as_tuple=True)
                    
                index = 0
                select_index = None
                for display, mode in modes:
                    #print (f"Mode: {display} -> {mode}")
                    self.mode_selector_widget.addItem(display, mode)
                    self.return_mode_selector_widget.addItem(display, mode)
                    if select_index is None and mode == current_mode and current_mode is not None:
                        select_index = index
                    index += 1
                if select_index is not None:
                        self.mode_selector_widget.setCurrentIndex(select_index)

                if self.action_data.enable_return_mode and self.action_data.return_mode:
                    # select the correct return mode if specified
                    index = self.return_mode_selector_widget.findData(self.action_data.return_mode)
                    if index != -1:
                        self.return_mode_selector_widget.setCurrentIndex(index)

        self.return_mode_selector_widget.setEnabled(self.action_data.enable_return_mode)

        # ensure the displayed mode is saved
        mode = self.mode_selector_widget.currentData()
        self.action_data.mode = mode                

    def _mode_selected_changed(self):
        if not Shiboken.isValid(self.mode_selector_widget):
            return
        mode = self.mode_selector_widget.currentData()
        self.action_data.mode = mode                

    def _return_mode_selected_changed(self):
        if not Shiboken.isValid(self.return_mode_selector_widget):
            return
        mode = self.return_mode_selector_widget.currentData()
        self.action_data.return_mode = mode


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
            

class TemporaryModeSwitchFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.action_data : TemporaryModeSwitch = action
        
    def process_event(self, event, value, extra_data = None):
        import gremlin.control_action
        import gremlin.shared_state
        verbose = gremlin.config.Configuration().verbose

        trigger = (event.is_pressed and self.action_data.exec_on_press) \
            or (not event.is_pressed and self.action_data.exec_on_release)
        if trigger:

            next_mode = self.action_data.mode # mode to change to
            current_mode = gremlin.shared_state.runtime_mode
            
            if self.action_data.enable_return_mode and self.action_data.return_mode is not None:
                return_mode = self.action_data.return_mode
            else:
                return_mode = current_mode

            if verbose: syslog.info(f"Temporary mode change: [{current_mode}] - next mode: [{next_mode}] - return mode: [{return_mode}] - specific mode to return: [{'enabled' if self.action_data.enable_return_mode else 'disabled'}]")


            if next_mode != current_mode:
                self.action_data.restore_mode = current_mode
                gremlin.input_devices.ButtonReleaseActions().register_callback(lambda : self._restore_callback(return_mode), event)
                gremlin.event_handler.EventHandler().change_mode(next_mode)
             
            else:
                # nothing to come back to
                if verbose: syslog.info(f"Temporary mode change: [{current_mode}] (no change because current mode is the same as the requested temporary mode)")
                self.action_data.restore_mode = None
        

            if verbose: 
                # get attached mode
                mode = self.action_data.get_mode()
                device_name = self.action_data.get_device_name()
                input_id = self.action_data.get_input_id()
                input_type = self.action_data.get_input_type()

                syslog.info(f"Temporary mode change event:")
                syslog.info(f"\tAttached device: {device_name} input type: {InputType.to_display_name(input_type)} input: {input_id} mode: {mode}")
                syslog.info(f"\tevent pressed: [{event.is_pressed}]  saved restore mode: [{self.action_data.restore_mode}]")
                syslog.info(f"\tcurrent profile mode: {gremlin.shared_state.runtime_mode} mode to set: {self.action_data.mode}")

        return True
    
    def _restore_callback(self, mode):
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog = logging.getLogger("system")
            syslog.info(f"Temporary mode change: callback: restoring mode {mode}")
        gremlin.event_handler.EventHandler().change_mode(mode)

class TemporaryModeSwitch(gremlin.base_profile.AbstractAction):

    """Action representing the change of mode."""

    name = "Temporary Mode Switch"
    tag = "temporary-mode-switch"
    hint = '''This action switches the profile mode while triggered.
When the trigger is released, the mode reverts to the prior mode.'''    


    default_button_activation = (True, False)


    widget = TemporaryModeSwitchWidget
    functor = TemporaryModeSwitchFunctor

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
        self.enable_return_mode = False # true if the return mode is enabled instead of the last mode
        self.return_mode = None # if set, returns to that mode instead of the prior mode
        self.restore_mode = None # set at runtime - holds the mode to restore

        self.exec_on_press = True # true if the mode should execute on input press
        self.exec_on_release = False # true if the mode should execute on input release

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
                syslog.info(f"TEMPSWITCHMODE: mode set to: {value}  input: {str(input_item)}")

        self.restore_mode = None
    

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Switch to: {self._mode}"

    def icon(self):
        return "ei.fork"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):
        self._mode = node.get("name")
        if "return-mode-enabled" in node.attrib:
            self.enable_return_mode = safe_read(node, "return-mode-enabled", bool, False)
        if "return-mode" in node.attrib:
            self.return_mode = node.get("return-mode")
            
        self.exec_on_press = safe_read(node,"exec-on-press", bool, True)
        self.exec_on_release = safe_read(node,"exec-on-release", bool, False)

    def _generate_xml(self):
        node = ElementTree.Element("temporary-mode-switch")
        node.set("name", self._mode)
        node.set("return-mode-enabled", safe_format(self.enable_return_mode, bool))
        node.set("return-mode", safe_format(self.return_mode, str))

        node.set("exec-on-press", safe_format(self.exec_on_press, bool))
        node.set("exec-on-release", safe_format(self.exec_on_release, bool))
        return node

    def _is_valid(self):
        return True
    
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        table = ReportTable(cellpadding=4) 
        table.addField("Mode", self.mode)
        table.addField("Return mode", 'last mode' if not self.enable_return_mode else self.return_mode)
        if self.exec_on_press:
            table.addField("Exec (press)", "Yes")
        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()


version = 1
name = "temporary-mode-switch"
create = TemporaryModeSwitch
