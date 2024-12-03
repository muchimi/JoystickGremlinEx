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
from gremlin.ui.input_item import AbstractActionWidget


class NoOpActionWidget(AbstractActionWidget):
    """Widget for the NoOp action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, NoOpAction))
        

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return "Noop"

    def _create_ui(self):
        self.label = QtWidgets.QLabel("NoOp")
        self.main_layout.addWidget(self.label)

    def _populate_ui(self):
        pass


class NoOpActionFunctor(gremlin.base_profile.AbstractFunctor):

    """Functor, executing the NoOp action."""

    def __init__(self, action, parent = None):
        super().__init__(action, parent)

    def process_event(self, event, value):
        return True


class NoOpAction(gremlin.base_profile.AbstractAction):

    """Action which performs no operation."""

    name = "NoOp"
    tag = "noop"

    default_button_activation = (True, False)
    # override default allowed input types here if not all
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = NoOpActionFunctor
    widget = NoOpActionWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node):
        pass

    def _generate_xml(self):
        return ElementTree.Element("noop")

    def _is_valid(self):
        return True


version = 1
name = "noop"
create = NoOpAction
