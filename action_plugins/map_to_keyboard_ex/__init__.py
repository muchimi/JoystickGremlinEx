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

from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.base_profile

import gremlin.config
import gremlin.config
import gremlin.config
from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.config
import gremlin.macro
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.ui.input_item
import enum
import gremlin.config
from gremlin.profile import safe_format, safe_read
from gremlin.keyboard import Key, key_from_name, key_from_code
from gremlin.ui.virtual_keyboard import *
from gremlin.types import MouseButton, MouseAction, MouseClickMode, KeyboardOutputMode
import logging
import threading
import time
from gremlin.util import log_info

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

        self.action_widget = QtWidgets.QWidget()
        self.action_layout = QtWidgets.QHBoxLayout()
        self.action_widget.setLayout(self.action_layout)

        self.record_button = QtWidgets.QPushButton("Listen")
        self.record_button.clicked.connect(self._record_keys_cb)

        self._options_widget = QtWidgets.QWidget()
        self._options_layout = QtWidgets.QHBoxLayout()
        self._options_widget.setLayout(self._options_layout)


        self.rb_press = QtWidgets.QRadioButton("Press")
        self.rb_release = QtWidgets.QRadioButton("Release")
        self.rb_both = QtWidgets.QRadioButton("Pulse")
        self.rb_autorepeat = QtWidgets.QRadioButton("Auto Repeat")
        self.rb_hold = QtWidgets.QRadioButton("Hold")

        self.delay_container_widget = QtWidgets.QWidget()
        self.delay_container_layout = QtWidgets.QHBoxLayout()
        self.delay_container_widget.setLayout(self.delay_container_layout)

        width = gremlin.ui.ui_common.get_char_width(8)

        delay_label = QtWidgets.QLabel("Delay (ms)")
        self.delay_box = gremlin.ui.ui_common.QIntLineEdit()
        self.delay_box.setRange(0, 20000)
        self.delay_box.setMaximumWidth(width)

        self.autorepeat_delay_label = QtWidgets.QLabel("Repeat Interval (ms)")
        self.autorepeat_delay_box = gremlin.ui.ui_common.QIntLineEdit()
        self.autorepeat_delay_box.setRange(0, 20000)
        self.autorepeat_delay_box.setMaximumWidth(width)

        quarter_sec_button = QtWidgets.QPushButton("1/4s")
        half_sec_button = QtWidgets.QPushButton("1/2s")
        sec_button = QtWidgets.QPushButton("1s")

        quarter_sec_button.clicked.connect(self._quarter_sec_delay)
        half_sec_button.clicked.connect(self._half_sec_delay)
        sec_button.clicked.connect(self._sec_delay)

        self.delay_box.setValue(self.action_data.delay)
        self.autorepeat_delay_box.setValue(self.action_data.autorepeat_delay)

        if self.action_data.mode == KeyboardOutputMode.Press:
            self.rb_press.setChecked(True)
        elif self.action_data.mode == KeyboardOutputMode.Release:
            self.rb_release.setChecked(True)
        elif self.action_data.mode == KeyboardOutputMode.Hold:
            self.rb_hold.setChecked(True)
        elif self.action_data.mode == KeyboardOutputMode.Both:
            self.rb_both.setChecked(True)
        elif self.action_data.mode == KeyboardOutputMode.AutoRepeat:
            self.rb_autorepeat.setChecked(True)

        self.description_widget = QtWidgets.QLabel()


        self.rb_press.clicked.connect(self._mode_changed)
        self.rb_release.clicked.connect(self._mode_changed)
        self.rb_both.clicked.connect(self._mode_changed)
        self.rb_hold.clicked.connect(self._mode_changed)
        self.rb_autorepeat.clicked.connect(self._mode_changed)

        self.delay_box.valueChanged.connect(self._delay_changed)
        self.autorepeat_delay_box.valueChanged.connect(self._autorepeat_changed)

        self._options_layout.addWidget(QtWidgets.QLabel("Mode:"))
        self._options_layout.addWidget(self.rb_hold)
        self._options_layout.addWidget(self.rb_both)
        self._options_layout.addWidget(self.rb_autorepeat)
        self._options_layout.addWidget(self.rb_press)
        self._options_layout.addWidget(self.rb_release)

        self._options_layout.addStretch(1)


        self.delay_container_layout.addWidget(delay_label)
        self.delay_container_layout.addWidget(self.delay_box)
        self.delay_container_layout.addWidget(quarter_sec_button)
        self.delay_container_layout.addWidget(half_sec_button)
        self.delay_container_layout.addWidget(sec_button)
        self.delay_container_layout.addWidget(self.autorepeat_delay_label)
        self.delay_container_layout.addWidget(self.autorepeat_delay_box)
        self.delay_container_layout.addStretch()

        self.show_keyboard_widget = QtWidgets.QPushButton("Select Keys")
        self.show_keyboard_widget.setIcon(load_icon("mdi.keyboard-settings-outline"))
        self.show_keyboard_widget.clicked.connect(self._select_keys_cb)

        self.action_layout.addWidget(self.record_button)
        self.action_layout.addWidget(self.show_keyboard_widget)
        self.action_layout.addStretch(1)


        self.main_layout.addWidget(self.key_combination)
        self.main_layout.addWidget(self.action_widget)
        self.main_layout.addWidget(self._options_widget)
        self.main_layout.addWidget(self.delay_container_widget)
        self.main_layout.addWidget(self.description_widget)


        self.main_layout.addStretch(1)
        self._mode_changed() # update UI based on mode

    def _select_keys_cb(self):
        ''' display the keyboard input dialog '''
        import gremlin.shared_state
        gremlin.shared_state.push_suspend_ui_keyinput()
        self._keyboard_dialog = InputKeyboardDialog(sequence = self.action_data.keys, parent = self)
        self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._keyboard_dialog_closed_cb)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.showNormal()

    def _keyboard_dialog_closed_cb(self):
        import gremlin.shared_state
        gremlin.shared_state.pop_suspend_ui_keyinput()

    def _keyboard_dialog_ok_cb(self):
        ''' callled when the virtual dialog completes '''

        # grab the new data
        self.action_data.keys = gremlin.keyboard.sort_keys(self._keyboard_dialog.keys)
        self.action_modified.emit()
        gremlin.shared_state.pop_suspend_ui_keyinput()


    def _populate_ui(self):
        """Populates the UI components."""
        text = "<b>Current key combination:</b> "
        text += f" + {self.action_data._get_display_keys()}"
        self.key_combination.setText(text)



    def _update_keys(self, keys):
        """Updates the storage with a new set of keys.

        :param keys the keys to use in the key combination
        """

        data = []
        for code in keys:
            if isinstance(code, tuple):
                key = gremlin.keyboard.KeyMap.find(code[0], code[1])
            elif isinstance(code, int):
                key = gremlin.keyboard.KeyMap.find_virtual(code)
            elif isinstance(code, Key):
                key = code
            else:
                assert True, f"Don't know how to handle: {code}"
            data.append(key)

        self.action_data.keys = gremlin.keyboard.sort_keys(data)
        self.action_modified.emit()


    def _mode_changed(self):
        delay_enabled = False
        autorepeat_visible = False
        if self.rb_press.isChecked():
            mode = KeyboardOutputMode.Press
            description = "<b>Press</b> mode will press keys() - the key(s) is not released and should be paired with a release at some point (keyboard 'make')."
        elif self.rb_release.isChecked():
            mode = KeyboardOutputMode.Release
            description = "<b>Release</b> mode will release keys(s) previously pressed with the Press mode (keyboard 'break')."
        elif self.rb_hold.isChecked():
            mode = KeyboardOutputMode.Hold
            description = "<b>Hold</b> mode will keep the key(s) pressed until the input is released."
        elif self.rb_both.isChecked():
            mode = KeyboardOutputMode.Both
            delay_enabled = True
            description = "<b>Pulse</b> mode will press the key(s), wait for the delay, then release the key(s)."
        elif self.rb_autorepeat.isChecked():
            mode = KeyboardOutputMode.AutoRepeat
            delay_enabled = True
            autorepeat_visible = True
            description = "<b>AutoRepeat</b> mode will pulse the key(s) repeatedly. The delay is the time between a press/release, interval is the time between pulses."
        else:
            # default
            mode = KeyboardOutputMode.Hold
        self.action_data.mode = mode
        self.delay_container_widget.setVisible(delay_enabled)
        self.description_widget.setText(description)

        self.autorepeat_delay_label.setVisible(autorepeat_visible)
        self.autorepeat_delay_box.setVisible(autorepeat_visible)

    def _delay_changed(self):
        self.action_data.delay = self.delay_box.value()
        

    def _autorepeat_changed(self):
        self.action_data.autorepeat_delay = self.autorepeat_delay_box.value()
        

    def _quarter_sec_delay(self):
        self.delay_box.setValue(250)
        

    def _half_sec_delay(self):
        self.delay_box.setValue(500)
        

    def _sec_delay(self):
        self.delay_box.setValue(1000)
        



    def _record_keys_cb(self):
        """Prompts the user to press the desired key combination."""
        button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=True
        )

        button_press_dialog.item_selected.connect(self._update_keys)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        button_press_dialog.show()


class MapToKeyboardExFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action):
        super().__init__(action)
        self.press = gremlin.macro.Macro()
        self.needs_auto_release = True
        self.mode = action.mode
        self.delay = action.delay / 1000
        self.autorepeat_delay = action.autorepeat_delay / 1000
        self.is_pressed = False
        self._ar_thread = None
        self._ar_running = False

        if self.delay < 0:
            self.delay = 0
        if self.autorepeat_delay < 0:
            self.autorepeat_delay = 0

        # build the macro that will play when the action is called
        key: Key
        for key in action.keys:
            self.press.press(key)

        self.release = gremlin.macro.Macro()

        # Execute release in reverse order
        for key in reversed(action.keys):
            self.release.release(key)

        self.delay_press_release = gremlin.macro.Macro()

        # execute press/release with a delay before releasing
        for key in action.keys:
            self.delay_press_release.press(key)
        if self.delay > 0:
            self.delay_press_release.pause(self.delay)
        for key in reversed(action.keys):
            self.delay_press_release.release(key)

        # tell the time delay or release macros to inform us when they are done running
        self.release.completed_callback = self._macro_completed
        self.delay_press_release.completed_callback = self._macro_completed

    def _macro_completed(self):
        ''' called when a macro is done running '''
        self.is_pressed = False

    def profile_start(self):
        self._ar_running = False

    def profile_stop(self):
        # release all keys
        if self.mode == KeyboardOutputMode.Hold:
            gremlin.macro.MacroManager().queue_macro(self.release)
        self._ar_running = False

    def process_event(self, event, value):
        if event.event_type == InputType.JoystickAxis or value.current:
            # joystick values or virtual button
            if self.mode == KeyboardOutputMode.Release:
                gremlin.macro.MacroManager().queue_macro(self.release)
            elif self.mode == KeyboardOutputMode.Press and not self.is_pressed:
                # press mode and not already triggered
                self.is_pressed = True
                gremlin.macro.MacroManager().queue_macro(self.press)

            elif self.mode == KeyboardOutputMode.Both:
                # make and break with delay
                if not self.is_pressed:
                    gremlin.macro.MacroManager().queue_macro(self.delay_press_release)
                    self.is_pressed = True

            elif self.mode == KeyboardOutputMode.Hold:
                gremlin.macro.MacroManager().queue_macro(self.press)
                if self.needs_auto_release:
                    ButtonReleaseActions().register_callback(
                        lambda: gremlin.macro.MacroManager().queue_macro(self.release),
                        event
                    )
            elif self.mode == KeyboardOutputMode.AutoRepeat:
                # setup autorepeat thread
                if self._ar_thread is None:
                    self._ar_thread = threading.Thread(target=self._ar_execute)
                    self._ar_running = True
                    self._ar_thread.start()
        else:
            # release
            if self.mode == KeyboardOutputMode.Hold:
                gremlin.macro.MacroManager().queue_macro(self.release)
            self._ar_running = False
            if self._ar_thread is not None:
                self._ar_thread.join()
                self._ar_thread = None

            
            
        
        
        return True

    def _ar_execute(self):
        ''' autorepeat run thread '''
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            log_info("autorepeat start...")
        while self._ar_running:
            gremlin.macro.MacroManager().queue_macro(self.delay_press_release)
            time.sleep(self.delay + self.autorepeat_delay) # give time for the key pulse + our own delay
        if verbose:
            log_info("autorepeat stop...")
        

            


class MapToKeyboardEx(gremlin.base_profile.AbstractAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """

    name = "Map to Keyboard Ex"
    tag = "map-to-keyboard-ex"

    default_button_activation = (True, True)
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MapToKeyboardExFunctor
    widget = MapToKeyboardExWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent
        self.keys = []
        self.mode = KeyboardOutputMode.Both
        config = gremlin.config.Configuration()
        self._delay = config.last_keyboard_mapper_pulse_value # delay between make/break in milliseconds
        self._autorepeat_delay = config.last_keyboard_mapper_interval_value # delay between autorepeats in milliseconds

    @property
    def delay(self):
        return self._delay
    @delay.setter
    def delay(self, value):
        if value < 0:
            value = 0
        self._delay = value
        gremlin.config.Configuration().last_keyboard_mapper_pulse_value = value

    @property
    def autorepeat_delay(self):
        return self._autorepeat_delay
    @autorepeat_delay.setter
    def autorepeat_delay(self, value):
        if value < 0:
            value = 0
        self._autorepeat_delay = value
        gremlin.config.Configuration().last_keyboard_mapper_interval_value = value

    def _update_config(self):
        config = gremlin.config.Configuration()
        
        config.last_keyboard_mapper_interval_value =self.autorepeat_delay_box.value()
        

    def _get_display_keys(self):
        text = ''
        names = []

        for code in self.keys:
            key = None
            if isinstance(code, tuple):
                key = gremlin.keyboard.KeyMap.find(code[0], code[1])
            elif isinstance(code, int):
                key = gremlin.keyboard.KeyMap.find_virtual(code)
            elif isinstance(code, Key):
                key = code
            else:
                assert True, f"Don't know how to handle: {code}"
            if key:
                names.append(key.name)
        text += " + ".join(names)
        return text

    def display_name(self):
        return self._get_display_keys()


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
        keys = []

        if "mode" in node.attrib:
            mode = safe_read(node, "mode", str)
            if mode == "make":
                self.mode = KeyboardOutputMode.Press
            elif mode == "break":
                self.mode = KeyboardOutputMode.Release
            elif mode == "both":
                self.mode = KeyboardOutputMode.Both
            elif mode == "hold":
                self.mode = KeyboardOutputMode.Hold
            elif mode == "autorepeat":
                self.mode = KeyboardOutputMode.AutoRepeat

        if "delay" in node.attrib:
            self.delay = safe_read(node, "delay", int, 250) # delay in milliseconds

        if "interval" in node.attrib:
            self.autorepeat_delay = safe_read(node, "interval", int, 250) # delay in milliseconds

        for child in node.findall("key"):
            virtual_code = safe_read(child, "virtual-code", int, 0)
            if virtual_code > 0:
                key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)
            else:
                scan_code = safe_read(child, "scan-code", int, 0)
                is_extended = safe_read(child, "extended", bool, False)
                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
            if key:
                keys.append(key)

        # sort the keys for display purposes
        self.keys = gremlin.keyboard.sort_keys(keys)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToKeyboardEx.tag)
        if self.mode == KeyboardOutputMode.Both:
            mode = "both"
        elif self.mode == KeyboardOutputMode.Press:
            mode = "make"
        elif self.mode == KeyboardOutputMode.Release:
            mode = "break"
        elif self.mode == KeyboardOutputMode.Hold:
            mode = "hold"
        elif self.mode == KeyboardOutputMode.AutoRepeat:
            mode = "autorepeat"

        node.set("mode",safe_format(mode, str) )

        node.set("delay",safe_format(self.delay, int))
        node.set("interval", safe_format(self.autorepeat_delay, int))

        for code in self.keys:
            if isinstance(code, tuple): # key ID (scan_code, extended)
                scan_code = code[0]
                is_extended = code[1]
                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
                virtual_code = key.virtual_code
            elif isinstance(code, int): # single virtual code
                key = gremlin.keyboard.KeyMap.find_virtual(code)
                scan_code = key.scan_code
                is_extended = key.is_extended
                virtual_code = code
            elif isinstance(code, Key):
                # key
                key = code
                scan_code = key.scan_code
                is_extended = key.is_extended
                virtual_code = key.virtual_code
            else:
                assert True, f"Don't know how to handle: {code}"

            key_node = ElementTree.Element("key")
            key_node.set("virtual-code", str(virtual_code))
            key_node.set("scan-code", str(scan_code))
            key_node.set("extended", str(is_extended))
            # useful for xml readability purposes = what scan code is this
            key_node.set("description", key.name)
            node.append(key_node)
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise

        """
        # return true by default so the action gets saved even if it doesn't do anything
        return True


version = 1
name = "map-to-keyboard-ex"
create = MapToKeyboardEx
