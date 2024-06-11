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

from PySide6 import QtWidgets, QtCore, QtGui

from gremlin.base_classes import AbstractAction, AbstractFunctor
from gremlin.common import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.ui.common
import gremlin.ui.input_item
import enum
from gremlin.profile import safe_format, safe_read
from gremlin.keyboard import Key, key_from_name
import logging

class QHLine(QtWidgets.QFrame):
    def __init__(self, parent = None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)

class QKeyWidget(QtWidgets.QPushButton):
    ''' custom key label '''
    def __init__(self, parent = None) -> None:
        super().__init__(parent)
        self._key = None
        self._selected = False

        self._default_style = "QPushButton {border: 2px solid black; background-color: #E8E8E8; border-style: outset; padding: 4px; min-width: 32px; max-height: 30px;} QPushButton:hover {border: 2px #4A4648;}"
        self._selected_style = "QPushButton {border: 2px solid black; background-color: #8FBC8F; border-style: outset; padding: 4px; min-width: 32px; max-height: 30px;} QPushButton:hover {border: 2px #4A4648;}"
        self.setStyleSheet(self._default_style)
        
        self.normal_key = None # what to display normally
        self.shifted_key = None # what to display when shifted

    @property
    def key(self) -> Key:
        ''' returns the associated key '''
        return self._key
    
    @key.setter
    def key(self, value : Key):
        ''' sets the associated key '''
        self._key = value

    @property
    def is_keypad(self):
        return self._is_keypad
    
    @is_keypad.setter
    def is_keypad(self, value):
        self._is_keypad = value

    @property
    def selected(self):
        return self._selected
    
    @selected.setter
    def selected(self,value):
        if self._selected != value:
            self._selected = value
            self._update_state()

    def _update_state(self):
        ''' updates the color of the button based on the selection state '''
        if self._selected:
            self.setStyleSheet(self._selected_style)
        else:
            self.setStyleSheet(self._default_style)

    

class InputKeyboardDialog(QtWidgets.QDialog):
    ''' dialog showing a virtual keyboard in which to select key combinations with the keyboard or mouse '''


    def __init__(self, sequence = None, parent = None):
        super().__init__(parent)
        # self._sequence = InputKeyboardModel(sequence=sequence)
        main_layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("Keyboard Input Mapper")

        self._key_map = {} # map of (scancode, extended) to keys  (scancode, extended) -> key
        self._key_widget_map = {} # map of keys to widgets  key -> widget
        self.keyboard_widget = self._create_keyboard_widget() # populate the two maps 
        self.keys = None # return data
        self.sequence = None # list of keys (scancode, extended)
        self._display_shifted = False # true if displayed shifted

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QHBoxLayout()
        self.button_widget.setLayout(self.button_layout)

        self.clear_widget = QtWidgets.QPushButton("Clear")
        self.clear_widget.clicked.connect(self._clear_button_cb)
        self.clear_widget.setToolTip("Clears the selection")

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        self.button_layout.addWidget(self.clear_widget)
        self.button_layout.addStretch(1)
        self.button_layout.addWidget(self.ok_widget)
        self.button_layout.addWidget(self.cancel_widget)


        main_layout.addWidget(self.keyboard_widget)
        main_layout.addWidget(QHLine())
        main_layout.addWidget(self.button_widget)


        self.setLayout(main_layout)

        # populate the sequence (the sequence is a sequence of keys)
        if sequence:
            # the action keeps a list of keys in the format (scancode, extended_flag)
            # convert that to a key from it and selected it if the key is mapped
            for scancode_extended_tuple in sequence:
                if scancode_extended_tuple in self._key_map.keys():
                    key_name = self._key_map[scancode_extended_tuple]
                    widget = self._key_widget_map[key_name]
                    widget.selected = True
                else:
                    # log the fact we didn't find the key in the keyboard dialog
                    logging.getLogger("system").warning(f"Keyboard: unable to find {scancode_extended_tuple:x} in dialog keyboard")

        # listen to events
        #self.installEventFilter(self)


    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Shift:
            self.display_shifted = True
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Shift:
            self.display_shifted = False
        super().keyReleaseEvent(event)        

    @property
    def display_shifted(self):
        return self._display_shifted

    @display_shifted.setter
    def display_shifted(self, value):
        ''' changes the display mode of the keyboard to shifted/unshifted'''
        if value != self._display_shifted:
            for widget in self._key_widget_map.values():
                if widget.normal_key == "9":
                        pass
                if widget.shifted_key != widget.normal_key:
                    # only updates those that are different in shifted form
                    widget.setText(widget.shifted_key if value else widget.normal_key)
                    #widget.update()
            self._display_shifted = value
            

    def _ok_button_cb(self):
        ''' ok button pressed '''
        keys = [widget.key for widget in self._key_widget_map.values() if widget.selected]
        self.keys = keys
        # convert to a scancode/extended sequence
        data = []

        modifier_map = {}
        modifiers = ["leftshift","leftcontrol","leftalt","rightshift","rightcontrol","rightalt"]
        for key_name in modifiers:
            modifier_map[key_name] = []

        # create output - place modifiers up front
        for key in keys:
            item = (key.scan_code, key.is_extended)
            key_name = key.lookup_name
            if key_name in modifiers:
                modifier_map[key_name].append(item)
            else:
                data.append(item)
        sequence = []
        for key_name in modifiers:
            sequence.extend(modifier_map[key_name])
        sequence.extend(data)            
        self.sequence = sequence
        self.accept()
        

    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()

    def _clear_button_cb(self):
        ''' clear button pressed - clear all entries  '''
        for widget in self._key_widget_map.values():
            widget.selected = False

    def _create_keyboard_widget(self, parent = None):
        ''' creates a full keyboard widget for manual data entry '''
        grid_layout = QtWidgets.QGridLayout()
        # grid_layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)
        
        # list of scancodes  https://handmade.network/forums/articles/t/2823-keyboard_inputs_-_scancodes%252C_raw_input%252C_text_input%252C_key_names

        # first row = QUERTY object
        row_0 = ["","","F13","F14","F15","F16","F17","F18","F19","F20","F21","F22","F23","F24"]
        row_1 = ["Esc","","F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12","",["PrtSc","printscreen"],["Scrlck","scrolllock"],["Pause","pause"]]
        row_2 = ["`","1","2","3","4","5","6","7","8","9","0","-","=",["Back","backspace"],"",["Ins","insert"],["Home","home"],["PgUp","pageup"],"",["NumLck","numlock"],["/","npdivide"],["*","npmultiply"],["-","npminus"]]
        row_3 = [["Tab","tab"],"Q","W","E","R","T","Y","U","I","O","P","[","]","\\","",["Del","delete"],"End",["PgDn","pagedown"],"",["7","np7"],["8","np8"],["9","np9"],["+","npplus",1,2]]
        row_4 = [["CapsLck","capslock"],"A","S","D","F","G","H","J","K","L",";","'",["Enter",2],"","","","","",["4","np4"],["5","np5"],["6","np6"]]
        row_5 = [["LShift","leftshift"],"Z","X","C","V","B","N","M",",",".","/",["RShift","rightshift"],"","","","","up","","",["1","np1"],["2","np2"],["3","np3"],["Enter","npenter",1,2]]
        row_6 = [["LCtrl","leftcontrol"],["LWin","leftwin"],["LAlt","leftalt"],["Spacebar","space",6],["RAlt","rightalt"],["RWin","rightwin"],["RCtrl","rightcontrol"],"","","","left","down","right","",["0/Ins","np0",2],["./Del","npdelete"]]

        shifted_list = [
            ("`","~"),("1","!"),("2","@"),("3","#"),("4","$"),("5","%"),("6","^"),
            ("7","&&"),("8","*"),("9","("),("0",")"),("-","_"),("=","+"),
            ("[","{"),("]","}"),("\\","|"),(";",":"),("'","\""),(",","<"),(".",">"),("/","?")
            ]
        
        shifted_map = {}
        for normal, shifted in shifted_list:
            shifted_map[normal] = shifted



        rows = [row_0,row_1,row_2,row_3,row_4,row_5,row_6]

        current_row = 0
        self._key_map = {}

        for row in rows:
            current_column = 0
            for data in row:
                if isinstance(data, list):
                    # combo
                    found_key = False
                    found_name = False
                    found_column = False
                    found_row = False
                    key = None
                    key_name = None
                    column_span = 1
                    row_span= 1                    
                    for item in data:
                        if not found_key:
                            key = item
                            key_name = key.lower()
                            found_key = True
                            continue
                        if not found_name and isinstance(item, str):
                            found_name = True
                            key_name = item
                            continue
                        if not found_column and isinstance(item, int):
                            found_column = True
                            column_span = item
                            continue
                        if not found_row and isinstance(item, int):
                            found_row = True
                            row_span = item
                            continue
                    key_complex = True
                else:
                    key = data
                    key_name = key.lower()
                    key_complex = False
                    column_span = 1
                    row_span= 1                    

                if key:
                    if key in shifted_map.keys():
                        shifted = shifted_map[key] if not key_complex else key
                    else:
                        shifted = key
                    
                    widget = QKeyWidget(key)
                    action_key = key_from_name(key_name)
                    widget.key = action_key # this name must be defined in keybpoard.py 
                    widget.normal_key = key
                    widget.shifted_key = shifted
                    widget.clicked.connect(self._key_cb)
                    #logging.getLogger("system").info(f"{key_name}: {key} {shifted}")

                    self._key_map[(action_key.scan_code, action_key.is_extended)] = key_name
                    assert key_name not in self._key_widget_map.keys(),f"duplicate key in keyboard map found: {key_name}"
                    self._key_widget_map[key_name] = widget
                else:
                    widget = QtWidgets.QLabel(" ")
                grid_layout.addWidget(widget, current_row, current_column, row_span, column_span)
                
                
                # bump column
                current_column += column_span
            # bump next row
            current_column = 0
            current_row +=1


        grid_widget = QtWidgets.QWidget(parent)
        grid_widget.setLayout(grid_layout)

        return grid_widget


    def _key_cb(self):
        ''' occurs when the widget is selected'''
        widget = self.sender()
        key = widget.key
        widget.selected = not widget.selected # toggle
      
        
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

        self.record_button = QtWidgets.QPushButton("Record keys")
        self.record_button.clicked.connect(self._record_keys_cb)

        self._options_widget = QtWidgets.QWidget()
        self._options_layout = QtWidgets.QHBoxLayout()
        self._options_widget.setLayout(self._options_layout)


        self.rb_press = QtWidgets.QRadioButton("Press")
        self.rb_release = QtWidgets.QRadioButton("Release")
        self.rb_both = QtWidgets.QRadioButton("Press/Release/Delay")
        self.rb_hold = QtWidgets.QRadioButton("Hold")

        self.delay_container_widget = QtWidgets.QWidget()
        self.delay_container_layout = QtWidgets.QHBoxLayout()
        self.delay_container_widget.setLayout(self.delay_container_layout)

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

        self._options_layout.addWidget(QtWidgets.QLabel("Mode:"))
        self._options_layout.addWidget(self.rb_hold)
        self._options_layout.addWidget(self.rb_both)
        self._options_layout.addWidget(self.rb_press)
        self._options_layout.addWidget(self.rb_release)
        
        self._options_layout.addStretch(1)


        self.delay_container_layout.addWidget(delay_label)
        self.delay_container_layout.addWidget(self.delay_box)
        self.delay_container_layout.addWidget(quarter_sec_button)
        self.delay_container_layout.addWidget(half_sec_button)
        self.delay_container_layout.addWidget(sec_button)
        self.delay_container_layout.addStretch(1)

        self.show_keyboard_widget = QtWidgets.QPushButton("Select Keys")
        self.show_keyboard_widget.clicked.connect(self._select_keys_cb)

        self.action_layout.addWidget(self.record_button)
        self.action_layout.addWidget(self.show_keyboard_widget)
        self.action_layout.addStretch(1)
        

        self.main_layout.addWidget(self.key_combination)
        self.main_layout.addWidget(self.action_widget)
        self.main_layout.addWidget(self._options_widget)
        self.main_layout.addWidget(self.delay_container_widget)
        
        
        self.main_layout.addStretch(1)

    
    def _select_keys_cb(self):
        ''' display the keyboard input dialog '''
        self._keyboard_dialog = InputKeyboardDialog(sequence = self.action_data.keys, parent = self)
        self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
        self._keyboard_dialog.showNormal()
        
    def _keyboard_dialog_ok_cb(self):
        ''' callled when the dialog completes '''

        # grab the new data
        self.action_data.keys = self._keyboard_dialog.sequence
        self.action_modified.emit()
    

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
        # self.sequence = InputKeyboardModel(action.keys)

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
        # return true by default so the action gets saved even if it doesn't do anything
        return True


version = 1
name = "map-to-keyboard-ex"
create = MapToKeyboardEx
