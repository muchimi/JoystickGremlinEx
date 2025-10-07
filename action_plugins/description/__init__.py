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
from lxml import etree as ElementTree

import gremlin.base_classes 
import gremlin.config
from gremlin.input_types import InputType
import gremlin.ui.input_item
from gremlin.util import safe_format, safe_read
from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets
import logging
from shiboken6 import Shiboken

syslog = logging.getLogger("system")

class DescriptionActionWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the description action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, DescriptionAction))

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.inner_layout = QtWidgets.QHBoxLayout()
        self.label = QtWidgets.QLabel("<b>Action description</b>")
        self.description = QtWidgets.QLineEdit()
        #self.description.setReadOnly(self.action_data.descriptionReadOnly)
        self.description.textChanged.connect(self._update_description)
        self.inner_layout.addWidget(self.label)
        self.inner_layout.addWidget(self.description)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press,
                                                                    self.action_data.exec_on_release,
                                                                    press_callback = self._execute_on_press_changed, 
                                                                    release_callback = self._execute_on_release_changed)
        # self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        # self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self.main_layout.addLayout(self.inner_layout)
        self.main_layout.addWidget(self._execute_widget)

    def _populate_ui(self):
        self.description.setText(self.action_data.description)
        #self.description.setReadOnly(self.action_data.)

    def _update_description(self, value):
        self.action_data.description = value

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked            


class DescriptionActionFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)

    def process_event(self, event, value, extra_data = None):
        is_pressed = event.is_pressed
        trigger = (is_pressed and self.action_data.exec_on_press) or \
                    (not is_pressed and self.action_data.exec_on_release) 
        
        if trigger:
            syslog.info(f"DESCRIPTION: {self.action_data.description}  (input pressed: [{is_pressed}])")
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
    hint = '''Legacy description action.
Adds a description to profiles.
Also see notes on actions and containers.
'''

    def __init__(self, parent):
        super().__init__(parent)
        self.description = ""
        self.parent = parent
        self.exec_on_press = True # true if trigger should execute on input press event
        self.exec_on_release = False # true if trigger should execute on input release event


    def icon(self):
        return "mdi.text"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node, data = None, extra_data = None):
        self.description = gremlin.profile.safe_read(node, "description", str, "")
        self.exec_on_press = safe_read(node,"exec_on_press",bool, True)
        self.exec_on_release = safe_read(node,"exec_on_release",bool, False)


    def _generate_xml(self):
        node = ElementTree.Element("description")
        node.set("description", str(self.description))
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))  
        return node

    def _is_valid(self):
        return True
    
    def __str__(self):
        return f"DescriptionAction: {self.description} exec on press: [{self.exec_on_press} on release: {self.exec_on_release}]"


version = 1
name = "description"
create = DescriptionAction
