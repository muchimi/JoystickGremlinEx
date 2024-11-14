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


import logging
import threading


import dinput

import gremlin.base_classes
import gremlin.base_profile
import gremlin.event_handler
import gremlin.shared_state

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


class Mapper():
    ''' mapping helper class'''

    class MapperDialog(QtWidgets.QDialog):
        ''' dialog for mapping options '''


        def __init__(self, profile_path, parent=None):

            super().__init__(parent)

            # make modal
            self.setWindowModality(QtCore.Qt.ApplicationModal)
            syslog = logging.getLogger("system")

            self.setMinimumWidth(600)

            self.main_layout = QtWidgets.QVBoxLayout(self)

            # import options
            self.container_options_widget = QtWidgets.QWidget()
            self.container_options_widget.setContentsMargins(0,0,0,0)
            self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
            self.container_options_layout.setContentsMargins(0,0,0,0)


            self.container_mode_widget = QtWidgets.QWidget()
            self.container_mode_widget.setContentsMargins(0,0,0,0)
            self.container_mode_layout = QtWidgets.QHBoxLayout(self.container_mode_widget)
            self.container_mode_layout.setContentsMargins(0,0,0,0)

            current_profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
            modes = current_profile.get_modes()

            




    def create_1to1_mapping(self):
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
            item_list = current_profile.list_unused_vjoy_inputs()
            for input_type in input_types:
                for entry in mode.config[input_type].values():
                    input_list  = item_list[1][type_name[input_type]]
                    if len(input_list) > 0:
                        vjoy_input_id = input_list.pop(0)
                        

                        container = container_plugins.repository["basic"](entry)
                        action = action_plugins.repository["Vjoy Remap"](container)
                        action.input_type = input_type
                        action.vjoy_input_id = vjoy_input_id
                        action.vjoy_device_id = 1 # first vjoy
                    

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

        
