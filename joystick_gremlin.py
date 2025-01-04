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

import dinput
from lxml import etree

import gremlin.event_handler
import gremlin.execution_graph
import gremlin.gamepad_handling
import gremlin.import_profile
import gremlin.input_devices
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.ui.keyboard_device
import gremlin.ui.midi_device
import gremlin.ui.osc_device
import gremlin.ui.mode_device
import gremlin.util
import gremlin.curve_handler
import gremlin.gated_handler
import gremlin.input_types
import anytree

from gremlin.util import InvokeUiMethod, assert_ui_thread


# Import QtMultimedia so pyinstaller doesn't miss it

import PySide6
from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
from gremlin.types import TabDeviceType



from gremlin.input_types import InputType
from gremlin.types import DeviceType

from gremlin.util import load_icon, load_pixmap, userprofile_path, find_file, waitCursor, popCursor, pushCursor, isCursorActive
import gremlin.shared_state
import gremlin.base_profile
import gremlin.event_handler
import gremlin.config
import gremlin.macro_handler
import gremlin.gated_handler



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



# Figure out the location of the code / executable and change the working
# directory accordingly
install_path = os.path.normcase(os.path.dirname(os.path.abspath(sys.argv[0])))
os.chdir(install_path)


import gremlin.ui.axis_calibration
import gremlin.ui.ui_common
import gremlin.ui.device_tab
import gremlin.ui.dialogs
import gremlin.ui.input_viewer
import gremlin.ui.merge_axis
import gremlin.ui.user_plugin_management
import gremlin.ui.profile_creator
import gremlin.ui.profile_settings

from PySide6 import QtCore

from gremlin.ui.ui_gremlin import Ui_Gremlin
#from gremlin.input_devices import remote_state

APPLICATION_NAME = "Joystick Gremlin Ex"
APPLICATION_BASE = "m55"
APPLICATION_VERSION = f"13.40.16ex ({APPLICATION_BASE})"


# the main ui
ui = None

from gremlin.singleton_decorator import SingletonDecorator

@SingletonDecorator
class Version():
    version = APPLICATION_VERSION


class TabData:
    def __init__(self, device_guid, tab_type : TabDeviceType):
        self._device_guid = device_guid
        self._tab_type = tab_type

    @property
    def device_guid(self) -> str:
        return self._device_guid
    @property
    def tab_type(self) -> TabDeviceType:
        return self._tab_type

class GremlinUi(QtWidgets.QMainWindow):

    """Main window of the Joystick Gremlin user interface."""



    ui = None

    # input_lock =  threading.Lock() # critical code operations - prevents reentry



    def __init__(self, parent=None):
        """Creates a new main ui window.

        :param parent the parent of this window
        """


        QtWidgets.QMainWindow.__init__(self, parent)
        self.ui = Ui_Gremlin()
        self.ui.setupUi(self)
        #self._recreate_tab_widget()
        self.locked = False
        self.activate_locked = False
        self._selection_locked = False
        self.joystick_event_lock = Lock() # lock for joystick events
        self.device_change_locked = False
        self._device_change_queue = 0 # count of device updates while the UI is already updating
        self._runtime_mode_map = {} # map of runtime processes to their last runtime mode

        self._resize_count = 0

        # list of detected devices
        self._active_devices = []

        # cache of widget references so they don't get garbage collected by QT

        self.ui.devices.tabChanged.connect(self._tab_selected)
        self.ui.devices.tabMoveCompleted.connect(self._tab_moved_cb)

        self._last_input_item = None # last selected input item


        gremlin.shared_state.application_version = APPLICATION_BASE

        self.config = gremlin.config.Configuration()

        

        # prevent saving anything until we have a profile loaded
        el = gremlin.event_handler.EventListener()
        el.push_input_selection()
        el.request_activate.connect(self.activate) # hook activation / deactivation requests
        


        # highlighing options
        self._icon_on = gremlin.util.load_icon("mdi.record", qta_color="green")
        self._icon_off = gremlin.util.load_icon("mdi.record", qta_color="lightgray")
        self._button_highlighting_enabled = self.config.highlight_input_buttons # true if highlighting on buttons
        self._axis_highlighting_enabled = self.config.highlight_input_axis  # true if highligthing on axes
        self._input_highlighting_enabled = self.config.highlight_enabled  # on/off global
        self._input_highlight_stack = 1 # push stack for enable/disable (start disabled)
        self._last_highlight_key = None    # last event processed for input highlights
        el.toggle_highlight.connect(self._handle_highlight_state) # input highlighting states
        el.ui_ready.connect(self._ui_ready)
        gremlin.shared_state.aborted = False
        el.request_profile_stop.connect(lambda x: self.abort(x))

        # Process monitor
        self.process_monitor = gremlin.process_monitor.ProcessMonitor()
        self.process_monitor.process_changed.connect(self._process_changed_cb)

        # Default path variable before any runtime changes
        self._base_path = list(sys.path)


        self._init_tab_data()
        self._reset_tab_data()

        self.runner = gremlin.code_runner.CodeRunner()
        self.repeater = gremlin.repeater.Repeater(
            [],
            self._update_statusbar_repeater
        )

        eh = gremlin.event_handler.EventHandler()
        eh.mode_changed.connect(self._update_mode_change)
        eh.mode_status_update.connect(self._update_mode_status_bar)
        el.mode_name_changed.connect(self._update_mode_status_bar)
        el.modes_changed.connect(self._update_mode_status_bar)


        self.tab_guids = []

        self.mode_selector = gremlin.ui.ui_common.ModeWidget()
        self.mode_selector.edit_mode_changed.connect(self._edit_mode_changed_cb)
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
        el.keyboard_event.connect(self._kb_event_cb)
        el.suspend_keyboard_input.connect(self._kb_suspend_cb)
        el.profile_start.connect(lambda: self._update_status_bar_active(True))
        el.profile_stop.connect(lambda: self._update_status_bar_active(False))
        #el.joystick_event.connect(self._joystick_input_handler)
        el.profile_changed.connect(self._profile_changed_cb)
        el.button_state_change.connect(self._button_state_change)
        el.axis_state_change.connect(self._axis_state_change)
        #el.request_profile_stop.connect(lambda reason: self.abort_requested(reason)) # request profile to stop

        # hook mode change
        el.modes_changed.connect(self._modes_changed)

        # hook input selection
        el.select_input.connect(self._select_input_handler)

        # hook config changes
        el.config_changed.connect(self._config_changed_cb)

        # hook changes
        eh = gremlin.event_handler.EventHandler()
        eh.profile_changed.connect(self._profile_changed_cb)


        self._context_menu_tab_index = None

        # Load existing configuration or create a new one otherwise
        if self.config.last_profile and os.path.isfile(self.config.last_profile):
            # check if this was a profile swap that we load the profile from the current user folder
            current_profile_folder = userprofile_path().lower()
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

        # Enable reloading for when a user connects / disconnects a
        # device. Sleep for a bit to avert race with devices being added
        # when they already exist.

        time.sleep(0.1)
        el._init_joysticks()
        el.device_change_event.connect(self._device_change_cb)

        self.apply_user_settings()
        self.apply_window_settings()

        self._profile_map = gremlin.base_profile.ProfileMap()

        GremlinUi.ui = self

    def _init_tab_data(self):
        self._widget_cache = {} # map of device widgets keyed by the device GUID

    def _reset_tab_data(self):
        
        self._tab_index_map = {} # map of device_guids indexed by their tab index from the tab header  (index -> device_guid)
        self._tab_device_map = {} # map of tab positions index mapped by device guid for the tab header (device_guid -> index)
        self._tab_name_map = {} # map fo device guid to device name for tabs
        
        self._current_tab_widget = None # selected content widget for the current device
        self._current_tab_device_guid = None # selected device GUID
        self._current_tab_input_id = None # selected input in the current tab
        self._joystick_device_guids = []
        self.tab_guids = []

        # remove all tab headers
        with QtCore.QSignalBlocker(self.ui.devices):
            while self.ui.devices.count():
                self.ui.devices.removeTab(0)

        gremlin.shared_state.device_profile_map.clear()
        
        

    def _add_tab(self, device_guid, tab_type, index = None) -> int: 
        ''' adds a tab to the tab header 
        :param device_guid: the device guid of the device to add
        :param index: optiona, if specified, the index to add
        :returns int: the index of the tab added 
        '''



        device_name = gremlin.shared_state.get_device_name(device_guid)
 

        # update tracking data
        syslog = logging.getLogger("system")
        if device_guid in self._tab_device_map:
            syslog.error(f"Duplicate GUID found in tabs: {device_name} {device_guid}")
            assert False

        

        if index is None:
            position = self.ui.devices.addTab(device_name)
        else:
            position = self.ui.devices.insertTab(index, device_name)
    
        self._tab_device_map[device_guid] = position
        self._tab_index_map[position] = device_guid
        self._tab_name_map[device_guid] = device_name
        
        self.ui.devices.setTabData(position, TabData(device_guid, tab_type))

        if tab_type == TabDeviceType.Joystick:
            self._joystick_device_guids.append(device_guid)
        
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            
            syslog.info(f"Add tab: {position} {device_name} {device_guid}")

        return position
    
    
    def _get_tab_map(self):
        ''' gets tab configuration data as a dictionary indexed by tab index holding device id, device name and device widget type


        :returns:  list of (device_guid, device_name, tabdevice_type, tab_index)
        '''
        tab_count = self.ui.devices.count()
        tab_map = {}
        for index in range(tab_count):
            device_guid = self._tab_index_map[index]
            data : TabData = self.ui.devices.tabData(index)
            assert device_guid ==  data.device_guid
            device_name = self._tab_name_map[device_guid]
            
            tab_map[index] = (device_guid, device_name, data.tab_type, index)
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
        
        verbose = gremlin.config.Configuration().verbose
        syslog = logging.getLogger("system")
        if verbose: syslog.info("UI: tab reindex")
        for index in range(self.ui.devices.count()):
            data = self.ui.devices.tabData(index)
            device_guid = data.device_guid
            device_name = gremlin.shared_state.get_device_name(device_guid)
            self._tab_index_map[index] = device_guid
            self._tab_device_map[device_guid] = index
            self._tab_name_map[device_guid] = device_name
            
            if verbose: 
                syslog.info(f"\t[{index}] {device_name} {device_guid}")

            
         

    def _tabswitch_needed(self, device_guid) -> bool:
        ''' checks to see if the device tab is the current tab or not '''
        
        tab_device_guid = self._current_tab_device_guid
        if isinstance(device_guid, str):
            device_guid = str(device_guid)
        return tab_device_guid != device_guid
    

    def _inputswitch_needed(self, device_guid, input_id) -> bool:
        ''' checks to see if an input switch is needed '''
        if isinstance(device_guid, str):
            device_guid = str(device_guid)
        tab_device_guid = self._current_tab_device_guid
        tab_input_id = self._current_tab_input_id
        return tab_device_guid != device_guid or tab_input_id != input_id


    def _button_state_change(self, device_guid, input_type, input_id, is_pressed):
        ''' button changed - triggered only at design time '''

        is_tabswitch_enabled = self.config.highlight_autoswitch
        if not is_pressed:
            # trigger only on presses
            return
        if self._input_highlight_stack > 0:
            # highlighting disabled
            return
        is_button = self.is_button_highlighting
        if not is_button:
            # highlight disabled
            return
        
        tab_switch_needed = self._tabswitch_needed(device_guid)
        input_switch_needed = tab_switch_needed or self._inputswitch_needed(device_guid, input_id)

        if tab_switch_needed and not is_tabswitch_enabled and not input_switch_needed:
            # not setup to auto change tabs (override via shift/control keys)
            return
        
        # see if input needs to change
        input_switch_needed = tab_switch_needed or self._inputswitch_needed(device_guid, input_id)
        if not input_switch_needed:
            return
        
        # trigger switch
        self._select_input_handler(device_guid, input_type, input_id)
        

    def _axis_state_change(self, device_guid, input_type, input_id, value):
        ''' axis changed - triggered only at design time '''
        # avoid input spamming
        if self._last_input_timestamp + self._input_delay > time.time():
            # delay not occured yet
            return
        self._last_input_timestamp = time.time()
        if self._input_highlight_stack > 0:
            # highlighting disabled
            return
        is_axis = self.is_axis_highlighting
        if not is_axis:
            # highlight disabled
            return
        tab_switch_needed = self._tabswitch_needed(device_guid)
        is_tabswitch_enabled = self.config.highlight_autoswitch
        input_switch_needed = tab_switch_needed or self._inputswitch_needed(device_guid, input_id)
        if tab_switch_needed and not is_tabswitch_enabled and not input_switch_needed:
            # not setup to auto change tabs (override via shift/control keys)
            return
        
        # see if input needs to change
        
        if not input_switch_needed:
            return
        
        # check for axis deviation
        if not device_guid in self._joystick_axis_highlight_map:
            self._joystick_axis_highlight_map[device_guid] = {}
        if not input_id in self._joystick_axis_highlight_map[device_guid]:
            self._joystick_axis_highlight_map[device_guid][input_id] = value
            deviation = 2.0
        else:
            deviation = abs(self._joystick_axis_highlight_map[device_guid][input_id] - value)

        if deviation < self._joystick_axis_highlight_deviation:
            # deviation insufficient to trigger a tab switch
            return
        
        # trigger switch
        self._select_input_handler(device_guid, input_type, input_id)

    @QtCore.Slot(int)
    def _tab_selected(self, index):
        ''' called when the device tab selection is changed
        :param: index = the index of the tab that was selected

        '''

        if self.ui.devices.moveInProgress:
            # ignore if the tab is being dragged
            return 

        device_guid = self.getDeviceGuidForTabIndex(index)
        # if self._current_tab_device_guid == device_guid:
        #     # already selected
        #     return 

        if device_guid is not None:
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                logging.getLogger("system").info(f"Tab index change: new tab [{index}] {self.ui.devices.tabText(index)} - device {device_guid} {gremlin.shared_state.get_device_name(device_guid)}")
            self.last_tab_index = index
            _, restore_input_type, restore_input_id = self.config.get_last_input(device_guid)
            self._select_input(device_guid = device_guid, input_type = restore_input_type, input_id = restore_input_id, force_update =True, force_switch=True)

        


    def add_custom_tools_menu(self, menuTools):
        ''' adds custom tools to the menu '''
        self._actionTabSort = QtGui.QAction("Sort Devices", self, triggered = self._tab_sort_cb)
        self._actionTabSort.setToolTip("Sorts input hardware devices in alphabetical order")
        self._actionTabSubstitute = QtGui.QAction("Device Substitution...", self, triggered = self._tab_substitute_cb)
        self._actionTabSubstitute.setToolTip("Substitute device GUIDs")
        self._actionTabClearMap = QtGui.QAction("Clear Mappings", self, triggered = self._tab_clear_map_cb)
        self._actionTabClearMap.setToolTip("Clears all mappings from the current device")
        self._actionTabImport = QtGui.QAction("Import Profile...", self, triggered = self._tab_import_cb)
        self._actionTabImport.setToolTip("Import profile data into the current device")

        menuTools.addSeparator()
        menuTools.addAction(self._actionTabSort)
        menuTools.addAction(self._actionTabSubstitute)
        menuTools.addAction(self._actionTabImport)
        menuTools.addAction(self._actionTabClearMap)



    def _tab_context_menu_cb(self, pos):
        ''' tab context menu '''
        tab_index = self.ui.devices.tabAt(pos)
        if tab_index == -1:
            return
        self._context_menu_tab_index = tab_index
        widget = self.ui.devices.widget(self._context_menu_tab_index)
        device_type, device_guid = widget.data
        # substitution is only available if the profile has been saved (a new profile matches the current devices by definition)
        is_enabled = device_type == TabDeviceType.Joystick \
            and self.profile is not None\
            and self.profile.profile_file is not None\
            and os.path.isfile(self.profile.profile_file)
        self._actionTabSubstitute.setEnabled(is_enabled)
        menu = QtWidgets.QMenu(self)
        menu.addAction(self._actionTabSort)
        menu.addAction(self._actionTabSubstitute)
        menu.addAction(self._actionTabImport)
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
        self._create_tabs()



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


        widget = self.ui.devices.widget(self._context_menu_tab_index)
        _, device_guid = widget.data

        device_name = self.ui.devices.tabText(self._context_menu_tab_index)
        dialog = gremlin.ui.dialogs.SubstituteDialog(device_guid=device_guid, device_name=device_name, parent = self)
        dialog.setModal(True)
        dialog.accepted.connect(self._substitute_complete_cb)
        gremlin.util.centerDialog(dialog)
        dialog.show()

    def _substitute_complete_cb(self):
        ''' substitution complete - reload profile '''
        profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self.load_profile(profile.profile_file)


    def _profile_changed_cb(self, new_profile = None):
        ''' called when the a profile should be loaded '''

        if new_profile is None:
            # save current contents to a temporary file
            profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
            tmp_file = os.path.join(os.getenv("temp"), gremlin.util.get_guid() + ".xml")
            profile.save(tmp_file)
            self._do_load_profile(tmp_file)
            os.unlink(tmp_file)
            profile.setProfileFile(None)
            self._update_window_title("Untitled")
        else:
            self._load_recent_profile(new_profile)

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
            self.modal_windows["log"].watcher.stop()

    def resizeEvent(self, evt):
        """Handling changing the size of the window.

        :param evt event information
        """
        if self._resize_count > 1:
            self.config.window_size = [evt.size().width(), evt.size().height()]
        self._resize_count += 1

    def moveEvent(self, evt):
        """Handle changing the position of the window.

        :param evt event information
        """
        if self._resize_count > 1:
            self.config.window_location = [evt.pos().x(), evt.pos().y()]

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
        """Opens the log display window."""
        self.modal_windows["log"] = gremlin.ui.dialogs.LogWindowUi()
        self.modal_windows["log"].show()
        self.modal_windows["log"].closed.connect(
            lambda: self._remove_modal_window("log")
        )

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
        dialog.closed.connect(
            lambda: self.apply_user_settings(ignore_minimize=True)
        )
        dialog.closed.connect(
            lambda: self._remove_modal_window("options")
        )
        dialog.closed.connect(lambda: self.refresh())
        dialog.show()


    def profile_creator(self):
        """Opens the UI used to create a profile from an existing one."""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Profile to load as template",
            gremlin.util.userprofile_path(),
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
        self.modal_windows["swap_devices"].closed.connect(
            self._create_tabs
        )

    def _remove_modal_window(self, name):
        """Removes the modal window widget from the system.

        :param name the name of the modal window to remove
        """
        if name in self.modal_windows:
            del self.modal_windows[name]

    # +---------------------------------------------------------------
    # | Action implementations
    # +---------------------------------------------------------------

    def menu_activate(self, activate):
        if not activate:
            el = gremlin.event_handler.EventListener()
            el.profile_stop_toolbar.emit()
        self.activate(activate)


    def abort(self, message = None):
        ''' aborts profile execution on error '''
        if gremlin.shared_state.aborted:
            return
        
        gremlin.shared_state.aborted = True # mark aborting globally
        el = gremlin.event_handler.EventListener()
        el.abort.emit()
        self.ui.actionActivate.setChecked(False)
        self.activate(False)
        if message:
            gremlin.ui.ui_common.MessageBox(prompt = message)


    def activate(self, activate):
        """Activates and deactivates the code runner.

        :param checked True when the runner is to be activated, False
            otherwise
        """
        import gremlin.ui.device_tab
        import gremlin.ui.keyboard_device
        import gremlin.ui.midi_device
        import gremlin.ui.osc_device
        import gremlin.shared_state

        if self.activate_locked:
            #logging.getLogger("system").info("Activate: re-entry")
            return


        el = gremlin.event_handler.EventListener()

        try:

            self.abort_received = False
            self.abort_reason = None
            #logging.getLogger("system").info("Activate: start")
            self.activate_locked = True

            is_running = gremlin.shared_state.is_running


            from gremlin.config import Configuration
            config = Configuration()
            verbose = config.verbose
            verbose_mode_exec = config.verbose_mode_exec

            if activate:
                # Generate the code for the profile and run it
                if verbose: syslog.info(f"Activate: activate profile")
                self._profile_auto_activated = False
                ec = gremlin.execution_graph.ExecutionContext()
                ec.reset()
                gremlin.shared_state.aborted = False # reset abort flag


                # start the profile with the specified runtime mode
                self.runner.start(
                    self.profile.build_inheritance_tree(),
                    self.profile.settings,
                    self._last_runtime_mode(),
                    self.profile
                )
                #print ("set icon ACTIVE")
                self.ui.tray_icon.setIcon(load_icon("gfx/icon_active.ico"))

                with QtCore.QSignalBlocker(self.ui.actionActivate):
                    self.ui.actionActivate.setChecked(True) # toolbar icon "on"

                if verbose_mode_exec:
                    ec.dumpActive()


                # tell callbacks they are starting
                
                el.profile_start.emit()

            else:
                # Stop running the code
                if verbose:
                    logging.getLogger("system").info(f"Deactivate profile requested")
                if is_running:
                    # running - save the last running mode to the executing profile
                    self.profile.set_last_runtime_mode(gremlin.shared_state.runtime_mode)

                
                # stop listen
                el.stop()
                # tell modules the profile is stopping
                el.profile_stop.emit()

                self.runner.stop()
                self._update_status_bar_active(False)
                self._profile_auto_activated = False
                current_index = self.ui.devices.currentIndex()
                device_guid = self.getDeviceGuidForTabIndex(current_index)
                widget = self.getWidget(device_guid)
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
                    pass
        except Exception as err:
            logging.getLogger("system").error(f"Activate: error: {err}\n{traceback.format_exc()}")

        finally:

            #logging.getLogger("system").info("Activate: completed")
            self.activate_locked = False

    def input_repeater(self):
        """Enables or disables the forwarding of events to the repeater."""
        el = gremlin.event_handler.EventListener()
        if self.ui.actionInputRepeater.isChecked():
            el.keyboard_event.connect(self.repeater.process_event)
            el.joystick_event.connect(self.repeater.process_event)
            self._update_statusbar_repeater("Waiting for input")
        else:
            el.keyboard_event.disconnect(self.repeater.process_event)
            el.joystick_event.disconnect(self.repeater.process_event)
            self.repeater.stop()
            self.status_bar_repeater_widget.setText("")

    def input_viewer(self):
        """Displays the input viewer dialog."""
        self.modal_windows["input_viewer"] = \
            gremlin.ui.input_viewer.InputViewerUi()
        geom = self.geometry()
        self.modal_windows["input_viewer"].setGeometry(
            int(geom.x() + geom.width() / 2 - 350),
            int(geom.y() + geom.height() / 2 - 150),
            700,
            300
        )
        self.modal_windows["input_viewer"].show()
        self.modal_windows["input_viewer"].closed.connect(
            lambda: self._remove_modal_window("input_viewer")
        )

    def load_profile(self, fname = None):
        """Prompts the user to select a profile file to load."""
        if not self._save_changes_request():
            return

        if not fname:

            fname, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Load Profile",
                gremlin.util.userprofile_path(),
                "XML files (*.xml)"
            )

        if fname != "":
            self._load_recent_profile(fname)

    def import_profile(self):
        ''' import a profile '''
        gremlin.import_profile.import_profile()



    def new_profile(self):
        """Creates a new empty profile."""
        # Disable Gremlin if active before opening a new profile

        pushCursor()



        self.ui.actionActivate.setChecked(False)
        self.activate(False)

        if not self._save_changes_request():
            return
        
        self.clearWidgets()

        gremlin.shared_state.resetState()
        eh = gremlin.event_handler.EventHandler()
        eh.reset()

        el = gremlin.event_handler.EventListener()
        el.profile_unloaded.emit() # tell the UI we're about to load a new profile

        new_profile =  gremlin.base_profile.Profile()
        self.profile = new_profile

        # default active mode
        gremlin.shared_state.runtime_mode = "Default"
        gremlin.shared_state.edit_mode = "Default"

        # For each connected device create a new empty device entry
        # in the new profile
        for device in gremlin.joystick_handling.physical_devices():
            self.profile.initialize_joystick_device(device, ["Default"])


        # non regular devices
        self.profile.initialize_regular_devices()

        # Update profile information
        self._update_window_title()


        # Create device tabs
        self._create_tabs()

        # reset modes
        current_mode = gremlin.shared_state.current_mode
        self.mode_selector.populate_selector(new_profile, current_mode, emit = False)

        # Create a default mode
        for device in self.profile.devices.values():
            device.ensure_mode_exists("Default")

        # Update everything to the new mode
        #self._mode_configuration_changed()



        popCursor()

    def save_profile(self):
        """Saves the current profile to the hard drive.

        If the file was loaded from an existing profile that file is
        updated, otherwise the user is prompted for a new file.
        """
        if self.profile.profile_file is not None:
            self.profile.save()
        else:
            self.save_profile_as()


    def save_profile_as(self):
        """Prompts the user for a file to save to profile to."""
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save Profile",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )
        if fname != "":
            self.profile.setProfileFile(fname)
            self.profile.save()
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

    def open_profile_xml(self):
        ''' views the profile as an xml in the default text editor '''
        profile_fname = self.profile.profile_file
        if profile_fname:
            # save first
            self.profile.to_xml(profile_fname)
            if  os.path.isfile(profile_fname):
                path = os.path.realpath(profile_fname)
                webbrowser.open(path)

    # +---------------------------------------------------------------
    # | Create UI elements
    # +---------------------------------------------------------------

    def _connect_actions(self):
        """Connects all QAction items to their corresponding callbacks."""
        # Menu actions
        # File
        self.ui.actionLoadProfile.triggered.connect(self.load_profile)
        self.ui.actionImportProfile.triggered.connect(self.import_profile)
        self.ui.actionNewProfile.triggered.connect(self.new_profile)
        self.ui.actionSaveProfile.triggered.connect(self.save_profile)
        self.ui.actionSaveProfileAs.triggered.connect(self.save_profile_as)
        self.ui.actionRevealProfile.triggered.connect(self.reveal_profile)
        self.ui.actionOpenXmlProfile.triggered.connect(self.open_profile_xml)
        self.ui.actionModifyProfile.triggered.connect(self.profile_creator)
        self.ui.actionExit.triggered.connect(self._force_close)
        # Actions
        self.ui.actionCreate1to1Mapping.triggered.connect(
            self._create_1to1_mapping
        )
        self.ui.actionMergeAxis.triggered.connect(self.merge_axis)
        self.ui.actionSwapDevices.triggered.connect(self.swap_devices)

        # Tools
        self.ui.actionDeviceInformation.triggered.connect(
            self.device_information
        )
        self.ui.actionManageModes.triggered.connect(self.manage_modes)
        self.ui.actionInputRepeater.triggered.connect(self.input_repeater)
        #self.ui.actionCalibration.triggered.connect(self.calibration)
        self.ui.actionInputViewer.triggered.connect(self.input_viewer)
        self.ui.actionPDFCheatsheet.triggered.connect(
            lambda: self._create_cheatsheet()
        )
        self.ui.actionViewInput.triggered.connect(lambda: self._view_input_map())
        self.ui.actionOptions.triggered.connect(self.options_dialog)
        self.ui.actionLogDisplay.triggered.connect(
            self.log_window
        )
        # About
        self.ui.actionAbout.triggered.connect(self.about)

        # Toolbar actions
        self.ui.actionActivate.triggered.connect(self.menu_activate)
        self.ui.actionOpen.triggered.connect(self.load_profile)
        self.ui.actionSave.triggered.connect(self.save_profile)

        # Tray icon
        self.ui.tray_icon.activated.connect(self._tray_icon_activated_cb)

        # Simconnect configuration
        self.ui.actionSimconnectOptions.triggered.connect(self.showSimconnectOptions)


    def showSimconnectOptions(self):
        ''' displays the simconnect options dialog '''
        from action_plugins.map_to_simconnect import SimconnectOptionsUi
        from action_plugins.map_to_simconnect.SimConnectManager import SimConnectManager
        profile = gremlin.shared_state.current_profile
        profile_file = profile.profile_file
        if not profile_file or not os.path.isfile(profile_file):
            gremlin.ui.ui_common.MessageBox(prompt="Please save the current profile before accessing Simconnect options.")
            return 
        dialog = SimconnectOptionsUi(SimConnectManager().simconnect)
        dialog.exec()

    def _create_1to1_mapping(self):
        ''' maps one to one '''
        mapper = gremlin.import_profile.Mapper()
        mapper.create_1to1_mapping()


    def _create_recent_profiles(self):
        """Populates the Recent submenu entry with the most recent profiles."""
        self.ui.menuRecent.clear()
        for entry in self.config.recent_profiles:
            action = self.ui.menuRecent.addAction(
                gremlin.util.truncate(entry, 5, 40)
            )
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
        self.status_bar_highlight_axis_widget.setToolTip("Enable axis input highlighting")

        self.status_bar_highlight_button_widget = QtWidgets.QPushButton()
        self.status_bar_highlight_button_widget.setStyleSheet("border: none")
        self.status_bar_highlight_button_widget.clicked.connect(self._toggle_button_highlight)
        self.status_bar_highlight_button_widget.setToolTip("Enable button input highlighting")

        self.ui.statusbar_widget.addWidget(self.status_bar_is_active_widget, 0)
        self.ui.statusbar_widget.addWidget(self.status_bar_mode_widget, 3)
        self.ui.statusbar_widget.addWidget(self.status_bar_repeater_widget, 1)
        self.ui.statusbar_widget.addWidget(QtWidgets.QLabel("<b>Highlight</b> Device:"))
        self.ui.statusbar_widget.addWidget(self.status_bar_highlight_tabswitch_widget, 0)
        self.ui.statusbar_widget.addWidget(QtWidgets.QLabel("Axis"), 0)                                                     
        self.ui.statusbar_widget.addWidget(self.status_bar_highlight_axis_widget, 0)
        self.ui.statusbar_widget.addWidget(QtWidgets.QLabel("Button"), 0)
        self.ui.statusbar_widget.addWidget(self.status_bar_highlight_button_widget, 0)


    @QtCore.Slot()
    def _toggle_tabswitch_highlight(self):
        eh = gremlin.event_handler.EventListener()
        status = self.config.highlight_autoswitch
        eh.toggle_highlight.emit(not status, None, None)
        
        
    @QtCore.Slot()
    def _toggle_axis_highlight(self):
        eh = gremlin.event_handler.EventListener()
        status = self.config.highlight_input_axis
        eh.toggle_highlight.emit(None, not status, None)


    @QtCore.Slot()
    def _toggle_button_highlight(self, checked):
        eh = gremlin.event_handler.EventListener()
        status = self.config.highlight_input_buttons
        eh.toggle_highlight.emit(None, None, not status)



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

        self.ui.action_tray_show.triggered.connect(
            lambda: self.setHidden(not self.isHidden())
        )
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


    def registerWidget(self, device_guid, widget, hide = True):
        ''' registers widget for cleanup - this is needed because QT doesn't tell us when widgets are discarded so we need to manually track this here 
        so widgets cleanup correctly and remove any hooks / references '''
        device_name = gremlin.shared_state.get_device_name(device_guid)
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._widget_cache:
            syslog.error(f"TAB: widget already exists for tab: {device_guid} {device_name}")
            return
        self._widget_cache[device_guid] = widget
        self.ui.tab_content_layout.addWidget(widget)
        
        if hide:
            widget.setVisible(False)
        
        

    def unregisterWidget(self, device_guid):
        ''' removes a widget from the cleanup list'''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._widget_cache:
            widget = self._widget_cache[device_guid]
            self.ui.tab_content_layout.removeWidget(widget)
            if hasattr(widget, "_cleanup_ui"):
                widget._cleanup_ui()
            del self._widget_cache[device_guid]


    def clearWidgets(self):
        ''' clears the device cache'''
        self._widget_cache.clear()
        gremlin.util.clear_layout(self.ui.tab_content_layout)

    def getTabIndexForDevice(self, device_guid):
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._tab_device_map:
            return self._tab_device_map[device_guid]
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
            return self.getWidget(device_guid)
        return None



    def clearRegisteredWidgets(self):
        ''' cleanup all widgets '''
        for widget in self._widget_cache.values():
            self.ui.tab_content_layout.removeWidget(widget)
            if hasattr(widget, "_cleanup_ui"):
                widget._cleanup_ui()
        self._widget_cache.clear()

    def getWidget(self, device_guid):
        ''' gets the content widget for the given device '''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._widget_cache:
            return self._widget_cache[device_guid]
        return None
    

    
    def hideTabWidgets(self):
        ''' hides all tab widgets '''
        for widget in self._widget_cache.values():
            widget.setVisible(False)

            
    def selectTabWidgetByIndex(self, index : int):
        ''' shows the page (content widget) for the specified tab index '''
        if index in self._tab_index_map:
            device_guid = self._tab_index_map[index]
            self.selectTabWidget(device_guid)


    def selectTabWidget(self, device_guid):
        ''' shows the page (content widget) for the specified device'''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)

        el = gremlin.event_handler.EventListener()
        verbose = gremlin.config.Configuration().verbose_mode_detailed
        
        current_device_guid = self._current_tab_device_guid
        if current_device_guid:
            if self._current_tab_device_guid == device_guid:
                # already shown
                return 
        
            device_name = gremlin.shared_state.get_device_name(current_device_guid)
            if verbose: syslog.info(f"TAB UNSELECT: {device_name}")
            el.tab_unselected.emit(current_device_guid)
        
        # select the tab index 
        index = self.getTabIndexForDevice(device_guid)
        if index and self.ui.devices.currentIndex() != index:
            with QtCore.QSignalBlocker(self.ui.devices):
                self.ui.devices.setCurrentIndex(index)
        
        if device_guid in self._widget_cache:
            widget = self._widget_cache[device_guid]
            if self._current_tab_widget:
                # hide the old widget
                self._current_tab_widget.setVisible(False)
                
            # show the new widget
            widget.setVisible(True)
            self._current_tab_widget = widget
            self._current_tab_device_guid = device_guid

            # tell ui a new device tab was selected
            device_name = gremlin.shared_state.get_device_name(device_guid)
            verbose = gremlin.config.Configuration().verbose_mode_detailed
            if verbose: syslog.info(f"TAB SELECT: {device_name}")
            el.tab_selected.emit(device_guid)



    def _create_tabs(self, activate_tab=None):
        """Creates the tabs of the configuration dialog representing
        the different connected devices.
        """
        try:

            device_guid = None
            # list of tab headers
            headers = []

            midi_enabled = self.config.midi_enabled
            osc_enabled = self.config.osc_enabled
            
            self._reset_tab_data()
            self.clearWidgets()

            # reload device list in case it changed
            gremlin.shared_state.reload_device_map()

            config = gremlin.config.Configuration()
            verbose_detailed = config.verbose_mode_detailed
            verbose = config.verbose


            gremlin.shared_state.is_tab_loading = True
            el = gremlin.event_handler.EventListener()
            el.push_input_selection() # prevent selections

            self.push_highlighting()



            # clear the widget map as it's recreated here
            gremlin.shared_state.device_widget_map.clear()

            self.last_tab_index = 0

            # Device lists
            phys_devices = gremlin.joystick_handling.physical_devices()
            vjoy_devices = gremlin.joystick_handling.vjoy_devices()

            self._active_devices = gremlin.joystick_handling.joystick_devices()

            # index of the current tab being addded 
            index = 0
            
            # Create physical joystick device tabs
            for device in sorted(phys_devices, key=lambda x: x.name):
                device_profile = self.profile.get_device_modes(
                    device.device_guid,
                    DeviceType.Joystick,
                    device.name
                )

                # this needs to be registered before widgets are created because widgets may need this data
                gremlin.shared_state.device_profile_map[device.device_guid] = device_profile
                gremlin.shared_state.device_type_map[device.device_guid] = DeviceType.Joystick
                tab_label = device.name.strip()
                
                device_guid = str(device.device_guid)
                widget = self.getWidget(device_guid)
                if not widget:
                    widget = gremlin.ui.device_tab.JoystickDeviceTabWidget(
                        device,
                        device_profile,
                        self.current_mode,
                    )

                    
                    self.registerWidget(device_guid, widget)

                self._add_tab(device_guid, TabDeviceType.Joystick)
                
                widget.data = (TabDeviceType.Joystick, device_guid, index)
                
                
                
                index += 1
                        

                gremlin.shared_state.device_widget_map[device_profile.device_guid] = widget

                widget.inputChanged.connect(self._device_input_changed_cb)

                # pick a default entry for each tab if one is not currently selected
                _, last_input_id = self._get_last_input(device_guid)
                if last_input_id is None:
                    # get the first input item of the tab
                    input_item = self._get_input_item(device_guid, 0)
                    if input_item:
                        input_id = input_item.input_id
                        input_type = input_item.input_type
                        gremlin.shared_state.set_last_input_id(device_guid, input_type, input_id)
                        self.config.set_last_input(device_guid, input_type, input_id)


            # add the VJOY input devices to the device tabs
            self._vjoy_input_device_guids = []

            # Create vJoy as input device tabs
            for device in sorted(vjoy_devices, key=lambda x: x.vjoy_id):
                # Ignore vJoy as output devices
                if not self.profile.settings.vjoy_as_input.get(device.vjoy_id, False):
                    continue

                device_profile = self.profile.get_device_modes(
                    device.device_guid,
                    DeviceType.Joystick,
                    device.name
                )

                device_guid = str(device.device_guid)
                widget = self.getWidget(device_guid)
                if not widget:
                    widget = gremlin.ui.device_tab.JoystickDeviceTabWidget(
                        device,
                        device_profile,
                        self.current_mode
                    )

                
                    self.registerWidget(device_guid, widget)
                    gremlin.shared_state.device_widget_map[device.device_guid] = widget
                

                
                widget.data = (TabDeviceType.VjoyInput, device_guid, index)
                self._add_tab(device_guid, TabDeviceType.VjoyInput)
                index += 1
                self._vjoy_input_device_guids.append(device_guid)


            # Create keyboard tab
            device_profile = self.profile.get_device_modes(
                dinput.GUID_Keyboard,
                DeviceType.Keyboard,
                DeviceType.to_string(DeviceType.Keyboard)
            )
            device_guid = str(dinput.GUID_Keyboard)
            widget = self.getWidget(device_guid)
            if not widget:
                widget = gremlin.ui.keyboard_device.KeyboardDeviceTabWidget(
                    device_profile,
                    self.current_mode
                )
                self.registerWidget(device_guid, widget)
                gremlin.shared_state.device_type_map[dinput.GUID_Keyboard] = DeviceType.Keyboard
                gremlin.shared_state.device_widget_map[dinput.GUID_Keyboard] = widget

            
            widget.data = (TabDeviceType.Keyboard, device_guid, index)
            self._keyboard_device_guid = device_guid
            
            
            self._add_tab(device_guid, TabDeviceType.Keyboard)
            index+=1
            

            # Create MIDI tab
            device_guid = str(gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid)
            midi_device_guid = device_guid
            if midi_enabled:
                device_profile = self.profile.get_device_modes(
                    gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid,
                    DeviceType.Midi,
                    DeviceType.to_string(DeviceType.Midi)
                )                
                widget = self.getWidget(device_guid)
                if not widget:
                    widget = gremlin.ui.midi_device.MidiDeviceTabWidget(
                        device_profile,
                        self.current_mode
                    )

                
                    self.registerWidget(device_guid, widget)
                    self._midi_device_guid = device_guid
                    
                    gremlin.shared_state.device_type_map[gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid] = DeviceType.Midi
                    gremlin.shared_state.device_widget_map[gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid] = widget
                
                widget.data = (TabDeviceType.Midi, device_guid, index)
                
                self._add_tab(device_guid,TabDeviceType.Midi)

                index+=1

                
                



            # Create OSC tab
            device_guid = str(gremlin.ui.osc_device.OscDeviceTabWidget.device_guid)
            osc_device_guid = device_guid
            if osc_enabled:
                device_profile = self.profile.get_device_modes(
                    gremlin.ui.osc_device.OscDeviceTabWidget.device_guid,
                    DeviceType.Osc,
                    DeviceType.to_string(DeviceType.Osc)
                )                
                widget = self.getWidget(device_guid)
                if not widget:
                    widget = gremlin.ui.osc_device.OscDeviceTabWidget(
                        device_profile,
                        self.current_mode
                    )
                
                

                    self.registerWidget(device_guid, widget)
                    self._osc_device_guid = device_guid
                    
                    gremlin.shared_state.device_type_map[gremlin.ui.osc_device.OscDeviceTabWidget.device_guid] = DeviceType.Osc
                    gremlin.shared_state.device_widget_map[gremlin.ui.osc_device.OscDeviceTabWidget.device_guid] = widget
                

                self._add_tab(device_guid,TabDeviceType.Osc)
                widget.data = (TabDeviceType.Osc, device_guid, index)
                
                index += 1
                


            # create mode control tab
            
            guid = gremlin.shared_state.mode_tab_guid
            device_guid = str(guid)

            device_profile = self.profile.get_device_modes(
                    guid,
                    DeviceType.ModeControl,
                    DeviceType.to_string(DeviceType.ModeControl)
                )
            
            widget = self.getWidget(device_guid)
            if not widget:
                widget = gremlin.ui.mode_device.ModeDeviceTabWidget(
                    device_profile,
                    self.current_mode
                )
                self.registerWidget(device_guid, widget)
                self._mode_device_guid = device_guid

            widget.data = (TabDeviceType.ModeControl, device_guid, index)
            self._add_tab(device_guid, TabDeviceType.ModeControl)
            

            self._vjoy_output_device_guids = []

            if self.config.show_output_vjoy:

                # Create the vjoy as output device tab
                for device in sorted(vjoy_devices, key=lambda x: x.vjoy_id):
                    # Ignore vJoy as input devices
                    if self.profile.settings.vjoy_as_input.get(device.vjoy_id, False):
                        continue

                    device_profile = self.profile.get_device_modes(
                        device.device_guid,
                        DeviceType.VJoy,
                        device.name
                    )
                    device_guid = str(device.device_guid)

                    widget = self.getWidget(device_guid)
                    if not widget:
                        widget = gremlin.ui.device_tab.JoystickDeviceTabWidget(
                            device,
                            device_profile,
                            self.current_mode
                        )
                    
                        self.registerWidget(device_guid, widget)
                        
                        gremlin.shared_state.device_widget_map[device.device_guid] = widget
                        self._vjoy_output_device_guids.append(device.device_guid)


                    widget.data = (TabDeviceType.VjoyOutput, device_guid, index)
                    
                    index += 1

                    self.ui.tab_content_layout.addWidget(widget)

                    
                    self._add_tab(device_guid, TabDeviceType.VjoyOutput)

                    
           



            # Add profile configuration tab

            device_guid = str(gremlin.shared_state.settings_tab_guid)
            device_name = gremlin.shared_state.get_device_name(device_guid)
            widget = self.getWidget(device_guid)
            if not widget:
                widget = gremlin.ui.profile_settings.ProfileSettingsWidget(
                    self.profile.settings
                )

                self.registerWidget(device_guid, widget)
                #widget.changed.connect(lambda: self._create_tabs(device_name))
                
                self._settings_device_guid = device_guid


            widget.data = (TabDeviceType.Settings, device_guid, index)
            self._add_tab(device_guid, TabDeviceType.Settings)
            
            

            # Add a plugin custom modules tab
            device_guid = str(gremlin.shared_state.plugins_tab_guid)
            widget = self.getWidget(device_guid)
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
                        device_name = gremlin.shared_state.get_device_name(device_guid)
                        syslog.info(f"\t{device_name} {device_guid}")

                    syslog.info("UI: Final reordered tabs ----------")
                    for device_guid, _, tab_type, index in reordered_data:
                        device_name = gremlin.shared_state.get_device_name(device_guid)
                        syslog.info(f"\t[{index}] {device_name} {device_guid} {tab_type}")

            
                # clear and rebuild the tabs in the new order
                self._reset_tab_data()
                for device_guid, device_name, tab_type, index in reordered_data:
                    self._add_tab(device_guid, tab_type)

                self._reindex_tabs()


            el = gremlin.event_handler.EventListener()
            el.tabs_loaded.emit()

            # select the tab that was last selected (if it exists)

            gremlin.shared_state.is_tab_loading = False
      
        except Exception as err:
            pass


        finally:
            try:
                el.pop_input_selection(reset = True) # allow selections

                # if not selected, select a default
                device_guid = self.config.last_device_guid
                if not device_guid in self._tab_device_map:
                    # the last selected device is no longer in the device list
                    device_guid = self.ui.devices.tabData(0).device_guid

                if device_guid is not None:
                    _, restore_input_type, restore_input_id = self.config.get_last_input(device_guid)
                    self._select_input(device_guid, restore_input_type, restore_input_id, force_switch=True)

                
                
                
            except Exception as err:
                pass

            self.pop_highlighting()

            if verbose_detailed: 
                syslog.info("Tab recreated:")
                for index in range(self.ui.devices.count()):
                    device_guid = self.ui.devices.tabData(index).device_guid
                    if device_guid:
                        device_name = gremlin.shared_state.get_device_name(device_guid)
                    else:
                        device_name = "(unknown)"
                    syslog.info(f"\t[{index}] {self.ui.devices.tabText(index)} {device_name}  {device_guid}")




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
            search_guid = str(search_guid) # tab map stores the GUID as a string
        tab_map = self._get_tab_map()
        data = [(device_guid, device_name, device_type, tab_index) for device_guid, device_name, device_type, tab_index in tab_map.values() if device_guid == search_guid]
        if data:
            return data[0]

        return None, None, None, None

    def _get_tab_widget_guid(self, device_guid):
        ''' gets a tab by device guid '''
        widgets = self._get_tab_widgets()
        # widget data holds (tab_type, device_guid)
        data = [widget for widget in widgets if widget.data[1] == device_guid]
        if data:
            return data[0]
        return None

    def _get_tab_index(self, device_guid):
        ''' gets the tab index for the given GUID '''
        widgets = self._get_tab_widgets()
        for index, widget in enumerate(widgets):
            if widget.data[1].casefold() == device_guid.casefold():
                return index
        return None


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
        return self._widget_cache.values()
    

    def _select_last_tab(self):
        ''' restore the last selected tab '''
        # print (f"select last tab: {self.config.last_tab_guid}")
        device_guid, input_type, input_id = self.config.get_last_input()
        eh = gremlin.event_handler.EventListener()
        eh.select_input.emit(device_guid, input_type, input_id, False, True)

    @QtCore.Slot()
    def _ui_ready(self):
        ''' UI loop is about to start '''

        # update the UI widgets that listen to inputs to disable the ones not visible 
        device_guid, input_type, input_id = self.config.get_last_input()
        el = gremlin.event_handler.EventListener()
        el.tab_unselected.emit(None)
        el.tab_selected.emit(device_guid)

        # enable highlighting
        self.pop_highlighting(True)

        
        # update status nar
        self._update_mode_status_bar()
        # startup setups
        el.toggle_highlight.emit(self.is_autoswitch_highlighting, self.is_axis_highlighting, self.is_button_highlighting)



    def _select_last_input(self):
        # if there is a last input - select that input as well
        device_guid, input_type, input_id = self.config.get_last_input()
        if input_type and input_id:
            eh = gremlin.event_handler.EventListener()
            eh.select_input.emit(device_guid, input_type, input_id, False, True)

    def _get_device_name(self, device_guid):
        ''' gets the name of the specified device '''
        return gremlin.shared_state.get_device_name(device_guid)

    def _get_last_input(self, device_guid : str) -> tuple:
        ''' Gets the last input selection for the given device

        If there was no prior selection, the first input for the device is returned.
        If there is no first input because it's empty, return None.

        :param: device_guid id of the device to get as a string
        :returns: (input_type, Input_id)

        '''
        input_type, input_id = gremlin.shared_state.last_input_id(device_guid)
        if not input_type:
            # pick the first input for that tab
            widget = self._get_tab_widget_guid(device_guid)
            input_item: gremlin.base_profile.InputItem = self._get_input_item(device_guid, 0)
            if input_item:
                return (input_item.input_type, input_item.input_id)
        return (None, None)

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
        items = self._get_input_items(device_guid)
        if items:
            return next((item for item in items if item.input_id == input_id and item.input_type == input_type), None)
        return None
        

    def _select_input(self, device_guid, input_type : InputType = None, input_id = None, force_update = False, force_switch = False):
        eh = gremlin.event_handler.EventListener()
        eh.select_input.emit(device_guid, input_type, input_id, force_update, force_switch)


    def _config_changed_cb(self):
        ''' called when configuraition has changed '''
        self.refresh()

    def _select_input_handler(self, device_guid : dinput.GUID, restore_input_type : gremlin.input_types.InputType = None, restore_input_id = None, force_update : bool = False, force_switch = False):
        ''' Selects a specific input on the given tab
        The tab is changed if different from the current tab.

        :params:
        device_guid = the device ID as a string or a Dinput GUID
        input_type = InputType enum or none to auto determine
        input_id = id of the input, none to auto determine


        '''

      

        verbose = gremlin.config.Configuration().verbose_mode_inputs
        verbose = True


        el = gremlin.event_handler.EventListener()
        if el.input_selection_suspended:
            # ignore selection requests if selection is suspended
            return

        if self._selection_locked:
            return
        
        # avoid spamming
        if not force_update and self._last_input_change_timestamp + self._input_delay > time.time():
                # delay not occured yet
                return
        self._last_input_change_timestamp = time.time()

        
        syslog = logging.getLogger("system")
        input_id = restore_input_id
        input_type = restore_input_type

        switch_enabled = self.is_autoswitch_highlighting
        s_device_guid = str(device_guid)
        if not force_switch and self._current_tab_device_guid != s_device_guid and not switch_enabled:
            if verbose:
                syslog.info(f"Select input event: {device_guid} {self._get_device_name(device_guid)} disabled: highlight switch is disabled)")
            return


        try:


            self._selection_locked = True

            self.push_highlighting()
            
            el.push_joystick() # suspend joystick input while changing UI

            
            if not isinstance(device_guid, str):
                device_guid = str(device_guid)


            # index of current device tab
            index = self.ui.devices.currentIndex()
            current_device_guid = self._current_tab_device_guid

            # make the content visible
            self.selectTabWidget(device_guid)
            
            # see if the request input is found
            input_item = self._find_input_item(device_guid, input_type, input_id)
            if input_item is None:
                # not found
                input_item = self._get_input_item(device_guid, 0)

            if input_item:
                input_type = input_item.input_type
                input_id = input_item.input_id

            if verbose:
                syslog.info(f"Select input event: {device_guid} {self._get_device_name(device_guid)} input: {InputType.to_display_name(input_type)} input ID: {input_id}  current mode: {gremlin.shared_state.current_mode}")


            # guid of current device tab

            if not current_device_guid or current_device_guid.casefold() != device_guid.casefold():
                # change tabs
                if verbose: syslog.info("Tab change requested")
                index = self._find_tab_index(device_guid)
                if index is not None:
                    with QtCore.QSignalBlocker(self.ui.devices):
                        self.ui.devices.setCurrentIndex(index)
                    if verbose: syslog.info("Tab change complete")

            if input_id is None:
                # get the default item to select
                if verbose: syslog.info(f"Select input: last input ID {input_id} not found - selecting default input ID")
                last_device_guid, last_input_type, input_id  = self.config.get_last_input(device_guid)
                if verbose: syslog.info(f"Select input: found {last_device_guid} {last_input_type} {input_id} ")
                if input_id is None:
                    input_item = self._get_input_item(device_guid, 0)
                    if input_item and self._last_input_item != input_item:
                        
                        
                        input_id = input_item.input_id
                        input_type = input_item.input_type
                        gremlin.shared_state.set_last_input_id(device_guid, input_type , input_id)
                        self.config.set_last_input(device_guid, input_type, input_id)
                        last_device_guid = device_guid
                        last_input_type = input_type
                        if verbose: syslog.info(f"Select input: defaulting to first item on list {last_device_guid} {last_input_type} {input_id} ")

                        self._last_input_item = input_item
                        



            if input_id is not None: 
                # within the inputs = select it
                #syslog.info("ID change started")
                widget = self.getWidget(device_guid)
                if widget:
                    if verbose: syslog.info(f"Select input: select widget {input_type} {input_id}")
                    widget.input_item_list_view.select_input(input_type, input_id, force_update = force_update)
                    index = widget.input_item_list_view.current_index
                    widget.input_item_list_view.redraw_index(index)
                    if verbose: syslog.info(f"Select input: selected widget {input_type} {input_id}")

                # remember the last input id
                self._current_tab_input_id = input_id


            # save settings as the last input
            current_device_guid, current_input_type, current_input_id = gremlin.shared_state.get_last_input_id()
            if current_device_guid != device_guid or current_input_type != input_type or current_input_id != input_id:
                gremlin.shared_state.set_last_input_id(device_guid, input_type, input_id)

        finally:
            self._selection_locked = False
            self.pop_highlighting()
            el.pop_joystick() # restore joystick input while changing UI



    def _find_tab_index(self, search_guid : str):
        tab_map = self._get_tab_map()
        if not isinstance(search_guid, str):
            search_guid = str(search_guid)
        for device_guid, device_name, device_class, tab_index in tab_map.values():
            if device_guid.casefold() == search_guid.casefold():
                # print (f"Found tab index {tab_index} for guid {search_guid} {device_name}")
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
        index = self.ui.devices.currentIndex()
        widget = self.ui.devices.widget(index)
        if hasattr(widget, "input_item_list_view"):
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
        log = logging.getLogger("system")
        for index, (device_guid, device_name, device_class, tab_index) in tab_map.items():
            log.info(f"[{index}] Tab index: [{tab_index}] {device_name} {device_class} {device_guid}")

    def _refresh_tab(self):
        ''' refreshes the current device tab '''
        current_widget = self._current_tab_widget
        if current_widget and hasattr(current_widget,"refresh"):
            current_widget.refresh()



    def _sort_tabs(self):
        ''' sorts device tabs by default order name '''

        # sorted list of item GUIDs
        guid_list = []
        tab_map = self._get_tab_map()
        if self.config.verbose_mode_details:
            self._dump_tab_map(tab_map)

        joystick_devices = self._find_joystick_tab_data()
        joystick_devices.sort(key=lambda x: x[1].casefold())
        guid_list.extend(joystick_devices)

        config = gremlin.config.Configuration()

        # add the Keyboard, OSC and MIDI
        guid_list.append(self._find_tab_data_guid(self._keyboard_device_guid))
        if config.midi_enabled:
            guid_list.append(self._find_tab_data_guid(self._midi_device_guid))
        if config.osc_enabled:
            guid_list.append(self._find_tab_data_guid(self._osc_device_guid))

        # add the input vjoy
        for device_guid in self._vjoy_input_device_guids:
            guid_list.append(self._find_tab_data_guid(device_guid))

        # add the output vjoy
        for device_guid in self._vjoy_output_device_guids:
            guid_list.append(self._find_tab_data_guid(device_guid))

        # add the settings tab
        guid_list.append(self._find_tab_data_guid(self._settings_device_guid))

        # add the user plugin tab
        guid_list.append(self._find_tab_data_guid(self._plugins_device_guid))


        # move the tabs to the correct location
        for index, (device_guid, device_name, device_type, tab_index) in enumerate(guid_list):
            tab_index = self._get_tab_index(device_guid)
            if tab_index is not None:
                self.ui.devices.moveTab(tab_index, index)

        tab_map = self._get_tab_map()
        if self.config.verbose_mode_details:
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

        icon = load_icon("gfx/profile_open.svg")
        #icon = self.load_icon("profile_open.svg"))
        self.ui.actionLoadProfile.setIcon(icon)

        icon = load_icon("gfx/profile_new.svg")
        self.ui.actionNewProfile.setIcon(icon)

        icon = load_icon("gfx/profile_save.svg")
        self.ui.actionSaveProfile.setIcon(icon)

        icon = load_icon("gfx/profile_save_as.svg")
        self.ui.actionSaveProfileAs.setIcon(icon)

        icon = load_icon("gfx/device_information.svg")
        self.ui.actionDeviceInformation.setIcon(icon)

        icon = load_icon("gfx/manage_modules.svg")
        self.ui.actionManageCustomModules.setIcon(icon)

        icon = load_icon("gfx/manage_modes.svg")
        self.ui.actionManageModes.setIcon(icon)

        icon = load_icon("gfx/input_repeater.svg")
        self.ui.actionInputRepeater.setIcon(icon)

        # icon = load_icon("gfx/calibration.svg")
        # self.ui.actionCalibration.setIcon(icon)

        icon = load_icon("gfx/input_viewer.svg")
        self.ui.actionInputViewer.setIcon(icon)

        icon = load_icon("gfx/logview.png")
        self.ui.actionLogDisplay.setIcon(icon)

        icon = load_icon("gfx/options.svg")
        self.ui.actionOptions.setIcon(icon)

        icon = load_icon("gfx/about.svg")
        self.ui.actionAbout.setIcon(icon)


        # Toolbar actions

        pixmap_off = load_pixmap("gfx/activate.svg")
        pixmap_on = load_pixmap("gfx/activate_on.svg")
        if pixmap_off and pixmap_on:
            activate_icon = QtGui.QIcon()
            activate_icon.addPixmap(pixmap_off, QtGui.QIcon.Normal)
            activate_icon.addPixmap(pixmap_on, QtGui.QIcon.Active, QtGui.QIcon.On)
            self.ui.actionActivate.setIcon(activate_icon)
        else:
            self.ui.actionActivate.setText("Run")

        self.ui.actionOpen.setIcon(load_icon("gfx/profile_open.svg"))

        self.ui.actionSave.setIcon(load_icon("fa5s.save"))


    # +---------------------------------------------------------------
    # | Signal handlers
    # +---------------------------------------------------------------


    def _device_change_cb(self):
        """Handles addition and removal of joystick devices."""
        # Update device tabs

        # record the device change
        self._device_change_queue +=1
        #print (f"device change detected {self._device_change_queue}")

        if not self.device_change_locked:
            self.device_change_locked = True
            while self._device_change_queue > 0:
                verbose = gremlin.config.Configuration().verbose
                try:
                    syslog =logging.getLogger("system")
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
                                if self._current_tab_device_guid == str(device_guid):
                                    self._current_tab_device_guid = None
                                    self._current_tab_widget = None

                    self._create_tabs()

                    # Stop Gremlin execution

                    self.ui.actionActivate.setChecked(False)
                    restart = self.runner.is_running()
                    if restart:
                        logging.getLogger("system").info(f"Profile restart due to device change")
                    self.activate(restart)
                finally:

                    if verbose:
                        logging.getLogger("system").info(f"Device change end")
                    self.device_change_locked = False
                # mark items processed
                self._device_change_queue = 0


    @QtCore.Slot()
    def _device_input_changed_cb(self, device_guid, input_type, input_id):
        ''' called when device input changed '''
        gremlin.shared_state.set_last_input_id(device_guid, input_type, input_id)


    def _tab_moved_cb(self, tab_from, tab_to):
        ''' occurs when a tab is moved '''
        # persist tab order
        print (f"tab move detected {tab_from} {tab_to}")
        # rebuild the tab order
        self._reindex_tabs()
        # update new order
        self.config.tab_list = self._get_tab_map()
        index = self.ui.devices.currentIndex()
        device_guid = self.ui.devices.tabData(index).device_guid
        _, restore_input_type, restore_input_id = self.config.get_last_input(device_guid)
        self._select_input(device_guid = device_guid, input_type = restore_input_type, input_id = restore_input_id, force_update =True, force_switch=True)




    def _edit_mode_changed_cb(self, new_mode):
        """Updates the current mode to the provided one.

        :param new_mode the name of the new current mode
        """

        # refresh the modes
        eh = gremlin.event_handler.EventHandler()
        eh.change_mode(new_mode)




    def _process_changed_cb(self, new_process_path):
        """Handles changes in the active windows process focus

        If the active process has a known associated profile it is
        loaded and activated. If none exists and the user has not
        enabled the option to keep the last profile active, the current
        profile is disabled,

        :param path the path to the currently active process executable
        """

        config = gremlin.config.Configuration()

        verbose = gremlin.config.Configuration().verbose_mode_process
        syslog = logging.getLogger("system")

        # check options
        option_auto_load = config.autoload_profiles
        option_auto_load_on_focus = config.activate_on_process_focus

        
        process_base = os.path.basename(new_process_path)
        if not option_auto_load:
            if verbose:
                syslog.info(f"PROC: Process focus change detected: {process_base}  autoload: {option_auto_load}  auto load on focus: {option_auto_load_on_focus}: change profile on process change option is disabled - skipping")
            return # ignore if not auto loading profiles or auto activating on focus change


        if verbose:
            syslog.info(f"PROC: Process focus change detected: {process_base}  autoload: {option_auto_load}  auto load on focus: {option_auto_load_on_focus} - processing change")

        option_keep_focus = config.keep_profile_active_on_focus_loss
        option_reset_mode_on_process_activate = config.reset_mode_on_process_activate
        eh = gremlin.event_handler.EventHandler()

       

        # see if we have a mapping entry for this executable
        profile_item = self._profile_map.get_map(new_process_path)

        profile_path = profile_item.profile if profile_item else None
        profile_change = False # assume no profile change
        #print (f"Profile: {profile_item}")
        mode = None # assume no mode change needed


        
        if verbose:
            if profile_path:
                syslog.info(f"PROC: found profile map [{os.path.basename(profile_path)}] for process {process_base} - current profile: [{self.profile.name}]  runtime mode: [{gremlin.shared_state.runtime_mode}]")
            else:
                syslog.info(f"PROC: no profile mapping found for process [{process_base}]  [full process: {new_process_path.replace("/","\\")}] - current profile: [{self.profile.name}]  runtime mode: [{gremlin.shared_state.runtime_mode}]")

        if profile_path:
            # profile entry found - see if we need to change profiles
            profile_base = os.path.basename(profile_path)
            if not compare_path(self.profile.profile_file, profile_path):
                
                # deactivate
                self.activate(False) # this saves the current profile runtime mode
                self.ui.actionActivate.setChecked(False)

                # remember the last mode
                self._runtime_mode_map[self.profile.profile_file] = gremlin.shared_state.runtime_mode

                # change profile
                if verbose:
                    syslog.info(f"PROC: process change: switch profile needed from [{os.path.basename(self.profile.profile_file)}] ->  [{os.path.basename(profile_path)}]")

                

                if verbose:
                    syslog.info(f"PROC: process change: save runtime mode  [{gremlin.shared_state.runtime_mode}] for [{os.path.basename(self.profile.profile_file)}]")
                
                
                # load the new profile
                self._do_load_profile(profile_path)
                self.ui.actionActivate.setChecked(True)
                self.activate(True) # this will also restore the profile runtime mode based on current options

                self._profile_auto_activated = True # remember the profile was auto activated by virtue of a process change
                profile_change = True

                # figure out which mode to restore mode for the new profile
                if verbose:
                    syslog.info(f"PROC: profile change: [{self.profile.name}] profile restore mode flag: [{self.profile.get_restore_mode()}], global restore mode flag: [{config.restore_profile_mode_on_start}]")


            else:
                mode = self.profile.get_last_runtime_mode()
                if verbose: syslog.info(f"PROC: profile change: [{profile_base}] is already activated - current mode: [{mode}]")


            # see if we need to activate the profile
            if option_auto_load_on_focus and not self.runner.is_running():
                self._profile_auto_activated = True # remember the profile was auto activated by virtue of a process change
                if verbose:
                    syslog.info(f"PROC: profile focus: [{profile_base}] auto activate")
                # auto activate
                self.ui.actionActivate.setChecked(True)
                self.activate(True)


                option_restore_mode = config.restore_profile_mode_on_start or gremlin.shared_state.current_profile.get_restore_mode()
                if option_restore_mode:
                    # get the mode to restore
                    mode = self.profile.get_last_runtime_mode()
                    if verbose:
                        syslog.info(f"PROC: profile focus: [{profile_base}] restore last mode: [{mode}] ")


            # a mapping profile was found - new profile was loaded if needed - see if we need to change the mode
            reset_mode = (profile_change or option_reset_mode_on_process_activate and profile_item.default_mode)
            # print (f"reset mode: {reset_mode}  reset on activate: {option_reset_mode_on_process_activate}  profile mode: '{profile_item.default_mode}'  current mode: '{self.current_mode}'")
            if not mode and reset_mode:
                # use the default mode specified in the process mapping when changing profiles
                mode = profile_item.default_mode
                if verbose:
                    syslog.info(f"PROC: profile mode check: [{os.path.basename(profile_path)}] using mode: [{mode}] ")

            # see if the profile activation has a new mapping
            if mode is None or not mode in self.profile.get_modes():
                # restore the profile's default mode on activation
                default_mode = self.profile.get_default_mode()
                if verbose:
                    logging.getLogger("system").info(f"PROC: profile mode check: [{os.path.basename(profile_path)}]  mode [{mode}] was not found, restoring default mode: [{default_mode}] ")
                mode = default_mode

            if mode is not None:
                eh = gremlin.event_handler.EventHandler()
                if verbose:
                    logging.getLogger("system").info(f"PROC: profile mode check: [{os.path.basename(profile_path)}]  change mode change to: '{mode}' ")
                eh.change_mode(mode, force_update = True) # set the selected mode - note that this may fail if mode locking is enabled



        elif self._profile_auto_activated and not option_keep_focus:
            # deactivate the profile if it was autoloaded
            self.ui.actionActivate.setChecked(False)
            self.activate(False)
            self._profile_auto_activated = False
            if verbose:
                current_profile = gremlin.shared_state.current_profile
                if current_profile:
                    logging.getLogger("system").info(f"PROC: keep focus not set - deactivated profile {current_profile.name}")

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

    def _update_status_bar(self, event):
        # updates the status bar


        """Updates the status bar with the current state of the system.

        :param is_active True if the system is active, False otherwise
        """
        try:
            if self._is_active:
                text_active = "<font color=\"green\">Active</font>"
            else:
                text_active = "<font color=\"red\">Paused</font>"
            if self.ui.actionActivate.isChecked():
                text_running = f"Running and {text_active}"
            else:
                text_running = "Not Running"

            # remote control status
            if event.is_local:
                local_msg = "<font color=\"green\">Active</font>"
            else:
                local_msg = "<font color=\"red\">Disabled</font>"
            if event.is_remote:
                remote_msg = "<font color=\"green\">Active</font>"
            else:
                remote_msg = "<font color=\"red\">Disabled</font>"

            self.status_bar_is_active_widget.setText(f"<b>Status:</b> {text_running} <b>Local Control</b> {local_msg} <b>Broadcast:</b> {remote_msg}")
            self._update_mode_status_bar()

        except e:
            log_sys_error(f"Unable to update status bar event: {event}")
            log_sys_error(e)

    def _update_mode_change(self, new_mode):
        self._update_ui_mode(new_mode)
        # self._mode_configuration_changed(new_mode)

    def _update_mode_status_bar(self):
        ''' updates the mode status bar with current runtime and edit modes '''
        try:

            is_running = gremlin.shared_state.is_running
            runtime_mode = gremlin.shared_state.runtime_mode
            edit_mode = gremlin.shared_state.edit_mode
            if not edit_mode:
                # get it from the mode drop down
                edit_mode = self.mode_selector.currentMode()

            msg = f"<b>Runtime Mode:</b> {runtime_mode if runtime_mode else "n/a"}"
            if not is_running:
                msg += f" <b>Edit Mode:</b> {edit_mode if edit_mode else "n/a"}"

            self.status_bar_mode_widget.setText(msg)
            if self.config.mode_change_message:
                self.ui.tray_icon.showMessage(f"Runtime Mode: {runtime_mode if runtime_mode else "n/a"} Edit mode: {edit_mode if edit_mode else "n/a"}","",QtWidgets.QSystemTrayIcon.MessageIcon.NoIcon,250)
        except Exception as err:
            log_sys_error(f"Unable to update status bar mode:\n{err}")


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


    def _kb_event_cb(self, event):
        ''' listen for keyboard modifiers and keyboard events at runtime '''

        key = gremlin.keyboard.KeyMap.from_event(event)

        # ignore if we're running
        if key is None or self.runner.is_running() or gremlin.shared_state.ui_keyinput_suspended():
            return

        if key.lookup_name == "f5":
            # activate mode on F5
            if not self.config.is_debug:
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

    def apply_user_settings(self, ignore_minimize=False):
        """Configures the program based on user settings."""

        # gamepad count
        gremlin.gamepad_handling.gamepad_reset()

        self._set_joystick_input_highlighting(
            self.config.highlight_input_axis
        )
        self._set_joystick_input_buttons_highlighting(self.config.highlight_input_buttons)
        if not ignore_minimize:
            self.setHidden(self.config.start_minimized)
        # if self.config.autoload_profiles:
        #     self.process_monitor.start()
        # else:
        #     self.process_monitor.stop()

        if self.config.activate_on_launch:
            self.ui.actionActivate.setChecked(True)
            self.activate(True)

    def apply_window_settings(self):
        """Restores the stored window geometry settings."""
        window_size = self.config.window_size
        window_location = self.config.window_location
        if window_size:
            self.resize(window_size[0], window_size[1])
        if window_location:
            self.move(window_location[0], window_location[1])

    def _create_cheatsheet(self):
        """Creates the cheatsheet and stores it in the desired place.

        :param file_format the format of the cheatsheet, html or pdf
        """
        import gremlin.cheatsheet
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save cheatsheet",
            gremlin.util.userprofile_path(),
            "PDF files (*.pdf)"
        )
        if len(fname) > 0:
            gremlin.cheatsheet.generate_cheatsheet(fname, self.profile)

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


    def _do_load_profile(self, fname):
        """Load the profile with the given filename.

        :param fname the name of the profile file to load
        """
        # Disable the program if it is running when we're loading a
        # new profile

        pushCursor()

        self.ui.actionActivate.setChecked(False)
        self.activate(False)

        el = gremlin.event_handler.EventListener()
        el.profile_unloaded.emit() # tell the UI we're about to load a new profile

        el.push_input_selection() # suspend input selection

           # Attempt to load the new profile
        try:
            new_profile = gremlin.base_profile.Profile()
            if gremlin.shared_state.current_profile:
                el.profile_unload.emit()

            gremlin.shared_state.current_profile = new_profile
            profile_updated = new_profile.from_xml(fname)

            profile_folder = os.path.dirname(fname)
            if profile_folder not in sys.path:
                sys.path = list(self._base_path)
                sys.path.insert(0, profile_folder)

            self._sanitize_profile(new_profile)



            last_edit_mode = gremlin.config.Configuration().get_profile_last_edit_mode()
            if not last_edit_mode:
                # pick the top mode if nothing was saved in the configuration
                last_edit_mode = self.profile.get_root_mode()
                gremlin.config.Configuration().set_profile_last_edit_mode(last_edit_mode)

            # if self.profile.get_restore_mode():
            #     # restore profile mode when loading is selected
            #     last_runtime_mode = gremlin.config.Configuration().get_profile_last_runtime_mode()
            #     if not last_runtime_mode:
            #         last_runtime_mode = self.profile.get_root_mode()
            #     if last_runtime_mode:
            #         syslog.info("PROFILE: restore last runtime mode on profile load is selected")
            #         gremlin.config.Configuration().set_profile_last_runtime_mode(last_runtime_mode)

            modes = new_profile.get_modes()
            if not last_edit_mode in modes:
                # no longer in the current mode list
                last_edit_mode = new_profile.get_default_mode()
            # if not last_runtime_mode in modes:
            #     last_runtime_mode = new_profile.get_default_mode()



            eh = gremlin.event_handler.EventHandler()
            # eh.set_runtime_mode(last_runtime_mode)
            eh.set_edit_mode(last_edit_mode)

            current_mode = gremlin.shared_state.current_mode

            self._create_tabs()

            # Make the first root node the default active mode
            self.mode_selector.populate_selector(new_profile, current_mode, emit = True)


            # Save the profile at this point if it was converted from a prior
            # profile version, as otherwise the change detection logic will
            # trip over insignificant input item additions.
            if profile_updated:
                new_profile.to_xml(fname)

            # ask the UI to update input curve icons
            el.update_input_icons.emit()




        except (KeyError, TypeError) as error:
            # An error occurred while parsing an existing profile,
            # creating an empty profile instead
            logging.getLogger("system").exception(f"Invalid profile content:\n{error}")
            self.new_profile()
        except gremlin.error.ProfileError as error:
            # Parsing the profile went wrong, stop loading and start with an
            # empty profile
            cfg = gremlin.config.Configuration()
            cfg.last_profile = None
            self.new_profile()
            gremlin.util.display_error(f"Failed to load the profile {fname} due to:\n\n{error}")

        finally:

            
            el.profile_loaded.emit()

            # update the status bar
            self._update_mode_status_bar()
            self._update_window_title()

            # restore the mouse cursor
            popCursor()

            el.pop_input_selection(True) # restore input selection and reset
            # restore the last selection for this profile
            config = gremlin.config.Configuration()
            
            device_guid, restore_input_type, restore_input_id = config.get_last_input()
            # syslog.info(f"LOAD: restore last selection: {device_guid} {restore_input_type} {restore_input_id}")
            self._select_input(device_guid, restore_input_type, restore_input_id, force_update=True)



    def refresh(self):
        ''' refresh the UI '''
        self._create_tabs()

        current_profile =gremlin.shared_state.current_profile
        current_mode = gremlin.shared_state.current_mode



        # Make the first root node the default active mode
        self.mode_selector.populate_selector(current_profile, current_mode, emit = False)
        self._update_mode_status_bar()


        # refresh current device tab
        self._refresh_tab()


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
        syslog = logging.getLogger("system")
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
            last_mode = self.profile.get_default_mode()
            syslog.info(f"\tusing profile default start mode [{last_mode}]")
        
        mode_list = gremlin.profile.mode_list(self.profile)

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

    def _modes_changed(self):
        ''' called when mode list has changed '''
        self.mode_selector.populate_selector(gremlin.shared_state.current_profile, gremlin.shared_state.current_mode)
        self._update_mode_status_bar()

    # def _mode_configuration_changed(self, new_mode = None):
    #     """Updates the mode configuration of the selector and profile."""

    #     logging.getLogger("system").warn("skipping mode config change event")
    #     return

    #     try:
    #         gremlin.util.pushCursor()

    #         if new_mode is None:
    #             new_mode = gremlin.shared_state.current_mode

    #         # if gremlin.shared_state.current_mode == new_mode:
    #         #     return
    #         widget = self.ui.devices.widget(self.ui.devices.count()-1)
    #         if hasattr(widget,"refresh_ui"):
    #             widget.refresh_ui()
    #         self._select_last_input() # restore the last input on mode change if possible

    #     finally:
    #         gremlin.util.popCursor()

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
        self._input_highlighting_enabled = is_enabled


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
        ''' true if button highlighting is currently enabled '''
        if not self.config.highlight_enabled:
            return False
        if self._input_highlight_stack > 0:
            # suspended
            return False
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False
        
        el = gremlin.event_handler.EventListener()
        is_hotkey_autoswitch = self.config.highlight_hotkey_autoswitch
        is_shifted = el.get_shifted_state() if is_hotkey_autoswitch else False
        return self.config.highlight_input_buttons or is_shifted or self._button_highlighting_enabled
    
    @property
    def is_axis_highlighting(self) -> bool:
        ''' true if button highlighting is currently enabled '''
        if not self.config.highlight_enabled:
            return False
        if self._input_highlight_stack > 0:
            # suspended
            return False
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False
        
        
        el = gremlin.event_handler.EventListener()
        is_hotkey_autoswitch = self.config.highlight_hotkey_autoswitch
        is_control = el.get_shifted_state() if is_hotkey_autoswitch else False
        return self.config.highlight_input_axis or is_control or self._axis_highlighting_enabled
    
    @property
    def is_autoswitch_highlighting(self) -> bool:
        ''' true if tab switch highlighting is enabled '''
        if not self.config.highlight_enabled:
            return False
        if self._input_highlight_stack > 0:
            # suspended
            return False
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False
        
        return self.config.highlight_autoswitch

    def push_highlighting(self):
        ''' disables the highlighting of devices '''
        self._input_highlight_stack +=1

    def pop_highlighting(self, reset = False):
        ''' enables the highlighting of devices '''
        if reset:
            self._input_highlight_stack = 0
        elif self._input_highlight_stack > 0:
            self._input_highlight_stack -=1




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

    # blitz the log file
    log_file = config["logfile"]
    try:
        if os.path.isfile(log_file):
            os.unlink(log_file)
    except:
        pass
    logger = logging.getLogger(config["name"])
    logger.setLevel(config["level"])
    handler = logging.FileHandler(config["logfile"])
    handler.setLevel(config["level"])
    formatter = logging.Formatter(config["format"], "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logger.debug("-" * 80)
    logger.debug(time.strftime("%Y-%m-%d %H:%M"))
    logger.debug(f"Starting {APPLICATION_NAME} {APPLICATION_VERSION}")
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
    logging.getLogger("system").error(msg)
    gremlin.util.display_error(msg)



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        help="Path to the profile to load on startup",
    )
    parser.add_argument(
        "--enable",
        help="Enable Joystick Gremlin upon launch",
        action="store_true"
    )
    parser.add_argument(
        "--start-minimized",
        help="Start Joystick Gremlin minimized",
        action="store_true"
    )
    args = parser.parse_args()

    gremlin.shared_state.ui_ready = False

        # Configure logging for system and user events
    configure_logger({
        "name": "system",
        "level": logging.DEBUG,
        "logfile": os.path.join(gremlin.util.userprofile_path(), "system.log"),
        "format": "%(asctime)s %(levelname)10s %(message)s"
    })
    configure_logger({
        "name": "user",
        "level": logging.DEBUG,
        "logfile": os.path.join(gremlin.util.userprofile_path(), "user.log"),
        "format": "%(asctime)s %(message)s"
    })

    # Path manging to ensure Gremlin starts independent of the CWD
    sys.path.insert(0, gremlin.util.userprofile_path())
    gremlin.util.setup_userprofile()

    # Fix some dumb Qt bugs
    QtWidgets.QApplication.addLibraryPath(os.path.join(
        os.path.dirname(PySide6.__file__),
        "plugins"
    ))



    syslog = logging.getLogger("system")

    syslog.info(F"Joystick Gremlin Ex version {Version().version}")

    # Initialize the vjoy interface
    from vjoy.vjoy_interface import VJoyInterface
    VJoyInterface.initialize()

    # Initialize the direct input interface class
    from dinput import DILL
    DILL.init()
    DILL.initialize_capi()
    logging.getLogger("system").info(f"Found DirectInput Interface version {DILL.version}")

    # Show unhandled exceptions to the user when running a compiled version
    # of Joystick Gremlin
    executable_name = os.path.split(sys.executable)[-1]
    if executable_name == "joystick_gremlin.exe":
        sys.excepthook = exception_hook

    # Initialize HidGuardian before we let SDL grab joystick data
    import gremlin.hid_guardian
    hg = gremlin.hid_guardian.HidGuardian()
    hg.add_process(os.getpid())

    # Create user interface
    app_id = u"joystick.gremlinex"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


    # disable dark mode for now while we sort icons in a future version
    os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"

    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(load_icon("gfx/icon.png"))
    app.setApplicationDisplayName(APPLICATION_NAME + " " + APPLICATION_VERSION)
    app.setApplicationVersion(APPLICATION_VERSION)
    app.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling)

    # handle windows themes better
    app.setStyle('Fusion')

    # Ensure joystick devices are correctly setup
    dinput.DILL.init()
    time.sleep(0.25)
    gremlin.joystick_handling.joystick_devices_initialization()

    # check for gamepad availability via VIGEM
    if gremlin.gamepad_handling.gamepadAvailable():
        gremlin.gamepad_handling.gamepad_initialization()


    # Check if vJoy is properly setup and if not display an error
    # and terminate GremlinEx
    try:
        syslog.info("Checking vJoy installation")
        vjoy_count = len([dev for dev in gremlin.joystick_handling.joystick_devices() if dev.is_virtual])
        vjoy_working = vjoy_count != 0
        logging.getLogger("system").info(f"\tFound {vjoy_count} vjoy device(s)")

        if not vjoy_working:
            msg = "No configured VJOY devices were found<br>This could be related to a different error scanning devices, check log in verbose mode"
            logging.getLogger("system").error(msg)
            gremlin.ui.ui_common.MessageBox("Error Scanning Devices", msg)
            # raise gremlin.error.GremlinError(msg)

    except (gremlin.error.GremlinError, dinput.DILLError) as e:
        error_display = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Critical,
            "Error",
            e.value,
            QtWidgets.QMessageBox.Ok
        )
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

    # Create Gremlin UI
    ui = GremlinUi()
    gremlin.shared_state.ui = ui

    syslog.info("GremlinEx UI created")

    # Handle user provided command line arguments
    if args.profile is not None and os.path.isfile(args.profile):
        ui._do_load_profile(args.profile)
    if args.enable:
        ui.ui.actionActivate.setChecked(True)
        ui.activate(True)
    if args.start_minimized:
        ui.setHidden(True)

    # automatic process monitoring check
    pmgr = gremlin.process_monitor.ProcessMonitor()
    el = gremlin.event_handler.EventListener()
    el.process_monitor_changed.emit()


    # Run UI
    syslog.info("GremlinEx UI launching")
    gremlin.shared_state.ui_ready = True

    el.ui_ready.emit()

    try:
        app.exec()
    except Exception as err:
        syslog.error(traceback.format_exc())

    syslog.info("GremlinEx UI terminated")



    # Terminate potentially running EventListener loop
    gremlin.joystick_handling.VJoyProxy.reset()
    el = gremlin.event_handler.EventListener()
    el.terminate() # terminates and sends the relevant shutdown triggers
    

    if vjoy_working:
        # Properly terminate the runner instance should it be running
        ui.runner.stop()

    # Relinquish control over all VJoy devices used
    gremlin.joystick_handling.VJoyProxy.reset()

    hg.remove_process(os.getpid())

    syslog.info("Terminating GremlinEx")
    sys.exit(0)