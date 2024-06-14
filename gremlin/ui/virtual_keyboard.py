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


    def __init__(self, sequence = None, parent = None, select_single = False):
        '''
        :param sequence - input keys to use
        :param select_single - if set, only can select a single key
        '''
        super().__init__(parent)
        # self._sequence = InputKeyboardModel(sequence=sequence)
        main_layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("Keyboard Input Mapper")

        self._select_single = select_single

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
        if self._select_single:
            # single select mode
            selected_widgets = [widget for widget in self._key_widget_map.values() if widget.selected]
            for widget in selected_widgets:
                widget.selected = False # deselect

        widget = self.sender()
        key = widget.key
        widget.selected = not widget.selected # toggle
        