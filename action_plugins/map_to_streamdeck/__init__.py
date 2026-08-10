# -*- coding: utf-8; -*-
#
# Map to Stream Deck — control a connected Stream Deck via the plugin bridge.
# First function: Change Page (Elgato switchToProfile + plugin-bundled profile pages).
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.util import safe_read, safe_format
import gremlin.ui.ui_common
import gremlin.input_item
from shiboken6 import Shiboken

syslog = logging.getLogger("system")

FUNCTIONS = [
    ("changePage", "Change Page"),
]

# Elgato DeviceType -> single plugin profile (pages are pages, not extra profiles).
PROFILE_BY_DEVICE_TYPE = {
    0: "profiles/jgex",  # Stream Deck (classic)
    1: "profiles/jgex-mini",  # Mini
    2: "profiles/jgex-xl",  # XL
    7: "profiles/jgex-plus",  # Stream Deck +
    9: "profiles/jgex-neo",  # Neo
}
DEFAULT_PROFILE = "profiles/jgex-xl"


def resolve_profile_for_device(device_id: str, page: int = 0) -> str:
    """Pick the single plugin-bundled profile for this device type."""
    try:
        from gremlin.ui.streamdeck_device import StreamDeckBridge

        info = StreamDeckBridge().devices.get(device_id) or {}
        dtype = info.get("type")
        if dtype is not None and dtype != "":
            try:
                return PROFILE_BY_DEVICE_TYPE.get(int(dtype), DEFAULT_PROFILE)
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    return DEFAULT_PROFILE


class MapToStreamDeckWidget(gremlin.input_item.AbstractActionWidget):
    """UI: pick a connected Stream Deck, then a function (Change Page first)."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        # Ensure press is on if a saved action had both flags cleared.
        if not self.action_data.execute_on_press and not self.action_data.execute_on_release:
            self.action_data.execute_on_press = True

        self.device_widget = gremlin.ui.ui_common.QDataComboBox()
        self.device_widget.setMinimumWidth(220)
        self.device_widget.currentIndexChanged.connect(self._device_changed)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.setToolTip("Reload connected Stream Deck devices from the bridge")
        self.refresh_btn.clicked.connect(self._refresh_devices)

        self.test_btn = QtWidgets.QPushButton("Test")
        self.test_btn.setToolTip("Send Change Page now (profile does not need to be running)")
        self.test_btn.clicked.connect(self._test_clicked)

        device_row = gremlin.ui.ui_common.getHContainer(
            [self.device_widget, self.refresh_btn, self.test_btn],
            "Device:",
            widget_only=True,
        )
        self.main_layout.addWidget(device_row)

        self.function_widget = gremlin.ui.ui_common.QDataComboBox()
        for value, label in FUNCTIONS:
            self.function_widget.addItem(label, value)
        idx = self.function_widget.findData(self.action_data.command)
        if idx < 0:
            idx = 0
        self.function_widget.setCurrentIndex(idx)
        self.function_widget.currentIndexChanged.connect(self._function_changed)
        self.main_layout.addWidget(
            gremlin.ui.ui_common.getHContainer(self.function_widget, "Function:", widget_only=True)
        )

        self.page_widget = gremlin.ui.ui_common.QIntLineEdit()
        self.page_widget.setRange(1, 99)
        stored = self.action_data.page
        self.page_widget.setValue(1 if stored is None else int(stored) + 1)
        self.page_widget.setToolTip(
            "Page number (1 = first JG Ex profile page). "
            "Close the Stream Deck configuration window before testing — "
            "Elgato ignores profile switches while the editor is open."
        )
        self.page_widget.valueChanged.connect(self._page_changed)
        self.page_row = gremlin.ui.ui_common.getHContainer(self.page_widget, "Page:", widget_only=True)
        self.main_layout.addWidget(self.page_row)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(
            self.action_data.execute_on_press,
            self.action_data.execute_on_release,
            press_callback=self._press_changed,
            release_callback=self._release_changed,
        )
        self.main_layout.addWidget(self._execute_widget)

        note = QtWidgets.QLabel(
            "Use the single <b>JG Ex XL</b> profile (pages stay pages inside that profile). "
            "Change Page updates key titles live over the plugin bridge and asks Elgato "
            "to switch to that page index. It does not create one profile per page, "
            "and does not restart or close Stream Deck."
        )
        note.setWordWrap(True)
        self.main_layout.addWidget(note)

        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
            bridge.devices_changed.connect(self._refresh_devices)
            bridge.plugin_connected.connect(lambda _c: self._refresh_devices())
        except Exception:
            pass

        self._refresh_devices()
        self._update_visibility()

    def _populate_ui(self):
        pass

    def _connected_devices(self) -> list[tuple[str, str]]:
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
            items = []
            for device_id, info in bridge.devices.items():
                name = (info.get("name") or "").strip() or f"Stream Deck ({str(device_id)[:8]})"
                dtype = info.get("type")
                suffix = f" [type {dtype}]" if dtype not in (None, "") else ""
                items.append((str(device_id), f"{name}{suffix}"))
            items.sort(key=lambda x: x[1].casefold())
            return items
        except Exception:
            return []

    @QtCore.Slot()
    def _refresh_devices(self):
        if not Shiboken.isValid(self) or not Shiboken.isValid(self.device_widget):
            return
        selected = self.action_data.device_id or ""
        self.device_widget.blockSignals(True)
        self.device_widget.clear()
        devices = self._connected_devices()
        if not devices:
            self.device_widget.addItem("(no Stream Deck connected)", "")
        else:
            for device_id, label in devices:
                self.device_widget.addItem(label, device_id)
            idx = self.device_widget.findData(selected) if selected else -1
            if idx < 0:
                idx = 0
            self.device_widget.setCurrentIndex(idx)
            self.action_data.device_id = self.device_widget.currentData() or ""
        self.device_widget.blockSignals(False)

    def _update_visibility(self):
        cmd = self.action_data.command or "changePage"
        self.page_row.setVisible(cmd == "changePage")

    def _send_change_page_now(self) -> bool:
        """Shared path for Test button and runtime functor."""
        import gremlin.ui.streamdeck_device

        bridge = gremlin.ui.streamdeck_device.StreamDeckBridge()
        if not bridge.started:
            bridge.start()

        device_id = self.action_data.device_id or ""
        if not device_id:
            devices = bridge.devices
            if len(devices) == 1:
                device_id = next(iter(devices.keys()))
                self.action_data.device_id = device_id

        if not bridge.plugin_is_connected:
            return False

        page = self.action_data.page
        if page is None:
            page = 0
        profile = resolve_profile_for_device(device_id, page)
        return bool(bridge.change_page(device_id, int(page), profile))

    @QtCore.Slot()
    def _test_clicked(self):
        # Sync page from spinner before sending.
        self._page_changed()
        if self._send_change_page_now():
            gremlin.ui.ui_common.MessageBoxInfo(
                title="Map to Stream Deck",
                prompt=(
                    "Change Page sent.\n\n"
                    "JG Ex Button keys should update to P1 / P2 / … titles "
                    "and one key flashes OK. Stream Deck is not closed or restarted.\n\n"
                    "Be on profile JG Ex XL with JG Ex Button actions visible."
                ),
            )
        else:
            gremlin.ui.ui_common.MessageBoxWarning(
                title="Map to Stream Deck",
                prompt=(
                    "Plugin is not connected.\n"
                    "Enable the Stream Deck bridge and confirm the PI shows Connected."
                ),
            )

    @QtCore.Slot()
    def _device_changed(self):
        self.action_data.device_id = self.device_widget.currentData() or ""

    @QtCore.Slot()
    def _function_changed(self):
        self.action_data.command = self.function_widget.currentData() or "changePage"
        self._update_visibility()

    @QtCore.Slot()
    def _page_changed(self):
        value = int(self.page_widget.value())
        self.action_data.page = max(0, value - 1)

    def _press_changed(self, checked: bool):
        self.action_data.execute_on_press = checked

    def _release_changed(self, checked: bool):
        self.action_data.execute_on_release = checked


class MapToStreamDeckFunctor(gremlin.base_profile.AbstractFunctor):
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self.action_data = action

    def process_event(self, event, value, extra_data=None) -> bool:
        is_pressed = bool(event.is_pressed)
        exec_press = bool(self.action_data.execute_on_press)
        exec_release = bool(self.action_data.execute_on_release)
        if not exec_press and not exec_release:
            exec_press = True

        if is_pressed and not exec_press:
            return True
        if (not is_pressed) and not exec_release:
            return True

        # Avoid running Change Page twice on press+release.
        if (not is_pressed) and exec_press:
            return True

        import gremlin.ui.streamdeck_device

        bridge = gremlin.ui.streamdeck_device.StreamDeckBridge()
        if not bridge.started:
            bridge.start()

        cmd = self.action_data.command or "changePage"
        device_id = self.action_data.device_id or ""
        # Prefer the device that actually sent this Stream Deck event.
        ident = event.identifier
        if hasattr(ident, "device_id") and ident.device_id:
            device_id = ident.device_id
        if not device_id:
            devices = bridge.devices
            if len(devices) == 1:
                device_id = next(iter(devices.keys()))

        if cmd == "changePage":
            page = self.action_data.page
            if page is None:
                page = 0
            profile = resolve_profile_for_device(device_id, page)
            syslog.info(
                f"Map to Stream Deck: Change Page -> profile={profile} page={int(page)+1} "
                f"device={device_id[:12] if device_id else '?'}"
            )
            bridge.change_page(device_id, int(page), profile)
        else:
            syslog.warning(f"Map to Stream Deck: unsupported function [{cmd}]")

        return True


class MapToStreamDeck(gremlin.input_item.AbstractAction):
    name = "Map to Stream Deck"
    tag = "map-to-streamdeck"
    hint = "Control a connected Stream Deck (Change Page, …)"

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
        InputType.KeyboardLatched,
        InputType.Midi,
        InputType.OpenSoundControl,
        InputType.OctaviIfr1,
        InputType.StreamDeck,
        InputType.ModeControl,
        InputType.State,
    ]

    functor = MapToStreamDeckFunctor
    widget = MapToStreamDeckWidget

    def __init__(self, parent, extra_data: dict = None):
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent
        self.command = "changePage"
        self.device_id = ""
        self.page = 0
        self.execute_on_press = True
        self.execute_on_release = False
        self.button_id = ""
        self.title = ""
        self.image = ""
        self.state = 0
        self.profile = ""

    def icon(self):
        return "mdi.view-grid-plus"

    def requires_virtual_button(self):
        return False

    def _is_valid(self):
        return gremlin.config.Configuration().streamdeck_enabled

    def _parse_xml(self, node, data=None, extra_data=None):
        command = safe_read(node, "command", str, "changePage")
        if command not in dict(FUNCTIONS):
            command = "changePage"
        self.command = command
        self.device_id = safe_read(node, "device-id", str, "")
        page = node.get("page")
        if page not in (None, ""):
            self.page = max(0, int(page))
        else:
            self.page = 0
        self.execute_on_press = safe_read(node, "on-press", bool, True)
        self.execute_on_release = safe_read(node, "on-release", bool, False)
        if not self.execute_on_press and not self.execute_on_release:
            self.execute_on_press = True
        self.button_id = safe_read(node, "button-id", str, "")
        self.title = safe_read(node, "title", str, "")
        self.image = safe_read(node, "image", str, "")
        self.state = safe_read(node, "state", int, 0)
        self.profile = safe_read(node, "profile", str, "")

    def _generate_xml(self):
        node = ElementTree.Element(MapToStreamDeck.tag)
        node.set("command", self.command or "changePage")
        node.set("device-id", self.device_id or "")
        if self.page is not None:
            node.set("page", safe_format(int(self.page), int))
        node.set("on-press", safe_format(self.execute_on_press, bool))
        node.set("on-release", safe_format(self.execute_on_release, bool))
        return node

    def to_html(self) -> str:
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Function", dict(FUNCTIONS).get(self.command, self.command))
        table.addField("Device", self.device_id or "(auto)")
        if self.command == "changePage":
            page_display = (int(self.page) + 1) if self.page is not None else 1
            table.addField("Page", str(page_display))
        return table.to_html()


version = 3
name = "map-to-streamdeck"
create = MapToStreamDeck
