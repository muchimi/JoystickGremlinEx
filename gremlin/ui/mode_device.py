

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
from gremlin.util import *
from lxml import etree as ElementTree
import enum
import gremlin.util
import gremlin.base_profile
import psygnal
from psygnal import Signal



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

      


class ModeDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):

    """Widget used to configure mode change actions """
    
    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.mode_tab_guid

    def __init__(
            self,
            device_profile,
            current_mode,
            object_name = 'Mode Device',
            parent=None
    ):
        """Creates a new object instance.

        :param device_profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """
        self._device_guid =gremlin.shared_state.mode_tab_guid
        self._device_id = str(self._device_guid)
        super().__init__(object_name, self.device_guid , parent)
        import gremlin.ui.ui_common as ui_common
        import gremlin.ui.input_item as input_item

        # Store parameters
        self.device_profile = device_profile
        self.device_profile.ensure_mode_exists(current_mode)
        self.widget_storage = {}

        # List of inputs
        self.input_item_list_model = input_item.InputItemListModel(
            device_profile,
            current_mode,
            [InputType.ModeControl] # only allow Mode inputs for this widget
        )

        # create the two entries
        self.ensureInputItems()


        # update the display names 

        self.input_item_list_view = input_item.InputItemListView(custom_widget_handler=self._custom_widget_handler, device_id = self._device_id)
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.setModel(self.input_item_list_model)
        self.input_item_list_view.redraw()

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)

        config = gremlin.config.Configuration()
        if config.show_container_id:
            device = gremlin.joystick_handling.get_device(self.device_guid)
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget, _ = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:")
            self.addLeftPanelWidget(widget)
            w1 = widget

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget, _ = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:")
            self.addLeftPanelWidget(widget)
            w2 = widget

            gremlin.ui.ui_common.synchronize_grids([w1, w2])        

        self.addLeftPanelWidget(self.input_item_list_view)

        
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()

        

        el = gremlin.event_handler.EventListener()
        el.mode_name_changed.connect(self._mode_name_changed)
        el.edit_mode_changed.connect(self._edit_mode_changed_cb) # edit mode changed or mode added/removed
        

        # last index selected, -1 means none
        self._last_selected_index = -1 


        
        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is None:
            selected_index = -1
        self._select_item_cb(selected_index)



    @QtCore.Slot(str)
    def _edit_mode_changed_cb(self, mode : str):
        ''' occurs when a new mode is selected '''
        self.set_mode(mode)

    @QtCore.Slot(str)
    def _mode_name_changed(self, name):
        ''' occurs when there's a mode name change '''
        self.input_item_list_view.redraw()


    def _config_changed_cb(self):
        ''' called when configuraition has changed '''
        self.refresh()      


    def _custom_name_handler(self, input_item):
        ''' gets the custom name for the input item '''
        input_item : gremlin.base_profile.InputItem
        match input_item.input_id:
            case ModeInputModeType.ModeEnter:
                return f"Mode [{gremlin.shared_state.edit_mode}] Activate"
            case ModeInputModeType.ModeExit:
                return f"Mode [{gremlin.shared_state.edit_mode}] Deactivate"
            case ModeInputModeType.ModeGlobalEnter:
                return f"Mode Activate (any)"
            case ModeInputModeType.ModeGlobalExit:
                return f"Mode Deactivate (any)"
            
        return f"Mode [{gremlin.shared_state.edit_mode}] Unknown id: {input_item.input_id}"
            
            

    def ensureInputItems(self, refresh = False):
        ''' ensures we have input items for the current mode 
        :param refresh: True if list view should be updated if changes are made
        :returns: True if changes were made 

        '''
        current_mode = gremlin.shared_state.edit_mode
        self.device_profile.ensure_mode_exists(current_mode)
        config = self.device_profile.modes[current_mode].config
        
        changed = False

        if not ModeInputModeType.ModeEnter in config[InputType.ModeControl]:
            modeEnter = gremlin.base_profile.InputItem(self._custom_name_handler)
            modeEnter.input_type = InputType.ModeControl
            modeEnter.setOverrideInputType(InputType.JoystickButton)
            modeEnter.input_id = ModeInputModeType.ModeEnter
            modeEnter.description = "Mode Enter Actions"
            modeEnter.descriptionReadOnly = True
            config[InputType.ModeControl][ModeInputModeType.ModeEnter] = modeEnter
            changed = True
        else:
            modeEnter = config[InputType.ModeControl][ModeInputModeType.ModeEnter]

        
        if not ModeInputModeType.ModeExit in config[InputType.ModeControl]:
            modeExit = gremlin.base_profile.InputItem(self._custom_name_handler)
            modeExit.input_type = InputType.ModeControl
            modeExit.setOverrideInputType(InputType.JoystickButton)
            modeExit.input_id = ModeInputModeType.ModeExit
            modeExit.description = "Mode Exit Actions"
            modeExit.descriptionReadOnly = True
            config[InputType.ModeControl][ModeInputModeType.ModeExit] = modeExit
            changed = True
        else:
            modeExit = config[InputType.ModeControl][ModeInputModeType.ModeExit]
        
        modeEnter.profile_mode = current_mode
        modeExit.profile_mode = current_mode
        
        if changed or refresh:
            self.input_item_list_model.refresh()    

        return changed 

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
        sorted_keys = list(mode.config[InputType.ModeControl].keys())
        return sorted_keys.index(input_id)
    
         
    def getWidgetKey(self, input_type, input_id):
        ''' gets the content widget compound key for the item / input combination'''
        return (self._device_guid, input_type, input_id)


    def _select_item_cb(self, index):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """


        self.ensureInputItems(True) # ensure the control inputs exist for this mode

        if index == -1:
            index = self._last_selected_index

        if index == -1:
            # select the first item
            if self.input_item_list_model.rows():
                index = 0
            else:
                self._blank_input()
                return 
        
        with QtCore.QSignalBlocker(self.input_item_list_view):
            self.input_item_list_view.select_item(index, False)
        
        
        item_data : gremlin.base_profile.InputItem = self.input_item_list_model.data(index)
        input_type = InputType.ModeControl

        key = self.getWidgetKey(input_type, index)
        widget = self.getRegisteredWidget(key)
        if not widget:
            widget = gremlin.ui.input_item.InputItemConfigurationWidget(item_data, object_name = f"Mode  [{item_data.display_name}]")
            self.registerWidget(key, widget)

        self._item_data = item_data

        widget = self.selectRegisteredWidget(key)

        # remember the last input
        config = gremlin.config.Configuration()
        device_guid = self.device_guid
        input_type = InputType.ModeControl
        input_id = item_data.input_id if item_data else None
        

        config.set_last_input(device_guid, input_type, input_id)

        if item_data:
            
            # Create new configuration widget
            item_data.is_axis = False
            change_cb = self._create_change_cb(index)
            widget.action_model.data_changed.connect(change_cb)
            widget.description_changed.connect(change_cb)

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
        widget.setTitle(self._custom_name_handler(data))
        widget.setInputDescription(data.description)
        widget.disable_close()
        widget.disable_edit()
        widget.setIcon("fa5.edit")



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
        mode = self.device_profile.modes[self.current_mode]
        sorted_keys = list(mode.config[InputType.ModeControl].keys())
        return sorted_keys.index(input_id)
        

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.input_item_list_view.redraw_index(index)

    def set_mode(self, mode):
        ''' changes the mode of the tab '''        
        self.current_mode = mode
        self.ensureInputItems()
        self.input_item_list_model.mode = mode
        
        #self.input_item_list_view.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.input_item_list_model.refresh()
            self.input_item_list_view.redraw()        
            self._select_item_cb(self._last_selected_index)

 

    def refresh(self, emit = True):
        """Refreshes the current selection, ensuring proper synchronization."""
        self.set_mode(gremlin.shared_state.edit_mode) # force a model and reload
        
        #self._select_item_cb(self.input_item_list_view.current_index)

