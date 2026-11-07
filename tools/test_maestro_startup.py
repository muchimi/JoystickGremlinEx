"""Hardware-free default Maestro device checks: python tools/test_maestro_startup.py."""

import ast
import inspect
import json
import logging
from pathlib import Path
import queue
import re
import socket
import struct
import sys
import threading
import time
from types import ModuleType, SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, call, patch

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken
from test_qt_marshalling import APP, flush_deletes


ROOT = Path(__file__).resolve().parents[1]
CONFIG = NS(maestro_enabled=False, maestro_device_count=4, maestro_device_map=None)
CONFIG.getWindowSize = CONFIG.getWindowLocation = lambda *args: None
CONFIG.setWindowSize = CONFIG.setWindowLocation = CONFIG.save = Mock()
GREMLIN = NS(config=NS(Configuration=lambda: CONFIG), util=NS(
    InvokeUiMethod=lambda callback, *args: callback(*args),
    valid_integer_string=lambda value: value.lstrip("-").isdigit(),
    clamp=lambda value, low, high: max(low, min(high, value)),
))


def load_definitions(path, names, namespace):
    nodes = [node for node in ast.parse((ROOT / path).read_bytes()).body if getattr(node, "name", None) in names]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), path, "exec"), namespace)


COMMON = dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, Qt=QtCore.Qt,
              QWidget=QtWidgets.QWidget, QSize=QtCore.QSize, QIcon=QtGui.QIcon,
              Callable=Callable, inspect=inspect, Shiboken=Shiboken,
              gremlin=GREMLIN, Buttons=NS(_default_parent=None),
              Color=lambda: NS(cssButton=lambda: ""), syslog=logging.getLogger("system"),
              get_text_width=lambda text: QtGui.QFontMetrics(APP.font()).horizontalAdvance(text))
load_definitions("gremlin/ui/ui_common.py", {
    "IntValidator", "QIntLineEdit", "QDataLabel", "QDataPushButton", "QRememberDialog",
    "getHContainer", "getVContainer",
}, COMMON)


class WarningLabel(QtWidgets.QLabel):
    def __init__(self, autohide=False):
        super().__init__()


NAMESPACE = dict(COMMON, SingletonDecorator=lambda cls: cls, Signal=lambda *args: Mock(),
                 threading=threading, GEX_MAX_DEVICES=16, QWarningWidget=WarningLabel,
                 MessageBoxWarning=Mock(), _GEX_ID_PATTERN=re.compile(r"gex-(?:gp-)?(\d+)"))
load_definitions("gremlin/maestro.py", {"is_valid_gex_id", "Maestro", "MaestroDefaultDevicesDialog"}, NAMESPACE)
Maestro = NAMESPACE["Maestro"]
Dialog = NAMESPACE["MaestroDefaultDevicesDialog"]


class DefaultDeviceChecks(unittest.TestCase):
    def setUp(self):
        CONFIG.maestro_enabled = False
        CONFIG.maestro_device_map = None
        CONFIG.maestro_device_count = 4
        CONFIG.save.reset_mock()
        self.maestro = Maestro()
        CONFIG.maestro_enabled = True
        self.maestro.ensureConnected = Mock(return_value=True)
        self.maestro.LoadActiveControllers = Mock()
        self.maestro.refreshDevices = Mock()
        self.maestro._client = Mock()
        self.maestro.client.list.return_value = []
        self.dialog = Mock(device_count=4)
        self.dialog.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted
        self.dialog_factory = patch.dict(NAMESPACE, MaestroDefaultDevicesDialog=Mock(return_value=self.dialog))
        self.dialog_factory.start()
        self.addCleanup(self.dialog_factory.stop)
        self.warning = NAMESPACE["MessageBoxWarning"]
        self.warning.reset_mock()
        logger = patch.dict(NAMESPACE, syslog=Mock())
        logger.start()
        self.addCleanup(logger.stop)

    def test_disabled_or_disconnected_does_not_prompt_or_create(self):
        CONFIG.maestro_enabled = False
        self.assertFalse(self.maestro.offerDefaultJoysticks())
        self.maestro.ensureConnected.assert_not_called()
        CONFIG.maestro_enabled = True
        self.maestro.ensureConnected.return_value = False
        self.assertFalse(self.maestro.offerDefaultJoysticks())
        NAMESPACE["MaestroDefaultDevicesDialog"].assert_not_called()

    def test_failed_inventory_does_not_treat_the_bridge_as_empty(self):
        self.maestro.client.list.side_effect = TimeoutError("No reply")
        self.assertFalse(self.maestro.offerDefaultJoysticks())
        NAMESPACE["MaestroDefaultDevicesDialog"].assert_not_called()
        self.assertFalse(self.maestro._default_devices_prompted)

    def test_connection_error_allows_profile_loading_without_a_prompt(self):
        self.maestro.ensureConnected.side_effect = OSError("Reply port unavailable")
        self.assertFalse(self.maestro.offerDefaultJoysticks())
        NAMESPACE["MaestroDefaultDevicesDialog"].assert_not_called()

    def test_any_existing_default_active_or_saved_suppresses_prompt(self):
        for address in ("/maestro_devices", "/maestro_definitions"):
            for device_id in ("gex-1", "gex-2", "gex-3", "gex-4"):
                with self.subTest(address=address, device_id=device_id):
                    self.maestro.client.list.side_effect = lambda target: [{"id": device_id}] if target == address else []
                    self.assertFalse(self.maestro.offerDefaultJoysticks())
        NAMESPACE["MaestroDefaultDevicesDialog"].assert_not_called()

    def test_cancel_creates_nothing_and_does_not_prompt_again(self):
        self.dialog.exec.return_value = QtWidgets.QDialog.DialogCode.Rejected
        self.maestro.createDefaultJoysticks = Mock()
        self.assertFalse(self.maestro.offerDefaultJoysticks())
        self.assertFalse(self.maestro.offerDefaultJoysticks())
        NAMESPACE["MaestroDefaultDevicesDialog"].assert_called_once_with(parent=None)
        self.maestro.createDefaultJoysticks.assert_not_called()
        self.assertIsNone(CONFIG.maestro_device_map)

    def test_offer_uses_chosen_count_and_parent(self):
        self.dialog.device_count = 16
        self.maestro.createDefaultJoysticks = Mock()
        parent = Mock()
        self.assertTrue(self.maestro.offerDefaultJoysticks(parent))
        self.maestro.createDefaultJoysticks.assert_called_once_with(16)
        NAMESPACE["MaestroDefaultDevicesDialog"].assert_called_once_with(parent=parent)

    def create(self, **kwargs):
        controller = NS(id=kwargs["name"], index=kwargs["at_index"])
        self.maestro._controller_map[controller.index] = controller
        self.maestro._register_controller(controller)
        return controller

    def test_creation_range_layout_ids_and_publish(self):
        for count in (1, 4, 16):
            with self.subTest(count=count):
                self.maestro._controller_map.clear()
                CONFIG.maestro_device_map = None
                self.maestro.createJoystickController = Mock(side_effect=self.create)
                self.maestro.refreshDevices.reset_mock()
                self.assertEqual(self.maestro.createDefaultJoysticks(count), count)
                self.assertEqual(CONFIG.maestro_device_count, count)
                for index, call in enumerate(self.maestro.createJoystickController.call_args_list):
                    self.assertEqual(call.kwargs, dict(name=f"gex-{index+1}", axis_count=8,
                                                      button_count=128, hat_count=4, at_index=index))
                self.assertEqual(CONFIG.maestro_device_map, {f"gex-{i+1}": i for i in range(count)})
                self.maestro.refreshDevices.assert_called_once_with()

    def test_invalid_counts_do_not_create(self):
        self.maestro.createJoystickController = Mock()
        for count in (0, 17, -1, True, 2.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.maestro.createDefaultJoysticks(count)
        self.maestro.createJoystickController.assert_not_called()

    def test_default_layout_is_sent_to_the_bridge_in_protocol_order(self):
        reply = Mock(data={"id": "gex-1", "name": "gex-1"})
        reply.raise_for_error.return_value = reply
        self.maestro.client.request.return_value = reply
        CONFIG.maestro_device_map = {}
        with (patch.dict(NAMESPACE, GEX_VENDOR_ID=1, GEX_PRODUCT_ID=1),
              patch.object(self.maestro, "_cache_controller", return_value=NS(id="gex-1", index=0))):
            self.assertEqual(self.maestro.createDefaultJoysticks(1), 1)
        self.maestro.client.request.assert_called_once_with(
            "/maestro_create_custom", "gex-1", "gex-1", 128, 8, 4, 1, 1, True
        )

    def test_existing_gamepad_slots_and_saved_joysticks_are_preserved(self):
        self.maestro._controller_map[0] = NS(id="gex-gp-1", index=0)
        self.maestro.client.list.side_effect = lambda address: [{"id": "gex-5"}] if address == "/maestro_definitions" else []
        self.maestro.createJoystickController = Mock(side_effect=self.create)
        self.assertEqual(self.maestro.createDefaultJoysticks(5), 4)
        self.assertEqual(self.maestro._controller_map[0].id, "gex-gp-1")
        self.assertEqual(CONFIG.maestro_device_map["gex-gp-1"], 0)
        self.assertNotIn("gex-5", [call.kwargs["name"] for call in self.maestro.createJoystickController.call_args_list])

    def test_insufficient_slots_fails_before_creating_anything(self):
        CONFIG.maestro_device_map = {"custom": 0}
        self.maestro.createJoystickController = Mock()
        with self.assertRaisesRegex(RuntimeError, "15 Maestro slots"):
            self.maestro.createDefaultJoysticks(16)
        self.maestro.createJoystickController.assert_not_called()
        self.assertEqual(CONFIG.maestro_device_map, {"custom": 0})

    def test_partial_failure_publishes_created_devices_and_reports_error(self):
        self.maestro.createJoystickController = Mock(side_effect=lambda **kwargs: self.create(**kwargs) if kwargs["name"] == "gex-1" else None)
        self.assertFalse(self.maestro.offerDefaultJoysticks())
        self.assertEqual(CONFIG.maestro_device_map, {"gex-1": 0})
        self.maestro.refreshDevices.assert_called_once_with()
        self.warning.assert_called_once()

    def test_enabled_constructor_attaches_without_creating_devices(self):
        CONFIG.maestro_enabled = True
        CONFIG.maestro_osc_reply_host = "192.0.2.1"
        with (patch.object(Maestro, "connect"), patch.object(Maestro, "LoadActiveControllers"),
              patch.object(Maestro, "populateDeviceList"), patch.object(Maestro, "sync"),
              patch.object(Maestro, "createJoystickController") as create):
            Maestro()
        create.assert_not_called()


class ConnectionPortChecks(unittest.TestCase):
    def setUp(self):
        CONFIG.maestro_enabled = False
        CONFIG.maestro_osc_port = 8010
        self.maestro = Maestro()
        self.maestro._connect = Mock(return_value=None)
        self.maestro.scan = Mock(return_value=None)
        logger = patch.dict(NAMESPACE, syslog=Mock())
        logger.start()
        self.addCleanup(logger.stop)

    def test_omitted_port_is_resolved_before_connect_and_fallback_scan(self):
        CONFIG.maestro_osc_port = 9123
        self.assertIsNone(self.maestro.connect())
        self.maestro._connect.assert_called_once_with(None, 9123, None, None, False)
        self.maestro.scan.assert_called_once_with(network_str="0.0.0.0/0", port=9123)

    def test_explicit_port_is_retained_when_a_host_is_discovered(self):
        reply = object()
        self.maestro.scan.return_value = "192.0.2.10"
        self.maestro._connect.side_effect = [None, reply]
        self.assertIs(self.maestro.connect(port=9234), reply)
        self.assertEqual(self.maestro._connect.call_args_list, [
            call(None, 9234, None, None, False), call("192.0.2.10", 9234, None, None, False),
        ])
        self.maestro.scan.assert_called_once_with(network_str="0.0.0.0/0", port=9234)

    def test_successful_connection_does_not_scan(self):
        self.maestro._connect.return_value = object()
        self.assertIs(self.maestro.connect(), self.maestro._connect.return_value)
        self.maestro.scan.assert_not_called()

    def test_ping_uses_the_handshake_without_an_extra_raw_message(self):
        self.maestro._connect.return_value = object()
        self.maestro._initialized = True
        self.maestro._client = Mock()
        self.maestro._client.request.return_value = NS(args=("MaestroOscService", 1))
        self.assertTrue(self.maestro.ping())
        self.maestro._connect.assert_called_once_with(None, 8010, None, None, False)
        self.maestro._client._send.assert_not_called()
        self.maestro._client.request.assert_not_called()

    def test_ping_returns_false_when_connection_fails(self):
        self.maestro._client = Mock()
        self.assertFalse(self.maestro.ping())
        self.maestro._client._send.assert_not_called()

    def test_ping_wire_packets_have_nonnegative_int32_request_ids(self):
        transport_namespace = dict(NAMESPACE, json=json, queue=queue, struct=struct, time=time,
                                   _SINGLE_REPLIES={"/maestro_ping": "/maestro_pong"}, _LIST_REPLIES={})
        load_definitions("gremlin/maestro.py", {
            "_osc_string", "_encode_message", "MaestroServiceError", "MaestroResult", "MaestroOscClient",
        }, transport_namespace)
        client = transport_namespace["MaestroOscClient"].__new__(transport_namespace["MaestroOscClient"])
        client._pending_lock = threading.Lock()
        client._pending = {}
        client._request_id = 0x7FFFFFFF
        client.timeout, client.attempts = 0.01, 1
        packets = []

        def send(packet):
            packets.append(packet)
            self.assertEqual(packet[:-4], b"/maestro_ping\0\0\0,i\0\0")
            request_id = struct.unpack(">i", packet[-4:])[0]
            self.assertGreaterEqual(request_id, 0)
            client._pending[request_id].put(("/maestro_pong", [request_id, "MaestroOscService", 1]))

        client._send = send
        self.maestro._client = client
        self.maestro._shutdown_connected = True
        self.maestro._connection_settings = ("127.0.0.1", 8010, "127.0.0.1", 8011)
        CONFIG.maestro_osc_host = CONFIG.maestro_osc_reply_host = "127.0.0.1"
        CONFIG.maestro_osc_reply_port = 8011
        CONFIG.verbose_mode_maestro = False
        with (patch.dict(NAMESPACE, socket=socket),
              patch.object(self.maestro, "_connect", Maestro._connect.__get__(self.maestro, Maestro))):
            self.assertTrue(self.maestro.ping())
            self.assertTrue(self.maestro.ping())
        self.assertEqual([struct.unpack(">i", packet[-4:])[0] for packet in packets], [0, 1])
        self.assertEqual(client._pending, {})
        self.maestro.scan.assert_not_called()

    def test_missing_or_invalid_configured_port_does_not_start_discovery(self):
        for port in (None, 0, 65536, "8010", True):
            CONFIG.maestro_osc_port = port
            self.assertIsNone(self.maestro.connect())
        self.maestro._connect.assert_not_called()
        self.maestro.scan.assert_not_called()
        with self.assertRaisesRegex(ValueError, "Maestro port"):
            self.maestro.connect(port=0, throw_on_error=True)

    def test_failed_candidates_do_not_recursively_scan(self):
        network = ModuleType("gremlin.network")
        network.scan_local_network = Mock(return_value=["192.0.2.10", "192.0.2.11"])
        package = ModuleType("gremlin")
        package.network = network
        with patch.dict(sys.modules, {"gremlin": package, "gremlin.network": network}):
            self.assertIsNone(Maestro.scan(self.maestro, "192.0.2.0/24", 8010))
        self.maestro.scan.assert_not_called()
        self.assertEqual(self.maestro._connect.call_args_list, [
            call(host="192.0.2.10", port=8010), call(host="192.0.2.11", port=8010),
        ])

    def test_disconnect_clears_the_backing_client(self):
        client = Mock()
        self.maestro._client = client
        self.maestro._handle_shutdown()
        client.close.assert_called_once_with()
        self.assertIsNone(self.maestro.client)


class DefaultDialogChecks(unittest.TestCase):
    def setUp(self):
        self.dialog = Dialog()
        self.addCleanup(self.cleanup_dialog)

    def cleanup_dialog(self):
        self.dialog.close()
        self.dialog.deleteLater()
        flush_deletes()

    def test_default_four_and_explicit_range_validation(self):
        self.assertEqual(self.dialog.device_count, 4)
        for value in ("", "0", "17", "-1"):
            self.dialog.count_widget.setText(value)
            self.dialog.create_button.click()
            self.assertNotEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertTrue(self.dialog.warning_widget.text())
        self.dialog.count_widget.setText("16")
        self.dialog.create_button.click()
        self.assertEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_not_now_rejects(self):
        self.dialog.cancel_button.click()
        self.assertEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)

    def test_startup_dialog_does_not_quit_the_application(self):
        self.assertFalse(self.dialog.testAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose))


class ProfileOrderingChecks(unittest.TestCase):
    def test_offer_precedes_profile_worker_and_startup_enumeration(self):
        tree = ast.parse((ROOT / "gremlinEx.py").read_bytes())
        ui = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GremlinUi")
        load = next(node for node in ui.body if isinstance(node, ast.FunctionDef) and node.name == "_do_load_profile_ui")
        calls = list(ast.walk(load))
        offer = next(node for node in calls if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "offerDefaultJoysticks")
        submit = next(node for node in calls if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "submit")
        self.assertLess(offer.lineno, submit.lineno)
        main = next(node for node in tree.body if isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare) and "__main__" in ast.unparse(node.test))
        main_calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)]
        offer = next(node for node in main_calls if isinstance(node.func, ast.Attribute) and node.func.attr == "offerDefaultJoysticks")
        enumerate_devices = next(node for node in main_calls if isinstance(node.func, ast.Attribute) and node.func.attr == "joystick_devices_initialization")
        build_ui = next(node for node in main_calls if isinstance(node.func, ast.Name) and node.func.id == "GremlinUi")
        self.assertLess(offer.lineno, enumerate_devices.lineno)
        self.assertLess(offer.lineno, build_ui.lineno)


if __name__ == "__main__":
    unittest.main(verbosity=2)
