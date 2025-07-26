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


import logging

from PySide6 import QtWidgets, QtCore
import lxml.etree
from lxml import etree
import os

import gremlin
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


syslog = logging.getLogger("system")



class JoystickDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):

    """Widget used to display the input joystick device."""

    inputChanged = Signal(str, object, object) # indicates the input selection changed sends (device_guid string, input_type, input_id)

    def __init__(
            self,
            device : DeviceSummary,
            device_profile,
            current_mode,
            object_name = "Joystick",
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

        config = gremlin.config.Configuration()

        # Store parameters
        
        
        self.curve_update_handler = {} # map of curve handlers to the input by index

        self.device = device
        self.device_profile = device_profile
        self.device_profile.ensure_mode_exists(current_mode, self.device)

        #self.widget_tracker = gremlin.ui.ui_common.DeviceWidgetTracker() # caches the  InputConfigurationItem for this item
        self.last_item_data_key = None
        self.last_selected_index = index = 0
        self.device_guid = device.device_guid
        self.device_name = device.name
        self._debug_widget = None
        
        self._last_selected_index = -1 # last selected index in the list
        

        # List of inputs
        self.input_item_list_model = gremlin.ui.input_item.InputItemListModel(
            device_profile,
            current_mode
        )
        self.input_item_list_view = gremlin.ui.input_item.InputItemListView(name=device.name, custom_widget_handler = self._custom_widget_handler)

        # Handle vJoy as input and vJoy as output devices properly
        vjoy_as_input = self.device_profile.parent.settings.vjoy_as_input

        # For vJoy as output only show axes entries, for all others treat them
        # as if they were physical input devices
        if device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
            self.input_item_list_view.limit_input_types([InputType.JoystickAxis])
        

        self.input_item_list_view.item_edit_curve.connect(self._edit_curve_item_cb)
        self.input_item_list_view.item_delete_curve.connect(self._delete_curve_item_cb)

        # load the model
        self.input_item_list_view.setModel(self.input_item_list_model)
        self.input_item_list_view.redraw()
    

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)
        

        # Add modifiable device label
        
        line_edit = gremlin.ui.ui_common.QDataLineEdit()
        line_edit.setText(device_profile.label)
        line_edit.textChanged.connect(self.update_device_label)

        # device properties
        
        icon = gremlin.ui.ui_common.Icons.axisIcon()
        label_axis = gremlin.ui.ui_common.QIconLabel(icon, f"{device.axis_count}")

        icon = gremlin.ui.ui_common.Icons.buttonIcon()
        label_button = gremlin.ui.ui_common.QIconLabel(icon, f"{device.button_count}")

        icon = gremlin.ui.ui_common.Icons.hatIcon()
        label_hat = gremlin.ui.ui_common.QIconLabel(icon, f"{device.hat_count}")

        widget, _ = gremlin.ui.ui_common.getHContainer([label_axis, label_button, label_hat])
        self.addLeftPanelWidget(widget)

        width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())

        grids = []

        widget, _ = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Label:")
        line_edit.setMinimumWidth(width)
        self.addLeftPanelWidget(widget)

        grids.append(widget)

        if config.show_container_id:

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget, _ = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:")
            self.addLeftPanelWidget(widget)
            grids.append(widget)

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget, _ = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:")
            self.addLeftPanelWidget(widget)
            grids.append(widget)

        gremlin.ui.ui_common.synchronize_grids(grids)

        self.addLeftPanelWidget(self.input_item_list_view)
        

        # Add a help text for the purpose of the vJoy tab
        if device is not None and \
                device.is_virtual and \
                not vjoy_as_input.get(device.vjoy_id, False):
            label = QtWidgets.QLabel(
                "This tab allows assigning a response curve to virtual axis. "
                "The purpose of this is to enable split and merge axis to be "
                "customized to a user's needs with regards to dead zone and "
                "response curve."
            )
            label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
            label.setWordWrap(True)
            label.setFrameShape(QtWidgets.QFrame.Box)
            label.setMargin(10)
            self.addLeftPanelWidget(label)


        config = gremlin.config.Configuration()

        if config.debug_ui:
            self._debug_widget = QtWidgets.QLabel("Debug widget")
            self._debug_widget.setMaximumHeight(32)
            self.addRightPanelWidget(self._debug_widget)

        el = gremlin.event_handler.EventListener()
        # update on an edit mode change so we update the display
        el.edit_mode_changed.connect(self._edit_mode_changed_cb)
        # update display on config change
        el.config_changed.connect(self._config_changed_cb)

        self.updating = False
        self.last_event = None

        # update the selection if nothing is selected
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None and selected_index != -1:
            self._select_item_cb(selected_index)

        

        # update all curve icons
        self.update_curve_icons()


    def _cleanup_ui(self):
        ''' called when deleted '''
        super()._cleanup_ui()
        if gremlin.util.isSignalConnected(self.input_item_list_view, "_edit_curve_item_cb"):
            self.input_item_list_view.item_edit_curve.disconnect(self._edit_curve_item_cb)
            self.input_item_list_view.item_delete_curve.disconnect(self._delete_curve_item_cb)
            self.input_item_list_view.item_selected.disconnect(self._select_item_cb)
            self.input_item_list_view.setParent(None)

            el = gremlin.event_handler.EventListener()
            
            el.edit_mode_changed.disconnect(self._edit_mode_changed_cb)
            el.config_changed.disconnect(self._config_changed_cb)

            
            

        
        

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
        update_handler = dialog.curve_update_handler
        self.curve_update_handler[index] = update_handler
        # update the dialog with the current input value
        value = gremlin.joystick_handling.get_axis(data.device_guid, data.input_id)
        update_handler(value)

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        self.curve_update_handler[index] = None
        print ("update curve data")
        data.curve_data.curve_update()

        # update the registered curve state
        eh = gremlin.event_handler.EventListener()
        eh.registerInput(data)

        # renable highlighting
        gremlin.shared_state.pop_suspend_highlighting()

        
        
        self._update_curve_icon(index, data)


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

    @QtCore.Slot(str)
    def _edit_mode_changed_cb(self, mode : str):
        ''' called on edit mode change '''
        if not Shiboken.isValid(self):
            return
        self.set_mode(mode)
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_detailed
        if verbose: syslog.info(f"DeviceWidget: {self.device_name} change mode: [{mode}]")
        self.update_curve_icons()


    def update_curve_icons(self):
        for index, widget in enumerate(self.input_item_list_view.getWidgets()):
            if widget is not None:
                self._update_curve_icon(index, self.input_item_list_view.model.data(index))

    def _update_curve_icon(self, index : int, data):
        
        widget = self.input_item_list_view.getWidgetAt(index)
        if widget is not None:
            widget.update_display()



    def _config_changed_cb(self):
        self.input_item_list_view.redraw()

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
    

    @QtCore.Slot()
    def _select_item_cb(self, index, force_update = False, emit = True):
        """ Handles the loading of mappings for a given input item - handler for select_input event

        :param index the index of the selected item
        """
        from gremlin.ui.input_item import InputItemConfigurationWidget

        try:

            self.setUpdatesEnabled(False)

            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_details
            #verbose = True
            # syslog = logging.getLogger("system")
            widget = None
            current_mode = gremlin.shared_state.edit_mode
            #self.device_profile.ensure_mode_exists(current_mode, self.device)
            #print (f"joystick device input select: current edit mode is {current_mode} ======================================")
            if index == -1:
                index = self.last_selected_index

            if index == -1:
                if self.input_item_list_model.rows() > 0:
                    item_data = self.input_item_list_model.data(0)
                    index = 0
                else:
                    self._blank_input()
                    return
            else:
                item_data = self.input_item_list_model.data(index)
            
            if not item_data:
                syslog.warning(f"JoystickDevice: Device [{device_name}] has no inputs for mode {current_mode} - this is not normal.")

            if verbose:
                device_name = gremlin.joystick_handling.device_name_from_guid(self.device_guid)
                if item_data:
                    syslog.info(f"Selecting input config item for {device_name} input index [{index}] mode: {current_mode}: {item_data.debug_display}")
                else:
                    syslog.info(f"Selecting input config item for {device_name} input index [{index}] mode: {current_mode}: Empty content")

            new_key = None
                
            self.last_item_data_key = new_key

            

            if item_data is not None:
    
                #self.clearRightPanel()
                device_guid = self.device_guid
                input_type = item_data.input_type
                input_id = item_data.input_id

                key = self.getWidgetKey(input_type, input_id)
                widget = self.getRegisteredWidget(key)
                if not widget:
                    
                    # not in cache, create it and add to cache for this device/input combination
                    if verbose: syslog.info(f"create and store in cache content widget for index: {index}  device: {self.device_guid}")
                    widget = InputItemConfigurationWidget(item_data, object_name = f"Joystick [{item_data.display_name}]")
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
                    widget.setItemData(item_data)

                # make the widget visible
                self.selectRegisteredWidget(key)
                #self.input_item_list_view.select_item(index, False)


                if verbose:
                    syslog.info(f"Show widget:  {widget.id} {item_data.debug_display}")
                
                if config.debug_ui:
                    self._debug_widget.setText(f"Contents for : {item_data.debug_display}")


            self.last_selected_index = index
            if emit:
                el = gremlin.event_handler.EventListener()
                el.input_selection_changed.emit(device_guid, input_type, input_id)

        finally:    
            self.setUpdatesEnabled(True)
            #gremlin.util.dumpWidgets(self._right_container_layout)
            self.update()
        

    
    def _description_changed_cb(self, index, text):
        ''' called when the description text of the widget changes to update the description on the input item 
        
        :param: index = the index of the input widget to update with the new text
        
        '''
        item = self.input_item_list_view.itemAt(index)
        item.data.description = text
        item.setDescription(text)

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

        # index = self.last_item_index
        # self.input_item_list_model.mode = mode
        # self.input_item_list_view.redraw()
        # self.input_item_list_view.select_item(index, emit=False)
        # self.input_item_selected_cb(index)

        self.input_item_list_model.mode = mode

        #self.input_item_list_view.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.input_item_list_model.refresh()
            self.input_item_list_view.redraw()        
            self.select_item(self._last_selected_index)





    def redraw(self):
        ''' updates the list widget '''
        self.input_item_list_view.redraw()
        
    def refresh(self, emit = True):
        """Refreshes the current selection, ensuring proper synchronization."""
        self._select_item_cb(self.input_item_list_view.current_index, force_update = True, emit = emit)

        # self.redraw()
        
        # if self.input_item_list_view.current_index is not None:
        #     self._select_item_cb(self.input_item_list_view.current_index, force_update = True)


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



