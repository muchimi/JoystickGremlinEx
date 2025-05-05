

# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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

from __future__ import annotations
import logging

from PySide6 import QtWidgets, QtCore, QtGui
import threading
import gremlin.config
import gremlin.event_handler
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.shared_state
from gremlin.keyboard import Key
import gremlin.ui.joystick_device
import uuid
from gremlin.singleton_decorator import SingletonDecorator
import collections
import logging
import re
import time
import logging
from typing import Any, Iterator, List, Union
import gremlin.ui.input_item
import os
import gremlin.ui.input_item
import gremlin.ui.ui_common
from gremlin.util import *
from lxml import etree as ElementTree
import enum
import gremlin.util
import gremlin.base_profile
from gremlin.base_classes import AbstractInputItem



class ModeInputModeType(enum.IntEnum):
    ''' possible input modes '''
    ModeEnter = 0  # executes on mode enter
    ModeExit = 1 # executes on mode exit
    ModeGlobalEnter = 2 # executes on any mode change (activate)
    ModeGlobalExit = 3 # executes on any mode change (deactivate)

    @staticmethod
    def to_display_name(value):
        match value:
            case ModeInputModeType.ModeEnter:
                return "Mode Activate"
            case ModeInputModeType.ModeExit:
                return "Mode Deactivate"
            case ModeInputModeType.ModeGlobalEnter:
                return "Mode Activate (any)"
            case ModeInputModeType.ModeGlobalExit:
                return "Mode Deactivate (any)"
        
        return f"Unknown mode: {value}"
    
class StateInputItem(AbstractInputItem):
    ''' holds a single state '''
    def __init__(self, key : str = None, default_value = False, description = None):
        super().__init__()
        self._id = gremlin.util.get_guid()
        self._key = key
        self._display_name = key
        self._default_value = default_value
        self._value = default_value
        self._type_cast = type(default_value) if default_value is not None else None
        self.description = description
        
        item = gremlin.base_profile.InputItem() #self._custom_name_handler)
        item.input_id = self
        item.input_type = InputType.State
        item.device_name = "State"
        item.device_type = DeviceType.State
        item.device_guid = gremlin.shared_state.state_tab_guid

        self._input_item = item

    @property
    def id(self) -> str:
        return self._id
    @id.setter
    def id(self, value : str):
        self._id = value


    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, data):
        self._value = data

    @property
    def default_value(self):
        return self._default_value
    
    @default_value.setter
    def default_value(self, data):
        self._default_value = data        

    @property
    def key(self)-> str:
        return self._key
    @key.setter
    def key(self, value : str):
        self._key = value
    
    @property
    def type_cast(self):
        return self._type_cast
    
    @property
    def message_key(self):
        return self.key
    
    def getOverrideInputType(self):
        # report to containers/actions as a button
        return InputType.JoystickButton 
    
    @property
    def input_item(self):
        ''' holds a reference to the mapping data for this input '''
        return self._input_item
    # @input_item.setter
    # def input_item(self, value):
    #     self._input_item = value

    def to_xml(self):
        ''' write XML state node '''
        node = ElementTree.Element("state", id = self._id, key = self._key)
        value = self._default_value
        description = self._description
        if description:
            node.set("description", description)
        if isinstance(value, str):
            node.set("value", value)
            node.set("type", "str")
        elif isinstance(value, float):
            node.set("value", safe_format(value, float))
            node.set("type", "float")
        elif isinstance(value, bool):
            node.set("value", safe_format(value, bool))
            node.set("type", "bool")
        else:
            # ignore other types
            return None

        # write container data
        self._input_item.to_xml(node)
        

        return node
    
    def from_xml(self, node, data = None):
        ''' read XML state node '''
        self._key = node.get("key")
        if "id" in node.attrib:
            self._id = node.get("id")
        node_type = node.get("type")
        
        if "description" in node.attrib:
            self._description = node.get("description")
        else:
            self._description = None
            
        value = None

        if node_type == "str":
            value = safe_read(node, "value", str, '')
        elif node_type == "float":
            value = safe_read(node, "value", float, 0.0)
        elif node_type == "int":
            value = safe_read(node, "value", int, 0)
        elif node_type == "bool":
            value = safe_read(node, "value", bool, False)

        self._default_value = value
        self._input_item.from_xml(node, data, skip_root=True)


    def __str__(self):
        return f"State: [{self._key}]"

    def __hash__(self):
        return hash(self._key)

        

    
    

@SingletonDecorator
class StateData(QtCore.QObject):
    ''' holds state information '''
    changed  = QtCore.Signal(object) # fires when the value changes (StateItem)

    def __init__(self):
        super().__init__()
        self._data = {}
        self.changed.connect(self._state_changed)
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._reset)

    def _reset(self):
        ''' reset states to default values '''
        for data in self._data.values():
            data.value = data.default_value

    def _register(self, key : str, value = None, description = None) -> StateInputItem:
        ''' registers a new state '''
        if not key:
            return None
        if key in self._data:
            # already in the list
            return self._data[key]
        
        item = StateInputItem(key, value, description)    
        self._data[key] = item
        return item
    
    def register(self, key : str, value = None, description = None) -> StateInputItem:
        ''' registers a new state '''
        item = self._register(key, value, description)
        self._sort()
        return item

    def unregister(self, key: str):
        ''' removes a state from the list '''
        if key in self._data:
            del self._data[key]

    def value(self, key : str):
        ''' gets the state value '''
        if key in self._data:
            return self._data[key].value
        return None
    
    def add(self, data : StateInputItem):
        if data and not data.key in self._data:
            self._data[data.key] = data
            self._sort()

    def _sort(self):
        self._data = dict(sorted(self._data.items()))

    def getStates(self):
        ''' gets all input items '''
        return self._data
    
    def getInputItems(self):
        ''' gets a dict of input items for each state'''
        input_items = {}
        for key, item in self._data.items():
            input_items[key] = item.input_item
        return input_items

    
    def setValue(self, key : str, value, emit = True):
        ''' sets state value (and registers if needed) '''
        if not key:
            return
        trigger = not key in self._data or self._data[key].value != value
        self._data[key].value = value
        if emit and trigger:
            self.changed.emit(self._data[key])    
    
    def description(self, key : str) -> str:
        ''' gets the description for the state '''
        if key in self._data:
            return self._data[key].description
        return None
    
    def sorted_keys(self) -> list:
        ''' returns the keys in the state data sorted alphabetically '''
        return list(self._data.keys())
    
    def setDescription(self, key : str, description : str, emit = True):
        ''' sets the description on a state '''
        if key in self._data:
            if self._data[key].description != description:
                self._data[key].description = description
                if self.emit:
                    self.changed.emit(self._data[key])
    
    def exists(self, key: str):
        ''' true if the key exists in the state data '''
        return key in self._data
    
    def clear(self):
        ''' clears all data '''
        self._data.clear()
        

    def remove(self, key : str):
        if key in self._data:
            del self._data[key]
    
    def index(self, item):
        ''' gets the index of the item in the current list'''
        if item.key in self._data:
            keys = list(self._data.keys())
            return keys.index(item.key)
        return -1
    
    def createDefault(self, count = 5):
        ''' creates default states '''
        for index in range(count):
            key = f"Default_{index+1}"
            self._register(key, False, f"Default state {index+1}")
        self._sort()

    def __iter__(self):
        return self._data.__iter__()
    
    def __next__(self):
        return self._data.__next__()
    
    def __len__(self):
        return len(self._data)

    def __getitem__(self, key):
        if key in self._data:
            return self._data[key]
        return None
        

    def to_xml(self):
        ''' persists the data to XML '''
        root = ElementTree.Element("states")
        for key in self._data:
            item = self._data[key]
            if item:
                node = item.to_xml()
                if node is not None:
                    root.append(node)
        return root

    def from_xml(self, root):
        ''' reads saved data '''

        for node in root:
            item = StateInputItem()
            item.from_xml(node)
            self._data[item.key] = item

    @QtCore.Slot(object)
    def _state_changed(self, data : StateInputItem):
        if not gremlin.shared_state.is_running:
            return
        event = gremlin.event_handler.Event(
            event_type= InputType.State,
            device_guid= gremlin.shared_state.state_tab_guid,
            identifier= data,
            value = data.value,
            curved_value = None,
            raw_value= None,
            is_axis = False,
            is_virtual = True,
            is_pressed = data.value,
            override_input_type=InputType.JoystickButton # tell actions we're a button
        )
        eh = gremlin.event_handler.EventHandler()
        eh.execute_event(event)


class StateInputConfigDialog(gremlin.ui.ui_common.QRememberDialog):
    ''' dialog showing the OSC input configuration options '''

    def __init__(self, data : StateInputItem, parent):
        '''
        :param index - the input item index zero based
        :param identifier - the input item identifier 
        '''
        
        super().__init__(self.__class__.__name__,parent = parent)
        # self._sequence = InputKeyboardModel(sequence=sequence)
        main_layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("State Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent # list view
        

        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        self._config_widget, self._config_layout = gremlin.ui.ui_common.getGridContainer()
        self.data = data

        self._name_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._name_widget.setText(data.key)
        self._name_widget.textChanged.connect(self._name_changed)
        self._description_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._description_widget.setText(data.description)
        self._description_widget.textChanged.connect(self._description_changed)

        row = 0
        col = 0
        self._config_layout.addWidget(QtWidgets.QLabel("Name:"), row, col)
        self._config_layout.addWidget(self._name_widget, row, col+1)

        row += 1
        self._config_layout.addWidget(QtWidgets.QLabel("Description:"), row, col)
        self._config_layout.addWidget(self._description_widget, row, col+1)

        row += 1
        self._config_layout.addWidget(QtWidgets.QLabel("Default State:"), row, col)

        self._default_on_widget = gremlin.ui.ui_common.QDataRadioButton("On", True)
        self._default_off_widget = gremlin.ui.ui_common.QDataRadioButton("Off", False)
        if data.value:
            self._default_on_widget.setChecked(True)
        else:
            self._default_off_widget.setChecked(True)
        self._default_off_widget.clicked.connect(self._default_changed)    
        self._default_on_widget.clicked.connect(self._default_changed)

        widget, layout = gremlin.ui.ui_common.getHContainer([self._default_on_widget, self._default_off_widget])
        self._config_layout.addWidget(widget, row, col+1)

        main_layout.addWidget(self._config_widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True)
        
        main_layout.addWidget(widget)



    def _validate(self):
        sd = StateData()
        enabled = bool(self.data.key)
        if enabled:
            item = sd.value(self.data.key)
            if item:
                enabled = item.id == self.data.id

        self.ok_widget.setEnabled(enabled)


    @QtCore.Slot()
    def _name_changed(self):
        self.data.key = self._name_widget.text()
        self._validate()

    @QtCore.Slot()
    def _description_changed(self):
        self.data.description = self._description_widget.text()
        


    @QtCore.Slot(bool)
    def _default_changed(self, checked):
        widget = self.sender()
        self.data.default_value = widget.data

    def _ok_button_cb(self):
        ''' ok button pressed '''
        self.accept()
        
    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()        
        
class StateDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):

    """Widget used to configure state change actions """
    
    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.state_tab_guid

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
        import gremlin.ui.ui_common as ui_common
        import gremlin.ui.input_item as input_item

        # Store parameters
        self.device_profile = device_profile
        self.widget_storage = {}

        # List of inputs
        self.input_item_list_model = input_item.InputItemListModel(
            device_profile,
            current_mode,
            [InputType.State], # only allow Mode inputs for this widget,
            custom_update_handler= self._update_handler,
            custom_remove_handler = self._remove_handler,
            custom_clear_handler = self._clear_handler,

        )


        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)
        

        # clear and add buttons to add/clear all states
        clear_button = ui_common.ConfirmPushButton("Clear States", show_callback = self._show_clear_cb)
        icon = gremlin.util.load_icon("fa6.trash-can")
        clear_button.setIcon(icon)
        clear_button.setToolTip("Deletes all states")
        clear_button.confirmed.connect(self._clear_inputs_cb)
        button_container_layout.addWidget(clear_button)
        button_container_layout.addStretch(1)

        # Key add button
        add_button = QtWidgets.QPushButton("Add State")
        add_button.setToolTip("Adds a new state to the profile")
        icon = gremlin.util.load_icon("fa6s.plus")
        add_button.setIcon(icon)
        add_button.clicked.connect(self._add_input_cb)

        button_container_layout.addWidget(add_button)




        # update the display names 
        self.input_item_list_view = input_item.InputItemListView(custom_widget_handler=self._custom_widget_handler)
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.setModel(self.input_item_list_model)
        self.input_item_list_view.redraw()

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)
        self.input_item_list_view.item_edit.connect(self._edit_item_cb)
        self.input_item_list_view.item_closed.connect(self._close_item_cb)
        
        

        self.addLeftPanelWidget(self.input_item_list_view)

        # default entry
        self._item_data = gremlin.ui.joystick_device.InputItemConfiguration()
        self.setRightPanelWidget(self._item_data)
        self.addLeftPanelWidget(button_container_widget)
        
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()

        

        # el = gremlin.event_handler.EventListener()
        # el.mode_name_changed.connect(self._mode_name_changed)
        # el.edit_mode_changed.connect(self._edit_mode_changed_cb) # edit mode changed or mode added/removed
        

        # last index selected, -1 means none
        self._last_selected_index = -1 


        
        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is None:
            selected_index = -1
        self._select_item_cb(selected_index)

    def _show_clear_cb(self):
        return self.input_item_list_model.rows() > 0

    def _config_changed_cb(self):
        ''' called when configuraition has changed '''
        self.refresh()      


    def _add_input_cb(self):
        """Adds a new input to the inputs list  """
        input_id = StateInputItem()
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()
        self.input_item_list_view.select_item(self._index_for_key(input_id),True)
        
        index = self.input_item_list_view.current_index

        # last index selected, -1 means none
        self._last_selected_index = -1 

        # redraw the UI
        self._select_item_cb(index)

        # auto edit new input
        self._edit_item_cb(None, index, input_id)

    def _edit_item_cb(self, widget, index, data):
        ''' called when the edit button is clicked  '''
        self._edit_dialog = StateInputConfigDialog(data, self)
        self._edit_dialog.accepted.connect(self._dialog_ok_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()
        self._index = index


    def _close_item_cb(self, widget, index, data):
        ''' called when the close button is clicked '''
        
        if not self.input_item_list_model.rows():
            # display blank page if no item left
            self._item_data = gremlin.ui.joystick_device.InputItemConfiguration()
            self.setRightPanelWidget(self._item_data)         

    def _dialog_ok_cb(self):        
        ''' called when edit dialog closes with ok '''
        data = self._edit_dialog.data
        sd = StateData()
        if not sd.exists(data):
            sd.add(data)
            self.input_item_list_model.refresh()

        index = sd.index(data)
        identifier = self.input_item_list_model.data(index)
        input_item : StateInputItem = identifier.input_id
        input_item.key = data.key
        input_item.description = data.description
        input_item.default_value = data.default_value
        self._select_item_cb(self._index)


    def _clear_inputs_cb(self):
        ''' clears all input keys '''
        self.input_item_list_model.clear(input_types=[InputType.State])
        self.input_item_list_view.redraw()

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        
        widget = gremlin.ui.joystick_device.InputItemConfiguration()     
        self.setRightPanelWidget(widget)
            
    def _update_handler(self, model, emit_change = True):
        ''' called when the data model for the input list needs to be updated - refreshes the model view '''
        state = self.device_profile.state
        self._input_items = {}

        keys = [key for key in state]
        keys.sort()

        model._index_map = {}
        model._item_map = {}
            
 
        changed = False
        for index, key in enumerate(keys):
            data = state[key]
            item = data.input_item
            # item = gremlin.base_profile.InputItem() #self._custom_name_handler)
            # item.input_id = data
            # item.input_type = InputType.State
            # item.device_name = "State"
            # item.device_type = DeviceType.State
            # item.device_guid = gremlin.shared_state.state_tab_guid
            self._input_items[key] = item
            changed = True
            model._index_map[index] = item
            model._item_map[key] = index
            
        
        if changed and emit_change:
            model.data_changed.emit()

    def _remove_handler(self, model, index, emit_change = True):
        ''' clears a single index '''
        if index in model._index_map:
            item = model._index_map[index]
            key = item.input_id.key
            sd = StateData()
            sd.remove(key)
            self._update_handler(model, emit_change)
            

    def _clear_handler(self, model, emit_change = True):
        ''' clears all state data '''
        model._index_map = {}
        model._item_map = {}
        model.data_changed.emit()
        sd = StateData()
        sd.clear()
        if emit_change:
            model.data_changed.emit()

    
    def itemAt(self, index):
        ''' returns the input widget at the given index '''
        return self.input_item_list_view.itemAt(index)

    def display_name(self, input_id):
        ''' returns the name for the given input ID '''
        return input_id.display_name


    def _index_for_key(self, input_id):
        ''' returns the index of the selected input id'''
        current_mode = gremlin.shared_state.edit_mode
        mode = self.device_profile.modes[current_mode]
        sorted_keys = list(mode.config[InputType.State].keys())
        return sorted_keys.index(input_id)
    

    def _select_item_cb(self, index):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """

        if index == -1:
            index = self._last_selected_index

        if index == -1:
            # select the first item
            if self.input_item_list_model.rows():
                index = 0
            else:
                return 
        
        with QtCore.QSignalBlocker(self.input_item_list_view):
            self.input_item_list_view.select_item(index, False)
        
        
        input_data : gremlin.base_profile.InputItem = self.input_item_list_model.data(index)
        
        widget = gremlin.ui.joystick_device.InputItemConfiguration(input_data)
        self._item_data = widget
        self.setRightPanelWidget(widget)

        # remember the last input
        config = gremlin.config.Configuration()
        device_guid = self.device_guid
        input_type = InputType.OpenSoundControl
        input_id = input_data.input_id if input_data else None
        

        config.set_last_input(device_guid, input_type, input_id)

        if input_data:
            
            # Create new configuration widget
            input_data.is_axis = False
            change_cb = self._create_change_cb(index)
            self._item_data.action_model.data_changed.connect(change_cb)
            self._item_data.description_changed.connect(change_cb)

            self.input_item_list_view.select_item(index,False)


        self._last_selected_index = index
        el = gremlin.event_handler.EventListener()
        el.input_selection_changed.emit(device_guid, input_type, input_id)

    def _custom_widget_handler(self, list_view, index : int, identifier, data, parent = None):
        ''' creates a widget for the input 
        
        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item
        
        '''
        import gremlin.ui.input_item

        widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, populate_ui_callback = self._populate_input_widget_ui, update_callback = self._update_input_widget, config_external=True, parent = parent)
        widget.data = data
        widget.create_action_icons(data)
        widget.setTitle(f"State: [{data.input_id.key}]")
        widget.setInputDescription(data.input_id.description)
        # widget.disable_close()
        # widget.disable_edit()
        widget.setIcon("mdi.state-machine")



        # remember what widget is at what index
        widget.index = index
        return widget

   
    
    def _set_status(self, widget, icon = None, status = None, use_qta = True, color = None):
        ''' sets the status of an input widget '''
        status_widget = widget.findChild(gremlin.ui.ui_common.QIconLabel, "status")
        if color:
            status_widget.setIcon(icon, use_qta = use_qta, color = color)
        else:
            status_widget.setIcon(icon, use_qta = use_qta)
        
        status_widget.setText(status)
        status_widget.setVisible(status is not None)    


    


    def _update_input_widget(self, input_widget, container_widget):
        ''' called when the widget has to update itself on a data change '''
        pass
 

    def _populate_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when a button is created for custom content '''
        layout = QtWidgets.QVBoxLayout(container_widget)
        status_widget = gremlin.ui.ui_common.QIconLabel()
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)
        self._update_input_widget(input_widget, container_widget)





    def _index_for_key(self, input_id):
        ''' returns the index of the selected input id'''
        sd = StateData()
        return sd.index(input_id)
        

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.input_item_list_view.redraw_index(index)

    def set_mode(self, mode):
        ''' changes the mode of the tab '''        
        self.current_mode = mode
        
        self.input_item_list_model.mode = mode
        
        #self.input_item_list_view.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.input_item_list_model.refresh()
            self.input_item_list_view.redraw()        
            self._select_item_cb(self._last_selected_index)

 

    def refresh(self):
        """Refreshes the current selection, ensuring proper synchronization."""
        self.set_mode(gremlin.shared_state.edit_mode) # force a model and reload
        #self._select_item_cb(self.input_item_list_view.current_index)

