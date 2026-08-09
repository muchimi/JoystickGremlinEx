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
    """1-based Elgato profile page; missing/invalid values become page 1 (legacy)."""
    try:
        n = int(page)
    except (TypeError, ValueError):
        return 1
    if n < 1:
        return 1
    if n > 99:
        return 99
    return n


def make_input_key(kind: str, button_id: str, device_id: str = "", page=1) -> str:
    """Stable config / message key: deviceId:kind:p{page}:buttonId."""
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


def _same_physical_streamdeck_key(a, b) -> bool:
    """True if two inputs / metas refer to the same page + plugin key/dial slot."""
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
    if _page_of(a) != _page_of(b):
        return False
    ca, cb = _coords_tuple(a), _coords_tuple(b)
    return ca is not None and ca == cb

def ensure_streamdeck_special_device(device_id: str, name: str = None, device_type=None):
    """Ensure a special DeviceType.StreamDeck exists for this Elgato deviceId."""
    if not device_id:
        return None
    guid = streamdeck_guid_for_device(device_id)
    label = friendly_streamdeck_name(name, device_type, device_id)
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
        self._page = 1  # 1-based Elgato profile page (legacy = 1)
        self._kind = "button"  # button | dial | dial_press
        self._title = ""
        self._context = ""
        self._row = None
        self._column = None

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
    def display_name(self) -> str:
        prefix = f"P{self.page} · "
        if self._title:
            return prefix + self._title
        if self._kind == "dial":
            return f"{prefix}Dial {self._button_id}"
        if self._kind == "dial_press":
            return f"{prefix}Dial Press {self._button_id}"
        coords = ""
        if self._row is not None and self._column is not None:
            coords = f" (R{self._row}C{self._column})"
        return f"{prefix}Button {self._button_id}{coords}"

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
        # (device_id, kind, page, button_id) -> metadata incl. context
        self._live_inputs: dict[tuple, dict] = {}
        self._autorelease_timers: dict[tuple, threading.Timer] = {}

        self._outbound_text.connect(
            self._broadcast_text,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)

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
            return "Bridge: disabled (enable Stream Deck bridge in Options -> OSC/MIDI)"
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

    def _profile_stop(self):
        # Keep bridge running while GEX is open so Property Inspector stays connected.
        pass

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
        syslog.info(f"STREAMDECK: send_command [{command}] clients={n} data={payload}")
        self.broadcast(payload)
        return True

    def change_page(self, device_id: str, page: int, profile: str) -> bool:
        """Live Change Page — no Stream Deck restart or window close.

        Sends changePage to the plugin. The plugin updates key titles for the
        active virtual page and attempts Elgato switchToProfile when the editor
        is already closed (Elgato blocks that API while the editor is open).
        """
        try:
            page_i = int(page)
        except (TypeError, ValueError):
            page_i = 0
        if page_i < 0:
            page_i = 0

        ok = self.send_command(
            "changePage",
            deviceId=device_id or "",
            page=page_i,
            profile=profile or "",
        )
        return bool(ok)

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
        return ""

    def _request_tab_refresh(self):
        """Rebuild device tabs without a full DINPUT rescan."""
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
            guid = streamdeck_guid_for_device(device_id)
            ensure_streamdeck_special_device(device_id, name, raw_type)
            self._devices[device_id] = {
                "device_id": device_id,
                "name": name,
                "type": raw_type if raw_type is not None else "",
                "guid": guid,
            }
            self.devices_changed.emit()
            # Only rebuild tabs when a deck appears or its display name changes.
            if previous is None or previous.get("name") != name:
                self._migrate_legacy_inputs_for_device(device_id)
                self._request_tab_refresh()
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
        page = normalize_page(data.get("page", 1))
        meta = {
            "device_id": device_id,
            "button_id": button_id,
            "page": page,
            "kind": kind,
            "title": data.get("title") if data.get("title") is not None else "",
            "context": context,
            "row": data.get("row"),
            "column": data.get("column"),
        }
        # Drop any prior live entry for this plugin context / same page + grid slot.
        for old_key, old_meta in list(self._live_inputs.items()):
            if _same_physical_streamdeck_key(old_meta, meta):
                self._live_inputs.pop(old_key, None)
        key = (device_id, kind, page, button_id)
        self._live_inputs[key] = meta
        guid = self._profile_device_guid(device_id)
        try:
            self._ensure_profile_input(meta)
        except Exception as err:
            syslog.error(f"STREAMDECK: failed to register input {meta}: {err}")
            import traceback

            syslog.error(traceback.format_exc())
        self.inputs_changed.emit(guid)

    def _handle_will_disappear(self, data: dict):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        button_id = normalize_button_id(str(data.get("buttonId") or ""))
        kind = data.get("kind") or "button"
        page = normalize_page(data.get("page", 1))
        context = str(data.get("context") or "")
        if context:
            for old_key, old_meta in list(self._live_inputs.items()):
                if old_meta.get("context") == context:
                    self._live_inputs.pop(old_key, None)
        else:
            self._live_inputs.pop((device_id, kind, page, button_id), None)
        self.inputs_changed.emit(self._profile_device_guid(device_id))

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
                # Plugin is source of truth for the label shown in the list.
                if "title" in prefer_meta:
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
                # Always take the plugin title when provided (source of truth).
                if new_title is not None:
                    item.title = new_title or ""
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

    def _handle_key(self, data: dict, is_pressed: bool):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        button_id = str(data.get("buttonId") or "")
        kind = data.get("kind") or "button"
        if not device_id or not button_id:
            return
        guid = self._profile_device_guid(device_id)
        meta = {
            "device_id": device_id,
            "button_id": button_id,
            "page": normalize_page(data.get("page", 1)),
            "kind": kind,
            "title": data.get("title") or "",
            "context": data.get("context") or "",
            "row": data.get("row"),
            "column": data.get("column"),
        }
        try:
            item = self._ensure_profile_input(meta)
        except Exception as err:
            syslog.error(f"STREAMDECK: key ensure input failed: {err}")
            item = None
        if item is None:
            return
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

    def _handle_dial_rotate(self, data: dict):
        device_id = str(data.get("deviceId") or data.get("device") or "")
        button_id = str(data.get("buttonId") or data.get("controller") or "")
        ticks = int(data.get("ticks") or data.get("steps") or 0)
        if not device_id or not button_id or ticks == 0:
            return
        direction = "inc" if ticks > 0 else "dec"
        input_kind = "dial"
        page = normalize_page(data.get("page", 1))
        guid = self._profile_device_guid(device_id)
        meta = {
            "device_id": device_id,
            "button_id": f"{button_id}:{direction}",
            "page": page,
            "kind": input_kind,
            "title": data.get("title") or f"Dial {button_id} {direction.upper()}",
            "context": data.get("context") or "",
            "row": None,
            "column": None,
        }
        self._live_inputs[(device_id, input_kind, page, meta["button_id"])] = meta
        try:
            item = self._ensure_profile_input(meta)
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

        key = (device_id, input_kind, page, meta["button_id"])
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
    """UI tab for one physical Stream Deck (or the legacy shared tab)."""

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

        self.inputItemListModel = StreamDeckInputItemListModel(
            profile=profile,
            mode=mode,
            device_guid=self.device_guid,
            custom_load_handler=self._load_handler,
        )

        bridge = StreamDeckBridge()
        # Ensure bridge is up when the tab is shown (enabled in Options).
        ensure_bridge_started()

        # Banner + Refresh: Stream Deck software owns the keys; GEX list can lag
        # after add/remove/move of JG Ex Button / Dial actions.
        banner = gremlin.ui.ui_common.QInfoBox(
            "After adding, removing, or reassigning <b>JG Ex Button</b> / <b>JG Ex Dial</b> "
            "actions in Stream Deck software, click <b>Refresh</b> to update this input list."
        )
        self.addLeftPanelHeaderWidget(banner)

        refresh_btn = gremlin.ui.ui_common.Buttons.getRefreshWidget(
            "Refresh",
            tooltip="Reload Stream Deck inputs from the connected plugin",
            callback=self._handle_refresh_clicked,
        )
        status = QtWidgets.QLabel()
        status.setObjectName("streamdeck_status")
        status.setText(bridge.status_text())
        self._status_label = status
        self.addLeftPanelHeaderWidget(
            gremlin.ui.ui_common.getHContainer(
                [status, "||", refresh_btn],
                widget_only=True,
            )
        )

        port = gremlin.config.Configuration().streamdeck_bridge_port or DEFAULT_BRIDGE_PORT
        if self._is_legacy_tab:
            hint_text = (
                f"Legacy Stream Deck tab (pre multi-device). Bridge: ws://127.0.0.1:{port}. "
                "New keys appear on per-device tabs."
            )
        else:
            hint_text = (
                f"Bridge: ws://127.0.0.1:{port} — place JG Ex Button / Dial actions on this deck"
            )
        hint = QtWidgets.QLabel(hint_text)
        hint.setWordWrap(True)
        self.addLeftPanelHeaderWidget(hint)

        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data=self.device_guid)
        self.addLeftPanelHeaderWidget(gremlin.ui.ui_common.getHContainer(lock_widget, left_stretch=True, widget_only=True))

        bridge.plugin_connected.connect(self._on_plugin_connected)
        bridge.inputs_changed.connect(self._on_inputs_changed)
        bridge.status_message.connect(self._on_status_message)
        # Refresh in case listen completed just before we subscribed.
        self._refresh_status_label()

        el = gremlin.event_handler.EventListener()
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)

    def _handle_refresh_clicked(self):
        """Ask the plugin for a fresh snapshot, then reload this deck's input list."""
        ensure_bridge_started()
        self._refresh_status_label()
        bridge = StreamDeckBridge()
        # Plugin re-fetches Elgato settings, then pushes titles after a short delay.
        bridge.send_command("syncInputs", deviceId=self._elgato_device_id or "")
        # Apply when the delayed plugin push arrives (and once more as a safety net).
        QtCore.QTimer.singleShot(500, self._refresh_after_plugin_sync)
        QtCore.QTimer.singleShot(900, self._refresh_after_plugin_sync)

    def _refresh_after_plugin_sync(self):
        if not Shiboken.isValid(self):
            return
        self.ensureInputItems(refresh=True)
        self._redraw_input_list()

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
            # Prefer the live mode config (survives Button ID re-keys).
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
        live_metas = bridge.live_inputs_for_device(device_id) if device_id else []
        for meta in live_metas:
            input_key = make_input_key(
                meta["kind"],
                meta["button_id"],
                meta.get("device_id") or "",
                meta.get("page", 1),
            )
            existing = config.get(input_key)
            prior_title = existing.title if isinstance(existing, StreamDeckInputItem) else None
            try:
                item = bridge._ensure_profile_input(meta)
            except Exception as err:
                syslog.error(f"STREAMDECK: ensureInputItems failed for {input_key}: {err}")
                continue
            if item is None:
                continue
            if existing is None or (
                isinstance(item, StreamDeckInputItem) and item.title != prior_title
            ):
                changed = True

        # Collapse leftover orphans from older Button ID formats (same page + coords only).
        pruned = bridge._prune_duplicate_streamdeck_inputs(config)
        if pruned:
            changed = True
            syslog.info(f"STREAMDECK: pruned {pruned} duplicate input(s) on refresh")

        if changed or refresh:
            self.inputItemListModel.refresh()
        return changed

    def _custom_widget_handler(self, list_view, index: int, identifier, data, parent=None):
        widget = gremlin.input_item.InputItemWidget(
            input_item=identifier.input_item if hasattr(identifier, "input_item") else identifier,
            populate_ui_callback=self._populate_input_widget_ui,
            update_callback=self._update_input_widget,
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


def register_default_streamdeck_device():
    """Register the legacy Stream Deck special device (old profiles only)."""
    device = dinput.DeviceSummary()
    device.name = "Stream Deck (legacy)"
    device.device_guid = gremlin.shared_state.streamdeck_tab_guid
    device.device_type = DeviceType.StreamDeck
    device.device_category = DeviceCategory.Special
    gremlin.joystick_handling.upsertSpecialDevice(device)
    resync_streamdeck_special_devices()
