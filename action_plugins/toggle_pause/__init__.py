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


from PySide6 import QtWidgets
from lxml import etree as ElementTree

import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.input_item
from shiboken6 import Shiboken


class TogglePauseActionWidget(gremlin.input_item.AbstractActionWidget):

    """Widget for the resume action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TogglePauseAction)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.label = QtWidgets.QLabel("Toggles the execution state")
        self.main_layout.addWidget(self.label)

    def _populate_ui(self):
        pass


class TogglePauseActionFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)

    def process_event(self, event, value, extra_data = None):
        import gremlin.control_action
        gremlin.control_action.toggle_pause_resume()
        return True


class TogglePauseAction(gremlin.base_profile.AbstractAction):

    """Action to resume callback execution."""

    name = "Toggle Pause & Resume"
    tag = "toggle-pause"
    hint = '''Toggles profile pause on/off.
Note that containers that have the always execute flag on
continue to run even if the profile is paused.'''
    

    default_button_activation = (True, False)
    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]
    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]

    functor = TogglePauseActionFunctor
    widget = TogglePauseActionWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return "Toggle Pause"
    
    def icon(self):
        return "fa5.pause-circle"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):
        pass

    def _generate_xml(self):
        return ElementTree.Element("toggle-pause")

    def _is_valid(self):
        return True


version = 1
name = "toggle-pause"
create = TogglePauseAction
