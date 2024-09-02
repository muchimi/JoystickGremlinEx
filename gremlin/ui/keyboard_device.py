

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
import json

# import container_plugins.basic
# import gremlin
import gremlin.config
from gremlin.input_types import InputType
import gremlin.keyboard
import gremlin.shared_state
from . import input_item, ui_common 
from gremlin.keyboard import Key
from .device_tab import InputItemConfiguration
from .input_item import InputItemWidget, InputIdentifier, InputItemListView
import uuid
from gremlin.util import *
from gremlin.input_types import InputType
import gremlin.base_classes
from lxml import etree as ElementTree
import gremlin.ui.ui_common

class KeyboardInputItem():
    ''' holds a keyboard input item '''
    def __init__(self):
        self.id = uuid.uuid4() # GUID (unique) if loaded from XML - will reload that one
        self._key = None # associated primary key (containing latched items)
        self._title_name = "Keyboard input (not configured)"
        self._display_name = None
        self._display_tooltip = None
        self._description = None
        self._suspend_update = False
        self._update()
        
    @property
    def title_name(self):
        ''' title for this input '''
        return self._title_name

    @property
    def display_name(self):
        ''' display name for this input '''
        return self._display_name
    
    @property
    def display_tooltip(self):
        return self._display_tooltip
    
    @property
    def key(self):
        return self._key
    
    @property
    def key_tuple(self):
        if self._key:
            return (self._key.scan_code, self._key.is_extended)
        return None
    
    @property
    def sequence(self):
        ''' returns a list of (scan_code, extended) tuples for all latched keys in this sequence '''
        if self._key:
            return self._key.sequence
        return []
    
    def _latched_key_update(self, source, action, index, value):
        self._update()

    
    
    @key.setter
    def key(self, value):
        assert isinstance(value, Key), f"Invalid type for key property: expected Key - got {value.type()}"
        self._key = value
        self._update()

    @property
    def index_tuple(self):
        if self._key:
            return self._key.index_tuple
        return None
    
    @property 
    def latched(self):
        ''' true if all the keys in this input are latched '''
        if not self._key:
            return False
        return self._key.latched

    @property
    def is_latched(self):
        if self._key:
            return self._key.is_latched
        return False
    
    @property
    def latched_keys(self) -> list:
        if self._key:
            return self._key.latched_keys
        return []
        

    @property
    def message_key(self):
        ''' returns the sorting key for this message '''
        return self._message_key
    
    @property
    def latched_keys(self):
        ''' returns a list of latched keys'''
        if not self.key:
            return []
        return self.key._latched_keys

    @property 
    def has_mouse(self):
        ''' true if any of the keys in the input is a mouse input '''
        if self._key:
            keys = [self._key]
            keys.extend(self._key._latched_keys)
            key: Key
            for key in keys:
                if key._is_mouse:
                    return True
                
        return False

    def parse_xml(self, node):
        ''' loads itself from xml '''
        from gremlin.keyboard import key_from_code
        self._suspend_update = True
        
        if node.tag == "input":
            self.id = read_guid(node, "guid", default_value=uuid.uuid4())

            for child in node:
                # ready key nodes
                if child.tag in ("key"):
                    virtual_code = safe_read(child,"virtual-code", int, 0)
                    scan_code = safe_read(child, "scan-code", int, 0)
                    is_extended = safe_read(child, "extended", bool, False)
                    is_mouse = safe_read(child, "mouse", bool, False)
                    # if is_mouse:
                    #     pass
                    # if virtual_code > 0:
                    #     key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)
                    # else:
                    (scan_code, is_extended), _= gremlin.keyboard.KeyMap.translate((scan_code, is_extended))
                    key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
                    
                    self._key = key
                    for latched_child in child:
                        if latched_child.tag == "latched":
                            virtual_code = safe_read(latched_child,"virtual-code", int, 0)
                            scan_code = safe_read(latched_child, "scan-code", int, 0)
                            is_extended = safe_read(latched_child, "extended", bool, False)
                            is_mouse = safe_read(latched_child, "mouse", bool, False)
                            if is_mouse:
                                
                                key = Key(scan_code = scan_code, is_mouse=True)
                            else:
                                # if virtual_code > 0:
                                #     key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)
                                # else:
                                (scan_code, is_extended), _ = gremlin.keyboard.KeyMap.translate((scan_code, is_extended))
                                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
                            if not key in self._key.latched_keys:
                                self._key._latched_keys.append(key) 

                    self._key._update()
        self._suspend_update = False
        self._update()
                    

    def to_xml(self):
        # saves itself to xml
        node = ElementTree.Element("input")
        node.set("guid", str(self.id))
        child = ElementTree.Element("key")
        root_key = self._key
        child.set("virtual-code", str(root_key.virtual_code))
        child.set("scan-code", str(root_key.scan_code))
        child.set("extended", str(root_key.is_extended))
        child.set("mouse", str(root_key.is_mouse))
        child.set("description", root_key.lookup_name)
        node.append(child)
        for key in root_key.latched_keys:
            latched_child = ElementTree.Element("latched")
            latched_child.set("virtual-code", str(key.virtual_code))
            latched_child.set("scan-code", str(key.scan_code))
            latched_child.set("extended", str(key.is_extended))
            latched_child.set("mouse", str(key.is_mouse))
            latched_child.set("description", key.lookup_name)
            child.append(latched_child)
        return node

    
    def _update(self):
        # updates the message key and display 
        if self._suspend_update:
            # ignore
            return 
        if not self._key:
            self._message_key = ""
            self._title_name = "Keyboard Input (not configured)"
            self._display_name = ""
            self._description = ""
            self._display_tooltip = ""
            return
        
    
        message_key = f"{self._key._scan_code:x}{1 if self.key._is_extended else 0}"
        
        key : Key
        for key in self._key._latched_keys:
            # if key._virtual_code > 0:
            #     message_key += f"|{key._virtual_code:x}"
            # else:
            message_key += f"|{key._scan_code:x}{1 if key._is_extended else 0}"
        
        self._message_key = message_key
    
        is_latched = self._key.is_latched
        self._title_name = f"Key input {'(latched)'if is_latched else ''}"

        self._display_name = self._key.latched_name
        self._description = self.key.latched_code
        self._display_tooltip = self._key.latched_name + " " + self.key.latched_code

    def to_string(self):
        return f"KeyboardInputItem: pair: {self.key_tuple} name: {self._display_name}"

    @property
    def name(self):
        ''' display name - can be a compound key '''
        return self._display_name

    def __eq__(self, other):
        if isinstance(other, KeyboardInputItem):
            return self.message_key == other.message_key 
        return self.__hash__() == other.__hash__()

    def __ne__(self, other):
        return not (self == other)
    
    def __hash__(self):
        return str(self.id).__hash__()
    
    def __lt__(self, other):
        ''' used for sorting purposes '''        
        # keep as is (don't sort this input entry)
        return False
    
    def __str__(self):
        return self.to_string()
    

            

from gremlin.ui.qdatawidget import QDataWidget
class KeyboardDeviceTabWidget(QDataWidget):

    """Widget used to configure keyboard inputs """

    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS (this one happens to match the regular keyboard device ID)
    device_guid = parse_guid('6F1D2B61-D5A0-11CF-BFC7-444553540000')

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
            current_mode,
            [InputType.Keyboard, InputType.KeyboardLatched]
        )


        self.input_item_list_view = input_item.InputItemListView(custom_widget_handler=self._custom_widget_handler, parent=self)
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.set_model(self.input_item_list_model)

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)
        self.input_item_list_view.item_edit.connect(self._edit_item_cb)
        
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
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)



        # key clear button
        
        clear_keyboard_button = ui_common.ConfirmPushButton("Clear Keys", show_callback = self._show_clear_cb)
        clear_keyboard_button.confirmed.connect(self._clear_keys_cb)
        button_container_layout.addWidget(clear_keyboard_button)
        button_container_layout.addStretch(1)

        virtual_keyboard_button = QtWidgets.QPushButton("Add Key")
        virtual_keyboard_button.clicked.connect(self._add_key_dialog_cb)
        button_container_layout.addWidget(virtual_keyboard_button)
        

        self.left_panel_layout.addWidget(button_container_widget)
        # Select default entry
        
        self.input_item_list_view.redraw()
        

        selected_index = self.input_item_list_view.current_index

        if selected_index != -1:
            self._select_item_cb(selected_index)

        # refresh on configuration change
        el = gremlin.event_handler.EventListener()
        el.config_changed.connect(self._config_changed_cb)


    def _config_changed_cb(self):
        self.input_item_list_view.redraw()
        
    @property
    def model(self):
        ''' the current model '''
        return self.input_item_list_model


    def _show_clear_cb(self):
        return self.input_item_list_model.rows() > 0

    def _clear_keys_cb(self):
        ''' clears keyboard input keys '''

        self.input_item_list_model.clear(input_types=[InputType.Keyboard, InputType.KeyboardLatched])
        self.input_item_list_view.redraw()

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        right_panel = self.main_layout.takeAt(1)
        if right_panel is not None and right_panel.widget():
            right_panel.widget().hide()
            right_panel.widget().deleteLater()
        if right_panel:
            self.main_layout.removeItem(right_panel)

        widget = InputItemConfiguration()
        self.main_layout.addWidget(widget,3)            

    def _add_key_dialog_cb(self):
        ''' display the keyboard input dialog '''
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        gremlin.shared_state.push_suspend_ui_keyinput()

        self._keyboard_dialog = InputKeyboardDialog(parent = self, select_single = False, index = -1)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._dialog_close_cb)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.showNormal()  
        

    def _dialog_close_cb(self):
        gremlin.shared_state.pop_suspend_ui_keyinput()

    def _dialog_ok_cb(self):
        ''' callled when the dialog completes '''

        # grab a new data index as this is a new entry
        index = self._keyboard_dialog.index 
        keys = self._keyboard_dialog.keys
        latched_key = self._keyboard_dialog.latched_key
        self._process_input_keys(keys, index, latched_key)        

    def _process_input_keys(self, keys, index, root_key = None):
        ''' processes input keys
         
        index of -1 indicates a new item
        reload: if set, updates the whole model

        '''

        # reload on new index
        reload = index == -1

        # figure out the root key
        if root_key is None:
            if not keys:
                # no data
                root_key = Key()
            else:
                root_key = gremlin.keyboard.KeyMap.get_latched_key(keys)

        # ensure the input item exists in the profile data
        if index >= 0:

            identifier = self.input_item_list_model.data(index)
            input_id = identifier.input_id
            #logging.getLogger("system").info(f"Editing index {index} {input_id.display_name}")
        else:
            input_id = KeyboardInputItem()
            index = self.input_item_list_model.rows() # new index
            #logging.getLogger("system").info(f"Adding new kbd input index {index} ")
        input_id.key = root_key
        input_type = InputType.KeyboardLatched # always use latched type starting with 13.40.14ex if root_key.is_latched else InputType.Keyboard


        # creates the item in the profile if needed 
        self.device_profile.modes[self.current_mode].get_data(input_type,input_id)

        if reload:
            # refreshes the model from the profile
            self.input_item_list_model.refresh()
            # redraw the list to include the new item
            self.input_item_list_view.redraw()
            # select the new item - its index may have changed
            index = self.input_item_list_model.input_id_index(input_id)
        else:
            # update the widget for this entry
            self.input_item_list_view.update_item(index)


        # select the item
        self.input_item_list_view.select_item(index, force = True)

        verbose = gremlin.config.Configuration().verbose
        if verbose:
            logging.getLogger("system").info(f"Final item index {index} {input_id.display_name}")
        
 

    def _select_item_cb(self, index):
        ''' called when a key has been selected - refreshes the view panel '''

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
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()
        self.input_item_list_view.select_item(-1)

        

    def mode_changed_cb(self, mode):
        """Handles mode change.

        :param mode the new mode
        """
        self.set_mode(mode)


    def refresh(self):
        """Refreshes the current selection, ensuring proper synchronization."""
        self._select_item_cb(self.input_item_list_view.current_index)

    def _custom_widget_handler(self, list_view : InputItemListView, index : int, identifier : InputIdentifier, data, parent = None):
        ''' creates a widget for the input 
        
        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item
        
        '''

        widget = InputItemWidget(identifier = identifier, populate_ui_callback=self._populate_input_widget_ui, update_callback = self._update_input_widget, config_external=True, parent=parent, data=data)
        widget.create_action_icons(data)
        widget.setDescription(data.description)

        widget.setIcon("fa.keyboard-o")
        widget.enable_close()
        widget.enable_edit()

        self._update_input_widget(widget, widget.parent)

        return widget
    

    def _update_input_widget(self, input_widget, container_widget):
        ''' called when the widget has to update itself on a data change '''
        data = input_widget.identifier.input_id 
        input_widget.setTitle(data.title_name)
        input_widget.setInputDescription(data.display_name)
        input_widget.setToolTip(data.display_tooltip)
        if data.has_mouse:
            input_widget.setInputDescriptionIcon("mdi.mouse")
        else:
            input_widget.setInputDescriptionIcon(None)

        is_warning = False
        status_text = ""
        if data.key is None:
            is_warning = True
            status_text = "Not configured"
        elif gremlin.config.Configuration().show_scancodes:
            status_text = data.key.latched_code
 
        if is_warning:
            self._status_widget.setIcon("fa.warning", use_qta=True, color="red")
        else:
            self._status_widget.setIcon() # clear it
        self._status_widget.setText(status_text)
        self._status_widget.setVisible(len(status_text)>0)



    def _populate_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when a button is created for custom content '''

        layout = QtWidgets.QVBoxLayout(container_widget)
        self._status_widget = gremlin.ui.ui_common.QIconLabel(parent=container_widget)
        self._status_widget.setVisible(False)
        self._status_widget.setObjectName("status")
        
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self._status_widget)
        self._update_input_widget(input_widget, container_widget)
                
  
    
    def _edit_item_cb(self, widget, index, data):
        ''' called when the edit button is clicked  '''
        from gremlin.keyboard import Key
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog

        data = self.model.data(index)
        sequence = data.input_id.sequence
            
        logging.getLogger("system").info(f"Editing index {index} {data.input_id.display_name}")
        gremlin.shared_state.push_suspend_ui_keyinput()
        self._keyboard_dialog = InputKeyboardDialog(sequence, parent = self, select_single = False, index = index)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._dialog_close_cb)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.showNormal()        
        






                
