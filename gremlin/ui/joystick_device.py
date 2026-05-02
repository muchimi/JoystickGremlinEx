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
import lxml.etree
from lxml import etree
import os

import gremlin
import dinput
from dinput import DeviceSummary

import gremlin.base_profile
import gremlin.base_profile
import gremlin.config
import gremlin.config
import gremlin.config
import gremlin.event_handler
import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.profile
import gremlin.shared_state
import gremlin.shared_state
import gremlin.types
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.ui
import gremlin.ui.input_item
import gremlin.util
from gremlin.util import safe_read
import gremlin.ui.ui_common
from  gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType
from shiboken6 import Shiboken
import psygnal
from psygnal import Signal
import gremlin.util
import copy
import vjoy.vjoy

syslog = logging.getLogger("system")



class JoystickDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):

    """Widget used to display the input joystick device."""

    inputChanged = Signal(str, object, object) # indicates the input selection changed sends (device_guid string, input_type, input_id)

    def __init__(
            self,
            device : DeviceSummary,
            device_profile : gremlin.base_profile.Device,
            current_mode,
            object_name = "Joystick",
            data = None,
            parent=None
    ):
        """Creates a new object instance.

        :param device device information about this widget's device
        :param device_profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """
        super().__init__(object_name, device.device_guid, parent)

        import gremlin.plugin_manager
        import gremlin.config
        import gremlin.ui.ui_common
        import gremlin.ui.input_item
        import gremlin

        config = gremlin.config.Configuration()

        # if device.is_virtual and device.vjoy_id == 4:
        #     pass

        # Store parameters

        self.data : gremlin.ui.tab= data
        self._refresh_lock = False # semaphore to block refresh in progress
        self.hook_id = gremlin.util.get_guid()
        self.curve_update_handler = {} # map of curve handlers to the input by index

        self.device = device
        self.device_profile = device_profile
        profile = gremlin.shared_state.current_profile

        self.device_profile.ensure_mode_exists(current_mode, self.device)

        #self.widget_tracker = gremlin.ui.ui_common.DeviceWidgetTracker() # caches the  InputConfigurationItem for this item
        self.last_item_data_key = None
        self.last_selected_index = index = 0
        self.device_guid = device.device_guid
        self.device_name = device.name
        self._debug_widget = None
        self._input_dirty = False # true if the input list should be refreshed

        self._last_selected_index = 0 # last selected index in the list



        # List of inputs
        self.input_item_list_model = gremlin.ui.input_item.InputItemListModel(
            device_profile,
            current_mode,
            custom_filter_handler= self._handle_custom_filter,
            show_filtered_only=True,
        )

        self.input_item_list_view = gremlin.ui.input_item.InputItemListView(name=device.name, custom_widget_handler = self._custom_widget_handler, device_id = device.device_id)


        # Handle vJoy as input and vJoy as output devices properly
        vjoy_as_input = self.device_profile.parent.settings.vjoy_as_input

        # For vJoy as output only show axes entries, for all others treat them
        # as if they were physical input devices
        if device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
            self.input_item_list_view.limit_input_types([InputType.JoystickAxis])

        # device stats
        self.stats : gremlin.base_profile.JoystickInputStats= profile.settings.getJoystickInputStats(device.device_guid)
        self.stats_widget = gremlin.ui.ui_common.QJoystickInputWidget(device.device_guid)
        self.stats_widget.setStats(self.stats)


        self.input_item_list_view.item_edit_curve.connect(self._edit_curve_item_cb)
        self.input_item_list_view.item_delete_curve.connect(self._delete_curve_item_cb)

        # load the model
        self.input_item_list_view.setModel(self.input_item_list_model)
        self._redraw_inputs()


        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)


        # Add modifiable device label

        line_edit = gremlin.ui.ui_common.QDataLineEdit()
        line_edit.setText(device_profile.label)
        line_edit.textChanged.connect(self.update_device_label)



        # lock widget (add filter for joystick devices)
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data = self.device_guid, filter = True, filter_enabled = True)
        lock_widget.filterChanged.connect(self._handle_filter_changed)
        #lock_widget.mappedChanged.connect(self._handle_mapped_changed)


        widget = gremlin.ui.ui_common.getHContainer(
            [
            self.stats_widget,
            "||",
            lock_widget],
            widget_only = True)

        self.addLeftPanelWidget(widget)

        width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())

        grids = []

        widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Label:", widget_only = True)
        line_edit.setMinimumWidth(width)
        self.addLeftPanelWidget(widget)



        grids.append(widget)

        if config.show_container_id:

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only = True)
            self.addLeftPanelWidget(widget)
            grids.append(widget)

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only = True)
            self.addLeftPanelWidget(widget)
            grids.append(widget)

        gremlin.ui.ui_common.synchronize_grids(grids)

        self.addLeftPanelWidget(self.input_item_list_view)

        # Add a help text for the purpose of the vJoy tab
        if device is not None and \
                device.is_virtual and \
                not vjoy_as_input.get(device.vjoy_id, False):

            # msg = '''
            #     This tab allows assigning a response curve to virtual axis.
            #     The purpose of this is to enable split and merge axis to be
            #     customized to a user's needs with regards to dead zone and
            #     response curve.
            #     '''
            msg = "Virtual Input Device"
            widget = gremlin.ui.ui_common.QInfoBox(msg)
            self.addLeftPanelWidget(widget)


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
        # lock all inputs
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)
        el.jump_to_mapped_input.connect(self._handle_jump_to_mapped_input)
        el.input_filtered_change.connect(self._handle_input_filter_changed)
        el.tab_selected.connect(self._handle_tab_changed)


        self.updating = False
        self.last_event = None

        # update the selection if nothing is selected
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None and selected_index != -1:
            self._select_item_cb(selected_index)




        # update all curve icons
        self.update_curve_icons()

        # update filtered status box
        self.update_stats_display()

    def getInputFilter(self):
        profile = gremlin.shared_state.current_profile
        return profile.settings.input_filter

    def update_stats(self):
        ''' updates mappings and filter stats '''
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateFilters(self.getInputFilter())
            self.stats.updateMappings()

    def ensure_stats(self):
        ''' ensures we have joystick input stats for the current device '''
        if not self.stats:
            profile = gremlin.shared_state.current_profile
            self.stats : gremlin.base_profile.JoystickInputStats = profile.settings.getJoystickInputStats(self.device_guid)

    def update_mappings(self):
        ''' updates input mapping status data '''
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateMappings()

    def update_filtered(self):
        ''' updates input mapping filter status data '''
        if not self.stats:
            self.ensure_stats()
        else:
            self.stats.updateFilters(self.getInputFilter())

    def update_stats_display(self, refresh : bool = True):
        ''' updates the display of stats '''
        if refresh:
            self.update_stats()

        self.stats_widget.setStats(self.stats)


    def _handle_custom_filter(self, input_item):
        ''' custom filter handled - true if the item is included in the list, false if not '''
        profile = gremlin.shared_state.current_profile

        verbose = gremlin.config.Configuration().verbose_mode_filter
        # filtered = true if the input should not be displayed (filtered), false if it should be visible
        filtered = profile.isInputFiltered(input_item.device_guid, input_item.input_type, input_item.input_id)
        if verbose and not filtered:
            syslog.info(f"custom filter: {input_item.input_type.name} {input_item.input_id} visible")
        return filtered



    @property
    def inputWidgetCount(self) -> int:
        ''' number of input widgets currently in the device '''
        return self.input_item_list_view.count()

    def _handle_jump_to_mapped_input(self):
        gremlin.util.InvokeUiMethod(self._handle_jump_to_mapped_input_ui)


    def _handle_input_filter_changed(self, device_guid):
        ''' called when input filter is changed '''
        if not gremlin.util.compare_guid(device_guid, self.device_guid) or self._input_dirty:
            # not ours
            return

        verbose = gremlin.config.Configuration().verbose_mode_filter
        if verbose:
            device = gremlin.joystick_handling.getDevice(device_guid)
            syslog.info(f"FILTER: [{device.name}] inputs marked dirty")
        self._input_dirty = True # indicate the list should be refreshed because it has changed

    def _handle_tab_changed(self, device_guid):
        ''' occurs when a tab is made visible '''
        if not gremlin.util.compare_guid(device_guid, self.device_guid):
            # not ours
            return

        if self._input_dirty:
            # update
            self._input_dirty = False
            verbose = gremlin.config.Configuration().verbose_mode_filter
            if verbose:
                device = gremlin.joystick_handling.getDevice(device_guid)
                syslog.info(f"FILTER: [{device.name}] - filter dirty - update list")
            input_item = self.input_item_list_view.selected_item()
            self.input_item_list_model.updateData() # force a model update for the new filter
            for input_item in self.input_item_list_model.getFilteredItems():
                syslog.info(f"\t{input_item.display_name}")
            index = self.input_item_list_model.indexOfInputItem(input_item)
            if index == -1 and self.input_item_list_model.rows():
                # select the first item
                index = 0
            self._redraw_inputs()


    def _handle_jump_to_mapped_input_ui(self):
        ''' jumps to the first mapped input '''
        if Shiboken.isValid(self):
            for input_item in self.input_item_list_model.getFilteredItems():
                if input_item.hasContainers:
                    index = self.input_item_list_model.indexOfInputItem(input_item)
                    self.select_item(index)
                    self.input_item_list_view.select_item(index, emit = False)
                    break


    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data) # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data) # ensure on UI thread

    def _handle_lock_inputs_ui(self, data):
        ''' lock all inputs event'''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.input_item_list_model.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        ''' unlock all inputs event '''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.input_item_list_model.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)



    def _handle_filter_changed(self, value : bool):
        gremlin.util.InvokeUiMethod(self._handle_filter_changed_ui, value) # ensure on UI thread

    def _handle_filter_changed_ui(self, value : bool):
        ''' update filtered to used inputs only'''

        dialog_filter = JoystickInputDialog(self.device_guid, callback = self._handle_filter_dialog)
        dialog_filter.exec()



    def _handle_filter_dialog(self):
        ''' runs when the filter dialog is closed'''
        dialog = self.sender()
        if dialog.accepted:
            # get the current selected input
            input_item = self.input_item_list_view.selected_item()

            # set the filter list from the visible inputs
            self.input_item_list_model.updateData()

            index = self.input_item_list_model.indexOfInputItem(input_item)
            if index == -1 and self.input_item_list_model.rows():
                # select the first item
                index = 0

            if index != -1:
                self.select_item(index)
                self.input_item_list_view.select_item(index, emit = False)




            # update the repeater
            self.update_stats_display()


            try:
                index = -1
                gremlin.util.pushCursor()
                selected_index = self.input_item_list_view.current_index
                input_item = self.input_item_list_model.inputItemAtIndex(selected_index)
                # filter setup
                self.input_item_list_model.show_filtered = True
                # find the index in the filtered list, -1 if not found
                count = self.input_item_list_model.filteredRows()
                if count:
                    index = self.input_item_list_model.indexOfInputItem(input_item)
                    if index == -1:
                        # no longer displayed, select the first item
                        index = 0

                if index != -1:
                    self.input_item_list_view.select_item(index)

            finally:
                gremlin.util.popCursor()


    def _handle_locked_changed(self, value : bool):
        if value:
            # lock
            self._handle_lock_inputs(self.device_guid)
        else:
            # unlock
            self._handle_unlock_inputs(self.device_guid)

    def update_used_filter(self, value : bool):
        ''' handles filter changes '''
        self.input_item_list_model.show_filtered = value


    def _cleanup_ui(self):
        ''' called when deleted '''
        super()._cleanup_ui()

        if gremlin.util.isSignalConnected(self.input_item_list_view, "_edit_curve_item_cb"):
            self.input_item_list_view.item_edit_curve.disconnect(self._edit_curve_item_cb)
            self.input_item_list_view.item_delete_curve.disconnect(self._delete_curve_item_cb)
            self.input_item_list_view.item_selected.disconnect(self._select_item_cb)
            self.input_item_list_view.setParent(None)
            self.input_item_list_view.deleteLater()

            el = gremlin.event_handler.EventListener()

            el.edit_mode_changed.disconnect(self._handle_edit_mode_changed)
            el.config_changed.disconnect(self._config_changed_cb)
            el.lock_inputs.disconnect(self._handle_lock_inputs)
            el.unlock_inputs.disconnect(self._handle_unlock_inputs)
            el.jump_to_mapped_input.disconnect(self._handle_jump_to_mapped_input)
            el.input_filtered_change.disconnect(self._handle_input_filter_changed)


            




    def _edit_curve_item_cb(self, widget, index, data):
        ''' edit curve request '''
        import gremlin.curve_handler
        import gremlin.event_handler
        curve_data : gremlin.curve_handler.AxisCurveData = data.curve_data
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

        device_name = gremlin.joystick_handling.getDeviceName(data.device_guid)
        description = f"curve position update: device: [{device_name}] input: [{data.input_id}]"

        # hook joystick queue to update position on the curve
        jep = gremlin.event_handler.JoystickEventProcessor()
        jep.registerCallback(
            self.hook_id,
            callback = self._handle_curve_update,
            device_guid = data.device_guid,
            input_type = InputType.JoystickAxis,
            input_id = data.input_id,
            ui_only = True,
            description = description
            )

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        self.curve_update_handler[index] = None
        # print ("update curve data")
        data.curve_data.curve_update()

        # renable highlighting
        gremlin.shared_state.pop_suspend_highlighting()

        jep.unregisterCallback(self.hook_id)

        self._update_curve_icon(index, data)

    def _handle_curve_update(self, event, values):
        if self._curve_update_handler:
            self._curve_update_handler(event.value)

    def unhook(self):
        jep = gremlin.event_handler.JoystickEventProcessor()
        jep.unregisterCallback(self.hook_id)


    def _delete_curve_item_cb(self, widget, index, data):
        ''' delete curve request '''
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("Delete this input curve?")
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            verbose = gremlin.config.Configuration().verbose_mode_ui
            if verbose: syslog.info("delete curve data")
            data.curve_data = None
            self._update_curve_icon(index, data)





    def _update_input_value_changed_cb(self, index : int, value : float):
        if index in self.curve_update_handler and self.curve_update_handler[index] is not None:
            self.curve_update_handler[index](value)


    def _handle_edit_mode_changed(self, mode : str):
        gremlin.util.InvokeUiMethod(self._edit_mode_changed_ui, mode) # ensure on UI thread

    def _edit_mode_changed_ui(self, mode : str):
        ''' called on edit mode change '''
        if not Shiboken.isValid(self):
            return
        self.set_mode(mode)
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_mode
        if verbose: syslog.info(f"DeviceWidget: {self.device_name} change mode: [{mode}]")
        self.update_curve_icons()


    def update_curve_icons(self):
        widgets = self.input_item_list_view.getWidgets()
        if widgets:
            for index, widget in enumerate(widgets):
                if widget is not None:
                    self._update_curve_icon(index, self.input_item_list_view.model.data(index))

    def _update_curve_icon(self, index : int, data):

        widget = self.input_item_list_view.getWidgetAt(index)
        if widget is not None:
            widget.update_display()

    def _redraw_inputs(self, force = False):
        gremlin.util.InvokeUiMethod(self._redraw_inputs_ui, force)

    def _redraw_inputs_ui(self, force = False):
        self.input_item_list_view.redraw(force)
        self.stats.updateFilters(self.getInputFilter())
        self.stats_widget.setStats(self.stats)

    def _config_changed_cb(self):
        self._redraw_inputs()

    def _custom_widget_handler(self, list_view, index : int, identifier, data, parent = None):
        ''' creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        '''


        if data.input_type == InputType.JoystickAxis:
            widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, parent=parent, data = data)
            prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
            widget.setIcon(f"{prefix}joystick.png", use_qta=False)
            if widget.axis_widget is not None and identifier.is_axis:
                widget.axis_widget.valueChanged.connect(lambda x: self._update_input_value_changed_cb(index, x))
        elif data.input_type == InputType.JoystickButton:
            widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, parent=parent, data = data)
            widget.setIcon("mdi.gesture-tap-button")
        elif data.input_type == InputType.JoystickHat:
            widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, parent=parent, data = data)
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


    def getSelectedItem(self):
        index = self._last_selected_index
        if index == -1:
            return None
        return self.input_item_list_model.data(index)



    @QtCore.Slot()
    def _select_item_cb(self, index, force_update = False, emit = True):
        """ Handles the loading of mappings for a given input item - handler for select_input event

        :param index the index of the selected item
        """
        from gremlin.ui.input_item import InputItemMappingWidget
        gremlin.util.assert_ui_thread()

        if not Shiboken.isValid(self) or not Shiboken.isValid(self.input_item_list_view):
            return

        try:

            self.setUpdatesEnabled(False)

            device = gremlin.joystick_handling.getDevice(self.device_guid)

            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_details




            if force_update or self.inputCount > 0 and self.inputWidgetCount == 0:
                self._redraw_inputs(force=True)




            #verbose = True
            # syslog = logging.getLogger("system")
            widget = None
            current_mode = gremlin.shared_state.edit_mode



            if index == -1:
                index = self.last_selected_index

            if index == -1:
                if self.input_item_list_model.rows() > 0:
                    input_item = self.input_item_list_model.data(0)
                    index = 0
                else:
                    self._blank_input()
                    return
            else:
                input_item = self.input_item_list_model.data(index)

            # if not input_item:
            #     syslog.warning(f"JoystickDevice: Device [{device.name}] has no inputs for mode {current_mode} - this is not normal.")

            if verbose:
                if input_item:
                    syslog.info(f"Selecting input config item for {device.name} input index [{index}] mode: {current_mode}: {input_item.debug_display}")
                else:
                    syslog.info(f"Selecting input config item for {device.name} input index [{index}] mode: {current_mode}: Empty content")

            new_key = None

            self.last_item_data_key = new_key



            if input_item is not None:

                # # ensure the LEFT panel widget is selected
                # self.input_item_list_view.clearSelection(emit = False)
                # widget = self.input_item_list_view.getWidgetForInputItem(input_item)
                # widget.setSelected(True, emit = False)


                # select the RIGHT panel item
                device_guid = self.device_guid
                input_type = input_item.input_type
                input_id = input_item.input_id

                key = self.getWidgetKey(input_type, input_id)
                widget = self.getRegisteredWidget(key)
                if not widget:

                    # not in cache, create it and add to cache for this device/input combination
                    if verbose: syslog.info(f"create and store in cache content widget for index: {index}  device: {self.device_guid}")
                    widget = InputItemMappingWidget(input_item, object_name = f"Joystick [{input_item.display_name}]")
                    device_name = gremlin.joystick_handling.device_name_from_guid(self.device_guid)
                    widget.setObjectName(f"InputItemConfig for device {device_name} index: {index} ")
                    widget.action_model.data_changed.connect(self._create_change_cb(index))
                    widget.description_changed.connect(lambda x: self._description_changed_cb(index, x))
                    widget.description_clear.connect(lambda: self._description_clear_cb(index,widget))




                    # indicate the input changed

                    self.registerWidget(key, widget)
                    if emit:
                        self.inputChanged.emit(device_guid, input_type, input_id)

                    #self.widget_tracker.registerWidget(widget, self.device_guid, item_data.input_type, item_data.input_id, item_data.id)

                if force_update:
                    # update the container to reflect the data change
                    widget.setItemData(input_item)

                # make the widget visible
                self.selectRegisteredWidget(key)


                if verbose:
                    syslog.info(f"Show widget:  {widget.id} {input_item.debug_display}")

                if config.debug_ui:
                    self._debug_widget.setText(f"Contents for : {input_item.debug_display}")



            self.last_selected_index = index

            # # ensure input is visible
            # self.input_item_list_view.scrollToInput(item_data)

            if input_item and emit:
                el = gremlin.event_handler.EventListener()
                el.input_selection_changed.emit(device_guid, input_type, input_id)

        finally:
            self.setUpdatesEnabled(True)
            self.update()





    def _description_changed_cb(self, index, text):
        ''' called when the description text of the widget changes to update the description on the input item

        :param: index = the index of the input widget to update with the new text

        '''
        item = self.input_item_list_view.itemAt(index)
        if item:
            item.data.description = text
            item.setDescription(text)
        else:
            syslog.error(f"set description (joystick input) failed: index: [{index}] does not exist.")

    def _description_clear_cb(self, index, widget):
        ''' delete description entry '''
        with QtCore.QSignalBlocker(widget.description_field):
            widget.description_field.setText('')
        item = self.input_item_list_view.itemAt(index)
        item.data.description = None
        item.setDescription('')



    def set_mode(self, mode):
        ''' changes the mode of the tab '''

        if gremlin.config.Configuration().verbose_mode_detailed:
            # syslog = logging.getLogger("system")
            syslog.info(f"Device tab: change mode requested: device tab: {gremlin.shared_state.get_device_name(self.device.device_guid)} current mode: [{mode}]  new mode: [{mode}] ")

        self.device_profile.ensure_mode_exists(mode, self.device)



        self.input_item_list_model.mode = mode

        #self.input_item_list_view.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.input_item_list_model.refresh()
            self._redraw_inputs()
            self.select_item(self._last_selected_index)

    def redraw(self):
        gremlin.util.InvokeUiMethod(self._redraw_ui) # ensure on UI thread

    def _redraw_ui(self):
        ''' updates the list widget '''
        self._redraw_inputs()

    def refresh(self, emit = True):
        gremlin.util.InvokeUiMethod(self._refresh_ui, emit) # ensure on UI thread

    def _refresh_ui(self, emit = True):
        """Refreshes the current selection, ensuring proper synchronization. - ensure on UI thread """
        if self._refresh_lock:
            return
        try:
            self._refresh_lock = True
            self._select_item_cb(self.input_item_list_view.current_index, force_update = True, emit = emit)
        finally:
            self._refresh_lock = False


    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.input_item_list_view.redraw_index(index)

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
        self.device_profile.label = text


    @property
    def inputCount(self) -> int:
        ''' number of inputs in the device '''
        return self.input_item_list_model.rows()

    @property
    def inputWidgetCount(self) -> int:
        ''' number of input widgets currently in the device '''
        return self.input_item_list_view.count()

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
                syslog.error(
                    "Attempting to retrieve non existent axis input, "
                    f"type={InputType.to_string(InputType.JoystickAxis)} index={axis_keys[index]}"
                )

            return input_items.get_data(
                InputType.JoystickAxis,
                axis_keys[index]
            )
        elif index < axis_count + button_count:
            if not input_items.has_data(
                    InputType.JoystickButton,
                    index - axis_count + 1
            ):
                syslog.error(
                    "Attempting to retrieve non existent button input, "
                    f"type={InputType.to_string(InputType.JoystickButton)} index={index - axis_count + 1}"
                )

            return input_items.get_data(
                InputType.JoystickButton,
                index - axis_count + 1
            )
        elif index < axis_count + button_count + hat_count:
            if not input_items.has_data(
                    InputType.JoystickHat,
                    index - axis_count - button_count + 1
            ):
                syslog.error(
                    "Attempting to retrieve non existent hat input, "
                    f"type={ InputType.to_string(InputType.JoystickHat)} index={index - axis_count - button_count + 1}"
                )

            return input_items.get_data(
                InputType.JoystickHat,
                index - axis_count - button_count + 1
            )



class JoystickInputDialog(gremlin.ui.ui_common.QRememberDialog):
#class JoystickInputDialog(QtWidgets.QDialog):
    ''' handles the filtering of inputs '''

    def __init__(self, device_guid, callback = None, parent = None):
        '''
        :param device_guid: the id of the device being filtered
        :param callback: close handler (optional)
        :param parent: parent widget, optional
        '''

        super().__init__(self.__class__.__name__, parent = parent)
        #super().__init__(parent=parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle("Input Filter Configuration")
        self.setModal(True)



        self.input_widgets = {} # holds a reference to the input widget


        device = gremlin.joystick_handling.getDevice(device_guid)
        self.device = device
        self.device_guid = device.device_guid

        profile = gremlin.shared_state.current_profile

        self._build_input_filter() # get the inputs for the current device

        self.stats = gremlin.base_profile.JoystickInputStats(device_guid, self.input_filter)

        # device properties
        self.stats_widget = gremlin.ui.ui_common.QJoystickInputWidget(device_guid)
        mapped_count_widget = QtWidgets.QLabel("")

        widgets = [
            "Input filter for:",
            device.name,
        ]

        header_widget = gremlin.ui.ui_common.getHContainer(widgets,widget_only=True)

        self.main_layout.addWidget(header_widget)
        container = gremlin.ui.ui_common.getHContainer([self.stats_widget, mapped_count_widget],widget_only=True)
        stats_container = gremlin.ui.ui_common.getHContainer(container, widget_only=True)
        self.main_layout.addWidget(stats_container)




        css = gremlin.ui.ui_common.Color.cssButtonState()

        data = []
        if device.axis_count:
            input_type = InputType.JoystickAxis
            for index in range(device.axis_count):
                linear_id = index + 1
                input_id = device.axis_sequence_to_input_id(index)
                #syslog.info(f"{device.name} axis {index} linear index: {linear_id} -> input {input_id}")
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
        for device_guid, input_type, input_id, name, linear_id in data:
            device = gremlin.joystick_handling.getDevice(device_guid)
            is_filtered = self._is_filtered(input_type, input_id)
            is_used = profile.isInputMapped(device.device_guid, input_type, input_id)
            if is_used:
                mapped_count += 1
            input_count += 1
            if linear_id == input_id:
                tooltip= f"{InputType.to_name(input_type)} {input_id}" if input_type != InputType.JoystickAxis else device.get_axis_name(input_id)
            else:
                tooltip= f"{InputType.to_name(input_type)} {input_id}/L{linear_id}" if input_type != InputType.JoystickAxis else device.get_axis_name(input_id)

            btn = gremlin.ui.ui_common.QUsedPushButton(
                str(input_id) if input_type != InputType.JoystickAxis else device.get_axis_name(input_id, short_name=True),
                used = is_used,
                callback=self._handle_toggle,
                data =(input_type, input_id),
                checkable = True,
                checked = not is_filtered,
                tooltip = tooltip
                )
            btn.setStyleSheet(css)

            flow_layouts[input_type].addWidget(btn)


            if not input_type in self.input_widgets:
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


        widget = gremlin.ui.ui_common.QDataPushButton("Default", callbackEx = self._handle_filter,  data = "default", tooltip = "Automatic default.\nUse Ctrl-Click to apply to all devices.")
        widgets.append(widget)

        # show mapped button always
        current_mode = gremlin.shared_state.edit_mode
        widget = gremlin.ui.ui_common.QDataPushButton(f"Mapped ({current_mode})", callbackEx = self._handle_filter, data = "mapped", tooltip=f"Include mapped inputs in mode [{current_mode}] only.\nUse Ctrl-Click to apply to all devices.")
        widgets.append(widget)

        # show mapped button always
        widget = gremlin.ui.ui_common.QDataPushButton("Mapped (all)", callbackEx = self._handle_filter, data = "mapped_all", tooltip="Include mapped inputs only for all profile modes.\nUse Ctrl-Click to apply to all devices.")
        widgets.append(widget)



        if device.axis_count:
            widget = gremlin.ui.ui_common.QDataPushButton("Hide Axis", callbackEx = self._handle_filter, data = "hide_axis", tooltip = "Remove all axes")
            widgets.append(widget)
            widget = gremlin.ui.ui_common.QDataPushButton("Show Axis", callbackEx = self._handle_filter, data = "show_axis", tooltip = "Show all axes")
            widgets.append(widget)

        if device.button_count:
            widget = gremlin.ui.ui_common.QDataPushButton("Hide Buttons", callbackEx = self._handle_filter, data = "hide_buttons",tooltip="Remove all buttons")
            widgets.append(widget)
            widget = gremlin.ui.ui_common.QDataPushButton("Show Buttons", callbackEx = self._handle_filter, data = "show_buttons",tooltip="Show all buttons")
            widgets.append(widget)

        if device.hat_count:
            widget = gremlin.ui.ui_common.QDataPushButton("Hide Hats", callbackEx = self._handle_filter, data = "hide_hats", tooltip = "Remove all hats")
            widgets.append(widget)
            widget = gremlin.ui.ui_common.QDataPushButton("Show Hats", callbackEx = self._handle_filter, data = "show_hats", tooltip = "Show all hats")
            widgets.append(widget)


        widget = gremlin.ui.ui_common.QDataPushButton("Hide All", callbackEx = self._handle_filter,  data = "hide_all", tooltip = "Hide all inputs.\nUse Ctrl-Click to apply to all devices.")
        widgets.append(widget)
        widget = gremlin.ui.ui_common.QDataPushButton("Show All", callbackEx = self._handle_filter, data = "show_all", tooltip = "Show all inputs")
        widgets.append(widget)
        widget = gremlin.ui.ui_common.QDataPushButton("Revert", callbackEx = self._handle_filter, data = "revert", tooltip = "Revert to current")
        widgets.append(widget)

        widget = gremlin.ui.ui_common.getFlowContainer(widgets, widget_only=True)
        self.main_layout.addWidget(widget)

        msg = """Toggle visible inputs by clicking on them, or press one of the shortcut actions. Control-click on <b>Default</b>, <b>Mapped</b> and <b>Hide All</b> shortcuts to apply the filter to all devices.
Shift-click makes the filter additive (existing visible inputs will not be removed).
Mapped inputs are shown with a green dot.
Inputs will highlight when the associated axis, button or hat is triggered to help with identification.
 If an input is hidden, it can be made visible again in this dialog.  Hidden inputs do not delete any mappings.
"""
        info_widget = gremlin.ui.ui_common.QInfoBox(msg, hide_key = self.__class__.__name__)

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
            self.cancel_widget

        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget)

        if callback:
            self.accepted.connect(callback)

        # hook inputs so buttons can highlight
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_handler)

        self._update_ui()

    def _update_ui(self):
        ''' updates widgets '''
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
        ''' builds the input list from the profile settings '''
        profile = gremlin.shared_state.current_profile
        device = self.device
        device_guid = device.device_guid
        self.input_filter = {}
        self.input_filter[device_guid] = {}

        if device.axis_count:
            self.input_filter[device.device_guid][InputType.JoystickAxis] = {}
            for index in range(device.axis_count):
                input_id = device.axis_sequence_to_input_id(index)
                self.input_filter[device.device_guid][InputType.JoystickAxis][input_id] = profile.settings.getFiltered(device_guid, InputType.JoystickAxis, input_id)
        if device.button_count:
            self.input_filter[device.device_guid][InputType.JoystickButton] = {}
            for index in range(device.button_count):
                input_id = index + 1
                self.input_filter[device.device_guid][InputType.JoystickButton][input_id] = profile.settings.getFiltered(device_guid, InputType.JoystickButton, input_id)
        if device.hat_count:
            self.input_filter[device.device_guid][InputType.JoystickHat] = {}
            for index in range(device.button_count):
                input_id = index + 1
                self.input_filter[device.device_guid][InputType.JoystickHat][input_id] = profile.settings.getFiltered(device_guid, InputType.JoystickHat, input_id)

        self.stats = gremlin.base_profile.JoystickInputStats(device_guid, self.input_filter)

    def closeEvent(self, event):
        self.input_widgets.clear() # remove all widget references
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._joystick_event_handler)
        gremlin.util.clear_layout(self.main_layout) # free up QT resources
        return super().closeEvent(event)

    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
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
                    is_pressed = value != (0,0)
                    btn.setHighlight(is_pressed)

    def dump_filter(self, p_device_guid = None):
        syslog.info("=" * 30)
        syslog.info(f"dialog input filter dump")
        visible_count = 0

        for device_guid, input_type, input_id, _, _ in self.input_map:
            if p_device_guid and p_device_guid != device_guid:
                continue
            filtered = self._is_filtered(input_type, input_id)
            if not filtered:
                # syslog.info(f"\t{input_type.name} {input_id} visible")
                visible_count+=1

        syslog.info(f"\tVisible count: {visible_count}")



    @QtCore.Slot()
    def _handle_filter(self, widget, is_control : bool, is_shift : bool, is_alt : bool, is_right : bool):
        mode = widget.data
        profile = gremlin.shared_state.current_profile
        device = self.device
        device_guid = self.device_guid
        verbose = gremlin.config.Configuration().verbose_mode_filter


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
                    gremlin.ui.ui_common.MessageBox(prompt="Default filter applied to all joystick devices", is_warning = False)

                return

            case "revert":
                # revert to current
                self._build_input_filter()


        prompt = None




        applied_all_filter = []
        for device_guid, input_type, input_id, _, _  in self.input_map:
            filtered = False
            match mode:
                case "mapped":
                    # filter to mapped devices only
                    current_mode = gremlin.shared_state.edit_mode

                    if is_control and not mode in applied_all_filter:
                        profile.settings.setAllFiltered(mode)
                        applied_all_filter.append(mode)
                        # if not prompt:
                        #     prompt="Mapped filter applied to all joystick devices"


                    filtered = not profile.isInputMapped(device_guid, input_type, input_id, current_mode)

                case "mapped_all":
                    if is_control:
                        profile.settings.setAllFiltered(mode)
                        applied_all_filter.append(mode)
                    # if not prompt:
                    #     prompt="Mapped filter applied to all joystick devices"

                    filtered = not profile.isInputMapped(device_guid, input_type, input_id)


                case "show_all":
                    # filter all inputs
                    filtered = False # remove all filters
                case "hide_axis":
                    # hide axes
                    if input_type != InputType.JoystickAxis:
                        continue
                    filtered = True
                case "show_axis":
                    # show axes
                    if input_type != InputType.JoystickAxis:
                        continue
                    filtered = False

                case "hide_buttons":
                    # hide buttons
                    if input_type != InputType.JoystickButton:
                        continue
                    filtered = True
                case "show_buttons":
                    # show buttons
                    if input_type != InputType.JoystickButton:
                        continue
                    filtered = False

                case "hide_hats":
                    # hide hats
                    if input_type != InputType.JoystickHat:
                        continue
                    filtered = True
                case "hide_hats":
                    # show hats
                    if input_type != InputType.JoystickHat:
                        continue
                    filtered = False

                case "hide_all":
                    # hide all inputs
                    filtered = True
                    if is_control and not mode in applied_all_filter:
                        profile.settings.setAllFiltered(mode)
                        applied_all_filter.append(mode)
                        if not prompt:
                            prompt = "Hide All filter applied to all joystick devices"



                case "revert":
                    # revert to original
                    filtered = self._is_filtered(input_type, input_id)

                case _:
                    continue

            #if verbose: syslog.info(f"{input_type.name} {input_id} {filtered}")
            btn : gremlin.ui.ui_common.QDataPushButton = self.input_widgets[input_type][input_id]
            selected = not filtered
            if not selected and is_shift and not btn.isChecked():
                # add to the selection
                btn.setChecked(True)
                self._set_filtered(input_type, input_id, filtered)
            else:
                btn.setChecked(selected) # turn on or off
                self._set_filtered(input_type, input_id, filtered)

        self.updateGroups()

        if prompt:
            gremlin.ui.ui_common.MessageBox(prompt=prompt, is_warning = False)

    def updateGroups(self):
        device = self.device
        # group headers
        if device.axis_count:
            self.group_widgets[InputType.JoystickAxis].setTitle(f"Axis ({device.axis_count} inputs, {self.stats.visible_axis_count} visible)")
        if device.button_count:
            self.group_widgets[InputType.JoystickButton].setTitle(f"Button ({device.button_count} inputs, {self.stats.visible_button_count} visible)")
        if device.hat_count:
            self.group_widgets[InputType.JoystickHat].setTitle(f"Hat ({device.hat_count} inputs, {self.stats.visible_hat_count} visible)")



    def _set_default_filter_list(self, device : dinput.DeviceSummary, input_type : InputType, max_count : int, add_only = False):
        ''' sets a default list of filtered inputs based on given parameters '''

        device_guid = device.device_guid
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
        map_data = [index + 1 for index in range(device_count)] # all possible inputs
        profile = gremlin.shared_state.current_profile

        for index in range(device_count):
            input_id = index + 1
            mapped = profile.isInputMapped(self.device_guid, input_type, input_id)
            if mapped:
                self._set_filtered(input_type, input_id, False, emit=False)
                btn = self.input_widgets[input_type][input_id]
                with QtCore.QSignalBlocker(btn):
                    btn.setChecked(False)
                visible_list.append(input_id)
                map_data.remove(input_id)

        if len(visible_list) < max_count:
            # take the first n inputs
            count = max_count -len(visible_list)
            add_list = map_data[:count]
            if add_list:
                visible_list.extend(add_list)

        # remove visible list from filtered list
        if map_data:
            map_data = [i for i in map_data if not i in visible_list]


        for index in range(device_count):

            if input_type == InputType.JoystickAxis:
                # correct for skipped axes
                input_id = device.getAxisInputId(index)
            else:
                input_id = index + 1
            filtered = input_id in map_data
            btn = self.input_widgets[input_type][input_id]

            if filtered and add_only and btn.isChecked():
                # item should be filtered = only apply if not cummulative
                continue

            self._set_filtered(input_type, input_id, filtered, emit= False)

            with QtCore.QSignalBlocker(btn):
                btn.setChecked(not filtered)

        # update stats
        self.stats.updateFilters(self.input_filter)
        self.stats_widget.setStats(self.stats)



    @QtCore.Slot()
    def _handle_toggle(self, btn):
        ''' handles a filter change '''
        data = btn.data
        input_type, input_id = data

        visible = btn.isChecked()
        # syslog.info(f"checked: {visible} input id: {input_id}")
        is_filtered = not visible
        self._set_filtered(input_type, input_id, is_filtered, emit = True)


    def _set_filtered(self, input_type : InputType, input_id : int, value : bool, emit = False):
        ''' sets the filtered state internal to the dialog '''
        verbose = gremlin.config.Configuration().verbose_mode_filter

        device_guid = self.device.device_guid
        if not device_guid in self.input_filter:
            self.input_filter[device_guid] = {}
        if not input_type in self.input_filter[device_guid]:
            self.input_filter[device_guid][input_type] = {}
        if verbose: syslog.info(f"Toggle {input_type.name} {input_id} {value}")
        self.input_filter[device_guid][input_type][input_id] = value
        if verbose and input_type == InputType.JoystickAxis:
            syslog.info(f"set filter: {self.device.name} axis: {input_id} filtered: {value}")
        if emit:
            self.stats.updateFilters(self.input_filter)
            self.stats_widget.setStats(self.stats)
            self.updateGroups()


            el = gremlin.event_handler.EventListener()
            el.input_filtered_change.emit(device_guid) # tell the widget the input list has changed




    def _is_filtered(self, input_type : InputType, input_id : int) -> bool:
        ''' checks filtered state internal to the dialog '''
        device_guid = self.device.device_guid
        if not device_guid in self.input_filter:
            return True
        if not input_type in self.input_filter[device_guid]:
            return True
        if not input_id in self.input_filter[device_guid][input_type]:
            return True
        return self.input_filter[device_guid][input_type][input_id]


    @QtCore.Slot()
    def _ok_button_cb(self):
        # update the profile map
        # self.dump_filter(self.device_guid)
        profile = gremlin.shared_state.current_profile
        device_guid = self.device.device_guid
        for input_type in self.input_filter[device_guid]:
            for input_id in self.input_filter[device_guid][input_type]:
                profile.settings.setFiltered(device_guid, input_type, input_id,self.input_filter[device_guid][input_type][input_id])

        self.accept()

    @QtCore.Slot()
    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()



    @QtCore.Slot()
    def _handle_set_default_for_device(self):
        profile = gremlin.shared_state.current_profile
        device_guid = self.device.device_guid
        for input_type in self.input_filter[device_guid]:
            for input_id in self.input_filter[device_guid][input_type]:
                profile.settings.setDefaultFiltered(device_guid, input_type, input_id,self.input_filter[device_guid][input_type][input_id])

       # save the profile
        result = profile.settings.saveFilterDefaults()
        if result:
            gremlin.ui.ui_common.MessageBoxInfo(prompt = f"Default filter saved.\nDevice [{self.device.name}].", parent = self)
        else:
            gremlin.ui.ui_common.MessageBoxWarning(prompt = f"Error saving defaults.\nCheck the log file for details.\nDevice [{self.device.name}].", parent = self)

        self._update_ui()

    @QtCore.Slot()
    def _handle_delete_default_for_device(self):
        gremlin.ui.ui_common.MessageBoxYesNo(prompt = f"Delete defaults for device [{self.device.name}]?", callback = self._handle_delete_confirm, parent = self)


    def _handle_delete_confirm(self, result):
        if result == QtWidgets.QMessageBox.StandardButton.Yes:
            profile = gremlin.shared_state.current_profile
            device_guid = self.device.device_guid
            result = profile.settings.clearDefaultsFiltered(device_guid)
            if not result:
                gremlin.ui.ui_common.MessageBoxWarning(prompt = f"Error deleting defaults.\nCheck the log file for details.\nDevice [{self.device.name}].", parent = self)
            self._update_ui()


