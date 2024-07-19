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

import argparse
import ctypes
import hashlib
import logging
import os
import sys
import time
import traceback
import threading
import webbrowser

import dinput
import gremlin.ui.keyboard_device
import gremlin.ui.midi_device
import gremlin.ui.osc_device
import gremlin.util

# Import QtMultimedia so pyinstaller doesn't miss it
import PySide6
from PySide6 import QtCore, QtGui, QtWidgets

import gremlin.event_handler 
import gremlin.shared_state
from gremlin.input_types import InputType
from gremlin.types import DeviceType



import gremlin.config
from gremlin.util import load_icon, load_pixmap, userprofile_path, find_file, waitCursor, popCursor


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
APPLICATION_VERSION = "13.40.14ex (k)"

# the main ui
ui = None

from gremlin.singleton_decorator import SingletonDecorator

@SingletonDecorator
class Version():
    version = APPLICATION_VERSION

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
        self.locked = False
        self.device_change_locked = False

        self._resize_count = 0



        # Process monitor
        self.process_monitor = gremlin.process_monitor.ProcessMonitor()
        self.process_monitor.process_changed.connect(self._process_changed_cb)

        # Default path variable before any runtime changes
        self._base_path = list(sys.path)

        self.tabs = {}
        self.config = gremlin.config.Configuration()
        self.runner = gremlin.code_runner.CodeRunner()
        self.repeater = gremlin.repeater.Repeater(
            [],
            self._update_statusbar_repeater
        )
        self.runner.event_handler.mode_changed.connect(
            self._update_status_bar_mode
        )
        self.runner.event_handler.is_active.connect(
            self._update_status_bar_active
        )

        self.mode_selector = gremlin.ui.ui_common.ModeWidget()
        self.mode_selector.edit_mode_changed.connect(self._edit_mode_changed_cb)

        self.ui.toolBar.addWidget(self.mode_selector)

        # Setup profile storage
        
        self._profile = gremlin.base_profile.Profile()
        self._profile_fname = None
        self._profile_auto_activated = False
        # Input selection storage
        self._last_input_timestamp = time.time()
        self._last_input_event = None
        self._last_tab_switch = None
        self._input_delay = 0.25
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
        el.profile_start.connect(lambda: self._update_status_bar_active(True))
        el.profile_stop.connect(lambda: self._update_status_bar_active(False))

        # hook changes
        eh = gremlin.event_handler.EventHandler()
        eh.profile_changed.connect(self._profile_changed_cb)



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

        



    def _profile_changed_cb(self, new_profile):
        ''' called when the a profile should be loaded '''
        self._load_recent_profile(new_profile)
    


    @property
    def current_profile(self):
        ''' gets the curernt active profile '''
        return self._profile

    def refresh(self):
        ''' forces a refreshes the UI by processing events '''
        app = QtWidgets.QApplication.instance()
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 1)



    def closeEvent(self, evt):
        """Terminate the entire application if the main window is closed.

        :param evt the closure event
        """
        if self.config.close_to_tray and self.ui.tray_icon.isVisible():
            self.hide()
            evt.ignore()
        else:
            self.process_monitor.running = False
            del self.ui.tray_icon
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
        self.modal_windows["calibration"] = \
            gremlin.ui.axis_calibration.CalibrationUi()
        self.modal_windows["calibration"].show()
        gremlin.shared_state.set_suspend_input_highlighting(True)
        self.modal_windows["calibration"].closed.connect(
            lambda: gremlin.shared_state.set_suspend_input_highlighting(False)
        )
        self.modal_windows["calibration"].closed.connect(
            lambda: self._remove_modal_window("calibration")
        )

    def device_information(self):
        """Opens the device information window."""
        self.modal_windows["device_information"] = \
            gremlin.ui.dialogs.DeviceInformationUi(self._profile)
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
        self.modal_windows["mode_manager"] = \
            gremlin.ui.dialogs.ModeManagerUi(self._profile)
        self.modal_windows["mode_manager"].modes_changed.connect(
            self._mode_configuration_changed
        )
        self.modal_windows["mode_manager"].show()
        self.modal_windows["mode_manager"].closed.connect(
            lambda: self._remove_modal_window("mode_manager")
        )

    def merge_axis(self):
        """Opens the modal window to define axis merging."""
        self.modal_windows["merge_axis"] = \
            gremlin.ui.merge_axis.MergeAxisUi(self._profile)
        self.modal_windows["merge_axis"].show()
        self.modal_windows["merge_axis"].closed.connect(
            lambda: self._remove_modal_window("merge_axis")
        )

    def options_dialog(self):
        """Opens the options dialog."""
        self.modal_windows["options"] = gremlin.ui.dialogs.OptionsUi()
        self.modal_windows["options"].setWindowModality(QtCore.Qt.ApplicationModal)
        self.modal_windows["options"].show()
        self.modal_windows["options"].closed.connect(
            lambda: self.apply_user_settings(ignore_minimize=True)
        )
        self.modal_windows["options"].closed.connect(
            lambda: self._remove_modal_window("options")
        )

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
        gremlin.shared_state.set_suspend_input_highlighting(True)
        self.modal_windows["profile_creator"].closed.connect(
            lambda: gremlin.shared_state.set_suspend_input_highlighting(False)
        )
        self.modal_windows["profile_creator"].closed.connect(
            lambda: self._remove_modal_window("profile_creator")
        )

    def swap_devices(self):
        """Opens the UI used to swap devices."""
        self.modal_windows["swap_devices"] = \
            gremlin.ui.dialogs.SwapDevicesUi(self._profile)
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

    def activate(self, activate):
        """Activates and deactivates the code runner.

        :param checked True when the runner is to be activated, False
            otherwise
        """

        import gremlin.ui.device_tab
        import gremlin.ui.keyboard_device
        import gremlin.ui.midi_device
        import gremlin.ui.osc_device

        # from gremlin.ui.device_tab import JoystickDeviceTabWidget
        # from gremlin.ui.keyboard_device import KeyboardDeviceTabWidget
        # from gremlin.ui.midi_device  import MidiDeviceTabWidget
        # from gremlin.ui.osc_device import OscDeviceTabWidget

        from gremlin.config import Configuration
        verbose = Configuration().verbose

        if activate:
            # Generate the code for the profile and run it
            if verbose:
                logging.getLogger("system").info(f"Activate: activate profile")
            self._profile_auto_activated = False
            self.runner.start(
                self._profile.build_inheritance_tree(),
                self._profile.settings,
                self._last_active_mode(),
                self._profile
            )
            #print ("set icon ACTIVE")
            self.ui.tray_icon.setIcon(load_icon("gfx/icon_active.ico"))
            
        else:
            # Stop running the code
            if verbose:
                logging.getLogger("system").info(f"Deactivate profile requested")
            if self.runner.is_running():
                # running - save the current mode 
                self._profile.set_last_mode(gremlin.shared_state.current_mode)
                
            
            self.runner.stop()
            self._update_status_bar_active(False)
            self._profile_auto_activated = False
            current_tab = self.ui.devices.currentWidget()
            if type(current_tab) in [
                gremlin.ui.device_tab.JoystickDeviceTabWidget,
                gremlin.ui.keyboard_device.KeyboardDeviceTabWidget,
                gremlin.ui.midi_device.MidiDeviceTabWidget,
                gremlin.ui.osc_device.OscDeviceTabWidget

            ]:
                self.ui.devices.currentWidget().refresh()
            #print ("set icon INACTIVE")
            self.ui.tray_icon.setIcon(load_icon("gfx/icon.ico"))
                    
            

    def create_1to1_mapping(self):
        """Creates a 1 to 1 mapping of the given device to the first
        vJoy device.
        """
        # Don't attempt to create the mapping for the "Getting Started"
        # widget
        if isinstance(self.ui.devices.currentWidget(), QtWidgets.QTextEdit):
            return

        device_profile = self.ui.devices.currentWidget().device_profile
        # Don't create mappings for non joystick devices
        if device_profile.type != DeviceType.Joystick:
            return

        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        action_plugins = gremlin.plugin_manager.ActionPlugins()

        mode = device_profile.modes[gremlin.shared_state.current_mode]
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
        main_profile = device_profile.parent
        for input_type in input_types:
            for entry in mode.config[input_type].values():
                item_list = main_profile.list_unused_vjoy_inputs()

                container = container_plugins.repository["basic"](entry)
                action = action_plugins.repository["remap"](container)
                action.input_type = input_type
                action.vjoy_device_id = 1
                if len(item_list[1][type_name[input_type]]) > 0:
                    action.vjoy_input_id = item_list[1][type_name[input_type]][0]
                else:
                    action.vjoy_input_id = 1

                container.add_action(action)
                entry.containers.append(container)
        self._create_tabs()

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
            self.status_bar_repeater.setText("")

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

    def new_profile(self):
        """Creates a new empty profile."""
        # Disable Gremlin if active before opening a new profile

        waitCursor()

        self.ui.actionActivate.setChecked(False)
        self.activate(False)

        if not self._save_changes_request():
            return

        self._profile = gremlin.base_profile.Profile()

        # For each connected device create a new empty device entry
        # in the new profile
        for device in gremlin.joystick_handling.physical_devices():
            self._profile.initialize_joystick_device(device, ["Default"])

        # add MIDI device
        midi_device =  gremlin.base_profile.Device(self._profile)
        midi_device.name = "midi"
        midi_device.device_guid = gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid
        midi_device.type = DeviceType.Midi
        self._profile.devices[midi_device.device_guid ] = midi_device

        # add OSC device
        osc_device =  gremlin.base_profile.Device(self._profile)
        osc_device.name = "osc"
        osc_device.device_guid = gremlin.ui.osc_device.OscDeviceTabWidget.device_guid
        osc_device.type = DeviceType.Osc
        self._profile.devices[osc_device.device_guid ] = osc_device

        # Create keyboard device entry
        keyboard_device = gremlin.base_profile.Device(self._profile)
        keyboard_device.name = "keyboard"
        keyboard_device.device_guid = dinput.GUID_Keyboard
        keyboard_device.type = DeviceType.Keyboard
        self._profile.devices[dinput.GUID_Keyboard] = keyboard_device

        

        # Update profile information
        self._profile_fname = None
        self._update_window_title()
        gremlin.shared_state.current_profile = self._profile

        # Create a default mode
        for device in self._profile.devices.values():
            device.ensure_mode_exists("Default")
        gremlin.shared_state.current_mode = "Default"

        # Create device tabs
        self._create_tabs()

        # Update everything to the new mode
        self._mode_configuration_changed()

        popCursor()

    def save_profile(self):
        """Saves the current profile to the hard drive.

        If the file was loaded from an existing profile that file is
        updated, otherwise the user is prompted for a new file.
        """
        if self._profile_fname:
            self._profile._profile_fname = self._profile_fname
            self._profile.save()
        else:
            self.save_profile_as()
        self._update_window_title()

    def save_profile_as(self):
        """Prompts the user for a file to save to profile to."""
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save Profile",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )
        if fname != "":
            self._profile._profile_fname = fname
            self._profile.save()
            self._profile_fname = fname
            self.config.last_profile = fname
            self._create_recent_profiles()
        self._update_window_title()

    def reveal_profile(self):
        ''' opens the profile in explorer '''
        if self._profile_fname and os.path.isfile(self._profile_fname):
            path = os.path.dirname(self._profile_fname)
            path = os.path.realpath(path)
            webbrowser.open(path)

    def open_profile_xml(self):
        ''' views the profile as an xml in the default text editor '''
        if self._profile_fname:
            # save first
            self._profile.to_xml(self._profile_fname)
            if  os.path.isfile(self._profile_fname):
                path = os.path.realpath(self._profile_fname)
                webbrowser.open(path)

    # +---------------------------------------------------------------
    # | Create UI elements
    # +---------------------------------------------------------------

    def _connect_actions(self):
        """Connects all QAction items to their corresponding callbacks."""
        # Menu actions
        # File
        self.ui.actionLoadProfile.triggered.connect(self.load_profile)
        self.ui.actionNewProfile.triggered.connect(self.new_profile)
        self.ui.actionSaveProfile.triggered.connect(self.save_profile)
        self.ui.actionSaveProfileAs.triggered.connect(self.save_profile_as)
        self.ui.actionRevealProfile.triggered.connect(self.reveal_profile)
        self.ui.actionOpenXmlProfile.triggered.connect(self.open_profile_xml)
        self.ui.actionModifyProfile.triggered.connect(self.profile_creator)
        self.ui.actionExit.triggered.connect(self._force_close)
        # Actions
        self.ui.actionCreate1to1Mapping.triggered.connect(
            self.create_1to1_mapping
        )
        self.ui.actionMergeAxis.triggered.connect(self.merge_axis)
        self.ui.actionSwapDevices.triggered.connect(self.swap_devices)

        # Tools
        self.ui.actionDeviceInformation.triggered.connect(
            self.device_information
        )
        self.ui.actionManageModes.triggered.connect(self.manage_modes)
        self.ui.actionInputRepeater.triggered.connect(self.input_repeater)
        self.ui.actionCalibration.triggered.connect(self.calibration)
        self.ui.actionInputViewer.triggered.connect(self.input_viewer)
        self.ui.actionPDFCheatsheet.triggered.connect(
            lambda: self._create_cheatsheet()
        )
        self.ui.actionOptions.triggered.connect(self.options_dialog)
        self.ui.actionLogDisplay.triggered.connect(
            self.log_window
        )
        # About
        self.ui.actionAbout.triggered.connect(self.about)

        # Toolbar actions
        self.ui.actionActivate.triggered.connect(self.activate)
        self.ui.actionOpen.triggered.connect(self.load_profile)

        # Tray icon
        self.ui.tray_icon.activated.connect(self._tray_icon_activated_cb)

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
        self.status_bar_mode = QtWidgets.QLabel("")
        self.status_bar_mode.setContentsMargins(5, 0, 5, 0)
        self.status_bar_is_active = QtWidgets.QLabel("")
        self.status_bar_is_active.setContentsMargins(5, 0, 5, 0)
        self.status_bar_repeater = QtWidgets.QLabel("")
        self.status_bar_repeater.setContentsMargins(5, 0, 5, 0)
        self.ui.statusbar.addWidget(self.status_bar_is_active, 0)
        self.ui.statusbar.addWidget(self.status_bar_mode, 3)
        self.ui.statusbar.addWidget(self.status_bar_repeater, 1)

    def _create_system_tray(self):
        """Creates the system tray icon and menu."""
        self.ui.tray_menu = QtWidgets.QMenu("Menu")
        self.ui.action_tray_show = \
            QtGui.QAction("Show / Hide", self)
        self.ui.action_tray_enable = \
            QtGui.QAction("Enable / Disable", self)
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

    def _create_tabs(self, activate_tab=None):
        """Creates the tabs of the configuration dialog representing
        the different connected devices.
        """
        self.ui.devices.clear()
        self.tabs = {}

        # Device lists
        phys_devices = gremlin.joystick_handling.physical_devices()
        vjoy_devices = gremlin.joystick_handling.vjoy_devices()

        # Create physical joystick device tabs
        for device in sorted(phys_devices, key=lambda x: x.name):
            device_profile = self._profile.get_device_modes(
                device.device_guid,
                DeviceType.Joystick,
                device.name
            )
            

            widget = gremlin.ui.device_tab.JoystickDeviceTabWidget(
                device,
                device_profile,
                self.current_mode,
            )
            self.tabs[device.device_guid] = widget
            tab_label = device.name.strip()
            self.ui.devices.addTab(widget, tab_label)

        

        # Create vJoy as input device tabs
        for device in sorted(vjoy_devices, key=lambda x: x.vjoy_id):
            # Ignore vJoy as output devices
            if not self._profile.settings.vjoy_as_input.get(device.vjoy_id, False):
                continue

            device_profile = self._profile.get_device_modes(
                device.device_guid,
                DeviceType.Joystick,
                device.name
            )

            widget = gremlin.ui.device_tab.JoystickDeviceTabWidget(
                device,
                device_profile,
                self.current_mode
            )
            self.tabs[device.device_guid] = widget
            tab_label = device.name.strip()
            tab_label += f" #{device.vjoy_id:d}"
            self.ui.devices.addTab(widget, tab_label)

        # Create keyboard tab
        device_profile = self._profile.get_device_modes(
            dinput.GUID_Keyboard,
            DeviceType.Keyboard,
            DeviceType.to_string(DeviceType.Keyboard)
        )
        widget = gremlin.ui.keyboard_device.KeyboardDeviceTabWidget(
            device_profile,
            self.current_mode
        )
        self.tabs[dinput.GUID_Keyboard] = widget
        self.ui.devices.addTab(widget, "Keyboard")

        device_profile = self._profile.get_device_modes(
            gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid,
            DeviceType.Midi,
            DeviceType.to_string(DeviceType.Midi)
        )

        # Create MIDI tab
        widget = gremlin.ui.midi_device.MidiDeviceTabWidget(
            device_profile,
            self.current_mode
        )
        self.tabs[gremlin.ui.midi_device.MidiDeviceTabWidget.device_guid] = widget
        self.ui.devices.addTab(widget, "MIDI")

        
        device_profile = self._profile.get_device_modes(
            gremlin.ui.osc_device.OscDeviceTabWidget.device_guid,
            DeviceType.Osc,
            DeviceType.to_string(DeviceType.Osc)
        )

        # Create OSC tab
        widget = gremlin.ui.osc_device.OscDeviceTabWidget(
            device_profile,
            self.current_mode
        )
        self.tabs[gremlin.ui.osc_device.OscDeviceTabWidget.device_guid] = widget
        self.ui.devices.addTab(widget, "OSC")

        # Create the vjoy as output device tab
        for device in sorted(vjoy_devices, key=lambda x: x.vjoy_id):
            # Ignore vJoy as input devices
            if self._profile.settings.vjoy_as_input.get(device.vjoy_id, False):
                continue

            device_profile = self._profile.get_device_modes(
                device.device_guid,
                DeviceType.VJoy,
                device.name
            )

            widget = gremlin.ui.device_tab.JoystickDeviceTabWidget(
                device,
                device_profile,
                self.current_mode
            )
            self.tabs[device.device_guid] = widget
            self.ui.devices.addTab(widget,f"{device.name} #{device.vjoy_id:d}")

        # Add profile configuration tab
        widget = gremlin.ui.profile_settings.ProfileSettingsWidget(
            self._profile.settings
        )
        widget.changed.connect(lambda: self._create_tabs("Settings"))
        self.ui.devices.addTab(widget, "Settings")

        # Add a custom modules tab
        self.mm = gremlin.ui.user_plugin_management.ModuleManagementController(
            self._profile
        )
        self.ui.devices.addTab(self.mm.view, "Plugins")

        # Select specified tab if one is selected
        if activate_tab is not None:
            for i in range(self.ui.devices.count()):
                if self.ui.devices.tabText(i) == activate_tab:
                    with QtCore.QSignalBlocker(self.ui.devices):
                        self.ui.devices.setCurrentIndex(i)

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

        icon = load_icon("gfx/calibration.svg")
        self.ui.actionCalibration.setIcon(icon)
            
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
        

    # +---------------------------------------------------------------
    # | Signal handlers
    # +---------------------------------------------------------------

    
    def _device_change_cb(self):
        """Handles addition and removal of joystick devices."""
        # Update device tabs
        
        if not self.device_change_locked:
            verbose = gremlin.config.Configuration().verbose
            try:
                if verbose:
                   logging.getLogger("system").info(f"Device change begin") 
                self.device_change_locked = True
                self.devices = gremlin.joystick_handling.joystick_devices()
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
            
        
            

    

    def _process_joystick_input_selection(self, event, buttons_only = False):
        """Handles joystick events to select the appropriate input item for device highligthing in the UI

        :param event the event to process
        """

        
        if self.locked:
            return

        verbose = gremlin.config.Configuration().verbose_mode_inputs

        # enter critical section
        try:

            self.locked = True

            if event.event_type == InputType.Keyboard:
                # ignore keyboard inputs
                return
            if self.runner.is_running() or self.current_mode is None:
                return
            if gremlin.shared_state.suspend_input_highlighting():
                return
            

            # Get device id of the event and check if this matches the currently
            if event.device_guid not in self.tabs:
                return

            config = self.config # gremlin.config.Configuration()
            
        
            # Switch to the tab corresponding to the event's device if the option
            tab_switch_needed = self.ui.devices.currentWidget() != self.tabs[event.device_guid] 
            device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid)
            if verbose and tab_switch_needed:
                logging.getLogger("system").info(f"Event: tab switch requested to: {device_name}/{event.device_guid}")

            # prevent spamming tab switches by constant varying inputs
            if tab_switch_needed:
                if self._last_tab_switch is not None and (self._last_tab_switch + self._input_delay) > time.time():
                    if verbose:
                        logging.getLogger("system").info(f"Event: tab switch ignored - events too close")
                    return
                # remember the switch time for next request            
                self._last_tab_switch = time.time()
                        
            # get the widget for the tab corresponding to the device
            widget = self.tabs[event.device_guid] 
            if not isinstance(widget, gremlin.ui.device_tab.JoystickDeviceTabWidget):
                if verbose:
                    logging.getLogger("system").error(f"Event: unable to find tab widget for: {device_name}/{event.device_guid}")
                return


            # prevent switching based on user options
            if not config.highlight_input and event.event_type == InputType.JoystickAxis:
                # ignore axis input
                if verbose:
                    logging.getLogger("system").info(f"Event: highlight axis input ignored (option off)")
                return
            if not config.highlight_input_buttons and event.event_type == InputType.JoystickButton:
                # ignore button input
                if verbose:
                    logging.getLogger("system").info(f"Event: highlight button input ignored (option off)")
                return        


            process_input = tab_switch_needed or self._should_process_input(event, widget, buttons_only)
            if verbose:
                logging.getLogger("system").info(f"Event: process input {'ok' if process_input else 'ignored'}")
            
            if not process_input:
                return


            if config.highlight_device and tab_switch_needed:
                if verbose:
                    logging.getLogger("system").info(f"Event: execute tab switch begin")
                self.ui.devices.setCurrentWidget(self.tabs[event.device_guid])
                self.refresh()
                if verbose:
                    logging.getLogger("system").info(f"Event: execute tab switch complete ")


            

            # If we want to act on the given event figure out which button
            # needs to be pressed and press ii
            widget.input_item_list_view.select_item(event)
            #syslog.debug(f"selecting input") # {event.input_type} {event.action_id}")
            index = widget.input_item_list_view.current_index
            widget.input_item_list_view.redraw_index(index)

        finally:
            if verbose:
                logging.getLogger("system").info(f"Event: done")
            self.locked = False
    


    def _joystick_input_selection(self, event):
        """Handles joystick events to select the appropriate input item. (buttons + axes)

        :param event the event to process
        """
        if self.config.highlight_input:
            self._process_joystick_input_selection(event, False)

    def _joystick_input_button_selection(self, event):
        """Handles joystick events to select the appropriate input item. (buttons only)

        :param event the event to process
        """
        if self.config.highlight_input_buttons:
            self._process_joystick_input_selection(event, True)


    def _edit_mode_changed_cb(self, new_mode):
        """Updates the current mode to the provided one.

        :param new_mode the name of the new current mode
        """
        if self.current_mode != new_mode:
            # change the profile if different 
            eh = gremlin.event_handler.EventHandler()
            eh.change_mode(new_mode)

    

    def _process_changed_cb(self, path):
        """Handles changes in the active process.

        If the active process has a known associated profile it is
        loaded and activated. If none exists and the user has not
        enabled the option to keep the last profile active, the current
        profile is disabled,

        :param path the path to the currently active process executable
        """

        config = gremlin.config.Configuration()

        # if gremlin.shared_state.is_running and not config.runtime_ui_update:
        #     # ignore updates when running a profile unless the UI should be updated
        #     return 

        # check options
        option_auto_load = config.autoload_profiles  
        option_auto_load_on_focus = config.activate_on_process_focus



        if not option_auto_load and not option_auto_load_on_focus:
            return # ignore if not auto loading profiles or auto activating on focus change

        option_restore_mode = config.restore_profile_mode_on_start or self._profile.get_restore_mode()
        option_keep_focus = config.keep_profile_active_on_focus_loss  
        option_reset_mode_on_process_activate = config.reset_mode_on_process_activate 
        eh = gremlin.event_handler.EventHandler()

        verbose = gremlin.config.Configuration().verbose
        # if verbose:
        #     logging.getLogger("system").info(f"PROC: Process focus change detected: {os.path.basename(path)}  autoload: {option_auto_load}  keep focus: {option_keep_focus} restore mode: {option_restore_mode}")

        # see if we have a mapping entry for this executable
        profile_item = self._profile_map.get_map(path)
        profile_path = profile_item.profile if profile_item else None
        profile_change = False # assume no profile change
        #print (f"Profile: {profile_item}")
        mode = None # assume no mode change needed
        if profile_path:
            # profile entry found - see if we need to change profiles
            if not compare_path(self._profile_fname, profile_path):
                # change profile
                if verbose: 
                    logging.getLogger("system").info(f"PROC: process change forces a profile load: switch from {os.path.basename(self._profile_fname)} ->  {os.path.basename(profile_path)}")   
                self.ui.actionActivate.setChecked(False)
                self.activate(False)
                self._do_load_profile(profile_path)
                self.ui.actionActivate.setChecked(True)
                
                self._profile_auto_activated = True # remember the profile was auto activated by virtue of a process change
                profile_change = True

                # figure out which mode to restore mode for the new profile 
                if option_restore_mode:
                    # get the mode to restore
                    mode = self._profile.get_last_mode()
                    if verbose:
                        logging.getLogger("system").info(f"PROC: profile: '{os.path.basename(profile_path)}' restore last mode: '{mode}' ")     

            # see if we need to activate the profile 
            if option_auto_load_on_focus and not self.runner.is_running():
                self.ui.actionActivate.setChecked(True) # activate
                self._profile_auto_activated = True # remember the profile was auto activated by virtue of a process change
                if verbose:
                    logging.getLogger("system").info(f"PROC: profile: '{os.path.basename(profile_path)}' auto activate")

                if option_restore_mode:
                    # get the mode to restore
                    mode = self._profile.get_last_mode()
                    if verbose:
                        logging.getLogger("system").info(f"PROC: profile: '{os.path.basename(profile_path)}' restore last mode: '{mode}' ")


            # a mapping profile was found - new profile was loaded if needed - see if we need to change the mode
            reset_mode = (profile_change or option_reset_mode_on_process_activate and profile_item.default_mode)
            # print (f"reset mode: {reset_mode}  reset on activate: {option_reset_mode_on_process_activate}  profile mode: '{profile_item.default_mode}'  current mode: '{self.current_mode}'")
            if not mode and reset_mode:
                # use the default mode specified in the process mapping when changing profiles
                mode = profile_item.default_mode
                if verbose:
                    logging.getLogger("system").info(f"PROC: profile: '{os.path.basename(profile_path)}' using mapping startup mode: '{mode}' ")                    

            # see if the profile activation has a new mapping
            if mode is None or not mode in self._profile.get_modes():
                # restore the profile's default mode on activation
                mode = self._profile.get_default_mode()
                # if verbose:
                #     logging.getLogger("system").info(f"PROC: restoring default mode: '{mode}' ")                    

            if mode and mode != self.current_mode:
                eh = gremlin.event_handler.EventHandler()
                if verbose:
                    logging.getLogger("system").info(f"PROC: determined that mode should change to: '{mode}' ")                    
                eh.change_mode(mode) # set the selected mode
                
                if config.initial_load_mode_tts:
                    tts = gremlin.tts.TextToSpeech()              
                    tts.speak(f"Profile mode set to {mode}")


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
        self._update_status_bar_mode(gremlin.shared_state.current_mode)

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

            self.status_bar_is_active.setText(f"<b>Status:</b> {text_running} <b>Local Control</b> {local_msg} <b>Broadcast:</b> {remote_msg}")
        except e:
            log_sys_error(f"Unable to update status bar event: {event}")
            log_sys_error(e)

    def _update_status_bar_mode(self, new_mode):
        """ called when the profile mode changes 

        :param mode the now current mode
        """
        
        gremlin.shared_state.current_mode = new_mode
        update = True
        is_running = gremlin.shared_state.is_running
        if is_running:
            update = self.config.runtime_ui_update
            
        if update:
            with QtCore.QSignalBlocker(self.mode_selector):
                for tab in self.tabs.values():
                    tab.set_mode(new_mode)

        
        
        # update the status bar on mode change
        try:
            self.status_bar_mode.setVisible(is_running)
            self.status_bar_mode.setText(f"<b>Mode:</b> {new_mode if new_mode else "n/a"}")
            if self.config.mode_change_message:
                self.ui.tray_icon.showMessage(f"Mode: {new_mode if new_mode else "n/a"}","",QtWidgets.QSystemTrayIcon.MessageIcon.NoIcon,250)
        except Exception as err:
            log_sys_error(f"Unable to update status bar mode: {new_mode}:\n{err}")


    def _kb_event_cb(self, event):
        ''' listen for keyboard modifiers and keyboard events at runtime '''

        key = gremlin.keyboard.KeyMap.from_event(event)

        # ignore if we're running
        if key is None or self.runner.is_running() or gremlin.shared_state.ui_keyinput_suspended():
            return
        


        if (self.config.highlight_input or self.config.highlight_input_buttons):
            if key.lookup_name == "leftshift":
                if event.is_pressed:
                    # temporarily force the listening to joystick axes changes
                    self._set_joystick_input_highlighting(True)
                    if not self._temp_input_axis_override:
                        self._input_delay = 0 # eliminate delay in processing when triggering this so it switches immediately
                        self._temp_input_axis_override = True
                else:
                    self._set_joystick_input_highlighting(self.config.highlight_input)
                    self._temp_input_axis_override = False
            
            elif key.lookup_name == "leftcontrol":
                # temporarily force the listening to joystick axes changes
                self._temp_input_axis_only_override = event.is_pressed
            
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
        self._set_joystick_input_highlighting(
            self.config.highlight_input
        )
        self._set_joystick_input_buttons_highlighting(self.config.highlight_input_buttons)
        if not ignore_minimize:
            self.setHidden(self.config.start_minimized)
        if self.config.autoload_profiles:
            self.process_monitor.start()
        else:
            self.process_monitor.stop()

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
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save cheatsheet",
            gremlin.util.userprofile_path(),
            "PDF files (*.pdf)"
        )
        if len(fname) > 0:
            gremlin.cheatsheet.generate_cheatsheet(fname, self._profile)

    def _create_load_profile_function(self, fname):
        """Creates a callback to load a specific profile.

        :param fname path to the profile to load
        :return function which will load the specified profile
        """
        return lambda: self._load_recent_profile(fname)

    def _do_load_profile(self, fname):
        """Load the profile with the given filename.

        :param fname the name of the profile file to load
        """
        # Disable the program if it is running when we're loading a
        # new profile
        self.ui.actionActivate.setChecked(False)
        self.activate(False)

        # Attempt to load the new profile
        try:
            new_profile = gremlin.base_profile.Profile()
            profile_updated = new_profile.from_xml(fname)

            profile_folder = os.path.dirname(fname)
            if profile_folder not in sys.path:
                sys.path = list(self._base_path)
                sys.path.insert(0, profile_folder)

            self._sanitize_profile(new_profile)
            self._profile = new_profile
            self._profile_fname = fname
            self._update_window_title()
            gremlin.shared_state.current_profile = self._profile
            current_mode = sorted(self._profile.get_root_modes())[0]
            gremlin.shared_state.current_mode = current_mode
            self._create_tabs()

            # Make the first root node the default active mode
            self.mode_selector.populate_selector(self._profile, current_mode)

            # Save the profile at this point if it was converted from a prior
            # profile version, as otherwise the change detection logic will
            # trip over insignificant input item additions.
            if profile_updated:
                self._profile.to_xml(fname)


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
        if device.device_guid in self._profile.devices:
            device_profile = self._profile.devices[device.device_guid]
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
        if self._profile.empty():
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

            response = message_box.exec()
            if response == QtWidgets.QMessageBox.StandardButton.Save:
                self.save_profile()
            elif response == QtWidgets.QMessageBox.StandardButton.Cancel:
                continue_process = False
        return continue_process

    def _has_profile_changed(self):
        """Returns whether or not the profile has changed.

        :return True if the profile has changed, false otherwise
        """
        if self._profile_fname is None:
            return True
        else:
            tmp_path = os.path.join(os.getenv("temp"), "gremlin.xml")
            self._profile.to_xml(tmp_path)
            current_sha = hashlib.sha256(
                open(tmp_path).read().encode("utf-8")
            ).hexdigest()
            profile_sha = hashlib.sha256(
                open(self._profile_fname).read().encode("utf-8")
            ).hexdigest()

            return current_sha != profile_sha

    def _last_active_mode(self):
        """Returns the name of the mode last active.

        :return name of the mode that was the last to be active, or the
            first top level mode if none was ever used before
        """
        last_mode = self.config.get_last_mode(self._profile_fname)
        mode_list = gremlin.profile.mode_list(self._profile)

        if last_mode in mode_list:
            return last_mode
        else:
            return sorted(self._profile.build_inheritance_tree().keys())[0]
        
    

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

    def _mode_configuration_changed(self):
        """Updates the mode configuration of the selector and profile."""
        self.mode_selector.populate_selector(self._profile,gremlin.shared_state.current_mode)
        self.ui.devices.widget(self.ui.devices.count()-1).refresh_ui()

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
        if is_enabled:
            el.joystick_event.connect(self._joystick_input_selection)
        else:
            try: 
                el.joystick_event.disconnect(self._joystick_input_selection)
            except (TypeError, RuntimeError):  # pragma: no cover 
                pass             


    def _set_joystick_input_buttons_highlighting(self, is_enabled):
        """Enables / disables the highlighting of the current input button when used.

        :param is_enabled if True the input highlighting is enabled and
            disabled otherwise
        """
        el = gremlin.event_handler.EventListener()
        if is_enabled:
            el.joystick_event.connect(self._joystick_input_button_selection)
        else:
            try: 
                el.joystick_event.disconnect(self._joystick_input_button_selection)
            except (TypeError, RuntimeError):  # pragma: no cover 
                pass 


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

        # minimum deviation to look for for an axis 
        deviation = 0.1 if is_running else 0.5

        if is_running:
            return False
       
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


            # Check if we should actually react to the event
            if event == self._last_input_event:
                return False
            
       
        process_input = False

        if event.event_type == InputType.JoystickAxis:
            # only worry about axis deviation delta if it's an axis

            if buttons_only and not self.input_axis_override:
                # ignore axis changes if in button only mode and not overriding
                #syslog.debug("process: axis input: ignored")
                return False
            
            if not self._last_input_event:
                # always process a new input if never processed
                #syslog.debug("process: new event: processed")
                process_input = True
            else:
                # force a switch if the input has changed
                is_new_device = self._last_input_event.identifier != event.identifier or self._last_input_event.device_guid != event.device_guid
                process_input = process_input or is_new_device

            process_input = process_input or gremlin.input_devices.JoystickInputSignificant().should_process(event, deviation) 
            

            self._input_delay = 1

            if process_input:
                if self._last_input_timestamp + self._input_delay > time.time():
                    # delay not occured yet
                    process_input = False
                    #syslog.debug("process: delay ignore")


        else:
            process_input = True
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
        self.status_bar_repeater.setText(
            "<b>Repeater: </b> {}".format(text)
        )

    def _update_window_title(self):
        """Updates the window title to include the current profile."""
        if self._profile_fname is not None:
            self.setWindowTitle(f"{os.path.basename(self._profile_fname)}")
        else:
            self.setWindowTitle("")




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


    # Path manging to ensure Gremlin starts independent of the CWD
    sys.path.insert(0, gremlin.util.userprofile_path())
    gremlin.util.setup_userprofile()

    # Fix some dumb Qt bugs
    QtWidgets.QApplication.addLibraryPath(os.path.join(
        os.path.dirname(PySide6.__file__),
        "plugins"
    ))

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
    
    # handle windows themes better
    app.setStyle('Fusion')

    # Ensure joystick devices are correctly setup
    dinput.DILL.init()
    time.sleep(0.25)
    gremlin.joystick_handling.joystick_devices_initialization()

    # Check if vJoy is properly setup and if not display an error
    # and terminate GremlinEx
    try:
        syslog.info("Checking vJoy installation")
        vjoy_count = len([dev for dev in gremlin.joystick_handling.joystick_devices() if dev.is_virtual])
        vjoy_working = vjoy_count != 0
        logging.getLogger("system").info(f"\tFound {vjoy_count} vjoy device(s)")

        if not vjoy_working:
            logging.getLogger("system").error(
                "vJoy is not present or incorrectly setup."
            )
            raise gremlin.error.GremlinError(
                "vJoy is not present or incorrectly setup."
            )
        
        

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
        event_listener = gremlin.event_handler.EventListener()
        event_listener.terminate()
        sys.exit(0)

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

    # Run UI
    syslog.info("GremlinEx UI launching")
    app.exec()
    syslog.info("GremlinEx UI terminated")

    # Terminate potentially running EventListener loop
    event_listener = gremlin.event_handler.EventListener()
    event_listener.terminate()

    if vjoy_working:
        # Properly terminate the runner instance should it be running
        ui.runner.stop()

    # Relinquish control over all VJoy devices used
    gremlin.joystick_handling.VJoyProxy.reset()

    hg.remove_process(os.getpid())

    syslog.info("Terminating GremlinEx")
    sys.exit(0)



