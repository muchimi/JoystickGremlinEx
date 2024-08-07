import os
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_profile
from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.keyboard
import gremlin.macro
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.ui.input_item
import enum

from gremlin.keyboard import Key
from gremlin.util import load_icon
import logging
import copy

      

class QKeyWidget(QtWidgets.QPushButton):

    # indicates when the widget is hovered (true = on)
    hover = QtCore.Signal(object, bool)

    # fires when selection changes
    selected_changed = QtCore.Signal(object)

    ''' custom key label '''
    def __init__(self, text = None, parent = None) -> None:
        super().__init__(text= text, parent = parent)
        self._key = None
        self._selected = False
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover, True)

        self._default_style = "QPushButton {border: 2px solid black; border-radius: 4px; background-color: #E8E8E8; border-style: outset; padding: 4px; min-width: 32px; max-height: 30px;} QPushButton:hover {border: 2px #4A4648;}"
        self._selected_style = "QPushButton {border: 2px solid black; border-radius: 4px; background-color: #8FBC8F; border-style: outset; padding: 4px; min-width: 32px; max-height: 30px;} QPushButton:hover {border: 2px #4A4648;}"
        self.setStyleSheet(self._default_style)
        
        self.normal_key = None # what to display normally
        self.shifted_key = None # what to display when shifted
        self.installEventFilter(self)

    @property
    def key(self) -> Key:
        ''' returns the associated key '''
        return self._key
    
    @key.setter
    def key(self, value : Key):
        ''' sets the associated key '''
        self._key = value

    @property
    def is_click_shifted(self):
        return self._click_shifted

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
            # tell listeners status changed
            #self.selected_changed.emit(self, self._click_shifted)

    def _update_state(self):
        ''' updates the color of the button based on the selection state '''
        if self._selected:
            self.setStyleSheet(self._selected_style)
        else:
            self.setStyleSheet(self._default_style)

  
    def eventFilter(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.Type.HoverEnter:
            self.hover.emit(self, True)
        elif t == QtCore.QEvent.Type.HoverLeave:
            self.hover.emit(self, False)

        return False
    
    @property
    def display_name(self):
        ''' friendly key name'''
        if self._key:
            return self._key.name + " " + self._key.latched_code
        return ""
        

    

class InputKeyboardDialog(QtWidgets.QDialog):
    ''' dialog showing a virtual keyboard in which to select key combinations with the keyboard or mouse '''
    
    closed = QtCore.Signal() # sent when the dialog closes

    def __init__(self, sequence = None, parent = None, select_single = False, allow_modifiers = True, index = None):
        '''
        :param sequence - input keys to use
        :param select_single - if set, only can select a single key
        :param allow_modifiers - if set - modifier keys along with regular keys are allowed
        '''
        super().__init__(parent)
        # self._sequence = InputKeyboardModel(sequence=sequence)
        main_layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("Keyboard & Mouse Input Mapper")
        self._select_single = select_single
        self._allow_modifiers = allow_modifiers
        self.index = index
        self._latched_key = None # contains a single primary key latched to all the others
        self._display_shifted = False
        self._solo_select = False

        self._modifier_keys = gremlin.keyboard.KeyMap._keyboard_modifiers

        self._key_map = {} # map of (scancode, extended) to keys  (scancode, extended) -> key
        self._key_widget_map = {} # map of keys to widgets  key -> widget
        self.keyboard_widget = self._create_keyboard_widget() # populate the two maps 
        self._keys = None # return data
        self._display_shifted = False # true if displayed shifted

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QHBoxLayout()
        self.button_widget.setLayout(self.button_layout)

        self.clear_widget = QtWidgets.QPushButton("Clear")
        self.clear_widget.clicked.connect(self._clear_button_cb)
        self.clear_widget.setToolTip("Clears the selection")

        self.listen_widget = QtWidgets.QPushButton("Listen")
        self.listen_widget.clicked.connect(self._listen_cb)

        self.numlock_widget = QtWidgets.QCheckBox("Force numlock Off")
        self.numlock_widget.setChecked(gremlin.shared_state.current_profile.get_force_numlock())
        self.numlock_widget.clicked.connect(self._force_numlock_cb)

        self.key_description = QtWidgets.QLabel()

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        self.button_layout.addWidget(self.clear_widget)
        self.button_layout.addWidget(self.listen_widget)
        self.button_layout.addWidget(QtWidgets.QLabel(" "))
        self.button_layout.addWidget(self.key_description)
        self.button_layout.addStretch(1)
        self.button_layout.addWidget(self.ok_widget)
        self.button_layout.addWidget(self.cancel_widget)


        main_layout.addWidget(self.keyboard_widget)
        main_layout.addWidget(gremlin.ui.ui_common.QHLine())
        main_layout.addWidget(self.button_widget)


        self.setLayout(main_layout)

        self._set_sequence(sequence)      

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    @property
    def latched_key(self):
        ''' contains a single key which represents the latched selection in the dialog '''
        return self._latched_key
    
    @property
    def keys(self):
        ''' list of raw selected keys '''
        return self._keys


    def _set_sequence(self, sequence):
        ''' loads a given key sequence into the virtual keyboard '''
        if sequence:
            # the action keeps a list of keys in the format (scancode, extended_flag)
            # convert that to a key from it and selected it if the key is mapped
            for widget in self._key_widget_map.values():
                widget.selected = False

            for item in sequence:
                if item in self._key_map.keys():
                    key_name = self._key_map[item]
                    widget = self._key_widget_map[key_name]
                    widget.selected = True
                elif isinstance(item, Key):
                    # key object
                    key_name = self._key_map[item.index_tuple()]
                    widget = self._key_widget_map[key_name]
                    widget.selected = True
                elif isinstance(item, tuple):
                    # key id
                    key_name = self._key_map[item]
                    widget = self._key_widget_map[key_name]
                    widget.selected = True
                elif isinstance(item, int):
                    # virtual code
                    key = gremlin.keyboard.KeyMap.find_virtual(item)
                    key_name = self._key_map[key.index_tuple()]
                    widget = self._key_widget_map[key_name]
                    widget.selected = True
                elif item in self._key_map.keys():
                    key_name = self._key_map[item]
                    widget = self._key_widget_map[key_name]
                    widget.selected = True
                else:
                    # log the fact we didn't find the key in the keyboard dialog
                    logging.getLogger("system").warning(f"Keyboard: unable to find {item} in dialog keyboard")

    def _force_numlock_cb(self, checked):
        gremlin.shared_state.current_profile.set_force_numlock(checked)

    def _listen_cb(self):
        """Handles adding of new keyboard keys to the list.

        Asks the user to press the key they wish to add bindings for.
        """
        from gremlin.ui.ui_common import InputListenerWidget
        self.button_press_dialog = InputListenerWidget(
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=True # allow key combinations
        )

        self.button_press_dialog.item_selected.connect(self._add_keyboard_listener_key_cb)

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
        

    def _add_keyboard_listener_key_cb(self, keys):
        """Adds the provided key to the list of keys.

        :param key the new key to add, either a single key or a combo-key

        """
        # the new entry will be a new index
        self._set_sequence(keys)


    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key.Key_Shift:
            self.display_shifted = True
        elif key == QtCore.Qt.Key.Key_Control:
            self.solo_select = True
        
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key.Key_Shift:
            self.display_shifted = False
        elif key == QtCore.Qt.Key.Key_Control:
            self.solo_select = False
        super().keyReleaseEvent(event)        

    @property
    def solo_select(self):
        return self._solo_select
    
    @solo_select.setter
    def solo_select(self, value):
        self._solo_select = value

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
        
        # keys = [Key(scan_code = widget.key.scan_code, is_extended = widget.key.is_extended, is_mouse=widget.key.is_mouse, virtual_code=widget.key.virtual_code) for widget in self._key_widget_map.values() if widget.selected]
        selected_widgets = [widget for widget in self._key_widget_map.values() if widget.selected]
        keys = []
        for widget in selected_widgets:
            key = widget.key.duplicate()
            # if widget.key.virtual_code > 0:
            #     key = gremlin.keyboard.KeyMap.find_virtual(widget.key.virtual_code)
            # else:
            #     key = gremlin.keyboard.KeyMap.find(widget.key.scan_code, widget.key.is_extended)
            keys.append(key)
            # print (f"returning key: {key} ")

        # returned keys
        self._keys = keys

        return_key = gremlin.keyboard.KeyMap.get_latched_key(keys)
        
        # print (f"Return key: {return_key}")
        self._latched_key = return_key
        

        self.accept()
        self.close()
        

    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()
        self.close()

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
        row_0 = ["","","F13","F14","F15","F16","F17","F18","F19","F20","F21","F22","F23","F24","","mouse_1","mouse_2","mouse_3","","mouse_4","mouse_5","wheel_up","wheel_down"]
        row_1 = ["Esc","","F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12","",["PrtSc","printscreen"],["Scrlck","scrolllock"],["Pause","pause"],"","","","wheel_left","wheel_right"]
        row_2 = ["`","1","2","3","4","5","6","7","8","9","0","-","=",["Back","backspace"],"",["Ins","insert"],["Home","home"],["PgUp","pageup"],"",["NumLck","numlock"],["/","npdivide"],["*","npmultiply"],["-","npminus"]]
        row_3 = [["Tab","tab"],"Q","W","E","R","T","Y","U","I","O","P","[","]","\\","",["Del","delete"],"End",["PgDn","pagedown"],"",["7","np7"],["8","np8"],["9","np9"],["+","npplus",1,2]]
        row_4 = [["CapsLck","capslock"],"A","S","D","F","G","H","J","K","L",";","'",["Enter",2],"","","","","",["4","np4"],["5","np5"],["6","np6"]]
        row_5 = [["LShift","leftshift"],"Z","X","C","V","B","N","M",",",".","/",["RShift","rightshift"],"","","","","up","","",["1","np1"],["2","np2"],["3","np3"],["Enter","npenter",1,2]]
        row_6 = [["LCtrl","leftcontrol"],["LWin","leftwin"],["LAlt","leftalt"],["Spacebar","space",6],["RAlt","rightalt2"],["RWin","rightwin"],["RCtrl","rightcontrol"],"","","","left","down","right","",["0/Ins","np0",2],["./Del","npdelete"]]

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
                        shifted = None

                    icon = None
                    # handle special key names
                    tooltip = ""
                    if key == "mouse_1":
                        key = "M1"
                        icon = "mdi.mouse"
                        toolltip = "Left Mouse Button"
                    elif key == "mouse_2":
                        key = "M2"
                        icon = "mdi.mouse"
                        toolltip = "Middle Mouse Button"
                    elif key == "mouse_3":
                        key = "M3"
                        icon = "mdi.mouse"
                        toolltip = "Right Mouse Button"
                    elif key == "mouse_4":
                        key = "M4"
                        icon = "mdi.mouse"
                        toolltip = "Forward Mouse Button"
                    elif key == "mouse_5":
                        key = "M5"
                        icon = "mdi.mouse"
                        toolltip = "Back Mouse Button"
                    elif key == "wheel_up":
                        key = "MWU"
                        icon = "mdi.mouse"
                        toolltip = "Wheel Up"
                    elif key == "wheel_down":
                        key = "MWD"
                        icon = "mdi.mouse"
                        toolltip = "Wheel Down"
                    elif key == "wheel_left":
                        key = "MWL"
                        icon = "mdi.mouse"    
                        toolltip = "Tilt Left"  
                    elif key == "wheel_right":
                        key = "MWR"
                        icon = "mdi.mouse"
                        toolltip = "Tilt Right"   
                    
                    widget = QKeyWidget(key)
                    if icon:
                        widget.setIcon(load_icon(icon))
                        widget.setIconSize(QtCore.QSize(14,14))


                    action_key = gremlin.keyboard.key_from_name(key_name)
                    widget.key = action_key # this name must be defined in keybpoard.py 
                    widget.normal_key = key
                    widget.shifted_key = shifted if shifted else widget.normal_key
                    
                    widget.clicked.connect(self._widget_clicked_cb)
                    widget.hover.connect(self._key_hover_cb)
                    #logging.getLogger("system").info(f"{key_name}: {key} {shifted}")
  

                    self._key_map[(action_key.scan_code, action_key.is_extended)] = key_name
                    assert key_name not in self._key_widget_map.keys(),f"duplicate key in keyboard map found: {key_name}"

                    # # handle special duplicates
                    # if key_name == "rightshift":
                    #     other_key = gremlin.keyboard.key_from_name("rightshift2")
                    #     self._key_map[(other_key.scan_code, other_key.is_extended)] = key_name
                    #     self._key_widget_map["rightshift2"] = widget
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
    
    def _key_hover_cb(self, widget, hover):
        if hover:
            self.key_description.setText(widget.display_name)
        else:
            self.key_description.setText("")

    def deselect(self):
        ''' deselects all keys '''
        selected_widgets = [widget for widget in self._key_widget_map.values() if widget.selected]
        for widget in selected_widgets:
            widget.selected = False


    def _widget_clicked_cb(self):
        ''' occurs when the widget is selected'''
        current_widget = self.sender()
        if self.solo_select:
            # deselect all
            self.deselect()

        if self._select_single:
            # single select mode
            source_modifier = False
            if self._allow_modifiers and current_widget.key.lookup_name in self._modifier_keys:
                source_modifier = True
            if not source_modifier:
                selected_widgets = [widget for widget in self._key_widget_map.values() if widget.selected]
                for widget in selected_widgets:
                    if self._allow_modifiers and widget.key.lookup_name in self._modifier_keys:
                        continue
                    widget.selected = False # deselect

        
        current_widget.selected = not current_widget.selected # toggle
        