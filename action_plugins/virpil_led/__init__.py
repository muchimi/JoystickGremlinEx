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
from enum import IntEnum, Enum
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
from dataclasses import dataclass


syslog = logging.getLogger("system")

VIRPIL_VENDOR_ID = 0x3344  # HID code for Virpil controllers


@dataclass(frozen=True)
class VirpilLedOption:
    """One selectable LED target for a Virpil device family."""

    key: str  # stable id for profiles / UI
    label: str  # human-readable name
    led_id: int  # ID sent to VPC_LED_Control.exe


class VirpilDeviceFamily(Enum):
    """Device families with distinct LED ID layouts (see virpil/m77_vpc_leds.py)."""

    Stick = "stick"
    Throttle = "throttle"
    ControlPanel1 = "control_panel_1"
    ControlPanel2 = "control_panel_2"
    Unknown = "unknown"


# LED maps for VPC_LED_Control.exe
#
# Command numbers are the values in the tool dropdown brackets, extracted from
# VPC_LED_Control.exe (v2024+/2025):
#   [001]-[020] On-board #01-#20
#   [021]-[040] Slave1 #01-#20   (Alpha Prime grip LEDs appear here as Slave1)
#   [041]-[060] Slave2 #01-#20
#   [061]-[080] Slave3 #01-#20
#   [081]-[100] Slave4 #01-#20
#   [101] All RGB LEDs
#   [102] All On-board
#   [103]-[106] All Slave1-4
#
# Control Panel #2 On-board map verified from Virpil forum (JasonAlaska).
# Other panel/throttle families use On-board indices (legacy plugin HID IDs
# were typically On-board+4 and are wrong for this tool).
# Alpha Prime sticks: VPC Config shows grip LEDs under Add-boards / Slave1
# with 9 LEDs — those are Slave1 #01-#09 => commands 21-29.
VIRPIL_DEVICE_LEDS: dict[VirpilDeviceFamily, list[VirpilLedOption]] = {
    VirpilDeviceFamily.Stick: [
        VirpilLedOption("grip_01", "LED 01", 21),
        VirpilLedOption("grip_02", "LED 02", 22),
        VirpilLedOption("grip_03", "LED 03", 23),
        VirpilLedOption("grip_04", "LED 04", 24),
        VirpilLedOption("grip_05", "LED 05", 25),
        VirpilLedOption("grip_06", "LED 06", 26),
        VirpilLedOption("grip_07", "LED 07", 27),
        VirpilLedOption("grip_08", "LED 08", 28),
        VirpilLedOption("grip_09", "LED 09", 29),
    ],
    VirpilDeviceFamily.Throttle: [
        VirpilLedOption("b1", "B1", 1),
        VirpilLedOption("b2", "B2", 2),
        VirpilLedOption("b3", "B3", 3),
        VirpilLedOption("b4", "B4", 4),
        VirpilLedOption("b5", "B5", 5),
        VirpilLedOption("b6", "B6", 6),
    ],
    VirpilDeviceFamily.ControlPanel1: [
        VirpilLedOption("b1", "B1", 12),
        VirpilLedOption("b2", "B2", 9),
        VirpilLedOption("b3", "B3", 11),
        VirpilLedOption("b4", "B4", 8),
        VirpilLedOption("b5", "B5", 10),
        VirpilLedOption("b6", "B6", 7),
        VirpilLedOption("b7", "B7", 4),
        VirpilLedOption("b8", "B8", 5),
        VirpilLedOption("b9", "B9", 6),
        VirpilLedOption("b10", "B10", 1),
        VirpilLedOption("b11", "B11", 2),
        VirpilLedOption("b12", "B12", 3),
    ],
    VirpilDeviceFamily.ControlPanel2: [
        VirpilLedOption("rudder", "Rudder", 5),
        VirpilLedOption("center", "Center (above gear)", 6),
        VirpilLedOption("flaps_left", "Flaps left", 7),
        VirpilLedOption("gear_left", "Gear left", 8),
        VirpilLedOption("gear_middle", "Gear middle", 9),
        VirpilLedOption("gear_right", "Gear right", 10),
        VirpilLedOption("flaps_right", "Flaps right", 11),
        VirpilLedOption("b1", "B1", 2),
        VirpilLedOption("b2", "B2", 1),
        VirpilLedOption("b3", "B3", 4),
        VirpilLedOption("b4", "B4", 3),
        VirpilLedOption("b5", "B5", 17),
        VirpilLedOption("b6", "B6", 14),
        VirpilLedOption("b7", "B7", 16),
        VirpilLedOption("b8", "B8", 13),
        VirpilLedOption("b9", "B9", 15),
        VirpilLedOption("b10", "B10", 12),
    ],
    VirpilDeviceFamily.Unknown: [],
}

# USB product IDs — verified against this system's DirectInput device list where noted.
# Prefer name-based classification when the device name is unambiguous (see classify_virpil_device).
VIRPIL_PRODUCT_FAMILY: dict[int, VirpilDeviceFamily] = {
    0x0259: VirpilDeviceFamily.ControlPanel1,  # classic CP1
    0x4259: VirpilDeviceFamily.ControlPanel1,  # CP1 variant (RIGHT VPC Panel #1 on this system)
    0x025B: VirpilDeviceFamily.ControlPanel2,
    0x825B: VirpilDeviceFamily.ControlPanel2,
    0x8193: VirpilDeviceFamily.Throttle,  # CM2
    0x0194: VirpilDeviceFamily.Throttle,  # CM3 / MongoosT
    0x8194: VirpilDeviceFamily.Throttle,  # CM3
    0x40CB: VirpilDeviceFamily.Stick,  # classic Alpha right
    0x80CB: VirpilDeviceFamily.Stick,  # classic Alpha left
    0x4391: VirpilDeviceFamily.Stick,  # RIGHT VPC Stick MT-50CM3 (this system)
    0x8390: VirpilDeviceFamily.Stick,  # LEFT VPC Stick MT-50CM3 (this system)
}


def classify_virpil_device(device: DeviceSummary | None) -> VirpilDeviceFamily:
    """Determine which LED layout applies to a connected Virpil device."""
    if device is None or not getattr(device, "enabled", False):
        return VirpilDeviceFamily.Unknown

    name = (device.name or "").casefold()

    # Name first — product IDs vary by firmware/revision and are easy to mis-map
    if "panel #1" in name or "panel 1" in name or "cp1" in name:
        return VirpilDeviceFamily.ControlPanel1
    if "panel #2" in name or "panel 2" in name or "cp2" in name:
        return VirpilDeviceFamily.ControlPanel2
    # Sticks often include base names like "MT-50CM3" — check stick/alpha before CM3
    if "stick" in name or "alpha" in name:
        return VirpilDeviceFamily.Stick
    if "mongoos" in name or "throttle" in name or "cm3" in name or "cm2" in name:
        return VirpilDeviceFamily.Throttle

    family = VIRPIL_PRODUCT_FAMILY.get(int(device.product_id or 0))
    if family is not None:
        return family

    return VirpilDeviceFamily.Unknown

# Map legacy flat enum names (pre device-aware lists) to LED keys
_LEGACY_LED_KEY_MAP = {
    "buttonb1": "b1",
    "buttonb2": "b2",
    "buttonb3": "b3",
    "buttonb4": "b4",
    "buttonb5": "b5",
    "buttonb6": "b6",
    "buttonb7": "b7",
    "buttonb8": "b8",
    "buttonb9": "b9",
    "b10": "b10",
    "top": "rudder",
    "middle": "center",
    "rudder": "rudder",
    "center": "center",
    "flapsleft": "flaps_left",
    "gearleft": "gear_left",
    "gearmiddle": "gear_middle",
    "gearright": "gear_right",
    "flapsright": "flaps_right",
    "flaps_left": "flaps_left",
    "gear_left": "gear_left",
    "gear_middle": "gear_middle",
    "gear_right": "gear_right",
    "flaps_right": "flaps_right",
    "control1b1": "b1",
    "control1b2": "b2",
    "control1b3": "b3",
    "control1b4": "b4",
    "control1b5": "b5",
    "control1b6": "b6",
    "control1b7": "b7",
    "control1b8": "b8",
    "control1b9": "b9",
    "control1b10": "b10",
    "control1b11": "b11",
    "control1b12": "b12",
    "throttleb1": "b1",
    "throttleb2": "b2",
    "throttleb3": "b3",
    "throttleb4": "b4",
    "throttleb5": "b5",
    "throttleb6": "b6",
    "stickb1": "grip_01",
    "stick_led": "grip_01",
    "grip_01": "grip_01",
    "grip_02": "grip_02",
    "grip_03": "grip_03",
    "grip_04": "grip_04",
    "grip_05": "grip_05",
    "grip_06": "grip_06",
    "grip_07": "grip_07",
    "grip_08": "grip_08",
    "grip_09": "grip_09",
}


def leds_for_device(device: DeviceSummary | None) -> list[VirpilLedOption]:
    """Return LED options for the selected device family."""
    return list(VIRPIL_DEVICE_LEDS.get(classify_virpil_device(device), []))


def available_leds_for_device(device: DeviceSummary | None, exclude_keys: set[str] | None = None) -> list[VirpilLedOption]:
    """LED options for a device, optionally skipping keys already added."""
    exclude = exclude_keys or set()
    return [led for led in leds_for_device(device) if led.key not in exclude]


def normalize_led_key(value: str | None) -> str:
    if not value:
        return "b1"
    key = value.casefold().strip()
    return _LEGACY_LED_KEY_MAP.get(key, key)


def resolve_led_option(device: DeviceSummary | None, led_key: str | None) -> VirpilLedOption | None:
    """Resolve a stored LED key to the option/id for the current device."""
    leds = leds_for_device(device)
    if not leds:
        return None
    key = normalize_led_key(led_key)
    match = next((led for led in leds if led.key == key), None)
    return match if match is not None else leds[0]


def led_display_label(device: DeviceSummary | None, led_key: str | None) -> str:
    """Human label for an LED key on the current device (B1, Gear left, LED 01, ...)."""
    option = resolve_led_option(device, led_key)
    return option.label if option else (led_key or "LED")


def led_combo_source(device: DeviceSummary | None) -> list[tuple[str, str]]:
    """Combo source tuples: (display label, led key)."""
    return [(led.label, led.key) for led in leds_for_device(device)]


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
        self,
        index: int = -1,
        device: DeviceSummary = None,
        mode: VirpilIntensity = None,
        channel: VirpilButtonChannel = None,
        led_key: str = None,
        led_id: int = None,
    ):
        self.id = gremlin.util.get_guid()  # unique ID
        self.device: DeviceSummary = device  # device reference
        self.led_key: str = normalize_led_key(led_key)
        option = resolve_led_option(device, self.led_key)
        self.led_id: int = led_id if led_id is not None else (option.led_id if option else 0)

        self.rgb: int = 0  # activation / blink primary
        self.deactivation_rgb: int = 0  # color when inactive / after blink stops
        self.blink_rgb: int = 0  # blink secondary color

        self.index: int = index

    def sync_led_to_device(self, device: DeviceSummary | None):
        """Re-resolve LED id/key for the currently selected Virpil device."""
        option = resolve_led_option(device, self.led_key)
        if option is None:
            self.led_key = "b1"
            self.led_id = 0
            return
        self.led_key = option.key
        self.led_id = option.led_id

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
        node.set("led", safe_format(self.led_key, str))
        node.set("led_id", safe_format(self.led_id, int))
        node.set("index", safe_format(self.index, int))
        node.set("guid", safe_format(self.id, str))
        node.set("rgb", safe_format(self.rgb, int))
        node.set("deactivation_rgb", safe_format(self.deactivation_rgb, int))
        node.set("blink_rgb", safe_format(self.blink_rgb, int))
        return node

    def from_xml(self, node):
        assert node.tag == VirpilButton.tag, f"Expected tag {VirpilButton.tag} but got {node.tag}"
        self.led_key = normalize_led_key(safe_read(node, "led", str, "b1"))
        self.led_id = safe_read(node, "led_id", int, 0)
        self.index = safe_read(node, "index", int, -1)
        self.id = safe_read(node, "guid", str, gremlin.util.get_guid())
        self.rgb = safe_read(node, "rgb", int, 0)
        self.deactivation_rgb = safe_read(node, "deactivation_rgb", int, 0)
        self.blink_rgb = safe_read(node, "blink_rgb", int, 0)

    def getRGB(self) -> tuple[int, int, int]:
        """Activation / blink primary color (clamped)."""
        return self._int_to_rgb(self.rgb)

    def getDeactivationRGB(self) -> tuple[int, int, int]:
        """Deactivation / post-blink color (clamped)."""
        return self._int_to_rgb(self.deactivation_rgb)

    def getBlinkRGB(self) -> tuple[int, int, int]:
        """Blink secondary color (clamped)."""
        return self._int_to_rgb(self.blink_rgb)

    def __hash__(self):
        return hash(self.id)


class VirpilActionModel(gremlin.input_item.AbstractCallbackModel):
    """holds a list of button definitions to trigger by the action"""

    tag = "virpil-action-model"

    def __init__(self, action_data: VirpilAction, parent=None):
        super().__init__(model_description="virpil led map")
        self.action_data = action_data

    def add(self, button: VirpilButton, index: int = -1):
        # super().add allocates the real slot when index == -1; keep button.index in sync
        index = super().add(button, index=index)
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
    """displays a configured Virpil LED row (On / Off / Blink colors)"""

    def __init__(self, action_data: VirpilAction, button_data: VirpilButton, index: int = -1, delete_callback: Callable = None, parent=None):
        super().__init__(parent)

        self.action_data = action_data
        self.delete_callback = delete_callback
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.button_data = button_data
        self.index: int = index  # index in the list
        self.selected: bool = False  # true if selected

        self.button_data.sync_led_to_device(self.action_data.device)
        label_text = led_display_label(self.action_data.device, self.button_data.led_key)
        self.led_label_widget = QtWidgets.QLabel(label_text)
        self.led_label_widget.setMinimumWidth(120)

        main_widgets = ["LED:", self.led_label_widget]

        self.on_swatch, self.on_button = self._make_color_controls("On", self._handle_get_on_color)
        self.off_swatch, self.off_button = self._make_color_controls("Off", self._handle_get_off_color)
        self.blink_swatch, self.blink_button = self._make_color_controls("Blink", self._handle_get_blink_color)
        self.blink_label = QtWidgets.QLabel("Blink:")

        main_widgets.extend(["On:", self.on_swatch, self.on_button, "Off:", self.off_swatch, self.off_button])
        main_widgets.extend([self.blink_label, self.blink_swatch, self.blink_button])

        if delete_callback is not None:
            delete_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback=self._handle_delete)
            main_widgets.append(delete_widget)

        widget = gremlin.ui.ui_common.getHContainer(main_widgets, widget_only=True, no_stretch=True)
        self.main_layout.addWidget(widget)
        self._update_colors()
        self.set_blink_visible(bool(getattr(self.action_data, "blink_enabled", False)))

    def _make_color_controls(self, title: str, callback: Callable):
        swatch = QtWidgets.QLabel("     ")
        swatch.setFixedWidth(50)
        button = gremlin.ui.ui_common.QDataPushButton(f"Select {title}", callback=callback)
        return swatch, button

    def refresh_led_options(self):
        """Refresh the displayed LED label after the parent Virpil device changes."""
        self.button_data.sync_led_to_device(self.action_data.device)
        self.led_label_widget.setText(led_display_label(self.action_data.device, self.button_data.led_key))

    def set_blink_visible(self, visible: bool):
        self.blink_label.setVisible(visible)
        self.blink_swatch.setVisible(visible)
        self.blink_button.setVisible(visible)

    def _pick_color(self, current_rgb: int, title: str) -> int | None:
        color = QColor.fromRgb(current_rgb)
        # Use Qt's dialog, not the Windows native one. Native "Add to Custom Colors"
        # always overwrites the selected (usually first) custom slot.
        selected = QColorDialog.getColor(
            initial=color,
            parent=self,
            title=title,
            options=QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if selected.isValid():
            return selected.rgb()
        return None

    def _handle_get_on_color(self):
        rgb = self._pick_color(self.button_data.rgb, "Select On Color")
        if rgb is not None:
            self.button_data.rgb = rgb
            self._update_colors()

    def _handle_get_off_color(self):
        rgb = self._pick_color(self.button_data.deactivation_rgb, "Select Off Color")
        if rgb is not None:
            self.button_data.deactivation_rgb = rgb
            self._update_colors()

    def _handle_get_blink_color(self):
        rgb = self._pick_color(self.button_data.blink_rgb, "Select Blink Color")
        if rgb is not None:
            self.button_data.blink_rgb = rgb
            self._update_colors()

    def _paint_swatch(self, widget: QtWidgets.QLabel, rgb: int):
        color = QColor.fromRgb(rgb)
        border_color = gremlin.ui.ui_common.Color.borderColor()
        widget.setStyleSheet(f".QLabel {{ background-color: {color.name()}; border: 4px solid {border_color}; }}")

    def _update_colors(self):
        self._paint_swatch(self.on_swatch, self.button_data.rgb)
        self._paint_swatch(self.off_swatch, self.button_data.deactivation_rgb)
        self._paint_swatch(self.blink_swatch, self.button_data.blink_rgb)

    def _handle_delete(self):
        """handles the delete button click"""
        if self.delete_callback:
            self.delete_callback(self)


class VirpilLedPickerDialog(QtWidgets.QDialog):
    """Dialog to choose one or more device LEDs to add."""

    def __init__(self, device: DeviceSummary, existing_keys: set[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Virpil LED")
        self.setMinimumWidth(360)
        self.setMinimumHeight(420)

        self._device = device
        self._existing_keys = existing_keys or set()
        self.selected_keys: list[str] = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Select LED(s) to add:"))

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        available = available_leds_for_device(device, self._existing_keys)
        for led in available:
            item = QtWidgets.QListWidgetItem(led.label)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, led.key)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self._add_selected)
        layout.addWidget(self.list_widget)

        if not available:
            layout.addWidget(gremlin.ui.ui_common.QWarningWidget("All LEDs for this device are already added."))

        self.add_selected_widget = gremlin.ui.ui_common.Buttons.getOkWidget(
            label="Add Selected", callback=self._add_selected
        )
        self.add_all_widget = gremlin.ui.ui_common.QDataPushButton("Add All", callback=self._add_all)
        self.cancel_widget = gremlin.ui.ui_common.Buttons.getCancelWidget(callback=self.reject)

        self.add_selected_widget.setEnabled(bool(available))
        self.add_all_widget.setEnabled(bool(available))

        buttons = gremlin.ui.ui_common.getHContainer(
            [self.add_selected_widget, self.add_all_widget, self.cancel_widget],
            widget_only=True,
            left_stretch=True,
        )
        layout.addWidget(buttons)

        if available:
            self.list_widget.setCurrentRow(0)

    def _keys_from_selection(self) -> list[str]:
        keys = []
        for item in self.list_widget.selectedItems():
            key = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if key:
                keys.append(key)
        return keys

    def _add_selected(self):
        keys = self._keys_from_selection()
        if not keys:
            # If nothing highlighted, add the current row
            item = self.list_widget.currentItem()
            if item is not None:
                key = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if key:
                    keys = [key]
        if not keys:
            return
        self.selected_keys = keys
        self.accept()

    def _add_all(self):
        keys = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            key = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if key:
                keys.append(key)
        if not keys:
            return
        self.selected_keys = keys
        self.accept()


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

        self.blink_enabled_widget = QtWidgets.QCheckBox("Blink between On and Blink colors")
        self.blink_enabled_widget.setChecked(bool(self.action_data.blink_enabled))
        self.blink_enabled_widget.toggled.connect(self._handle_blink_enabled_changed)

        self.blink_while_held_widget = QtWidgets.QCheckBox("Blink while held")
        self.blink_while_held_widget.setToolTip(
            "Checked: blink while the button is held, stop on release.\n"
            "Unchecked: each press toggles blinking on/off (then Off colors)."
        )
        self.blink_while_held_widget.setChecked(bool(self.action_data.blink_while_held))
        self.blink_while_held_widget.toggled.connect(self._handle_blink_while_held_changed)

        self.blink_interval_widget = gremlin.ui.ui_common.QDelayWidget(
            value=self.action_data.blink_interval_ms, callback=self._handle_blink_interval_changed
        )

        self.main_layout.addWidget(self.output_mode_widget)
        self.main_layout.addWidget(self.device_selector)

        self.no_device_warning_widget = gremlin.ui.ui_common.QWarningWidget(
            "Select a Virpil device first before adding LEDs."
        )
        self.main_layout.addWidget(self.no_device_warning_widget)

        self.main_layout.addWidget(self.view_widget)

        # button bar
        widgets = [self.add_widget, self.test_widget]
        container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.button_bar_widget = container
        self.main_layout.addWidget(container)

        # delay widget
        self.pulse_container_widget = gremlin.ui.ui_common.getHContainer(["Pulse Duration (ms):", self.delay_widget], widget_only=True)
        self.main_layout.addWidget(self.pulse_container_widget)

        # blink panel
        blink_row = gremlin.ui.ui_common.getHContainer(
            [
                self.blink_enabled_widget,
                self.blink_while_held_widget,
                "Interval (ms):",
                self.blink_interval_widget,
            ],
            widget_only=True,
        )
        self.blink_container_widget = blink_row
        self.main_layout.addWidget(self.blink_container_widget)

        self.main_layout.addWidget(self._execute_widget)

        self._update_view_widget()  # load the items

        self._update()

    def _has_valid_device(self) -> bool:
        """True when a real Virpil device (not 'No Device') is selected."""
        device = self.action_data.device
        return device is not None and bool(getattr(device, "enabled", False))

    def _handle_configure(self):
        dialog = VirpilExecutableDialog(self.action_data, parent=self)
        dialog.exec_()

    def _update_view_widget(self):
        self.view_widget.clear()
        for widget in self._widget_map.values():
            delete_widget(widget)
        self._widget_map.clear()
        if not self._has_valid_device():
            return
        for index, button in enumerate(self.action_data.model):
            widget = VirpilButtonWidget(self.action_data, button, delete_callback=self._handle_delete, index = index)
            item = QtWidgets.QListWidgetItem()
            self.view_widget.addItem(item)
            self.view_widget.setItemWidget(item, widget)
            size = widget.sizeHint()  # get the size hint of the widget
            item.setSizeHint(size)  # size to fit the widget
            self._widget_map[index] = widget

    def _update(self):
        has_device = self._has_valid_device()
        pulse_visible = has_device and self.action_data.output_mode == VirpilOutputMode.Pulse
        self.pulse_container_widget.setVisible(pulse_visible)
        self.blink_container_widget.setVisible(has_device)
        self.blink_while_held_widget.setEnabled(self.action_data.blink_enabled)
        self.blink_interval_widget.setEnabled(self.action_data.blink_enabled)
        self.no_device_warning_widget.setVisible(not has_device)
        self.view_widget.setVisible(has_device)
        self.button_bar_widget.setVisible(has_device)
        self.add_widget.setEnabled(has_device)
        self.test_widget.setEnabled(has_device)
        for widget in self._widget_map.values():
            if hasattr(widget, "set_blink_visible"):
                widget.set_blink_visible(bool(self.action_data.blink_enabled))

    def _handle_test(self):
        if not self._has_valid_device():
            return
        if self.action_data.device and self.action_data.device.enabled:
            for button in self.action_data.model:
                r, g, b = button.getRGB()
                self.action_data.setState(r, g, b, button.led_id)


    def _handle_delay_changed(self, value: int):
        self.action_data.pulse_duration = value

    def _handle_blink_enabled_changed(self, checked: bool):
        self.action_data.blink_enabled = bool(checked)
        self._update()

    def _handle_blink_while_held_changed(self, checked: bool):
        self.action_data.blink_while_held = bool(checked)

    def _handle_blink_interval_changed(self, value: int):
        self.action_data.blink_interval_ms = max(100, min(25000, int(value)))

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
        if not self._has_valid_device():
            return
        existing = {button.led_key for button in self.action_data.model}
        dialog = VirpilLedPickerDialog(self.action_data.device, existing_keys=existing, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        for led_key in dialog.selected_keys:
            self._add_led(led_key, refresh=False)
        self._update_view_widget()

    def _add_led(self, led_key: str, refresh: bool = True):
        option = resolve_led_option(self.action_data.device, led_key)
        if option is None:
            return
        # Skip duplicates
        if any(button.led_key == option.key for button in self.action_data.model):
            return
        button = VirpilButton(
            index=len(self.action_data.model),
            device=self.action_data.device,
            mode=VirpilIntensity.Max,
            channel=VirpilButtonChannel.Blue,
            led_key=option.key,
            led_id=option.led_id,
        )
        self.action_data.model.add(button)
        if refresh:
            self._update_view_widget()

    def _handle_delete(self, widget: VirpilButtonWidget):
        # Remove by object — model indices can be sparse after prior deletes,
        # so enumerate() widget positions are not reliable removeAt() keys.
        button = widget.button_data
        if button is not None:
            self.action_data.model.remove(button)
            self._reindex_buttons()
            self._update_view_widget()

    def _reindex_buttons(self):
        """Compact model slots to 0..n-1 so UI and XML indices stay consistent."""
        buttons = list(self.action_data.model)
        self.action_data.model.clear(emit=False)
        for i, button in enumerate(buttons):
            button.index = i
            self.action_data.model.add(button, index=i)

    def _handle_mode_changed(self, widget, checked: bool):
        if checked:
            self.action_data.output_mode = widget.data
            self._update()

    def _handle_device_changed(self, device : dinput.DeviceSummary):
        self.action_data.device = device
        for button in self.action_data.model:
            button.sync_led_to_device(device)
        # Rebuild LED rows so each dropdown shows only this device's LEDs
        self._update_view_widget()
        self._update()

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
        self._blink_timer = None
        self._blink_phase = False  # False = On/primary, True = Blink secondary
        self._blinking = False

    def profile_start(self):
        self._valid = self.action_data.device and self.action_data.device.enabled
        self._toggle_state = False
        self._stop_blink(apply_deactivation=False)
        if self._valid:
            self._apply_deactivation()

    def profile_stop(self):
        if self._pulse_timer is not None:
            self._pulse_timer.cancel()
            self._pulse_timer = None
        self._stop_blink(apply_deactivation=False)
        if self._valid:
            self._apply_deactivation()
        try:
            import gremlin.virpil_led_hid

            gremlin.virpil_led_hid.VirpilLedHid().close_all()
        except Exception:
            pass

    def process_event(self, event: gremlin.event_handler.Event, value: gremlin.actions.Value, extra_data=None):
        if not self._valid:
            return False

        is_pressed = bool(event.is_pressed)
        mode = self.action_data.output_mode

        # Blink overlays Hold/Toggle press semantics when enabled
        if self.action_data.blink_enabled:
            if self.action_data.blink_while_held:
                if is_pressed:
                    self._start_blink()
                else:
                    self._stop_blink(apply_deactivation=True)
            else:
                # Momentary toggle: each press starts/stops blinking
                if is_pressed:
                    if self._blinking:
                        self._stop_blink(apply_deactivation=True)
                    else:
                        self._start_blink()
            return True

        match mode:
            case VirpilOutputMode.Hold:
                # Always honor both edges so Off colors apply on release
                if is_pressed:
                    self._apply_activation()
                else:
                    self._apply_deactivation()
            case VirpilOutputMode.Pulse:
                if is_pressed:
                    self._apply_activation()
                    if self._pulse_timer is not None:
                        self._pulse_timer.cancel()
                    self._pulse_timer = threading.Timer(
                        max(1, int(self.action_data.pulse_duration)) / 1000.0,
                        self._apply_deactivation,
                    )
                    self._pulse_timer.daemon = True
                    self._pulse_timer.start()
            case VirpilOutputMode.Toggle:
                if is_pressed:
                    self._toggle_state = not self._toggle_state
                    if self._toggle_state:
                        self._apply_activation()
                    else:
                        self._apply_deactivation()

        return True

    def _apply_activation(self):
        if not self._valid:
            return
        for button in self.action_data.model:
            r, g, b = button.getRGB()
            self.action_data.setState(r, g, b, button.led_id)

    def _apply_deactivation(self):
        if not self._valid:
            return
        for button in self.action_data.model:
            r, g, b = button.getDeactivationRGB()
            self.action_data.setState(r, g, b, button.led_id)

    def _apply_blink_phase(self):
        if not self._valid:
            return
        for button in self.action_data.model:
            if self._blink_phase:
                r, g, b = button.getBlinkRGB()
            else:
                r, g, b = button.getRGB()
            self.action_data.setState(r, g, b, button.led_id)

    def _blink_interval_sec(self) -> float:
        ms = int(getattr(self.action_data, "blink_interval_ms", 500) or 500)
        ms = max(100, min(25000, ms))
        return ms / 1000.0

    def _start_blink(self):
        self._stop_blink(apply_deactivation=False)
        self._blinking = True
        self._blink_phase = False
        self._apply_blink_phase()
        self._schedule_blink_tick()

    def _schedule_blink_tick(self):
        if not self._blinking:
            return
        self._blink_timer = threading.Timer(self._blink_interval_sec(), self._blink_tick)
        self._blink_timer.daemon = True
        self._blink_timer.start()

    def _blink_tick(self):
        if not self._blinking or not self._valid:
            return
        self._blink_phase = not self._blink_phase
        self._apply_blink_phase()
        self._schedule_blink_tick()

    def _stop_blink(self, apply_deactivation: bool = True):
        self._blinking = False
        if self._blink_timer is not None:
            self._blink_timer.cancel()
            self._blink_timer = None
        if apply_deactivation and self._valid:
            self._apply_deactivation()


class VirpilAction(gremlin.input_item.AbstractAction):
    """Action for pausing the execution of callbacks."""

    name = "Virpil LED"
    tag = "virpil-led"
    hint = "Virpil LED action plugin."

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)

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
        self.exec_on_release = True  # release needed for Off colors / blink-while-held
        self.blink_enabled = False
        self.blink_interval_ms = 500
        self.blink_while_held = True

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

    @staticmethod
    def _channel_to_virpil_hex(value: int) -> str:
        """Map a 0..255 color channel to Virpil LED tool intensity codes."""
        # VPC_LED_Control accepts only: 00 (off), 40 (low), 80 (mid), FF (max)
        if value <= 0:
            return "00"
        if value <= 76:
            return "40"
        if value <= 153:
            return "80"
        return "FF"

    def setState(self, r: int, g: int, b: int, led_id: int):
        if not self.device or not self.device.enabled:
            return

        # Prefer direct HID (keeps device open) — fall back to VPC_LED_Control.exe
        try:
            import gremlin.virpil_led_hid

            if gremlin.virpil_led_hid.VirpilLedHid().set_led(
                self.device.vendor_id,
                self.device.product_id,
                led_id,
                r,
                g,
                b,
            ):
                return
        except Exception as exc:
            syslog.warning(f"VIRPIL HID: unavailable, using exe fallback: {exc}")

        if not os.path.isfile(self.virpil_executable):
            syslog.warning("VIRPIL: LED update failed (HID unavailable and executable missing)")
            return

        rh = self._channel_to_virpil_hex(r)
        gh = self._channel_to_virpil_hex(g)
        bh = self._channel_to_virpil_hex(b)
        syslog.info(f"VIRPIL: setting LED state via exe: r={rh}, g={gh}, b={bh}, led={led_id}")

        # LED tool expects hex VID/PID and intensity codes (00/40/80/FF), not 0..255 RGB
        args = [
            self.virpil_executable,
            f"{self.device.vendor_id:04x}",
            f"{self.device.product_id:04x}",
            str(led_id),
            rh,
            gh,
            bh,
        ]
        syslog.info(f"VIRPIL: {' '.join(args)}")
        # for diagnostics window
        # subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE)

        # no window
        subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)

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
        for button in self.model:
            button.sync_led_to_device(self.device)
        self.output_mode = VirpilOutputMode.from_string(safe_read(node, "output_mode", str, "hold"))

        self.exec_on_press = safe_read(node, "exec_on_press", bool, True)
        self.exec_on_release = safe_read(node, "exec_on_release", bool, True)
        self.pulse_duration = safe_read(node, "pulse_duration", int, 1000)
        self.blink_enabled = safe_read(node, "blink_enabled", bool, False)
        self.blink_while_held = safe_read(node, "blink_while_held", bool, True)
        self.blink_interval_ms = max(100, min(25000, safe_read(node, "blink_interval_ms", int, 500)))

    def _generate_xml(self):
        node = ElementTree.Element(self.tag)
        node.set("device_guid", self.device_id)
        node.set("output_mode", VirpilOutputMode.to_string(self.output_mode))
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))
        node.set("pulse_duration", safe_format(self.pulse_duration, int))
        node.set("blink_enabled", safe_format(self.blink_enabled, bool))
        node.set("blink_while_held", safe_format(self.blink_while_held, bool))
        node.set("blink_interval_ms", safe_format(self.blink_interval_ms, int))
        node.append(self.model.to_xml())

        return node

    def _is_valid(self):
        return True


version = 1
name = "Virpil LED"
create = VirpilAction
