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
from typing import Callable
import logging

from PySide6 import QtWidgets, QtCore

import dinput
from dinput import DeviceSummary

import gremlin.config
import gremlin.ui.ui_common
import gremlin.base_profile
import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.input_types import InputType
import gremlin.ui
import gremlin.input_item
import gremlin.util
import gremlin.ui.ui_common
from shiboken6 import Shiboken
from psygnal import Signal
import gremlin.util


syslog = logging.getLogger("system")


class JoystickInputModel(gremlin.input_item.InputItemListModel):
    """model for the list of input items for a joystick device"""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        device_guid: str,
        mode: str,
        custom_filter_handler: Callable = None,
        show_filtered_only=False,
    ):
        """creates a new model for the input items of a joystick device

        :param profile the profile data for the device this model represents
        :param device_guid the GUID of the device this model represents
        :param mode the current mode to display inputs for
        :param custom_filter_handler a handler that takes an input item and returns true if it should be filtered (not displayed) or false if it should be visible
        :param show_filtered_only if true only show filtered items, if false show all items with filtered items visually indicated
        """
        super().__init__(
            profile=profile,
            device_guid=device_guid,
            mode=mode,
            allowed_types=[
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat,
            ],
            custom_filter_handler=custom_filter_handler,
            custom_sort_handler=self._custom_sort,
            show_filtered_only=show_filtered_only,
        )

    def _custom_sort(self, items):
        """sorting for joystick devices has axes first, buttons next, hats last"""
        data = [(item, item.sortKey) for item in items]
        data.sort(key=lambda x: x[1])
        # sequence the list
        indices = (data.index(x) for x in data)
        return indices


class JoystickDeviceTabWidget(gremlin.input_item.BaseDeviceTabWidget):
    """Widget used to display the input joystick device."""

    inputChanged = Signal(str, object, object)  # indicates the input selection changed sends (device_guid string, input_type, input_id)

    def __init__(
        self,
        device: DeviceSummary,
        profile: gremlin.base_profile.Profile,
        mode: str,
        object_name="Joystick",
        data=None,
        parent=None,
    ):
        """Creates a new object instance.

        :param device device information about this widget's device
        :param profile profile data of the entire device
        :param mode the current mode to display
        :param parent the parent of this widget
        """

        assert isinstance(device, DeviceSummary), "Device invalid"

        self.device_guid = device.device_guid
        super().__init__(
            device=device,
            profile=profile,
            mode=mode,
            object_name=object_name,
            enable_filter=True,
            parent=parent,
        )

        config = gremlin.config.Configuration()

        # Store parameters

        self.data: gremlin.ui.tab = data

        self._refresh_lock = False  # semaphore to block refresh in progress
        self.hook_id = gremlin.util.get_guid()
        self.curve_update_handler = {}  # map of curve handlers to the input by index

        self.device = device
        self.profile = profile
        profile.ensure_mode_exists(mode)
        self.device_profile = profile.getDevice(self.device_guid)

        profile = gremlin.shared_state.current_profile

        # self.widget_tracker = gremlin.ui.ui_common.DeviceWidgetTracker() # caches the  InputConfigurationItem for this item
        self.last_item_data_key = None
        self._last_selected_index = _index = 0
        self._last_selected_input_item = None
        self.device_guid = device.device_guid

        self.device_name = device.name
        self._debug_widget = None
        self._input_dirty = False  # true if the input list should be refreshed

        self._last_selected_index = 0  # last selected index in the list

        # if device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
        #     self.inputItemListView.limit_input_types([InputType.JoystickAxis])

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(2)
        if verbose:
            device = gremlin.joystick_handling.getDevice(self._device_guid)
            syslog.info(f"Create Joystick Device tab widget: for [{device.name}]")
            if "left" in device.name.casefold():
                pass

        # model that holds all the input items for the joystick device
        model = JoystickInputModel(
            profile=profile,
            device_guid=device.device_guid,
            mode=mode,
            custom_filter_handler=self._handle_custom_filter,
            show_filtered_only=True,
        )

        self.setInputItemListModel(model)
        model.addCallback(self._handle_model_changed)  # listen to model changes

        # Handle vJoy as input and vJoy as output devices properly
        vjoy_as_input = self.device_profile.parent.settings.vjoy_as_input

        # For vJoy as output only show axes entries, for all others treat them
        # as if they were physical input devices

        # device stats
        self.stats: gremlin.base_profile.JoystickInputStats = profile.settings.getJoystickInputStats(device.device_guid)
        self.stats_widget = gremlin.ui.ui_common.QJoystickInputWidget(device.device_guid)
        self.stats_widget.setStats(self.stats)

        # Add modifiable device label

        line_edit = gremlin.ui.ui_common.QDataLineEdit()
        line_edit.setText(profile.getDeviceLabel(device.device_guid))
        line_edit.textChanged.connect(self.update_device_label)

        # lock widget (add filter for joystick devices)
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data=self.device_guid, filter=True, filter_enabled=True)
        lock_widget.filterChanged.connect(self._handle_filter_changed)

        widget = gremlin.ui.ui_common.getHContainer([self.stats_widget, "||", lock_widget], widget_only=True)

        self.addLeftPanelHeaderWidget(widget)

        width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())

        grids = []

        widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Label:", widget_only=True)
        line_edit.setMinimumWidth(width)
        self.addLeftPanelHeaderWidget(widget)

        grids.append(widget)

        if config.show_container_id:
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            grids.append(widget)

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            grids.append(widget)

        gremlin.ui.ui_common.synchronize_grids(grids)

        # Add a help text for the purpose of the vJoy tab
        if device is not None and device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
            # msg = '''
            #     This tab allows assigning a response curve to virtual axis.
            #     The purpose of this is to enable split and merge axis to be
            #     customized to a user's needs with regards to dead zone and
            #     response curve.
            #     '''
            msg = "Virtual Input Device"
            widget = gremlin.ui.ui_common.QInfoBox(msg)
            self.addLeftPanelHeaderWidget(widget)

        config = gremlin.config.Configuration()

        if config.debug_ui:
            self._debug_widget = QtWidgets.QLabel("Debug widget")
            self._debug_widget.setMaximumHeight(32)
            self.addRightPanelWidget(self._debug_widget)

        el = gremlin.event_handler.EventListener()
        # update on an edit mode change so we update the display
        el.edit_mode_changed.connect(self._handle_edit_mode_changed)
        # update display on config change
        el.config_changed.connect(self._config_changed_cb)

        self.updating = False
        self.last_event = None

    def onInputListViewCreated(self):
        """called when the list view is created"""

        assert self.stats is not None, "stats should be created before listview"
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info("JoystickDevice: update stats on list view create")

        self.update_stats_display(refresh=True)

    def _handle_model_changed(self):
        """called when the input model changes to update the display of stats and filter status"""
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info("JoystickDevice: update stats on model change")
        self.update_stats_display(refresh=True)

    def getDefaultFilter(self) -> dict:
        """gets the default filter for the given device"""

        device_guid = self.device_guid
        device = gremlin.joystick_handling.getDevice(device_guid)
        profile: gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        settings = profile.settings

        # see if the profile has a default input setup saved for this input

        if settings.hasFilterDefinition(device_guid):
            count = settings.getVisibleInputCounts(device_guid, [InputType.JoystickAxis, InputType.JoystickButton])
            if count:
                input_filter = settings.getInputFilter(device_guid)
                return input_filter

        # come up with a default value

        input_filter = {}
        input_filter[device.device_id] = {}

        # default axes
        if device.axis_count:
            axis_count = max(device.axis_count, 3)  # first three axes
            input_filter[device.device_id][InputType.JoystickAxis] = {}
            for index in range(axis_count):
                input_id = device.axis_sequence_to_input_id(index)
                if input_id in input_filter[device.device_id][InputType.JoystickAxis]:
                    del input_filter[device.device_id][InputType.JoystickAxis][input_id]
                else:
                    # not visible
                    input_filter[device.device_id][InputType.JoystickAxis][input_id] = False
        if device.button_count:
            button_count = max(device.button_count, 2)  # first 2 buttons
            input_filter[device.device_id][InputType.JoystickButton] = {}
            for input_id in range(1, button_count + 1):
                if input_id in input_filter[device.device_id][InputType.JoystickButton]:
                    del input_filter[device.device_id][InputType.JoystickButton][input_id]
                else:
                    input_filter[device.device_id][InputType.JoystickButton][input_id] = False
        # ignore hats

        # save the defaults to the settings
        settings.applyFilter(input_filter)

        return input_filter

    def getInputFilter(self):
        """gets the input filter for the current device """
        profile = gremlin.shared_state.current_profile
        return profile.settings.getInputVisibleMap()

    def update_stats(self):
        """updates mappings and filter stats"""
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateFilters(self.getInputFilter())
            self.stats.updateMappings()

    def ensure_stats(self):
        """ensures we have joystick input stats for the current device"""
        if not self.stats:
            profile = gremlin.shared_state.current_profile
            self.stats: gremlin.base_profile.JoystickInputStats = profile.settings.getJoystickInputStats(self.device_guid)

    def update_mappings(self):
        """updates input mapping status data"""
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateMappings()

    def update_filtered(self):
        """updates input mapping filter status data"""
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateFilters(self.getInputFilter())

    def update_stats_display(self, refresh: bool = True):
        """updates the display of stats"""
        if refresh:
            self.update_stats()

        self.stats_widget.setStats(self.stats)

    def _handle_custom_filter(self, input_item):
        """custom filter handled - true if the item is included in the list, false if not"""
        profile = gremlin.shared_state.current_profile

        verbose = gremlin.config.Configuration().verbose_mode_filter

        # filtered = true if the input should not be displayed (filtered), false if it should be visible
        include = profile.isInputFiltered(input_item.device_guid, input_item.input_type, input_item.input_id)
        if verbose and include:
            syslog.info(f"custom filter: {input_item.input_type.name} {input_item.input_id} visible")
        return include

    def _handle_filter_changed(self, value: bool):
        gremlin.util.InvokeUiMethod(self._handle_filter_changed_ui, value)  # ensure on UI thread

    def _handle_filter_changed_ui(self, value: bool):
        """update filtered to used inputs only"""

        dialog_filter = JoystickFilterDialog(self.device_guid, callback=self._handle_filter_dialog)
        dialog_filter.exec()

    def _handle_filter_dialog(self):
        """runs when the filter dialog is closed"""
        dialog = self.sender()
        if dialog.accepted:
            # get the current selected input
            input_item = self.inputItemListView.getSelectedItem()

            # see if there are changes to the filter

            # set the filter list from the visible inputs
            self.inputItemListModel.refresh()

            index = self.inputItemListModel.indexOfInputItem(input_item)
            if index == -1 and self.inputItemListModel.rows():
                # select the first item
                index = 0

            if index != -1:
                self.inputItemListView._select_item_ui(index, emit=False)

            # update the repeater
            self.update_stats_display()

            try:
                index = -1

                selected_index = self.inputItemListView.current_index
                input_item = self.inputItemListModel.itemAt(selected_index)
                # filter setup
                self.inputItemListModel.show_filtered = True
                # find the index in the filtered list, -1 if not found
                count = self.inputItemListModel.count()
                if count:
                    index = self.inputItemListModel.indexOf(input_item)
                    if index == -1:
                        # no longer displayed, select the first item
                        index = 0

                if index != -1:
                    self.inputItemListView._select_item_ui(index)

            finally:
                dialog.deleteLater()

    def _handle_locked_changed(self, value: bool):
        if value:
            # lock
            self._handle_lock_inputs(self.device_guid)
        else:
            # unlock
            self._handle_unlock_inputs(self.device_guid)

    def update_used_filter(self, value: bool):
        """handles filter changes"""
        self.inputItemListModel.show_filtered = value

    def _cleanup_ui(self):
        """called when deleted"""
        super()._cleanup_ui()

        if gremlin.util.isSignalConnected(self.inputItemListView, "_edit_curve_item_cb"):
            self.inputItemListView.item_edit_curve.disconnect(self._edit_curve_item_cb)
            self.inputItemListView.item_delete_curve.disconnect(self._delete_curve_item_cb)

            self.inputItemListView.setParent(None)
            self.inputItemListView.deleteLater()

            el = gremlin.event_handler.EventListener()

            el.edit_mode_changed.disconnect(self._handle_edit_mode_changed)
            el.config_changed.disconnect(self._config_changed_cb)
            el.lock_inputs.disconnect(self._handle_lock_inputs)
            el.unlock_inputs.disconnect(self._handle_unlock_inputs)
            el.jump_to_mapped_input.disconnect(self._handle_jump_to_mapped_input)
            el.input_filtered_change.disconnect(self._handle_input_filter_changed)

    def _edit_curve_item_cb(self, widget, index, data):
        """edit curve request"""
        import gremlin.curve_handler
        import gremlin.event_handler

        curve_data: gremlin.curve_handler.AxisCurveData = data.curve_data
        if not curve_data:
            curve_data = gremlin.curve_handler.AxisCurveData()
            curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(data.device_guid, data.input_id)
            curve_data.curve_update()
            data.curve_data = curve_data

        dialog = gremlin.curve_handler.AxisCurveDialog(curve_data)
        gremlin.util.centerDialog(dialog, dialog.width(), dialog.height())

        # hook input value changed handler
        self._curve_update_handler = dialog.curve_update_handler
        self.curve_update_handler[index] = self._curve_update_handler
        # update the dialog with the current input value
        value = gremlin.joystick_handling.get_axis(data.device_guid, data.input_id)
        self._curve_update_handler(value)

        # device_name = gremlin.joystick_handling.getDeviceName(data.device_guid)
        # description = (
        #     f"curve position update: device: [{device_name}] input: [{data.input_id}]"
        # )

        # hook joystick queue to update position on the curve
        # jep = gremlin.event_handler.JoystickEventProcessor()
        # jep.registerCallback(
        #     self.hook_id,
        #     callback=self._handle_curve_update,
        #     device_guid=data.device_guid,
        #     input_type=InputType.JoystickAxis,
        #     input_id=data.input_id,
        #     ui_only=True,
        #     description=description,
        # )

        el = gremlin.event_handler.EventListener()
        el.joystick_event_ui.connect(self._handle_curve_update)

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        self.curve_update_handler[index] = None
        # print ("update curve data")
        data.curve_data.curve_update()

        # renable highlighting
        gremlin.shared_state.pop_suspend_highlighting()

        # jep.unregisterCallback(self.hook_id)

        self._update_curve_icon(index, data)

    def _handle_curve_update(self, event: gremlin.event_handler.Event):
        if not event.is_axis:
            return
        if not event.device_guid == self.device_guid:
            return
        if self._curve_update_handler:
            self._curve_update_handler(event.value)

    def unhook(self):
        # jep = gremlin.event_handler.JoystickEventProcessor()
        # jep.unregisterCallback(self.hook_id)
        pass

    def _delete_curve_item_cb(self, widget, index, data):
        """delete curve request"""
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("Delete this input curve?")
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
            if verbose:
                syslog.info("delete curve data")
            data.curve_data = None
            self._update_curve_icon(index, data)

    def _update_input_value_changed_cb(self, index: int, value: float):
        if index in self.curve_update_handler and self.curve_update_handler[index] is not None:
            self.curve_update_handler[index](value)

    def _handle_edit_mode_changed(self, mode: str):
        gremlin.util.InvokeUiMethod(self._edit_mode_changed_ui, mode)  # ensure on UI thread

    def _edit_mode_changed_ui(self, mode: str):
        """called on edit mode change"""
        if not Shiboken.isValid(self):
            return
        self.set_mode(mode)
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_mode
        if verbose:
            syslog.info(f"DeviceTabWidget: {self.device_name} change mode: [{mode}]")
        self.update_curve_icons()

    def update_curve_icons(self):
        if self.inputItemListView:  # check for delay load
            widgets = self.inputItemListView.getWidgets()
            if widgets:
                for index, widget in enumerate(widgets):
                    if widget is not None:
                        self._update_curve_icon(index, self.inputItemListView.model.data(index))

    def _update_curve_icon(self, index: int, data):
        widget = self.inputItemListView.widget(index)
        if widget is not None:
            widget.update_display()

    def _config_changed_cb(self):
        if self.inputItemListView:  # check for delay load
            self.inputItemListModel.refresh()

    def _custom_widget_handler(self, list_view, index: int, identifier, data, parent=None):
        """creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        """

        if data.input_type == InputType.JoystickAxis:
            widget = gremlin.input_item.InputItemWidget(identifier=identifier, parent=parent, data=data)
            prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
            widget.setIcon(f"{prefix}joystick.png", use_qta=False)
            if widget.axis_repeater_widget is not None and identifier.is_axis:
                widget.axis_repeater_widget.valueChanged.connect(lambda x: self._update_input_value_changed_cb(index, x))
        elif data.input_type == InputType.JoystickButton:
            widget = gremlin.input_item.InputItemWidget(identifier=identifier, parent=parent, data=data)
            widget.setIcon("mdi.gesture-tap-button")
        elif data.input_type == InputType.JoystickHat:
            widget = gremlin.input_item.InputItemWidget(identifier=identifier, parent=parent, data=data)
            widget.setIcon("ei.fullscreen")
        widget.create_action_icons(data)
        widget.disable_close()
        widget.disable_edit()
        widget.setDescription(data.description)
        widget.index = index

        return widget

    @property
    def running(self):
        return gremlin.shared_state.is_running

    def set_mode(self, mode):
        """changes the mode of the tab"""

        if gremlin.config.Configuration().verbose_mode_detailed:
            # syslog = logging.getLogger("system")
            syslog.info(
                f"Device tab: change mode requested: device tab: {gremlin.shared_state.get_device_name(self.device.device_guid)} current mode: [{mode}]  new mode: [{mode}] "
            )

        self.device_profile.ensure_mode_exists(mode, self.device)

        self.inputItemListModel.mode = mode

        # self.inputItemListView.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.inputItemListModel.refresh()
            self.selectInputItemIndex(self._last_selected_index)

    # def _create_change_cb(self, index):
    #     """Creates a callback handling content changes.

    #     :param index the index of the content being changed
    #     :return callback function redrawing changed content
    #     """
    #     return lambda: self.inputItemListView.redraw_index(index)

    def _create_description_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.description_changed_cb(index)

    def update_device_label(self, text):
        """Updates the label assigned to this device.

        :param text the new label text
        """
        self.device_profile.setDeviceLabel(self.device.device_guid, text)

    @property
    def inputCount(self) -> int:
        """number of inputs in the device"""
        return self.inputItemListModel.rows()

    @property
    def inputWidgetCount(self) -> int:
        """number of input widgets currently in the device"""
        return self.inputItemListView.count()

    def input_item_index_lookup(self, index):
        """Returns the profile data belonging to the provided index.

        This function determines which actual input item a given index refers to
        and then returns the content for it.

        :param index the index for which to return the data
        :param input_items the profile data from which to return the data
        :return profile data corresponding to the provided index
        """
        current_mode = gremlin.shared_state.edit_mode
        device_profile = gremlin.shared_state.device_profile_map[self.device_guid]
        self.device_profile.ensure_mode_exists(current_mode, self.device)
        input_items = device_profile.modes[current_mode]
        axis_count = len(input_items.config[InputType.JoystickAxis])
        button_count = len(input_items.config[InputType.JoystickButton])
        hat_count = len(input_items.config[InputType.JoystickHat])

        if index < axis_count:
            # Handle non continuous axis setups
            axis_keys = sorted(input_items.config[InputType.JoystickAxis].keys())
            if not input_items.has_data(InputType.JoystickAxis, axis_keys[index]):
                syslog.error(f"Attempting to retrieve non existent axis input, type={InputType.to_string(InputType.JoystickAxis)} index={axis_keys[index]}")

            return input_items.get_data(InputType.JoystickAxis, axis_keys[index])
        elif index < axis_count + button_count:
            if not input_items.has_data(InputType.JoystickButton, index - axis_count + 1):
                syslog.error(
                    f"Attempting to retrieve non existent button input, type={InputType.to_string(InputType.JoystickButton)} index={index - axis_count + 1}"
                )

            return input_items.get_data(InputType.JoystickButton, index - axis_count + 1)
        elif index < axis_count + button_count + hat_count:
            if not input_items.has_data(InputType.JoystickHat, index - axis_count - button_count + 1):
                syslog.error(
                    f"Attempting to retrieve non existent hat input, type={InputType.to_string(InputType.JoystickHat)} index={index - axis_count - button_count + 1}"
                )

            return input_items.get_data(InputType.JoystickHat, index - axis_count - button_count + 1)


class JoystickFilterDialog(gremlin.ui.ui_common.QRememberDialog):
    # class JoystickInputDialog(QtWidgets.QDialog):
    """handles the filtering of inputs"""

    def __init__(self, device_guid, callback=None, parent=None):
        """
        :param device_guid: the id of the device being filtered
        :param callback: close handler (optional)
        :param parent: parent widget, optional
        """

        super().__init__(self.__class__.__name__, parent=parent)
        # super().__init__(parent=parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle("Input Filter Configuration")
        self.setModal(True)

        try:
            # self.setUpdatesEnabled(False)

            self.input_widgets = {}  # holds a reference to the input widget

            device = gremlin.joystick_handling.getDevice(device_guid)
            self.device = device
            self.device_guid = device.device_guid

            profile = gremlin.shared_state.current_profile

            self._build_input_filter()  # get the inputs for the current device
            self._base_hash = gremlin.util.hashDict(self.input_visible_map)  # get a base hash value

            self.stats = gremlin.base_profile.JoystickInputStats(self.device_guid, self.input_visible_map)

            # device properties

            self.stats_widget = gremlin.ui.ui_common.QJoystickInputWidget(self.device_guid)

            mapped_count_widget = QtWidgets.QLabel("")

            widgets = [
                "Input filter for:",
                device.name,
            ]

            header_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

            self.main_layout.addWidget(header_widget)
            container = gremlin.ui.ui_common.getHContainer([self.stats_widget, mapped_count_widget], widget_only=True)
            stats_container = gremlin.ui.ui_common.getHContainer(container, widget_only=True)
            self.main_layout.addWidget(stats_container)

            css = gremlin.ui.ui_common.Color.cssButtonState()

            data = []
            if device.axis_count:
                input_type = InputType.JoystickAxis
                for index in range(device.axis_count):
                    linear_id = index + 1
                    input_id = device.axis_sequence_to_input_id(index)
                    # syslog.info(f"{device.name} axis {index} linear index: {linear_id} -> input {input_id}")
                    name = device.getAxisName(input_id)
                    data.append((device_guid, input_type, input_id, name, linear_id))
            if device.button_count:
                input_type = InputType.JoystickButton
                for index in range(device.button_count):
                    input_id = index + 1
                    name = device.get_button_name(input_id)
                    data.append((device_guid, input_type, input_id, name, input_id))
            if device.hat_count:
                input_type = InputType.JoystickHat
                for index in range(device.hat_count):
                    input_id = index + 1
                    name = device.get_hat_name(input_id)
                    data.append((device_guid, input_type, input_id, name, input_id))

            # axis widget

            self.group_widgets = {}
            flow_layouts = {}

            if device.axis_count:
                input_type = InputType.JoystickAxis
                self.group_widgets[input_type] = QtWidgets.QGroupBox(f"Axis ({device.axis_count} inputs, {self.stats.visible_axis_count} visible)")
                flow_layouts[input_type] = gremlin.ui.ui_common.QFlowLayout(self.group_widgets[input_type])

            if device.button_count:
                input_type = InputType.JoystickButton
                self.group_widgets[input_type] = QtWidgets.QGroupBox(f"Buttons ({device.button_count} inputs, {self.stats.visible_button_count} visible)")
                flow_layouts[input_type] = gremlin.ui.ui_common.QFlowLayout(self.group_widgets[input_type])

            if device.hat_count:
                input_type = InputType.JoystickHat
                self.group_widgets[input_type] = QtWidgets.QGroupBox(f"Hats ({device.hat_count} inputs, {self.stats.visible_hat_count} visible)")
                flow_layouts[input_type] = gremlin.ui.ui_common.QFlowLayout(self.group_widgets[input_type])

            mapped_count = 0
            input_count = 0
            device = gremlin.joystick_handling.getDevice(device_guid)
            for _, input_type, input_id, name, linear_id in data:
                is_filtered = self._is_input_visible(input_type, input_id)
                is_used = profile.isInputMapped(device_guid, input_type, input_id)
                if is_used:
                    mapped_count += 1
                input_count += 1
                if linear_id == input_id:
                    tooltip = f"{InputType.to_name(input_type)} {input_id}" if input_type != InputType.JoystickAxis else device.get_axis_name(input_id)
                else:
                    tooltip = (
                        f"{InputType.to_name(input_type)} {input_id}/L{linear_id}" if input_type != InputType.JoystickAxis else device.get_axis_name(input_id)
                    )

                btn = gremlin.ui.ui_common.QUsedPushButton(
                    str(input_id) if input_type != InputType.JoystickAxis else device.get_axis_name(input_id, short_name=True),
                    used=is_used,
                    callback=self._handle_toggle,
                    data=(input_type, input_id),
                    checkable=True,
                    checked=is_filtered,
                    tooltip=tooltip,
                )
                btn.setStyleSheet(css)

                flow_layouts[input_type].addWidget(btn)

                if input_type not in self.input_widgets:
                    self.input_widgets[input_type] = {}
                self.input_widgets[input_type][input_id] = btn

            self.input_map = data

            mapped_count_widget.setText(f"- Found {input_count} input(s), {mapped_count} mapped")
            self.stats_widget.setStats(self.stats)

            container_group, container_layout = gremlin.ui.ui_common.getVContainer()
            # add groups
            for group_widget in self.group_widgets.values():
                container_layout.addWidget(group_widget)

            # scroll area
            self.scroll_area = gremlin.ui.ui_common.QScrollableWidget(container_group)
            self.scroll_area.setMinimumHeight(200)
            self.main_layout.addWidget(self.scroll_area)

            widgets = []

            widget = gremlin.ui.ui_common.QDataPushButton(
                "Default",
                callbackEx=self._handle_filter,
                data="default",
                tooltip="Automatic default.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)

            # show mapped button always
            current_mode = gremlin.shared_state.edit_mode
            widget = gremlin.ui.ui_common.QDataPushButton(
                f"Mapped ({current_mode})",
                callbackEx=self._handle_filter,
                data="mapped",
                tooltip=f"Include mapped inputs in mode [{current_mode}] only.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)

            # show mapped button always
            widget = gremlin.ui.ui_common.QDataPushButton(
                "Mapped (all)",
                callbackEx=self._handle_filter,
                data="mapped_all",
                tooltip="Include mapped inputs only for all profile modes.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)

            if device.axis_count:
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Hide Axis",
                    callbackEx=self._handle_filter,
                    data="hide_axis",
                    tooltip="Hide all axes",
                )
                widgets.append(widget)
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Show Axis",
                    callbackEx=self._handle_filter,
                    data="show_axis",
                    tooltip="Show all axes",
                )
                widgets.append(widget)

            if device.button_count:
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Hide Buttons",
                    callbackEx=self._handle_filter,
                    data="hide_buttons",
                    tooltip="Remove all buttons",
                )
                widgets.append(widget)
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Show Buttons",
                    callbackEx=self._handle_filter,
                    data="show_buttons",
                    tooltip="Show all buttons",
                )
                widgets.append(widget)

            if device.hat_count:
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Hide Hats",
                    callbackEx=self._handle_filter,
                    data="hide_hats",
                    tooltip="Remove all hats",
                )
                widgets.append(widget)
                widget = gremlin.ui.ui_common.QDataPushButton(
                    "Show Hats",
                    callbackEx=self._handle_filter,
                    data="show_hats",
                    tooltip="Show all hats",
                )
                widgets.append(widget)

            widget = gremlin.ui.ui_common.QDataPushButton(
                "Hide All",
                callbackEx=self._handle_filter,
                data="hide_all",
                tooltip="Hide all inputs.\nUse Ctrl-Click to apply to all devices.",
            )
            widgets.append(widget)
            widget = gremlin.ui.ui_common.QDataPushButton(
                "Show All",
                callbackEx=self._handle_filter,
                data="show_all",
                tooltip="Show all inputs",
            )
            widgets.append(widget)
            widget = gremlin.ui.ui_common.QDataPushButton(
                "Revert",
                callbackEx=self._handle_filter,
                data="revert",
                tooltip="Revert to current",
            )
            widgets.append(widget)

            widget = gremlin.ui.ui_common.getFlowContainer(widgets, widget_only=True)
            self.main_layout.addWidget(widget)

            msg = """Toggle visible inputs by clicking on them, or press one of the shortcut actions. Control-click on <b>Default</b>, <b>Mapped</b> and <b>Hide All</b> shortcuts to apply the filter to all devices.
    Shift-click makes the filter additive (existing visible inputs will not be removed).
    Mapped inputs are shown with a green dot.
    Inputs will highlight when the associated axis, button or hat is triggered to help with identification.
    If an input is hidden, it can be made visible again in this dialog.  Hidden inputs do not delete any mappings.
    """
            info_widget = gremlin.ui.ui_common.QInfoBox(msg, hide_key=self.__class__.__name__)

            self.main_layout.addWidget(info_widget)

            self.main_layout.addStretch()

            # status for device filter
            self.status_widget = gremlin.ui.ui_common.QIconLabel()
            self.main_layout.addWidget(self.status_widget)

            self.save_default_widget = QtWidgets.QPushButton("Set Default for device")
            self.save_default_widget.clicked.connect(self._handle_set_default_for_device)
            self.save_default_widget.setToolTip("Saves the current filter selection as default for new profiles for this device")

            self.delete_default_widget = QtWidgets.QPushButton("Delete Default")
            self.delete_default_widget.clicked.connect(self._handle_delete_default_for_device)
            self.delete_default_widget.setToolTip("Saves the current filter selection as default for new profiles for this device")

            self.ok_widget = QtWidgets.QPushButton("Ok")
            self.ok_widget.clicked.connect(self._ok_button_cb)

            self.cancel_widget = QtWidgets.QPushButton("Cancel")
            self.cancel_widget.clicked.connect(self._cancel_button_cb)
            widgets = [
                self.save_default_widget,
                self.delete_default_widget,
                "||",
                self.ok_widget,
                self.cancel_widget,
            ]

            widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
            self.main_layout.addWidget(widget)

            if callback:
                self.accepted.connect(callback)

            # hook inputs so buttons can highlight
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event_handler)
        finally:
            pass


        self._update_ui()

    def _update_ui(self):
        """updates widgets"""
        profile = gremlin.shared_state.current_profile
        delete_visible = False
        if profile.settings.isDefaultFiltered(self.device.device_guid):
            icon = gremlin.ui.ui_common.Icons.recordIcon("#1EC047")
            label = "This device has a default saved."
            delete_visible = True
        else:
            icon = gremlin.ui.ui_common.Icons.recordIcon("#7E7E7E")
            label = "No saved defaults found."
        self.status_widget.setIcon(icon)
        self.status_widget.setText(label)
        self.delete_default_widget.setVisible(delete_visible)

    def _build_input_filter(self):
        """builds the input list from the profile settings"""
        profile = gremlin.shared_state.current_profile
        device = self.device
        device_guid = device.device_id  # use string version
        self.input_visible_map = {}
        self.input_visible_map[device_guid] = {}

        if device.axis_count:
            self.input_visible_map[device_guid][InputType.JoystickAxis] = {}
            for index in range(device.axis_count):
                input_id = device.getAxisInputId(index+1)
                self.input_visible_map[device_guid][InputType.JoystickAxis][input_id] = profile.settings.getInputVisible(
                    device_guid, InputType.JoystickAxis, input_id
                )
        if device.button_count:
            self.input_visible_map[device_guid][InputType.JoystickButton] = {}
            for index in range(device.button_count):
                input_id = index + 1
                self.input_visible_map[device_guid][InputType.JoystickButton][input_id] = profile.settings.getInputVisible(
                    device_guid, InputType.JoystickButton, input_id
                )
        if device.hat_count:
            self.input_visible_map[device_guid][InputType.JoystickHat] = {}
            for index in range(device.hat_count):
                input_id = index + 1
                self.input_visible_map[device_guid][InputType.JoystickHat][input_id] = profile.settings.getInputVisible(
                    device_guid, InputType.JoystickHat, input_id
                )

    def closeEvent(self, event):
        self.input_widgets.clear()  # remove all widget references
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._joystick_event_handler)
        gremlin.util.clear_layout(self.main_layout)  # free up QT resources
        return super().closeEvent(event)

    def _joystick_event_handler(self, event):
        """handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time"""
        if event.device_guid != self.device_guid:
            # not an event we care about
            return

        input_id = event.identifier
        input_type = event.event_type

        if input_type in self.input_widgets and input_id in self.input_widgets[input_type]:
            btn = self.input_widgets[input_type][input_id]
            match input_type:
                case InputType.JoystickAxis:
                    btn.pulseHighlight()
                case InputType.JoystickButton:
                    btn.setHighlight(event.is_pressed)
                case InputType.JoystickHat:
                    value = event.value
                    is_pressed = value != (0, 0)
                    btn.setHighlight(is_pressed)

    def dump_filter(self, p_device_guid=None):
        syslog.info("=" * 30)
        syslog.info("dialog input filter dump")
        visible_count = 0

        for device_guid, input_type, input_id, _, _ in self.input_map:
            if p_device_guid and p_device_guid != device_guid:
                continue
            is_included = self._is_input_visible(input_type, input_id)
            if not is_included:
                # syslog.info(f"\t{input_type.name} {input_id} visible")
                visible_count += 1

        syslog.info(f"\tVisible count: {visible_count}")

    @QtCore.Slot()
    def _handle_filter(self, widget, is_control: bool, is_shift: bool, is_alt: bool, is_right: bool):
        mode = widget.data
        profile = gremlin.shared_state.current_profile
        device = self.device
        device_guid = self.device_guid

        # global modes that impact multiple inputs
        match mode:
            case "default":
                # do the default selection

                config = gremlin.config.Configuration()
                max_count = config.device_filter_max_axis
                if device.axis_count > max_count:
                    self._set_default_filter_list(device, InputType.JoystickAxis, max_count, is_shift)
                max_count = config.device_filter_max_button
                if device.button_count > max_count:
                    self._set_default_filter_list(device, InputType.JoystickButton, max_count, is_shift)
                max_count = config.device_filter_max_hat
                if device.hat_count > max_count:
                    self._set_default_filter_list(device, InputType.JoystickHat, max_count, is_shift)

                if is_control:
                    # apply to all devices
                    profile.settings.setAllFiltered(mode)
                    gremlin.ui.ui_common.MessageBox(
                        prompt="Default filter applied to all joystick devices",
                        is_warning=False,
                    )

                return

            case "revert":
                # revert to current
                self._build_input_filter()

        prompt = None

        applied_all_filter = []
        for device_guid, input_type, input_id, _, _ in self.input_map:
            included = False
            match mode:
                case "mapped":
                    # filter to mapped devices only
                    current_mode = gremlin.shared_state.edit_mode

                    if is_control and mode not in applied_all_filter:
                        profile.settings.setAllFiltered(mode)
                        applied_all_filter.append(mode)
                        # if not prompt:
                        #     prompt="Mapped filter applied to all joystick devices"

                    included = profile.isInputMapped(device_guid, input_type, input_id, current_mode)

                case "mapped_all":
                    if is_control:
                        profile.settings.setAllFiltered(mode)
                        applied_all_filter.append(mode)
                    # if not prompt:
                    #     prompt="Mapped filter applied to all joystick devices"

                    included = profile.isInputMapped(device_guid, input_type, input_id)

                case "show_all":
                    # filter all inputs
                    included = True  # remove all filters
                case "hide_axis":
                    # hide axes
                    if input_type != InputType.JoystickAxis:
                        continue
                    included = False
                case "show_axis":
                    # show axes
                    if input_type != InputType.JoystickAxis:
                        continue
                    included = True

                case "hide_buttons":
                    # hide buttons
                    if input_type != InputType.JoystickButton:
                        continue
                    included = False
                case "show_buttons":
                    # show buttons
                    if input_type != InputType.JoystickButton:
                        continue
                    included = True

                case "hide_hats":
                    # hide hats
                    if input_type != InputType.JoystickHat:
                        continue
                    included = False

                case "hide_all":
                    # hide all inputs
                    included = False
                    if is_control and mode not in applied_all_filter:
                        profile.settings.setAllFiltered(mode)
                        applied_all_filter.append(mode)
                        if not prompt:
                            prompt = "Hide All filter applied to all joystick devices"

                case "revert":
                    # revert to original
                    included = self._is_input_visible(input_type, input_id)

                case _:
                    continue

            # if verbose: syslog.info(f"{input_type.name} {input_id} {filtered}")
            btn: gremlin.ui.ui_common.QDataPushButton = self.input_widgets[input_type][input_id]
            selected = not included
            if not selected and is_shift and not btn.isChecked():
                # add to the selection
                btn.setChecked(True)
                self._set_input_visible(input_type, input_id, included)
            else:
                btn.setChecked(selected)  # turn on or off
                self._set_input_visible(input_type, input_id, included)

        self.updateGroups()

        if prompt:
            gremlin.ui.ui_common.MessageBox(prompt=prompt, is_warning=False)

    def updateGroups(self):
        device = self.device
        # group headers
        if device.axis_count:
            self.group_widgets[InputType.JoystickAxis].setTitle(f"Axis ({device.axis_count} inputs, {self.stats.visible_axis_count} visible)")
        if device.button_count:
            self.group_widgets[InputType.JoystickButton].setTitle(f"Button ({device.button_count} inputs, {self.stats.visible_button_count} visible)")
        if device.hat_count:
            self.group_widgets[InputType.JoystickHat].setTitle(f"Hat ({device.hat_count} inputs, {self.stats.visible_hat_count} visible)")

    def _set_default_filter_list(
        self,
        device: dinput.DeviceSummary,
        input_type: InputType,
        max_count: int,
        add_only=False,
    ):
        """sets a default list of filtered inputs based on given parameters"""

        _device_guid = device.device_guid
        match input_type:
            case InputType.JoystickAxis:
                device_count = device.axis_count
            case InputType.JoystickButton:
                device_count = device.button_count
            case InputType.JoystickHat:
                device_count = device.hat_count
            case _:
                # not an input type we care about
                return

        visible_list = []
        map_data = [index + 1 for index in range(device_count)]  # all possible inputs
        profile = gremlin.shared_state.current_profile

        for index in range(device_count):
            input_id = index + 1
            mapped = profile.isInputMapped(self.device_guid, input_type, input_id)
            if mapped:
                self._set_input_visible(input_type, input_id, False, emit=False)
                btn = self.input_widgets[input_type][input_id]
                with QtCore.QSignalBlocker(btn):
                    btn.setChecked(False)
                visible_list.append(input_id)
                map_data.remove(input_id)

        if len(visible_list) < max_count:
            # take the first n inputs
            count = max_count - len(visible_list)
            add_list = map_data[:count]
            if add_list:
                visible_list.extend(add_list)

        # remove visible list from filtered list
        if map_data:
            map_data = [i for i in map_data if i not in visible_list]

        for index in range(device_count):
            if input_type == InputType.JoystickAxis:
                # correct for skipped axes
                input_id = device.getAxisInputId(index + 1)
                assert input_id in device.axis_id_map, f"Input id {input_id} not found in device axis map for device {device.name}"
            else:
                input_id = index + 1
            filtered = input_id in map_data
            btn = self.input_widgets[input_type][input_id]

            if filtered and add_only and btn.isChecked():
                # item should be filtered = only apply if not cummulative
                continue

            self._set_input_visible(input_type, input_id, filtered, emit=False)

            with QtCore.QSignalBlocker(btn):
                btn.setChecked(not filtered)

        # update stats
        self.stats.updateFilters(self.input_visible_map)
        self.stats_widget.setStats(self.stats)

    @QtCore.Slot()
    def _handle_toggle(self, btn):
        """handles a filter change"""
        data = btn.data
        input_type, input_id = data

        visible = btn.isChecked()
        # syslog.info(f"checked: {visible} input id: {input_id}")
        is_filtered = visible
        self._set_input_visible(input_type, input_id, is_filtered, emit=False)

    def _set_input_visible(self, input_type: InputType, input_id: int, visible: bool, emit=False):
        """sets the filtered state internal to the dialog"""
        verbose = gremlin.config.Configuration().verbose_mode_filter

        device_guid = self.device.device_id  # use string representation
        if device_guid not in self.input_visible_map:
            self.input_visible_map[device_guid] = {}
        if input_type not in self.input_visible_map[device_guid]:
            self.input_visible_map[device_guid][input_type] = {}
        if verbose:
            syslog.info(f"Toggle {input_type.name} {input_id} {visible}")
        if visible:
            # visible does not show in the input filter
            if input_id in self.input_visible_map[device_guid][input_type]:
                del self.input_visible_map[device_guid][input_type][input_id]
        else:
            self.input_visible_map[device_guid][input_type][input_id] = visible
        if verbose and input_type == InputType.JoystickAxis:
            syslog.info(f"set filter: {self.device.name} axis: {input_id} included: {visible}")
        if emit:
            self.stats.updateFilters(self.input_visible_map)
            self.stats_widget.setStats(self.stats)
            self.updateGroups()

            el = gremlin.event_handler.EventListener()
            el.input_filtered_change.emit(device_guid)  # tell the widget the input list has changed

    def _is_input_visible(self, input_type: InputType, input_id: int) -> bool:
        """true if the input is visible, false if not"""
        device_guid = self.device.device_id
        if device_guid not in self.input_visible_map:
            return True
        if input_type not in self.input_visible_map[device_guid]:
            return True
        if input_id not in self.input_visible_map[device_guid][input_type]:
            return True
        value = self.input_visible_map[device_guid][input_type][input_id]
        return value

    @QtCore.Slot()
    def _ok_button_cb(self):
        # update the profile map
        # self.dump_filter(self.device_guid)
        new_hash = gremlin.util.hashDict(self.input_visible_map)
        if new_hash != self._base_hash:
            # has changes
            profile = gremlin.shared_state.current_profile
            for device_guid in self.input_visible_map:
                for input_type in self.input_visible_map[device_guid]:
                    for input_id in self.input_visible_map[device_guid][input_type]:
                        profile.settings.setFiltered(
                            device_guid,
                            input_type,
                            input_id,
                            self.input_visible_map[device_guid][input_type][input_id],
                        )

            self.accept()
        else:
            # issue a cancel instead
            self.reject()

    @QtCore.Slot()
    def _cancel_button_cb(self):
        """cancel button pressed"""
        self.reject()

    @QtCore.Slot()
    def _handle_set_default_for_device(self):
        profile = gremlin.shared_state.current_profile
        device_id = self.device.device_id  # str for input filter
        for input_type in self.input_visible_map[device_id]:
            for input_id in self.input_visible_map[device_id][input_type]:
                profile.settings.setDefaultFiltered(
                    device_id,
                    input_type,
                    input_id,
                    self.input_visible_map[device_id][input_type][input_id],
                )

        # save the profile
        result = profile.settings.saveFilterDefaults()
        if result:
            gremlin.ui.ui_common.MessageBoxInfo(
                prompt=f"Default filter saved.\nDevice [{self.device.name}].",
                parent=self,
            )
        else:
            gremlin.ui.ui_common.MessageBoxWarning(
                prompt=f"Error saving defaults.\nCheck the log file for details.\nDevice [{self.device.name}].",
                parent=self,
            )

        self._update_ui()

    @QtCore.Slot()
    def _handle_delete_default_for_device(self):
        gremlin.ui.ui_common.MessageBoxYesNo(
            prompt=f"Delete defaults for device [{self.device.name}]?",
            callback=self._handle_delete_confirm,
            parent=self,
        )

    def _handle_delete_confirm(self, result):
        if result == QtWidgets.QMessageBox.StandardButton.Yes:
            profile = gremlin.shared_state.current_profile
            device_guid = self.device.device_guid
            result = profile.settings.clearDefaultsFiltered(device_guid)
            if not result:
                gremlin.ui.ui_common.MessageBoxWarning(
                    prompt=f"Error deleting defaults.\nCheck the log file for details.\nDevice [{self.device.name}].",
                    parent=self,
                )
            self._update_ui()
