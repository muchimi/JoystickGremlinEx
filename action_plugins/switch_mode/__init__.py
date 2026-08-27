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


from PySide6 import QtCore
from lxml import etree as ElementTree

import gremlin.base_profile
import gremlin.event_handler
import gremlin.execution_graph
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.input_item
import gremlin.ui.ui_common
import gremlin.util
import gremlin.shared_state
import logging
from shiboken6 import Shiboken
from gremlin.util import safe_format, safe_read


syslog = logging.getLogger("system")


class SwitchModeWidget(gremlin.input_item.AbstractActionWidget):
    """Widget which allows the configuration of a mode to switch to."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        self.mode_selector_widget = gremlin.ui.ui_common.QDataComboBox()
        self.mode_selector_widget.currentIndexChanged.connect(self._mode_selected_changed)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self._warning_widget = gremlin.ui.ui_common.QWarningWidget("Mode must not be empty and cannot be the current mode.")

        widget = gremlin.ui.ui_common.getHContainer(self.mode_selector_widget, "Switch to mode:", widget_only=True)

        self.main_layout.addWidget(widget)

        self.main_layout.addWidget(self._execute_widget)

        self.main_layout.addWidget(self._warning_widget)

        self.ec = gremlin.execution_graph.ExecutionContext()
        el = gremlin.event_handler.EventListener()
        el.profile_modes_changed.connect(self._update_modes)
        el.execution_context_changed.connect(self._update_context_modes)
        el.mode_list_update.connect(self._update_modes)
        self._update_modes_ui()

    def unhook(self):
        gremlin.util.clear_layout(self.main_layout)

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        self.action_data.exec_on_release = checked

    def _update_modes(self):
        gremlin.util.InvokeUiMethod(self._update_modes_ui)  # ensure on UI thread

    def _update_modes_ui(self):
        """called when mode list needs to be updated"""
        gremlin.util.assert_ui_thread()
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
                # if mode != edit_mode:
                #     # can't switch to the mode we're in
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
        gremlin.util.InvokeUiMethod(self._update_context_modes_ui)  # ensure on UI thread

    def _update_context_modes_ui(self):
        """called when mode list needs to be updated"""
        gremlin.util.assert_ui_thread()
        # update the list of available modes
        if not Shiboken.isValid(self.mode_selector_widget):
            return
        with QtCore.QSignalBlocker(self.mode_selector_widget):
            current_mode = self.action_data.mode  # current mode
            self.mode_selector_widget.clear()
            _edit_mode = gremlin.shared_state.edit_mode

            # remove the current mode so we cannot switch to ourselves

            modes = self.ec.getModeNames(as_tuple=True, include_current=False)  # (display, mode) = exclude current mode
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
        # if mode == gremlin.shared_state.edit_mode:
        #     syslog.error(f"Invalid mode selected: {mode} selected mode cannot be the current mode")
        #     return
        if not mode:
            syslog.error("Invalid mode selected: selected mode cannot be NULL")
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
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self.action_data = action
        self._last_mode = None

    def profile_start(self):
        """occurs on profile start"""
        self._last_mode = None

    def process_event(self, event, value, extra_data=None):
        import gremlin.control_action
        import gremlin.config

        trigger = (event.is_pressed and self.action_data.exec_on_press) or (not event.is_pressed and self.action_data.exec_on_release)
        if trigger:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_mode
            new_mode = self.action_data.mode
            assert new_mode, "Invalid mode configured in mode switch - mode is not specified"
            current_mode = gremlin.shared_state.runtime_mode

            if verbose:
                mode = self.action_data.get_mode()
                input_id = self.action_data.get_input_id()
                input_type = self.action_data.get_input_type()
                device_name = self.action_data.get_device_name()
                syslog.info(f"SWITCH MODE ACTION: [{self.id}] requesting mode switch from [{current_mode}] to [{new_mode}]")
                syslog.info(f"\tAttached device: [{device_name}] input type: [{InputType.to_display_name(input_type)}] input: [{input_id}] mode: [{mode}]")
                syslog.info(f"\tevent pressed: [{event.is_pressed}]")
                syslog.info(f"\tcurrent profile mode: {gremlin.shared_state.runtime_mode} mode to set: {new_mode}")

            switch = self._last_mode is None or new_mode != self._last_mode or current_mode != new_mode
            if switch:
                if verbose:
                    syslog.info(f"\tswitch to [{new_mode}]")
                gremlin.control_action.switch_mode(new_mode)
            else:
                if verbose:
                    syslog.info("\tno action")

            self._last_mode = new_mode

        return True


class SwitchMode(gremlin.input_item.AbstractAction):
    """Action representing the change of mode."""

    name = "Switch Mode"
    tag = "switch-mode"
    hint = """This action changes the profile mode to the specified mode.
To change the mode temporarily, use the temporary mode switch action."""

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, False)

    functor = SwitchModeFunctor
    widget = SwitchModeWidget

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    def __init__(self, parent, extra_data: dict = None):
        super().__init__(parent, extra_data=extra_data)
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
        self.exec_on_press = True  # true if the mode should execute on input press
        self.exec_on_release = False  # true if the mode should execute on input release
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value != self._mode and value is not None:
            self._mode = value
            # verbose = gremlin.config.Configuration().verbose
            # if verbose:
            #     input_item = self.get_input_item()
            #     syslog.info(f"SWITCHMODE: mode set to: {value}  input: {str(input_item)}")

    def display_name(self):
        """returns a display string for the current configuration"""
        return f"Switch Mode: [{self._mode}]"

    def icon(self):
        return "ei.fork"

    def requires_virtual_button(self):
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    def _parse_xml(self, node, data=None, extra_data=None):
        mode = safe_read(node, "name", str, "")
        self.mode = mode

        if not gremlin.util._xml_paste_mode(node, extra_data):
            parent_mode = None
            mode_node = node
            while mode_node is not None and mode_node.tag not in ("mode", "state"):
                mode_node = mode_node.getparent()

            if mode_node is not None and mode_node.tag == "mode":
                # validate nesting
                parent_mode = mode_node.get("name")
                assert parent_mode is not None, f"XML error: missing parent mode tag - offending XML line: {node.sourceline}"
                # assert bool(mode) and self.mode != parent_mode,f"logic error: switch mode cannot be the same as the current edit mode:  - offending XML line: {node.sourceline}" # cannot be the same as edit mode

        self.exec_on_press = safe_read(node, "exec-on-press", bool, True)
        self.exec_on_release = safe_read(node, "exec-on-release", bool, False)

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

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)

        table.addField("Switch To Mode", self.mode)

        if self.exec_on_press:
            table.addField("Exec (press)", "Yes")
        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()


version = 1
name = "switch-mode"
create = SwitchMode
