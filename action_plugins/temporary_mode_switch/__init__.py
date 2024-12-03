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
from PySide6 import QtWidgets
from lxml import etree as ElementTree

import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.profile
import gremlin.shared_state
import gremlin.ui.input_item
import gremlin.ui.ui_common

class TemporaryModeSwitchWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of a mode to switch to."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TemporaryModeSwitch)

    def _create_ui(self):
        self.mode_list = gremlin.ui.ui_common.QComboBox()
        for entry in gremlin.profile.mode_list(self.action_data):
            self.mode_list.addItem(entry)
        self.mode_list.activated.connect(self._mode_list_changed_cb)
        self.main_layout.addWidget(self.mode_list)

    def _mode_list_changed_cb(self):
        self.action_data.mode_name = self.mode_list.currentText()
        self.action_modified.emit()

    def _populate_ui(self):
        mode_id = self.mode_list.findText(self.action_data.mode_name)
        self.mode_list.setCurrentIndex(mode_id)


class TemporaryModeSwitchFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.action_data : TemporaryModeSwitch = action
        

    def process_event(self, event, value):
        import gremlin.control_action
        if event.is_pressed:
            next_mode = self.action_data.mode_name
            current_mode = gremlin.shared_state.current_mode
            if next_mode != current_mode:
                self.action_data.restore_mode = current_mode
                gremlin.event_handler.EventHandler().change_mode(next_mode)
                gremlin.input_devices.ButtonReleaseActions().register_callback(
                    lambda : gremlin.event_handler.EventHandler().change_mode(current_mode),
                    event
                )

            else:
                # nothing to come back to
                self.action_data.restore_mode = None


        # gremlin.input_devices.ButtonReleaseActions().register_callback(
        #     gremlin.control_action.switch_to_previous_mode,
        #     event
        # )
        # gremlin.control_action.switch_mode(self.mode_name)

        return True


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
        self.mode_name = self.get_mode()
        self.parent = parent
        self.restore_mode = None

    @property
    def priority(self):
        # priority relative to other actions in this sequence - 0 is the default for all actions unless specified - the highest number runs last
        return 999        

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Switch to: {self.mode_name}"

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
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
