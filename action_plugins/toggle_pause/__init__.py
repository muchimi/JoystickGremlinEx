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
import gremlin.ui.input_item


class TogglePauseActionWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the resume action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TogglePauseAction)

    def _create_ui(self):
        self.label = QtWidgets.QLabel("Toggles the execution state")
        self.main_layout.addWidget(self.label)

    def _populate_ui(self):
        pass


class TogglePauseActionFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action):
        super().__init__(action)

    def process_event(self, event, value):
        import gremlin.control_action
        gremlin.control_action.toggle_pause_resume()
        return True


class TogglePauseAction(gremlin.base_profile.AbstractAction):

    """Action to resume callback execution."""

    name = "Toggle Pause & Resume"
    tag = "toggle-pause"

    default_button_activation = (True, False)
    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = TogglePauseActionFunctor
    widget = TogglePauseActionWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return "Toggle Pause"
    
    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        pass

    def _generate_xml(self):
        return ElementTree.Element("toggle-pause")

    def _is_valid(self):
        return True


version = 1
name = "toggle-pause"
create = TogglePauseAction
