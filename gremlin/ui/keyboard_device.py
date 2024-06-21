

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


import logging

from PySide6 import QtWidgets, QtCore

# import container_plugins.basic
# import gremlin
from gremlin.input_types import InputType
#from gremlin.common import DeviceType
from . import input_item, ui_common 
from gremlin.keyboard import Key
from .device_tab import InputItemConfiguration
from .input_item import InputItemWidget, InputIdentifier, InputItemListView
import uuid
from gremlin.util import load_pixmap, load_icon


class KeyboardDeviceTabWidget(QtWidgets.QWidget):

    """Widget used to configure keyboard inputs """

    def __init__(
            self,
            device_profile,
            current_mode,
            parent=None
    ):
        """Creates a new object instance.

        :param device_profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """
        super().__init__(parent)

        # Store parameters
        self.device_profile = device_profile
        self.current_mode = current_mode

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.left_panel_layout = QtWidgets.QVBoxLayout()
        self.device_profile.ensure_mode_exists(self.current_mode)
        self.widget_storage = {}

        # List of inputs
        self.input_item_list_model = input_item.InputItemListModel(
            device_profile,
            current_mode
        )
        self.input_item_list_view = input_item.InputItemListView(custom_widget_handler=self.custom_widget_handler)
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.set_model(self.input_item_list_model)
        

        # TODO: make this saner
        self.input_item_list_view.redraw()

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(
            self.input_item_selected_cb
        )

        self.left_panel_layout.addWidget(self.input_item_list_view)
        self.main_layout.addLayout(self.left_panel_layout,1)

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        right_panel = self.main_layout.takeAt(1)
        if right_panel is not None and right_panel.widget():
            right_panel.widget().hide()
            right_panel.widget().deleteLater()
        if right_panel:
            self.main_layout.removeItem(right_panel)

        widget = InputItemConfiguration()     
        self.main_layout.addWidget(widget,3)

        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout()
        button_container_widget.setLayout(button_container_layout)

        # key clear button
        
        clear_keyboard_button = ui_common.ConfirmPushButton("Clear Keys", show_callback = self._show_clear_cb)
        clear_keyboard_button.confirmed.connect(self._clear_keys_cb)
        button_container_layout.addWidget(clear_keyboard_button)
        button_container_layout.addStretch(1)

        # Key add button
        button = ui_common.NoKeyboardPushButton("Add Key")
        button.clicked.connect(self._record_keyboard_key_cb)

        button_container_layout.addWidget(button)
        

        virtual_keyboard_button = QtWidgets.QPushButton("Select Key")
        virtual_keyboard_button.clicked.connect(self._select_keys_cb)
        button_container_layout.addWidget(virtual_keyboard_button)
        

        self.left_panel_layout.addWidget(button_container_widget)
        

        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None:
            self.input_item_selected_cb(selected_index)
        

    def _show_clear_cb(self):
        return self.input_item_list_model.rows() > 0

    def _clear_keys_cb(self):
        ''' clears keyboard input keys '''

        self.input_item_list_model.clear()
        self.input_item_list_view.redraw()

    def _select_keys_cb(self):
        ''' display the keyboard input dialog '''
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        self._keyboard_dialog = InputKeyboardDialog(parent = self, select_single = True)
        self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
        self._keyboard_dialog.showNormal()  

    def _keyboard_dialog_ok_cb(self):
        ''' callled when the dialog completes '''

        # grab the new data
        keys = self._keyboard_dialog.keys
        if keys:
            modifiers = []
            root_key = None
            for key in keys:
                if key.is_modifier:
                    modifiers.append(key)
                else:
                    root_key = key
            if modifiers:
                root_key.latched_keys = modifiers
            self._add_keyboard_key_cb(root_key)
                  

    def input_item_selected_cb(self, index):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """
        # Assumption is that the entries are sorted by their scancode and
        # extended flag identification
        # sorted_keys = sorted(self.device_profile.modes[self.current_mode].config[InputType.Keyboard])
        #sorted_keys = list(self.device_profile.modes[self.current_mode].config[InputType.Keyboard])

        item_data = self.input_item_list_model.data(index)


        # if index is None or len(sorted_keys) <= index:
        #     item_data = None
        # else:
        #     index_key = sorted_keys[index]
        #     item_data = self.device_profile.modes[self.current_mode]. \
        #         config[InputType.Keyboard][index_key]

        right_panel = self.main_layout.takeAt(1)
        if right_panel is not None and right_panel.widget():
            right_panel.widget().hide()
            right_panel.widget().deleteLater()
        if right_panel:
            self.main_layout.removeItem(right_panel)

        widget = InputItemConfiguration(item_data)
        self.main_layout.addWidget(widget,3)            

        if item_data:
            
            # Create new configuration widget
            
            change_cb = self._create_change_cb(index)
            widget.action_model.data_changed.connect(change_cb)
            widget.description_changed.connect(change_cb)

            

            # Refresh item list view and select correct entry
            #self.input_item_list_view.redraw()
            #self.input_item_list_view.select_item(index,False)

    def _record_keyboard_key_cb(self):
        """Handles adding of new keyboard keys to the list.

        Asks the user to press the key they wish to add bindings for.
        """
        self.button_press_dialog = ui_common.InputListenerWidget(
            self._add_keyboard_key_cb,
            [InputType.Keyboard],
            return_kb_event=False,
            multi_keys=False
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

    def _add_keyboard_key_cb(self, key : Key):
        """Adds the provided key to the list of keys.

        :param key the new key to add, either a single key or a combo-key

        """

        # ensure there's an entry for the 
        input_type = InputType.KeyboardLatched if key.is_latched else InputType.Keyboard

        self.device_profile.modes[self.current_mode].get_data(input_type,key)
        self.input_item_list_view.redraw()
        self.input_item_list_view.select_item(self._index_for_key(key),True)

    def _index_for_key(self, key_or_index):
        """Returns the index into the key list based on the key itself.

        :param key the keyboard key being queried
        :return index of the provided key
        """

        mode = self.device_profile.modes[self.current_mode]
        if isinstance(key_or_index, Key):
            key = key_or_index
            if key.is_latched:
                sorted_keys = list(mode.config[InputType.KeyboardLatched])
                return sorted_keys.index(key)
        sorted_keys = list(mode.config[InputType.Keyboard])
        return sorted_keys.index(key_or_index)
        

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.input_item_list_view.redraw_index(index)

    def set_mode(self, mode):
        ''' changes the mode of the tab '''        
        self.current_mode = mode
        self.device_profile.ensure_mode_exists(self.current_mode)
        self.input_item_list_model.mode = mode

        # Remove the existing widget, if there is one
        item = self.main_layout.takeAt(1)
        if item is not None and item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        if item:
            self.main_layout.removeItem(item)

    def mode_changed_cb(self, mode):
        """Handles mode change.

        :param mode the new mode
        """
        self.set_mode(mode)


    def refresh(self):
        """Refreshes the current selection, ensuring proper synchronization."""
        self.input_item_selected_cb(self.input_item_list_view.current_index)

    def custom_widget_handler(self, list_view : InputItemListView, index : int, identifier : InputIdentifier, data):
        ''' creates a widget for the input 
        
        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item
        
        '''

        widget = InputItemWidget(identifier)
        widget.create_action_icons(data)
        widget.update_description(data.description)
        widget.selected_changed.connect(list_view._create_selection_callback(index))
        widget.closed.connect(self._create_close_callback(index))
        widget.edit.connect(self._create_edit_callback(index))
                
        widget.enable_close()
        widget.enable_edit()

        return widget
    
    def edit_item(self, index, emit_signal = True):
        ''' handles the closing of a specific item '''
        from gremlin.keyboard import Key
        sequence = None
        key: Key
        key = None
        data = self.model.data(index)
        if data.input_type == InputType.KeyboardLatched:
            key = data.input_id
            sequence = [key.index_tuple()]
            lk: Key
            for lk in key.latched_keys:
                sequence.append(lk.index_tuple())
        elif data.input_type == InputType.Keyboard:
            sequence = [data.input_id]

        if sequence:
            from gremlin.ui.virtual_keyboard import InputKeyboardDialog
            self._keyboard_dialog = InputKeyboardDialog(sequence, parent = self, select_single = True)
            self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
            self._keyboard_dialog.showNormal()

    def close_item(self, index, emit_signal = True):
        ''' handles the closing of a specific item '''
        data = self.model.data(index)
        if data.containers:
            # item includes containers, prompt
            message_box = QtWidgets.QMessageBox()
            message_box.setText("Delete confirmation")
            message_box.setInformativeText("This will delete associated actions for this entry.\nAre you sure?")
            pixmap = load_pixmap("warning.svg")
            pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio) 
            message_box.setIconPixmap(pixmap)
            message_box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Ok |
                QtWidgets.QMessageBox.StandardButton.Cancel
                )
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            result = message_box.exec()
            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                self._confirmed_close(index)
        else:
            self._confirmed_close(index)

    def _create_close_callback(self, index):
        ''' creates a callback to handle the closing of items '''
        return lambda x: self.close_item(index)
    
    
    def _create_edit_callback(self, index):
        ''' creates a callback to handle the edit of items '''
        return lambda x: self.edit_item(index)
                


    def _confirmed_close(self, index):
        self.model.removeRow(index)
        self.redraw()


    def _keyboard_dialog_ok_cb(self):
        ''' callled when the dialog completes '''

        # grab the new data
        keys = self._keyboard_dialog.keys
        if keys:
            data = self.model.data(self._current_index)
            # convert to keyboard latch input if it's not already        
            data.input_type = InputType.KeyboardLatched
            modifiers = []
            root_key = None
            for key in keys:
                if key.is_modifier:
                    modifiers.append(key)
                else:
                    root_key = key
            if modifiers:
                root_key.latched_keys = modifiers
            data.input_id = root_key
            self.redraw()

                
