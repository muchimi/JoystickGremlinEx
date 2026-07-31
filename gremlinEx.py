# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - GremlinEx is (C) EMCS 2026
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

# # ruff: disable[E401]
from __future__ import annotations  # deprecated with python 3.14+

# ruff: disable[F401]
import faulthandler
import ctypes
import logging
import os
import subprocess
import sys
import time
import trace
import uuid
import traceback
import threading
from threading import Lock
from typing import Callable
from collections.abc import Iterator
import webbrowser


import filelock

from objprint.executing.executing import lock
import dinput
from dinput import DeviceSummary
import PySide6
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QThread, QTimer, Signal
from gremlin.types import TabDeviceType, DeviceType, DeviceCategory
from shiboken6 import Shiboken
import gremlin.tabstate
import win32api
import win32con
import gremlin.joystick_handling
import gremlin.util
import gremlin.input_types
import gremlin.event_handler
import gremlin.base_classes
import gremlin.remote
import gremlin.raw_input
import gremlin.config
import gremlin.joystick_handling
import gremlin.input_devices
import gremlin.hid
import gremlin.process
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
import gremlin.input_item
import gremlin.plugin_manager
import gremlin.process
import gremlin.execution_graph
import gremlin.gamepad_handling
import gremlin.import_profile
import gremlin.windows_event_hook  # reference needed for packaging
import gremlin.macro_handler  # reference needed for packaging
import gremlin.ui.octavi_device
import gremlin.ui.virpil_device
import gremlin.sound
import gremlin.ktts
from gremlin.worker import WorkManager
import gremlin.maestro


# Import QtMultimedia so pyinstaller doesn't miss it


from gremlin.input_types import InputType
import gremlin.types

from gremlin.util import load_icon, find_file
import gremlin.shared_state
import gremlin.base_profile
import gremlin.event_handler
import gremlin.config


import gremlin.code_runner

import gremlin.keyboard
import gremlin.process
import gremlin.code_runner
import gremlin.repeater
import gremlin.base_profile

# imports needed by pyinstaller to be included
import gremlin.control_action


import gremlin.tts

from gremlin.util import log_sys_error, compare_path
import gremlin.util
import graphviz


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
from shiboken6 import Shiboken

from gremlin.input_item import InputItem, InputItemWidget, BaseDeviceTabWidget


from gremlin.ui.ui_gremlin import Ui_Gremlin


import gremlin.reporting
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.tabstate import TabData

from logging.handlers import RotatingFileHandler

syslog = logging.getLogger("system")


# Figure out the location of the code / executable and change the working
# directory accordingly
install_path = os.path.normcase(os.path.dirname(os.path.abspath(sys.argv[0])))
os.chdir(install_path)


class GremlinUi(gremlin.ui.ui_common.QRememberMainWindow):
    """Main window of the Joystick Gremlin user interface."""

    ui = None

    # input_lock =  threading.Lock() # critical code operations - prevents reentry

    def __init__(self, parent=None):
        """Creates a new main ui window.

        :param parent the parent of this window
        """

        self.instance = self

        gremlin.shared_state.ui = self
        self.initialized = False

        super().__init__("main_window", parent)

        self.ui = Ui_Gremlin()
        # self.addWidget(QtWidgets.QLabel("TOP"))
        self.ui.build(self)  # build the main window
        # self.addWidget(QtWidgets.QLabel("BOTTOM"))

        self._is_active = False  # status bar active flag
        self._widget_device_index_map = {}

        self._profile_load_stack = []
        self._profile_load_temporary_files = []
        self._profile_hash = None  # active profile hash to detect changes
        self.locked = False
        self.activate_locked = False
        self._selection_locked = False
        self.joystick_event_lock = Lock()  # lock for joystick events
        self.device_change_locked = False
        self._device_change_queue = 0  # count of device updates while the UI is already updating
        self._runtime_mode_map = {}  # map of runtime processes to their last runtime mode
        self._process_runtime_map = {}  # map of MODE to process associated with a profile - the process executable is the key
        self._active_process_path = None  # active mapped process path
        self._last_toast_message = None
        self._change_input_lock = threading.Lock()  # true when changing inputs
        self._ui_update_pending = False  # flag = if True, UI updates are pending
        self._suspend_ui_update = 0  # stack = if non zero, UI updates should be suspended

        self._comparative_file = os.path.join(os.getenv("temp"), "8c71a5a6eae74f989cf903816868028e.xml")

        self._loading_stack = 0
        self._loading_stack_target = 0  # target index if a call to select a page is done while page cycling is suspended

        # self.ui.device_page_widget.currentChanged.connect(self._handle_device_widget_index_changed)

        self._last_selected_device_guid = None
        self._last_selected_input_type = None
        self._last_selected_input_id = None

        self._resize_count = 0

        # list of detected devices
        self._active_devices = []
        self._tab_dirty = True  # True if tabs should be refreshed
        self._tab_map = None  # holds tabdata objects indexed by tab index

        # cache of widget references so they don't get garbage collected by QT

        self.ui.devices_tab_header_widget.tabChanged.connect(self._tab_selected)
        self.ui.devices_tab_header_widget.tabMoveCompleted.connect(self._tab_moved_cb)
        self.ui.devices_tab_header_widget.tabContextMenu.connect(self._tab_context_menu_cb)
        self.ui.devices_tab_header_widget.currentChanged.connect(self._tab_changed)

        self._last_input_item = None  # last selected input item
        self._last_state_device_guid = None
        self._last_state_input_id = None
        self._last_state_data = {}  # holds data for axis highlight switching

        gremlin.shared_state.application_version = gremlin.version.APPLICATION_VERSION

        self.config = gremlin.config.Configuration()
        self.config.changed.connect(self._config_filter_changed_cb)

        # last input from last run to restore
        self.restore_input = self.config.get_last_input()

        # prevent saving anything until we have a profile loaded
        el = gremlin.event_handler.EventListener()
        el.push_input_selection()
        el.request_activate.connect(self.activate)  # hook activation / deactivation requests
        el.refresh_devices.connect(self._create_tabs)  # refresh device list
        el.request_profile_reload.connect(self._reload_profile)  # reload the profile from a temporary file
        el.request_reload.connect(self._reload)
        el.device_mapping_changed.connect(self._update_tab)
        # el.mapping_changed.connect(self._mapping_changed)
        el.show_container_id_changed.connect(self._show_container_id_visible_changed)
        el.toolbar_changed.connect(self._update_toolbar)
        el.update_mode_status_bar.connect(self._update_mode_status_bar)
        el.request_ui_refresh.connect(self.refresh)
        el.shutdown.connect(self.handle_shutdown)
        el.feature_changed.connect(self._handle_feature_changed)  # handle feature changes
        el.input_selection_changed.connect(self._handle_item_selected)

        # highlighing options
        self._icon_on = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            qta_color=gremlin.ui.ui_common.Color.activeColor(),
        )
        self._icon_off = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            qta_color=gremlin.ui.ui_common.Color.inactiveColor(),
        )
        self._button_highlighting_enabled = self.config.highlight_input_buttons  # true if highlighting on buttons
        self._axis_highlighting_enabled = self.config.highlight_input_axis  # true if highligthing on axes
        self._input_highlighting_enabled = self.config.highlight_enabled  # on/off global

        el.enable_highlight_changed.connect(self._highlight_enable_changed)  # fires when highlight mode is toggled

        self._last_highlight_key = None  # last event processed for input highlights
        el.toggle_highlight.connect(self._handle_highlight_state)  # input highlighting states
        el.ui_ready.connect(self._ui_ready)
        gremlin.shared_state.aborted = False
        el.request_profile_stop.connect(lambda x: self.abort(x))

        # Process monitor
        self.process_monitor = gremlin.process.ProcessMonitor()
        self.process_monitor.process_changed.connect(self._process_changed_cb)
        self.current_process_path = None  # current process
        self._last_tts_notify_time = None  # last autoload process change TTS time
        self._process_change_in_progress = False

        # Default path variable before any runtime changes
        self._base_path = list(sys.path)

        self._init_tab_data()
        self._reset_tab_data()

        self.runner = gremlin.code_runner.CodeRunner()
        self.repeater = gremlin.repeater.Repeater([], self._update_statusbar_repeater)

        self._status_bar_last_runtime_mode = None
        self._status_bar_last_edit_mode = None

        el.runtime_mode_changed.connect(self._runtime_mode_changed)
        el.edit_mode_changed.connect(self._edit_mode_changed)
        el.edit_mode_ui_update.connect(self._edit_mode_update)

        self.tab_guids = []

        self.mode_selector = gremlin.ui.ui_common.ModeWidget()  # main UI mode selector
        self.mode_selector.edit_mode_changed.connect(self._edit_mode_selector_changed)
        self.mode_selector.setRuntimeDisabled(True)

        self.ui.toolBar.addWidget(self.mode_selector)

        # Setup profile storage

        self.profile = gremlin.base_profile.Profile()  # blank profile
        self._profile_auto_activated = False
        # Input selection storage
        self._last_input_timestamp = time.time()
        self._last_input_change_timestamp = time.time()

        self._last_input_event = None
        self._last_input_identifier = None  # input id of the last triggered device
        # self._last_device_guid = None # string representation of the last GUID of the last triggered device
        # self._last_input_type = None # last input type (InputType) selected
        # self._last_input_id = None # last input id selected

        self._last_tab_switch = None
        self._input_delay = 0.25  # delay in seconds between joystick inputs for highlighting purposes
        self._joystick_axis_highlight_deviation = 0.5  # deviation needed before registering a highlight on axis change (this is to avoid noisy inputs and prevent the UI from going crazy) 1.0 = half travel
        self._joystick_axis_highlight_map = {}  # map of device / axis values
        self._event_process_registry = {}
        self._temp_input_axis_override = False  # flag that tracks device swaps on axis
        self._temp_input_axis_only_override = False  # flag that tracks device swaps but on axis only (shift + ctrl key)

        # Create all required UI elements
        self._create_system_tray()
        self._setup_icons()
        self._connect_actions()
        self._create_statusbar()
        self._update_status_bar_active(False)

        # hook status bar to events
        el = gremlin.event_handler.EventListener()

        el.remote_control_state_change.connect(self._update_status_bar)  # remote control state changes

        el.keyboard_event.connect(self._kb_event_cb)  # for repeaters

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

        # disable autoload if ctrl key is held
        if win32api.GetKeyState(win32con.VK_CONTROL) < 0:
            syslog.info("START: autoload profile disabled (ctrl key detected)")
            self.config.auto_load_disabled = True

        profile_to_load = None
        if not self.config.auto_load_disabled:
            if config.profile_to_load and os.path.isfile(config.profile_to_load):
                profile_to_load = config.profile_to_load
            elif self.config.last_profile and os.path.isfile(self.config.last_profile):
                # check if this was a profile swap that we load the profile from the current user folder
                profile_to_load = self.config.last_profile

            if profile_to_load:
                current_profile_folder = gremlin.shared_state.data_path.casefold()
                last_profile = self.config.last_profile.lower()
                if current_profile_folder not in last_profile:
                    _, base_file = os.path.split(last_profile)
                    located_profile = find_file(base_file, current_profile_folder)
                    if located_profile:
                        self.config.last_profile = located_profile
            profile_to_load = self.config.last_profile

        if profile_to_load:
            self._autostart_target_name = os.path.splitext(os.path.basename(profile_to_load))[0]
            self._do_load_profile(profile_to_load)
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

        self._profile_map = gremlin.base_profile.ProfileMap()

        GremlinUi.ui = self

        self.ui.update_toolbar()
        self._update_status_bar()
        el.config_option_changed.connect(self._config_option_changed)
        el.device_change_event.connect(self._handle_devices_changed)
        el.ui_initialized.connect(self._update_start_tab)

        self.vjoy_state = gremlin.joystick_handling.VirtualDeviceUsageState()

        self.initialized = True
        gremlin.shared_state.initialized = True

        el.ui_initialized.emit()

        # handle auto start
        if self.config.run_on_start and profile_to_load:
            # register a startup call
            el.profile_loaded.connect(self._handle_auto_start_on_load)

    def _handle_auto_start_on_load(self):
        """Handles auto start when the profile is loaded"""
        el = gremlin.event_handler.EventListener()
        el.profile_loaded.disconnect(self._handle_auto_start_on_load)
        el.request_activate.emit(True)

    # def _handle_device_widget_index_changed(self, index):
    #     syslog.info(f"device page: index set to [{index}]")

    def pushSuspendTabUpdate(self):
        self._suspend_ui_update += 1

    def popSuspendTabUpdate(self, reset=False):
        if reset:
            self._suspend_ui_update = 0
        if self._suspend_ui_update > 0:
            self._suspend_ui_update -= 1
        if self._suspend_ui_update == 0 and self._ui_update_pending:
            self._ui_update_pending = False
            self._create_tabs()  # recreate the UI tabs

    def pushLoading(self):
        if self._loading_stack == 0:
            self.hideDeviceContent()
        self._loading_stack += 1

    def popLoading(self, device_guid: dinput.GUID = None, reset=False):
        if self._loading_stack:
            if reset:
                self._loading_stack = 0
            else:
                self._loading_stack -= 1

            if self._loading_stack == 0:
                if self._loading_stack_target:
                    self.setDeviceContentIndex(self._loading_stack_target)
                    # syslog.info(f"loading: display saved index [{self._loading_stack_target}]")
                    self._loading_stack_target = 0
                else:
                    self.showDeviceContent(device_guid)

    def handle_shutdown(self):
        # cleanup on shutdown
        if os.path.isfile(self._comparative_file):
            os.unlink(self._comparative_file)

    def handle_tab_selected(self, device_guid):
        """persists the last selected device for the profile"""
        if self.profile:
            self.profile.saveLastDevice(device_guid)

    def _update_start_tab(self):
        """forces a tab index reload on init"""
        tab_index = self.ui.devices_tab_header_widget.currentIndex()
        self._tab_selected(tab_index)

    def _update_toolbar(self):
        """updates the toolbar when the toolbar changes"""
        self.ui.update_toolbar()

    def registerTemporaryProfileLoadFile(self, xml_file: str):
        """registers a temporary file that the profile loader will load"""
        if xml_file not in self._profile_load_temporary_files:
            self._profile_load_temporary_files.append(xml_file)

    def _init_tab_data(self):
        self._widget_device_index_map = {}  # map of device widgets keyed by the device GUID
        self._widget_index_device_map = {}

    def _reset_tab_data(self):

        self._tab_index_map = {}  # map of device_guids indexed by their tab index from the tab header  (index -> device_guid)
        self._tab_device_map = {}  # map of tab positions index mapped by device guid for the tab header (device_guid -> index)
        self._tab_name_map = {}  # map fo device guid to device name for tabs

        # self._current_tab_widget = None # selected content widget for the current device
        self._current_tab_input_id = None  # selected input in the current tab
        self._joystick_device_guids = []
        self.tab_guids = []

        self._clear_tabs()

    def _clear_tabs(self):
        gremlin.util.InvokeUiMethod(self._clear_tabs_ui)  # ensure on UI thread

    def getTabCount(self) -> int:
        return self.ui.devices_tab_header_widget.count()

    def _clear_tabs_ui(self):
        # remove all tab headers
        assert gremlin.util.is_ui_thread()
        if self.ui.devices_tab_header_widget:
            with QtCore.QSignalBlocker(self.ui.devices_tab_header_widget):
                while self.ui.devices_tab_header_widget.count():
                    self.ui.devices_tab_header_widget.removeTab(0)
        self._tab_device_map.clear()
        self._tab_index_map.clear()
        self._tab_name_map.clear()

    def _get_device(self, device_guid) -> dinput.DeviceSummary:
        """gets the device for a given GUID, connected or not"""
        return gremlin.joystick_handling.getDevice(device_guid)

    def _get_device_name(self, device_guid):
        """gets the name of a device"""
        device = self._get_device(device_guid)
        if device:
            return device.name
        return None

    def _add_tab(self, device_guid, tab_type, index=None, override_name=None) -> int:
        """adds a tab to the tab header
        :param device_guid: the device guid of the device to add
        :param index: optiona, if specified, the index to add
        :returns int: the index of the tab added
        """
        device_guid = gremlin.util.to_guid(device_guid)

        device: dinput.DeviceSummary = self._get_device(device_guid)
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

        tab_name = override_name if override_name else device_name
        with QtCore.QSignalBlocker(self.ui.devices_tab_header_widget):
            if index is None:
                position = self.ui.devices_tab_header_widget.addTab(tab_name)
            else:
                position = self.ui.devices_tab_header_widget.insertTab(index, tab_name)

        #  tab data block
        data = ts.addData(position, tab_type, device)
        self.ui.devices_tab_header_widget.setTabData(position, data)

        self._tab_device_map[device_guid] = position
        self._tab_index_map[position] = device_guid
        self._tab_name_map[device_guid] = tab_name

        if tab_type == TabDeviceType.Joystick:
            self._joystick_device_guids.append(device_guid)

        verbose = gremlin.config.Configuration().verbose_mode_device

        if verbose:
            syslog.info(f"Add tab: index [{position}]  [{device_name}] data: {self.ui.devices_tab_header_widget.tabData(position)}")

        self._update_tab(device_guid)

        return position

    def _remove_tab(self, device_guid):
        """removes a device tab"""
        device_guid = gremlin.util.to_guid(device_guid)
        device: dinput.DeviceSummary = self._get_device(device_guid)
        if not device:
            syslog.error(f"Unknown device GUID found in tabs: {device_guid}")
            return

        # ensure the device tab does not already exist
        if device_guid in self._tab_device_map:
            widget = self.getRegisteredWidget(device_guid)
            if widget:
                widget.hide()
                if hasattr(widget, "_cleanup_ui"):
                    widget._cleanup_ui()
                widget.setParent(None)
                widget.deleteLater()

            index = self._tab_device_map[device_guid]
            self.ui.devices_tab_header_widget.removeTab(index)

            del self._tab_device_map[device_guid]
            del self._tab_index_map[index]
            del self._tab_name_map[device_guid]

    def _has_mapping(self, device_guid, any_mode=False) -> bool:
        """true if the device has mappings"""
        return self.profile.hasMapping(device_guid, any_mode)

    def _get_mappings(self, device_guid) -> dict:
        """returns a map of [mode], has_mapping"""
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
            return {edit_mode: True} if names else {}
        elif device_guid == gremlin.shared_state.settings_tab_guid:
            return {}
        elif device_guid == gremlin.shared_state.plugins_tab_guid:
            # plugins
            plugins = gremlin.shared_state.current_profile.plugins
            return {edit_mode: True} if len(plugins) > 0 else {}
        elif device_guid == gremlin.shared_state.keyboard_tab_guid:
            look_for_containers = False

        mode_map = {}

        if device_guid in devices:
            device_data = devices[device_guid]
            for mode_name in device_data.modes:
                mode_data = device_data.modes[mode_name]
                mode_map[mode_name] = False
                for input_type, input_items in mode_data.config.items():
                    # account for delay loaded input mappings
                    input_item_list = [item for item in input_items.values() if item is not None]
                    for input_item in input_item_list:
                        if look_for_containers:
                            if input_item.containers:
                                mode_map[mode_name] = True
                                break
                        else:
                            # input count indicates content
                            mode_map[mode_name] = True
                            break

        return mode_map

    def getTabMap(self) -> dict:
        """gets tab data as tupless"""
        return self._get_tab_map()

    def getTabDataMap(self) -> dict:
        """gets tab data as TabData object"""

        return self._get_tab_data_map()

    def getTabDataIndex(self, data: gremlin.tabstate.TabData):
        for index in range(self.ui.devices_tab_header_widget.count()):
            if self.ui.devices_tab_header_widget.tabData(index) == data:
                return index
        return -1

    def _get_tab_map(self) -> dict[int, TabData]:
        """gets tab configuration data as a dictionary indexed by tab index holding device id, device name and device widget type
        :returns:  list of (device_guid, device_name, tabdevice_type, tab_index)
        """

        tab_count = self.ui.devices_tab_header_widget.count()
        tab_map = {}
        for index in range(tab_count):
            data: TabData = self.ui.devices_tab_header_widget.tabData(index)
            tab_map[index] = data
        return tab_map

    def _get_tab_data_at(self, index: int) -> TabData | None:
        """gets the tab data for the given tab index"""
        if 0 <= index < self.ui.devices_tab_header_widget.count():
            return self.ui.devices_tab_header_widget.tabData(index)
        return None

    def _get_tab_data_map(self) -> dict[dinput.GUID, TabData]:
        """returns the map of tab data objects associated with their device GUID"""
        tab_count = self.ui.devices_tab_header_widget.count()
        tab_map = {}
        for index in range(tab_count):
            data = self.ui.devices_tab_header_widget.tabData(index)
            tab_map[data.device_guid] = data

        return tab_map

    def _get_tab_type(self, index):
        """gets the tab type for the given tab index"""
        data = self.ui.devices_tab_header_widget.tabData(index)
        return data.tab_type

    def _get_tab_type_from_device_guid(self, device_guid: uuid.UUID | dinput.GUID | str) -> TabDeviceType:
        device = gremlin.joystick_handling.getDevice(device_guid)
        return self._get_tab_type_from_device(device)

    def _get_tab_type_from_device(self, device: dinput.DeviceSummary) -> TabDeviceType:
        if device:
            match device.device_type:
                case DeviceType.NotSet:  # not set
                    return TabDeviceType.NotSet
                case DeviceType.Keyboard:  # keyboard special device
                    return TabDeviceType.Keyboard
                case DeviceType.Joystick:  # joystick or game controller
                    return TabDeviceType.Joystick
                case DeviceType.VJoy:  # vjoy (virtual)
                    return TabDeviceType.VjoyInput
                case DeviceType.Maestro:  # maestro device
                    return TabDeviceType.MaestroInput
                case DeviceType.Midi:  # midi special device
                    return TabDeviceType.Midi
                case DeviceType.Osc:  # open source control special device
                    return TabDeviceType.Osc
                case DeviceType.ModeControl:  # mode control special device
                    return TabDeviceType.ModeControl
                case DeviceType.Settings:  # settings special device
                    return TabDeviceType.Settings
                case DeviceType.State:  # state special device
                    return TabDeviceType.State
                case DeviceType.Plugins:  # plugins special device
                    return TabDeviceType.Plugins
                case DeviceType.OctaviIFR1:  # octavi IFR1 special device
                    return TabDeviceType.OctaviIFR1

            raise ValueError(f"Don't know how to handle type: [{device.device_type}]")

        return TabDeviceType.NotSet

    def _reindex_tabs(self):
        """rebuilds the tab index"""
        self._tab_index_map.clear()
        self._tab_device_map.clear()
        self._tab_name_map.clear()

        verbose = gremlin.config.Configuration().verbose_mode_device
        # syslog = logging.getLogger("system")
        if verbose:
            syslog.info("UI: tab reindex")
        for index in range(self.ui.devices_tab_header_widget.count()):
            data = self.ui.devices_tab_header_widget.tabData(index)
            device_guid = gremlin.util.to_guid(data.device_guid)
            device_name = self._get_device_name(device_guid)
            self._tab_index_map[index] = device_guid
            self._tab_device_map[device_guid] = index
            self._tab_name_map[device_guid] = device_name

            if verbose:
                syslog.info(f"\t[{index}] {device_name} {device_guid}")

    def _tabswitch_needed(self, device_guid) -> bool:
        """checks to see if the device tab is the current tab or not"""

        tab_device_guid = self.getCurrentTabDeviceGuid()

        if tab_device_guid is None:
            # no tab selected yet
            return True

        device_guid = gremlin.util.to_guid(device_guid)  # compare dinput.GUID objects
        assert isinstance(tab_device_guid, dinput.GUID) and isinstance(device_guid, dinput.GUID), "device id comparison mismatch data types"

        return tab_device_guid != device_guid

    def getCurrentTabDeviceGuid(self) -> dinput.GUID:
        """updates the current tab tracking variables"""
        tab_device_guid = gremlin.shared_state.current_tab_device_guid
        if tab_device_guid is None:
            tab_device_guid = self._tab_index_map.get(self.ui.devices_tab_header_widget.currentIndex())
            gremlin.shared_state.current_tab_device_guid = tab_device_guid
            gremlin.shared_state.current_tab_device_id = gremlin.util.normalize_guid(tab_device_guid)
        assert isinstance(tab_device_guid, dinput.GUID), "current tab device guid is not a dinput.GUID"
        return tab_device_guid

    def _inputswitch_needed(self, device_guid: dinput.GUID, input_id) -> bool:
        """checks to see if an input switch is needed"""

        tab_device_guid = self.getCurrentTabDeviceGuid()
        assert isinstance(tab_device_guid, dinput.GUID) and isinstance(device_guid, dinput.GUID), "device id comparison mismatch"
        tab_input_id = self._current_tab_input_id
        return tab_device_guid != device_guid or tab_input_id != input_id

    def _button_state_change(self, event):
        """button changed - triggered only at design time - look for highlighting triggers - HIGHLIGHT SYSTEM"""

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
            # highlight for buttons disabled
            return

        tab_switch_needed = self._tabswitch_needed(device_guid)
        if tab_switch_needed and not is_tabswitch_enabled:
            # tab switch is disabled
            return

        input_switch_needed = True  # tab_switch_needed or self._inputswitch_needed(device_guid, input_id)

        if not input_switch_needed:
            # not setup to auto change tabs (override via shift/control keys)
            return

        # # see if input needs to change
        # input_switch_needed = tab_switch_needed or self._inputswitch_needed(device_guid, input_id)
        # if not input_switch_needed:
        #     return

        # trigger switch
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info(f"Button input switch to {device_guid} button {input_id}")

        self._select_input_handler(device_guid, input_type, input_id, force_switch=True)

    def _axis_state_change(self, event):
        """axis changed - triggered only at design time - HIGHLIGHT SYSTEM"""

        if gremlin.shared_state.is_highlighting_suspended():
            # highlighting disabled
            return

        el = gremlin.event_handler.EventListener()
        is_control = el.get_control_shift_state()
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
        if device_guid not in self._last_state_data:
            self._last_state_data[device_guid] = {}
        if input_id not in self._last_state_data[device_guid]:
            self._last_state_data[device_guid][input_id] = None

        if self._last_state_data[device_guid][input_id] is not None:
            last_value = self._last_state_data[device_guid][input_id]
            if abs(last_value - value) <= 0.2:
                return  # insufficient deviation to trigger

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
        if verbose:
            syslog.info(f"Axis input switch to {device_guid} axis {input_id}")
        self._select_input_handler(device_guid, input_type, input_id, force_switch=True)

    @QtCore.Slot(int)
    def _tab_changed(self, index):
        # syslog.info(f"tab changed : {index}")
        self._tab_selected(index)

    @QtCore.Slot(int)
    def _tab_selected(self, index):
        """called when the device tab selection is changed
        :param: index = the index of the tab that was selected

        """
        if index == -1:
            # not a valid tab
            return

        if self.ui.devices_tab_header_widget.moveInProgress:
            # ignore if the tab is being dragged
            return

        self.pushLoading()

        verbose = gremlin.config.Configuration().verbose_mode_ui

        if verbose:
            syslog.info(f"TAB CHANGED: selected : {index}")

        device_guid = self.getDeviceGuidForTabIndex(index)
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device"

        if verbose:
            syslog.info(f"TAB CHANGED:  new tab [{index}] {self.ui.devices_tab_header_widget.tabText(index)} - device [{device.name}] id [{device.device_id}]")
        self.last_tab_index = index

        wm = WorkManager()

        wm.submit(callback=self._tab_selected_worker, args=device_guid)

    def _tab_selected_worker(self, args):
        device_guid = args
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device"

        self._tab_selection_completed = False

        _, restore_input_type, restore_input_id = self.config.get_last_input(device_guid)
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info(f"TabSelectedWorker: start select device [{device.name}] id [{device.device_id}]")

        self._select_input(
            device_guid=device_guid,
            input_type=restore_input_type,
            input_id=restore_input_id,
            force_update=True,
            force_switch=True,
            tab_changed=True,
            extra_data={
                "completion_callback": self._tab_selection_complete,
                "source": "tab_selected",
            },
        )

        # wait for the tab selection to complete
        while not self._tab_selection_completed:
            QThread.sleep(0)

        if verbose:
            syslog.info("tab selection worker complete")

    def _tab_selection_complete(self, *args):
        self._tab_selection_completed = True
        self.popLoading()

    def add_custom_tools_menu(self, menuTools):
        """adds custom tools to the menu"""
        # self._actionTabSort = QtGui.QAction("Sort Devices", self, triggered=self._tab_sort_cb)
        # self._actionTabSort.setToolTip("Sorts input hardware devices in alphabetical order")

        self._actionTabDisplayDevice = QtGui.QAction("Device List...", self, triggered=self._tab_display_device_cb)
        self._actionTabDisplayDevice.setToolTip("Displays the selected device in the profile")

        self._ationTabCopyAssignments = QtGui.QAction("Copy to device...", self, triggered=self._tab_copy_cb)
        self._ationTabCopyAssignments.setToolTip("Copies assignments to specified target device")

        # self._actionTabSubstitute = QtGui.QAction("Device Swap...", self, triggered = self._tab_substitute_cb)
        # self._actionTabSubstitute.setToolTip("Swap one device ID for another device ID")

        self._actionTabClearMap = QtGui.QAction("Clear Mappings", self, triggered=self._tab_clear_map_cb)
        self._actionTabClearMap.setToolTip("Clears all mappings from the current device")
        # tab remove device moved to display options in m77
        # self._actionTabRemoveDevice = QtGui.QAction("Change Visible Device...", self, triggered=self._tab_remove_device_cb)
        # self._actionTabRemoveDevice.setToolTip("Removes the device from the profile")
        # self._actionTabImport = QtGui.QAction("Import Profile...", self, triggered = self._tab_import_cb)
        # self._actionTabImport.setToolTip("Import profile data into the current device")

        menuTools.addSeparator()
        # menuTools.addAction(self._actionTabSort)
        menuTools.addAction(self._actionTabDisplayDevice)
        menuTools.addAction(self._ationTabCopyAssignments)
        # menuTools.addAction(self._actionTabSubstitute)

        # menuTools.addAction(self._actionTabRemoveDevice)
        # menuTools.addAction(self._actionTabImport)
        menuTools.addAction(self._actionTabClearMap)

    def _tab_context_menu_cb(self, tab_index):
        """tab context menu"""
        self._context_menu_tab_index = tab_index
        data = self.ui.devices_tab_header_widget.tabData(tab_index)
        _tab_type = data.tab_type
        # device_guid = data.device_guid
        # substitution is only available if the profile has been saved (a new profile matches the current devices by definition)
        # is_enabled = tab_type == TabDeviceType.Joystick
        #     and self.profile is not None\
        #     and self.profile.profile_file is not None\
        #     and os.path.isfile(self.profile.profile_file)
        # self._actionTabSubstitute.setEnabled(is_enabled)
        menu = QtWidgets.QMenu(self)
        # menu.addAction(self._actionTabSort)
        menu.addAction(self.ui.actionReorderDevices)
        menu.addAction(self.ui.actionDeviceInformation)
        menu.addAction(self._ationTabCopyAssignments)
        # menu.addAction(self._actionTabSubstitute)
        # menu.addAction(self._actionTabImport)
        # menu.addAction(self._actionTabRemoveDevice)
        menu.addAction(self._actionTabClearMap)

        advanced_menu = menu.addMenu("Advanced...")

        action = QtGui.QAction(
            "Copy Device ID",
            self,
            triggered=self._crate_copy_device_id_callback(data.device_guid),
            toolTip="Copy this device's ID to the clipboard",
        )
        advanced_menu.addAction(action)

        action = QtGui.QAction(
            "Copy Device XML header",
            self,
            triggered=self._crate_copy_device_id_callback(data.device_guid, True),
            toolTip="Places an XML profile entry header for this device into the clipboard",
        )

        advanced_menu.addAction(action)

        menu.addMenu(advanced_menu)

        switch_menu = menu.addMenu("Switch to...")

        # switch to another device
        for index in range(self.ui.devices_tab_header_widget.count()):
            if tab_index == index:
                continue  # skip current tab
            data: gremlin.tabstate.TabData = self.ui.devices_tab_header_widget.tabData(index)
            name = data.device.name
            action = QtGui.QAction(name, self, triggered=self._create_tab_change_trigger_callback(index))
            switch_menu.addAction(action)

        menu.exec_(QtGui.QCursor.pos())

    def _crate_copy_device_id_callback(self, device_guid, is_xml=False):
        return lambda x: self._handle_copy_device_id_to_clipboard(device_guid, is_xml)

    def _handle_copy_device_id_to_clipboard(self, device_guid, is_xml: bool = False):
        from gremlin.clipboard import Clipboard

        clipboard = Clipboard()
        if is_xml:
            device = gremlin.joystick_handling.getDevice(device_guid)
            if device:
                xml = f'<device name="{device.name}" label="" device-guid="{device.device_id}" type="{DeviceType.to_string(device.device_type)}">'
                clipboard.set_windows_clipboard_text(xml)
            else:
                gremlin.ui.ui_common.MessageBoxWarning(prompt="Device is not found. Cannot derive XML header.")
        else:
            clipboard.set_windows_clipboard_text(gremlin.util.normalize_guid(device_guid))

    def _create_tab_change_trigger_callback(self, index):
        return lambda x: self._handle_tab_change_context(index)

    def _handle_tab_change_context(self, index):
        """changes to a new tab from the context menu"""
        self.ui.devices_tab_header_widget.setCurrentIndex(index)

    def _tab_sort_cb(self):
        """sorts the tabs"""
        self._sort_tabs()

    def _tab_clear_map_cb(self):
        """clears the mappings from the current tab"""
        tab_guid = gremlin.util.parse_guid(self._active_tab_guid())
        device: gremlin.base_profile.ProfileDeviceNode = gremlin.shared_state.current_profile.devices[tab_guid]
        current_mode = gremlin.shared_state.current_mode
        result = gremlin.ui.ui_common.ConfirmBox(f"Remove all mappings from {device.name}, mode [{current_mode}]?")
        if result:
            self._tab_clear_map_execute(device, current_mode)

    # def _tab_remove_device_cb(self):
    #     """removes a disconnected device from the menu"""
    #     self.change_visible_profile_devices()

    def _tab_import_cb(self):
        """imports a profile into the device"""
        # tab_guid = gremlin.util.parse_guid(gremlin.shared_state.ui._active_tab_guid())
        # device : gremlin.base_profile.Device = gremlin.shared_state.current_profile.devices[tab_guid]
        gremlin.import_profile.import_profile()

    def _tab_clear_map_execute(self, device, mode_name):
        """removes all mappings from the given device in the active mode"""

        mode = device.modes[mode_name]
        for input_type in mode.config.keys():
            for entry in mode.config[input_type].values():
                entry.containers.clear()
        self.setTabsDirty(True)

    def _tab_remove_device_execute(self, device: dinput.DeviceSummary):
        """removes the specified device"""
        current_profile = gremlin.shared_state.current_profile
        current_profile.remove_device(device)

    def _tab_substitute_cb(self, pos):
        """substitution dialog for devices"""
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
        data = self.ui.devices_tab_header_widget.tabData(self._context_menu_tab_index)
        device_guid = data.device_guid

        # device_name = self.ui.devices.tabText(self._context_menu_tab_index)
        self._dialog_substitute = gremlin.profile_graph.DeviceRemapDialogUI(self.current_profile.graph, self, device_guid)
        # dialog = gremlin.ui.dialogs.SubstituteDialog(device_guid=device_guid, device_name=device_name, parent = self)
        # dialog.setModal(True)
        self._dialog_substitute.accepted.connect(self._substitute_complete_cb)
        self._dialog_substitute.rejected.connect(self._handle_substitute_rejected)
        gremlin.util.centerDialog(self._dialog_substitute)
        self._dialog_substitute.show()

    def _tab_display_device_cb(self):
        """displays the device dialog"""
        profile = gremlin.shared_state.current_profile
        if profile:
            dialog = gremlin.ui.dialogs.DeviceInformationDialog(profile=profile, parent=self)
            dialog.exec()

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
        data = self.ui.devices_tab_header_widget.tabData(self._context_menu_tab_index)
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
        """substitution complete - reload profile"""
        # profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        # self.load_profile(profile.profile_file)
        self._dialog_substitute.deleteLater()
        self._dialog_substitute = None

    def _handle_substitute_rejected(self):
        self._dialog_substitute.deleteLater()
        self._dialog_substitute = None

    def _reload(self):
        """reloads the ui"""
        self.setTabsDirty(True)

    @QtCore.Slot(str, bool)
    def _reload_profile(self, source_xml: str, as_new_profile: bool):
        """loads profile data from the specified file, optionally setting it up a new, unsaved, profile"""
        self._do_load_profile(source_xml, as_new_profile)

    def _profile_changed_cb(self, new_profile=None):
        """called when the a profile should be loaded"""

        if new_profile is None:
            # save current contents to a temporary file
            profile: gremlin.base_profile.Profile = gremlin.shared_state.current_profile
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

    def closeEvent(self, event):
        """Terminate the entire application if the main window is closed.

        :param evt the closure event
        """

        if self.config.close_to_tray and self.ui.tray_icon is not None and not getattr(self, "_really_quitting", False):
            self.hide()
            event.ignore()
        else:
            # terminate the idle thread
            self.process_monitor.running = False
            try:
                if self.ui.tray_icon:
                    self.ui_tray_icon = None
            except Exception:
                pass
            QtCore.QCoreApplication.quit()

        # Terminate file watcher thread
        if "log" in self.modal_windows:
            dialog = self.modal_windows["log"]
            if dialog:
                dialog.watcher.stop()

        return super().closeEvent(event)

    # +---------------------------------------------------------------
    # | Modal window creation
    # +---------------------------------------------------------------

    def about(self):
        """Opens the about window."""
        self.modal_windows["about"] = gremlin.ui.dialogs.AboutUi()
        self.modal_windows["about"].show()
        self.modal_windows["about"].closed.connect(lambda: self._remove_modal_window("about"))

    @property
    def current_mode(self) -> str:
        """returns the current active profile mode"""
        return gremlin.shared_state.current_mode

    @property
    def current_profile(self) -> gremlin.base_profile.Profile:
        return gremlin.shared_state.current_profile

    def calibration(self):
        """Opens the calibration window."""
        # indicate the feature has been deprecated
        return

    # def change_visible_profile_devices(self):
    #     """opens the profile device dialog"""
    #     dialog = gremlin.ui.dialogs.RemovedDeviceUi()
    #     geom = self.geometry()
    #     w = 600
    #     h = 400
    #     dialog.setGeometry(
    #         int(geom.x() + geom.width() / 2 - w / 2),
    #         int(geom.y() + geom.height() / 2 - h / 2),
    #         w,
    #         h,
    #     )
    #     dialog.exec()

    def device_information(self):
        """Opens the device information window."""
        self.modal_windows["device_information"] = gremlin.ui.dialogs.DeviceInformationDialog(self.profile)
        geom = self.geometry()
        w = 600
        h = 400
        self.modal_windows["device_information"].setGeometry(
            int(geom.x() + geom.width() / 2 - w / 2),
            int(geom.y() + geom.height() / 2 - h / 2),
            w,
            h,
        )
        self.modal_windows["device_information"].show()
        self.modal_windows["device_information"].closed.connect(lambda: self._remove_modal_window("device_information"))

    def log_window(self):
        gremlin.util.InvokeUiMethod(self._log_window_ui)

    def _log_window_ui(self):
        """Opens the log display window."""
        gremlin.util.assert_ui_thread()
        self.modal_windows["log"] = gremlin.ui.dialogs.LogWindowUi()
        self.modal_windows["log"].closed.connect(lambda: self._remove_modal_window("log"))
        self.modal_windows["log"].show()

    def log_edit(self):
        """opens the log file in the editor"""
        log_file = os.path.join(gremlin.shared_state.data_path, "system.log")
        if os.path.isfile(log_file):
            gremlin.util.display_file(log_file)

    def manage_modes(self):
        """Opens the mode management window."""
        dialog = gremlin.ui.dialogs.ModeManagerDialog(self.profile)
        self.modal_windows["mode_manager"] = dialog
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.closed.connect(self._handle_mode_manager_closed)
        dialog.show()

    def _handle_mode_manager_closed(self):
        self._remove_modal_window("mode_manager")
        # update the edit mode if it was removed from the list of modes in the mode editor
        edit_mode = gremlin.shared_state.edit_mode
        profile = gremlin.shared_state.current_profile
        modes = profile.get_selectable_modes()
        if edit_mode not in modes:
            new_mode = profile.get_default_mode()
            el = gremlin.event_handler.EventHandler()
            el.change_mode(new_mode)

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
        dialog = gremlin.ui.dialogs.OptionsDialog()
        self.modal_windows["options"] = dialog
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.ensurePolished()
        gremlin.util.centerDialog(dialog, width=dialog.width(), height=dialog.height())
        dialog.closed.connect(self._handle_options_closed)
        dialog.exec()
        dialog.apply_window_settings()

    def _handle_options_closed(self):
        dialog = self.sender()
        self.modal_windows["options"] = None
        if not dialog.accepted:
            return

        self._apply_user_settings_ui(ignore_minimize=True, auto_start=False)

        # if dialog.reload_profile:
        self.refresh()
        # else:
        # tell components of the possible changes to the options
        el = gremlin.event_handler.EventListener()
        el.options_changed.emit()


    def profile_creator(self):
        """Opens the UI used to create a profile from an existing one."""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Profile to load as template",
            gremlin.shared_state.data_path,
            "XML files (*.xml)",
        )
        if fname == "":
            return

        profile_data = gremlin.base_profile.Profile()
        profile_data.from_xml(fname)

        self.modal_windows["profile_creator"] = gremlin.ui.profile_creator.ProfileCreator(profile_data)
        self.modal_windows["profile_creator"].show()
        gremlin.shared_state.push_suspend_highlighting()
        self.modal_windows["profile_creator"].closed.connect(lambda: gremlin.shared_state.pop_suspend_highlighting())
        self.modal_windows["profile_creator"].closed.connect(lambda: self._remove_modal_window("profile_creator"))

    def swap_devices(self):
        """Opens the UI used to swap devices."""
        self.modal_windows["swap_devices"] = gremlin.ui.dialogs.SwapDevicesUi(self.profile)
        geom = self.geometry()
        self.modal_windows["swap_devices"].setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        self.modal_windows["swap_devices"].show()
        self.modal_windows["swap_devices"].closed.connect(lambda: self._remove_modal_window("swap_devices"))
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
        el = gremlin.event_handler.EventListener()
        el.request_activate.emit(activate)

    def toggle_remote(self, enable):
        el = gremlin.event_handler.EventListener()
        if enable:
            # request to enable
            el.remote_control_enable.emit()
        else:
            # request to disable
            el.remote_control_disable.emit()

        el.remote_control_changed.emit(enable)
        el.remote_control_state_change.emit()

    def abort(self, message=None):
        gremlin.util.InvokeUiMethod(self._abort_ui, message)  # run on UI thread

    def _abort_ui(self, message=None):
        """aborts profile execution on error"""
        if not gremlin.shared_state.is_running:
            # nothing to abort
            return

        el = gremlin.event_handler.EventListener()

        if not gremlin.shared_state.aborted:
            el.abort.emit()
            gremlin.shared_state.aborted = True  # mark aborting globally

        # update UI
        self.ui.actionActivate.setChecked(False)
        el.request_activate.emit(False)

        # wait for things to stabilize
        QtWidgets.QApplication.processEvents()
        if message:
            gremlin.ui.ui_common.MessageBox(prompt=message)

    def setUiMode(self):
        """enables or disables the UI based on the runtime mode and options

        this can lock the UI while a profile is running to prevent inadvertent changes

        """
        enabled = True
        if gremlin.shared_state.is_running:
            enabled = self.config.runtime_ui_update
            self.push_highlighting()
        else:
            self.pop_highlighting(True)

        self.ui.tab_bar_widget.setEnabled(enabled)
        self.ui.device_page_widget.setEnabled(enabled)
        self.ui.menuTools.setEnabled(enabled)
        self.ui.actionNewProfile.setEnabled(enabled)
        self.ui.actionSaveProfile.setEnabled(enabled)
        self.ui.actionSaveProfileAs.setEnabled(enabled)
        self.ui.actionManageCustomModules.setEnabled(enabled)

        self.ui.actionOptions.setEnabled(enabled)
        self.ui.actionCreate1to1Mapping.setEnabled(enabled)
        # self.ui.actionModifyProfile.setEnabled(enabled)
        self.ui.menuRecent.setEnabled(enabled)
        # self.ui.actionSwapDevices.setEnabled(enabled)
        # self.ui.actionMergeAxis.setEnabled(enabled)

        self.ui.actionManageModes.setEnabled(enabled)

        self.ui.actionInputRepeater.setEnabled(enabled)
        self.ui.actionGenerate.setEnabled(enabled)
        # self.ui.actionImportProfile.setEnabled(enabled)
        self.ui.actionLoadProfile.setEnabled(enabled)

    def activate(self, activate: bool):
        gremlin.util.InvokeUiMethod(self._activate_ui, activate)  # ensure on UI thread

    def _activate_ui(self, activate: bool):
        """Activates and deactivates the code runner.

        :param checked True when the runner is to be activated, False
            otherwise
        """
        import gremlin.shared_state

        if self.activate_locked:
            # syslog.info("Activate: re-entry")
            return

        el = gremlin.event_handler.EventListener()

        try:
            self.abort_received = False
            self.abort_reason = None
            # syslog.info("Activate: start")
            self.activate_locked = True
            is_running = gremlin.shared_state.is_running
            gremlin.shared_state.profile_state = True  # assume all ok

            from gremlin.config import Configuration

            config = Configuration()
            verbose = config.verbose
            _verbose_mode_exec = config.verbose_mode_exec

            if activate:
                # Generate the code for the profile and run it
                if verbose:
                    syslog.info("Activate: activate profile")
                self._profile_auto_activated = False
                # ec = gremlin.execution_graph.ExecutionContext()
                # ec.reset()
                gremlin.shared_state.aborted = False  # reset abort flag

                # start the profile with the specified runtime mode
                result = self.runner.start(
                    self.profile.build_inheritance_tree(),
                    self.profile.settings,
                    self._last_runtime_mode(),
                    self.profile,
                )

                if not result:
                    # profile start failed
                    gremlin.shared_state.profile_state = False
                    self.ui.tray_icon.setIcon(load_icon("icon.ico"))
                    with QtCore.QSignalBlocker(self.ui.actionActivate):
                        self.ui.actionActivate.setChecked(False)  # toolbar icon "off"

                    if not gremlin.shared_state.profile_message_issued:
                        # error message not issued = issue it
                        gremlin.ui.ui_common.MessageBox(
                            title="Profile Start Error",
                            prompt="An error occured when starting the profile.\nCheck the log file for specifics.",
                        )
                        gremlin.shared_state.profile_message_issued = True

                    return

                if gremlin.shared_state.profile_state:
                    # print ("set icon ACTIVE")
                    self.ui.tray_icon.setIcon(load_icon("icon_active.ico"))

                    with QtCore.QSignalBlocker(self.ui.actionActivate):
                        self.ui.actionActivate.setChecked(True)  # toolbar icon "on"

                    return

            else:
                el.profile_stop_toolbar.emit()

            if not gremlin.shared_state.profile_state or is_running:
                # Stop running the code

                # running - save the last running mode to the executing profile
                if verbose:
                    syslog.info("Deactivate profile requested")
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
                current_index = self.ui.devices_tab_header_widget.currentIndex()
                device_guid = self.getDeviceGuidForTabIndex(current_index)
                widget = self.getRegisteredWidget(device_guid)

                if widget:
                    tab_type = widget.data[0]
                    if tab_type in (
                        TabDeviceType.Joystick,
                        TabDeviceType.Keyboard,
                        TabDeviceType.Osc,
                        TabDeviceType.Midi,
                    ):
                        widget.refresh()

                # toolbar icon
                with QtCore.QSignalBlocker(self.ui.actionActivate):
                    self.ui.actionActivate.setChecked(False)  # toolbar icon "off"

                try:
                    if self.ui.tray_icon is not None:
                        self.ui.tray_icon.setIcon(load_icon("icon.ico"))
                except Exception as err:
                    syslog.error(f"Load Icon: error: {err}\n{traceback.format_exc()}")
        except Exception as err:
            syslog.error(f"Activate: error: {err}\n{traceback.format_exc()}")

        finally:
            # syslog.info("Activate: completed")
            self.activate_locked = False

            self.setUiMode()

    @QtCore.Slot()
    def input_repeater(self):
        """Enables or disables the forwarding of events to the repeater."""
        el = gremlin.event_handler.EventListener()
        if self.ui.actionInputRepeater.isChecked():
            el.keyboard_event.connect(self.repeater.process_event)
            el.joystick_event_ui.connect(self.repeater.process_event)
            el.vjoy_event.connect(self.repeater.process_event)
            el.vjoy_output_event.connect(self.repeater.process_event)
            self._update_statusbar_repeater("Waiting for input")
        else:
            el.disconnect(el.keyboard_event, self.repeater.process_event)
            el.disconnect(el.joystick_event_ui, self.repeater.process_event)
            el.disconnect(el.vjoy_event, self.repeater.process_event)
            el.disconnect(el.vjoy_output_event, self.repeater.process_event)
            # el.keyboard_event.disconnect(self.repeater.process_event)
            # el.joystick_event_ui.disconnect(self.repeater.process_event)
            # el.vjoy_event.disconnect(self.repeater.process_event)
            self.repeater.stop()
            self.status_bar_repeater_widget.setText("")

    @QtCore.Slot()
    def input_viewer(self):
        """Displays the input viewer dialog."""
        if self.modal_windows["input_viewer"]:
            # set the focus to that window
            dialog = self.modal_windows["input_viewer"]
            el = gremlin.event_handler.EventListener()
            if el.get_control_state():
                dialog.activateWindow()
                self.ui.actionInputViewer.setChecked(True)
            else:
                # close the window
                dialog.close()

        else:
            dialog = gremlin.ui.input_viewer.InputViewerDialog()
            self.modal_windows["input_viewer"] = dialog

            if not dialog.hasConfig():
                # set size
                geom = self.geometry()
                self.modal_windows["input_viewer"].setGeometry(
                    int(geom.x() + geom.width() / 2 - 350),
                    int(geom.y() + geom.height() / 2 - 150),
                    700,
                    300,
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

    def backup_config(self):
        config = gremlin.config.Configuration()
        config.backup()

    def restore_config(self):
        config = gremlin.config.Configuration()
        config.restore()

    def load_profile(self, fname=None):
        """Prompts the user to select a profile file to load."""
        if not self._save_changes_request():
            return

        if not fname:
            fname, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Load Profile",
                gremlin.shared_state.data_path,
                "XML files (*.xml)",
            )

        if os.path.isfile(fname):
            self._load_recent_profile(fname)

    def import_profile(self):
        """import a profile"""
        gremlin.import_profile.import_profile()

    def new_profile(self):
        """Creates a new empty profile."""
        wm = WorkManager()
        wm.submit(callback=self._new_profile_worker)

    def _new_profile_worker(self, args):
        """Creates a new empty profile."""
        # Disable Gremlin if active before opening a new profile
        if not self._save_changes_request():
            return

        el = gremlin.event_handler.EventListener()

        if gremlin.shared_state.current_profile:
            current_profile = gremlin.shared_state.current_profile
            current_profile.unload()
            gremlin.shared_state.current_profile = None
            el.profile_unloaded.emit()  # tell the UI we're about to load a new profile

        # clear any old data
        self.unregisterAllWidgets()
        self._reset_tab_data()
        while self.getTabCount():
            # wait for the tabs to go poof
            QThread.sleep(0)

        self.clearWidgets()

        ec = gremlin.execution_graph.ExecutionContext()
        ec.reset(no_rebuild=True)

        self.ui.actionActivate.setChecked(False)
        el = gremlin.event_handler.EventListener()
        el.request_activate.emit(False)

        gremlin.shared_state.resetState()
        eh = gremlin.event_handler.EventHandler()
        eh.reset()

        new_profile = gremlin.base_profile.Profile()
        self.profile = new_profile

        # default active mode
        gremlin.shared_state.runtime_mode = "Default"
        gremlin.shared_state.edit_mode = "Default"
        gremlin.shared_state.current_profile = new_profile

        registry = new_profile.registry
        registry.reset()

        # For each connected device create a new empty device entry
        # in the new profile
        for device in gremlin.joystick_handling.physical_devices():
            self.profile.initialize_joystick_device(device, ["Default"])

        # non regular devices
        self.profile.initialize_regular_devices()

        # reload defaults for the profile
        self.profile.settings.loadFilterDefaults()

        # reset joystick input/output flags
        sd = gremlin.event_handler.JoystickState()
        sd.reset()

        # reset event processor
        # jap = gremlin.event_handler.JoystickEventProcessor()
        # jap.reset()

        # Update profile information
        self._update_window_title()

        self.setTabsDirty(True)

        # reset modes
        current_mode = gremlin.shared_state.current_mode
        self.mode_selector.populate_selector(new_profile, current_mode, emit=False)

        # Create a default mode
        for device in self.profile.devices.values():
            device.ensure_mode_exists(mode_name="Default")

        # Update everything to the new mode
        # self._mode_configuration_changed()

        self._update_status_bar()
        self._select_last_tab()

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
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(None, "Save Profile", gremlin.shared_state.data_path, "XML files (*.xml)")
        if fname != "":
            self.profile.setProfileFile(fname)
            self.profile.save()
            # update the hash so we can detect changes
            self._profile_hash = self.profile.getMappingHash()
            self.config.last_profile = self.profile.profile_file
            self._create_recent_profiles()
            self._update_window_title()

    def reveal_profile(self):
        """opens the profile in explorer"""
        profile_fname = self.profile.profile_file
        if profile_fname and os.path.isfile(profile_fname):
            path = os.path.dirname(profile_fname)
            path = os.path.realpath(path)
            webbrowser.open(path)

    def reveal_logfile(self):
        """opens the logfile in the current text editor"""
        logfile = os.path.join(gremlin.shared_state.data_path, "system.log")
        if os.path.isfile(logfile):
            webbrowser.open(logfile)

    def open_profile_xml(self):
        """views the profile as an xml in the default text editor"""
        profile_fname = self.profile.profile_file
        if profile_fname:
            # save first
            self.profile.to_xml(profile_fname)
            if os.path.isfile(profile_fname):
                path = os.path.realpath(profile_fname)
                webbrowser.open(path)

    def open_gremlinex_folder(self):
        """opens the gremlin EX folder"""
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
        # self.ui.actionImportProfile.triggered.connect(self.import_profile)
        self.ui.actionNewProfile.triggered.connect(self.new_profile)
        self.ui.actionSaveProfile.triggered.connect(self.save_profile)
        self.ui.actionSaveProfileAs.triggered.connect(self.save_profile_as)
        self.ui.actionRevealProfile.triggered.connect(self.reveal_profile)
        self.ui.actionOpenLogFile.triggered.connect(self.reveal_logfile)
        self.ui.actionOpenXmlProfile.triggered.connect(self.open_profile_xml)
        self.ui.actionOpenGremlinExFolder.triggered.connect(self.open_gremlinex_folder)
        # self.ui.actionModifyProfile.triggered.connect(self.profile_creator)
        self.ui.actionExit.triggered.connect(self._force_close)
        # Actions
        self.ui.actionCreate1to1Mapping.triggered.connect(self._create_1to1_mapping)
        # self.ui.actionMergeAxis.triggered.connect(self.merge_axis)
        # self.ui.actionSwapDevices.triggered.connect(self.swap_devices)

        # Tools
        self.ui.actionDeviceInformation.triggered.connect(self.device_information)
        # self.ui.actionProfileDevices.triggered.connect(self.change_visible_profile_devices)
        self.ui.actionManageModes.triggered.connect(self.manage_modes)
        self.ui.actionInputRepeater.triggered.connect(self.input_repeater)
        # self.ui.actionCalibration.triggered.connect(self.calibration)
        self.ui.actionInputViewer.triggered.connect(self.input_viewer)

        self.ui.actionReloadDevices.triggered.connect(self._reload_devices)
        self.ui.actionReorderDevices.triggered.connect(self._reorder_tabs)

        self.ui.actionCheatsheet.triggered.connect(lambda: self._create_cheatsheet())
        # self.ui.actionViewInput.triggered.connect(lambda: self._view_input_map())
        self.ui.actionOptions.triggered.connect(self.options_dialog)
        self.ui.actionLogDisplay.triggered.connect(self.log_window)
        self.ui.actionLogEdit.triggered.connect(self.log_edit)
        # About
        self.ui.actionAbout.triggered.connect(self.about)

        # Toolbar actions
        self.ui.actionActivate.triggered.connect(self.menu_activate)
        self.ui.actionOpen.triggered.connect(self.load_profile)
        self.ui.actionSave.triggered.connect(self.save_profile)

        # config backup/restore
        self.ui.actionBackupConfig.triggered.connect(self.backup_config)
        self.ui.actionRestoreConfig.triggered.connect(self.restore_config)

        connected = gremlin.config.Configuration().remoteEnabled()
        self.ui.actionToggleRemoteControl.setChecked(connected)
        self.ui.actionToggleRemoteControl.triggered.connect(self.toggle_remote)

        # Tray icon
        self.ui.tray_icon.activated.connect(self._tray_icon_activated_cb)

        # Simconnect configuration
        self.ui.actionSimconnectOptions.triggered.connect(self.showSimconnectOptions)
        self.ui.actionSimconnectOptionsToolbar.triggered.connect(self.showSimconnectOptions)

    def showSimconnectOptions(self):
        """displays the simconnect options dialog"""
        el = gremlin.event_handler.EventListener()
        el.simconnect_show_options.emit()

    def _create_1to1_mapping(self):
        """maps one to one"""
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

        server_icon = "mdi6.wifi-arrow-up"
        client_icon = "ph.cloud-arrow-down-bold"
        remote_icon = "mdi6.wifi-arrow-up"
        self.status_bar_server_widget = gremlin.ui.ui_common.QOnOffStatusfWidget(
            on_icon=server_icon,
            off_icon=server_icon,
            icon_size=20,
            tooltip="Server state",
        )
        self.status_bar_client_widget = gremlin.ui.ui_common.QOnOffStatusfWidget(
            on_icon=client_icon,
            off_icon=client_icon,
            icon_size=20,
            tooltip="Client state",
        )
        self.status_bar_remote_widget = gremlin.ui.ui_common.QOnOffStatusfWidget(
            on_icon=remote_icon,
            off_icon=remote_icon,
            off_color=gremlin.ui.ui_common.Color.orangeOffColor(),
            on_color=gremlin.ui.ui_common.Color.orangeColor(),
            icon_size=20,
            tooltip="Profile remote state",
        )

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
        self.status_bar_highlight_button_widget.setToolTip(
            "Enable button input highlighting.\nThis mode can also be temporarily enabled while holding a shift key."
        )

        self.status_bar_highlight_enable_widget = QtWidgets.QPushButton()
        self.status_bar_highlight_enable_widget.setStyleSheet("border: none")
        self.status_bar_highlight_enable_widget.setChecked(self.config.highlight_enabled)
        self.status_bar_highlight_enable_widget.clicked.connect(self._toggle_highlight_enabled)
        self.status_bar_highlight_enable_widget.setToolTip("Enable highlighting")

        self.status_bar_module_container_widget = QtWidgets.QWidget()
        self.status_bar_module_container_widget.setContentsMargins(0, 0, 0, 0)
        self.status_bar_module_container_layout = QtWidgets.QHBoxLayout(self.status_bar_module_container_widget)
        self.status_bar_module_container_layout.setContentsMargins(0, 0, 0, 0)

        self._status_bar_module_states = {}
        el = gremlin.event_handler.EventListener()
        el.module_state_change.connect(self._module_state_changed)
        el.module_state_register.connect(self.registerStatusModule)

        widgets = [
            self.status_bar_server_widget,
            self.status_bar_client_widget,
            self.status_bar_remote_widget,
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.ui.statusbar_layout.addWidget(widget)

        self.ui.statusbar_layout.addWidget(self.status_bar_is_active_widget)
        self.ui.statusbar_layout.addWidget(self.status_bar_repeater_widget)
        self.ui.statusbar_layout.addWidget(self.status_bar_mode_widget)

        self.ui.statusbar_layout.addWidget(QtWidgets.QLabel(" "))
        self.ui.statusbar_layout.addWidget(self.status_bar_module_container_widget)

        self.ui_statusbar_highlight_container_widget = QtWidgets.QWidget()
        self.ui_statusbar_highlight_container_widget.setContentsMargins(0, 0, 0, 0)
        self.ui_statusbar_highlight_container_layout = QtWidgets.QHBoxLayout(self.ui_statusbar_highlight_container_widget)
        self.ui_statusbar_highlight_container_layout.setContentsMargins(0, 0, 0, 0)

        self.ui_statusbar_highlight_state_container_widget = QtWidgets.QWidget()
        self.ui_statusbar_highlight_state_container_widget.setContentsMargins(0, 0, 0, 0)
        self.ui_statusbar_highlight_state_container_layout = QtWidgets.QHBoxLayout(self.ui_statusbar_highlight_state_container_widget)
        self.ui_statusbar_highlight_state_container_layout.setContentsMargins(0, 0, 0, 0)

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

        icon_size = QtCore.QSize(16, 16)
        icon = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            use_qta=True,
            qta_color=gremlin.ui.ui_common.Color.recordColor(),
        )
        self._icon_red = icon
        self._status_red = icon.pixmap(icon_size)
        icon = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            use_qta=True,
            qta_color=gremlin.ui.ui_common.Color.activeColor(),
        )
        self._icon_green = icon
        self._status_green = icon.pixmap(icon_size)
        icon = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            use_qta=True,
            qta_color=gremlin.ui.ui_common.Color.inactiveColor(),
        )
        self._icon_gray = icon
        self._status_gray = icon.pixmap(icon_size)

        self._update_highlight_toolbar_enabled()
        self._update_status_bar()

    def _update_highlight_toolbar_enabled(self):
        """updates the enabled status of the highlight status bar buttons based on current enabled state"""
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
    def registerStatusModule(self, key, label: str, state: object, callback):
        """registersor updates a module with a state"""
        if key:
            self._status_bar_module_states[key] = (label, state, callback)
            self._update_status_bar_modules()

    @QtCore.Slot(str, object)
    def _module_state_changed(self, key, state: object):
        # syslog = logging.getLogger("system")
        syslog.info(f"module state: {key} state: {state}")
        if key in self._status_bar_module_states:
            label, value, callback = self._status_bar_module_states[key]
            if value != state:
                self._status_bar_module_states[key] = (label, state, callback)
                self._update_status_bar_modules_ui()

    def _update_status_bar_modules(self):
        gremlin.util.InvokeUiMethod(self._update_status_bar_modules_ui)  # ensure on UI thread

    def _update_status_bar_modules_ui(self):
        """recreates the module status bar UI based on current status - this is used for modules to add content to the status bar at runtime"""
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
                    pixmap = state.pixmap(24, 24)

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
        status = not status
        eh.toggle_highlight.emit(status, None, None)
        self.config.highlight_autoswitch = status

    @QtCore.Slot()
    def _toggle_axis_highlight(self):
        eh = gremlin.event_handler.EventListener()
        status = self.config.highlight_input_axis
        enabled = not status
        self.config.highlight_input_axis = enabled
        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui:
            syslog.info(f"Toggle axis highlight: {enabled}")
        eh.toggle_highlight.emit(None, enabled, None)

    @QtCore.Slot()
    def _toggle_button_highlight(self, checked: bool):
        eh = gremlin.event_handler.EventListener()

        status = self.config.highlight_input_buttons
        enabled = not status
        self.config.highlight_input_buttons = enabled

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui:
            syslog.info(f"Toggle button highlight: {enabled}")
        eh.toggle_highlight.emit(None, None, enabled)

    @QtCore.Slot()
    def _toggle_highlight_enabled(self, checked: bool):
        self.config.highlight_enabled = not self.config.highlight_enabled
        el = gremlin.event_handler.EventListener()
        el.enable_highlight_changed.emit(checked)

    @QtCore.Slot(bool)
    def _highlight_enable_changed(self, enabled: bool):
        self._update_highlight_toolbar_enabled()
        if enabled:
            # reset the highlight stack
            gremlin.shared_state.pop_suspend_highlighting(True)

    def _create_system_tray(self):
        """Creates the system tray icon and menu."""
        self.ui.tray_menu = QtWidgets.QMenu("Menu")
        self.ui.action_tray_show = QtGui.QAction("Show / Hide", self)
        self.ui.action_tray_enable = QtGui.QAction("Start/Stop profile", self)
        self.ui.action_tray_quit = QtGui.QAction("Quit", self)
        self.ui.tray_menu.addAction(self.ui.action_tray_show)
        self.ui.tray_menu.addAction(self.ui.action_tray_enable)
        self.ui.tray_menu.addAction(self.ui.action_tray_quit)

        self.ui.action_tray_show.triggered.connect(self._show_hide_cb)

        self.ui.action_tray_enable.triggered.connect(self.ui.actionActivate.trigger)
        self.ui.action_tray_quit.triggered.connect(self._force_close)

        self.ui.tray_icon = QtWidgets.QSystemTrayIcon()
        self.ui.tray_icon.setIcon(load_icon("icon.ico"))
        self.ui.tray_icon.setContextMenu(self.ui.tray_menu)
        self.ui.tray_icon.show()

    def _show_hide_cb(self):
        """show or hide the window"""
        if self.isHidden():
            self.setHidden(False)
            self.showNormal()
        else:
            self.setHidden(True)

    def hideDeviceContent(self):
        """hides the device content"""
        if gremlin.util.is_ui_thread():
            self._set_content_index_ui(0)
        else:
            gremlin.util.InvokeUiMethod(self._set_content_index_ui, 0)

    def showDeviceContent(self, device_guid: dinput.GUID | str = None):
        """shows the content for the specified device"""
        if device_guid:
            device_id = gremlin.util.normalize_guid(device_guid)
        else:
            device_id = self.getActiveTabDeviceGuid()

        if device_id in self._widget_device_index_map:
            index = self._widget_device_index_map[device_id]
        else:
            index = 0  # Hide
        if __debug__:
            device = gremlin.joystick_handling.getDevice(device_id)
            device_name = device.name if device is not None else "<unknown>"
            syslog.info(f"show content page: [{device_name}] index: [{index}] id: [{device_id}] ")
        self.setDeviceContentIndex(index)

    def setDeviceContentIndex(self, index: int):
        """sets the page index for the device content - 0 is the empty page"""
        if self._loading_stack:
            # displaying idle, ignore and remember what to change to
            self._loading_stack_target = index
            return

        if gremlin.util.is_ui_thread():
            self._set_content_index_ui(index)
        else:
            gremlin.util.InvokeUiMethod(self._set_content_index_ui, index)

    def _set_content_index_ui(self, index: int):
        current_index = self.ui.device_page_widget.currentIndex()
        if current_index != index:
            self.ui.device_page_widget.setCurrentIndex(index)
            if index:
                # not the empty page
                widget = self.ui.device_page_widget.widget(index)
                if isinstance(widget, BaseDeviceTabWidget):
                    widget.ensureLoaded()
                self.ui.device_page_widget.update()
            # self.ui.device_widget.repaint() # redraw now

    def registerWidget(self, device_guid: dinput.Guid | str, widget, hide=True) -> int:
        """registers widget for cleanup - this is needed because QT doesn't tell us when widgets are discarded so we need to manually track this here
        so widgets cleanup correctly and remove any hooks / references

        :returns: index - the index of the widget

        """

        assert widget is not None, "Invalid widget"

        device_id = gremlin.util.normalize_guid(device_guid)

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(2)
        # verbose = True

        index = self.ui.device_page_widget.indexOf(widget)
        if index != -1:
            # widget is already in the list
            device_name = self._get_device_name(device_id)
            syslog.error(f"TAB: widget already exists for tab: {device_id} {device_name}")
        else:
            self.ui.device_page_widget.addWidget(widget)

        index = self.ui.device_page_widget.indexOf(widget)
        self._widget_device_index_map[device_id] = index
        self._widget_index_device_map[index] = device_id
        device_name = self._get_device_name(device_id)
        if verbose:
            syslog.info(f"REGISTER WIDGET: {device_id} index {index}  name: {device_name}")

        return index

    def selectRegisteredWidget(self, device_guid) -> int:
        """selects the content for the given device id if the content exists

        :param device_guid: device to select
        :returns: index, -1 if not found

        """
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        index = -1
        if device_guid in self._widget_device_index_map:
            index = self._widget_device_index_map[device_guid]
            if index == -1:
                device_name = self._get_device_name(device_guid)
                syslog.warning(f"Requested widget for device [{device_guid}] [{device_name}] not found.")
            else:
                self.setDeviceContentIndex(index)

        return index

    def unregisterWidget(self, device_guid):
        """removes a widget from the cleanup list"""
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._widget_device_index_map:
            index = self._widget_device_index_map[device_guid]
            if index != -1:
                widget = self.ui.device_page_widget.widget(index)
                if hasattr(widget, "_cleanup_ui"):
                    widget._cleanup_ui()
                self.ui.device_page_widget.removeWidget(widget)
                widget.deleteLater()
            del self._widget_device_index_map[device_guid]
            del self._widget_index_device_map[index]

    def getCurrentRegisteredWidgetDeviceGuid(self):
        """gets the device ID for the currently selected device widget"""
        index = self.ui.device_page_widget.currentIndex()
        if index != -1:
            # returns None on invalid index
            widget = self.ui.device_page_widget.widget(index)
            if widget:
                tab_data: gremlin.tabstate.TabData = self.ui.devices_tab_header_widget.tabData(index)
                return tab_data.device_guid
        return None

    def clearRegisteredWidgets(self):
        """cleanup all widgets"""
        return self.unregisterAllWidgets()

    def _unregister_all_widgets_ui(self):
        """removes all widgets from the devices tab widget"""
        # remove python references
        for index in self._widget_device_index_map.values():
            widget = self.ui.device_page_widget.widget(index)
            if widget:
                widget.hide()
                self.ui.device_page_widget.removeWidget(widget)
                gremlin.util.delete_widget(widget)

        self._widget_device_index_map.clear()
        self._widget_index_device_map.clear()

        # manual QT cleanup
        stacked_widget = self.ui.device_page_widget
        gremlin.ui.ui_common.clearStackedWidget(stacked_widget)

    def unregisterAllWidgets(self):
        """clears all device widgets"""
        gremlin.util.InvokeUiMethod(self._unregister_all_widgets_ui)  # ensure on UI thread

    def getRegisteredWidget(self, device_guid) -> QtWidgets.QWidget:
        """gets the widget for the given device id, None if not found"""
        device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._widget_device_index_map:
            index = self._widget_device_index_map[device_guid]
            return self.ui.device_page_widget.widget(index)
        return None

    def getCurrentRegisteredWidget(self) -> QtWidgets.QWidget:
        """gets the widget for the currently selected device"""
        index = self.ui.device_page_widget.currentIndex()
        tab_data = self._get_tab_data_at(index)
        if tab_data:
            device_guid = tab_data.device_guid
            return self.getRegisteredWidget(device_guid)
        return None

    def getRegisteredWidgetIndex(self, device_guid) -> int:
        device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._widget_device_index_map:
            return self._widget_device_index_map[device_guid]
        return None

    def clearWidgets(self):
        """clears the device cache"""
        tracker = gremlin.ui.ui_common.StateTracker()
        tracker.clear()
        # self.unregisterAllWidgets()
        verbose = gremlin.config.Configuration().verbose_mode_ui
        # gc.collect()
        if verbose:
            syslog.info("TABS TRACKER: clear()")

    def getTabIndexForDevice(self, device_guid):
        device_guid = gremlin.util.to_guid(device_guid)
        if device_guid in self._tab_device_map:
            return self._tab_device_map[device_guid]
        return -1

    def getFirstTabDeviceGuid(self):
        """gets the device for the first tab"""
        for device_guid in self._tab_device_map.keys():
            return device_guid
        return None

    def getDeviceGuidForTabIndex(self, index):
        """gets the device GUID for a given tab index"""
        if index in self._tab_index_map:
            return self._tab_index_map[index]

    def swapTab(self, index, other):
        """swaps two values in the map"""
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
        """gets the device widget by the tab index"""
        if index in self._tab_index_map:
            device_guid = self._tab_index_map[index]
            return self.getRegisteredWidget(device_guid)
        return None

    def hideTabWidgets(self):
        """hides all tab widgets"""
        if gremlin.shared_state.ui_ready:
            for widget in self._widget_device_index_map.values():
                if widget.parent():
                    widget.setVisible(False)

    def selectTabWidgetByIndex(self, index: int):
        """shows the page (content widget) for the specified tab index"""
        if index in self._tab_index_map:
            device_guid = self._tab_index_map[index]
            self.selectTabWidget(device_guid)

    def selectTabWidget(self, device_guid):
        """shows the page (content widget) for the specified device"""
        device_guid = gremlin.util.to_guid(device_guid)

        el = gremlin.event_handler.EventListener()
        verbose = gremlin.config.Configuration().verbose_mode_extra

        # select the tab index

        # index of new tab
        index = self.getTabIndexForDevice(device_guid)
        if index is None or index == -1:
            # nothing to do
            return

        # index of old tab
        current_index = self.ui.devices_tab_header_widget.currentIndex()

        if current_index != index:
            # indicate the old tab is being deselected
            td: gremlin.tabstate.TabData = self.ui.devices_tab_header_widget.tabData(current_index)
            old_device_guid = td.device_guid
            if verbose:
                device_name = self._get_device_name(old_device_guid)
                syslog.info(f"TAB UNSELECT: {device_name}")

            # notify the old tab we're changing
            el.tab_unselected.emit(old_device_guid)

            if verbose:
                device_name = self._get_device_name(device_guid)
                syslog.info(f"TAB SELECT: {device_name}")

            # select the new tab
            with QtCore.QSignalBlocker(self.ui.devices_tab_header_widget):
                self.ui.devices_tab_header_widget.setCurrentIndex(index)
                if verbose:
                    syslog.info(f"TAB SELECT: {device_name}")

            # el.tab_selected.emit(device_guid)

            # select the current tab
            with QtCore.QSignalBlocker(self.ui.devices_tab_header_widget):
                self.ui.devices_tab_header_widget.setCurrentIndex(index)

        # ensure the widget is displayed
        widget = self.getWidgetByTabIndex(index)
        if widget is not None:
            index = self.ui.device_page_widget.indexOf(widget)
            assert index != -1, "device widget not found in the UI"
            self.setDeviceContentIndex(index)

    def getActiveTabWidget(self) -> gremlin.ui.ui_common.QSplitTabWidget:
        """gets the current tab widget"""
        return self.getCurrentRegisteredWidget()

    def getActiveTabIndex(self) -> int:
        """gets the current tab index"""
        return self.ui.devices_tab_header_widget.currentIndex()

    def getActiveTabDeviceGuid(self):
        """gets the active device GUID"""
        index = self.ui.devices_tab_header_widget.currentIndex()
        if index != -1:
            data: gremlin.tabstate.TabData = self.ui.devices_tab_header_widget.tabData(index)
            return data.device_guid
        return None

    def getActiveTabType(self) -> TabDeviceType:
        index = self.ui.devices_tab_header_widget.currentIndex()
        if index != -1:
            data: gremlin.tabstate.TabData = self.ui.devices_tab_header_widget.tabData(index)
            return TabDeviceType(data.tab_type)
        return None

    def _mapping_changed(self, item_data: InputItem):
        """called when mapping changes"""

        self._update_tab(item_data.device_id)  # update tab header

    def _show_container_id_visible_changed(self):
        """refresh the UI on container visibility changed"""
        self.refresh()

    def _update_tab(self, device_id: str):
        gremlin.util.InvokeUiMethod(self._update_tab_ui, device_id)

    def _update_tab_ui(self, device_id: str):
        """updates the given tab for mapping and connection status - sets tab color and icons based on the device"""
        position = self.getTabIndexForDevice(device_id)

        if position is not None:
            # determine the status
            device = gremlin.joystick_handling.getDevice(device_id)
            if device:
                device.update()  # update connection state
                if not device.connected:
                    # indicate device is disconnected
                    color = gremlin.ui.ui_common.Color.tabMissingForegroundColor()
                    icon = gremlin.ui.ui_common.Icons.disconnectedIcon()  # .load_icon("mdi.power-plug-off", qta_color = color)
                    self.ui.devices_tab_header_widget.setTabIcon(position, icon)
                    self.ui.devices_tab_header_widget.setTabTextColor(position, color)
                else:
                    # tab color based on mapping
                    mode_map = self._get_mappings(device_id)
                    edit_mode = gremlin.shared_state.edit_mode
                    has_active_map = edit_mode in mode_map and mode_map[edit_mode]
                    has_map = False
                    if has_active_map:
                        color = gremlin.ui.ui_common.Color.tabUsedForegroundColor()
                        icon = gremlin.ui.ui_common.Icons.mappedIcon(qta_color=color)
                    else:
                        has_map = sum(mode_map.values()) > 0
                        if has_map:
                            color = gremlin.ui.ui_common.Color.tabUsedOtherForegroundColor()
                            icon = gremlin.ui.ui_common.Icons.mappedOtherIcon(qta_color=color)
                        else:
                            color = gremlin.ui.ui_common.Color.tabForegroundColor()
                            icon = QtGui.QIcon()

                    self.ui.devices_tab_header_widget.setTabTextColor(position, color)
                    self.ui.devices_tab_header_widget.setTabIcon(position, icon)  # clear the icon

    def _handle_feature_changed(self, feature):
        """called when a feature changes"""
        self.setTabsDirty(update=True)  # mark tabs as dirty and updateD

    def setTabsDirty(self, update=False):
        """indicate tabs must be refreshed next time create tabs is called"""

        if gremlin.shared_state.profile_loading:
            # ignore if loading a profile
            return

        self._tab_device_map.clear()  # remove tab data to force a tab reload

        if update:
            self._create_tabs()

    @QtCore.Slot()
    def _handle_on_change(self):
        """manual lambda for QT memory references"""
        self._create_tabs_ui()

    def _create_tabs(self, activate_tab=None):
        gremlin.util.InvokeUiMethod(self._create_tabs_ui)

    def _get_vjoy_input_enabled(self, device):
        """gets the vjoy input enabled state"""
        if device:
            if device.vjoy_id in self.profile.settings.vjoy_as_input:
                return self.profile.settings.vjoy_as_input.get(device.vjoy_id, False)
        return False

    def _get_maestro_input_enabled(self, device):
        """gets the maestro input enabled state"""
        if device:
            if device.virtual_id in self.profile.settings.maestro_as_input:
                return self.profile.settings.maestro_as_input.get(device.virtual_id, False)
        return False

    def _map_insert(self, data: dict, index: int, count: int, value):
        """inserts an index into a dictionary and moves all entries up as needed"""
        if index in data:
            for i in range(count, index + 1, step=-1):
                data[i] = data[i - 1]
        data[index] = value

    def _get_sorted_tab_map(self, reset=False) -> tuple:
        """gets the sorted tab information  - either user order or sorted order by device name

        returns a tuple of (sorted_device, physical_devices, vjoy_devices, special_devices, tab map)
        list: list of dinput.DeviceSummary object in tab order

        dict:
        key = (device_id : str, device_name : str, tab_type : TabDeviceType, tab_index: int )
        value: same as key

        """
        verbose = self.config.verbose_mode_ui_level(1)
        verbose_detailed = self.config.verbose_mode_ui_level(2)
        tab_map = self.config.tab_list

        # physical joysticks
        physical_devices = [dev for dev in gremlin.joystick_handling.all_joystick_devices() if dev.device_category == DeviceCategory.Physical]

        # add vjoy input devices
        vjoy_devices = [dev for dev in gremlin.joystick_handling.all_vjoy_devices() if self._get_vjoy_input_enabled(dev)]
        maestro_devices = [dev for dev in gremlin.joystick_handling.all_maestro_devices() if self._get_maestro_input_enabled(dev)]

        # add special devices
        sd = gremlin.joystick_handling.getSpecialDevices()
        special_devices = list(sd)

        # plugin/settings
        cd = gremlin.joystick_handling.getConfigDevices()
        config_devices = list(cd)

        section_map = {
            DeviceCategory.Physical: physical_devices,
            DeviceCategory.Virtual: vjoy_devices + maestro_devices,
            DeviceCategory.Special: special_devices,
            DeviceCategory.Config: config_devices,
        }

        if not reset and tab_map:
            # existing device order configuration data saved
            # don't resort but add or remove any devices not in the map or connected since then

            # holds saved devices by category
            category_map = {
                DeviceCategory.Physical: [],
                DeviceCategory.Virtual: [],
                DeviceCategory.Special: [],
                DeviceCategory.Config: [],
            }

            # build the tab list using existing tab order or default tab order if an existing isn't set
            sorted_devices = []
            id_list = []
            data: TabData
            # sort the tab map by index
            index, pair = tab_map.items().__iter__().__next__()
            if isinstance(pair, (list, tuple)):
                item_list = [(int(index), gremlin.joystick_handling.getDevice(device_id), visible) for index, (device_id, visible) in tab_map.items()]
            else:
                item_list = [(int(index), gremlin.joystick_handling.getDevice(device_id), True) for index, device_id in tab_map.items()]
            item_list.sort(key=lambda x: x[0])
            invisible_list = []
            for index, device, visible in item_list:
                if not device:
                    # skip if disconnected
                    continue
                if device.device_id in id_list:
                    # in case the file was edited manually look for dups
                    continue
                if device.disabled:
                    # skip disabled devices
                    continue
                if not visible:
                    # skip hidden devices
                    invisible_list.append(device)
                    continue
                if device.is_virtual:
                    # skip devices if the VJOY device is not setup as input
                    input_enabled = self.profile.settings.vjoy_as_input.get(device.vjoy_id, False)
                    if not input_enabled:
                        continue

                id_list.append(device.device_id)
                sorted_devices.append((device.device_id, device.name, device))
                category_map[device.device_category].append(device)
                if verbose:
                    syslog.info(f"from saved tabs: add index [{index}] [{device.device_name}]")

            # add any missing devices connected but not in the tab map

            for category, section in section_map.items():
                missing_devices = [dev for dev in section if dev not in category_map[category]]
                # index of the last item per section
                for device in missing_devices:
                    # next index
                    if device.disabled:
                        # skip
                        continue
                    if device in invisible_list:
                        # skip
                        continue
                    sorted_devices.append((device.device_id, device.name, device))

        else:
            # setup default sorting order is by name (index 1 of id, name, dev triplets)
            # default is sort by physical, vjoy, special and config and by name within these categories
            physical_devices.sort(key=lambda x: x.name)
            special_devices.sort(key=lambda x: x.name)
            config_devices.sort(key=lambda x: x.name)
            vjoy_devices.sort(key=lambda x: x.name)
            maestro_devices.sort(key=lambda x: x.name)
            sorted_devices = [
                (device.device_id, device.name, device) for device in physical_devices + vjoy_devices + maestro_devices + special_devices + config_devices
            ]

        index = 0

        # update new tab map
        tab_map = {}
        for id, name, device in sorted_devices:
            tab_map[index] = id
            index += 1

        if verbose_detailed:
            syslog.info("UI: Stored device tabs ----------")
            self._dump_tab_map(tab_map)

        indexed_map = {}
        for index, triplet in enumerate(sorted_devices):
            indexed_map[index] = triplet[0]  # index, device_id

        # return data block
        data = {
            "tab_map": tab_map,
            "sorted": sorted_devices,
            "physical": physical_devices,
            "vjoy": vjoy_devices,
            "maestro": maestro_devices,
            "special": special_devices,
            "config": config_devices,
            "index_map": indexed_map,
        }

        # verbose = True
        if verbose:
            syslog.info("Derived sorted device list:")
            index = 0
            for id, name, dev in sorted_devices:
                syslog.info(f"\t[{index}] [{dev.device_category.name}] [{name}] [{id}] ")
                index += 1
            pass

        return data

    def _create_tabs_ui(self, activate_tab=None):
        """Creates the tabs of the configuration dialog representing
        the different connected devices.
        """

        assert gremlin.util.is_ui_thread(), "UI updates must be performed on the main UI thread"

        # record the update requirement
        if self._suspend_ui_update:
            self._ui_update_pending = True
            return

        try:
            self.pushLoading()

            # clear all cached widgets
            self._unregister_all_widgets_ui()
            self.clearWidgets()

            gremlin.shared_state.push_redraw()
            reset = len(self._tab_device_map) == 0

            # sd = gremlin.event_handler.JoystickState()
            ts = gremlin.tabstate.TabState()

            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_device or config.verbose_mode_ui
            verbose_l1 = verbose and config.verbose_mode_l1
            # verbose_l1 = True
            verbose_detailed = verbose and config.verbose_mode_extra

            if verbose_l1:
                syslog.info("CREATE TAB: start")

            # if verbose_detailed: syslog.info("CREATE TAB: start")

            device: DeviceSummary
            device_guid = None

            midi_enabled = self.config.midi_enabled
            osc_enabled = self.config.osc_enabled

            self.push_highlighting()
            el = gremlin.event_handler.EventListener()
            gremlin.shared_state.push_input_selection()  # prevent selections

            if reset:
                self._reset_tab_data()
                self.clearWidgets()
                self.last_tab_index = 0

            # reload device list in case it changed
            gremlin.shared_state.reload_device_map()

            gremlin.shared_state.push_suspend_save_input()

            gremlin.shared_state.is_tab_loading = True

            # clear the widget map as it's recreated here
            # gremlin.shared_state.device_widget_map.clear()

            # update device lists
            phys_devices = gremlin.joystick_handling.physical_devices()
            vjoy_devices = gremlin.joystick_handling.virtual_devices()
            maestro_devices = gremlin.joystick_handling.all_maestro_devices()
            self._active_devices = gremlin.joystick_handling.all_joystick_devices()

            # get list of devices in the profile that do not exist or are not connected
            graph: gremlin.profile_graph.ProfileGraph = gremlin.shared_state.current_profile.graph

            graph_devices = graph.joystick_devices()

            # derive missing devices found in the profile, but not currently connected
            missing_phys_devices = [
                dev
                for dev in graph_devices
                if dev.device_guid not in [d.device_guid for d in phys_devices] and dev.device_type == gremlin.types.DeviceType.Joystick
            ]
            missing_vjoy_devices = [
                dev
                for dev in graph_devices
                if dev.device_guid not in [d.device_guid for d in vjoy_devices] and dev.device_type == gremlin.types.DeviceType.VJoy
            ]
            missing_maestro_devices = [
                dev
                for dev in graph_devices
                if dev.device_guid not in [d.device_guid for d in maestro_devices] and dev.device_type == gremlin.types.DeviceType.Maestro
            ]

            self._missing_phys_devices = missing_phys_devices
            self._missing_vjoy_devices = missing_vjoy_devices
            self._missing_maestro_devices = missing_maestro_devices

            for device in self._missing_phys_devices + self._missing_vjoy_devices + self._missing_maestro_devices:
                gremlin.joystick_handling.registerSpecialDevice(device)

            if verbose:
                for device in self._missing_phys_devices:
                    syslog.warning(f"Missing device: {str(device)}")

            all_phys_devices = missing_phys_devices + phys_devices
            all_vjoy_devices = missing_vjoy_devices + vjoy_devices
            all_maestro_devices = missing_maestro_devices + maestro_devices

            self._all_devices_map = {}
            for device in all_phys_devices + all_vjoy_devices + all_maestro_devices:
                self._all_devices_map[device.device_id] = device

            # index of the current tab being addded
            index = 0

            data = self._get_sorted_tab_map()
            sorted_devices = data["sorted"]
            physical_devices = data["physical"]
            vjoy_devices = data["vjoy"]
            maestro_devices = data["maestro"]
            special_devices = data["special"]
            config_devices = data["config"]
            self._tab_map = data["tab_map"]
            gremlin.shared_state.tab_devices = {id: dev for id, _, dev in sorted_devices}

            self._vjoy_input_device_guids = [dev.device_guid for dev in vjoy_devices]

            # get the last device selected to determine which tab should be active
            active_device_guid = config.last_device_guid
            active_device: DeviceSummary = gremlin.joystick_handling.getDevice(active_device_guid) if active_device_guid else None
            if not active_device:
                # not found - pick the first one by tab order

                _, _, active_device = sorted_devices[0]
                active_device_guid = active_device.device_guid
                gremlin.shared_state.setActiveDeviceGuid(active_device_guid)

            if verbose_l1:
                syslog.info(f"TABS: active device: [{active_device.name}] id: [{active_device.device_id}]")

            visible_map = config.device_visible_map

            # reset tab selector
            self._clear_tabs_ui()

            tab_device_list = []

            for device_id, device_name, device in sorted_devices:
                if device.disabled:
                    if verbose_l1:
                        syslog.info(f"\tdevice [{device_name}] is disabled - skipping tab")
                    continue
                visible = visible_map[device_id] if device_id in visible_map else True
                device.visible = visible
                if not visible:
                    if verbose_l1:
                        syslog.info(f"\tdevice [{device_name}] is hidden - skipping tab")
                    continue

                if self.profile.isRemovedDevice(device_id):
                    if verbose_l1:
                        syslog.info("\tremoved by user - skipping tab")
                    continue
                if verbose:
                    syslog.info(f"TAB: [{index}] processing device [{device_name}]  [{device_id}]")

                if device in physical_devices:
                    device_profile = self.profile.get_device_modes(device.device_guid, DeviceType.Joystick, device.name)

                    # this needs to be registered before widgets are created because widgets may need this data
                    gremlin.shared_state.device_profile_map[device.device_guid] = device_profile
                    gremlin.shared_state.device_type_map[device.device_guid] = DeviceType.Joystick

                    if verbose:
                        syslog.info(f"Device tab widget: for [{device.name}]")

                    device_guid = device.device_id
                    device_name = device.name
                    if device_name:
                        widget = self.getRegisteredWidget(device_guid)
                        if not widget or not Shiboken.isValid(widget):
                            if verbose_l1:
                                syslog.info(f"\tcreating device widget for [{device.name}].")
                            widget = gremlin.ui.joystick_device.JoystickDeviceTabWidget(
                                device=device,
                                mode=self.current_mode,
                                profile=self.profile,
                                object_name=f"Joystick [{device_name}]",
                            )

                            self.registerWidget(device_guid, widget)

                            widget.tabData = ts.getData(device_guid)

                            widget.data = (TabDeviceType.Joystick, device_guid, index)

                            index += 1

                            #  pick a default entry for each tab if one is not currently selected
                            device_guid = self.config.last_device_guid
                            _, last_input_id = self._get_last_input(device_guid)
                            if last_input_id is None:
                                # get the first input item of the tab
                                input_item = self._get_input_item(device_guid, 0)
                                if input_item:
                                    self.config.last_device_guid = device_guid

                    # add tab header for this device
                    if device not in tab_device_list:
                        self._add_tab(device.device_guid, TabDeviceType.Joystick)
                        tab_device_list.append(device)
                        index += 1

                elif device in vjoy_devices:
                    # =======================================================
                    # vjoy input devices

                    # Create vJoy as input device tabs

                    device_guid = gremlin.util.normalize_guid(device.device_guid)
                    device_name = device.name
                    input_enabled = self.profile.settings.vjoy_as_input.get(device.vjoy_id, False)

                    if not input_enabled:
                        if verbose_l1:
                            syslog.info(f"VJOY TAB: {device_name} not created because input is disabled on this device.")
                        continue
                    if not device.connected:
                        if verbose_l1:
                            syslog.info(f"VJOY TAB: {device_name} not created because device is not connected.")
                        continue

                    index += 1

                    # vjoy as input enabled
                    widget = self.getRegisteredWidget(device_guid)
                    if widget is not None and Shiboken.isValid(widget):
                        # found cached widget for this device
                        continue

                    if not widget:
                        widget = gremlin.ui.joystick_device.JoystickDeviceTabWidget(
                            device=device,
                            profile=self.profile,
                            mode=self.current_mode,
                            object_name=f"Vjoy [{device_name}]",
                        )

                        self.registerWidget(device_guid, widget)

                    widget.data = (TabDeviceType.VjoyInput, device_guid, index)
                    # add tab header for this device
                    if device not in tab_device_list:
                        self._add_tab(device.device_guid, TabDeviceType.VjoyInput)
                        tab_device_list.append(device)
                        index += 1
                        if verbose_l1:
                            syslog.info(f"Added vjoy tab: {device_name} index {index}")

                elif device in maestro_devices:
                    # =======================================================
                    # Maestro input devices

                    # Create Maestro as input device tabs

                    device_guid = gremlin.util.normalize_guid(device.device_guid)
                    device_name = device.name
                    input_enabled = self.profile.settings.maestro_as_input.get(device.virtual_id, False)

                    if not input_enabled:
                        if verbose_l1:
                            syslog.info(f"MAESTRO TAB: {device_name} not created because input is disabled on this device.")
                        continue
                    if not device.connected:
                        if verbose_l1:
                            syslog.info(f"MAESTRO TAB: {device_name} not created because device is not connected.")
                        continue

                    index += 1

                    # Maestro as input enabled
                    widget = self.getRegisteredWidget(device_guid)
                    if widget is not None and Shiboken.isValid(widget):
                        # found cached widget for this device
                        continue

                    if not widget:
                        widget = gremlin.ui.joystick_device.JoystickDeviceTabWidget(
                            device=device, profile=self.profile, mode=self.current_mode, object_name=device_name
                        )

                        self.registerWidget(device_guid, widget)

                    widget.data = (TabDeviceType.MaestroInput, device_guid, index)
                    # add tab header for this device
                    if device not in tab_device_list:
                        self._add_tab(device.device_guid, TabDeviceType.MaestroInput)
                        tab_device_list.append(device)
                        index += 1
                        if verbose_l1:
                            syslog.info(f"Added Maestro tab: {device_name} index {index}")

                elif device in special_devices:
                    # =======================================================
                    # special devices

                    match device.device_type:
                        case DeviceType.Keyboard:
                            # =======================================================
                            # Create keyboard tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
                            device_profile = self.profile.get_device_modes(
                                dinput.GUID_Keyboard,
                                DeviceType.Keyboard,
                                DeviceType.to_string(DeviceType.Keyboard),
                            )

                            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.keyboard_tab_guid)
                            device = gremlin.joystick_handling.getDevice(device_guid)

                            widget = self.getRegisteredWidget(device_guid)
                            if not widget:
                                # create the keyboard device
                                widget = gremlin.ui.keyboard_device.KeyboardDeviceTabWidget(self.profile, self.current_mode)

                                self.registerWidget(device_guid, widget)
                                gremlin.shared_state.device_type_map[dinput.GUID_Keyboard] = DeviceType.Keyboard

                                widget.data = (
                                    TabDeviceType.Keyboard,
                                    device_guid,
                                    index,
                                )
                                self._keyboard_device_guid = device_guid

                            # add tab header for this device
                            if device not in tab_device_list:
                                self._add_tab(
                                    device.device_guid,
                                    TabDeviceType.Keyboard,
                                    override_name="Keyboard/Mouse",
                                )
                                tab_device_list.append(device)
                                index += 1

                        case DeviceType.Midi:
                            # =======================================================
                            # Create MIDI tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
                            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.midi_tab_guid)
                            device = gremlin.joystick_handling.getDevice(device_guid)

                            if midi_enabled:
                                widget = self.getRegisteredWidget(device_guid)
                                if not widget:
                                    # create the device
                                    widget = gremlin.ui.midi_device.MidiDeviceTabWidget(profile=self.profile, mode=self.current_mode)

                                    self.registerWidget(device_guid, widget)
                                    self._midi_device_guid = device_guid

                                    gremlin.shared_state.device_type_map[gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid] = DeviceType.Midi
                                    # gremlin.shared_state.device_widget_map[gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid] = widget

                                    widget.data = (
                                        TabDeviceType.Midi,
                                        device_guid,
                                        index,
                                    )
                                # add tab header for this device
                                if device not in tab_device_list:
                                    self._add_tab(device.device_guid, TabDeviceType.Midi)
                                    tab_device_list.append(device)
                                    index += 1

                        case DeviceType.Osc:
                            # =======================================================
                            # Create OSC tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
                            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.osc_tab_guid)
                            device = gremlin.joystick_handling.getDevice(device_guid)

                            if osc_enabled:
                                widget = self.getRegisteredWidget(device_guid)
                                if not widget:
                                    widget = gremlin.ui.osc_device.OscDeviceTabWidget(profile=self.profile, mode=self.current_mode)

                                    self.registerWidget(device_guid, widget)
                                    self._osc_device_guid = device_guid

                                    gremlin.shared_state.device_type_map[device_guid] = DeviceType.Osc
                                    # gremlin.shared_state.device_widget_map[gremlin.ui.osc_device.OscDeviceTabWidget.device_guid] = widget

                                    widget.data = (
                                        TabDeviceType.Osc,
                                        device_guid,
                                        index,
                                    )
                                # add tab header for this device
                                if device not in tab_device_list:
                                    self._add_tab(device.device_guid, TabDeviceType.Osc)
                                    tab_device_list.append(device)
                                    index += 1

                        case DeviceType.OctaviIFR1:
                            # =======================================================
                            # create Octavi IFR1 if it exists (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
                            oo = gremlin.ui.octavi_device.OctaviInterface()
                            if oo.deviceFound():
                                guid = gremlin.shared_state.octavi_tab_guid
                                device_guid = gremlin.util.normalize_guid(guid)
                                device_type = DeviceType.OctaviIFR1

                                widget = self.getRegisteredWidget(device_guid)
                                if not widget:
                                    widget = gremlin.ui.octavi_device.OctaviDeviceTabWidget(profile=self.profile, mode=self.current_mode)
                                    self.registerWidget(device_guid, widget)
                                    self._state_device_guid = device_guid

                                    widget.data = (
                                        TabDeviceType.OctaviIFR1,
                                        device_guid,
                                        index,
                                    )

                                # add tab header for this device
                                if device not in tab_device_list:
                                    self._add_tab(device.device_guid, TabDeviceType.OctaviIFR1)
                                    tab_device_list.append(device)
                                    gremlin.shared_state.device_type_map[device_guid] = device_type
                                    index += 1

                        case DeviceType.ModeControl:
                            # =======================================================
                            # create mode control tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
                            guid = gremlin.shared_state.mode_tab_guid
                            device_guid = gremlin.util.normalize_guid(guid)
                            device = gremlin.joystick_handling.getDevice(device_guid)

                            widget = self.getRegisteredWidget(device_guid)
                            if not widget:
                                widget = gremlin.ui.mode_device.ModeDeviceTabWidget(profile=self.profile, mode=self.current_mode)
                                self.registerWidget(device_guid, widget)
                                self._mode_device_guid = device_guid

                                widget.data = (
                                    TabDeviceType.ModeControl,
                                    device_guid,
                                    index,
                                )
                            # add tab header for this device
                            if device not in tab_device_list:
                                self._add_tab(device.device_guid, TabDeviceType.ModeControl)
                                tab_device_list.append(device)
                                index += 1

                        case DeviceType.State:
                            # =======================================================
                            # create state tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)
                            guid = gremlin.shared_state.state_tab_guid
                            device_guid = gremlin.util.normalize_guid(guid)
                            device = gremlin.joystick_handling.getDevice(device_guid)
                            widget = self.getRegisteredWidget(device_guid)
                            if not widget:
                                widget = gremlin.ui.state_device.StateDeviceTabWidget(profile=self.profile, mode=self.current_mode)
                                self.registerWidget(device_guid, widget)
                                self._state_device_guid = device_guid

                                widget.data = (TabDeviceType.State, device_guid, index)
                            # add tab header for this device
                            if device not in tab_device_list:
                                self._add_tab(device.device_guid, TabDeviceType.State)
                                tab_device_list.append(device)
                                index += 1

                elif device in config_devices:
                    # =======================================================
                    # config devices
                    match device.device_type:
                        case DeviceType.Settings:
                            # =======================================================
                            # Add profile configuration tab (special device - must also be registered in gremlin.joystick_handling.RegisterSpecialDevice)

                            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.settings_tab_guid)
                            device = gremlin.joystick_handling.getDevice(device_guid)
                            widget = self.getRegisteredWidget(device_guid)
                            if not widget:
                                widget = gremlin.ui.profile_settings.ProfileSettingsWidget(self.profile.settings)
                                self.registerWidget(device_guid, widget)
                                # widget.changed.connect(self._handle_on_change)

                                self._settings_device_guid = device_guid

                                widget.data = (
                                    TabDeviceType.Settings,
                                    device_guid,
                                    index,
                                )
                            # add tab header for this device
                            if device not in tab_device_list:
                                self._add_tab(device_guid, TabDeviceType.Settings)
                                tab_device_list.append(device)
                                index += 1

                        case DeviceType.Plugins:
                            # =======================================================
                            # Add a plugin custom modules tab
                            device_guid = gremlin.util.normalize_guid(gremlin.shared_state.plugins_tab_guid)
                            device = gremlin.joystick_handling.getDevice(device_guid)
                            widget = self.getRegisteredWidget(device_guid)
                            if not widget:
                                widget = gremlin.ui.user_plugin_management.ModuleManagementController(self.profile)
                                self.mm = widget
                                widget = self.mm.view
                                self.registerWidget(device_guid, widget)

                                self._plugins_device_guid = device_guid

                                widget.data = (
                                    TabDeviceType.Plugins,
                                    device_guid,
                                    index,
                                )
                            # add tab header for this device
                            if device not in tab_device_list:
                                self._add_tab(device_guid, TabDeviceType.Plugins)
                                tab_device_list.append(device)
                                index += 1

            self._reindex_tabs()

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

            gremlin.shared_state.pop_redraw()

            try:
                gremlin.shared_state.pop_input_selection(reset=True)  # allow selections
                last_device_guid, last_input_type, last_input_id = config.get_last_input()

                device = gremlin.joystick_handling.getDevice(last_device_guid) if last_device_guid else None
                if not device:
                    # does not exist anymore
                    last_input_id = None
                    last_input_type = None
                    last_device_guid = self.ui.devices_tab_header_widget.tabData(0).device_guid  # pick first
                    device = gremlin.joystick_handling.getDevice(last_device_guid)
                    assert device is not None, "unable to derive device"

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

                if verbose:
                    syslog.info(f"CreateTabs: select tab index: [{index}]  device: [{device.name}]")
                index = self.getTabIndexForDevice(last_device_guid)

                if index is not None:
                    widget: BaseDeviceTabWidget = self.getRegisteredWidget(last_device_guid)
                    if not widget:
                        # device may not longer be visible, select the first tab
                        device_guid = self.ui.devices_tab_header_widget.tabData(0).device_guid  # pick first
                        index = self.getTabIndexForDevice(device_guid)
                        widget = self.getRegisteredWidget(device_guid)
                        last_device_guid = device_guid
                        # get the first input item
                        input_item = self.profile.first_input(device_guid)
                        if input_item:
                            last_input_id = input_item.input_id
                            last_input_type = input_item.input_type

                    assert widget is not None, "invalid widget"

                    widget.refresh()

                    # self.ui.devices.setCurrentIndex(index)
                    self._select_input(
                        last_device_guid,
                        last_input_type,
                        last_input_id,
                        force_switch=True,
                    )

                    if isinstance(widget, BaseDeviceTabWidget):
                        # ensure the input is visible
                        gremlin.util.singleShot(lambda: widget.ensureSelectedVisible())

            except Exception as err:
                syslog.error(f"CREATE DEVICE TABS (step 2): failed: {err}")
                tb_msg = traceback.format_exc()
                syslog.error(tb_msg)

            self.pop_highlighting()
            self._update_highlight_toolbar_enabled()
            gremlin.shared_state.pop_suspend_save_input()
            selected_device_guid = self.getActiveTabDeviceGuid()
            if verbose:
                syslog.info("Tab recreated:")
                for index in range(self.ui.devices_tab_header_widget.count()):
                    device_guid = self.ui.devices_tab_header_widget.tabData(index).device_guid
                    if device_guid:
                        device_name = self._get_device_name(device_guid)
                    else:
                        device_name = "(unknown)"

                    stub = "[SELECTED]" if device_guid == selected_device_guid else ""
                    syslog.info(f"\t[{index}] {self.ui.devices_tab_header_widget.tabText(index)} {device_name}  {device_guid} {stub}")

            # update tracking
            device_guid = self._tab_index_map.get(self.ui.devices_tab_header_widget.currentIndex())
            self.setCurrentTabTracking(device_guid)

            if verbose_detailed:
                syslog.info("CREATE TABS: complete")

            self.popLoading(selected_device_guid)

    def get_ordered_device_guid_list(self, filter_tab_type: TabDeviceType = TabDeviceType.NotSet) -> Iterator[dinput.GUID]:
        """returns the list of device guids as directinput GUIDs

        :param: filter_tab_type = the type of tab device to filter for
        :returns: list of DINPUT GUID

        """
        tab_map = self._get_tab_map()
        return [data.device_guid for data in tab_map.values if data.tab_type == filter_tab_type]

    def _find_tab_data(self, search_widget_type: TabDeviceType) -> Iterator[TabData]:
        """gets tab data based on widget type"""
        tab_map = self._get_tab_map()
        return [data for data in tab_map.values() if data.device_type == search_widget_type]

    def _find_joystick_tab_data(self) -> Iterator[TabData]:
        """gets the joystick tab data"""
        return self._find_tab_data(TabDeviceType.Joystick)

    def _find_tab_data_guid(self, search_guid) -> TabData:
        """gets tab data based on the device guid"""
        if not isinstance(search_guid, str):
            search_guid = gremlin.util.normalize_guid(search_guid)  # tab map stores the GUID as a string
        tab_map = self._get_tab_map()
        return next((data for data in tab_map.values() if data.device_guid == search_guid), None)

    def _get_tab_widget_guid(self, device_guid):
        """gets a tab by device guid"""
        return self.getRegisteredWidget(device_guid)

    def _get_tab_index(self, device_guid):
        """gets the tab index for the given GUID"""
        device_guid = gremlin.util.normalize_guid(device_guid)
        return self.getRegisteredWidgetIndex(device_guid)

    def _get_tab_widgets_by_type(self, tab_type: TabDeviceType):
        """gets widgets by the tab type"""
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
        """returns the tab objects"""
        widgets = [self.ui.device_page_widget.widget(index) for index in range(self.ui.device_page_widget.count())]
        return widgets
        # return self._widget_device_index_map.values()

    def _select_last_tab(self):
        """restore the last selected tab"""
        # print (f"select last tab: {self.config.last_tab_guid}")
        device_guid, input_type, input_id = self.config.get_last_input()
        el = gremlin.event_handler.EventListener()
        el.select_input.emit(device_guid, input_type, input_id, False, True, False, None)

    @QtCore.Slot()
    def _ui_ready(self):
        """UI loop is about to start"""

        # update the UI widgets that listen to inputs to disable the ones not visible
        device_guid, input_type, input_id = self.restore_input
        # syslog = logging.getLogger("system")
        verbose = self.config.verbose_mode_details

        if device_guid is None:
            # no default selected, pick the first tab
            device_guid = self.getFirstTabDeviceGuid()
            syslog.info("UI: no prior device selection found - selecting first device")
        if device_guid is not None:
            info = gremlin.joystick_handling.getDevice(device_guid)
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

    def _select_last_input(
        self,
        extra_data: dict = None,
    ):
        # if there is a last input - select that input as well
        device_guid, input_type, input_id = self.config.get_last_input()
        if input_type and input_id:
            eh = gremlin.event_handler.EventListener()
            eh.select_input.emit(device_guid, input_type, input_id, False, True, False, extra_data)

    def _get_last_input(self, device_guid: str) -> tuple:
        """Gets the last input selection for the given device

        If there was no prior selection, the first input for the device is returned.
        If there is no first input because it's empty, return None.

        :param: device_guid id of the device to get as a string
        :returns: (input_type, Input_id)

        """

        device_guid, input_type, input_id = gremlin.shared_state.current_profile.getLastInput(device_guid)

        # _, input_type, input_id = gremlin.config.Configuration().get_last_input(device_guid)
        if not input_type:
            # pick the first input for that tab
            _widget = self._get_tab_widget_guid(device_guid)
            input_item: InputItem = self._get_input_item(device_guid, 0)
            if input_item:
                return (input_item.input_type, input_item.input_id)
        return (input_type, input_id)

    def _get_input_item(self, device_guid: str | dinput.GUID, index: int) -> InputItem:
        """get the input item at the specified index in the device - index is 0 based"""
        assert index >= 0, f"invalid index {index}"
        widget: BaseDeviceTabWidget = self._get_tab_widget_guid(device_guid)
        if widget is None or not hasattr(widget, "inputItemListModel") or not widget.isLoaded():
            return None

        row_count = widget.inputItemListModel.rows()
        if row_count == 0 or index > row_count:
            return None
        return widget.inputItemListModel.data(index)

    def _get_input_items(self, device_guid: str | dinput.GUID) -> list[InputItem]:
        """gets the list of all input items for a given device"""
        widget = self._get_tab_widget_guid(device_guid)
        if widget is None or not hasattr(widget, "inputItemListModel") or not widget.isLoaded():
            return None

        row_count = widget.inputItemListModel.rows()
        return [widget.inputItemListModel.data(index) for index in range(row_count)]

    def _find_input_item(self, device_guid: str | dinput.GUID, input_type, input_id) -> InputItem:
        """find the input item matching the input id for a given device"""
        if not device_guid or input_id is None or input_type is None:
            # nothing to match
            return None

        widget = self._get_tab_widget_guid(device_guid)
        if widget is not None and hasattr(widget, "find_input"):
            return widget.find_input(device_guid, input_type, input_id)

        items = self._get_input_items(device_guid)
        if items:
            return next(
                (item for item in items if item and item.input_id and item.input_id == input_id and item.input_type == input_type),
                None,
            )
        return None

    def _select_input(
        self,
        device_guid,
        input_type: InputType = None,
        input_id=None,
        mode=None,
        force_update=False,
        force_switch=False,
        tab_changed=False,
        extra_data: dict = None,
    ):
        if gremlin.shared_state.is_input_selection_suspended:
            return  # skip if disabled

        args = (
            device_guid,
            input_type,
            input_id,
            force_update,
            force_switch,
            tab_changed,
            extra_data,
        )

        if gremlin.util.is_ui_thread():
            self._select_input_handler_ui(args)
        else:
            gremlin.util.InvokeUiMethod(self._select_input_handler_ui, args)

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

    def _select_input_handler(
        self,
        device_guid: dinput.GUID,
        restore_input_type: gremlin.input_types.InputType = None,
        restore_input_id=None,
        force_update: bool = False,
        force_switch=False,
        tab_changed=False,
        extra_data: dict = None,
    ):
        args = (
            device_guid,
            restore_input_type,
            restore_input_id,
            force_update,
            force_switch,
            tab_changed,
            extra_data,
        )
        gremlin.util.InvokeUiMethod(self._select_input_handler_ui, args)

    def _select_input_handler_ui(self, args):
        """Selects a specific input on the given tab.
        The tab is changed if different from the current tab.
        selection_change handler
        """

        restore_device_guid: dinput.GUID
        restore_input_type: gremlin.input_types.InputType = None
        restore_input_id = None
        force_update: bool = False
        force_switch = False
        tab_changed = False
        extra_data: dict = None

        (
            restore_device_guid,
            restore_input_type,
            restore_input_id,
            force_update,
            force_switch,
            tab_changed,
            extra_data,
        ) = args

        import gremlin.config
        import gremlin.event_handler

        import gremlin.util
        import gremlin.shared_state
        import gremlin.joystick_handling

        completion_callback = None
        if extra_data:
            if "completion_callback" in extra_data:
                completion_callback = extra_data["completion_callback"]
                assert isinstance(completion_callback, Callable), "invalid completion callback"
            pass

        try:
            device_guid = None
            input_type = None
            input_id = None
            if self._change_input_lock.locked():
                return

            verbose = self.config.verbose_mode_select
            # verbose = True

            widget = None
            _push_cursor = False

            with self._change_input_lock:
                try:
                    if gremlin.shared_state.is_input_selection_suspended:
                        return  # skip if disabled

                    if not restore_device_guid:
                        # no device selected - ignore
                        return

                    if not force_update and not force_switch:
                        if not gremlin.util.compare_guid(restore_device_guid, gremlin.shared_state.active_device_guid):
                            # looking to select an input that isn't visible
                            return

                    device_guid = gremlin.util.normalize_guid(restore_device_guid)

                    # avoid spamming
                    if not force_update and self._last_input_change_timestamp + self._input_delay > time.time():
                        # delay not occured yet
                        return

                    self._last_input_change_timestamp = time.time()

                    # syslog = logging.getLogger("system")
                    input_id = restore_input_id
                    input_type = restore_input_type

                    switch_input = force_switch  # true if inputs are switched or forcing refresh

                    switch_enabled = self.is_highligthing_enabled
                    if not force_switch and gremlin.shared_state.current_tab_device_guid != device_guid and not switch_enabled:
                        if verbose:
                            syslog.info(f"SELECT INPUT: event: {device_guid} {self._get_device_name(device_guid)} disabled: highlight switch is disabled)")
                        return

                    # index of current device tab
                    index = self.ui.devices_tab_header_widget.currentIndex()
                    if index == -1:
                        # no current index
                        return

                    tabdata = self.ui.devices_tab_header_widget.tabData(index)
                    assert tabdata is not None, "invalid tab data"

                    current_device_guid = tabdata.device_guid
                    current_input_type, current_input_id = self._get_last_input(current_device_guid)

                    # refresh the input list view for that tab if needed

                    # guid of current device tab
                    switch_tabs = False
                    index = self._find_tab_index(device_guid)
                    if current_device_guid != device_guid or index == -1:  # device changed or not found
                        # change tab if not on the correct device tab
                        if verbose:
                            syslog.info("Tab change requested")
                        # validate the requested device exists (this could be because the device is disconnected for example)

                        if index == -1:
                            # not found
                            device = gremlin.joystick_handling.getDevice(device_guid)
                            if device:
                                if device.is_virtual:
                                    # use the current tab if the VJOY device is not visible
                                    last_device_guid, last_input_type, input_id = self.config.get_last_input(device_guid)
                                    index = self._find_tab_index(device_guid)

                                else:
                                    # not virtual
                                    syslog.warning(
                                        f"SELECT INPUT: tab not found for device {gremlin.util.normalize_guid(device_guid)} - device does not exist - selecting default"
                                    )
                                    # change to the first
                                    device: DeviceSummary = gremlin.joystick_handling.default_device()
                                    if not device:
                                        syslog.warning("SELECT INPUT: no default device to select found - aborting selection")
                                        return
                                    device_guid = device.device_guid
                                    # get a default input for that device (first axis or first button)
                                    if device.axis_count:
                                        input_id = device.getAxisInputId(1)
                                    elif device.button_count:
                                        input_item = self._get_input_item(device_guid, 0)
                                    else:
                                        syslog.warning("SELECT INPUT: default device has no default input - aborting selection")
                                        return

                                    switch_input = True

                                    index = self._find_tab_index(device_guid)

                        if index is None:
                            syslog.warning(f"SELECT INPUT: default device not found in device tabs: {str(device)} - aborting selection")
                            return

                        with QtCore.QSignalBlocker(self.ui.devices_tab_header_widget):
                            self.ui.devices_tab_header_widget.setCurrentIndex(index)

                        if verbose:
                            syslog.info(f"Tab change complete: device {gremlin.util.normalize_guid(device_guid)}")
                        switch_tabs = True  # we are switching tabs
                        switch_input = True  # we are switching inputs

                    if switch_tabs and not force_switch and not config.highlight_autoswitch:
                        if verbose:
                            syslog.info("SELECT INPUT: Tab change ignored: auto tab switching is disabled")
                        return

                    # validate the current device widget first
                    widget: BaseDeviceTabWidget = self.getRegisteredWidget(device_guid)
                    assert widget is not None, f"error retrieving widget for device [{device.name}] id:[{device.device_id}]"
                    if Shiboken.isValid(widget):
                        widget.ensureLoaded()

                        if not widget.isLoaded():
                            return
                    else:
                        return

                    input_count = widget.inputCount
                    input_widget_count = widget.inputWidgetCount
                    if verbose:
                        syslog.info(f"Device widget: input count: {input_count:,}  widget count: {input_widget_count}")

                    if input_count and input_widget_count == 0:
                        # widget not loaded, load it
                        widget.refresh(emit=False)
                        input_widget_count = widget.inputWidgetCount
                        if verbose:
                            syslog.info(f"Post refresh: Device widget: input count: {input_count:,}  widget count: {input_widget_count}")

                    has_inputs = gremlin.util.compare_guid(
                        device_guid,
                        (
                            gremlin.shared_state.settings_tab_guid,
                            gremlin.shared_state.plugins_tab_guid,
                        ),
                    )  # settings and plugins tabs don't have inputs

                    if verbose:
                        syslog.info(
                            f"SELECT INPUT: current input: {current_device_guid} {self._get_device_name(device_guid)} input: {InputType.to_display_name(current_input_type)} input ID: {current_input_id} current mode: {gremlin.shared_state.current_mode}"
                        )

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
                        switch_input = not input_item.selected or not has_containers  # switch inputs if the input is not currently selected

                    if verbose:
                        syslog.info(
                            f"SELECT INPUT: new input: {device_guid} {self._get_device_name(device_guid)} input: {InputType.to_display_name(input_type)} input ID: {input_id}  current mode: {gremlin.shared_state.current_mode}"
                        )

                    if input_id is None and has_inputs:
                        # get the default item to select

                        if verbose:
                            syslog.info(f"SELECT INPUT: last input ID {input_id} not found - selecting default input ID")
                        last_device_guid, last_input_type, input_id = self.config.get_last_input(device_guid)
                        if verbose:
                            syslog.info(f"SELECT INPUT: found {last_device_guid} {last_input_type} {input_id} ")
                        if input_id is None:
                            input_item = self._get_input_item(device_guid, 0)
                            if input_item and self._last_input_item != input_item:
                                input_id = input_item.input_id
                                input_type = input_item.input_type
                                last_device_guid = device_guid
                                last_input_type = input_type
                                has_containers = len(input_item.containers) > 0
                                if verbose:
                                    syslog.info(f"SELECT INPUT: defaulting to first item on list {last_device_guid} {last_input_type} {input_id} ")

                                self._last_input_item = input_item
                        switch_input = True  # we are switching inputs

                    self._update_highlight_toolbar_enabled()

                    if not switch_input:
                        if widget and isinstance(widget, BaseDeviceTabWidget):
                            current_input_id = widget.getContentInputId()
                            if current_input_id:
                                switch_input = current_input_id != input_id

                    if input_id is not None and switch_input:
                        # select a particular input within a tab

                        if widget:
                            if isinstance(widget, BaseDeviceTabWidget):  # some tabs are not the standard widget - ignore those as they have no inputs
                                self.selectRegisteredWidget(device_guid)
                                if verbose:
                                    syslog.info(f"SELECT INPUT: select widget {input_type} {input_id}")
                                if tab_changed or not hasattr(widget, "inputItemListView"):
                                    widget.refresh(emit=False)
                                if not force_update:
                                    force_update = (
                                        current_input_id != input_id
                                        or current_input_type != current_input_id
                                        or gremlin.util.compare_guid(current_device_guid, device_guid)
                                    )

                                index = widget.indexOf(input_item)
                                if index == -1:
                                    device = gremlin.joystick_handling.getDevice(device_guid)
                                    if device.device_type == DeviceType.Joystick and self.is_highligthing_enabled and self.config.filter_auto_unhide:
                                        # auto unhide the input and select it
                                        widget.setInputVisible(input_item, True, emit=True)
                                        index = widget.indexOf(input_item)
                                        if verbose:
                                            syslog.info(f"SELECT INPUT: input {input_item.display_name} made visible at index {index}")

                                # widget.input_item_list_view.redraw_index(index)
                                widget.selectInputItemIndex(index)

                                # widget.refresh(False)

                                # widget.select_item(index)
                                widget.setContentWidget(input_type, input_id)

                                input_item_widget = widget.inputItemListView.widget(index)
                                if input_item_widget:
                                    if not input_item_widget.selected:
                                        input_item_widget.setSelected(True, emit=False)

                                    # input_widget.ensureStyle()

                                if verbose:
                                    syslog.info(f"SELECT INPUT: selected widget {input_type.name} {input_id}")

                                # ensure the input is highlighted

                        # remember the last input id
                        self._current_tab_input_id = input_id

                    elif not has_inputs:
                        # special tabs
                        widget = self.getRegisteredWidget(device_guid)
                        if widget:
                            self.selectRegisteredWidget(device_guid)
                            widget.refresh(emit=False)

                    # save settings as the last input
                    el = gremlin.event_handler.EventListener()
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
                    gremlin.shared_state.setActiveDeviceGuid(device_guid)
                    # allow UI to refresh / update
                    self.ensureTabLoaded()

                    # ensure content is visible
                    self.selectTabWidget(device_guid)
        finally:
            # update tracking
            self.setCurrentTabTracking(device_guid)

            self._last_selected_device_guid = device_guid
            self._last_selected_input_type = input_type
            self._last_selected_input_id = input_id
            config.set_last_input(device_guid, input_type, input_id)

            if completion_callback:
                # fire the callback on completion
                completion_callback(device_guid, input_type, input_id)

    def _handle_item_selected(self, device_guid, input_type, input_id):
        """Handles item selection events from the list view"""
        self.saveInputSelection(device_guid, input_type, input_id)

    def saveInputSelection(self, device_guid, input_type, input_id):
        """Saves the current input selection to the configuration"""
        config = gremlin.config.Configuration()
        config.set_last_input(device_guid, input_type, input_id)
        self._last_selected_device_guid = device_guid
        self._last_selected_input_type = input_type
        self._last_selected_input_id = input_id
        verbose = config.verbose_mode_select
        if verbose:
            device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
            syslog.info(f"SELECT INPUT: save selection device_name={device_name}, device_guid={device_guid}, input_type={input_type}, input_id={input_id}")

    def setCurrentTabTracking(self, device_guid: str):
        """sets the tracking tab to the given device guid"""
        gremlin.shared_state.current_tab_device_guid = gremlin.util.to_guid(device_guid)
        gremlin.shared_state.current_tab_device_id = gremlin.util.normalize_guid(device_guid)

    def ensureTabLoaded(self):
        """ensures a tab device UI is loaded/refreshed"""

        position = self.ui.devices_tab_header_widget.currentIndex()
        if position == -1:
            # no tab selected yet
            return
        tabdata = self.ui.devices_tab_header_widget.tabData(position)
        if tabdata:
            current_tab_device_guid = tabdata.device_guid
            widget: gremlin.ui.ui_common.QSplitTabWidget = self.getRegisteredWidget(current_tab_device_guid)
            assert widget is not None, f"SELECT: sync issue: no widget found for the given device: {current_tab_device_guid}"
            widget.ensureLoaded()
        else:
            syslog.warning(f"Tab: ensureTabLoaded(): [{position}] not found")

    @QtCore.Slot(object, object, object)
    def _input_changed_handler(self, device_guid, input_type, input_id):
        """called when an input changes"""
        current_device_guid, current_input_type, current_input_id = gremlin.shared_state.get_last_input_id()
        if current_device_guid != device_guid or current_input_type != input_type or current_input_id != input_id:
            # syslog = logging.getLogger("system")
            verbose = self.config.verbose_mode_device
            if verbose:
                device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
                syslog.info(f"INPUT CHANGE: selected {device_name} {device_guid} {InputType.to_display_name(input_type)} input: {input_id}")
            gremlin.shared_state.set_last_input_id(device_guid, input_type, input_id)

    def _find_tab_index(self, search_guid: str):
        ts = gremlin.tabstate.TabState()
        index = ts.getTabIndex(search_guid)
        return index

        # search_guid = gremlin.util.to_guid(search_guid)
        # tab_map = self._get_tab_map()
        # if search_guid in tab_map:
        #     return tab_map[search_guid].position

        # # for device_guid, _, _, tab_index in tab_map.values():
        # #     if device_guid == search_guid:
        # #         return tab_index

        # for id in tab_map:
        #     if gremlin.util.compare_guid(search_guid, id):
        #         return tab_map[id].position
        # return None

    def _active_tab_guid(self):
        """gets the GUID of the device for the active tab"""
        return self._get_tab_guid(self.ui.devices_tab_header_widget.currentIndex())

    def _active_tab_index(self):
        """gets the index of the current tab"""
        return self.ui.devices_tab_header_widget.currentIndex()

    def _active_input_item(self) -> InputItem:
        """gets the current selected input item"""
        widget = self.getActiveTabWidget()
        if widget and hasattr(widget, "inputItemListView"):
            return widget.inputItemListView.currentItem()
        return None

    def _get_tab_guid(self, index: int) -> str:
        """gets the tab GUID from its index"""
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "data"):
            return widget.data[1]  # id is index 1
        return None

    def _get_tab_input_type(self, index: int):
        """gets the input type of the tab"""
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "inputItemListView"):
            item_index = widget.inputItemListView.currentIndex()
            data = widget.inputItemListView.model.data(item_index)
            return data.device_type
        return None

    def _get_tab_input_id(self, index: int):
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "inputItemListView"):
            item_index = widget.inputItemListView.currentIndex()
            data = widget.inputItemListView.model.data(item_index)
            return data.input_id
        return None

    def _get_tab_input_data(self, index: int):
        """returns (input_type, input_id) for a given tab index"""
        widget = self.getWidgetByTabIndex(index)
        if hasattr(widget, "inputItemListView"):
            item_index = widget.inputItemListView.currentIndex()
            data = widget.inputItemListView.model.data(item_index)
            if data is not None:
                return (data.device_type, data.input_id)
        return (None, None)

    def _dump_tab_map(self, tab_map):
        log = syslog
        for index, (
            device_guid,
            device_name,
            device_class,
            tab_index,
        ) in tab_map.items():
            log.info(f"[{index}] Tab index: [{tab_index}] {device_name} {device_class} {device_guid}")

    def _refresh_tab(self):
        """refreshes the current device tab"""
        widget = self.getActiveTabWidget()
        if widget and hasattr(widget, "refresh"):
            widget.refresh()

    def _sort_tabs(self):
        """sorts device tabs"""
        wm = WorkManager()
        wm.submit(self._sort_tabs_worker)

    def _sort_tabs_worker(self, args):
        """sorts device tabs by default order name"""

        self._tab_sorted_flag = False

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

        # add the settings tab
        guid_list.append(self._find_tab_data_guid(gremlin.shared_state.settings_tab_guid))

        # add the user plugin tab
        guid_list.append(self._find_tab_data_guid(gremlin.shared_state.plugins_tab_guid))

        # move the tabs to the correct location
        tab_data = [self.ui.devices_tab_header_widget.tabData(index) for index in range(self.ui.devices_tab_header_widget.count())]
        self._reset_tab_data()
        while self.getTabCount():
            # wait for the tabs to go poof
            QThread.sleep(0)
        for index, (device_guid, device_name, device_type, tab_index) in enumerate(guid_list):
            data = tab_data[index]
            self._add_tab(device_guid, data.tab_type, index)

        tab_map = self._get_tab_map()
        if self.config.verbose:
            syslog.info("SORT: post result:")
            self._dump_tab_map(tab_map)

        self._select_last_tab()
        self._select_last_input(extra_data={"completion_callback": self._handle_tabs_sorted_completed})

        while not self._tab_sorted_flag:
            QThread.sleep(0)

    def _handle_tabs_sorted_completed(self, *args):
        self._tab_sorted_flag = True

    def _setup_icons(self):
        """Sets the icons of all QAction items."""
        # Menu actions
        from pathlib import Path

        folder = gremlin.shared_state.root_path
        gfx_folder = os.path.join(folder, "icons")
        if not os.path.isdir(gfx_folder):
            # look for parent
            parent = Path(folder).parent
            gfx_folder = os.path.join(parent, "icons")
            if not os.path.isdir(gfx_folder):
                raise gremlin.error.GremlinError(f"Unable to find icons: {folder}")

        normal_color = gremlin.ui.ui_common.Color.normalColor()
        active_color = gremlin.ui.ui_common.Color.activeColor()
        is_dark = gremlin.shared_state.is_dark_theme

        profile_icon = "dark_profile_open.svg" if is_dark else "profile_open.svg"

        icon = load_icon(profile_icon)
        # icon = self.load_icon("profile_open.svg"))
        self.ui.actionLoadProfile.setIcon(icon)

        prefix = "dark_" if is_dark else ""

        profile_new_icon = f"{prefix}profile_new.svg"

        icon = load_icon(profile_new_icon)
        self.ui.actionNewProfile.setIcon(icon)

        profile_save_icon = f"{prefix}profile_save.svg"
        icon = load_icon(profile_save_icon)
        self.ui.actionSaveProfile.setIcon(icon)

        profile_save_as_icon = f"{prefix}profile_save_as.svg"
        icon = load_icon(profile_save_as_icon)
        self.ui.actionSaveProfileAs.setIcon(icon)

        device_information_icon = f"{prefix}device_information.svg"
        icon = load_icon(device_information_icon)
        self.ui.actionDeviceInformation.setIcon(icon)

        manage_module_icon = f"{prefix}manage_modules.svg"
        icon = load_icon(manage_module_icon)
        self.ui.actionManageCustomModules.setIcon(icon)

        manage_modes_icon = f"{prefix}manage_modes.svg"
        icon = load_icon(manage_modes_icon)
        self.ui.actionManageModes.setIcon(icon)

        input_repeater_icon = f"{prefix}input_repeater.svg"
        icon = load_icon(input_repeater_icon)
        self.ui.actionInputRepeater.setIcon(icon)

        # input_viewer_icon = load_icon("ei.adjust-alt")
        # icon = load_icon(input_viewer_icon)
        # self.ui.actionInputViewer.setIcon(icon)

        icon = load_icon(f"{prefix}logview.png")
        self.ui.actionLogDisplay.setIcon(icon)
        self.ui.actionLogEdit.setIcon(icon)

        options_icon = f"{prefix}options.svg"
        icon = load_icon(options_icon)
        self.ui.actionOptions.setIcon(icon)

        # about_icon = f"{prefix}about.svg"
        # icon = load_icon(about_icon)
        # self.ui.actionAbout.setIcon(icon)

        # input actions

        input_icon = load_icon("ei.adjust-alt", qta_color=normal_color)
        input_on_icon = load_icon("ei.adjust-alt", qta_color=active_color)
        pixmap_off = input_icon.pixmap(24, 24)
        pixmap_on = input_on_icon.pixmap(24, 24)
        viewer_icon = QtGui.QIcon()
        viewer_icon.addPixmap(pixmap_off, QtGui.QIcon.Normal)
        viewer_icon.addPixmap(pixmap_on, QtGui.QIcon.Active, QtGui.QIcon.On)
        self.ui.actionInputViewer.setCheckable(True)
        self.ui.actionInputViewer.setIcon(viewer_icon)

        # Toolbar actions

        activate_icon = load_icon("fa5s.gamepad", qta_color=normal_color)
        activate_on_icon = load_icon("fa5s.gamepad", qta_color=active_color)
        pixmap_off = activate_icon.pixmap(24, 24)
        pixmap_on = activate_on_icon.pixmap(24, 24)
        activate_icon = QtGui.QIcon()
        activate_icon.addPixmap(pixmap_off, QtGui.QIcon.Normal)
        activate_icon.addPixmap(pixmap_on, QtGui.QIcon.Active, QtGui.QIcon.On)

        # self.ui.actionActivate.setCheckable(True)
        self.ui.actionActivate.setIcon(activate_icon)

        remote_icon = load_icon("mdi.remote", qta_color=normal_color)
        remote_on_icon = load_icon("mdi.remote", qta_color=active_color)
        pixmap_off = remote_icon.pixmap(24, 24)
        pixmap_on = remote_on_icon.pixmap(24, 24)

        remote_activate_icon = QtGui.QIcon()
        remote_activate_icon.addPixmap(pixmap_off, QtGui.QIcon.Normal)
        remote_activate_icon.addPixmap(pixmap_on, QtGui.QIcon.Active, QtGui.QIcon.On)

        # self.ui.actionToggleRemotecontrol.setCheckable(True)
        self.ui.actionToggleRemoteControl.setIcon(remote_activate_icon)

        self.ui.actionOpen.setIcon(load_icon(profile_icon))

        self.ui.actionSave.setIcon(load_icon("fa5s.save", qta_color=normal_color))

    # +---------------------------------------------------------------
    # | Signal handlers
    # +---------------------------------------------------------------

    def _handle_devices_changed(self):
        gremlin.util.InvokeUiMethod(self._device_change_ui)  # ensure the update is on the UI thread

    def _device_change_ui(self):
        """Handles addition and removal of joystick devices."""

        if not gremlin.joystick_handling.joystick_initialized():
            # not initialized yet
            return

        # record the device change
        self._device_change_queue += 1
        # print (f"device change detected {self._device_change_queue}")

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
                        syslog.info("Device change begin")

                    # list which device is different
                    old_devices = [(device.device_guid, device.name) for device in self._active_devices]
                    detected_devices = gremlin.joystick_handling.joystick_devices()
                    new_devices = [(device.device_guid, device.name) for device in detected_devices]
                    added_devices = [item for item in new_devices if item not in old_devices]
                    removed_devices = [item for item in old_devices if item not in new_devices]
                    if verbose:
                        if added_devices:
                            syslog.info("\tDevice added detected:")
                            for device_guid, device_name in added_devices:
                                syslog.info(f"\t\t{device_name} {device_guid}")
                        if removed_devices:
                            syslog.info("\tDevice removed detected:")
                            for device_guid, device_name in removed_devices:
                                syslog.info(f"\t\t{device_name} {device_guid}")
                                assert isinstance(device_guid, dinput.GUID), "invalid device guid format"
                                if gremlin.shared_state.current_tab_device_guid == device_guid:
                                    # select a different tab
                                    self.unregisterWidget(device_guid)
                                    gremlin.shared_state.current_tab_device_guid = None
                                    gremlin.shared_state.current_tab_device_id = None
                                    # self._current_tab_widget = None

                    # recreate the tabs
                    self.setTabsDirty()

                    # Stop Gremlin execution

                    self.ui.actionActivate.setChecked(False)
                    restart = self.runner.is_running()
                    if restart:
                        syslog.info("Profile restart due to device change")

                    el = gremlin.event_handler.EventListener()
                    el.request_activate.emit(restart)

                finally:
                    if verbose_detailed:
                        syslog.info("Device change end")
                    self.device_change_locked = False

                    self._create_tabs()

                # mark items processed
                self._device_change_queue = 0

    @QtCore.Slot()
    def _device_input_changed_cb(self, device_guid, input_type, input_id):
        """called when device input changed"""
        el = gremlin.event_handler.EventListener()
        el.input_selection_changed.emit(device_guid, input_type, input_id)

    def _tab_moved_cb(self, tab_from, tab_to):
        """occurs when a tab is moved"""
        # persist tab order
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info(f"UI: tab move detected {tab_from} {tab_to}")
        wm = WorkManager()
        wm.submit(self._tab_move_worker)

    def _tab_move_worker(self, args):
        """worker thread to process tab move"""

        syslog.info("tab move start")
        # rebuild the tab order
        self._reindex_tabs()
        # update new order
        tab_map = self._get_tab_map()
        save_map = {}
        for index, tab_data in tab_map.items():
            device_id = tab_data.device_id
            save_map[index] = (device_id, True)
        self.config.tab_list = save_map

        index = self.ui.devices_tab_header_widget.currentIndex()
        device_guid = self.ui.devices_tab_header_widget.tabData(index).device_guid
        _, restore_input_type, restore_input_id = self.config.get_last_input(device_guid)
        syslog.info("tab move selecting")
        self._tab_move_completed_flag = False
        self._select_input(
            device_guid=device_guid,
            input_type=restore_input_type,
            input_id=restore_input_id,
            force_update=True,
            force_switch=True,
            extra_data={
                "completion_callback": self._handle_tab_move_completed,
                "source": "tab_move",
            },
        )

        syslog.info("tab move waiting for selection complete")
        while not self._tab_move_completed_flag:
            QThread.sleep(0)

        syslog.info("tab move finished")

    def _handle_tab_move_completed(self, *args):
        syslog.info("tab move completed event")
        self._tab_move_completed_flag = True

    def _edit_mode_selector_changed(self, new_mode):
        """Updates the current mode to the provided one.

        :param new_mode the name of the new current mode
        """

        # refresh the modes
        eh = gremlin.event_handler.EventHandler()
        eh.change_mode(new_mode, force_update=True)

    def _get_process_mode(self, process_path):
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_process
        if process_path in self._process_runtime_map:
            mode = self._process_runtime_map[process_path]
            if verbose:
                syslog.info(f"PROC MODE: using last mode [{mode}] for process {process_path}")
        else:
            mode = self.profile.get_last_runtime_mode()
            if verbose:
                syslog.info(f"PROC MODE: using last saved profile mode mode [{mode}]")
        return mode

    def _process_changed_cb(self, new_process_path: str):
        gremlin.util.InvokeUiMethod(self._process_changed_cb_ui, new_process_path)  # ensure on UI thread

    def _process_changed_cb_ui(self, new_process_path: str):
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
        profile = gremlin.shared_state.current_profile

        verbose = config.verbose_mode_process
        # syslog = logging.getLogger("system")

        if not self.current_process_path:
            self.current_process_path = new_process_path

        #  get auto load options
        option_auto_load = (
            config.autoload_profiles
        )  # if true, change the profile if a process is mapped to one, do not activate unless gremlin was already activated
        option_auto_load_on_focus = config.activate_on_process_focus  # if true, also activate the mapped profile if not activated
        process_base = os.path.basename(new_process_path)

        option_keep_focus = config.keep_profile_active_on_focus_loss  # if true, do not deactivate the profile on gremlinEx focus loss
        option_reset_mode_on_process_activate = config.reset_mode_on_process_activate  # if true, reset the profile to the default start mode on process focus
        option_restore_mode = (
            config.restore_profile_mode_on_start
        )  # if true, restore last used profile mode on process focus (overrides the reset to default mode)

        el = gremlin.event_handler.EventListener()

        if verbose:
            syslog.info("=" * 50)
            syslog.info(f"PROC: Process change detected: new process: >>>>>> [{process_base}] <<<<<<<")
            syslog.info(f"\t autoload: [{option_auto_load}]")
            syslog.info(f"\t autoload on focus: [{option_auto_load}]")
            syslog.info(f"\t keep focus: [{option_keep_focus}]")
            syslog.info(f"\t reset to default mode on process activate: [{option_reset_mode_on_process_activate}]")
            syslog.info(f"\t restore mode on profile start: [{option_restore_mode}]")

        try:
            if not option_auto_load or not option_auto_load_on_focus:
                # skip if we are not auto starting or auto loading profiles
                if verbose:
                    syslog.info(f"PROC: Process change detected [{process_base}]: ignoring because auto-load options are disabled")
                return

            current_profile_path = profile.profile_file if profile else None

            # is_running = (
            #     gremlin.shared_state.is_running
            # )  # true if gremlin is running at process change
            # if is_running:
            #     current_profile_save_mode = gremlin.shared_state.current_mode
            # else:
            #     current_profile_save_mode = None

            # see if we have a mapping entry for this executable
            profile_item = self._profile_map.get_map(new_process_path)
            # start_mode = None
            # if profile_item:
            #     start_mode = profile_item.default_mode

            new_profile_path = profile_item.profile if profile_item else None

            if not current_profile_path or not os.path.isfile(current_profile_path):
                syslog.info("PROC: no current profile found - auto process start is unable to function")
                # gremlin.ui.ui_common.MessageBox(prompt = f"Current profile  [{current_profile_path}] is not saved or the XML could not be found.  Process auto-start disabled.")
                return

            current_profile_base = os.path.basename(current_profile_path)

            if not new_profile_path:
                # no profile was found for the new process that received focus
                if not option_keep_focus:
                    # keep focus is off so we disable the profile
                    if verbose:
                        syslog.info(f"PROC: process change: unmapped process [{process_base}] - keep focus is disabled - deactivate profile")
                    el.request_activate.emit(False)
                    self.ui.actionActivate.setChecked(False)  # this turns "on" the run icon
                    # done
                    return
                if verbose:
                    syslog.info(f"PROC: process change: unmapped process [{process_base}] - ignoring process change")
                return

            if not os.path.isfile(new_profile_path):
                syslog.error(f"PROC: process [{new_process_path}] profile file [{new_profile_path}] not found - ignoring process change")
                # gremlin.ui.ui_common.MessageBox(prompt = f"New profile [{new_profile_path}] profile XML could not be found.  Process auto-start disabled.")
                return

            new_profile_base = os.path.basename(new_profile_path)

            if verbose:
                syslog.info(
                    f"PROC: found profile map [{new_profile_base}] for process {process_base} - current profile: [{current_profile_base}]  runtime mode: [{gremlin.shared_state.runtime_mode}]"
                )

            # profile entry found - see if we need to change profiles
            if not current_profile_path or not os.path.isfile(current_profile_path):
                syslog.error(
                    "PROC: Profile does not exist or is not saved.  Ignoring process activation as this feature requires the current profile to be saved."
                )
                return

            # restore_mode = None  # derived profile mode to change to
            # mode_changed = False  # true if a mode change occured

            if not compare_path(current_profile_path, new_profile_path):
                # current profile and new profile are different - swap to the new profile

                # deactivate any current profile if active
                if verbose:
                    current_base_name = os.path.basename(current_profile_path)
                    syslog.info(
                        f"PROC: process change: deactivate current profile: [{current_base_name}] - saving last used mode: [{gremlin.shared_state.runtime_mode}]"
                    )

                el.request_activate.emit(False)  # load new profile

        finally:
            if verbose:
                if gremlin.shared_state.current_profile.profile_file:
                    base_profile = os.path.basename(gremlin.shared_state.current_profile.profile_file)
                else:
                    base_profile = "Not Saved"
                syslog.info(
                    f"PROC: END Process change detected: process: >>>>>> [{process_base}] <<<<<<<  final profile: [{base_profile}] mode: [{gremlin.shared_state.current_mode}]"
                )

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
        self._update_status_bar(gremlin.remote.remote_control.to_state_event())

    def _remote_control_changed(self, enabled: bool):
        gremlin.util.InvokeUiMethod(self._remote_control_changed_ui, enabled)

    def _remote_control_changed_ui(self, enabled: bool):
        """called when remote control state changes"""
        with QtCore.QSignalBlocker(self.ui.actionToggleRemoteControl):
            self.ui.actionToggleRemoteControl.setChecked(enabled)

    def _update_status_bar(self, event=None):
        # updates the status bar
        gremlin.util.InvokeUiMethod(self._update_status_bar_ui, event)

    def _update_status_bar_ui(self, event=None):
        """Updates the status bar with the current state of the system.

        :param is_active True if the system is active, False otherwise
        """
        Color = gremlin.ui.ui_common.Color
        try:
            if self._is_active:
                text_active = f'<font color="{Color.activeColor()}">Active</font>'
            else:
                text_active = f'<font color="{Color.inactiveColor()}">Paused</font>'

            if gremlin.shared_state.is_running:
                text_running = f"Running and {text_active}"
            else:
                text_running = "Not Running"

            # remote control status
            if not event:
                event = gremlin.remote.remote_control.to_state_event()

            server_state = gremlin.remote.remote_control.serverEnabled
            client_state = gremlin.remote.remote_control.clientEnabled
            remote_state = gremlin.remote.remote_control.is_remote
            self.status_bar_client_widget.setState(client_state)
            self.status_bar_client_widget.setToolTip(
                "Client enabled - this client can receive remote control commands."
                if client_state
                else "Client disabled.  This client cannot receive remote control commands."
            )
            self.status_bar_server_widget.setState(server_state)
            self.status_bar_server_widget.setToolTip(
                "Broadcast enabled.  This client can send remote control commands to other clients."
                if server_state
                else "Broadcast disabled.  This client cannot send remote control commands to other clients."
            )
            self.status_bar_remote_widget.setState(remote_state)
            self.status_bar_remote_widget.setToolTip(f"Profile remote mode is currently {'active.' if remote_state else 'inactive.'}")

            # if event.is_local:
            #     local_msg = f"<font color=\"{Color.activeColor()}\">Active</font>"
            # else:
            #     local_msg = f"<font color=\"{Color.inactiveColor()}\">Disabled</font>"
            # if event.is_remote:
            #     remote_msg = f"<font color=\"{Color.activeColor()}\">Active</font>"
            # else:
            #     remote_msg = f"<font color=\"{Color.inactiveColor()}\">Disabled</font>"
            # self.status_bar_is_active_widget.setText(f"<b>Status:</b> {text_running} <b>Local Control</b> {local_msg} <b>Broadcast:</b> {remote_msg}")

            self.status_bar_is_active_widget.setText(f"<b>Status:</b> {text_running}")
            self._update_mode_status_bar_ui()

        except Exception as err:
            log_sys_error(f"Unable to update status bar event: {event}")
            syslog.error(f"{err}\n{traceback.format_exc()}")

    @QtCore.Slot()
    def _update_mode_change(self, new_mode):
        self._update_ui_mode(new_mode)

    def _update_mode_status_bar(self, mode: str = None):
        gremlin.util.InvokeUiMethod(self._update_mode_status_bar_ui, mode)  # ensure on UI thread

    def _update_mode_status_bar_ui(self, mode: str = None):
        """updates the mode status bar with current runtime and edit modes"""
        try:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_mode
            is_running = gremlin.shared_state.is_running

            if not is_running:
                # syslog = logging.getLogger("system")
                edit_mode = mode if mode else gremlin.shared_state.edit_mode
                if not edit_mode:
                    # get it from the mode drop down
                    edit_mode = self.mode_selector.currentMode()

                if config.hide_default_mode and edit_mode and edit_mode.casefold() == "default":
                    msg = ""
                else:
                    msg = f" <b>Edit Mode:</b> {edit_mode if edit_mode else 'n/a'}"
                if self._status_bar_last_edit_mode != edit_mode:
                    if verbose:
                        syslog.info(f"Mode: New edit mode: [{edit_mode}] (last mode [{self._status_bar_last_edit_mode}])")
                    self._status_bar_last_edit_mode = edit_mode

            else:
                runtime_mode = mode if mode else gremlin.shared_state.runtime_mode

                if config.hide_default_mode and runtime_mode and runtime_mode.casefold() == "default":
                    msg = ""
                else:
                    msg = f"<b>Runtime Mode:</b> {runtime_mode if runtime_mode else 'n/a'}"
                if self._status_bar_last_runtime_mode != runtime_mode:
                    # if verbose: syslog.info(f"CHANGE MODE: To: [{runtime_mode}] (from [{self._status_bar_last_runtime_mode}])")
                    self._status_bar_last_runtime_mode = runtime_mode

            self.status_bar_mode_widget.setText(msg)
            if self.config.mode_change_message:
                toast_msg = f"Runtime Mode: {runtime_mode if runtime_mode else 'n/a'} Edit mode: {edit_mode if edit_mode else 'n/a'}"
                if self._last_toast_message is None or self._last_toast_message != toast_msg:
                    self.ui.tray_icon.showMessage(toast_msg, "", QtWidgets.QSystemTrayIcon.MessageIcon.NoIcon, 250)
                    self._last_toast_message = toast_msg
        except Exception as err:
            syslog.error("Unable to update status bar mode:")
            syslog.error(f"{err}\n{traceback.format_exc()}")

    def _update_ui_mode(self, new_mode):
        """called when the profile mode changes

        :param mode the now current mode
        """

        update = True
        is_running = gremlin.shared_state.is_running
        if is_running:
            update = self.config.runtime_ui_update

        if update:
            with QtCore.QSignalBlocker(self.mode_selector):
                for tab in self._get_tab_widgets():
                    if hasattr(tab, "set_mode"):
                        tab.set_mode(new_mode)

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
        """UI hotkey trap - listen for keyboard modifiers and keyboard events at runtime"""

        if event.is_pressed:
            key = gremlin.keyboard.KeyMap.from_event(event)

            # ignore if we're running
            if key is None or self.runner.is_running() or gremlin.shared_state.ui_keyinput_suspended():
                return

            if not gremlin.shared_state.ui_keyinput_suspended():
                match key.lookup_name:
                    case "f5":
                        # activate mode on F5
                        if not self.config.is_debug and self.config.start_on_f5:
                            self.ui.actionActivate.trigger()
                    case "f3":
                        # search again
                        el = gremlin.event_handler.EventListener()
                        el.find_next.emit()

    @property
    def input_axis_override(self):
        """true if temporary override of monitoring axis is enabled"""
        return self._temp_input_axis_override

    @property
    def input_axis_only_override(self):
        """true if temporary override of monitoring exclusive axis is enabled"""
        return self._temp_input_axis_only_override

    # +---------------------------------------------------------------
    # | Utilities
    # +---------------------------------------------------------------

    def apply_user_settings(self, ignore_minimize=False, auto_start=True):
        gremlin.util.InvokeUiMethod(self._apply_user_settings_ui, ignore_minimize, auto_start)  # run on UI thread

    def _apply_user_settings_ui(self, ignore_minimize=False, auto_start=True):
        """Configures the program based on user settings. UI thread"""

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
                thread = threading.Thread(target=self._auto_start_runner)
                thread.name = "autostart"
                thread.start()

    def _auto_start_runner(self):
        while gremlin.shared_state.ui is None or not gremlin.shared_state.ui.initialized:
            syslog.info("autostart waiting to start...")
            time.sleep(0.1)
            if gremlin.shared_state.terminating:
                # app is terminating
                return

        # also wait for the actual profile to be fully loaded in the
        # background worker thread - ui.initialized alone is not enough,
        # the profile can still be a placeholder/empty one at this point,
        # which builds an empty execution graph (0 functors) once activated
        target_name = getattr(self, "_autostart_target_name", None)
        if target_name:
            max_wait = 10.0  # seconds
            waited = 0.0
            while waited < max_wait:
                profile = gremlin.shared_state.current_profile
                if profile and profile.name == target_name:
                    break
                syslog.info(f"autostart waiting for profile [{target_name}] to finish loading...")
                time.sleep(0.1)
                waited += 0.1
                if gremlin.shared_state.terminating:
                    return

        syslog.info("autostart starting")

        el = gremlin.event_handler.EventListener()
        el.request_activate.emit(True)

        syslog.info("autostart completed")

    def _create_cheatsheet(self):
        """Creates a profile cheatsheet"""

        import gremlin.ui.ui_common
        import gremlin.ui.dialogs

        # gremlin.ui.ui_common.MessageBox(prompt="This feature is not currently available.")
        # return # disable in this version

        dialog = gremlin.ui.dialogs.CreateReportDialog(parent=self)
        dialog.exec()

    def _reorder_tabs(self):
        """opens a dialog to reorder tabs"""
        import gremlin.ui.ui_common
        import gremlin.ui.dialogs

        dialog = gremlin.ui.dialogs.DeviceDisplayDialog(parent=self)
        dialog.exec()

    def _view_input_map(self):
        """display input map dialog"""
        import gremlin.cheatsheet
        import gremlin.util

        dialog = gremlin.cheatsheet.ViewInput(parent=self)
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
    def profile(self) -> gremlin.base_profile.Profile:
        return gremlin.shared_state.current_profile

    @profile.setter
    def profile(self, value: gremlin.base_profile.Profile):
        current_profile = gremlin.shared_state.current_profile
        if current_profile and current_profile != value:
            eh = gremlin.event_handler.EventListener()
            eh.profile_unload.emit()

        gremlin.shared_state.current_profile = value

    def _do_load_profile(self, source_xml: str, as_new_profile=False, emit=True):
        self._profile_load_stack = []

        # clear list of disconnected devices from any prior profile
        gremlin.joystick_handling.clearDisconnectedDevices()

        if not source_xml:
            # invalid file
            return
        ext = gremlin.util.get_ext(source_xml)
        if not ext:
            source_xml = gremlin.util.swap_ext(source_xml, "xml")

        if not os.path.isfile(source_xml):
            # file does not exist
            return

        wm = WorkManager()
        wm.submit(
            callback=self._do_load_profile_internal_worker,
            complete_callback=self._profile_load_completed,
            args=(
                source_xml,
                as_new_profile,
                emit,
            ),
        )

    class delayed_runner_worker(QtCore.QObject):
        finished = QtCore.Signal()

        def __init__(self, ui):
            super().__init__()
            self.ui = ui

        @QtCore.Slot()
        def run(self):
            widget = self.ui.getCurrentRegisteredWidget()
            while widget is None:  # not available yet
                QThread.msleep(100)
                widget = self.ui.getCurrentRegisteredWidget()
            widget.refresh()
            self.finished.emit()  # indicate done

    def _profile_load_completed(self, *args):
        """called when a profile has been loaded"""  # force a UI update
        verbose = gremlin.config.Configuration().verbose_mode_ui
        widget: BaseDeviceTabWidget = self.getCurrentRegisteredWidget()
        if widget:
            widget.refresh(force=True)
        else:
            # delay refresh the current widget and we wait until it's available
            self._delay_refresh_thread = QThread()
            self.worker = GremlinUi.delayed_runner_worker(self)
            # Move worker to the new thread
            self.worker.moveToThread(self._delay_refresh_thread)

            # Connect thread lifecycle signals
            self._delay_refresh_thread.started.connect(self.worker.run)
            self.worker.finished.connect(self._delay_refresh_completed)
            self._delay_refresh_thread.start()
        if verbose:
            syslog.info("profile loaded")

    @QtCore.Slot()
    def _delay_refresh_completed(self):
        """called when the delayed refresh has completed"""
        self.worker.deleteLater()
        self._delay_refresh_thread.quit()
        self._delay_refresh_thread.deleteLater()

    def _do_load_profile_internal_worker(self, args) -> bool | tuple:
        """Load the profile with the given filename.

        :param source_xml: the name of the profile file to load
        :param as_new_profile: if set, loads the new profile as an unsaved profile

        """
        # Disable the program if it is running when we're loading a
        # new profile

        source_xml: str
        as_new_profile: bool
        source_xml, as_new_profile, emit = args

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info("Profile: worker: start loading")

        syslog.info(f"Profile: worker: loading profile {gremlin.util.toUrl(source_xml)}")

        # trap recursive call
        if self._profile_load_stack:
            self._profile_load_stack.append(source_xml)
            return

        eh = gremlin.event_handler.EventHandler()
        el = gremlin.event_handler.EventListener()

        # indicate tabs will need to be reloaded
        self.setTabsDirty()  #

        try:
            gremlin.shared_state.push_redraw()

            gremlin.shared_state.push_suspend_save_input()
            gremlin.shared_state.profile_loading = True

            self._profile_load_stack.append(source_xml)
            gremlin.shared_state.import_prompt_stack = 0  # reset prompt count for import remap (in profile_graph)

            el.profile_loading.emit()  # indicate we are loading a profile

            last_edit_mode = gremlin.config.Configuration().get_profile_last_edit_mode()

            # clear any old data
            self._reset_tab_data()
            while self.getTabCount():
                # wait for the tabs to go poof
                QThread.sleep(0)
            self.clearWidgets()

            # reset execution context
            ec = gremlin.execution_graph.ExecutionContext()
            ec.reset(no_rebuild=True)

            # reset joystick input/output flags
            sd = gremlin.event_handler.JoystickState()
            sd.reset()

            # reset event processor
            # jap = gremlin.event_handler.JoystickEventProcessor()
            # jap.reset()

            if emit:
                el.request_activate.emit(False)

            if gremlin.shared_state.current_profile:
                if emit:
                    el.profile_unload.emit()  # fire unload start
                current_profile = gremlin.shared_state.current_profile
                current_profile.unload()
                gremlin.shared_state.current_profile = None
                if emit:
                    el.profile_unloaded.emit()  # tell the UI we're about to load a new profile

            el.push_input_selection()  # suspend input selection

            while self._profile_load_stack:
                source_xml = self._profile_load_stack[0]

                import_data = gremlin.base_profile.ProfileImportData()
                import_data.used_ids.clear()

                # Attempt to load the new profile
                try:
                    new_profile = gremlin.base_profile.Profile()

                    if not os.path.isfile(source_xml):
                        gremlin.ui.ui_common.MessageBox(title="Profile Error", prompt="Specified file not found.")
                        return False
                    if os.path.getsize(source_xml) == 0:
                        gremlin.ui.ui_common.MessageBox(title="Profile Error", prompt="Specified file is empty.")
                        return False

                    gremlin.shared_state.current_profile = new_profile
                    self.profile = new_profile
                    profile_updated = new_profile.from_xml(source_xml)

                    profile_folder = os.path.dirname(source_xml)
                    if profile_folder not in sys.path:
                        sys.path = list(self._base_path)
                        sys.path.insert(0, profile_folder)

                    self._sanitize_profile(new_profile)

                    # save the profile comparative template
                    if os.path.isfile(self._comparative_file):
                        os.unlink(self._comparative_file)

                    # save a copy using new setup if any
                    new_profile.to_xml(self._comparative_file)

                    # Save the profile at this point if it was converted from a prior
                    # profile version, as otherwise the change detection logic will
                    # trip over insignificant input item additions.
                    if profile_updated:
                        new_profile.to_xml(source_xml)

                        # reload the profile
                        syslog.info("Profile: reload due to conversion.")
                        new_profile = gremlin.base_profile.Profile()
                        gremlin.shared_state.current_profile = new_profile
                        self.profile = new_profile
                        new_profile.from_xml(source_xml)

                    # next file

                    if source_xml in self._profile_load_temporary_files:
                        # clean up the temporary file once loaded
                        os.unlink(source_xml)
                        new_profile.setProfileFile(None)

                    self._profile_load_stack.pop(0)
                    if verbose:
                        syslog.info("Profile: worker parse completed.")

                except (KeyError, TypeError) as err:
                    # An error occurred while parsing an existing profile,
                    # creating an empty profile instead
                    syslog.exception("Invalid profile content:")
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

            if last_edit_mode not in modes:
                # no longer in the current mode list
                last_edit_mode = new_profile.get_default_mode()

            # Make the first root node the default active mode
            self.mode_selector.populate_selector(new_profile, last_edit_mode, emit=False)

            gremlin.shared_state.edit_mode = last_edit_mode
            gremlin.shared_state.runtime_mode = new_profile.get_default_start_mode()

            # indicate profile was loaded
            new_profile.setLoaded(True)

            # update the hash value
            self._profile_hash = new_profile.getMappingHash()

            # setup default profile input filter
            if not new_profile.settings.input_visible_map:
                # default to mapped mode for older profiles without data
                new_profile.settings.setAllVisible("mapped")

            # reload the calibration data if the profile has custom calibration
            mgr = gremlin.ui.axis_calibration.CalibrationManager()
            mgr.reload()

            # select the new mode

            eh.change_mode(last_edit_mode, force_update=True, emit=False)

            if emit:
                el.profile_loaded.emit()

                # ask the UI to update input curve icons
                el.update_input_icons.emit()

            # update the status bar

            self._update_window_title()

            el.pop_input_selection(True)  # restore input selection and reset

            syslog.info("Profile: load completed.")

            # mode to restore post-load if possible

            last_device_guid, last_input_type, last_input_id = new_profile.getLastInput()  # self.config.get_last_input()

            # enable saving the configuration
            new_profile.saveConfigEnabled = True
            if last_device_guid is not None:
                self._select_input(
                    last_device_guid,
                    last_input_type,
                    last_input_id,
                    force_switch=True,
                    force_update=True,
                )

        finally:
            gremlin.shared_state.pop_redraw()

            gremlin.shared_state.profile_loading = False  # done loading
            gremlin.shared_state.pop_suspend_save_input()

            el.profile_loading_completed.emit()

            # update UI post load
            self.refresh()
            pass

    def refresh(self):
        gremlin.util.InvokeUiMethod(self._refresh_ui)

    def _refresh_ui(self):
        """refresh the UI"""

        # save selection
        current_device_guid = gremlin.shared_state.current_tab_device_guid
        current_input_type, current_input_id = self._get_last_input(current_device_guid)

        self._create_tabs_ui()

        current_profile = gremlin.shared_state.current_profile
        current_mode = gremlin.shared_state.current_mode

        # Make the first root node the default active mode
        self.mode_selector.populate_selector(current_profile, current_mode, emit=False)

        # refresh current device tab
        # self._refresh_tab()

        # select
        self._select_input(current_device_guid, current_input_type, current_input_id, True)

    def _force_close(self):
        """Forces the closure of the program."""
        self._really_quitting = True
        self.ui.tray_icon.hide()
        self.close()
        # safety net: some background threads may not release the process
        # promptly after quit(), leaving it alive in Task Manager with no
        # window or tray icon. External watchdog guarantees termination.
        pid = os.getpid()
        try:
            subprocess.Popen(
                ["cmd", "/c", f"timeout /t 5 /nobreak >nul & taskkill /F /PID {pid}"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

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
        result = None

        def setResult(value):
            nonlocal result
            result = value

        if gremlin.util.is_ui_thread():
            return self._save_changes_request_ui()
        else:
            gremlin.util.InvokeUiMethod(self._save_changes_request_ui, setResult)

        # gremlin.util.InvokeUiMethod(self._save_changes_request_ui, setResult)
        while result is None:
            time.sleep(0.01)
        return result

    def _save_changes_request_ui(self, callback: Callable = None):
        """Asks the user what to do in case of a profile change.

        Presents the user with a dialog asking whether or not to save or
        discard changes to a profile or entirely abort the process.

        :return True continue with the intended action, False abort
        """
        gremlin.util.assert_ui_thread()

        # If the profile is empty we don't need to ask anything
        if not self.profile:
            if callback:
                callback(True)
            return True
        if self.profile.empty():
            if callback:
                callback(True)
            return True

        continue_process = True
        if self._has_profile_changed():
            message_box = QtWidgets.QMessageBox()
            message_box.setText("The profile has been modified.")
            message_box.setInformativeText("Do you want to save your changes?")
            message_box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel
            )
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
            gremlin.util.centerDialog(message_box)

            response = message_box.exec()

            if response == QtWidgets.QMessageBox.StandardButton.Save:
                self.save_profile()
            elif response == QtWidgets.QMessageBox.StandardButton.Cancel:
                continue_process = False
        if callback:
            callback(continue_process)
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
            # tmp_path = os.path.join(os.getenv("temp"), gremlin.util.get_guid() + ".xml")
            tmp_path = os.path.join(os.getenv("temp"), "gremlin.xml")

            try:
                self.profile.to_xml(tmp_path)
            except Exception as e:
                syslog.warning(f"Failed to write profile to temporary XML file: {e}")
                return False

            # compare files
            import filecmp

            if os.path.isfile(tmp_path) and os.path.isfile(self._comparative_file):
                is_changed = filecmp.cmp(tmp_path, self._comparative_file, shallow=False)
            else:
                # missing file means no changes detected
                is_changed = False

            # is_changed = filecmp.cmp(tmp_path, self._comparative_file, shallow=False)
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except Exception as e:
                syslog.warning(f"Failed to remove temporary XML file: {e}")

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

        if self.profile.override_start_mode:
            last_mode = self.profile.override_start_mode
            self.profile.override_start_mode = None  # one time use
        else:
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

        if last_mode not in mode_list:
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

    def _edit_mode_changed(self, mode: str):
        gremlin.util.InvokeUiMethod(self._edit_mode_changed_ui, mode)  # ensure on UI thread

    def _edit_mode_changed_ui(self, mode: str):
        """called when edit time mode has changed"""
        # update the mode selector to the correct edit mode
        if mode:
            self.mode_selector.select_mode(mode)
            gremlin.event_handler.EventHandler().set_edit_mode(mode)

        self.setTabsDirty(True)

    def _edit_mode_update(self, mode: str):
        if mode and self.mode_selector.currentMode() != mode:
            gremlin.util.InvokeUiMethod(self._edit_mode_update_ui, mode)  # ensure on UI thread

    def _edit_mode_update_ui(self, mode: str):
        if mode and self.mode_selector.currentMode() != mode:
            self.mode_selector.select_mode(mode)

    def _runtime_mode_changed(self, mode: str):
        """called when runtime mode changes"""

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
            self.config.highlight_input_buttons = button_state

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
        """true if button highlighting is currently enabled - this is either highlight or one of the shift keys held"""
        if not self.config.highlight_enabled or not self.config.highlight_input_buttons:
            # disabled
            return False
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False

        el = gremlin.event_handler.EventListener()
        is_hotkey_autoswitch = self.config.highlight_hotkey_autoswitch
        is_control = el.get_control_shift_state()
        if is_control:
            return False  # listen to axis only
        is_shifted = el.get_shifted_state() if is_hotkey_autoswitch else False
        return self.config.highlight_input_buttons or is_shifted or self._button_highlighting_enabled

    @property
    def is_axis_highlighting(self) -> bool:
        """true if button highlighting is currently enabled"""
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
            return False  # listen to buttons only
        is_control = el.get_control_shift_state() if is_hotkey_autoswitch else False
        return self.config.highlight_input_axis or is_control or self._axis_highlighting_enabled

    @property
    def is_highligthing_enabled(self) -> bool:
        """true if tab switch highlighting is enabled"""
        if gremlin.shared_state.is_highlighting_suspended():
            # skip if highlighting is currently suspended
            return False

        return self.config.highlight_enabled

    def push_highlighting(self):
        """disables the highlighting of devices"""
        gremlin.shared_state.push_suspend_highlighting()

    def pop_highlighting(self, reset=False):
        """enables the highlighting of devices"""
        gremlin.shared_state.pop_suspend_highlighting(reset)

    def _should_process_input(self, event, widget, buttons_only=False):
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

        if self.input_axis_override and self.input_axis_only_override and event.event_type == InputType.JoystickButton:
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
        self.status_bar_repeater_widget.setText("<b>Repeater: </b> {}".format(text))

    def _update_window_title(self, title: str = None):
        gremlin.util.InvokeUiMethod(self._update_window_title_ui, title)

    def _update_window_title_ui(self, title: str = None):
        """Updates the window title to include the current profile."""
        assert gremlin.util.is_ui_thread()
        if title is None:
            profile_fname = None
            if gremlin.shared_state.current_profile is not None:
                profile_fname = gremlin.shared_state.current_profile.profile_file
            if profile_fname:
                the_title = f"{os.path.basename(profile_fname)}"
            else:
                the_title = "Untitled"

        else:
            the_title = title

        # add client name to title bar if remote mode is enabled
        config = gremlin.config.Configuration()

        if config.enable_log_version:
            the_title = f"{the_title} [V]"

        if config.remoteEnabled():
            # add client name as a reference to title bar if a remote mode is enabled
            the_title = f"{the_title} [{gremlin.remote.remote_client.getClientName()}]"

        self.setWindowTitle(the_title)



def configure_logger(config: dict):
    """Creates a new logger instance.

    :param config configuration information for the new logger
    """
    import logging.handlers

    # blitz the log file
    log_file = config["logfile"]
    unlink = config.get("unlink", True)
    try:
        if unlink and os.path.isfile(log_file):
            os.unlink(log_file)
    except IOError as err:
        syslog.error(f"Unable to remove old log file [{log_file}] - another instance may be running")
        # syslog.error(f"{err}\n{traceback.format_exc()}")
        return False

    logger = logging.getLogger(config["name"])
    logger.setLevel(config["level"])
    mb = config.get("megabytes", 5) * 1024 * 1024
    bc = config.get("backupCount", 1)

    fmt = config.get("format", "%(asctime)s.%(msecs)03d %(levelname)10s %(message)s")
    formatter = logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S")

    # handler = logging.FileHandler(config["logfile"])
    handler = RotatingFileHandler(config["logfile"], maxBytes=mb, backupCount=bc)
    handler.setLevel(config["level"])

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    if "faultfile" in config:
        mb = config.get("faultmegabytes", config.get("faultmegabytes", 1)) * 1024 * 1024
        bc = config.get("faultbackupCount", config.get("faultbackupCount", 3))
        fault_handler = RotatingFileHandler(config["faultfile"], maxBytes=mb, backupCount=bc)
        fault_handler.setLevel(logging.ERROR)
        fault_handler.setFormatter(formatter)
        logger.addHandler(fault_handler)

    # logger.debug("-" * 80)
    # logger.debug(time.strftime("%Y-%m-%d %H:%M"))
    # logger.debug(f"Starting {gremlin.version.APPLICATION_NAME} {gremlin.version.APPLICATION_VERSION}")
    # logger.debug("-" * 80)

    console = logging.StreamHandler()
    logger.addHandler(console)

    return True


def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    # Ignore KeyboardInterrupt (Ctrl+C) so users can close the app normally
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Log the complete traceback string automatically into both log files
    msg = "Uncaught exception:\n"
    msg += " ".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    syslog.critical(msg)
    gremlin.util.display_error(msg)


# general exception handling
sys.excepthook = handle_unhandled_exception

WM_INPUT = 0x00FF


if __name__ == "__main__":
    gremlin.shared_state.ui_ready = False

    # Create user interface
    app_id = "gremlinex"
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
    # app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)  # don't quit when the main window is hidden (minimize to tray)
    app.setStyle(gremlin.ui.ui_common.GexAppStyle())
    app.setStyleSheet(gremlin.ui.ui_common.Color.cssApplication())
    icon = gremlin.util.load_icon("gex.ico")
    if icon:
        app.setWindowIcon(icon)

    # set faster context switch for Python
    sys.setswitchinterval(0.001)

    try:
        app_path = gremlin.shared_state.data_path

        # check for running instances
        ph = gremlin.process.ProcessHelper()
        process_name = gremlin.version.APPLICATION_EXE
        prompted = False

        # ensure only one instance is running at a time - this is setup to not require admin rights as long as the process is started by the user
        while ph.processRunning(process_name):
            # attempt to kill it
            # run the application so we can get a message box UI

            if not prompted:
                result = gremlin.ui.ui_common.ConfirmBox(
                    informative_text="Another instance of GremlinEx is already running.  If the current instance cannot be terminated, this one will exit.",
                    prompt="Terminate running process?",
                )
                prompted = True
            else:
                result = True

            if result:
                result = ph.killProcess(process_name, timeout_ms=5000)
                if not result:
                    syslog.error(f"PROC: Failed to terminate process {process_name}")
                    os._exit(1)
                syslog.info(f"PROC: Successfully terminated process {process_name}")

            else:
                # terminate
                os._exit(0)

        # log file configuration

        # Path mangling to ensure Gremlin starts independent of the CWD
        sys.path.insert(0, app_path)
        gremlin.config.Configuration().setup_userprofile()

        system_log_path = os.path.join(app_path, "system.log")
        user_log_path = os.path.join(app_path, "user.log")
        fault_log_path = os.path.join(app_path, "fault.log")
        fl = None

        gremlin.shared_state.app_path = app_path
        gremlin.shared_state.system_log = system_log_path
        gremlin.shared_state.user_log = user_log_path
        gremlin.shared_state.fault_log = fault_log_path

        # system log
        result = configure_logger(
            {
                "name": "system",
                "level": logging.DEBUG,
                "logfile": system_log_path,
                "megabytes": 5,
                "backupCount": 1,
                "faultfile": fault_log_path,
                "faultbackupCount": 2,
                "faultmegabytes": 1,
                "unlink": False,
            }
        )
        if not result:
            # another instance running
            os._exit(1)

        # user log
        configure_logger(
            {
                "name": "user",
                "level": logging.DEBUG,
                "logfile": user_log_path,
            }
        )

        # Fix some dumb Qt bugs
        QtWidgets.QApplication.addLibraryPath(os.path.join(os.path.dirname(PySide6.__file__), "plugins"))

        # syslog = logging.getLogger("system")

        syslog.info(f"Joystick Gremlin Ex version {gremlin.version.Version().version}  (P{gremlin.util.getPythonVersion()})")

        # Initialize the vjoy interface
        from vjoy.vjoy_interface import VJoyInterface

        VJoyInterface.initialize()

        # Initialize the direct input interface class
        from dinput import DILL

        DILL.init()
        DILL.initialize_capi()
        syslog.info(f"Found DirectInput Interface version {DILL.version}")

        # qt version
        syslog.info(f"Found QT version {PySide6.__version__}")

        # Show unhandled exceptions to the user when running a compiled version
        # of Joystick Gremlin
        executable_name = os.path.split(sys.executable)[-1]

        # Initialize HidGuardian before we let SDL grab joystick data
        import gremlin.hid_guardian

        hg = gremlin.hid_guardian.HidGuardian()
        hg.add_process(os.getpid())

        config = gremlin.config.Configuration()

        # command line parser
        parser = QtCore.QCommandLineParser()
        parser.addOption(QtCore.QCommandLineOption(["noprofile", "np"], "Do not load a profile on start (--r and --p will be ignored)"))
        parser.addOption(QtCore.QCommandLineOption(["run", "r"], "Automatically run the last profile, or specified profile via --p on start"))
        parser.addOption(
            QtCore.QCommandLineOption(
                ["profile", "p"],
                "Profile to load, requires the profile xml to be provided.  If a path is not provided, GremlinEx will look for the profile file in the default profile folder.",
            )
        )
        parser.addOption(QtCore.QCommandLineOption(["nomousehook", "nmh"], "Disables mouse hook (prevents mouse output) - diagnostics use only"))
        parser.addHelpOption()

        parser.process(app.arguments())

        config.mouse_hook_disabled = parser.isSet("nomousehook")

        config.auto_load_disabled = parser.isSet("noprofile")
        if config.auto_load_disabled:
            # start with a new profile
            config.run_on_start = False
            config.profile_to_load = False
        else:
            config.run_on_start = parser.isSet("run")
            profile_specified = parser.isSet("profile")
            args = parser.positionalArguments() if profile_specified else None
            if args:
                profile_to_load = args[0]
                if not os.path.isfile(profile_to_load):
                    profile_to_load = os.path.join(app_path, profile_to_load)
                    if not os.path.isfile(profile_to_load):
                        msg = f"Profile file not found: {args[0]}"
                        gremlin.ui.ui_common.MessageBoxWarning(msg)
                        syslog.error(msg)
                        os._exit(1)
            else:
                if profile_specified:
                    msg = "Missing argument: Profile file not specified"
                    gremlin.ui.ui_common.MessageBoxWarning(msg)
                    syslog.error(msg)
                    os._exit(1)

            config.profile_to_load = profile_to_load if args else None

        # event listener init (after processing command line args)
        el = gremlin.event_handler.EventListener()
        el.postInit()

        # for now force localization to use US English until we have proper localization support
        locale = QtCore.QLocale("UnitedStates")
        QtCore.QLocale.setDefault(locale)

        icon = gremlin.util.load_icon("gex.ico")
        if icon:
            app.setWindowIcon(icon)
        app.setApplicationDisplayName(gremlin.version.APPLICATION_NAME + " " + gremlin.version.APPLICATION_VERSION)
        app.setApplicationVersion(gremlin.version.APPLICATION_VERSION)
        # no longer needed in QT6
        # app.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling)

        # handle windows themes better
        app.setStyle("Fusion")

        # Ensure joystick devices are correctly setup
        dinput.DILL.init()
        time.sleep(0.25)

        # instance
        # _pixmaps = gremlin.ui.ui_common.Pixmaps()
        # _widget_manager = gremlin.ui.ui_common.WidgetManager()

        # check for gamepad availability via VIGEM
        if gremlin.gamepad_handling.gamepadAvailable():
            gremlin.gamepad_handling.gamepad_initialization()

        # update device list
        gremlin.joystick_handling.joystick_devices_initialization()

        # Check if vJoy is properly setup and if not display an error
        # and terminate GremlinEx
        try:
            syslog.info("Checking vJoy installation")
            vjoy_count = len([dev for dev in gremlin.joystick_handling.all_joystick_devices() if dev.is_virtual and dev.connected])
            vjoy_working = vjoy_count != 0
            syslog.info(f"\tFound {vjoy_count} configured vjoy device(s)")

            gremlin.shared_state.vjoy_enabled = vjoy_working

            if not vjoy_working:
                msg = "No configured VJOY devices were found.  VJOY output will be disabled.  This is normal if VJOY is not installed or not configured."
                syslog.warning(msg)
                # gremlin.ui.ui_common.MessageBox("Error Scanning Devices", msg)
                # raise gremlin.error.GremlinError(msg)

        except (gremlin.error.GremlinError, dinput.DILLError) as e:
            error_display = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical, "Error", e.value, QtWidgets.QMessageBox.Ok)
            error_display.move
            error_display.show()

            app.exec_()

            gremlin.joystick_handling.VJoyProxy.reset()
            el = gremlin.event_handler.EventListener()
            el.terminate()  # terminates and sends the relevant shutdown triggers
            fl.close()
            sys.exit(0)

        gremlin.shared_state.reload_device_map()

        # Initialize action plugins
        syslog.info("Initializing plugins")
        gremlin.plugin_manager.ActionPlugins()
        gremlin.plugin_manager.ContainerPlugins()

        # input map tracking instance
        iim_tracker = gremlin.ui.ui_common.WidgetCacheTracker()

        # Create Gremlin UI
        ui = GremlinUi()

        # joystick state
        sd = gremlin.event_handler.JoystickState()
        sd.hook()
        sd.reset()  # initial state

        _tab_state = gremlin.tabstate.TabState()  # instance

        astate = gremlin.event_handler.AxisState()
        astate.reset()

        # joystick processor instance
        # event_processor = gremlin.event_handler.JoystickEventProcessor()

        syslog.info("GremlinEx UI created")

        # state monitoring
        profile_state_monitor = gremlin.shared_state.ProfileStateMonitor()

        # automatic process monitoring check

        pmgr = gremlin.process.ProcessMonitor()
        el = gremlin.event_handler.EventListener()
        el.process_monitor_changed.emit()

        ec = gremlin.execution_graph.ExecutionContext()

        gremlin.shared_state.char_width = gremlin.ui.ui_common.get_text_width("M")

        # report ui
        report = gremlin.reporting.ReportEngine()

        # sound engine
        sound = gremlin.sound.Sound()
        edge_tts = gremlin.sound.EdgeTTS()

        # MIDI
        midi_client = gremlin.ui.midi_device.MidiClient()

        # event regsitry
        event_registry = gremlin.event_handler.EventRegistry()

        # RPC server if enabled in configuration
        if config.remoteEnabled():
            gremlin.remote.remote_server.start()
            gremlin.remote.remote_client.start()

        # HID maestro
        maestro = gremlin.maestro.Maestro()

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

        syslog.info("Apply settings...")
        ui.apply_user_settings()

        # identify self to the network on start
        gremlin.remote.remote_client.requestIdentify()

        if not config.start_minimized:
            ui.showNormal()

        syslog.info("GremlinEx UI launching...")

        try:
            # integrate twisted with QT framework
            # twisted framework
            # syslog.info("starting app exec")
            app.exec()
        except Exception as err:
            syslog.error(f"{err}\n{traceback.format_exc()}")

        syslog.info("GremlinEx UI terminated")

        gremlin.shared_state.terminating = True

        # Terminate potentially running EventListener loop
        gremlin.joystick_handling.VJoyProxy.reset()
        el = gremlin.event_handler.EventListener()
        el.terminate()  # terminates and sends the relevant shutdown triggers

        if vjoy_working:
            # Properly terminate the runner instance should it be running
            ui.runner.stop()

        # Relinquish control over all VJoy devices used
        gremlin.joystick_handling.VJoyProxy.reset()

        # hg.remove_process(os.getpid())
        if fl:
            fl.close()

        syslog.info("Terminating GremlinEx")
        # gc.collect()
        sys.exit(0)

    except Exception as e:
        pass
