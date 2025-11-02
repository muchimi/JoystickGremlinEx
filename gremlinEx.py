# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - GremlinEx is (C) EMCS 2025
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

"""
Main UI of JoystickGremlin.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import logging
import os
import gc
import weakref
import sys
import time
import traceback
import threading
from threading import Lock
import webbrowser
import faulthandler
import dinput
import psygnal
from psygnal import Signal
import anytree
from dinput import DeviceSummary
from gremlin.util import InvokeUiMethod, assert_ui_thread
from lxml import etree
import PySide6
from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
from gremlin.types import TabDeviceType
from shiboken6 import Shiboken
import gremlin.tabstate


import gremlin.joystick_handling

''' ALL gremlin modules should be imported here to avoid packaging errors '''


import gremlin.util
import gremlin.config
import gremlin.input_types

import gremlin.event_handler
import gremlin.base_classes


import gremlin.config
import gremlin.joystick_handling

import gremlin.input_devices

import gremlin.hid
import gremlin.shared_state
import gremlin.types
import gremlin.profile_graph
import gremlin.base_profile
import gremlin.ui.keyboard_device
import gremlin.ui.midi_device
import gremlin.ui.osc_device
import gremlin.ui.mode_device
import gremlin.ui.state_device
import gremlin.ui.theme

import gremlin.plugin_manager
import gremlin.process_monitor
import gremlin.execution_graph
import gremlin.gamepad_handling
import gremlin.import_profile
import gremlin.windows_event_hook # reference needed for packaging
import gremlin.macro_handler # reference needed for packaging
import gremlin.ui.octavi_device
import gremlin.ui.virpil_device




# Import QtMultimedia so pyinstaller doesn't miss it




from gremlin.input_types import InputType
from gremlin.types import DeviceType

from gremlin.util import load_icon, load_pixmap, userprofile_path, find_file, waitCursor, popCursor, pushCursor, isCursorActive
import gremlin.shared_state
import gremlin.base_profile
import gremlin.event_handler
import gremlin.config


import gremlin.code_runner

import gremlin.keyboard
import gremlin.process_monitor
import gremlin.code_runner
import gremlin.repeater
import gremlin.base_profile

# imports needed by pyinstaller to be included
import gremlin.control_action


import gremlin.tts

from gremlin.util import log_sys_error, compare_path
import gremlin.util
import graphviz


# Figure out the location of the code / executable and change the working
# directory accordingly
install_path = os.path.normcase(os.path.dirname(os.path.abspath(sys.argv[0])))
os.chdir(install_path)


import gremlin.ui.axis_calibration
import gremlin.ui.ui_common
import gremlin.ui.joystick_device
import gremlin.ui.dialogs
import gremlin.ui.input_viewer
import gremlin.ui.merge_axis
import gremlin.ui.user_plugin_management
import gremlin.ui.profile_creator
import gremlin.ui.profile_settings
import gremlin.version

from PySide6 import QtCore

from gremlin.ui.ui_gremlin import Ui_Gremlin
#from gremlin.input_devices import remote_state


import gremlin.reporting

syslog = logging.getLogger("system")

# the main ui
ui = None





class GremlinUi(gremlin.ui.ui_common.QRememberMainWindow):

    """Main window of the Joystick Gremlin user interface."""

    ui = None

    # input_lock =  threading.Lock() # critical code operations - prevents reentry
    



    def __init__(self, parent=None):
        """Creates a new main ui window.

        :param parent the parent of this window
        """

        gremlin.shared_state.ui = self
        self.initialized = False

        super().__init__("main_window", parent)

        self.ui = Ui_Gremlin()
        self.ui.setupUi(self)
  
        
        
        

        self._profile_load_stack = []
        self._profile_load_temporary_files = []
        self._profile_hash = None # active profile hash to detect changes
        self.locked = False
        self.activate_locked = False
        self._selection_locked = False
        self.joystick_event_lock = Lock() # lock for joystick events
        self.device_change_locked = False
        self._device_change_queue = 0 # count of device updates while the UI is already updating
        self._runtime_mode_map = {} # map of runtime processes to their last runtime mode
        self._process_runtime_map = {} # map of MODE to process associated with a profile - the process executable is the key
        self._active_process_path = None # active mapped process path 
        self._last_toast_message = None
        self._change_input_lock = threading.Lock() # true when changing inputs

        self._last_selected_device_guid = None
        self._last_selected_input_type = None
        self._last_selected_input_id = None

        self._resize_count = 0

        # list of detected devices
        self._active_devices = []
        self._tab_dirty = True # True if tabs should be refreshed
        self._tab_map = None # holds tabdata objects indexed by tab index

        # cache of widget references so they don't get garbage collected by QT

        self.ui.devices.tabChanged.connect(self._tab_selected)
        self.ui.devices.tabMoveCompleted.connect(self._tab_moved_cb)
        self.ui.devices.tabContextMenu.connect(self._tab_context_menu_cb)
        self.ui.devices.currentChanged.connect(self._tab_changed)

        self._last_input_item = None # last selected input item
        self._last_state_device_guid = None
        self._last_state_input_id = None
        self._last_state_data = {} # holds data for axis highlight switching


        gremlin.shared_state.application_version =gremlin.version.APPLICATION_VERSION

        self.config = gremlin.config.Configuration()
        self.config.changed.connect(self._config_filter_changed_cb)

        # last input from last run to restore
        self.restore_input = self.config.get_last_input() 

        

        # prevent saving anything until we have a profile loaded
        el = gremlin.event_handler.EventListener()
        el.push_input_selection()
        el.request_activate.connect(self.activate) # hook activation / deactivation requests
        el.refresh_devices.connect(self._create_tabs) # refresh device list
        el.request_profile_reload.connect(self._reload_profile) # reload the profile from a temporary file
        el.request_reload.connect(self._reload)
        el.device_mapping_changed.connect(self._update_tab)
        el.mapping_changed.connect(self._mapping_changed)
        el.show_container_id_changed.connect(self._show_container_id_visible_changed)
        el.toolbar_changed.connect(self._update_toolbar)

        # highlighing options
        self._icon_on = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color= gremlin.ui.ui_common.Color.activeColor())
        self._icon_off = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color= gremlin.ui.ui_common.Color.inactiveColor())
        self._button_highlighting_enabled = self.config.highlight_input_buttons # true if highlighting on buttons
        self._axis_highlighting_enabled = self.config.highlight_input_axis  # true if highligthing on axes
        self._input_highlighting_enabled = self.config.highlight_enabled  # on/off global

        el.enable_highlight_changed.connect(self._highlight_enable_changed) # fires when highlight mode is toggled

        self._last_highlight_key = None    # last event processed for input highlights
        el.toggle_highlight.connect(self._handle_highlight_state) # input highlighting states
        el.ui_ready.connect(self._ui_ready)
        gremlin.shared_state.aborted = False
        el.request_profile_stop.connect(lambda x: self.abort(x))

        # Process monitor
        self.process_monitor = gremlin.process_monitor.ProcessMonitor()
        self.process_monitor.process_changed.connect(self._process_changed_cb)
        self.current_process_path = None # current process
        self._last_tts_notify_time = None # last autoload process change TTS time
        self._process_change_in_progress = False

        # Default path variable before any runtime changes
        self._base_path = list(sys.path)


        self._init_tab_data()
        self._reset_tab_data()

        self.runner = gremlin.code_runner.CodeRunner()
        self.repeater = gremlin.repeater.Repeater([],self._update_statusbar_repeater)


        self._status_bar_last_runtime_mode = None
        self._status_bar_last_edit_mode = None
        eh = gremlin.event_handler.EventHandler()
        eh.mode_status_update.connect(self._update_mode_status_bar)

        el.runtime_mode_changed.connect(self._runtime_mode_changed)
        el.edit_mode_changed.connect(self._edit_mode_changed)
        el.mode_name_changed.connect(self._mode_name_changed)

        self.tab_guids = []

        self.mode_selector = gremlin.ui.ui_common.ModeWidget()
        self.mode_selector.edit_mode_changed.connect(self._edit_mode_selector_changed)
        self.mode_selector.setRuntimeDisabled(True)

        self.ui.toolBar.addWidget(self.mode_selector)

        # Setup profile storage

        self.profile = gremlin.base_profile.Profile()
        self._profile_auto_activated = False
        # Input selection storage
        self._last_input_timestamp = time.time()
        self._last_input_change_timestamp = time.time()

        self._last_input_event = None
        self._last_input_identifier = None # input id of the last triggered device
        # self._last_device_guid = None # string representation of the last GUID of the last triggered device
        # self._last_input_type = None # last input type (InputType) selected
        # self._last_input_id = None # last input id selected

        self._last_tab_switch = None
        self._input_delay = 0.25 # delay in seconds between joystick inputs for highlighting purposes
        self._joystick_axis_highlight_deviation = 0.5 # deviation needed before registering a highlight on axis change (this is to avoid noisy inputs and prevent the UI from going crazy) 1.0 = half travel
        self._joystick_axis_highlight_map = {} # map of device / axis values
        self._event_process_registry = {}
        self._temp_input_axis_override = False # flag that tracks device swaps on axis
        self._temp_input_axis_only_override = False # flag that tracks device swaps but on axis only (shift + ctrl key)

        # Create all required UI elements
        self._create_system_tray()
        self._setup_icons()
        self._connect_actions()
        self._create_statusbar()
        self._update_status_bar_active(False)

        # hook status bar to events
        el = gremlin.event_handler.EventListener()
        el.broadcast_changed.connect(self._update_status_bar)
        el.keyboard_event.connect(self._kb_event_cb) # for repeaters
        
        el.suspend_keyboard_input.connect(self._kb_suspend_cb)
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)
        
        el.profile_changed.connect(self._profile_changed_cb)
        el.button_state_change.connect(self._button_state_change)
        el.axis_state_change.connect(self._axis_state_change)
        el.input_selection_changed.connect(self._input_changed_handler)
        el.remote_control_changed(self._remote_control_changed)

        
        # hook input selection
        el.select_input.connect(self._select_input_handler)

        # hook config changes
        el.config_changed.connect(self._config_changed_cb)

        # hook changes
        eh = gremlin.event_handler.EventHandler()
        eh.profile_changed.connect(self._profile_changed_cb)


        self._context_menu_tab_index = None

        # Load existing configuration or create a new one otherwise
        
        if not self.config.auto_load_disabled and self.config.last_profile and os.path.isfile(self.config.last_profile):
            # check if this was a profile swap that we load the profile from the current user folder
            current_profile_folder = gremlin.shared_state.data_path.casefold()
            last_profile = self.config.last_profile.lower()
            if not current_profile_folder in last_profile:
                _, base_file = os.path.split(last_profile)
                located_profile = find_file(base_file,current_profile_folder)
                if located_profile:
                    self.config.last_profile = located_profile
            self._do_load_profile(self.config.last_profile)
        else:
            self.new_profile()

        # Setup the recent files menu
        self._create_recent_profiles()

        # Modal windows
        self.modal_windows = {}
        self.modal_windows["input_viewer"] = None

        # Enable reloading for when a user connects / disconnects a
        # device. Sleep for a bit to avert race with devices being added
        # when they already exist.

        el._init_joysticks()
  

        #self.apply_user_settings()
        self._apply_window_settings()

        self._profile_map = gremlin.base_profile.ProfileMap()

        GremlinUi.ui = self

        self.ui.update_toolbar()
        el.config_option_changed.connect(self._config_option_changed)
        el.device_change_event.connect(self._device_change_cb)

        self.initialized = True

    def _update_toolbar(self):
        ''' updates the toolbar when the toolbar changes '''
        self.ui.update_toolbar()

    def registerTemporaryProfileLoadFile(self, xml_file : str):
        ''' registers a temporary file that the profile loader will load '''
        if not xml_file in self._profile_load_temporary_files:
            self._profile_load_temporary_files.append(xml_file)


    def _init_tab_data(self):
        self._widget_device_index_map = {} # map of device widgets keyed by the device GUID
        self._widget_index_device_map = {}

    def _reset_tab_data(self):
        
        self._tab_index_map = {} # map of device_guids indexed by their tab index from the tab header  (index -> device_guid)
        self._tab_device_map = {} # map of tab positions index mapped by device guid for the tab header (device_guid -> index)
        self._tab_name_map = {} # map fo device guid to device name for tabs
        
        # self._current_tab_widget = None # selected content widget for the current device
        self._current_tab_input_id = None # selected input in the current tab
        self._joystick_device_guids = []
        self.tab_guids = []

       
        self._clear_tabs()


    def _clear_tabs(self):
         # remove all tab headers
        if self.ui.devices:
            with QtCore.QSignalBlocker(self.ui.devices):
                while self.ui.devices.count():
                    self.ui.devices.removeTab(0)

    def _get_device(self, device_guid) -> dinput.DeviceSummary:
        ''' gets the device for a given GUID, connected or not '''
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._all_devices_map:
            return self._all_devices_map[device_guid]
        return gremlin.joystick_handling.device_info_from_guid(device_guid)
    
    def _get_device_name(self, device_guid):
        ''' gets the name of a device '''
        device = self._get_device(device_guid)
        if device:
            return device.name
        return None



    def _add_tab(self, device_guid, tab_type, index = None, override_name = None) -> int: 
        ''' adds a tab to the tab header 
        :param device_guid: the device guid of the device to add
        :param index: optiona, if specified, the index to add
        :returns int: the index of the tab added 
        '''
        device_guid = gremlin.util.normalize_guid(device_guid)

        device : dinput.DeviceSummary = self._get_device(device_guid)
        if not device:
            syslog.error(f"Unknown device GUID found in tabs: {device_guid}")
            return
        device_name = device.name

        # ensure the device tab does not already exist
        if device_guid in self._tab_device_map:
            # already present - skip
            syslog.info(f"ADDTAB: skip adding device [{device_name}] [{device_guid}] as this device already exists in the device list.")
            return

        ts = gremlin.tabstate.TabState()

        #has_mapping = self._has_mapping(device_guid)
        widget = self.getRegisteredWidget(device_guid)
        if device_name == "Controller (XBOX 360 For Windows)":
            object_name = f"Game Controller [{device_name}]"
        else:
            object_name = device_name

        if not widget:
            device_profile = self.profile.get_device_modes(
                device.device_guid,
                DeviceType.Joystick,
                device.name,
            )
        
            widget = gremlin.ui.joystick_device.JoystickDeviceTabWidget(
                        device,
                        device_profile,
                        self.current_mode,
                        object_name= object_name
                        )
            widget.data = (TabDeviceType.VjoyInput, device_guid, index)
            
            self.registerWidget(device_guid, widget)
        

                
        

        tab_name = override_name if override_name else device_name
        with QtCore.QSignalBlocker(self.ui.devices):
            if index is None:
                position = self.ui.devices.addTab(tab_name)
            else:
                position = self.ui.devices.insertTab(index, tab_name)

        #  tab data block
        data = ts.addData(device_guid, tab_type, device)
        self.ui.devices.setTabData(position, data)

        self._tab_device_map[device_guid] = position
        self._tab_index_map[position] = device_guid
        self._tab_name_map[device_guid] = tab_name
        
        

        if tab_type == TabDeviceType.Joystick:
            self._joystick_device_guids.append(device_guid)
        
        verbose = gremlin.config.Configuration().verbose_mode_device
        
        if verbose: syslog.info(f"Add tab: {position} {device_name} tab name: {tab_name} {device_guid}  tab data: {self.ui.devices.tabData(position)}  ")

        self._update_tab(device_guid)

        return position
    
    def _has_mapping(self, device_guid) -> bool:
        ''' true if the device has mappings '''
        if isinstance(device_guid, str):
            device_guid = gremlin.util.parse_guid(device_guid)
        profile = gremlin.shared_state.current_profile
        edit_mode = gremlin.shared_state.edit_mode
        devices = profile.devices
        look_for_containers = True
        # special devices
        if device_guid == gremlin.shared_state.state_tab_guid:
            # state
            sd = gremlin.ui.state_device.StateData()
            names = sd.getStateNames()
            return len(names) > 0
        elif device_guid == gremlin.shared_state.settings_tab_guid:
            return True
        elif device_guid == gremlin.shared_state.plugins_tab_guid:
            # plugins
            plugins = gremlin.shared_state.current_profile.plugins
            return len(plugins) > 0
        elif device_guid == gremlin.shared_state.keyboard_tab_guid:
            look_for_containers = False

        if device_guid in devices:
            device_data = devices[device_guid]
            if edit_mode in device_data.modes:
                mode_data = device_data.modes[edit_mode]
                for input_type, input_items in mode_data.config.items():
                    for input_item in input_items.values():
                        if look_for_containers:
                            if input_item.containers:
                                return True
                        else:
                            # input count indicates content
                            return True
        return False

    def _get_tab_map(self):
        ''' gets tab configuration data as a dictionary indexed by tab index holding device id, device name and device widget type


        :returns:  list of (device_guid, device_name, tabdevice_type, tab_index)
        '''
        tab_count = self.ui.devices.count()
        tab_map = {}
        for index in range(tab_count):
            data  =  self.ui.devices.tabData(index)
            device_guid = data.device_guid
            device_name = self._tab_name_map[device_guid]
            
            tab_map[index] = (device_guid, device_name, data.tab_type, index)
        return tab_map
    
    def _get_tab_data_map(self) -> dict:
        ''' returns the map of tab data objects associated with their device GUID '''
        tab_count = self.ui.devices.count()
        tab_map = {}
        for index in range(tab_count):
            data  =  self.ui.devices.tabData(index)
            tab_map[data.device_guid] = data

        return tab_map
    
    def _get_tab_type(self, index):
        ''' gets the tab type for the given tab index '''
        data = self.ui.devices.tabData(index)
        return data.tab_type


    def _reindex_tabs(self):
        ''' rebuilds the tab index '''
        self._tab_index_map.clear()
        self._tab_device_map.clear()
        self._tab_name_map.clear()
        
        verbose = gremlin.config.Configuration().verbose_mode_device
        # syslog = logging.getLogger("system")
        if verbose: syslog.info("UI: tab reindex")
        for index in range(self.ui.devices.count()):
            data = self.ui.devices.tabData(index)
            device_guid = data.device_guid
            device_name = self._get_device_name(device_guid)
            self._tab_index_map[index] = device_guid
            self._tab_device_map[device_guid] = index
            self._tab_name_map[device_guid] = device_name
            
            if verbose: 
                syslog.info(f"\t[{index}] {device_name} {device_guid}")

    def _tabswitch_needed(self, device_guid) -> bool:
        ''' checks to see if the device tab is the current tab or not '''
        
        tab_device_guid = gremlin.shared_state.current_tab_device_guid
        if isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        return tab_device_guid != device_guid
    

    def _inputswitch_needed(self, device_guid, input_id) -> bool:
        ''' checks to see if an input switch is needed '''
        if isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        tab_device_guid = gremlin.shared_state.current_tab_device_guid
        tab_input_id = self._current_tab_input_id
        return tab_device_guid != device_guid or tab_input_id != input_id


    def _button_state_change(self, event):
        ''' button changed - triggered only at design time - look for highlighting triggers - HIGHLIGHT SYSTEM '''

        if gremlin.shared_state.is_highlighting_suspended():
            # highlighting disabled
            return

        el = gremlin.event_handler.EventListener()
        is_shifted = el.get_shifted_state()

        is_tabswitch_enabled = self.config.highlight_autoswitch
        device_guid = event.device_guid
        input_type = event.event_type
        input_id = event.identifier
        is_pressed = event.is_pressed

        if not is_pressed:
            # trigger only on presses
            return
      
        is_button = self.is_button_highlighting or is_shifted
        if not is_button:
            # highlight disabled
            return
        
        tab_switch_needed = self._tabswitch_needed(device_guid)
        input_switch_needed = tab_switch_needed or self._inputswitch_needed(device_guid, input_id)

        if tab_switch_needed and not is_tabswitch_enabled and not input_switch_needed:
            # not setup to auto change tabs (override via shift/control keys)
            return
        
       
        # # see if input needs to change
        # input_switch_needed = tab_switch_needed or self._inputswitch_needed(device_guid, input_id)
        # if not input_switch_needed:
        #     return
        
        # trigger switch
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: syslog.info(f"Button input switch to {device_guid} button {input_id}")
        self._select_input_handler(device_guid, input_type, input_id)



    def _axis_state_change(self, event):
        ''' axis changed - triggered only at design time - HIGHLIGHT SYSTEM'''

        if gremlin.shared_state.is_highlighting_suspended():
            # highlighting disabled
            return
        
        

        el = gremlin.event_handler.EventListener()
        is_control = el.get_control_state()
        if not self.is_axis_highlighting and not is_control:
            # highlight disabled - reset tracking 
            self._last_state_device_guid = None
            self._last_state_input_id = None
            self._last_state_data = {}
            return
        

        device_guid = event.device_guid
        input_type = event.event_type
        input_id = event.identifier
        value = event.value

        if self._last_state_input_id == device_guid and self._last_state_input_id == input_id:
            # same device as last selected, ignore
            return 
        
        # to avoid instant triggers - compare deviation from last value for that specific axis
        # this avoids a small change on a new axis from triggering a change
        if not device_guid in self._last_state_data:
            self._last_state_data[device_guid] = {}
        if not input_id in self._last_state_data[device_guid]:
            self._last_state_data[device_guid][input_id] = None

        if self._last_state_data[device_guid][input_id] is not None:
            last_value = self._last_state_data[device_guid][input_id]
            if abs(last_value - value) <= 0.2:
                return # insufficient deviation to trigger
            
        

        tab_switch_needed = self._tabswitch_needed(device_guid)
        is_tabswitch_enabled = self.config.highlight_autoswitch
        input_switch_needed = tab_switch_needed or self._inputswitch_needed(device_guid, input_id)
        if tab_switch_needed and not is_tabswitch_enabled and not input_switch_needed:
            # not setup to auto change tabs (override via shift/control keys)
            return
        
        # see if input needs to change
        
        if not input_switch_needed:
            return
     
        # trigger - record last value
        self._last_state_data[device_guid][input_id] = value

        # trigger highlight switch
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: syslog.info(f"Axis input switch to {device_guid} axis {input_id}")
        self._select_input_handler(device_guid, input_type, input_id, force_switch=True)

    @QtCore.Slot(int)
    def _tab_changed(self, index):
        #syslog.info(f"tab changed : {index}")
        self._tab_selected(index)

    @QtCore.Slot(int)
    def _tab_selected(self, index):
        ''' called when the device tab selection is changed
        :param: index = the index of the tab that was selected

        '''

        if self.ui.devices.moveInProgress:
            # ignore if the tab is being dragged
            return 
        
        verbose = gremlin.config.Configuration().verbose_mode_ui
        
        if verbose: syslog.info(f"TAB CHANGED: selected : {index}")

        device_guid = self.getDeviceGuidForTabIndex(index)
        gremlin.util.pushCursor()

        if device_guid is not None:
            
            if verbose:
                device_name = self._get_device_name(device_guid)
                syslog.info(f"TAB CHANGED:  new tab [{index}] {self.ui.devices.tabText(index)} - device {device_guid} {device_name}")
            self.last_tab_index = index
            _, restore_input_type, restore_input_id = self.config.get_last_input(device_guid)
            self._select_input(device_guid = device_guid, input_type = restore_input_type, input_id = restore_input_id, force_update =True, force_switch=True, tab_changed = True)

            # verify the data is being populated
            self.ensureTabLoaded()

        gremlin.util.popCursor()

    def add_custom_tools_menu(self, menuTools):
        ''' adds custom tools to the menu '''
        self._actionTabSort = QtGui.QAction("Sort Devices", self, triggered = self._tab_sort_cb)
        self._actionTabSort.setToolTip("Sorts input hardware devices in alphabetical order")

        self._ationTabCopyAssignments = QtGui.QAction("Copy to device...", self, triggered = self._tab_copy_cb)
        self._ationTabCopyAssignments.setToolTip("Copies assignments to specified target device")

        # self._actionTabSubstitute = QtGui.QAction("Device Swap...", self, triggered = self._tab_substitute_cb)
        # self._actionTabSubstitute.setToolTip("Swap one device ID for another device ID")

        self._actionTabClearMap = QtGui.QAction("Clear Mappings", self, triggered = self._tab_clear_map_cb)
        self._actionTabClearMap.setToolTip("Clears all mappings from the current device")
        self._actionTabRemoveDevice  = QtGui.QAction("Remove device", self, triggered = self._tab_remove_device_cb)
        self._actionTabRemoveDevice.setToolTip("Removes the device from the profile (disconnected devices only)")
        #self._actionTabImport = QtGui.QAction("Import Profile...", self, triggered = self._tab_import_cb)
        #self._actionTabImport.setToolTip("Import profile data into the current device")

        menuTools.addSeparator()
        menuTools.addAction(self._actionTabSort)
        menuTools.addAction(self._ationTabCopyAssignments)
        #menuTools.addAction(self._actionTabSubstitute)

        menuTools.addAction(self._actionTabRemoveDevice)
        #menuTools.addAction(self._actionTabImport)
        menuTools.addAction(self._actionTabClearMap)



    def _tab_context_menu_cb(self, tab_index):
        ''' tab context menu '''
        self._context_menu_tab_index = tab_index
        data = self.ui.devices.tabData(tab_index)
        tab_type = data.tab_type
        #device_guid = data.device_guid
        # substitution is only available if the profile has been saved (a new profile matches the current devices by definition)
        is_enabled = tab_type == TabDeviceType.Joystick
        #     and self.profile is not None\
        #     and self.profile.profile_file is not None\
        #     and os.path.isfile(self.profile.profile_file)
        # self._actionTabSubstitute.setEnabled(is_enabled)
        menu = QtWidgets.QMenu(self)
        menu.addAction(self._actionTabSort)
        menu.addAction(self._ationTabCopyAssignments)
        # menu.addAction(self._actionTabSubstitute)
        #menu.addAction(self._actionTabImport)
        menu.addAction(self._actionTabRemoveDevice)
        menu.addAction(self._actionTabClearMap)
        menu.exec_(QtGui.QCursor.pos())

    def _tab_sort_cb(self):
        ''' sorts the tabs '''
        self._sort_tabs()


    def _tab_clear_map_cb(self):
        ''' clears the mappings from the current tab '''
        tab_guid = gremlin.util.parse_guid(self._active_tab_guid())
        device : gremlin.base_profile.Device = gremlin.shared_state.current_profile.devices[tab_guid]
        current_mode = gremlin.shared_state.current_mode
        msgbox = gremlin.ui.ui_common.ConfirmBox(f"Remove all mappings from {device.name}, mode [{current_mode}]?")
        result = msgbox.show()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._tab_clear_map_execute(device, current_mode)

    def _tab_remove_device_cb(self):
        ''' removes a disconnected device from the menu '''
        tab_guid = gremlin.util.parse_guid(self._active_tab_guid())
        device : gremlin.base_profile.Device = gremlin.shared_state.current_profile.devices[tab_guid]
        if not device.connected:
            msgbox = gremlin.ui.ui_common.ConfirmBox(f"Remove this device from the profile?")
            result = msgbox.show()
            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                self._tab_remove_device_execute(device)

    def _tab_import_cb(self):
        ''' imports a profile into the device '''
        # tab_guid = gremlin.util.parse_guid(gremlin.shared_state.ui._active_tab_guid())
        # device : gremlin.base_profile.Device = gremlin.shared_state.current_profile.devices[tab_guid]
        gremlin.import_profile.import_profile()

    def _tab_clear_map_execute(self, device, mode_name):
        ''' removes all mappings from the given device in the active mode '''

        mode = device.modes[mode_name]
        for input_type in mode.config.keys():
            for entry in mode.config[input_type].values():
                entry.containers.clear()
        self.setTabsDirty(True)
       

    def _tab_remove_device_execute(self, device):
        ''' removes the specified device '''
        current_profile = gremlin.shared_state.current_profile
        current_profile.remove_device(device)



    def _tab_substitute_cb(self, pos):
        ''' substitution dialog for devices '''
        if self._context_menu_tab_index is None:
            # not setup yet - use the first discovered device in the profile
            profile = gremlin.shared_state.current_profile
            if len(profile.devices) > 0:
                self._context_menu_tab_index = 0

        if self._context_menu_tab_index is None:
            # no hardware tab found
            gremlin.ui.dialogs.ok_message_box("No input hardware was found to substitute.")
            return

        # verify we have hardware to substitute with
        data  = self.ui.devices.tabData(self._context_menu_tab_index)
        device_guid = data.device_guid

        #device_name = self.ui.devices.tabText(self._context_menu_tab_index)
        dialog = gremlin.profile_graph.DeviceRemapDialogUI(self.current_profile.graph, self, device_guid)
        # dialog = gremlin.ui.dialogs.SubstituteDialog(device_guid=device_guid, device_name=device_name, parent = self)
        # dialog.setModal(True)
        dialog.accepted.connect(self._substitute_complete_cb)
        gremlin.util.centerDialog(dialog)
        dialog.show()

    def _tab_copy_cb(self, pos):
        if self._context_menu_tab_index is None:
            # not setup yet - use the first discovered device in the profile
            profile = gremlin.shared_state.current_profile
            if len(profile.devices) > 0:
                self._context_menu_tab_index = 0

        if self._context_menu_tab_index is None:
            # no hardware tab found
            gremlin.ui.dialogs.ok_message_box("No input hardware was found to substitute.")
            return

        # verify we have hardware to substitute with
        data  = self.ui.devices.tabData(self._context_menu_tab_index)
        device_guid = data.device_guid

        dialog = gremlin.profile_graph.DeviceCopyDialogUI(device_guid)
        dialog.dialog_closed.connect(self._device_copy)
        dialog.exec()


    def _device_copy(self, dialog):
        if not dialog.result():
            return
        
        target_device = dialog.target_device
        source_device = dialog.source_device
        current_profile = gremlin.shared_state.current_profile
        current_profile.copy_devices(source_device.device_guid, target_device.device_guid)



    def _substitute_complete_cb(self):
        ''' substitution complete - reload profile '''
        # profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        # self.load_profile(profile.profile_file)
        pass

    def _reload(self):
        ''' reloads the ui '''
        self.setTabsDirty(True)


    @QtCore.Slot(str, bool)
    def _reload_profile(self, source_xml : str, as_new_profile : bool):
        ''' loads profile data from the specified file, optionally setting it up a new, unsaved, profile '''
        self._do_load_profile(source_xml, as_new_profile)
    
    def _profile_changed_cb(self, new_profile = None):
        ''' called when the a profile should be loaded '''

        if new_profile is None:
            # save current contents to a temporary file
            profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
            tmp_file = os.path.join(os.getenv("temp"), gremlin.util.get_guid() + ".xml")
            profile.save(tmp_file)
            self._profile_load_temporary_files.append(tmp_file)
            self._do_load_profile(tmp_file)
            os.unlink(tmp_file)
            profile.setProfileFile(None)
            self._update_window_title("Untitled")
        else:
            self._load_recent_profile(new_profile)

        self._update_status_bar()

    @property
    def current_profile(self):
        ''' gets the curernt active profile '''
        return self.profile


    def closeEvent(self, evt):
        """Terminate the entire application if the main window is closed.

        :param evt the closure event
        """

        if self.config.close_to_tray and self.ui.tray_icon.isVisible():
            self.hide()
            evt.ignore()
        else:

            # terminate the idle thread
            self.process_monitor.running = False
            try:
                if self.ui.tray_icon:
                    self.ui_tray_icon = None
            except:
                pass
            QtCore.QCoreApplication.quit()

        # Terminate file watcher thread
        if "log" in self.modal_windows:
            dialog = self.modal_windows["log"]
            if dialog:
                dialog.watcher.stop()


    # +---------------------------------------------------------------
    # | Modal window creation
    # +---------------------------------------------------------------

    def about(self):
        """Opens the about window."""
        self.modal_windows["about"] = gremlin.ui.dialogs.AboutUi()
        self.modal_windows["about"].show()
        self.modal_windows["about"].closed.connect(
            lambda: self._remove_modal_window("about")
        )


    @property
    def current_mode(self) -> str:
        ''' returns the current active profile mode '''
        return gremlin.shared_state.current_mode


    @property
    def current_profile(self) -> gremlin.base_profile.Profile:
        return gremlin.shared_state.current_profile


    def calibration(self):
        """Opens the calibration window."""
        # indicate the feature has been deprecated
        return
    

    def device_information(self):
        """Opens the device information window."""
        self.modal_windows["device_information"] = \
            gremlin.ui.dialogs.DeviceInformationUi(self.profile)
        geom = self.geometry()
        w = 600
        h = 400
        self.modal_windows["device_information"].setGeometry(
            int(geom.x() + geom.width() / 2 - w/2),
            int(geom.y() + geom.height() / 2 - h/2),
            w,
            h
        )
        self.modal_windows["device_information"].show()
        self.modal_windows["device_information"].closed.connect(
            lambda: self._remove_modal_window("device_information")
        )

    def log_window(self):
        gremlin.util.InvokeUiMethod(self._log_window_ui)

    def _log_window_ui(self):
        """Opens the log display window."""
        gremlin.util.assert_ui_thread()
        self.modal_windows["log"] = gremlin.ui.dialogs.LogWindowUi()
        self.modal_windows["log"].closed.connect(lambda: self._remove_modal_window("log"))
        self.modal_windows["log"].show()


    def log_edit(self):
        ''' opens the log file in the editor '''
        log_file = os.path.join(gremlin.shared_state.data_path, "system.log")
        if os.path.isfile(log_file):
            gremlin.util.display_file(log_file)


    def manage_modes(self):
        """Opens the mode management window."""
        dialog = gremlin.ui.dialogs.ModeManagerUi(self.profile)
        self.modal_windows["mode_manager"] = dialog
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.closed.connect(lambda: self._remove_modal_window("mode_manager"))
        dialog.show()


    def merge_axis(self):
        """Opens the modal window to define axis merging."""
        dialog = gremlin.ui.merge_axis.MergeAxisUi(self.profile)
        self.modal_windows["merge_axis"] = dialog
        gremlin.util.centerDialog(dialog)
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.closed.connect(lambda: self._remove_modal_window("merge_axis"))
        dialog.show()


    def options_dialog(self):
        """Opens the options dialog."""
        dialog = gremlin.ui.dialogs.OptionsUi()
        self.modal_windows["options"] = dialog
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.ensurePolished()
        gremlin.util.centerDialog(dialog, width = dialog.width(), height=dialog.height())
        dialog.closed.connect(self._handle_options_closed)
        dialog.exec()
        dialog.apply_window_settings()


    def _handle_options_closed(self):
        dialog = self.sender()
        self.modal_windows["options"] = None
        if not dialog.accepted:
            return
        
        self._apply_user_settings_ui(ignore_minimize=True, auto_start = False)

        # if dialog.reload_profile:
        self.refresh()
        # else:
        # tell components of the possible changes to the options
        el = gremlin.event_handler.EventListener()
        el.options_changed.emit()


        
    # def options_closed(self):
    #     dialog = self.sender()
    #     if dialog.reload_profile:
    #         self.refresh()



    def profile_creator(self):
        """Opens the UI used to create a profile from an existing one."""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Profile to load as template",
            gremlin.shared_state.data_path,
            "XML files (*.xml)"
        )
        if fname == "":
            return

        profile_data = gremlin.base_profile.Profile()
        profile_data.from_xml(fname)

        self.modal_windows["profile_creator"] = \
            gremlin.ui.profile_creator.ProfileCreator(profile_data)
        self.modal_windows["profile_creator"].show()
        gremlin.shared_state.push_suspend_highlighting()
        self.modal_windows["profile_creator"].closed.connect(
            lambda: gremlin.shared_state.pop_suspend_highlighting()
        )
        self.modal_windows["profile_creator"].closed.connect(
            lambda: self._remove_modal_window("profile_creator")
        )

    def swap_devices(self):
        """Opens the UI used to swap devices."""
        self.modal_windows["swap_devices"] = \
            gremlin.ui.dialogs.SwapDevicesUi(self.profile)
        geom = self.geometry()
        self.modal_windows["swap_devices"].setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        self.modal_windows["swap_devices"].show()
        self.modal_windows["swap_devices"].closed.connect(
            lambda: self._remove_modal_window("swap_devices")
        )
        self.modal_windows["swap_devices"].accepted.connect(self._create_tabs)


    def _remove_modal_window(self, name):
        """Removes the modal window widget from the system.

        :param name the name of the modal window to remove
        """
        if name in self.modal_windows:
            self.modal_windows[name] = None

    # +---------------------------------------------------------------
    # | Action implementations
    # +---------------------------------------------------------------

    def menu_activate(self, activate):
        if not activate:
            el = gremlin.event_handler.EventListener()
            el.profile_stop_toolbar.emit()
        self.activate(activate)

    def toggle_remote(self, enable):
        el = gremlin.event_handler.EventListener()
        if enable:
            # request to enable
            el.remote_control_enable.emit()
        else:
            # request to disable
            el.remote_control_disable.emit()





    def abort(self, message = None):
        gremlin.util.InvokeUiMethod(self._abort_ui, message) # run on UI thread

    def _abort_ui(self, message = None):
        ''' aborts profile execution on error '''
        if not gremlin.shared_state.is_running:
            # nothing to abort
            return

        
        if not gremlin.shared_state.aborted:
            el = gremlin.event_handler.EventListener()
            el.abort.emit()
            gremlin.shared_state.aborted = True # mark aborting globally

        # update UI
        self.ui.actionActivate.setChecked(False)
        self.activate(False)
        # wait for things to stabilize
        QtWidgets.QApplication.processEvents()
        if message:
            gremlin.ui.ui_common.MessageBox(prompt = message)


    def setUiMode(self):
        ''' enables or disables the UI based on the runtime mode and options 
        
        this can lock the UI while a profile is running to prevent inadvertent changes 

        '''
        enabled = True
        if gremlin.shared_state.is_running:
            enabled = self.config.runtime_ui_update
            self.push_highlighting()
        else:
            self.pop_highlighting(True)
            
        self.ui.tab_bar_widget.setEnabled(enabled)
        self.ui.tab_content_widget.setEnabled(enabled)
        self.ui.menuTools.setEnabled(enabled)
        self.ui.actionNewProfile.setEnabled(enabled)
        self.ui.actionSaveProfile.setEnabled(enabled)
        self.ui.actionSaveProfileAs.setEnabled(enabled)
        self.ui.actionManageCustomModules.setEnabled(enabled)

        self.ui.actionOptions.setEnabled(enabled)
        self.ui.actionCreate1to1Mapping.setEnabled(enabled)
        self.ui.actionModifyProfile.setEnabled(enabled)
        self.ui.menuRecent.setEnabled(enabled)
        # self.ui.actionSwapDevices.setEnabled(enabled)
        # self.ui.actionMergeAxis.setEnabled(enabled)

        self.ui.actionManageModes.setEnabled(enabled)

        self.ui.actionInputRepeater.setEnabled(enabled)
        self.ui.actionGenerate.setEnabled(enabled)
        #self.ui.actionImportProfile.setEnabled(enabled)
        self.ui.actionLoadProfile.setEnabled(enabled)


    



    def activate(self, activate: bool):
        gremlin.util.InvokeUiMethod(self._activate_ui, activate) # ensure on UI thread
        

    def _activate_ui(self, activate : bool):
        """Activates and deactivates the code runner.

        :param checked True when the runner is to be activated, False
            otherwise
        """
        import gremlin.ui.joystick_device
        import gremlin.ui.keyboard_device
        import gremlin.ui.midi_device
        import gremlin.ui.osc_device
        import gremlin.shared_state

        if self.activate_locked:
            #syslog.info("Activate: re-entry")
            return


        el = gremlin.event_handler.EventListener()

        try:

            self.abort_received = False
            self.abort_reason = None
            #syslog.info("Activate: start")
            self.activate_locked = True
            is_running = gremlin.shared_state.is_running
            gremlin.shared_state.profile_state = True # assume all ok



            from gremlin.config import Configuration
            config = Configuration()
            verbose = config.verbose
            verbose_mode_exec = config.verbose_mode_exec

            if activate:
                # Generate the code for the profile and run it
                if verbose: syslog.info(f"Activate: activate profile")
                self._profile_auto_activated = False
                #ec = gremlin.execution_graph.ExecutionContext()
                #ec.reset()
                gremlin.shared_state.aborted = False # reset abort flag


                # start the profile with the specified runtime mode
                result = self.runner.start(
                    self.profile.build_inheritance_tree(),
                    self.profile.settings,
                    self._last_runtime_mode(),
                    self.profile
                )

                if not result:
                    # profile start failed
                    gremlin.shared_state.profile_state = False
                    self.ui.tray_icon.setIcon(load_icon("gfx/icon.ico"))
                    with QtCore.QSignalBlocker(self.ui.actionActivate):
                        self.ui.actionActivate.setChecked(False) # toolbar icon "off"

                    if not gremlin.shared_state.profile_message_issued:
                        # error message not issued = issue it
                        gremlin.ui.ui_common.MessageBox(title = "Profile Start Error", prompt = f"An error occured when starting the profile.\nCheck the log file for specifics.")
                        gremlin.shared_state.profile_message_issued = True

                    return

                if gremlin.shared_state.profile_state:
                    #print ("set icon ACTIVE")
                    self.ui.tray_icon.setIcon(load_icon("gfx/icon_active.ico"))

                    with QtCore.QSignalBlocker(self.ui.actionActivate):
                        self.ui.actionActivate.setChecked(True) # toolbar icon "on"

                    return


            if not gremlin.shared_state.profile_state or is_running:
                # Stop running the code

                # running - save the last running mode to the executing profile
                if verbose: syslog.info(f"Deactivate profile requested")
                self.profile.set_last_runtime_mode(gremlin.shared_state.runtime_mode)
            
                # stop listen
                el.stop()

                # tell runner to stop
                self.runner.stop()

                if gremlin.shared_state.terminating:
                    # terminate faster
                    return

                self._update_status_bar_active(False)
                self._profile_auto_activated = False
                current_index = self.ui.devices.currentIndex()
                device_guid = self.getDeviceGuidForTabIndex(current_index)
                widget = self.getRegisteredWidget(device_guid)

                if widget:
                    tab_type = widget.data[0]
                    if tab_type in (
                    TabDeviceType.Joystick,
                    TabDeviceType.Keyboard,
                    TabDeviceType.Osc,
                    TabDeviceType.Midi):
                        widget.refresh()

                # toolbar icon
                with QtCore.QSignalBlocker(self.ui.actionActivate):
                    self.ui.actionActivate.setChecked(False) # toolbar icon "off"

                try:
                    if self.ui.tray_icon is not None:
                        self.ui.tray_icon.setIcon(load_icon("gfx/icon.ico"))
                except:
                     syslog.error(f"Load Icon: error: {err}\n{traceback.format_exc()}")
        except Exception as err:
            syslog.error(f"Activate: error: {err}\n{traceback.format_exc()}")

        finally:

            #syslog.info("Activate: completed")
            self.activate_locked = False

            self.setUiMode()

    @QtCore.Slot()
    def input_repeater(self):
        """Enables or disables the forwarding of events to the repeater."""
        el = gremlin.event_handler.EventListener()
        if self.ui.actionInputRepeater.isChecked():
            el.keyboard_event.connect(self.repeater.process_event)
            el.joystick_event.connect(self.repeater.process_event)
            el.vjoy_event.connect(self.repeater.process_event)
            self._update_statusbar_repeater("Waiting for input")
        else:
            el.keyboard_event.disconnect(self.repeater.process_event)
            el.joystick_event.disconnect(self.repeater.process_event)
            el.vjoy_event.disconnect(self.repeater.process_event)
            self.repeater.stop()
            self.status_bar_repeater_widget.setText("")

    @QtCore.Slot()
    def input_viewer(self):
        """Displays the input viewer dialog."""
        if self.modal_windows["input_viewer"]:
            # set the focus to that window
            dialog =self.modal_windows["input_viewer"]
            el = gremlin.event_handler.EventListener()
            if el.get_control_state():
                
                dialog.activateWindow()
                self.ui.actionInputViewer.setChecked(True)
            else:
                # close the window
                dialog.close()
                

        else:
            dialog = gremlin.ui.input_viewer.InputViewerUi()
            self.modal_windows["input_viewer"] = dialog
            
            if not dialog.hasConfig():
                # set size
                geom = self.geometry()
                self.modal_windows["input_viewer"].setGeometry(
                    int(geom.x() + geom.width() / 2 - 350),
                    int(geom.y() + geom.height() / 2 - 150),
                    700,
                    300
                )
            
            self.ui.actionInputViewer.setChecked(True)
            if gremlin.config.Configuration().input_viewer_disables_repeaters:
                gremlin.shared_state.push_repeater()

            dialog.show()
            dialog.closed.connect(self._close_input_viewer)
            gremlin.util.singleShot(dialog.apply_window_settings)

    @QtCore.Slot()
    def _reload_devices(self):
        gremlin.joystick_handling.reset_devices()

    def _close_input_viewer(self):
        # gremlin.shared_state.pop_suspend_highlighting()
        self._remove_modal_window("input_viewer")
        self.ui.actionInputViewer.setChecked(False)

        if gremlin.config.Configuration().input_viewer_disables_repeaters:
                gremlin.shared_state.pop_repeater()


    def load_profile(self, fname = None):
        """Prompts the user to select a profile file to load."""
        if not self._save_changes_request():
            return

        if not fname:

            fname, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Load Profile",
                gremlin.shared_state.data_path,
                "XML files (*.xml)"
            )

        if os.path.isfile(fname):
            self._load_recent_profile(fname)

    def import_profile(self):
        ''' import a profile '''
        gremlin.import_profile.import_profile()



    def new_profile(self):
        """Creates a new empty profile."""
        # Disable Gremlin if active before opening a new profile

        pushCursor()





        if not self._save_changes_request():
            return
        
        el = gremlin.event_handler.EventListener()
        
        if gremlin.shared_state.current_profile:
            current_profile = gremlin.shared_state.current_profile
            current_profile.unload()
            gremlin.shared_state.current_profile = None
            el.profile_unloaded.emit() # tell the UI we're about to load a new profile

        
        # clear any old data
        self._reset_tab_data()
        self.clearWidgets()

        ec = gremlin.execution_graph.ExecutionContext()
        ec.reset(no_rebuild = True)

        self.ui.actionActivate.setChecked(False)
        self.activate(False)


        gremlin.shared_state.resetState()
        eh = gremlin.event_handler.EventHandler()
        eh.reset()




        new_profile =  gremlin.base_profile.Profile()
        self.profile = new_profile
        

        # default active mode
        gremlin.shared_state.runtime_mode = "Default"
        gremlin.shared_state.edit_mode = "Default"
        gremlin.shared_state.current_profile = new_profile

        # For each connected device create a new empty device entry
        # in the new profile
        for device in gremlin.joystick_handling.physical_devices():
            self.profile.initialize_joystick_device(device, ["Default"])


        # non regular devices
        self.profile.initialize_regular_devices()

        # reset joystick input/output flags
        sd = gremlin.event_handler.JoystickState()
        sd.reset()

        # Update profile information
        self._update_window_title()

        

        self.setTabsDirty(True)

        # reset modes
        current_mode = gremlin.shared_state.current_mode
        self.mode_selector.populate_selector(new_profile, current_mode, emit = False)

        # Create a default mode
        for device in self.profile.devices.values():
            device.ensure_mode_exists("Default")

        # Update everything to the new mode
        #self._mode_configuration_changed()




        self._update_status_bar()
        self._select_last_tab()
        
        
        popCursor()

    def save_profile(self):
        """Saves the current profile to the hard drive.

        If the file was loaded from an existing profile that file is
        updated, otherwise the user is prompted for a new file.
        """
        if self.profile.profile_file is not None:
            self.profile.save()
            # update the hash so we can detect changes
            self._profile_hash = self.profile.getMappingHash()
        else:
            self.save_profile_as()

        

    def save_profile_as(self):
        """Prompts the user for a file to save to profile to."""
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save Profile",
            gremlin.shared_state.data_path,
            "XML files (*.xml)"
        )
        if fname != "":
            self.profile.setProfileFile(fname)
            self.profile.save()
            # update the hash so we can detect changes
            self._profile_hash = self.profile.getMappingHash()
            self.config.last_profile = self.profile.profile_file
            self._create_recent_profiles()
            self._update_window_title()

    def reveal_profile(self):
        ''' opens the profile in explorer '''
        profile_fname = self.profile.profile_file
        if profile_fname and os.path.isfile(profile_fname):
            path = os.path.dirname(profile_fname)
            path = os.path.realpath(path)
            webbrowser.open(path)

    def reveal_logfile(self):
        ''' opens the logfile in the current text editor '''
        logfile = os.path.join(gremlin.shared_state.data_path, "system.log")
        if os.path.isfile(logfile):
            webbrowser.open(logfile)

    def open_profile_xml(self):
        ''' views the profile as an xml in the default text editor '''
        profile_fname = self.profile.profile_file
        if profile_fname:
            # save first
            self.profile.to_xml(profile_fname)
            if  os.path.isfile(profile_fname):
                path = os.path.realpath(profile_fname)
                webbrowser.open(path)


    def open_gremlinex_folder(self):
        ''' opens the gremlin EX folder '''
        path = gremlin.shared_state.data_path
        webbrowser.open(path)


    # +---------------------------------------------------------------
    # | Create UI elements
    # +---------------------------------------------------------------

    def _connect_actions(self):
        """Connects all QAction items to their corresponding callbacks."""
        # Menu actions
        # File
        self.ui.actionLoadProfile.triggered.connect(self.load_profile)
        #self.ui.actionImportProfile.triggered.connect(self.import_profile)
        self.ui.actionNewProfile.triggered.connect(self.new_profile)
        self.ui.actionSaveProfile.triggered.connect(self.save_profile)
        self.ui.actionSaveProfileAs.triggered.connect(self.save_profile_as)
        self.ui.actionRevealProfile.triggered.connect(self.reveal_profile)
        self.ui.actionOpenLogFile.triggered.connect(self.reveal_logfile)
        self.ui.actionOpenXmlProfile.triggered.connect(self.open_profile_xml)
        self.ui.actionOpenGremlinExFolder.triggered.connect(self.open_gremlinex_folder)
        self.ui.actionModifyProfile.triggered.connect(self.profile_creator)
        self.ui.actionExit.triggered.connect(self._force_close)
        # Actions
        self.ui.actionCreate1to1Mapping.triggered.connect(self._create_1to1_mapping)
        # self.ui.actionMergeAxis.triggered.connect(self.merge_axis)
        # self.ui.actionSwapDevices.triggered.connect(self.swap_devices)

        # Tools
        self.ui.actionDeviceInformation.triggered.connect(self.device_information)
        self.ui.actionManageModes.triggered.connect(self.manage_modes)
        self.ui.actionInputRepeater.triggered.connect(self.input_repeater)
        #self.ui.actionCalibration.triggered.connect(self.calibration)
        self.ui.actionInputViewer.triggered.connect(self.input_viewer)

        self.ui.actionReloadDevices.triggered.connect(self._reload_devices)

        self.ui.actionCheatsheet.triggered.connect(lambda: self._create_cheatsheet())
        self.ui.actionViewInput.triggered.connect(lambda: self._view_input_map())
        self.ui.actionOptions.triggered.connect(self.options_dialog)
        self.ui.actionLogDisplay.triggered.connect(self.log_window)
        self.ui.actionLogEdit.triggered.connect(self.log_edit)
        # About
        self.ui.actionAbout.triggered.connect(self.about)

        # Toolbar actions
        self.ui.actionActivate.triggered.connect(self.menu_activate)
        self.ui.actionOpen.triggered.connect(self.load_profile)
        self.ui.actionSave.triggered.connect(self.save_profile)
        self.ui.actionToggleRemoteControl.triggered.connect(self.toggle_remote)
        

        # Tray icon
        self.ui.tray_icon.activated.connect(self._tray_icon_activated_cb)

        # Simconnect configuration
        self.ui.actionSimconnectOptions.triggered.connect(self.showSimconnectOptions)
        self.ui.actionSimconnectOptionsToolbar.triggered.connect(self.showSimconnectOptions)


    def showSimconnectOptions(self):
        ''' displays the simconnect options dialog '''
        el = gremlin.event_handler.EventListener()
        el.simconnect_show_options.emit()

    def _create_1to1_mapping(self):
        ''' maps one to one '''
        mapper = gremlin.import_profile.Mapper()
        mapper.create_1to1_mapping()


    def _create_recent_profiles(self):
        """Populates the Recent submenu entry with the most recent profiles."""
        self.ui.menuRecent.clear()
        for entry in self.config.recent_profiles:
            action = self.ui.menuRecent.addAction(gremlin.util.truncate(entry, 5, 40))
            action.triggered.connect(self._create_load_profile_function(entry))

    def _create_statusbar(self):
        """Creates the ui widgets used in the status bar."""
        self.status_bar_mode_widget = QtWidgets.QLabel("")
        self.status_bar_mode_widget.setContentsMargins(5, 0, 5, 0)
        self.status_bar_is_active_widget = QtWidgets.QLabel("")
        self.status_bar_is_active_widget.setContentsMargins(5, 0, 5, 0)
        self.status_bar_repeater_widget = QtWidgets.QLabel("")
        self.status_bar_repeater_widget.setContentsMargins(5, 0, 5, 0)

        self.status_bar_highlight_tabswitch_widget = QtWidgets.QPushButton()
        self.status_bar_highlight_tabswitch_widget.setStyleSheet("border: none")
        self.status_bar_highlight_tabswitch_widget.clicked.connect(self._toggle_tabswitch_highlight)
        self.status_bar_highlight_tabswitch_widget.setToolTip("Enable auto-tab switch on device input")


        self.status_bar_highlight_axis_widget = QtWidgets.QPushButton()
        self.status_bar_highlight_axis_widget.setStyleSheet("border: none")
        self.status_bar_highlight_axis_widget.clicked.connect(self._toggle_axis_highlight)
        self.status_bar_highlight_axis_widget.setToolTip("Enable axis input highlighting.\nThis mode can also be temporarily enabled while holding a ctrl key.")

        self.status_bar_highlight_button_widget = QtWidgets.QPushButton()
        self.status_bar_highlight_button_widget.setStyleSheet("border: none")
        self.status_bar_highlight_button_widget.clicked.connect(self._toggle_button_highlight)
        self.status_bar_highlight_button_widget.setToolTip("Enable button input highlighting.\nThis mode can also be temporarily enabled while holding a shift key.")


        self.status_bar_highlight_enable_widget = QtWidgets.QPushButton()
        self.status_bar_highlight_enable_widget.setStyleSheet("border: none")
        self.status_bar_highlight_enable_widget.setChecked(self.config.highlight_enabled)
        self.status_bar_highlight_enable_widget.clicked.connect(self._toggle_highlight_enabled)
        self.status_bar_highlight_enable_widget.setToolTip("Enable highlighting")


        self.status_bar_module_container_widget = QtWidgets.QWidget()
        self.status_bar_module_container_widget.setContentsMargins(0,0,0,0)
        self.status_bar_module_container_layout = QtWidgets.QHBoxLayout(self.status_bar_module_container_widget)
        self.status_bar_module_container_layout.setContentsMargins(0,0,0,0)

        self._status_bar_module_states = {}
        el = gremlin.event_handler.EventListener()
        el.module_state_change.connect(self._module_state_changed)
        el.module_state_register.connect(self.registerStatusModule)
        

        self.ui.statusbar_layout.addWidget(self.status_bar_is_active_widget)
        self.ui.statusbar_layout.addWidget(self.status_bar_repeater_widget)
        self.ui.statusbar_layout.addWidget(self.status_bar_mode_widget)
        self.ui.statusbar_layout.addWidget(QtWidgets.QLabel(" "))
        self.ui.statusbar_layout.addWidget(self.status_bar_module_container_widget)

        self.ui_statusbar_highlight_container_widget = QtWidgets.QWidget()
        self.ui_statusbar_highlight_container_widget.setContentsMargins(0,0,0,0)
        self.ui_statusbar_highlight_container_layout = QtWidgets.QHBoxLayout(self.ui_statusbar_highlight_container_widget)
        self.ui_statusbar_highlight_container_layout.setContentsMargins(0,0,0,0)

        self.ui_statusbar_highlight_state_container_widget = QtWidgets.QWidget()
        self.ui_statusbar_highlight_state_container_widget.setContentsMargins(0,0,0,0)
        self.ui_statusbar_highlight_state_container_layout = QtWidgets.QHBoxLayout(self.ui_statusbar_highlight_state_container_widget)
        self.ui_statusbar_highlight_state_container_layout.setContentsMargins(0,0,0,0)

        self.ui_statusbar_highlight_state_container_layout.addWidget(QtWidgets.QLabel("Device"))                                                     
        self.ui_statusbar_highlight_state_container_layout.addWidget(self.status_bar_highlight_tabswitch_widget)
        
        self.ui_statusbar_highlight_state_container_layout.addWidget(gremlin.ui.ui_common.QHorizontalSeparator())
        self.ui_statusbar_highlight_state_container_layout.addWidget(QtWidgets.QLabel("Axis"))                                                     
        self.ui_statusbar_highlight_state_container_layout.addWidget(self.status_bar_highlight_axis_widget)

        
        self.ui_statusbar_highlight_state_container_layout.addWidget(gremlin.ui.ui_common.QHorizontalSeparator())
        self.ui_statusbar_highlight_state_container_layout.addWidget(QtWidgets.QLabel("Button"))
        self.ui_statusbar_highlight_state_container_layout.addWidget(self.status_bar_highlight_button_widget)

        self.ui_statusbar_highlight_container_layout.addStretch()
        self.ui_statusbar_highlight_container_layout.addWidget(QtWidgets.QLabel("<b>Highlight</b>"))
        self.ui_statusbar_highlight_container_layout.addWidget(self.ui_statusbar_highlight_state_container_widget)

        
        self.ui_statusbar_highlight_state_container_layout.addWidget(gremlin.ui.ui_common.QHorizontalSeparator())
        self.ui_statusbar_highlight_container_layout.addWidget(QtWidgets.QLabel("Enabled"))
        self.ui_statusbar_highlight_container_layout.addWidget(self.status_bar_highlight_enable_widget)

        self.ui.statusbar_layout.addStretch()
        self.ui.statusbar_layout.addWidget(self.ui_statusbar_highlight_container_widget)
        

        
        self.ui.statusbar_layout.addStretch()
        self.ui.statusbar_layout.addWidget(self.ui_statusbar_highlight_container_widget)
        

        

        icon_size = QtCore.QSize(16,16)
        icon = gremlin.util.load_icon("mdi.checkbox-blank-circle", use_qta=True,qta_color= gremlin.ui.ui_common.Color.recordColor())
        self._icon_red = icon
        self._status_red = icon.pixmap(icon_size)
        icon = gremlin.util.load_icon("mdi.checkbox-blank-circle", use_qta=True,qta_color=gremlin.ui.ui_common.Color.activeColor())
        self._icon_green = icon
        self._status_green = icon.pixmap(icon_size)
        icon = gremlin.util.load_icon("mdi.checkbox-blank-circle", use_qta=True,qta_color=gremlin.ui.ui_common.Color.inactiveColor())
        self._icon_gray = icon
        self._status_gray = icon.pixmap(icon_size)


        self._update_highlight_toolbar_enabled()



    def _update_highlight_toolbar_enabled(self):
        ''' updates the enabled status of the highlight status bar buttons based on current enabled state '''
        enabled = self.config.highlight_enabled
        icon = self._icon_green if enabled else self._icon_gray
        self.status_bar_highlight_enable_widget.setIcon(icon)



    @QtCore.Slot()
    def _profile_start(self):
        self.setUiMode()
        self._update_status_bar_active(True)
        self._update_status_bar_modules_ui()
        self.ui_statusbar_highlight_state_container_widget.setEnabled(False)
    
    @QtCore.Slot()
    def _profile_stop(self):
        self.setUiMode()
        self._update_status_bar_active(False)
        self._update_highlight_toolbar_enabled()
        self.ui_statusbar_highlight_state_container_widget.setEnabled(True)

    @QtCore.Slot(str, str, object)
    def registerStatusModule(self, key, label : str, state : object, callback):
        ''' registersor updates a module with a state '''
        if key:
            self._status_bar_module_states[key] = (label, state, callback)
            self._update_status_bar_modules()

    
    @QtCore.Slot(str, object)
    def _module_state_changed(self, key, state : object):
        # syslog = logging.getLogger("system")
        syslog.info(f"module state: {key} state: {state}")
        if key in self._status_bar_module_states:
            label, value, callback = self._status_bar_module_states[key]
            if value != state:
                self._status_bar_module_states[key] = (label, state, callback)
                self._update_status_bar_modules_ui()

    def _update_status_bar_modules(self):
        gremlin.util.InvokeUiMethod(self._update_status_bar_modules_ui) # ensure on UI thread

    def _update_status_bar_modules_ui(self):
        ''' recreates the module status bar UI based on current status - this is used for modules to add content to the status bar at runtime '''
        if not Shiboken.isValid(self.status_bar_module_container_widget):
            return
        gremlin.ui.ui_common.clear_layout(self.status_bar_module_container_layout)
        index = 0
        for label, state, callback in self._status_bar_module_states.values():
            pixmap = None
            widget = None
            if state is not None:
                if isinstance(state, bool):
                    pixmap = self._status_green if state else self._status_red
                elif isinstance(state, str):
                    state = state.casefold()
                    match state:
                        case "on":
                            pixmap = self._status_green
                        case "off":
                            pixmap = self._status_red
                        case "notset":
                            pixmap = self._status_gray
                        case "":
                            pixmap = self._status_gray
                elif isinstance(state, QtGui.QIcon):
                    # state is a widget
                    pixmap = state.pixmap(24,24)


            if pixmap is not None:
                widget = QtWidgets.QLabel()
                widget.setPixmap(pixmap)
            

            if callback is not None:
                action_widget = QtWidgets.QPushButton(label)
                action_widget.clicked.connect(callback)
                action_widget.setStyleSheet("background:transparent; border: 0;")
            else:
                action_widget = QtWidgets.QLabel(label)

            if index and label: 
                # add a separator
                self.status_bar_module_container_layout.addWidget(gremlin.ui.ui_common.QHorizontalSeparator())

            self.status_bar_module_container_layout.addWidget(action_widget)
            if widget:
                self.status_bar_module_container_layout.addWidget(widget)

            index += 1

        self.status_bar_module_container_layout.addStretch()

        self._update_highlight_toolbar_enabled()


    @QtCore.Slot()
    def _toggle_tabswitch_highlight(self):
        eh = gremlin.event_handler.EventListener()
        status = self.config.highlight_autoswitch
        eh.toggle_highlight.emit(not status, None, None)
        
        
    @QtCore.Slot()
    def _toggle_axis_highlight(self):
        eh = gremlin.event_handler.EventListener()
        status = self.config.highlight_input_axis
        enabled = not status
        self.config.highlight_input_axis = enabled
        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info(f"Toggle axis highlight: {enabled}")
        eh.toggle_highlight.emit(None, enabled, None)


    @QtCore.Slot()
    def _toggle_button_highlight(self, checked):
        eh = gremlin.event_handler.EventListener()
        
        status = self.config.highlight_input_buttons
        enabled = not status
        self.config.highlight_input_buttons = enabled

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info(f"Toggle button highlight: {enabled}")
        eh.toggle_highlight.emit(None, None, enabled)

    @QtCore.Slot()
    def _toggle_highlight_enabled(self, checked):
        self.config.highlight_enabled = not self.config.highlight_enabled
        el = gremlin.event_handler.EventListener()
        el.enable_highlight_changed.emit(checked)



    @QtCore.Slot(bool)
    def _highlight_enable_changed(self, enabled : bool):
        self._update_highlight_toolbar_enabled()
        if enabled:
            # reset the highlight stack
            gremlin.shared_state.pop_suspend_highlighting(True)
        

        
        


    def _create_system_tray(self):
        """Creates the system tray icon and menu."""
        self.ui.tray_menu = QtWidgets.QMenu("Menu")
        self.ui.action_tray_show = \
            QtGui.QAction("Show / Hide", self)
        self.ui.action_tray_enable = \
            QtGui.QAction("Start/Stop profile", self)
        self.ui.action_tray_quit = QtGui.QAction("Quit", self)
        self.ui.tray_menu.addAction(self.ui.action_tray_show)
        self.ui.tray_menu.addAction(self.ui.action_tray_enable)
        self.ui.tray_menu.addAction(self.ui.action_tray_quit)

        self.ui.action_tray_show.triggered.connect(self._show_hide_cb)

        self.ui.action_tray_enable.triggered.connect(
            self.ui.actionActivate.trigger
        )
        self.ui.action_tray_quit.triggered.connect(
            self._force_close
        )

        self.ui.tray_icon = QtWidgets.QSystemTrayIcon()
        self.ui.tray_icon.setIcon(load_icon("gfx/icon.ico"))
        self.ui.tray_icon.setContextMenu(self.ui.tray_menu)
        self.ui.tray_icon.show()

    def _show_hide_cb(self):
        ''' show or hide the window '''
        if self.isHidden():
            self.setHidden(False)
            self.showNormal()
        else:
            self.setHidden(True)


    def registerWidget(self, device_guid, widget, hide = True) -> int:
        ''' registers widget for cleanup - this is needed because QT doesn't tell us when widgets are discarded so we need to manually track this here 
        so widgets cleanup correctly and remove any hooks / references 
        
        :returns: index - the index of the widget
        
        '''

        assert widget is not None, "Invalid widget"
        
        
        device_guid = gremlin.util.normalize_guid(device_guid)

        # device = gremlin.joystick_handling.device_info_from_guid(device_guid)
        verbose = gremlin.config.Configuration().verbose_mode_ui


        index =  self.ui.device_widget.indexOf(widget)
        if index != -1:
            # widget is already in the list
            device_name = self._get_device_name(device_guid)
            syslog.error(f"TAB: widget already exists for tab: {device_guid} {device_name}")
        else:
            self.ui.device_widget.addWidget(widget)

        index = self.ui.device_widget.indexOf(widget)
        self._widget_device_index_map[device_guid] = index
        self._widget_index_device_map[index] = device_guid
        device_name = self._get_device_name(device_guid)
        if verbose: syslog.info(f"REGISTER WIDGET: {device_guid} index {index}  name: {device_name}")

        if not hide:
            # make visible
            self.ui.device_widget.setCurrentIndex(index)

        return index
        
        
    def selectRegisteredWidget(self, device_guid) -> int:
        ''' selects the content for the given device id if the content exists 
        
        :param device_guid: device to select
        :returns: index, -1 if not found
        
        '''
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        index = -1
        if device_guid in self._widget_device_index_map:
            index = self._widget_device_index_map[device_guid]
            if index == -1:
                device_name = self._get_device_name(device_guid)
                syslog.warning(f"Requested widget for device [{device_guid}] [{device_name}] not found.")
            else:
                if self.ui.device_widget.currentIndex() != index:
                    self.ui.device_widget.setCurrentIndex(index)
        return index


    def unregisterWidget(self, device_guid):
        ''' removes a widget from the cleanup list'''
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._widget_device_index_map:
            index = self._widget_device_index_map[device_guid]
            if index != -1:
                widget = self.ui.device_widget.widget(index)
                if hasattr(widget, "_cleanup_ui"):
                    widget._cleanup_ui()    
                self.ui.device_widget.removeWidget(widget)
                widget.deleteLater()
            del self._widget_device_index_map[device_guid]
            del self._widget_index_device_map[index]

    def getCurrentRegisteredWidgetDevice(self):
        ''' gets the device ID for the currently selected device widget '''
        index = self.ui.device_widget.currentIndex()
        if index != -1:
            device_guid = self._widget_index_device_map[index]
            return device_guid
        return None


    def clearRegisteredWidgets(self):
        ''' cleanup all widgets '''
        return self.unregisterAllWidgets()


    def unregisterAllWidgets(self):
        ''' clears all device widgets '''
        while self.ui.device_widget.count():
            widget = self.ui.device_widget.widget(0)
            if hasattr(widget, "_cleanup_ui"):
                # tell the widget it's being deleted
                widget._cleanup_ui()    
            self.ui.device_widget.removeWidget(widget)
            widget.deleteLater()
            
        self._widget_device_index_map.clear()
        self._widget_index_device_map.clear()

    def getRegisteredWidget(self, device_guid) -> QtWidgets.QWidget:
        ''' gets the widget for the given device id, None if not found'''
        device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._widget_device_index_map:
            index = self._widget_device_index_map[device_guid]
            return self.ui.device_widget.widget(index)
        return None
    
    def getRegisteredWidgetIndex(self, device_guid) -> int:
        device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._widget_device_index_map:
            return self._widget_device_index_map[device_guid]
        return None

    def clearWidgets(self):
        ''' clears the device cache'''
        tracker = gremlin.ui.ui_common.StateTracker()
        tracker.clear()
        self.unregisterAllWidgets()
        verbose = gremlin.config.Configuration().verbose_mode_ui
        gc.collect()
        if verbose: syslog.info("TABS TRACKER: clear()")
        

    def getTabIndexForDevice(self, device_guid):
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._tab_device_map:
            return self._tab_device_map[device_guid]
        return None
    
    def getFirstTabDeviceGuid(self):
        ''' gets the device for the first tab '''
        for device_guid in self._tab_device_map.keys():
            return device_guid
        return None

    def getDeviceGuidForTabIndex(self, index):
        ''' gets the device GUID for a given tab index '''
        if index in self._tab_index_map:
            return self._tab_index_map[index]


    def swapTab(self, index, other):
        ''' swaps two values in the map '''
        if index in self._tab_index_map and other in self._tab_index_map:
            d1 = self._tab_index_map[index]
            d2 = self._tab_index_map[other]
            self._tab_index_map[index] = d2
            self._tab_index_map[other] = d1
            self._tab_device_map[d1] = other
            self._tab_device_map[d2] = index


    def clearTabIndex(self):
         self._tab_index_map.clear()


    def getWidgetByTabIndex(self, index):
        ''' gets the device widget by the tab index'''
        if index in self._tab_index_map:
            device_guid =  self._tab_index_map[index]
            return self.getRegisteredWidget(device_guid)
        return None




    
    def hideTabWidgets(self):
        ''' hides all tab widgets '''
        if gremlin.shared_state.ui_ready:
            for widget in self._widget_device_index_map.values():
                if widget.parent(): widget.setVisible(False)

            
    def selectTabWidgetByIndex(self, index : int):
        ''' shows the page (content widget) for the specified tab index '''
        if index in self._tab_index_map:
            device_guid = self._tab_index_map[index]
            self.selectTabWidget(device_guid)


    def selectTabWidget(self, device_guid):
        ''' shows the page (content widget) for the specified device'''
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)

        el = gremlin.event_handler.EventListener()
        verbose = gremlin.config.Configuration().verbose_mode_extra
        
        current_device_guid = gremlin.shared_state.current_tab_device_guid
        if current_device_guid:
            if gremlin.shared_state.current_tab_device_guid == device_guid:
                # already shown
                return 
        
            device_name = self._get_device_name(current_device_guid)
            if verbose: syslog.info(f"TAB UNSELECT: {device_name}")
            el.tab_unselected.emit(current_device_guid)
        
        # select the tab index 
        index = self.getTabIndexForDevice(device_guid)
        if index and self.ui.devices.currentIndex() != index:
            with QtCore.QSignalBlocker(self.ui.devices):
                self.ui.devices.setCurrentIndex(index)
        
        
        index = self.selectRegisteredWidget(device_guid)
        if index != -1:
            
            if not isinstance(device_guid, str):
                device_guid = gremlin.util.normalize_guid(device_guid)
            # tell ui a new device tab was selected
            gremlin.shared_state.current_tab_device_guid = device_guid
            device_name = self._get_device_name(device_guid)

            verbose = gremlin.config.Configuration().verbose_mode_extra
            if verbose: syslog.info(f"TAB SELECT: {device_name}")
            el.tab_selected.emit(device_guid)
            

    def getActiveTabWidget(self) -> gremlin.ui.ui_common.QSplitTabWidget:
        ''' gets the current tab widget '''
        return self.getRegisteredWidget(gremlin.shared_state.current_tab_device_guid)
    
    def getActiveTabIndex(self) -> int:
        ''' gets the current tab index '''
        return self.ui.devices.currentIndex()

    def getActiveTabType(self) -> TabDeviceType:
        index = self.ui.devices.currentIndex()
        data : gremlin.input_item.TabData = self.ui.devices.tabData(index)
        return  TabDeviceType(data.tab_type)
    
    def _mapping_changed(self, item_data : gremlin.base_profile.InputItem):
        ''' called when mapping changes '''

        self._update_tab(item_data.device_id) # update tab header

    def _show_container_id_visible_changed(self):
        ''' refresh the UI on container visibility changed'''
        self.refresh()

    def _update_tab(self, device_id: str):
        gremlin.util.InvokeUiMethod(self._update_tab_ui, device_id)
    
    def _update_tab_ui(self, device_id: str):
        ''' updates the given tab for mapping and connection status '''
        position = self.getTabIndexForDevice(device_id)
        if position is not None:
            device = gremlin.joystick_handling.device_info_from_guid(device_id)
            device.update() # update connection state
            if not device.connected:
                # indicate device is disconnected
                color = gremlin.ui.ui_common.Color().disconnectedColor()
                icon = gremlin.ui.ui_common.Icons.disconnectedIcon() #.load_icon("mdi.power-plug-off", qta_color = color)
                self.ui.devices.setTabIcon(position, icon)
                self.ui.devices.setTabTextColor(position, color)   
            else:
                # tab color based on mapping
                has_mapping = self._has_mapping(device_id)
                color = gremlin.ui.ui_common.Color().mappedColor() if has_mapping else gremlin.ui.ui_common.Color().unmappedColor()
                self.ui.devices.setTabTextColor(position, color)
        


    def setTabsDirty(self, update = False):
        ''' indicate tabs must be refreshed next time create tabs is called '''


        if update:
            self._create_tabs()

    def _create_tabs(self, activate_tab=None):
        gremlin.util.InvokeUiMethod(self._create_tabs_ui)

    def _create_tabs_ui(self, activate_tab=None):
        """Creates the tabs of the configuration dialog representing
        the different connected devices.
        """
        try:
            

            #sd = gremlin.event_handler.JoystickState()
            ts = gremlin.tabstate.TabState()

            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_device or config.verbose_mode_ui
            # verbose = True
            verbose_detailed = verbose and config.verbose_mode_extra
           
            if verbose: syslog.info("CREATE TAB: start")

            #if verbose_detailed: syslog.info("CREATE TAB: start")

            device : DeviceSummary
            device_guid = None

            midi_enabled = self.config.midi_enabled
            osc_enabled = self.config.osc_enabled

            self.push_highlighting()
            el = gremlin.event_handler.EventListener()
            gremlin.shared_state.push_input_selection() # prevent selections
            
            self._reset_tab_data()
            self.clearWidgets()

            # reload device list in case it changed
            gremlin.shared_state.reload_device_map()

            


            gremlin.shared_state.is_tab_loading = True
           
            # clear the widget map as it's recreated here
            #gremlin.shared_state.device_widget_map.clear()

            self.last_tab_index = 0

            # Device lists
            phys_devices = gremlin.joystick_handling.physical_devices()
            vjoy_devices = gremlin.joystick_handling.vjoy_devices()

            self._active_devices = gremlin.joystick_handling.all_joystick_devices()


            # get list of devices in the profile that do not exist or are not connected
            graph : gremlin.profile_graph.ProfileGraph = gremlin.shared_state.current_profile.graph

            graph_devices = graph.joystick_devices()

            # derive missing devices found in the profile, but not currently connected
            missing_phys_devices = [dev for dev in graph_devices if not dev.device_guid in [d.device_guid for d in phys_devices] and dev.device_type == gremlin.types.DeviceType.Joystick]
            missing_vjoy_devices = [dev for dev in graph_devices if not dev.device_guid in [d.device_guid for d in vjoy_devices] and dev.device_type == gremlin.types.DeviceType.VJoy]

            self._missing_phys_devices = missing_phys_devices
            self._missing_vjoy_devices = missing_vjoy_devices

            for device in self._missing_phys_devices + self._missing_vjoy_devices:
                gremlin.joystick_handling.registerSpecialDevice(device)

            

            if verbose:
                for device in self._missing_phys_devices:
                    syslog.warning(f"Missing device: {str(device)}")

            all_phys_devices = missing_phys_devices + phys_devices
            all_vjoy_devices = missing_vjoy_devices + vjoy_devices
            

            self._all_devices_map = {}
            for device in all_phys_devices + all_vjoy_devices:
                self._all_devices_map[device.device_id] = device
            

            # index of the current tab being addded 
            index = 0

            sorted_devices = sorted(all_phys_devices, key=lambda x: x.name)
            
            # =======================================================
            # Create physical joystick device tabs
            for device in sorted_devices:
                if verbose: syslog.info(f"TAB: [{index}] processing device [{device.name}]  [{device.device_id}]")
                if device.disabled:
                    if verbose: syslog.info("\tdisabled - skipping tab")
                    continue
                device_profile = self.profile.get_device_modes(
                    device.device_guid,
                    DeviceType.Joystick,
                    device.name
                )

                # this needs to be registered before widgets are created because widgets may need this data
                gremlin.shared_state.device_profile_map[device.device_guid] = device_profile
                gremlin.shared_state.device_type_map[device.device_guid] = DeviceType.Joystick
                #tab_label = device.name.strip()
                
                
                device_guid = device.device_id
                device_name = device.name
                if device_name:
                    widget = self.getRegisteredWidget(device_guid)
                    
                    if not widget or not Shiboken.isValid(widget):
                        if verbose: syslog.info("\tcreating widget...")
                        widget = gremlin.ui.joystick_device.JoystickDeviceTabWidget(
                            device,
                            device_profile,
                            self.current_mode,
                            object_name= f"Joystick [{device_name}]"
                        )
                        
                        self.registerWidget(device_guid, widget)
                    else:
                        if verbose: syslog.info("\tusing existing widget...")

                    self._add_tab(device_guid, TabDeviceType.Joystick)
                    widget.tabData = ts.getData(device_guid)

                  
                    widget.data = (TabDeviceType.Joystick, device_guid, index)

                    #gremlin.shared_state.device_widget_map[device_profile.device_guid] = widget
                    widget.inputChanged.connect(self._device_input_changed_cb)
                
                    index += 1
                        


                    # pick a default entry for each tab if one is not currently selected
                    device_guid = self.config.last_device_guid
                    _, last_input_id = self._get_last_input(device_guid)
                    if last_input_id is None:
                        # get the first input item of the tab
                        input_item = self._get_input_item(device_guid, 0)
                        if input_item:
                            # input_id = input_item.input_id
                            # input_type = input_item.input_type
                            #el.input_selection_changed.emit(device_guid, input_type, input_id)
                            self.config.last_device_guid = device_guid
                        

            # =======================================================
            # add the VJOY input devices to the device tabs
            self._vjoy_input_device_guids = []
            
            # Create vJoy as input device tabs
            for device in sorted(all_vjoy_devices, key=lambda x: x.vjoy_id):
                # Ignore vJoy as output devices
                
                device_guid = device.device_guid
                device_name = device.name
                #input_enabled = sd.inputEnabled(device.device_guid) #  self.profile.settings.vjoy_as_input.get(device.vjoy_id, False)
                input_enabled = self.profile.settings.vjoy_as_input.get(device.vjoy_id, False)
              
                if not input_enabled:
                    if verbose: syslog.info(f"VJOY TAB: {device_name} not created because input is disabled on this device.")
                    continue
                if not device.connected:
                    if verbose: syslog.info(f"VJOY TAB: {device_name} not created because device is not connected.")
                    continue
                # vjoy as input enabled
                
                if device_name:
                    device_profile = self.profile.get_device_modes(
                        device.device_guid,
                        DeviceType.Joystick,
                        device_name
                    )

                    device_guid = gremlin.util.normalize_guid(device.device_guid)
                    widget = self.getRegisteredWidget(device_guid)
                    if not widget:
                        widget = gremlin.ui.joystick_device.JoystickDeviceTabWidget(
                            device,
                            device_profile,
                            self.current_mode,
                            object_name = f"Vjoy [{device_name}]"
                        )

                    
                        self.registerWidget(device_guid, widget)
                        #gremlin.shared_state.device_widget_map[device.device_guid] = widget
                    
                    widget.data = (TabDeviceType.VjoyInput, device_guid, index)
                    self._add_tab(device_guid, TabDeviceType.VjoyInput)
                    index += 1
                    self._vjoy_input_device_guids.append(device_guid)
                    if verbose:
                        syslog.info(f"Added vjoy tab: {device_name} index {index}")

            # =======================================================
            # Create keyboard tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
            device_profile = self.profile.get_device_modes(
                dinput.GUID_Keyboard,
                DeviceType.Keyboard,
                DeviceType.to_string(DeviceType.Keyboard)
            )

            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.keyboard_tab_guid)
            device = gremlin.joystick_handling.device_info_from_guid(device_guid)
          
            widget = self.getRegisteredWidget(device_guid)
            if not widget:
                widget = gremlin.ui.keyboard_device.KeyboardDeviceTabWidget(
                    device_profile,
                    self.current_mode
                )
                self.registerWidget(device_guid, widget)
                gremlin.shared_state.device_type_map[dinput.GUID_Keyboard] = DeviceType.Keyboard
                #gremlin.shared_state.device_widget_map[dinput.GUID_Keyboard] = widget

            
            widget.data = (TabDeviceType.Keyboard, device_guid, index)
            self._keyboard_device_guid = device_guid
            
            
            self._add_tab(device_guid, TabDeviceType.Keyboard, override_name="Keyboard/Mouse")
            index+=1
            
            # =======================================================
            # Create MIDI tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.midi_tab_guid)
            device = gremlin.joystick_handling.device_info_from_guid(device_guid)
          
            midi_device_guid = device_guid
            if midi_enabled:
                device_profile = self.profile.get_device_modes(
                    gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid,
                    DeviceType.Midi,
                    DeviceType.to_string(DeviceType.Midi)
                )                
                widget = self.getRegisteredWidget(device_guid)
                if not widget:
                    widget = gremlin.ui.midi_device.MidiDeviceTabWidget(
                        device_profile,
                        self.current_mode
                    )

                
                    self.registerWidget(device_guid, widget)
                    self._midi_device_guid = device_guid
                    
                    gremlin.shared_state.device_type_map[gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid] = DeviceType.Midi
                    #gremlin.shared_state.device_widget_map[gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid] = widget
                
                widget.data = (TabDeviceType.Midi, device_guid, index)
                
                self._add_tab(device_guid,TabDeviceType.Midi)

                index+=1


            # =======================================================
            # Create OSC tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.osc_tab_guid)
            device = gremlin.joystick_handling.device_info_from_guid(device_guid)
           
            osc_device_guid = device_guid
            if osc_enabled:
                device_profile = self.profile.get_device_modes(
                    gremlin.ui.osc_device.OscDeviceTabWidget.device_guid,
                    DeviceType.Osc,
                    DeviceType.to_string(DeviceType.Osc)
                )                
                widget = self.getRegisteredWidget(device_guid)
                if not widget:
                    widget = gremlin.ui.osc_device.OscDeviceTabWidget(
                        device_profile,
                        self.current_mode
                    )
                
                

                    self.registerWidget(device_guid, widget)
                    self._osc_device_guid = device_guid
                    
                    gremlin.shared_state.device_type_map[device_guid] = DeviceType.Osc
                    #gremlin.shared_state.device_widget_map[gremlin.ui.osc_device.OscDeviceTabWidget.device_guid] = widget
                

                self._add_tab(device_guid,TabDeviceType.Osc)
                widget.data = (TabDeviceType.Osc, device_guid, index)
                
                index += 1

            # =======================================================
            # create Octavi IFR1 if it exists (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
            oo = gremlin.ui.octavi_device.OctaviInterface()
            if oo.deviceFound():
                guid = gremlin.shared_state.octavi_tab_guid
                device_guid = gremlin.util.normalize_guid(guid)
                device_type = DeviceType.OctaviIFR1
                device_profile = self.profile.get_device_modes(
                    gremlin.ui.octavi_device.OctaviDeviceTabWidget.device_guid,
                    device_type,
                    DeviceType.to_string(device_type)
                )         
                
                widget = self.getRegisteredWidget(device_guid)
                if not widget:
                    widget = gremlin.ui.octavi_device.OctaviDeviceTabWidget(
                        device_profile,
                        self.current_mode
                    )
                    self.registerWidget(device_guid, widget)
                    self._state_device_guid = device_guid

                widget.data = (TabDeviceType.OctaviIFR1, device_guid, index)
                self._add_tab(device_guid, TabDeviceType.OctaviIFR1)                
                gremlin.shared_state.device_type_map[device_guid] = device_type
                index += 1
                

            # =======================================================
            # create mode control tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
            guid = gremlin.shared_state.mode_tab_guid
            device_guid = gremlin.util.normalize_guid(guid)
            device = gremlin.joystick_handling.device_info_from_guid(device_guid)

            device_profile = self.profile.get_device_modes(
                    guid,
                    DeviceType.ModeControl,
                    DeviceType.to_string(DeviceType.ModeControl)
                )
            
            widget = self.getRegisteredWidget(device_guid)
            if not widget:
                widget = gremlin.ui.mode_device.ModeDeviceTabWidget(
                    device_profile,
                    self.current_mode
                )
                self.registerWidget(device_guid, widget)
                self._mode_device_guid = device_guid

            widget.data = (TabDeviceType.ModeControl, device_guid, index)
            self._add_tab(device_guid, TabDeviceType.ModeControl)
            index += 1

          

            
            # =======================================================
            # create state tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
            guid = gremlin.shared_state.state_tab_guid
            device_guid = gremlin.util.normalize_guid(guid)
            device = gremlin.joystick_handling.device_info_from_guid(device_guid)
            widget = self.getRegisteredWidget(device_guid)
            if not widget:
                widget = gremlin.ui.state_device.StateDeviceTabWidget(
                    self.profile,
                    self.current_mode
                )
                self.registerWidget(device_guid, widget)
                self._state_device_guid = device_guid

            widget.data = (TabDeviceType.State, device_guid, index)
            self._add_tab(device_guid, TabDeviceType.State)
            index += 1


           


            # =======================================================
            # Add profile configuration tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)

            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.settings_tab_guid)
            device = gremlin.joystick_handling.device_info_from_guid(device_guid)
            widget = self.getRegisteredWidget(device_guid)
            if not widget:
                widget = gremlin.ui.profile_settings.ProfileSettingsWidget(self.profile.settings)
                self.registerWidget(device_guid, widget)
                widget.changed.connect(lambda: self._create_tabs())
                
                self._settings_device_guid = device_guid


            widget.data = (TabDeviceType.Settings, device_guid, index)
            self._add_tab(device_guid, TabDeviceType.Settings)
            index += 1
                
            
            # =======================================================
            # Add a plugin custom modules tab
            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.plugins_tab_guid)
            device = gremlin.joystick_handling.device_info_from_guid(device_guid)
            widget = self.getRegisteredWidget(device_guid)
            if not widget:
                widget = gremlin.ui.user_plugin_management.ModuleManagementController(self.profile)
                self.mm = widget
                widget = self.mm.view
                self.registerWidget(device_guid, widget)
                
                self._plugins_device_guid = device_guid
            
            widget.data = (TabDeviceType.Plugins, device_guid, index)
            self._add_tab(device_guid, TabDeviceType.Plugins)
            index += 1


            # reorder the tabs based on user preferences if a tab order was previously saved

            config_tab_map = self.config.tab_list
            if config_tab_map:
                id_list = []
                ctm = {}
                for key, (id, name, a, b) in config_tab_map.items():
                    if id in id_list:
                        continue
                    device = gremlin.joystick_handling.device_info_from_guid(id)
                    if not device:
                        if verbose: syslog.info(f"TAB REORDER: skipping a device - ID not found in detected devices: [{id}]")  
                        continue
                    if device.disabled:
                        if verbose: syslog.info(f"TAB REORDER: skipping a device - device disabled - [{device.name}] ID [{id}]")  
                        continue

                    if device.is_virtual:
                        # skip devices if the VJOY device is not setup as input
                        input_enabled = self.profile.settings.vjoy_as_input.get(device.vjoy_id, False)
                        if not input_enabled:
                            continue

                    id_list.append(id)
                    ctm[key] = [id, name, a, b]

                config_tab_map = ctm

           
            if config_tab_map:
                current_tab_map = self._get_tab_map()

                remove_index = []
                if not midi_enabled or not osc_enabled:
                    for index, pairs in config_tab_map.items():
                        device_guid = pairs[0]
                        if not midi_enabled and device_guid == midi_device_guid:
                            remove_index.append(index)
                        if not osc_enabled and device_guid == osc_device_guid:
                            remove_index.append(index)

                if remove_index:
                    for index in remove_index:
                        del config_tab_map[index]
                    

                current_tab_guids = [device_guid for device_guid, _, _, _ in current_tab_map.values()]
                
                config_tab_guids = [device_guid for device_guid, _, _, _ in config_tab_map.values()] if config_tab_map else []
                missing_tab_guids = [device_guid for device_guid in current_tab_guids if device_guid not in config_tab_guids]
                missing_data = []

                # remove MIDI tab if not enabled
                if not midi_enabled and midi_device_guid in missing_tab_guids:
                    missing_tab_guids.remove(midi_device_guid)
                if not osc_enabled and osc_device_guid in missing_tab_guids:
                    missing_tab_guids.remove(osc_device_guid)

                reordered_data = list(config_tab_map.values())
                # list of (device_guid, device_name, data.tab_type, index)
                
                for device_guid in missing_tab_guids:
                    index = self._get_tab_index(device_guid)
                    tab_type = self._get_tab_type(index)
                    missing_data.append((device_guid, tab_type))
                    reordered_data.append((device_guid, device_name, tab_type, index))
                
                
                reordered_data.sort(key = lambda x: x[3])
                

                if verbose_detailed:
                    syslog.info("UI: Current device tabs ----------")
                    self._dump_tab_map(current_tab_map)
                    syslog.info("UI: Stored device tabs ----------")
                    self._dump_tab_map(config_tab_map)
                    if missing_tab_guids:
                        syslog.info(f"Found {len(missing_data)} devices from the saved ordered list:")
                    for device_guid, tab_type in missing_data:
                        device_name = self._get_device_name(device_guid)
                        syslog.info(f"\t{device_name} {device_guid}")

                    syslog.info("UI: Final reordered tabs ----------")
                    for device_guid, _, tab_type, index in reordered_data:
                        device_name = self._get_device_name(device_guid)
                        syslog.info(f"\t[{index}] {device_name} {device_guid} {tab_type}")

            
                # clear and rebuild the tabs in the new order
                self._reset_tab_data()
                for device_guid, device_name, tab_type, index in reordered_data:
                    device = self._get_device(device_guid)
                    tab_name = "Keyboard/Mouse" if device.device_type == DeviceType.Keyboard else device.name
                    self._add_tab(device_guid, tab_type, override_name= tab_name)

                self._reindex_tabs()

            # style the tabs by connection
            #self._update_tab_stylesheet()

            self._tab_map = self._get_tab_data_map()



            el = gremlin.event_handler.EventListener()
            el.tabs_loaded.emit()

            # select the tab that was last selected (if it exists)

            gremlin.shared_state.is_tab_loading = False
      
        except Exception as err:
            syslog.error(f"DEVICE TABS: (step 1) failed: {err}")
            tb_msg = traceback.format_exc()
            syslog.error(tb_msg)
            


        finally:
            # select last items 
            try:
                gremlin.shared_state.pop_input_selection(reset = True) # allow selections
                last_device_guid, last_input_type, last_input_id = config.get_last_input()

                device = gremlin.joystick_handling.device_info_from_guid(last_device_guid)
                if not device:
                    # does not exist anymore
                    last_input_id = None
                    last_input_type = None
                    last_device_guid = self.ui.devices.tabData(0).device_guid # pick first

                input_item = None
                if last_input_id:
                    # ensure the input still exists
                    input_item = self.profile.find_input(last_device_guid, last_input_id)

                if not input_item:
                    # not found
                    input_item = self.profile.first_input(last_device_guid)
                    if input_item:
                        last_input_id = input_item.input_id
                        last_input_type = input_item.input_type
                
                if verbose: syslog.info(f"SELECT TAB INDEX: {index}")
                index = self.getTabIndexForDevice(last_device_guid)
                if index is not None:
                    self.ui.devices.setCurrentIndex(index)
                    self._select_input(last_device_guid, last_input_type, last_input_id, force_switch=True)
                
                
            except Exception as err:
                syslog.error(f"CREATE DEVICE TABS (step 2): failed: {err}")
                tb_msg = traceback.format_exc()
                syslog.error(tb_msg)
                

            self.pop_highlighting()
            self._update_highlight_toolbar_enabled()

            if verbose: 
                syslog.info("Tab recreated:")
                for index in range(self.ui.devices.count()):
                    device_guid = self.ui.devices.tabData(index).device_guid
                    if device_guid:
                        device_name = self._get_device_name(device_guid)
                    else:
                        device_name = "(unknown)"
                    syslog.info(f"\t[{index}] {self.ui.devices.tabText(index)} {device_name}  {device_guid}")

            if verbose_detailed:
                syslog.info("CREATE TABS: complete")





    def get_ordered_device_guid_list(self, filter_tab_type : TabDeviceType = TabDeviceType.NotSet):
        ''' returns the list of device guids as directinput GUIDs

        :param: filter_tab_type = the type of tab device to filter for
        :returns: list of DINPUT GUID

        '''
        data = self._get_tab_map()
        device_guid_list = []
        for index in range(len(data)):
            (device_guid, device_name, tab_type, index) = data[index]
            if filter_tab_type == TabDeviceType.NotSet or tab_type == filter_tab_type:
                device_guid_list.append(gremlin.util.parse_guid(device_guid))

        return device_guid_list






    def _find_tab_data(self, search_widget_type : TabDeviceType):
        ''' gets tab data based on widget type'''
        tab_map = self._get_tab_map()
        data = []
        for device_guid, device_name, device_type, tab_index in tab_map.values():
            if device_type == search_widget_type:
                data.append((device_guid, device_name, device_type, tab_index))
        return data

    def _find_joystick_tab_data(self):
        ''' gets the joystick tab data '''
        return self._find_tab_data(TabDeviceType.Joystick)

    def _find_tab_data_guid(self, search_guid):
        ''' gets tab data based on the device guid '''
        if not isinstance(search_guid,str):
            search_guid = gremlin.util.normalize_guid(search_guid) # tab map stores the GUID as a string
        tab_map = self._get_tab_map()
        data = [(device_guid, device_name, device_type, tab_index) for device_guid, device_name, device_type, tab_index in tab_map.values() if device_guid == search_guid]
        if data:
            return data[0]

        return None, None, None, None

    def _get_tab_widget_guid(self, device_guid):
        ''' gets a tab by device guid '''
        return self.getRegisteredWidget(device_guid)



        # widgets = self._get_tab_widgets()
        # # widget data holds (tab_type, device_guid)
        # data = [widget for widget in widgets if widget.data[1] == device_guid]
        # if data:
        #     return data[0]
        # return None

    def _get_tab_index(self, device_guid):
        ''' gets the tab index for the given GUID '''
        device_guid = gremlin.util.normalize_guid(device_guid)
        return self.getRegisteredWidgetIndex(device_guid)
        # if not isinstance(device_guid, str):
        #     device_guid = gremlin.util.normalize_guid(device_guid)
        # if device_guid in self._tab_device_map:
        #     return self._tab_device_map[device_guid]
        # return None


    def _get_tab_widgets_by_type(self, tab_type : TabDeviceType):
        ''' gets widgets by the tab type '''
        widgets = self._get_tab_widgets()
        # widget data holds (tab_type, device_guid)
        data = [widget for widget in widgets if widget.data[0] == tab_type]
        if data:
            return data[0]
        return None

    def _get_tab_name_guid(self, device_guid):
        data = self._find_tab_data_guid(device_guid)
        _, device_name, _, _ = data
        return device_name


    def _get_tab_widgets(self):
        ''' returns the tab objects '''
        widgets = [self.ui.device_widget.widget(index) for index in range(self.ui.device_widget.count())]
        return widgets
        #return self._widget_device_index_map.values()
    

    def _select_last_tab(self):
        ''' restore the last selected tab '''
        # print (f"select last tab: {self.config.last_tab_guid}")
        device_guid, input_type, input_id = self.config.get_last_input()
        eh = gremlin.event_handler.EventListener()
        eh.select_input.emit(device_guid, input_type, input_id, False, True, False)

    @QtCore.Slot()
    def _ui_ready(self):
        ''' UI loop is about to start '''

        # update the UI widgets that listen to inputs to disable the ones not visible 
        device_guid, input_type, input_id = self.restore_input
        # syslog = logging.getLogger("system")
        verbose = self.config.verbose_mode_details
        
        if device_guid is None:
            # no default selected, pick the first tab
            device_guid = self.getFirstTabDeviceGuid()
            syslog.info("UI: no prior device selection found - selecting first device")
        if device_guid is not None:
            info = gremlin.joystick_handling.device_info_from_guid(device_guid)
            default_input_id = None
            default_input_type = None
            if info:
                if info.device_type == DeviceType.Joystick:
                    if info.axis_count:
                        default_input_id = 1
                        default_input_type = InputType.JoystickAxis
                    elif info.button_count:
                        default_input_id = 1
                        default_input_type = InputType.JoystickButton
                    elif info.hat_count:
                        default_input_id = 1
                        default_input_type = InputType.JoystickHat

            if input_type is None:
                input_type = default_input_type
                input_id = default_input_id
            if input_id is None:
                input_id = default_input_id
                
            # self._select_input(device_guid, input_type, input_id)
        if verbose:
            device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
            syslog.info(f"UI: startup selection: {device_name} {gremlin.input_types.InputType.to_string(input_type)} {input_id}") 
        
                    


        # enable highlighting
        self.pop_highlighting(True)

        # update status nar
        self._update_mode_status_bar()


    def _select_last_input(self):
        # if there is a last input - select that input as well
        device_guid, input_type, input_id = self.config.get_last_input()
        if input_type and input_id:
            eh = gremlin.event_handler.EventListener()
            eh.select_input.emit(device_guid, input_type, input_id, False, True, False)


    def _get_last_input(self, device_guid : str) -> tuple:
        ''' Gets the last input selection for the given device

        If there was no prior selection, the first input for the device is returned.
        If there is no first input because it's empty, return None.

        :param: device_guid id of the device to get as a string
        :returns: (input_type, Input_id)

        '''
        
        _, input_type, input_id = gremlin.config.Configuration().get_last_input(device_guid)
        if not input_type:
            # pick the first input for that tab
            widget = self._get_tab_widget_guid(device_guid)
            input_item: gremlin.base_profile.InputItem = self._get_input_item(device_guid, 0)
            if input_item:
                return (input_item.input_type, input_item.input_id)
        return (input_type, input_id)

    def _get_input_item(self, device_guid : str, index : int) -> gremlin.base_profile.InputItem:
        ''' get the input item at the specified index in the device - index is 0 based '''
        widget = self._get_tab_widget_guid(device_guid)
        if widget is None or not hasattr(widget,"input_item_list_model"):
            return None

        row_count = widget.input_item_list_model.rows()
        if row_count == 0 or index > row_count:
            return None
        return widget.input_item_list_model.data(index)
    
    
    def _get_input_items(self, device_guid : str) -> list[gremlin.base_profile.InputItem]:
        ''' gets the list of all input items for a given device '''
        widget = self._get_tab_widget_guid(device_guid)
        if widget is None or not hasattr(widget,"input_item_list_model"):
            return None

        row_count = widget.input_item_list_model.rows()
        return [widget.input_item_list_model.data(index) for index in range(row_count)]
    
    def _find_input_item(self, device_guid : str, input_type, input_id) -> gremlin.base_profile.InputItem:
        ''' find the input item matching the input id for a given device '''
        if not device_guid or input_id is None or input_type is None:
            # nothing to match
            return None
        
        widget = self._get_tab_widget_guid(device_guid)
        if widget is not None and hasattr(widget,"find_input"):
            return widget.find_input(device_guid, input_type, input_id)

        items = self._get_input_items(device_guid)
        if items:
            return next((item for item in items if item and item.input_id and item.input_id == input_id and item.input_type == input_type), None)
        return None
        

    def _select_input(self, device_guid, input_type : InputType = None, input_id = None, mode = None, force_update = False, force_switch = False, tab_changed = False):
        if gremlin.shared_state.is_input_selection_suspended:
            return # skip if disabled
        gremlin.util.pushCursor()
        el = gremlin.event_handler.EventListener()
        el.select_input.emit(device_guid, input_type, input_id, force_update, force_switch, tab_changed)
        gremlin.util.popCursor()


    def _config_changed_cb(self):
        self.refresh()

    def _config_filter_changed_cb(self, filter, value):
        match filter:
            case "input_viewer_disables_repeaters":
                if value:
                    gremlin.shared_state.push_repeater()
                else:
                    gremlin.shared_state.pop_repeater()
            case "show_input_axis":
                self.refresh()

    def _config_option_changed(self):
        self._update_highlight_toolbar_enabled()


    def _select_input_handler(self, device_guid : dinput.GUID, restore_input_type : gremlin.input_types.InputType = None, restore_input_id = None,  force_update : bool = False, force_switch = False, tab_changed = False):
        gremlin.util.InvokeUiMethod(self._select_input_handler_ui,
                                    device_guid,
                                    restore_input_type,
                                    restore_input_id,
                                    force_update,
                                    force_switch,
                                    tab_changed)

    def _select_input_handler_ui(self, device_guid : dinput.GUID, restore_input_type : gremlin.input_types.InputType = None, restore_input_id = None,  force_update : bool = False, force_switch = False, tab_changed = False):
        ''' Selects a specific input on the given tab
        The tab is changed if different from the current tab.

        :params:
        device_guid = the device ID as a string or a Dinput GUID
        input_type = InputType enum or none to auto determine
        input_id = id of the input, none to auto determine


        '''
        
        import gremlin.config
        import gremlin.event_handler
        import gremlin.ui.input_item
        import gremlin.util
        import gremlin.shared_state
        import gremlin.joystick_handling

        if self._change_input_lock.locked():
            return
        
        verbose = gremlin.config.Configuration().verbose_mode_inputs
        # verbose = True
        
        widget = None
        try:
        
            self._change_input_lock.acquire_lock()
            gremlin.util.pushCursor()

            
            if gremlin.shared_state.is_input_selection_suspended:
                return # skip if disabled


            el = gremlin.event_handler.EventListener()

            if not device_guid:
                # no device selected - ignore
                return

 
            # avoid spamming
            if not force_update and self._last_input_change_timestamp + self._input_delay > time.time():
                    # delay not occured yet
                    return
            
            self._last_input_change_timestamp = time.time()

            
            # syslog = logging.getLogger("system")
            input_id = restore_input_id
            input_type = restore_input_type
            
            switch_input = force_switch # true if inputs are switched or forcing refresh

            switch_enabled = self.is_highligthing_enabled
            if not force_switch and gremlin.util.compare_guid(gremlin.shared_state.current_tab_device_guid,device_guid) and not switch_enabled:
                if verbose:
                    syslog.info(f"SELECT INPUT: event: {device_guid} {self._get_device_name(device_guid)} disabled: highlight switch is disabled)")
                return


            #self._selection_locked = True

            if not isinstance(device_guid, str):
                device_guid = gremlin.util.normalize_guid(device_guid)


            # index of current device tab
            index = self.ui.devices.currentIndex()
            if index == -1:
                # no current index 
                return
            tabdata = self.ui.devices.tabData(index)
            if not tabdata:
                # no current data
                return
            

          
            current_device_guid = tabdata.device_guid
            current_input_type, current_input_id = self._get_last_input(current_device_guid)

            # get the device widget
            widget = self.getRegisteredWidget(device_guid)

            input_count = widget.inputCount
            input_widget_count = widget.inputWidgetCount
            if verbose: syslog.info(f"Device widget: input count: {input_count:,}  widget count: {input_widget_count}")

            if input_count and input_widget_count == 0:
                # widget not loaded, load it
                widget.refresh(emit = False)
                input_widget_count = widget.inputWidgetCount
                if verbose: syslog.info(f"Post refresh: Device widget: input count: {input_count:,}  widget count: {input_widget_count}")
            
            #device = gremlin.joystick_handling.device_info_from_guid(device_guid)
            has_inputs = gremlin.util.compare_guid(device_guid, (gremlin.shared_state.settings_tab_guid, gremlin.shared_state.plugins_tab_guid)) # settings and plugins tabs don't have inputs

            if verbose:
                syslog.info(f"SELECT INPUT: current input: {current_device_guid} {self._get_device_name(device_guid)} input: {InputType.to_display_name(current_input_type)} input ID: {current_input_id} current mode: {gremlin.shared_state.current_mode}")

            # make the content visible
            self.selectTabWidget(device_guid)

            has_containers = False

            # see if the request input is found
            input_item = self._find_input_item(device_guid, input_type, input_id)
            if input_item is None:
                # not found
                input_item = self._get_input_item(device_guid, 0)

            if input_item:
                input_type = input_item.input_type
                input_id = input_item.input_id
                has_containers = len(input_item.containers) > 0
                switch_input = not input_item.selected or not has_containers # switch inputs if the input is not currently selected
                
               

            if verbose:
                syslog.info(f"SELECT INPUT: new input: {device_guid} {self._get_device_name(device_guid)} input: {InputType.to_display_name(input_type)} input ID: {input_id}  current mode: {gremlin.shared_state.current_mode}")


            # guid of current device tab
            switch_tabs = False
            index = self._find_tab_index(device_guid)
            if not gremlin.util.compare_guid(current_device_guid, device_guid) or index is None: # device changed or not found
                # change tab if not on the correct device tab
                if verbose: syslog.info("Tab change requested")
                # validate the requested device exists (this could be because the device is disconnected for example)
                
                if index is None:
                    device = gremlin.joystick_handling.device_info_from_guid(device_guid)
                    if device.is_virtual:
                        # use the current tab if the VJOY device is not visible
                        last_device_guid, last_input_type, input_id = self.config.get_last_input(device_guid)
                        index = self._find_tab_index(device_guid)

                    else:
                        # not virtual
                        syslog.warning(f"SELECT INPUT: tab not found for device {gremlin.util.normalize_guid(device_guid)} - device does not exist - selecting default")
                        # change to the first
                        device : DeviceSummary = gremlin.joystick_handling.default_device()
                        if not device:
                            syslog.warning(f"SELECT INPUT: no default device to select found - aborting selection")
                            return
                        device_guid = device.device_guid
                        # get a default input for that device (first axis or first button)
                        if device.axis_count:
                            input_id = device.getAxisInputId(0)
                        elif device.button_count:
                            input_item = self._get_input_item(device_guid, 0)
                        else:
                            syslog.warning(f"SELECT INPUT: default device has no default input - aborting selection")
                            return

                        switch_input = True

                        index = self._find_tab_index(device_guid)
                        if index is None:
                            syslog.warning(f"SELECT INPUT: default device not found in device tabs: {str(device)} - aborting selection")
                            return


                        with QtCore.QSignalBlocker(self.ui.devices):
                            self.ui.devices.setCurrentIndex(index)
                            gremlin.shared_state.current_tab_device_guid = device_guid
                            

                        if verbose: syslog.info(f"Tab change complete: device {gremlin.util.normalize_guid(device_guid)}")
                        switch_tabs = True # we are switching tabs
                        switch_input = True # we are switching inputs


            if switch_tabs and not force_switch and not config.highlight_autoswitch:
                if verbose: syslog.info("SELECT INPUT: Tab change ignored: auto tab switching is disabled")
                return


            if input_id is None and has_inputs:
                # get the default item to select


                if verbose: syslog.info(f"SELECT INPUT: last input ID {input_id} not found - selecting default input ID")
                last_device_guid, last_input_type, input_id = self.config.get_last_input(device_guid)
                if verbose: syslog.info(f"SELECT INPUT: found {last_device_guid} {last_input_type} {input_id} ")
                if input_id is None:
                    input_item = self._get_input_item(device_guid, 0)
                    if input_item and self._last_input_item != input_item:
                        
                        
                        input_id = input_item.input_id
                        input_type = input_item.input_type
                        last_device_guid = device_guid
                        last_input_type = input_type
                        has_containers = len(input_item.containers) > 0
                        if verbose: syslog.info(f"SELECT INPUT: defaulting to first item on list {last_device_guid} {last_input_type} {input_id} ")

                        self._last_input_item = input_item
                switch_input = True # we are switching inputs
                        
            self._update_highlight_toolbar_enabled()

            if not switch_input:
                
                if widget and isinstance(widget, gremlin.ui.ui_common.QSplitTabWidget):
                    current_input_id = widget.getContentInputId()
                    if current_input_id:
                        switch_input = current_input_id != input_id
    

            if input_id is not None and switch_input:
                # select a particular input within a tab
                

                if widget:
                    if isinstance(widget, gremlin.ui.ui_common.QSplitTabWidget): # some tabs are not the standard widget - ignore those as they have no inputs
                        self.selectRegisteredWidget(device_guid)
                        if verbose: syslog.info(f"SELECT INPUT: select widget {input_type} {input_id}")
                        if tab_changed or not hasattr(widget, "input_item_list_view"):
                            widget.refresh(emit = False)
                        if not force_update:
                            force_update = current_input_id != input_id or current_input_type != current_input_id or gremlin.util.compare_guid(current_device_guid, device_guid)

                        emit = gremlin.shared_state.profile_loading #True #not has_containers
                        
                        widget.input_item_list_view.select_input(input_type, input_id, force_update = force_update, emit = emit)
                        index = widget.input_item_list_view.current_index
                        widget.input_item_list_view.redraw_index(index)
                        widget._select_item_cb(index)
                        #widget.refresh(False)

                        item : gremlin.base_profile.InputItem = widget.input_item_list_view.select_item(index, emit = False)
                        if verbose: assert item is not None, f"SELECT: sync issue: no selection"
                        item = widget.input_item_list_view.selected_item()
                        if verbose: assert item is not None, f"SELECT: sync issue: no selection"

                        #widget.select_item(index)
                        widget.setContentWidget(input_type, input_id)

                        # syslog.info("sync input requested")
                        el.sync_input.emit(item)

          
                    if verbose: syslog.info(f"SELECT INPUT: selected widget {input_type} {input_id}")

                # remember the last input id
                self._current_tab_input_id = input_id

            elif not has_inputs:
                # special tabs
                widget = self.getRegisteredWidget(device_guid)
                if widget:
                    self.selectRegisteredWidget(device_guid)
                    widget.refresh(emit = False)
                    




            # save settings as the last input
            el.input_selection_changed.emit(device_guid, input_type, input_id)
            el.update_input_state.emit(device_guid)

            self._last_selected_device_guid = device_guid
            self._last_selected_input_type = input_type
            self._last_selected_input_id = input_id

        except Exception as err:
            # something went south with the selection
            syslog.error("TabIndex generic unhandled error occured in _select_input_handler_ui():")
            syslog.error(f"{err}\n{traceback.format_exc()}")


            

        finally:
            
            # allow UI to refresh / update
            self.ensureTabLoaded()

            # validation check
            if verbose:
                

                # current tab
                position = self.ui.devices.currentIndex()
                tabdata = self.ui.devices.tabData(position)
                current_tab_device_guid = tabdata.device_guid
                assert gremlin.util.compare_guid(current_tab_device_guid,device_guid), "SELECT: sync issue: tab device mismatch"

    


                # current input 
                if widget and hasattr(widget,"input_item_list_view"):
                    lv : gremlin.ui.input_item.InputItemListView = widget.input_item_list_view
                    item : gremlin.base_profile.InputItem = lv.selected_item()
                    assert item is not None, f"SELECT: sync issue: no selection"
                    assert item.input_id == restore_input_id, f"SELECT: sync issue: input id mismatch: expected {restore_input_id} got {item.input_id}"
                
       
                    

            
            gremlin.util.popCursor()
            self._change_input_lock.release_lock()

    def ensureTabLoaded(self):
        ''' ensures a tab device UI is loaded/refreshed '''

        position = self.ui.devices.currentIndex()
        tabdata = self.ui.devices.tabData(position)
        current_tab_device_guid = tabdata.device_guid
        widget : gremlin.ui.ui_common.QSplitTabWidget = self.getRegisteredWidget(current_tab_device_guid)
        assert widget is not None, f"SELECT: sync issue: no widget found for the given device: {current_tab_device_guid}"
        widget.ensureLoaded()  


            
    @QtCore.Slot(object, object, object)
    def _input_changed_handler(self, device_guid, input_type, input_id):
        ''' called when an input changes '''
        current_device_guid, current_input_type, current_input_id = gremlin.shared_state.get_last_input_id()
        if current_device_guid != device_guid or current_input_type != input_type or current_input_id != input_id:
            # syslog = logging.getLogger("system")
            verbose = self.config.verbose_mode_device
            if verbose: 
                device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
                syslog.info(f"INPUT CHANGE: selected {device_name} {device_guid} {InputType.to_display_name(input_type)} input: {input_id}")
            gremlin.shared_state.set_last_input_id(device_guid, input_type, input_id)

    def _find_tab_index(self, search_guid : str):
        search_guid = gremlin.util.normalize_guid(search_guid)
        tab_map = self._get_tab_map()
        for device_guid, _, _, tab_index in tab_map.values():
            if device_guid == search_guid:
                return tab_index
        return None

    def _active_tab_guid(self):
        ''' gets the GUID of the device for the active tab '''
        return self._get_tab_guid(self.ui.devices.currentIndex())

    def _active_tab_index(self):
        ''' gets the index of the current tab '''
        return self.ui.devices.currentIndex()

    def _active_input_item(self) -> gremlin.base_profile.InputItem:
        ''' gets the current selected input item '''
        widget = self.getActiveTabWidget()
        if widget and hasattr(widget, "input_item_list_view"):
            item_index = widget.input_item_list_view.current_index
            data = widget.input_item_list_view.model.data(item_index)
            return data

        return None




    def _get_tab_guid(self, index : int) -> str:
        ''' gets the tab GUID from its index '''
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "data"):
            return widget.data[1] # id is index 1
        return None

    def _get_tab_input_type(self, index: int):
        ''' gets the input type of the tab '''
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "input_item_list_view"):
            item_index = widget.input_item_list_view.current_index
            data = widget.input_item_list_view.model.data(item_index)
            return data.device_type
        return None

    def _get_tab_input_id(self, index: int):
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "input_item_list_view"):
            item_index = widget.input_item_list_view.current_index
            data = widget.input_item_list_view.model.data(item_index)
            return data.input_id
        return None

    def _get_tab_input_data(self, index: int):
        ''' returns (input_type, input_id) for a given tab index '''
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "input_item_list_view"):
            item_index = widget.input_item_list_view.current_index
            data = widget.input_item_list_view.model.data(item_index)
            if data is not None:
                return (data.device_type, data.input_id)
        return (None, None)

    def _dump_tab_map(self, tab_map):
        log = syslog
        for index, (device_guid, device_name, device_class, tab_index) in tab_map.items():
            log.info(f"[{index}] Tab index: [{tab_index}] {device_name} {device_class} {device_guid}")

    def _refresh_tab(self):
        ''' refreshes the current device tab '''
        widget = self.getActiveTabWidget()
        if widget and hasattr(widget,"refresh"):
            widget.refresh()



    def _sort_tabs(self):
        ''' sorts device tabs by default order name '''

        # sorted list of item GUIDs
        guid_list = []
        tab_map = self._get_tab_map()
        if self.config.verbose:
            syslog.info("SORT: pre sort state:")
            self._dump_tab_map(tab_map)

        # add hardware joystick devices by their alphabetical name 
        joystick_devices = self._find_joystick_tab_data()
        joystick_devices.sort(key=lambda x: x[1].casefold())
        guid_list.extend(joystick_devices)

        

        # add the Keyboard, OSC and MIDI
        
        guid_list.append(self._find_tab_data_guid(gremlin.shared_state.keyboard_tab_guid))
        if self.config.midi_enabled:
            guid_list.append(self._find_tab_data_guid(gremlin.shared_state.midi_tab_guid))
        if self.config.osc_enabled:
            guid_list.append(self._find_tab_data_guid(gremlin.shared_state.osc_tab_guid))

        # add the input vjoy devices
        for device_guid in self._vjoy_input_device_guids:
            guid_list.append(self._find_tab_data_guid(device_guid))

        # # add the output vjoy
        # for device_guid in self._vjoy_output_device_guids:
        #     guid_list.append(self._find_tab_data_guid(device_guid))

        # add the settings tab
        guid_list.append(self._find_tab_data_guid(gremlin.shared_state.settings_tab_guid))

        # add the user plugin tab
        guid_list.append(self._find_tab_data_guid(gremlin.shared_state.plugins_tab_guid))


        # move the tabs to the correct location
        tab_data = [self.ui.devices.tabData(index) for index in range(self.ui.devices.count())]
        self._reset_tab_data()
        for index, (device_guid, device_name, device_type, tab_index) in enumerate(guid_list):
            data = tab_data[index]
            self._add_tab(device_guid, data.tab_type, index)

        tab_map = self._get_tab_map()
        if self.config.verbose:
            syslog.info("SORT: post result:")
            self._dump_tab_map(tab_map)


        self._select_last_tab()
        self._select_last_input()



    def _setup_icons(self):
        """Sets the icons of all QAction items."""
        # Menu actions
        from pathlib import Path

        folder = gremlin.shared_state.root_path
        gfx_folder = os.path.join(folder, "gfx")
        if not os.path.isdir(gfx_folder):
            # look for parent
            parent = Path(folder).parent
            gfx_folder = os.path.join(parent, "gfx")
            if not os.path.isdir(gfx_folder):
                raise gremlin.error.GremlinError(f"Unable to find icons: {folder}")
            
        normal_color = gremlin.ui.ui_common.Color.normalColor()        
        active_color = gremlin.ui.ui_common.Color.activeColor()
        is_dark = gremlin.shared_state.is_dark_theme    

        profile_icon = "gfx/dark_profile_open.svg" if is_dark else "gfx/profile_open.svg"

        icon = load_icon(profile_icon)
        #icon = self.load_icon("profile_open.svg"))
        self.ui.actionLoadProfile.setIcon(icon)

        prefix = "dark_" if is_dark else ""

        profile_new_icon = f"gfx/{prefix}profile_new.svg" 

        icon = load_icon(profile_new_icon)
        self.ui.actionNewProfile.setIcon(icon)

        profile_save_icon = f"gfx/{prefix}profile_save.svg" 
        icon = load_icon(profile_save_icon)
        self.ui.actionSaveProfile.setIcon(icon)

        profile_save_as_icon = f"gfx/{prefix}profile_save_as.svg" 
        icon = load_icon(profile_save_as_icon)
        self.ui.actionSaveProfileAs.setIcon(icon)


        device_information_icon = f"gfx/{prefix}device_information.svg"
        icon = load_icon(device_information_icon)
        self.ui.actionDeviceInformation.setIcon(icon)

        manage_module_icon = f"gfx/{prefix}manage_modules.svg"
        icon = load_icon(manage_module_icon)
        self.ui.actionManageCustomModules.setIcon(icon)

        manage_modes_icon = f"gfx/{prefix}manage_modes.svg"
        icon = load_icon(manage_modes_icon)
        self.ui.actionManageModes.setIcon(icon)

        input_repeater_icon = f"gfx/{prefix}input_repeater.svg"
        icon = load_icon(input_repeater_icon)
        self.ui.actionInputRepeater.setIcon(icon)


        # input_viewer_icon = load_icon("ei.adjust-alt")
        # icon = load_icon(input_viewer_icon)
        # self.ui.actionInputViewer.setIcon(icon)

        icon = load_icon(f"gfx/{prefix}logview.png")
        self.ui.actionLogDisplay.setIcon(icon)
        self.ui.actionLogEdit.setIcon(icon)

        options_icon = f"gfx/{prefix}options.svg"
        icon = load_icon(options_icon)
        self.ui.actionOptions.setIcon(icon)

        about_icon = f"gfx/{prefix}about.svg"
        icon = load_icon(about_icon)
        self.ui.actionAbout.setIcon(icon)

        # input actions

        input_icon = load_icon("ei.adjust-alt", qta_color=normal_color)
        input_on_icon = load_icon("ei.adjust-alt", qta_color=active_color)
        pixmap_off = input_icon.pixmap(24,24)
        pixmap_on = input_on_icon.pixmap(24,24)
        viewer_icon = QtGui.QIcon()
        viewer_icon.addPixmap(pixmap_off, QtGui.QIcon.Normal)
        viewer_icon.addPixmap(pixmap_on, QtGui.QIcon.Active, QtGui.QIcon.On)
        self.ui.actionInputViewer.setCheckable(True)
        self.ui.actionInputViewer.setIcon(viewer_icon)
        
        # Toolbar actions

        
        activate_icon = load_icon("fa5s.gamepad", qta_color=normal_color)
        activate_on_icon = load_icon("fa5s.gamepad", qta_color=active_color)
        pixmap_off = activate_icon.pixmap(24,24)
        pixmap_on = activate_on_icon.pixmap(24,24)
        activate_icon = QtGui.QIcon()
        activate_icon.addPixmap(pixmap_off, QtGui.QIcon.Normal)
        activate_icon.addPixmap(pixmap_on, QtGui.QIcon.Active, QtGui.QIcon.On)

        #self.ui.actionActivate.setCheckable(True)
        self.ui.actionActivate.setIcon(activate_icon)


        remote_icon = load_icon("mdi.remote", qta_color=normal_color)
        remote_on_icon = load_icon("mdi.remote", qta_color=active_color)
        pixmap_off = remote_icon.pixmap(24,24)
        pixmap_on = remote_on_icon.pixmap(24,24)

        remote_activate_icon = QtGui.QIcon()
        remote_activate_icon.addPixmap(pixmap_off, QtGui.QIcon.Normal)
        remote_activate_icon.addPixmap(pixmap_on, QtGui.QIcon.Active, QtGui.QIcon.On)
        
        #self.ui.actionToggleRemotecontrol.setCheckable(True)
        self.ui.actionToggleRemoteControl.setIcon(remote_activate_icon)
        


        
        self.ui.actionOpen.setIcon(load_icon(profile_icon))

        
        self.ui.actionSave.setIcon(load_icon("fa5s.save", qta_color=normal_color))


    # +---------------------------------------------------------------
    # | Signal handlers
    # +---------------------------------------------------------------

    def _device_change_cb(self):
        gremlin.util.InvokeUiMethod(self._device_change_ui) # ensure the update is on the UI thread

    def _device_change_ui(self):
        """Handles addition and removal of joystick devices."""

        if not gremlin.joystick_handling.joystick_initialized():
            # not initialized yet
            return
        

        # Update device tabs
        gremlin.util.pushCursor() # long running op

        # record the device change
        self._device_change_queue +=1
        #print (f"device change detected {self._device_change_queue}")
        

        if not self.device_change_locked:

            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_device
            verbose_detailed = config.verbose_mode_details


            self.device_change_locked = True

            # force a re-read of DINPUT data
            syslog.warning("DILL: Device change reported by DINPUT - updating enumeration data:")
            dinput.DILL.reset()


            while self._device_change_queue > 0:

                try:
                    # syslog =syslog
                    if verbose:
                        syslog.info(f"Device change begin")

                    # list which device is different
                    old_devices = [(device.device_guid, device.name) for device in self._active_devices]
                    detected_devices = gremlin.joystick_handling.joystick_devices()
                    new_devices = [(device.device_guid, device.name) for device in detected_devices]
                    added_devices = [item for item in new_devices if not item in old_devices]
                    removed_devices = [item for item in old_devices if not item in new_devices]
                    if verbose:
                        if added_devices:
                            syslog.info("\tDevice added detected:")
                            for device_guid, device_name in added_devices:
                                syslog.info(f"\t\t{device_name} {device_guid}")
                        if removed_devices:
                            syslog.info("\tDevice removed detected:")
                            for device_guid, device_name in removed_devices:
                                syslog.info(f"\t\t{device_name} {device_guid}")
                                if gremlin.shared_state.current_tab_device_guid == gremlin.util.normalize_guid(device_guid):
                                    # select a different tab
                                    self.unregisterWidget(device_guid)
                                    gremlin.shared_state.current_tab_device_guid = None
                                    #self._current_tab_widget = None

                    # recreate the tabs
                    self.setTabsDirty()

                    # Stop Gremlin execution

                    self.ui.actionActivate.setChecked(False)
                    restart = self.runner.is_running()
                    if restart:
                        syslog.info(f"Profile restart due to device change")
                    self.activate(restart)
                finally:

                    if verbose_detailed:
                        syslog.info(f"Device change end")
                    self.device_change_locked = False

                    # # display a message
                    # if not gremlin.shared_state.is_running:
                    #     gremlin.util.pushCursorLevel()
                    #     gremlin.ui.ui_common.MessageBox("Device change detected","A device change was detected and you may need to reselect a device/input.")
                    #     gremlin.util.popCursorLevel()
                    

                    self._create_tabs()

                # mark items processed
                self._device_change_queue = 0

        gremlin.util.popCursor()


    @QtCore.Slot()
    def _device_input_changed_cb(self, device_guid, input_type, input_id):
        ''' called when device input changed '''
        el = gremlin.event_handler.EventListener()
        el.input_selection_changed.emit(device_guid, input_type, input_id)


    def _tab_moved_cb(self, tab_from, tab_to):
        ''' occurs when a tab is moved '''
        # persist tab order
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: syslog.info(f"UI: tab move detected {tab_from} {tab_to}")
        # rebuild the tab order
        self._reindex_tabs()
        # update new order
        self.config.tab_list = self._get_tab_map()
        index = self.ui.devices.currentIndex()
        device_guid = self.ui.devices.tabData(index).device_guid
        _, restore_input_type, restore_input_id = self.config.get_last_input(device_guid)
        self._select_input(device_guid = device_guid, input_type = restore_input_type, input_id = restore_input_id, force_update =True, force_switch=True)




    def _edit_mode_selector_changed(self, new_mode):
        """Updates the current mode to the provided one.

        :param new_mode the name of the new current mode
        """

        # refresh the modes
        eh = gremlin.event_handler.EventHandler()
        eh.change_mode(new_mode, force_update = True)


    def _get_process_mode(self, process_path):
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_process
        if process_path in self._process_runtime_map:
            mode = self._process_runtime_map[process_path]
            if verbose: syslog.info(f"PROC MODE: using last mode [{mode}] for process {process_path}")
        else:
            mode = self.profile.get_last_runtime_mode()
            if verbose: syslog.info(f"PROC MODE: using last saved profile mode mode [{mode}]")
        return mode
    
    def _process_changed_cb(self, new_process_path : str):
        gremlin.util.InvokeUiMethod(self._process_changed_cb_ui, new_process_path) # ensure on UI thread

    def _process_changed_cb_ui(self, new_process_path : str):
        """Handles changes in the active windows process focus

        If the active process has a known associated profile it is
        loaded and activated. If none exists and the user has not
        enabled the option to keep the last profile active, the current
        profile is disabled,

        :param path the path to the currently active process executable
        """

        if self._process_change_in_progress:
            return
        
        self._process_change_in_progress = True

        config = gremlin.config.Configuration()

        verbose = config.verbose_mode_process
        # syslog = logging.getLogger("system")

        if not self.current_process_path:
            self.current_process_path = new_process_path

        #  get auto load options
        option_auto_load = config.autoload_profiles # if true, change the profile if a process is mapped to one, do not activate unless gremlin was already activated
        option_auto_load_on_focus = config.activate_on_process_focus  # if true, also activate the mapped profile if not activated
        process_base = os.path.basename(new_process_path)


        option_keep_focus = config.keep_profile_active_on_focus_loss # if true, do not deactivate the profile on gremlinEx focus loss
        option_reset_mode_on_process_activate = config.reset_mode_on_process_activate # if true, reset the profile to the default start mode on process focus
        option_restore_mode = config.restore_profile_mode_on_start  # if true, restore last used profile mode on process focus (overrides the reset to default mode)


        if verbose:
            syslog.info("="*50)
            syslog.info(f"PROC: Process change detected: new process: >>>>>> [{process_base}] <<<<<<<")
            syslog.info(f"\t autoload: [{option_auto_load}]")
            syslog.info(f"\t autoload on focus: [{option_auto_load}]")
            syslog.info(f"\t keep focus: [{option_keep_focus}]")
            syslog.info(f"\t reset to default mode on process activate: [{option_reset_mode_on_process_activate}]")
            syslog.info(f"\t restore mode on profile start: [{option_restore_mode}]")

        try:

            if not option_auto_load or not option_auto_load_on_focus:
                # skip if we are not auto starting or auto loading profiles
                if verbose: syslog.info(f"PROC: Process change detected [{process_base}]: ignoring because auto-load options are disabled")    
                return



            eh = gremlin.event_handler.EventHandler()

            current_profile_path = self.profile.profile_file
        
            is_running = gremlin.shared_state.is_running # true if gremlin is running at process change
            if is_running :
                current_profile_save_mode = gremlin.shared_state.current_mode
            else:
                current_profile_save_mode = None

            # see if we have a mapping entry for this executable
            profile_item = self._profile_map.get_map(new_process_path)

            new_profile_path = profile_item.profile if profile_item else None

            if not current_profile_path or not os.path.isfile(current_profile_path):
                syslog.error("PROC: current profile is not saved - auto process start is unable to function")
                gremlin.ui.ui_common.MessageBox(prompt = f"Current profile  [{current_profile_path}] is not saved or the XML could not be found.  Process auto-start disabled.")
                return
            
            current_profile_base = os.path.basename(current_profile_path)
            
            if not new_profile_path:
                # no profile was found for the new process that received focus
                if not option_keep_focus:
                    # keep focus is off so we disable the profile
                    if verbose: syslog.info(f"PROC: process change: unmapped process [{process_base}] - keep focus is disabled - deactivate profile")
                    self.activate(False) # this saves the current profile runtime mode
                    self.ui.actionActivate.setChecked(False) # this turns "on" the run icon
                    # done
                    return
                if verbose: syslog.info(f"PROC: process change: unmapped process [{process_base}] - ignoring process change")
                return
                
            
            if not os.path.isfile(new_profile_path):
                syslog.error(f"PROC: process [{new_process_path}] profile file [{new_profile_path}] not found - ignoring process change")
                #gremlin.ui.ui_common.MessageBox(prompt = f"New profile [{new_profile_path}] profile XML could not be found.  Process auto-start disabled.")
                return
            

            new_profile_base = os.path.basename(new_profile_path)
            
            if verbose:
                    syslog.info(f"PROC: found profile map [{new_profile_base}] for process {process_base} - current profile: [{current_profile_base}]  runtime mode: [{gremlin.shared_state.runtime_mode}]")


            # profile entry found - see if we need to change profiles
            if not current_profile_path or not os.path.isfile(current_profile_path):
                syslog.error("PROC: Profile does not exist or is not saved.  Ignoring process activation as this feature requires the current profile to be saved.")
                return
            
        
            eh = gremlin.event_handler.EventHandler()
            restore_mode = None # derived profile mode to change to
            mode_changed = False # true if a mode change occured

            if not compare_path(current_profile_path, new_profile_path):
                # current profile and new profile are different - swap to the new profile
                
                # deactivate any current profile if active
                if verbose:
                    current_base_name = os.path.basename(current_profile_path)
                    syslog.info(f"PROC: process change: deactivate current profile: [{current_base_name}] - saving last used mode: [{gremlin.shared_state.runtime_mode}]")

                self.activate(False) # this saves the current profile runtime mode
                self.ui.actionActivate.setChecked(False) # this turns "on" the run icon

                # remember the last used mode for the profile before we change to the new - only do this if we are in runtime
                if current_profile_save_mode:
                    if verbose: syslog.info(f"\tSave last used mode: {current_profile_save_mode} for profile [{current_base_name}]")
                    self._runtime_mode_map[current_profile_path] = current_profile_save_mode
                    if self.current_process_path:
                        if verbose: 
                            base_process_name = os.path.basename(self.current_process_path)
                            syslog.info(f"\tAssociate last process [{base_process_name}] with mode [{current_profile_save_mode}]")
                        self._process_runtime_map[self.current_process_path] = current_profile_save_mode
                else:
                    if verbose: syslog.info(f"\tSave last used mode: no active mode found for profile [{current_base_name}]")

                self._active_process_path = new_process_path

                # change profile
                if verbose: syslog.info(f"PROC: process change: switch profile [{current_base_name}] ->  [{new_profile_base}]")
                
                # load the new profile
                self._do_load_profile(new_profile_path)

                loaded_profile = gremlin.shared_state.current_profile
                self.profile = loaded_profile

                if verbose: syslog.info(f"PROC: process change: loaded profile [{new_profile_base}]")

                if not is_running:
                    # gremlin was not running at the time of the process change - see if we should auto-activate the profile based on the auto activate option
                    if not option_auto_load_on_focus:
                        # activation is not requested - load only,  we're done
                        if verbose: syslog.info(f"PROC: Profile loaded, activation is not requested and GremlinEx wasn't running at process change.  Process change completed.")
                        return

                # activate the new profile
                if verbose: syslog.info(f"PROC: Activate profile [{new_profile_base}]")
                self.ui.actionActivate.setChecked(True)
                self.activate(True) # this will also restore the profile runtime mode based on current options
                

                if verbose: syslog.info(f"PROC: Profile [{new_profile_base}] activated")

                # update flag if a mode should be restored
                option_restore_mode = option_restore_mode or loaded_profile.get_restore_mode()

                self._profile_auto_activated = True # remember the profile was auto activated by virtue of a process change

                restore_mode = loaded_profile.get_restore_mode()

                # figure out which mode to restore mode for the new profile
                if verbose:  syslog.info(f"PROC: profile restore mode flag: [{option_restore_mode}]")

                current_mode = gremlin.shared_state.current_mode # current mode of the loaded profile

                if verbose: syslog.info(f"PROC: profile load mode: {current_mode}  derived mode to restore: [{restore_mode}]")

                
                if option_reset_mode_on_process_activate:
                    # restore only the profile default mode
                    restore_mode = loaded_profile.get_default_mode()
                    if verbose: syslog.info(f"PROC: Selected profile default mode [{restore_mode}] from profile mode dialog")
                elif option_restore_mode:
                    # restore to the mapped profile default mode defined in mappings
                    restore_mode = self._get_process_mode(new_process_path)
                    if verbose and restore_mode: syslog.info(f"PROC: Selected profile default mode [{restore_mode}] from runtime memory")
                    if not restore_mode:
                        restore_mode = gremlin.shared_state.current_profile.get_restore_mode() # saved JSON mode
                        if verbose and restore_mode: syslog.info(f"PROC: Selected profile default mode [{restore_mode}] from profile mode dialog")
                    if not restore_mode:
                        restore_mode = gremlin.shared_state.current_profile.get_default_mode()
                        if verbose: syslog.info(f"PROC: Selected profile default mode [{restore_mode}] from profile mode dialog as a fallback")

                # a mapping profile was found - new profile was loaded if needed - see if we need to change the mode
                if restore_mode is not None:
                    if restore_mode != current_mode:
                        if not restore_mode in loaded_profile.get_modes():
                            syslog.error(f"PROC: Unable to find mode [{restore_mode}] in profile - defaulting to default mode dialog startup mode")
                            restore_mode = loaded_profile.get_default_mode()

                        
                        if verbose: syslog.info(f"PROC: request mode change to [{restore_mode}]")
                        eh.change_mode(restore_mode, force_update = True) # set the selected mode - note that this may fail if mode locking is enabled
                        mode_changed = True

                # done

            elif option_auto_load_on_focus and not is_running:
                # re-activate the profile if not activated 
                if verbose: syslog.info(f"PROC: profile auto-focus ON: profile not activated, auto-activating profile [{new_profile_base}] ")
                self.ui.actionActivate.setChecked(True)
                self.activate(True)
                self._profile_auto_activated = True


            
            if not mode_changed:
                # if TTS is enabled and the process changed, issue a TTS message when the mode was not changed so we hear there was a change recorded in focus
                eh.TTSNotify(f"Process focus mode {restore_mode}")


            # remember the last process that received focus        
            self.current_process_path = new_process_path
        finally:
            if verbose: 
                if gremlin.shared_state.current_profile.profile_file:
                    base_profile = os.path.basename(gremlin.shared_state.current_profile.profile_file)
                else:
                    base_profile= "Not Saved"
                syslog.info(f"PROC: END Process change detected: process: >>>>>> [{process_base}] <<<<<<<  final profile: [{base_profile}] mode: [{gremlin.shared_state.current_mode}]")

            self._process_change_in_progress = False

    def _tray_icon_activated_cb(self, reason):
        """Callback triggered by clicking on the system tray icon.

        :param reason the type of click performed on the icon
        """
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.setHidden(not self.isHidden())


    def _update_status_bar_active(self, is_active):
        import gremlin.input_devices
        self._is_active = is_active
        self._update_status_bar(gremlin.input_devices.remote_state.to_state_event())

    def _remote_control_changed(self, enabled : bool):
        gremlin.util.InvokeUiMethod(self._remote_control_changed_ui, enabled)
    
    def _remote_control_changed_ui(self, enabled : bool):
        ''' called when remote control state changes '''
        with QtCore.QSignalBlocker(self.ui.actionToggleRemoteControl):
            self.ui.actionToggleRemoteControl.setChecked(enabled)

    def _update_status_bar(self, event = None):
        # updates the status bar


        """Updates the status bar with the current state of the system.

        :param is_active True if the system is active, False otherwise
        """
        Color = gremlin.ui.ui_common.Color
        try:
            if self._is_active:
                text_active = f"<font color=\"{Color.activeColor()}\">Active</font>"
            else:
                text_active = f"<font color=\"{Color.inactiveColor()}\">Paused</font>"
            if self.ui.actionActivate.isChecked():
                text_running = f"Running and {text_active}"
            else:
                text_running = "Not Running"

            # remote control status
            if not event:
                event = gremlin.input_devices.remote_state.to_state_event()
                
            if event.is_local:
                local_msg = f"<font color=\"{Color.activeColor()}\">Active</font>"
            else:
                local_msg = f"<font color=\"{Color.inactiveColor()}\">Disabled</font>"
            if event.is_remote:
                remote_msg = f"<font color=\"{Color.activeColor()}\">Active</font>"
            else:
                remote_msg = f"<font color=\"{Color.inactiveColor()}\">Disabled</font>"

            self.status_bar_is_active_widget.setText(f"<b>Status:</b> {text_running} <b>Local Control</b> {local_msg} <b>Broadcast:</b> {remote_msg}")
            self._update_mode_status_bar()

        except Exception as err:
            log_sys_error(f"Unable to update status bar event: {event}")
            syslog.error(f"{err}\n{traceback.format_exc()}")


    @QtCore.Slot()
    def _update_mode_change(self, new_mode):
        self._update_ui_mode(new_mode)
        self._update_mode_status_bar()
    
    def _update_mode_status_bar(self):
        gremlin.util.InvokeUiMethod(self._update_mode_status_bar_ui) # ensure on UI thread
    
    def _update_mode_status_bar_ui(self):
        ''' updates the mode status bar with current runtime and edit modes '''
        try:

            verbose = gremlin.config.Configuration().verbose
            is_running = gremlin.shared_state.is_running
            runtime_mode = gremlin.shared_state.runtime_mode

            # syslog = logging.getLogger("system")


            edit_mode = gremlin.shared_state.edit_mode
            if not edit_mode:
                # get it from the mode drop down
                edit_mode = self.mode_selector.currentMode()


            
            if not is_running:
                msg = f" <b>Edit Mode:</b> {edit_mode if edit_mode else "n/a"}"
                if self._status_bar_last_edit_mode != edit_mode:
                    if verbose: syslog.info(f"Mode: New edit mode: [{edit_mode}] (last mode [{self._status_bar_last_edit_mode}])")
                    self._status_bar_last_edit_mode = edit_mode

            else:
                msg = f"<b>Runtime Mode:</b> {runtime_mode if runtime_mode else "n/a"}"
                if self._status_bar_last_runtime_mode != runtime_mode:
                    if verbose: syslog.info(f"CHANGE MODE: To: [{runtime_mode}] (from [{self._status_bar_last_runtime_mode}])")
                    self._status_bar_last_runtime_mode = runtime_mode



            self.status_bar_mode_widget.setText(msg)
            if self.config.mode_change_message:
                toast_msg = f"Runtime Mode: {runtime_mode if runtime_mode else "n/a"} Edit mode: {edit_mode if edit_mode else "n/a"}"
                if self._last_toast_message is None or self._last_toast_message != toast_msg:
                    self.ui.tray_icon.showMessage(toast_msg,"",QtWidgets.QSystemTrayIcon.MessageIcon.NoIcon,250)
                    self._last_toast_message = toast_msg
        except Exception as err:
            syslog.error(f"Unable to update status bar mode:")
            syslog.error(f"{err}\n{traceback.format_exc()}")



    def _update_ui_mode(self, new_mode):
        """ called when the profile mode changes

        :param mode the now current mode
        """

        update = True
        is_running = gremlin.shared_state.is_running
        if is_running:
            update = self.config.runtime_ui_update

        if update:
            gremlin.util.pushCursor()
            with QtCore.QSignalBlocker(self.mode_selector):
                for tab in self._get_tab_widgets():
                    if hasattr(tab,"set_mode"):
                        tab.set_mode(new_mode)
                # select the last input after mode change
                # self._select_last_input()

            self._update_mode_status_bar()
            gremlin.util.popCursor()

    @QtCore.Slot(bool)
    def _kb_suspend_cb(self, suspend):
        el = gremlin.event_handler.EventListener()
        if suspend:
            el.keyboard_event.disconnect(self._kb_event_cb)
            # syslog.info("Suspend keyboard events")
        else:
            el.keyboard_event.connect(self._kb_event_cb)
            # syslog.info("Enable keyboard events")

    @QtCore.Slot(object)
    def _kb_event_cb(self, event):
        ''' listen for keyboard modifiers and keyboard events at runtime '''

        key = gremlin.keyboard.KeyMap.from_event(event)

        # ignore if we're running
        if key is None or self.runner.is_running() or gremlin.shared_state.ui_keyinput_suspended():
            return

        if key.lookup_name == "f5":
            # activate mode on F5
            if not self.config.is_debug and self.config.start_on_f5 and not gremlin.shared_state.ui_keyinput_suspended():
               self.ui.actionActivate.trigger()

    @property
    def input_axis_override(self):
        ''' true if temporary override of monitoring axis is enabled '''
        return self._temp_input_axis_override


    @property
    def input_axis_only_override(self):
        ''' true if temporary override of monitoring exclusive axis is enabled '''
        return self._temp_input_axis_only_override

    # +---------------------------------------------------------------
    # | Utilities
    # +---------------------------------------------------------------

    def apply_user_settings(self, ignore_minimize=False, auto_start = True):
        gremlin.util.InvokeUiMethod(self._apply_user_settings_ui, ignore_minimize, auto_start) # run on UI thread

    def _apply_user_settings_ui(self, ignore_minimize=False, auto_start = True):
        ''' Configures the program based on user settings. UI thread '''

        

        # gamepad count
        gremlin.gamepad_handling.gamepad_reset()

        self._set_joystick_input_highlighting(self.config.highlight_enabled)
        self._set_joystick_input_axis_highlighting(self.config.highlight_input_axis)
        self._set_joystick_input_buttons_highlighting(self.config.highlight_input_buttons)
        if not ignore_minimize and self.config.start_minimized:
            self.setHidden(self.config.start_minimized)
   
        if auto_start:
            config = gremlin.config.Configuration()
            if config.activate_on_launch:
                syslog.info("autostart requested")
                thread = threading.Thread(target = self._auto_start_runner)
                thread.name = "autostart"
                thread.start()
                
    
    def _auto_start_runner(self):
        while gremlin.shared_state.ui is None or not gremlin.shared_state.ui.initialized:
            syslog.info("autostart waiting to start...")
            time.sleep(0.1)
            if gremlin.shared_state.terminating:
                # app is terminating
                return
            
        syslog.info("autostart starting")

        gremlin.util.InvokeUiMethod(self._auto_start_activate_ui)

        syslog.info("autostart completed")

    def _auto_start_activate_ui(self):
        ''' auto activate on UI thread'''        
        self.ui.actionActivate.setChecked(True)
        self.activate(True)



    def _create_cheatsheet(self):
        ''' Creates a profile cheatsheet  '''

        import gremlin.ui.ui_common
        import gremlin.ui.dialogs
        
        # gremlin.ui.ui_common.MessageBox(prompt="This feature is not currently available.")
        # return # disable in this version

        dialog = gremlin.ui.dialogs.CreateReportDialog(parent = self)
        dialog.exec()


    def _view_input_map(self):
        ''' display input map dialog '''
        import gremlin.cheatsheet
        import gremlin.util
        dialog = gremlin.cheatsheet.ViewInput(parent = self)
        dialog.setMinimumHeight(600)
        gremlin.util.centerDialog(dialog)
        dialog.show()

    def _create_load_profile_function(self, fname):
        """Creates a callback to load a specific profile.

        :param fname path to the profile to load
        :return function which will load the specified profile
        """
        return lambda: self._load_recent_profile(fname)


    @property
    def profile(self):
        return gremlin.shared_state.current_profile

    @profile.setter
    def profile(self, value):
        current_profile = gremlin.shared_state.current_profile
        if current_profile and current_profile != value:
            eh = gremlin.event_handler.EventListener()
            eh.profile_unload.emit()

        gremlin.shared_state.current_profile = value

    def _do_load_profile(self, source_xml : str, as_new_profile = False) -> bool | tuple:
        self._profile_load_stack = []
        return self._do_load_profile_internal(source_xml, as_new_profile)

    def _do_load_profile_internal(self, source_xml : str, as_new_profile = False) -> bool | tuple:
        """Load the profile with the given filename.

        :param source_xml: the name of the profile file to load
        :param as_new_profile: if set, loads the new profile as an unsaved profile

        """
        # Disable the program if it is running when we're loading a
        # new profile

                    
        # trap recursive call
        if self._profile_load_stack:
            self._profile_load_stack.append(source_xml)
            return
        
        try:

            gremlin.shared_state.profile_loading = True

            self._profile_load_stack.append(source_xml)
            gremlin.shared_state.import_prompt_stack = 0 # reset prompt count for import remap (in profile_graph)
            
            

            pushCursor()
            eh = gremlin.event_handler.EventHandler()
            el = gremlin.event_handler.EventListener()

            last_edit_mode = gremlin.config.Configuration().get_profile_last_edit_mode()


            # clear any old data
            self._reset_tab_data()
            self.clearWidgets()

            # reset execution context
            ec = gremlin.execution_graph.ExecutionContext()
            ec.reset(no_rebuild = True)

            self.ui.actionActivate.setChecked(False)
            self.activate(False)
                

            if gremlin.shared_state.current_profile:
                el.profile_unload.emit() # fire unload start 
                current_profile = gremlin.shared_state.current_profile
                current_profile.unload()
                gremlin.shared_state.current_profile = None
                el.profile_unloaded.emit() # tell the UI we're about to load a new profile
            el.push_input_selection() # suspend input selection            

            while self._profile_load_stack:
                source_xml = self._profile_load_stack[0]

                import_data = gremlin.base_profile.ProfileImportData()
                import_data.used_ids.clear()




                # Attempt to load the new profile
                try:

                    new_profile = gremlin.base_profile.Profile()

                    if not os.path.isfile(source_xml):
                        gremlin.ui.ui_common.MessageBox(title = "Profile Error", prompt = f"Specified file not found.")
                        return False
                    if os.path.getsize(source_xml) == 0:
                        gremlin.ui.ui_common.MessageBox(title = "Profile Error", prompt = f"Specified file is empty.")
                        return False

                
                    gremlin.shared_state.current_profile = new_profile
                    profile_updated = new_profile.from_xml(source_xml)

                    profile_folder = os.path.dirname(source_xml)
                    if profile_folder not in sys.path:
                        sys.path = list(self._base_path)
                        sys.path.insert(0, profile_folder)

                    self._sanitize_profile(new_profile)


                    # Save the profile at this point if it was converted from a prior
                    # profile version, as otherwise the change detection logic will
                    # trip over insignificant input item additions.
                    if profile_updated:
                        new_profile.to_xml(source_xml)

                        # reload the profile
                        syslog.info("Profile: reload due to conversion.")
                        new_profile = gremlin.base_profile.Profile()
                        gremlin.shared_state.current_profile = new_profile
                        new_profile.from_xml(source_xml)




                    
                    # next file

                    if source_xml in self._profile_load_temporary_files:
                        # clean up the temporary file once loaded
                        os.unlink(source_xml)
                        new_profile.setProfileFile(None)

                    self._profile_load_stack.pop(0)
                    syslog.info("Profile: parse completed.")


                except (KeyError, TypeError) as err:
                    # An error occurred while parsing an existing profile,
                    # creating an empty profile instead
                    syslog.exception(f"Invalid profile content:")
                    syslog.error(f"{err}\n{traceback.format_exc()}")
                    self.new_profile()
                    self._profile_load_stack.clear()

                except gremlin.error.ProfileError as err:
                    # Parsing the profile went wrong, stop loading and start with an
                    # empty profile
                    cfg = gremlin.config.Configuration()
                    cfg.last_profile = None
                    self.new_profile()
                    gremlin.util.display_error(f"Failed to load the profile {source_xml} due to:\n\n{err}")
                    syslog.error(f"{err}\n{traceback.format_exc()}")
                    self._profile_load_stack.clear()

                except Exception as err:
                    syslog.error("Profile load error (generic):")
                    syslog.error(traceback.format_exc())
                    gremlin.util.display_error(f"Failed to load the profile {source_xml} (see log for details)")
                    syslog.error(f"{err}\n{traceback.format_exc()}")
                    self._profile_load_stack.clear()


            if not last_edit_mode:
                # pick the top mode if nothing was saved in the configuration
                last_edit_mode = self.profile.get_root_mode()
                gremlin.config.Configuration().set_profile_last_edit_mode(last_edit_mode)

            if as_new_profile:
                # set as new unsaved profile
                new_profile.setProfileFile(None)
            
            modes = new_profile.get_modes()
            if last_edit_mode is None:
                last_edit_mode = modes[0]

            if not last_edit_mode in modes:
                # no longer in the current mode list
                last_edit_mode = new_profile.get_default_mode()

            # Make the first root node the default active mode
            self.mode_selector.populate_selector(new_profile, last_edit_mode, emit = False)

            gremlin.shared_state.edit_mode = last_edit_mode
            gremlin.shared_state.runtime_mode = new_profile.get_default_start_mode()                


            # indicate profile was loaded
            new_profile.setLoaded(True)            

            # update the hash value
            self._profile_hash = new_profile.getMappingHash()

            # self._create_tabs()

            

            # select the new mode
            eh.change_mode(last_edit_mode, force_update = True)
            
            el.profile_loaded.emit()

            # ask the UI to update input curve icons
            el.update_input_icons.emit()

            # update the status bar
            self._update_mode_status_bar()
            self._update_window_title()

            el.pop_input_selection(True) # restore input selection and reset
            #self._select_input(last_device_guid, last_input_type, last_input_id, True)

            syslog.info("Profile: load completed.")

            # mode to restore post-load if possible
            last_device_guid, last_input_type, last_input_id = self.config.get_last_input()
            self._select_input(last_device_guid, last_input_type, last_input_id)


        finally:
        
            
            gremlin.shared_state.profile_loading = False # done loading

            # restore the mouse cursor
            popCursor()

        
    # def _do_load_profile_old(self, source_xml : str, as_new_profile = False):
    #     """Load the profile with the given filename.

    #     :param source_xml: the name of the profile file to load
    #     :param as_new_profile: if set, loads the new profile as an unsaved profile

    #     """
    #     # Disable the program if it is running when we're loading a
    #     # new profile

    #     pushCursor()
    #     import_data = gremlin.base_profile.ProfileImportData()
    #     import_data.used_ids.clear()


    #     self.ui.actionActivate.setChecked(False)
    #     self.activate(False)

    #     el = gremlin.event_handler.EventListener()
    #     el.profile_unloaded.emit() # tell the UI we're about to load a new profile

    #     el.push_input_selection() # suspend input selection


    #     # mode to restore post-load if possible
    #     last_device_guid, last_input_type, last_input_id = self.config.get_last_input()

    #        # Attempt to load the new profile
    #     try:
    #         new_profile = gremlin.base_profile.Profile()
           

    #         gremlin.shared_state.current_profile = new_profile
    #         profile_updated = new_profile.from_xml(source_xml)

    #         profile_folder = os.path.dirname(source_xml)
    #         if profile_folder not in sys.path:
    #             sys.path = list(self._base_path)
    #             sys.path.insert(0, profile_folder)

    #         self._sanitize_profile(new_profile)

    #         if as_new_profile:
    #             # set as new unsaved profile
    #             new_profile.setProfileFile(None)



    #         last_edit_mode = gremlin.config.Configuration().get_profile_last_edit_mode()
    #         if not last_edit_mode:
    #             # pick the top mode if nothing was saved in the configuration
    #             last_edit_mode = self.profile.get_root_mode()
    #             gremlin.config.Configuration().set_profile_last_edit_mode(last_edit_mode)
            
    #         modes = new_profile.get_modes()
    #         if last_edit_mode is None:
    #             last_edit_mode = modes[0]

    #         if not last_edit_mode in modes:
    #             # no longer in the current mode list
    #             last_edit_mode = new_profile.get_default_mode()


    #         eh = gremlin.event_handler.EventHandler()
    #         eh.set_edit_mode(last_edit_mode)

    #         gremlin.shared_state.edit_mode = last_edit_mode

    #         self._create_tabs()

    #         # Make the first root node the default active mode
    #         self.mode_selector.populate_selector(new_profile, last_edit_mode, emit = False)


    #         # Save the profile at this point if it was converted from a prior
    #         # profile version, as otherwise the change detection logic will
    #         # trip over insignificant input item additions.
    #         if profile_updated:
    #             new_profile.to_xml(source_xml)

    #         # ask the UI to update input curve icons
    #         el.update_input_icons.emit()

    #         # update the hash value
    #         self._profile_hash = new_profile.getMappingHash()


    #     except (KeyError, TypeError) as error:
    #         # An error occurred while parsing an existing profile,
    #         # creating an empty profile instead
    #         syslog.exception(f"Invalid profile content:\n{error}")
    #         self.new_profile()
    #     except gremlin.error.ProfileError as error:
    #         # Parsing the profile went wrong, stop loading and start with an
    #         # empty profile
    #         cfg = gremlin.config.Configuration()
    #         cfg.last_profile = None
    #         self.new_profile()
    #         gremlin.util.display_error(f"Failed to load the profile {source_xml} due to:\n\n{error}")

    #     finally:

            
    #         el.profile_loaded.emit()

    #         # update the status bar
    #         self._update_mode_status_bar()
    #         self._update_window_title()

    #         # restore the mouse cursor
    #         popCursor()

    #         el.pop_input_selection(True) # restore input selection and reset
    #         self._select_input(last_device_guid, last_input_type, last_input_id, True)

    def refresh(self):
        gremlin.util.InvokeUiMethod(self._refresh_ui)

    def _refresh_ui(self):
        ''' refresh the UI '''

        gremlin.util.pushCursor()
        try:

            # save selection
            current_device_guid = gremlin.shared_state.current_tab_device_guid
            current_input_type, current_input_id = self._get_last_input(current_device_guid)

            self._create_tabs()

            current_profile =gremlin.shared_state.current_profile
            current_mode = gremlin.shared_state.current_mode



            # Make the first root node the default active mode
            self.mode_selector.populate_selector(current_profile, current_mode, emit = False)
            self._update_mode_status_bar()


            # refresh current device tab
            #self._refresh_tab()

            # select
            self._select_input(current_device_guid, current_input_type, current_input_id, True)
        finally:
            gremlin.util.popCursor()


    def _force_close(self):
        """Forces the closure of the program."""
        self.ui.tray_icon.hide()
        self.close()

    def _get_device_profile(self, device):
        """Returns a profile for the given device.

        If no profile exists for the given device a new empty one is
        created.

        :param device the device for which to return the profile
        :return profile for the provided device
        """
        profile = self.profile
        if device.device_guid in profile.devices:
            device_profile = profile.devices[device.device_guid]
        else:
            device_profile = {}

        return device_profile

    def _save_changes_request(self):
        """Asks the user what to do in case of a profile change.

        Presents the user with a dialog asking whether or not to save or
        discard changes to a profile or entirely abort the process.

        :return True continue with the intended action, False abort
        """
        # If the profile is empty we don't need to ask anything
        if not self.profile:
            return True
        if self.profile.empty():
            return True

        continue_process = True
        if self._has_profile_changed():

            message_box = QtWidgets.QMessageBox()
            message_box.setText("The profile has been modified.")
            message_box.setInformativeText("Do you want to save your changes?")
            message_box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Save |
                QtWidgets.QMessageBox.StandardButton.Discard |
                QtWidgets.QMessageBox.StandardButton.Cancel
            )
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
            gremlin.util.centerDialog(message_box)
            is_cursor = isCursorActive()
            if is_cursor:
                popCursor()
            response = message_box.exec()
            if is_cursor:
                pushCursor()
            if response == QtWidgets.QMessageBox.StandardButton.Save:
                self.save_profile()
            elif response == QtWidgets.QMessageBox.StandardButton.Cancel:
                continue_process = False
        return continue_process

    def _has_profile_changed(self):
        """Returns whether or not the profile has changed.

        :return True if the profile has changed, false otherwise
        """
        profile_fname = self.profile.profile_file
        if profile_fname is None:
            # profile not saved yet
            return True
        if not os.path.isfile(profile_fname):
            # profile not saved yet
            return True

        else:

            # get the current hash to detect changes
            current_hash = self.profile.getMappingHash()
            if self._profile_hash == current_hash:
                return False

            # save the profile and compare to the original file
            #tmp_path = os.path.join(os.getenv("temp"), gremlin.util.get_guid() + ".xml")
            tmp_path = os.path.join(os.getenv("temp"), "gremlin.xml")

            self.profile.to_xml(tmp_path)

            # remove blank text and comments from the XML files
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            try:
                t1 = etree.parse(tmp_path, parser=parser)
                t2 = etree.parse(profile_fname, parser=parser)
            except:
                # error loading file - assume no changes
                return False

            # remove container IDs and action IDs from xml
            trees = (t1, t2)
            ignore_list = ("container_id","action_id")
            gate_ignore_list = ("id","min_id","max_id")

            for t in trees:
                remove_nodes = []
                for node in t.findall(".//*"):
                    for attrib in ignore_list:
                        if attrib in node.attrib:
                            del node.attrib[attrib]
                    description = None
                    if "description" in node.attrib:
                        # clear blank description nodes
                        description = node.get("description")
                        if not description:
                            del node.attrib["description"]
                    if node.tag in ("button","axis","hat") and not description:
                        children = list(node)
                        if not children:
                            # remove blank axis, button and hat nodes from the comparison
                            remove_nodes.append(node)
                    if node.tag in ("gate","range"):
                        # ignore IDs that will change
                        for attrib in gate_ignore_list:
                            if attrib in node.attrib:
                                del node.attrib[attrib]

                # remove don't care nodes
                for node in remove_nodes:
                    node.getparent().remove(node)

            is_changed = etree.tostring(t1) != etree.tostring(t2)


            return is_changed


    def _last_runtime_mode(self):
        """Returns the name of the mode last active.

        :return name of the mode that was the last to be active, or the
            first top level mode if none was ever used before
        """
        config = gremlin.config.Configuration()
        option_restore_mode = config.restore_profile_mode_on_start or gremlin.shared_state.current_profile.get_restore_mode()
        # syslog = logging.getLogger("system")
        syslog.info(f"RUNTIME MODE: Runtime mode determination for profile [{self.profile.name}]")

        if option_restore_mode:
            syslog.info("\tAutomatic restore runtime mode is activated")
            key = self.profile.profile_file
            if key in self._runtime_mode_map:
                last_mode = self._runtime_mode_map[key]
                syslog.info(f"\tusing cached runtime mode [{last_mode}]")
            else:
                last_mode = self.profile.get_last_runtime_mode()
                syslog.info(f"\tusing profile saved last runtime mode [{last_mode}]")

        else:
            last_mode = self.profile.get_start_mode()
            syslog.info(f"\tusing profile default start mode [{last_mode}]")
        
        mode_list = gremlin.profile.mode_list()

        if not last_mode in mode_list:
            syslog.info(f"\tMode {last_mode} not found")
            default_mode = self.profile.get_root_mode()
            syslog.info(f"\tMode {last_mode} not found - using [{default_mode}]")

        return last_mode



    def _load_recent_profile(self, fname):
        """Loads the provided profile and updates the list of recently used
        profiles.

        :param fname path to the profile to load
        """
        if not self._save_changes_request():
            return

        self.config.last_profile = fname
        self._do_load_profile(fname)
        self._create_recent_profiles()

    
    def _mode_name_changed(self, old_mode:str, new_mode:str):
        self._update_mode_status_bar()

    def _edit_mode_changed(self, mode : str):
        gremlin.util.InvokeUiMethod(self._edit_mode_changed_ui, mode)    # ensure on UI thread

    def _edit_mode_changed_ui(self, mode : str):
        ''' called when edit time mode has changed '''
        # update the mode selector to the correct edit mode
        if mode:
            self.mode_selector.select_mode(mode)
            gremlin.event_handler.EventHandler().set_edit_mode(mode)
        self._update_mode_status_bar()
        self.setTabsDirty(True)


    def _runtime_mode_changed(self, mode : str):
        ''' called when runtime mode changes '''

        gremlin.shared_state.runtime_mode = mode
        if self._active_process_path:
            verbose = gremlin.config.Configuration().verbose_mode_process
            # syslog = logging.getLogger("system")
            
            if verbose:
                base_name = os.path.basename(self._active_process_path)
                base_profile = os.path.basename(self.profile.profile_file)
                syslog.info(f"PROC: save runtime mode process: [{base_name}] mode [{mode}] profile [{base_profile}]")
            self._process_runtime_map[self._active_process_path] = mode
            # save to JSON as well
            self.profile.set_last_runtime_mode(mode)

        self._update_mode_status_bar()


    def _sanitize_profile(self, profile_data):
        """Validates a profile file before actually loading it.

        :param profile_data the profile to verify
        """
        profile_devices = {}
        for device in profile_data.devices.values():
            # Ignore the keyboard
            if device.device_guid == dinput.GUID_Keyboard:
                continue
            profile_devices[device.device_guid] = device.name

        physical_devices = {}
        for device in gremlin.joystick_handling.physical_devices():
            physical_devices[device.device_guid] = device.name

    def _set_joystick_input_highlighting(self, is_enabled):
        """Enables / disables the highlighting of the current input
        when used.

        :param is_enabled if True the input highlighting is enabled and
            disabled otherwise
        """
        el = gremlin.event_handler.EventListener()
        el.enable_highlight_changed.emit(is_enabled)


    def _set_joystick_input_buttons_highlighting(self, is_enabled):
        """Enables / disables the highlighting of the current input button when used.

        :param is_enabled if True the input highlighting is enabled and
            disabled otherwise
        """
        eh = gremlin.event_handler.EventListener()
        eh.toggle_highlight.emit(None, None, is_enabled)

    def _set_joystick_input_axis_highlighting(self, is_enabled):
        """Enables / disables the highlighting of the current input button when used.

        :param is_enabled if True the input highlighting is enabled and
            disabled otherwise
        """
        eh = gremlin.event_handler.EventListener()
        eh.toggle_highlight.emit(None, is_enabled, None)        

    @QtCore.Slot(object, object)
    def _handle_highlight_state(self, autoswitch_state, axis_state, button_state):
        

        if autoswitch_state is not None:
            self.config.highlight_autoswitch = autoswitch_state

        if axis_state is not None:
            self.config.highlight_input_axis = axis_state

        if button_state is not None:
            self.config.highlight_input_buttons  = button_state

        # update status bar widgets

        with QtCore.QSignalBlocker(self.status_bar_highlight_tabswitch_widget):
            icon = self._icon_on if self.config.highlight_autoswitch else self._icon_off
            self.status_bar_highlight_tabswitch_widget.setIcon(icon)

        with QtCore.QSignalBlocker(self.status_bar_highlight_axis_widget):
            icon = self._icon_on if self.config.highlight_input_axis else self._icon_off
            self.status_bar_highlight_axis_widget.setIcon(icon)

        with QtCore.QSignalBlocker(self.status_bar_highlight_button_widget):
            icon = self._icon_on if self.config.highlight_input_buttons else self._icon_off
            self.status_bar_highlight_button_widget.setIcon(icon)
            



    @property
    def is_button_highlighting(self) -> bool:
        ''' true if button highlighting is currently enabled - this is either highlight or one of the shift keys held '''
        if not self.config.highlight_enabled or not self.config.highlight_input_buttons:
            # disabled
            return False
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False
        
        el = gremlin.event_handler.EventListener()
        is_hotkey_autoswitch = self.config.highlight_hotkey_autoswitch
        is_control = el.get_control_state()
        if is_control:
            return False # listen to axis only
        is_shifted = el.get_shifted_state() if is_hotkey_autoswitch else False
        return self.config.highlight_input_buttons or is_shifted or self._button_highlighting_enabled
    
    @property
    def is_axis_highlighting(self) -> bool:
        ''' true if button highlighting is currently enabled '''
        if not self.config.highlight_enabled or not self.config.highlight_input_axis:
            # disabled
            return False
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False
        
        
        el = gremlin.event_handler.EventListener()
        is_hotkey_autoswitch = self.config.highlight_hotkey_autoswitch
        is_shifted = el.get_shifted_state()
        if is_shifted:
            return False # listen to buttons only
        is_control = el.get_control_state() if is_hotkey_autoswitch else False
        return self.config.highlight_input_axis or is_control or self._axis_highlighting_enabled
    
    @property
    def is_highligthing_enabled(self) -> bool:
        ''' true if tab switch highlighting is enabled '''
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False
        
        return self.config.highlight_enabled
    

    def push_highlighting(self):
        ''' disables the highlighting of devices '''
        gremlin.shared_state.push_suspend_highlighting()
        

    def pop_highlighting(self, reset = False):
        ''' enables the highlighting of devices '''
        gremlin.shared_state.pop_suspend_highlighting(reset)




    def _should_process_input(self, event, widget, buttons_only = False):
        """Returns True when to process and input, False otherwise.

        This enforces a certain downtime between subsequent inputs
        triggering an update of the UI as well as preventing inputs
        from the same, currently active input to trigger another
        update.

        :param event the event to make the decision about
        :return True if the event is to be processed, False otherwise
        """
        # Check whether or not the event's input is significant enough to
        # be processed further

        is_running = self.runner.is_running()

        if is_running:
            return False


        # minimum deviation to look for for an axis
        deviation = self._joystick_axis_highlight_deviation


        if buttons_only and event.event_type == InputType.JoystickAxis and not self.input_axis_override:
            # ignore axis moves if button only mode
            return False

        if  self.input_axis_override and self.input_axis_only_override and event.event_type == InputType.JoystickButton:
            # exclusive axis mode - ignore buttons
            return False

        # see what is displayed currently in the UI
        data = widget.input_item_list_view.selected_item()
        if data:
            # if event.event_type == InputType.JoystickButton:
            #     pass
            if data.input_type == event.event_type and data.input_id == event.identifier:
                return False



        process_input = False
        is_new_device = self._last_input_event is None or self._last_input_event.hardwareKey != event.hardwareKey

        if event.event_type == InputType.JoystickAxis:
            # only worry about axis deviation delta if it's an axis

            if buttons_only and not self.input_axis_override:
                return False

            process_input = gremlin.input_devices.JoystickInputSignificant().should_process(event, deviation)

            self._input_delay = 1

            if process_input:
                if self._last_input_timestamp + self._input_delay > time.time():
                    # delay not occured yet
                    process_input = False


        else:
            process_input = is_new_device
            self._input_delay = 0.25

        if process_input:
            # remember when the last input was processed and what it was
            self._last_input_event = event
            self._last_input_timestamp = time.time()

            return True

        return False

    def _update_statusbar_repeater(self, text):
        """Updates the statusbar with information from the input
        repeater module.

        :param text the text to display
        """
        self.status_bar_repeater_widget.setText(
            "<b>Repeater: </b> {}".format(text)
        )

    def _update_window_title(self, title = None):
        """Updates the window title to include the current profile."""
        if title is None:
            profile_fname = None
            if gremlin.shared_state.current_profile is not None:
                profile_fname = gremlin.shared_state.current_profile.profile_file
            if profile_fname is not None:
                self.setWindowTitle(f"{os.path.basename(profile_fname)}")
            else:
                self.setWindowTitle("Untitled")
        else:
            self.setWindowTitle(title)



def configure_logger(config):
    """Creates a new logger instance.

    :param config configuration information for the new logger
    """
    import logging.handlers

    # blitz the log file
    log_file = config["logfile"]
    try:
        if os.path.isfile(log_file):
            os.unlink(log_file)
    except:
        syslog.error(f"Unable to remove old log file [{log_file}]")
        syslog.error(f"{err}\n{traceback.format_exc()}")
        
    logger = logging.getLogger(config["name"])
    logger.setLevel(config["level"])
    #handler = logging.FileHandler(config["logfile"])
    handler = logging.handlers.RotatingFileHandler(config["logfile"], maxBytes = 2 * 1024 * 1024, backupCount = 1)
    handler.setLevel(config["level"])

    formatter = logging.Formatter(config["format"], "%Y-%m-%d %H:%M:%S")
    

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logger.debug("-" * 80)
    logger.debug(time.strftime("%Y-%m-%d %H:%M"))
    logger.debug(f"Starting {gremlin.version.APPLICATION_NAME} {gremlin.version.APPLICATION_VERSION}")
    logger.debug("-" * 80)

    console = logging.StreamHandler()
    logger.addHandler(console)


def exception_hook(exception_type, value, trace):
    """Logs any uncaught exceptions.

    :param exception_type type of exception being caught
    :param value content of the exception
    :param trace the stack trace which produced the exception
    """
    msg = "Uncaught exception:\n"
    msg += " ".join(traceback.format_exception(exception_type, value, trace))
    syslog.error(msg)
    gremlin.util.display_error(msg)



if __name__ == "__main__":
   

    gremlin.shared_state.ui_ready = False

    # log file configuration
    app_path = gremlin.shared_state.data_path
    
    
    system_log_path = os.path.join(app_path, "system.log")
    user_log_path = os.path.join(app_path, "user.log")

    fault_log_path = os.path.join(app_path,"fault.log")
    if os.path.isfile(fault_log_path):
        os.unlink(fault_log_path)
    with open(fault_log_path,"w") as fl:
        faulthandler.enable(file=fl)

    gremlin.shared_state.app_path = app_path
    gremlin.shared_state.system_log = system_log_path
    gremlin.shared_state.user_log = user_log_path
    configure_logger({
        "name": "system",
        "level": logging.DEBUG,
        "logfile": system_log_path,
        "format": "%(asctime)s.%(msecs)03d %(levelname)10s %(message)s"
    })
    configure_logger({
        "name": "user",
        "level": logging.DEBUG,
        "logfile": user_log_path,
        "format": "%(asctime)s %(message)s"
    })

    # Path mangling to ensure Gremlin starts independent of the CWD
    sys.path.insert(0, app_path)
    gremlin.config.Configuration().setup_userprofile()

    # Fix some dumb Qt bugs
    QtWidgets.QApplication.addLibraryPath(os.path.join(
        os.path.dirname(PySide6.__file__),
        "plugins"
    ))



    # syslog = logging.getLogger("system")

    syslog.info(F"Joystick Gremlin Ex version {gremlin.version.Version().version}  (P{gremlin.util.getPythonVersion()})")

    # Initialize the vjoy interface
    from vjoy.vjoy_interface import VJoyInterface
    VJoyInterface.initialize()

    # Initialize the direct input interface class
    from dinput import DILL
    DILL.init()
    DILL.initialize_capi()
    syslog.info(f"Found DirectInput Interface version {DILL.version}")

    # Show unhandled exceptions to the user when running a compiled version
    # of Joystick Gremlin
    executable_name = os.path.split(sys.executable)[-1]
    if executable_name.casefold() == "gremlinex.exe":
        sys.excepthook = exception_hook

    # Initialize HidGuardian before we let SDL grab joystick data
    import gremlin.hid_guardian
    hg = gremlin.hid_guardian.HidGuardian()
    hg.add_process(os.getpid())

    # Create user interface
    app_id = u"gremlinex"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


    # disable dark mode for now while we sort icons in a future version
    
    theme = gremlin.config.Configuration().theme
    match theme:
        case "auto":
            gremlin.shared_state.is_dark_theme = gremlin.ui.theme.theme() == "Dark"
            app = QtWidgets.QApplication(sys.argv)
            

        case "light":
            os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"
            gremlin.shared_state.is_dark_theme = False
            app = QtWidgets.QApplication(sys.argv)
            app.setStyle("Windows")

        case "dark":
            os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=2"
            gremlin.shared_state.is_dark_theme = True
            app = QtWidgets.QApplication(sys.argv)

    # application style and css
    app.setStyle("Fusion")
    app.setStyleSheet(gremlin.ui.ui_common.Color.cssApplication())

    config = gremlin.config.Configuration()

    # command line parser
    parser = QtCore.QCommandLineParser()
    parser.addOption(QtCore.QCommandLineOption(["np","noprofile"],"Do not load a profile on start"))
    parser.process(app.arguments())
    config.auto_load_disabled = parser.isSet("noprofile")

    # for now force localization to use US English until we have proper localization support
    locale = QtCore.QLocale("UnitedStates")
    QtCore.QLocale.setDefault(locale)


    app.setWindowIcon(load_icon("gfx/icon.png"))
    app.setApplicationDisplayName(gremlin.version.APPLICATION_NAME + " " + gremlin.version.APPLICATION_VERSION)
    app.setApplicationVersion(gremlin.version.APPLICATION_VERSION)
    # no longer needed in QT6
    #app.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling)

    # handle windows themes better
    app.setStyle('Fusion')

    # Ensure joystick devices are correctly setup
    dinput.DILL.init()
    time.sleep(0.25)
    

    # check for gamepad availability via VIGEM
    if gremlin.gamepad_handling.gamepadAvailable():
        gremlin.gamepad_handling.gamepad_initialization()

    # update device list
    gremlin.joystick_handling.joystick_devices_initialization()
    

    # Check if vJoy is properly setup and if not display an error
    # and terminate GremlinEx
    try:
        syslog.info("Checking vJoy installation")
        vjoy_count = len([dev for dev in gremlin.joystick_handling.all_joystick_devices() if dev.is_virtual])
        vjoy_working = vjoy_count != 0
        syslog.info(f"\tFound {vjoy_count} vjoy device(s)")

        gremlin.shared_state.vjoy_enabled = vjoy_working

        if not vjoy_working:
            msg = "No configured VJOY devices were found.  VJOY output will be disabled.  This is normal if VJOY is not installed or not configured."
            syslog.warning(msg)
            #gremlin.ui.ui_common.MessageBox("Error Scanning Devices", msg)
            # raise gremlin.error.GremlinError(msg)

    except (gremlin.error.GremlinError, dinput.DILLError) as e:
        error_display = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Critical,
            "Error",
            e.value,
            QtWidgets.QMessageBox.Ok
        )
        error_display.move
        error_display.show()


        app.exec_()

        gremlin.joystick_handling.VJoyProxy.reset()
        el = gremlin.event_handler.EventListener()
        el.terminate() # terminates and sends the relevant shutdown triggers
        sys.exit(0)

    gremlin.shared_state.reload_device_map()

    # Initialize action plugins
    syslog.info("Initializing plugins")
    gremlin.plugin_manager.ActionPlugins()
    gremlin.plugin_manager.ContainerPlugins()

    # splash_pixmap = QtGui.QPixmap("gremlin-ex-logo.png")
    # splash = QtWidgets.QSplashScreen(splash_pixmap)
    # splash.show()
    # app.processEvents()

    # hid test
    #_hid = gremlin.hid.Hid()


    # Create Gremlin UI
    ui = GremlinUi()

    # joystick state
    sd = gremlin.event_handler.JoystickState()
    sd.hook()
    sd.reset() # initial state

    astate = gremlin.event_handler.AxisState()
    astate.reset()

    

    syslog.info("GremlinEx UI created")

        # state monitoring
    profile_state_monitor = gremlin.shared_state.ProfileStateMonitor()   

    # automatic process monitoring check
        
    pmgr = gremlin.process_monitor.ProcessMonitor()
    el = gremlin.event_handler.EventListener()
    el.process_monitor_changed.emit()


    ec = gremlin.execution_graph.ExecutionContext()

    gremlin.shared_state.char_width = gremlin.ui.ui_common.get_text_width("M")

    # report ui
    report = gremlin.reporting.ReportEngine()


    # Run UI


    # for some reason QT shows the window with a white background and ignores stylesheets/background color
    # workaround for now: show the window minimized so it doesnt' flash on the screen
    # let it update
    # show the window normally
    ui.showMinimized()
    app.processEvents()


        
    gremlin.shared_state.ui_ready = True

    syslog.info("Init completed...")
    el.ui_ready.emit()
    el.toggle_highlight.emit(ui.is_highligthing_enabled, ui.is_axis_highlighting, ui.is_button_highlighting)

  
    syslog.info("Apply settings...")
    ui.apply_user_settings() 

    if not config.start_minimized:
        ui.showNormal()
    
    #splash.finish(ui)

    # generate icons if needed
    #_icon_generator = gremlin.ui.ui_common.IconGenerator()

    syslog.info("GremlinEx UI launching")
    try:
        app.exec()
    except Exception as err:
        syslog.error(f"{err}\n{traceback.format_exc()}")

    syslog.info("GremlinEx UI terminated")

    gremlin.shared_state.terminating = True


    # Terminate potentially running EventListener loop
    gremlin.joystick_handling.VJoyProxy.reset()
    el = gremlin.event_handler.EventListener()
    el.terminate() # terminates and sends the relevant shutdown triggers
    

    if vjoy_working:
        # Properly terminate the runner instance should it be running
        ui.runner.stop()

    # Relinquish control over all VJoy devices used
    gremlin.joystick_handling.VJoyProxy.reset()

    #hg.remove_process(os.getpid())

    syslog.info("Terminating GremlinEx")
    #gc.collect()
    sys.exit(0)



