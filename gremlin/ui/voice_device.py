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

from __future__ import annotations  # deprecated with python 3.14+
import logging
import fnmatch
import random
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QModelIndex
import threading
from lxml import etree as ElementTree
import gremlin.util
from gremlin.util import safe_format, safe_read, write_guid, read_guid

import gremlin.config
import gremlin.event_handler
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.shared_state
import html
import re

from gremlin.singleton_decorator import SingletonDecorator
import gremlin.base_profile
from psygnal import Signal
import gremlin.input_item
from gremlin.input_item import AbstractCondition, InputItemWidget, BaseAbstractCondition, AbstractConditionWidget, InputItem, AbstractContainer, AbstractAction
from shiboken6 import Shiboken
import html
from typing import Callable

from faster_whisper import WhisperModel

syslog = logging.getLogger("system")

class VoiceInputItem(InputItem):
    """holds a single speech recognition input"""

    def __init__(
        self,
        key: str = None,
        text : str = None,
        description=None,
        data=None,
        ):

        master_mode = gremlin.shared_state.master_mode
        self._emit = True

        # get the mode object for this state input
        profile = gremlin.shared_state.current_profile
        # device = gremlin.joystick_handling.getDevice(StateDeviceTabWidget.device_guid)
        device_modes = profile.get_device_modes(
            gremlin.shared_state.state_tab_guid,
            DeviceType.State,
            DeviceType.to_string(DeviceType.State),
        )
        mode_object = device_modes.ensure_mode_exists(master_mode)

        self._key = key  # ok if None (blank)
        self._text = text
        self._hooked = False
        super().__init__(
            mode_node=mode_object,
            device_guid=VoiceDeviceTabWidget.device_guid,
            input_type=InputType.State,
            custom_input_id_handler=self._handle_input_id_callback,
        )


    def suppressEvents(self):
        """disable events"""
        self._emit = False

    def enableEvents(self):
        """enable events"""
        self._emit = True

    def clone(self):
        """clones the input item (gives it a new ID)"""

        return VoiceInputItem(
            key = self.key,
            text = self.text,
            description = self.description,
        )

    def _handle_input_id_callback(self):
        """input id is self for a voice input """
        return self

    def hook(self):
        """called when the state is being created - hooks into the event model"""
        if not self._hooked:
            sd = gremlin.ui.state_device.StateData()
            sd.key_changed.connect(self._change_state_name)
            self._hooked = True
            el = gremlin.event_handler.EventListener()
            el.profile_unloaded.connect(self._handle_profile_unload)
            verbose = gremlin.config.Configuration().verbose_mode_state
            if verbose:
                syslog.info(f"VOICE: hook [{self._key}] id: [{self._guid}]")

    def unhook(self):
        """called when the state should unhook itself because it is being discarded"""
        if self._hooked:
            sd = gremlin.ui.state_device.StateData()
            sd.key_changed.disconnect(self._change_state_name)
            # clear any dependencies
            el = gremlin.event_handler.EventListener()
            el.profile_unloaded.disconnect(self._handle_profile_unload)
            self._hooked = False
            verbose = gremlin.config.Configuration().verbose_mode_state
            if verbose:
                syslog.info(f"VOICE: unhook [{self._key}]  id: [{self._guid}]")

    def _handle_profile_unload(self):
        """occurs on profile unload before a new profile is loaded"""
        self.unhook()

    @property
    def display_name(self):
        return self._key

    @property
    def key(self) -> str:
        return self._key

    @key.setter
    def key(self, value: str):
        value = value.casefold().strip()
        if self._key != value:
            old_name = self._key
            self._key = value
            if self._emit:
                self.key_changed.emit(self, old_name, value)
                sd = VoiceData()
                sd.update_key(self, old_name, value)

    @property
    def message_key(self):
        return self.key

    @property
    def text(self) -> str:
        return self._text
    @text.setter
    def text(self, value: str):
        self._text = value

    def to_xml(self) -> ElementTree.Element:
        """write XML voice input node"""

        node = ElementTree.Element("voice-input", id=write_guid(self._id), key=self._key)

        description = self.description

        node.set("id", write_guid(self._id))


        if description:
            node.set("description", html.escape(description))

        node.set("text", html.escape(self._text))

        # write container data
        super().to_xml(node)

        return node

    def from_xml(self, node, data=None, extra_data=None):
        """read XML voice input node"""

        self._key = node.get("key")
        if "id" in node.attrib:
            self.setId(read_guid(node, "id"))

        description = None
        if "description" in node.attrib:
            description = html.unescape(node.get("description"))

        self.setDescription(description)

        text = node.get("text")
        if text:
            text = html.unescape(text)

        self._text = text



class VoiceInputItemModel(gremlin.input_item.InputItemListModel):
    """data model for state inputs"""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        custom_load_handler: Callable = None,
        custom_filter_handler: Callable = None,
        custom_change_handler: Callable = None,
        item_changed_handler: Callable = None,
    ):

        super().__init__(
            profile=profile,
            device_guid=VoiceDeviceTabWidget.device_guid,
            mode=gremlin.shared_state.master_mode,
            allowed_types=[InputType.Voice],
            custom_load_handler=custom_load_handler,
            custom_change_handler=custom_change_handler,
            custom_filter_handler=custom_filter_handler,
            show_master_mode=True,
        )

        if item_changed_handler:
            self.addOnItemChangedCallback(item_changed_handler)

@SingletonDecorator
class VoiceData:
    """holds voice information"""
    crud = Signal()  # fires when a voice input is added or removed or changed


    def __init__(self):
        self._data = {}
        self._id_map = {}

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._reset)
        el.profile_unloaded.connect(self._handle_profile_unload)


        model_size = "base"   # Options: "tiny", "base", "small", "medium", "large-v3"

        # Run on GPU with FP16
        #self.engine = WhisperModel(model_size, device="cuda", compute_type="float16")
        self.engine = WhisperModel(model_size, device="cpu", compute_type="int8")


    def _reset(self):
        """reset voices """
        pass


    def _handle_profile_unload(self):
        """occurs on profile unload before a new profile is loaded"""

        self._data = {}
        self._id_map = {}
        verbose = gremlin.config.Configuration().verbose_mode_voice
        if verbose:
            syslog.info("VOICE: clear data")

    def _register(self, key: str, text=None, description=None) -> VoiceInputItem:
        """registers a new voice input"""
        if not key:
            return None
        key = key.casefold().strip()
        if key in self._data:
            # already in the list
            return self._data[key]

        input_item = VoiceInputItem(key, text, description)
        self._data[key] = input_item
        self._id_map[input_item.id] = input_item
        self.crud.emit()
        return input_item

    def register(self, key: str, text=None, description=None) -> VoiceInputItem:
        """registers a new state"""
        item = self._register(key, text, description)
        if item:
            self._sort()
        return item

    def unregister(self, key: str):
        """removes a voice input from the list"""
        key = key.casefold().strip()
        if key in self._data:
            input_item = self._data[key]
            input_item.unhook()

            id = input_item.id
            del self._data[key]
            del self._id_map[id]

    def add(self, data: VoiceInputItem, emit=True):
        if data and data.key not in self._data:
            self._data[data.key] = data
            self._id_map[data.id] = data
            self._sort()
            if emit:
                self.crud.emit()

    def _sort(self):
        self._data = dict(sorted(self._data.items()))

    def sorted_keys(self) -> list:
        """returns the keys in the state data sorted alphabetically"""
        return list(self._data.keys())

    def exists(self, key: str | VoiceInputItem):
        """true if the key exists in the state data"""
        if isinstance(key, str):
            key = key.casefold().strip()
            return key in self._data

        data: VoiceInputItem = key
        if data.id in self._id_map:
            return True
        if data.key in self._data:
            return True
        return False

    def clear(self):
        """clears all data"""
        if self._data:
            self._data.clear()
            self._id_map.clear()
            self.crud.emit()

    def remove(self, state: VoiceInputItem | str):

        if isinstance(state, str):
            key = state.casefold().strip()
        else:
            key = state.key
        if key in self._data:
            data = self._data[key]
            data.unhook()
            del self._data[key]
            del self._id_map[data.id]
            self.crud.emit()

    def removeId(self, id: str):
        if id in self._id_map:
            data = self._id_map[id]
            data.unhook()
            key = data.key
            del self._data[key]
            del self._id_map[data.id]

    def index(self, item: VoiceInputItem):
        """gets the index of the item in the current list"""
        if item.key in self._data:
            keys = list(self._data.keys())
            return keys.index(item.key)
        return -1

    def getVoices(self) -> list:
        """returns a list of all voice input items"""
        return list(self._data.values())

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
        """persists the data to XML"""
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose:
            syslog.info(f"Persisting voices to XML - voice count: {len(self._data)}")
        root = ElementTree.Element("voices")
        for key in self._data:
            item = self._data[key]
            if item:
                node = item.to_xml()
                if node is not None:
                    root.append(node)



        return root

    def __deepcopy__(self, memo):
        # deep copy returns self as this is a singleton object
        return self

    def from_xml(self, root, data=None, extra_data=None):
        """reads saved data"""

        for node in root:
            if node.tag == "voice-input":
                item = VoiceInputItem()
                item.from_xml(node)
                self._data[item.key] = item
                self._id_map[item.id] = item


class VoiceInputConfigDialog(gremlin.ui.ui_common.QShowAtCursorDialog):
    """dialog showing the voice input configuration options"""

    def __init__(
        self,
        input_item: VoiceInputItem,
        ref_input_item: VoiceInputItem,
        edit_mode: bool,
        parent=None,
    ):
        """
        :param input_item - the voice input item being edited
        :param ref_input_item - the reference voice input item
        """

        super().__init__(self.__class__.__name__, parent=parent)

        gremlin.shared_state.push_suspend_highlighting()  # prevent device highlight changes while editing a state

        # self._sequence = InputKeyboardModel(sequence=sequence)
        self.setWindowTitle("Voice Input Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent  # list view
        self._is_edit = edit_mode  # edit mode vs new mode

        el = gremlin.event_handler.EventListener()

        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        self._config_widget, self._config_layout = gremlin.ui.ui_common.getGridContainer()
        self.data = input_item
        self.ref_data = ref_input_item  # reference state

        self._name_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._name_widget.setText(input_item.key)
        self._name_widget.textChanged.connect(self._name_changed)


        self._text_widget = QtWidgets.QPlainTextEdit()
        #self._text_widget.setAcceptRichText(False)
        self._text_widget.setMinimumWidth(200)
        self._text_widget.setPlainText(input_item.text)

        self._test_widget = QtWidgets.QPushButton("Test")
        self._test_widget.setToolTip("Tests the voice recognition")
        self._test_widget.setEnabled(False)

        self._description_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._description_widget.setText(input_item._description)
        self._description_widget.textChanged.connect(self._description_changed)

        # Removed autorelease widgets and containers as they are no longer needed

        self._status_widget = gremlin.ui.ui_common.QWarningWidget()

        row = 0
        col = 0
        self._config_layout.addWidget(QtWidgets.QLabel("Name:"), row, col)
        self._config_layout.addWidget(self._name_widget, row, col + 1)

        row += 1
        self._config_layout.addWidget(QtWidgets.QLabel("Description:"), row, col)
        self._config_layout.addWidget(self._description_widget, row, col + 1)


        row += 1
        self._config_layout.addWidget(QtWidgets.QLabel("Voice Command:"), row, col)
        row += 1
        self._config_layout.addWidget(self._text_widget, row, col, 1, -1)


        main_layout.addWidget(self._config_widget)

        main_layout.addWidget(self._status_widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True, widget_only=True)

        main_layout.addWidget(widget)
        self._update_ui()

    @property
    def editMode(self) -> bool:
        """true if the dialog was called in edit mode"""
        return self._is_edit



    def _set_status(self, text: str):
        """sets the status text"""
        self._status_widget.setText(text)
        self._update_ui()

    def _clear_status(self):
        """clears and hides the status text"""
        self._set_status(None)

    def _validate(self):
        sd = VoiceData()
        msg = None
        key = self.data.key

        # blank
        enabled = bool(key)
        if not enabled:
            msg = "Name cannot be blank."

        # words
        if re.search(r"\s", key):
            enabled = False
            msg = "Name cannot include spaces"

        if enabled:
            voice = sd.getVoice(self.data.key)
            if voice and self.ref_data and voice != self.ref_data:
                enabled = False
                msg = "Name is not case sensitive and must be unique."



        self.ok_widget.setEnabled(enabled)
        self._set_status(msg)

    @QtCore.Slot()
    def _name_changed(self):
        self.data.key = self._name_widget.text()
        self._validate()

    @QtCore.Slot()
    def _description_changed(self):
        description = self._description_widget.text()
        self.data.setDescription(description)

    @QtCore.Slot(bool)
    def _default_changed(self, checked: bool):
        widget = self.sender()
        self.data.default_value = widget.data

    def _ok_button_cb(self):
        """ok button pressed"""
        # ensure the item is unique and not already used

        key = self.data.key


        if key:
            key_low = self.data.key.casefold().strip()
            if key_low:
                if not self._is_edit:
                    # validate if not editing
                    id = self.data.id
                    sc = VoiceData()
                    data = sc.getVoices()
                    voices = [item.key for item in data.values() if item.id != id and key_low == item.key]
                    if voices:
                        gremlin.ui.ui_common.MessageBox(
                            title="Voice Input Error",
                            prompt=f"[{key}] is already defined as a voice input.\nVoice input names must be unique and are not case sensitive.",
                        )
                        return

                gremlin.shared_state.pop_suspend_highlighting()
                self.accept()
        else:
            gremlin.ui.ui_common.MessageBox(title="Voice Input Error", prompt="A voice input name is required.")

    def _cancel_button_cb(self):
        """cancel button pressed"""
        gremlin.shared_state.pop_suspend_highlighting()
        self.reject()

    def _update_ui(self):
        """updates the dialog controls based on options"""

        self._status_widget.setVisible(bool(self._status_widget.text()))




class VoiceDeviceTabWidget(gremlin.input_item.BaseDeviceTabWidget):
    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.voice_tab_guid

    def __init__(
            self,
            profile: gremlin.base_profile.Profile,
            mode: str,
            object_name="Voice Device",
            parent=None,
            ):
        """Creates a new object instance.

        :param profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """

        device = gremlin.joystick_handling.getDevice(self.device_guid)
        super().__init__(
            device=device,
            profile=profile,
            mode=mode,
            object_name=object_name,
            custom_input_widget_callback=self._custom_widget_handler,
            blank_input_message="Please add a voice input.",
            parent=parent,
        )

        self._widget_map = {}


        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)

        config = gremlin.config.Configuration()

        # lock widget
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data=self.device_guid)
        widget = gremlin.ui.ui_common.getHContainer(["Voice Inputs", "||", lock_widget], widget_only=True)
        self.addLeftPanelHeaderWidget(widget)

        if config.show_container_id:
            device = gremlin.joystick_handling.get_device(self.device_guid)
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            w1 = widget

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            w2 = widget

            gremlin.ui.ui_common.synchronize_grids([w1, w2])

        self._filter = gremlin.util.decorate_filter(config.state_filter)
        self._category_filter = config.state_category_filter

        # data model
        model = VoiceInputItemModel(
            profile,
            custom_load_handler=self._load_handler,
            custom_filter_handler=self._filter_data,
            item_changed_handler=self.onItemChanged,
        )

        self.setInputItemListModel(model)

        # clear and add buttons to add/clear all states
        clear_button = gremlin.ui.ui_common.ConfirmPushButton("Clear", show_callback=self._show_clear_cb)
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        clear_button.setIcon(icon)
        clear_button.setToolTip("Deletes all states")
        clear_button.confirmed.connect(self._confirm_clear_inputs_cb)
        button_container_layout.addWidget(clear_button)

        test_button = gremlin.ui.ui_common.QDataPushButton("Test", callback=self._test_input_cb)
        button_container_layout.addWidget(test_button)

        # right align
        button_container_layout.addStretch(1)


        # sort states
        sort_button = QtWidgets.QPushButton("Sort")
        icon = gremlin.ui.ui_common.Icons.sortIcon()
        sort_button.setIcon(icon)
        sort_button.clicked.connect(self._sort_input_cb)
        button_container_layout.addWidget(sort_button)

        # Key add button
        add_button = QtWidgets.QPushButton("Add")
        add_button.setToolTip("Adds a new state to the profile")
        icon = gremlin.ui.ui_common.Icons.addIcon()
        add_button.setIcon(icon)
        add_button.clicked.connect(self._add_input_cb)

        button_container_layout.addWidget(add_button)

        # Handle user interaction
        self.addLeftPanelHeaderWidget(button_container_widget)

        self.inputItemListModel.refresh()

        # refresh on configuration change
        el = gremlin.event_handler.EventListener()
        # lock all inputs
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)
        el.find_next.connect(self._handle_find_next)

    def _test_input_cb(self):
        """callback for the test input button"""
        pass

    def _filter_data(self, input_item) -> bool:
        """custom filter handler - true if the data is included in the filter, false otherwise"""

        if not self._filter:
            return True  # ok
        item: VoiceInputItem = input_item.input_id
        key = item.key
        if not key:
            # no key = match
            return True

        key = item.key.casefold().strip()
        if self._filter in key:
            return True
        return fnmatch.fnmatch(key, self._filter)

    def _custom_widget_handler(self, list_view, index: int, identifier, data, parent=None):
        """creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        """

        assert isinstance(data, VoiceInputItem), f"Unexpected type in widget handler - expected VoiceInputItem and got [{type(data).__name__}]"

        widget = InputItemWidget(
            input_item=identifier.input_item,
            populate_ui_callback=self._populate_input_widget_ui,
            mapping_changed_callback=self._update_input_widget,
            confirm_delete_callback=self._handle_confirm_delete,
            config_external=True,
            parent=parent,
            data=data,
        )
        widget._identifier = data
        widget.create_action_icons(data)
        input_item: VoiceInputItem = data

        vd = VoiceData()

        title = f"State: [{input_item.key}] [{input_item.id}]" if gremlin.config.Configuration().show_container_id else f"State: [{input_item.key}]"
        widget.setTitle(title)
        widget.enable_edit()
        widget.enable_close()
        widget.clearWidgets()

        if input_item.description:
            widget.addWidget(QtWidgets.QLabel(f"{input_item.description}"))

        widget.setIcon("ri.user-voice-fill")

        # remember what widget is at what index
        widget.index = index
        return widget

    def _load_handler(self, model: VoiceInputItemModel, emit=True) -> bool:
        """called when the data model for the input list needs to be updated - refreshes the model view"""
        voice = self.profile.voice
        self._input_items = {}

        keys = [key for key in voice]
        keys.sort()

        model.pushSuspend()
        model.clear(emit=False)


        changed = False
        index = 0
        for key in keys:
            data = voice[key]
            input_item = data
            self._input_items[key] = input_item
            changed = True
            model.setItemAt(index, input_item)
            index += 1

        model.applyFilter()  # update model filters and sort
        model.popSuspend()

        if changed and emit:
            model.trigger()  # causes an update
        return changed

    def onItemChanged(self, model, index, new_item, old_item, operation):
        redraw = False
        vd = VoiceData()
        match operation:
            case "add":
                # handle add operation
                vd.add(new_item)
                redraw = True
            case "remove":
                vd.remove(old_item)
                redraw = True
        if redraw:
            self.inputItemListView.redraw()  # tell the list

    def onInputListViewCreated(self):
        """called when list view is created"""
        self.inputItemListView.item_edit.connect(self._edit_item_cb)
        self.inputItemListView.item_closed.connect(self._close_item_cb)

    def onInputListViewRemoved(self):
        """called when list view is removed"""
        self.inputItemListView.item_edit.disconnect(self._edit_item_cb)
        self.inputItemListView.item_closed.disconnect(self._close_item_cb)

    def _handle_model_changed_cb(self, data=None, force: bool = False):
        """called when the model changes"""
        self._filter_widget.updateCounts()

    @property
    def inputCount(self) -> int:
        """number of inputs in the device"""
        return self.inputItemListModel.rows()

    @property
    def inputWidgetCount(self) -> int:
        """number of input widgets currently in the device"""
        return self.inputItemListView.count()

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data)  # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data)  # ensure on UI thread

    def _handle_find_next(self):
        """finds the next item"""
        if gremlin.shared_state.current_tab_device_guid == gremlin.shared_state.state_tab_id:
            term = gremlin.config.Configuration().state_last_search_term  # last search term
            if term:
                gremlin.util.InvokeUiMethod(self._filter_widget.find_next, term)

    def _handle_lock_inputs_ui(self, data):
        """lock all inputs event"""

        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        """unlock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)

    def _show_clear_cb(self):
        return self.inputItemListModel.rows() > 0

    def _config_changed_cb(self):
        gremlin.util.InvokeUiMethod(self._config_changed_ui)

    def _config_changed_ui(self):
        """called when configuraition has changed"""
        gremlin.util.assert_ui_thread()
        self.refresh()



    def getOverrideInputType(self):
        """override type"""
        return InputType.JoystickButton

    @QtCore.Slot()
    def _add_input_cb(self):
        """Adds a new state to the inputs list ADD STATE"""
        input_item = VoiceInputItem()
        input_item.suppressEvents()

        self._edit_dialog = VoiceInputConfigDialog(input_item, None, edit_mode=False, parent=self)
        self._edit_dialog.accepted.connect(self._dialog_ok_confirm_cb)
        self._edit_dialog.rejected.connect(self._dialog_cancel_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()

    def _edit_item_cb(self, widget, index, input_item):
        """edit the state"""
        tmp_input_item = input_item.clone()
        tmp_input_item.suppressEvents()
        self._edit_dialog = VoiceInputConfigDialog(tmp_input_item, input_item, edit_mode=True, parent=self)
        self._edit_dialog.accepted.connect(self._dialog_ok_confirm_cb)
        self._edit_dialog.rejected.connect(self._dialog_cancel_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()

    def _dialog_cancel_cb(self):
        self._edit_dialog.deleteLater()
        self._edit_dialog = None

    def _dialog_ok_confirm_cb(self):
        """called when edit dialog closes with ok on a new state"""
        try:
            verbose = gremlin.config.Configuration().verbose_mode_state
            edit_mode = self._edit_dialog.editMode

            edited_input_item = self._edit_dialog.data
            input_item = self._edit_dialog.ref_data if edit_mode else edited_input_item

            sd = VoiceData()

            if not edit_mode:
                # add the new state
                index = self.inputItemListModel.add(input_item)
                if verbose:
                    syslog.info(f"adding id: [{input_item.id}]  key: [{input_item.key}] at index [{index}]")

                # change the state
                sd.add(edited_input_item)

            else:
                # edit an existing state

                index = self.inputItemListModel.indexOf(input_item)
                assert index != -1, "Reference input is missing from model"
                if verbose:
                    syslog.info(f"modifying id: [{input_item.id}]  key: [{edited_input_item.key}] at index [{index}]")

                # copy changed data
                input_item.enableEvents()
                category = self._edit_dialog.category()
                input_item.setCategory(category)
                input_item.key = edited_input_item.key
                input_item.setDescription(edited_input_item.description)
                input_item.text = edited_input_item.text


                self.inputItemListModel.refresh()
                self._filter_widget.updateCounts()

            index = self.inputItemListView.indexOf(input_item)
            syslog.info(f"selecting state index: [{index}] for [{input_item.input_id}]")
            self.selectInputItemIndex(index)

            el = gremlin.event_handler.EventListener()
            el.device_mapping_changed.emit(self._device_id)
        finally:
            self._edit_dialog.deleteLater()
            self._edit_dialog = None
            self.inputItemListView.redraw()

    def _sort_input_cb(self):
        """sorts states by key name"""

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
            # reselect the saved item - because the inputs were likely recreated - we can't compare the old with the new
            # so we need to find the matching data packet
            self.selectInputItemIndex(current_selection.index)

    def _sort_callback(self, items: list):
        """callback for sorting inputs in this device"""
        items.sort(key=lambda x: x.input_id.key.casefold() if x.input_id.key else "")
        return items

    def _close_item_cb(self, widget, index, data):
        """called when the close button is clicked"""
        key = self.getRegisteredKeyIndex(index)
        self.unregisterWidget(key)
        if not self.inputItemListModel.rows():
            # display blank page if no item left
            self._blank_input()

    def _confirm_clear_inputs_cb(self):
        """clears all input keys"""
        sd = VoiceData()
        sd.clear()
        profile = gremlin.shared_state.current_profile
        profile.state.clear()

        self.inputItemListModel.clear()

        self._filter_widget.updateCounts()

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        self._blank_input()