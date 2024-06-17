

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

import container_plugins.basic
import gremlin
from gremlin.common import DeviceType, InputType
from . import common, input_item 
from gremlin.keyboard import Key
from .device_tab import InputItemConfiguration
import uuid

class OscInput(QtCore.QObject):
    ''' open sound control input object  '''

    def __init__(self, parent = None):
        super().__init__(parent)




class OscDeviceTabWidget(QtWidgets.QWidget):

    """Widget used to configure open sound control (OSC) inputs """

    device_guid = uuid.UUID('ccb486e8-808e-4b3f-abe7-bcb380f39aa4')

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
        self.input_item_list_view = input_item.InputItemListView()
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.set_model(self.input_item_list_model)
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
        
        clear_keyboard_button = common.ConfirmPushButton("Clear Inputs", show_callback = self._show_clear_cb)
        clear_keyboard_button.confirmed.connect(self._clear_inputs_cb)
        button_container_layout.addWidget(clear_keyboard_button)
        button_container_layout.addStretch(1)

        # Key add button
        button = QtWidgets.QPushButton("Add Input")
        button.clicked.connect(self._add_input_cb)

        button_container_layout.addWidget(button)

        self.left_panel_layout.addWidget(button_container_widget)
        

        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None:
            self.input_item_selected_cb(selected_index)
        

    def _show_clear_cb(self):
        return self.input_item_list_model.keyboard_rows > 0

    def _clear_inputs_cb(self):
        ''' clears all input keys '''
        self.input_item_list_model.clear()
        self.input_item_list_view.redraw()

    def _select_keys_cb(self):
        ''' display the keyboard input dialog '''
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        self._keyboard_dialog = InputKeyboardDialog(parent = self, select_single = True)
        self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
        self._keyboard_dialog.showNormal()  

    def input_item_selected_cb(self, index):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """

        item_data = self.input_item_list_model.data(index)

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

  
    def _add_input_cb(self, key : OscInput):
        """Adds the provided key to the list of keys.

        :param key the new key to add, either a single key or a combo-key

        """

        # ensure there's an entry for the 
        input_type = InputType.OpenSoundControl
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
