# -*- coding: utf-8; -*-
#
# Stream Deck plugin bridge for Joystick Gremlin Ex.
# Elgato Stream Deck software owns USB; a companion plugin talks to GEX over localhost WebSocket.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from typing import Any, Optional

from PySide6 import QtCore, QtWidgets, QtWebSockets, QtNetwork
from shiboken6 import Shiboken

import dinput
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.input_item
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.util
from gremlin.input_types import InputType
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import DeviceCategory, DeviceType, EventSourceType
from gremlin.util import compare_guid
from lxml import etree as ElementTree
from psygnal import Signal

syslog = logging.getLogger("system")

PROTOCOL_VERSION = 1
DEFAULT_BRIDGE_PORT = 9020
STREAMDECK_PAGES_CONFIG_KEY = "streamdeck_pages"
STREAMDECK_PLUGIN_FOLDER = "com.joystickgremlin.ex.sdPlugin"


def default_streamdeck_plugins_dir() -> Optional[str]:
    """Return the usual Elgato Plugins folder when it (or its parent) exists.

    Typical path: ``%AppData%\\Elgato\\StreamDeck\\Plugins``
    """
    appdata = os.environ.get("APPDATA") or ""
    if not appdata:
        return None
    streamdeck_root = os.path.join(appdata, "Elgato", "StreamDeck")
    plugins = os.path.join(streamdeck_root, "Plugins")
    if os.path.isdir(plugins):
        return plugins
    if os.path.isdir(streamdeck_root):
        return plugins  # create Plugins on install
    return None


def streamdeck_plugins_dir_hint() -> str:
    """Human-readable guidance for the normal Plugins location."""
    appdata = os.environ.get("APPDATA") or r"C:\Users\<you>\AppData\Roaming"
    return os.path.join(appdata, "Elgato", "StreamDeck", "Plugins")


def streamdeck_plugin_source_dir() -> Optional[str]:
    """Bundled / source-tree plugin folder next to the GEX install."""
    root = gremlin.util.get_root_folder()
    candidates = [
        os.path.join(str(root), "streamdeck_plugin", STREAMDECK_PLUGIN_FOLDER),
        os.path.join(str(root), STREAMDECK_PLUGIN_FOLDER),
    ]
    for path in candidates:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "manifest.json")):
            return path
    return None


def install_streamdeck_plugin(dest_plugins_dir: str) -> tuple[bool, str]:
    """Copy the JG Ex Stream Deck plugin into ``dest_plugins_dir``.

    Returns ``(ok, message)``. Caller should ask the user to quit Stream Deck first.
    """
    source = streamdeck_plugin_source_dir()
    if not source:
        return False, (
            "Could not find the bundled plugin folder "
            f"({STREAMDECK_PLUGIN_FOLDER}). Run from the JoystickGremlinEx source tree "
            "or a build that includes streamdeck_plugin/."
        )
    if not dest_plugins_dir:
        return False, "No destination Plugins folder was selected."

    dest = os.path.join(dest_plugins_dir, STREAMDECK_PLUGIN_FOLDER)
    try:
        os.makedirs(dest_plugins_dir, exist_ok=True)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
    except Exception as err:
        syslog.error(f"STREAMDECK: plugin install failed: {err}")
        return False, f"Install failed: {err}"

    syslog.info(f"STREAMDECK: plugin installed to {dest}")
    return True, f"Plugin installed to:\n{dest}\n\nQuit and relaunch Stream Deck software if it was running."


# Elgato DeviceType -> label when the plugin omits / weakens the user-facing name.
STREAMDECK_TYPE_NAMES = {
    0: "Stream Deck",
    1: "Stream Deck Mini",
    2: "Stream Deck XL",
    3: "Stream Deck Mobile",
    4: "Corsair G Keys",
    5: "Stream Deck Pedal",
    7: "Stream Deck +",
    9: "Stream Deck Neo",
}


def streamdeck_guid_for_device(device_id: str):
    """Stable GUID for a physical Stream Deck reported by the Elgato plugin."""
    if not device_id:
        return gremlin.shared_state.streamdeck_tab_guid
    u = uuid.uuid5(uuid.UUID(str(gremlin.shared_state.streamdeck_namespace_guid)), str(device_id))
    return gremlin.util.parse_guid(str(u))


def _is_weak_streamdeck_name(name: str, device_id: str = "") -> bool:
    if not name or not str(name).strip():
        return True
    s = str(name).strip()
    if device_id and s == f"Stream Deck ({device_id[:8]})":
        return True
    if s.startswith("Stream Deck (") and s.endswith(")") and len(s) <= 22:
        # Truncated opaque id fallback
        inner = s[len("Stream Deck (") : -1]
        if all(c in "0123456789abcdefABCDEF" for c in inner):
            return True
    if s.startswith("Stream Deck ") and len(s) <= 21:
        rest = s[len("Stream Deck ") :]
        if all(c in "0123456789abcdefABCDEF" for c in rest):
            return True
    return False


def friendly_streamdeck_name(name: str = None, device_type=None, device_id: str = "") -> str:
    """Prefer Elgato's user-facing device name; else type label; else short id."""
    if not _is_weak_streamdeck_name(name, device_id):
        return str(name).strip()
    try:
        dtype = int(device_type) if device_type is not None and device_type != "" else None
    except (TypeError, ValueError):
        dtype = None
    if dtype is not None and dtype in STREAMDECK_TYPE_NAMES:
        return STREAMDECK_TYPE_NAMES[dtype]
    if device_id:
        return f"Stream Deck ({device_id[:8]})"
    return "Stream Deck"


def normalize_button_id(button_id: str) -> str:
    """Normalize legacy coordinate IDs (0_0 -> 0:0)."""
    if button_id is None:
        return ""
    button_id = str(button_id).strip()
    if not button_id:
        return ""
    if "_" in button_id and ":" not in button_id:
        parts = button_id.split("_")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return f"{parts[0]}:{parts[1]}"
    return button_id


def normalize_page(page) -> int:
    """1-based GEX virtual page (Companion-style bank). Missing/invalid → 1.

    Not limited to Elgato's ~10 profile pages — GEX owns unlimited banks.
    """
    try:
        n = int(page)
    except (TypeError, ValueError):
        return 1
    if n < 1:
        return 1
    return n


# Elgato DeviceType → (columns, rows) for the key grid (Companion viewport).
# Only types listed here are treated as supported in the designer.
DEVICE_GRID_LAYOUTS = {
    0: (5, 3),   # Stream Deck / MK.2
    1: (3, 2),   # Mini
    2: (8, 4),   # XL
    3: (5, 3),   # Mobile
    7: (4, 2),   # Stream Deck + (keys; dials are separate)
    8: (4, 2),   # Stream Deck + (alt type id)
    9: (4, 2),   # Neo
}

# Known Elgato types that connect but have no JG Ex key/dial grid yet
# (e.g. Corsair G Keys = 4, Pedal = 5).
UNSUPPORTED_STREAMDECK_TYPES = frozenset({4, 5})


def parse_streamdeck_device_type(device_type) -> int | None:
    try:
        if device_type is None or device_type == "":
            return None
        return int(device_type)
    except (TypeError, ValueError):
        return None


def is_streamdeck_designer_supported(device_type=None) -> bool:
    """True when GEX knows a key (and optional dial) layout for this DeviceType."""
    dtype = parse_streamdeck_device_type(device_type)
    return dtype is not None and dtype in DEVICE_GRID_LAYOUTS


def device_grid_size(device_type=None) -> tuple[int, int] | None:
    """Return (columns, rows) for a supported Stream Deck DeviceType, else None."""
    dtype = parse_streamdeck_device_type(device_type)
    if dtype is not None and dtype in DEVICE_GRID_LAYOUTS:
        return DEVICE_GRID_LAYOUTS[dtype]
    return None


def make_slot_key(kind: str = "button", row=None, column=None, button_id: str = "") -> str:
    """Stable physical slot id: r{row}c{col}, else normalized Button ID."""
    kind = kind or "button"
    if row is not None and column is not None:
        try:
            return f"r{int(row)}c{int(column)}"
        except (TypeError, ValueError):
            pass
    bid = normalize_button_id(button_id)
    return bid or f"{kind}-slot"


def make_input_key(kind: str, button_id: str, device_id: str = "", page=1) -> str:
    """Stable config / message key: deviceId:kind:p{gexPage}:buttonId (or slot)."""
    kind = kind or "button"
    button_id = normalize_button_id(button_id)
    page = normalize_page(page)
    device_id = str(device_id) if device_id else ""
    if device_id:
        return f"{device_id}:{kind}:p{page}:{button_id}"
    return f"{kind}:p{page}:{button_id}"


def _coords_tuple(item_or_meta) -> tuple | None:
    if isinstance(item_or_meta, dict):
        row, column = item_or_meta.get("row"), item_or_meta.get("column")
    else:
        row = getattr(item_or_meta, "_row", None)
        column = getattr(item_or_meta, "_column", None)
    if row is None or column is None:
        return None
    try:
        return (int(row), int(column))
    except (TypeError, ValueError):
        return None


def _page_of(item_or_meta) -> int:
    if isinstance(item_or_meta, dict):
        return normalize_page(item_or_meta.get("page", 1))
    return normalize_page(getattr(item_or_meta, "page", 1))


def _slot_key_of(item_or_meta) -> str:
    if isinstance(item_or_meta, dict):
        sk = item_or_meta.get("slot_key")
        if sk:
            return str(sk)
        return make_slot_key(
            item_or_meta.get("kind") or "button",
            item_or_meta.get("row"),
            item_or_meta.get("column"),
            item_or_meta.get("button_id") or "",
        )
    sk = getattr(item_or_meta, "slot_key", None)
    if sk:
        return str(sk)
    return make_slot_key(
        getattr(item_or_meta, "kind", "button") or "button",
        getattr(item_or_meta, "_row", None),
        getattr(item_or_meta, "_column", None),
        getattr(item_or_meta, "button_id", "") or "",
    )


def _same_live_slot(a, b) -> bool:
    """Physical viewport slot (ignore GEX page) — context or device+kind+coords/id."""
    a_ctx = (a.get("context") if isinstance(a, dict) else getattr(a, "context", "")) or ""
    b_ctx = (b.get("context") if isinstance(b, dict) else getattr(b, "context", "")) or ""
    if a_ctx and b_ctx and a_ctx == b_ctx:
        return True
    a_dev = (a.get("device_id") if isinstance(a, dict) else getattr(a, "device_id", "")) or ""
    b_dev = (b.get("device_id") if isinstance(b, dict) else getattr(b, "device_id", "")) or ""
    a_kind = (a.get("kind") if isinstance(a, dict) else getattr(a, "kind", "button")) or "button"
    b_kind = (b.get("kind") if isinstance(b, dict) else getattr(b, "kind", "button")) or "button"
    if a_dev != b_dev or a_kind != b_kind:
        return False
    ca, cb = _coords_tuple(a), _coords_tuple(b)
    if ca is not None and ca == cb:
        return True
    return _slot_key_of(a) == _slot_key_of(b)


def _same_physical_streamdeck_key(a, b) -> bool:
    """Same GEX page + physical slot (profile duplicate collapse)."""
    if _page_of(a) != _page_of(b):
        return False
    return _same_live_slot(a, b)

def ensure_streamdeck_special_device(device_id: str, name: str = None, device_type=None):
    """Ensure a special DeviceType.StreamDeck exists for this Elgato deviceId."""
    if not device_id:
        return None
    guid = streamdeck_guid_for_device(device_id)
    label = friendly_streamdeck_name(name, device_type, device_id)
    # Profile XML / empty plugin updates often call this with only a device_id.
    # Never replace a good tab name ("Stream Deck XL") with "Stream Deck (b1772166)".
    existing = gremlin.joystick_handling.getDevice(guid)
    if existing is not None and existing.name:
        if _is_weak_streamdeck_name(label, device_id) and not _is_weak_streamdeck_name(existing.name, device_id):
            label = existing.name
    device = dinput.DeviceSummary()
    device.name = label
    device.device_guid = guid
    device.device_type = DeviceType.StreamDeck
    device.device_category = DeviceCategory.Special
    gremlin.joystick_handling.upsertSpecialDevice(device)
    try:
        gremlin.shared_state._virtual_device_guid_to_name_map[str(guid).casefold()] = label
    except Exception:
        pass
    return device


def resync_streamdeck_special_devices():
    """Re-register special devices for decks the bridge currently knows about."""
    try:
        bridge = StreamDeckBridge()
    except Exception:
        return
    for device_id, info in bridge.devices.items():
        ensure_streamdeck_special_device(device_id, info.get("name"), info.get("type"))


def legacy_streamdeck_tab_needed(profile=None) -> bool:
    """True if an old profile still has inputs under the shared Stream Deck GUID."""
    profile = profile or gremlin.shared_state.current_profile
    if not profile:
        return False
    legacy = gremlin.shared_state.streamdeck_tab_guid
    try:
        device_node = profile.getDeviceNode(legacy, autocreate=False)
    except Exception:
        device_node = None
    if device_node is None:
        return False
    try:
        if device_node.hasInputItems():
            return True
    except Exception:
        pass
    try:
        for mode_node in device_node.modes.values():
            config = mode_node.getConfig(InputType.StreamDeck)
            if config:
                return True
    except Exception:
        pass
    try:
        registry = profile.registry
        mode = gremlin.shared_state.edit_mode or gremlin.shared_state.current_mode
        items = registry.getInputItems(legacy, mode, InputType.StreamDeck) if mode else None
        if items:
            return True
    except Exception:
        pass
    return False


def should_show_streamdeck_tab(device_guid, profile=None) -> bool:
    """Whether a Stream Deck special device should get a UI tab right now."""
    if compare_guid(device_guid, gremlin.shared_state.streamdeck_tab_guid):
        return legacy_streamdeck_tab_needed(profile)
    bridge = StreamDeckBridge()
    return bridge.is_guid_connected(device_guid)


class StreamDeckInputItem(gremlin.input_item.InputItem):
    """Profile input bound to a JG Ex Button / Dial from the Stream Deck plugin.

    Like OSC/MIDI: input_id is this item (AbstractInputItem), not a string.
    Config map keys use message_key via ProfileModeNode.addInputItem / getInputIdKey.
    """

    def __init__(self, mode_object: gremlin.base_profile.ProfileModeNode = None, device_guid=None):
        # Fields used by display_name / setters — must exist before InputItem.__init__ runs.
        self._elgato_device_id = ""
        self._button_id = ""
        self._page = 1  # 1-based GEX virtual page (Companion-style bank)
        self._kind = "button"  # button | dial | dial_press
        self._title = ""
        self._title_expr = ""  # optional $(var:x) / $(state:y) expression for paint
        self._image = ""  # data-URL for setImage paint
        self._image_path = ""  # source file path (for UI)
        self._image_expr = ""
        self._image_pressed = ""  # optional pressed-state image data-URL
        self._image_pressed_path = ""
        # Companion-style appearance
        self._text_line2 = ""
        self._text_line3 = ""
        self._title_pressed = ""
        self._text_line2_pressed = ""
        self._text_line3_pressed = ""
        self._font_family = "Segoe UI"
        self._font_size = 18
        self._font_color = "#ffffff"
        self._text_h_align = "center"  # left|center|right
        self._text_v_align = "bottom"  # top|middle|bottom
        self._shrink_to_fit = True
        self._icon_h_align = "center"
        self._icon_v_align = "middle"
        self._bg_color = ""  # empty = default dark key
        # Pressed-state style (independent; defaults match released)
        self._font_family_pressed = "Segoe UI"
        self._font_size_pressed = 18
        self._font_color_pressed = "#ffffff"
        self._text_h_align_pressed = "center"
        self._text_v_align_pressed = "bottom"
        self._shrink_to_fit_pressed = True
        self._icon_h_align_pressed = "center"
        self._icon_v_align_pressed = "middle"
        self._bg_color_pressed = ""
        self._step_mode = "all"  # all | advance | latch
        self._step_index = 0
        self._step_wrap = True
        self._context = ""
        self._row = None
        self._column = None
        # 1-based page this slot mirrors (same coords); 0 = not linked
        self._linked_page = 0

        # Prefer the hosting device node GUID (per-deck); fall back to legacy tab GUID.
        if device_guid is None and mode_object is not None and getattr(mode_object, "parent", None) is not None:
            device_guid = getattr(mode_object.parent, "device_guid", None)
        if device_guid is None:
            device_guid = gremlin.shared_state.streamdeck_tab_guid
        if gremlin.joystick_handling.getDevice(device_guid) is None:
            placeholder = dinput.DeviceSummary()
            placeholder.name = "Stream Deck"
            placeholder.device_guid = device_guid
            placeholder.device_type = DeviceType.StreamDeck
            placeholder.device_category = DeviceCategory.Special
            gremlin.joystick_handling.upsertSpecialDevice(placeholder)
        super().__init__(
            mode_object,
            InputType.StreamDeck,
            device_guid=device_guid,
            custom_input_id_handler=self._handle_input_id_callback,
            override_input_type=InputType.JoystickButton,
        )
        self.setInputIdCallback(self._handle_input_id_callback)
        self.setInputType(InputType.StreamDeck)
        self.setOverrideInputType(InputType.JoystickButton)

    def _handle_input_id_callback(self):
        # InputItem IDs for non-hardware devices are the item itself (MIDI/OSC pattern).
        return self

    @property
    def message_key(self) -> str:
        return make_input_key(self._kind, self._button_id, self._elgato_device_id, self._page)

    @property
    def sortKey(self):
        """Keep grid order stable when Button ID / title change (avoid keys 'vanishing' off-screen)."""
        try:
            row = int(self._row) if self._row is not None else 999
        except (TypeError, ValueError):
            row = 999
        try:
            col = int(self._column) if self._column is not None else 999
        except (TypeError, ValueError):
            col = 999
        return (normalize_page(self._page), row, col, str(self._button_id or ""), str(self._kind or ""))

    @property
    def device_id(self) -> str:
        return self._elgato_device_id

    @device_id.setter
    def device_id(self, value: str):
        self._elgato_device_id = value or ""

    @property
    def button_id(self) -> str:
        return self._button_id

    @button_id.setter
    def button_id(self, value: str):
        self._button_id = normalize_button_id(value)

    @property
    def page(self) -> int:
        return normalize_page(self._page)

    @page.setter
    def page(self, value):
        self._page = normalize_page(value)

    @property
    def kind(self) -> str:
        return self._kind

    @kind.setter
    def kind(self, value: str):
        self._kind = value or "button"

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str):
        self._title = value or ""
        self.description = self.display_name

    @property
    def context(self) -> str:
        return self._context

    @context.setter
    def context(self, value: str):
        self._context = value or ""

    @property
    def slot_key(self) -> str:
        return make_slot_key(self._kind, self._row, self._column, self._button_id)

    @property
    def linked_page(self) -> int:
        """1-based source page this slot mirrors, or 0 if not linked."""
        try:
            page = int(self._linked_page or 0)
        except (TypeError, ValueError):
            return 0
        return page if page > 0 else 0

    @linked_page.setter
    def linked_page(self, value):
        try:
            page = int(value or 0)
        except (TypeError, ValueError):
            page = 0
        self._linked_page = page if page > 0 else 0

    @property
    def is_linked(self) -> bool:
        return self.linked_page > 0

    @property
    def image(self) -> str:
        return self._image

    @image.setter
    def image(self, value: str):
        self._image = value or ""

    @property
    def image_path(self) -> str:
        return self._image_path

    @image_path.setter
    def image_path(self, value: str):
        self._image_path = value or ""

    @property
    def title_expr(self) -> str:
        return self._title_expr

    @title_expr.setter
    def title_expr(self, value: str):
        self._title_expr = value or ""

    @property
    def image_expr(self) -> str:
        return self._image_expr

    @image_expr.setter
    def image_expr(self, value: str):
        self._image_expr = value or ""

    @property
    def image_pressed(self) -> str:
        return self._image_pressed

    @image_pressed.setter
    def image_pressed(self, value: str):
        self._image_pressed = value or ""

    @property
    def image_pressed_path(self) -> str:
        return self._image_pressed_path

    @image_pressed_path.setter
    def image_pressed_path(self, value: str):
        self._image_pressed_path = value or ""

    @property
    def text_line2(self) -> str:
        return self._text_line2

    @text_line2.setter
    def text_line2(self, value: str):
        self._text_line2 = value or ""

    @property
    def text_line3(self) -> str:
        return self._text_line3

    @text_line3.setter
    def text_line3(self, value: str):
        self._text_line3 = value or ""

    @property
    def title_pressed(self) -> str:
        return self._title_pressed

    @title_pressed.setter
    def title_pressed(self, value: str):
        self._title_pressed = value or ""

    @property
    def text_line2_pressed(self) -> str:
        return self._text_line2_pressed

    @text_line2_pressed.setter
    def text_line2_pressed(self, value: str):
        self._text_line2_pressed = value or ""

    @property
    def text_line3_pressed(self) -> str:
        return self._text_line3_pressed

    @text_line3_pressed.setter
    def text_line3_pressed(self, value: str):
        self._text_line3_pressed = value or ""

    @property
    def font_family(self) -> str:
        return self._font_family or "Segoe UI"

    @font_family.setter
    def font_family(self, value: str):
        self._font_family = (value or "Segoe UI").strip() or "Segoe UI"

    @property
    def font_size(self) -> int:
        try:
            return max(8, min(72, int(self._font_size or 18)))
        except (TypeError, ValueError):
            return 18

    @font_size.setter
    def font_size(self, value):
        try:
            self._font_size = max(8, min(72, int(value)))
        except (TypeError, ValueError):
            self._font_size = 18

    @property
    def font_color(self) -> str:
        return self._font_color or "#ffffff"

    @font_color.setter
    def font_color(self, value: str):
        self._font_color = value or "#ffffff"

    @property
    def text_h_align(self) -> str:
        v = (self._text_h_align or "center").lower()
        return v if v in ("left", "center", "right") else "center"

    @text_h_align.setter
    def text_h_align(self, value: str):
        v = (value or "center").lower()
        self._text_h_align = v if v in ("left", "center", "right") else "center"

    @property
    def text_v_align(self) -> str:
        v = (self._text_v_align or "bottom").lower()
        return v if v in ("top", "middle", "bottom") else "bottom"

    @text_v_align.setter
    def text_v_align(self, value: str):
        v = (value or "bottom").lower()
        self._text_v_align = v if v in ("top", "middle", "bottom") else "bottom"

    @property
    def shrink_to_fit(self) -> bool:
        return bool(self._shrink_to_fit)

    @shrink_to_fit.setter
    def shrink_to_fit(self, value: bool):
        self._shrink_to_fit = bool(value)

    @property
    def icon_h_align(self) -> str:
        v = (self._icon_h_align or "center").lower()
        return v if v in ("left", "center", "right") else "center"

    @icon_h_align.setter
    def icon_h_align(self, value: str):
        v = (value or "center").lower()
        self._icon_h_align = v if v in ("left", "center", "right") else "center"

    @property
    def icon_v_align(self) -> str:
        v = (self._icon_v_align or "middle").lower()
        return v if v in ("top", "middle", "bottom") else "middle"

    @icon_v_align.setter
    def icon_v_align(self, value: str):
        v = (value or "middle").lower()
        self._icon_v_align = v if v in ("top", "middle", "bottom") else "middle"

    @property
    def bg_color(self) -> str:
        return self._bg_color or ""

    @bg_color.setter
    def bg_color(self, value: str):
        self._bg_color = value or ""

    @property
    def font_family_pressed(self) -> str:
        return self._font_family_pressed or "Segoe UI"

    @font_family_pressed.setter
    def font_family_pressed(self, value: str):
        self._font_family_pressed = (value or "Segoe UI").strip() or "Segoe UI"

    @property
    def font_size_pressed(self) -> int:
        try:
            return max(8, min(72, int(self._font_size_pressed or 18)))
        except (TypeError, ValueError):
            return 18

    @font_size_pressed.setter
    def font_size_pressed(self, value):
        try:
            self._font_size_pressed = max(8, min(72, int(value)))
        except (TypeError, ValueError):
            self._font_size_pressed = 18

    @property
    def font_color_pressed(self) -> str:
        return self._font_color_pressed or "#ffffff"

    @font_color_pressed.setter
    def font_color_pressed(self, value: str):
        self._font_color_pressed = value or "#ffffff"

    @property
    def text_h_align_pressed(self) -> str:
        v = (self._text_h_align_pressed or "center").lower()
        return v if v in ("left", "center", "right") else "center"

    @text_h_align_pressed.setter
    def text_h_align_pressed(self, value: str):
        v = (value or "center").lower()
        self._text_h_align_pressed = v if v in ("left", "center", "right") else "center"

    @property
    def text_v_align_pressed(self) -> str:
        v = (self._text_v_align_pressed or "bottom").lower()
        return v if v in ("top", "middle", "bottom") else "bottom"

    @text_v_align_pressed.setter
    def text_v_align_pressed(self, value: str):
        v = (value or "bottom").lower()
        self._text_v_align_pressed = v if v in ("top", "middle", "bottom") else "bottom"

    @property
    def shrink_to_fit_pressed(self) -> bool:
        return bool(self._shrink_to_fit_pressed)

    @shrink_to_fit_pressed.setter
    def shrink_to_fit_pressed(self, value: bool):
        self._shrink_to_fit_pressed = bool(value)

    @property
    def icon_h_align_pressed(self) -> str:
        v = (self._icon_h_align_pressed or "center").lower()
        return v if v in ("left", "center", "right") else "center"

    @icon_h_align_pressed.setter
    def icon_h_align_pressed(self, value: str):
        v = (value or "center").lower()
        self._icon_h_align_pressed = v if v in ("left", "center", "right") else "center"

    @property
    def icon_v_align_pressed(self) -> str:
        v = (self._icon_v_align_pressed or "middle").lower()
        return v if v in ("top", "middle", "bottom") else "middle"

    @icon_v_align_pressed.setter
    def icon_v_align_pressed(self, value: str):
        v = (value or "middle").lower()
        self._icon_v_align_pressed = v if v in ("top", "middle", "bottom") else "middle"

    @property
    def bg_color_pressed(self) -> str:
        return self._bg_color_pressed or ""

    @bg_color_pressed.setter
    def bg_color_pressed(self, value: str):
        self._bg_color_pressed = value or ""

    def sync_pressed_style_from_released(self):
        """Copy released style into pressed (used when loading profiles without pressed style)."""
        self._font_family_pressed = self._font_family
        self._font_size_pressed = self._font_size
        self._font_color_pressed = self._font_color
        self._text_h_align_pressed = self._text_h_align
        self._text_v_align_pressed = self._text_v_align
        self._shrink_to_fit_pressed = self._shrink_to_fit
        self._icon_h_align_pressed = self._icon_h_align
        self._icon_v_align_pressed = self._icon_v_align
        self._bg_color_pressed = self._bg_color

    def style_snapshot(self) -> dict:
        """Appearance fields for copy/paste / swap."""
        return {
            "title": self.title,
            "text_line2": self.text_line2,
            "text_line3": self.text_line3,
            "title_pressed": self.title_pressed,
            "text_line2_pressed": self.text_line2_pressed,
            "text_line3_pressed": self.text_line3_pressed,
            "image": self.image,
            "image_path": self.image_path,
            "image_expr": self.image_expr,
            "image_pressed": self.image_pressed,
            "image_pressed_path": self.image_pressed_path,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "font_color": self.font_color,
            "text_h_align": self.text_h_align,
            "text_v_align": self.text_v_align,
            "shrink_to_fit": self.shrink_to_fit,
            "icon_h_align": self.icon_h_align,
            "icon_v_align": self.icon_v_align,
            "bg_color": self.bg_color,
            "font_family_pressed": self.font_family_pressed,
            "font_size_pressed": self.font_size_pressed,
            "font_color_pressed": self.font_color_pressed,
            "text_h_align_pressed": self.text_h_align_pressed,
            "text_v_align_pressed": self.text_v_align_pressed,
            "shrink_to_fit_pressed": self.shrink_to_fit_pressed,
            "icon_h_align_pressed": self.icon_h_align_pressed,
            "icon_v_align_pressed": self.icon_v_align_pressed,
            "bg_color_pressed": self.bg_color_pressed,
            "step_mode": self.step_mode,
            "step_wrap": self.step_wrap,
            "linked_page": self.linked_page,
        }

    def apply_style_snapshot(self, data: dict):
        if not isinstance(data, dict):
            return
        allowed = set(self.style_snapshot().keys())
        for key, value in data.items():
            if key in allowed and hasattr(self, key):
                setattr(self, key, value)
        # Older clipboards omit linked_page — treat as unlinked.
        if "linked_page" not in data:
            self.linked_page = 0

    @property
    def step_mode(self) -> str:
        return self._step_mode or "all"

    @step_mode.setter
    def step_mode(self, value: str):
        v = (value or "all").lower()
        if v not in ("all", "advance", "latch"):
            v = "all"
        self._step_mode = v

    @property
    def step_index(self) -> int:
        return int(self._step_index or 0)

    @step_index.setter
    def step_index(self, value):
        try:
            self._step_index = max(0, int(value))
        except (TypeError, ValueError):
            self._step_index = 0

    @property
    def step_wrap(self) -> bool:
        return bool(self._step_wrap)

    @step_wrap.setter
    def step_wrap(self, value: bool):
        self._step_wrap = bool(value)

    @property
    def display_name(self) -> str:
        prefix = f"P{self.page} · "
        if self.is_linked:
            return f"{prefix}↗ Page {self.linked_page}"
        if self._title:
            return prefix + self._title
        if self._kind == "dial":
            bid = str(self._button_id or "")
            if bid.endswith(":inc"):
                base = bid[:-4] or "?"
                return f"{prefix}Dial {base} clockwise"
            if bid.endswith(":dec"):
                base = bid[:-4] or "?"
                return f"{prefix}Dial {base} counterclockwise"
            return f"{prefix}Dial {self._button_id}"
        if self._kind == "dial_press":
            return f"{prefix}Dial {self._button_id} press"
        coords = ""
        if self._row is not None and self._column is not None:
            coords = f" (R{self._row}C{self._column})"
        return f"{prefix}Button {self._button_id}{coords}"

    def getDisplayName(self, full: bool = True) -> str:
        """List/widget titles call getDisplayName(); keep in sync with display_name."""
        return self.display_name if full else (self._title or self._button_id or self.slot_key)

    def parse_xml(self, node, data=None, extra_data=None):
        if node.tag != "input":
            return
        from gremlin.util import safe_read, read_guid

        if node.get("guid"):
            self.setId(read_guid(node, "guid"))
        self._elgato_device_id = safe_read(node, "device-id", str, "")
        self._kind = safe_read(node, "kind", str, "button")
        self.button_id = safe_read(node, "button-id", str, "")
        self.page = safe_read(node, "page", int, 1) if "page" in node.attrib else 1
        self.title = safe_read(node, "title", str, "")
        # Legacy title-expr ignored (feature removed); keep reading so old profiles load.
        _ = safe_read(node, "title-expr", str, "")
        self._title_expr = ""
        self._image = safe_read(node, "image", str, "")
        self._image_path = safe_read(node, "image-path", str, "")
        self._image_expr = safe_read(node, "image-expr", str, "")
        self._image_pressed = safe_read(node, "image-pressed", str, "")
        self._image_pressed_path = safe_read(node, "image-pressed-path", str, "")
        self._text_line2 = safe_read(node, "text-line2", str, "")
        self._text_line3 = safe_read(node, "text-line3", str, "")
        self._title_pressed = safe_read(node, "title-pressed", str, "")
        self._text_line2_pressed = safe_read(node, "text-line2-pressed", str, "")
        self._text_line3_pressed = safe_read(node, "text-line3-pressed", str, "")
        self.font_family = safe_read(node, "font-family", str, "Segoe UI")
        self.font_size = safe_read(node, "font-size", int, 18)
        self.font_color = safe_read(node, "font-color", str, "#ffffff")
        self.text_h_align = safe_read(node, "text-h-align", str, "center")
        self.text_v_align = safe_read(node, "text-v-align", str, "bottom")
        self.shrink_to_fit = safe_read(node, "shrink-to-fit", bool, True)
        self.icon_h_align = safe_read(node, "icon-h-align", str, "center")
        self.icon_v_align = safe_read(node, "icon-v-align", str, "middle")
        self._bg_color = safe_read(node, "bg-color", str, "")
        # Pressed style: explicit attrs, else copy released so older profiles keep looking right.
        if "font-family-pressed" in node.attrib or "font-size-pressed" in node.attrib or "bg-color-pressed" in node.attrib:
            self.font_family_pressed = safe_read(node, "font-family-pressed", str, self.font_family)
            self.font_size_pressed = safe_read(node, "font-size-pressed", int, self.font_size)
            self.font_color_pressed = safe_read(node, "font-color-pressed", str, self.font_color)
            self.text_h_align_pressed = safe_read(node, "text-h-align-pressed", str, self.text_h_align)
            self.text_v_align_pressed = safe_read(node, "text-v-align-pressed", str, self.text_v_align)
            self.shrink_to_fit_pressed = safe_read(node, "shrink-to-fit-pressed", bool, self.shrink_to_fit)
            self.icon_h_align_pressed = safe_read(node, "icon-h-align-pressed", str, self.icon_h_align)
            self.icon_v_align_pressed = safe_read(node, "icon-v-align-pressed", str, self.icon_v_align)
            self._bg_color_pressed = safe_read(node, "bg-color-pressed", str, self._bg_color)
        else:
            self.sync_pressed_style_from_released()
        self.step_mode = safe_read(node, "step-mode", str, "all")
        self.step_index = safe_read(node, "step-index", int, 0)
        self.step_wrap = safe_read(node, "step-wrap", bool, True)
        self.linked_page = safe_read(node, "linked-page", int, 0) if "linked-page" in node.attrib else 0
        self._context = safe_read(node, "context", str, "")
        if "row" in node.attrib:
            self._row = safe_read(node, "row", int, 0)
        if "column" in node.attrib:
            self._column = safe_read(node, "column", int, 0)
        self.setOverrideInputType(InputType.JoystickButton)
        if self._elgato_device_id:
            ensure_streamdeck_special_device(self._elgato_device_id)

    def from_xml(self, node, data=None, extra_data=None):
        for child in node:
            if child.tag == "input":
                self.parse_xml(child, data, extra_data)
        if node.tag == "input":
            self.parse_xml(node, data, extra_data)
        self.setOverrideInputType(InputType.JoystickButton)
        super().from_xml(node, data, extra_data)

    def to_xml(self, parent_node=None):
        node = ElementTree.Element("input")
        node.set("guid", str(self.id))
        node.set("device-id", self._elgato_device_id or "")
        node.set("button-id", self._button_id or "")
        node.set("page", str(self.page))
        node.set("kind", self._kind or "button")
        node.set("title", self._title or "")
        if self._image:
            node.set("image", self._image)
        if self._image_path:
            node.set("image-path", self._image_path)
        if self._image_expr:
            node.set("image-expr", self._image_expr)
        if self._image_pressed:
            node.set("image-pressed", self._image_pressed)
        if self._image_pressed_path:
            node.set("image-pressed-path", self._image_pressed_path)
        if self._text_line2:
            node.set("text-line2", self._text_line2)
        if self._text_line3:
            node.set("text-line3", self._text_line3)
        if self._title_pressed:
            node.set("title-pressed", self._title_pressed)
        if self._text_line2_pressed:
            node.set("text-line2-pressed", self._text_line2_pressed)
        if self._text_line3_pressed:
            node.set("text-line3-pressed", self._text_line3_pressed)
        if self.font_family and self.font_family != "Segoe UI":
            node.set("font-family", self.font_family)
        if self.font_size != 18:
            node.set("font-size", str(self.font_size))
        if self.font_color and self.font_color.lower() not in ("#ffffff", "#fff", "white"):
            node.set("font-color", self.font_color)
        if self.text_h_align != "center":
            node.set("text-h-align", self.text_h_align)
        if self.text_v_align != "bottom":
            node.set("text-v-align", self.text_v_align)
        if not self.shrink_to_fit:
            node.set("shrink-to-fit", "false")
        if self.icon_h_align != "center":
            node.set("icon-h-align", self.icon_h_align)
        if self.icon_v_align != "middle":
            node.set("icon-v-align", self.icon_v_align)
        if self._bg_color:
            node.set("bg-color", self._bg_color)
        if self.font_family_pressed and self.font_family_pressed != "Segoe UI":
            node.set("font-family-pressed", self.font_family_pressed)
        if self.font_size_pressed != 18:
            node.set("font-size-pressed", str(self.font_size_pressed))
        if self.font_color_pressed and self.font_color_pressed.lower() not in ("#ffffff", "#fff", "white"):
            node.set("font-color-pressed", self.font_color_pressed)
        if self.text_h_align_pressed != "center":
            node.set("text-h-align-pressed", self.text_h_align_pressed)
        if self.text_v_align_pressed != "bottom":
            node.set("text-v-align-pressed", self.text_v_align_pressed)
        if not self.shrink_to_fit_pressed:
            node.set("shrink-to-fit-pressed", "false")
        if self.icon_h_align_pressed != "center":
            node.set("icon-h-align-pressed", self.icon_h_align_pressed)
        if self.icon_v_align_pressed != "middle":
            node.set("icon-v-align-pressed", self.icon_v_align_pressed)
        if self._bg_color_pressed:
            node.set("bg-color-pressed", self._bg_color_pressed)
        # Always stamp one pressed-style marker when pressed differs from released defaults
        # so load can distinguish "legacy profile" vs "explicit pressed style".
        if (
            self.font_family_pressed != self.font_family
            or self.font_size_pressed != self.font_size
            or self.font_color_pressed != self.font_color
            or self.text_h_align_pressed != self.text_h_align
            or self.text_v_align_pressed != self.text_v_align
            or self.shrink_to_fit_pressed != self.shrink_to_fit
            or self.icon_h_align_pressed != self.icon_h_align
            or self.icon_v_align_pressed != self.icon_v_align
            or self.bg_color_pressed != self.bg_color
        ):
            node.set("font-family-pressed", self.font_family_pressed)
            node.set("font-size-pressed", str(self.font_size_pressed))
            node.set("font-color-pressed", self.font_color_pressed)
            node.set("text-h-align-pressed", self.text_h_align_pressed)
            node.set("text-v-align-pressed", self.text_v_align_pressed)
            node.set("shrink-to-fit-pressed", str(bool(self.shrink_to_fit_pressed)).lower())
            node.set("icon-h-align-pressed", self.icon_h_align_pressed)
            node.set("icon-v-align-pressed", self.icon_v_align_pressed)
            if self._bg_color_pressed:
                node.set("bg-color-pressed", self._bg_color_pressed)
            else:
                node.set("bg-color-pressed", "")
        if self.step_mode != "all":
            node.set("step-mode", self.step_mode)
            node.set("step-index", str(self.step_index))
            node.set("step-wrap", str(bool(self.step_wrap)).lower())
        if self.linked_page > 0:
            node.set("linked-page", str(self.linked_page))
        node.set("context", self._context or "")
        if self._row is not None:
            node.set("row", str(self._row))
        if self._column is not None:
            node.set("column", str(self._column))
        super().to_xml(node)
        return node
    def __hash__(self):
        key = self.message_key
        return hash(key) if key else hash(self.id)

    def __eq__(self, other):
        if isinstance(other, StreamDeckInputItem):
            return self.message_key == other.message_key
        if isinstance(other, str):
            return self.message_key == other
        return False


@SingletonDecorator
class StreamDeckBridge(QtCore.QObject):
    """Localhost WebSocket server bridging the Elgato plugin and GEX."""

    plugin_connected = Signal(bool)
    devices_changed = Signal()
    inputs_changed = Signal(object)  # device_guid
    status_message = Signal(str)
    virtual_page_changed = Signal(object, int)  # device_id, 1-based GEX page
    slot_pressed = Signal(object, object, object, bool)  # device_id, row, column, is_pressed
    # Qt signal (not psygnal) so we can QueuedConnection onto the UI thread.
    _outbound_text = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._server: Optional[QtWebSockets.QWebSocketServer] = None
        self._clients: list[QtWebSockets.QWebSocket] = []
        self._lock = threading.RLock()
        self._started = False
        self._plugin_connected = False
        # device_id -> {name, type, guid}
        self._devices: dict[str, dict] = {}
        # (device_id, kind, slot_key) -> live viewport metadata (no GEX page)
        self._live_inputs: dict[tuple, dict] = {}
        self._autorelease_timers: dict[tuple, threading.Timer] = {}
        # Companion-style: device_id -> active 1-based GEX virtual page
        self._active_page: dict[str, int] = {}
        # device_id -> previous 1-based page (for Return to Last)
        self._last_page: dict[str, int] = {}
        # device_id -> {page_int: name}
        self._page_names: dict[str, dict[int, str]] = {}
        # device_id -> ordered list of page numbers (explicit banks, may include empty)
        self._page_order: dict[str, list[int]] = {}
        # Coalesce inputs_changed / paint during willAppear storms
        self._inputs_changed_pending: set = set()
        self._paint_pending: set[str] = set()
        # Keys currently held on hardware — paint must keep pressed appearance until keyUp.
        # Entries: (device_id, "ctx", context) or (device_id, "slot", slot_key)
        self._held_slots: set[tuple] = set()
        # Bumped when overlay widgets should redraw (paint, hold, appearance).
        self._overlay_gen = 0

        self._outbound_text.connect(
            self._broadcast_text,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)
        try:
            el.profile_loaded.connect(self._load_page_metadata)
        except Exception:
            pass

    @property
    def started(self) -> bool:
        return self._started

    @property
    def plugin_is_connected(self) -> bool:
        return self._plugin_connected and len(self._clients) > 0

    def status_text(self) -> str:
        """Human-readable bridge/plugin status for the device tab."""
        config = gremlin.config.Configuration()
        if not config.streamdeck_enabled:
            return "Bridge: disabled (enable Stream Deck bridge in Options → Stream Deck)"
        port = config.streamdeck_bridge_port or DEFAULT_BRIDGE_PORT
        if not self._started:
            return f"Bridge: not listening on {port} (Apply bridge settings in Options, or reload tabs)"
        if self.plugin_is_connected:
            return "Plugin: connected"
        return f"Plugin: waiting for connection (listening on ws://127.0.0.1:{port})"

    @property
    def devices(self) -> dict[str, dict]:
        return dict(self._devices)

    def live_inputs_for_device(self, device_id: str) -> list[dict]:
        return [meta for (did, *_rest), meta in self._live_inputs.items() if did == device_id]

    def viewport_known(self, device_id: str) -> bool:
        """True when the plugin is connected and this deck has registered."""
        return bool(self.plugin_is_connected and device_id and device_id in self._devices)

    def live_button_coords(self, device_id: str) -> set[tuple[int, int]]:
        """Physical key slots that currently have a JG Ex Button (willAppear)."""
        coords = set()
        for meta in self.live_inputs_for_device(device_id):
            kind = (meta.get("kind") or "button")
            if kind not in ("button", "", None):
                continue
            row, column = meta.get("row"), meta.get("column")
            if row is None or column is None:
                continue
            try:
                coords.add((int(row), int(column)))
            except (TypeError, ValueError):
                pass
        return coords

    def live_dial_columns(self, device_id: str) -> set[int]:
        """Physical dial columns that currently have a JG Ex Dial (willAppear)."""
        cols = set()
        for meta in self.live_inputs_for_device(device_id):
            kind = (meta.get("kind") or "")
            if kind not in ("dial", "dial_press"):
                continue
            column = meta.get("column")
            if column is None:
                bid = str(meta.get("button_id") or "").split(":", 1)[0]
                if bid.isdigit():
                    column = int(bid)
            if column is None:
                continue
            try:
                cols.add(int(column))
            except (TypeError, ValueError):
                pass
        return cols

    def start(self, port: int = None):
        config = gremlin.config.Configuration()
        if not config.streamdeck_enabled:
            return
        if port is None:
            port = config.streamdeck_bridge_port or DEFAULT_BRIDGE_PORT
        if self._started:
            if self._server and self._server.serverPort() == port:
                return
            self.stop()

        self._server = QtWebSockets.QWebSocketServer(
            "GremlinEx-StreamDeck",
            QtWebSockets.QWebSocketServer.SslMode.NonSecureMode,
        )
        if not self._server.listen(QtNetwork.QHostAddress.SpecialAddress.LocalHost, int(port)):
            err = self._server.errorString()
            syslog.error(f"STREAMDECK: failed to listen on 127.0.0.1:{port}: {err}")
            self.status_message.emit(f"Bridge listen failed: {err}")
            self._server = None
            return

        self._server.newConnection.connect(self._on_new_connection)
        self._started = True
        syslog.info(f"STREAMDECK: bridge listening on ws://127.0.0.1:{port}")
        self.status_message.emit(self.status_text())
        self.plugin_connected.emit(self.plugin_is_connected)

    def stop(self):
        with self._lock:
            for sock in list(self._clients):
                try:
                    sock.close()
                except Exception:
                    pass
            self._clients.clear()
            if self._server:
                self._server.close()
                self._server = None
            self._started = False
            self._plugin_connected = False
            self.plugin_connected.emit(False)
            self.status_message.emit(self.status_text())

    def _profile_start(self):
        if gremlin.config.Configuration().streamdeck_enabled:
            self.start()
        self._load_page_metadata(emit=False)

    def _profile_stop(self):
        # Keep bridge running while GEX is open so Property Inspector stays connected.
        pass

    def _load_page_metadata(self, *_args, emit: bool = True):
        """Restore GEX virtual page names/order from the profile sidecar JSON."""
        # Always replace — stale names from a previously loaded profile must not linger.
        self._page_names = {}
        self._page_order = {}
        profile = gremlin.shared_state.current_profile
        data = {}
        try:
            fname = None
            if profile is not None:
                fname = getattr(profile, "_profile_config_fname", None)
                if not fname:
                    # Fall back to <profile>.json next to the XML.
                    try:
                        xml = getattr(profile, "profile_path", None) or getattr(profile, "_profile_fname", None)
                        if xml:
                            fname = os.path.splitext(str(xml))[0] + ".json"
                    except Exception:
                        fname = None
            if fname and os.path.isfile(fname):
                with open(fname, "r", encoding="utf-8") as hdl:
                    cfg = json.load(hdl)
                data = cfg.get(STREAMDECK_PAGES_CONFIG_KEY) or {}
            elif profile is not None and hasattr(profile, "_readConfig"):
                cfg = profile._readConfig() or {}
                data = cfg.get(STREAMDECK_PAGES_CONFIG_KEY) or {}
        except Exception as err:
            syslog.warning(f"STREAMDECK: page metadata load failed: {err}")
            data = {}
        if not isinstance(data, dict):
            data = {}
        for device_id, meta in data.items():
            if not device_id or not isinstance(meta, dict):
                continue
            order = meta.get("order") or []
            names = meta.get("names") or {}
            parsed_order: list[int] = []
            for p in order:
                try:
                    parsed_order.append(normalize_page(p))
                except Exception:
                    continue
            if parsed_order:
                # Keep as the set of known banks (list_pages sorts numerically).
                self._page_order[device_id] = parsed_order
            name_map: dict[int, str] = {}
            if isinstance(names, dict):
                for pk, pv in names.items():
                    try:
                        name_map[normalize_page(pk)] = str(pv or "").strip() or f"Page {normalize_page(pk)}"
                    except Exception:
                        continue
            if name_map:
                self._page_names[device_id] = name_map
        # Reconnect: bind orphaned sidecar blobs to live decks that lack metadata.
        try:
            live_ids = list(self._devices.keys())
        except Exception:
            live_ids = []
        self._adopt_orphan_page_metadata(live_ids)
        # Repair accidental cross-device copies (identical name maps on two live decks).
        self._dedupe_live_page_metadata(live_ids)
        if not emit:
            return
        # profile_loaded is psygnal (may fire on the worker) — refresh designers on UI thread.
        gremlin.util.InvokeUiMethod(self._emit_page_metadata_changed)

    def _emit_page_metadata_changed(self):
        for device_id in list(self._page_names.keys()) + list(self._devices.keys()):
            if not device_id:
                continue
            try:
                self.virtual_page_changed.emit(device_id, self.get_active_page(device_id))
            except Exception:
                pass

    def _adopt_orphan_page_metadata(self, live_ids: list[str] | None = None):
        """Attach sidecar page names to live decks when Elgato ids drifted or plugin was late."""
        try:
            all_live = list(self._devices.keys())
        except Exception:
            all_live = []
        # Orphans = sidecar keys that are not any currently connected deck.
        orphans = [sid for sid in self._page_names.keys() if sid and sid not in all_live]
        if not orphans:
            return
        targets = list(live_ids) if live_ids is not None else list(all_live)
        if not targets:
            return

        def _custom_score(device_id: str) -> tuple[int, int]:
            names = self._page_names.get(device_id) or {}
            order = self._page_order.get(device_id) or []
            custom = sum(
                1
                for page, label in names.items()
                if label and label != f"Page {page}"
            )
            return (custom, max(len(names), len(order)))

        for live_id in targets:
            if not live_id:
                continue
            live_custom, _live_richness = _custom_score(live_id)
            # Skip only when this live deck already has real custom names.
            # Generic "Page N" placeholders must still adopt richer orphans.
            if live_custom > 0:
                continue
            # Prefer an orphan that already matches this deck's profile input pages.
            input_pages = {item.page for item in self._iter_device_inputs(live_id)}
            best = None
            best_score = (-1, -1, -1)
            for orphan_id in orphans:
                names = self._page_names.get(orphan_id) or {}
                order = set(self._page_order.get(orphan_id) or [])
                overlap = len(input_pages.intersection(set(names.keys()) | order)) if input_pages else 0
                custom, richness = _custom_score(orphan_id)
                score = (overlap, custom, richness)
                if score > best_score:
                    best_score = score
                    best = orphan_id
            if best is None:
                continue
            # Require either page overlap with profile inputs, or a uniquely rich orphan.
            if best_score[0] <= 0 and not (len(orphans) == 1 and best_score[1] > 0):
                if len(all_live) != 1 or len(orphans) != 1:
                    # Still allow upgrade when live is empty/generic and orphan is rich.
                    if best_score[1] <= live_custom:
                        continue
            self._page_names[live_id] = dict(self._page_names.get(best) or {})
            if best in self._page_order:
                self._page_order[live_id] = list(self._page_order[best])
            syslog.info(
                f"STREAMDECK: adopted page metadata {best[:12]}… → {live_id[:12]}…"
            )

    def _dedupe_live_page_metadata(self, live_ids: list[str] | None = None):
        """Keep page banks per device: undo shared copies between connected decks."""
        try:
            live_ids = list(live_ids if live_ids is not None else self._devices.keys())
        except Exception:
            live_ids = []
        if len(live_ids) < 2:
            return
        changed = False
        for i, a in enumerate(live_ids):
            names_a = dict(self._page_names.get(a) or {})
            order_a = list(self._page_order.get(a) or [])
            if not names_a and len(order_a) <= 1:
                continue
            for b in live_ids[i + 1 :]:
                names_b = dict(self._page_names.get(b) or {})
                order_b = list(self._page_order.get(b) or [])
                inputs_a = {item.page for item in self._iter_device_inputs(a)}
                inputs_b = {item.page for item in self._iter_device_inputs(b)}
                shared_names = bool(names_a) and names_a == names_b
                shared_order = bool(order_a) and order_a == order_b and len(order_a) > 1
                if not shared_names and not shared_order:
                    continue
                score_a = len(inputs_a.intersection(set(order_a) | set(names_a.keys())))
                score_b = len(inputs_b.intersection(set(order_b) | set(names_b.keys())))
                if score_a >= score_b:
                    drop, drop_inputs = b, inputs_b
                else:
                    drop, drop_inputs = a, inputs_a
                drop_pages = sorted(drop_inputs) or [1]
                self._page_order[drop] = list(drop_pages)
                self._page_names[drop] = {}
                changed = True
                syslog.info(
                    f"STREAMDECK: split shared page metadata; reset {drop[:12]}… "
                    f"to pages {drop_pages}"
                )
        if changed:
            try:
                self._persist_page_metadata()
            except Exception:
                pass

    def _persist_page_metadata(self, device_id: str = None):
        """Save page names/order into the profile sidecar JSON."""
        profile = gremlin.shared_state.current_profile
        if profile is None or not hasattr(profile, "_setConfig"):
            return
        try:
            cfg = {}
            if hasattr(profile, "_readConfig"):
                cfg = dict(profile._readConfig(force=True) or {})
            payload = dict(cfg.get(STREAMDECK_PAGES_CONFIG_KEY) or {})
            device_ids = [device_id] if device_id else sorted(
                set(list(self._page_names.keys()) + list(self._page_order.keys()))
            )
            for did in device_ids:
                if not did:
                    continue
                order = list(self._page_order.get(did) or self.list_pages(did))
                names = {
                    str(p): self.page_name(did, p)
                    for p in order
                }
                # Never replace a rich saved name map with an empty/generic one.
                existing = payload.get(did) or {}
                existing_names = existing.get("names") or {}
                existing_custom = sum(
                    1
                    for pk, pv in existing_names.items()
                    if pv and str(pv) != f"Page {pk}"
                )
                new_custom = sum(
                    1
                    for pk, pv in names.items()
                    if pv and str(pv) != f"Page {pk}"
                )
                if existing_custom > 0 and new_custom == 0:
                    continue
                payload[did] = {"order": order, "names": names}
            profile._setConfig(STREAMDECK_PAGES_CONFIG_KEY, payload)
        except Exception as err:
            syslog.error(f"STREAMDECK: persist page metadata failed: {err}")

    def _on_new_connection(self):
        if not self._server:
            return
        sock = self._server.nextPendingConnection()
        if not sock:
            return
        sock.textMessageReceived.connect(lambda msg, s=sock: self._on_message(s, msg))
        sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))
        with self._lock:
            self._clients.append(sock)
        self._plugin_connected = True
        self.plugin_connected.emit(True)
        self.status_message.emit(self.status_text())
        self._send(sock, {"type": "hello", "version": PROTOCOL_VERSION, "app": "JoystickGremlinEx"})
        if gremlin.config.Configuration().verbose_mode_streamdeck:
            syslog.info("STREAMDECK: plugin client connected")

    def _on_disconnected(self, sock: QtWebSockets.QWebSocket):
        with self._lock:
            if sock in self._clients:
                self._clients.remove(sock)
            connected = len(self._clients) > 0
        self._plugin_connected = connected
        self.plugin_connected.emit(connected)
        self.status_message.emit(self.status_text())
        if gremlin.config.Configuration().verbose_mode_streamdeck:
            syslog.info("STREAMDECK: plugin client disconnected")

    def _send(self, sock: QtWebSockets.QWebSocket, payload: dict):
        try:
            sock.sendTextMessage(json.dumps(payload))
        except Exception as err:
            syslog.error(f"STREAMDECK: send failed: {err}")

    def _broadcast_text(self, data: str):
        """Must run on the Qt thread (connected via QueuedConnection)."""
        with self._lock:
            clients = list(self._clients)
        for sock in clients:
            try:
                sock.sendTextMessage(data)
            except Exception as err:
                syslog.error(f"STREAMDECK: broadcast failed: {err}")

    def broadcast(self, payload: dict):
        """Queue a JSON payload to all plugin clients (thread-safe)."""
        self._outbound_text.emit(json.dumps(payload))

    def send_command(self, command: str, **kwargs):
        """Send an outbound command to the Elgato plugin."""
        payload = {"type": "command", "command": command}
        payload.update(kwargs)
        with self._lock:
            n = len(self._clients)
        if n <= 0:
            syslog.warning(f"STREAMDECK: send_command [{command}] dropped - plugin not connected")
            return False
        # Never log full paint/image payloads (base64 can be huge and was aborting plugin handlers).
        if command in ("paintPage", "setImage"):
            keys = payload.get("keys") or []
            img_len = len(payload.get("image") or "")
            with_img = sum(1 for k in keys if isinstance(k, dict) and k.get("image"))
            syslog.info(
                f"STREAMDECK: send_command [{command}] clients={n} "
                f"keys={len(keys)} with_image={with_img} image_chars={img_len}"
            )
        elif gremlin.config.Configuration().verbose_mode_streamdeck:
            syslog.info(f"STREAMDECK: send_command [{command}] clients={n} data={payload}")
        else:
            syslog.info(f"STREAMDECK: send_command [{command}] clients={n}")
        self.broadcast(payload)
        return True

    def get_active_page(self, device_id: str) -> int:
        """1-based GEX virtual page currently shown on this deck's viewport."""
        device_id = device_id or ""
        return normalize_page(self._active_page.get(device_id, 1))

    def get_last_page(self, device_id: str) -> int | None:
        """Previous 1-based page before the current one, or None if unknown."""
        device_id = device_id or ""
        if not device_id or device_id not in self._last_page:
            return None
        return normalize_page(self._last_page[device_id])

    def set_virtual_page(self, device_id: str, page: int) -> bool:
        """Switch Companion-style GEX bank and paint live keys (no Elgato page limit)."""
        device_id = device_id or ""
        page = normalize_page(page)
        if not device_id:
            syslog.warning("STREAMDECK: set_virtual_page — empty device_id")
            return False
        if self.devices and device_id not in self.devices:
            syslog.warning(
                f"STREAMDECK: set_virtual_page — unknown device "
                f"[{device_id[:12]}…] (not in connected decks)"
            )
            return False
        previous = normalize_page(self._active_page.get(device_id, 1))
        if previous != page:
            self._last_page[device_id] = previous
            # Drop press-hold visuals — they belong to the old bank and would
            # ghost over the new page until keyUp (Change Page under the finger).
            self._clear_held_for_device(device_id)
        self._ensure_page_listed(device_id, page)
        self._active_page[device_id] = page
        self.paint_active_page(device_id)
        self.virtual_page_changed.emit(device_id, page)
        return True

    def return_to_last_page(self, device_id: str) -> bool:
        """Switch back to the page that was active before the current one."""
        device_id = device_id or ""
        last = self.get_last_page(device_id)
        if last is None:
            syslog.info(
                f"STREAMDECK: Return to Last — no previous page for "
                f"device={device_id[:12] if device_id else '?'}"
            )
            return False
        current = self.get_active_page(device_id)
        if last == current:
            return True
        syslog.info(
            f"STREAMDECK: Return to Last {current} -> {last} "
            f"device={device_id[:12] if device_id else '?'}"
        )
        return self.set_virtual_page(device_id, last)

    def change_page(self, device_id: str, page: int, profile: str = "") -> bool:
        """Map to Stream Deck Change Page — GEX virtual bank (0-based page arg from action).

        ``page`` is 0-based from Map to Stream Deck (page 0 → GEX bank 1).
        ``profile`` is ignored for virtual banks (kept for API compatibility).
        """
        try:
            page_i = int(page)
        except (TypeError, ValueError):
            page_i = 0
        if page_i < 0:
            page_i = 0
        return self.set_virtual_page(device_id or "", page_i + 1)

    def list_pages(self, device_id: str) -> list[int]:
        """Ordered GEX virtual pages for a deck (at least page 1).

        Always numeric ascending. Visit/activation order must not scramble the list
        (that previously happened via ``_ensure_page_listed`` during page clicks).
        """
        device_id = device_id or ""
        pages = set(self._page_order.get(device_id) or [])
        for item in self._iter_device_inputs(device_id):
            pages.add(item.page)
        if not pages:
            pages.add(1)
        return sorted(pages)

    def page_name(self, device_id: str, page: int) -> str:
        """Return the display name for a page on this device only (no cross-deck lookup)."""
        page = normalize_page(page)
        device_id = device_id or ""
        names = self._page_names.get(device_id) or {}
        if page in names and names[page]:
            return names[page]
        return f"Page {page}"

    def rename_page(self, device_id: str, page: int, name: str):
        device_id = device_id or ""
        page = normalize_page(page)
        self._page_names.setdefault(device_id, {})[page] = (name or "").strip() or f"Page {page}"
        self._persist_page_metadata(device_id)
        self.virtual_page_changed.emit(device_id, self.get_active_page(device_id))

    def add_page(self, device_id: str, name: str = "") -> int:
        """Append a new empty GEX virtual page; returns its 1-based number."""
        device_id = device_id or ""
        existing = self.list_pages(device_id)
        new_page = (max(existing) if existing else 0) + 1
        self._ensure_page_listed(device_id, new_page)
        if name:
            self.rename_page(device_id, new_page, name)
        else:
            self._persist_page_metadata(device_id)
        self.virtual_page_changed.emit(device_id, self.get_active_page(device_id))
        return new_page

    def delete_page(self, device_id: str, page: int) -> bool:
        """Remove a GEX page and its inputs. Keeps at least one page."""
        device_id = device_id or ""
        page = normalize_page(page)
        pages = self.list_pages(device_id)
        if len(pages) <= 1 or page not in pages:
            return False
        profile = gremlin.shared_state.current_profile
        mode = gremlin.shared_state.edit_mode or gremlin.shared_state.current_mode
        if profile and mode:
            device_guid = self._profile_device_guid(device_id)
            try:
                mode_object = profile.getDeviceNode(device_guid, autocreate=False).getModeNode(mode, autocreate=False)
            except Exception:
                mode_object = None
            if mode_object is not None:
                config = mode_object.getConfig(InputType.StreamDeck) or {}
                for key, item in list(config.items()):
                    if isinstance(item, StreamDeckInputItem) and item.page == page:
                        try:
                            if hasattr(mode_object, "removeInputItem"):
                                mode_object.removeInputItem(item)
                            else:
                                config.pop(key, None)
                        except Exception:
                            config.pop(key, None)
        order = [p for p in self.list_pages(device_id) if p != page]
        self._page_order[device_id] = order
        names = self._page_names.get(device_id)
        if names and page in names:
            names.pop(page, None)
        if self.get_active_page(device_id) == page:
            self.set_virtual_page(device_id, order[0] if order else 1)
        else:
            self.virtual_page_changed.emit(device_id, self.get_active_page(device_id))
        self._persist_page_metadata(device_id)
        self._bump_overlay_gen()
        self.inputs_changed.emit(self._profile_device_guid(device_id))
        return True

    def _ensure_page_listed(self, device_id: str, page: int):
        page = normalize_page(page)
        order = self._page_order.setdefault(device_id or "", [])
        if page not in order:
            order.append(page)

    def overlay_generation(self) -> int:
        """Monotonic stamp for overlay widgets that mirror this bridge."""
        return int(self._overlay_gen)

    def _bump_overlay_gen(self):
        self._overlay_gen = int(self._overlay_gen) + 1

    def resolve_overlay_device_id(self, requested: str = "") -> str:
        """Return a connected deck id: the requested one, else the first supported deck."""
        requested = requested or ""
        if requested and requested in self._devices:
            return requested
        if requested:
            return requested
        for did, info in self._devices.items():
            if is_streamdeck_designer_supported((info or {}).get("type")):
                return did
        if self._devices:
            return next(iter(self._devices))
        return ""

    def held_slot_keys(self, device_id: str) -> frozenset[str]:
        """Physical slot keys currently held on this deck."""
        device_id = device_id or ""
        return frozenset(
            str(k[2]) for k in self._held_slots if k[0] == device_id and k[1] == "slot" and k[2]
        )

    def overlay_slots(self, device_id: str, page: int) -> dict[tuple, object]:
        """Map (kind, row, col) → StreamDeckInputItem for overlay paint.

        Linked keys resolve to their source-page item so the overlay mirrors
        the hardware paint (empty proxies would otherwise draw blank).
        """
        page = normalize_page(page)
        device_id = device_id or ""
        slots: dict[tuple, object] = {}
        for item in self._iter_device_inputs(device_id):
            if item.page != page:
                continue
            display = item
            if getattr(item, "is_linked", False):
                display = self.resolve_linked_source(item)
                if display is None:
                    continue
            kind = getattr(item, "kind", "button") or "button"
            if kind == "button":
                coords = _coords_tuple(item)
                if coords:
                    slots[("button", coords[0], coords[1])] = display
                continue
            if kind != "dial_press":
                continue
            col = None
            try:
                col = int(item._column) if item._column is not None else None
            except (TypeError, ValueError):
                col = None
            if col is None:
                try:
                    bid = str(item.button_id or "")
                    if bid and ":" not in bid and not bid.endswith((":inc", ":dec")):
                        col = int(bid)
                except (TypeError, ValueError):
                    col = None
            if col is not None:
                slots[("dial_press", 0, int(col))] = display
        return slots

    def _iter_device_inputs(self, device_id: str) -> list:
        profile = gremlin.shared_state.current_profile
        mode = gremlin.shared_state.edit_mode or gremlin.shared_state.current_mode
        if not profile or not mode or not device_id:
            return []
        try:
            mode_object = profile.getDeviceNode(self._profile_device_guid(device_id), autocreate=False)
            mode_object = mode_object.getModeNode(mode, autocreate=False) if mode_object else None
        except Exception:
            mode_object = None
        if mode_object is None:
            return []
        config = mode_object.getConfig(InputType.StreamDeck) or {}
        return [i for i in config.values() if isinstance(i, StreamDeckInputItem) and (i.device_id or "") == device_id]

    def find_input_for_slot(self, device_id: str, page: int, meta: dict) -> StreamDeckInputItem | None:
        """Locate profile input for GEX page + physical slot.

        Live JG Ex Dial instances are kind ``dial``; designer appearance lives on
        ``dial_press``. Painting resolves dial → dial_press so LCD backgrounds apply.

        Dial Button IDs from the plugin are often ``row:col`` (e.g. ``0:2``). Do **not**
        treat the left side of ``:`` as the dial index — that wrongly maps every dial
        on row 0 to dial_press ``0``.
        """
        page = normalize_page(page)
        device_id = device_id or ""
        kind = meta.get("kind") or "button"
        kinds = [kind]
        if kind == "dial":
            kinds.append("dial_press")
        elif kind == "dial_press":
            kinds.append("dial")
        slot = _slot_key_of(meta)
        coords = _coords_tuple(meta)
        button_id = normalize_button_id(meta.get("button_id") or "")

        dial_col = None
        if kind in ("dial", "dial_press"):
            if coords is not None:
                dial_col = coords[1]
            elif button_id.isdigit():
                dial_col = int(button_id)
            elif ":" in button_id:
                parts = button_id.split(":", 1)
                # Prefer column from row:col; bare "3:inc" uses the left side.
                if parts[1] in ("inc", "dec") and parts[0].isdigit():
                    dial_col = int(parts[0])
                elif parts[1].isdigit():
                    dial_col = int(parts[1])

        for try_kind in kinds:
            for item in self._iter_device_inputs(device_id):
                if item.page != page or (item.kind or "button") != try_kind:
                    continue
                ic = _coords_tuple(item)
                if coords is not None and ic == coords:
                    return item
                if item.slot_key == slot:
                    return item
                item_bid = normalize_button_id(item.button_id)
                if button_id and item_bid == button_id:
                    return item
                if try_kind == "dial_press" and dial_col is not None:
                    try:
                        if item._column is not None and int(item._column) == int(dial_col):
                            return item
                    except (TypeError, ValueError):
                        pass
                    if item_bid == str(dial_col):
                        return item
                if try_kind == "dial" and dial_col is not None and item_bid == str(dial_col):
                    return item
        return None

    def resolve_linked_source(self, item: StreamDeckInputItem | None) -> StreamDeckInputItem | None:
        """Follow ``linked_page`` to the item that owns appearance and mappings.

        Returns ``None`` when the chain is broken or cyclic. Unlinked items return themselves.
        """
        if item is None:
            return None
        visited: set[int] = set()
        current = item
        while True:
            link = int(getattr(current, "linked_page", 0) or 0)
            if link <= 0:
                return current
            oid = id(current)
            if oid in visited:
                syslog.warning(
                    f"STREAMDECK: linked_page cycle at page={current.page} "
                    f"slot={current.slot_key}"
                )
                return None
            visited.add(oid)
            if link == current.page:
                syslog.warning(
                    f"STREAMDECK: linked_page points at itself page={link} slot={current.slot_key}"
                )
                return None
            meta = {
                "kind": current.kind or "button",
                "row": current._row,
                "column": current._column,
                "button_id": current.button_id or "",
                "slot_key": current.slot_key,
            }
            nxt = self.find_input_for_slot(current.device_id or "", link, meta)
            if nxt is None:
                return None
            current = nxt

    def ensure_slot_input(
        self,
        device_id: str,
        page: int,
        kind: str = "button",
        row=None,
        column=None,
        button_id: str = "",
        title: str = "",
        context: str = "",
    ) -> StreamDeckInputItem | None:
        """Create or return the StreamDeckInputItem for a GEX page + slot."""
        page = normalize_page(page)
        self._ensure_page_listed(device_id, page)
        if row is not None and column is not None and not button_id:
            button_id = f"{int(row)}:{int(column)}"
        meta = {
            "device_id": device_id,
            "button_id": normalize_button_id(button_id),
            "page": page,
            "kind": kind or "button",
            "title": title or "",
            "context": context or "",
            "row": row,
            "column": column,
            "slot_key": make_slot_key(kind, row, column, button_id),
        }
        # Prefer live context for this slot when painting / binding hardware.
        for live in self.live_inputs_for_device(device_id):
            if _same_live_slot(live, meta):
                meta["context"] = live.get("context") or meta["context"]
                if live.get("button_id") and not button_id:
                    meta["button_id"] = normalize_button_id(live["button_id"])
                if meta["row"] is None:
                    meta["row"] = live.get("row")
                if meta["column"] is None:
                    meta["column"] = live.get("column")
                break
        return self._ensure_profile_input(meta)

    def paint_active_page(self, device_id: str) -> bool:
        """Push titles/images for the active GEX bank onto all live plugin slots."""
        self._bump_overlay_gen()
        from gremlin.ui.streamdeck_surface import (
            compose_pressed_image,
            empty_key_image,
            resolved_image,
            resolved_pressed_title,
            resolved_title,
        )

        device_id = device_id or ""
        page = self.get_active_page(device_id)
        title_keys = []
        image_jobs = []
        for meta in self.live_inputs_for_device(device_id):
            item = self.find_input_for_slot(device_id, page, meta)
            if item is not None and item.is_linked:
                item = self.resolve_linked_source(item)
            title = ""
            image = ""
            if item is not None:
                use_pressed = self._slot_is_held(device_id, meta)
                if use_pressed:
                    try:
                        image = compose_pressed_image(item) or ""
                    except Exception as err:
                        syslog.error(f"STREAMDECK: resolve pressed image failed: {err}")
                        image = ""
                    title = resolved_pressed_title(item)
                    if title is None:
                        title = ""
                else:
                    title = resolved_title(item)
                    try:
                        image = resolved_image(item) or ""
                    except Exception as err:
                        syslog.error(f"STREAMDECK: resolve image failed: {err}")
                        image = ""
            live_kind = (meta.get("kind") or "button")
            # Unassigned / icon-less slots must not fall back to the blue plugin default.
            if not image:
                if live_kind in ("dial", "dial_press"):
                    image = empty_key_image(200, 100)
                else:
                    image = empty_key_image(144, 144)
            ctx = meta.get("context") or ""
            title_keys.append(
                {
                    "context": ctx,
                    "deviceId": device_id,
                    "buttonId": meta.get("button_id") or "",
                    "title": title,
                    "row": meta.get("row"),
                    "column": meta.get("column"),
                }
            )
            job = {
                "deviceId": device_id,
                "buttonId": meta.get("button_id") or "",
                "image": image,
                "clear": False,
            }
            if live_kind in ("dial", "dial_press"):
                # Touch-strip LCD via plugin setFeedback ($A0), not setImage.
                job["feedback"] = True
                job["target"] = "lcd"
            if ctx:
                job["context"] = ctx
            else:
                job["row"] = meta.get("row")
                job["column"] = meta.get("column")
            image_jobs.append(job)
        ok = self.send_command(
            "paintPage",
            deviceId=device_id,
            page=page - 1,
            keys=title_keys,
        )
        # Separate setImage calls so one large icon cannot blow up paintPage JSON
        # or the plugin's command logging stringify.
        for job in image_jobs:
            self.send_command("setImage", **job)
        return bool(ok)

    def _hold_keys_for_meta(self, device_id: str, meta: dict) -> list[tuple]:
        keys = []
        device_id = device_id or ""
        ctx = (meta or {}).get("context") or ""
        if ctx:
            keys.append((device_id, "ctx", str(ctx)))
        slot_key = (meta or {}).get("slot_key") or ""
        if slot_key:
            keys.append((device_id, "slot", str(slot_key)))
        return keys

    def _slot_is_held(self, device_id: str, meta: dict) -> bool:
        for key in self._hold_keys_for_meta(device_id, meta):
            if key in self._held_slots:
                return True
        return False

    def _set_slot_held(self, device_id: str, meta: dict, held: bool):
        for key in self._hold_keys_for_meta(device_id, meta):
            if held:
                self._held_slots.add(key)
            else:
                self._held_slots.discard(key)
        self._bump_overlay_gen()

    def _clear_held_for_device(self, device_id: str):
        """Forget press-hold state for a deck (used when the GEX page changes)."""
        device_id = device_id or ""
        if not device_id:
            return
        before = len(self._held_slots)
        self._held_slots = {k for k in self._held_slots if k[0] != device_id}
        if len(self._held_slots) != before:
            self._bump_overlay_gen()

    def _paint_pressed_appearance(self, item, device_id: str, context: str = ""):
        """Push pressed icon/title/style for one held key (stays until keyUp / idle paint)."""
        from gremlin.ui.streamdeck_surface import compose_pressed_image, resolved_pressed_title

        if item is not None and getattr(item, "is_linked", False):
            item = self.resolve_linked_source(item)
        if item is None:
            return
        ctx = (context or "").strip() or (getattr(item, "context", "") or "")
        if not ctx:
            return
        try:
            img = compose_pressed_image(item) or ""
            if img:
                self.send_command(
                    "setImage",
                    deviceId=device_id,
                    buttonId=item.button_id or "",
                    context=ctx,
                    image=img,
                )
            title = resolved_pressed_title(item)
            if title is not None:
                self.send_command(
                    "setTitle",
                    deviceId=device_id,
                    buttonId=item.button_id or "",
                    context=ctx,
                    title=title,
                )
        except Exception as err:
            syslog.error(f"STREAMDECK: pressed paint failed: {err}")

    def _on_message(self, sock: QtWebSockets.QWebSocket, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            syslog.error(f"STREAMDECK: invalid JSON from plugin: {message[:200]}")
            return

        msg_type = data.get("type")
        verbose = gremlin.config.Configuration().verbose_mode_streamdeck
        if verbose:
            syslog.info(f"STREAMDECK: recv {msg_type}: {data}")

        if msg_type == "hello":
            self._send(sock, {"type": "hello_ack", "version": PROTOCOL_VERSION})
            self._send(sock, {"type": "status", "connected": True})
        elif msg_type == "command_ack":
            syslog.info(f"STREAMDECK: plugin ack {data}")
        elif msg_type == "ping":
            self._send(sock, {"type": "pong"})
        elif msg_type == "device":
            self._handle_device(data)
        elif msg_type == "willAppear":
            self._handle_will_appear(data)
        elif msg_type == "willDisappear":
            self._handle_will_disappear(data)
        elif msg_type in ("keyDown", "keyUp"):
            self._handle_key(data, is_pressed=(msg_type == "keyDown"))
        elif msg_type in ("dialRotate",):
            self._handle_dial_rotate(data)
        elif msg_type in ("dialDown", "dialUp"):
            self._handle_key({**data, "kind": "dial_press"}, is_pressed=(msg_type == "dialDown"))
        elif msg_type == "status":
            pass
        else:
            if verbose:
                syslog.info(f"STREAMDECK: unhandled message type {msg_type}")

    def _profile_device_guid(self, device_id: str = ""):
        """Per-physical-deck GUID (legacy tab GUID only when device_id is empty)."""
        return streamdeck_guid_for_device(device_id or "")

    def is_guid_connected(self, device_guid) -> bool:
        for info in self._devices.values():
            if compare_guid(info.get("guid"), device_guid):
                return True
        return False

    def device_id_for_guid(self, device_guid) -> str:
        for device_id, info in self._devices.items():
            if compare_guid(info.get("guid"), device_guid):
                return device_id
        # Plugin may not be connected yet — reverse uuid5 from known sidecar / profile ids.
        candidates = set(list(self._page_names.keys()) + list(self._page_order.keys()))
        try:
            profile = gremlin.shared_state.current_profile
            mode = gremlin.shared_state.edit_mode or gremlin.shared_state.current_mode
            if profile is not None and mode:
                for item in profile.registry.getInputItems(device_guid, mode, InputType.StreamDeck) or []:
                    did = getattr(item, "device_id", None) or getattr(item, "_elgato_device_id", None)
                    if did:
                        candidates.add(str(did))
        except Exception:
            pass
        for device_id in candidates:
            if device_id and compare_guid(streamdeck_guid_for_device(device_id), device_guid):
                return device_id
        return ""

    def _request_tab_refresh(self):
        """Rebuild device tabs without a full DINPUT rescan."""
        if gremlin.shared_state.is_running:
            return
        try:
            el = gremlin.event_handler.EventListener()
            el.refresh_devices.emit()
        except Exception as err:
            syslog.error(f"STREAMDECK: tab refresh failed: {err}")

    def _handle_device(self, data: dict):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        if not device_id:
            return
        action = data.get("action", "connected")
        raw_type = data.get("deviceType") if data.get("deviceType") is not None else data.get("type")
        previous = self._devices.get(device_id)
        # Keep a previously known good type/name if this update is weak.
        if previous and (raw_type is None or raw_type == ""):
            raw_type = previous.get("type")
        name = friendly_streamdeck_name(
            data.get("name") or (previous.get("name") if previous else None),
            raw_type,
            device_id,
        )
        if action in ("connected", "update"):
            # Keep a strong previous label if this update only has a weak id fallback.
            if previous and _is_weak_streamdeck_name(name, device_id) and not _is_weak_streamdeck_name(
                previous.get("name") or "", device_id
            ):
                name = previous.get("name")
            guid = streamdeck_guid_for_device(device_id)
            ensure_streamdeck_special_device(device_id, name, raw_type)
            self._devices[device_id] = {
                "device_id": device_id,
                "name": name,
                "type": raw_type if raw_type is not None else (previous.get("type") if previous else ""),
                "guid": guid,
            }
            self.devices_changed.emit()
            # Only rebuild tabs when a deck appears or its display name changes.
            if previous is None or previous.get("name") != name:
                self._migrate_legacy_inputs_for_device(device_id)
                self._request_tab_refresh()
            try:
                self._adopt_orphan_page_metadata([device_id] if device_id else None)
                self._dedupe_live_page_metadata()
            except Exception:
                pass
            # First connect often arrives after profile_loaded — refresh page names now.
            if previous is None:
                try:
                    gremlin.util.InvokeUiMethod(self._emit_page_metadata_changed)
                except Exception:
                    pass
            if gremlin.config.Configuration().verbose_mode_streamdeck:
                syslog.info(f"STREAMDECK: device {name} ({device_id})")
        elif action == "disconnected":
            if device_id in self._devices:
                self._devices.pop(device_id, None)
                self.devices_changed.emit()
                # Keep special device for getDevice / profile data; hide tab via filter.
                self._request_tab_refresh()

    def _handle_will_appear(self, data: dict):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        button_id = str(data.get("buttonId") or "")
        kind = data.get("kind") or "button"
        if not device_id or not button_id:
            return
        if device_id not in self._devices:
            self._handle_device(
                {
                    "deviceId": device_id,
                    "name": data.get("deviceName") or data.get("name"),
                    "action": "connected",
                    "deviceType": data.get("deviceType"),
                }
            )
        elif data.get("deviceName") or data.get("deviceType") is not None:
            # Upgrade a weak placeholder name if Elgato info arrives later.
            self._handle_device(
                {
                    "deviceId": device_id,
                    "name": data.get("deviceName") or data.get("name"),
                    "action": "update",
                    "deviceType": data.get("deviceType"),
                }
            )
        context = str(data.get("context") or "")
        button_id = normalize_button_id(button_id)
        row = data.get("row")
        column = data.get("column")
        slot_key = make_slot_key(kind, row, column, button_id)
        # Live viewport is physical only — GEX page comes from active bank, not Elgato.
        meta = {
            "device_id": device_id,
            "button_id": button_id,
            "kind": kind,
            "title": data.get("title") if data.get("title") is not None else "",
            "context": context,
            "row": row,
            "column": column,
            "slot_key": slot_key,
        }
        for old_key, old_meta in list(self._live_inputs.items()):
            if _same_live_slot(old_meta, meta):
                self._live_inputs.pop(old_key, None)
        key = (device_id, kind, slot_key)
        self._live_inputs[key] = meta
        self._ensure_page_listed(device_id, self.get_active_page(device_id))
        # Refresh context on matching profile inputs (all GEX pages for this slot).
        try:
            self._sync_live_context_to_profile(meta)
        except Exception as err:
            syslog.error(f"STREAMDECK: sync live context failed: {err}")
        guid = self._profile_device_guid(device_id)
        self._schedule_inputs_changed(guid)
        self._schedule_paint(device_id)

    def _schedule_inputs_changed(self, guid):
        # Designer-only: do not refresh UI while the profile is executing.
        if gremlin.shared_state.is_running:
            return
        key = str(guid)
        if key in self._inputs_changed_pending:
            return
        self._inputs_changed_pending.add(key)

        def _emit(g=guid, k=key):
            self._inputs_changed_pending.discard(k)
            self._bump_overlay_gen()
            self.inputs_changed.emit(g)

        QtCore.QTimer.singleShot(50, _emit)

    def _schedule_paint(self, device_id: str):
        device_id = device_id or ""
        if device_id in self._paint_pending:
            return
        self._paint_pending.add(device_id)

        def _paint(d=device_id):
            self._paint_pending.discard(d)
            try:
                self.paint_active_page(d)
            except Exception:
                pass

        QtCore.QTimer.singleShot(75, _paint)

    def _sync_live_context_to_profile(self, meta: dict):
        device_id = meta.get("device_id") or ""
        for item in self._iter_device_inputs(device_id):
            if not _same_live_slot(item, meta):
                continue
            if meta.get("context"):
                item.context = meta["context"]
            if meta.get("row") is not None:
                item._row = meta.get("row")
            if meta.get("column") is not None:
                item._column = meta.get("column")

    def _handle_will_disappear(self, data: dict):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        button_id = normalize_button_id(str(data.get("buttonId") or ""))
        kind = data.get("kind") or "button"
        row = data.get("row")
        column = data.get("column")
        context = str(data.get("context") or "")
        slot_key = make_slot_key(kind, row, column, button_id)
        if context:
            for old_key, old_meta in list(self._live_inputs.items()):
                if old_meta.get("context") == context:
                    self._live_inputs.pop(old_key, None)
        else:
            self._live_inputs.pop((device_id, kind, slot_key), None)
        self._schedule_inputs_changed(self._profile_device_guid(device_id))

    def _migrate_legacy_inputs_for_device(self, device_id: str):
        """Move inputs stored under the legacy tab GUID onto this deck's GUID."""
        if not device_id:
            return
        profile = gremlin.shared_state.current_profile
        if not profile:
            return
        mode = gremlin.shared_state.edit_mode or gremlin.shared_state.current_mode
        if not mode:
            return
        legacy_guid = gremlin.shared_state.streamdeck_tab_guid
        target_guid = streamdeck_guid_for_device(device_id)
        if compare_guid(legacy_guid, target_guid):
            return
        try:
            legacy_node = profile.getDeviceNode(legacy_guid, autocreate=False)
        except Exception:
            legacy_node = None
        if legacy_node is None:
            return
        try:
            legacy_mode = legacy_node.getModeNode(mode, autocreate=False)
        except Exception:
            legacy_mode = None
        if legacy_mode is None:
            return
        config = legacy_mode.getConfig(InputType.StreamDeck) or {}
        to_move = []
        for key, item in list(config.items()):
            if isinstance(item, StreamDeckInputItem) and item.device_id == device_id:
                to_move.append((key, item))
        if not to_move:
            return
        ensure_streamdeck_special_device(device_id, self._devices.get(device_id, {}).get("name"))
        target_node = profile.getDeviceNode(target_guid, autocreate=True)
        target_mode = target_node.ensure_mode_exists(mode)
        for key, item in to_move:
            try:
                if hasattr(legacy_mode, "removeInputItem"):
                    legacy_mode.removeInputItem(item)
                else:
                    config.pop(key, None)
            except Exception:
                config.pop(key, None)
            # Re-home under the per-device node
            item._device_guid = target_guid
            try:
                target_mode.addInputItem(item)
                profile.registry.registerInputItem(item)
            except Exception as err:
                syslog.error(f"STREAMDECK: legacy migrate failed for {key}: {err}")
        if gremlin.config.Configuration().verbose_mode_streamdeck:
            syslog.info(f"STREAMDECK: migrated {len(to_move)} legacy input(s) -> {device_id}")

    def _find_existing_streamdeck_input(self, config: dict, meta: dict, input_key: str):
        """Locate an existing input by key, plugin context, page + coords, or Button ID."""
        item = config.get(input_key)
        if item is not None:
            return item, input_key

        # Pre-page keys were device:kind:buttonId (implicit page 1).
        page = normalize_page(meta.get("page", 1))
        if page == 1:
            device_id = meta.get("device_id") or ""
            kind = meta.get("kind") or "button"
            button_id = normalize_button_id(meta.get("button_id") or "")
            legacy_key = f"{device_id}:{kind}:{button_id}" if device_id else f"{kind}:{button_id}"
            legacy = config.get(legacy_key)
            if isinstance(legacy, StreamDeckInputItem):
                return legacy, legacy_key

        meta_button = normalize_button_id(meta.get("button_id") or "")
        meta_dev = meta.get("device_id") or ""
        meta_kind = meta.get("kind") or "button"
        for existing_key, existing in list(config.items()):
            if not isinstance(existing, StreamDeckInputItem):
                continue
            if _same_physical_streamdeck_key(existing, meta):
                return existing, existing_key
            # Dials / items without coordinates: match page + Button ID.
            if (
                (existing.device_id or "") == meta_dev
                and (existing.kind or "button") == meta_kind
                and existing.page == page
                and normalize_button_id(existing.button_id) == meta_button
            ):
                return existing, existing_key
        return None, input_key

    def _pick_duplicate_keeper(self, group: list, prefer_meta: dict = None):
        """Choose which duplicate to keep; prefer live Button ID, mappings, then title."""
        prefer_button = normalize_button_id((prefer_meta or {}).get("button_id") or "")

        def score(pair):
            _key, item = pair
            s = 0
            if prefer_button and normalize_button_id(item.button_id) == prefer_button:
                s += 100
            if getattr(item, "containers", None):
                try:
                    if item.hasActions:
                        s += 50
                except Exception:
                    if item.containers:
                        s += 40
            if item.title:
                s += 20
            if item.context:
                s += 10
            bid = normalize_button_id(item.button_id)
            if ":" in bid:
                s += 5
            if "_" in str(item.button_id or ""):
                s -= 5
            return s

        return max(group, key=score)

    def _prune_duplicate_streamdeck_inputs(self, config: dict, prefer_meta: dict = None) -> int:
        """Collapse multiple profile entries for the same physical key/dial."""
        entries = [(k, v) for k, v in list(config.items()) if isinstance(v, StreamDeckInputItem)]
        if len(entries) < 2:
            return 0

        used = set()
        removed = 0
        for i, (k1, v1) in enumerate(entries):
            if id(v1) in used:
                continue
            group = [(k1, v1)]
            used.add(id(v1))
            for k2, v2 in entries[i + 1 :]:
                if id(v2) in used:
                    continue
                if _same_physical_streamdeck_key(v1, v2):
                    group.append((k2, v2))
                    used.add(id(v2))
            if len(group) <= 1:
                continue

            keep_key, keeper = self._pick_duplicate_keeper(group, prefer_meta)
            if prefer_meta:
                # Align keeper with the live plugin values.
                if prefer_meta.get("button_id"):
                    keeper.button_id = normalize_button_id(prefer_meta["button_id"])
                if prefer_meta.get("kind"):
                    keeper.kind = prefer_meta["kind"]
                if "page" in prefer_meta:
                    keeper.page = prefer_meta.get("page")
                # Plugin is source of truth for the label only when it sends a non-empty title.
                # Empty title in prefer_meta must not wipe a user-edited LCD/key title.
                if prefer_meta.get("title"):
                    keeper.title = prefer_meta.get("title") or ""
                if prefer_meta.get("context"):
                    keeper.context = prefer_meta["context"]
                if prefer_meta.get("row") is not None:
                    keeper._row = prefer_meta.get("row")
                if prefer_meta.get("column") is not None:
                    keeper._column = prefer_meta.get("column")

            for old_key, old_item in group:
                if old_item is keeper:
                    continue
                # Never collapse distinct pages; and keep mapped containers when possible.
                try:
                    if (not keeper.containers) and old_item.containers:
                        keeper.containers = list(old_item.containers)
                except Exception:
                    pass
                config.pop(old_key, None)
                removed += 1
                syslog.info(
                    f"STREAMDECK: pruned duplicate input {old_key!r} "
                    f"(kept page={keeper.page} buttonId={keeper.button_id!r} title={keeper.title!r})"
                )

            new_key = keeper.message_key
            if keep_key in config and keep_key != new_key:
                config.pop(keep_key, None)
            config[new_key] = keeper
        return removed

    def _ensure_profile_input(self, meta: dict):
        profile = gremlin.shared_state.current_profile
        if not profile:
            return None
        mode = gremlin.shared_state.edit_mode or gremlin.shared_state.current_mode
        if not mode:
            return None
        device_id = meta.get("device_id") or ""
        meta = dict(meta)
        meta["button_id"] = normalize_button_id(meta.get("button_id") or "")
        meta["page"] = normalize_page(meta.get("page", 1))
        ensure_streamdeck_special_device(device_id, self._devices.get(device_id, {}).get("name"))
        device_guid = self._profile_device_guid(device_id)
        device_node = profile.getDeviceNode(device_guid, autocreate=True)
        mode_object = device_node.ensure_mode_exists(mode)
        input_type = InputType.StreamDeck
        input_key = make_input_key(meta["kind"], meta["button_id"], device_id, meta["page"])
        config = mode_object.getConfig(input_type)
        context = meta.get("context") or ""

        # Drop stale duplicates for this page + physical key before upserting.
        self._prune_duplicate_streamdeck_inputs(config, prefer_meta=meta)

        item, found_key = self._find_existing_streamdeck_input(config, meta, input_key)
        if item is not None and found_key != input_key:
            config.pop(found_key, None)

        if item is None:
            # Prefer an existing legacy entry with the same key (migrate in place).
            self._migrate_legacy_inputs_for_device(device_id)
            config = mode_object.getConfig(input_type)
            self._prune_duplicate_streamdeck_inputs(config, prefer_meta=meta)
            item, found_key = self._find_existing_streamdeck_input(config, meta, input_key)
            if item is not None and found_key != input_key:
                config.pop(found_key, None)

        new_title = meta.get("title") if "title" in meta else None
        if item is None:
            item = StreamDeckInputItem(mode_object=mode_object, device_guid=device_guid)
            item.device_id = device_id
            item.kind = meta["kind"]
            item.button_id = meta["button_id"]
            item.page = meta["page"]
            item.title = new_title or ""
            item.context = context
            item._row = meta.get("row")
            item._column = meta.get("column")
            item.setOverrideInputType(InputType.JoystickButton)
            mode_object.addInputItem(item)
            profile.registry.registerInputItem(item)
            syslog.info(
                f"STREAMDECK: created input title={item.display_name!r} "
                f"page={item.page} buttonId={item.button_id!r} key={item.message_key}"
            )
        else:
            if isinstance(item, StreamDeckInputItem):
                old_title = item.title
                old_button = item.button_id
                old_page = item.page
                item.button_id = meta["button_id"]
                item.page = meta["page"]
                item.kind = meta["kind"]
                # Only apply a new title when the caller provides a non-empty value.
                # Designer LCD clicks must not stamp "Dial N" over a cleared/custom title.
                if new_title:
                    item.title = new_title
                if context:
                    item.context = context
                item._row = meta.get("row")
                item._column = meta.get("column")
                # Ensure config is keyed by the current message_key.
                config[input_key] = item
                if old_title != item.title or old_button != item.button_id or old_page != item.page:
                    syslog.info(
                        f"STREAMDECK: updated input title={item.title!r} "
                        f"page={item.page} buttonId={item.button_id!r} "
                        f"(was page={old_page} title={old_title!r} buttonId={old_button!r})"
                    )
                elif new_title is not None:
                    # Title forced equal after prune — still log when plugin asserts a value.
                    syslog.info(
                        f"STREAMDECK: sync title={item.title!r} "
                        f"page={item.page} buttonId={item.button_id!r}"
                    )
            if hasattr(item, "setOverrideInputType"):
                item.setOverrideInputType(InputType.JoystickButton)

        # Final sweep in case create + old orphans both remain.
        self._prune_duplicate_streamdeck_inputs(config, prefer_meta=meta)
        return config.get(item.message_key, item)

    def _resolve_event_input(self, meta: dict):
        """Find (runtime) or create (edit) the profile input for a live event."""
        device_id = meta.get("device_id") or ""
        page = normalize_page(meta.get("page", 1))
        if gremlin.shared_state.is_running:
            # Never create/mutate profile slots while actions are executing.
            return self.find_input_for_slot(device_id, page, meta)
        return self._ensure_profile_input(meta)

    def _handle_key(self, data: dict, is_pressed: bool):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        button_id = str(data.get("buttonId") or "")
        kind = data.get("kind") or "button"
        if not device_id or not button_id:
            return
        guid = self._profile_device_guid(device_id)
        # Resolve against the active GEX virtual page (Companion-style), not Elgato page.
        page = self.get_active_page(device_id)
        row = data.get("row")
        column = data.get("column")
        button_id = normalize_button_id(button_id)
        meta = {
            "device_id": device_id,
            "button_id": button_id,
            "page": page,
            "kind": kind,
            "title": data.get("title") or "",
            "context": data.get("context") or "",
            "row": row,
            "column": column,
            "slot_key": make_slot_key(kind, row, column, button_id),
        }
        try:
            item = self._resolve_event_input(meta)
        except Exception as err:
            syslog.error(f"STREAMDECK: key ensure input failed: {err}")
            item = None
        if item is None:
            return
        live_context = data.get("context") or getattr(item, "context", None) or ""
        # Linked slots run the source page's mappings / pressed look.
        if getattr(item, "is_linked", False):
            source = self.resolve_linked_source(item)
            if source is None:
                return
            item = source
        hold_meta = {
            "context": live_context,
            "slot_key": meta.get("slot_key") or "",
        }
        try:
            from gremlin.ui.streamdeck_surface import advance_step

            # Gate uses current step_index; advance after press is handled below.
        except Exception:
            advance_step = None

        # Mark hold + paint pressed BEFORE actions so same-page presses keep pressed look.
        page_before = self.get_active_page(device_id)
        if is_pressed:
            self._set_slot_held(device_id, hold_meta, True)
            self._paint_pressed_appearance(item, device_id, context=live_context)
        else:
            self._set_slot_held(device_id, hold_meta, False)

        event = gremlin.event_handler.Event(
            InputType.StreamDeck,
            item,
            guid,
            is_pressed=is_pressed,
            value=1.0 if is_pressed else 0.0,
            raw_value=1.0 if is_pressed else 0.0,
            override_input_type=InputType.JoystickButton,
            extra_data={"input_item": item},
        )
        event.source = EventSourceType.StreamDeck
        self._emit_event(event)
        if not gremlin.shared_state.is_running:
            try:
                self.slot_pressed.emit(device_id, row, column, bool(is_pressed))
            except Exception:
                pass
        if is_pressed:
            try:
                if advance_step is not None:
                    advance_step(item, True)
            except Exception:
                pass
            page_after = self.get_active_page(device_id)
            if page_after == page_before:
                # Re-assert pressed look after actions (actions may have scheduled an idle paint).
                self._paint_pressed_appearance(item, device_id, context=live_context)
            else:
                # Change Page / Next / Previous / Return ran under this press.
                # Do not stamp the old key art back on top of the new bank.
                self._set_slot_held(device_id, hold_meta, False)
                try:
                    self.paint_active_page(device_id)
                except Exception:
                    pass
        else:
            try:
                self._schedule_paint(device_id)
            except Exception:
                pass

    def _handle_dial_rotate(self, data: dict):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        button_id = str(data.get("buttonId") or data.get("controller") or "")
        ticks = int(data.get("ticks") or data.get("steps") or 0)
        if not device_id or not button_id or ticks == 0:
            return
        direction = "inc" if ticks > 0 else "dec"
        input_kind = "dial"
        page = self.get_active_page(device_id)
        guid = self._profile_device_guid(device_id)
        bid = f"{normalize_button_id(button_id)}:{direction}"
        meta = {
            "device_id": device_id,
            "button_id": bid,
            "page": page,
            "kind": input_kind,
            "title": data.get("title") or f"Dial {button_id} {direction.upper()}",
            "context": data.get("context") or "",
            "row": None,
            "column": None,
            "slot_key": make_slot_key(input_kind, None, None, bid),
        }
        self._live_inputs[(device_id, input_kind, meta["slot_key"])] = meta
        try:
            item = self._resolve_event_input(meta)
        except Exception as err:
            syslog.error(f"STREAMDECK: dial ensure input failed: {err}")
            return
        if item is None:
            return

        event = gremlin.event_handler.Event(
            InputType.StreamDeck,
            item,
            guid,
            is_pressed=True,
            value=1.0,
            raw_value=float(ticks),
            override_input_type=InputType.JoystickButton,
            extra_data={"input_item": item},
        )
        event.source = EventSourceType.StreamDeck
        self._emit_event(event)

        key = (device_id, input_kind, meta["slot_key"])
        delay = gremlin.config.Configuration().osc_default_autorelease_delay

        def _release(k=key, g=guid, iid=item):
            release = gremlin.event_handler.Event(
                InputType.StreamDeck,
                iid,
                g,
                is_pressed=False,
                value=0.0,
                raw_value=0.0,
                override_input_type=InputType.JoystickButton,
                extra_data={"input_item": iid},
            )
            release.source = EventSourceType.StreamDeck
            self._emit_event(release)

        old = self._autorelease_timers.pop(key, None)
        if old:
            old.cancel()
        timer = threading.Timer(delay, _release)
        self._autorelease_timers[key] = timer
        timer.daemon = True
        timer.start()
        if not gremlin.shared_state.is_running:
            self._bump_overlay_gen()
            self.inputs_changed.emit(guid)

    def _emit_event(self, event: gremlin.event_handler.Event):
        """Dispatch a Stream Deck input event (OSC-style).

        When the profile is running, code_runner connects streamdeck_event → execute_event.
        Always emit UI joystick feedback so repeaters update while editing.
        """
        el = gremlin.event_handler.EventListener()
        el.streamdeck_event.emit(event)
        try:
            el.joystick_event_ui.emit(event)
        except Exception:
            pass
        if not gremlin.shared_state.is_running:
            # Extra UI path while idle (same pattern as OSC)
            try:
                el.joystick_event.emit(event)
            except Exception:
                pass


class StreamDeckInputItemListModel(gremlin.input_item.InputItemListModel):
    def __init__(self, profile, mode, device_guid, custom_filter_handler=None, custom_load_handler=None):
        super().__init__(
            profile=profile,
            device_guid=device_guid,
            mode=mode,
            allowed_types=[InputType.StreamDeck],
            custom_filter_handler=custom_filter_handler,
            custom_load_handler=custom_load_handler,
            show_master_mode=True,
        )


class StreamDeckDeviceTabWidget(gremlin.input_item.BaseDeviceTabWidget):
    """UI tab for one physical Stream Deck (or the legacy shared tab).

    Companion-style: left/center designer (pages + grid); right panel shows
    the selected key's containers/actions via the normal mapping widget.
    """

    device_guid = gremlin.shared_state.streamdeck_tab_guid

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        mode: str,
        device_guid=None,
        object_name="Stream Deck",
        parent=None,
    ):
        if device_guid is not None:
            self.device_guid = device_guid if not isinstance(device_guid, str) else gremlin.util.parse_guid(device_guid)

        device = gremlin.joystick_handling.getDevice(self.device_guid)
        super().__init__(
            device=device,
            profile=profile,
            mode=mode,
            object_name=object_name,
            custom_input_widget_callback=self._custom_widget_handler,
            parent=parent,
        )

        self.profile = profile
        profile.ensure_mode_exists(mode)
        self.device_node = profile.getDeviceNode(self.device_guid, autocreate=True)
        self.device_node.getModeNode(mode, autocreate=True)
        self.widget_storage = {}
        self._is_legacy_tab = compare_guid(self.device_guid, gremlin.shared_state.streamdeck_tab_guid)
        self._elgato_device_id = "" if self._is_legacy_tab else StreamDeckBridge().device_id_for_guid(self.device_guid)
        self._designer = None
        self._status_label = QtWidgets.QLabel()

        self.inputItemListModel = StreamDeckInputItemListModel(
            profile=profile,
            mode=mode,
            device_guid=self.device_guid,
            custom_load_handler=self._load_handler,
        )

        bridge = StreamDeckBridge()
        ensure_bridge_started()

        # Hide the classic input list; Companion grid lives in the designer.
        try:
            self.listview_container.hide()
        except Exception:
            pass
        self.clearLeftPanelHeaderWidget()

        if self._is_legacy_tab:
            banner = gremlin.ui.ui_common.QInfoBox(
                "Legacy Stream Deck tab (pre multi-device). New keys appear on per-device tabs."
            )
            self.addLeftPanelHeaderWidget(banner)
        else:
            from gremlin.ui.streamdeck_designer import StreamDeckDesignerWidget

            self._designer = StreamDeckDesignerWidget(self)
            self._designer.selection_changed.connect(self._on_designer_selection)
            self._designer.mapping_enabled_changed.connect(self._on_designer_mapping_enabled)
            self.addLeftPanelWidget(self._designer)
            self._lcd_hint_widget = None
            self._designer_mappings_enabled = True
            # Designer needs horizontal room; don't starve it vs mapping pane.
            # Keep Stream Deck split local so classic device-tab shares stay intact.
            try:
                self._share_splitter_sizes = False
                self._splitter.setChildrenCollapsible(True)
                self._splitter.setStretchFactor(0, 3)
                self._splitter.setStretchFactor(1, 2)
                self._left_panel_widget.setMinimumWidth(0)
                scroll = getattr(self, "_right_scroll_area", None)
                if scroll is not None:
                    scroll.setMinimumWidth(0)
                total = max(400, self._content_widget.width() or 900)
                left = max(280, int(total * 0.55))
                sizes = [left, max(200, total - left)]
                self._splitter.setSizes(sizes)
                self._last_sizes = list(sizes)
            except Exception:
                pass

        bridge.plugin_connected.connect(self._on_plugin_connected)
        bridge.inputs_changed.connect(self._on_inputs_changed)
        bridge.status_message.connect(self._on_status_message)
        self._refresh_status_label()

        el = gremlin.event_handler.EventListener()
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)

    def _cleanup_ui(self):
        if self._designer is not None:
            try:
                self._designer._cleanup_ui()
            except Exception:
                pass
            self._designer = None
        try:
            super()._cleanup_ui()
        except Exception:
            pass

    def _on_designer_mapping_enabled(self, enabled: bool):
        """LCD / other-plugin selection hides the mapping pane."""
        self._designer_mappings_enabled = bool(enabled)
        if enabled:
            return
        try:
            widget = self._ensure_no_mapping_hint_widget()
            if widget is not None:
                self.selectRegisteredWidget(widget)
                self.setLastSelectedWidget(widget)
        except Exception as err:
            syslog.error(f"STREAMDECK: no-mapping hint panel failed: {err}")

    def _ensure_lcd_hint_widget(self):
        return self._ensure_no_mapping_hint_widget()

    def _ensure_no_mapping_hint_widget(self):
        if getattr(self, "_lcd_hint_widget", None) is not None:
            self._update_no_mapping_hint()
            return self._lcd_hint_widget
        from PySide6 import QtWidgets

        w = QtWidgets.QWidget()
        w.setObjectName("StreamDeckLcdHint")
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        title = QtWidgets.QLabel("Dial LCD")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        body = QtWidgets.QLabel("")
        body.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(body)
        lay.addStretch(1)
        self._no_map_hint_title = title
        self._no_map_hint_body = body
        self.registerWidget("streamdeck_lcd_hint", w)
        self._lcd_hint_widget = w
        self._update_no_mapping_hint()
        return w

    def _update_no_mapping_hint(self):
        title = getattr(self, "_no_map_hint_title", None)
        body = getattr(self, "_no_map_hint_body", None)
        if title is None or body is None:
            return
        designer = getattr(self, "_designer", None)
        foreign = False
        kind = "button"
        linked_page = 0
        multi_count = 0
        if designer is not None:
            kind = getattr(designer, "_selected_kind", "button") or "button"
            try:
                foreign = designer._slot_is_foreign(
                    designer._selected_row,
                    designer._selected_col,
                    kind,
                )
            except Exception:
                foreign = False
            try:
                multi_count = len(designer._button_selection_keys())
            except Exception:
                multi_count = 0
            try:
                item = designer._selected_item()
                if item is not None and getattr(item, "is_linked", False):
                    linked_page = int(getattr(item, "linked_page", 0) or 0)
            except Exception:
                linked_page = 0
        if multi_count > 1:
            title.setText("Multiple keys")
            body.setText(
                f"{multi_count} keys are selected.\n\n"
                "Right-click any selected key for Link to page, Unlink, Delete, or Paste "
                "across the whole selection.\n\n"
                "Ctrl+click to add or remove keys. Click without Ctrl to select one."
            )
        elif linked_page > 0:
            src_name = f"page {linked_page}"
            try:
                if designer is not None and designer._device_id:
                    nm = StreamDeckBridge().page_name(designer._device_id, linked_page)
                    if nm and nm != f"Page {linked_page}":
                        src_name = f"page {linked_page} ({nm})"
            except Exception:
                pass
            title.setText("Linked key")
            body.setText(
                f"This key mirrors {src_name} at the same position.\n\n"
                f"It shows and runs that page’s button. Edit icon, style, "
                f"and mappings on {src_name}.\n\n"
                "Use Unlink in the designer if you want a separate button here."
            )
        elif foreign:
            title.setText("Other plugin key")
            body.setText(
                "This hardware key is not a JG Ex Button.\n\n"
                "You can still set an icon and background under the deck "
                "(shown in the designer and overlay). Mappings cannot be added here.\n\n"
                "Put a JG Ex Button on this key in Stream Deck software to map actions."
            )
        else:
            title.setText("Dial LCD")
            body.setText(
                "This is the touch-strip window for the dial — not a button.\n\n"
                "Edit icon, title, and background in the LCD settings under the deck.\n"
                "Add press / rotate mappings on the dial: circle = press, "
                "arrows = clockwise / counterclockwise."
            )

    def _on_designer_selection(self, input_item):
        """Show containers/actions for the grid selection in the right panel."""
        if gremlin.shared_state.is_running:
            return
        if input_item is None:
            # Page change / look-only selection — blank or no-mapping hint.
            try:
                self.setLastSelectedInputItem(None)
                if not getattr(self, "_designer_mappings_enabled", True):
                    widget = self._ensure_no_mapping_hint_widget()
                    if widget is not None:
                        self.selectRegisteredWidget(widget)
                        self.setLastSelectedWidget(widget)
                    return
                self.setLastSelectedWidget(None)
                self.showBlank()
            except Exception as err:
                syslog.error(f"STREAMDECK: clear designer selection failed: {err}")
            return
        try:
            if self._input_item_list_model is not None:
                self._load_handler(self._input_item_list_model, emit=False)
            widget = self._ensure_mapping_widget(input_item)
            if widget is not None:
                self.selectRegisteredWidget(widget)
                self.setLastSelectedInputItem(input_item)
                self.setLastSelectedWidget(widget)
                try:
                    widget.redraw()
                except Exception as redraw_err:
                    # Failed redraw can leave the mapping pane on the blank
                    # "Please select an input" page — rebuild and retry once.
                    syslog.error(f"STREAMDECK: mapping redraw failed, rebuilding: {redraw_err}")
                    widget = self._ensure_mapping_widget(input_item, force_new=True)
                    if widget is not None:
                        self.selectRegisteredWidget(widget)
                        self.setLastSelectedInputItem(input_item)
                        self.setLastSelectedWidget(widget)
                        widget.redraw()
        except Exception as err:
            syslog.error(f"STREAMDECK: designer selection failed: {err}")
            import traceback

            syslog.error(traceback.format_exc())

    def _ensure_mapping_widget(self, input_item, force_new: bool = False):
        """Return (and register) an InputItemMappingWidget for ``input_item``."""
        key = self.getInputItemWidgetKey(input_item)
        if force_new:
            try:
                self.unregisterWidget(key)
            except Exception:
                pass
            try:
                input_item.setMappingWidget(None)
            except Exception:
                pass
        widget = None
        if not force_new:
            if self._input_item_list_model is not None and self._input_item_list_model.indexOf(input_item) != -1:
                widget = self.getInputItemMappingWidget(input_item)
            if widget is None:
                widget = self.getRegisteredWidget(key)
        if widget is None:
            widget = gremlin.input_item.InputItemMappingWidget(
                input_item=input_item,
                object_name=f"StreamDeck: {input_item.display_name}",
            )
            input_item.setMappingWidget(widget)
            self.registerWidget(key, widget)
        return widget

    def isLoaded(self) -> bool:
        if self._designer is not None:
            return self._input_item_list_model is not None
        return super().isLoaded()

    def ensureLoaded(self):
        if gremlin.shared_state.is_running:
            return
        if self._designer is not None:
            if self._input_item_list_model is not None:
                self._load_handler(self._input_item_list_model, emit=True)
            self._designer.refresh()
            return
        super().ensureLoaded()

    def _handle_refresh_clicked(self):
        """Ask the plugin for a fresh snapshot, then reload this deck's input list."""
        if gremlin.shared_state.is_running:
            return
        ensure_bridge_started()
        self._refresh_status_label()
        bridge = StreamDeckBridge()
        bridge.send_command("syncInputs", deviceId=self._elgato_device_id or "")
        QtCore.QTimer.singleShot(500, self._refresh_after_plugin_sync)
        QtCore.QTimer.singleShot(900, self._refresh_after_plugin_sync)

    def _refresh_after_plugin_sync(self):
        if not Shiboken.isValid(self) or gremlin.shared_state.is_running:
            return
        self.ensureInputItems(refresh=True)
        self._redraw_input_list()
        if self._designer is not None:
            self._designer.refresh()

    def _redraw_input_list(self):
        if hasattr(self, "inputItemListView") and self.inputItemListView is not None:
            try:
                self.inputItemListView.redraw(force=True)
            except TypeError:
                try:
                    self.inputItemListView.redraw()
                except Exception:
                    pass
            except Exception:
                pass

    def _load_handler(self, model: StreamDeckInputItemListModel, emit=True) -> bool:
        """Load Stream Deck inputs (InputItemListModel.refresh only knows joystick types)."""
        model.pushSuspend()
        model.clear(emit=False)
        mode = gremlin.shared_state.edit_mode
        input_list = []
        try:
            mode_object = self.device_node.getModeNode(mode, autocreate=False) if mode else None
            if mode_object is not None:
                config = mode_object.getConfig(InputType.StreamDeck) or {}
                input_list = [item for item in config.values() if isinstance(item, StreamDeckInputItem)]
        except Exception:
            input_list = []
        if not input_list:
            registry = gremlin.shared_state.current_profile.registry
            input_list = registry.getInputItems(self.device_guid, mode, InputType.StreamDeck) or []
        if input_list:
            try:
                input_list.sort(key=lambda x: x.sortKey)
            except Exception:
                pass
            for index, input_item in enumerate(input_list):
                model.setItemAt(index, input_item)
        model.popSuspend()
        if emit:
            model.trigger()
        return True

    @property
    def inputCount(self) -> int:
        """Number of inputs in the device (required by tab selection)."""
        return self.inputItemListModel.rows() if self.inputItemListModel else 0

    @property
    def inputWidgetCount(self) -> int:
        """Number of input widgets currently shown."""
        if hasattr(self, "inputItemListView") and self.inputItemListView is not None:
            return self.inputItemListView.count()
        return 0

    def onInputListViewCreated(self):
        self.ensureInputItems(refresh=True)

    def _refresh_status_label(self):
        if Shiboken.isValid(self._status_label):
            self._status_label.setText(StreamDeckBridge().status_text())

    def _on_plugin_connected(self, connected: bool):
        self._refresh_status_label()
        if not connected:
            return
        # Resolve Elgato id now that the plugin is up (tab may have been built earlier).
        if not self._is_legacy_tab:
            resolved = StreamDeckBridge().device_id_for_guid(self.device_guid)
            if resolved:
                self._elgato_device_id = resolved
        try:
            StreamDeckBridge()._adopt_orphan_page_metadata()
        except Exception:
            pass
        gremlin.util.InvokeUiMethod(self.ensureInputItems, True)

    def _on_status_message(self, message: str):
        if Shiboken.isValid(self._status_label):
            # Prefer structured status; fall back to raw message if provided.
            text = StreamDeckBridge().status_text()
            self._status_label.setText(text if text else message)

    def _on_inputs_changed(self, device_guid):
        if compare_guid(device_guid, self.device_guid):
            gremlin.util.InvokeUiMethod(self.ensureInputItems, True)

    def ensureInputItems(self, refresh=False):
        current_mode = gremlin.shared_state.edit_mode
        mode_object = self.device_node.ensure_mode_exists(current_mode)
        config = mode_object.getConfig(InputType.StreamDeck)

        bridge = StreamDeckBridge()
        changed = False
        # Legacy tab is read-only for auto-create; new inputs go to per-device tabs.
        if self._is_legacy_tab:
            if refresh:
                self.inputItemListModel.refresh()
            return False

        device_id = self._elgato_device_id or bridge.device_id_for_guid(self.device_guid)
        # Sync live plugin context onto existing GEX-page inputs for the same slot.
        # Do not auto-create profile rows from the viewport (Companion model: create on grid click / press).
        if device_id:
            for meta in bridge.live_inputs_for_device(device_id):
                try:
                    bridge._sync_live_context_to_profile(meta)
                except Exception:
                    pass

        pruned = bridge._prune_duplicate_streamdeck_inputs(config)
        if pruned:
            changed = True
            syslog.info(f"STREAMDECK: pruned {pruned} duplicate input(s) on refresh")

        if changed or refresh:
            self.inputItemListModel.refresh()
            if hasattr(self, "_designer") and self._designer is not None:
                try:
                    self._designer.refresh()
                except Exception:
                    pass
        return changed

    def _custom_widget_handler(self, list_view, index: int, identifier, data, parent=None):
        widget = gremlin.input_item.InputItemWidget(
            input_item=identifier.input_item if hasattr(identifier, "input_item") else identifier,
            populate_ui_callback=self._populate_input_widget_ui,
            mapping_changed_callback=self._update_input_widget,
            config_external=True,
            parent=parent,
            data=data,
        )
        widget._identifier = data
        widget.create_action_icons(data)
        widget.setIcon("mdi.view-grid")
        widget.index = index
        return widget

    def _update_input_widget(self, input_widget, container_widget):
        item = getattr(input_widget, "input_item", None)
        if item is None:
            data = getattr(input_widget, "_identifier", None)
            item = data.input_item if hasattr(data, "input_item") else data
        if isinstance(item, StreamDeckInputItem):
            input_widget.setTitle(item.display_name)
            input_widget.setInputDescription(
                f"Page {item.page} · ID {item.button_id} ({item.kind})"
            )
        elif item is not None:
            input_widget.setTitle(str(getattr(item, "display_name", getattr(item, "input_id", item))))

    def _populate_input_widget_ui(self, input_widget, container_widget, data=None):
        layout = QtWidgets.QVBoxLayout(container_widget)
        status_widget = gremlin.ui.ui_common.QIconLabel()
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)
        self._update_input_widget(input_widget, container_widget)

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data)

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data)

    def _handle_lock_inputs_ui(self, data):
        if Shiboken.isValid(self) and data == self.device_guid:
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        if Shiboken.isValid(self) and data == self.device_guid:
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)


def ensure_bridge_started():
    """Start the bridge if Stream Deck support is enabled."""
    config = gremlin.config.Configuration()
    if config.streamdeck_enabled:
        StreamDeckBridge().start()
        try:
            from gremlin.ui.streamdeck_surface import (
                SurfaceVariableStore,
                hook_feedback_engine,
                install_functor_step_gate,
            )

            SurfaceVariableStore().ensure_hooks()
            install_functor_step_gate()
            hook_feedback_engine()
        except Exception as err:
            syslog.error(f"STREAMDECK: surface engine init failed: {err}")


def register_default_streamdeck_device():
    """Register the legacy Stream Deck special device (old profiles only)."""
    device = dinput.DeviceSummary()
    device.name = "Stream Deck (legacy)"
    device.device_guid = gremlin.shared_state.streamdeck_tab_guid
    device.device_type = DeviceType.StreamDeck
    device.device_category = DeviceCategory.Special
    gremlin.joystick_handling.upsertSpecialDevice(device)
    resync_streamdeck_special_devices()
