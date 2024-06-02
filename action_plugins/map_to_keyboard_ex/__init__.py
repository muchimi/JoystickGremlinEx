# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2019 Lionel Ott - Modified by Muchimi (C) EMCS 2024 and other contributors
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
from xml.etree import ElementTree

from PySide6 import QtWidgets

from gremlin.base_classes import AbstractAction, AbstractFunctor
from gremlin.common import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.ui.common
import gremlin.ui.input_item
import enum
from gremlin.profile import safe_format, safe_read

class MapToKeyboardExWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to keyboard key combinations - adds extra functionality to the base module ."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        self.action_data = action_data

    def _create_ui(self):
        """Creates the UI components."""


        self.key_combination = QtWidgets.QLabel()
        self.record_button = QtWidgets.QPushButton("Record keys")

        self.record_button.clicked.connect(self._record_keys_cb)

        options_widget = QtWidgets.QWidget()
        options = QtWidgets.QHBoxLayout()
        options_widget.setLayout(options)


        self.rb_press = QtWidgets.QRadioButton("Press")
        self.rb_release = QtWidgets.QRadioButton("Release")
        self.rb_both = QtWidgets.QRadioButton("Press/Release/Delay")
        self.rb_hold = QtWidgets.QRadioButton("Hold")

        delay_label = QtWidgets.QLabel("Delay(ms)")
        self.delay_box = QtWidgets.QSpinBox()
        self.delay_box.setRange(0, 20000)

        quarter_sec_button = QtWidgets.QPushButton("1/4s")
        half_sec_button = QtWidgets.QPushButton("1/2s")
        sec_button = QtWidgets.QPushButton("1s")

        quarter_sec_button.clicked.connect(self._quarter_sec_delay)
        half_sec_button.clicked.connect(self._half_sec_delay)
        sec_button.clicked.connect(self._sec_delay)

        self.delay_box.setValue(self.action_data.delay)

        if self.action_data.mode == MapToKeyboardExMode.Press:
            self.rb_press.setChecked(True)
        elif self.action_data.mode == MapToKeyboardExMode.Release:
            self.rb_release.setChecked(True)
        elif self.action_data.mode == MapToKeyboardExMode.Hold:
            self.rb_hold.setChecked(True)
        elif self.action_data.mode == MapToKeyboardExMode.Both:            
            self.rb_both.setChecked(True)
            

        self.rb_press.clicked.connect(self._mode_changed)
        self.rb_release.clicked.connect(self._mode_changed)
        self.rb_both.clicked.connect(self._mode_changed)
        self.rb_hold.clicked.connect(self._mode_changed)

        self.delay_box.valueChanged.connect(self._delay_changed)

        options.addWidget(self.rb_hold)
        options.addWidget(self.rb_both)
        options.addWidget(self.rb_press)
        options.addWidget(self.rb_release)
        options.addWidget(delay_label)
        options.addWidget(self.delay_box)
        options.addWidget(quarter_sec_button)
        options.addWidget(half_sec_button)
        options.addWidget(sec_button)
        options.addStretch(1)

        self.main_layout.addWidget(self.key_combination)
        self.main_layout.addWidget(self.record_button)
        self.main_layout.addWidget(options_widget)
        
        self.main_layout.addStretch(1)

    def _populate_ui(self):
        """Populates the UI components."""
        text = "<b>Current key combination:</b> "
        names = []
        for key in self.action_data.keys:
            names.append(gremlin.macro.key_from_code(*key).name)
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

    def _mode_changed(self):
        if self.rb_press.isChecked():
            mode = MapToKeyboardExMode.Press
        elif self.rb_release.isChecked():
            mode = MapToKeyboardExMode.Release
        elif self.rb_hold.isChecked():
            mode = MapToKeyboardExMode.Hold
        elif self.rb_both.isChecked():
            mode = MapToKeyboardExMode.Both
        else:
            mode = MapToKeyboardExMode.Hold
        self.action_data.mode = mode

    def _delay_changed(self):
        self.action_data.delay = self.delay_box.value()
        
    def _quarter_sec_delay(self):
        self.delay_box.setValue(250)


    def _half_sec_delay(self):
        self.delay_box.setValue(500)

    def _sec_delay(self):
        self.delay_box.setValue(1000)

    def _record_keys_cb(self):
        """Prompts the user to press the desired key combination."""
        self.button_press_dialog = gremlin.ui.common.InputListenerWidget(
            self._update_keys,
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=True
        )

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


class MapToKeyboardExFunctor(AbstractFunctor):

    def __init__(self, action):
        super().__init__(action)
        self.press = gremlin.macro.Macro()
        self.needs_auto_release = True
        self.mode = action.mode
        self.delay = action.delay / 1000
        self.is_pressed = False

        if self.delay < 0:
            self.delay = 0

        for key in action.keys:
            self.press.press(gremlin.macro.key_from_code(key[0], key[1]))

        self.release = gremlin.macro.Macro()
        # Execute release in reverse order
        for key in reversed(action.keys):
            self.release.release(gremlin.macro.key_from_code(key[0], key[1]))
            

        self.delay_press_release = gremlin.macro.Macro()
        # execute press/release with a delay before releasing
        for key in action.keys:
            self.delay_press_release.press(gremlin.macro.key_from_code(key[0], key[1]))
        if self.delay > 0:
            self.delay_press_release.pause(self.delay)
        for key in reversed(action.keys):
            self.delay_press_release.release(gremlin.macro.key_from_code(key[0], key[1]))

        # tell the time delay or release macros to inform us when they are done running
        self.release.completed_callback = self._macro_completed
        self.delay_press_release.completed_callback = self._macro_completed

    def _macro_completed(self):
        ''' called when a macro is done running '''
        self.is_pressed = False

    def process_event(self, event, value):
        if event.event_type == InputType.JoystickAxis or value.current:
            # joystick values or virtual button
            if self.mode == MapToKeyboardExMode.Release:
                gremlin.macro.MacroManager().queue_macro(self.release)
            elif self.mode == MapToKeyboardExMode.Press and not self.is_pressed:
                # press mode and not already triggered
                self.is_pressed = True
                gremlin.macro.MacroManager().queue_macro(self.press)

            elif self.mode == MapToKeyboardExMode.Both:
                # make and break with delay
                if not self.is_pressed:
                    gremlin.macro.MacroManager().queue_macro(self.delay_press_release)
                    self.is_pressed = True

            elif self.mode == MapToKeyboardExMode.Hold:
                gremlin.macro.MacroManager().queue_macro(self.press)
                if self.needs_auto_release:
                    ButtonReleaseActions().register_callback(
                        lambda: gremlin.macro.MacroManager().queue_macro(self.release),
                        event
                    )
        elif self.mode == MapToKeyboardExMode.Hold:
            gremlin.macro.MacroManager().queue_macro(self.release)

        return True


class MapToKeyboardExMode(enum.Enum):
    Both = 0 # keyboard make and break (press/release)
    Press = 1 # keyboard make only
    Release = 2 # keyboard release only
    Hold = 3 # press while held (default Gremlin behavior)

class MapToKeyboardEx(AbstractAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """

    name = "Map to Keyboard Ex"
    tag = "map-to-keyboard-ex"

    default_button_activation = (True, True)
    input_types = [
        InputType.JoystickAxis,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard
    ]

    functor = MapToKeyboardExFunctor
    widget = MapToKeyboardExWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.keys = []
        self.mode = MapToKeyboardExMode.Both
        self.delay = 250 # delay between make/break in milliseconds

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

        if "mode" in node.attrib:
            mode = safe_read(node, "mode", str)
            if mode == "make":
                self.mode = MapToKeyboardExMode.Press
            elif mode == "break":
                self.mode = MapToKeyboardExMode.Release
            elif mode == "both":
                self.mode = MapToKeyboardExMode.Both
            elif mode == "hold":
                self.mode = MapToKeyboardExMode.Hold
            
        if "delay" in node.attrib:
            self.delay = safe_read(node, "delay", int) # delay in milliseconds


        for child in node.findall("key"):
            self.keys.append((
                int(child.get("scan-code")),
                gremlin.profile.parse_bool(child.get("extended"))
            ))

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToKeyboardEx.tag)
        if self.mode == MapToKeyboardExMode.Both:
            mode = "both"
        elif self.mode == MapToKeyboardExMode.Press:
            mode = "make"
        elif self.mode == MapToKeyboardExMode.Release:
            mode = "break"
        elif self.mode == MapToKeyboardExMode.Hold:
            mode = "hold"

        node.set("mode",safe_format(mode, str) )

        node.set("delay",safe_format(self.delay, int))
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


version = 1
name = "map-to-keyboard-ex"
create = MapToKeyboardEx
