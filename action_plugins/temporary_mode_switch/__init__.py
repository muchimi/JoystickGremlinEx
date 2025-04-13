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


syslog = logging.getLogger("system")


class TemporaryModeSwitchWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of a mode to switch to."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TemporaryModeSwitch)

    def _create_ui(self):
        self.mode_selector_widget = gremlin.ui.ui_common.QComboBox()
        self.mode_selector_widget.activated.connect(self._mode_list_changed_cb)
        self.main_layout.addWidget(self.mode_selector_widget)
        self._update_modes()

        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.connect(self._update_modes)        
        el.profile_modes_changed.connect(self._update_modes)

    def _update_modes(self):

        current_mode = self.action_data.mode_name
        index = 0
        select_index = None

        # remove the current mode so we cannot switch to ourselves
        ec = gremlin.execution_graph.ExecutionContext()
        modes = ec.getModeNames(as_tuple=True, include_current = False) # (display, mode)
        if not modes:
            # allow to select self if that's the only option
            modes = ec.getModeNames(as_tuple=True)


        with QtCore.QSignalBlocker(self.mode_selector_widget):
            self.mode_selector_widget.clear()
            for display, mode in modes:
                self.mode_selector_widget.addItem(display, mode)
                if current_mode and select_index is None and mode == current_mode:
                    select_index = index
                index += 1

            if select_index is not None:
                self.mode_selector_widget.setCurrentIndex(select_index)
            elif self.mode_selector_widget.count():
                self.mode_selector_widget.setCurrentIndex(0)


    def _mode_list_changed_cb(self):
        self.action_data.mode_name = self.mode_selector_widget.currentData()
        self.action_modified.emit()

    def _populate_ui(self):
        assert self.mode_selector_widget.count() > 0
        mode = self.action_data.mode_name
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
        if verbose:
            syslog = logging.getLogger("system")
        if verbose: 
            # get attached mode
            mode = self.action_data.get_mode()
            device_name = self.action_data.get_device_name()
            input_id = self.action_data.get_input_id()
            input_type = self.action_data.get_input_type()

            syslog.info(f"Temporary mode change event:")
            syslog.info(f"\tAttached device: {device_name} input type: {InputType.to_display_name(input_type)} input: {input_id} mode: {mode}")
            syslog.info(f"\tevent pressed: [{event.is_pressed}]  saved restore mode: [{self.action_data.restore_mode}]")
            syslog.info(f"\tcurrent profile mode: {gremlin.shared_state.runtime_mode} mode to set: {self.action_data.mode_name}")
        if event.is_pressed:
            next_mode = self.action_data.mode_name
            current_mode = gremlin.shared_state.runtime_mode
            if next_mode != current_mode:
                if verbose: syslog.info(f"Temporary mode change: saved current mode [{current_mode}] as the restore mode")
                self.action_data.restore_mode = current_mode
                if verbose: syslog.info(f"Temporary mode change: change mode to [{next_mode}] (the restore mode is [{current_mode}])")
                gremlin.event_handler.EventHandler().change_mode(next_mode)
                if verbose: syslog.info(f"Temporary mode change: register callback")
                gremlin.input_devices.ButtonReleaseActions().register_callback(lambda : self._restore_callback(current_mode), event)
            else:
                # nothing to come back to
                if verbose: syslog.info(f"Temporary mode change: [{current_mode}] (no change because current mode is the same as the requested temporary mode)")
                self.action_data.restore_mode = None
        
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


    default_button_activation = (True, False)
    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    widget = TemporaryModeSwitchWidget
    functor = TemporaryModeSwitchFunctor

    def __init__(self, parent):
        super().__init__(parent)
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
            else:
                mode = current_mode
        
        self.mode_name = mode
        self.parent = parent
        self.restore_mode = None
    

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Switch to: {self.mode_name}"

    def icon(self):
        return "ei.fork"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None):
        self.mode_name = node.get("name")

    def _generate_xml(self):
        node = ElementTree.Element("temporary-mode-switch")
        node.set("name", self.mode_name)
        return node

    def _is_valid(self):
        return len(self.mode_name) > 0


version = 1
name = "temporary-mode-switch"
create = TemporaryModeSwitch
