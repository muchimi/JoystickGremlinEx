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

"""GEX HIDMaestro Bridge service and interface.


The GEX Maestro Bridge Service is a background Windows service that lets GEX communicate with HIDMaestro devices without
requiring direct administrator privileges.  The Bridge Service is a separate open source project on GitHub written in C#.

Details on the HIDMaestro open source project: https://github.com/hifihedgehog/HIDMaestro

Note: HIDMaestro is NOT included with GEX and must be separately installed along with the GEX Bridge Service.

In order to use HIDMaestro devices with GEX, the bridge service must be installed and running on the machine that will use Maestro virtual devices.
This can be the same machine as GEX, or a different machine on the same network.

The bridge service talks to GEX over the OSC protocol using IPv4 UDP.  This allows relatively simple, readable and low
overhead two way binary communication between GEX (Python/C++) and the bridge service (HIDMaestro/C#).

The use of the OSC protocol is distinct from the OSC device support in GEX, so runs on a separate IP/Port/Channel.

This design eliminates the need for GEX to talk directly to .NET, and the OSC protocol offers easier cross-language communication.
The use of OSC is similar to the OSC commands used by other OSC devices to exchange data with GEX so will be familiar.
The translation layer that maps GEX mapping actions to VJOY is identical for Maestro devices.
In other words, from GEX's perspective, a Maestro device behaves just like a Vjoy device.

The GEX is able, via this module and the bridge service, to:
- Enumerate available HIDMaestro profiles, definitions, and devices.
- Create, activate, rename, and remove devices via Maestro.
- Query and manage connected HIDMaestro devices.
- Obtain axis, button and hat states from connected HIDMaestro devices.
- Send axis, button and hat states to connected HIDMaestro devices asynchronously.
- Provides an interface to manage these services in the GEX user interface.

This is managed from within GEX's Maestro devices option dialog so that GEX is aware of Maestro devices it can use.
Mapping to Maestro devices is done via the usual vjoy remap and the bridge service handles all the necessary translations.
This is designed so a Maestro device looks exactly like a Vjoy device.
"""

from dataclasses import dataclass
import json
import logging
import math
import queue
import re
import secrets
import socket
import struct
import threading
import time
from types import SimpleNamespace
import uuid

from PySide6 import QtCore, QtWidgets

import dinput
from dinput import GEX_ID_STRING, GEX_MAX_DEVICES, GEX_PID_BASE, GEX_PRODUCT_STRING
import gremlin.config
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.ui import ui_common
from gremlin.ui.ui_common import QRememberDialog


syslog = logging.getLogger("system")
AXIS_NAMES = ("X", "Y", "Z", "Rx", "Ry", "Rz", "Slider", "Dial")
HAT_POSITIONS = {
    (0, 0): 0,
    (0, 1): 1,
    (1, 1): 2,
    (1, 0): 3,
    (1, -1): 4,
    (0, -1): 5,
    (-1, -1): 6,
    (-1, 0): 7,
    (-1, 1): 8,
}
_LIST_REPLIES = {
    "/maestro_profiles": "/maestro_profile",
    "/maestro_definitions": "/maestro_definition",
    "/maestro_devices": "/maestro_device",
    "/maestro_system_devices": "/maestro_system_device",
}
_SINGLE_REPLIES = {
    "/maestro_ping": "/maestro_pong",
    "/maestro_create": "/maestro_created",
    "/maestro_create_custom": "/maestro_created",
    "/maestro_activate": "/maestro_created",
    "/maestro_rename": "/maestro_renamed",
    "/maestro_remove": "/maestro_ok",
    "/maestro_delete": "/maestro_ok",
    "/maestro_capabilities": "/maestro_capabilities_result",
    "/maestro_state": "/maestro_state_result",
    "/maestro_reset": "/maestro_ok",
}


def _osc_string(value):
    if "\0" in value:
        raise ValueError("OSC strings cannot contain NUL")
    data = value.encode("utf-8") + b"\0"
    return data + b"\0" * (-len(data) % 4)


def _encode_message(address, arguments):
    """Encode the scalar types used by Maestro protocol version 1."""
    tags, payload = ",", bytearray()
    for value in arguments:
        if isinstance(value, bool):
            tags += "T" if value else "F"
        elif isinstance(value, int):
            tags += "i"
            payload.extend(struct.pack(">i", value))
        elif isinstance(value, float):
            tags += "f"
            payload.extend(struct.pack(">f", value))
        elif isinstance(value, str):
            tags += "s"
            payload.extend(_osc_string(value))
        else:
            raise TypeError(f"Unsupported OSC argument: {type(value).__name__}")
    return _osc_string(address) + _osc_string(tags) + payload


def _decode_message(data):
    """Decode a service reply. The service sends individual OSC messages."""
    offset = 0

    def read_string():
        nonlocal offset
        end = data.index(b"\0", offset)
        value = data[offset:end].decode("utf-8")
        padded_end = (end + 4) & ~3
        if padded_end > len(data) or any(data[end:padded_end]):
            raise ValueError("Invalid OSC string padding")
        offset = padded_end
        return value

    address, tags = read_string(), read_string()
    if not address.startswith("/maestro_") or not tags.startswith(","):
        raise ValueError("Invalid Maestro OSC reply")
    values = []
    for tag in tags[1:]:
        if tag == "s":
            values.append(read_string())
        elif tag in "ifhd":
            fmt = ">" + {"h": "q"}.get(tag, tag)
            values.append(struct.unpack_from(fmt, data, offset)[0])
            offset += struct.calcsize(fmt)
        elif tag in "TF":
            values.append(tag == "T")
        else:
            raise ValueError(f"Unsupported OSC reply type: {tag}")
    if offset != len(data):
        raise ValueError("Trailing OSC reply data")
    return address, values


class MaestroServiceError(RuntimeError):
    """An error returned by MaestroOscService."""

    def __init__(self, address, code, description):
        super().__init__(f"{address}: {code}: {description}")
        self.address, self.code = address, code


class MaestroOscClient:
    """Dedicated OSC transport, independent of GEX's user OSC input/output.

    A receiver drains control echoes/errors without blocking output callbacks.
    Management calls correlate by ID and retry identical packets from the same
    source socket, using the service's replay cache. Lists collect indexed rows
    even when completion arrives before the data or a retry repeats rows.
    """

    def __init__(self, host="127.0.0.1", port=8010, reply_host="127.0.0.1", reply_port=8011, timeout=3.0, attempts=3):
        self.destination = (socket.gethostbyname(host), port)
        self.timeout, self.attempts = timeout, attempts
        self._closed = threading.Event()
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._request_id = secrets.randbelow(1 << 30)
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Two applications cannot correlate replies reliably on a shared
            # fixed destination port. Never enable SO_REUSEADDR here.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self._rx.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self._rx.bind((reply_host, reply_port))
            self._rx.settimeout(0.2)
        except OSError:
            self._tx.close()
            self._rx.close()
            raise
        self._receiver = threading.Thread(target=self._receive, name="Maestro OSC replies", daemon=True)
        self._receiver.start()

    def _send(self, packet):
        with self._send_lock:
            if self._closed.is_set():
                raise OSError("Maestro OSC client is closed")
            self._tx.sendto(packet, self.destination)

    def write(self, address, value):
        """Send a value-first control message without a management request ID."""
        self._send(_encode_message(address, [value]))

    def request(self, address, *arguments, timeout=None, attempts=None):
        if address not in _LIST_REPLIES and address not in _SINGLE_REPLIES:
            raise ValueError(f"Not a Maestro management address: {address}")
        replies = queue.Queue()
        with self._pending_lock:
            self._request_id = (self._request_id + 1) & 0x7FFFFFFF
            request_id = self._request_id
            self._pending[request_id] = replies
        try:
            packet = _encode_message(address, [request_id, *arguments])
            rows, done = {}, None
            for _ in range(self.attempts if attempts is None else attempts):
                self._send(packet)
                deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
                while time.monotonic() < deadline:
                    try:
                        item = replies.get(timeout=max(0.001, deadline - time.monotonic()))
                    except queue.Empty:
                        break
                    if item is None:
                        raise OSError("Maestro OSC client is closed")
                    reply, values = item
                    if reply == "/maestro_error":
                        raise MaestroServiceError(values[1], values[2], values[3])
                    if address not in _LIST_REPLIES:
                        if reply == _SINGLE_REPLIES[address]:
                            return values
                        continue
                    if reply == "/maestro_done" and len(values) == 5 and values[1] == address:
                        done = values
                    elif reply == _LIST_REPLIES[address] and len(values) == 3:
                        rows[values[1]] = values[2]
                    if done is not None:
                        expected = range(done[3], done[3] + done[4])
                        if all(index in rows for index in expected):
                            return [json.loads(rows[index]) for index in expected], done[2]
            raise TimeoutError(f"No complete Maestro reply for {address} at {self.destination}")
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def list(self, address):
        result, offset = [], 0
        while True:
            rows, total = self.request(address, offset, 100)
            result.extend(rows)
            offset += len(rows)
            if offset >= total:
                return result
            if not rows:
                raise RuntimeError(f"Maestro list made no progress: {address}")

    def _receive(self):
        while not self._closed.is_set():
            try:
                data, source = self._rx.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if not self._closed.is_set():
                    syslog.exception("MAESTRO: reply listener failed")
                return
            if source[0] != self.destination[0]:
                continue
            try:
                reply, values = _decode_message(data)
                if reply == "/maestro_error" and len(values) != 4:
                    raise ValueError("Invalid Maestro error reply")
                with self._pending_lock:
                    pending = self._pending.get(values[0]) if values and type(values[0]) is int else None
                    if pending is not None and not reply.startswith(
                        (
                            "/maestro_axis/",
                            "/maestro_button/",
                            "/maestro_hat/",
                            "/maestro_gamepad_axis/",
                        )
                    ):
                        pending.put((reply, values))
                    elif reply == "/maestro_error":
                        syslog.error("MAESTRO: %s: %s: %s", *values[1:])
            except (ValueError, IndexError, struct.error) as error:
                syslog.warning("MAESTRO: invalid OSC reply: %s", error)

    def close(self):
        with self._send_lock:
            self._closed.set()
            self._tx.close()
            self._rx.close()
        with self._pending_lock:
            for pending in self._pending.values():
                pending.put(None)
        if threading.current_thread() is not self._receiver:
            self._receiver.join(timeout=1)


@dataclass
class MaestroController:
    """Service-owned custom joystick; Index and Profile retain legacy access."""

    Index: int
    Id: str
    Name: str
    axis_count: int
    button_count: int
    hat_count: int
    Profile: SimpleNamespace
    axis_names: tuple = AXIS_NAMES
    kind: str = "custom"


def service_snapshot(client):
    """Read saved definitions, active devices and the host's profile catalog."""
    return dict(definitions=client.list("/maestro_definitions"), devices=client.list("/maestro_devices"), profiles=client.list("/maestro_profiles"))


def save_device_definition(client, definition, previous=None):
    """Save the editor's definition using the service's version 1 commands.

    Layout edits require recreation. If any step fails, restore the previous
    saved definition, including whether it was active. Never erase input maps.
    """
    device_id = definition["id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id):
        raise ValueError("Device ID must contain 1–64 letters, digits, underscores or hyphens")
    if not definition["name"].strip() or len(definition["name"]) > 128:
        raise ValueError("Device name must contain 1–128 characters")
    if previous is not None and previous["id"] != device_id:
        raise ValueError("An existing device's ID cannot be changed")

    def create(row):
        if row["kind"] == "custom":
            client.request("/maestro_create_custom", row["id"], row["name"], row["buttons"], row["axes"], row["hats"])
        else:
            client.request("/maestro_create", row["id"], row["profileId"], row["name"])
        if not row["enabled"]:
            client.request("/maestro_remove", row["id"])

    layout_keys = ("kind", "profileId", "axes", "buttons", "hats")
    changed_layout = previous is not None and any(definition.get(k) != previous.get(k) for k in layout_keys)
    if previous is None:
        create(definition)
    elif changed_layout:
        client.request("/maestro_delete", device_id)
        try:
            create(definition)
        except Exception as error:
            try:
                # A failed create may still have saved a definition (e.g. a
                # later deactivate failed). Clear that ID before restoring.
                if any(d["id"] == device_id for d in client.list("/maestro_definitions")):
                    client.request("/maestro_delete", device_id)
                create(previous)
            except Exception as restore_error:
                raise RuntimeError(f"{error}. Restoring the previous device also failed: {restore_error}") from error
            raise RuntimeError(f"{error}. The previous device definition was restored.") from error
    else:
        if definition["name"] != previous["name"]:
            client.request("/maestro_rename", device_id, definition["name"])
        if definition["enabled"] != previous["enabled"]:
            client.request("/maestro_activate" if definition["enabled"] else "/maestro_remove", device_id)


@SingletonDecorator
class Maestro:
    def __init__(self):
        self._controller_map = {}
        self._device_map = {}
        self._buffer_map = {}
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._sync_worker = None
        self._stopping = threading.Event()
        self._dirty = False
        self.ctx = None
        self._initialized = False
        self._shutdown_connected = False
        self._local_service = True
        config = gremlin.config.Configuration()
        if not config.maestro_enabled:
            syslog.info("MAESTRO: disabled")
            return
        try:
            self.connect(config.maestro_osc_host, config.maestro_osc_port, config.maestro_osc_reply_host, config.maestro_osc_reply_port)
            self.LoadActiveControllers()
            if config.maestro_device_map is None:
                for index in range(min(GEX_MAX_DEVICES, max(0, config.maestro_device_count))):
                    if index not in self._controller_map:
                        self.createJoystickController(at_index=index)
            self.populateDeviceList()
            self.sync(force=True)
            syslog.info(f"MAESTRO: connected to Maestro Bridge service {len(self._controller_map)} managed controllers")
        except (OSError, RuntimeError, ValueError, IndexError) as error:
            syslog.error("MAESTRO: could not initialize Maestro Bridge service: %s", error)
            if self.ctx is not None:
                self.ctx.close()
                self.ctx = None
            self._initialized = False

    @staticmethod
    def _service_id(index):
        return f"{GEX_ID_STRING.lower()}-{index}"

    @classmethod
    def _service_index(cls, device_id):
        return next((i for i in range(GEX_MAX_DEVICES) if cls._service_id(i) == device_id), None)

    @property
    def initialized(self):
        return self._initialized

    @property
    def enabled(self):
        return self.initialized and gremlin.config.Configuration().maestro_enabled

    def connect(self, host, port, reply_host, reply_port):
        """Connect or retest the shared transport used by output and the dialog."""
        settings = (socket.gethostbyname(host), port, reply_host, reply_port)
        with self._lock:
            if self.ctx is not None and getattr(self, "_connection_settings", None) != settings:
                self._handle_shutdown()
                self._controller_map.clear()
                self._device_map.clear()
                self._buffer_map.clear()
                from gremlin import joystick_handling

                joystick_handling.set_maestro_devices([])
            if self.ctx is None:
                self.ctx = MaestroOscClient(*settings)
            try:
                pong = self.ctx.request("/maestro_ping", timeout=1.0, attempts=2)
                if pong[1:] != ["MaestroOscService", 1]:
                    raise RuntimeError(f"Unsupported Maestro service/protocol: {pong[1:]}")
            except Exception:
                self.ctx.close()
                self.ctx = None
                self._initialized = False
                raise
            self._connection_settings = settings
            self._local_service = settings[0].startswith("127.") or settings[0] == "0.0.0.0"
            if not self._local_service:
                try:
                    self._local_service = settings[0] in socket.gethostbyname_ex(socket.gethostname())[2]
                except OSError:
                    pass
            self._stopping.clear()
            self._initialized = True
            if not self._shutdown_connected:
                from gremlin import event_handler

                event_handler.EventListener().shutdown.connect(self._handle_shutdown)
                self._shutdown_connected = True
            return pong

    def _handle_shutdown(self):
        self._stopping.set()
        with self._lock:
            if self.ctx is None:
                return
            # The service outlives GEX. Finish in-flight writes before resetting
            # controls, and retain definitions for the next GEX session.
            try:
                for controller in list(self._controller_map.values()):
                    try:
                        self.ctx.request("/maestro_reset", controller.Id, timeout=0.3, attempts=1)
                    except (OSError, RuntimeError) as error:
                        syslog.warning("MAESTRO: reset on shutdown failed: %s", error)
            finally:
                self.ctx.close()
                self.ctx = None
                self._initialized = False

    def _cache_controller(self, info, definition, index=None):
        if index is None:
            index = self._service_index(info["id"])
        capabilities = json.loads(self.ctx.request("/maestro_capabilities", info["id"])[-1])
        state = json.loads(self.ctx.request("/maestro_state", info["id"])[-1])
        axes = tuple(capabilities["axes"])
        custom = definition["kind"] == "custom"
        buttons = definition["buttons"] if custom else capabilities.get("addressableButtons", 32)
        hats = definition["hats"] if custom else capabilities.get("hatCount", 1)
        controller = MaestroController(
            index,
            info["id"],
            info["name"],
            len(axes),
            buttons,
            hats,
            SimpleNamespace(ProductId=capabilities["productId"], VendorId=capabilities["vendorId"]),
            axes,
            definition["kind"],
        )
        with self._lock:
            self._controller_map[index] = controller
            self._buffer_map[index] = self._neutral_buffer(controller)
            for axis, name in enumerate(axes, 1):
                self._set_axis(index, axis, state["axes"].get(name, 0.5) * 2 - 1)
            pressed = state.get("pressedButtons")
            if pressed is None:
                pressed = [b for b in range(1, buttons + 1) if state["buttons"] & (1 << (b - 1))]
            for button in pressed:
                self._set_button(index, button, True)
            positions = state.get("hats") or ([state["hat"]] if hats else [])
            for hat, position in enumerate(positions, 1):
                self._set_hat(index, hat, position)
            self._dirty = True
        return controller

    def LoadActiveControllers(self, device_map=None):
        """Attach selected active definitions without recreating hardware."""
        if not self.initialized:
            return
        if device_map is None:
            device_map = gremlin.config.Configuration().maestro_device_map
        definitions = {d["id"]: d for d in self.ctx.list("/maestro_definitions")}
        active = {}
        for info in self.ctx.list("/maestro_devices"):
            index = self._service_index(info["id"]) if device_map is None else device_map.get(info["id"])
            if index is not None and info["id"] in definitions:
                controller = self._cache_controller(info, definitions[info["id"]], index)
                active[controller.Index] = controller
        with self._lock:
            self._controller_map = active
            self._device_map = {i: d for i, d in self._device_map.items() if i in active}
            self._buffer_map = {i: b for i, b in self._buffer_map.items() if i in active}
            self._dirty = True

    def reset(self):
        """Reconnect saved active controllers and refresh DirectInput discovery."""
        if self.enabled:
            self.LoadActiveControllers()
            self.populateDeviceList()
            self.sync(force=True)

    def sync(self, force=False) -> bool:
        if not self.enabled or self._stopping.is_set() or not (self._dirty or force):
            return False
        with self._sync_lock:
            if self._sync_worker is not None:
                return False
            self.syncControllers()
            if not self._compare_list():
                self._dirty = False
                return False
            self._sync_worker = threading.Thread(target=self._sync_worker_runner, name="Maestro DirectInput sync", daemon=True)
            self._sync_worker.start()
            return True

    def _sync_worker_runner(self):
        try:
            deadline = time.monotonic() + 20
            while not self._stopping.is_set():
                self.syncControllers()
                if not self._compare_list():
                    self._dirty = False
                    import gremlin.joystick_handling

                    self.populateDeviceList()
                    gremlin.joystick_handling.joystick_devices_initialization()
                    return
                if time.monotonic() >= deadline:
                    syslog.warning("MAESTRO: DirectInput discovery timed out (service names may be cached by Windows)")
                    return
                self._stopping.wait(0.2)
        except Exception:
            syslog.exception("MAESTRO: DirectInput synchronization failed")
        finally:
            with self._sync_lock:
                self._sync_worker = None

    def _compare_list(self) -> bool:
        with self._lock:
            if not self._local_service:
                return False
            return self._controller_map.keys() != self._device_map.keys()

    def syncControllers(self):
        """Match by name and capabilities: service PIDs are not device indices."""
        if not self._local_service:
            with self._lock:
                self._device_map.clear()
            return
        devices = dinput.DILL.getDevices()
        with self._lock:
            mapped = {}
            for index, controller in self._controller_map.items():
                matches = [
                    d
                    for d in devices
                    if d.name == controller.Name
                    and d.vendor_id == controller.Profile.VendorId
                    and d.product_id == controller.Profile.ProductId
                    and (d.axis_count, d.button_count, d.hat_count) == (controller.axis_count, controller.button_count, controller.hat_count)
                ]
                if len(matches) == 1:
                    mapped[index] = matches[0]
            self._device_map = mapped

    def populateDeviceList(self):
        """Publish selected service devices to Gremlin's virtual device registry.

        Use native DirectInput identities where they can be matched uniquely.
        Other hosts use stable endpoint/device identities and expose output
        capabilities; they do not generate local joystick input events.
        """
        from gremlin import joystick_handling
        from gremlin.types import DeviceType, DeviceCategory

        self.syncControllers()
        devices = []
        with self._lock:
            for index, controller in self._controller_map.items():
                device = self._device_map.get(index)
                if device is None:
                    device = dinput.DeviceSummary()
                    host, port = self.ctx.destination
                    device.device_guid = dinput.GUID(uuid.uuid5(uuid.NAMESPACE_URL, f"maestro://{host}:{port}/{controller.Id}"))
                    device.axis_count = controller.axis_count
                    device.button_count = controller.button_count
                    device.hat_count = controller.hat_count
                    device.vendor_id = controller.Profile.VendorId
                    device.product_id = controller.Profile.ProductId
                    for axis, name in enumerate(controller.axis_names[: controller.axis_count], 1):
                        device.linear_id_map[axis] = axis
                        device.axis_id_map[axis] = axis
                        device.axis_names[axis] = name
                    device.setConnected(True)
                    device.input_enabled = False
                axis_map = dict(device.axis_id_map)
                device.setAxisCallback(lambda axis, i=index, mapping=axis_map: self._read_axis_raw(i, mapping.get(axis, axis)))
                device.setButtonCallback(lambda button, i=index: self._read_button(i, button))
                device.setHatCallback(lambda hat, i=index: self._read_hat(i, hat))
                device.name = controller.Name
                device.device_type = DeviceType.Maestro
                device.device_category = DeviceCategory.Virtual
                device.setVirtual(True)
                device.virtual_id = index
                device.data["maestro_service_id"] = controller.Id
                devices.append(device)
        joystick_handling.set_maestro_devices(devices)

    def _read_axis_raw(self, index, axis):
        """Return the retained OSC output in DirectInput's signed axis units."""
        with self._lock:
            controller = self._controller_map.get(index)
            if controller is None or not 1 <= axis <= controller.axis_count:
                return 0
            offset = (controller.button_count + 7) // 8 + (axis - 1) * 2
            return struct.unpack_from("<h", self._buffer_map[index], offset)[0]

    def _read_button(self, index, button):
        with self._lock:
            controller = self._controller_map.get(index)
            if controller is None or not 1 <= button <= controller.button_count:
                return False
            return bool(self._buffer_map[index][(button - 1) // 8] & (1 << ((button - 1) % 8)))

    def _read_hat(self, index, hat):
        with self._lock:
            controller = self._controller_map.get(index)
            if controller is None or not 1 <= hat <= controller.hat_count:
                return -1
            offset = (controller.button_count + 7) // 8 + controller.axis_count * 2 + hat - 1
            value = self._buffer_map[index][offset]
            return -1 if value == 255 else value * 4500

    def getController(self, key: int):
        return self._controller_map.get(key)

    def getAllDevices(self) -> list:
        """Return JSON records for all active devices owned by the service."""
        return self.ctx.list("/maestro_devices") if self.enabled else []

    def addMissingControllers(self):
        if self.enabled:
            if gremlin.config.Configuration().maestro_device_map is not None:
                self.LoadActiveControllers()
                self.populateDeviceList()
                return
            count = min(GEX_MAX_DEVICES, max(0, gremlin.config.Configuration().maestro_device_count))
            for index in range(count):
                if index not in self._controller_map:
                    self.createJoystickController(at_index=index)

    def removeController(self, controller):
        """Deactivate one GEX controller, retaining its saved definition."""
        if not self.enabled or self._controller_map.get(controller.Index) is not controller:
            return
        self.ctx.request("/maestro_remove", controller.Id)
        with self._lock:
            self._controller_map.pop(controller.Index, None)
            self._device_map.pop(controller.Index, None)
            self._buffer_map.pop(controller.Index, None)
            self._dirty = True
        self.populateDeviceList()

    def removeAllControllers(self):
        """Deactivate only attached GEX devices; never remove other clients' devices."""
        for controller in list(self._controller_map.values()):
            self.removeController(controller)

    def createJoystickController(self, axis_count=8, button_count=128, hat_count=4, at_index=None):
        if not self.enabled:
            return None
        counts = ((axis_count, 8), (button_count, 128), (hat_count, 4))
        if any(type(n) is not int or not 0 <= n <= maximum for n, maximum in counts) or not any(n for n, _ in counts):
            raise ValueError("Maestro joystick requires 0..8 axes, 0..128 buttons, 0..4 hats and at least one control")
        index = at_index
        if index is None:
            index = next((i for i in range(GEX_MAX_DEVICES) if i not in self._controller_map), GEX_MAX_DEVICES)
        if type(index) is not int or not 0 <= index < GEX_MAX_DEVICES:
            syslog.warning("MAESTRO: controller index must be 0..%s", GEX_MAX_DEVICES - 1)
            return None
        try:
            device_id, name = self._service_id(index), f"{GEX_PRODUCT_STRING} {index}"
            result = self.ctx.request("/maestro_create_custom", device_id, name, button_count, axis_count, hat_count)
            controller = self._cache_controller(json.loads(result[-1]), dict(kind="custom", axes=axis_count, buttons=button_count, hats=hat_count))
            self.populateDeviceList()
            return controller
        except (OSError, RuntimeError, ValueError) as error:
            syslog.error("MAESTRO: failed to create controller %s: %s", index, error)
            return None

    def pidToIndex(self, pid: int) -> int:
        """Convert a legacy GEX logical PID; service hardware PIDs are shared."""
        index = pid - GEX_PID_BASE
        return index if 0 <= index < GEX_MAX_DEVICES else -1

    def getDevice(self, pid: int):
        """Look up DirectInput using a legacy GEX logical PID (base + index)."""
        if self._dirty:
            self.syncControllers()
        return self._device_map.get(self.pidToIndex(pid))

    @staticmethod
    def _neutral_buffer(controller):
        size = (controller.button_count + 7) // 8 + controller.axis_count * 2
        return bytearray(size) + bytearray([255] * controller.hat_count)

    def getBuffer(self, device_index):
        """Return the local service-layout snapshot; mutating it sends no OSC."""
        return self._buffer_map.get(device_index)

    def _control(self, device_index, control_index, kind):
        controller = self._controller_map.get(device_index)
        if controller is None:
            return None
        count = getattr(controller, f"{kind}_count")
        if type(control_index) is not int or not 1 <= control_index <= count:
            raise ValueError(f"Maestro {kind} index must be 1..{count}")
        return controller

    def _set_axis(self, device_index, axis_index, value):
        controller = self._control(device_index, axis_index, "axis")
        if controller is None:
            return
        if not math.isfinite(value):
            raise ValueError("Maestro axis value must be finite")
        value = max(-1.0, min(1.0, value))
        raw = value * 32767
        raw = math.floor(raw + 0.5) if raw >= 0 else math.ceil(raw - 0.5)
        offset = (controller.button_count + 7) // 8 + (axis_index - 1) * 2
        struct.pack_into("<h", self._buffer_map[device_index], offset, raw)

    def setAxis(self, device_index: int, axis_index: int, value: float):
        """Write a one-based axis, converting GEX -1..1 to service 0..1."""
        with self._lock:
            if not self.enabled or self._stopping.is_set():
                return
            controller = self._control(device_index, axis_index, "axis")
            if controller is None:
                return
            if not math.isfinite(value):
                raise ValueError("Maestro axis value must be finite")
            value = max(-1.0, min(1.0, value))
            self.ctx.write(f"/maestro_axis/{controller.Id}/{controller.axis_names[axis_index - 1]}", (value + 1) / 2)
            self._set_axis(device_index, axis_index, value)

    def _set_button(self, device_index, button_index, is_pressed):
        if self._control(device_index, button_index, "button") is None:
            return
        offset, bit = divmod(button_index - 1, 8)
        buffer = self._buffer_map[device_index]
        if is_pressed:
            buffer[offset] |= 1 << bit
        else:
            buffer[offset] &= ~(1 << bit)

    def setButton(self, device_index: int, button_index: int, is_pressed: bool):
        """Write a one-based descriptor button, including buttons 33..128."""
        with self._lock:
            if not self.enabled or self._stopping.is_set():
                return
            controller = self._control(device_index, button_index, "button")
            if controller is None:
                return
            self.ctx.write(f"/maestro_button/{controller.Id}/{button_index}", int(bool(is_pressed)))
            self._set_button(device_index, button_index, is_pressed)

    def _set_hat(self, device_index, hat_index, value):
        controller = self._control(device_index, hat_index, "hat")
        if controller is None:
            return
        offset = (controller.button_count + 7) // 8 + controller.axis_count * 2 + hat_index - 1
        self._buffer_map[device_index][offset] = value - 1 if value else 255

    def setHat(self, device_index: int, hat_index: int, position: tuple):
        """Write a one-based independent hat using a GEX (x, y) direction."""
        with self._lock:
            if not self.enabled or self._stopping.is_set():
                return
            controller = self._control(device_index, hat_index, "hat")
            if controller is None:
                return
            value = HAT_POSITIONS.get(position, 0)
            self.ctx.write(f"/maestro_hat/{controller.Id}/{hat_index}", value)
            self._set_hat(device_index, hat_index, value)

    def syncBuffer(self, device_index: int):
        """Refresh the local snapshot from DirectInput without sending outputs."""
        import gremlin.joystick_handling

        with self._lock:
            device = self._device_map.get(device_index)
            controller = self._controller_map.get(device_index)
            if device is None or controller is None:
                return
            for axis in range(1, controller.axis_count + 1):
                input_id = device.axis_sequence_to_input_id(axis - 1)
                self._set_axis(device_index, axis, gremlin.joystick_handling.get_axis(device.device_guid, input_id))
            for button in range(1, controller.button_count + 1):
                self._set_button(device_index, button, gremlin.joystick_handling.get_button(device.device_guid, button))
            for hat in range(1, controller.hat_count + 1):
                position = gremlin.joystick_handling.get_hat_position(device.device_guid, hat)
                self._set_hat(device_index, hat, HAT_POSITIONS.get(position, 0))

    def removeDevice(self):
        """Legacy single-controller removal hook."""
        controller = getattr(self, "controller", None)
        if controller is not None:
            self.removeController(controller)
            self.controller = None


class MaestroAxis:
    def __init__(self, device, index):
        self.device, self.axis_id = device, index

    @property
    def value(self):
        return self.device.maestro._read_axis_raw(self.device.id, self.axis_id) / 32767

    @value.setter
    def value(self, value):
        self.device.maestro.setAxis(self.device.id, self.axis_id, value)

    def set_absolute_value(self, value):
        self.value = value


class MaestroButton:
    def __init__(self, device, index):
        self.device, self.button_id = device, index

    @property
    def is_pressed(self):
        return self.device.maestro._read_button(self.device.id, self.button_id)

    @is_pressed.setter
    def is_pressed(self, value):
        self.device.maestro.setButton(self.device.id, self.button_id, value)


class MaestroHat:
    def __init__(self, device, index):
        self.device, self.hat_id = device, index

    @property
    def direction(self):
        degrees = self.device.maestro._read_hat(self.device.id, self.hat_id)
        value = 0 if degrees == -1 else degrees // 4500 + 1
        return next(position for position, code in HAT_POSITIONS.items() if code == value)

    @direction.setter
    def direction(self, value):
        self.device.maestro.setHat(self.device.id, self.hat_id, value)


class MaestroOutputDevice:
    """vjoy.VJoy-compatible axis/button/hat access backed by Maestro OSC."""

    def __init__(self, index, maestro=None):
        self.id = index
        self.maestro = maestro if maestro is not None else Maestro()

    @property
    def controller(self):
        controller = self.maestro.getController(self.id)
        if controller is None:
            raise RuntimeError(f"Maestro device {self.id} is unavailable")
        return controller

    @property
    def axis_count(self):
        return self.controller.axis_count

    @property
    def button_count(self):
        return self.controller.button_count

    @property
    def hat_count(self):
        return self.controller.hat_count

    def is_axis_valid(self, axis_id=None, linear_index=None):
        index = axis_id if axis_id is not None else linear_index
        return type(index) is int and 1 <= index <= self.axis_count

    def is_button_valid(self, index):
        return type(index) is int and 1 <= index <= self.button_count

    def is_hat_valid(self, index):
        return type(index) is int and 1 <= index <= self.hat_count

    def axis(self, axis_id=None, linear_index=None):
        index = axis_id if axis_id is not None else linear_index
        if not self.is_axis_valid(index):
            raise ValueError(f"Invalid Maestro axis: {index}")
        return MaestroAxis(self, index)

    def button(self, index):
        if not self.is_button_valid(index):
            raise ValueError(f"Invalid Maestro button: {index}")
        return MaestroButton(self, index)

    def hat(self, index):
        if not self.is_hat_valid(index):
            raise ValueError(f"Invalid Maestro hat: {index}")
        return MaestroHat(self, index)


class _MaestroDialogSignals(QtCore.QObject):
    completed = QtCore.Signal(object, object)


class MaestroDialog(QRememberDialog):
    """Configure HIDMaestro via the GEX bridge, edit service devices and update GremlinEx targets."""

    devices_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__("MaestroDialog", width=920, height=760, parent=parent)
        self.setWindowTitle("Maestro Devices")
        self.setModal(True)
        self.config = gremlin.config.Configuration()
        self.maestro = Maestro()
        self._busy = False
        self._tested_settings = None
        self._definitions = {}
        self._profiles = {}
        self._selected_ids = set()
        self._previous = None
        self._completion = None
        self._signals = _MaestroDialogSignals(self)
        self._signals.completed.connect(self._completed, QtCore.Qt.ConnectionType.QueuedConnection)
        layout = QtWidgets.QVBoxLayout(self)

        self.connection_group = ui_common.QGroupBoxV("Maestro Bridge service")
        self.host_widget = ui_common.QDataLineEdit(self.config.maestro_osc_host, tooltip="Host name or IPv4 address of the Maestro service")
        self.port_widget = ui_common.QIntLineEdit(min_range=1, max_range=65535, value=self.config.maestro_osc_port, chars=6)
        self.reply_host_widget = ui_common.QDataIPLineEdit(self.config.maestro_osc_reply_host)
        self.reply_port_widget = ui_common.QIntLineEdit(min_range=1, max_range=65535, value=self.config.maestro_osc_reply_port, chars=6)
        self.test_button = ui_common.QDataPushButton("Test Connection", clicked=self._connect)
        self.refresh_button = ui_common.QDataPushButton("Refresh Devices", clicked=self._connect)
        self.connection_group.addWidget(
            ui_common.getHContainer(
                [
                    "Host:",
                    self.host_widget,
                    "Port:",
                    self.port_widget,
                    self.test_button,
                    self.refresh_button,
                ],
                widget_only=True,
            )
        )
        self.connection_group.addWidget(
            ui_common.getHContainer(
                [
                    "Receive replies on:",
                    self.reply_host_widget,
                    "Reply port:",
                    self.reply_port_widget,
                ],
                widget_only=True,
                tooltip="Reply port must match the host service's SendPort. For another host, use a local LAN interface or 0.0.0.0.",
            )
        )
        layout.addWidget(self.connection_group)
        self.status_widget = ui_common.QDataLabel("Enter the service address and test the connection.")
        self.status_widget.setWordWrap(True)
        self.status_widget.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.status_widget)
        self.warning_widget = ui_common.QWarningWidget(autohide=True)
        layout.addWidget(self.warning_widget)

        self.devices_group = ui_common.QGroupBoxV("Devices on host — check devices to include in Gremlin")
        self.device_list = ui_common.QScrollableWidget(stretch=False, horizontal_scroll=False)
        self.device_list.getLayout().setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.device_list.setMinimumHeight(150)
        self.devices_group.addWidget(self.device_list)
        self.new_button = ui_common.QDataPushButton("New Device", clicked=self._new_device)
        self.devices_group.addWidget(ui_common.getHContainer([self.new_button], widget_only=True))
        layout.addWidget(self.devices_group, 1)

        self.editor_group = ui_common.QGroupBoxV("Device options")
        self.id_widget = ui_common.QDataLineEdit()
        self.id_widget.setMaxLength(64)
        self.name_widget = ui_common.QDataLineEdit()
        self.name_widget.setMaxLength(128)
        self.profile_widget = ui_common.QDataComboBox(wheel_enabled=False)
        self.axes_widget = ui_common.QIntLineEdit(min_range=0, max_range=8, value=8, chars=3)
        self.buttons_widget = ui_common.QIntLineEdit(min_range=0, max_range=128, value=128, chars=4)
        self.hats_widget = ui_common.QIntLineEdit(min_range=0, max_range=4, value=4, chars=3)
        self.active_widget = ui_common.QDataCheckbox("Active on host", checked=True)
        self.include_widget = ui_common.QDataCheckbox("Include in Gremlin", checked=True)
        self.save_button = ui_common.QDataPushButton("Save Device", clicked=self._save_device)
        for widgets in (
            ["Device ID:", self.id_widget, "Name:", self.name_widget],
            ["Profile:", self.profile_widget],
            ["Axes:", self.axes_widget, "Buttons:", self.buttons_widget, "Hats:", self.hats_widget],
            [self.active_widget, self.include_widget, "||", self.save_button],
        ):
            self.editor_group.addWidget(ui_common.getHContainer(widgets, widget_only=True))
        editor_note = ui_common.QDataLabel("Saving a new layout or renaming an active device reconnects it and resets its inputs.")
        editor_note.setWordWrap(True)
        self.editor_group.addWidget(editor_note)
        layout.addWidget(self.editor_group)
       
        self.apply_button = ui_common.QDataPushButton("Apply to Gremlin", clicked=self._apply)
        self.close_button = ui_common.QDataPushButton("Close", clicked=self.close)
        layout.addWidget(
            ui_common.getHContainer(
                [
                    self.apply_button,
                    self.close_button,
                ],
                widget_only=True,
                auto_size=True
            )
        )
        self.profile_widget.currentIndexChanged.connect(self._profile_changed)
        for widget in (self.host_widget, self.reply_host_widget, self.port_widget, self.reply_port_widget):
            widget.textChanged.connect(self._invalidate_connection)
        self._update_enabled()

    def _settings(self):
        host, reply_host = self.host_widget.text().strip(), self.reply_host_widget.text().strip()
        port, reply_port = self.port_widget.value(), self.reply_port_widget.value()
        if not host or not reply_host or port is None or reply_port is None or not 1 <= port <= 65535 or not 1 <= reply_port <= 65535 or port == reply_port:
            raise ValueError("Enter a host, a reply interface and two different ports between 1 and 65535")
        return host, port, reply_host, reply_port

    def _invalidate_connection(self, *args):
        self._tested_settings = None
        self._update_enabled()
        self.status_widget.setText("Connection settings changed. Test the connection to load this host's devices.")

    def _update_enabled(self):
        connected = self._tested_settings is not None
        self.connection_group.setEnabled(not self._busy)
        self.devices_group.setEnabled(connected and not self._busy)
        self.editor_group.setEnabled(connected and not self._busy)
        self.apply_button.setEnabled(connected and not self._busy)
        self.enabled_widget.setEnabled(not self._busy)
        self.close_button.setEnabled(not self._busy)

    def _submit(self, operation, complete, message):
        if self._busy:
            return
        self._busy = True
        self._completion = complete
        self.warning_widget.setText("")
        self.status_widget.setText(message)
        self._update_enabled()
        signals = self._signals

        def run():
            result, error = None, None
            try:
                result = operation()
            except Exception as exc:
                syslog.exception("MAESTRO: dialog operation failed")
                error = str(exc)
            signals.completed.emit(result, error)

        threading.Thread(target=run, name="Maestro dialog request", daemon=True).start()

    @QtCore.Slot(object, object)
    def _completed(self, result, error):
        self._busy = False
        complete, self._completion = self._completion, None
        if error:
            self.warning_widget.setText(error)
            self.status_widget.setText("The operation did not complete. Refresh to read the host's current devices.")
        else:
            complete(result)
        self._update_enabled()

    def _connect(self):
        try:
            settings = self._settings()
        except ValueError as error:
            self.warning_widget.setText(str(error))
            return
        retain_selection = settings == self._tested_settings
        self._tested_settings = None

        def operation():
            self.maestro.connect(*settings)
            return service_snapshot(self.maestro.ctx)

        def complete(snapshot):
            self._tested_settings = settings
            if not retain_selection:
                same_host = settings[:2] == (self.config.maestro_osc_host, self.config.maestro_osc_port)
                selected = self.config.maestro_device_map if same_host else None
                self._selected_ids = (
                    set(selected) if selected is not None else {d["id"] for d in snapshot["definitions"] if Maestro.klass._service_index(d["id"]) is not None}
                )
            self._load_snapshot(snapshot)
            self.status_widget.setText(f"Connected to {settings[0]}:{settings[1]} — {len(snapshot['devices'])} active device(s).")

        self._submit(operation, complete, "Testing the connection and reading devices…")

    def _load_snapshot(self, snapshot, select_id=None):
        self._definitions = {d["id"]: d for d in snapshot["definitions"]}
        self._profiles = {p["id"]: p for p in snapshot["profiles"]}
        active = {d["id"] for d in snapshot["devices"]}
        self._selected_ids.intersection_update(self._definitions)
        self.device_list.clear()
        for row in sorted(self._definitions.values(), key=lambda d: d["name"].casefold()):
            device_id = row["id"]
            custom = row["kind"] == "custom"
            profile = self._profiles.get(row["profileId"], {})
            axes = row["axes"] if custom else len(profile.get("axes", []))
            buttons = row["buttons"] if custom else profile.get("addressableButtons", 32)
            hats = row["hats"] if custom else profile.get("hatCount", 1)
            checkbox = ui_common.QDataCheckbox(data=device_id, checked=device_id in self._selected_ids, callbackEx=self._selection_changed)
            label = ui_common.QDataLabel(
                f"{row['name']}  [{device_id}] — {axes} axes, {buttons} buttons, {hats} hats — {'Active' if device_id in active else 'Inactive'}"
            )
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            edit = ui_common.QDataPushButton("Edit", data=device_id, callback=self._edit_clicked)
            self.device_list.addWidget(ui_common.getHContainer([checkbox, (label, 1), edit], right_stretch=False, widget_only=True))
        if not self._definitions:
            self.device_list.addWidget(ui_common.QDataLabel("No saved devices on this host. Use New Device to create one."))
        with QtCore.QSignalBlocker(self.profile_widget):
            self.profile_widget.clear()
            self.profile_widget.addItem("Custom joystick", "")
            for profile in sorted(self._profiles.values(), key=lambda p: p["name"].casefold()):
                if profile["deployable"] and profile["type"].lower() not in ("keyboard", "mouse"):
                    self.profile_widget.addItem(profile["name"], profile["id"])
        if select_id in self._definitions:
            self._edit_device(select_id)
        elif self._previous and self._previous["id"] in self._definitions:
            self._edit_device(self._previous["id"])
        else:
            self._new_device()

    def _selection_changed(self, widget, checked):
        if checked:
            self._selected_ids.add(widget.data)
        else:
            self._selected_ids.discard(widget.data)
        if self._previous and self._previous["id"] == widget.data:
            self.include_widget.setChecked(checked)

    def _edit_clicked(self, widget):
        self._edit_device(widget.data)

    def _edit_device(self, device_id):
        self._previous = dict(self._definitions[device_id])
        row = self._previous
        self.id_widget.setText(device_id)
        self.id_widget.setReadOnly(True)
        self.name_widget.setText(row["name"])
        profile_id = "" if row["kind"] == "custom" else row["profileId"]
        index = self.profile_widget.findData(profile_id)
        if index < 0:
            self.profile_widget.addItem(profile_id, profile_id)
            index = self.profile_widget.count() - 1
        self.profile_widget.setCurrentIndex(index)
        self.axes_widget.setValue(row["axes"])
        self.buttons_widget.setValue(row["buttons"])
        self.hats_widget.setValue(row["hats"])
        self.active_widget.setChecked(row["enabled"])
        self.include_widget.setChecked(device_id in self._selected_ids)
        self._profile_changed()

    def _new_device(self):
        self._previous = None
        index = next((i for i in range(GEX_MAX_DEVICES) if Maestro.klass._service_id(i) not in self._definitions), None)
        self.id_widget.setReadOnly(False)
        self.id_widget.setText(Maestro.klass._service_id(index) if index is not None else "")
        self.name_widget.setText(f"{GEX_PRODUCT_STRING} {index}" if index is not None else "")
        self.profile_widget.setCurrentIndex(0)
        for widget, value in ((self.axes_widget, 8), (self.buttons_widget, 128), (self.hats_widget, 4)):
            widget.setValue(value)
        self.active_widget.setChecked(True)
        self.include_widget.setChecked(True)
        self._profile_changed()

    def _profile_changed(self, *args):
        custom = not self.profile_widget.currentData()
        for widget in (self.axes_widget, self.buttons_widget, self.hats_widget):
            widget.setEnabled(custom)
        if not custom:
            profile = self._profiles.get(self.profile_widget.currentData(), {})
            self.axes_widget.setValue(len(profile.get("axes", [])))
            self.buttons_widget.setValue(profile.get("addressableButtons", 32))
            self.hats_widget.setValue(profile.get("hatCount", 1))

    def _save_device(self):
        device_id = self.id_widget.text().strip()
        profile_id = self.profile_widget.currentData() or "custom-" + device_id
        custom = not self.profile_widget.currentData()
        axes, buttons, hats = self.axes_widget.value(), self.buttons_widget.value(), self.hats_widget.value()
        name = self.name_widget.text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id) or not name:
            self.warning_widget.setText("Enter a device ID with letters, digits, underscores or hyphens, and a display name.")
            return
        if self._previous is None and device_id in self._definitions:
            self.warning_widget.setText("This device ID already exists. Select Edit for that device.")
            return
        if custom and (None in (axes, buttons, hats) or not 0 <= axes <= 8 or not 0 <= buttons <= 128 or not 0 <= hats <= 4 or axes + buttons + hats == 0):
            self.warning_widget.setText("A custom joystick requires at least one axis, button or hat.")
            return
        definition = dict(
            id=device_id,
            kind="custom" if custom else "profile",
            profileId=profile_id,
            name=name,
            axes=axes if custom else 0,
            buttons=buttons if custom else 0,
            hats=hats if custom else 0,
            enabled=self.active_widget.isChecked(),
        )
        previous = dict(self._previous) if self._previous else None
        include = self.include_widget.isChecked()
        if include and device_id not in self._selected_ids and len(self._selected_ids) >= GEX_MAX_DEVICES:
            self.warning_widget.setText(f"Gremlin supports at most {GEX_MAX_DEVICES} Maestro targets. Uncheck another device first.")
            return

        def operation():
            save_device_definition(self.maestro.ctx, definition, previous)
            return service_snapshot(self.maestro.ctx)

        def complete(snapshot):
            if include:
                self._selected_ids.add(device_id)
            else:
                self._selected_ids.discard(device_id)
            self._load_snapshot(snapshot, device_id)
            # A layout edit must not leave an existing target using stale
            # capabilities when this dialog closes.
            self._apply()

        self._submit(operation, complete, "Saving device options…")

    def _apply(self):
        if len(self._selected_ids) > GEX_MAX_DEVICES:
            self.warning_widget.setText(f"Select at most {GEX_MAX_DEVICES} Maestro targets.")
            return
        current_map = self.config.maestro_device_map or {}
        device_map = {key: value for key, value in current_map.items() if key in self._selected_ids}
        for device_id in sorted(self._selected_ids):
            if device_id not in device_map:
                preferred = Maestro.klass._service_index(device_id)
                slots = [preferred] if preferred is not None else []
                slots += list(range(GEX_MAX_DEVICES))
                device_map[device_id] = next(index for index in slots if index not in device_map.values())
        settings = self._tested_settings
        enabled = self.enabled_widget.isChecked()

        def operation():
            # A previous Apply may have disabled/closed the output transport.
            self.maestro.connect(*settings)
            if enabled:
                self.maestro.LoadActiveControllers(device_map)
                self.maestro.populateDeviceList()
            else:
                # Keep the management connection usable while output is off.
                # Host device activation and Gremlin output are independent.
                self.maestro._stopping.set()
                with self.maestro._lock:
                    for controller in self.maestro._controller_map.values():
                        self.maestro.ctx.request("/maestro_reset", controller.Id, timeout=0.3, attempts=1)
                    self.maestro._controller_map.clear()
                    self.maestro._device_map.clear()
                    self.maestro._buffer_map.clear()
                from gremlin import joystick_handling

                joystick_handling.set_maestro_devices([])
            return service_snapshot(self.maestro.ctx) if self.maestro.ctx is not None else None

        def complete(snapshot):
            (self.config.maestro_osc_host, self.config.maestro_osc_port, self.config.maestro_osc_reply_host, self.config.maestro_osc_reply_port) = settings
            self.config.maestro_device_map = device_map
            self.config.maestro_device_count = len(device_map)
            self.config.maestro_enabled = enabled
            self.config.save()
            if snapshot is not None:
                self._load_snapshot(snapshot)
            else:
                self._tested_settings = None
            self.devices_changed.emit()
            self.status_widget.setText(f"Maestro settings saved. {len(self.maestro._controller_map)} active target(s) available in Gremlin.")

        self._submit(operation, complete, "Updating the Maestro target list…")

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if not self._busy:
            super().reject()
