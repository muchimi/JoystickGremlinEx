# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026 
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

import enum
from PySide6 import QtWidgets, QtCore, QtGui
from lxml import etree
import lxml.etree

import gremlin
import gremlin.config
import gremlin.event_handler
import gremlin.singleton_decorator
import gremlin.types
import gremlin.base_conditions
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
import gremlin.ui.axis_calibration
import gremlin.ui.ui_common
import gremlin.ui.eliding
from gremlin.util import load_icon, load_pixmap, get_guid
import gremlin.util
from gremlin.input_types import InputType
from gremlin.base_buttons import *
from gremlin.types import DeviceType, TabDeviceType
import gremlin.plugin_manager
import gremlin.ui.ui_common as ui_common
from gremlin.ui.ui_common import QBoxFrame
from functools import partial
from  gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType
import logging
import lxml
from shiboken6 import Shiboken
import psygnal
from psygnal import Signal
import copy
import gremlin.tabstate



from gremlin.ui import virtual_button

syslog = logging.getLogger("system")

class InputIdentifier(QtCore.QObject):

    """Represents the identifier of a single input item."""

    def __init__(self, input_type, device_guid, input_id, device_type, input_name, is_axis = False, is_button = False):
        """Creates a new instance.

        :param input_type: the type of input
        :param input_id: the identifier of the input
        :param device_type: the type of device this input belongs to
        :param input_name: the name to display 
        :param is_axis: true if the input is an axis behavior
        :param is_button: true if the input is a button behavior
        """
        super().__init__()
        self._input_type = input_type
        self._device_guid = device_guid
        self._input_id = input_id
        self._device_type = device_type
        self._input_guid = get_guid() # unique internal GUID for this entry
        self._input_name = input_name
        self._is_axis = is_axis


    @property
    def device_guid(self):
        return self._device_guid

    @property
    def device_type(self):
        return self._device_type

    @property
    def input_type(self):
        return self._input_type

    @property
    def input_id(self):
        return self._input_id

    @input_id.setter
    def input_id(self, value):
        self._input_id = value

    @property
    def input_name(self) -> str:
        return self._input_name
    @input_name.setter
    def input_name(self, value : str):
        self._input_name = value

    @property
    def guid(self):
        return self._input_guid
    
    @property
    def is_axis(self) -> bool:
        ''' true if this item is setup as an axis input (linear) '''
        if self._input_id and hasattr(self._input_id, "is_axis"):
            return self._input_id.is_axis
        return self._is_axis

    @property
    def is_button(self) -> bool:
        ''' true if this item is setup as an button input (momentary) '''
        return not self.is_axis
    
    @property
    def is_valid(self) -> bool:
        if hasattr(self._input_id, "is_valid"):
            return self._input_id.is_valid
        return True
    
    @property
    def is_status(self) -> bool:
        if hasattr(self._input_id, "is_status"):
            return self._input_id.is_status
        return True
    
    @property
    def is_hat(self) -> bool:
        ''' true if the item is a hat '''
        return self._input_type == InputType.JoystickHat
    
    def getInputItem(self):
        ''' gets the input item for this identifier '''
        profile = gremlin.shared_state.current_profile
        if self._device_type == DeviceType.State:
            mode = gremlin.shared_state.master_mode
            device_guid = gremlin.shared_state.state_tab_guid
        else:
            mode = gremlin.shared_state.edit_mode
            device_guid = self._device_guid
        
        if device_guid in profile.devices:
            if mode in profile.devices[device_guid].modes:
                if self._input_type in profile.devices[device_guid].modes[mode].config:
                    input_items = profile.devices[device_guid].modes[mode].config[self._input_type]
                    if self._input_id in input_items:
                        input_item = input_items[self._input_id]
                        return input_item
            
        return None # not found

    
class InputItemListModel(ui_common.AbstractModel):

    """Model storing a device's input item list."""

    def __init__(self,
                 device_data,
                 mode : str,
                 allowed_types : list = None,
                 custom_update_handler = None, 
                 custom_remove_handler = None, 
                 custom_clear_handler = None, 
                 custom_filter_handler = None,
                 custom_delete_confirm_handler = None,
                 show_master_mode : bool = False,
                 show_filtered_only : bool = False):
        """Creates a new instance.

        :param device_data the profile data managed by this model
        :param mode the mode this model manages
        :param custom_update_handler: handler for custom updates to the data
        :param show_master_mode: determines if master mode items are displayed in the model
        """
        import gremlin.base_profile
        super().__init__()
        self._device_data  : gremlin.base_profile.Device = device_data
        self._mode = mode
        self._show_master_mode = show_master_mode
        self._show_filtered_only = show_filtered_only

        
        self._index_map = {} # map of index to input item
        self._item_map = {} # map of input_id to index
        self._source_index_map = {} # map of source states
        if allowed_types is not None:
            self._allowed_input_types  = gremlin.base_classes.TraceableList(allowed_types, self._filter_change_cb)
        else:
            # all types
            self._allowed_input_types = gremlin.base_classes.TraceableList(InputType.to_list(), self._filter_change_cb)

        
        self._custom_update_handler = custom_update_handler
        self._custom_clear_handler = custom_clear_handler
        self._custom_remove_handler = custom_remove_handler
        self._custom_filter_handler = custom_filter_handler # handles entries, return true to include, false to exclude
        self._custom_delete_confirm_handler = custom_delete_confirm_handler # return true if the input can be deleted

        self.updateData()

    @property
    def show_filtered(self) -> bool:
        return self._show_filtered_only
    @show_filtered.setter
    def show_filtered(self, value : bool):
        if self._show_filtered_only != value:
            self._show_filtered_only = value
            self.updateData()
    

    def _filter_change_cb(self):
        ''' occurs when the input filter changes '''
        self.updateData()


    @property
    def allowed_input_types(self):
        ''' input type filter list '''
        return self._allowed_input_types


    @property
    def mode(self):
        """Returns the mode handled by this model.

        :return the mode managed by the model
        """
        return self._mode

    @mode.setter
    def mode(self, mode):
        """Sets the mode managed by the model.

        :param mode the mode handled by the model
        """
        self._mode = mode
        self.updateData()


    def _filter_data(self):
        # filters the input data
        if self._custom_filter_handler:
            # apply filter
            new_index_map = {} # holds filtered items only
            new_item_map = {}
            new_index = 0
            for index in self._source_index_map:
                data = self._source_index_map[index]
                if self._custom_filter_handler(data):
                    new_index_map[new_index] = data
                    new_item_map[data.input_id] = new_index
                    new_index +=1

            self._index_map = new_index_map
            self._item_map = new_item_map

    def getFilteredIndices(self):
        ''' returns the list of indices currently visible in the model '''
        return [index for index in self._index_map]
    
    def getFilteredItems(self):
        ''' returns the list of filtered items '''
        return self._index_map.values()

    def getItems(self):
        ''' returns the list of unfiltered items '''
        return self._source_index_map.values()
    
    def _update_source(self):
        ''' updates source data (unfiltered) '''
        self._source_index_map = self._index_map.copy()
        self._source_item_map = self._item_map.copy()

    def _update_filter(self, emit = False):
        ''' updates the filters only (does not load new data) '''
        self._filter_data()     

    def _next_source_index(self):
        ''' gets the next index for a source map '''
        i_list = [i for i in self._source_index_map]
        i_list.sort()
        index = 0
        while index in i_list:
            index+=1
        return index
    
    def _next_index(self):
        ''' gets the next index for a source map '''
        i_list = [i for i in self._index_map]
        i_list.sort()
        index = 0
        while index in i_list:
            index+=1
        return index
    
           

    
    def updateData(self, apply_filter = True, emit_change = True):
        ''' loads into the data model all the items for the current mode and device '''
        import gremlin.base_profile
        import gremlin.config
        # load the items for this mode

        if self._custom_update_handler:
            # use our custom handler to update the model data
            self._custom_update_handler(self, emit_change)
            self._update_source()
            if apply_filter: self._filter_data()
            return
        
        registry = gremlin.base_profile.ProfileRegistry()
        device_guid = self._device_data.device_guid
        mode = self.mode

        #mode_object = self._device_data.modes[self._mode]
        index = 0

        profile = gremlin.shared_state.current_profile

        verbose = gremlin.config.Configuration().verbose_mode_filter


        self._index_map = {} # map of index to value
        self._item_map = {}  # map of values to their index

        device : dinput.DeviceSummary = gremlin.joystick_handling.getDevice(device_guid)           

        for input_type in self._allowed_input_types:

            input_items = registry.getInputItems(device_guid, mode, input_type = input_type)
           
            
            if input_items and device.device_type in (DeviceType.Joystick, DeviceType.VJoy):
                # sort by axes and buttons
                input_items.sort(key = lambda x: x.sortKey)
       
            for input_item in input_items:
                if self._show_filtered_only or device.device_type in (DeviceType.Joystick, DeviceType.VJoy):
                    filtered = profile.settings.getFiltered(input_item.device_guid, input_item.input_type, input_item.input_id)
                    
                    if filtered:
                        continue
                    if verbose: syslog.info(f"Input {device.name} : {input_item.input_type.name} {input_item.input_id} visible")
                
                self._index_map[index] = input_item
                self._item_map[input_item.input_id] = index 
                index += 1

  
        if self._show_master_mode:
            master_mode = gremlin.shared_state.master_mode
            if master_mode in self._device_data.modes:
                # older profile may not have master mode defined until saved
                input_items = registry.getInputItems(device_guid, master_mode, input_type)
                for input_item in input_items:
                        
                        if self._show_filtered_only or device.device_type == DeviceType.Joystick:
                            filtered = profile.settings.getFiltered(input_item.device_guid, input_item.input_type, input_item.input_id)
                            
                            if filtered:
                                continue
                            if verbose: syslog.info(f"Input {device.name} : {input_item.input_type.name} {input_item.input_id} visible")
                        
                        self._index_map[index] = input_item
                        self._item_map[input_item.input_id] = index 
                        index += 1

                # mode_object = self._device_data.modes[master_mode]
                # for input_type in self._allowed_input_types:
                #     if input_type in mode_object.config.keys():
                #         sorted_keys = sorted(mode_object.config[input_type].keys())
                #         for data_key in sorted_keys:
                #             input_item : gremlin.base_profile.InputItem = mode_object.config[input_type][data_key]
                #             # add hardware GUID reference to data block so we have an easier reference to it

                #             if self._show_filtered_only:
                #                 if not input_item.hasContainers:
                #                     # filter out empty items 
                #                     continue
                #             input_item.device_guid = self._device_data.device_guid
                #             self._index_map[index] = input_item
                            
                #             self._item_map[input_item.input_id] = index
                #             index += 1



        self._update_source()
        #if apply_filter: self._filter_data()

        if emit_change:
            self.data_changed.emit()


    def indexOf(self, input_id):
        if input_id in self._item_map:
            return self._item_map[input_id]
        return -1
    
    def hasInputItem(self, input_item):
        ''' true if the model contains the input item '''
        return input_item in self._index_map.values()
    
    def indexOfInputItem(self, input_item):
        for index, item in self._index_map.items():
            if item == input_item:
                return index
        return -1 # not found
    
    def inputItemAtIndex(self, index):
        ''' gets the input item as the given index '''
        if index in self._index_map:
            return self._index_map[index]
        return None
    
    


    def sort(self, sort_callback):
        ''' sorts the data using a sorting callback - the callback takes a list of input items, and returns a list of input items '''

        syslog.info("Before sort:----------------------------")
        for index, item in self._source_index_map.items():
            syslog.info(f"[{index}] = [{item.input_id.display_name}]")

        syslog.info("After sort:----------------------------")
        
        item_list = [item for item in self._source_index_map.values()]
        item_list = sort_callback(item_list)
        
        new_index_map = {}
        new_item_map = {}
        new_source_index_map = {}
        new_source_item_map = {}

        for index, item in enumerate(item_list):
            if item in self._item_map:
                new_index_map[index] = item
                new_item_map[item] = index
            new_source_index_map[index] = item
            new_source_item_map[item] = index
            syslog.info(f"[{index}] = [{item.input_id.display_name}]")

        self._index_map = new_index_map if new_index_map else new_source_index_map
        self._item_map = new_item_map if new_item_map else new_source_item_map
        self._source_index_map = new_source_index_map
        self._source_item_map = new_source_item_map

        # input_items = self._device_data.modes[self._mode]
        # for input_type in self._allowed_input_types:
        #     if input_type in input_items.config.keys():
        #         saved_data = {}
        #         for key in item_list:
        #             input_id = key.input_id
        #             if input_id in input_items.config[input_type]:
        #                 data = input_items.config[input_type][input_id]
        #                 saved_data[input_id] = data
        #                 del input_items.config[input_type][input_id]
                        
                        
        #         for key in item_list:
        #             input_id = key.input_id
        #             if input_id in saved_data:
        # self.updateData()
        self.data_changed.emit()


    def refresh(self, emit = False):
        ''' refreshes the mode data without data reload '''
        self.updateData(emit_change = emit)

    def applyFilter(self):
        ''' applies the filters only (does not load new data)'''
        self._filter_data()

    def clearFilter(self):
        ''' removes any filtering '''
        self.updateData(apply_filter = False)



    def rows(self) -> int:
        """Returns the number of rows in the model.

        :return number of rows in the model
        """
        return len(self._source_index_map)
    
    def filteredRows(self) -> int:
         return len(self._index_map)
    

    def dataModel(self):
        ''' gets all the items'''
        return self._source_index_map


    def data(self, index):
        """Returns the data stored at the provided index.

        :param index the index for which to return the data
        :return data stored at the provided index
        """
        if not index in self._source_index_map:
            return None

        return self._source_index_map[index]
    
    def filteredData(self, index):
        """Returns the data stored at the provided index.

        :param index the index for which to return the data
        :return data stored at the provided index
        """

        if not index in self._index_map:
            return None

        return self._index_map[index]
    

    
    def add(self, item):
        ''' adds new item at the new index '''

        if not item in self._index_map:
            new_index = len(self._index_map)
            self._item_map[item] = new_index
            self._index_map[new_index] = item

            self._update_source()
            self._update_filter()

            return new_index
        else:
            # return the index of the existing item
            return self._item_map[item]




    def removeRow(self, index):
        ''' removes the item at the specified index '''
        import gremlin.base_profile

        try:
            if self._custom_remove_handler:
                self._custom_remove_handler(self, index)
        
                return True

            data = self.data(index)
            if data:
                input_type = data.input_type
                if not input_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.OpenSoundControl, InputType.Midi, InputType.State):
                    # cannot remove other types
                    return False

                input_item = data
                input_id = data.input_id

                registry = gremlin.base_profile.ProfileRegistry()
                input_id_key = registry.getInputIdKey(input_id)

                input_items = self._device_data.modes[self._mode]
                if input_type in input_items.config and input_id_key in input_items.config[input_type]:
                    del input_items.config[input_type][input_id_key]
                registry.removeInputItem(input_item)
                


            return True
        finally:
            self.updateData()


    def action_id_to_index(self, action_id):
        ''' get the model index containing the action id'''

        if action_id:
            # find the row by action_id
            for index in range(self.rows()):
                data = self.data(index)
                for container in data.containers:
                    for action_list in container.action_sets:
                        for action_data in action_list:
                            if action_data.action_id == action_id:
                                return index

        # not found
        return -1

    def input_id_index(self, item):
        ''' gets the model index based on the input id content '''
        if item and item in self._item_map.keys():
            return self._item_map[item]
        return -1

    def event_to_index(self, event):
        """Converts an event to a model index.

        :param event the event to convert
        :return index corresponding to the event's input
        """

        input_items = self._device_data.modes[self._mode]


        offset_map = dict()
        offset_map[InputType.Keyboard] = 0
        offset_map[InputType.JoystickAxis] =\
            len(input_items.config[InputType.Keyboard])
        offset_map[InputType.JoystickButton] = \
            offset_map[InputType.JoystickAxis] + \
            len(input_items.config[InputType.JoystickAxis])
        offset_map[InputType.JoystickHat] = \
            offset_map[InputType.JoystickButton] + \
            len(input_items.config[InputType.JoystickButton])
        offset_map[InputType.KeyboardLatched] = \
            offset_map[InputType.JoystickHat] + \
            len(input_items.config[InputType.JoystickHat])
        offset_map[InputType.OpenSoundControl] = \
            offset_map[InputType.KeyboardLatched] + \
            len(input_items.config[InputType.KeyboardLatched
            ])
        offset_map[InputType.Midi] = \
            offset_map[InputType.OpenSoundControl] + \
            len(input_items.config[InputType.OpenSoundControl
            ])
        

        if event.event_type in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
            # Generate a mapping from axis index to linear axis index
            # axis_index_to_linear_index = {}
            item: gremlin.base_profile.InputItem
            item_found: gremlin.base_profile.InputItem = None
            index : int

            for index, item in self._index_map.items():
                if item.input_type == event.event_type and item.input_id == event.identifier:
                    item_found = item
                    break
            if item_found:
                return index
            
            return 0

        else:
            return offset_map[event.event_type] + event.identifier - 1

    def clear(self, input_types):
        ''' removes all inputs of the specififed type '''
        if self._custom_clear_handler:
            self._custom_clear_handler(self)
        else:
            input_items = self._device_data.modes[self._mode]
            for input_type in input_types:
                if input_type in input_items.config:
                    input_items.config[input_type] = {}

        self.reset()

    def reset(self):
        ''' clears all data '''
        self._index_map = {} # map of filtered index to input item
        self._item_map = {} # map of filtered input_id to index
        self._source_index_map = {} # map of source data 
        


class InputItemListView(ui_common.AbstractView):

    """View displaying the contents of an InputItemListModel. Used in the left panel of the main UI to display inputs."""

    # fires when the list view is redrawn
    updated = Signal()

    # Conversion from input type to a display name
    type_to_string = {
        InputType.JoystickAxis: "Axis",
        InputType.JoystickButton: "Button",
        InputType.JoystickHat: "Hat",
        InputType.Keyboard: "",
        InputType.KeyboardLatched: "(latched)",
        InputType.OpenSoundControl: "OSC",
        InputType.Midi: "Midi"
    }

    def __init__(self, parent=None, name = "Not set", custom_widget_handler = None, device_id : str = None):
        """Creates a new input item view instance

        :param parent: the parent of the widget
        :param name: name of the list
        :param custom_widget_handler: (list_view : InputItemListView, index : int, identifier : InputIdentifier, data, parent = None)
       
        """
        super().__init__(parent)

        # default visible supported input types
        self.shown_input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.OpenSoundControl,
            InputType.Midi
        ]
        self.name = name
        self._device_id = device_id
        self._current_index = -1 # nothing selected
        self.custom_widget_handler = custom_widget_handler
        self._deleted = False


        # Create required UI items
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.scroll_widget, self.scroll_layout = gremlin.ui.ui_common.getVContainer()
        self.scroll_widget.setContentsMargins(2,2,2,2)

        # Configure the scroll area
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)
        

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_area)


        el = gremlin.event_handler.EventListener()
        el.mapping_changed.connect(self._mapping_changed)
        el.sync_input.connect(self._sync_input)
        

    def _model_changed(self):
        # indicate selection is invalid
        self._current_index = -1
        self.redraw()

    def _sync_input(self, input_item):
        gremlin.util.InvokeUiMethod(self._sync_input_ui, input_item)

    def _sync_input_ui(self, input_item):
        if not Shiboken.isValid(self) or not Shiboken.isValid(self.scroll_layout):
            return
        
        if self.model.hasInputItem(input_item):
            index = self.model.indexOfInputItem(input_item)
            self.scrollToIndex(index)
            widgets = gremlin.util.get_layout_widgets(self.scroll_layout)
            # shenanigans to have the selected input visible in the scroll area of inputs
            # the size() on the widget returns the wrong size so each widget has an "actual size" function trapping the event 
            # so we get the correct height as rendered
            # then we compute the pixel offset and tell the scroll area to scroll to that pixel height

            if widgets and widgets[0].widget_height is not None:
                
                h = 0
                for i, widget in enumerate(widgets):
                    h += widget.widget_height
                    if i == index:
                        break
                self.scroll_area.ensureVisible(0,h)
                
            # target_widget = widgets[index]
            # self.scroll_area.ensureWidgetVisible(target_widget)
            
    def scrollToInput(self, input_item):
        self._sync_input(input_item)

    def scrollToWidget(self, widget):
        ''' scrolls the list view to the specified widget '''
        widgets = [w for w in gremlin.util.get_layout_widgets(self.scroll_layout)]
        if widget in widgets:
            self.scroll_area.ensureWidgetVisible(widget)


    @property
    def current_index(self):
        return self._current_index

    @property
    def current_device(self):
        ''' gets the device associated with this list view '''
        return self.model._device_data

    def _mapping_changed(self, item_data):
        gremlin.util.InvokeUiMethod(self._mapping_changed_ui, item_data) # to UI thread if needed

    def _mapping_changed_ui(self, item_data):
        ''' mapping changed '''
        for index in range(self.model.rows()):
            data = self.model.data(index)
            if data != item_data:
                continue
            self.redraw_index(index)

    


    def limit_input_types(self, types):
        """Limits the items shown to the given types.

        :param types list of input types to display
        """
        self.shown_input_types = types
        self.redraw()

    def removeRow(self, index):
        ''' removes the item at the given index '''
        if self.model.removeRow(index):
            # pick a new index if the item was selected
            rowcount = self.model.rows()
            if rowcount == 0:
                new_index = -1
            else:
                # reselect the item at the new index if possible
                new_index = index
                if new_index >= rowcount:
                    new_index = 0
            
            self.select_item(new_index)
        

    def getWidgets(self):
        ''' gets the list of widgets in the list view '''
        if not Shiboken.isValid(self.scroll_layout):
            return
        widgets = gremlin.util.get_layout_widgets(self.scroll_layout)
        return widgets
    
    def count(self) -> int:
        ''' return the number of widgets in the list '''
        widgets = self.getWidgets()
        return len(widgets)

    def getWidgetAt(self, index):
        ''' gets a specific widgets at the given index '''
        if not Shiboken.isValid(self.scroll_layout):
            return
        widgets = self.getWidgets()
        widget = [w for w in widgets if w.index == index]
        if widget:
            return widget[0]
        # if index < len(widgets):
        #     return widgets[index]
        return None
    
    def getWidgetForInputItem(self, input_item):
        ''' gets the corresponding widget for the given input item '''
        index = self.model.indexOfInputItem(input_item)
        if index != -1:
            widgets = [w for w in gremlin.util.get_layout_widgets(self.scroll_layout)]
            if index < len(widgets):
                return widgets[index]
        return None
    
    def scrollToIndex(self, index):
        if not Shiboken.isValid(self.scroll_layout):
            return
        widget = self.getWidgetAt(index)
        if index != -1:
            self._scroll_to_item(widget)

    def redraw(self, force : bool = False):
        gremlin.util.InvokeUiMethod(self._redraw_ui, force) # ensure on UI thread

    def _redraw_ui(self, force :bool = False):
        """Redraws the entire view.  must be on UI thread"""

        """Redraws the entire model.
        """
        if not Shiboken.isValid(self):
            return
        
        ts = gremlin.tabstate.TabState()
        data = ts.getData(self._device_id)
        if not force:
            if not data or not data.populateEnabled:
                # do not populate the list yet
                return 
        self.setUpdatesEnabled(False)
        try:

            verbose = gremlin.config.Configuration().verbose_mode_inputs
            #self._clear_widgets()

            if self.model is None:
                return
            

            with QtCore.QSignalBlocker(self):

                row_count = self.model.rows()
                device_name = self.current_device.name
                
                # clear the widgets
                ui_common.clear_layout(self.scroll_layout)


                for index in range(row_count):
                    data = self.model.data(index)
                    if not data:
                        continue


                    identifier = InputIdentifier(
                        data.input_type,
                        data.device_guid,
                        data.input_id,
                        data.device_type,
                        data.input_name,
                        is_axis = data.is_axis,
                        is_button = data.is_button
                    )

                    

                    if self.custom_widget_handler:
                        # custom widget creation handling
                        widget = self.custom_widget_handler(self, index, identifier, data, parent = self.scroll_layout)
                        assert widget is not None, "Custom widget handler didn't return a widget"
                    else:
                        widget = InputItemWidget(identifier)
                        if data.input_type == InputType.JoystickAxis:
                            prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
                            widget.setIcon(f"{prefix}joystick.png")
                        elif data.input_type == InputType.JoystickButton:
                            widget.setIcon("mdi.gesture-tap-button")
                        elif data.input_type == InputType.JoystickHat:
                            widget.setIcon("ei.fullscreen")
                        widget.create_action_icons(data)
                        

                    # set the description based on the mapping description
                    widget.setDescription(data.description)                        
                    # id update
                    widget._update_container_id()

                    self.scroll_layout.addWidget(widget)
                    

                    # hook the widget
                    widget.selected_changed.connect(self._widget_selection_change_cb)
                    widget.unselected.connect(self._widget_unselected_cb)
                    widget.index = index # assigned index

                    widget.edit.connect(self._create_edit_callback(index))
                    widget.edit_curve.connect(self._create_edit_curve_callback(index))
                    widget.delete_curve.connect(self._create_delete_curve_callback(index))
                    widget.closed.connect(self._create_closed_callback(index))

                                        

                    
                    if verbose:
                        syslog.info(f"LV: {device_name} [{index:02d}] type: {InputType.to_string(data.input_type)} name: {data.input_id}")

            self.scroll_layout.addStretch(10) # stretch at the bottom in case we have fewer items
                
        finally:
            self.setUpdatesEnabled(True)
            self.update()

        # reselect input
        input_widget = self.getWidgetAt(self.current_index)
        if input_widget:
            input_widget.setSelected(True, emit = False)

    def redraw_index(self, index : int):
        if not gremlin.shared_state.is_running:
            gremlin.util.InvokeUiMethod(self._redraw_index_ui, index) # ensure on UI thread


    def _redraw_index_ui(self, index : int):
        """Redraws the view entry at the given index.

        :param index the index of the entry to redraw
        """

        if not Shiboken.isValid(self):
            # garbage collected
            return

        if self.model is None or self._deleted:
            return


        # syslog.info(f"redraw_index: {index}")

        data = self.model.data(index)
        item = self.scroll_layout.itemAt(index)
        if item is not None:
            widget = item.widget()
            if widget is not None:
                if self.custom_widget_handler:
                    widget.update_display()
                else:
                    widget.create_action_icons(data)
                    widget.setDescription(data.description)
                    widget.setInputDescription(data.display_name)
            
                        
    @QtCore.Slot(object)
    def _widget_selection_change_cb(self, widget):
        ''' called when a widget selection changes '''
        self.select_item(widget.index, user_selected=True, force_update=False)


    @QtCore.Slot(object)
    def _widget_unselected_cb(self, widget):
        self.unselect_item(widget.index)
        

    def itemAt(self, index : int):
        ''' gets the input widget as the given index'''
        item =  self.scroll_layout.itemAt(index)
        if item:
            return item.widget()
        return None


   

    def _create_edit_callback(self, index : int):
        """Creates a callback handling the edit action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """
        return lambda x: self._edit_item_cb(index)


    def _create_edit_curve_callback(self, index : int):
        return lambda : self._edit_curve_item_cb(index)
    
    def _create_delete_curve_callback(self, index : int):
        return lambda : self._delete_curve_item_cb(index)
    

    def _create_closed_callback(self, index : int):
        """Creates a callback handling the close action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """

        # get the index for this widget
        return lambda x: self._close_item_cb(index)



    def select_input(self, input_type, identifier, emit = True, force_update = False):
        ''' selects an entry based on input type and ID'''
        verbose = gremlin.config.Configuration().verbose_mode_inputs
        if verbose: syslog.info(f"InputItem: select type: {input_type.name} input: {identifier}")
        if self._deleted:
            if verbose: syslog.info("\tdeleted")
            return False
        
        for index in range(self.model.rows()):
            data = self.model.data(index)
            if input_type is not None and data.input_type != input_type:
                continue
            if hasattr(data.input_id, "message_key"):
                if data.input_id.message_key == identifier.message_key:
                    self.select_item(index, emit, force_update)    
                    return True
            
            elif data.input_id == identifier:
                self.select_item(index, emit, force_update)
                
                return True

        return False
            
        

    def selected_item(self):
        ''' returns the currently selected input in the list view '''

        index = self.current_index
        if index == -1:
            return None

        return self.model.data(index)

    def _close_item_cb(self, index):
        ''' remove a particular input '''
        from PySide6.QtCore import QMetaMethod

        widget = self.itemAt(index)
        if isSignalConnected(widget,"closed(InputIdentifier)"):
            widget.closed.emit(self, index)
            return

        # select the widget if it's not selected
        data = self.model.data(index)
        if data and (data.containers or data.input_type == InputType.KeyboardLatched):
            # prompt confirm
            result = gremlin.ui.ui_common.ConfirmBox("Delete confirmation","This will delete associated actions for this entry.\nAre you sure?")
            if result:
                self._confirmed_close(index)
        else:
            # no need to confirm
            self._confirmed_close(index)

    def _confirmed_close(self, index):
        self.removeRow(index)
        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)
        self.item_closed.emit(self, index, self.model.data(index)) # widget, index, data
        self.redraw()
        # select prior item
        if index > 0:
            index-=1
            data = self.model.data(index)
            if data:
                self.select_item(index)

    def _edit_item_cb(self, index : int):
        ''' emits the edit event along with the item being edited '''
        self.item_edit.emit(self, index, self.model.data(index).input_id) # widget, index, data

    def _edit_curve_item_cb(self, index : int):
        input_item = self.model.data(index)
        self.item_edit_curve.emit(self, index, input_item)
        el = gremlin.event_handler.EventListener()
        el.curve_added.emit(input_item)

    def _delete_curve_item_cb(self, index : int):
        input_item = self.model.data(index)
        self.item_delete_curve.emit(self, index, self.model.data(index))
        el = gremlin.event_handler.EventListener()
        el.curve_deleted.emit(input_item)

    def _update_value_changed(self, index : int, value : float):
        self.item_input_value_changed.emit(self, index, self.model.data(index), value)



    def update_item(self, index):
        ''' update the widget with new data '''
        widget = self.itemAt(index)
        if not widget:
            self.redraw()
            self.select_item(index)
            widget = self.itemAt(index)
        if widget:
            widget.update_display()
        

    def unselect_item(self, index):
        ''' unselects an item '''
        pass


    def select_item(self, index, emit=True, force_update = False, user_selected = False):
        """Handles selecting a specific item.  this is called whenever an input item is selected

        :param index the index of the item being selected
        :param emit_signal flag indicating whether or not a signal is to be
            emitted when the item is being selected
        """


        verbose = gremlin.config.Configuration().verbose_mode_inputs
        if verbose: syslog.info(f"InputItem: select input: {index}")
        if not Shiboken.isValid(self.scroll_area):
            if verbose: syslog.warning("\tshiboken invalid")
            return

        
        if index == -1:
            # always reset things if the index is the clear value of -1
            force_update = True

        if not force_update and self._current_index == index:
            if verbose: syslog.warning("\tnothing to do")
            return # nothing to do if the current index is the same as the new index
        
        # If the index is actually an event we have to correctly translate the
        # event into an index, taking the possible non-contiguous nature of
        # axes into account
        if isinstance(index, gremlin.event_handler.Event):
            event = index
            if event.action_id:
                index = self.mode.action_id_to_index(event.action_id)
            else:
                index = self.model.event_to_index(event)


        
        if index == -1:
            for item in self.scroll_layout.children():
                widget = item.widget()
                if widget:
                    if widget.selected:
                        index = widget.index
                        break

        
        last_widget = self.itemAt(self._current_index)
        if last_widget:
            with (QtCore.QSignalBlocker(last_widget)):
                last_widget.setSelected(False, False)
                #last_widget.selected = False

                

        self._current_index = index


        widgets = [w for w in gremlin.util.get_layout_widgets(self.scroll_layout)]
        widget = self.itemAt(index)
        if widgets:
            if widget in widgets:
                widgets.remove(widget)
            for w in widgets:
                w.setSelected(False, emit = False)

        if widget:
            # select it
            with (QtCore.QSignalBlocker(widget)):
                widget.setSelected(True, emit = False)
                if verbose: 
                    data = self.model.data(index)
                    syslog.info(f"\tselected: {data.debug_display}")

            # if the list is long - bring the selected widget into view
            #gremlin.util.singleShot(lambda: self._scroll_to_item(widget))

        if emit and index != -1:
            self.item_selected.emit(index, force_update) # load the mapped content for the given index

        # return the currently selected widget
        return widget
    
    def clearSelection(self, emit = True):
        widgets = [w for w in gremlin.util.get_layout_widgets(self.scroll_layout)]
        for w in widgets:
            w.setSelected(False, emit = emit)

    
    def _create_scroll_callback(self, widget):
        return lambda : self._scroll_to_item(widget)
    
    def ensureVisible(self, widget):
        gremlin.util.singleShot(self._create_scroll_callback(widget))

    def _scroll_to_item(self, widget):
        gremlin.util.InvokeUiMethod(self._scroll_to_item_ui, widget)

    def _scroll_to_item_ui(self, widget):
        # runs on UI thread
        QtWidgets.QApplication.processEvents()
        if Shiboken.isValid(self.scroll_area) and Shiboken.isValid(widget):
            self.scroll_area.ensureWidgetVisible(widget)


class ActionSetModel(ui_common.AbstractModel):

    """Model storing a set of actions."""

    def __init__(self, action_set=[]):
        super().__init__()
        assert isinstance(action_set, list),"Invalid action set provided"
        self._action_set = action_set

    def rows(self):
        return len(self._action_set)

    def data(self, index):
        return self._action_set[index]

    def add_action(self, action):
        self._action_set.append(action)
        
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = action.hardware_device_guid
        event.device_input_id = action.hardware_input_id
        event.device_input_type = action.hardware_input_type
        event.source = action
        
        el.icon_changed.emit(event)

        container : gremlin.base_profile.AbstractContainer = action.get_container()
        container.mapping_changed() # tell the UI about the change

        # blows up in QT 6.11
        # try:
        #     self.data_changed.emit()
        # except:
        #     pass # ignore signal issues
        


    def remove_action(self, action):
        ''' runs when an action should be deleted '''
        import gremlin.util
        try:
            gremlin.util.pushCursor()
            if action in self._action_set:
                input_item = action.get_input_item()
                container : gremlin.base_profile.AbstractContainer = action.get_container()
                del self._action_set[self._action_set.index(action)]

                # run action delete if the action supports it
                if hasattr(action,"actionDeleted"):
                    action.actionDeleted()

                el = gremlin.event_handler.EventListener()
                el.action_delete.emit(input_item, container, action) # tell the UI the action is being deleted
                if hasattr(action,"_cleanup"):
                    action._cleanup()

                event = gremlin.event_handler.DeviceChangeEvent()
                event.source = input_item
                event.device_input_id = input_item
                el.icon_changed.emit(event)

                container.mapping_changed() # tell the UI about the change
                
                
            # try:
            #     self.data_changed.emit()
            # except:
            #     pass
        finally:
            gremlin.util.popCursor()
        


@gremlin.singleton_decorator.SingletonDecorator
class ActionSetViewCache():
    def __init__(self):
        self.cache = {} # map of action ID to widget

    def registerWidget(self, key, widget):
        self.cache[key] = widget

    def unregisterWidget(self, key, widget):
        if key in self.cache:
            del self.cache[key]

    def getWidget(self, key):
        if key in self.cache:
            return self.cache[key]
        return None

    def clearWidget(self, widget):
        for key in self.cache:
            if widget == self.cache[key]:
                del self.cache[key]
                

_action_set_view_cache = ActionSetViewCache()

class ActionSetView(ui_common.AbstractView):

    """View displaying the action set content."""

    class Interactions(enum.Enum):
        """Enumeration of possible interactions."""
        Up = 1
        Down = 2
        Delete = 3
        Edit = 4
        Add = 5
        Count = 6
        Copy = 7 # copy to clipboard

    # Signal emitted when an interaction is triggered on an action
    interacted = Signal(Interactions)

    def __init__(
            self,
            profile_data,
            label = None,
            view_type=ui_common.ContainerViewTypes.Action,
            icon = None,
            icon_size = 24,
            parent=None
    ):

        super().__init__(parent)

        self._redraw_lock = False

        self.has_edit_controls = False # assume no edit controls
        self.view_type = view_type
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine(color = gremlin.ui.ui_common.Color.grayColor()))

        self.profile_data = profile_data
        self.allowed_interactions = profile_data.interaction_types
        self.label = label
        self._selected = False # true if the object is selected
        title = None

        if self.label:
            if icon:
                title = gremlin.ui.ui_common.QIconLabel(icon, icon_size = icon_size, text = f"{self.label} action:")
            else:
                title = QtWidgets.QLabel(f"{self.label} action:")
        elif icon:
            title = gremlin.ui.ui_common.QIconLabel(icon, icon_size = icon_size)

        if title:
            self.main_layout.addWidget(title)


        left_panel, left_layout = gremlin.ui.ui_common.getVContainer()
        right_panel, right_layout = gremlin.ui.ui_common.getVContainer()
        right_panel.setMaximumWidth(0) # use no space by default unless needed

        action_container, action_layout = gremlin.ui.ui_common.getGridContainer()
        action_layout.addWidget(left_panel, 0, 0)
        action_layout.addWidget(right_panel, 0, 1)

        add_action_container, add_action_layout = gremlin.ui.ui_common.getVContainer()
        
        widgets = [action_container, add_action_container]
        content_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)

        #self.collapsible_container.setContent(content_widget)
        self.main_layout.addWidget(content_widget)

        
        self.setObjectName(f"ActionSetView: {'n/a' if label is None else label}")

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info(f"ActionSetView: create: {self.objectName()}")

       
        # Create group box contents
        self.action_widget, self.action_layout = gremlin.ui.ui_common.getVContainer()
        

        # Only show edit controls in the basic tab
        if self.view_type == ui_common.ContainerViewTypes.Action:
            self._create_edit_controls()
            left_layout.addWidget(self.action_widget)
            if self.has_edit_controls:
                right_layout.addWidget(self.controls_widget)
                right_panel.setMaximumWidth(34)
                right_panel.setMinimumWidth(34)
        else:
            left_layout.addWidget(self.action_widget)
        
        # Only permit adding actions from the basic tab and if the tab is
        # not associated with a vJoy device
        
        if self.view_type == ui_common.ContainerViewTypes.Action and \
                self.profile_data.get_device_type() != DeviceType.VJoy:
            input_type = None
            if hasattr(profile_data,"override_input_type"):
                # override specified
                input_type = profile_data.override_input_type
            else:
                input_type = profile_data.parent.getInputType()
                
            if input_type is None:
                input_type = profile_data.input_item.get_input_type()
            
            self.action_selector = gremlin.ui.ui_common.ActionSelector(
                input_type,
                profile_data.input_item
            )
            self.action_selector.inputItem = profile_data.input_item
            self.action_selector.action_added.connect(self._add_action)
            self.action_selector.action_paste.connect(self._paste_action)
            widget = gremlin.ui.ui_common.getHContainer(self.action_selector, widget_only = True)
            add_action_layout.addWidget(widget)
            

        # self.main_layout.addWidget(group_widget)
        self.left_layout = left_layout
        self.right_layout = right_layout

        self._widgets = []




    def setSelected(self, value:bool):
        ''' sets selected state'''
        if value and not self._selected:
            self._selected = True
            background_color = gremlin.ui.ui_common.Color.selectedDockTabBackgroundColor()
            self.setStyleSheet = f"background: {background_color};"
        elif not value and not self._selected:
            self._selected = False
            self.setStyleSheet("")

    def redraw(self):
        gremlin.util.InvokeUiMethod(self._redraw_ui) # ensure on UI thread

    def _redraw_ui(self):
        """Redraws the entire view.  must be on UI thread"""

        if not Shiboken.isValid(self):
            return
        
        gremlin.util.assert_ui_thread()
        
        if self._redraw_lock:
            return
        
        try:
            self._redraw_lock = True
        
            cache = ActionSetViewCache()

            
            verbose_ui = gremlin.config.Configuration().verbose_mode_ui
            if verbose_ui: object_name = self.objectName()
            if verbose_ui: syslog.info(f"ActionSet: redraw start: {object_name}")

            widgets = gremlin.util.get_layout_widgets(self.left_layout)
            if widgets:
                if verbose_ui: syslog.info(f"ActionSet: redraw cleanup start: {object_name}")
                for widget in widgets:
                    cache.clearWidget(widget)
                    gremlin.util.delete_widget(widget)


                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
                self._widgets.clear()
                

                if verbose_ui: syslog.info(f"ActionSet: redraw cleanup complete: {object_name}")


            self.left_layout.removeWidget(self.action_widget)
            self.action_widget.hide()
            self.action_widget.deleteLater()
            
            
            self.action_widget, self.action_layout = gremlin.ui.ui_common.getVContainer()
            self.left_layout.addWidget(self.action_widget)

            
            if self.model is None:
                return
            
            with QtCore.QSignalBlocker(self.model): # .data_changed.blocked():

                clipboard = Clipboard()
                clipboard.disable()
                if self.view_type == ui_common.ContainerViewTypes.Action:
                    for index in range(self.model.rows()):
                        data = self.model.data(index)
                        if verbose_ui: syslog.info(f"ActionSet: redraw action widget start: {object_name}")
                        widget = data.widget(data)
                        cache.registerWidget(data.id, widget)
                        widget.action_modified.connect(self.model.data_changed.emit)
                        wrapped_widget = BasicActionWrapper(widget)
                        wrapped_widget.closed.connect(self._create_closed_cb(widget))
                        self.action_layout.addWidget(wrapped_widget)
                        self._widgets.append(wrapped_widget)
                        if verbose_ui: syslog.info(f"ActionSet: redraw action widget completed: {object_name}")
                        
                elif self.view_type == ui_common.ContainerViewTypes.Conditions:
                    for index in range(self.model.rows()):
                        is_cached = True
                        data = self.model.data(index)
                        if verbose_ui: syslog.info(f"ActionSet: redraw condition widget start: {object_name}")
                        widget = cache.getWidget(data.id)
                        if not widget:
                            is_cached = False
                            widget = data.widget(data)
                        #widget.action_modified.connect(self.model.data_changed.emit)
                        wrapped_widget = ConditionActionWrapper(widget)
                        if not is_cached and hasattr(widget,"_cleanup_ui"):
                            widget._cleanup_ui()
                            widget.deleteLater()
                        if verbose_ui: syslog.info(f"ActionSet: redraw condition widget completed: {object_name}")
                        self.action_layout.addWidget(wrapped_widget)
                        self._widgets.append(wrapped_widget)


                clipboard.enable()

            if verbose_ui: syslog.info(f"ActionSet: redraw complete: {object_name}")
        # except:
        #     pass
        finally:
            self._redraw_lock = False

    def _add_action(self, action_name):
        import gremlin.plugin_manager
        import gremlin.base_profile
        import gremlin.ui.ui_common

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()

            action = plugin_manager.get_class(action_name)(self.profile_data)
            if action.singleton:
                input_item : gremlin.base_profile.InputItem = self.profile_data.input_item
                if input_item.is_action:
                    gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add [{action_name}].  The action cannot be added to a sub-container.")    
                    return
                if input_item.hasAction(action_name):
                    gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add: [{action_name}]. The action can only appear once per input.")
                    return
                    

            self.model.add_action(action)
  
                
            

        finally:
            gremlin.util.popCursor()

    def _paste_action(self, action, container):
        ''' handles action paste operation '''

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            if isinstance(action, ObjectEncoder):
                oc = action
                if oc.encoder_type == EncoderType.Action:
                    xml = oc.data
                    node = lxml.etree.fromstring(xml)
                    action_tag = node.tag
                    action_tag_map = plugin_manager.tag_map
                    new_action = action_tag_map[action_tag](self.profile_data)
                    new_action.from_xml(node)
                    new_action.setId(get_guid())
                    self.model.add_action(new_action)
            else:
                action_item = plugin_manager.duplicate(action,self.profile_data)
                self.model.add_action(action_item)
        finally:
            gremlin.util.popCursor()


    def _create_closed_cb(self, widget):
        """Create callbacks to remove individual containers from the model.

        :param widget the container widget to be removed
        :return callback function to remove the provided widget from the
            model
        """
        #return lambda: self.model.remove_action(widget.action_data)
        return lambda: self._remove_model_action_data(widget.action_data)

    def _remove_model_action_data(self, action_data):
        try:
            self.model.remove_action(action_data)
        except:
            pass



    def _create_edit_controls(self):
        """Creates interaction controls based on the allowed interactions.

        :param allowed_interactions list of allowed interactions
        """
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.Red)
        self.has_edit_controls = False

        self.controls_widget = QtWidgets.QWidget()
        self.controls_layout = QtWidgets.QVBoxLayout(self.controls_widget)
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        if ActionSetView.Interactions.Up in self.allowed_interactions:
            self.control_move_up = QtWidgets.QPushButton(
                load_icon(f"gfx/{prefix}button_up.png"), ""
            )
            self.control_move_up.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Up)
            )
            self.controls_layout.addWidget(self.control_move_up)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Down in self.allowed_interactions:
            self.control_move_down = QtWidgets.QPushButton(
                load_icon(f"gfx/{prefix}button_down.png"), ""
            )
            self.control_move_down.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Down)
            )
            self.controls_layout.addWidget(self.control_move_down)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Delete in self.allowed_interactions:

            self.control_delete = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.interacted.emit(ActionSetView.Interactions.Delete))
            # self.control_delete = QtWidgets.QPushButton(
            #     load_icon(f"gfx/{prefix}button_delete.png"), ""
            # )
            # # syslog.info(f"action: delete allowed")
            # self.control_delete.clicked.connect(
            #     lambda: self.interacted.emit(ActionSetView.Interactions.Delete)
            # )
            self.controls_layout.addWidget(self.control_delete)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Edit in self.allowed_interactions:
            self.control_edit = gremlin.ui.ui_common.Buttons.getEditWidget(callback = lambda: self.interacted.emit(ActionSetView.Interactions.Edit))
            # self.control_edit = QtWidgets.QPushButton(
            #     load_icon(f"gfx/{prefix}button_edit.png"), ""
            # )
            # self.control_edit.clicked.connect(
            #     lambda: self.interacted.emit(ActionSetView.Interactions.Edit)
            # )
            self.controls_layout.addWidget(self.control_edit)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Copy in self.allowed_interactions:
            self.control_edit = gremlin.ui.ui_common.Buttons.getCopyWidget(callback = lambda: self.interacted.emit(ActionSetView.Interactions.Copy))
            self.controls_layout.addWidget(self.control_edit)
            self.has_edit_controls = True


        self.controls_layout.addStretch(1)


class InputItemWidget(QBoxFrame):
    """ holds the input widget (left side of the interface) for available inputs that get mapped.
    
    this widget is used to represent an input mapping.  There are multiple variants of this for joysticks, vjoy (as input), keyboard, OSC and MIDI.

    Some of those use custom widget rendering based on their types.

    This event can be used to display input item specific customization
    widgets. This button also shows icons of the associated actions.
    """

    # Signal emitted whenever this button is pressed
    selected_changed = Signal(InputIdentifier)

    # fires when unselected
    unselected = Signal(InputIdentifier) 

    # signal when button's close button is pressed
    closed =  Signal(InputIdentifier)

    # signal when button's edit button is pressed
    edit =  Signal(InputIdentifier)

    # signal when the edit curve button is pressed
    edit_curve = Signal(InputIdentifier)

    # signal when the clear curve button is pressed
    delete_curve = Signal(InputIdentifier)

    # signal input value changed
    input_value_changed = Signal(InputIdentifier, float)

    def __init__(self, identifier, parent=None,
                  populate_ui_callback = None,
                  populate_name_callback = None, 
                  update_callback = None, 
                  confirm_delete_callback = None, 
                  config_external = False, data = None):
        ''' builds the widget '''

        super().__init__(parent)

      
        self.parent = parent
        self.widget_width = None # actual width in pixels
        self.widget_height = None # actual height in pixels

        self._ui_loaded = False
        self.data = data
        self._selected = False
        self._confirm_delete_callback = confirm_delete_callback
        self.setContentsMargins(0,0,0,0)
        
        self._debug_layout = False

        self.identifier = identifier
        self._input_id = identifier.input_id
        self._device_guid = identifier.device_guid
        self._input_type = identifier.input_type

        if hasattr(self._input_id, "input_mode_changed"):
            # hook identifiers that can change mode from axis to button or vice versa so the repeaters match - example OSC or MIDI
            self._input_id.input_mode_changed.connect(self._update_repeater)
        
        self._multi_row = populate_ui_callback is not None
        self.populate_ui = populate_ui_callback # get custom content callback
        self.populate_name = populate_name_callback # get name callback
        
        self._config_external = config_external # true if the widget is a custom widget configured externally
        self._update_callback = update_callback # callback to use when a specific widget index must be updated


        self._data = data # InputItem
        self._title_icons = [] # title bar icons

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.main_layout.setSpacing(0)
        self.setObjectName("main_layout")

        # main container
        self._container_widget, self._container_layout = gremlin.ui.ui_common.getVContainer()
        self._container_widget.setContentsMargins(4,0,4,0)
        self._container_layout.setSpacing(0)
        self.main_layout.addWidget(self._container_widget)

        # lock icon
        icon_lock = gremlin.ui.ui_common.Icons.lockIcon()
        icon_unlock = gremlin.ui.ui_common.Icons.unlockIcon()
        self._lock_widget = gremlin.ui.ui_common.QIconCheckbox(icon_lock, icon_unlock, size = 16)
        



        if isinstance(data, gremlin.base_profile.InputItem):
            input_item = data
        else:
            input_item = identifier.getInputItem()
        if input_item:
            input_item.lockedChanged.connect(self._handle_input_item_lock_changed)
        else:
            pass

        self._input_item = input_item

        if input_item:
            self._lock_widget.setChecked(input_item.locked)
        self._lock_widget.clicked.connect(self._handle_lock_changed)
        


        # top row
        # title bar
        self._title_bar_widget, self._title_bar_layout = gremlin.ui.ui_common.getVContainer()
        self._title_container_widget, self._title_container_layout = gremlin.ui.ui_common.getGridContainer()
        self._title_bar_widget.setContentsMargins(4,2,4,2) # title bar
        self._title_bar_layout.addWidget(self._title_container_widget)
        self._title_bar_widget.setObjectName("title_bar")
        

        
        # title bar left side

        self._title_text_widget = gremlin.ui.ui_common.QIconLabel()
        self._title_text_widget.setContentsMargins(0,0,0,0)
        self._title_text_widget.setText("Input not configured")
        self._title_text_widget.setObjectName("title")

        
        self._title_text_container_widget = gremlin.ui.ui_common.getHContainer([
                                                                            self._lock_widget,
                                                                            self._title_text_widget    
                                                                        ], widget_only = True)


        # title bar right side - holds the icons
        self._title_icon_widget, self._title_icon_layout = gremlin.ui.ui_common.getHContainer()
    
        
        self._title_container_layout.addWidget(self._title_text_container_widget, 0, 0)
        self._title_container_layout.addWidget(QtWidgets.QWidget(), 0, 1)
        self._title_container_layout.addWidget(self._title_icon_widget, 0, 2, alignment = QtCore.Qt.AlignmentFlag.AlignRight)
        self._title_container_layout.setColumnStretch(1,1)

        
        self._container_layout.addWidget(self._title_bar_widget)
        

        # icon setup
        size = self._getIconSize() # icon size
        active_color = gremlin.ui.ui_common.Color.activeColor()
        normal_color = gremlin.ui.ui_common.Color.normalColor()
        self._curve_icon_inactive = load_icon("mdi.chart-bell-curve",qta_color=normal_color)
        self._curve_icon_active = load_icon("mdi.chart-bell-curve",qta_color=active_color)
        self._input_icon_inactive = load_icon("fa6s.power-off",qta_color=normal_color)
        self._input_icon_active = load_icon("fa6s.power-off",qta_color=active_color)
        self._calibration_icon_active = load_icon("mdi.arrow-expand-horizontal",qta_color=active_color)
        self._calibration_icon_inactive = load_icon("mdi.arrow-expand-horizontal",qta_color=normal_color)


        # action buttons
        self._edit_button_widget = None

        # input button on/off - added only via enable_edit()
        self._input_button_widget = None

        # close widget - added only via enable_close()
        self._close_button_widget = None

        # curve toolbar
        self.is_axis = self.data.is_axis if self.data else False

        # calibration button
        self._calibration_button_widget = None
        
        # input curve button
        self._curve_button_widget = None
        
        # clear input curve button
        self.clear_curve_widget = None

        if self.is_axis:

            # curve container (axis only)
            self._curve_container_widget, self._curve_container_layout = gremlin.ui.ui_common.getHContainer()
            self._title_icon_layout.addWidget(self._curve_container_widget)

            self._curve_container_layout.addStretch()

            self._curve_button_widget = QtWidgets.QPushButton() 
            self._curve_button_widget.setIcon(self._curve_icon_active)
            self._curve_button_widget.setToolTip("Input Curve")
            self._curve_button_widget.setFixedSize(size,size)
            self._curve_button_widget.clicked.connect(self._curve_button_cb)
            self._curve_container_layout.addWidget(self._curve_button_widget)

            self._calibration_button_widget = QtWidgets.QPushButton() 
            self._calibration_button_widget.setIcon(self._calibration_icon_active)
            self._calibration_button_widget.setToolTip("Device calibration options")
            self._calibration_button_widget.setFixedSize(size,size)
            self._calibration_button_widget.clicked.connect(self._calibration_button_cb)
            self._curve_container_layout.addWidget(self._calibration_button_widget)

            self.clear_curve_widget = QtWidgets.QPushButton()
            self.clear_curve_widget.setToolTip("Clear Curve")
            self.clear_curve_widget.setIcon(load_icon("mdi.delete"))
            self.clear_curve_widget.setFixedSize(size,size)
            self.clear_curve_widget.clicked.connect(self._clear_curve_cb)            
            self._curve_container_layout.addWidget(self.clear_curve_widget)


        # axis repeater object
        self.axis_widget = None

        # button repeater object
        self.button_widget = None

        hide_widgets = []

        
        # description row
        self._description_widget = gremlin.ui.ui_common.QIconLabel()
        self._description_widget.setStyleSheet("font-style: italic;")
        self._description_widget.setToolTip("Mapping Description")
        self._description_container_widget, self._description_container_layout = gremlin.ui.ui_common.getHContainer(self._description_widget)
        self._description_icon = None
        hide_widgets.append(self._description_container_widget)
        
        if self._debug_layout: self._description_container_widget.setStyleSheet("background: blue;")
        self._container_layout.addWidget(self._description_container_widget)


        # container icons
        self._action_container_widget, self._action_container_layout = gremlin.ui.ui_common.getVContainer()
        self._action_container_widget.setObjectName("action_container")
        if self._debug_layout: self._action_container_widget.setStyleSheet("#action_container { background: yellow; }")
        self._action_icons_container_widget, self._action_icons_container_layout = gremlin.ui.ui_common.getGridContainer()
        self._action_container_layout.addWidget(self._action_icons_container_widget)
        hide_widgets.append(self._action_container_widget)

        
        self._container_layout.addWidget(self._action_container_widget)

        # input description row
        self._input_description_widget = gremlin.ui.ui_common.QIconLabel()
        self._input_description_container_widget, self._input_description_container_layout = gremlin.ui.ui_common.getHContainer(self._input_description_widget)
        self._input_description_icon = None
        hide_widgets.append(self._input_description_container_widget)

        if self._debug_layout: self._description_container_widget.setStyleSheet("background: brown;")
        self._container_layout.addWidget(self._input_description_container_widget)

        # custom widget row (used by some inputs to display custom UI elements like keyboard )
        self._custom_container_widget, self._custom_container_layout = gremlin.ui.ui_common.getVContainer()
        self._custom_container_layout.setContentsMargins(4,0,0,0)
        hide_widgets.append(self._custom_container_widget)
        
        if self._debug_layout: self._custom_container_widget.setStyleSheet("background: cyan; ")
        self._container_layout.addWidget(self._custom_container_widget)
  

        # repeater
        self._repeater_container_widget, self._repeater_container_layout = gremlin.ui.ui_common.getVContainer()
        self._repeater_container_widget.setContentsMargins(0,0,0,2)

        if self._debug_layout: self._repeater_container_widget.setStyleSheet("background: red;")
        self._container_layout.addWidget(self._repeater_container_widget)
        

        # comment row
        self._comment_container_widget, self._comment_container_layout = gremlin.ui.ui_common.getHContainer()
        hide_widgets.append(self._comment_container_widget)
        
        if self._debug_layout: self._comment_container_widget.setStyleSheet("background: orange;")
        self._container_layout.addWidget(self._comment_container_widget)

        # custom content row
        self._custom_container_widget, self._custom_container_layout = gremlin.ui.ui_common.getVContainer()
        self._custom_container_widget.setContentsMargins(0,0,0,4) # give room below
        hide_widgets.append(self._custom_container_widget)
        
   
        if self._debug_layout:self._custom_container_widget.setStyleSheet("background: cyan;")
        self._container_layout.addWidget(self._custom_container_widget)

        # status row
        self._status_container_widget, self._status_container_layout = gremlin.ui.ui_common.getVContainer()
        hide_widgets.append(self._status_container_widget)
        if self._debug_layout:self._status_container_widget.setStyleSheet("background: gray;")
        

        self._status_widget = None
        self._container_layout.addWidget(self._status_container_widget)
        
        # container ID row
        self._container_id_widget, self._container_id_layout = gremlin.ui.ui_common.getVContainer()
        if self._debug_layout:self._container_id_widget.setStyleSheet("background: magenta;")
        hide_widgets.append(self._container_id_widget)
        
        
        self._container_layout.addWidget(self._container_id_widget)
        spacer = QtWidgets.QWidget()
        spacer.setFixedHeight(4)
        self._container_layout.addWidget(spacer)
        
        #self._container_layout.addStretch(2)
    

        self._ui_loaded = True

        self._setWidgetHeight(hide_widgets, 0)

        # event filter
        self.installEventFilter(self)

        # hook mapping changed event
        el = gremlin.event_handler.EventListener()
        el.mapping_changed.connect(self._mapping_changed_cb)
        el.curve_deleted.connect(self._curve_changed_cb)
        el.curve_added.connect(self._curve_changed_cb)
        el.calibration_added.connect(self._calibration_changed_cb)
        el.calibration_deleted.connect(self._calibration_changed_cb)
        el.icon_changed.connect(self._icon_changed_cb)
        el.update_input_icons.connect(self._update_axis_icons)
        el.profile_loaded.connect(self._update_axis_icons) # update icons after profile load as calibration data load order is not guaranteed

        # update mapping action icons
        self._update_repeater() # create the correct repeater widget
        self._update_selected_ui()
        self._update_display_ui()

        if self.is_axis:
            # update axis input icons
            self._update_axis_icons_ui()

        self.ensureStyle()

    
    def resizeEvent(self, event):
        size = self.size()
        self.widget_width = size.width()
        self.widget_height = size.height()
        return super().resizeEvent(event)

    @property
    def input_item(self):
        return self._input_item

    def eventFilter(self, widget, event):
        # trap mouse click
        if not self._selected:
            t = event.type()
            if t == QtCore.QEvent.Type.MouseButtonPress:
                button = event.buttons()
                if button == QtCore.Qt.LeftButton:
                    self.selected = True

        return super().eventFilter(widget, event)
        
    def getLayout(self):
        return self._custom_container_layout
    
    def addWidget(self, widget):
        ''' adds a widget to the container '''
        self._custom_container_layout.addWidget(widget)
        h = sum(w.height() for w in gremlin.util.get_layout_widgets(self._custom_container_layout))
        self._custom_container_widget.setMaximumHeight(h + 5)

    def clearWidgets(self):
        ''' clears the custom container layout and hides it '''
        gremlin.util.clear_layout(self._custom_container_layout)
        self._custom_container_widget.setMaximumHeight(0)

    
    def _handle_input_item_lock_changed(self, input_item):
        if input_item == self._input_item:
            gremlin.util.InvokeUiMethod(self._handle_input_item_lock_changed_ui, input_item)

    def _handle_input_item_lock_changed_ui(self, input_item):
        
        if Shiboken.isValid(self._lock_widget):
            with QtCore.QSignalBlocker(self._lock_widget):
                self._lock_widget.setChecked(input_item.locked)
        
        # enable the delete button if not locked
        if self._close_button_widget and Shiboken.isValid(self._close_button_widget):
            self._close_button_widget.setEnabled(not input_item.locked)
        
    @QtCore.Slot(bool)
    def _handle_lock_changed(self, checked : bool):
        self.data.locked = checked
        if self.data.locked != checked:
            # input cannot be locked/unlocked - undo the check
            with QtCore.QSignalBlocker(self._lock_widget):
                self._lock_widget.setChecked(not checked)





    def _update_title(self):
        ''' updates the title bar stylesheet based on the selection state '''
        css = gremlin.ui.ui_common.Color.cssInputHeader() if self._selected else gremlin.ui.ui_common.Color.cssUnselectedInputHeader()
        self._title_container_widget.setStyleSheet(css)

    def _update_container_id(self):
        gremlin.util.InvokeUiMethod(self._update_container_id_ui) # on UI thread

    def _update_container_id_ui(self):
        ''' updates container ID display for associated containers with this input '''
        if not Shiboken.isValid(self._container_id_widget):
            return
        config = gremlin.config.Configuration()
        gremlin.util.clear_layout(self._container_id_layout)
        if config.show_container_id:
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            grids = []
            rh = self._getRowHeight()
            

            if self.data:
                # input id
                line_edit = gremlin.ui.ui_common.QDataLineEdit()
                line_edit.setMinimumWidth(width)
                line_edit.setText(gremlin.util.idString(self.data.id))
                line_edit.setReadOnly(True)
                widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Input ID:", widget_only = True)
                self._container_id_layout.addWidget(widget)
                grids.append(widget)

                container_count = len(self.data.containers)
                if container_count:
                    for index, container in enumerate(self.data.containers):
                        line_edit = gremlin.ui.ui_common.QDataLineEdit()
                        line_edit.setMinimumWidth(width)
                        line_edit.setText(container.id)
                        line_edit.setReadOnly(True)
                        widget = gremlin.ui.ui_common.getGridContainer(line_edit, f"[{index}] {container.name}", widget_only = True)
                        self._container_id_layout.addWidget(widget)
                        grids.append(widget)
                else:
                    # no container
                    line_edit = gremlin.ui.ui_common.QDataLineEdit()
                    line_edit.setMinimumWidth(width)
                    line_edit.setText("No container found")
                    line_edit.setReadOnly(True)
                    widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Mapping:", widget_only = True)
                    self._container_id_layout.addWidget(widget)
                    grids.append(widget)
                    
            
            h = rh * (len(grids) + 1)
            self._setWidgetHeight(self._container_id_widget, h)
            gremlin.ui.ui_common.synchronize_grids(grids)

            # selected state
            self._container_id_layout.addWidget(QtWidgets.QLabel(f"Selected: {self.selected}"))
        else:
            self._setWidgetHeight(self._container_id_widget, 0)


    def _cleanup_ui(self):
        ''' called when widget is removed '''
        el = gremlin.event_handler.EventListener()
        el.action_created.disconnect(self._action_changed_cb)
        el.action_delete.disconnect(self._action_deleted_cb)
        el.icon_changed.disconnect(self._icon_changed_cb)
        el.mapping_changed.disconnect(self._mapping_changed_cb)
        el.update_input_icons.disconnect(self._update_axis_icons)
        el.input_enabled_changed.disconnect(self._update_enabled_state)
        el.profile_loaded.disconnect(self._update_axis_icons)
        gremlin.util.clear_layout(self.main_layout)
        self._deleted = True
    
    @property
    def deleted(self):
        # true if the cleanup function was found and the widget should be deleted
        return self._deleted


    @property
    def content_layout(self):
        ''' gets the the content row '''
        return self._custom_container_layout
    
    def _getIconSize(self) -> int:
        return 16
    
    def _getRowHeight(self) -> int:
        return 28
    
    def _setWidgetHeight(self, widget : QtWidgets.QWidget | list [QtWidgets.QWidget] , h):
        ''' sets fixed min/max height'''
        if not hasattr(widget,"__iter__"):
            w_list = [widget]
        else:
            w_list = widget
        for widget in w_list:
            if widget == self._description_container_widget and h != 0:
                pass
            if Shiboken.isValid(widget):
                widget.setFixedHeight(h)


    def unhook(self):
        hook_id = gremlin.util.normalize_guid(self.data.id)
        if self.axis_widget:
            verbose = gremlin.config.Configuration().verbose_mode_perf
            if verbose:
                description = f"input repeater:  hook id: [{hook_id}] [{str(self.input_item.id)}] device [{gremlin.joystick_handling.getDeviceName(self.identifier.device_guid)}] axis id: [{self.identifier.input_id}] "
                syslog.info(f"Unregister repeater: {description}")
            self.axis_widget.unhookDevice()
            self.axis_widget.setParent(None)
            self.axis_widget.deleteLater()
            self.axis_widget = None
        if self.button_widget:
            self.button_widget.setParent(None)
            self.button_widget.deleteLater()
            self.button_widget = None
        



    def _update_repeater(self):
        ''' updates the repeaters based on the type of widget '''

        if self._input_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.ModeControl, InputType.State):
            gremlin.util.clear_layout(self._repeater_container_layout)
            self._setWidgetHeight(self._repeater_container_widget, 0) # turn off repeater for non axis widgets
            self.axis_widget = None
            self.button_widget = None
            return
        
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_perf

        widget = None # widget created for the repeater

        # if self.identifier.input_type in (InputType.Keyboard, InputType.KeyboardLatched):
        #     pass
        input_type = self.identifier.input_type

        if config.show_input_axis:

            self.axis_widget = None
            self.button_widget = None
            gremlin.util.clear_layout(self._repeater_container_layout)
            
            if (self.identifier.is_axis or self.identifier.is_button or self.identifier.is_hat) or \
                input_type in (InputType.JoystickAxis, InputType.JoystickButton,  InputType.JoystickHat, InputType.OpenSoundControl, InputType.Midi):

                if self.identifier.is_valid:
                    hook_id = gremlin.util.normalize_guid(self.data.id)
                    if self.identifier.is_axis:
                        # axis
                        device_guid = self.identifier.device_guid
                        input_id = self.identifier.input_id
                        astate = gremlin.event_handler.AxisState()
                        values = astate.getAxisValues(device_guid, input_id)
                        widget = gremlin.ui.ui_common.QHookedProgressBar(orientation=QtCore.Qt.Orientation.Horizontal, value = values)

                        widget.unhooked.connect(self._axis_widget_unhooked)
                        widget.sizeChanged.connect(self._repeater_size_changed)
                        widget.data = self
                        self.axis_widget = widget
                        self._repeater_container_layout.addWidget(widget)                
                        self._repeater_container_layout.addStretch()

                        widget.setMaximumWidth(200)
                        if self._debug_layout:
                            widget.setStyleSheet("background: purple;")
                        
                        description = f"input repeater:  hook id: [{hook_id}] [{str(self.input_item.id)}] device [{gremlin.joystick_handling.getDeviceName(self.identifier.device_guid)}] axis id: [{self.identifier.input_id}] "
                        if verbose: syslog.info(f"register repeater: {description}")
                        widget.hookDevice(hook_id, self.identifier.device_guid, self.identifier.input_type, self.identifier.input_id, ui_only = True, description = description)
                        height = widget.sizeHint().height() + 4
                        self._setWidgetHeight(self._repeater_container_widget, height)

                        self.axis_widget.triggerUpdate() # force an update
                    else: 
                        # button
                        widget = gremlin.ui.ui_common.ButtonStateWidget()
                        widget.unhooked.connect(self._button_widget_unhooked)
                        widget.hookDevice(hook_id, self.identifier.device_guid, self.identifier.input_type, self.identifier.input_id)
                        #widget.hookDevice(self._device_guid, input_type, self._input_id )
                        self.button_widget = widget
                        self._repeater_container_layout.addWidget(widget)
                        widget.updateState()       
                                 
                        self._repeater_container_layout.addStretch()
                        if self._debug_layout:
                            widget.setStyleSheet("background: purple;")
                        height = widget.sizeHint().height() + 4
                        self._setWidgetHeight(self._repeater_container_widget, height)
                



    def _button_widget_unhooked(self):
        self.button_widget = None # force a new button widget
        gremlin.util.clear_layout(self._repeater_container_layout)

    def _axis_widget_unhooked(self):
        self.axis_widget = None
        gremlin.util.clear_layout(self._repeater_container_layout)
        


    def _repeater_size_changed(self):
        widget = self.sender()
        height = widget.sizeHint().height() + 4
        self._setWidgetHeight(self._repeater_container_widget, height)


    def _message_key_changed(self, old_message_key, new_message_key):
        state_tracker = gremlin.ui.ui_common.StateTracker()

        print (f"INPUT ITEM: message change {old_message_key} to {new_message_key}")

        if old_message_key:
            state_tracker.unregisterAxisState(self._device_guid, self._input_type, old_message_key)
            state_tracker.unregisterButtonState(self._device_guid, self._input_type,old_message_key)

        if self.axis_widget:
            state_tracker.registerAxisState(self.axis_widget, self._device_guid, self._input_type, new_message_key)
        if self.button_widget:
            state_tracker.registerButtonState(self.button_widget, self._device_guid, self._input_type, new_message_key)

    @QtCore.Slot(object)
    def _update_enabled_state(self, input_item ): # : gremlin.base_profile.InputItem
        ''' updates the enabled state '''
        if self.data == input_item:
            # ours
            if input_item.enabled:
                self._input_button_widget.setIcon(self._input_icon_active)
            else:
                self._input_button_widget.setIcon(self._input_icon_inactive)


    def _update_axis_icons(self):
        if not self._ui_loaded or not self.is_axis:
            return
        gremlin.util.InvokeUiMethod(self._update_axis_icons_ui)

    
    def _update_axis_icons_ui(self):
        ''' update titlebar icons - UI thread'''
        is_curve = self.data.is_curve
        if Shiboken.isValid(self._curve_button_widget):
            if is_curve:
                self._curve_button_widget.setIcon(self._curve_icon_active)
            else:
                self._curve_button_widget.setIcon(self._curve_icon_inactive)

        if Shiboken.isValid(self.clear_curve_widget):
           self.clear_curve_widget.setEnabled(is_curve)

        if Shiboken.isValid(self._calibration_button_widget):
            has_calibration = self.data.hasCalibration
            if has_calibration:
                self._calibration_button_widget.setIcon(self._calibration_icon_active)
            else:
                self._calibration_button_widget.setIcon(self._calibration_icon_inactive)


    def _update_action_icons(self):
        ''' updates the input item's action icon list '''
        gremlin.util.InvokeUiMethod(self._update_action_icons_ui)

    def _update_action_icons_ui(self):
        # update mapping icons 
        self.create_action_icons(self.data)


    def _icon_changed_cb(self, event : gremlin.event_handler.DeviceChangeEvent):
        gremlin.util.InvokeUiMethod(self._icon_changed_cb_ui, event)
    
    def _icon_changed_cb_ui(self, event : gremlin.event_handler.DeviceChangeEvent):
        ''' updates the input item icons based on the actions it contains - UI thread '''
        if isinstance(event.source, gremlin.base_profile.AbstractAction):
            action = event.source
            if self.findAction(action):
                # update the action
                self.create_action_icons(self.data)
        elif isinstance(event.source, gremlin.base_profile.InputItem):
            if self.data and self.data == event.source:
                self.create_action_icons(self.data)

    
    @QtCore.Slot(object)
    def _action_changed_cb(self, event):
        ''' occurs when an action is added or changed '''
        if isinstance(event,gremlin.base_profile.AbstractAction):
            action = event
        elif isinstance(event,gremlin.event_handler.DeviceChangeEvent):
            action = event.source
        else:
            return
        if isinstance(action, gremlin.base_profile.AbstractAction):
            if self.findAction(action):
                # update the action
                self.create_action_icons(self.data)

    @QtCore.Slot(object, object, object)
    def _action_deleted_cb(self, item_dat, container, action):
        ''' occurs when an action is deleted '''
        if self.findAction(action) and Shiboken.isValid(self):
            # find the widget corresponding to this action
            gremlin.util.InvokeUiMethod(self.clear_action_icon, self.data, action) # ensure on UI thread

    def _curve_changed_cb(self, input_item):
        ''' fires when a curve is added or deleted '''
        if input_item == self._input_item and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._update_repeater) # ensure on UI thread

    def _calibration_changed_cb(self, input_item):
        ''' fires when a calibration is added or deleted '''
        if input_item == self._input_item and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._update_repeater) # ensure on UI thread

    def _mapping_changed_cb(self, item_data):
        ''' called when a mapping changes - sends the item being changed '''
        if item_data == self.data and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._mapping_changed_cb_ui, item_data) # ensure on UI thread

    def _mapping_changed_cb_ui(self, item_data):
            ''' update the widget on mapping change '''
            if Shiboken.isValid(self):
                self._update_container_id_ui()
                self._update_action_icons_ui()
        
                

    def update_curve_icon(self, enabled : bool):
        ''' enables or disables curve buttons '''
        if self.is_axis:
            if enabled:
                self._curve_button_widget.setIcon(self._curve_icon_active)
            else:
                self._curve_button_widget.setIcon(self._curve_icon_inactive)
            self.clear_curve_widget.setEnabled(enabled)
            if self.identifier.input_type == InputType.JoystickAxis:
                if self.axis_widget is not None: # will be null if input axes not displayed
                    self.axis_widget.show_curved = enabled


    @QtCore.Slot(float)
    def _input_value_changed(self, value):
        ''' called when the input changes '''
        self.input_value_changed.emit(self, value)

        
    @property
    def data(self):
        ''' gets any data object associated with this widget '''
        return self._data
    @data.setter
    def data(self, value):
        self._data = value

    @property
    def index(self):
        ''' assigned index '''
        return self._index

    @index.setter
    def index(self, value):
        self._index = value

    @property
    def config_external(self):
        return self._config_external

    @config_external.setter
    def config_external(self, value):
        self._config_external = value

    def setTitle(self, value):
        ''' sets the title of the input widget '''
        self._title_text_widget.setText(value)

    def setCustomContent(self, items : QtWidgets.QWidget | list [QtWidgets.QWidget]):
        ''' adds custom content to the input widget (vertical container)'''
        gremlin.util.clear_layout(self._custom_container_layout)
        if not items:
            self._setWidgetHeight(self._custom_container_widget, 0)
        if not hasattr(items, "__iter__"):
            widgets = [items]
        else:
            widgets = items
        rh = 0
        widget : QtWidgets.QWidget
        for widget in widgets:
            self._custom_container_layout.addWidget(widget)
            rh += widget.sizeHint().height()

        self._setWidgetHeight(self._custom_container_widget, rh + 4)


    def setInputDescription(self, description : str | None):
        ''' sets the input description for an input widget (optional) '''
 
        if description:
            rh = self._getRowHeight()
            self._input_description_widget.setText(description) 
            self._input_description_widget.setIcon(self._input_description_icon)
            self._setWidgetHeight(self._input_description_container_widget, rh)
        else:
            self._input_description_widget.setText(None)
            self._input_description_widget.setIcon(None)
            self._setWidgetHeight(self._input_description_container_widget, 0)

            

        

    def setInputDescriptionIcon(self, icon_path, use_qta = True):
        ''' sets (or clears) the icon for the input description line '''
        if isinstance(icon_path, QtGui.QIcon):
            self._input_description_icon = icon_path
        else:
            self._input_description_icon = load_icon(icon_path, use_qta) if icon_path else None
        if Shiboken.isValid(self._input_description_widget):
            self._input_description_widget.setIcon(self._input_description_icon)

    def setStatus(self, status: str, icon = None):
        ''' sets the status'''
        if not self._ui_loaded: return
        gremlin.util.clear_layout(self._status_container_layout)
        if status:
            self._status_widget = gremlin.ui.ui_common.QIconLabel(icon, status)
            self._setWidgetHeight(self._status_container_widget, self._getRowHeight())
        else:
            self._setWidgetHeight(self._status_container_widget, 0)
        


    def setDescription(self, description : str | None):
        ''' sets the description of the input widget '''
        if description:
            rh = self._getRowHeight()
            self._description_widget.setText(description) 
            self._description_widget.setIcon(self._input_description_icon)
            self._setWidgetHeight(self._description_container_widget, rh)
        else:
            self._description_widget.setText(None)
            self._description_widget.setIcon(None)
            self._setWidgetHeight(self._description_container_widget, 0)

       
    def setComment(self, value, icon = None):
        ''' sets the comment field of the input widget '''
        if value:
            gremlin.util.clear_layout(self._comment_container_layout)
            widget = gremlin.ui.ui_common.QIconLabel(icon_path = icon, text = f"<i>{value}</i>")
            self._comment_container_layout.addWidget(widget)
            self._setWidgetHeight(self._comment_container_widget, self._getRowHeight())
        else:
            self._setWidgetHeight(self._comment_container_widget, 0)
        self.updateHeight()

    def setToolTip(self, tooltip):
        ''' sets the tooltip for the widget '''
        super().setToolTip(tooltip)

    def setIcon(self, icon_path, use_qta = True):
        ''' sets the widget's icon '''
        self._title_text_widget.setIcon(icon_path, use_qta)
        

    # def addWidget(self, widget):
    #     ''' adds a widget to the contents '''
    #     self._container_layout.addWidget(widget,self._row_custom_content,0) # custom container      

    def update_display(self):
        gremlin.util.InvokeUiMethod(self._update_display_ui)
              

    def _update_display_ui(self):
        ''' updates the display text for the button, custom content and input enabled '''
        
        
        if gremlin.shared_state.is_running:
            return # do not update UI at runtime


        if self._ui_loaded:
            config = gremlin.config.Configuration() 
            power_visible = config.show_input_enable
            if power_visible:
                if not self._input_button_widget:
                    
                    size = self._getIconSize()
                    self._input_button_widget = QtWidgets.QPushButton() 
                    self._input_button_widget.setIcon(self._input_icon_active)
                    self._input_button_widget.setToolTip("Enables or disables this input.  If disabled, input from this specific input will be ignored.<br>The state can be changed by the control action as well.")
                    self._input_button_widget.setFixedSize(size,size)
                    self._input_button_widget.clicked.connect(self._input_button_cb)
                    self._title_icon_layout.addWidget(self._input_button_widget)
            else:
                if self._input_button_widget and Shiboken.isValid(self._input_button_widget):
                    self._title_icon_layout.removeWidget(self._input_button_widget)
                    self._input_button_widget = None

            # description field
            self.setDescription(self.data.description)


            if not self._config_external or self.populate_name is not None:
                #display_text = self.populate_name(self, self.identifier) if self.populate_name else gremlin.common.input_to_ui_string( self.identifier.input_type,self.identifier.input_id)
                display_text = self.populate_name(self, self.identifier) if self.populate_name is not None else self.identifier.input_name
                self._title_text_widget.setText(display_text)

            self._update_axis_icons()

            # update selection css
            self._update_selected_ui()

            # populate the custom content
            if self._update_callback:
                self._update_callback(self, self._custom_container_widget)

            # update repeater
            if not self.identifier.is_valid:
                self._setWidgetHeight(self._repeater_container_widget, 0)

            # update status
            if not self.identifier.is_status:
                self._setWidgetHeight(self._status_container_widget, 0)
           
            # update repeater for this widget
            self._update_repeater()

    @property
    def selected(self) -> bool:
        ''' True if the item is currently selected '''
        return self._selected

    @selected.setter
    def selected(self, value : bool):
        self.setSelected(value)

    def setSelected(self, value : bool, emit = True):
        if value != self._selected:
            self._selected = value
            if emit:
                if not value:
                    self.unselected.emit(self)

            if emit:
                self.selected_changed.emit(self)

        # ensure the widget has the correct visual selection state
        self._update_selected() # uptate widget style
  
        
    def ensureStyle(self):
        ''' updates the visual selection '''
        self._update_selected()

    def _update_selected(self):
        ''' updates the widget style based on selection '''
        gremlin.util.InvokeUiMethod(self._update_selected_ui)

    def _update_selected_ui(self):
        ''' called whenever selection changes '''            
        if self._selected:
            style = f'''
                    #main_layout {{
                        background: {gremlin.ui.ui_common.Color.selectColor()}; 
                        border: 2px solid {gremlin.ui.ui_common.Color.selectBorderColor()};
                    }}
                '''
            self.setStyleSheet(style)
            css = gremlin.ui.ui_common.Color.cssInputHeader()
        else:
            self._default_style()
            css = gremlin.ui.ui_common.Color.cssUnselectedInputHeader()
        
        # update style for title bar
        self._title_bar_widget.setStyleSheet(css)

        # update container
        self._update_container_id()


    def _default_style(self):
        ''' sets the default style'''
        style = f'''
                    #main_layout {{
                        background: {gremlin.ui.ui_common.Color.backgroundColor()}; 
                        border: 1px solid {gremlin.ui.ui_common.Color.borderColor()};
                        }}
                        '''
        self.setStyleSheet(style)

    def enable_close(self):
        ''' enables the close button on the input widget (keyboard only usually) '''
        if self._close_button_widget:
            # already visible
            return
        size = self._getIconSize()
        icon = gremlin.ui.ui_common.load_icon("mdi.delete")
        self._close_button_widget = QtWidgets.QPushButton()
        self._close_button_widget.setIcon(icon)
        self._close_button_widget.setFixedSize(size,size)
        self._close_button_widget.clicked.connect(self._close_button_cb)
        # insert in last position
        self._title_icon_layout.addWidget(self._close_button_widget)


        

    def disable_close(self):
        ''' enables the close button on the input widget (keyboard only usually) '''
        if self._close_button_widget and Shiboken.isValid(self._close_button_widget):
            self._title_icon_layout.removeWidget(self._close_button_widget)
            self._close_button_widget = None

    def enable_repeater(self):
        # enables the repeater container
        self._repeater_enabled = True
        self._update_repeater()

    def disable_repeater(self):
        # disables the repeater container
        self._repeater_enabled = False
        self._update_repeater()


    def enable_edit(self):
        ''' enables the edit button on the input widget (keyboard only usually) '''

        # we avoid using setVisible() because of the QT event wiring
        if self._edit_button_widget:
            # already visible
            return
        size = self._getIconSize()
        icon = gremlin.ui.ui_common.Icons.gearIcon()
        self._edit_button_widget = QtWidgets.QPushButton() 
        self._edit_button_widget.setIcon(icon)
        self._edit_button_widget.setToolTip("Configure")
        self._edit_button_widget.setFixedSize(size,size)
        self._edit_button_widget.clicked.connect(self._edit_button_cb)

        # insert next to last button
        index = len(gremlin.util.get_layout_widgets(self._title_icon_layout))
        if index > 0:
            index -= 1
        self._title_icon_layout.insertWidget(index, self._edit_button_widget)


    def disable_edit(self):
        ''' enables the edit button on the input widget (keyboard only usually) '''
        if self._edit_button_widget and Shiboken.isValid(self._edit_button_widget):
            # remove it
            self._title_icon_layout.removeWidget(self._edit_button_widget)
            self._edit_button_widget = None


    def create_action_icons(self, profile_data):
        """Creates the label of this instance.

        Renders the text representing the instance's name as well as
        icons of actions associated with it.

        :param profile_data the profile.InputItem object associated
            with this instance
        """

        if not Shiboken.isValid(self._action_icons_container_layout):
            return

        if profile_data is None or self.data.id != profile_data.id:
            return

        ui_common.clear_layout(self._action_icons_container_layout)
        self._action_icons_container_layout.addWidget(QtWidgets.QWidget(),0,0)
        self._action_icons_container_layout.setColumnStretch(0,1)
        rh = self._getRowHeight()

        if profile_data.containers:
            # Create the actual icons
            row = 0
            col = 1
            max_col = 5 
            size = self._getIconSize()
            for container in profile_data.containers:
                action_sets = container.get_action_sets()
                if action_sets:
                    for actions in [a for a in action_sets if a is not None]:
                        for action in actions:
                            if action is not None:
                                widget = ui_common.ActionLabel(action)
                                widget.setMaximumWidth(size)
                                widget.setMaximumHeight(size)
                                self._action_icons_container_layout.addWidget(widget, row, col)
                                col +=1
                                if col > max_col:
                                    col = 1
                                    row +=1

                else:
                    for actions in [a for a in container.action_sets if a is not None]:
                        for action in actions:
                            if action is not None:
                                widget = ui_common.ActionLabel(action)
                                widget.setMaximumWidth(size)
                                widget.setMaximumHeight(size)
                                self._action_icons_container_layout.addWidget(widget, row, col)
                                col+=1
                                if col > max_col:
                                    col = 1
                                    row +=1

            self._setWidgetHeight(self._action_container_widget, rh * (row + 1))
            
        else:
            label = QtWidgets.QLabel("∅", alignment=QtCore.Qt.AlignmentFlag.AlignRight)
            font = label.font()
            font.setPixelSize(24)
            label.setFont(font)
            label.setToolTip("No mappings found")
            self._action_icons_container_layout.addWidget(label,0,1)
            self._setWidgetHeight(self._action_container_widget, rh)

        

    def clear_action_icon(self, profile_data, action_to_remove):
        ''' delete an action icon '''
        ui_common.clear_layout(self._action_icons_container_layout)
        self._action_icons_container_layout.addWidget(QtWidgets.QWidget(),0,0)
        self._action_icons_container_layout.setColumnStretch(0,1)
        row = 0
        col = 1
        max_col = 5 
        rh = self._getRowHeight()
        if profile_data.containers:
            for container in profile_data.containers:
                action_sets = container.get_action_sets()
                if action_sets:
                    for actions in [a for a in action_sets if a is not None]:
                        for action in actions:
                            if action is not None and action != action_to_remove:
                                self._action_icons_container_layout.addWidget(ui_common.ActionLabel(action), row, col)
                                col += 1
                                if col > max_col:
                                    col = 1
                                    row +=1


                else:
                    for actions in [a for a in container.action_sets if a is not None]:
                        for action in actions:
                            if action is not None and action != action_to_remove:
                                self._action_icons_container_layout.addWidget(ui_common.ActionLabel(action), row, col)
                                col +=1
                                if col > max_col:
                                    col = 1
                                    row +=1

            self._setWidgetHeight(self._action_container_widget, rh * (row + 1))
        else:
            self._action_icons_container_layout.addWidget(QtWidgets.QLabel("∅", alignment=QtCore.Qt.AlignmentFlag.AlignRight),0,1)
            self._setWidgetHeight(self._action_container_widget, rh)



            

    def findAction(self, action):
        ''' true if the action is found in our containers '''
        if self.data and self.data.containers:
            for container in self.data.containers:
                action_sets = container.get_action_sets()
                if action_sets:
                    for action_set in action_sets:
                        if action_set:
                            if action in action_set:
                                return True
        return False


    def mousePressEvent(self, event):
        """Emits the input_item_changed event when this instance is
        clicked on by the mouse.

        :param event the mouse event
        """
        if not self.selected:
            self.selected_changed.emit(self)

    QtCore.Slot()
    def _close_button_cb(self):
        ''' fires the closed event when the close button has been pressed '''
        
        if self._confirm_delete_callback:
            if not self._confirm_delete_callback(self._input_item):
                # request failed
                return

        # prompt
        ui = gremlin.shared_state.ui
        result =gremlin.ui.ui_common.ConfirmBox(prompt = "Remove this input?", parent = ui)
        if not result:
            return

        # remove the tracker objects
        widget_tracker = gremlin.ui.ui_common.StateTracker()
        device_guid = self._device_guid
        input_type = self._input_type
        input_id = self._input_id
        widget_tracker.unregisterAxisState(device_guid, input_type, input_id)
        widget_tracker.unregisterButtonState(device_guid, input_type, input_id)

        self.closed.emit(self)



    QtCore.Slot()
    def _edit_button_cb(self):
        ''' edit button clicked '''
        self.edit.emit(self)

    QtCore.Slot()
    def _curve_button_cb(self):
        self.edit_curve.emit(self)

    QtCore.Slot()
    def _input_button_cb(self):
        # toggle input state
        self.data.enabled = not self.data.enabled

    @QtCore.Slot()
    def _calibration_button_cb(self):
        # open the calibration button for this input
        dialog = gremlin.ui.axis_calibration.CalibrationDialogEx(self.data)
        dialog.exec()
        self.data.calibration.copyFrom(dialog.action_data)
        self._update_axis_icons()
        

    QtCore.Slot()
    def _clear_curve_cb(self):
        self.delete_curve.emit(self)



class ContainerSelector(QtWidgets.QWidget):

    """Allows the selection of a container type."""

    # Signal emitted when a container type is selected
    container_added = Signal(str) # fires when a container is added (name of the container)
    container_copy =  Signal() # copy all containers
    container_paste = Signal(object, object) # paste containers (clipboard data, extra_data [optional])
    container_delete = Signal() # delete all containers
    container_from_template = Signal(dict) # load a new container from template, passes a dictionary (can be null) of data items
    container_to_template = Signal(object) # saves the mappings to a template, passes the input_item as the parameter

    def __init__(self, input_type, is_axis = False, data = None, parent=None):
        """Creates a new selector instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.input_type = input_type
        self.is_axis = is_axis
        self.data = data # input item
        

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.addWidget(QtWidgets.QLabel("Container"))

        self.container_dropdown = gremlin.ui.ui_common.QDataComboBox()
        
        self.add_container_widget = gremlin.ui.ui_common.Buttons.getAddWidget(tooltip = "Adds the selected container", callback = self._add_container)

        # self.help_widget = gremlin.ui.ui_common.Buttons.getHelpWidget(callback = self._handle_help)

        self.save_template_widget =  gremlin.ui.ui_common.Buttons.getSaveWidget(callback =self._save_container_to_template,
                                                                                  tooltip = "Save mappings to template")

        self.load_template_widget =  gremlin.ui.ui_common.Buttons.getFolderWidget(callback =self._load_container_from_template,
                                                                                  tooltip = "Load mappings from template")
        
        self.data.lockedChanged.connect(self._handle_lock_changed)
        
        default_container = gremlin.config.Configuration().last_container
        self.container_dropdown.setCurrentText(default_container)
        self.container_dropdown.currentIndexChanged.connect(self._container_changed)


        # clipboard
        self.copy_button_widget = gremlin.ui.ui_common.Buttons.getCopyWidget(callback = self._copy_container, tooltip = "Copy container(s)")
        self.paste_button_widget = gremlin.ui.ui_common.Buttons.getPasteWidget(callback = self._paste_container, tooltip = "Paste container(s)")
        self.paste_button_widget.data = self.data # input item doing the paste
        
        # delete all containers
        self.delete_button =  QtWidgets.QPushButton()
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        self.delete_button.setIcon(icon)
        self.delete_button.clicked.connect(self._delete_container)
        self.delete_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.delete_button.setToolTip("Delete container(s)")


        widgets = [self.container_dropdown,
                   self.add_container_widget,
                  ]
        
        widget = gremlin.ui.ui_common.getHContainer(widgets,widget_only = True)
        self.main_layout.addWidget(widget)

        # self.main_layout.addWidget(self.container_dropdown)
        # self.main_layout.addWidget(self.help_widget)
        # self.main_layout.addWidget(self.add_container_widget)

        self.main_layout.addWidget(self.save_template_widget)
        self.main_layout.addWidget(self.load_template_widget)
        self.main_layout.addWidget(self.copy_button_widget)
        self.main_layout.addWidget(self.paste_button_widget)
        self.main_layout.addWidget(self.delete_button)

        self.refresh(data)

        self._handle_lock_changed_ui(self.data)

        eh = gremlin.event_handler.EventHandler()
        eh.last_container_changed.connect(self._last_container_changed)

    def _handle_lock_changed(self, input_item):
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item) # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        if Shiboken.isValid(self):
            unlocked = not input_item.locked
            self.load_template_widget.setEnabled(unlocked)
            self.add_container_widget.setEnabled(unlocked)
            self.paste_button_widget.setEnabled(unlocked)
            self.delete_button.setEnabled(unlocked)



    def refresh(self, input_item):
        ''' reloads the selector based on the input '''
        self.input_type = input_item.input_type
        with QtCore.QSignalBlocker(self.container_dropdown):
            self.container_dropdown.clear()
            for name in input_item.get_valid_container_list():
                self.container_dropdown.addItem(name )
            config = gremlin.config.Configuration()
            self.container_dropdown.setCurrentText(config.last_container)

        enabled = self.data and len(self.data.containers) > 0
        self.save_template_widget.setEnabled(enabled)
    
    def _last_container_changed(self, widget, name):
        gremlin.util.InvokeUiMethod(self._last_container_changed_ui, widget, name) # ensure on UI thread
    
    def _last_container_changed_ui(self, widget, name):
        if not Shiboken.isValid(self):
            return
        if widget != self.container_dropdown:
            with QtCore.QSignalBlocker(self.container_dropdown):
                self.container_dropdown.setCurrentText(name)

    def _container_changed(self):
        ''' remember the selection '''
        if not Shiboken.isValid(self):
            return
        name = self.container_dropdown.currentText()
        config = gremlin.config.Configuration()
        config.last_container = name
        if config.sync_last_selection:
            eh = gremlin.event_handler.EventHandler()
            eh.last_container_changed.emit(self.container_dropdown, name)

    def _valid_container_list(self, input_type : InputType):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        container_list = []
        
        for entry in gremlin.plugin_manager.ContainerPlugins().repository.values():
            if not entry.input_types or input_type in entry.input_types:
                if entry.axis_only:
                    # container requires an axis
                    if not self.is_axis:
                        continue
                container_list.append(entry.name)
        return sorted(container_list)

    @QtCore.Slot()
    def _add_container(self, clicked=False):
        """Handles add button events.

        :param clicked flag indicating whether or not the button was pressed
        """
        self.container_added.emit(self.container_dropdown.currentText())

    def _handle_help(self):
        ''' help button '''
        import gremlin.base_profile
        container_name = self.container_dropdown.currentText()
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        
        input_item = self.data
        container = plugin_manager.get_class(container_name)(input_item)
        if hasattr(container,"hint"):
            hint = container.hint
        else:
            hint = gremlin.hints.hint.get(container.tag, "")
        if hint:
            gremlin.ui.ui_common.MessageBox(title = f"About the {container_name} container:", prompt = hint, width = 300, is_warning = False)


    def _clipboard_changed(self, clipboard):
        ''' handles paste button state based on clipboard data '''
        self.paste_button_widget.setEnabled(clipboard.is_container)
        ''' updates the paste button tooltip with the current clipboard contents'''
        if clipboard.is_container:
            self.paste_button_widget.setToolTip(f"Paste container ({clipboard.data.name})")
        else:
            self.paste_button_widget.setToolTip(f"Paste container (not available)")

    @QtCore.Slot()
    def _paste_container(self):
        ''' handle paste containern '''
        clipboard = Clipboard()
        widget = self.sender()
        input_item = widget.data
        extra_data = input_item.toExtraData()

        # validate the clipboard data is an action and is of the correct type for the input/container
        if clipboard.is_container:
            self.container_paste.emit(clipboard.data, extra_data)
    
    @QtCore.Slot()
    def _copy_container(self):
        ''' fires the copy container '''
        self.container_copy.emit()

    @QtCore.Slot()
    def _delete_container(self):
        ''' delete container '''
        self.container_delete.emit()

    @QtCore.Slot()
    def _save_container_to_template(self):
        ''' saves a complete mapping to a template '''
        input_item : gremlin.base_profile.InputItem = self.data
        self.container_to_template.emit(input_item)

    @QtCore.Slot()
    def _load_container_from_template(self):
        ''' loads container from template '''
        input_item : gremlin.base_profile.InputItem = self.data
        extra_data = input_item.toExtraData()
        self.container_from_template.emit(extra_data)

class ConditionTrackerInfo:
    def __init__(self, input_item, device_guid, input_id, container, widget):
        self.device_guid = device_guid
        self.input_id = input_id
        self.containerWidget = widget
        self.input_item = input_item
        self.container = container
        
    @property
    def dock_tabs(self):
        if self.containerWidget:
            return self.containerWidget.dock_tabs
        return None
    

@gremlin.singleton_decorator.SingletonDecorator
class ConditionStateTracker():
    def __init__(self):
        self._cache = {} # maps input to condition tab
        self._widget_cache = {} # tracks the dock tab widget for the registered input_item for this mode
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._condition_state_changed)
        el.condition_changed.connect(self._condition_changed)
        el.container_delete.connect(self._container_delete)
        el.mapping_changed.connect(self._mapping_changed)
        self._icon_enabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.activeColor())
        self._icon_disabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.inactiveColor())

    def register(self, input_item, container, container_widget):
        ''' registers a condition tracker '''
        if not isinstance(container, gremlin.base_profile.AbstractContainer):
            return

        dock_tab : QtWidgets.QTabWidget = container_widget.dock_tabs
        device_guid = input_item.device_guid
        mode =input_item.profile_mode # gremlin.shared_state.current_mode
        input_id = input_item.input_id
        if not device_guid in self._cache:
            self._cache[device_guid] = {}
        if not mode in self._cache[device_guid]:
            self._cache[device_guid][mode] = {}
        if not input_id in self._cache[device_guid][mode]:
            self._cache[device_guid][mode][input_id] = {}
        info = ConditionTrackerInfo(input_item, device_guid, input_id, container, container_widget)
        self._cache[device_guid][mode][input_id][container.id] = info

        enabled = info.input_item.hasConditions()
        self.set_condition_tab_state(dock_tab, enabled)

    def unregister(self, input_item, container):
        ''' unregisters a condition tracker '''
        if not isinstance(container, gremlin.base_profile.AbstractContainer):
            return
        assert isinstance(container, gremlin.base_profile.AbstractContainer)
        device_guid = input_item.device_guid
        mode = input_item.profile_mode # gremlin.shared_state.current_mode
        input_id = input_item.input_id
        if device_guid in self._cache:
            if mode in self._cache[device_guid]:
                if input_id in self._cache[device_guid][mode]:
                    if container.id in self._cache[device_guid][mode][input_id]:
                            del self._cache[device_guid][mode][input_id][container.id]


    @QtCore.Slot(object)
    def _condition_state_changed(self, container):
        if not isinstance(container, gremlin.base_profile.AbstractContainer):
            return
        device_guid = container.hardware_device_guid
        input_id = container.hardware_input_id
        mode = gremlin.shared_state.current_mode
        if device_guid in self._cache:
            if mode in self._cache[device_guid]:
                if input_id in self._cache[device_guid][mode]:
                    if container.id in self._cache[device_guid][mode][input_id]:
                        info = self._cache[device_guid][mode][input_id][container.id]
                        enabled = info.input_item.hasConditions()
                       
                        dock_tabs = info.dock_tabs
                        self.set_condition_tab_state(dock_tabs, enabled)
                        
                        

    @QtCore.Slot(object)
    def _condition_changed(self, container):
        device_guid = container.hardware_device_guid
        input_id = container.hardware_input_id
        mode = gremlin.shared_state.current_mode
        if device_guid in self._cache:
            if mode in self._cache[device_guid]:
                if input_id in self._cache[device_guid][mode]:
                    if container.id in self._cache[device_guid][mode][input_id]:
                        info = self._cache[device_guid][mode][input_id][container.id]
                        container_widget : AbstractContainerWidget = info.containerWidget
                        container_widget._update_condition_ui(container)
                        enabled = info.input_item.hasConditions()
                        dock_tabs = info.dock_tabs
                        self.set_condition_tab_state(dock_tabs, enabled)


    @QtCore.Slot(object, object)
    def _container_delete(self, input_item, container):
        if not isinstance(container, gremlin.base_profile.AbstractContainer):
            return
        self.unregister(input_item, container)
                    
    @QtCore.Slot()
    def _mapping_changed(self):
        ''' called when a mapping is changed '''    
        # ensure condition "state" is updated following the change
        
        

     
    def set_condition_tab_state(self, dock_tabs : QtWidgets.QTabWidget, enabled : bool):
        ''' marks the condition tab used or not '''
        if Shiboken.isValid(dock_tabs):
            try:
                for i in range(dock_tabs.count()):
                    if dock_tabs.tabText(i) == "Conditions":
                        tb = dock_tabs.tabBar()
                        icon = self._icon_enabled if enabled else self._icon_disabled
                        tb.setTabIcon(i, icon)
                        break
            except:
                pass

    
        


class AbstractContainerWidget(QtWidgets.QDockWidget):

    """Base class for container widgets."""

    # Signal which is emitted whenever the widget is closed
    closed = QtCore.Signal(QtWidgets.QWidget)

    # fires when the container is about to be closed
    closing = QtCore.Signal()

        
    container_modified = QtCore.Signal()  # container contents changed


   
    # Maps virtual button data to virtual button widgets
    virtual_axis_to_widget = {
        VirtualAxisButton: virtual_button.VirtualAxisButtonWidget,
        VirtualHatButton: virtual_button.VirtualHatButtonWidget
    }

    def __init__(self, profile_data, parent=None):
        """Creates a new container widget object.

        :param profile_data the data the container handles
        :param parent the parent of the widget
        """

        import gremlin.hints
        import gremlin.event_handler
        import gremlin.base_profile
        import gremlin.ui.ui_common
        import gremlin.shared_state
        import gremlin.config

        assert isinstance(profile_data, gremlin.base_profile.AbstractContainer)
        super().__init__(parent)

   
        background_color = gremlin.ui.ui_common.Color.containerBackgroundColor()
        css = f"background-color:{background_color}"
        self.setStyleSheet(css)

        self._abstract_container_content_widget, self._abstract_container_content_layout = gremlin.ui.ui_common.getVContainer(no_stretch=True)

        el = gremlin.event_handler.EventListener()
        el.condition_redraw.connect(self._condition_redraw) # hook the condition redraw event so we can remove existing references to the UI going away on redraw
        el.condition_changed.connect(self._condition_changed) # hook condition changed so we can update the UI

        #el.ui_ready.connect(self._ui_ready)
        self._icon_enabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.activeColor())
        self._icon_disabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.inactiveColor())

        if isinstance(profile_data, gremlin.base_profile.AbstractContainer):
            self.container = profile_data
        else:
            self.container = None
        self.profile_data = profile_data
        self.action_widgets = []

        mode = self.profile_data.get_mode()
        if mode == gremlin.shared_state.master_mode:
            mode = "[Master]"
        if hasattr(self.profile_data,"hint"):
            hint = self.profile_data.hint
        else:
            hint = gremlin.hints.hint.get(self.profile_data.tag, "")
        self._title_bar_widget = TitleBar(
            f"{self._get_window_title()} ({mode})",
            hint,
            self._container_remove,
            self._copy_container,
            data = profile_data)
        
        self.title_frame_widget = gremlin.ui.ui_common.QBorderWidget()
        self.title_frame_widget.addWidget(self._title_bar_widget)

        # self.title_frame_widget.setMaximumWidth(600)
        self.title_frame_widget.setMinimumWidth(200)


        self.title_frame_widget.setBackgroundColor(gremlin.ui.ui_common.Color.containerBackgroundColor())
        self.collapsible_widget = gremlin.ui.ui_common.QCollapsible(title_widget = self.title_frame_widget)
        self.collapsible_widget.toggled.connect(self._handle_toggled)
        
        #self.setTitleBarWidget(self._title_bar_widget)
        self.setTitleBarWidget(self.collapsible_widget)
        

        # Create tab widget to display various UI controls in
        self.dock_tabs =  gremlin.ui.ui_common.QDataTab()
        # self.dock_tabs.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)

        background_color = gremlin.ui.ui_common.Color.selectedDockTabBackgroundColor()
        self.setStyleSheet = f"QDockWidget: {{ background-color: {background_color}; }}"

        self.dock_tabs.setStyleSheet(f"QTabBar::tab:selected {{ background-color: {background_color}; }}")
        
        self.dock_tabs.setTabPosition(QtWidgets.QTabWidget.East)
        
        self._abstract_container_content_layout.addWidget(self.dock_tabs)
        self.setWidget(self._abstract_container_content_widget)

        self.dock_tabs.data = self.container # associated the data tab with the container
        self.activation_condition_widget = None
        
        # Create the individual tabs
        self._create_action_tab()
        # if self.profile_data.get_device_type() != DeviceType.VJoy:
        if self.profile_data.condition_enabled:
            self._create_activation_condition_tab()
        if self.profile_data.virtual_button_enabled:
            self._create_virtual_button_tab()

        self.dock_tabs.currentChanged.connect(self._tab_changed)

        # Select appropriate tab
        self._select_tab(self.profile_data.current_view_type)

        tracker = ConditionStateTracker()
        tracker.register(self.profile_data.input_item, self.profile_data, self)
        
        self.profile_data.input_item.lockedChanged.connect(self._handle_lock_changed)

        save_widget = gremlin.ui.ui_common.Buttons.getSaveWidget(tooltip="Save this container to a template", callback = self._save_template)
        
        #self._title_bar_widget.extra_layout.addWidget(open_widget)
        self._title_bar_widget.extra_layout.addWidget(save_widget)

        # this is for CONTAINER CONDITIONS only (Action conditions are handled elsewhere) - this hooks the condition state tab to the conditions added to the container
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._update_container_ui)

        self.activation_count_widget = None
        #el.condition_state_changed.emit(self.container)

        self._handle_lock_changed_ui(self.profile_data.input_item)

        gremlin.util.singleShot(self._config_visible)

        if self.container.collapsed:
            self.collapsible_widget.collapse(False)
        else:
            self.collapsible_widget.expand(False)
        

        self.collapsible_widget.setContent(self._abstract_container_content_widget, own = False)

        el = gremlin.event_handler.EventListener()
        el.collapse_all_containers.connect(self._handle_collapse)
        el.expand_all_containers.connect(self._handle_expand)

        self._update_container_ui(self.container)





    @QtCore.Slot()
    def _handle_toggled(self):
        self.container.collapsed = self.collapsible_widget.isCollapsed()


    def _handle_collapse(self):
        gremlin.util.InvokeUiMethod(self._handle_collapse_ui)

    def _handle_collapse_ui(self):
        ''' collapse the container - ui thread'''
        self.collapsible_widget.collapse(False)

    def _handle_expand(self):
        gremlin.util.InvokeUiMethod(self._handle_expand_ui)

    def _handle_expand_ui(self):
        ''' expand the container - ui thread '''
        self.collapsible_widget.expand(False)

    def _config_visible(self):
        if not Shiboken.isValid(self):
            return
        config = gremlin.config.Configuration()
        self._title_bar_widget.setIdVisible(config.show_container_id)

    def _handle_lock_changed(self, input_item):
        ''' enable/disable based on lock state '''
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item) # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        ''' enable/disable based on lock state '''
        if Shiboken.isValid(self):
            self.setEnabled(not input_item.locked)
        
        
    @QtCore.Slot()
    def _open_template(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Container template",
            gremlin.shared_state.data_path,
            "XML files (*.xml)"
        )
        if fname and os.path.isfile(fname):
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            try:
                tree = etree.parse(fname, parser=parser)
                root = tree.getRoot()
                if root.tag == "container_template":
                    # get root containers only
                    nodes = root.xpath("//container[not(ancestor::container)]")
                    for node in nodes:
                        container_type = node.get("type")
                        container_plugins = gremlin.plugin_manager.ContainerPlugins()
                        container_tag_map = container_plugins.tag_map
                        valid_containers_names = self.profile_data.get_valid_container_list()

                        # verify the container is valid for the input
                        if container_type in container_tag_map:
                            container_name = container_tag_map[container_type].name
                            if container_name in valid_containers_names:
                                new_container = container_tag_map[container_type](self.item_data)
                                new_container.from_xml(node, self.profile_data)
                                new_container.generateGuids()
                                self.container = new_container
                                if Shiboken.isValid(self):
                                    self.container_modified.emit()

            except:
                pass

    @QtCore.Slot()
    def _save_template(self):
        if not self.container:
            # no container to save
            return
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Container template",
            gremlin.shared_state.data_path,
            "XML files (*.xml)"
        )
        if fname:
            # get the container nodes
            node = self.container.to_xml()
            root = etree.Element("container_template")
            root.append(node)
            tree = etree.ElementTree(root)
            try:
                if os.path.isfile(fname):
                    # blitz existing file
                    os.unlink(fname)
                tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
            except:
                syslog.error(f"Error writing template to: {fname}")
                return False
            return True
            
    

    @QtCore.Slot(object)
    def _update_container_ui(self, container):
        ''' update the condition icon in the RIGHT PANEL tab '''
        if not Shiboken.isValid(self.dock_tabs):
            return
        dock_tabs = self.dock_tabs
        if dock_tabs.data == container:
            # tracker = gremlin.base_conditions.ConditionTracker()
            #input_item = container.input_item
            # count = tracker.getInputItemConditionCount(input_item)
            enabled = container.hasConditions() # tracker.getContainerConditionCount(container) > 0
            # count = self.container.condition_count
            # enabled = count > 0 or enabled
            virtual_enabled = self.profile_data.virtual_button_user_enabled
            try:
                
                for i in range(dock_tabs.count()):
                    if dock_tabs.tabText(i) == "Conditions":
                        tb = dock_tabs.tabBar()
                        icon = self._icon_enabled if enabled else self._icon_disabled
                        tb.setTabIcon(i, icon)
                        
                    if dock_tabs.tabText(i) == "Virtual Button":
                        tb = dock_tabs.tabBar()
                        icon = self._icon_enabled if virtual_enabled else self._icon_disabled
                        tb.setTabIcon(i, icon)
                        
            except:
                pass

        if self.container == container and self.activation_condition_widget:
            self._update_counts()
            self.activation_condition_widget._update_conditions_ui()


    @QtCore.Slot(object, object)
    def _condition_changed(self, container):
        ''' called when conditions change '''
        if container.id == self.container.id and self.activation_condition_widget:
            self.activation_condition_widget._update_conditions_ui()

    @QtCore.Slot()
    def _condition_redraw(self, data):
        ''' occurs when a condition redraws '''

        if self.profile_data == data:
            self._cleanup_ui()
        
            
            
    def _cleanup_ui(self):
        tracker = ConditionStateTracker()
        tracker.unregister(self.profile_data.input_item, self.profile_data)
        self.profile_data.input_item.lockedChanged.disconnect(self._handle_lock_changed)
        


    def _create_action_tab(self):
        # Create root widget of the dock element
        self.action_tab_widget = QtWidgets.QWidget()
        # Create layout and place it inside the dock widget
        self.action_layout = QtWidgets.QVBoxLayout(self.action_tab_widget)

        # Create the actual UI
        self.dock_tabs.addTab(self.action_tab_widget, "Action")
        self._create(self.profile_data)
        self._create_action_ui()
     

    def _create_activation_condition_tab(self):
        # Create widget to place inside the tab
        import gremlin.ui.ui_activation_condition


        self.activation_condition_tab_widget = QtWidgets.QWidget()
        self.activation_condition_tab_layout = QtWidgets.QVBoxLayout(self.activation_condition_tab_widget)
        #self.activation_condition_tab_widget.setContentsMargins(0,0,0,0)
        #self.activation_condition_tab_layout.setContentsMargins(0,0,0,0)

        # Create container condition widget
        self.activation_condition_widget = gremlin.ui.ui_activation_condition.ActivationConditionWidget(self.profile_data)
        self.activation_condition_widget.activation_condition_modified.connect(self.container_modified.emit)

        # Put everything together
        self.activation_condition_tab_layout.addWidget(self.activation_condition_widget)
        self.condition_tab_index = self.dock_tabs.addTab(self.activation_condition_tab_widget,"Conditions")


        # conditions for the actions in the container
        self.action_condition_frame_widget = gremlin.ui.ui_common.QBoxFrame()
        self.action_condition_frame_widget.setContentsMargins(0,0,0,0)
        
        
        border_color = gremlin.ui.ui_common.Color.borderColor()
        background_color = gremlin.ui.ui_common.Color.actionBackgroundColor()
        css = f"#frame {{ border 1px solid {border_color}; border-top: none; background-color:{background_color} }}"
        self.action_condition_frame_widget.setStyleSheet(css)

        self.activation_condition_layout = QtWidgets.QVBoxLayout(self.action_condition_frame_widget)
        self.activation_condition_layout.setContentsMargins(0,0,0,0)

        self.activation_count_widget = QtWidgets.QLabel()
        self.activation_condition_layout.addWidget(self.activation_count_widget)

        self.activation_condition_tab_layout.addWidget(self.action_condition_frame_widget)
        
        # create the action container widget
        # widgets are placed in activation_condition_layout
        self._create_condition_ui()
        self.activation_condition_layout.addStretch()
        self.activation_condition_tab_layout.addStretch()

        self._update_counts()

        self._update_selected(self.dock_tabs.currentIndex())

    def _update_condition_ui(self):
        ''' updates the condition UI tab only '''
        self.activation_condition_widget._update_conditions_ui()

    
    def _update_counts(self):
        ''' refreshes counts '''   
        
        if self.activation_count_widget:  # can get called before all is loaded
            if self.container:
                self.activation_count_widget.setText(f"Container conditions ({self.container.condition_count} found):")
            else:
                # not a container
                self.activation_count_widget.setText(f"Container conditions (N/A):")
        



    def _create_virtual_button_tab(self):
        # Return if nothing is to be done
        if not self.profile_data.virtual_button:
            return

        # Create widget to place inside the tab
        self.virtual_button_tab_widget = QtWidgets.QWidget()
        self.virtual_button_layout = QtWidgets.QVBoxLayout(
            self.virtual_button_tab_widget
        )

        # Create actual virtual button UI
        self.virtual_button_widget =  AbstractContainerWidget.virtual_axis_to_widget[type(self.profile_data.virtual_button)](self.profile_data.virtual_button)

        # Put everything together
        self.virtual_button_layout.addWidget(self.virtual_button_widget)
        self.dock_tabs.addTab(self.virtual_button_tab_widget, "Virtual Button")

        self.virtual_button_layout.addStretch(10)

    def _select_tab(self, view_type):
        if view_type is None or self.dock_tabs is None:
            return

        try:
            tab_title = ui_common.ContainerViewTypes.to_string(view_type).title()
            for i in range(self.dock_tabs.count()):
                if self.dock_tabs.tabText(i) == tab_title:
                    self.dock_tabs.setCurrentIndex(i)

        except gremlin.error.GremlinError:
            return
        
    def _update_selected(self, index):
        ''' selection state for the tab page'''
        widget : ActionSetView
        for i, widget in enumerate(self.action_widgets):
            widget.setSelected(i == index)

    def _tab_changed(self, index):
        ''' called when a device tab is selected '''
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_device
        verbose_detailed = config.verbose_mode_details
        try:
            if verbose: syslog.info(f"Device change begin")
            tab_text = self.dock_tabs.tabText(index)
            self.profile_data.current_view_type = ui_common.ContainerViewTypes.to_enum(tab_text.lower())
            self._update_selected(index)
        


        except gremlin.error.GremlinError:
            return
        finally:
            if verbose_detailed:
                syslog.info(f"Device change end")

    

    def _get_widget_index(self, widget):
        """Returns the zero based index of the provided widget.

        :param widget the widget for which to return the index
        :return the index of the provided widget, -1 if not present
        """
        index = -1
        for i, entry in enumerate(self.action_widgets):
            if entry == widget:
                index = i
        return index

    def _create_action_set_widget(self, action_set_data, label = None, view_type= ui_common.ContainerViewTypes.Action, icon = None, icon_size = 24):
        """Adds an action widget to the container.

        :param action_set_data: data of the actions which form the action set
        :param label the label:  to show in the title
        :param view_type visualization type
        :
        :return wrapped widget
        """
        action_set_model = ActionSetModel(action_set_data)
        
        action_set_view = ActionSetView(
            self.profile_data,
            label,
            view_type,
            icon,     
            icon_size,      
            parent = self
        )
        action_set_view.setModel(action_set_model)

        action_set_view.interacted.connect(lambda x: self._handle_interaction(action_set_view, x))

        # Store the view widget so we can use it for interactions later on
        self.action_widgets.append(action_set_view)

        return action_set_view

    def _container_remove(self):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def redrawActionSets(self):
        ''' redraws the action set widgets '''
        for widget in self.action_widgets:
            if Shiboken.isValid(widget):
                widget.redraw()

    def _copy_container(self, _):
        """Emits the copy clipboard when the widget is being copied """
        clipboard = Clipboard()
        container = self.profile_data

        # create a new container

        node = container.to_xml()

        
        xml = lxml.etree.tostring(node)
        encoder = ObjectEncoder(container, xml, container.name, EncoderType.Container)
        encoder.name = container.name
        clipboard.data = encoder
        #clipboard.data = self.profile_data
        verbose = gremlin.config.Configuration().verbose
        if verbose: syslog.info(f"container {self.profile_data.name} copied to clipboard")

    def _handle_interaction(self, widget, action):
        """Handles interaction with widgets inside the container.

        :param widget the widget on which the interaction is being carried out
        :param action the action being applied
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._handle_interaction not "
            "implemented in subclass"
        )

    def _create(self, action_data = None):
        # optional override by subclasses - called before _create_action_ui
        pass
        
    def _create_action_ui(self):
        """Creates the UI elements for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._create_basic_ui not "
            "implemented in subclass"
        )

    def _create_condition_ui(self):
        """Creates the UI elements for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._create_condition_ui not "
            "implemented in subclass"
        )
    
    def _update_condition_ui(self):
        ''' updates the condition UI for the widget '''
        pass

    def _get_window_title(self):
        """Returns the title to show on the widget."""
        # container name
        return self.profile_data.name


class AbstractActionWidget(QtWidgets.QFrame):

    """Base class for all widgets representing actions from the profile
    module."""

    # Signal which is emitted whenever the widget's contents change
    action_modified = Signal()

    def __init__(
            self,
            action_data,
            layout_type=QtWidgets.QVBoxLayout,
            parent=None
    ):
        """Creates a new instance.

        :param action_data the sub-classed AbstractAction instance
            associated with this specific action.
        :param layout_type type of layout to use for the widget
        :param parent parent widget
        """

        import gremlin.ui.ui_common
        import gremlin.util
        QtWidgets.QFrame.__init__(self, parent)

        css = f"background-color: {gremlin.ui.ui_common.Color.actionBackgroundColor()}"
        self.setStyleSheet(css) 

        self.action_data = action_data

        self.main_layout = layout_type(self)

        eh = gremlin.event_handler.EventListener()
        # eh.profile_unload.connect(self._cleanup_ui)
        eh.action_delete.connect(self._action_delete)


        self._create(action_data)
        self._create_ui()
        self._populate_ui()

    @QtCore.Slot(object)
    def _action_delete(self, input_item, container, action):
        if self.action_data._id is not None and self.action_data._id == action._id and hasattr(self, "_cleanup_ui"):
            self._cleanup_ui()
            
    def _create(self, action_data = None):
        ''' called before create_UI if present '''
        pass


    def _create_ui(self):
        """Creates all the elements necessary for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractActionWidget._create_ui not implemented in subclass"
        )
    

    def _populate_ui(self):
        """Updates this widget's representation based on the provided
        AbstractAction instance.
        """
        raise gremlin.error.MissingImplementationError(
            "ActionWidget._populate_ui not implemented in subclass"
        )

    def _get_input_type(self):
        """Returns the input type this widget's action is associated with.

        :return InputType corresponding to this action
        """
        return self.action_data.hardware_input_type
    
    def _get_device_id(self):
        ''' returns the device ID of the input associated with the action '''
        return self.action_data.hardware_device_guid
    
    def _get_input_id(self):
        ''' gets the input id for the input associated with the action '''
        return self.action_data.hardware_input_id

    


    def _get_profile_root(self):
        """Returns the root of the entire profile.

        :return root Profile instance
        """

        return gremlin.shared_state.current_profile        
        
    
    @property
    def is_running(self):
        ''' true if the profile is running '''
        return gremlin.shared_state.is_running

   
class AbstractActionWrapper(QtWidgets.QDockWidget):

    """Base class for all action widget wrappers.

    The specializations of this class will be used to contain an action
    widget while rendering the UI components needed for a specific view.
    """

    def __init__(self, action_widget, parent=None):
        """Wrapes a widget inside a docking container.

        :param action_widget the action widget to wrap
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.action_widget = action_widget

        # Create widget sitting in the root of the dock element
        self.dock_widget = QtWidgets.QFrame()
        self.dock_widget.setFrameShape(QtWidgets.QFrame.Box)
        self.dock_widget.setObjectName("frame")
        border_color = gremlin.ui.ui_common.Color.borderColor()
        background_color = gremlin.ui.ui_common.Color.actionBackgroundColor()
        css = f"#frame {{ border 1px solid {border_color}; border-top: none; background-color:{background_color} }}"
        self.dock_widget.setStyleSheet(css)
        self.setWidget(self.dock_widget)

        # Create default layout
        self.main_layout = QtWidgets.QVBoxLayout(self.dock_widget)


class TitleBarButton(QtWidgets.QAbstractButton):

    """Button usable in the titlebar of dock widgets."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

    def sizeHint(self):
        """Returns the ideal size of this widget.

        :return ideal size of the widget
        """
        self.ensurePolished()

        size = 2 * self.style().pixelMetric(
            QtWidgets.QStyle.PM_DockWidgetTitleBarButtonMargin
        )



        if not self.icon().isNull():
            icon_size = self.style().pixelMetric(
                QtWidgets.QStyle.PM_SmallIconSize
            )
            sz = self.icon().actualSize(QtCore.QSize(icon_size, icon_size))
            size += max(sz.width(), sz.height())

        if size < 12: size = 12

        return QtCore.QSize(size, size)

    def enterEvent(self, event):
        """Handles the event of the widget being entered.

        :param event the event to handle
        """
        if self.isEnabled():
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Handles the event of leaving the widget.

        :param event the event to handle
        """
        if self.isEnabled():
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        """Render the widget based on its current state.

        :param event the rendering event
        """

        # syslog.info("title paint start")
        p = QtGui.QPainter(self)

        options = QtWidgets.QStyleOptionToolButton()
        options.initFrom(self)
        options.state |= QtWidgets.QStyle.State_AutoRaise

        if self.style().styleHint(QtWidgets.QStyle.SH_DockWidget_ButtonsHaveFrame):
            if self.isEnabled() \
                    and self.underMouse() \
                    and not self.isChecked() \
                    and not self.isDown():
                options.state |= QtWidgets.QStyle.State_Raised
            if self.isChecked():
                options.state |= QtWidgets.QStyle.State_On
            if self.isDown():
                options.state |= QtWidgets.QStyle.State_Sunken
            self.style().drawPrimitive(
                QtWidgets.QStyle.PE_PanelButtonTool,
                options,
                p,
                self
            )

        options.icon = self.icon()
        options.subControls = QtWidgets.QStyle.SC_None
        options.activeSubControls = QtWidgets.QStyle.SC_None
        options.features = QtWidgets.QStyleOptionToolButton.None_
        options.arrowType = QtCore.Qt.NoArrow
        size = self.style().pixelMetric(
            QtWidgets.QStyle.PM_SmallIconSize
        )
        if size < 12: size = 12
        options.iconSize = QtCore.QSize(size, size)
        self.style().drawComplexControl(
            QtWidgets.QStyle.CC_ToolButton, options, p, self
        )

        p.end()

        # syslog.info("title paint end")


class TitleBar(QtWidgets.QWidget):

    """Represents a titlebar for use with dock widgets.

    This titlebar behaves like the default DockWidget title bar with the
    exception that it has a "help" button which will display some information
    about the content of the widget.
    """

    def __init__(self, label, hint, close_callback, clipboard_cb = None, parent=None, data = None):
        """Creates a new instance.

        :param label the label of the title bar
        :param hint the hint to show if needed
        :param close_cb the function to call when closing the widget
        :param clipboard_cb the function to call for clipboard operations (optional)
        :param parent the parent of this widget
        """
        import gremlin.ui.ui_common
        import gremlin.shared_state
        import gremlin.config
        import gremlin.event_handler
        import gremlin.util
        super().__init__(parent)

        el = gremlin.event_handler.EventListener()
        el.show_container_id_changed.connect(self._show_container_id_changed)
        
        config = gremlin.config.Configuration()

        self._id_value = None

        self.hint = hint
        width = gremlin.ui.ui_common.get_text_width(label)
        if width > 200:
            fm =  QtGui.QFontMetrics(QtGui.QFont())
            e_label = fm.elidedText(label, QtCore.Qt.ElideRight, 200)
        else:
            e_label = label
        self.label = QtWidgets.QLabel(e_label)
        self._close_callback = close_callback
        size = 12

        widget, layout = gremlin.ui.ui_common.getHContainer()
        self.extra_widget = widget
        self.extra_layout = layout
        
        # help button
        self.help_button = TitleBarButton()

        icon_help = load_icon("mdi.help")
        pixmap_help = icon_help.pixmap(size, size) # load_pixmap(icon_help)
        if not pixmap_help or pixmap_help.isNull():
            self.help_button.setText("?")
        else:
            icon = QtGui.QIcon()
            pixmap_help = pixmap_help.scaled(size, size, QtCore.Qt.KeepAspectRatio)
            icon.addPixmap(pixmap_help, QtGui.QIcon.Normal)
            self.help_button.setIcon(icon)
        self.help_button.setToolTip("Help")

        self.help_button.clicked.connect(self._show_hint)

        # close button
        self.close_button = TitleBarButton()
        close_icon = load_icon("mdi.delete")

        pixmap_close = close_icon.pixmap(size,size) # load_pixmap("gfx/close.png")
        if not pixmap_close or pixmap_close.isNull():
            self.close_button.setText("X")
        else:
            icon = QtGui.QIcon()
            pixmap_close = pixmap_close.scaled(size, size, QtCore.Qt.KeepAspectRatio)
            icon.addPixmap(pixmap_close, QtGui.QIcon.Normal)
            self.close_button.setIcon(icon)
        self.close_button.setToolTip("Delete")

        self.close_button.clicked.connect(self._delete_cb)

        # clipboard copy button - only if a handler is given
        if clipboard_cb:
            self.copy_button = TitleBarButton()
            copy_icon = gremlin.ui.ui_common.Icons.copyIcon() 
            pixmap_copy = load_pixmap(copy_icon)
            icon = QtGui.QIcon()
            pixmap_copy = pixmap_copy.scaled(size, size, QtCore.Qt.KeepAspectRatio)
            icon.addPixmap(pixmap_copy, QtGui.QIcon.Normal)
            self.copy_button.setIcon(icon)
            self.copy_button.clicked.connect(clipboard_cb)
            self.copy_button.setToolTip("Copy")

        if data is not None and hasattr(data,"id") and config.show_container_id:
            self.id_widget = gremlin.ui.ui_common.QDataLineEdit(width=100)
            self.id_widget.setReadOnly(True)
            self.id_widget.data = data
            self.setIdValue(data.id)
        else:
            self.id_widget = None


        self.comment_widget = gremlin.ui.ui_common.QDataLineEdit()
        self.comment_widget.data = data
        if hasattr(data,"comment"):
            self.comment_widget.setText(data.comment)
        self.comment_widget.textChanged.connect(self._comment_changed)


        if hasattr(data,"priority"):
            self.priority_widget = gremlin.ui.ui_common.QIntLineEdit(data,min_range=0, max_range=1000,value = data.priority,chars=4)
            self.priority_widget.setToolTip("Execution priority.  Lower priority runs first.")
            self.priority_widget.valueChanged.connect(self._priority_changed)
            self.priority_container = gremlin.ui.ui_common.getHContainer(self.priority_widget,"Priority", widget_only = True, right_stretch=False, left_stretch=False)
        else:
            self.priority_widget = None
            self.priority_container = None


        widgets = [
            self.label,
            self.id_widget,
            "||",
            self.priority_container,
            "Notes:",
            self.comment_widget,
            self.extra_widget,
            self.copy_button if clipboard_cb else None,
            self.help_button,
            self.close_button
        ]
        
        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True, right_stretch=False, left_stretch=False)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(widget)

        # self.main_layout.setContentsMargins(5, 0, 5, 0)

        # self.main_layout.addWidget(self.label)
        # self.main_layout.addWidget(self.id_widget)
        # if self.priority_container:
        #     self.main_layout.addWidget(self.priority_container)
        # self.main_layout.addWidget(QtWidgets.QLabel("Notes:"))
        # self.main_layout.addWidget(self.comment_widget)
        # self.main_layout.addStretch()
        # self.main_layout.addWidget(self.extra_widget)

        # if clipboard_cb:
        #     self.main_layout.addWidget(self.copy_button)

        # self.main_layout.addWidget(self.help_button)
        # self.main_layout.addWidget(self.close_button)



        self._show_container_id_changed_ui()

    def setIdVisible(self, visible : bool):
        if self.id_widget and Shiboken.isValid(self.id_widget):
            if visible:
                self.id_widget.setText(self._id_value)
            else:
                self.id_widget.setText(None)

    def setIdValue(self, value : str):
        self._id_value = value
        self._show_container_id_changed()

    def _show_container_id_changed(self):
        gremlin.util.InvokeUiMethod(self._show_container_id_changed_ui)
    
    def _show_container_id_changed_ui(self):
        ''' display/hide container Ids on config change'''
        config = gremlin.config.Configuration()
        visible = config.show_container_id
        self.setIdVisible(visible)
        

    @QtCore.Slot()
    def _comment_changed(self):
        ''' called when comment text is changed '''
        widget = self.sender()
        data = widget.data
        data.comment = widget.text()

    def _priority_changed(self, value):
        widget = self.sender()
        data = widget.data
        data.setPriority(value)


    def _show_hint(self):
        """Displays a hint, explaining the purpose of the action."""
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            self.hint
        )

    def _delete_cb(self):
        ''' called on delete button '''
        if self._close_callback:
            self._close_callback()




class BasicActionWrapper(AbstractActionWrapper):

    """Wraps an action widget and displays the basic config dialog."""

    # Signal which is emitted whenever the widget is closed
    closed = QtCore.Signal(QtWidgets.QWidget)

    def __init__(self, action_widget, parent=None):
        """Wraps an existing action widget.

        :param action_widget the action widget to wrap
        :param parent the parent of the widget
        """
        super().__init__(action_widget, parent)

        mode = action_widget.action_data.get_mode()
        self.action_widget = action_widget

        action = self.action_widget.action_data
        if hasattr(action,"hint"):
            hint = action.hint
        else:
            hint = gremlin.hints.hint.get(action.tag, "")  

        self._title_bar_widget = TitleBar(
            f"{action_widget.action_data.name} ({mode})",
            hint,
            self._remove,
            self._clipboard_copy,
            data = action_widget.action_data)


        self.title_frame_widget = gremlin.ui.ui_common.QBorderWidget()
        self.title_frame_widget.addWidget(self._title_bar_widget)

        
        self.title_frame_widget.setBackgroundColor(gremlin.ui.ui_common.Color.actionBackgroundColor())
        self.setTitleBarWidget(self.title_frame_widget)

        self.main_layout.addWidget(self.action_widget)

        gremlin.util.singleShot(self._config_visible)

    def _config_visible(self):
        if not Shiboken.isValid(self):
            return
        config = gremlin.config.Configuration()
        self._title_bar_widget.setIdVisible(config.show_container_id)

    def _remove(self):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def _cleanup_ui(self):
        ''' cleans the object '''
        # if hasattr(self.action_widget, "_cleanup_ui"):
        #     self.action_widget._cleanup_ui()
        gremlin.util.clear_layout(self.main_layout)

    def _clipboard_copy(self, _):
        ''' clipboard copy event '''
        clipboard = Clipboard()
        action =  self.action_widget.action_data
        node = action.to_xml()
        xml = lxml.etree.tostring(node)
        encoded =  ObjectEncoder(action, xml, action.name, EncoderType.Action)
        #clipboard.data = action
        clipboard.data = encoded
        syslog.info(f"copy to clipboard: {action.name}")


class ConditionActionWrapper(AbstractActionWrapper):

    """Wraps an action widget and displays the condition config dialog."""

    def __init__(self, action_widget, parent=None):
        """Wraps an existing action widget.

        :param action_widget the action widget to wrap
        :param parent the parent of the widget
        """
        super().__init__(action_widget, parent)
        import gremlin.ui.ui_activation_condition as ui_activation_condition

        # Disable all dock features and give it a title
        self.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        title = f"{action_widget.action_data.name}"
        if action_widget.action_data.comment:
            title += f" ({action_widget.action_data.comment})"
        self.setWindowTitle(title)

        # Setup activation condition UI
        container = self.action_widget.action_data
        # if action_data.parent.has_action_conditions:
        if container.activation_condition is None:
            container.activation_condition = gremlin.base_conditions.ActivationCondition([],gremlin.types.ActivationRule.All)
            container.activation_condition.setContainer(container)

        self.condition_model = ui_activation_condition.ConditionModel(
            container,
            container.activation_condition
        )
        self.condition_view = ui_activation_condition.ConditionView()
        container.condition_view = self.condition_view
        self.condition_view.setContainer(container)
        self.condition_view.setModel(self.condition_model)
        self.condition_view.redraw()
        self.main_layout.addWidget(self.condition_view)
        # else:
        #     action_data.activation_condition = None




class ActionContainerModel(gremlin.ui.ui_common.AbstractModel):

    """Stores action containers for display using the corresponding view."""

    def __init__(self, containers, item_data : InputItemMappingWidget = None, input_type: InputType = None, parent=None):
        """Creates a new instance.

        :param containers: the container instances of this model
        :param item_data: the input mapping data (InputItemMappingWidget)
        :param input_type: the override input type if different from the input item configuration
        :param parent: the parent of this widget
        """
        super().__init__(parent)
        self._containers = containers
        self._item_data = item_data
        self._input_type = input_type if input_type is not None else item_data._input_type

    @property
    def item_data(self) -> InputItemMappingWidget:
        ''' get the item data associated with this action container '''
        return self._item_data
    
    @property
    def input_type(self) -> InputType:
        return self._input_type
    
    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows in the model
        """
        return len(self._containers)

    def data(self, index):
        """Returns the data stored at the given location.

        :param index the location for which to return data
        :return the data stored at the requested location
        """
        assert len(self._containers) > index
        return self._containers[index]

    def add_container(self, container):
        """Adds a container to the model.

        :param container the container instance to be added
        """
        self._containers.append(container)
        self.data_changed.emit()

    def remove_container(self, container):
        """Removes an existing container from the model.

        :param container the container instance to remove
        """
        el = gremlin.event_handler.EventListener()
        if container in self._containers:
            # notify actions that the container is closing
            for action_set in container.action_sets:
                if action_set:
                    for action in action_set:
                        if hasattr(action,"actionDeleted"):
                            action.actionDeleted()
                        el.action_delete.emit(self._item_data, container, action)


            self._containers.remove(container)

            # self._item_data.remove_container(container)
            
            self.data_changed.emit()
            el.container_delete.emit(self.item_data, container)
            el.mapping_changed.emit(self.item_data)


    def remove_all_containers(self):
        """Removes an existing container from the model.

        :param container the container instance to remove
        """
        el = gremlin.event_handler.EventListener()
        container_list = [container for container in self._containers]
        for container in container_list:
            # notify actions that the container is closing
            for action_set in container.action_sets:
                for action in action_set:
                    # if hasattr(action, "_cleanup"):
                    #     action._cleanup()
                    el.action_delete.emit(self._item_data, container, action)

            el.container_delete.emit(self.item_data, container)
            del self._containers[self._containers.index(container)]

        self.data_changed.emit()
        el.mapping_changed.emit(self.item_data)
        


class ActionContainerView(gremlin.ui.ui_common.AbstractView):

    """View class used to display ActionContainerModel contents."""

    def __init__(self, parent=None):
        """Creates a new view instance.

        :param parent the parent of the widget
        """
        super().__init__(parent)

        # Create required UI items
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self._redraw_lock = False
        self._deleted = False

        self.input_item = None

        self.scroll_area = QtWidgets.QScrollArea()

        # Configure the widget holding the layout with all the buttons
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Configure the scroll area
        #self.scroll_area.setMinimumWidth(300)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = None
        self.scroll_layout = None

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_area)

        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: syslog.info(f"create actioncontainerview [{parent.item_data.debug_display}]")

        self._widgets = []

    def _cleanup_ui(self):
        ''' widget cleanup '''
        self._deleted = True
        self._clear_widgets()

    def _clear_widgets(self):
        ''' clears the widgets '''
        widgets = gremlin.util.get_layout_widgets(self.scroll_layout)
        if widgets:
            for widget in widgets:
                if hasattr(widget,"_cleanup_ui"):
                    widget._cleanup_ui()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            self._widgets.clear()

        if self.scroll_widget:
            self.scroll_widget.hide()
            self.scroll_widget.deleteLater()

        self.scroll_widget, self.scroll_layout = gremlin.ui.ui_common.getVContainer()
        self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.scroll_area.setWidget(self.scroll_widget)



    def redraw(self):
        gremlin.util.InvokeUiMethod(self._redraw_ui) # ensure on UI thread

    def _redraw_ui(self):
        """Redraws the entire view.  must be on UI thread"""
        import gremlin.util
        import gremlin.ui.ui_common

        if not Shiboken.isValid(self):
            return

        if not Shiboken.isValid(self.scroll_area):
            return
        
        if self._redraw_lock:
            return
        
        self._redraw_lock = True
        try:
            #with self.model.data_changed.blocked():
            with QtCore.QSignalBlocker(self.model):
                self._clear_widgets()
                container_count = self.model.rows()    
                if container_count:
                    for index in range(container_count):
                        widget = self.model.data(index).widget(self.model.data(index))
                        widget.closed.connect(self._create_closed_cb(widget))
                        widget.container_modified.connect(self.model.data_changed.emit)
                        self.scroll_layout.addWidget(widget)
                        self._widgets.append(widget)
                        
                else:
                    # input_type = self.model.input_type # InputType.JoystickAxis
                    label = QtWidgets.QLabel(f"Please add an action or container for {self.model.item_data.display_name}") # ({InputType.to_display_name(input_type)})")
                    
                    widget = gremlin.ui.ui_common.getVContainer(label, widget_only = True)
                    widget.setContentsMargins(4,4,4,4)
                    #widget.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
                    self.scroll_layout.addWidget(widget)
                self.scroll_layout.addStretch()
        finally:
            self._redraw_lock = False

        # gremlin.util.singleShot(lambda: self.doLayout())

    def _create_closed_cb(self, widget):
        """Create callbacks to remove individual containers from the model.

        :param widget the container widget to be removed
        :return callback function to remove the provided widget from the
            model
        """

        return lambda: self.model.remove_container(widget.profile_data)
    


class InputItemMappingWidget(QtWidgets.QWidget):

    """ mapping viewer for a selected input item (this is the right side of the device tab) - right panel widgets """

    # Signal emitted when the description changes
    description_changed = Signal(str) # indicates the description was changed
    description_clear = Signal() # clear the description field

    def __init__(self, item_data, input_type = None, object_name : str = None, spacer_height = 32, parent=None):
        """Creates a new object instance.

        :params:
         
        item_data =profile data associated with the item, can be none to display an empty box
        input_type = override input type if the input type is not that of the item_data (InputItem) - controls what containers/actions are available
        spacer_height = hack margin at top
        parent = the parent of this widget

        """
        super().__init__(parent)

        assert item_data is not None,"Item Data must be provided"
        
        # self.setObjectName(object_name if object_name else "(object name not provided)")
        self.id = gremlin.util.get_guid()
        self.setObjectName(object_name if object_name else f"InputItemMappingWidget#{item_data.display_name}")
        
        self.item_data : gremlin.base_profile.InputItem = item_data
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.container_widget = None

        self._spacer_height = spacer_height


        # widget = QtWidgets.QWidget()
        # self.main_layout = QtWidgets.QVBoxLayout(widget)
        # obj_name = f"C_{self.id}"
        # widget.setObjectName(obj_name)
        
        #main_layout.addWidget(widget)

        

        # self.container_widget = None
        #css = f"QWidget#{obj_name} {{background: #050505; border-color:red; border: 5px;}}"
        # css = "border: none;"
        # css = "border: 5px;"
        # syslog.info(css)
        # self.setStyleSheet(css)


        self.container_view = None
        self.profile_mode = self.item_data.profile_mode
        
        self._input_type = InputType.NotSet
        if input_type is not None:
            # override input type
            self._input_type = input_type
        else:
            if item_data is not None and hasattr(item_data,"input_type"):
                self._input_type = item_data.input_type

        self.action_model = ActionContainerModel(self.item_data.containers, self.item_data, self._input_type)
        self.container_view = ActionContainerView(self)
        self.container_view.input_item = self.item_data
        self.container_view.setContentsMargins(0,0,0,0)
        self.container_view.setModel(self.action_model)


        self.setItemData(item_data)

        el = gremlin.event_handler.EventListener()
        el.mapping_changed.connect(self._mapping_changed)
     
        self._deleted = False

      


    def _mapping_changed(self, item_data):
        ''' occurs when a device mapping changed through user interaction with the UI '''
        from gremlin.event_handler import DeviceChangeEvent
        if item_data != self.item_data:
            # not ours
            return
        self.refresh()
        
        el = gremlin.event_handler.EventListener()
        el.update_action_icons.emit(item_data)
            
        



    def isBlank(self):
        ''' true if not associated with any data (blank widget)'''
        return self.item_data is None

    def _cleanup_ui(self):
        ''' called when widget is deleted '''
        self._deleted = True
        if self.container_view:
            self.container_view._cleanup_ui()
            self.container_view = None

    @property
    def deleted(self):
        return self._deleted
    
    
    def refresh(self):
        ''' refreshes the current content with any changes '''
        gremlin.util.InvokeUiMethod(self._refresh_ui)

    def _refresh_ui(self):
        ''' refresh on ui thread'''
        self.setItemData(None)


    def setItemData(self, item_data):
        ''' updates the item data '''

        from gremlin.ui.joystick_device import JoystickDeviceTabWidget
        assert gremlin.util.is_ui_thread()
        if not Shiboken.isValid(self):
            return

        if item_data is None:
            assert self.item_data, "Device data must be provided"
            item_data = self.item_data
        
        self.setUpdatesEnabled(False)
        try:

            if self.container_widget:
                self.container_widget.setParent(None) # remove from container
                self.main_layout.removeWidget(self.container_widget)
                
            self.container_widget = QtWidgets.QWidget()
            self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)
            self.main_layout.addWidget(self.container_widget)
            self.container_widget.setContentsMargins(0,0,0,0)
            self.container_layout.setContentsMargins(0,0,0,0)


            spacer = QtWidgets.QLabel(" ")
            spacer.setFixedHeight(self._spacer_height)
            self.container_layout.addWidget(spacer)

            # self.container_layout.addWidget(QtWidgets.QLabel("C0"))

            

            self.item_data : gremlin.base_profile.InputItem = item_data

            config = gremlin.config.Configuration()
            if config.show_container_id:

                # debug containter type
                widgets = []
                label = QtWidgets.QLabel(f"Mode: [{self.item_data.profile_mode if self.item_data.profile_mode else "N/A"}]")
                widgets.append(label)

                input_id = None
                if self.item_data:
                    input_id = self.item_data.input_id
                    raw_input_type = self.item_data.getRawInputType()
                    input_type = self.item_data.getInputType()
                    if raw_input_type != input_type:
                        # override used
                        label_name = f"Input Type: (override) {input_type.name}"
                    else:
                        label_name = f"Input Type: {input_type.name}"

                    
                else:
                    label_name = f"Input Type: N/A"
                

                label = QtWidgets.QLabel(label_name)
                widgets.append(label)
                if input_id is not None:
                    width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
                    line_edit = gremlin.ui.ui_common.QDataLineEdit()
                    line_edit.setMinimumWidth(width)
                    line_edit.setText(str(input_id) if isinstance(input_id, int) else gremlin.util.normalize_guid(input_id.id))
                    line_edit.setReadOnly(True)
                    widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Input Id:", widget_only = True)
                    widgets.append(widget)
                
                widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)

                name = self.objectName()
                css = "background: green;"
                if not name:
                    if item_data:
                        name = f"InputItemConfig for: {self.item_data.display_name}"
                        css = "background: gray;"
                if not name:
                    name = "(name not available)"
                    css = "background: red;"

                label_name = QtWidgets.QLabel(name)

                id_label = QtWidgets.QLabel(f"({self.id})")
                label_name.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
                label_name.setStyleSheet(css)
                widgets.append(label_name)
                widgets.append(id_label)
                
                widget, layout = gremlin.ui.ui_common.getHContainer(widgets)

                # self.container_layout.addWidget(QtWidgets.QLabel("C1"))
                self.container_layout.addWidget(widget)
                # self.container_layout.addWidget(QtWidgets.QLabel("C2"))

            if item_data is None:
                parent = self.parent()
                while parent and not isinstance(parent, JoystickDeviceTabWidget):
                    parent = self.parent()
                parent :JoystickDeviceTabWidget
                if parent is not None:
                    item_data = parent.last_item_data_key

                if item_data is None:
                    self._blank_input()
                    return
            


         
            
            if not item_data.is_action:
                # only draw description if not a sub action item
                self._create_description()


            if self.item_data.device_type == DeviceType.VJoy:
                self._create_vjoy_dropdowns()
            else:
                self._create_mapping_toolbar()

            self.action_model = ActionContainerModel(self.item_data.containers, self.item_data, self._input_type)
            self.container_view = ActionContainerView(self)
            self.container_view.input_item = self.item_data
            self.container_view.setContentsMargins(0,0,0,0)
            self.container_view.setModel(self.action_model)

            
            self.container_layout.addWidget(self.container_view)

            # setup the container widget reference
            plugin_manager = gremlin.plugin_manager.ContainerPlugins()
            plugin_manager.set_widget(self.item_data, self)


        finally:
            pass
            self.setUpdatesEnabled(True)
            self.container_view.redraw()
            self.update()


        # self.container_layout.addWidget(QtWidgets.QLabel("C11"))


    def _add_action(self, action_name):
        """Adds a new action to the input item.

        :param action_name name of the action to be added
        """
        import container_plugins.basic
        import gremlin.plugin_manager
        import gremlin.ui.ui_common

        gremlin.util.pushCursor()

        try:

            # If this is a vJoy item then do not permit adding an action if
            # there is already one present, as only response curves can be added
            # and only one of them makes sense to exist
            if self.item_data.get_device_type() == DeviceType.VJoy:
                if len(self.item_data.containers) > 0:
                    return
                
            
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            container = container_plugins.basic.BasicContainer(self.item_data)
            action = plugin_manager.get_class(action_name)(container)

            if action.singleton:
                # action can only exist once in the container list
                if self.item_data.is_action:
                    gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add [{action_name}].  The action cannot be added to a sub-container.")    
                    return
                if self.item_data.hasAction(action_name):
                    gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add: [{action_name}]. The action can only appear once per input.")
                    return 


            container.add_action(action)
        
            if len(container.action_sets) > 0:
                self.action_model.add_container(container)
            
            self.action_model.data_changed.emit()

            el = gremlin.event_handler.EventListener()
            el.mapping_changed.emit(self.item_data)
            self.notify_changed()
        finally:
            gremlin.util.popCursor()

    def notify_changed(self):
        ''' notifies the item has changed'''
        
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = self.item_data.device_guid
        event.device_name = self.item_data.device_name
        event.device_input_type = self.item_data.input_type
        event.device_input_id = self.item_data.input_id
        event.vjoy_id = 0
        event.vjoy_input_id = 0
        event.source = self.item_data
        el.profile_device_changed.emit(event)
        el.icon_changed.emit(event)


    def _paste_action(self, data_or_action, container):
        """ paste action to the input item """
        import container_plugins.basic
        import gremlin.plugin_manager
        import gremlin.base_profile


        if self.item_data.get_device_type() == DeviceType.VJoy:
            if len(self.item_data.containers) > 0:
                return
            
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_tag_map = plugin_manager.tag_map

            
        if isinstance(data_or_action, ObjectEncoder):
            oc = data_or_action
            if oc.encoder_type == EncoderType.Action:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                action_tag = node.tag
                if action_tag in action_tag_map:
                    action_name = action_tag_map[action_tag]
                    container = container_plugins.basic.BasicContainer(self.item_data)
                    action_item = action_name(container)
                    action_item.setId(gremlin.util.get_guid())
            else:
                # not an action type, ignore
                return

        elif isinstance(data_or_action, gremlin.base_profile.AbstractAction):
            action = data_or_action
            container = container_plugins.basic.BasicContainer(self.item_data)
            action_item = plugin_manager.duplicate(action, container )
        else:
            # nothing to do
            return
        
        # remap inputs
        action_item.update_inputs(self.item_data)
        container.add_action(action_item)
        
        if len(container.action_sets) > 0:
            self.action_model.add_container(container)
        self.action_model.data_changed.emit()

        eh = gremlin.event_handler.EventListener()
        eh.mapping_changed.emit(self.item_data)
        self.notify_changed()

    def _add_container(self, container_name):
        """Adds a new container to the input item.

        :param container_name name of the container to be added
        """

        gremlin.util.pushCursor()
        try:

            plugin_manager = gremlin.plugin_manager.ContainerPlugins()
            container = plugin_manager.get_class(container_name)(self.item_data)
            if hasattr(container, "action_model"):
                container.action_model = self.action_model
            self.action_model.add_container(container)
            plugin_manager.set_container_data(self.item_data, container)

            eh = gremlin.event_handler.EventListener()
            eh.mapping_changed.emit(self.item_data)
        finally:
            gremlin.util.popCursor()

        return container
    
    def _copy_container(self):
        ''' copies all containers to the clipboard '''
        if len(self.item_data.containers) > 0:
            clipboard = Clipboard()
            
            root = lxml.etree.Element("multi_containers")
            for container in self.item_data.containers:
                 node = container.to_xml()
                 root.append(node)
            xml = lxml.etree.tostring(root)
            # debug
            # filename = gremlin.util.save_xml("copy_container.xml", root)
            # gremlin.util.display_file(filename)
            encoded = ObjectEncoder(self.item_data.containers, xml, "multi", EncoderType.MultiContainer)
            clipboard.data = encoded
            syslog.info(f"multi container copied to clipboard")
    

    def _save_container_to_template(self, item):
        input_item : gremlin.base_profile.InputItem = item
        ''' saves a mapping set to a template '''
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save template",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )

        if fname:
            root = etree.Element("container_template")
            # get the xml for every container in the mapping
            for container in input_item.containers:
                node = container.to_xml()
                root.append(node)
            # save the xml
            tree = etree.ElementTree(root)
            try:
                if os.path.isfile(fname):
                    # blitz existing file
                    os.unlink(fname)
                tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
            except:
                syslog.error(f"Error writing template to: {fname}")
                return False
            return True
        
        return False
    
    



    def _load_container_from_template(self, extra_data = None):
        ''' loads a container from a template '''
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Container template",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )
        if fname and os.path.isfile(fname):
            container_list = []
            plugin_manager = gremlin.plugin_manager.ContainerPlugins()
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            msg_list = []
            try:
                tree = etree.parse(fname, parser=parser)
                root = tree.getroot()
                if root.tag == "container_template":
                    # get root containers only
                    nodes = root.xpath("//container[not(ancestor::container)]")
                    for node in nodes:
                        container_type = node.get("type")
                        container_plugins = gremlin.plugin_manager.ContainerPlugins()
                        container_tag_map = container_plugins.tag_map

                        # verify the container is valid for the input type
                        valid_containers_names = self.item_data.get_valid_container_list()
                        if container_type in container_tag_map:
                            container_name = container_tag_map[container_type].name
                            if container_name in valid_containers_names:
                                new_container = container_tag_map[container_type](self.item_data)
                                new_container.from_xml(node, self.item_data, extra_data)
                                new_container.generateGuids() # replace IDs to avoid conflicts
                                container_list.append(new_container)
                        else:
                            msg = f"Container {container_type.name} is not valid for the current input"
                            msg_list.append(msg)
                            syslog.warning(msg)


                if msg_list:
                    prompt = "".join((msg + "\n" for msg in msg_list))
                    gremlin.ui.ui_common.MessageBox(title="Load Template", prompt = prompt)

            except:
                pass
            if container_list:
                for new_container in container_list:
                    if hasattr(new_container, "action_model"):
                        new_container.action_model = self.action_model
                    
                        plugin_manager.set_container_data(self.item_data, new_container)
                        self.action_model.add_container(new_container)
                    


                el = gremlin.event_handler.EventListener()
                el.mapping_changed.emit(self.item_data)
                self.notify_changed()


    @QtCore.Slot(object)
    def _paste_container(self, container, extra_data = None):
        """Adds a new container to the input item.

        :param container container to be added
        """
        import gremlin.base_profile
        el = gremlin.event_handler.EventListener()
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container_list = []

        # tracker = gremlin.base_conditions.ConditionTracker()
        import_data = gremlin.base_profile.ProfileImportData()
        verbose = gremlin.config.Configuration().verbose

        if not extra_data:
            extra_data = {}
        extra_data["paste"] = True # indicate paste mode for xml readers

        if isinstance(container, ObjectEncoder):
            oc = container
            valid_containers_names = self.item_data.get_valid_container_list()
            container_tag_map = plugin_manager.tag_map
            if oc.encoder_type == EncoderType.Container:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                container_type = node.get("type")
                # verify the container is valid for the input
                if container_type in container_tag_map:
                    container_name = container_tag_map[container_type].name
                    if container_name in valid_containers_names:
                        new_container = container_tag_map[container_type](self.item_data)
                        new_container.from_xml(node, data = self.item_data, extra_data = extra_data)
                        new_container.generateGuids()
                        if new_container.id in import_data.used_ids:
                            new_id = gremlin.util.get_guid()
                            if verbose: syslog.warning(f"PASTE: DUPLICATE ID:container {new_container.id} -> {new_id}")
                            new_container._id = new_id
                        import_data.used_ids[new_container.id] = new_container

                        container_list.append(new_container)

              

            elif oc.encoder_type == EncoderType.MultiContainer:
                xml = oc.data

                root = etree.fromstring(xml)
 
                for node in root:
                    container_type = node.get("type")

                    if container_type in container_tag_map:
                        container_name = container_tag_map[container_type].name
                        if container_name in valid_containers_names:
                            new_container = container_tag_map[container_type](self.item_data)
                            new_container.from_xml(node, data = self.item_data, extra_data = extra_data)
                            new_container.generateGuids()
                            if new_container.id in import_data.used_ids:
                                new_id = gremlin.util.get_guid()
                                if verbose: syslog.warning(f"PASTE: DUPLICATE ID:container {new_container.id} -> {new_id}")
                                new_container._id = new_id
                            import_data.used_ids[new_container.id] = new_container

                            container_list.append(new_container)


                            # debug
                            root = lxml.etree.Element("generate-guid-containers")
                            node = new_container.to_xml()
                            root.append(node)
                            # filename = gremlin.util.save_xml("container_new_id.xml", root)
                            # gremlin.util.display_file(filename)
                                                    



        else:
            new_container = plugin_manager.duplicate(container, self.item_data)
            new_container.generateGuids()
            container_list.append(new_container)


        if container_list:
            for new_container in container_list:
                if hasattr(new_container, "action_model"):
                    new_container.action_model = self.action_model
                
                    plugin_manager.set_container_data(self.item_data, new_container)
                    self.action_model.add_container(new_container)
                    



            
            el.mapping_changed.emit(self.item_data)
            self.notify_changed()

        return container_list
    

    




    
    def _delete_container(self):
        ''' call to delete all containers '''
        if not self.item_data.containers:
            # nothing to do
            return 
        # do a confirmation box just in case
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("This will remove the current container set and any actions.")
        message_box.setInformativeText("Are you sure?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Cancel | 
            QtWidgets.QMessageBox.StandardButton.Ok 
        )
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Cancel:
            return
        
        self.action_model.remove_all_containers()
            

    def _remove_container(self, container):
        """Removes an existing container from the InputItem.

        :param container the container instance to be removed
        """

        self.action_model.remove_container(container)


                

    def _create_description(self):
        """Creates the description input for the input item."""
        self.description_layout = QtWidgets.QHBoxLayout()
        self.description_layout.addWidget(
            QtWidgets.QLabel("Mapping Description:")
        )
        self.description_field = QtWidgets.QLineEdit()
        self.description_field.setText(self.item_data.description)
        self.description_field.textChanged.connect(self._edit_description_cb)
        self.description_layout.addWidget(self.description_field)
        self.description_field.setReadOnly(self.item_data.descriptionReadOnly)        
        self.description_clear_button = gremlin.ui.ui_common.Buttons.getEraserWidget(callback = self._delete_description_cb, tooltip="Reset description to default", width = 20, height = 20)
        self.description_layout.addWidget(self.description_clear_button)

        self.container_layout.addLayout(self.description_layout)


    def _create_mapping_toolbar(self):
        """Creates a drop down selection with actions that can be
        added to the current input item.
        """
        import gremlin.ui.input_item as input_item
        import gremlin.ui.ui_common as ui_common
        
        

        # check for an override for the inputs that can change types (such as OSC)
        input_type = self.item_data.getInputType()


        self.sync_widget = gremlin.ui.ui_common.Buttons.getListSyncWidget(callback = self._sync_list)

        self.action_selector = ui_common.ActionSelector(None, self.item_data)
        self.action_selector.inputItem = self.item_data
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)

        self.container_selector = input_item.ContainerSelector(input_type, self.item_data.is_axis, data = self.item_data)
        
        self.container_selector.container_added.connect(self._add_container)
        self.container_selector.container_copy.connect(self._copy_container)
        self.container_selector.container_paste.connect(self._paste_container)

        self.container_selector.container_from_template.connect(self._load_container_from_template)
        self.container_selector.container_to_template.connect(self._save_container_to_template)
        self.container_selector.container_delete.connect(self._delete_container)
        self.always_execute = QtWidgets.QCheckBox("Always execute")
        self.always_execute.setToolTip("If enabled, the mapping continues to process triggers even if the profile is paused.")
        self.always_execute.setChecked(self.item_data.always_execute)
        self.always_execute.stateChanged.connect(self._always_execute_cb)

        self.collapse_all_widget = gremlin.ui.ui_common.Buttons.getCollapseAllWidget(callback = self._handle_collapse_all)
        self.expand_all_widget = gremlin.ui.ui_common.Buttons.getExpandAllWidget(callback = self._handle_expand_all)

        widgets = [
                   self.sync_widget, 
                   self.action_selector,
                   self.container_selector,
                   self.collapse_all_widget,
                   self.expand_all_widget,
                   "|",
                   self.always_execute
                   ]

        self.dropdown_widget, self.dropdown_layout = gremlin.ui.ui_common.getHContainer(widgets)
        self.container_layout.addWidget(self.dropdown_widget)
        desired_width = self.dropdown_widget.sizeHint().width()
        self.dropdown_widget.setMinimumWidth(desired_width)
        
    def _sync_list(self):
        input_item = self.item_data
        el = gremlin.event_handler.EventListener()
        el.sync_input.emit(input_item)
        

    def _handle_collapse_all(self):
        ''' collapses all containers '''
        el = gremlin.event_handler.EventListener()
        el.collapse_all_containers.emit()

    def _handle_expand_all(self):
        ''' expands all containers '''
        el = gremlin.event_handler.EventListener()
        el.expand_all_containers.emit()

    def updateSelectors(self, input_type, item_data):
        self.action_selector.refresh(input_type, item_data)
        self.container_selector.refresh(input_type, item_data)
    

    def _create_vjoy_dropdowns(self):
        """Creates the action drop down selection for vJoy devices."""
        self.action_selector_widget = QtWidgets.QWidget()
        self.action_selector_layout = QtWidgets.QHBoxLayout(self.action_selector_widget)

        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            gremlin.types.DeviceType.VJoy,
            None,
            parent = self.action_selector_widget,
            
        )
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)
        self.action_selector_layout.addWidget(self.action_selector)
        self.container_layout.addWidget(self.action_selector_widget)

    @QtCore.Slot()
    def _edit_description_cb(self, text):
        """Handles changes to the description text field.

        :param text the new contents of the text field
        """
        self.item_data.description = text
        self.description_changed.emit(text)

    @QtCore.Slot()
    def _delete_description_cb(self):
        """ deletes the description text.

        :param text the new contents of the text field
        """
        self.item_data.description = None
        self.description_clear.emit()

    def _always_execute_cb(self, state):
        """Handles changes to the always execute checkbox.

        :param state the new state of the checkbox
        """
        self.item_data.always_execute = self.always_execute.isChecked()

    def _valid_action_names(self):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        action_names = []
        if self.item_data.input_type == gremlin.types.DeviceType.VJoy:
            entry = gremlin.plugin_manager.ActionPlugins().repository.get(
                "response-curve-ex",
                None
            )
            if entry is not None:
                action_names.append(entry.name)
            else:
                raise gremlin.error.GremlinError(
                    "Response curve plugin is missing"
                )
        else:
            for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
                if self.item_data.input_type in entry.input_types:
                    action_names.append(entry.name)
        return sorted(action_names)

    def __eq__(self, other):
        if other is None:
            return False
        if hasattr(self,"item_data"):
            if not hasattr(other,"item_data"):
                return False
            if self.item_data and other.item_data:
                return self.item_data.callbackKey() == other.item_data.callbackKey()
        return self.id == other.id
