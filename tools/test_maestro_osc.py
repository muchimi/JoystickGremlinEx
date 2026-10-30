"""Hardware-free Maestro OSC checks.

Run: python tools/test_maestro_osc.py
Set MAESTRO_TEST_EXE to a built MaestroOscService.exe to also run the C# mock
integration. That process uses private UDP ports and a temporary definitions file.
"""

import ast
import enum
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace as NS
import unittest
import uuid
from typing import Callable
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken
from test_qt_marshalling import APP, pump_until, flush_deletes


ROOT = Path(__file__).resolve().parents[1]
CONFIG = NS(maestro_enabled=True, maestro_device_count=0, maestro_device_map=None, maestro_osc_host="127.0.0.1",
            maestro_osc_port=8010, maestro_osc_reply_host="127.0.0.1", maestro_osc_reply_port=8011)
CONFIG.getWindowSize = CONFIG.getWindowLocation = lambda *args: None
CONFIG.setWindowSize = CONFIG.setWindowLocation = CONFIG.save = Mock()
CONFIG.dropdown_use_mouse_wheel = False
GREMLIN = ModuleType("gremlin")
GREMLIN.__path__ = [str(ROOT / "gremlin")]
GREMLIN.config = ModuleType("gremlin.config")
GREMLIN.config.Configuration = lambda: CONFIG
GREMLIN.event_handler = ModuleType("gremlin.event_handler")
GREMLIN.event_handler.EventListener = Mock(return_value=NS(shutdown=Mock()))
GREMLIN.event_handler.JoystickState = lambda: NS(outputIgnored=lambda guid: False)
GREMLIN.remote = ModuleType("gremlin.remote")
GREMLIN.joystick_handling = ModuleType("gremlin.joystick_handling")
GREMLIN.joystick_handling.set_maestro_devices = Mock()
GREMLIN.util = ModuleType("gremlin.util")
GREMLIN.util.InvokeUiMethod = lambda callback, *args: callback(*args)
GREMLIN.util.valid_integer_string = lambda value: value.lstrip("-").isdigit()
GREMLIN.util.clamp = lambda value, low, high: max(low, min(high, value))
GREMLIN.types = ModuleType("gremlin.types")


def source_definitions(path, names, namespace):
    nodes = [n for n in ast.parse((ROOT / path).read_bytes()).body if getattr(n, "name", None) in names]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), path, "exec"), namespace)


type_namespace = dict(IntEnum=enum.IntEnum, enum=enum)
source_definitions("gremlin/types.py", {"DeviceType", "DeviceCategory"}, type_namespace)
GREMLIN.types.DeviceType, GREMLIN.types.DeviceCategory = type_namespace["DeviceType"], type_namespace["DeviceCategory"]


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


GREMLIN.util.clear_layout = clear_layout
GREMLIN.ui = ModuleType("gremlin.ui")
GREMLIN.ui.ui_common = ModuleType("gremlin.ui.ui_common")
common_namespace = GREMLIN.ui.ui_common.__dict__
common_namespace.update(dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, Qt=QtCore.Qt,
                             QWidget=QtWidgets.QWidget, QSize=QtCore.QSize, QIcon=QtGui.QIcon,
                             Callable=Callable, inspect=inspect, Shiboken=Shiboken, gremlin=GREMLIN,
                             syslog=logging.getLogger("system"), Buttons=NS(_default_parent=None),
                             Color=lambda: NS(cssButton=lambda: ""),
                             get_text_width=lambda text: QtGui.QFontMetrics(APP.font()).horizontalAdvance(text)))
source_definitions("gremlin/ui/ui_common.py", {
    "IntValidator", "QIntLineEdit", "QDataLabel", "QDataCheckbox", "QComboBox", "QDataComboBox",
    "QDataPushButton", "QDataLineEdit", "QDataIPLineEdit", "QRememberDialog", "QGroupBoxV",
    "QScrollableWidget", "getHContainer", "getVContainer",
}, common_namespace)


class WarningFixture(QtWidgets.QLabel):
    def __init__(self, autohide=False):
        super().__init__()
    def setText(self, value):
        super().setText(value)
        self.setVisible(bool(value))


GREMLIN.ui.ui_common.QWarningWidget = WarningFixture
DINPUT = ModuleType("dinput")


class TestGUID(uuid.UUID):
    def __init__(self, value):
        super().__init__(hex=value.hex if isinstance(value, uuid.UUID) else value)


DINPUT.GUID = TestGUID
for key, value in dict(GEX_ID_STRING="GEX", GEX_MAX_DEVICES=16, GEX_PID_BASE=0x1000,
                       GEX_PRODUCT_STRING="GEX Custom Device").items():
    setattr(DINPUT, key, value)
DINPUT.DILL = NS(getDevices=Mock(return_value=[]))
MODULES = {"gremlin": GREMLIN, "gremlin.config": GREMLIN.config,
           "gremlin.event_handler": GREMLIN.event_handler,
           "gremlin.joystick_handling": GREMLIN.joystick_handling, "dinput": DINPUT,
           "gremlin.util": GREMLIN.util, "gremlin.types": GREMLIN.types,
           "gremlin.ui": GREMLIN.ui, "gremlin.ui.ui_common": GREMLIN.ui.ui_common,
           "gremlin.remote": GREMLIN.remote}
with patch.dict(sys.modules, MODULES):
    device_namespace = dict(gremlin=GREMLIN, GUID=TestGUID, DeviceType=GREMLIN.types.DeviceType,
                            DeviceCategory=GREMLIN.types.DeviceCategory, DILL=DINPUT.DILL)
    source_definitions("dinput/__init__.py", {"DeviceSummary"}, device_namespace)
    DINPUT.DeviceSummary = device_namespace["DeviceSummary"]
SPEC = importlib.util.spec_from_file_location("maestro_osc_checks", ROOT / "gremlin/maestro.py")
MAESTRO = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {**MODULES, SPEC.name: MAESTRO}):
    SPEC.loader.exec_module(MAESTRO)
MODULES["gremlin.maestro"] = MAESTRO
GREMLIN.maestro = MAESTRO


def packet(address, *values):
    """Independent fixture encoder for service replies."""
    def string(value):
        result = value.encode() + b"\0"
        return result + b"\0" * (-len(result) % 4)
    tags, data = ",", b""
    for value in values:
        if isinstance(value, str):
            tags += "s"
            data += string(value)
        elif isinstance(value, int):
            tags += "i"
            data += struct.pack(">i", value)
        else:
            tags += "f"
            data += struct.pack(">f", value)
    return string(address) + string(tags) + data


class Endpoint:
    """Script replies from an ephemeral source port, as the C# service does."""

    def __init__(self, handler):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(("127.0.0.1", 0))
        self.rx.settimeout(0.05)
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client = MAESTRO.MaestroOscClient(port=self.rx.getsockname()[1], reply_port=0,
                                              timeout=0.08, attempts=3)
        self.reply_to = self.client._rx.getsockname()
        self.received = []
        self.handler = handler
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def send(self, address, *values):
        self.tx.sendto(packet(address, *values), self.reply_to)

    def run(self):
        while not self.stopped.is_set():
            try:
                data, source = self.rx.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            self.received.append((data, source))
            self.handler(self, *MAESTRO._decode_message(data))

    def close(self):
        self.stopped.set()
        self.worker.join(timeout=1)
        self.client.close()
        self.tx.close()
        self.rx.close()


class TransportTests(unittest.TestCase):
    def endpoint(self, handler):
        endpoint = Endpoint(handler)
        self.addCleanup(endpoint.close)
        return endpoint

    def test_osc_encoding_matches_wire_format(self):
        expected = b"/maestro_ping\0\0\0,i\0\0\x00\x00\x00\x2a"
        self.assertEqual(MAESTRO._encode_message("/maestro_ping", [42]), expected)
        self.assertEqual(MAESTRO._decode_message(packet("/maestro_axis/gex-0/X", 0.75)),
                         ("/maestro_axis/gex-0/X", [0.75]))

    def test_retry_keeps_request_id_packet_and_source_socket(self):
        def reply(endpoint, address, values):
            if len(endpoint.received) == 2:
                endpoint.send("/maestro_pong", values[0], "MaestroOscService", 1)
        endpoint = self.endpoint(reply)
        result = endpoint.client.request("/maestro_ping")
        self.assertEqual(result[1:], ["MaestroOscService", 1])
        self.assertEqual(endpoint.received[0], endpoint.received[1])

    def test_list_collects_rows_after_done_and_recovers_missing_row_on_retry(self):
        def reply(endpoint, address, values):
            request_id, offset, limit = values
            endpoint.send("/maestro_done", request_id, address, 2, offset, 2)
            endpoint.send("/maestro_device", request_id, 1, '{"id":"second"}')
            if len(endpoint.received) > 1:
                endpoint.send("/maestro_device", request_id, 0, '{"id":"first"}')
        endpoint = self.endpoint(reply)
        self.assertEqual(endpoint.client.list("/maestro_devices"), [{"id": "first"}, {"id": "second"}])
        self.assertEqual(endpoint.received[0], endpoint.received[1])

    def test_pagination_and_empty_list(self):
        def reply(endpoint, address, values):
            request_id, offset, limit = values
            count = min(100, 101 - offset) if address == "/maestro_devices" else 0
            endpoint.send("/maestro_done", request_id, address, 101 if count else 0, offset, count)
            for index in reversed(range(offset, offset + count)):
                endpoint.send("/maestro_device", request_id, index, json.dumps({"index": index}))
        endpoint = self.endpoint(reply)
        self.assertEqual(endpoint.client.list("/maestro_devices"), [{"index": i} for i in range(101)])
        self.assertEqual(endpoint.client.list("/maestro_definitions"), [])

    def test_service_errors_are_reported(self):
        endpoint = self.endpoint(lambda e, a, v: e.send("/maestro_error", v[0], a, "not_found", "Missing device"))
        with self.assertRaisesRegex(MAESTRO.MaestroServiceError, "not_found: Missing device"):
            endpoint.client.request("/maestro_state", "missing")

    def test_control_echo_does_not_satisfy_management_request(self):
        def reply(endpoint, address, values):
            endpoint.send("/maestro_button/gex-0/1", values[0])
            endpoint.send("/maestro_pong", values[0] - 1, "Wrong request", 1)
            endpoint.send("/maestro_pong", values[0], "MaestroOscService", 1)
        endpoint = self.endpoint(reply)
        self.assertEqual(endpoint.client.request("/maestro_ping")[1:], ["MaestroOscService", 1])

    def test_malformed_datagram_does_not_stop_listener(self):
        def reply(endpoint, address, values):
            endpoint.tx.sendto(b"bad OSC", endpoint.reply_to)
            endpoint.send("/maestro_pong", values[0], "MaestroOscService", 1)
        endpoint = self.endpoint(reply)
        with self.assertLogs("system", logging.WARNING):
            self.assertEqual(endpoint.client.request("/maestro_ping")[2], 1)

    def test_timeout_and_close_stop_receiver(self):
        endpoint = self.endpoint(lambda *args: None)
        with self.assertRaises(TimeoutError):
            endpoint.client.request("/maestro_ping", timeout=0.01, attempts=1)
        endpoint.client.close()
        self.assertFalse(endpoint.client._receiver.is_alive())
        with self.assertRaises(OSError):
            endpoint.client.write("/maestro_button/gex-0/1", 1)

    def test_reply_port_is_exclusive(self):
        endpoint = self.endpoint(lambda *args: None)
        with self.assertRaises(OSError):
            MAESTRO.MaestroOscClient(reply_port=endpoint.reply_to[1])


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.modules = patch.dict(sys.modules, MODULES)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(setattr, CONFIG, "maestro_enabled", True)
        CONFIG.maestro_enabled = False
        self.maestro = MAESTRO.Maestro.klass()
        CONFIG.maestro_enabled = True
        self.maestro._initialized = True
        self.maestro.ctx = Mock()
        self.maestro.ctx.destination = ("127.0.0.1", 8010)
        self.controller(0, 8, 128, 4)

    def controller(self, index, axes, buttons, hats):
        controller = MAESTRO.MaestroController(index, f"gex-{index}", f"GEX Custom Device {index}",
                                               axes, buttons, hats, NS(VendorId=0xFEED, ProductId=0x8010))
        self.maestro._controller_map[index] = controller
        self.maestro._buffer_map[index] = self.maestro._neutral_buffer(controller)
        return controller

    def test_axes_use_one_based_selectors_and_normalized_values(self):
        for axis in (1, 8):
            for value, expected in ((-1, 0.0), (0, 0.5), (1, 1.0), (2, 1.0)):
                self.maestro.setAxis(0, axis, value)
                self.maestro.ctx.write.assert_called_with(f"/maestro_axis/gex-0/{MAESTRO.AXIS_NAMES[axis - 1]}", expected)
                self.assertEqual(struct.unpack_from("<h", self.maestro.getBuffer(0), 16 + (axis - 1) * 2)[0],
                                 {-1: -32767, 0: 0, 1: 32767, 2: 32767}[value])
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.maestro.setAxis(0, 1, value)

    def test_buttons_1_and_128_and_all_hat_directions_are_independent(self):
        self.maestro.setButton(0, 1, True)
        self.maestro.setButton(0, 128, True)
        self.maestro.ctx.write.assert_called_with("/maestro_button/gex-0/128", 1)
        self.maestro.setButton(0, 1, False)
        buffer = self.maestro.getBuffer(0)
        self.assertEqual(buffer[0], 0)
        self.assertEqual(buffer[15], 128)
        for hat in range(1, 5):
            for position, value in MAESTRO.HAT_POSITIONS.items():
                self.maestro.setHat(0, hat, position)
                self.maestro.ctx.write.assert_called_with(f"/maestro_hat/gex-0/{hat}", value)
                self.assertEqual(buffer[31 + hat], value - 1 if value else 255)
        self.assertEqual(buffer[15], 128)

    def test_odd_button_count_uses_byte_padding(self):
        self.controller(1, 1, 9, 1)
        self.maestro.setButton(1, 9, True)
        self.maestro.setAxis(1, 1, -1)
        self.maestro.setHat(1, 1, (0, 1))
        self.assertEqual(self.maestro.getBuffer(1), bytearray([0, 1, 1, 128, 0]))

    def test_invalid_indices_and_unknown_devices_do_not_send(self):
        for method, index, value in ((self.maestro.setAxis, 0, 0), (self.maestro.setAxis, 9, 0),
                                     (self.maestro.setButton, 0, True), (self.maestro.setButton, 129, True),
                                     (self.maestro.setHat, 0, (0, 0)), (self.maestro.setHat, 5, (0, 0))):
            with self.assertRaises(ValueError):
                method(0, index, value)
            method(15, index, value)
        self.maestro.ctx.write.assert_not_called()

    def test_device_matching_disambiguates_shared_pid_and_rejects_duplicates(self):
        self.controller(1, 8, 128, 4)
        devices = [NS(name=f"GEX Custom Device {i}", vendor_id=0xFEED, product_id=0x8010,
                      axis_count=8, button_count=128, hat_count=4) for i in (0, 1)]
        with patch.object(DINPUT.DILL, "getDevices", return_value=list(reversed(devices))):
            self.maestro.syncControllers()
            self.assertIs(self.maestro.getDevice(0x1001), devices[1])
        with patch.object(DINPUT.DILL, "getDevices", return_value=[devices[0], devices[0]]):
            self.maestro.syncControllers()
            self.assertIsNone(self.maestro.getDevice(0x1000))

    def test_shutdown_resets_owned_controllers_and_closes_transport(self):
        context = self.maestro.ctx
        self.maestro._handle_shutdown()
        context.request.assert_called_once_with("/maestro_reset", "gex-0", timeout=0.3, attempts=1)
        context.close.assert_called_once()
        self.assertFalse(self.maestro.initialized)
        self.maestro.setButton(0, 1, True)
        context.write.assert_not_called()

    def test_vjoy_style_output_api_uses_osc_and_retains_state(self):
        output = MAESTRO.MaestroOutputDevice(0, self.maestro)
        output.axis(8).value = 0.5
        self.maestro.ctx.write.assert_called_with("/maestro_axis/gex-0/Dial", 0.75)
        self.assertAlmostEqual(output.axis(linear_index=8).value, 0.5, places=4)
        output.button(128).is_pressed = True
        self.assertTrue(output.button(128).is_pressed)
        self.maestro.ctx.write.assert_called_with("/maestro_button/gex-0/128", 1)
        output.hat(4).direction = (-1, 1)
        self.assertEqual(output.hat(4).direction, (-1, 1))
        self.maestro.ctx.write.assert_called_with("/maestro_hat/gex-0/4", 8)
        self.assertTrue(output.is_axis_valid(linear_index=8))
        self.assertFalse(output.is_button_valid(129))
        with self.assertRaises(ValueError):
            output.hat(0)

    def test_device_summary_publishes_modified_options_with_stable_identity(self):
        self.maestro.populateDeviceList()
        summary = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
        self.assertIsInstance(summary, DINPUT.DeviceSummary)
        self.assertEqual(summary.device_type, GREMLIN.types.DeviceType.Maestro)
        self.assertTrue(summary.is_virtual)
        self.assertTrue(summary.connected)
        self.assertEqual((summary.virtual_id, summary.axis_count, summary.button_count, summary.hat_count), (0, 8, 128, 4))
        guid = summary.device_guid
        self.controller(0, 2, 9, 1).Name = "Changed layout"
        self.maestro.populateDeviceList()
        updated = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
        self.assertEqual(updated.device_guid, guid)
        self.assertEqual((updated.name, updated.axis_count, updated.button_count, updated.hat_count), ("Changed layout", 2, 9, 1))

    def test_joystick_read_helpers_read_maestro_without_touching_vjoy_or_dinput(self):
        self.maestro.populateDeviceList()
        summary = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
        # Even an accidentally assigned vJoy ID must not change this backend.
        summary.vjoy_id = 1
        namespace = dict(DeviceType=GREMLIN.types.DeviceType, dinput=DINPUT, gremlin=GREMLIN,
                         get_device=lambda guid: summary if guid == summary.device_guid else None,
                         VJoyProxy=Mock(side_effect=AssertionError("Wrong vJoy backend")),
                         syslog=logging.getLogger("system"))
        source_definitions("gremlin/joystick_handling.py", {"get_axis", "get_button", "get_hat"}, namespace)
        with patch.object(GREMLIN.util, "scale_to_range", lambda value, **kwargs: value / 32767, create=True):
            self.maestro.setAxis(0, 8, -0.75)
            self.maestro.setButton(0, 128, True)
            self.maestro.setHat(0, 4, (-1, 1))
            self.assertAlmostEqual(namespace["get_axis"](summary.device_guid, 8), -0.75, places=4)
            self.assertEqual(namespace["get_axis"](summary.device_guid, 8, normalized=False), -24575)
            self.assertTrue(namespace["get_button"](summary.device_guid, 128))
            self.assertEqual(namespace["get_hat"](summary.device_guid, 4), 31500)
            self.maestro.setButton(0, 128, False)
            self.maestro.setHat(0, 4, (0, 0))
            self.assertFalse(namespace["get_button"](summary.device_guid, 128))
            self.assertEqual(namespace["get_hat"](summary.device_guid, 4), -1)

    def test_joystick_write_helpers_use_the_maestro_output_api(self):
        self.maestro.populateDeviceList()
        summary = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
        namespace = dict(DeviceType=GREMLIN.types.DeviceType, dinput=DINPUT, gremlin=GREMLIN,
                         getDevice=lambda guid: summary, syslog=logging.getLogger("system"))
        source_definitions("gremlin/joystick_handling.py", {"set_axis", "set_button", "set_hat"}, namespace)
        with patch.object(MAESTRO.Maestro, "instance", self.maestro):
            namespace["set_axis"](summary.device_guid, 8, 0.5)
            self.maestro.ctx.write.assert_called_with("/maestro_axis/gex-0/Dial", 0.75)
            namespace["set_button"](summary.device_guid, 128, True)
            self.maestro.ctx.write.assert_called_with("/maestro_button/gex-0/128", 1)
            namespace["set_hat"](summary.device_guid, 4, (-1, 1))
            self.maestro.ctx.write.assert_called_with("/maestro_hat/gex-0/4", 8)

    def test_native_device_axis_callbacks_translate_assigned_axis_ids(self):
        self.controller(0, 2, 9, 1)
        native = DINPUT.DeviceSummary()
        native.name, native.vendor_id, native.product_id = "GEX Custom Device 0", 0xFEED, 0x8010
        native.axis_count, native.button_count, native.hat_count = 2, 9, 1
        native.device_guid = TestGUID(uuid.uuid4())
        native.axis_id_map = {1: 1, 6: 2}
        native.linear_id_map = {1: 1, 2: 6}
        with patch.object(DINPUT.DILL, "getDevices", return_value=[native]):
            self.maestro.populateDeviceList()
        self.maestro.setAxis(0, 2, 1)
        self.assertEqual(native.get_axis(6), 32767)

    def test_remote_host_does_not_claim_a_matching_local_device(self):
        self.maestro._local_service = False
        self.maestro.ctx.destination = ("192.0.2.1", 8010)
        with patch.object(DINPUT.DILL, "getDevices", side_effect=AssertionError("Remote host queried local hardware")):
            self.maestro.populateDeviceList()
        self.assertEqual(self.maestro._device_map, {})
        self.assertFalse(self.maestro._compare_list())
        summary = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
        self.assertEqual(summary.data["maestro_service_id"], "gex-0")

    def test_create_uses_first_free_index_and_does_not_require_admin(self):
        self.controller(2, 8, 128, 4)
        info = dict(id="gex-1", name="GEX Custom Device 1")
        self.maestro.ctx.request.return_value = [123, json.dumps(info)]
        with patch.object(self.maestro, "_cache_controller", return_value="controller"):
            self.assertEqual(self.maestro.createJoystickController(), "controller")
        self.maestro.ctx.request.assert_called_once_with("/maestro_create_custom", "gex-1", "GEX Custom Device 1", 128, 8, 4)

    def test_disabled_startup_does_not_open_sockets(self):
        CONFIG.maestro_enabled = False
        with patch.object(MAESTRO, "MaestroOscClient") as client:
            maestro = MAESTRO.Maestro.klass()
            self.assertFalse(maestro.initialized)
            client.assert_not_called()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.modules = patch.dict(sys.modules, MODULES)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.registry = dict(DeviceType=GREMLIN.types.DeviceType, threading=threading,
                             _device_registry_lock=threading.RLock())
        for key in ("_all_devices_map", "_joystick_device_guid_map", "_maestro_service_devices", "_maestro_replaced_devices",
                    "_maestro_devices_map", "_vjoy_devices_map", "_all_vjoy_devices_map", "_disconnected_devices_map",
                    "_all_virtual_devices_map"):
            self.registry[key] = {}
        source_definitions("gremlin/joystick_handling.py", {
            "set_maestro_devices", "_apply_maestro_service_devices", "_update_joystick_device_maps", "_update_virtual_map",
            "maestro_device_map", "all_maestro_devices", "virtual_devices", "vjoy_devices", "maestro_devices",
        }, self.registry)

    def summary(self, device_id, name="Maestro target", kind=None):
        device = DINPUT.DeviceSummary()
        device.device_guid = TestGUID(uuid.uuid5(uuid.NAMESPACE_URL, device_id))
        device.name = name
        device.virtual_id = 0
        device.axis_count, device.button_count, device.hat_count = 8, 128, 4
        device.device_type = kind or GREMLIN.types.DeviceType.Maestro
        device.setVirtual(True)
        device.setConnected(True)
        return device

    def test_registration_updates_virtual_targets_and_removes_stale_devices(self):
        first = self.summary("first")
        self.registry["set_maestro_devices"]([first])
        self.assertEqual(self.registry["maestro_device_map"](), {0: first})
        self.assertEqual(self.registry["virtual_devices"](), [first])
        updated = self.summary("first", "New name")
        updated.button_count = 9
        self.registry["set_maestro_devices"]([updated])
        self.assertEqual(self.registry["all_maestro_devices"](), [updated])
        self.assertEqual(self.registry["maestro_device_map"]()[0].button_count, 9)
        self.registry["set_maestro_devices"]([])
        self.assertEqual(self.registry["virtual_devices"](), [])
        self.assertNotIn(first.device_guid, self.registry["_all_devices_map"])

    def test_metadata_survives_native_enumeration_and_restores_original_on_removal(self):
        native = self.summary("native", "Native label", GREMLIN.types.DeviceType.Joystick)
        overlay = self.summary("native", "Service name")
        self.registry["_all_devices_map"][native.device_guid] = native
        self.registry["set_maestro_devices"]([overlay])
        self.assertIs(self.registry["_all_devices_map"][native.device_guid], overlay)
        # A fresh native enumeration replaces the raw registry entries.
        refreshed_native = self.summary("native", "New native instance", GREMLIN.types.DeviceType.Joystick)
        self.registry["_all_devices_map"] = {native.device_guid: refreshed_native}
        self.registry["_update_joystick_device_maps"]()
        self.assertIs(self.registry["maestro_device_map"]()[0], overlay)
        self.registry["set_maestro_devices"]([])
        self.assertIs(self.registry["_all_devices_map"][native.device_guid], refreshed_native)


class RemapRoutingTests(unittest.TestCase):
    setUp = OutputTests.setUp
    controller = OutputTests.controller

    def load_functor(self):
        names = {"_is_maestro_target", "_output_key", "_target_device", "_is_output_connected", "_output_device", "_send_flags",
                 "_set_axis", "_get_axis", "_register_button_release"}
        tree = ast.parse((ROOT / "action_plugins/map_to_vjoy/__init__.py").read_bytes())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VJoyRemapFunctor")
        cls.body = [n for n in cls.body if getattr(n, "name", None) in names]
        cls.bases = []
        namespace = dict(joystick_handling=GREMLIN.joystick_handling, DeviceType=GREMLIN.types.DeviceType,
                         syslog=logging.getLogger("system"), input_devices=NS(CallbackActions=Mock()))
        code = ast.Module(body=[cls], type_ignores=[])
        exec(compile(ast.fix_missing_locations(code), "remap-routing-checks", "exec"), namespace)
        functor = namespace["VJoyRemapFunctor"]()
        functor.action_data = NS(virtual_device=NS(device_type=GREMLIN.types.DeviceType.Maestro, device_guid="maestro", connected=True),
                                 sendFlags=Mock(return_value=(False, True)))
        functor.verbose = False
        functor.remote_client = Mock()
        functor.usage_data = NS(is_inverted=lambda *args: False)
        functor.client_list = []
        return functor, namespace

    def test_remap_routes_maestro_to_osc_and_preserves_vjoy_routing(self):
        functor, namespace = self.load_functor()
        with patch.object(MAESTRO.Maestro, "instance", self.maestro):
            functor._set_axis(0, 8, 0.5, send_flags=(False, True), force_remote=True)
            self.maestro.ctx.write.assert_called_with("/maestro_axis/gex-0/Dial", 0.75)
            self.assertAlmostEqual(functor._get_axis(0, 8), 0.5, places=4)
            functor._output_device(0).button(128).is_pressed = True
            functor._output_device(0).hat(4).direction = (0, -1)
        functor.remote_client.send_axis.assert_not_called()
        self.assertEqual(functor._send_flags(), (True, False))
        axis = NS(value=0)
        proxy = NS(axis=lambda index: axis)
        with patch.object(GREMLIN.joystick_handling, "VJoyProxy", return_value={0: proxy}, create=True):
            functor.action_data.virtual_device.device_type = GREMLIN.types.DeviceType.VJoy
            functor._set_axis(0, 8, -0.25, send_flags=(True, False))
            self.assertEqual(axis.value, -0.25)
        self.assertEqual(functor._send_flags(), (False, True))

    def test_maestro_auto_release_uses_the_same_output_backend(self):
        functor, namespace = self.load_functor()
        callbacks = namespace["input_devices"].CallbackActions.return_value
        with patch.object(MAESTRO.Maestro, "instance", self.maestro):
            functor._register_button_release((0, 128), "physical press", activate_on=False)
            callback, event = callbacks.register_callback.call_args.args
            self.assertEqual(event, "physical press")
            callback()
        self.maestro.ctx.write.assert_called_with("/maestro_button/gex-0/128", 0)
        callbacks.register_button_release.assert_not_called()


@unittest.skipUnless(os.environ.get("MAESTRO_TEST_EXE"), "Set MAESTRO_TEST_EXE for C# mock integration")
class CSharpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="gex-maestro-")
        sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        cls.port, cls.reply_port = [sock.getsockname()[1] for sock in sockets]
        for sock in sockets:
            sock.close()
        cls.log = open(Path(cls.temp.name) / "service.log", "w+")
        cls.process = subprocess.Popen([
            os.environ["MAESTRO_TEST_EXE"], "--mock", f"--Osc:ReceivePort={cls.port}",
            f"--Osc:SendPort={cls.reply_port}", f"--Osc:DefinitionsPath={cls.temp.name}/devices.json",
            "--Logging:EventLog:LogLevel:Default=None",
        ], cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        cls.addClassCleanup(cls.cleanup_service)
        with patch.dict(sys.modules, MODULES):
            client = MAESTRO.MaestroOscClient(port=cls.port, reply_port=cls.reply_port, timeout=0.2, attempts=1)
            try:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        client.request("/maestro_ping")
                        break
                    except OSError:
                        if cls.process.poll() is not None or time.monotonic() > deadline:
                            cls.log.seek(0)
                            raise RuntimeError(cls.log.read())
            finally:
                client.close()

    @classmethod
    def cleanup_service(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    def setUp(self):
        self.modules = patch.dict(sys.modules, MODULES)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.settings = patch.multiple(CONFIG, maestro_enabled=True, maestro_device_count=0,
                                       maestro_device_map=None,
                                       maestro_osc_port=self.port, maestro_osc_reply_port=self.reply_port)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.maestro = MAESTRO.Maestro.klass()
        self.assertTrue(self.maestro.initialized)
        self.addCleanup(self.cleanup_devices)

    def cleanup_devices(self):
        for info in self.maestro.ctx.list("/maestro_definitions"):
            self.maestro.ctx.request("/maestro_delete", info["id"])
        self.maestro._controller_map.clear()
        self.maestro._handle_shutdown()

    def state(self, device_id="gex-0"):
        return json.loads(self.maestro.ctx.request("/maestro_state", device_id)[-1])

    def test_full_controller_lifecycle_against_csharp(self):
        controller = self.maestro.createJoystickController(at_index=0)
        self.assertIsNotNone(controller)
        self.assertEqual(len(self.maestro.getBuffer(0)), 36)
        self.maestro.setAxis(0, 1, -1)
        self.maestro.setAxis(0, 8, 1)
        self.maestro.setButton(0, 128, True)
        for hat, position in enumerate(((0, 1), (1, 0), (0, -1), (-1, 1)), 1):
            self.maestro.setHat(0, hat, position)
        state = self.state()
        self.assertEqual(state["axes"]["X"], 0)
        self.assertEqual(state["axes"]["Dial"], 1)
        self.assertEqual(state["pressedButtons"], [128])
        self.assertEqual(state["hats"], [1, 3, 5, 8])
        self.maestro.LoadActiveControllers()
        self.assertEqual(self.maestro.getBuffer(0)[15], 128)
        self.assertEqual(self.maestro.getBuffer(0)[32:], bytearray([0, 2, 4, 7]))
        self.maestro.ctx.request("/maestro_create_custom", "other-client", "Other client", 1, 1, 0)
        self.maestro.removeAllControllers()
        self.assertEqual([d["id"] for d in self.maestro.getAllDevices()], ["other-client"])
        self.assertEqual(len(self.maestro.ctx.list("/maestro_definitions")), 2)
        self.assertIsNotNone(self.maestro.createJoystickController(at_index=0))
        self.assertEqual(self.state()["pressedButtons"], [])
        self.assertEqual(self.state()["hats"], [0, 0, 0, 0])
        with self.assertRaises(MAESTRO.MaestroServiceError):
            self.maestro.ctx.request("/maestro_state", "missing")

    def test_odd_layout_and_shutdown_reset_against_csharp(self):
        self.assertIsNotNone(self.maestro.createJoystickController(axis_count=1, button_count=9, hat_count=1))
        self.maestro.setButton(0, 9, True)
        self.maestro.setAxis(0, 1, 0.5)
        self.maestro.setHat(0, 1, (-1, -1))
        state = self.state()
        self.assertEqual(state["pressedButtons"], [9])
        self.assertEqual(state["axes"]["X"], 0.75)
        self.assertEqual(state["hats"], [6])
        self.maestro._handle_shutdown()
        self.maestro = MAESTRO.Maestro.klass()
        self.assertEqual(self.state()["pressedButtons"], [])
        self.assertEqual(self.state()["axes"]["X"], 0.5)
        self.assertEqual(self.state()["hats"], [0])

    def test_definition_layout_failure_restores_existing_controller(self):
        self.maestro.createJoystickController(axis_count=2, button_count=9, hat_count=1)
        previous = self.maestro.ctx.list("/maestro_definitions")[0]
        with self.assertRaisesRegex(RuntimeError, "previous device definition was restored"):
            MAESTRO.save_device_definition(self.maestro.ctx, previous | dict(axes=9), previous)
        self.assertEqual(self.maestro.ctx.list("/maestro_definitions"), [previous])
        renamed = previous | dict(name="Updated layout", axes=3, buttons=128, hats=4)
        MAESTRO.save_device_definition(self.maestro.ctx, renamed, previous)
        self.maestro.LoadActiveControllers()
        self.maestro.populateDeviceList()
        summary = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
        self.assertEqual((summary.name, summary.axis_count, summary.button_count, summary.hat_count), ("Updated layout", 3, 128, 4))

    def test_catalog_profile_uses_its_axis_order_and_button_mask(self):
        self.maestro.ctx.request("/maestro_create", "catalog", "mock-gamepad", "Catalog pad")
        self.maestro.LoadActiveControllers({"catalog": 3})
        output = MAESTRO.MaestroOutputDevice(3, self.maestro)
        output.axis(3).value = 0.5
        output.button(32).is_pressed = True
        output.hat(1).direction = (1, 0)
        state = self.state("catalog")
        self.assertEqual(state["axes"]["Rx"], 0.75)
        self.assertEqual(state["buttons"], 1 << 31)
        self.assertEqual(state["hat"], 3)
        self.maestro.LoadActiveControllers({"catalog": 3})
        self.assertTrue(output.button(32).is_pressed)

    def test_dialog_creates_edits_and_populates_gremlin_targets(self):
        with patch.object(MAESTRO.Maestro, "instance", self.maestro):
            dialog = MAESTRO.MaestroDialog()
            self.addCleanup(dialog.deleteLater)
            self.assertIsInstance(dialog, GREMLIN.ui.ui_common.QRememberDialog)
            self.assertIsInstance(dialog.port_widget, GREMLIN.ui.ui_common.QIntLineEdit)
            dialog.test_button.click()
            pump_until(lambda: not dialog._busy)
            self.assertIsNotNone(dialog._tested_settings, dialog.warning_widget.text())
            dialog.name_widget.setText("Dialog flight stick")
            dialog.axes_widget.setValue(3)
            dialog.buttons_widget.setValue(9)
            dialog.hats_widget.setValue(2)
            dialog.save_button.click()
            pump_until(lambda: not dialog._busy)
            self.assertIn("gex-0", dialog._definitions, dialog.warning_widget.text())
            dialog.apply_button.click()
            pump_until(lambda: not dialog._busy)
            self.assertFalse(dialog.warning_widget.text())
            summary = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
            self.assertEqual((summary.name, summary.axis_count, summary.button_count, summary.hat_count), ("Dialog flight stick", 3, 9, 2))
            self.assertEqual(CONFIG.maestro_device_map, {"gex-0": 0})
            dialog.name_widget.setText("Renamed stick")
            dialog.buttons_widget.setValue(128)
            dialog.save_button.click()
            pump_until(lambda: not dialog._busy)
            dialog.apply_button.click()
            pump_until(lambda: not dialog._busy)
            updated = GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0][0]
            self.assertEqual(updated.name, "Renamed stick")
            self.assertEqual(updated.button_count, 128)
            self.assertEqual(updated.device_guid, summary.device_guid)
            dialog.active_widget.setChecked(False)
            dialog.save_button.click()
            pump_until(lambda: not dialog._busy)
            dialog.apply_button.click()
            pump_until(lambda: not dialog._busy)
            self.assertEqual(GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0], [])
            self.assertFalse(dialog._definitions["gex-0"]["enabled"])
            dialog.active_widget.setChecked(True)
            dialog.save_button.click()
            pump_until(lambda: not dialog._busy)
            self.assertIn(0, self.maestro._controller_map)
            dialog.enabled_widget.setChecked(False)
            dialog.apply_button.click()
            pump_until(lambda: not dialog._busy)
            self.assertFalse(self.maestro.enabled)
            self.assertIsNotNone(self.maestro.ctx)
            self.assertEqual(GREMLIN.joystick_handling.set_maestro_devices.call_args.args[0], [])
            dialog.enabled_widget.setChecked(True)
            dialog.apply_button.click()
            pump_until(lambda: not dialog._busy)
            self.assertTrue(self.maestro.enabled)
            self.assertIn(0, self.maestro._controller_map)
            dialog.close()
            flush_deletes()


if __name__ == "__main__":
    unittest.main(verbosity=2)
