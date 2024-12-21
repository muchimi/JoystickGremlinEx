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
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtGui
import gremlin.base_profile

from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.keyboard import key_from_code

class MapToKeyboardWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to keyboard key combinations."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)

    def _create_ui(self):
        """Creates the UI components."""
        self.key_combination = QtWidgets.QLabel()
        self.record_button = QtWidgets.QPushButton("Record keys")

        self.record_button.clicked.connect(self._record_keys_cb)

        self.main_layout.addWidget(self.key_combination)
        self.main_layout.addWidget(self.record_button)

        warning_container = QtWidgets.QWidget()
        warning_layout = QtWidgets.QHBoxLayout(warning_container)
        warning_widget = gremlin.ui.ui_common.QIconLabel("fa.warning",use_qta=True,icon_color=QtGui.QColor("yellow"),text="Legacy mapper - consider using <i>Map to Keyboard Ex</i> for additional functionality", use_wrap=False)
        warning_layout.addWidget(warning_widget)
        warning_layout.addStretch()
        self.main_layout.addWidget(warning_container)                   

    def _populate_ui(self):
        """Populates the UI components."""
        text = "<b>Current key combination:</b> "
        names = []
        for key in self.action_data.keys:
            names.append(key_from_code(key[0],key[1]).name)
        text += " + ".join(names)

        self.key_combination.setText(text)

    def _update_keys(self, keys):
        """Updates the storage with a new set of keys.

        :param keys the keys to use in the key combination
        """
        self.action_data.keys = [
            (key.scan_code, key.is_extended) for key in keys
        ]
        self.action_modified.emit()

    def _record_keys_cb(self):
        """Prompts the user to press the desired key combination."""


        
        self.button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=True
        )

        self.button_press_dialog.item_selected.connect(self._update_keys)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        self.button_press_dialog.show()


class MapToKeyboardFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.press = gremlin.macro.Macro()
        self.needs_auto_release = action.input_is_axis()
        for key in action.keys:
            self.press.press(key_from_code(key[0], key[1]))

        self.release = gremlin.macro.Macro()
        # Execute release in reverse order
        for key in reversed(action.keys):
            self.release.release(key_from_code(key[0], key[1]))

    def process_event(self, event, value):
        if value.current:
            gremlin.macro.MacroManager().queue_macro(self.press)
            print("press")

            if self.needs_auto_release:
                print ("auto release event ")
                event_release = event.clone()               
                event_release.is_pressed = False
                ButtonReleaseActions().register_callback(
                    lambda: gremlin.macro.MacroManager().queue_macro(self.release),
                    event_release
                )
        else:
            if not self.needs_auto_release:
                print ("release")
                gremlin.macro.MacroManager().queue_macro(self.release)
        return True


class MapToKeyboard(gremlin.base_profile.AbstractAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """

    name = "Map to Keyboard"
    tag = "map-to-keyboard"

    default_button_activation = (True, True)
    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MapToKeyboardFunctor
    widget = MapToKeyboardWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.keys = []
        self.parent = parent

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        self.keys = []

        for child in node.findall("key"):
            self.keys.append((
                int(child.get("scan-code")),
                gremlin.profile.parse_bool(child.get("extended"))
            ))

        pass

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element("map-to-keyboard")
        for key in self.keys:
            key_node = ElementTree.Element("key")
            key_node.set("scan-code", str(key[0]))
            key_node.set("extended", str(key[1]))
            node.append(key_node)
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return len(self.keys) > 0
    
    def display_name(self):
        ''' friendly display name '''
        names = []
        text = ""
        for key in self.keys:
            names.append(key_from_code(key[0],key[1]).name)
        text += " + ".join(names)
        return text

version = 1
name = "map-to-keyboard"
create = MapToKeyboard
