# -*- coding: utf-8; -*-
#
# Map to Stream Deck — control a connected Stream Deck via the plugin bridge.
# Change / Next / Previous / Return to Last switch unlimited GEX virtual banks and paint keys.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
import threading
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
    ("nextPage", "Next Page"),
    ("previousPage", "Previous Page"),
    ("returnToLast", "Return to Last"),
]

PAGE_COMMANDS = frozenset(cmd for cmd, _ in FUNCTIONS)
# Functions that jump to a specific/adjacent page (support timed auto-return).
AUTO_RETURN_COMMANDS = frozenset({"changePage", "nextPage", "previousPage"})

# Elgato DeviceType -> single plugin profile (pages are pages, not extra profiles).
PROFILE_BY_DEVICE_TYPE = {
    0: "profiles/jgex",  # Stream Deck (classic)
    1: "profiles/jgex-mini",  # Mini
    2: "profiles/jgex-xl",  # XL
    7: "profiles/jgex-plus",  # Stream Deck +
    9: "profiles/jgex-neo",  # Neo
}
DEFAULT_PROFILE = "profiles/jgex-xl"

# Pending auto-return timers keyed by device_id (one pending return per deck).
_auto_return_timers: dict[str, threading.Timer] = {}
DEFAULT_AUTO_RETURN_SECONDS = 5.0


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


def adjacent_page_1based(device_id: str, delta: int) -> int:
    """Next/previous GEX page (1-based), wrapping within ``list_pages``."""
    from gremlin.ui.streamdeck_device import StreamDeckBridge

    bridge = StreamDeckBridge()
    device_id = device_id or ""
    pages = list(bridge.list_pages(device_id) or [1])
    if not pages:
        pages = [1]
    current = bridge.get_active_page(device_id) if device_id else pages[0]
    if current not in pages:
        pages = sorted(set(pages) | {current})
    idx = pages.index(current)
    return pages[(idx + int(delta)) % len(pages)]


def cancel_auto_return(device_id: str = "") -> None:
    """Cancel any pending auto-return for a deck (or all if device_id empty)."""
    if device_id:
        timer = _auto_return_timers.pop(device_id, None)
        if timer is not None:
            timer.cancel()
        return
    for key in list(_auto_return_timers.keys()):
        timer = _auto_return_timers.pop(key, None)
        if timer is not None:
            timer.cancel()


def schedule_auto_return(device_id: str, page_0based: int, seconds: float) -> None:
    """After ``seconds``, switch the deck back to ``page_0based`` (action page index)."""
    device_id = device_id or ""
    cancel_auto_return(device_id)
    try:
        delay = float(seconds)
    except (TypeError, ValueError):
        delay = 0.0
    if delay <= 0:
        return

    def _fire():
        _auto_return_timers.pop(device_id, None)
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
            syslog.info(f"Map to Stream Deck: Auto-return -> GEX bank {int(page_0based) + 1} device={device_id[:12] if device_id else '?'}")
            bridge.change_page(device_id, int(page_0based), "")
        except Exception as exc:
            syslog.warning(f"Map to Stream Deck: auto-return failed: {exc}")

    timer = threading.Timer(delay, _fire)
    timer.daemon = True
    _auto_return_timers[device_id] = timer
    timer.start()


def apply_change_page(
    device_id: str,
    page_0based: int,
    *,
    auto_return: bool = False,
    auto_return_seconds: float = DEFAULT_AUTO_RETURN_SECONDS,
    profile: str = "",
) -> bool:
    """Switch GEX virtual page; optionally schedule return to the prior page."""
    from gremlin.ui.streamdeck_device import StreamDeckBridge

    bridge = StreamDeckBridge()
    if not bridge.started:
        bridge.start()

    device_id = device_id or ""
    # Any new Change Page cancels a pending return for this deck.
    cancel_auto_return(device_id)

    previous_1based = bridge.get_active_page(device_id) if device_id else 1
    try:
        target_0based = max(0, int(page_0based))
    except (TypeError, ValueError):
        target_0based = 0
    target_1based = target_0based + 1

    ok = bool(bridge.change_page(device_id, target_0based, profile or ""))
    if not ok:
        return False

    if auto_return and previous_1based != target_1based:
        schedule_auto_return(device_id, max(0, previous_1based - 1), auto_return_seconds)
    return True


def apply_return_to_last(device_id: str) -> bool:
    """Switch to the page that was active before the current one."""
    from gremlin.ui.streamdeck_device import StreamDeckBridge

    bridge = StreamDeckBridge()
    if not bridge.started:
        bridge.start()
    device_id = device_id or ""
    cancel_auto_return(device_id)
    return bool(bridge.return_to_last_page(device_id))


def apply_page_command(
    device_id: str,
    command: str,
    page_0based: int = 0,
    *,
    auto_return: bool = False,
    auto_return_seconds: float = DEFAULT_AUTO_RETURN_SECONDS,
    profile: str = "",
) -> bool:
    """Run Change / Next / Previous / Return to Last with optional auto-return."""
    cmd = command or "changePage"
    if cmd == "returnToLast":
        return apply_return_to_last(device_id)
    if cmd == "nextPage":
        page_0based = adjacent_page_1based(device_id, +1) - 1
    elif cmd == "previousPage":
        page_0based = adjacent_page_1based(device_id, -1) - 1
    elif cmd != "changePage":
        syslog.warning(f"Map to Stream Deck: unsupported function [{cmd}]")
        return False
    return apply_change_page(
        device_id,
        page_0based,
        auto_return=auto_return,
        auto_return_seconds=auto_return_seconds,
        profile=profile,
    )


class MapToStreamDeckWidget(gremlin.input_item.AbstractActionWidget):
    """UI: pick a connected Stream Deck, then a page function."""

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
        self.test_btn.setToolTip("Run this page function now (profile does not need to be running)")
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
        self.main_layout.addWidget(gremlin.ui.ui_common.getHContainer(self.function_widget, "Function:", widget_only=True))

        self.page_widget = gremlin.ui.ui_common.QDataComboBox()
        self.page_widget.setMinimumWidth(220)
        self.page_widget.setToolTip(
            "GEX virtual page (Companion-style bank). Unlimited — not limited by Elgato's ~10 profile pages. "
            "Populate one Elgato page with JG Ex Buttons as the hardware viewport."
        )
        self.page_widget.currentIndexChanged.connect(self._page_changed)
        self.page_row = gremlin.ui.ui_common.getHContainer(self.page_widget, "Page:", widget_only=True)
        self.main_layout.addWidget(self.page_row)

        self.auto_return_widget = QtWidgets.QCheckBox("Auto-return to previous page")
        self.auto_return_widget.setToolTip("After switching, automatically return to the page that was active before this action.")
        self.auto_return_widget.setChecked(bool(self.action_data.auto_return))
        self.auto_return_widget.toggled.connect(self._auto_return_toggled)

        self.auto_return_seconds_widget = QtWidgets.QDoubleSpinBox()
        self.auto_return_seconds_widget.setRange(0.1, 3600.0)
        self.auto_return_seconds_widget.setDecimals(1)
        self.auto_return_seconds_widget.setSingleStep(0.5)
        self.auto_return_seconds_widget.setSuffix(" s")
        self.auto_return_seconds_widget.setToolTip("Seconds to stay on the target page before returning")
        try:
            seconds = float(self.action_data.auto_return_seconds)
        except (TypeError, ValueError):
            seconds = DEFAULT_AUTO_RETURN_SECONDS
        self.auto_return_seconds_widget.setValue(max(0.1, seconds))
        self.auto_return_seconds_widget.valueChanged.connect(self._auto_return_seconds_changed)

        self.auto_return_row = gremlin.ui.ui_common.getHContainer(
            [self.auto_return_widget, self.auto_return_seconds_widget],
            widget_only=True,
        )
        self.main_layout.addWidget(self.auto_return_row)

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(
            self.action_data.execute_on_press,
            self.action_data.execute_on_release,
            press_callback=self._press_changed,
            release_callback=self._release_changed,
        )
        
        if not self.action_data.execute_on_press and not self.action_data.execute_on_release:
            self.action_data.execute_on_press = True
            self._execute_widget.execute_on_press = True
        self.main_layout.addWidget(self._execute_widget)

        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
            bridge.devices_changed.connect(self._refresh_devices)
            bridge.plugin_connected.connect(self._refresh_devices)
            bridge.virtual_page_changed.connect(self._on_virtual_page_changed)
        except Exception:
            pass

        self._refresh_devices()
        self._refresh_pages()
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

    def _page_choices(self, device_id: str) -> list[tuple[int, str]]:
        """Return [(1-based page, label), ...] for the selected deck only."""
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
            did = device_id or ""
            if not did and bridge.devices:
                did = next(iter(bridge.devices.keys()))
            pages = bridge.list_pages(did) if did else [1]
            if not pages:
                pages = [1]
            out = []
            for page in pages:
                name = bridge.page_name(did, page) if did else f"Page {page}"
                if name == f"Page {page}":
                    label = f"{page}. Page {page}"
                else:
                    label = f"{page}. {name}"
                out.append((page, label))
            return out
        except Exception:
            return [(1, "1. Page 1")]

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
        self._refresh_pages()

    def _refresh_pages(self):
        if not Shiboken.isValid(self) or not Shiboken.isValid(self.page_widget):
            return
        device_id = self.action_data.device_id or (self.device_widget.currentData() if Shiboken.isValid(self.device_widget) else "") or ""
        stored = self.action_data.page
        want = 1 if stored is None else int(stored) + 1

        choices = self._page_choices(device_id)
        page_nums = {p for p, _ in choices}
        if want not in page_nums:
            choices.append((want, f"{want}. Page {want}"))
            choices.sort(key=lambda x: x[0])

        self.page_widget.blockSignals(True)
        self.page_widget.clear()
        select_idx = 0
        for i, (page, label) in enumerate(choices):
            self.page_widget.addItem(label, page)
            if page == want:
                select_idx = i
        self.page_widget.setCurrentIndex(select_idx)
        self.page_widget.blockSignals(False)
        # Keep action_data in sync with the combo selection.
        data = self.page_widget.currentData()
        if data is not None:
            self.action_data.page = max(0, int(data) - 1)

    def _on_virtual_page_changed(self, device_id, page):
        if not Shiboken.isValid(self):
            return
        selected = self.action_data.device_id or ""
        if selected and device_id and selected != device_id:
            return
        self._refresh_pages()

    def _update_visibility(self):
        cmd = self.action_data.command or "changePage"
        show_auto = cmd in AUTO_RETURN_COMMANDS
        self.page_row.setVisible(cmd == "changePage")
        self.auto_return_row.setVisible(show_auto)
        self.auto_return_seconds_widget.setVisible(show_auto and bool(self.action_data.auto_return))

    def _send_page_command_now(self) -> bool:
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
        cmd = self.action_data.command or "changePage"
        profile = resolve_profile_for_device(device_id, page)
        return apply_page_command(
            device_id,
            cmd,
            int(page),
            auto_return=bool(self.action_data.auto_return),
            auto_return_seconds=float(self.action_data.auto_return_seconds or DEFAULT_AUTO_RETURN_SECONDS),
            profile=profile,
        )

    @QtCore.Slot()
    def _test_clicked(self):
        # Sync page from combo before sending (Change Page only).
        if (self.action_data.command or "") == "changePage":
            self._page_changed()
        cmd = self.action_data.command or "changePage"
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            connected = bool(StreamDeckBridge().plugin_is_connected)
        except Exception:
            connected = False
        ok = self._send_page_command_now()
        if ok:
            extra = ""
            if cmd in AUTO_RETURN_COMMANDS and self.action_data.auto_return:
                secs = float(self.action_data.auto_return_seconds or DEFAULT_AUTO_RETURN_SECONDS)
                extra = f"\n\nAuto-return to the previous page in {secs:g} s."
            label = dict(FUNCTIONS).get(cmd, "Page")
            detail = (
                "Returned to the previously displayed page."
                if cmd == "returnToLast"
                else ("Live JG Ex keys should show that bank's titles. Presses now run mappings for that page.")
            )
            gremlin.ui.ui_common.MessageBoxInfo(
                title="Map to Stream Deck",
                prompt=f"{label} activated.\n\n{detail}{extra}",
            )
        elif not connected:
            gremlin.ui.ui_common.MessageBoxWarning(
                title="Map to Stream Deck",
                prompt=("Plugin is not connected.\nEnable the Stream Deck bridge and confirm the PI shows Connected."),
            )
        elif cmd == "returnToLast":
            gremlin.ui.ui_common.MessageBoxWarning(
                title="Map to Stream Deck",
                prompt=("No previous page is stored yet.\nChange to another page first, then use Return to Last."),
            )
        else:
            gremlin.ui.ui_common.MessageBoxWarning(
                title="Map to Stream Deck",
                prompt="Could not change page. Check the Stream Deck bridge connection.",
            )

    @QtCore.Slot()
    def _device_changed(self):
        self.action_data.device_id = self.device_widget.currentData() or ""
        self._refresh_pages()

    @QtCore.Slot()
    def _function_changed(self):
        self.action_data.command = self.function_widget.currentData() or "changePage"
        self._update_visibility()
        if (self.action_data.command or "") == "changePage":
            self._refresh_pages()

    @QtCore.Slot()
    def _page_changed(self):
        data = self.page_widget.currentData()
        if data is None:
            return
        self.action_data.page = max(0, int(data) - 1)

    def _auto_return_toggled(self, checked: bool):
        self.action_data.auto_return = bool(checked)
        self._update_visibility()

    def _auto_return_seconds_changed(self, value: float):
        self.action_data.auto_return_seconds = max(0.1, float(value))

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
        # Only Stream Deck events carry an Elgato deviceId on the identifier.
        # State/Joystick InputItem.device_id is the GEX device string (e.g. state
        # tab GUID 72bbc0f4…) — using that here sent Change Page to a non-deck.
        if event.event_type == InputType.StreamDeck:
            ident = event.identifier
            elgato_id = getattr(ident, "device_id", None) or getattr(ident, "_elgato_device_id", None)
            if elgato_id and elgato_id in bridge.devices:
                device_id = elgato_id

        devices = bridge.devices
        if device_id and device_id not in devices:
            syslog.warning(
                f"Map to Stream Deck: device [{device_id[:12]}] is not a connected Stream Deck (src={event.event_type.name}) — check Device selection."
            )
            device_id = ""
        if not device_id:
            if len(devices) == 1:
                device_id = next(iter(devices.keys()))
            elif len(devices) > 1:
                syslog.warning("Map to Stream Deck: no device selected and multiple decks are connected — pick a Device in the action.")
                return True
            else:
                syslog.warning("Map to Stream Deck: no Stream Deck connected (plugin bridge).")
                return True

        if cmd in PAGE_COMMANDS:
            page = self.action_data.page
            if page is None:
                page = 0
            label = dict(FUNCTIONS).get(cmd, cmd)
            syslog.info(
                f"Map to Stream Deck: {label} "
                f"device={device_id[:12] if device_id else '?'} "
                f"page0={int(page)} pressed={is_pressed} "
                f"src={event.event_type.name}"
                + (f" (auto-return {float(self.action_data.auto_return_seconds or DEFAULT_AUTO_RETURN_SECONDS):g}s)" if self.action_data.auto_return else "")
            )
            ok = apply_page_command(
                device_id,
                cmd,
                int(page),
                auto_return=bool(self.action_data.auto_return),
                auto_return_seconds=float(self.action_data.auto_return_seconds or DEFAULT_AUTO_RETURN_SECONDS),
            )
            if not ok:
                syslog.warning(f"Map to Stream Deck: {label} failed for device={device_id[:12] if device_id else '?'}")
        else:
            syslog.warning(f"Map to Stream Deck: unsupported function [{cmd}]")

        return True


class MapToStreamDeck(gremlin.input_item.AbstractAction):
    name = "Map to Stream Deck"
    tag = "map-to-streamdeck"
    hint = "Control a connected Stream Deck (Change / Next / Previous / Return to Last)"

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
        self.auto_return = False
        self.auto_return_seconds = DEFAULT_AUTO_RETURN_SECONDS
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
        # Keep mappings runnable once configured even if the Options toggle
        # flaps; bridge start is handled at profile start / functor time.
        return bool(self.command)

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
        self.auto_return = safe_read(node, "auto-return", bool, False)
        try:
            seconds = float(safe_read(node, "auto-return-seconds", float, DEFAULT_AUTO_RETURN_SECONDS))
        except (TypeError, ValueError):
            seconds = DEFAULT_AUTO_RETURN_SECONDS
        self.auto_return_seconds = max(0.1, seconds)
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
        node.set("auto-return", safe_format(bool(self.auto_return), bool))
        node.set(
            "auto-return-seconds",
            safe_format(float(self.auto_return_seconds or DEFAULT_AUTO_RETURN_SECONDS), float),
        )
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
            try:
                from gremlin.ui.streamdeck_device import StreamDeckBridge

                bridge = StreamDeckBridge()
                did = self.device_id or ""
                if not did and bridge.devices:
                    did = next(iter(bridge.devices.keys()))
                title = bridge.page_name(did, page_display) if did else f"Page {page_display}"
                if title and title != f"Page {page_display}":
                    page_display = f"{page_display}. {title}"
                else:
                    page_display = str(page_display)
            except Exception:
                page_display = str(page_display)
            table.addField("Page", page_display)
        if self.command in PAGE_COMMANDS and self.auto_return:
            secs = float(self.auto_return_seconds or DEFAULT_AUTO_RETURN_SECONDS)
            table.addField("Auto-return", f"{secs:g} s")
        return table.to_html()


version = 3
name = "map-to-streamdeck"
create = MapToStreamDeck
