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

import os
import shutil
import subprocess
import sys
import winreg

from PySide6 import QtCore, QtGui, QtWidgets

import dinput

import gremlin
from PySide6.QtGui import QIcon as load_icon
from PySide6.QtWidgets import QMessageBox
from gremlin.clipboard import Clipboard
import gremlin.config
import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.types
import gremlin.ui
import gremlin.ui.ui_common

import gremlin.ui.ui_about as ui_about
import gremlin.ui.ui_common as ui_common

from gremlin.util import load_icon, userprofile_path, load_pixmap, pushCursor, popCursor
import logging
from gremlin.input_types import InputType
import gremlin.base_profile
import uuid
from lxml import etree
import dinput
import gremlin.util

class ProfileOptionsUi(QtWidgets.QDialog):
    """UI to set individual profile settings """
    start_mode_changed = QtCore.Signal(str)  # when the start mode changes

    def __init__(self, parent=None):
        super().__init__(parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        min_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Minimum
        )
        exp_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Minimum
        )

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()
        self.setMinimumWidth(400)

        self.mode_list = []
        self.profile = gremlin.shared_state.current_profile

        self.setWindowTitle("Profile Options")

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.numlock_widget = QtWidgets.QCheckBox("Force numlock off on profile start")
        self.numlock_widget.setToolTip("When enabled, the numlock key will be turned off when the profile (re)activates - this avoids issue with keylatching for the numeric keypad")
        self.numlock_widget.setChecked(self.profile.get_force_numlock())
        self.numlock_widget.clicked.connect(self._numlock_force_cb)

        self.profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self.start_label = QtWidgets.QLabel("Start Mode")
        self.start_label.setSizePolicy(min_min_sp)
        self.start_mode_selector = gremlin.ui.ui_common.QComboBox()
        self.start_mode_selector.setSizePolicy(exp_min_sp)
        self.start_mode_selector.setMinimumContentsLength(20)
        self.start_mode_selector.setToolTip("Selects the startup mode when the profile is activated and the restore last mode option is not set")
        self.start_mode_selector.currentIndexChanged.connect(self._start_mode_changed_cb)
        self.start_container_widget = QtWidgets.QWidget()
        self.start_container_layout = QtWidgets.QHBoxLayout(self.start_container_widget)

        self.start_container_layout.addWidget(self.start_label)
        self.start_container_layout.addWidget(self.start_mode_selector)
        self.start_container_layout.addStretch()
        
        # Restore last mode on profile activate
        self.activate_restore_mode = QtWidgets.QCheckBox("Restore last mode on start")
        self.activate_restore_mode.clicked.connect(self._restore_mode_cb)
        self.activate_restore_mode.setChecked(self.profile.get_restore_mode())
        self.activate_restore_mode.setToolTip("""When set, the last mode used by this profile will be set whenever the profile is activated.""")

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self._close_cb)


        close_button_widget = QtWidgets.QWidget()
        close_button_layout = QtWidgets.QHBoxLayout(close_button_widget)
        close_button_layout.addStretch()
        close_button_layout.addWidget(self.close_button)

        self.main_layout.addWidget(self.numlock_widget)
        self.main_layout.addWidget(self.activate_restore_mode)
        self.main_layout.addWidget(self.start_container_widget)
        self.main_layout.addWidget(close_button_widget)

        self.populate_selector()

    def populate_selector(self):

        self.start_mode_selector.currentIndexChanged.disconnect(self._start_mode_changed_cb)
        while self.start_mode_selector.count() > 0:
            self.start_mode_selector.removeItem(0)

        start_mode = self.profile.get_start_mode()
        default_mode = self.profile.get_default_mode()
        if not start_mode in self.mode_list:
            # the start mode no longer exists - use the default mode
            logging.getLogger("system").warning(f"Specified start mode {start_mode} no longer exists - using default mode {default_mode}")
            default_mode = self.profile.get_default_mode()
            start_mode = default_mode
            self.profile.set_start_mode(default_mode)

        mode_list = gremlin.ui.ui_common.get_mode_list(gremlin.shared_state.current_profile)
        index = 0
        current_index = 0
        self.mode_list = []
        for display_name, mode_name in mode_list:
            self.start_mode_selector.addItem(display_name, mode_name)
            if mode_name == start_mode:
                current_index = index
            self.mode_list.append(mode_name)
            index +=1
        
        self.start_mode_selector.setCurrentIndex(current_index)

        self.start_mode_selector.currentIndexChanged.connect(self._start_mode_changed_cb)

    @QtCore.Slot(bool)
    def _numlock_force_cb(self, checked):
        self.profile.set_force_numlock(checked)


    @QtCore.Slot(bool)
    def _restore_mode_cb(self, checked):
        self.profile.set_restore_mode(checked)

    def _close_cb(self):
        self.close()



    @QtCore.Slot(int)
    def _start_mode_changed_cb(self, index):
        mode_name = self.mode_list[index]
        self.profile.set_start_mode(mode_name)
        self.start_mode_changed.emit(mode_name)



class OptionsUi(ui_common.BaseDialogUi):

    """UI allowing the configuration of a variety of options."""

    queue_refresh = QtCore.Signal() # refresh request

    def __init__(self, parent=None):
        """Creates a new options UI instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()
        self.setMinimumWidth(400)

        self.setWindowTitle("Options")

        self.main_layout = QtWidgets.QGridLayout(self)
        self.tab_container = QtWidgets.QTabWidget()
        self.main_layout.addWidget(self.tab_container,0,0)
        
        self.closed.connect(self._save_on_close_cb)
        
        self._create_general_page()
        self._create_profile_page()

        # do not create the page for now as this serves no purpose with new version of HID guardian
        # self._create_hidguardian_page()

        # closing bar
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.close)
        self.main_layout.addWidget(close_button,1,0)

        # select the last used tab
        index = self.config.last_options_tab
        if index != self.tab_container.currentIndex():
            self.tab_container.setCurrentIndex(index)

        self.queue_refresh.connect(self.populate_map)

        self.tab_container.currentChanged.connect(self._tab_changed_cb)

    def confirmClose(self, event):
        ''' override ability to close '''
        import gremlin.util
        self._profile_mapper.validate()
        if self._profile_mapper.valid:
            event.accept()
        else:
            
            # set the tab to the proper item

            # update the map with the errors
            self.populate_map()

            index = 1 # profile tab
            if index != self.tab_container.currentIndex():
                self.tab_container.setCurrentIndex(index)
            # display a message box
            message_box = QtWidgets.QMessageBox()
            message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            message_box.setText("Configuration Error")
            message_box.setInformativeText("The configuration is invalid.<br/>Press cancel to return,<br>or discard to remove the invalid entries.")
            message_box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Cancel |
                QtWidgets.QMessageBox.StandardButton.Discard
            )
            gremlin.util.centerDialog(message_box)
            result = message_box.exec()
            if result == QtWidgets.QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()

        
            

    def _save_on_close_cb(self):
        ''' occurs when the dialog is closed - autosave '''
        self._save_map_cb()
        eh = gremlin.event_handler.EventListener()
        eh.config_changed.emit()


    def _tab_changed_cb(self, new_index):
        ''' occurs on tab change, save the last used tab index so we can restore it later '''
        self.config.last_options_tab = new_index


    def _create_general_page(self):
        """Creates the general options page."""
        self.general_page = QtWidgets.QWidget()
        self.general_layout = QtWidgets.QVBoxLayout()
        self.general_page.setLayout(self.general_layout)

        # highlight autoswitch
        self.highlight_autoswitch = QtWidgets.QCheckBox(
            "Switch to new device on input highlight trigger"
        )
        self.highlight_autoswitch.clicked.connect(self._highlight_autoswitch)
        self.highlight_autoswitch.setChecked(self.config.highlight_autoswitch)
        self.highlight_autoswitch.setToolTip("This option enables automatic device tab switching on device input triggers (physical hardware only)")

        # Highlight input option
        self.highlight_input_axis = QtWidgets.QCheckBox(
            "Highlight currently triggered axis"
        )
        self.highlight_input_axis.clicked.connect(self._highlight_input_axis)
        self.highlight_input_axis.setToolTip("This otion will enable automatic selection and highlighting of device inputs when they are triggered.")
        self.highlight_input_axis.setChecked(self.config.highlight_input_axis)

        # Highlight input option buttons
        self.highlight_input_buttons = QtWidgets.QCheckBox(
            "Highlight currently triggered button"
        )
        self.highlight_input_buttons.clicked.connect(self._highlight_input_buttons)
        self.highlight_input_buttons.setChecked(self.config.highlight_input_buttons)

        # Switch to highlighted device
        self.highlight_enabled = QtWidgets.QCheckBox("Highlight swaps device tabs")
        self.highlight_enabled.clicked.connect(self._highlight_enabled)
        self.highlight_enabled.setChecked(self.config.highlight_enabled)

        # Close to system tray option
        self.close_to_systray = QtWidgets.QCheckBox("Closing minimizes to system tray")
        self.close_to_systray.clicked.connect(self._close_to_systray)
        self.close_to_systray.setChecked(self.config.close_to_tray)

        # enable ui at runtime
        self.enable_ui_runtime = QtWidgets.QCheckBox("Keep UI enabled when profile is active")
        self.enable_ui_runtime.setToolTip("When enabled, the UI will remain interactable while a profile is running.<br>This can create conflicts if the profile or mode is changed while a profile is running,<b>use caution.</b>")
        self.enable_ui_runtime.setChecked(self.config.runtime_ui_active)
        self.enable_ui_runtime.clicked.connect(self._runtime_ui_active)


        self.debug_ui = QtWidgets.QCheckBox("Debug UI")
        self.debug_ui.setToolTip("Enabled additional diagnostics widgets on the UI - only use for troubleshooting/debug purposes<br>Restart required to take effect.")
        self.debug_ui.setChecked(self.config.debug_ui)
        self.debug_ui.clicked.connect(self._debug_ui)
        
        
        # synchronize action/container drop downs
        self.sync_last_selection = QtWidgets.QCheckBox("Sync action &amp; container selections")
        self.sync_last_selection.setToolTip("When enabled, action and container drop downs will remain synchronized with the last selected entry")
        self.sync_last_selection.setChecked(self.config.sync_last_selection)
        self.sync_last_selection.clicked.connect(self._sync_last_selection)
        

        # ignore device changes at runtime
        self.runtime_ignore_device_change = QtWidgets.QCheckBox("Ignore device change at runtime")
        self.runtime_ignore_device_change.setToolTip("When enabled, device connect/disconnects will be ignored at runtime")
        self.runtime_ignore_device_change.setChecked(self.config.runtime_ignore_device_change)
        self.runtime_ignore_device_change.clicked.connect(self._runtime_ignore_device_change)


        # Start minimized option
        self.start_minimized = QtWidgets.QCheckBox(
            "Start Joystick Gremlin Ex minimized"
        )
        self.start_minimized.clicked.connect(self._start_minimized)
        self.start_minimized.setChecked(self.config.start_minimized)

        # Start on user login
        self.start_with_windows = QtWidgets.QCheckBox(
            "Start Joystick Gremlin Ex with Windows"
        )
        self.start_with_windows.clicked.connect(self._start_windows)
        self.start_with_windows.setChecked(self._start_windows_enabled())

        # Persist clipboard to file (user profile)
        self.persist_clipboard = QtWidgets.QCheckBox(
            "Persist clipboard data between sessions"
        )
        self.persist_clipboard.clicked.connect(self._persist_clipboard)
        self.persist_clipboard.setChecked(self._persist_clipboard_enabled())

        # show scan codes
        self.show_scancodes_widget = QtWidgets.QCheckBox("Show keyboard scancodes for keyboard inputs")
        self.show_scancodes_widget.setToolTip("When enabled, keyboard hexadecimal scan codes will be displayed in the keyboard input UI")
        self.show_scancodes_widget.setChecked(self.config.show_scancodes)
        self.show_scancodes_widget.clicked.connect(self._show_scancodes_cb)

        # show scan codes
        self.show_joystick_input_widget = QtWidgets.QCheckBox("Show live joystick inputs")
        self.show_joystick_input_widget.setToolTip("When enabled, current state of hardware inputs will be displayed in the UI")
        self.show_joystick_input_widget.setChecked(self.config.show_input_axis)
        self.show_joystick_input_widget.clicked.connect(self._show_joystick_input_cb)

        # allow partial plugin configurations
        self.partial_plugin_save = QtWidgets.QCheckBox("Save partial user plugin data")
        self.partial_plugin_save.setToolTip("When enabled, user-plugin configuration will be saved even if one or more input variable reports not-configured.<br>This feature allows saving of the configuration to date.<br>Incomplete configurations will not be activated at runtime even if this feature is used.")
        self.partial_plugin_save.setChecked(self.config.partial_plugin_save)
        self.partial_plugin_save.clicked.connect(self._partial_plugin_save)


        # verbose output
        self.verbose_container_widget = QtWidgets.QWidget()
        self.verbose_container_widget.setContentsMargins(0,0,0,0)
        self.verbose_container_layout = QtWidgets.QGridLayout()
        self.verbose_container_layout.setContentsMargins(0,0,0,0)
        self.verbose_container_widget.setLayout(self.verbose_container_layout)

        self.verbose_widget = QtWidgets.QCheckBox("Verbose log")
        verbose = self.config.verbose
        self.verbose_widget.setChecked(verbose)
        self.verbose_widget.clicked.connect(self._verbose_cb)

        self._verbose_mode_widgets = {}
        row = 0
        col = 1
        self.verbose_container_layout.addWidget(self.verbose_widget,0,0)
        for mode in gremlin.types.VerboseMode:
            if mode in (gremlin.types.VerboseMode.NotSet, gremlin.types.VerboseMode.All):
                continue
            widget = ui_common.QDataCheckbox(mode.name, mode)
            is_checked = self.config.is_verbose_mode(mode)
            widget.setChecked(is_checked)
            widget.clicked.connect(self._verbose_set_cb)
            self.verbose_container_layout.addWidget(widget, row, col)
            col += 1
            if col > 2:
                col = 1
                row +=1
            self._verbose_mode_widgets[mode] = widget



        # midi enabled
        self.osc_enabled = QtWidgets.QCheckBox("Enable OSC input")
        self.osc_enabled.clicked.connect(self._osc_enabled)
        self.osc_enabled.setChecked(self.config.osc_enabled)
        self.osc_enabled.setToolTip("When set, Joystick Gremlin Ex will listen to OSC network traffic on the specified port when a profile is activated.")

        self.osc_port = QtWidgets.QSpinBox()
        self.osc_port.setRange(4096,65535)
        self.osc_port.setEnabled(self.config.osc_enabled)
        port = self.config.osc_port
        self.osc_port.setValue(port)
        self.osc_port.valueChanged.connect(self._osc_port)


        # midi enabled
        self.midi_enabled = QtWidgets.QCheckBox("Enable MIDI input")
        self.midi_enabled.clicked.connect(self._midi_enabled)
        self.midi_enabled.setChecked(self.config.midi_enabled)
        self.midi_enabled.setToolTip("When set, Joystick Gremlin Ex will listen to MIDI ports when a profile is activated.")

        # Show message on mode change
        self.show_mode_change_message = QtWidgets.QCheckBox("Show message when changing mode")
        self.show_mode_change_message.clicked.connect(
            self._show_mode_change_message
        )
        self.show_mode_change_message.setChecked(self.config.mode_change_message)

        # remote control section
        self.remote_control_widget = QtWidgets.QWidget()
        self.remote_control_widget.setContentsMargins(0,0,0,0)
        self.remote_control_layout = QtWidgets.QHBoxLayout(self.remote_control_widget)
        self.remote_control_layout.setContentsMargins(0,0,0,0)

        self.remote_control_label = QtWidgets.QLabel("Remote control")

        self.enable_remote_control = QtWidgets.QCheckBox("Enable remote control")
        self.enable_remote_control.setChecked(self.config.enable_remote_control)
        self.enable_remote_control.clicked.connect(self._enable_remote_control)
        self.enable_remote_control.setToolTip("When set, Joystick Gremlin Ex will enable the remote control feature.  This allows this instance of JGEX to control the master instance on another network computer.")


        self.enable_remote_broadcast = QtWidgets.QCheckBox("Enable broadcast")
        self.enable_remote_broadcast.setChecked(self.config.enable_remote_broadcast)
        self.enable_remote_broadcast.clicked.connect(self._enable_remote_broadcast)
        self.enable_remote_control.setToolTip("When set, Joystick Gremlin Ex will enable the remote broadcast feature.  This allows this instance of JGEX to broadcast control messages to other instances on the network.")


        self.enable_broadcast_speech = QtWidgets.QCheckBox("Enable speech on broadcast mode change")
        self.enable_broadcast_speech.setChecked(self.config.enable_broadcast_speech)
        self.enable_broadcast_speech.clicked.connect(self._enable_broadcast_speech)
        self.enable_remote_control.setToolTip("When set, Joystick Gremlin Ex will voice a enable the remote control feature.  This allows JGEX to output an audio cue when the broadcast mode is changed, which can be changed by an action.")

        self.remote_control_label = QtWidgets.QLabel("Port:")

        self.remote_control_port = QtWidgets.QDoubleSpinBox()
        self.remote_control_port.setRange(4096,65535)
        self.remote_control_port.setDecimals(0)
        self.remote_control_port.setValue(float(self.config.server_port))
        self.remote_control_port.valueChanged.connect(self._remote_control_server_port)
        self.remote_control_port.setToolTip("This specifies the UDP port used to communicate with other Joystick Gremlin Ex instances on the network.  The local firewall must allow the ports to broadcast.  The +1 port is used to receive messages.")


        self.remote_control_layout.addWidget(self.enable_remote_control)
        self.remote_control_layout.addWidget(self.enable_remote_broadcast)
        self.remote_control_layout.addWidget(self.remote_control_label)
        self.remote_control_layout.addWidget(self.remote_control_port)
        self.remote_control_layout.addStretch()








        # Default action selection
        self.default_action_widget = QtWidgets.QWidget()
        self.default_action_widget.setContentsMargins(0,0,0,0)
        self.default_action_layout = QtWidgets.QHBoxLayout(self.default_action_widget)
        self.default_action_layout.setContentsMargins(0,0,0,0)
        

        self.default_action_label = QtWidgets.QLabel("Default action")
        self.default_action_dropdown = gremlin.ui.ui_common.QComboBox()
        self.default_action_layout.addWidget(self.default_action_label)
        self.default_action_layout.addWidget(self.default_action_dropdown)
        self._init_action_dropdown()
        self.default_action_layout.addStretch()

        # Macro axis polling rate
        self.macro_axis_polling_widget = QtWidgets.QWidget()
        self.macro_axis_polling_widget.setContentsMargins(0,0,0,0)
        self.macro_axis_polling_layout = QtWidgets.QHBoxLayout(self.macro_axis_polling_widget)
        self.macro_axis_polling_layout.setContentsMargins(0,0,0,0)

        self.macro_axis_polling_label = QtWidgets.QLabel("Macro axis polling rate")
        self.macro_axis_polling_value = ui_common.DynamicDoubleSpinBox()
        self.macro_axis_polling_value.setRange(0.001, 1.0)
        self.macro_axis_polling_value.setSingleStep(0.05)
        self.macro_axis_polling_value.setDecimals(3)
        self.macro_axis_polling_value.setValue(
            self.config.macro_axis_polling_rate
        )
        self.macro_axis_polling_value.valueChanged.connect(
            self._macro_axis_polling_rate
        )
        self.macro_axis_polling_layout.addWidget(self.macro_axis_polling_label)
        self.macro_axis_polling_layout.addWidget(self.macro_axis_polling_value)
        self.macro_axis_polling_layout.addStretch()

        # Macro axis minimum change value
        self.macro_axis_minimum_change_widget = QtWidgets.QWidget()
        self.macro_axis_minimum_change_widget.setContentsMargins(0,0,0,0)
        self.macro_axis_minimum_change_layout = QtWidgets.QHBoxLayout(self.macro_axis_minimum_change_widget)
        self.macro_axis_minimum_change_layout.setContentsMargins(0,0,0,0)

        self.macro_axis_minimum_change_label = QtWidgets.QLabel("Macro axis minimum change value")
        self.macro_axis_minimum_change_value = ui_common.DynamicDoubleSpinBox()
        self.macro_axis_minimum_change_value.setRange(0.00001, 1.0)
        self.macro_axis_minimum_change_value.setSingleStep(0.01)
        self.macro_axis_minimum_change_value.setDecimals(5)
        self.macro_axis_minimum_change_value.setValue(self.config.macro_axis_minimum_change_rate)
        self.macro_axis_minimum_change_value.valueChanged.connect(self._macro_axis_minimum_change_value)
        self.macro_axis_minimum_change_layout.addWidget(self.macro_axis_minimum_change_label)
        self.macro_axis_minimum_change_layout.addWidget(self.macro_axis_minimum_change_value)
        self.macro_axis_minimum_change_layout.addStretch()


        self.runtime_ui_update = QtWidgets.QCheckBox("Update UI when profile is active")
        self.runtime_ui_update.setChecked(self.config.runtime_ui_update)
        self.runtime_ui_update.clicked.connect(self._runtime_ui_update)
        self.runtime_ui_update.setToolTip("When set, Joystick Gremlin Ex will update the UI on profile or mode changes at runtime - this can be turned off to enhance performance at runtime")


        # gamepad device count
        self.gamepad_container_widget = QtWidgets.QWidget()
        self.gamepad_container_widget.setContentsMargins(0,0,0,0)
        self.gamepad_container_layout = QtWidgets.QHBoxLayout(self.gamepad_container_widget)
        self.gamepad_container_layout.setContentsMargins(0,0,0,0)
        self.gamepad_device_count_widget = QtWidgets.QSpinBox()
        self.gamepad_device_count_widget.setRange(0,4) # 0 (none), 1 to 4 devices
        self.gamepad_device_count_widget.setValue(self.config.vigem_device_count)
        self.gamepad_device_count_widget.setToolTip("Number of virtual gamepad devices to create, 0 for none, 1 to 4")
        self.gamepad_device_count_widget.valueChanged.connect(self._device_count_changed)
        self.gamepad_container_layout.addWidget(QtWidgets.QLabel("Gamepad count:"))
        self.gamepad_container_layout.addWidget(self.gamepad_device_count_widget)
        self.gamepad_container_layout.addStretch()


        self.column_widget = QtWidgets.QWidget()
        self.column_widget.setContentsMargins(0,0,0,0)
        self.column_layout = QtWidgets.QGridLayout(self.column_widget)
        self.column_layout.setContentsMargins(0,0,0,0)


        # column 1
        col = 0
        row = 0
        self.column_layout.addWidget(self.highlight_autoswitch, row, col)
        row+=1
        self.column_layout.addWidget(self.highlight_input_axis, row, col)
        row+=1
        self.column_layout.addWidget(self.highlight_input_buttons, row, col)
        row+=1
        self.column_layout.addWidget(self.highlight_enabled, row, col)
        row+=1
        self.column_layout.addWidget(self.sync_last_selection, row, col)
        row+=1
        self.column_layout.addWidget(self.close_to_systray, row, col)
        row+=1
        self.column_layout.addWidget(self.enable_ui_runtime, row, col)
        row+=1
        self.column_layout.addWidget(self.start_minimized, row, col)
        row+=1
        self.column_layout.addWidget(self.start_with_windows, row, col)


        # column 2
        col = 1
        row = 0
        self.column_layout.addWidget(self.persist_clipboard, row, col)
        row+=1
        self.column_layout.addWidget(self.show_scancodes_widget, row, col)
        row+=1
        self.column_layout.addWidget(self.partial_plugin_save, row, col)
        row+=1
        self.column_layout.addWidget(self.show_joystick_input_widget, row, col)
        row+=1
        self.column_layout.addWidget(self.runtime_ui_update, row, col)
        row+=1
        self.column_layout.addWidget(self.midi_enabled, row, col)
        row+=1
        self.column_layout.addWidget(self.verbose_container_widget, row, col)
        row+=1
        self.column_layout.addWidget(self.runtime_ignore_device_change, row, col)
        row+=1
        self.column_layout.addWidget(self.debug_ui, row, col)

        self.general_layout.addWidget(self.column_widget)


        self.general_layout.addWidget(self.gamepad_container_widget)

        
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.addWidget(self.osc_enabled)
        layout.addWidget(QtWidgets.QLabel("Listen port number (outbound is +1)"))
        layout.addWidget(self.osc_port)
        layout.addStretch()
        layout.setContentsMargins(0,0,0,0)
        
        


        
        self.general_layout.addWidget(container)
        self.general_layout.addWidget(self.show_mode_change_message)
        self.general_layout.addWidget(self.default_action_widget)
        self.general_layout.addWidget(self.macro_axis_minimum_change_widget)
        self.general_layout.addWidget(self.remote_control_widget)
        self.general_layout.addWidget(self.enable_broadcast_speech)
        self.general_layout.addStretch()
        self.tab_container.addTab(self.general_page, "General")


    def _create_profile_page(self):
        """Creates the profile options page."""
        self.profile_page = QtWidgets.QWidget()
        self.profile_page_layout = QtWidgets.QGridLayout(self.profile_page)

        # holds the mapping of a process (.exe) to a profile (.xml)
        self._profile_mapper = gremlin.base_profile.ProfileMap()
        self._profile_map_exe_widgets = {}
        self._profile_map_xml_widgets = {}
        self._profile_map_mode_widgets = {}

        # Autoload profile option
        self.autoload_checkbox = QtWidgets.QCheckBox("Automatically load a mapped profile based on current application (process)")
        self.autoload_checkbox.clicked.connect(self._autoload_mapped_profile)
        self.autoload_checkbox.setChecked(self.config.autoload_profiles)
        self.autoload_checkbox.setToolTip("When set, GremlinEx will autoload and activate a mapped profile when in \"run\" mode")

        self.keep_active_on_focus_lost_checkbox = QtWidgets.QCheckBox("Keep profile active on focus loss")
        self.keep_active_on_focus_lost_checkbox.setToolTip("""If this option is set, the last active profile
will remain active until a different profile is loaded.""")
        self.keep_active_on_focus_lost_checkbox.clicked.connect(self._keep_focus)
        self.keep_active_on_focus_lost_checkbox.setChecked(self.config.keep_profile_active_on_focus_loss)
        self.keep_active_on_focus_lost_checkbox.setEnabled(self.config.autoload_profiles)

        self.keep_active_on_focus_lost_checkbox.setToolTip("When set, GremlinEx will keep the profile active when the target application loses focus (such as on alt-tab)")


        # Activate profile on launch
        self.activate_on_launch = QtWidgets.QCheckBox("Auto-Activate last profile on launch")
        self.activate_on_launch.clicked.connect(self._activate_on_launch)
        self.activate_on_launch.setChecked(self.config.activate_on_launch)
        self.activate_on_launch.setToolTip("When set, the last used profile will be automatically activated when GremlinEx starts.")

        self.activate_on_process_focus = QtWidgets.QCheckBox("Auto-Activate on profile focus")
        self.activate_on_process_focus.clicked.connect(self._activate_on_process_focus)
        self.activate_on_process_focus.setChecked(self.config.activate_on_process_focus)
        self.activate_on_process_focus.setEnabled(self.config.autoload_profiles)
        self.activate_on_process_focus.setToolTip("When set, Gremlin Ex will automatically load and activate a profile when a mapped profile receives the focus regardless of other options")

        # Restore last mode on profile activate
        self.activate_restore_mode = QtWidgets.QCheckBox("Restore last used mode on profile activation (global)")
        self.activate_restore_mode.clicked.connect(self._restore_profile_mode)
        self.activate_restore_mode.setChecked(self.config.restore_profile_mode_on_start)
        self.activate_restore_mode.setToolTip("""When set, activated profiles will use the last known mode the profile used. This is a global setting and overrides the per-profile option.
This setting is also available on a profile by profile basis on the profile tab, or in the modes editor.""")

        self.initial_load_mode_tts = QtWidgets.QCheckBox("Say active mode on profile activation via TTS")
        self.initial_load_mode_tts.setChecked(self.config.initial_load_mode_tts)
        self.initial_load_mode_tts.clicked.connect(self._initial_load_mode_tts)
        self.initial_load_mode_tts.setToolTip("""When set, GremlinEx will say that text-to-speech the profile mode whenever a profile is first loaded""")

        self.reset_mode_on_process_activate = QtWidgets.QCheckBox("Reset mode on process activation")
        self.reset_mode_on_process_activate.setChecked(self.config.reset_mode_on_process_activate)
        self.reset_mode_on_process_activate.clicked.connect(self._reset_mode_on_process_activate)
        self.reset_mode_on_process_activate.setToolTip("If set, the profile mode will be reset to the startup mode whenever the application has the focus")

        row = 0
        self.profile_page_layout.addWidget(self.autoload_checkbox,row,0)
        row+=1
        self.profile_page_layout.addWidget(self.keep_active_on_focus_lost_checkbox,row,0)
        row+=1
        self.profile_page_layout.addWidget(self.activate_on_process_focus,row,0)
        row+=1
        self.profile_page_layout.addWidget(self.activate_on_launch,row,0)
        row+=1
        self.profile_page_layout.addWidget(self.activate_restore_mode,row,0)
        row+=1
        self.profile_page_layout.addWidget(self.initial_load_mode_tts,row,0)
        row+=1
        self.profile_page_layout.addWidget(self.reset_mode_on_process_activate, row, 0)
        row+=1


        self.tab_container.addTab(self.profile_page, "Profiles")


        # profile map widgets
        self.container_map_widget = QtWidgets.QWidget()
        self.container_map_layout = QtWidgets.QVBoxLayout(self.container_map_widget)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        self.scroll_area.setMinimumWidth(300)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.map_widget = QtWidgets.QWidget()
        self.map_layout = QtWidgets.QGridLayout()
        self.map_layout.setContentsMargins(0,0,0,0)
        self.map_widget.setLayout(self.map_layout)

        self.scroll_layout.addWidget(self.map_widget)
        self.scroll_layout.setContentsMargins(6,0,6,0)
        self.scroll_layout.addStretch()
        self.container_map_layout.addWidget(self.scroll_area)

        container_bar_widget = QtWidgets.QWidget()
        container_bar_layout = QtWidgets.QHBoxLayout()
        container_bar_widget.setLayout(container_bar_layout)


        sort_profile_widget = QtWidgets.QPushButton("Sort Profile")
        sort_profile_widget.clicked.connect(self._sort_profile_cb)
        sort_profile_widget.setToolTip("Sorts mappings by profile")

        sort_process_widget = QtWidgets.QPushButton("Sort Process")
        sort_process_widget.clicked.connect(self._sort_process_cb)
        sort_process_widget.setToolTip("Sorts mappings by process")

        add_map_widget = QtWidgets.QPushButton("Add mapping")
        add_map_widget.setIcon(load_icon("gfx/button_add.png"))
        add_map_widget.clicked.connect(self._add_profile_map_cb)
        add_map_widget.setToolTip("Adds a new application (process) to profile mapping entry")

        self.profile_page_layout.addWidget(container_bar_widget, row, 0)
        row+=1
        container_bar_layout.addWidget(QtWidgets.QLabel("Process/Profile map:"))
        container_bar_layout.addStretch()

        container_bar_layout.addWidget(sort_profile_widget)
        container_bar_layout.addWidget(sort_process_widget)
        container_bar_layout.addWidget(add_map_widget)


        self.profile_page_layout.addWidget(container_bar_widget, row, 0 )
        row+=1
        self.profile_page_layout.addWidget(self.container_map_widget, row, 0)
        row+=1

        # force a data reload
        self._profile_mapper.load_profile_map()
        self.populate_map()


    def _create_hidguardian_page(self):
        self.hg_page = QtWidgets.QWidget()
        self.hg_page_layout = QtWidgets.QVBoxLayout(self.hg_page)

        # Display instructions for non admin users
        if not gremlin.util.is_user_admin():
            label = QtWidgets.QLabel(
                "In order to use HidGuardian to both specify the devices to "
                "hide via HidGuardian as well as have Gremlin see them, "
                "Gremlin has to be run as Administrator."
            )
            label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
            label.setWordWrap(True)
            label.setFrameShape(QtWidgets.QFrame.Box)
            label.setMargin(10)
            self.hg_page_layout.addWidget(label)

        else:
            # Get list of devices affected by HidGuardian
            hg = gremlin.hid_guardian.HidGuardian()
            hg_device_list = hg.get_device_list()

            self.hg_device_layout = QtWidgets.QGridLayout()
            self.hg_device_layout.addWidget(
                QtWidgets.QLabel("<b>Device Name</b>"), 0, 0
            )
            self.hg_device_layout.addWidget(
                QtWidgets.QLabel("<b>Hidden</b>"), 0, 1
            )

            devices = gremlin.joystick_handling.joystick_devices()
            devices_added = []
            for i, dev in enumerate(devices):
                # Don't add vJoy to this list
                if dev.name == "vJoy Device":
                    continue

                # For identical VID / PID devices only add one instance
                vid_pid_key = (dev.vendor_id, dev.product_id)
                if vid_pid_key in devices_added:
                    continue

                # Set checkbox state based on whether or not HidGuardian tracks
                # the device. Add a callback with pid/vid to add / remove said
                # device from the list of devices handled by HidGuardian
                self.hg_device_layout.addWidget(QtWidgets.QLabel(dev.name), i+1, 0)
                checkbox = QtWidgets.QCheckBox("")
                checkbox.setChecked(vid_pid_key in hg_device_list)
                checkbox.stateChanged.connect(self._create_hg_cb(dev))
                self.hg_device_layout.addWidget(checkbox, i+1, 1)
                devices_added.append(vid_pid_key)

            self.hg_page_layout.addLayout(self.hg_device_layout)

            self.hg_page_layout.addStretch()
            label = QtWidgets.QLabel(
                "After making changes to the devices hidden by HidGuardian "
                "the devices that should now be hidden or shown to other"
                "applications need to be unplugged and plugged back in for "
                "the changes to take effect."
            )
            label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
            label.setWordWrap(True)
            label.setFrameShape(QtWidgets.QFrame.Box)
            label.setMargin(10)
            self.hg_page_layout.addWidget(label)

        self.tab_container.addTab(self.hg_page, "HidGuardian")

    def closeEvent(self, event):
        """Closes the calibration window.

        :param event the close event
        """
        self.config.save()
        super().closeEvent(event)

    # def populate_executables(self, executable_name=None):
    #     """Populates the profile drop down menu.

    #     :param executable_name name of the executable to pre select
    #     """
    #     self.profile_field.textChanged.disconnect(self._update_profile)
    #     self.executable_selection.clear()
    #     executable_list = self.config.get_executable_list()
    #     for path in executable_list:
    #         self.executable_selection.addItem(path)
    #     self.profile_field.textChanged.connect(self._update_profile)

    #     # Select the provided executable if it exists, otherwise the first one
    #     # in the list
    #     index = 0
    #     if executable_name is not None and executable_name in executable_list:
    #         index = self.executable_selection.findText(executable_name)
    #     self.executable_selection.setCurrentIndex(index)

    # def _profile_restore_flag_cb(self, checked):
    #     ''' called when the restore last mode checked state is changed '''
    #     self.config.current_profile.set_restore_mode(checked)

    @QtCore.Slot(bool)
    def _autoload_mapped_profile(self, checked):
        """Stores profile autoloading preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.keep_active_on_focus_lost_checkbox.setEnabled(checked)
        self.activate_on_process_focus.setEnabled(checked)
        self.config.autoload_profiles = checked

    @QtCore.Slot(bool)
    def _keep_focus(self, checked):
        self.config.keep_profile_active_on_focus_loss = checked

    @QtCore.Slot(bool)
    def _activate_on_launch(self, checked):
        self.config.activate_on_launch = checked

    @QtCore.Slot(bool)
    def _activate_on_process_focus(self, checked):
        self.config.activate_on_process_focus = checked

    @QtCore.Slot(bool)
    def _runtime_ui_update(self, checked):
        self.config.runtime_ui_update = checked

    @QtCore.Slot(bool)
    def _restore_profile_mode(self, checked):
        self.config.restore_profile_mode_on_start = checked

    @QtCore.Slot(bool)
    def _initial_load_mode_tts(self, checked):
        self.config.initial_load_mode_tts = checked

    @QtCore.Slot(bool)
    def _reset_mode_on_process_activate(self, checked):
        self.config.reset_mode_on_process_activate = checked

    @QtCore.Slot(bool)
    def _close_to_systray(self, checked):
        """Stores closing to system tray preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.close_to_tray = checked

    @QtCore.Slot(bool)
    def _debug_ui(self, checked):
        self.config.debug_ui = checked

    @QtCore.Slot(bool)
    def _runtime_ui_active(self, checked):
        self.config.runtime_ui_active = checked

    @QtCore.Slot(bool)
    def _sync_last_selection(self, checked):
        self.config.sync_last_selection = checked

    @QtCore.Slot(bool)
    def _runtime_ignore_device_change(self, checked):
        self.config.runtime_ignore_device_change = checked


    @QtCore.Slot(bool)
    def _start_minimized(self, checked):
        """Stores start minimized preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.start_minimized = checked

    @QtCore.Slot(bool)
    def _persist_clipboard(self, checked):
        self.config.persist_clipboard = checked

    @QtCore.Slot(bool)
    def _persist_clipboard_enabled(self):
        return self.config.persist_clipboard
    
    @QtCore.Slot(bool)
    def _show_scancodes_cb(self, checked):
        self.config.show_scancodes = checked

    @QtCore.Slot(bool)
    def _show_joystick_input_cb(self, checked):
        self.config.show_input_axis = checked

    @QtCore.Slot(bool)
    def _partial_plugin_save(self, checked):
        self.config.partial_plugin_save = checked
    
    
    @QtCore.Slot(bool)
    def _verbose_cb(self, checked):
        ''' stores verbose setting '''
        self.config.verbose = checked
        for widget in self._verbose_mode_widgets.values():
            widget.setEnabled(checked)

    def _verbose_set_cb(self):
        # is_checked = self._verbose_mode_widgets[mode].isChecked()
        widget = self.sender()
        mode = widget.data
        is_checked = widget.isChecked()
        self.config.verbose_set_mode(mode, is_checked)

    @QtCore.Slot(bool)
    def _midi_enabled(self, checked):
        self.config.midi_enabled = checked

    @QtCore.Slot(bool)
    def _osc_enabled(self, checked):
        self.config.osc_enabled = checked
        self.osc_port.setEnabled(checked)


    def _osc_port(self):
        self.config.osc_port = self.osc_port.value()


    @QtCore.Slot(bool)
    def _start_windows(self, checked):
        """Set registry entry to launch Joystick Gremlin on login.

        :param clicked True if launch should happen on login, False otherwise
        """
        if checked:
            path = os.path.abspath(sys.argv[0])
            subprocess.run(
                f'reg add "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /V "Joystick Gremlin" /t REG_SZ /F /D "{path}"'
            )
        else:
            subprocess.run(
                'reg delete "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /F /V "Joystick Gremlin"'
            )
        self.activateWindow()

    def _start_windows_enabled(self):
        """Returns whether or not Gremlin should launch on login.

        :return True if Gremlin launches on login, False otherwise
        """
        key_handle = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                "Software\\Microsoft\\Windows\\CurrentVersion\\Run"
            )
        key_info = winreg.QueryInfoKey(key_handle)

        for i in range(key_info[1]):
            value_info = winreg.EnumValue(key_handle, i)
            if value_info[0] == "Joystick Gremlin":
                return True
        return False

    def _device_count_changed(self):
        self.config.vigem_device_count = self.gamepad_device_count_widget.value()


    @QtCore.Slot(bool)
    def _highlight_autoswitch(self, clicked):
        """Stores preference for input highlighting  """
        self.config.highlight_autoswitch = clicked




    @QtCore.Slot(bool)
    def _highlight_input_axis(self, clicked):
        """Stores preference for input highlighting.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.highlight_input_axis = clicked

    @QtCore.Slot(bool)
    def _highlight_input_buttons(self, clicked):
        """Stores preference for input highlighting (buttons).

        :param clicked whether or not the checkbox is ticked
        """
        self.config.highlight_input_buttons = clicked



    @QtCore.Slot(bool)
    def _highlight_enabled(self, clicked):
        """Stores preference for device highlighting.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.highlight_enabled = clicked
        self.config.save()

    def _select_profile(self):
        """Displays a file selection dialog for a profile.

        If a valid file is selected the mapping from executable to
        profile is updated.
        """
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Path to executable",
            gremlin.util.userprofile_path(),
            "Profile (*.xml)"
        )
        if fname != "":
            self.profile_field.setText(fname)
            self.config.set_profile(
                self.executable_selection.currentText(),
                self.profile_field.text()
            )

            self.queue_refresh.emit()

    def _show_executable(self, exec_path):
        """Displays the profile associated with the given executable.

        :param exec_path path to the executable to shop
        """
        self.profile_field.setText(self.config.get_profile(exec_path))

    @QtCore.Slot(bool)
    def _show_mode_change_message(self, clicked):
        """Stores the user's preference for mode change notifications.

        :param clicked whether or not the checkbox is ticked"""
        self.config.mode_change_message = clicked
        self.config.save()

    def _update_profile(self):
        """Updates the profile associated with the current executable."""
        self.config.set_profile(
            self.executable_selection.currentText(),
            self.profile_field.text()
        )
        self._profile_mapper.validate()

    def _init_action_dropdown(self):
        """Initializes the action selection dropdown menu."""
        plugins = gremlin.plugin_manager.ActionPlugins()

        for act in sorted(plugins.repository.values(), key=lambda x: x.name):
            self.default_action_dropdown.addItem(act.name)
        self.default_action_dropdown.setCurrentText(self.config.default_action)
        self.default_action_dropdown.currentTextChanged.connect(
            self._update_default_action
        )

    def _update_default_action(self, value):
        """Updates the config with the newly selected action name.

        :param value the name of the newly selected action
        """
        self.config.default_action = value
        self.config.save()


    def _enable_remote_control(self, clicked):
        ''' updates remote control flag '''
        self.config.enable_remote_control = clicked
        self.config.save()

    def _enable_remote_broadcast(self, clicked):
        ''' updates remote broadcast flag '''
        self.config.enable_remote_broadcast = clicked
        self.config.save()

    def _enable_broadcast_speech(self, clicked):
        self.config.enable_broadcast_speech = clicked
        self.config.save()

    def _remote_control_server_port(self, value):
        ''' updates the remote control server port'''
        self.config.server_port = value
        self.config.save()

    def _macro_axis_polling_rate(self, value):
        """Updates the config with the newly set polling rate.

        :param value the new polling rate
        """
        self.config.macro_axis_polling_rate = value
        self.config.save()

    def _macro_axis_minimum_change_value(self, value):
        """Updates the config with the newly set minimum change value.

        :param value the new minimum change value
        """
        self.config.macro_axis_minimum_change_rate = value

    def _create_hg_cb(self, *params):
        return lambda x: self._update_hg_device(x, *params)

    def _update_hg_device(self, state, device):
        hg = gremlin.hid_guardian.HidGuardian()
        if state == QtCore.Qt.Checked.value:
            hg.add_device(device.vendor_id, device.product_id)
        else:
            hg.remove_device(device.vendor_id, device.product_id)

    def _sort_profile_cb(self):
        ''' sorts entries by profile '''
        self._profile_mapper.sort_profile()
        self.populate_map()

    def _sort_process_cb(self):
        ''' sorts entries by process '''
        self._profile_mapper.sort_process()
        self.populate_map()

    def _add_profile_map_cb(self):
        ''' adds a new profile mapping '''
        item = gremlin.base_profile.ProfileMapItem()
        self._profile_mapper.register(item)
        self.populate_map()

    def _save_map_cb(self):
        ''' saves the current mappings and options '''
        pushCursor()
        for item in self._profile_mapper.items():
            item.save()

        self._profile_mapper.save_profile_map()
        popCursor()

    def populate_map(self):
        ''' populates the map of executables to profiles '''

        # figure out the size of the header part of the control so things line up
        lbl = QtWidgets.QLabel("w")
        char_width = lbl.fontMetrics().averageCharWidth()
        headers = ["Process:", "Profile:"]
        width = 0
        for header in headers:
            width = max(width, char_width*(len(header)))

        for widget in self._profile_map_exe_widgets.values():
            if widget:
                widget.setParent(None)
        for widget in self._profile_map_xml_widgets.values():
            if widget:
                widget.setParent(None)

        self._profile_map_exe_widgets = {}
        self._profile_map_xml_widgets = {}
        self._profile_map_mode_widgets = {}

        # clear the widgets
        ui_common.clear_layout(self.map_layout)

        if not self._profile_mapper:
             missing = QtWidgets.QLabel("No mappings found.")
             missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
             self.map_layout.addWidget(missing, 0, 0)
             return

        item: gremlin.base_profile.ProfileMapItem
        self._profile_mapper.validate()
        for index, item in enumerate(self._profile_mapper.items()):

            exe_widget = None
            xml_widget = None
            pd = item.get_profile_data()
            
            mode_enabled = bool(pd.mode_list)

            if item:
                # add a new item if it exists and either one of the profile/process entries are refined

                row = 0

                container_widget = QtWidgets.QWidget()
                container_layout = QtWidgets.QGridLayout()
                container_layout.setColumnStretch(0,2)
                container_layout.setColumnStretch(1,2)
                container_layout.setContentsMargins(0,0,0,0)
                container_widget.setLayout(container_layout)

                exe_widget = ui_common.QPathLineItem("Process:",item.process, item)
                exe_widget.pathChanged.connect(self._process_changed_cb)
                exe_widget.open.connect(self._process_open_cb)
                container_layout.addWidget(exe_widget,row,0,1,2)
                row+=1

                xml_widget = ui_common.QPathLineItem("Profile:",item.profile, item)
                xml_widget.pathChanged.connect(self._profile_changed_cb)
                xml_widget.open.connect(self._profile_open_cb)
                container_layout.addWidget(xml_widget,row,0,1,2)
                row+=1

                options_line = QtWidgets.QWidget()
                options_layout = QtWidgets.QGridLayout(options_line)
                options_layout.setContentsMargins(0,0,0,0)
                

                restore_widget = ui_common.QDataCheckbox("Restore last mode on start", item)
                restore_widget.setChecked(pd.restore_last)
                restore_widget.clicked.connect(self._restore_changed)
                restore_widget.setToolTip("When set, restores the last used mode if the profile has been automatically loaded on process change")

                force_numlock_widget = ui_common.QDataCheckbox("Force numlock off", item)
                force_numlock_widget.setToolTip("When set, GremlinEx will force the keyboard numlock state to Off to prevent issues with numpad keymapping")
                force_numlock_widget.setChecked(pd.force_numlock_off)
                force_numlock_widget.clicked.connect(self._force_numlock_cb)
                

                mode_widget = ui_common.QDataComboBox(item)
                
                mode_widget.addItems(pd.mode_list)
                if mode_enabled:
                    if pd.default_mode:
                        mode_widget.setCurrentText(pd.default_mode)
                        item.default_mode = pd.default_mode
                    else:
                        item.default_mode = pd.mode_list[0] # first item
                    mode_widget.setEnabled(True)
                else:
                    mode_widget.setEnabled(False)

            
                mode_widget.currentIndexChanged.connect(self._default_mode_changed)
                mode_widget.setToolTip("Default startup mode for this profile")


                options_layout.addWidget(force_numlock_widget,0,0,1,-1)
                options_layout.addWidget(restore_widget,1,0)
                options_layout.addWidget(QtWidgets.QLabel("Default start mode:"),1,1)
                options_layout.addWidget(mode_widget,1,2)

                container_layout.addWidget(options_line,row,0,1,-1)
                row+=1

                clear_button = ui_common.QDataPushButton()
                clear_button.setIcon(load_icon("mdi.delete"))
                clear_button.setMaximumWidth(20)
                clear_button.data = item
                clear_button.clicked.connect(self._mapping_delete_cb)
                clear_button.setToolTip("Removes this entry")
                container_layout.addWidget(clear_button, 0, 3)


                duplicate_button = ui_common.QDataPushButton()
                duplicate_button.setIcon(load_icon("mdi.content-duplicate"))
                duplicate_button.setMaximumWidth(20)
                duplicate_button.data = item
                duplicate_button.clicked.connect(self._mapping_duplicate_cb)
                duplicate_button.setToolTip("Duplicates this entry")
                container_layout.addWidget(duplicate_button, 1, 3)


                if not item.valid:
                    warning_widget = ui_common.QIconLabel("fa.warning", text=item.warning, use_qta = True,  icon_color="red")
                    container_layout.addWidget(warning_widget, row, 0, 1, -1)
                    row+=1

                container_layout.addWidget(ui_common.QHLine(),row,0,1, -1)

                item.index = index
                self.map_layout.addWidget(container_widget, index, 0)

                exe_widget.header_width = width
                xml_widget.header_width = width

            self._profile_map_exe_widgets[index] = exe_widget
            self._profile_map_xml_widgets[index] = xml_widget
            self._profile_map_mode_widgets[index] = mode_widget


    def _default_mode_changed(self):
        widget = self.sender()
        item : gremlin.base_profile.ProfileMapItem = widget.data
        item.default_mode = widget.currentText()

    def _restore_changed(self, checked):
        widget = self.sender()
        item : gremlin.base_profile.ProfileMapItem = widget.data
        item.restore_mode = checked

    def _force_numlock_cb(self, checked):
        widget = self.sender()
        item : gremlin.base_profile.ProfileMapItem = widget.data
        item.numlock_force = checked
        

    def _process_open_cb(self, widget):
        ''' opens the process executable '''
        fname = widget.data.process
        self.executable_dialog = ProcessWindow(fname)
        self.executable_dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        self.executable_dialog.data = widget
        self.executable_dialog.process_selected.connect(self._select_executable)
        self.executable_dialog.show()

    def _profile_open_cb(self, widget):
        ''' opens the profile list '''
        item = widget.data
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Select Profile",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )
        if fname:
            item.profile = fname
            with QtCore.QSignalBlocker(widget):
                widget.setText(fname)
            self.populate_map()


    def _select_executable(self, fname):
        """Adds the provided executable to the list of configurations.

        :param fname the executable for which to add a mapping
        """
        widget = self.sender()
        w = widget.data
        item = w.data
        item.process = fname
        with QtCore.QSignalBlocker(w):
            w.setText(fname)
        self.queue_refresh.emit()


    def _mapping_delete_cb(self):
        import gremlin.util
        widget = self.sender()
        item = widget.data
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText("This will delete this profile association.\nAre you sure?")
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_confirmed_cb(item)


    def _delete_confirmed_cb(self, item):
        self._profile_mapper.remove(item)
        self.populate_map()

    def _mapping_duplicate_cb(self):
        ''' duplicates the current entry '''
        widget = self.sender()
        item = widget.data
        duplicate_item = gremlin.base_profile.ProfileMapItem(item.profile, item.process)
        self._profile_mapper.register(duplicate_item)
        self.queue_refresh.emit()


    def _process_changed_cb(self, widget, text):
        ''' called when the process path changes '''
        item = widget.data
        item.process = text if widget.valid else None
        self.queue_refresh.emit()


    def _profile_changed_cb(self, widget, text):
        ''' called when the profile '''
        item = widget.data
        item.profile = text if widget.valid else None
        self.queue_refresh.emit()

    def get_profile_item(self, profile_path, executable_path):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        widget.setLayout(layout)

        profile_widget = QtWidgets.QLineEdit()
        layout.addWidget(profile_widget)

        exe_widget = QtWidgets.QLineEdit()
        layout.addWidget(exe_widget)




class ProcessWindow(ui_common.BaseDialogUi):

    """Displays active processes in a window for the user to select."""

    # Signal emitted when the user selects a process
    process_selected = QtCore.Signal(str)

    def __init__(self, text = None, parent=None):
        """Creates a new instance.

        :param text: the process exe to select by default (if one is provided, and the item is not in the list, the file open will executed at that folder location)
        :param parent the parent of the widget
        """
        super().__init__(parent)

        self.setWindowTitle("Process List")
        self.setMinimumWidth(400)
        self.setMinimumHeight(600)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.list_model = QtCore.QStringListModel()

        process_list = gremlin.process_monitor.list_current_processes()
        self.list_model.setStringList(process_list)

        self.list_view = QtWidgets.QListView()
        self.list_view.setModel(self.list_model)
        self.list_view.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.list_view.doubleClicked.connect(self._select)
        self._current_selection_qindex = None
        self.list_view.clicked.connect(self._selection_changed)

        self.button_bar_widget = QtWidgets.QWidget()
        self.button_bar_layout = QtWidgets.QHBoxLayout()
        self.button_bar_widget.setLayout(self.button_bar_layout)

        self.refresh_button =QtWidgets.QPushButton("Refresh")
        self.refresh_button.setIcon(load_icon("fa.refresh",qta_color="green"))
        self.refresh_button.clicked.connect(self._refresh)

        self.main_layout.addWidget(self.list_view)

        self.select_button = QtWidgets.QPushButton("Select")
        self.select_button.clicked.connect(self._select)
        self.main_layout.addWidget(self.select_button)

        self.browse_button = QtWidgets.QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse)

        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)

        self.button_bar_layout.addWidget(self.refresh_button)
        self.button_bar_layout.addWidget(self.select_button)
        self.button_bar_layout.addWidget(self.browse_button)
        self.button_bar_layout.addWidget(self.cancel_button)

        self.main_layout.addWidget(self.button_bar_widget)


        # optional data item to track for this item
        self._data = None

        if text and os.path.isfile(text):
            if not text in process_list:
                # selected item is not in the running process list
                self._browse(text)

            else:
                # select the item in the list
                index = process_list.index(text)
                model_index = self.list_model.index(index)  # process_list.index(text)
                with QtCore.QSignalBlocker(self.list_view):
                    self.list_view.setCurrentIndex(model_index)
                    self._current_selection_qindex = model_index

    def _refresh(self):
        self.list_model.setStringList(
            gremlin.process_monitor.list_current_processes()
        )

    def _cancel(self):
        ''' cancel clicked '''
        self.close()



    def _selection_changed(self, index):
        self._current_selection_qindex = index

    def _select(self):
        """Emits the process_signal when the select button is pressed."""
        
        self.process_selected.emit(self.list_view.currentIndex().data())
        self.close()

    def _browse(self, text = None):
        if not text and self._current_selection_qindex is not None:
            text = self.list_model.itemData(self._current_selection_qindex)[0]

        if text and os.path.isfile(text):
            dir = os.path.dirname(text)
        else:
            dir = "C:\\"
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Path to executable",
            dir,
            "EXE Files (*.exe);"
        )
        if fname != "":
            self.process_selected.emit(fname)
            self.close()



class LogWindowUi(ui_common.BaseDialogUi):

    """Window displaying log file content."""

    def __init__(self,  parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.setWindowTitle("Log Viewer")
        self.setMinimumWidth(600)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.tab_container = QtWidgets.QTabWidget()
        self.main_layout.addWidget(self.tab_container)

        self._ui_elements = {}
        self._create_log_display(
            os.path.join(gremlin.util.userprofile_path(), "system.log"),
            "System"
        )
        self._create_log_display(
            os.path.join(gremlin.util.userprofile_path(), "user.log"),
            "User"
        )
        self.watcher = gremlin.util.FileWatcher([
            os.path.join(gremlin.util.userprofile_path(), "system.log"),
            os.path.join(gremlin.util.userprofile_path(), "user.log")
        ])
        self.watcher.file_changed.connect(self._reload)

    def closeEvent(self, event):
        """Handles closing of the window.

        :param event the closing event
        """
        self.watcher.stop()
        super().closeEvent(event)

    def _create_log_display(self, fname, title):
        """Creates a new tab displaying log file contents.

        :param fname path to the file whose content to display
        :param title the title of the tab
        """
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        log_display = QtWidgets.QTextEdit()
        log_display.setText(open(fname).read())
        button = QtWidgets.QPushButton("Clear log")
        button.clicked.connect(lambda: self._clear_log(fname))
        layout.addWidget(log_display)
        layout.addWidget(button)

        self._ui_elements[fname] = {
            "page": page,
            "layout": layout,
            "button": button,
            "log_display": log_display
        }

        self.tab_container.addTab(
            self._ui_elements[fname]["page"],
            title
        )

    def _clear_log(self, fname):
        """Clears the specified log file.

        :param fname path to the file to clear
        """
        open(fname, "w").close()

    def _reload(self, fname):
        """Reloads the content of tab displaying the given file.

        :param fname name of the file whose content to update
        """
        widget = self._ui_elements[fname]["log_display"]
        widget.setText(open(fname).read())
        widget.verticalScrollBar().setValue(
            widget.verticalScrollBar().maximum()
        )


class AboutUi(ui_common.BaseDialogUi):

    """Widget which displays information about the application."""

    def __init__(self, parent=None):
        """Creates a new about widget.

        This creates a simple widget which shows version information
        and various software licenses.

        :param parent parent of this widget
        """
        super().__init__(parent)
        self.ui = ui_about.Ui_About()
        self.ui.setupUi(self)

        self.ui.about.setHtml(
            open(gremlin.util.resource_path("about/about.html")).read()
        )

        self.ui.jg_license.setHtml(
            open(gremlin.util.resource_path("about/joystick_gremlin.html")).read()
        )

        license_list = [
            "about/third_party_licenses.html",
            "about/modernuiicons.html",
            "about/pyqt.html",
            "about/pywin32.html",
            "about/qt5.html",
            "about/reportlab.html",
            "about/vjoy.html",
        ]
        third_party_licenses = ""
        for fname in license_list:
            third_party_licenses += open(gremlin.util.resource_path(fname)).read()
            third_party_licenses += "<hr>"
        self.ui.third_party_licenses.setHtml(third_party_licenses)


class ModeManagerUi(ui_common.BaseDialogUi):

    """Enables the creation of modes and configuring their inheritance."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the data being profile whose modes are being
            configured
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self._profile = profile_data
        self.setWindowTitle("Mode Manager")

        self.mode_dropdowns = {}
        self.mode_rename = {}
        self.mode_delete = {}
        self.mode_callbacks = {}
        self.is_modified = False # true if the modes were modified

        self._create_ui()

        # Disable keyboard event handler
        el = gremlin.event_handler.EventListener()
        el.keyboard_hook.stop()

    def closeEvent(self, event):
        """Emits the closed event when this widget is being closed.

        :param event the close event details
        """
        # Re-enable keyboard event handler
        el = gremlin.event_handler.EventListener()
        el.modes_changed.emit()
        el.keyboard_hook.start()
        super().closeEvent(event)

    def _create_ui(self):
        """Creates the required UII elements."""
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        self.scroll_area.setMinimumWidth(300)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.mode_widget = QtWidgets.QWidget()
        self.mode_layout = QtWidgets.QGridLayout()
        self.mode_widget.setLayout(self.mode_layout)

        self.scroll_layout.addWidget(self.mode_widget)

        
        self.add_button = QtWidgets.QPushButton("Add Mode")
        self.add_button.clicked.connect(self._add_mode_cb)

        self.scroll_layout.addWidget(self.add_button)

        label = QtWidgets.QLabel(
            "Modes are by default self contained configurations. Specifying "
            "a parent for a mode causes the the mode \"inherits\" all actions "
            "defined in the parent, unless the mode configures its own actions "
            "for specific inputs."
        )
        label.setStyleSheet("QLabel { background-color : #8FBC8F; }")
        label.setWordWrap(True)
        label.setFrameShape(QtWidgets.QFrame.Box)
        label.setMargin(10)
        self.scroll_layout.addWidget(label)

        close_button_widget = QtWidgets.QPushButton("Close")
        close_button_widget.clicked.connect(self._close_cb)
        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)
        button_container_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        button_container_layout.addWidget(close_button_widget)


        self.main_layout.addWidget(self.scroll_area)
        self.main_layout.addWidget(button_container_widget)

        self._populate_mode_layout()

    @QtCore.Slot()
    def _close_cb(self):
        self.close()

    def _get_mode_list(self):
        mode_list = {}
        for device in self._profile.devices.values():
            for mode in device.modes.values():
                if mode.name not in mode_list:
                    if mode.name:
                        mode_list[mode.name] = mode.inherit
        return mode_list


    def _populate_mode_layout(self):
        """Generates the mode layout UI displaying the different modes."""
        # Clear potentially existing content
        ui_common.clear_layout(self.mode_layout)
        self.mode_dropdowns = {}
        self.mode_rename = {}
        self.mode_delete = {}
        self.mode_callbacks = {}
        self.mode_default = None # default startup mode

        

        self._display_width = 0

        # Obtain mode names and the mode they inherit from
        mode_list = self._get_mode_list()

        # Add header information
        self.mode_layout.addWidget(QtWidgets.QLabel("<b>Name</b>"), 0, 0)
        self.mode_layout.addWidget(QtWidgets.QLabel("<b>Parent</b>"), 0, 1)

        self.mode_default_selector = gremlin.ui.ui_common.QComboBox()
        self.mode_default_selector.setToolTip("Specifies the default startup mode for this profile when it is loaded. This setting can be overriden if the restore last active mode option is set.")


        # Create UI element for each mode
        row = 1
        for mode, inherit in sorted(mode_list.items()):
            self.mode_layout.addWidget(QtWidgets.QLabel(mode), row, 0)
            self.mode_dropdowns[mode] = gremlin.ui.ui_common.QComboBox()
            self.mode_dropdowns[mode].addItem("None")
            self.mode_dropdowns[mode].setMinimumContentsLength(20)
            self.mode_default_selector.addItem(mode)
            for name in sorted(mode_list.keys()):
                if name != mode:
                    self.mode_dropdowns[mode].addItem(name)



            self.mode_callbacks[mode] = self._create_inheritance_change_cb(mode)
            self.mode_dropdowns[mode].currentTextChanged.connect(
                self.mode_callbacks[mode]
            )
            self.mode_dropdowns[mode].setCurrentText(inherit)

            # Rename mode button
            self.mode_rename[mode] = QtWidgets.QPushButton(
                load_icon("fa.edit"), ""
            )
            self.mode_rename[mode].setMaximumWidth(20)
            self.mode_layout.addWidget(self.mode_rename[mode], row, 2)
            self.mode_rename[mode].clicked.connect(
                self._create_rename_mode_cb(mode)
            )
            self.mode_rename[mode].setToolTip("Edit")

            # Delete mode button
            self.mode_delete[mode] = QtWidgets.QPushButton(
                load_icon("mdi.delete"), ""
            )
            self.mode_delete[mode].setMaximumWidth(20)
            self.mode_delete[mode].setToolTip("Delete")
            self.mode_layout.addWidget(self.mode_delete[mode], row, 3)
            self.mode_delete[mode].clicked.connect(
                self._create_delete_mode_cb(mode)
            )

            self.mode_layout.addWidget(self.mode_dropdowns[mode], row, 1)

            # padd right column that expands
            self.mode_layout.addWidget(QtWidgets.QLabel(" "),row, 4)
            row += 1

        # add the default mode selector
        self.container_default_widget = QtWidgets.QWidget()
        self.container_default_layout = QtWidgets.QHBoxLayout()
        self.container_default_layout.setContentsMargins(0,0,0,0)
        self.container_default_widget.setLayout(self.container_default_layout)

        self.mode_restore_flag = QtWidgets.QCheckBox("Restore last mode on activation")
        self.mode_restore_flag.setToolTip("""When enabled, the last known active mode for this profile will be used when the profile is loaded or re-activated regardless of the default mode specified in the Modes Editor

The setting can be overriden by the global mode reload option set in Options for this profile.
""")
        self.mode_restore_flag.setChecked(gremlin.shared_state.current_profile.get_restore_mode())
        self.mode_restore_flag.clicked.connect(self._profile_restore_flag_cb)


        
        self.mode_layout.addWidget(ui_common.QHLine(),row,0,1,-1)
        row+=1
        
        self.mode_layout.addWidget(QtWidgets.QLabel("Profile start mode"), row, 0)
        self.mode_layout.addWidget(self.mode_default_selector,row,1)
        row += 1


        mode = gremlin.shared_state.current_profile.get_start_mode()
        self.mode_default_selector.setCurrentText(mode)
        self.mode_default_selector.currentIndexChanged.connect(self._change_default_mode_cb)

        # add the default flag
        self.mode_layout.addWidget(self.mode_restore_flag, row, 0, 1, -1)

        self.mode_layout.setColumnStretch(4,4)
        

        

    def _profile_restore_flag_cb(self, clicked):
        ''' called when the restore last mode checked state is changed '''
        self._profile.set_restore_mode(clicked)

    def _create_inheritance_change_cb(self, mode):
        """Returns a lambda function callback to change the inheritance of
        a mode.

        This is required as otherwise lambda functions created within a
        function do not behave as desired.

        :param mode the mode for which the callback is being created
        :return customized lambda function
        """
        return lambda x: self._change_mode_inheritance(mode, x)

    def _create_rename_mode_cb(self, mode):
        """Returns a lambda function callback to rename a mode.

        This is required as otherwise lambda functions created within a
        function do not behave as desired.

        :param mode the mode for which the callback is being created
        :return customized lambda function
        """
        return lambda: self._rename_mode(mode)

    def _create_delete_mode_cb(self, mode):
        """Returns a lambda function callback to delete the given mode.

        This is required as otherwise lambda functions created within a
        function do not behave as desired.

        :param mode the mode to remove
        :return lambda function to perform the removal
        """

        # modes can be deleted except the last one
        return lambda: self._delete_mode(mode)



    def _change_mode_inheritance(self, mode, inherit):
        """Updates the inheritance information of a given mode.

        :param mode the mode to update
        :param inherit the name of the mode this mode inherits from
        """
        # Check if this inheritance would cause a cycle, turning the
        # tree structure into a graph
        has_inheritance_cycle = False
        if inherit != "None":
            all_modes = list(self._profile.devices.values())[0].modes
            cur_mode = inherit
            while all_modes[cur_mode].inherit is not None:
                if all_modes[cur_mode].inherit == mode:
                    has_inheritance_cycle = True
                    break
                cur_mode = all_modes[cur_mode].inherit

        # Update the inheritance information in the profile
        if not has_inheritance_cycle:
            for name, device in self._profile.devices.items():
                if inherit == "None":
                    inherit = None
                device.ensure_mode_exists(mode)
                device.modes[mode].inherit = inherit

        # eh = gremlin.event_handler.EventListener()
        # eh.modes_changed.emit()

    def _rename_mode(self, mode_name):
        """Asks the user for the new name for the given mode.

        If the user provided name for the mode is invalid the
        renaming is aborted and no change made.

        :param mode_name new name for the mode
        """
        # Retrieve new name from the user
        name, user_input = QtWidgets.QInputDialog.getText(
                self,
                "Mode name",
                "",
                QtWidgets.QLineEdit.Normal,
                mode_name
        )
        if user_input:
            if name in gremlin.profile.mode_list(self._profile):
                gremlin.util.display_error(
                    f"A mode with the name \"{name}\" already exists"
                )
            else:
                # Update the renamed mode in each device
                for device in self._profile.devices.values():
                    device.modes[name] = device.modes[mode_name]
                    device.modes[name].name = name
                    del device.modes[mode_name]
                    if gremlin.shared_state.edit_mode == mode_name:
                        gremlin.shared_state.edit_mode = name
                    if gremlin.shared_state.runtime_mode == mode_name:
                        gremlin.shared_state.runtime_mode = name

                    # Update inheritance information
                    for mode in device.modes.values():
                        if mode.inherit == mode_name:
                            mode.inherit = name

                # rename the startup mode if it's the same
                if mode_name == gremlin.shared_state.current_profile.get_start_mode():
                    gremlin.shared_state.current_profile.set_start_mode(name)

                

            self._populate_mode_layout()
            self._fire_mode_change()

    def _fire_mode_change(self):
        eh = gremlin.event_handler.EventListener()
        eh.modes_changed.emit()

    def _delete_mode(self, mode_name):
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText(f"Delete mode {mode_name}?<br>This will delete this mode and all associated mappings.<br>Are you sure?")
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_mode_confirm(mode_name)


    def _delete_mode_confirm(self, mode_name):
        """Removes the specified mode.

        Performs an update of the inheritance of all modes that inherited
        from the deleted mode.

        :param mode_name the name of the mode to delete
        """
        # Obtain mode from which the mode we want to delete inherits

        mode_list = self._get_mode_list()
        if len(mode_list.keys()) == 1:
            QMessageBox.warning(self, "Warning","Cannot delete last mode - one mode must exist")
            return
        
        

        parent_of_deleted = None
        for mode in list(self._profile.devices.values())[0].modes.values():
            if mode.name == mode_name:
                parent_of_deleted = mode.inherit

        # Assign the inherited mode of the the deleted one to all modes that
        # inherit from the mode to be deleted
        for device in self._profile.devices.values():
            for mode in device.modes.values():
                if mode.inherit == mode_name:
                    mode.inherit = parent_of_deleted

        # Remove the mode from the profile
        for device in self._profile.devices.values():
            del device.modes[mode_name]


        
        default_mode = gremlin.shared_state.current_profile.get_root_mode()
        if gremlin.shared_state.edit_mode == mode_name:
            gremlin.shared_state.edit_mode = default_mode
        if gremlin.shared_state.runtime_mode == mode_name:
            gremlin.shared_state.runtime_mode = default_mode


        # Update the ui
        self._populate_mode_layout()
        self._fire_mode_change()


    @QtCore.Slot()
    def _add_mode_cb(self):
        """Asks the user for a new mode to add.

        If the user provided name for the mode is invalid no mode is
        added.

        :param checked flag indicating whether or not the checkbox is active
        """
        name, user_input = QtWidgets.QInputDialog.getText(None, "Mode name", "")
        if user_input:
            if name in gremlin.profile.mode_list(self._profile):
                gremlin.util.display_error(
                    f"A mode with the name \"{name}\" already exists"
                )
            else:
                for device in self._profile.devices.values():
                    new_mode = gremlin.base_profile.Mode(device)
                    new_mode.name = name
                    device.modes[name] = new_mode
                

            self._populate_mode_layout()
            self._fire_mode_change()

    @QtCore.Slot(int)
    def _change_default_mode_cb(self, index):
        ''' occurs when the default mode is changed '''
        mode = self.mode_default_selector.currentText()
        gremlin.shared_state.current_profile.set_start_mode(mode)


class DeviceInformationUi(ui_common.BaseDialogUi):

    """Widget which displays information about all connected joystick
    devices."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param parent the parent widget
        """
        super().__init__(parent)

        self.profile = profile_data

        self.devices = gremlin.joystick_handling.joystick_devices()

        self.setWindowTitle("Device Information")

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()
        self.table = QtWidgets.QTableWidget()
        self.table.setSortingEnabled(True)

        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        self.scroll_area.setMinimumWidth(400)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.scroll_layout.addWidget(self.table)

        self.main_layout.addWidget(self.scroll_area)


        # row headers

        headers = [
            "Device Name",
            "Axis Count",
            "Buttons Count",
            "Hat Count",
            "Vendor ID",
            "Product ID",
            "GUID",
            "Device name (nocase)"
        ]

        # table data



        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(self.devices))
        self.table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu_cb)
        self.table.viewport().installEventFilter(self)

        self.menu = None # context menu for the table
        self.menu_item = None # the cell item the menu applies to

        for i, entry in enumerate(self.devices):
            # w_name = QtWidgets.QLineEdit()
            # w_name.setText(entry.name)
            # w_name.setReadOnly(True)
            # w_name.setMinimumWidth(w)
            # w_name.setMaximumWidth(w)
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(entry.name))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(entry.axis_count)))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(entry.button_count)))
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(str(entry.hat_count)))
            self.table.setItem(i, 4, QtWidgets.QTableWidgetItem(f"{entry.vendor_id:04X}"))
            self.table.setItem(i, 5, QtWidgets.QTableWidgetItem(f"{entry.product_id:04X}"))


            # guid_field = QtWidgets.QLineEdit()
            # guid_field.setText(str(entry.device_guid))
            # guid_field.setReadOnly(True)
            # guid_field.setMinimumWidth(w)
            # guid_field.setMaximumWidth(w)

            self.table.setItem(i, 6, QtWidgets.QTableWidgetItem(str(entry.device_guid)))
            self.table.setItem(i, 7, QtWidgets.QTableWidgetItem(entry.name.lower()))

        # resize
        self.table.resizeColumnsToContents()

        # toolbar

        self.tool_widget = QtWidgets.QWidget()
        self.tool_layout = QtWidgets.QHBoxLayout()
        self.tool_widget.setLayout(self.tool_layout)

        self.script_copy_button = QtWidgets.QPushButton("Generate plugin script header")
        self.script_copy_button.clicked.connect(self._copy_to_script)
        self.tool_layout.addWidget(self.script_copy_button)

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(lambda: self.close())
        self.tool_layout.addWidget(self.close_button)

        self.main_layout.addWidget(self.tool_widget)

    def eventFilter(self, source, event):
        ''' table event filter '''
        if isinstance(event, QtGui.QSinglePointEvent) and event.type() == QtCore.QEvent.MouseButtonPress and source is self.table.viewport():
            button = event.buttons()
            if button == QtCore.Qt.RightButton:
                pos = event.position().toPoint()
                item = self.table.itemAt(pos)
                if item is not None:
                    verbose = gremlin.config.Configuration().verbose
                    if verbose:
                        logging.getLogger("system").info(f"DeviceInfo: context click on: {item.row()} {item.column()} {item.text()}")
                    self.menu = QtWidgets.QMenu(self)
                    action = QtWidgets.QWidgetAction(self)
                    label = QtWidgets.QLabel(self)
                    label.setText("Copy")
                    label.setMargin(4)
                    action.setDefaultWidget(label)
                    action.triggered.connect(self._menu_copy)
                    self.menu.addAction(action)
                    self.menu_item = item
        return super().eventFilter(source, event)

    def _menu_copy(self, widget):
        ''' handles copy operation'''
        item = self.menu_item
        if item:
            # copy the data to the clipboard
            clipboard = Clipboard()
            clipboard.set_windows_clipboard_text(item.text())
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                logging.getLogger("system").info(f"DeviceInfo: copy to clipboard Item: {item.row()} {item.column()} {item.text()}")

    def _context_menu_cb(self, loc):
        ''' context menu for the table '''
        if self.menu:
            self.menu.exec(self.table.mapToGlobal(loc))

    def _copy_to_script(self):
        ''' copies device entries to clipboard in script format '''
        import re
        s_list = []
        a_map = {}

        s_list.append("# GremlinEx plugin script device list\n")

        # grab all defined modes in the current profile
        mode_list = set()
        for device in self.profile.devices.values():
            for mode in device.modes.values():
                if mode.name is None:
                    continue
                mode_list.add(mode.name)

        mode_list = list(mode_list)
        mode_list.sort()

        for i, entry in enumerate(self.devices):
            if entry.is_virtual:
                # skip virtual devices
                continue
            var_name = re.sub('[^0-9a-zA-Z]+', '_', entry.name) # cleanup non alphanumeric in the name for clean variable names
            s_list.append(f"\n# device {entry.name} - axis count: {entry.axis_count}  hat count: {entry.hat_count}  button count: {entry.button_count}")
            s_list.append(f"{var_name}_NAME = \"{entry.name}\"")
            s_list.append(f"{var_name}_GUID = \"{entry.device_guid}\"")
            for mode_name in mode_list:
                mode_suffix = mode_name.replace(" ","_")
                if not mode_name in a_map.keys():
                    a_map[mode_name] = set()
                a_map[mode_name].add(f"{var_name}_{mode_suffix} = gremlin.input_devices.JoystickDecorator({var_name}_NAME, {var_name}_GUID, \"{mode_name}\")")

        script = ""
        for line in s_list:
            script += line + "\n"

        script += "\n# plugin decorator definitions\n"
        for mode_name in a_map.keys():
            script += f"\n# decorators for mode {mode_name}\n"
            for line in a_map[mode_name]:
                script += line + "\n"

        # set the clipboard data
        clipboard = Clipboard()
        clipboard.set_windows_clipboard_text(script)




class SwapDevicesUi(ui_common.BaseDialogUi):

    """UI Widget that allows users to swap identical devices."""

    def __init__(self, profile, parent=None):
        """Creates a new instance.

        :param profile the current profile
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.profile = profile

        # Create UI elements
        self.setWindowTitle("Swap Devices")
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._create_swap_ui()

    def _create_swap_ui(self):
        """Displays possible groups of swappable devices."""
        ui_common.clear_layout(self.main_layout)

        profile_modifier = gremlin.profile.ProfileModifier(self.profile)
        device_list = profile_modifier.device_information_list()

        device_layout = QtWidgets.QGridLayout()
        for i, data in enumerate(device_list):
            # Ignore the keyboard
            if data.device_guid == dinput.GUID_Keyboard:
                continue

            # Ignore devices with no remappable entries
            if (data.containers + data.conditions + data.merge_axis) == 0:
                continue

            # UI elements for this devic
            name = QtWidgets.QLabel(data.name)
            name.setAlignment(QtCore.Qt.AlignTop)
            labels = QtWidgets.QLabel("Containers\nConditions\nMerge Axis")
            counts = QtWidgets.QLabel(f"{data.containers:d}\n{data.conditions:d}\n{data.merge_axis:d}")
            counts.setAlignment(QtCore.Qt.AlignRight)
            record_button = QtWidgets.QPushButton(
                f"Assigned to: {data.device_guid} - {data.name}"
            )
            record_button.clicked.connect(
                self._create_request_user_input_cb(data.device_guid)
            )

            # Combine labels and counts into it's own layout
            layout = QtWidgets.QHBoxLayout()
            layout.addWidget(labels)
            layout.addWidget(counts)
            layout.addStretch()

            # Put everything together
            device_layout.addWidget(name, i, 0)
            device_layout.addLayout(layout, i, 1)
            device_layout.addWidget(record_button, i, 2, QtCore.Qt.AlignTop)

        self.main_layout.addLayout(device_layout)
        self.main_layout.addStretch()

    def _create_request_user_input_cb(self, device_guid):
        """Creates the callback handling user device selection.

        :param device_guid GUID of the associated device
        :return callback function for user input selection handling
        """
        return lambda: self._request_user_input(
            lambda event: self._user_input_cb(event, device_guid)
        )

    def _user_input_cb(self, event, device_guid):
        """Processes input events to update the UI and model.

        :param event the input event to process
        :param device_guid GUID of the selected device
        """
        profile_modifier = gremlin.profile.ProfileModifier(self.profile)
        profile_modifier.change_device_guid(
            device_guid,
            event.device_guid
        )

        self._create_swap_ui()

    def _request_user_input(self, callback):
        """Prompts the user for the input to bind to this item.

        :param callback function to call with the accepted input
        """
        self.input_dialog = ui_common.InputListenerWidget(
            [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ],
            return_kb_event=False,
            multi_keys=False
        )
        self.input_dialog.item_selected.connect(callback)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.input_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        self.input_dialog.show()




class SubstituteDialog(QtWidgets.QDialog):
    ''' device substitution - allows the swap of one device_guid for another '''

    def __init__(self, device_guid, device_name, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._device_guid = device_guid # current device GUID
        self._device_name = device_name # current device name

        fm = QtGui.QFontMetrics(self.font())
        
        

        # get current profile
        profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile

        
        self.profile_device_widget = gremlin.ui.ui_common.QComboBox()
        self.hardware_device_widget = gremlin.ui.ui_common.QComboBox()
        
        self.replace_button_widget = QtWidgets.QPushButton("Replace")
        self.replace_button_widget.clicked.connect(self._replace_cb)
        
        self.header_container_widget = QtWidgets.QWidget()
        self.header_container_layout = QtWidgets.QGridLayout(self.header_container_widget)

        self.header_container_layout.addWidget(QtWidgets.QLabel("Profile device: "),0,0)
        self.header_container_layout.addWidget(self.profile_device_widget,0,1)


        self.header_container_layout.addWidget(QtWidgets.QLabel("Replace with: "),1,0)
        self.header_container_layout.addWidget(self.hardware_device_widget,1,1)
        

        self.header_container_layout.addWidget(self.replace_button_widget,1,2)
        self.header_container_layout.addWidget(QtWidgets.QLabel(" "),0,3)
        self.header_container_layout.setColumnStretch(3,2)


        self.main_layout.addWidget(QtWidgets.QLabel("Device substitution enables the replacement of one device ID with another<br/>in case the hardware ID has changed since the profile was created."))
        self.main_layout.addWidget(self.header_container_widget)
        self.main_layout.addStretch()

        self._profile_devices = [device for device in profile.devices.values() if device.type == gremlin.types.DeviceType.Joystick]
        self._profile_devices.sort(key = lambda x: x.name.casefold())

        # populate devices currently connected
        self._hardware_devices = []
        device_count = dinput.DILL.get_device_count()
        for index in range(device_count):
            info : dinput.DeviceSummary = dinput.DILL.get_device_information_by_index(index)
            if not info.is_virtual:
                # skip vjoy devices
                self._hardware_devices.append(info)

        # sort
        self._hardware_devices.sort(key = lambda x: x.name.casefold())
        for info in self._hardware_devices:
            self.hardware_device_widget.addItem(f"[{str(info.device_guid)}] {info.name}", info)

        for info in self._profile_devices:
            self.profile_device_widget.addItem(f"[{str(info.device_guid)}] {info.name}", info)


        self.hardware_device_widget.currentIndexChanged.connect(self._validate)
        self.profile_device_widget.currentIndexChanged.connect(self._validate)

        self._validate()

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )

        self.ensurePolished()
        self.adjustSize()

    def sizeHint(self):
        return QtCore.QSize(700,150)

    def ok_message_box(self, content):
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText(content)
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()

    def confirm_message_box(self, content):
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText(content)
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        return result == QtWidgets.QMessageBox.StandardButton.Ok

    def _validate(self):
        self._hardware_device_guid = str(self.hardware_device_widget.currentData().device_guid)
        self._profile_device_guid = str(self.profile_device_widget.currentData().device_guid)
        is_enabled = self._hardware_device_guid != self._profile_device_guid
        self.replace_button_widget.setEnabled(is_enabled)


    @QtCore.Slot()
    def _replace_cb(self):

        current_guid = self._profile_device_guid
        current_name = self.profile_device_widget.currentData().name
        new_device_guid = self._hardware_device_guid
        new_device_name = self.hardware_device_widget.currentData().name

        if self.confirm_message_box(f"Replace ID '{current_guid}' with '{new_device_guid}' (no undo?)"):
            # read the XML as a text file

            profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile

            # make a backup of the profile just in case ... roundrobin file name ...
            xml_file =  profile.profile_file
            backup_file = profile.profile_file
            dirname, base_file = os.path.split(backup_file)
            basename, ext = os.path.splitext(base_file)
            max_count = 5
            count = 0
            file_list = []
            while os.path.isfile(backup_file) and count < max_count:
                backup_file = os.path.join(dirname, f"{basename}_{count:02d}.xml")
                if os.path.isfile(backup_file):
                    file_list.append((backup_file, os.path.getmtime(backup_file)))
                count+=1
            if count == max_count:
                # ran out of roundrobin option - blitz the oldest file
                file_list.sort(key = lambda x: x[1])
                backup_file = file_list[-1][0]
                os.unlink(backup_file)

            try:
               shutil.copyfile(xml_file, backup_file)
            except Exception as err:
                logging.getLogger("system").error(f"Error backing up profile to :{backup_file}\n{err}")
                self.ok_message_box("Error backing up the profile")
                return


            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.parse(xml_file, parser)

            nodes = root.xpath(f'//device') # iterate through all because we need to compare case for guid
            for node in nodes:
                tmp_guid = node.get("device-guid")
                if tmp_guid.casefold() == current_guid.casefold():
                    node.set("device-guid", new_device_guid)
                    node.set("name", new_device_name)
                    node_comment = etree.Comment(f"Substituted: [{current_guid}] {current_name} with [{new_device_guid}] {new_device_name}")
                    previous_node = node.getprevious()
                    if previous_node is not None:
                        previous_node.append(node_comment)
                    else:
                        parent_node = node.getparent()
                        parent_node.insert(0, node_comment)
                    

            try:
                # save the file
                tree = root
                out_file = xml_file
                # dirname, basename = os.path.split(xml_file)
                # out_file = os.path.join(dirname, f"sub_{basename}")
                tree.write(out_file, pretty_print=True,xml_declaration=True,encoding="utf-8")
            except Exception as err:
                logging.getLogger("system").error(f"Error writing updated profile: {out_file}\n{err}")
                self.ok_message_box("Error writing new profile")
                return
        
            # reload the profile with the new changes
            self.accept()
            self.close()

