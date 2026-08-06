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
import threading

from PySide6 import QtWidgets, QtCore
from PySide6.QtWidgets import QColorDialog
from PySide6.QtGui import QColor

import dinput
from lxml import etree as ElementTree


import gremlin.actions
import gremlin.base_profile
import gremlin.event_handler
import gremlin.config
from gremlin.input_types import InputType
import gremlin.input_item
from enum import IntEnum
from gremlin.util import safe_read, safe_format, to_guid, delete_widget
import gremlin.ui.ui_common
import time
import os
import subprocess
import logging
from shiboken6 import Shiboken
import subprocess
import gremlin.joystick_handling
from dinput import DeviceSummary
import gremlin.ui.ui_common
from typing import Callable


syslog = logging.getLogger("system")

VIRPIL_VENDOR_ID = 0x3344  # HID code for Virpil controllers


class VirpilButtonType(IntEnum):
    # Virpil LED buttons indices
    ButtonB1 = 6
    ButtonB2 = 5
    ButtonB3 = 6
    ButtonB4 = 7

    ButtonB5 = 21
    ButtonB6 = 18
    ButtonB7 = 20
    ButtonB8 = 17
    ButtonB9 = 19
    B10 = 16

    # flight buttons
    Top = 9
    Middle = 10
    FlapsLeft = 11
    GearLeft = 12
    GearMiddle = 13
    GearRight = 14
    FlapsRight = 15

    # control panel 1
    Control1B1 = 16
    Control1B2 = 13
    Control1B3 = 15
    Control1B4 = 12
    Control1B5 = 14
    Control1B6 = 11

    Control1B7 = 8
    Control1B8 = 9
    Control1B9 = 10
    Control1B10 = 5
    Control1B11 = 6
    Control1B12 = 7

    # throttle buttons
    ThrottleB1 = 5
    ThrottleB2 = 6
    ThrottleB3 = 7
    ThrottleB4 = 8
    ThrottleB5 = 9
    ThrottleB6 = 10

    # stick buttons
    StickB1 = 1

    @staticmethod
    def from_string(value: str):
        value = value.casefold()
        result = next((btn for btn in VirpilButtonType if btn.name.casefold() == value), None)
        if result is not None:
            return result
        return result

    @staticmethod
    def to_string(value: VirpilButtonType):
        return value.name.casefold()


class VirpilOutputMode(IntEnum):
    """action behavior when triggered"""

    Hold = 0
    Toggle = 1
    Pulse = 2

    @staticmethod
    def from_string(value: str) -> "VirpilOutputMode":
        match value.casefold():
            case "hold":
                return VirpilOutputMode.Hold
            case "toggle":
                return VirpilOutputMode.Toggle
            case "pulse":
                return VirpilOutputMode.Pulse
            case _:
                raise ValueError(f"Unknown VirpilOutputMode: {value}")

    @staticmethod
    def to_string(value: "VirpilOutputMode") -> str:
        match value:
            case VirpilOutputMode.Hold:
                return "hold"
            case VirpilOutputMode.Toggle:
                return "toggle"
            case VirpilOutputMode.Pulse:
                return "pulse"
            case _:
                raise ValueError(f"Unknown VirpilOutputMode: {value}")

    @staticmethod
    def to_description(value: "VirpilOutputMode") -> str:
        match value:
            case VirpilOutputMode.Hold:
                return "The action is active while the button is held down."
            case VirpilOutputMode.Toggle:
                return "The action toggles on and off with each button press."
            case VirpilOutputMode.Pulse:
                return "The action triggers a brief pulse when the button is pressed."
            case _:
                raise ValueError(f"Unknown VirpilOutputMode: {value}")


class VirpilIntensity(IntEnum):
    """Virpil button intensity levels"""

    Off = 0
    Low = 1
    Mid = 2
    Max = 3

    @staticmethod
    def from_string(value: str) -> "VirpilIntensity":
        match value.casefold():
            case "off":
                return VirpilIntensity.Off
            case "low":
                return VirpilIntensity.Low
            case "mid":
                return VirpilIntensity.Mid
            case "max":
                return VirpilIntensity.Max
            case _:
                raise ValueError(f"Unknown VirpilButtonMode: {value}")

    @staticmethod
    def to_string(value: "VirpilIntensity") -> str:
        match value:
            case VirpilIntensity.Off:
                return "off"
            case VirpilIntensity.Low:
                return "low"
            case VirpilIntensity.Mid:
                return "mid"
            case VirpilIntensity.Max:
                return "max"
            case _:
                raise ValueError(f"Unknown VirpilButtonMode: {value}")


class VirpilButtonChannel(IntEnum):
    """Virpil button LED color channels"""

    Red = 0
    Green = 1
    Blue = 2

    @staticmethod
    def from_string(value: str) -> "VirpilButtonChannel":
        match value.casefold():
            case "red":
                return VirpilButtonChannel.Red
            case "green":
                return VirpilButtonChannel.Green
            case "blue":
                return VirpilButtonChannel.Blue
            case _:
                raise ValueError(f"Unknown VirpilButtonChannel: {value}")

    @staticmethod
    def to_string(value: "VirpilButtonChannel") -> str:
        match value:
            case VirpilButtonChannel.Red:
                return "red"
            case VirpilButtonChannel.Green:
                return "green"
            case VirpilButtonChannel.Blue:
                return "blue"
            case _:
                raise ValueError(f"Unknown VirpilButtonChannel: {value}")


class VirpilButton:
    """holds a button definition for a Virpil LED action"""

    tag = "virpil-button"

    def __init__(
        self, index: int = -1, device: DeviceSummary = None, mode: VirpilIntensity = None, channel: VirpilButtonChannel = None, led: VirpilButtonType = None
    ):
        self.id = gremlin.util.get_guid()  # unique ID
        self.device: DeviceSummary = device  # device reference
        # self.mode: VirpilIntensity = mode
        # self.channel: VirpilButtonChannel = channel
        self.led: VirpilButtonType = led

        self.rgb: int = 0

        self.index: int = index

    def hexToRGB(self, hex: str):
        hex = hex.lstrip("#")
        r = int(hex[0:2], 16)
        g = int(hex[2:4], 16)
        b = int(hex[4:6], 16)
        return r, g, b

    def hexToInt(self, hex: str):
        hex = hex.lstrip("#")
        r = int(hex[0:2], 16)
        g = int(hex[2:4], 16)
        b = int(hex[4:6], 16)
        return self.rgbToInt(r, g, b)

    def rgbToInt(self, r, g, b):
        # Pack R, G, and B into a 24-bit integer
        return (r << 16) + (g << 8) + b

    def _clamped_level(self, value: int):
        """clamps a component value 0..255 to the corresponding VirpilIntensity level"""
        if value == 0:
            return VirpilIntensity.Off
        elif value <= 76:  # int(255 * 0.3):  # 76
            return VirpilIntensity.Low
        elif value <= 153:  # int(255 * 0.6):  # 153
            return VirpilIntensity.Mid
        else:
            return VirpilIntensity.Max

    def _clamped_value(self, value: int):
        if value == 0:
            return 0  # VirpilIntensity.Off
        elif value <= 76:  # int(255 * 0.3):  # 76
            return 76  # VirpilIntensity.Low
        elif value <= 153:  # int(255 * 0.6):  # 153
            return 153  # VirpilIntensity.Mid
        else:
            return 255  # VirpilIntensity.Max

    def _clamp_channel(self, value: int, level: VirpilIntensity):
        """clamp a channel to virpil intensity levels"""
        # Map intensity levels to maximum allowed percentage thresholds
        thresholds = {
            VirpilIntensity.Off: 0.0,  # Off:   0%
            VirpilIntensity.Low: 0.3,  # Low:  30%
            VirpilIntensity.Mid: 0.6,  # Mid:  60%
            VirpilIntensity.Max: 1.0,  # Max: 100%
        }

        # Fallback to 100% if an invalid level is provided
        percentage = thresholds.get(level, 1.0)

        # Calculate the upper limit for a standard 8-bit channel (0-255)
        value = int(255 * percentage)
        return min(max(value, 0), value)

    def _clamp_to_level(self, r, g, b, level: VirpilIntensity):
        rc = VirpilButton._clamp_channel(r, level)
        gc = VirpilButton._clamp_channel(g, level)
        bc = VirpilButton._clamp_channel(b, level)
        return rc, gc, bc

    def _clamp_rgb(self, r, g, b):
        rc = self._clamped_value(r)
        gc = self._clamped_value(g)
        bc = self._clamped_value(b)
        return rc, gc, bc

    def _int_to_rgb(self, rgb_int: int) -> tuple[int, int, int]:
        # Extract R, G, and B back using bit shifts and a mask
        r = (rgb_int >> 16) & 255
        g = (rgb_int >> 8) & 255
        b = rgb_int & 255
        return self._clamp_rgb(r, g, b)

    def to_xml(self):
        node = ElementTree.Element(self.tag)
        # node.set("mode", VirpilIntensity.to_string(self.mode))
        # node.set("channel", VirpilButtonChannel.to_string(self.channel))
        node.set("led", VirpilButtonType.to_string(self.led))
        node.set("index", safe_format(self.index, int))
        node.set("guid", safe_format(self.id, str))
        node.set("rgb", safe_format(self.rgb, int))
        return node

    def from_xml(self, node):
        assert node.tag == VirpilButton.tag, f"Expected tag {VirpilButton.tag} but got {node.tag}"
        self.led = VirpilButtonType.from_string(safe_read(node, "led", str, "buttonb1"))
        # self.mode = VirpilIntensity.from_string(safe_read(node, "mode", str, "off"))
        # self.channel = VirpilButtonChannel.from_string(safe_read(node, "channel", str, "red"))
        self.index = safe_read(node, "index", int, -1)
        self.id = safe_read(node, "guid", str, gremlin.util.get_guid())
        self.rgb = safe_read(node, "rgb", int, 0)

    def getRGB(self) -> tuple[int, int, int]:
        """gets the clamped RGB value from any RGB color"""
        return self._int_to_rgb(self.rgb)  # clamped value per channel

    def __hash__(self):
        return hash(self.id)


class VirpilActionModel(gremlin.input_item.AbstractCallbackModel):
    """holds a list of button definitions to trigger by the action"""

    tag = "virpil-action-model"

    def __init__(self, action_data: VirpilAction, parent=None):
        super().__init__(model_description="virpil led map")
        self.action_data = action_data

    def add(self, button: VirpilButton, index: int = -1):
        super().add(button, index=index)
        button.index = index
        syslog.info(f"added button, new count: {len(self)}")

    def to_xml(self):
        node = ElementTree.Element(VirpilActionModel.tag)
        for button in self:
            node.append(button.to_xml())
        return node

    def from_xml(self, node):
        self.clear()
        assert node.tag == VirpilActionModel.tag, f"Expected tag {VirpilActionModel.tag} but got {node.tag}"

        # read buttons and sort by definition order
        buttons = []
        for child in node:
            data = VirpilButton()
            data.from_xml(child)
            buttons.append(data)
        if buttons:
            buttons.sort(key=lambda x: x.index)
        for button in buttons:
            self.add(button, index=button.index)


class VirpilButtonWidget(QtWidgets.QWidget):
    """displays a virpil button selector"""

    def __init__(self, action_data: VirpilAction, button_data: VirpilButton, index: int = -1, delete_callback: Callable = None, parent=None):
        super().__init__(parent)

        self.action_data = action_data
        self.delete_callback = delete_callback
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.button_data = button_data
        self.index: int = index  # index in the list
        self.selected: bool = False  # true if selected

        main_widgets = ["LED:"]

        # button type selector
        items = [(led.name, led) for led in VirpilButtonType]
        self.button_selector = gremlin.ui.ui_common.QDataComboBox(
            source=items, tooltip="Virpil Button Selector", value=self.button_data.led, callback=self._handle_led_changed
        )
        self.button_selector.setWidthToContent()
        main_widgets.append(self.button_selector)

        # color

        self.current_color_widget = QtWidgets.QLabel("     ")
        self.current_color_widget.setFixedWidth(50)
        self._update_color()

        self.color_widget = gremlin.ui.ui_common.QDataPushButton("Select Color", callback=self._handle_get_color)
        main_widgets.append(self.current_color_widget)
        main_widgets.append(self.color_widget)

        if delete_callback is not None:
            delete_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback=self._handle_delete)
            main_widgets.append(delete_widget)

        widget = gremlin.ui.ui_common.getHContainer(main_widgets, widget_only=True, no_stretch=True)
        self.main_layout.addWidget(widget)

    def _handle_get_color(self):
        color = QColor.fromRgb(self.button_data.rgb)
        dialog = QColorDialog.getColor(initial=color, parent=self, title="Select a Color")
        if dialog.isValid():
            rgb = dialog.rgb()
            self.button_data.rgb = rgb
            self._update_color()

    def _update_color(self):
        color = QColor.fromRgb(self.button_data.rgb)
        border_color = gremlin.ui.ui_common.Color.borderColor()
        self.current_color_widget.setStyleSheet(f".QLabel {{ background-color: {color.name()}; border: 4px solid {border_color}; }}")

    def _handle_delete(self):
        """handles the delete button click"""
        # Implement the delete functionality here
        if self.delete_callback:
            self.delete_callback(self)

    def _handle_led_changed(self, new_led: VirpilButtonType):
        self.button_data.led = new_led

    def _handle_mode_changed(self, new_mode: VirpilIntensity):
        self.button_data.mode = new_mode

    def _handle_channel_changed(self, new_channel: VirpilButtonChannel):
        self.button_data.channel = new_channel


class VirpilExecutableDialog(QtWidgets.QDialog):
    def __init__(self, action_data: VirpilAction, parent=None):
        super().__init__(parent)
        self.action_data = action_data
        self.setWindowTitle("Select Virpil Executable")
        self.layout = QtWidgets.QVBoxLayout(self)
        self.file_path_widget = gremlin.ui.ui_common.QLineEdit(
            update_on_text_change=True, text=action_data.virpil_executable, callback=self._handle_executable_changed, tooltip="Path to Virpil LED executable"
        )
        self.file_path_widget.setMinimumWidth(300)

        self.setMinimumWidth(500)

        self.edit_path_widget = gremlin.ui.ui_common.Buttons.getFolderWidget(callback=self._get_executable)

        self.layout.addWidget(QtWidgets.QLabel("Virpil Executable: (VPC_LED_Control.exe)"))
        widget = gremlin.ui.ui_common.getHContainer([(self.file_path_widget, 100), self.edit_path_widget], widget_only=True)
        self.layout.addWidget(widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True, widget_only=True)
        self.layout.addWidget(widget)

    @QtCore.Slot()
    def _ok_button_cb(self):
        """ok button pressed"""
        exe = self.file_path_widget.text()
        if os.path.isfile(exe):
            self.action_data.virpil_executable = self.file_path_widget.text()
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(self, "Invalid Executable", "The specified Virpil LED executable does not exist.")

    @QtCore.Slot()
    def _cancel_button_cb(self):
        """cancel button pressed"""
        self.reject()

    def _handle_executable_changed(self, new_path):
        found = os.path.isfile(self.file_path_widget.text())
        self.ok_widget.setEnabled(found)

    def _get_executable(self):
        file_dialog = QtWidgets.QFileDialog(self)
        file_dialog.setWindowTitle("Select Virpil LED Executable")
        exe = self.action_data.virpil_executable
        if exe:
            dirname = os.path.dirname(exe)
            if os.path.isdir(dirname):
                file_dialog.setDirectory(dirname)

        file_dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        if file_dialog.exec_():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.file_path_widget.setText(selected_files[0])


class VirpilActionWidget(gremlin.input_item.AbstractActionWidget):
    """Widget for the Virpil LED action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, VirpilAction)

    def _create(self, action_data):
        self.action_data: VirpilAction = action_data

    def display_name(self):
        """returns a display string for the current configuration"""
        return "Virpil Action"

    def _create_ui(self):

        warning_widget = gremlin.ui.ui_common.QWarningWidget("This action is an experimental Feature.")
        self.main_layout.addWidget(warning_widget)

        items = [(dev.name, dev) for dev in self.action_data.device_map.values()]
        self._widget_map = {}  # holds the button widgets in the list, indexed by the display order

        self.device_selector = gremlin.ui.ui_common.QDataComboBox(
            source=items, tooltip="Virpil Device Selector", value=self.action_data.device, callback=self._handle_device_changed
        )

        self.configure_executable_widget = gremlin.ui.ui_common.QIconPushButton(
            icon=gremlin.ui.ui_common.Icons.gearIcon(), tooltip="Configure Options", callback=self._handle_configure, height=24, width=24, icon_size=18
        )

        self.main_layout.addWidget(self.configure_executable_widget)

        # action mode
        widgets = ["Trigger Mode:"]
        modes = [(mode.name, mode) for mode in VirpilOutputMode]
        for name, mode in modes:
            widget = gremlin.ui.ui_common.QDataRadioButton(
                name, data=mode, value=mode == self.action_data.output_mode, callbackEx=self._handle_mode_changed, tooltip=VirpilOutputMode.to_description(mode)
            )
            widgets.append(widget)

        widgets.append(self.configure_executable_widget)  # configure button

        self.output_mode_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(value=self.action_data.pulse_duration, callback=self._handle_delay_changed)

        self.view_widget = QtWidgets.QListWidget()
        self.view_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.view_widget.setMinimumHeight(300)
        self.add_widget = gremlin.ui.ui_common.Buttons.getAddWidget(callback=self._handle_add)

        self.test_widget = gremlin.ui.ui_common.Buttons.getPlayWidget(callback=self._handle_test)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self.main_layout.addWidget(self.output_mode_widget)
        self.main_layout.addWidget(self.device_selector)

        self.main_layout.addWidget(self.view_widget)

        # button bar
        widgets = [self.add_widget, self.test_widget]
        container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.main_layout.addWidget(container)

        # delay widget
        self.pulse_container_widget = gremlin.ui.ui_common.getHContainer(["Pulse Duration (ms):", self.delay_widget], widget_only=True)
        self.main_layout.addWidget(self.pulse_container_widget)

        self.main_layout.addWidget(self._execute_widget)

        self._update_view_widget()  # load the items

        self._update()

    def _handle_configure(self):
        dialog = VirpilExecutableDialog(self.action_data, parent=self)
        dialog.exec_()

    def _update_view_widget(self):
        self.view_widget.clear()
        for widget in self._widget_map.values():
            delete_widget(widget)
        self._widget_map.clear()
        for index, button in enumerate(self.action_data.model):
            widget = VirpilButtonWidget(self.action_data, button, delete_callback=self._handle_delete, index = index)
            item = QtWidgets.QListWidgetItem()
            self.view_widget.addItem(item)
            self.view_widget.setItemWidget(item, widget)
            size = widget.sizeHint()  # get the size hint of the widget
            item.setSizeHint(size)  # size to fit the widget
            self._widget_map[index] = widget

    def _update(self):
        pulse_visible = self.action_data.output_mode == VirpilOutputMode.Pulse
        self.pulse_container_widget.setVisible(pulse_visible)

    def _handle_test(self):
        if self.action_data.device and self.action_data.device.enabled:
            for button in self.action_data.model:
                r, g, b = button.getRGB()
                self.action_data.setState(r, g, b, button.led)


    def _handle_delay_changed(self, value: int):
        self.action_data.pulse_duration = value

    def _handle_executable_changed(self):
        fname = self.file_path_widget.text()
        valid = os.path.isfile(fname)
        if valid:
            self._setIcon("mdi.checkbox-marked-outline", color=gremlin.ui.ui_common.Color.activeColor())
            self.action_data.virpil_executable = self.action_data.virpil_executable  # force a reload at next play
            self._populate_ui()
        else:
            self._setIcon("fa6s.circle-exclamation", color="red")

    @QtCore.Slot()
    def _get_executable(self):
        """Prompts the user to select the virpil LED executable"""
        fname = self.file_path_widget.text()  # current entry
        if os.path.isfile(fname):
            dir = fname
        else:
            dir = self.action_data.virpil_executable
            if dir is None or not os.path.isfile(dir):
                dir = gremlin.shared_state.data_path
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(None, "Path to Virpil LED executable", dir, "Executable files (*.exe)")
        if os.path.isfile(fname):
            self.action_data.virpil_executable = fname
            gremlin.config.Configuration().virpil_led_executable = fname
            self._populate_ui()

    def _handle_add(self):
        button = VirpilButton(
            index=len(self.action_data.model),
            device=self.action_data.device,
            mode=VirpilIntensity.Max,
            channel=VirpilButtonChannel.Blue,
            led=VirpilButtonType.ButtonB1,
        )
        self.action_data.model.add(button)
        self._update_view_widget()

    def _handle_delete(self, widget: VirpilButtonWidget)        :
        index = widget.index
        if index != -1:
            self.action_data.model.removeAt(index)
            self._update_view_widget()

    def _handle_mode_changed(self, widget: VirpilButtonWidget, checked : bool):
        if checked:
            mode: VirpilIntensity = widget.data
            self.action_data.mode = mode

    def _handle_device_changed(self, device : dinput.DeviceSummary):
        self.action_data.device = device

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        self.action_data.exec_on_release = checked

    def _populate_ui(self):

        pass


class VirpilActionFunctor(gremlin.base_profile.AbstractFunctor):
    def __init__(self, action_data: VirpilAction, parent=None):
        super().__init__(action_data, parent)
        self.action_data = action_data
        self._toggle_state = False
        self._valid = action_data.device and action_data.device.enabled
        self._pulse_timer = None

    def profile_start(self):
        self._valid = self.action_data.device and self.action_data.device.enabled
        if self._valid:
            self._turn_off_leds()



    def profile_stop(self):
        if self._pulse_timer is not None:
            self._pulse_timer.cancel()
            self._pulse_timer = None
            if self._valid:
                self._turn_off_leds()


    def process_event(self, event: gremlin.event_handler.Event, value: gremlin.actions.Value, extra_data=None):

        if not self._valid:
            # no valid output device
            return False
        is_pressed = event.is_pressed
        trigger = self.action_data.exec_on_press and is_pressed or self.action_data.exec_on_release and not is_pressed

        button: VirpilButton
        mode = self.action_data.output_mode


        match mode:
            case VirpilOutputMode.Hold:
                for button in self.action_data.model:
                    if trigger:
                        r, g, b = button.getRGB()
                    else:
                        # turn off
                        r, g, b = 0, 0, 0

                    self.action_data.setState(r, g, b, button.led)
            case VirpilOutputMode.Pulse:
                if trigger:
                    for button in self.action_data.model:
                        r, g, b = button.getRGB()
                        self.action_data.setState(r, g, b, button.led)
                    self._pulse_timer = threading.Timer(self.action_data.pulse_duration / 1000.0, self._turn_off_leds)
                    self._pulse_timer.start()

                # no further action needed here as the timer will handle turning off the LEDs
            case VirpilOutputMode.Toggle:
                if trigger:
                    self._toggle_state = not self._toggle_state
                    if self._toggle_state:
                        for button in self.action_data.model:
                            r, g, b = button.getRGB()
                            self.action_data.setState(r, g, b, button.led)
                    else:
                        for button in self.action_data.model:
                            self.action_data.setState(0, 0, 0, button.led)

        return True

    def _turn_off_leds(self):
        if self._valid:
            for button in self.action_data.model:
                self.action_data.setState(0, 0, 0, button.led)


class VirpilAction(gremlin.input_item.AbstractAction):
    """Action for pausing the execution of callbacks."""

    name = "Virpil LED"
    tag = "virpil-led"
    hint = "Virpil LED action plugin."

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, False)

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    functor = VirpilActionFunctor
    widget = VirpilActionWidget

    def __init__(self, parent, extra_data: dict = None):
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent
        self.device_map = self.getDeviceMap()

        self.virpil_executable = gremlin.config.Configuration().virpil_led_executable
        invalid_device = gremlin.joystick_handling.getInvalidDevice()
        self.device: DeviceSummary = invalid_device
        self.model = VirpilActionModel(self)
        self.output_mode: VirpilOutputMode = VirpilOutputMode.Hold
        self.pulse_duration: int = 1000  # duration of the pulse in milliseconds
        self.exec_on_press = True  # true if trigger should execute on input press event
        self.exec_on_release = False  # true if trigger should execute on input release event

    @property
    def device_id(self) -> str:
        return self.device.device_id if self.device else None

    @property
    def device_guid(self) -> dinput.GUID:
        return self.device.device_guid if self.device else None


    def getDeviceMap(self) -> dict[str, DeviceSummary]:
        """gets the map  of virpil devices"""
        devices = gremlin.joystick_handling.physical_devices()
        dev: DeviceSummary
        virpil_map = {dev.device_id: dev for dev in devices if dev.enabled and dev.vendor_id == VIRPIL_VENDOR_ID}
        dev = gremlin.joystick_handling.getInvalidDevice()
        virpil_map[dev.device_id] = dev

        return virpil_map

    def icon(self):
        base_path = gremlin.util.script_path()
        icon_path = os.path.join(base_path, "action_plugins", "virpil_led", "icon.png")
        if os.path.isfile(icon_path):
            syslog.info(f"found virpil icon at {icon_path}")
            return icon_path
        return None

    def requires_virtual_button(self):
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    def setState(self, r: int, g: int, b: int, led: VirpilButtonType):
        if self.device and self.device.enabled and os.path.isfile(self.virpil_executable):
            syslog.info(f"VIRPIL: setting LED state: r={r}, g={g}, b={b}, led={led.value}")

            # LED tool expects the product and vendor IDs to be in hex values, 4 digits
            command = f"{self.virpil_executable} {self.device.vendor_id:04x} {self.device.product_id:04x} {led.value} {r} {g} {b}"
            syslog.info(f"VIRPIL: {command}")
            # for diagnostics window
            # subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE)

            # no window
            subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)

    def _parse_xml(self, node, data=None, extra_data=None):
        assert node.tag == self.tag, f"Expected tag {self.tag} but got {node.tag}"
        device_id = safe_read(node, "device_guid", str, "")
        device = gremlin.joystick_handling.getDevice(device_id)
        if not device:
            device = gremlin.joystick_handling.getInvalidDevice()
        self.device = device

        model_node = node.xpath(f"./{VirpilActionModel.tag}")
        if model_node is not None:
            self.model.from_xml(model_node[0])
        self.output_mode = VirpilOutputMode.from_string(safe_read(node, "output_mode", str, "hold"))

        self.exec_on_press = safe_read(node, "exec_on_press", bool, True)
        self.exec_on_release = safe_read(node, "exec_on_release", bool, False)
        self.pulse_duration = safe_read(node, "pulse_duration", int, 1000)

    def _generate_xml(self):
        node = ElementTree.Element(self.tag)
        node.set("device_guid", self.device_id)
        node.set("output_mode", VirpilOutputMode.to_string(self.output_mode))
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))
        node.set("pulse_duration", safe_format(self.pulse_duration, int))
        node.append(self.model.to_xml())

        return node

    def _is_valid(self):
        return True


version = 1
name = "Virpil LED"
create = VirpilAction
