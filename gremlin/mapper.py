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
import threading


import dinput

import gremlin.base_classes
import gremlin.base_profile
import gremlin.event_handler
import gremlin.shared_state
import vjoy.vjoy

from . import common, error, util
from vjoy import vjoy
from dinput import DeviceSummary
from gremlin.input_types import InputType
from gremlin.types import DeviceType
from gremlin.types import TabDeviceType
import gremlin.config
from gremlin.ui import ui_common
from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.util
import gremlin.joystick_handling
import gremlin.ui.ui_common
import dinput
import enum
import vjoy


class MapperMode(enum.IntEnum):
    Stop = 1
    RoundRobin = 2
    Unused = 3

class Mapper():
    ''' mapping helper class'''


    class MapperDialog(QtWidgets.QDialog):
        ''' dialog for mapping options '''


        def __init__(self, device_info : dinput.DeviceSummary, parent=None):

            super().__init__(parent)

            # make modal
            self.setWindowModality(QtCore.Qt.ApplicationModal)
            syslog = logging.getLogger("system")

            self.setMinimumWidth(400)

            self.main_layout = QtWidgets.QVBoxLayout(self)

            self.button_mapper = "Vjoy Remap"

            devices = sorted(gremlin.joystick_handling.vjoy_devices(),key=lambda x: x.vjoy_id)
            if not devices:
                # no vjoy devices to map
                ui_common.MessageBox(prompt="No VJOY devices found to map to")
                self.close()
            

            # info
            self.container_info_widget = QtWidgets.QWidget()
            self.container_info_widget.setContentsMargins(0,0,0,0)
            self.container_info_layout = QtWidgets.QVBoxLayout(self.container_info_widget)
            self.container_info_layout.setContentsMargins(0,0,0,0)

            self.device_widget = QtWidgets.QWidget()
            self.device_layout = QtWidgets.QFormLayout(self.device_widget)

            self.mode : MapperMode = gremlin.config.Configuration().mapping_rollover_mode

            self.device_layout.addRow("Source:", self.getStrWidget(device_info.name))
            self.device_layout.addRow("Profile Mode:", self.getStrWidget(gremlin.shared_state.edit_mode))
            self.device_layout.addRow("Axis count:", self.getIntWidget(device_info.axis_count))
            self.device_layout.addRow("Button count:", self.getIntWidget(device_info.button_count))
            self.device_layout.addRow("Hat count:", self.getIntWidget(device_info.hat_count))

            self.container_info_layout.addWidget(QtWidgets.QLabel("<b>1:1 Mapping Options</b>"))
            self.container_info_layout.addWidget(self.device_widget)

        

            # import options
            self.container_options_widget = QtWidgets.QWidget()
            self.container_options_widget.setContentsMargins(0,0,0,0)
            self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
            self.container_options_layout.setContentsMargins(0,0,0,0)

            self.container_rollover_widget = QtWidgets.QWidget()
            self.container_rollover_widget.setContentsMargins(0,0,0,0)
            self.container_rollover_layout = QtWidgets.QHBoxLayout(self.container_rollover_widget)
            self.container_rollover_layout.setContentsMargins(0,0,0,0)


            self.container_button_widget = QtWidgets.QWidget()
            self.container_button_widget.setContentsMargins(0,0,0,0)
            self.container_button_layout = QtWidgets.QHBoxLayout(self.container_button_widget)
            self.container_button_layout.setContentsMargins(0,0,0,0)
            

            self.lbl_vjoy_device_selector = QtWidgets.QLabel("Target VJoy Device:")
            self.cb_vjoy_device_selector = gremlin.ui.ui_common.NoWheelComboBox()

            
            self.container_selector_widget = QtWidgets.QWidget()
            self.container_selector_widget.setContentsMargins(0,0,0,0)
            self.container_selector_layout = QtWidgets.QHBoxLayout(self.container_selector_widget)
            self.container_selector_layout.setContentsMargins(0,0,0,0)
            self.container_selector_layout.addWidget(self.lbl_vjoy_device_selector)
            self.container_selector_layout.addWidget(self.cb_vjoy_device_selector)
            self.container_selector_layout.addStretch()

            self.vjoy_map = {}

            config = gremlin.config.Configuration()



            
            self._vjoy_id = config.mapping_vjoy_id

            selected_index = None
            index = 0
            for dev in devices:
                self.cb_vjoy_device_selector.addItem(dev.name, dev.vjoy_id)
                self.vjoy_map[dev.vjoy_id] = dev
                if dev.vjoy_id == self.vjoy_id:
                    selected_index = index
                index+=1

            if selected_index is not None:
                self.cb_vjoy_device_selector.setCurrentIndex(selected_index)

            if not self.vjoy_id in self.vjoy_map:
                self.vjoy_id = self.cb_vjoy_device_selector.itemData(0)
                

            self.cb_vjoy_device_selector.currentIndexChanged.connect(self._select_vjoy)


            self.mapper_vjoy_remap_widget = QtWidgets.QRadioButton("Vjoy Remap")
            self.mapper_vjoy_remap_widget.setChecked(True)
            self.mapper_remap_widget = QtWidgets.QRadioButton("Legacy Remap")

            self.mapper_vjoy_remap_widget.clicked.connect(self._select_vjoy_remap)
            self.mapper_remap_widget.clicked.connect(self._select_remap)


            self.container_options_layout.addWidget(QtWidgets.QLabel("Target Vjoy Mapper:"))
            self.container_options_layout.addWidget(self.mapper_vjoy_remap_widget)
            self.container_options_layout.addWidget(self.mapper_remap_widget)
            self.container_options_layout.addStretch()


            self.rollover_stop_widget = QtWidgets.QRadioButton("Stop")
            self.rollover_stop_widget.setToolTip("In this mode, the assignments will stop if the target VJOY device has insufficient axis, button or hat counts to do the mapping")
            self.rollover_roundrobin_widget = QtWidgets.QRadioButton("Round-robin")
            self.rollover_roundrobin_widget.setToolTip("In this mode, the assignments will restart at 1 if the target VJOY device has insufficient axis, button or hat counts to do the mapping")
            self.rollover_unused_widget = QtWidgets.QRadioButton("Unused")
            self.rollover_unused_widget.setToolTip("In this mode, the assignment uses the first unused VJOY output and stops if it runs out of available mappings.")


            self.container_rollover_layout.addWidget(QtWidgets.QLabel("Mapping Rollover behavior:"))
            self.container_rollover_layout.addWidget(self.rollover_unused_widget)
            self.container_rollover_layout.addWidget(self.rollover_stop_widget)
            self.container_rollover_layout.addWidget(self.rollover_roundrobin_widget)
            self.container_rollover_layout.addStretch()


            match self.mode:
                case MapperMode.RoundRobin:
                    self.rollover_roundrobin_widget.setChecked(True)
                case MapperMode.Stop:
                    self.rollover_stop_widget.setChecked(True)
                case _:
                    self.rollover_unused_widget.setChecked(True)

            self.rollover_roundrobin_widget.clicked.connect(self._select_roundrobin)
            self.rollover_stop_widget.clicked.connect(self._select_stop)
            self.rollover_unused_widget.clicked.connect(self._select_unused)


            self.execute_button = QtWidgets.QPushButton("Map 1:1")
            self.execute_button.clicked.connect(self._execute_mapping)
            self.cancel_button = QtWidgets.QPushButton("Cancel")
            self.cancel_button.clicked.connect(self.close)

            self.container_button_layout.addStretch()
            self.container_button_layout.addWidget(self.execute_button)
            self.container_button_layout.addWidget(self.cancel_button)


            self.main_layout.addWidget(self.container_info_widget)
            self.main_layout.addWidget(self.container_selector_widget)
            self.main_layout.addWidget(self.container_options_widget)
            self.main_layout.addWidget(self.container_rollover_widget)
            self.main_layout.addStretch()
            self.main_layout.addWidget(self.container_button_widget)

        def getIntWidget(self, value : int) -> ui_common.QIntLineEdit:
            widget = ui_common.QIntLineEdit()
            widget.setReadOnly(True)
            widget.setValue(value)
            return widget
        
        def getStrWidget(self, value : int) -> ui_common.QDataLineEdit:
            widget = ui_common.QDataLineEdit()
            widget.setReadOnly(True)
            widget.setText(value)
            return widget            


        @property
        def vjoy_id(self) -> int:
            return self._vjoy_id
        @vjoy_id.setter
        def vjoy_id(self, value: int):
            self._vjoy_id = value
            gremlin.config.Configuration().mapping_vjoy_id = value
            
        @QtCore.Slot(bool)
        def _select_vjoy_remap(self, checked):
            if checked:
                self.button_mapper = "Vjoy Remap"

        @QtCore.Slot(bool)
        def _select_remap(self, checked):
            if checked:
                self.button_mapper = "Remap"

        @QtCore.Slot()
        def _select_vjoy(self):
            self.vjoy_id = self.cb_vjoy_device_selector.currentData()
            


        @QtCore.Slot(bool)
        def _select_roundrobin(self, checked):
            self.mode = MapperMode.RoundRobin
            gremlin.config.Configuration().mapping_rollover_mode = self.mode


        @QtCore.Slot(bool)
        def _select_stop(self, checked):
            self.mode = MapperMode.Stop
            gremlin.config.Configuration().mapping_rollover_mode = self.mode

        @QtCore.Slot(bool)
        def _select_unused(self, checked):
            self.mode = MapperMode.Unused
            gremlin.config.Configuration().mapping_rollover_mode = self.mode                        

        @QtCore.Slot()
        def _execute_mapping(self):
            ''' executes the mapping '''
            self.create_1to1_mapping(self.vjoy_id, self.button_mapper, self.mode)
            self.close()





        def create_1to1_mapping(self, vjoy_id : int = 1, vjoy_mapper : str = "Vjoy Remap", rollover : MapperMode = MapperMode.Unused):
            """Creates a 1 to 1 mapping of the given device to the first
            vJoy device.
            """
            # Don't attempt to create the mapping for the "Getting Started"
            # widget

            gremlin.util.pushCursor()
            try:
                syslog = logging.getLogger("system")
                tab_device_type : TabDeviceType
                gremlin_ui = gremlin.shared_state.ui
                ui = gremlin_ui.ui
                tab_device_type, _ = ui.devices.currentWidget().data
                if not tab_device_type in (TabDeviceType.Joystick, TabDeviceType.VjoyInput):
                    gremlin.ui.ui_common.MessageBox("Information","1:1 mapping is only available on input joysticks")
                    return

                device_profile = ui.devices.currentWidget().device_profile
                # Don't create mappings for non joystick devices
                if device_profile.type != DeviceType.Joystick:
                    return

                container_plugins = gremlin.plugin_manager.ContainerPlugins()
                action_plugins = gremlin.plugin_manager.ActionPlugins()
                current_mode = gremlin.shared_state.current_mode
                # mode = device_profile.modes[current_mode]
                input_types = [
                    InputType.JoystickAxis,
                    InputType.JoystickButton,
                    InputType.JoystickHat
                ]
                type_name = {
                    InputType.JoystickAxis: "axis",
                    InputType.JoystickButton: "button",
                    InputType.JoystickHat: "hat",
                }
                #current_profile = device_profile.parent

                current_profile = gremlin.shared_state.current_profile
                tab_guid = gremlin.util.parse_guid(gremlin_ui._active_tab_guid())
                device : gremlin.base_profile.Device = current_profile.devices[tab_guid]

                tab_map = gremlin_ui._get_tab_map()
                if device.type != DeviceType.Joystick:
                    ''' selected tab is not a joystick - pick the first joystick tab as ordered by the user '''
                    
                    tab_ids = [device_id for device_id, _, tab_type, _ in tab_map.values() if tab_type == TabDeviceType.Joystick]

                    if not tab_ids:
                        syslog.warning("No joystick available to map to")
                        mb =ui_common.MessageBox("Unable to create mapping, no suitable input hardware found.")
                        mb.exec()
                        return
                    
                    tab_guid = gremlin.util.parse_guid(tab_ids[0])
                    device = current_profile.devices[tab_guid]

                mode = device.modes[current_mode]
                if rollover == MapperMode.Unused:
                    item_list = current_profile.list_unused_vjoy_inputs()
                    for input_type in input_types:
                        for entry in mode.config[input_type].values():
                            input_list  = item_list[vjoy_id][type_name[input_type]]
                            if len(input_list) > 0:
                                vjoy_input_id = input_list.pop(0)
                                container = container_plugins.repository["basic"](entry)
                                action = action_plugins.repository[vjoy_mapper](container)
                                action.input_type = input_type
                                action.vjoy_input_id = vjoy_input_id
                                action.vjoy_device_id = vjoy_id

                                container.add_action(action)
                                entry.containers.append(container)

                elif rollover == MapperMode.Stop:
                    info : dinput.DeviceSummary = gremlin.joystick_handling.vjoy_info_from_vjoy_id(vjoy_id)
                    axis_list = [i for i in range(1, info.axis_count+1)]
                    hat_list = [i for i in range(1, info.hat_count+1)]
                    button_list = [i for i in range(1, info.button_count+1)]

                    for input_type in input_types:
                        for entry in mode.config[input_type].values():
                            if input_type == InputType.JoystickAxis:
                                if not axis_list:
                                    continue
                                input_list = axis_list
                            elif input_type == InputType.JoystickHat:
                                if not hat_list:
                                    continue
                                input_list = hat_list
                            elif input_type == InputType.JoystickButton:
                                if not button_list:
                                    continue
                                input_list = button_list
                            else:
                                continue

                            if len(input_list) > 0:
                                vjoy_input_id = input_list.pop(0)
                                container = container_plugins.repository["basic"](entry)
                                action = action_plugins.repository[vjoy_mapper](container)
                                action.input_type = input_type
                                action.vjoy_input_id = vjoy_input_id
                                action.vjoy_device_id = vjoy_id

                                container.add_action(action)
                                entry.containers.append(container)

                elif rollover == MapperMode.RoundRobin:
                    info = gremlin.joystick_handling.vjoy_info_from_vjoy_id(vjoy_id)
                    axis_list = [i for i in range(1, info.axis_count+1)]
                    hat_list = [i for i in range(1, info.hat_count+1)]
                    button_list = [i for i in range(1, info.button_count+1)]
                    axis_index = 0
                    hat_index = 0
                    button_index = 0

                    for input_type in input_types:
                        for entry in mode.config[input_type].values():
                            if input_type == InputType.JoystickAxis:
                                if not axis_list:
                                    continue
                                vjoy_input_id = axis_list[axis_index]
                                axis_index +=1
                                if axis_index >= len(axis_list):
                                    axis_index = 0
                            elif input_type == InputType.JoystickHat:
                                if not hat_list:
                                    continue
                                vjoy_input_id = hat_list[hat_index]
                                hat_index +=1
                                if hat_index >= len(hat_list):
                                    hat_index = 0

                            elif input_type == InputType.JoystickButton:
                                if not button_list:
                                    continue
                                vjoy_input_id = button_list[button_index]
                                button_index +=1
                                if button_index >= len(button_list):
                                    button_index = 0
                            else:
                                continue

                            container = container_plugins.repository["basic"](entry)
                            action = action_plugins.repository[vjoy_mapper](container)
                            action.input_type = input_type
                            action.vjoy_input_id = vjoy_input_id
                            action.vjoy_device_id = vjoy_id

                            container.add_action(action)
                            entry.containers.append(container)

                            

                            

                # refresh the input tabs

                devices : QtWidgets.QTabWidget = ui.devices
                tab_index = gremlin_ui._active_tab_index()
                tab_widget =  devices.widget(tab_index)
                tab_widget.refresh()

                # update the selection
                eh = gremlin.event_handler.EventListener()
                device_guid, input_type, input_id = gremlin.config.Configuration().get_last_input()
                if input_type and input_id:
                    eh = gremlin.event_handler.EventListener()
                    eh.select_input.emit(device_guid, input_type, input_id, True)
            finally:
                gremlin.util.popCursor()

            
    def create_1to1_mapping(self):           
        ''' shows the dialog '''
        #input_item = gremlin.shared_state.ui._active_input_item()
        device_guid = gremlin.shared_state.ui._active_tab_guid()
        device_info = gremlin.joystick_handling.device_info_from_guid(device_guid)
        if device_info is not None:
            dialog = Mapper.MapperDialog(device_info)
            gremlin.util.centerDialog(dialog, width = dialog.width(), height=dialog.height())
            dialog.exec()