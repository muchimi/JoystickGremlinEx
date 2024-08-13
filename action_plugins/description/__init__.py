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

import gremlin.base_classes 
from gremlin.input_types import InputType
import gremlin.ui.input_item


class DescriptionActionWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the description action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, DescriptionAction))

    def _create_ui(self):
        self.inner_layout = QtWidgets.QHBoxLayout()
        self.label = QtWidgets.QLabel("<b>Action description</b>")
        self.description = QtWidgets.QLineEdit()
        self.description.textChanged.connect(self._update_description)
        self.inner_layout.addWidget(self.label)
        self.inner_layout.addWidget(self.description)
        self.main_layout.addLayout(self.inner_layout)

    def _populate_ui(self):
        self.description.setText(self.action_data.description)

    def _update_description(self, value):
        self.action_data.description = value


class DescriptionActionFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action):
        super().__init__(action)

    def process_event(self, event, value):
        return True


class DescriptionAction(gremlin.base_profile.AbstractAction):

    """Action for adding a description to a set of actions."""

    name = "Description"
    tag = "description"

    default_button_activation = (True, False)
    
    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = DescriptionActionFunctor
    widget = DescriptionActionWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.description = ""
        self.parent = parent

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node):
        self.description = gremlin.profile.safe_read(
            node, "description", str, ""
        )

    def _generate_xml(self):
        node = ElementTree.Element("description")
        node.set("description", str(self.description))
        return node

    def _is_valid(self):
        return True


version = 1
name = "description"
create = DescriptionAction
