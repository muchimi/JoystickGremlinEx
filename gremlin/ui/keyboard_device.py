

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

from __future__ import annotations
import logging
from PySide6 import QtWidgets, QtCore
import json

# import container_plugins.basic
# import gremlin
import gremlin.config
from gremlin.input_types import InputType
import gremlin.keyboard
import gremlin.shared_state
import gremlin.util
from . import input_item, ui_common
from gremlin.keyboard import Key
from .input_item import InputItemWidget, InputIdentifier, InputItemListView, InputItemMappingWidget
import uuid
from gremlin.util import *
from gremlin.input_types import InputType
from lxml import etree
import gremlin.ui.ui_common
import gremlin.base_profile
from gremlin.ui.input_item import InputItemMappingWidget


syslog = logging.getLogger("system")

class KeyboardInputItem(gremlin.base_profile.InputItem):
    ''' holds a keyboard input item '''
    def __init__(self, mode_object : gremlin.base_profile.Mode  ):
        ''' Keyboard input id
            :param mode: the profile mode for this input
        '''
        super().__init__(mode_object, device_guid = KeyboardDeviceTabWidget.device_guid)

        self._key = None # associated primary key (containing latched items)
        self._title_name = "Keyboard input (not configured)"

        self._display_tooltip = None
        self._input_type = InputType.KeyboardLatched
        self._suspend_update = False
        self._update()
        self.setInputIdCallback(self._handle_input_id_callback)

    def _handle_input_id_callback(self):
        ''' input id is the key for keyboard '''
        return self._key

    def getOverrideInputType(self):
        ''' override type '''
        return InputType.JoystickButton

    @property
    def title_name(self):
        ''' title for this input '''
        return self._title_name

    @property
    def display_tooltip(self):
        return self._display_tooltip

    @property
    def key(self):
        return self._key

    @key.setter
    def key(self, value):
        assert isinstance(value, Key), f"Invalid type for key property: expected Key - got {value.type()}"
        self._key = value
        self._update()

    @property
    def key_tuple(self):
        # must be hashable
        if self._key:
            return self._key.scan_code, self._key.is_extended
        return None


    @property
    def sequence(self):
        ''' returns a list of (scan_code, extended) tuples for all latched keys in this sequence '''
        if self._key:
            return self._key.sequence
        return []

    def _latched_key_update(self, source, action, index, value):
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
    def keynames(self) -> list:
        key_list = [self._key.name]
        key_list.extend([key.name for key in self.latched_keys])
        return key_list

    def getKeyList(self) -> list:
        ''' gets keys as a list, including any latched keys '''
        key_list = [self._key]
        key_list.extend([key for key in self.latched_keys])
        return key_list




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

    def from_xml(self, node, data = None, extra_data : dict = None):
        self.parse_xml(node, data, extra_data)
       

    def parse_xml(self, node, data = None, extra_data : dict = None):
        ''' loads itself from xml '''
        from gremlin.keyboard import key_from_code
        self._suspend_update = True

        if node.tag in ("keyboard","keylatched"):
            if not "guid" in node.attrib:
                # older style GUID is in the input tag
                for child in node.xpath("./input"):
                    self.setId(read_guid(child, "guid", default_value=uuid.uuid4()))
                    break
            else:
                # new style
                self.setId(read_guid(node, "guid", default_value=uuid.uuid4()))

            child = next((n for n in node.xpath(".//key")), None)
            if child is None:
                raise ValueError(f"Invalid XML - missing key definition in profile XML - offending line: [{node.sourceline}]")

            # virtual_code = safe_read(child,"virtual-code", int, 0)
            scan_code = safe_read(child, "scan-code", int, 0)
            is_extended = safe_read(child, "extended", bool, False)
            is_mouse = safe_read(child, "mouse", bool, False)


            (scan_code, is_extended), _= gremlin.keyboard.KeyMap.translate((scan_code, is_extended))
            key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)

            self._key = key
            for latched_child in child:
                if latched_child.tag == "latched":
                    # virtual_code = safe_read(latched_child,"virtual-code", int, 0)
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

        # read the mappings
        super().from_xml(node, data, extra_data)

        self._suspend_update = False
        self._update()


    def to_xml(self):
        # saves itself to xml

        node = etree.Element(InputType.to_string(self.input_type))
        node.set("guid", write_guid(self.id))
        
        if self.description:
            node.set("description", self.description)



        # comment
        comment = "".join(name for name in self.keynames)
        node_comment = etree.Comment(comment)
        node.append(node_comment)

        # key entry
        child = etree.Element("key")
        root_key = self._key
        child.set("virtual-code", str(root_key.virtual_code))
        child.set("scan-code", str(root_key.scan_code))
        child.set("extended", str(root_key.is_extended))
        child.set("mouse", str(root_key.is_mouse))
        child.set("description", root_key.lookup_name)
        node.append(child)



        for key in root_key.latched_keys:
            comment = f"virtual: 0x{key.virtual_code:x}/{key.virtual_code} scan code: 0x{key.scan_code:x}/{key.scan_code} extended: {key.is_extended}"
            latched_child = etree.Element("latched")
            latched_child.set("virtual-code", str(key.virtual_code))
            latched_child.set("scan-code", str(key.scan_code))
            latched_child.set("extended", str(key.is_extended))
            latched_child.set("mouse", str(key.is_mouse))
            latched_child.set("description", key.lookup_name)
            node_comment = etree.Comment(comment)
            child.append(node_comment)
            child.append(latched_child)

        # output containers
        super().to_xml(node)

        return node


    def _update(self):
        # updates the message key and display
        if self._suspend_update:
            # ignore
            return
        if not self._key:
            self._message_key = self._guid
            self._title_name = "Keyboard Input (not configured)"
            self._display_name = ""
            self._description = ""
            self._display_tooltip = ""
            return

        extended_key = '0x0E ' if self._key._is_extended else ''
        message_key = f"| {extended_key}0x{self._key._scan_code:02X}"

        key : Key
        for key in self._key._latched_keys:
            extended_key = '0x0E ' if key._is_extended else ''
            message_key += f"|{extended_key}0x{key._scan_code:02X}"

        self._message_key = message_key

        is_latched = self._key.is_latched
        self._title_name = f"Key/Mouse input {'(latched)'if is_latched else ''}"

        self._display_name = self._key.latched_name
        self._description = self.key.latched_code
        try:
            self._display_tooltip = self._key.latched_name + " " + self.key.latched_code
        except:
            self._display_tooltip = ""

    def to_string(self):
        return f"KeyboardInputItem: pair: {self.key_tuple} name: {self._display_name}"

    @property
    def name(self):
        ''' display name - can be a compound key '''
        return self._display_name

    @property
    def display_name_scan(self) -> str:
        return f"{self._display_name} {self.message_key}"

    @property
    def display_name(self) -> str:
        return f"{self._display_name} {self.message_key}"

    def duplicate(self) -> KeyboardInputItem:
        ''' duplicates this object '''
        import copy
        source = self
        target = KeyboardInputItem(source.profile_mode)
        target.id = uuid.uuid4()
        target._key = copy.deepcopy(source._key)
        target._title_name = source._title_name
        target._display_name = source._display_name
        target._input_description = source._input_description
        target._display_tooltip = source._display_tooltip
        target._description = source._description
        target._suspend_update = source._suspend_update
        target._update()
        return target

    def __eq__(self, other):
        if isinstance(other, KeyboardInputItem):
            return self.message_key == other.message_key
        return self.__hash__() == other.__hash__()

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return str(self._message_key).__hash__()

    def __lt__(self, other):
        ''' used for sorting purposes '''
        # keep as is (don't sort this input entry)
        return False

    def __str__(self):
        return self.to_string()


class KeyboardInputItemModel(gremlin.ui.input_item.InputItemListModel):
    ''' data model for state inputs '''
    def __init__(self,
                 profile : gremlin.base_profile.Profile,
                 mode : str,
                 custom_load_handler : Callable = None,
                 custom_remove_handler : Callable = None,
                 custom_filter_handler : Callable = None):
        ''' creates a new model for keyboard input items
        :param profile: the profile data for the device this model represents
        :param mode: the current mode
        :param custom_load_handler: a custom handler for loading items
        :param custom_remove_handler: a custom handler for removing items
        :param custom_filter_handler: a custom handler for filtering items
        '''
        super().__init__(profile = profile,
                         device_guid = KeyboardDeviceTabWidget.device_guid,
                         mode = mode,
                         allowed_types = [InputType.Keyboard, InputType.KeyboardLatched],
                         custom_load_handler = custom_load_handler,
                         custom_remove_handler = custom_remove_handler,
                         custom_filter_handler = custom_filter_handler)

class KeyboardInputItemListView(gremlin.ui.input_item.InputItemListView):
    ''' view for state inputs '''
    def __init__(self, custom_widget_handler : Callable = None, parent : QtWidgets.QWidget = None, blank_message : str = None, model : KeyboardInputItemModel = None):
        ''' creates a new list view for keyboard input items
        :param custom_widget_handler: a handler for creating custom widgets for items in this list
        :param parent: the parent of this widget
        :param blank_message: the message to display when there are no items in the list
        :param model: the data model for this list view
        '''
        
        super().__init__(custom_widget_handler = custom_widget_handler,
                         device_guid = KeyboardDeviceTabWidget.device_guid,
                         parent = parent,
                         blank_message = blank_message,
                         model = model)



class KeyboardDeviceTabWidget(gremlin.ui.input_item.BaseDeviceTabWidget):

    """Widget used to configure keyboard inputs """

    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS (this one happens to match the regular keyboard device ID)
    device_guid = gremlin.shared_state.keyboard_tab_guid

    def __init__(
            self,
            profile : gremlin.base_profile.Profile,
            mode : str,
            object_name = "Keyboard",
            parent=None
    ):
        """Creates a new object instance.

        :param profile: profile data
        :param mode: mode to display inputs for
        :param parent: the parent of this widget
        """

        device = gremlin.joystick_handling.getDevice(self.device_guid)
        super().__init__(
                    device = device,
                    profile = profile,
                    mode = mode,
                    object_name = object_name,
                    parent = parent
                    )

  
       
        # List of inputs
        self.inputItemListModel = KeyboardInputItemModel(
            self.profile,
            mode = mode)



        self.inputItemListView = KeyboardInputItemListView(
            custom_widget_handler = self._custom_widget_handler,
            parent=self,
            blank_message = "Please add a keyboard or mouse input.",
            model = self.inputItemListModel
        )
        
        self.inputItemListModel.refresh()

        # Handle user interaction
        
        self.inputItemListView.item_edit.connect(self._edit_item_cb)
        self.inputItemListView.item_closed.connect(self._close_item_cb)


        # lock widget
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data = self.device_guid)
        widget = gremlin.ui.ui_common.getHContainer(["Keyboard/Mouse Inputs", "||", lock_widget], widget_only = True)
        self.addLeftPanelWidget(widget)

        config = gremlin.config.Configuration()
        if config.show_container_id:
            device = gremlin.joystick_handling.get_device(self.device_guid)
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only = True)
            self.addLeftPanelWidget(widget)
            w1 = widget

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only = True)
            self.addLeftPanelWidget(widget)
            w2 = widget

            gremlin.ui.ui_common.synchronize_grids([w1, w2])

        self.addLeftPanelWidget(self.inputItemListView)

        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)



        # key clear button

        clear_keyboard_button = ui_common.ConfirmPushButton("Clear", show_callback = self._show_clear_cb)
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        clear_keyboard_button.setIcon(icon)
        clear_keyboard_button.confirmed.connect(self._clear_keys_cb)
        button_container_layout.addWidget(clear_keyboard_button)
        button_container_layout.addStretch(1)

               # sort keyboard input
        sort_button = QtWidgets.QPushButton("Sort")
        icon = gremlin.ui.ui_common.Icons.sortIcon()
        sort_button.setIcon(icon)
        sort_button.clicked.connect(self._sort_input_cb)
        button_container_layout.addWidget(sort_button)

        self.addLeftPanelWidget(button_container_widget)

        virtual_keyboard_button = QtWidgets.QPushButton("Add")
        virtual_keyboard_button.setToolTip("Adds a new key/mouse input to the profile")
        icon = gremlin.ui.ui_common.Icons.keyboardIcon()
        virtual_keyboard_button.setIcon(icon)
        virtual_keyboard_button.clicked.connect(self._add_key_dialog_cb)
        button_container_layout.addWidget(virtual_keyboard_button)



        # refresh on configuration change
        el = gremlin.event_handler.EventListener()
        # update on an edit mode change so we update the display
        el.edit_mode_changed.connect(self._handle_edit_mode_changed)
        el.config_changed.connect(self._config_changed_cb)
        # lock all inputs
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)


        # Select default entry
        selected_index = self.inputItemListView.currentIndex()
        if selected_index is not None:
            self.selectInputItemIndex(selected_index)


    def _sort_input_cb(self):
        ''' sorts the inputs by VK '''

        if not self.inputItemListModel.rows():
            # nothing to sort
            return

        # current selection (so we can select the item that was selected if the order changes)
        index = self._last_selected_index
        current_selection = None
        if index != -1:
            current_selection = self.inputItemListModel.data(index)

        self.inputItemListModel.sort(self._sort_callback)

        if current_selection:
            # reselect the saved item
            # so we need to find the matching data packet
            self.selectInputItemIndex(current_selection.index)

    def _sort_callback(self, items : list):
        ''' callback for sorting inputs in this device '''
        # sort alpha by keynames for now
        items.sort(key = lambda x: x.input_id.keynames)
        return items

    @property
    def inputCount(self) -> int:
        ''' number of inputs in the device '''
        return self.inputItemListModel.rows()

    @property
    def inputWidgetCount(self) -> int:
        ''' number of input widgets currently in the device '''
        return self.inputItemListView.count()

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data) # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data) # ensure on UI thread

    def _handle_lock_inputs_ui(self, data):
        ''' lock all inputs event'''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        ''' unlock all inputs event '''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)



    def _reload_model(self, mode = None):
        ''' reloads the data for the current device/mode '''
        current_mode = mode if mode else gremlin.shared_state.edit_mode
        self.profile.ensure_mode_exists(current_mode)
        self.inputItemListModel = input_item.InputItemListModel(
            self.profile,
            current_mode,
            [InputType.Keyboard, InputType.KeyboardLatched]
        )
        self.inputItemListView.setModel(self.inputItemListModel)
        
        self.selectInputItemIndex(self._last_selected_index)


        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)



    def _handle_edit_mode_changed(self, mode : str):
        gremlin.util.InvokeUiMethod(self._edit_mode_changed_ui, mode) # ensure on UI thread

    def _edit_mode_changed_ui(self, mode : str):
        ''' occurs when a new mode is selected '''
        self.set_mode(mode)

    def _config_changed_cb(self):
        self.inputItemListModel.refresh()


    @property
    def model(self):
        ''' the current model '''
        return self.inputItemListModel


    def _show_clear_cb(self):
        return self.inputItemListModel.rows() > 0

    def _clear_keys_cb(self):
        ''' clears keyboard input keys '''

        self.inputItemListModel.clear(input_types=[InputType.Keyboard, InputType.KeyboardLatched])
        assert self.inputItemListModel.rows() == 0,"Unexpected entries in model - should be 0"

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout


        # blank the container view
        widget = self.getContentWidget()
        widget.setItemData(None)


    def _add_key_dialog_cb(self):
        ''' display the keyboard input dialog '''
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        gremlin.shared_state.push_suspend_ui_keyinput()

        self._keyboard_dialog = InputKeyboardDialog(parent = self, select_single = False, index = -1)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._dialog_close_cb)
        self._keyboard_dialog.setModal(True)
        gremlin.util.centerDialog(self._keyboard_dialog)
        self._keyboard_dialog.showNormal()


    def _dialog_close_cb(self):
        gremlin.shared_state.pop_suspend_ui_keyinput()
        self._keyboard_dialog.deleteLater()
        self._keyboard_dialog = None

    def _dialog_ok_cb(self):
        ''' called when the add/edit key dialog completes '''

        # grab a new data index as this is a new entry
        index = self._keyboard_dialog.index
        keys = self._keyboard_dialog.keys
        latched_key = self._keyboard_dialog.latched_key
        self._process_input_keys(keys, index, latched_key)

        self._keyboard_dialog.deleteLater()
        self._keyboard_dialog = None

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)



    def _process_input_keys(self, keys, index, root_key = None):
        ''' processes input keys

        index of -1 indicates a new item
        reload: if set, updates the whole model

        '''


        # reload on new index
        reload = index == -1
        current_mode = gremlin.shared_state.edit_mode

        # figure out the root key
        if root_key is None:
            if not keys:
                # no data
                root_key = Key()
            else:
                root_key = gremlin.keyboard.KeyMap.get_latched_key(keys)

        # ensure the input item exists in the profile data
        if index >= 0:

            input_item = self.inputItemListModel.data(index)

            #syslog.info(f"Editing index {index} {input_id.display_name}")
        else:
            input_item = KeyboardInputItem(current_mode)
            index = self.inputItemListModel.rows() # new index
            #syslog.info(f"Adding new kbd input index {index} ")

        input_item.key = root_key
        input_item.setOverrideInputType(InputType.JoystickButton)

        # creates the item in the profile if needed
        registry = gremlin.base_profile.ProfileRegistry()
        self.profile.modes[current_mode].get_data(input_item.input_type, input_item.input_id) # creates the entry in the profile
        # ensure override type for keyboard input is a joystick button
        registry.sync()


        if reload:
            # refreshes the model from the profile
            self.inputItemListModel.refresh()
            
            # select the new item - its index may have changed
            index = self.inputItemListModel.input_id_index(input_item)
        else:
            # update the widget for this entry
            self.inputItemListView.update_item(index)


        # select the item
        self.inputItemListView.select_item(index, force_update = True)

        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        if verbose:
            syslog.info(f"Final item index {index} {input_item.display_name}")

    
    
    # def _select_item_cb(self, index, emit = True):
    #     ''' called when a key has been selected - refreshes the view panel '''

    #     if not Shiboken.isValid(self.inputItemListView):
    #         return

    #     if index == -1:
    #         index = self._last_selected_index

    #     if index == -1:
    #         if self.inputItemListModel.rows() > 0:
    #             input_item = self.inputItemListModel.data(0)
    #             index = 0
    #         else:
    #             self._blank_input()
    #             return
    #     else:
    #         input_item = self.inputItemListModel.data(index)

    #     device_guid = self.device_guid
    #     input_type = InputType.KeyboardLatched
    #     input_id = input_item.input_id if input_item else None

    #     if input_item:


    #         profile = gremlin.shared_state.current_profile
    #         if profile:
    #             profile.setLastInput(device_guid, input_type, input_id)

    #         config = gremlin.config.Configuration()
    #         config.set_last_input(device_guid, input_type, input_id)

    #         key = self.getWidgetKey(input_type, input_id)
    #         widget = self.getRegisteredWidget(key)
    #         if not widget:
    #             widget = InputItemMappingWidget(input_item = input_item, object_name = f"Keyboard InputItemConfig for: {input_item.display_name}")
    #             self.registerWidget(key, widget)
    #             widget.redraw() # load the data

    #         # Create new configuration widget

    #         change_cb = self._create_change_cb(index)
    #         widget._container_model.data_changed.connect(change_cb)
    #         widget.description_changed.connect(change_cb)
    #         self.rightPanelLocked = input_item.locked


    #         #self.inputItemListView.select_item(index, False)
    #         self.selectRegisteredWidget(key)
    #     else:
    #         self._blank_input()
    #         # widget = InputItemWidget(object_name = "Blank inputitemconfig for keyhboard device (select item cb - no item data)")
    #         # self.setRightPanelWidget(widget)


    #     self._last_selected_index = index

    #     if emit:
    #         el = gremlin.event_handler.EventListener()
    #         el.select_input.emit(device_guid, input_type, input_id, False, True, False)
    #         # el.input_selection_changed.emit(device_guid, input_type, input_id)


    def _index_for_key(self, key_or_index):
        """Returns the index into the key list based on the key itself.

        :param key the keyboard key being queried
        :return index of the provided key
        """
        current_mode = gremlin.shared_state.edit_mode
        mode = self.profile.modes[current_mode]
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
        return lambda: self.inputItemListView.redraw_index(index)

    def set_mode(self, mode):
        ''' changes the mode of the tab '''
        self.current_mode = mode
        #self._reload_model(mode)
        self.profile.ensure_mode_exists(self.current_mode)
        self.inputItemListModel.mode = mode

        #self.inputItemListView.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.inputItemListModel.refresh()


    def refresh(self, emit = True):
        """Refreshes the current selection, ensuring proper synchronization."""
        self.inputItemListModel.refresh()



    def _custom_widget_handler(self, list_view : InputItemListView, index : int, identifier : InputIdentifier, data, parent = None):
        ''' creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        '''

        widget = InputItemWidget(identifier = identifier, populate_ui_callback=self._populate_input_widget_ui, update_callback = self._update_input_widget, config_external=True, parent=parent, data=data)
        widget.data = data
        widget.create_action_icons(data)
        widget.setIcon("fa6s.keyboard")
        widget.enable_close()
        widget.enable_edit()

        self._update_input_widget(widget, widget.parent)


        return widget

    def _set_custom_content(self, input_widget, values : list[gremlin.keyboard.Key]):
        ''' sets custom content '''
        if not values:
            # clear content
            input_widget.setCustomContent(None)
            return

        widgets = []
        if len(values) < 8:
            key : gremlin.keyboard.Key
            for key in values:

                widget = gremlin.ui.virtual_keyboard.QKeyWidget()
                icon = gremlin.keyboard.KeyMap.icon(key)
                name = gremlin.keyboard.KeyMap.get_name(key)
                tooltip = gremlin.keyboard.KeyMap.get_description(key, True)
                if icon:
                    widget.setIcon(icon)
                if name:
                    widget.setText(name)
                if tooltip:
                    widget.setToolTip(tooltip)
                widget.keySize = 2
                widget.autoSize = True
                widget.setFixedHeight(28)

                widget.setReadOnly(True)
                widgets.append(widget)
        else:
            # output as text that can wrap
            keys = "".join(key.name + " " for key in values)
            lbl = QtWidgets.QLabel(keys)
            lbl.setWordWrap(True)
            widgets = [lbl]


        # update
        container_widget, container_layout = gremlin.ui.ui_common.getHContainer(widgets)
        input_widget.setCustomContent(container_widget)

    def _update_input_widget(self, input_widget, container_widget):
        ''' called when the keyboard input widget has to update itself on a data change '''
        input_item = input_widget.identifier.input_item
        input_widget.setTitle(input_item.title_name)
        values = input_item.getKeyList()
        self._set_custom_content(input_widget, values)

        #input_widget.setInputDescription(data.display_name_scan)
        input_widget.display_name = input_item.display_name_scan

        input_widget.setToolTip(input_item.display_tooltip)
        if input_item.has_mouse:
            input_widget.setInputDescriptionIcon("mdi.mouse")
        else:
            input_widget.setInputDescriptionIcon(None)

        is_warning = False
        status_text = ""
        if input_item.key is None:
            is_warning = True
            status_text = "Not configured"
        elif gremlin.config.Configuration().show_scancodes:
            status_text = input_item.key.latched_code

        icon = None
        if is_warning:
            warning_color = gremlin.ui.ui_common.Color.warningColor()
            icon_color= QtGui.QColor(warning_color)
            icon = gremlin.util.load_icon("ph.shield-warning-fill", use_qta=True, qta_color=QtGui.QColor(warning_color))

        input_widget.setStatus(status_text, icon)






    def _populate_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when a button is created for custom content '''



        self._update_input_widget(input_widget, container_widget)



    def _edit_item_cb(self, widget, index, data):
        ''' called when the edit button is clicked  '''
        from gremlin.keyboard import Key
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog

        data = self.model.data(index)
        sequence = data.input_id.sequence

        syslog.info(f"Editing index {index} {data.display_name}")
        gremlin.shared_state.push_suspend_ui_keyinput()
        self._keyboard_dialog = InputKeyboardDialog(sequence, parent = self, select_single = False, index = index)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._dialog_close_cb)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.showNormal()


    def _close_item_cb(self, widget, index, data):
        ''' called when the close button is clicked '''
        key = self.getRegisteredKeyIndex(index)
        self.unregisterWidget(key)
        if not self.inputItemListModel.rows():
            # display blank page if no item left
            self._blank_input()


