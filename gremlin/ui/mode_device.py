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
from gremlin.util import *
import enum
import gremlin.util
import gremlin.base_profile
from shiboken6 import Shiboken


class ModeInputModeType(enum.IntEnum):
    """possible input modes"""

    ModeEnter = 0  # executes on mode enter
    ModeExit = 1  # executes on mode exit
    ModeGlobalEnter = 2  # executes on any mode change (activate)
    ModeGlobalExit = 3  # executes on any mode change (deactivate)
    ModeProfileLoad = 4  # executes on profile load
    ModeProfileStart = 5  # executes on profile start
    ModeProfileStop = 6  # executes on profile stop

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

        return f"Unknown mode: {value}"


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
    pass


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

        # ensure inputs are defined
        self.ensureInputItems()

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

    def _load_handler(self, model: ModeInputItemModel, emit=True) -> bool:
        """called when the data model for the input list needs to be updated - refreshes the model view"""

        model.pushSuspend()  # suspend triggers
        model.clear(emit=False)
        registry = gremlin.shared_state.current_profile.registry
        mode = gremlin.shared_state.edit_mode
        # main inputs
        input_list = registry.getInputItems(self.device_guid, gremlin.shared_state.master_mode, InputType.ModeControl)
        input_list.extend(registry.getInputItems(self.device_guid, mode, InputType.ModeControl))
        if len(input_list) > 0:
            input_list.sort(key=lambda x: x.sortKey)
            for index, input_item in enumerate(input_list):
                model.setItemAt(index, input_item)

        model.popSuspend()  # resume triggers
        if emit:
            model.trigger()  # causes an update
        return True

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
        self.ensureInputItems()


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

    def ensureInputItems(self, refresh=False):
        """ensures we have input items for the current mode
        :param refresh: True if list view should be updated if changes are made
        :returns: True if changes were made

        """

        # mode actions are tied to the individual mode

        current_mode = self.current_mode
        # syslog.info(f"ensure: mode: {current_mode}")
        mode_object = self.device_profile.ensure_mode_exists(profile=self.profile, mode_name=current_mode, device=self.device_guid)

        # mode changes are tied to the master mode - so apply
        master_mode = ModeDeviceTabWidget.master_mode
        master_mode_object = self.device_profile.ensure_mode_exists(profile=self.profile, mode_name=master_mode, is_system=True, device=self.device_guid)

        changed = False
        registry = gremlin.shared_state.current_profile.registry

        def created_handler(input_item):
            nonlocal changed
            changed = True

        # ensure the mode exists
        modeEnter = registry.getInputItem(
            device_guid= ModeDeviceTabWidget.device_guid,
            device_type=DeviceType.ModeControl,
            input_type=InputType.ModeControl,
            input_id=ModeInputModeType.ModeEnter,
            mode_name = mode_object.name,
            override_input_type=InputType.JoystickButton,
            custom_name_handler=self._custom_name_handler,
            autocreate=True,
            create_handler=created_handler,
            tooltip = f"Triggers on mode [{mode_object.name}] entry",
            # description="Mode Enter",
            # description_readonly=True,
        )

        modeExit = registry.getInputItem(
            device_guid=gremlin.shared_state.mode_tab_guid,
            device_type=DeviceType.ModeControl,
            input_type=InputType.ModeControl,
            input_id=ModeInputModeType.ModeExit,
            mode_name=mode_object.name,
            override_input_type=InputType.JoystickButton,
            custom_name_handler=self._custom_name_handler,
            autocreate=True,
            create_handler=created_handler,
            tooltip = f"Triggers on mode [{mode_object.name}] exit",
            # description="Mode Exit",
            # description_readonly=True,
        )

        modeProfileStart = registry.getInputItem(
            device_guid=gremlin.shared_state.mode_tab_guid,
            device_type=DeviceType.ModeControl,
            input_type=InputType.ModeControl,
            input_id=ModeInputModeType.ModeProfileStart,
            mode_name=master_mode_object.name,
            override_input_type=InputType.JoystickButton,
            custom_name_handler=self._custom_name_handler,
            autocreate=True,
            create_handler=created_handler,
            tooltip = "Triggers on profile start",
            # description="Profile Start",
            # description_readonly=True,
        )

        modeProfileStop = registry.getInputItem(
            device_guid=gremlin.shared_state.mode_tab_guid,
            device_type=DeviceType.ModeControl,
            input_type=InputType.ModeControl,
            input_id=ModeInputModeType.ModeProfileStop,
            mode_name=master_mode_object.name,
            override_input_type=InputType.JoystickButton,
            custom_name_handler=self._custom_name_handler,
            autocreate=True,
            create_handler=created_handler,
            tooltip = "Triggers on profile stop",
            # description="Profile Stop",
            # description_readonly=True,
        )

        if self.inputItemListModel is not None and changed or refresh:
            self.refreshInputItems()

        return changed

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
        mode = self.device_profile.modes[current_mode]
        sorted_keys = list(mode.config[InputType.ModeControl].keys())
        return sorted_keys.index(input_id)

    def getWidgetKey(self, input_type, input_id):
        """gets the content widget compound key for the item / input combination"""
        mode = gremlin.shared_state.edit_mode
        return (self._device_guid, input_type, input_id, mode)

    # def _select_item_cb(self, index):
    #     """Handles the selection of an input item.

    #     :param index the index of the selected item
    #     """
    #     if not Shiboken.isValid(self.inputItemListView):
    #         return

    #     if index == -1:
    #         # nothing to select
    #         return

    #     self.ensureInputItems(True) # ensure the control inputs exist for this mode

    #     if index == -1:
    #         index = self._last_selected_index

    #     if index == -1:
    #         # select the first item
    #         if self.inputItemListModel.rows():
    #             index = 0
    #         else:
    #             self._blank_input()
    #             return

    #     with QtCore.QSignalBlocker(self.inputItemListView):
    #         self.inputItemListView.select_item(index, False)

    #     input_item : gremlin.input_item.InputItem = self.inputItemListModel.data(index)
    #     input_type = InputType.ModeControl

    #     key = self.getWidgetKey(input_type, index)
    #     widget = self.getRegisteredWidget(key)
    #     if not widget:
    #         widget = gremlin.input_item.InputItemMappingWidget(input_item = input_item, object_name = f"Mode  [{input_item.display_name}]")
    #         self.registerWidget(key, widget)
    #         widget.redraw() # load the data

    #     self._item_data = input_item

    #     widget = self.selectRegisteredWidget(key)

    #     # remember the last input
    #     config = gremlin.config.Configuration()
    #     device_guid = self.device_guid
    #     input_type = InputType.ModeControl
    #     input_id = input_item.input_id if input_item else None

    #     profile = gremlin.shared_state.current_profile
    #     if profile:
    #         profile.setLastInput(device_guid, input_type, input_id)
    #     config.set_last_input(device_guid, input_type, input_id)

    #     if input_item:

    #         # Create new configuration widget
    #         input_item.is_axis = False
    #         change_cb = self._create_change_cb(index)
    #         widget.action_model.data_changed.connect(change_cb)
    #         widget.description_changed.connect(change_cb)

    #         self.inputItemListView.select_item(index,False)

    #         # update container display if blank
    #         self.updateContainerViewBlankMessage(input_item)

    #     self._last_selected_index = index
    #     el = gremlin.event_handler.EventListener()
    #     el.input_selection_changed.emit(device_guid, input_type, input_id )

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
            identifier=identifier,
            populate_ui_callback=self._populate_input_widget_ui,
            update_callback=self._update_input_widget,
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
        mode = self.device_profile.modes[self.current_mode]
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
        self.ensureInputItems()
        self.inputItemListModel.mode = mode
        self.inputItemListModel.refresh()

        self.selectInputItemIndex(self._last_selected_index)

    def refresh(self, emit=True):
        """Refreshes the current selection, ensuring proper synchronization."""
        self.set_mode(gremlin.shared_state.edit_mode)  # force a model and reload
