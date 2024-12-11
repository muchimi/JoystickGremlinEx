

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
import gremlin.ui.device_tab
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


def get_mode_device_guid():
    return parse_guid('b3b159a0-4d06-4bd6-93f9-7583ec08b877')


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
    device_guid = get_mode_device_guid()

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
        self.current_mode = current_mode

        self.device_profile.ensure_mode_exists(self.current_mode)
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

        self.input_item_list_view = input_item.InputItemListView(custom_widget_handler=self._custom_widget_handler)
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.set_model(self.input_item_list_model)
        self.input_item_list_view.redraw()

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)

        self.addLeftPanelWidget(self.input_item_list_view)

        self._item_data = gremlin.ui.device_tab.InputItemConfiguration()
        self.setRightPanelWidget(self._item_data)

        
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()

        # handle mode change inputs
        eh = gremlin.event_handler.EventHandler()
        eh.mode_changed.connect(self._mode_changed_cb)

        el = gremlin.event_handler.EventListener()
        el.mode_name_changed.connect(self._mode_name_changed)

        
        
        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None:
            self._select_item_cb(selected_index)

    @QtCore.Slot(str)
    def _mode_name_changed(self, name):
        ''' occurs when there's a mode name change '''
        self.input_item_list_view.redraw()

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
            
        return f"Mode [{gremlin.shared_state.edit_mod}] Unknown id: {input_item.input_id}"
            

    @QtCore.Slot(str)
    def _mode_changed_cb(self, mode):
        ''' occurs when a new mode is selected '''
        self.ensureInputItems() # ensure the control inputs exist for this mode

    def ensureInputItems(self):
        ''' ensures we have input items for the current mode '''

        config = self.device_profile.modes[self.current_mode].config
        # global_config = self.device_profile.modes[gremlin.shared_state.global_mode].config

        if not ModeInputModeType.ModeEnter in config[InputType.ModeControl]:
            modeEnter = gremlin.base_profile.InputItem(self._custom_name_handler)
            modeEnter.input_id = ModeInputModeType.ModeEnter
            modeEnter.device_name = "Mode"
            modeEnter.input_type = InputType.ModeControl
            modeEnter.device_guid = get_mode_device_guid()
            modeEnter.description="Enter mode actions"
            config[InputType.ModeControl][ModeInputModeType.ModeEnter] = modeEnter
        config[InputType.ModeControl][ModeInputModeType.ModeEnter].descriptionReadOnly = True

        
        if not ModeInputModeType.ModeExit in config[InputType.ModeControl]:
            modeExit = gremlin.base_profile.InputItem(self._custom_name_handler)
            modeExit.device_name = "Mode"
            modeExit.device_guid = get_mode_device_guid()
            modeExit.input_type = InputType.ModeControl
            modeExit.input_id = ModeInputModeType.ModeExit
            modeExit.description="Exit mode actions"
            modeExit.descriptionReadonly = True
            config[InputType.ModeControl][ModeInputModeType.ModeExit] = modeExit
        config[InputType.ModeControl][ModeInputModeType.ModeExit].descriptionReadOnly = True


        
        # config = self.device_profile.modes[gremlin.shared_state.global_mode].config

        # if not ModeInputModeType.ModeGlobalEnter in config[InputType.ModeControl]:
        #     modeEnter = gremlin.base_profile.InputItem(self._custom_name_handler)
        #     modeEnter.input_id = ModeInputModeType.ModeEnter
        #     modeEnter.device_name = "Mode"
        #     modeEnter.input_type = InputType.ModeControl
        #     modeEnter.device_guid = get_mode_device_guid()
        #     modeEnter.description="Enter any mode actions"
        #     config[InputType.ModeControl][ModeInputModeType.ModeEnter] = modeEnter
        # config[InputType.ModeControl][ModeInputModeType.ModeEnter].descriptionReadOnly = True

        
        # if not ModeInputModeType.ModeGlobalExit in config[InputType.ModeControl]:
        #     modeExit = gremlin.base_profile.InputItem(self._custom_name_handler)
        #     modeExit.device_name = "Mode"
        #     modeExit.device_guid = get_mode_device_guid()
        #     modeExit.input_type = InputType.ModeControl
        #     modeExit.input_id = ModeInputModeType.ModeExit
        #     modeExit.description="Exit any mode actions"
        #     modeExit.descriptionReadonly = True
        #     config[InputType.ModeControl][ModeInputModeType.ModeExit] = modeExit
        # config[InputType.ModeControl][ModeInputModeType.ModeExit].descriptionReadOnly = True
        

    def itemAt(self, index):
        ''' returns the input widget at the given index '''
        return self.input_item_list_view.itemAt(index)

    def display_name(self, input_id):
        ''' returns the name for the given input ID '''
        return input_id.display_name


    def _index_for_key(self, input_id):
        ''' returns the index of the selected input id'''
        mode = self.device_profile.modes[self.current_mode]
        sorted_keys = list(mode.config[InputType.OpenSoundControl].keys())
        return sorted_keys.index(input_id)
    

    def _select_item_cb(self, index):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """

        if index == -1:
            # nothing to select
            return 
        
        
        with QtCore.QSignalBlocker(self.input_item_list_view):
            self.input_item_list_view.select_item(index, False)
        

        input_data : gremlin.base_profile.InputItem = self.input_item_list_model.data(index)
        
        self._item_data = gremlin.ui.device_tab.InputItemConfiguration(input_data)
        self.setRightPanelWidget(self._item_data)

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
        data : gremlin.base_profile.InputItem 
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
