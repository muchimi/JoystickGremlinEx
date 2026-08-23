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

from PySide6 import QtWidgets

import gremlin.config
import gremlin.event_handler
from typing import Callable
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.ui.joystick_device
import gremlin.input_item
from gremlin.util import read_guid, safe_format, safe_read, write_guid
import enum
import gremlin.util
import gremlin.base_profile
from shiboken6 import Shiboken
from lxml import etree as ElementTree
import html
import logging
import dinput
from gremlin.ui.ui_common import Ansi

syslog = logging.getLogger("system")


class ModeInputModeType(enum.IntEnum):
    """possible input modes"""

    NotSet = 0 # not set
    ModeEnter = 8  # executes on mode enter
    ModeExit = 1  # executes on mode exit
    ModeGlobalEnter = 2  # executes on any mode change (activate)
    ModeGlobalExit = 3  # executes on any mode change (deactivate)
    ModeProfileLoad = 4  # executes on profile load
    ModeProfileStart = 5  # executes on profile start
    ModeProfileStop = 6  # executes on profile stop
    DelayLoad = 7  # delay load

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
            case ModeInputModeType.ModeProfileLoad:
                return "Profile load"
            case ModeInputModeType.ModeProfileStart:
                return "Profile start"
            case ModeInputModeType.ModeProfileStop:
                return "Profile stop"
            case ModeInputModeType.DelayLoad:
                return "Delay Load"

        return f"Unknown mode: {value}"

    @staticmethod
    def from_name(value: str) -> ModeInputModeType:
        match value.casefold():
            case "not-set":
                return ModeInputModeType.NotSet
            case "enter":
                return ModeInputModeType.ModeEnter
            case "exit":
                return ModeInputModeType.ModeExit
            case "start":
                return ModeInputModeType.ModeProfileStart
            case "stop":
                return ModeInputModeType.ModeProfileStop
            case "load":
                return ModeInputModeType.ModeProfileLoad
            case "global-enter":
                return ModeInputModeType.ModeGlobalEnter
            case "global-exit":
                return ModeInputModeType.ModeGlobalExit
            case "delay-load":
                return ModeInputModeType.DelayLoad

        raise ValueError(f"ModeInputModeType: don't know to handle [{value}]")

    @staticmethod
    def to_name(value: ModeInputModeType):
        match value:
            case ModeInputModeType.NotSet:
                return "not-set"
            case ModeInputModeType.ModeEnter:
                return "enter"
            case ModeInputModeType.ModeExit:
                return "exit"
            case ModeInputModeType.ModeGlobalEnter:
                return "global-enter"
            case ModeInputModeType.ModeGlobalExit:
                return "global-exit"
            case ModeInputModeType.ModeProfileLoad:
                return "load"
            case ModeInputModeType.ModeProfileStart:
                return "start"
            case ModeInputModeType.ModeProfileStop:
                return "stop"
            case ModeInputModeType.DelayLoad:
                return "delay-load"

        raise ValueError(f"ModeInputModeType: don't know to handle [{value}]")


class ModeInputItemModel(gremlin.input_item.InputItemListModel):
    """model for mode input items"""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        mode: str,
        custom_load_handler: Callable = None,
        custom_remove_handler: Callable = None,
        custom_filter_handler: Callable = None,
    ):
        """creates a new model for mode input items

        :param profile: the profile data for the device this model represents
        :param mode: the current mode to display inputs for
        :param custom_filter_handler: a handler that takes an input item and returns true if it should be filtered (not displayed) or false if it should be visible
        """

        super().__init__(
            profile=profile,
            device_guid=ModeDeviceTabWidget.device_guid,
            mode=mode,
            allowed_types=[InputType.ModeControl],
            custom_load_handler=custom_load_handler,
            custom_remove_handler=custom_remove_handler,
            custom_filter_handler=custom_filter_handler,
            show_master_mode=True,
        )


class ModeInputItem(gremlin.input_item.InputItem):
    def __init__(
        self,
        mode_node: gremlin.base_profile.ProfileModeNode,
        input_id: ModeInputModeType = ModeInputModeType.DelayLoad,
        description: str = None,
        description_readonly: bool = None,
        tooltip: str = None,
    ):

        assert mode_node is not None, "mode must be provided"
        assert mode_node.device_guid is not None, "mode node must have a valid device ID"
        assert isinstance(input_id, ModeInputModeType), "invalid input id"

        self._value : bool = False

        if input_id == ModeInputModeType.NotSet:
            # if not set, use the appropriate default
            input_id = ModeInputModeType.DelayLoad

        super().__init__(
            mode_node,
            input_type=InputType.ModeControl,
            input_id=input_id,
            description=description,
            description_readonly=description_readonly,
            device_guid=mode_node.device_guid,
            tooltip=tooltip,
            override_input_type=InputType.JoystickButton,
        )  # parent is the mode object this input belongs to



    @property
    def value(self) -> bool:
        """gets the current value of the input"""
        return self._value

    @value.setter
    def value(self, new_value: bool):
        """sets the current value of the input"""
        if self._value != new_value:
            self._value = new_value

    def from_xml(self, node, data=None, extra_data: dict = None):
        # mode data
        # for child in node:
        #     if child.tag in ("modecontrol","mode-control"):
        #         self.parse_xml(child, data, extra_data)
        if node.tag in ("modecontrol", "mode-control"):
            self.parse_xml(node, data, extra_data)

        # read containers
        super().from_xml(node, data, extra_data, skip_root=True)

        assert self.input_id is not None, "ModeInputItem: input id load failed"
        assert self.input_id != ModeInputModeType.DelayLoad, "invalid input read from XML data"

        # syslog.info(
        #     f"loaded xml for ModeInput id {Ansi.YELLOW}[{self.id}]{Ansi.RESET}  input id: {Ansi.GREEN}[{self.input_id.name}]{Ansi.RESET} container count: [{self.containers.count()}]"
        # )

        self.setInputIdReadOnly(True)  # ensure it cannot be changed

    def parse_xml(self, node: ElementTree.Element, data=None, extra_data: dict = None):
        """reads an input item from xml"""
        match node.tag:
            case "modecontrol":
                # version 0
                if "id" in node.attrib:
                    # old style
                    self.input_id = ModeInputModeType(safe_read(node, "id", int, 0))
                else:
                    raise ValueError(f"ModeControl: invalid XML, expected 'id' attribute - offending line: {node.sourceline}")
            case "mode-control":
                # version 1
                if "guid" in node.attrib:
                    self.setId(read_guid(node, "guid"))

                if "type" in node.attrib:
                    self.input_id = ModeInputModeType.from_name(node.get("type"))
                if "description" in node.attrib:
                    self.description = html.unescape(node.get("description"))

        self.setOverrideInputType(InputType.JoystickButton)
        self.descriptionReadOnly = True

    def to_xml(self):
        """writes the xml node for this input"""
        node = ElementTree.Element("mode-control")
        node.set("guid", str(self.id))
        node.set("type", ModeInputModeType.to_name(self.input_id))
        if self.description:
            node.set("description", html.escape(self.description))

        # write containers
        super().to_xml(node)
        return node


def ensureMasterInputItems(profile: gremlin.base_profile.Profile):
    """initializes the profile master inputs - initialized on a new profile"""

    device_guid = ModeDeviceTabWidget.device_guid
    device_node = profile.getDeviceNode(device_guid, autocreate=True)
    mode_node = device_node.getModeNode(gremlin.shared_state.master_mode, True, autocreate=True)
    if not mode_node.getInputItem(InputType.ModeControl, ModeInputModeType.ModeProfileStart):
        input_item = ModeInputItem(mode_node, input_id=ModeInputModeType.ModeProfileStart)
        mode_node.addInputItem(input_item)
    if not mode_node.getInputItem(InputType.ModeControl, ModeInputModeType.ModeProfileStop):
        input_item = ModeInputItem(mode_node, input_id=ModeInputModeType.ModeProfileStop)
        mode_node.addInputItem(input_item)


def ensureModeInputItems(profile: gremlin.base_profile.Profile, mode: str):
    device_guid = ModeDeviceTabWidget.device_guid
    device_node = profile.getDeviceNode(device_guid, autocreate=True)
    mode_node = device_node.getModeNode(mode, autocreate=True)
    if not mode_node.getInputItem(InputType.ModeControl, ModeInputModeType.ModeEnter):
        input_item = ModeInputItem(mode_node, input_id=ModeInputModeType.ModeEnter)
        mode_node.addInputItem(input_item)
    if not mode_node.getInputItem(InputType.ModeControl, ModeInputModeType.ModeExit):
        input_item = ModeInputItem(mode_node, input_id=ModeInputModeType.ModeExit)
        mode_node.addInputItem(input_item)



class ModeDeviceTabWidget(gremlin.input_item.BaseDeviceTabWidget):
    """Widget used to configure mode change actions"""

    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.mode_tab_guid

    # master mode name for profile wide mode
    master_mode = str(gremlin.shared_state.mode_tab_guid)

    def __init__(self, profile: gremlin.base_profile.Profile, mode: str, object_name="Mode Device", parent=None):
        """Creates a new object instance.

        :param profile: profile data of the entire device
        :param mode: currently active mode
        :param object_name: name of the tab
        :param parent: the parent of this widget
        """

        assert profile is not None, "Profile cannot be None"
        assert isinstance(profile, gremlin.base_profile.Profile), "Invalid profile type"
        assert mode is not None and mode != "", "Mode cannot be None or empty"


        device = gremlin.joystick_handling.getDevice(self.device_guid)
        super().__init__(
            device=device, profile=profile, mode=mode, object_name=object_name, custom_input_widget_callback=self._custom_widget_handler, parent=parent
        )

        self.current_mode = mode
        self.widget_storage = {}
        self._filter = ""  # active search filter string (empty = no filtering)

        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self._handle_new_profile)
        el.edit_mode_changed.connect(self._handle_profile_mode_changed)

        # List of inputs
        self.inputItemListModel = ModeInputItemModel(
            profile,
            mode,
            custom_load_handler=self._load_handler,
            custom_remove_handler=self._remove_handler,
            custom_filter_handler=self._filter_data,
        )

        # lock widget
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data=self.device_guid)
        widget = gremlin.ui.ui_common.getHContainer(lock_widget, left_stretch=True, widget_only=True)
        self.addLeftPanelHeaderWidget(widget)

        config = gremlin.config.Configuration()
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

        el = gremlin.event_handler.EventListener()
        el.mode_name_changed.connect(self._mode_name_changed)

        # lock all inputs
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)

    def _handle_new_profile(self):
        """new profile"""
        self.profile: gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self._handle_profile_mode_changed(gremlin.shared_state.edit_mode)

    def _handle_profile_mode_changed(self, new_mode: str):
        self.current_mode = new_mode
        ensureModeInputItems(self.profile, new_mode)

    def _load_handler(self, model: ModeInputItemModel, emit=True) -> bool:
        """called when the data model for the input list needs to be updated - refreshes the model view"""
        self._update_model(model)  # load the model
        if emit:
            model.trigger()  # causes an update
        return True

    def _update_model(self, model: ModeInputItemModel):
        """updates the model with any changed data"""
        # ensure inputs are defined
        from gremlin.input_item import InputItem

        mode = self.current_mode
        master_mode = gremlin.shared_state.master_mode
        registry = self.profile.registry

        ensureMasterInputItems(self.profile)
        ensureModeInputItems(self.profile, mode)

        input_enter = registry.getInputItem(self.device_guid, mode, InputType.ModeControl, ModeInputModeType.ModeEnter)
        input_exit = registry.getInputItem(self.device_guid, mode, InputType.ModeControl, ModeInputModeType.ModeExit)
        input_start = registry.getInputItem(self.device_guid, master_mode, InputType.ModeControl, ModeInputModeType.ModeProfileStart)
        input_stop = registry.getInputItem(self.device_guid, master_mode, InputType.ModeControl, ModeInputModeType.ModeProfileStop)

        assert input_enter is not None, "invalid mode enter input"
        assert input_exit is not None, "invalid mode exit input"
        assert input_start is not None, "invalid profile start input"
        assert input_stop is not None, "invalid profile stop input"

        input_items = [
            input_enter,
            input_exit,
            input_start,
            input_stop,
        ]

        model.pushSuspend()  # suspend triggers
        input_item: InputItem
        for index, input_item in enumerate(input_items):
            assert input_item is not None, "invalid input item - should be defined here"
            assert input_item.input_id is not None, "invalid input id for input item"
            model.setItemAt(index, input_item)
            # syslog.info(f"Mode model: index [{index}] contains input item id {Ansi.YELLOW}[{input_item.id}]{Ansi.RESET} [{input_item.display_name}] container count: [{input_item.containers.count()}]")

        model.popSuspend()

    def _remove_handler(self, model: ModeInputItemModel, index, emit_change=True):
        """clears a single index"""
        if index in model._index_map:
            del model._index_map[index]
            item = next((key for key, data in model._item_map.items() if data == index), None)
            if item:
                del model._item_map[item]

            model._update_filter()

    def _filter_data(self, input_item) -> bool:
        """custom filter handler - true if the data is included in the filter, false otherwise"""
        import fnmatch

        if not self._filter:
            return True  # ok
        item: ModeInputItem = input_item.input_id
        key = item.key
        if not key:
            # no key = match
            return True

        key = item.key.casefold().strip()
        if self._filter in key:
            return True
        return fnmatch.fnmatch(key, self._filter)

    def onInputListViewCreated(self):
        # create the two mode entries in the input
        pass  # just load the model

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

    def _handle_lock_inputs_ui(self, data):
        """lock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = len(input_item.containers) > 0  # don't lock if not mapped
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        """unlock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)

    def _mode_name_changed(self, name):
        gremlin.util.InvokeUiMethod(self._mode_name_changed_ui)  # ensure on UI thread

    def _mode_name_changed_ui(self, name):
        """occurs when there's a mode name change"""
        self.inputItemListModel.refresh()

    def _config_changed_cb(self):
        """called when configuraition has changed"""
        self.refresh()

    def _custom_name_handler(self, input_item):
        """gets the custom name for the input item"""
        input_item: gremlin.input_item.InputItem
        current_mode = self.current_mode
        # syslog.info(f"name handler: mode: {current_mode}")
        match input_item.input_id:
            case ModeInputModeType.ModeEnter:
                return f"Mode [{current_mode}] Activate"
            case ModeInputModeType.ModeExit:
                return f"Mode [{current_mode}] Deactivate"
            case ModeInputModeType.ModeGlobalEnter:
                return "Mode Activate (any)"
            case ModeInputModeType.ModeGlobalExit:
                return "Mode Deactivate (any)"
            case ModeInputModeType.ModeProfileLoad:
                return "Profile load"
            case ModeInputModeType.ModeProfileStart:
                return "Profile start"
            case ModeInputModeType.ModeProfileStop:
                return "Profile stop"

        return f"Mode [{gremlin.shared_state.edit_mode}] Unknown id: {input_item.input_id}"

    def create_handler(
        self,
        device_guid: dinput.GUID | str,
        mode_name: str,
        input_type: InputType,
        input_id,
        override_input_type: InputType = None,
        custom_name_handler: Callable = None,
        custom_mode_name_handler: Callable = None,
        description: str = None,
        description_readonly: bool = None,
        tooltip: str = None,
    ) -> ModeInputItem:
        """creates the input item when it does not exist"""
        mode_node = self.profile.getModeNode(device_guid=device_guid, mode=mode_name)
        assert mode_node is not None, "mode does not exist in profile"
        assert mode_node.device_guid is not None, "invalid mode node - missing device ID "

        input_item = self.profile.getInputItem(device_guid, mode_name, input_type, input_id)
        if input_item is None:
            input_item = ModeInputItem(mode_node, input_id=input_id, description=description, description_readonly=description_readonly, tooltip=tooltip)

        # update the model
        return input_item

    def refreshInputItems(self):
        """refreshes input list"""
        # syslog.info(f"refresh: mode {self.current_mode}")
        self.inputItemListModel.refresh()


    def display_name(self, input_id):
        """returns the name for the given input ID"""
        return input_id.display_name

    def _index_for_key(self, input_id):
        """returns the index of the selected input id"""
        current_mode = gremlin.shared_state.edit_mode
        mode = self.device_node.modes[current_mode]
        sorted_keys = list(mode.config[InputType.ModeControl].keys())
        return sorted_keys.index(input_id)

    def getWidgetKey(self, input_type, input_id):
        """gets the content widget compound key for the item / input combination"""
        mode = gremlin.shared_state.edit_mode
        return (self._device_guid, input_type, input_id, mode)

    def _custom_widget_handler(self, list_view, index: int, identifier, data, parent=None):
        """creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        """
        import gremlin.input_item

        widget = gremlin.input_item.InputItemWidget(
            input_item=identifier.input_item,
            populate_ui_callback=self._populate_input_widget_ui,
            mapping_changed_callback=self._update_input_widget,
            config_external=True,
            parent=parent,
            data=data,
        )
        widget._identifier = data
        widget.create_action_icons(data)
        widget.setTitle(self._custom_name_handler(data))
        widget.setInputDescription(data.description)
        widget.disable_close()
        widget.disable_edit()
        widget.setIcon("fa5.edit")

        # remember what widget is at what index
        widget.index = index
        return widget

    def _set_status(self, widget, icon=None, status=None, use_qta=True, color=None):
        """sets the status of an input widget"""
        status_widget = widget.findChild(gremlin.ui.ui_common.QIconLabel, "status")
        if color:
            status_widget.setIcon(icon, use_qta=use_qta, color=color)
        else:
            status_widget.setIcon(icon, use_qta=use_qta)

        status_widget.setText(status)
        status_widget.setVisible(status is not None)

    def _update_input_widget(self, input_widget, container_widget):
        """called when the widget has to update itself on a data change"""
        pass

    def _populate_input_widget_ui(self, input_widget, container_widget, data):
        """called when a button is created for custom content"""
        layout = QtWidgets.QVBoxLayout(container_widget)
        status_widget = gremlin.ui.ui_common.QIconLabel()
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)
        self._update_input_widget(input_widget, container_widget)

    def _index_for_key(self, input_id):
        """returns the index of the selected input id"""
        mode = self.device_node.modes[self.current_mode]
        sorted_keys = list(mode.config[InputType.ModeControl].keys())
        return sorted_keys.index(input_id)

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.inputItemListView.redraw_index(index)

    def set_mode(self, mode):
        """changes the mode of the tab"""
        self.current_mode = mode
        self.inputItemListModel.mode = mode
        self.inputItemListModel.refresh()

        self.selectInputItemIndex(self._last_selected_index)

    def refresh(self, emit=True):
        """Refreshes the current selection, ensuring proper synchronization."""
        self.set_mode(gremlin.shared_state.edit_mode)  # force a model and reload
