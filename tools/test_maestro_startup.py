# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
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
from unittest.mock import MagicMock, Mock, call, patch

from PySide6 import QtCore, QtGui, QtWidgets
from lxml import etree
from shiboken6 import Shiboken
from test_qt_marshalling import APP, flush_deletes
from test_device_change_suppression import listener_fixture


ROOT = Path(__file__).resolve().parents[1]
CONFIG = NS(maestro_enabled=False, maestro_device_count=4, maestro_device_map=None)
CONFIG.getWindowSize = CONFIG.getWindowLocation = lambda *args: None
CONFIG.setWindowSize = CONFIG.setWindowLocation = CONFIG.save = Mock()
GREMLIN = NS(config=NS(Configuration=lambda: CONFIG), util=NS(
    InvokeUiMethod=lambda callback, *args: callback(*args),
    valid_integer_string=lambda value: value.lstrip("-").isdigit(),
    clamp=lambda value, low, high: max(low, min(high, value)),
))
DEVICE_LISTENER = listener_fixture()
GREMLIN.event_handler = NS(EventListener=lambda: DEVICE_LISTENER)


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
    "IntValidator", "QIntLineEdit", "QDataLabel", "QDataPushButton", "QRememberDialog", "QScrollableWidget",
    "getHContainer", "getVContainer",
}, COMMON)


class WarningLabel(QtWidgets.QLabel):
    def __init__(self, autohide=False):
        super().__init__()


NAMESPACE = dict(COMMON, SingletonDecorator=lambda cls: cls, Signal=lambda *args: Mock(),
                 threading=threading, re=re, GEX_MAX_DEVICES=256, MAX_GAMEPADS=4,
                 GEX_VENDOR_ID=1, GEX_PRODUCT_ID=1, GEX_JOYSTICK_PID_BASE=0x4700, GEX_GAMEPAD_PID_BASE=0x4800,
                 QWarningWidget=WarningLabel,
                 MessageBoxWarning=Mock(), _GEX_ID_PATTERN=re.compile(r"gex-(?:gp-)?(\d+)"))
load_definitions("gremlin/maestro.py", {
    "is_valid_gex_id", "gex_product_id", "gex_device_sort_key", "MaestroResult", "Maestro",
    "MaestroDefaultDevicesDialog", "MaestroProfileDevicesDialog",
}, NAMESPACE)
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
        self.listener = listener_fixture()
        GREMLIN.event_handler = NS(EventListener=lambda: self.listener)
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

    def test_missing_profile_devices_reuse_definitions_and_fill_requested_slots(self):
        import gremlin

        CONFIG.maestro_device_map = {"gex-1": 0, "gex-5": 4}
        self.maestro._controller_map = {0: NS(id="gex-1", index=0)}
        self.maestro.client.list.side_effect = lambda address: (
            [{"id": "gex-1"}, {"id": "gex-5"}] if address == "/maestro_definitions" else [{"id": "gex-1"}]
        )
        self.maestro.createJoystickController = Mock(return_value=NS(index=7))
        tree = etree.ElementTree(etree.fromstring(b"""
            <profile>
                <settings><maestro-input id="4" enabled="True" /></settings>
                <vjoyremap device-type="Maestro" virtual-id="7" mode="VJoyButtonPress" />
                <vjoyremap device-type="Maestro" virtual-id="9" mode="VJoyDisableLocal" />
            </profile>
        """))
        dialog = Mock()
        dialog.exec.side_effect = [QtWidgets.QDialog.DialogCode.Rejected, QtWidgets.QDialog.DialogCode.Accepted]
        with patch.object(CONFIG, "vjoy_installed", True, create=True), \
             patch.object(gremlin, "profile", NS(parse_profile_xml=lambda *_: tree), create=True), \
             patch.dict(NAMESPACE, MaestroProfileDevicesDialog=Mock(return_value=dialog)):
            prompt = NAMESPACE["MaestroProfileDevicesDialog"]
            self.assertEqual(self.maestro.offerProfileDevices("profile.xml"), ())
            self.maestro.client.request.assert_not_called()
            self.maestro.createJoystickController.assert_not_called()
            self.assertEqual(self.maestro.offerProfileDevices("profile.xml"), (4, 7))
        self.assertEqual(prompt.call_args_list, [call(("gex-5", "gex-8"), parent=None)] * 2)
        self.assertEqual(dialog.deleteLater.call_count, 2)
        self.maestro.client.request.assert_called_once_with("/maestro_activate", "gex-5")
        self.maestro.createJoystickController.assert_called_once_with(name="gex-8", at_index=7, refresh=False)
        self.assertEqual(CONFIG.maestro_device_map, {"gex-1": 0, "gex-5": 4, "gex-8": 7})
        self.maestro.refreshDevices.assert_called_once_with()

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

    def test_successful_deletion_suppresses_offers_before_refresh_and_later_profile_loads(self):
        for delete_all in (False, True):
            with self.subTest(delete_all=delete_all), patch.dict(NAMESPACE, GEX_VENDOR_ID=1, GEX_PRODUCT_ID=1):
                self.maestro._default_devices_prompted = False
                self.maestro.client.request.return_value = Mock()
                self.maestro.refreshDevices.reset_mock()
                self.maestro.refreshDevices.side_effect = lambda: self.assertFalse(self.maestro.offerDefaultJoysticks())
                if delete_all:
                    self.maestro.client.list.return_value = [{"id": "gex-1"}]
                    self.maestro.deleteAll()
                else:
                    self.maestro.deleteDevice("gex-1")
                self.assertTrue(self.maestro._default_devices_prompted)
                self.maestro.refreshDevices.assert_called_once_with()
                self.assertFalse(self.maestro.offerDefaultJoysticks())
                self.assertFalse(self.maestro.offerDefaultJoysticks())
                NAMESPACE["MaestroDefaultDevicesDialog"].assert_not_called()

    def test_failed_deletion_does_not_suppress_the_initial_offer(self):
        for delete_all in (False, True):
            with self.subTest(delete_all=delete_all), patch.dict(NAMESPACE, GEX_VENDOR_ID=1, GEX_PRODUCT_ID=1):
                self.maestro._default_devices_prompted = False
                result = MagicMock(code="delete_failed", message="Device busy")
                result.__bool__.return_value = False
                self.maestro.client.request.return_value = result
                if delete_all:
                    self.maestro.client.list.return_value = [{"id": "gex-1"}]
                    self.maestro.deleteAll()
                else:
                    self.maestro.deleteDevice("gex-1")
                self.assertFalse(self.maestro._default_devices_prompted)
                self.maestro.refreshDevices.assert_not_called()

    def create(self, **kwargs):
        controller = NS(id=kwargs["name"], index=kwargs["at_index"])
        self.maestro._controller_map[controller.index] = controller
        self.maestro._register_controller(controller)
        return controller

    def test_creation_range_layout_ids_and_publish(self):
        for count in (1, 4, 16, 32, 256):
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

    def test_default_batch_defers_all_native_updates_until_completion(self):
        device = NS(vendor_id=1, product_id=1, button_count=128, name=b"gex")

        def create(**kwargs):
            self.assertGreater(self.listener._device_change_suppressed, 0)
            self.listener._dinput_device_change_handler(device, 1)
            self.assertIsNone(self.listener._device_update_timer)
            return self.create(**kwargs)

        self.maestro.createJoystickController = Mock(side_effect=create)
        self.assertEqual(self.maestro.createDefaultJoysticks(4), 4)
        self.assertEqual(self.listener._device_change_suppressed, 0)
        self.listener.reset_devices.assert_not_called()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once_with(force=False)

    def test_invalid_counts_do_not_create(self):
        self.maestro.createJoystickController = Mock()
        for count in (0, 257, -1, True, 2.5):
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
            "/maestro_create_custom", "gex-1", "gex-1", 128, 8, 4, 1, 0x4701, True
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
        with self.assertRaisesRegex(RuntimeError, "255 Maestro slots"):
            self.maestro.createDefaultJoysticks(256)
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
        CONFIG.maestro_configured = True
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
        for value in ("", "0", "257", "-1"):
            self.dialog.count_widget.setText(value)
            self.dialog.create_button.click()
            self.assertNotEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertTrue(self.dialog.warning_widget.text())
        self.dialog.count_widget.setText("256")
        self.dialog.create_button.click()
        self.assertEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_not_now_rejects(self):
        self.dialog.cancel_button.click()
        self.assertEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)

    def test_startup_dialog_does_not_quit_the_application(self):
        self.assertFalse(self.dialog.testAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose))


class ProfileDevicesDialogChecks(unittest.TestCase):
    def test_shared_dialog_lists_devices_and_supports_both_choices(self):
        dialog = NAMESPACE["MaestroProfileDevicesDialog"](("gex-5", "gex-8"))
        try:
            self.assertIsInstance(dialog, COMMON["QRememberDialog"])
            self.assertTrue(dialog.cancel_button.isDefault())
            device_list = dialog.findChild(COMMON["QScrollableWidget"])
            self.assertEqual(device_list.findChild(COMMON["QDataLabel"]).text(), "gex-5\ngex-8")
            dialog.cancel_button.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            dialog.create_button.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.deleteLater()
            flush_deletes()


class ProfileOrderingChecks(unittest.TestCase):
    def test_offer_precedes_profile_worker_and_startup_enumeration(self):
        tree = ast.parse((ROOT / "gremlinEx.py").read_bytes())
        ui = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GremlinUi")
        load = next(node for node in ui.body if isinstance(node, ast.FunctionDef) and node.name == "_do_load_profile_ui")
        calls = list(ast.walk(load))
        offer = next(node for node in calls if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "offerProfileDevices")
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
