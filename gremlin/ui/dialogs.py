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
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.types
from . import ui_about, ui_common
from gremlin.util import load_icon, userprofile_path, load_pixmap
import logging
from gremlin.input_types import InputType
import gremlin.base_profile



class OptionsUi(ui_common.BaseDialogUi):

    """UI allowing the configuration of a variety of options."""

    def __init__(self, parent=None):
        """Creates a new options UI instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()
        self.setMinimumWidth(400)

        self.setWindowTitle("Options")

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.tab_container = QtWidgets.QTabWidget()
        self.main_layout.addWidget(self.tab_container)

        self._create_general_page()
        self._create_profile_page()
        self._create_hidguardian_page()

    def _create_general_page(self):
        """Creates the general options page."""
        self.general_page = QtWidgets.QWidget()
        self.general_layout = QtWidgets.QVBoxLayout(self.general_page)

        # Highlight input option
        self.highlight_input = QtWidgets.QCheckBox(
            "Highlight currently used input (axis + buttons)"
        )
        self.highlight_input.clicked.connect(self._highlight_input)
        self.highlight_input.setChecked(self.config.highlight_input)

        # Highlight input option buttons
        self.highlight_input_buttons = QtWidgets.QCheckBox(
            "Highlight currently used buttons"
        )
        self.highlight_input_buttons.clicked.connect(self._highlight_input_buttons)
        self.highlight_input_buttons.setChecked(self.config.highlight_input_buttons)

        # Switch to highlighted device
        self.highlight_device = QtWidgets.QCheckBox(
            "Highlight swaps device tabs"
        )
        self.highlight_device.clicked.connect(self._highlight_device)
        self.highlight_device.setChecked(self.config.highlight_device)

        # Close to system tray option
        self.close_to_systray = QtWidgets.QCheckBox(
            "Closing minimizes to system tray"
        )
        self.close_to_systray.clicked.connect(self._close_to_systray)
        self.close_to_systray.setChecked(self.config.close_to_tray)

        # Activate profile on launch
        self.activate_on_launch = QtWidgets.QCheckBox(
            "Activate profile on launch"
        )
        self.activate_on_launch.clicked.connect(self._activate_on_launch)
        self.activate_on_launch.setChecked(self.config.activate_on_launch)
        self.activate_on_launch.setToolTip("When set, the last loaded profile will be automatically activated when GremlinEx starts.")

        # Restore last mode on profile activate
        self.activate_restore_mode = QtWidgets.QCheckBox(
            "Restore last used mode on profile activation"
        )
        self.activate_restore_mode.clicked.connect(self._restore_profile_mode)
        self.activate_restore_mode.setChecked(self.config.restore_profile_mode_on_start)
        self.activate_restore_mode.setToolTip("""When set, all profiles loaded will revert to the last active mode used for that profile.  This is a global setting.
This setting is also available on a profile by profile basis on the profile tab, or in the modes editor.                                              
                                              """)

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

        # verbose output
        self.verbose_container_widget = QtWidgets.QWidget()
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
        self.remote_control_layout = QtWidgets.QHBoxLayout()
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
        self.default_action_layout = QtWidgets.QHBoxLayout()
        self.default_action_label = QtWidgets.QLabel("Default action")
        self.default_action_dropdown = QtWidgets.QComboBox()
        self.default_action_layout.addWidget(self.default_action_label)
        self.default_action_layout.addWidget(self.default_action_dropdown)
        self._init_action_dropdown()
        self.default_action_layout.addStretch()

        # Macro axis polling rate
        self.macro_axis_polling_layout = QtWidgets.QHBoxLayout()
        self.macro_axis_polling_label = \
            QtWidgets.QLabel("Macro axis polling rate")
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
        self.macro_axis_minimum_change_layout = QtWidgets.QHBoxLayout()
        self.macro_axis_minimum_change_label = \
            QtWidgets.QLabel("Macro axis minimum change value")
        self.macro_axis_minimum_change_value = ui_common.DynamicDoubleSpinBox()
        self.macro_axis_minimum_change_value.setRange(0.00001, 1.0)
        self.macro_axis_minimum_change_value.setSingleStep(0.01)
        self.macro_axis_minimum_change_value.setDecimals(5)
        self.macro_axis_minimum_change_value.setValue(
            self.config.macro_axis_minimum_change_rate
        )
        self.macro_axis_minimum_change_value.valueChanged.connect(
            self._macro_axis_minimum_change_value
        )
        self.macro_axis_minimum_change_layout.addWidget(
            self.macro_axis_minimum_change_label
        )
        self.macro_axis_minimum_change_layout.addWidget(
            self.macro_axis_minimum_change_value
        )
        self.macro_axis_minimum_change_layout.addStretch()

        self.general_layout.addWidget(self.highlight_input)
        self.general_layout.addWidget(self.highlight_input_buttons)
        self.general_layout.addWidget(self.highlight_device)
        self.general_layout.addWidget(self.close_to_systray)
        self.general_layout.addWidget(self.activate_on_launch)
        self.general_layout.addWidget(self.activate_restore_mode)
        self.general_layout.addWidget(self.start_minimized)
        self.general_layout.addWidget(self.start_with_windows)
        self.general_layout.addWidget(self.persist_clipboard)
        self.general_layout.addWidget(self.verbose_container_widget)
        self.general_layout.addWidget(self.midi_enabled)
        
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        container.setLayout(layout)
        layout.addWidget(self.osc_enabled)
        layout.addWidget(QtWidgets.QLabel("Listen port number (outbound is +1)"))
        layout.addWidget(self.osc_port)
        layout.addStretch()
        layout.setContentsMargins(0,0,0,0)
        self.general_layout.addWidget(container)

        self.general_layout.addWidget(self.show_mode_change_message)

        self.general_layout.addLayout(self.default_action_layout)
        self.general_layout.addLayout(self.macro_axis_polling_layout)
        self.general_layout.addLayout(self.macro_axis_minimum_change_layout)
        self.general_layout.addLayout(self.remote_control_layout)
        self.general_layout.addWidget(self.enable_broadcast_speech)
        self.general_layout.addStretch()
        self.tab_container.addTab(self.general_page, "General")

    def _create_profile_page(self):
        """Creates the profile options page."""
        self.profile_page = QtWidgets.QWidget()
        self.profile_page_layout = QtWidgets.QVBoxLayout(self.profile_page)

        # holds the mapping of a process (.exe) to a profile (.xml)
        self._profile_mapper = gremlin.base_profile.ProfileMap()
        self._profile_map_exe_widgets = {}
        self._profile_map_xml_widgets = {}

        # Autoload profile option
        self.autoload_checkbox = QtWidgets.QCheckBox(
            "Automatically load profile based on current application"
        )
        self.autoload_checkbox.clicked.connect(self._autoload_profiles)
        self.autoload_checkbox.setChecked(self.config.autoload_profiles)

        self.keep_active_on_focus_lost_checkbox = QtWidgets.QCheckBox(
            "Keep profile active on focus loss"
        )
        self.keep_active_on_focus_lost_checkbox.setToolTip("""If this option is set, the last active profile
will remain active until a different profile is loaded.""")
        
        self.mode_restore_flag = QtWidgets.QCheckBox("Restore last mode on activation")
        
        
        self.mode_restore_flag.clicked.connect(self._profile_restore_flag_cb)
        self.mode_restore_flag.setToolTip("""When enabled, the last known active mode for this profile will be used when the profile is loaded or re-activated regardless of the default mode specified in the Modes Editor
                                          
The setting can be overriden by the global mode reload option set in Options for this profile.
""")
                                                    
        self.keep_active_on_focus_lost_checkbox.clicked.connect(self._keep_last_autoload)
        self.keep_active_on_focus_lost_checkbox.setChecked(self.config.keep_profile_active_on_focus_loss)
        self.keep_active_on_focus_lost_checkbox.setEnabled(self.config.autoload_profiles)
        self.mode_restore_flag.setChecked(gremlin.shared_state.current_profile.get_restore_mode())



        # Executable dropdown list
        self.executable_layout = QtWidgets.QHBoxLayout()
        self.executable_label = QtWidgets.QLabel("Executable")
        self.executable_selection = QtWidgets.QComboBox()
        self.executable_selection.setMinimumWidth(300)
        self.executable_selection.currentTextChanged.connect(
            self._show_executable
        )
        self.executable_add = QtWidgets.QPushButton()
        self.executable_add.setIcon(load_icon("gfx/button_add.png"))
        self.executable_add.clicked.connect(self._new_executable)
        self.executable_remove = QtWidgets.QPushButton()
        self.executable_remove.setIcon(load_icon("gfx/button_delete.png"))
        self.executable_remove.clicked.connect(self._remove_executable)
        self.executable_edit = QtWidgets.QPushButton()
        self.executable_edit.setIcon(load_icon("gfx/button_edit.png"))
        self.executable_edit.clicked.connect(self._edit_executable)
        self.executable_list = QtWidgets.QPushButton()
        self.executable_list.setIcon(load_icon("gfx/list_show.png"))
        self.executable_list.clicked.connect(self._list_executables)

        self.executable_layout.addWidget(self.executable_label)
        self.executable_layout.addWidget(self.executable_selection)
        self.executable_layout.addWidget(self.executable_add)
        self.executable_layout.addWidget(self.executable_remove)
        self.executable_layout.addWidget(self.executable_edit)
        self.executable_layout.addWidget(self.executable_list)
        self.executable_layout.addStretch()

        self.profile_layout = QtWidgets.QHBoxLayout()
        self.profile_field = QtWidgets.QLineEdit()
        self.profile_field.textChanged.connect(self._update_profile)
        self.profile_field.editingFinished.connect(self._update_profile)
        self.profile_select = QtWidgets.QPushButton()
        self.profile_select.setIcon(load_icon("gfx/button_edit.png"))
        self.profile_select.clicked.connect(self._select_profile)

        self.profile_layout.addWidget(self.profile_field)
        self.profile_layout.addWidget(self.profile_select)

        self.profile_page_layout.addWidget(self.autoload_checkbox)
        self.profile_page_layout.addWidget(self.keep_active_on_focus_lost_checkbox)
        # self.profile_page_layout.addLayout(self.executable_layout)
        # self.profile_page_layout.addLayout(self.profile_layout)




        self.tab_container.addTab(self.profile_page, "Profiles")


        # profile map widgets

        self.container_map_widget = QtWidgets.QWidget()
        self.container_map_layout = QtWidgets.QVBoxLayout()
        self.container_map_widget.setLayout(self.container_map_layout)

        
        


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

        container_footer_widget = QtWidgets.QWidget()
        container_footer_layout = QtWidgets.QHBoxLayout()
        container_footer_widget.setLayout(container_footer_layout)
        

        add_map_widget = QtWidgets.QPushButton("Add mapping")
        add_map_widget.setIcon(load_icon("gfx/button_add.png"))
        add_map_widget.clicked.connect(self._add_profile_map_cb)

        save_map_widget = QtWidgets.QPushButton("Save")
        save_map_widget.setIcon(load_icon("fa.save"))
        save_map_widget.clicked.connect(self._save_map_cb)




        self.profile_page_layout.addWidget(container_bar_widget)
        container_bar_layout.addWidget(QtWidgets.QLabel("Profile to process map:"))
        container_bar_layout.addStretch()
        container_bar_layout.addWidget(add_map_widget)

        container_footer_layout.addStretch()
        container_footer_layout.addWidget(save_map_widget)

        self.profile_page_layout.addWidget(container_bar_widget)
        self.profile_page_layout.addWidget(self.container_map_widget)
        self.profile_page_layout.addWidget(container_footer_widget)
        self.profile_page_layout.addStretch()

        self.populate_executables()

        
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
                self.hg_device_layout.addWidget(
                    QtWidgets.QLabel(dev.name), i+1, 0
                )
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

    def populate_executables(self, executable_name=None):
        """Populates the profile drop down menu.

        :param executable_name name of the executable to pre select
        """
        self.profile_field.textChanged.disconnect(self._update_profile)
        self.executable_selection.clear()
        executable_list = self.config.get_executable_list()
        for path in executable_list:
            self.executable_selection.addItem(path)
        self.profile_field.textChanged.connect(self._update_profile)

        # Select the provided executable if it exists, otherwise the first one
        # in the list
        index = 0
        if executable_name is not None and executable_name in executable_list:
            index = self.executable_selection.findText(executable_name)
        self.executable_selection.setCurrentIndex(index)

    def _profile_restore_flag_cb(self, clicked):
        ''' called when the restore last mode checked state is changed '''
        self.config.current_profile.set_restore_mode(clicked)

    def _autoload_profiles(self, clicked):
        """Stores profile autoloading preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.keep_active_on_focus_lost_checkbox.setEnabled(clicked)
        self.config.autoload_profiles = clicked
        self.config.save()

    def _keep_last_autoload(self, clicked):
        """Stores keep last autoload preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.keep_last_autoload = clicked
        self.config.save()

    def _activate_on_launch(self, clicked):
        """Stores activation of profile on launch preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.activate_on_launch = clicked
        self.config.save()

    def _restore_profile_mode(self, clicked):
        self.config.restore_profile_mode_on_start = clicked
        self.config.save()

    def _close_to_systray(self, clicked):
        """Stores closing to system tray preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.close_to_tray = clicked
        self.config.save()

    def _start_minimized(self, clicked):
        """Stores start minimized preference.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.start_minimized = clicked
        

    def _persist_clipboard(self, clicked):
        self.config.persist_clipboard = clicked
        

    def _persist_clipboard_enabled(self):
        return self.config.persist_clipboard
    
    def _verbose_cb(self, clicked):
        ''' stores verbose setting '''
        self.config.verbose = clicked
        for widget in self._verbose_mode_widgets.values():
            widget.setEnabled(clicked)

    def _verbose_set_cb(self):
        # is_checked = self._verbose_mode_widgets[mode].isChecked()
        widget = self.sender()
        mode = widget.data
        is_checked = widget.isChecked()
        self.config.verbose_set_mode(mode, is_checked)

    def _midi_enabled(self, clicked):
        self.config.midi_enabled = clicked
        

    def _osc_enabled(self, clicked):
        self.config.osc_enabled = clicked
        self.osc_port.setEnabled(clicked)
        

    def _osc_port(self):
        self.config.osc_port = self.osc_port.value()
        


    def _start_windows(self, clicked):
        """Set registry entry to launch Joystick Gremlin on login.

        :param clicked True if launch should happen on login, False otherwise
        """
        if clicked:
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
    



    def _highlight_input(self, clicked):
        """Stores preference for input highlighting.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.highlight_input = clicked
        self.config.save()

    def _highlight_input_buttons(self, clicked):
        """Stores preference for input highlighting (buttons).

        :param clicked whether or not the checkbox is ticked
        """
        self.config.highlight_input_buttons = clicked
        self.config.save()

        


    def _highlight_device(self, clicked):
        """Stores preference for device highlighting.

        :param clicked whether or not the checkbox is ticked
        """
        self.config.highlight_device = clicked
        self.config.save()

    def _list_executables(self):
        """Shows a list of executables for the user to pick."""
        self.executable_list_view = ProcessWindow()
        self.executable_list_view.process_selected.connect(self._add_executable)
        self.executable_list_view.show()

    def _add_executable(self, fname):
        """Adds the provided executable to the list of configurations.

        :param fname the executable for which to add a mapping
        """
        if fname not in self.config.get_executable_list():
            self.config.set_profile(fname, "")
            self.populate_executables(fname)
        else:
            self.executable_selection.setCurrentIndex(
                self.executable_selection.findText(fname)
            )

    def _edit_executable(self):
        """Allows editing the path of an executable."""
        new_text, flag = QtWidgets.QInputDialog.getText(
            self,
            "Change Executable / RegExp",
            "Change the executable text or enter a regular expression to use.",
            QtWidgets.QLineEdit.Normal,
            self.executable_selection.currentText()
        )

        # If the user did click on ok update the entry
        old_entry = self.executable_selection.currentText()
        if flag:
            if old_entry not in self.config.get_executable_list():
                self._add_executable(new_text)
            else:
                self.config.set_profile(
                    new_text,
                    self.config.get_profile(old_entry)
                )
                self.config.remove_profile(old_entry)
                self.populate_executables(new_text)

    def _new_executable(self):
        """Prompts the user to select a new executable to add to the
        profile.
        """
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Path to executable",
            "C:\\",
            "Executable (*.exe)"
        )
        if fname != "":
            self._add_executable(fname)

    def _remove_executable(self):
        """Removes the current executable from the configuration."""
        self.config.remove_profile(self.executable_selection.currentText())
        self.populate_executables()

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

    def _show_executable(self, exec_path):
        """Displays the profile associated with the given executable.

        :param exec_path path to the executable to shop
        """
        self.profile_field.setText(self.config.get_profile(exec_path))

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


    
    def _add_profile_map_cb(self):
        ''' adds a new profile mapping '''
        item = gremlin.base_profile.ProfileMapItem()
        self._profile_mapper.register(item)
        self.populate_map()

    def _save_map_cb(self):
        ''' saves the current mappings '''
        self.save_profile_map()

    def populate_map(self):
        ''' populates the map of executables to profiles '''

        
        for widget in self._profile_map_exe_widgets.values():
            if widget:
                widget.setParent(None)
        for widget in self._profile_map_xml_widgets.values():
            if widget:
                widget.setParent(None)

        self._profile_map_exe_widgets = {}
        self._profile_map_xml_widgets = {}

        # clear the widgets
        ui_common.clear_layout(self.map_layout)

        if not self._profile_mapper:
             missing = QtWidgets.QLabel("No mappings found.")
             missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
             self.map_layout.addWidget(missing, 0, 0)
             return

        item: gremlin.base_profile.ProfileMapItem
        for index, item in enumerate(self._profile_mapper.items()):

            exe_widget = None
            xml_widget = None
            
            if item:
                # add a new item if it exists and either one of the profile/process entries are refined

                exe_widget = ui_common.QPathLineItem(item.process, item)
                exe_widget.pathChanged.connect(self._process_changed_cb)
                exe_widget.open.connect(self._process_open_cb)
                self.map_layout.addWidget(exe_widget, index, 0)
                
                xml_widget = ui_common.QPathLineItem(item.profile, item)
                xml_widget.pathChanged.connect(self._profile_changed_cb)
                xml_widget.open.connect(self._profile_open_cb)
                self.map_layout.addWidget(xml_widget, index, 1)

                clear_button = ui_common.QDataPushButton()
                clear_button.setIcon(load_icon("mdi.delete"))
                clear_button.setMaximumWidth(20)
                clear_button.data = item
                clear_button.clicked.connect(self._mapping_delete_cb)
                self.map_layout.addWidget(clear_button, index, 2)

                item.index = index

            self._profile_map_exe_widgets[index] = exe_widget
            self._profile_map_xml_widgets[index] = xml_widget


    def _process_open_cb(self, widget):
        ''' opens the process executable '''
        self.executable_list_view = ProcessWindow()
        self.executable_list_view.data = widget
        self.executable_list_view.process_selected.connect(self._select_executable)
        self.executable_list_view.show()        

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
        
        
            
    def _mapping_delete_cb(self):
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
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_confirmed_cb(item)

    def _delete_confirmed_cb(self, item):
        self._profile_mapper.remove(item)
        self.populate_map()

    def _process_changed_cb(self, widget, text):
        ''' called when the process path changes '''
        item = widget.data
        item.process = text if widget.valid else None

    def _profile_changed_cb(self, widget, text):
        ''' called when the profile '''
        item = widget.data
        item.profile = text if widget.valid else None

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

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of the widget
        """
        super().__init__(parent)

        self.setWindowTitle("Process List")
        self.setMinimumWidth(400)
        self.setMinimumHeight(600)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.list_model = QtCore.QStringListModel()
        self.list_model.setStringList(
            gremlin.process_monitor.list_current_processes()
        )
        self.list_view = QtWidgets.QListView()
        self.list_view.setModel(self.list_model)
        self.list_view.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.list_view.doubleClicked.connect(self._select)

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

        self.button_bar_layout.addWidget(self.refresh_button)
        self.button_bar_layout.addWidget(self.select_button)
        self.button_bar_layout.addWidget(self.browse_button)

        self.main_layout.addWidget(self.button_bar_widget)


        # optional data item to track for this item
        self._data = None

    def _refresh(self):
        self.list_model.setStringList(
            gremlin.process_monitor.list_current_processes()
        )

    def _select(self):
        """Emits the process_signal when the select button is pressed."""
        self.process_selected.emit(self.list_view.currentIndex().data())
        self.close()

    def _browse(self):
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

    # Signal emitted when mode configuration changes
    modes_changed = QtCore.Signal()

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

        self.main_layout.addWidget(self.scroll_area)
        self.add_button = QtWidgets.QPushButton("Add Mode")
        self.add_button.clicked.connect(self._add_mode_cb)

        label = QtWidgets.QLabel(
            "Modes are by default self contained configurations. Specifying "
            "a parent for a mode causes the the mode \"inherits\" all actions "
            "defined in the parent, unless the mode configures its own actions "
            "for specific inputs."
        )
        label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
        label.setWordWrap(True)
        label.setFrameShape(QtWidgets.QFrame.Box)
        label.setMargin(10)
        self.scroll_layout.addWidget(label)

        self.scroll_layout.addWidget(self.add_button)

        self._populate_mode_layout()

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

        # Obtain mode names and the mode they inherit from
        mode_list = self._get_mode_list()

        # Add header information
        self.mode_layout.addWidget(QtWidgets.QLabel("<b>Name</b>"), 0, 0)
        self.mode_layout.addWidget(QtWidgets.QLabel("<b>Parent</b>"), 0, 1)

        self.mode_default_selector = QtWidgets.QComboBox()
        self.mode_default_selector.setToolTip("Specifies the default startup mode for this profile when it is loaded. This setting can be overriden if the restore last active mode option is set.")
        

        # Create UI element for each mode
        row = 1
        for mode, inherit in sorted(mode_list.items()):
            self.mode_layout.addWidget(QtWidgets.QLabel(mode), row, 0)
            self.mode_dropdowns[mode] = QtWidgets.QComboBox()
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
                load_icon("button_edit.png"), ""
            )
            self.mode_layout.addWidget(self.mode_rename[mode], row, 2)
            self.mode_rename[mode].clicked.connect(
                self._create_rename_mode_cb(mode)
            )
            # Delete mode button
            self.mode_delete[mode] = QtWidgets.QPushButton(
                load_icon("mode_delete.svg"), ""
            )
            self.mode_layout.addWidget(self.mode_delete[mode], row, 3)
            self.mode_delete[mode].clicked.connect(
                self._create_delete_mode_cb(mode)
            )

            self.mode_layout.addWidget(self.mode_dropdowns[mode], row, 1)
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

        self.container_default_layout.addWidget(QtWidgets.QLabel("Profile start mode:"))
        self.container_default_layout.addWidget(self.mode_default_selector)
        self.container_default_layout.addStretch()
        self.mode_layout.addWidget(self.container_default_widget, row, 0, 1, -1)
        row += 1


        mode = gremlin.shared_state.current_profile.get_start_mode()
        self.mode_default_selector.setCurrentText(mode)
        self.mode_default_selector.currentIndexChanged.connect(self._change_default_mode_cb)

        # add the default flag
        self.mode_layout.addWidget(self.mode_restore_flag, row, 0, 1, -1)

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
            self.modes_changed.emit()

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

                    # Update inheritance information
                    for mode in device.modes.values():
                        if mode.inherit == mode_name:
                            mode.inherit = name

                # rename the startup mode if it's the same
                if mode_name == gremlin.shared_state.current_profile.get_start_mode():
                    gremlin.shared_state.current_profile.set_start_mode(name)

                self.modes_changed.emit()

            self._populate_mode_layout()

    def _delete_mode(self, mode_name):
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

        # Update the ui
        self._populate_mode_layout()
        self.modes_changed.emit()

    def _add_mode_cb(self, checked):
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
                self.modes_changed.emit()

            self._populate_mode_layout()

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
