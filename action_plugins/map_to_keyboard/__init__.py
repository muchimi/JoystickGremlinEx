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


import os
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtGui, QtCore
import gremlin.base_profile

from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.keyboard
from gremlin.profile import safe_format, safe_read
import gremlin.util
from shiboken6 import Shiboken
import html
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
        if not Shiboken.isValid(self):
            return
        self.key_combination = QtWidgets.QLabel()
        self.record_button = gremlin.ui.ui_common.Buttons.getListenWidget(callback = self._record_keys_cb)

        self.main_layout.addWidget(self.key_combination)
        self.main_layout.addWidget(self.record_button, alignment = QtCore.Qt.AlignmentFlag.AlignCenter)

        warning_color = gremlin.ui.ui_common.Color.warningColor()
        warning_widget = gremlin.ui.ui_common.QIconLabel("ph.shield-warning-fill",use_qta=True,icon_color=QtGui.QColor(warning_color),text="Legacy mapper - consider using <i>Map to Keyboard Ex</i> for additional functionality", use_wrap=False)
        warning_container, warning_layout = gremlin.ui.ui_common.getHContainer(warning_widget)
        self.main_layout.addWidget(warning_container)

    def _populate_ui(self):
        """Populates the UI components."""
        text = "<b>Current key combination:</b> "
        names = []
        for key in self.action_data.keys:
            names.append(gremlin.keyboard.key_from_code(key[0],key[1]).name)
        text += " + ".join(names)

        self.key_combination.setText(text)

    def _update_keys(self, keys):
        gremlin.util.InvokeUiMethod(self._update_keys_ui, keys)

    def _update_keys_ui(self, keys):
        """Updates the storage with a new set of keys.

        :param keys the keys to use in the key combination
        """


        self.action_data.keys = [
            (key.scan_code, key.is_extended) for key in keys
        ]
        self._populate_ui()
        self.action_modified.emit()

    def _record_keys_cb(self):
        """Prompts the user to press the desired key combination."""


        
        self.button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=False,
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
            self.press.press(gremlin.keyboard.key_from_code(key[0], key[1]))

        self.release = gremlin.macro.Macro()
        # Execute release in reverse order
        for key in reversed(action.keys):
            self.release.release(gremlin.keyboard.key_from_code(key[0], key[1]))

    def process_event(self, event, value, extra_data = None):
        if value.current:
            gremlin.macro.MacroManager().queue_macro(self.press)
            # print("press")

            if self.needs_auto_release:
                # print ("auto release event ")
                event_release = event.clone()               
                event_release.is_pressed = False
                ButtonReleaseActions().register_callback(
                    lambda: gremlin.macro.MacroManager().queue_macro(self.release),
                    event_release
                )
        else:
            if not self.needs_auto_release:
                # print ("release")
                gremlin.macro.MacroManager().queue_macro(self.release)
        return True


class MapToKeyboard(gremlin.base_profile.AbstractAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """

    name = "Map to Keyboard"
    tag = "map-to-keyboard"
    hint = "Legacy keyboard mapper."
    
    # trigger condition (trigger_on_press, trigger_on_release)
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
        return "fa6s.keyboard"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):
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

    

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        import gremlin.keyboard
        node = ElementTree.Element("map-to-keyboard")
        for scan_code, extended in self.keys:
            key_node = ElementTree.Element("key")
            key_node.set("scan-code", safe_format(scan_code, int))
            key_node.set("extended", safe_format(extended, bool))
            key = gremlin.keyboard.key_from_code(scan_code, extended)
            comment = f"key: {key.name} 0x{key.virtual_code:x}/{key.virtual_code} scan code: 0x{key.scan_code:x}/{key.scan_code} extended: {key.is_extended}"
            node_comment = ElementTree.Comment(comment)
            node.append(node_comment)
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
            names.append(gremlin.keyboard.key_from_code(key[0],key[1]).name)
        text += " + ".join(names)
        return f"Keyboard (legacy): {text}"
    
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        table = ReportTable(cellpadding=4)    
        names = []
        text = ""
        for key in self.keys:
            names.append(gremlin.keyboard.key_from_code(key[0],key[1]).name)
        text += " + ".join(names)
        table.addField("Key", html.escape(text))
        return table.to_html()

version = 1
name = "map-to-keyboard"
create = MapToKeyboard
