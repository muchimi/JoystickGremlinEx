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
"""Hardware-free device-list checks: python tools/test_maestro_dialog.py."""

from dataclasses import dataclass
import json
import re
import socket
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtTest, QtWidgets
from test_maestro_startup import COMMON, GREMLIN, NAMESPACE, Maestro as MaestroService, load_definitions
from test_qt_marshalling import APP, flush_deletes, pump_until
from test_device_change_suppression import listener_fixture


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


GREMLIN.util.clear_layout = clear_layout
GREMLIN.shared_state = NS(is_dark_theme=True)
UI = dict(COMMON)
load_definitions("gremlin/ui/ui_common.py", {"QDataCheckbox", "QScrollableWidget"}, UI)
UI["Buttons"] = NS(getDeleteWidget=lambda data, callback: UI["QDataPushButton"]("Delete", data=data, callback=callback))
UI.update(dataclass=dataclass, threading=threading, re=re, socket=socket, Slot=QtCore.Slot, GEX_MAX_DEVICES=256,
          AXIS_NAMES=("X", "Y", "Z", "Rx", "Ry", "Rz", "Slider", "Dial"),
          GEX_VENDOR_ID=1, GEX_PRODUCT_ID=1, GEX_JOYSTICK_PID_BASE=0x4700, GEX_GAMEPAD_PID_BASE=0x4800,
          MAX_GAMEPADS=4, WorkManager=lambda: NS(pushCursor=lambda: None, popCursor=lambda: None),
          _GEX_ID_PATTERN=re.compile(r"gex-(?:gp-)?(\d+)"),
          Maestro=NS(klass=NS(_service_index=MaestroService._service_index)))
load_definitions("gremlin/maestro.py", {
    "MaestroProfileInfo", "_MaestroDialogSignals", "MaestroDialog", "service_snapshot",
    "is_valid_gex_id", "gex_product_id", "gex_device_sort_key", "save_device_definition", "MaestroServiceError", "MaestroResult",
}, UI)


def joystick(device_id, enabled=True):
    return dict(id=device_id, name=device_id, kind="custom", profileId="custom-" + device_id,
                axes=8, buttons=128, hats=4, enabled=enabled)


class Bridge:
    """In-memory management responses; no sockets or HID devices."""

    def __init__(self, definitions):
        self.definitions = {row["id"]: dict(row) for row in definitions}
        self.profiles = {}
        self.destination = ("127.0.0.1", 8010)
        self.active_only = {}
        self.requests = []
        self.request_threads = []

    def list(self, address):
        if address == "/maestro_definitions":
            return list(self.definitions.values())
        if address == "/maestro_devices":
            return [dict(id=row["id"], name=row["name"]) for row in self.definitions.values() if row["enabled"]] + list(self.active_only.values())
        if address == "/maestro_profiles":
            return list(self.profiles.values())
        raise AssertionError(address)

    def request(self, address, *args, **kwargs):
        self.requests.append((address, args))
        self.request_threads.append(threading.get_ident())
        if address == "/maestro_create_custom":
            device_id, name, buttons, axes, hats, vendor_id, product_id = args
            self.definitions[device_id] = joystick(device_id) | dict(name=name, buttons=buttons, axes=axes, hats=hats, vendorId=vendor_id, productId=product_id)
        elif address == "/maestro_create_gamepad":
            device_id, name = args
            self.definitions[device_id] = dict(id=device_id, name=name, kind="gamepad",
                profileId="xbox-360-wireless", axes=6, buttons=16, hats=1, enabled=True)
        elif address == "/maestro_create":
            service_device_id, profile_id, display_name = args
            if service_device_id in self.definitions or service_device_id in self.active_only:
                raise AssertionError("Test creation must not reuse an existing service device ID")
            if not self.profiles[profile_id]["deployable"]:
                raise AssertionError("Test creation requires a deployable profile")
            self.definitions[service_device_id] = dict(
                id=service_device_id, name=display_name, kind="profile", profileId=profile_id, enabled=True)
        elif address == "/maestro_remove":
            self.definitions[args[0]]["enabled"] = False
        elif address == "/maestro_delete":
            self.definitions.pop(args[0], None)
            self.active_only.pop(args[0], None)
        elif address == "/maestro_delete_all":
            self.definitions.clear()
        else:
            raise AssertionError(address)
        return UI["MaestroResult"](True, address)


class MaestroFixture:
    createTestDevices = MaestroService.createTestDevices
    deleteDevice = MaestroService.deleteDevice
    deleteAll = MaestroService.deleteAll

    def __init__(self, bridge):
        self.client = bridge
        self._default_devices_prompted = False
        self._controller_map = {}
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._device_map, self._buffer_map = {}, {}
        self.missing_capabilities = set()
        self.capability_threads = []
        self.connect = Mock(return_value=True)
        self.ensureConnected = Mock(return_value=True)
        self.populateDeviceList = Mock()
        self.refreshDevices = Mock()
        self.syncBridge = Mock()

    def connected(self):
        return True

    def LoadActiveControllers(self, device_map):
        self._controller_map = {
            slot: NS(id=service_device_id, service_device_id=service_device_id)
            for service_device_id, slot in device_map.items()
        }

    def getCapabilities(self, device_id):
        self.capability_threads.append(threading.get_ident())
        if device_id in self.missing_capabilities:
            return None
        row = self.client.definitions.get(device_id) or self.client.active_only[device_id]
        if row["kind"] == "profile":
            data = dict(self.client.profiles[row["profileId"]], name=row["name"], kind="profile")
        else:
            data = dict(id=row["profileId"], name=row["name"], kind=row["kind"],
                        type="gamepad" if row["kind"] == "gamepad" else "joystick",
                        axes=list(UI["AXIS_NAMES"][:row["axes"]]), addressableButtons=row["buttons"], hatCount=row["hats"])
        return UI["MaestroProfileInfo"].from_dict(data, device_id)


class DialogHarness(UI["MaestroDialog"]):
    """Use the production actions, worker, completion and row widgets."""

    def __init__(self, definitions):
        UI["QRememberDialog"].__init__(self, "MaestroDialogChecks")
        self.config = NS(maestro_device_map={row["id"]: i for i, row in enumerate(definitions)},
                         maestro_device_count=len(definitions), maestro_enabled=True, maestro_use_localhost=True,
                         maestro_osc_host="127.0.0.1", maestro_osc_port=8010,
                         maestro_osc_reply_host="127.0.0.1", maestro_osc_reply_port=8011, save=Mock())
        self.maestro = MaestroFixture(Bridge(definitions))
        self.listener = listener_fixture()
        GREMLIN.event_handler = NS(EventListener=lambda: self.listener)
        GREMLIN.joystick_handling = NS(get_maestro_failover_devices=lambda: [
            NS(device_name=row["name"], data={
                "maestro_key": f"maestro://{self.maestro.client.destination[0]}:{self.maestro.client.destination[1]}/{row['id']}"
            }) for row in self.maestro.client.definitions.values()
            if row["enabled"] and re.fullmatch(r"gex-([1-9]|1[0-6])", row["id"])
        ])
        self.verbose = False
        self._busy = False
        self._completion = None
        self._tested_settings = ("127.0.0.1", 8010, "127.0.0.1", 8011)
        self._selected_service_device_ids = set(self.config.maestro_device_map)
        self._definitions_by_service_id, self._profiles_by_profile_id, self._selection_widgets_by_service_id = {}, {}, {}
        self._signals = UI["_MaestroDialogSignals"](self)
        self._signals.completed.connect(self._completed, QtCore.Qt.ConnectionType.QueuedConnection)
        self.warning_widget = QtWidgets.QLabel(self)
        self.status_widget = QtWidgets.QLabel(self)
        self.status_bar_maestro_widget = Mock()
        self.host_widget = QtWidgets.QLineEdit("127.0.0.1", self)
        self.reply_host_widget = QtWidgets.QLineEdit("127.0.0.1", self)
        self.port_widget = NS(value=lambda: 8010)
        self.reply_port_widget = NS(value=lambda: 8011)
        for name in ("connection_group", "devices_group", "host_container", "reply_host_container", "connected_widget", "close_button",
                     "select_all_button", "presets_widget", "apply_button"):
            setattr(self, name, QtWidgets.QPushButton(self))
        self.enabled_widget = QtWidgets.QCheckBox(self)
        self.enabled_widget.setChecked(True)
        self.device_list = UI["QScrollableWidget"](stretch=False, parent=self)
        self.test_devices_button = UI["QDataPushButton"](
            "Create Test Devices", parent=self, clicked=self._create_test_devices)
        self.new_button = UI["QDataPushButton"]("New Device", parent=self, clicked=self._create_new_joystick)
        self.delete_all_button = UI["QDataPushButton"](
            "Delete Selected", parent=self, clicked=self._handle_delete_selected_devices)
        self._load_snapshot(self.snapshot())

    def snapshot(self):
        return self._read_snapshot()

    def labels(self):
        layout = self.device_list.getLayout()
        labels = []
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, QtWidgets.QLabel):
                labels.append(widget.text())
            labels.extend(label.text() for label in widget.findChildren(QtWidgets.QLabel))
        return labels


class DeviceListChecks(unittest.TestCase):
    def setUp(self):
        service_ids = patch.dict(NAMESPACE, GEX_VENDOR_ID=1, GEX_PRODUCT_ID=1)
        service_ids.start()
        self.addCleanup(service_ids.stop)
        self.dialog = DialogHarness([joystick("gex-1")])
        self.addCleanup(self.cleanup_dialog)

    def cleanup_dialog(self):
        pump_until(lambda: not self.dialog._busy)
        self.dialog.close()
        self.dialog.deleteLater()
        flush_deletes()

    def create_device(self, device_id="gex-2", include=True, name=None):
        editor = Mock(include=include)
        editor.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted
        editor.definition.return_value = joystick(device_id)
        if name is not None:
            editor.definition.return_value["name"] = name
        with patch.dict(UI, MaestroNewDeviceDialog=Mock(return_value=editor)):
            self.dialog.new_button.click()
            pump_until(lambda: not self.dialog._busy)

    def delete_selected(self, confirmed=True):
        confirmation = Mock(side_effect=lambda **kwargs: kwargs["callback"](confirmed, None))
        with patch.dict(UI, MessageBoxYesNo=confirmation):
            self.dialog.delete_all_button.click()
            pump_until(lambda: not self.dialog._busy)
        confirmation.assert_called_once()

    def add_test_profiles(self):
        self.dialog.maestro.client.profiles = {
            profile_id: dict(id=profile_id, name=name, type=kind, deployable=True,
                             axes=axes, addressableButtons=buttons, hatCount=hats)
            for profile_id, name, kind, axes, buttons, hats in (
                ("logitech-wingman-formula-gp", "Logitech WingMan Formula GP", "wheel", ["X", "Y"], 6, 0),
                ("saitek-x52", "Saitek X52 Flight Control System", "hotas", ["X", "Y", "Z", "Rz"], 32, 2),
                ("thrustmaster-t16000m", "Thrustmaster T.16000M Joystick", "joystick", ["X", "Y", "Rz", "Slider"], 16, 1),
            )
        }

    def create_test_devices_from_dialog(self):
        reads, loads = [], []
        read_snapshot = self.dialog._read_snapshot
        load_snapshot = self.dialog._load_snapshot

        def read():
            reads.append(threading.get_ident())
            return read_snapshot()

        def load(snapshot):
            loads.append(threading.get_ident())
            return load_snapshot(snapshot)

        warning = Mock(side_effect=AssertionError("Worker must not open a Qt dialog"))
        with patch.object(self.dialog, "_read_snapshot", side_effect=read), patch.object(
            self.dialog, "_load_snapshot", side_effect=load
        ), patch.dict(UI, MessageBoxWarning=warning):
            self.dialog._create_test_devices()
            pump_until(lambda: not self.dialog._busy)
        warning.assert_not_called()
        self.assertEqual(len(reads), 1)
        self.assertNotEqual(reads[0], threading.get_ident())
        self.assertEqual(loads, [threading.get_ident()])

    def preset(self, count=8, kind="joystick"):
        self.dialog._handle_preset_selected("Test preset", dict(type=kind, count=count, axes=8, buttons=128, hats=4))
        pump_until(lambda: not self.dialog._busy)

    def test_preset_defers_native_changes_through_apply_and_refreshes_once(self):
        listener = self.dialog.listener
        bridge = self.dialog.maestro.client
        request = bridge.request
        applying, release = threading.Event(), threading.Event()
        device = NS(vendor_id=1, product_id=1, button_count=128, name=b"gex")

        def create(address, *args):
            self.assertGreater(listener._device_change_suppressed, 0)
            result = request(address, *args)
            listener._dinput_device_change_handler(device, 1)
            listener.reset_devices.assert_not_called()
            self.assertIsNone(listener._device_update_timer)
            return result

        load = self.dialog.maestro.LoadActiveControllers

        def apply(device_map):
            applying.set()
            if not release.wait(2):
                raise AssertionError("Apply was not released")
            load(device_map)

        bridge.request = create
        with patch.object(self.dialog.maestro, "LoadActiveControllers", side_effect=apply):
            try:
                self.dialog._handle_preset_selected("Four joysticks", dict(type="joystick", count=4))
                pump_until(applying.is_set)
                self.assertTrue(self.dialog._busy)
                self.assertGreater(listener._device_change_suppressed, 0)
                self.assertIsNone(listener._device_update_timer)
                listener.device_change_event.emit.assert_not_called()
            finally:
                release.set()
                pump_until(lambda: not self.dialog._busy)
        self.assertEqual(listener._device_change_suppressed, 0)
        self.assertEqual(len(self.dialog.config.maestro_device_map), 5)
        listener._device_update_timer.fire()
        listener.reset_devices.assert_called_once_with(force=False)
        listener.device_change_event.emit.assert_called_once_with()

    def test_failed_preset_resumes_previously_queued_native_changes(self):
        listener = self.dialog.listener
        device = NS(vendor_id=1, product_id=1, button_count=128, name=b"gex")
        listener._dinput_device_change_handler(device, 1)
        before = listener._device_update_timer
        self.dialog.maestro.ensureConnected.return_value = False
        self.preset(4)
        self.assertTrue(before.cancelled)
        self.assertEqual(listener._device_change_suppressed, 0)
        before.fire()
        listener.reset_devices.assert_not_called()
        listener._device_update_timer.fire()
        listener.reset_devices.assert_called_once_with(force=False)

    def test_completion_error_releases_device_change_suppression(self):
        listener = self.dialog.listener
        listener.pushDeviceChangeSuppression()
        self.dialog._completion = Mock(side_effect=RuntimeError("Completion failed")), listener
        with self.assertRaisesRegex(RuntimeError, "Completion failed"):
            self.dialog._completed(None, None)
        self.assertEqual(listener._device_change_suppressed, 0)

    def test_worker_start_error_releases_device_change_suppression(self):
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("Worker unavailable")):
            self.dialog._handle_preset_selected("Four joysticks", dict(type="joystick", count=4))
        self.assertFalse(self.dialog._busy)
        self.assertEqual(self.dialog.listener._device_change_suppressed, 0)
        self.assertIn("Worker unavailable", self.dialog.warning_widget.text())

    def test_four_device_preset_waits_for_slow_windows_creation(self):
        from test_maestro_osc import Endpoint, MAESTRO

        bridge = self.dialog.maestro.client
        bridge.definitions.clear()
        self.dialog._selected_service_device_ids.clear()
        self.dialog.config.maestro_device_map = {}
        replies = {}

        def reply(endpoint, address, values):
            request_id, *args = values
            if address in MAESTRO._LIST_REPLIES:
                rows = bridge.list(address)
                for index, row in enumerate(rows):
                    endpoint.send(MAESTRO._LIST_REPLIES[address], request_id, index, json.dumps(row))
                endpoint.send("/maestro_done", request_id, address, len(rows), 0, len(rows))
                return
            if request_id not in replies:
                if not bridge.requests:
                    # A cold Windows create can outlast all ordinary query
                    # retries. Scale the time down for this hardware-free test.
                    time.sleep(0.35)
                bridge.request(address, *args)
                replies[request_id] = json.dumps(bridge.definitions[args[0]])
            endpoint.send("/maestro_created", request_id, replies[request_id])

        endpoint = Endpoint(reply)
        self.addCleanup(endpoint.close)
        self.dialog.maestro.client = endpoint.client
        # Keep the capability fixture, while using the real UDP request path
        # for creation and the authoritative inventory used by the dialog.
        for name in ("definitions", "active_only", "profiles"):
            setattr(endpoint.client, name, getattr(bridge, name))
        self.preset(4)
        expected = {f"gex-{n}" for n in range(1, 5)}
        self.assertEqual(set(bridge.definitions), expected)
        self.assertEqual(set(self.dialog.config.maestro_device_map), expected)
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), expected)
        self.assertEqual(len(bridge.requests), 4)
        self.assertFalse(self.dialog.warning_widget.text())

    def test_eight_device_preset_keeps_qt_responsive_and_publishes_once(self):
        bridge = self.dialog.maestro.client
        entered, release = threading.Event(), threading.Event()
        request = bridge.request
        loads = []
        load = self.dialog._load_snapshot
        self.dialog._load_snapshot = lambda *args: (loads.append(threading.get_ident()), load(*args))[-1]

        def delayed_request(address, *args):
            if address == "/maestro_create_custom" and not entered.is_set():
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("Test did not release the worker")
            return request(address, *args)

        bridge.request = delayed_request
        try:
            self.dialog._handle_preset_selected("Eight joysticks", dict(type="joystick", count=8, axes=8, buttons=128, hats=4))
            self.assertTrue(entered.wait(1), "The background worker did not start")
            self.assertTrue(self.dialog._busy)
            self.assertFalse(self.dialog.presets_widget.isEnabled())
            self.assertFalse(self.dialog.new_button.isEnabled())
            ticks = []
            QtCore.QTimer.singleShot(0, lambda: ticks.append(True))
            APP.processEvents()
            self.assertEqual(ticks, [True], "Qt could not process events during device creation")
            # A queued preset action must not start a second overlapping batch.
            self.dialog._handle_preset_selected("Eight joysticks", dict(type="joystick", count=8))
        finally:
            release.set()
        pump_until(lambda: not self.dialog._busy)
        expected = {f"gex-{n}" for n in range(1, 10)}
        self.assertEqual(set(bridge.definitions), expected)
        self.assertEqual(set(self.dialog.config.maestro_device_map), expected)
        self.assertEqual(self.dialog.config.maestro_device_count, 9)
        self.dialog.config.save.assert_called_once_with()
        self.assertEqual(len(bridge.requests), 8)
        self.assertTrue(all(tid != threading.get_ident() for tid in bridge.request_threads))
        self.assertTrue(all(tid == threading.get_ident() for tid in loads))
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertTrue(self.dialog.presets_widget.isEnabled())
        self.dialog.maestro.refreshDevices.assert_not_called()

    def test_preset_partial_failure_publishes_and_attaches_successful_devices(self):
        bridge = self.dialog.maestro.client
        request = bridge.request

        def fail_third(address, *args):
            if address == "/maestro_create_custom" and args[0] == "gex-4":
                raise RuntimeError("Windows device creation failed")
            return request(address, *args)

        bridge.request = fail_third
        self.preset()
        self.assertEqual(set(bridge.definitions), {"gex-1", "gex-2", "gex-3"})
        self.assertEqual(set(self.dialog.config.maestro_device_map), {"gex-1", "gex-2", "gex-3"})
        self.assertIn("Created 2 of 8", self.dialog.warning_widget.text())
        self.assertIn("Windows device creation failed", self.dialog.warning_widget.text())
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), set(bridge.definitions))

    def test_preset_reserves_inactive_and_active_only_service_ids(self):
        bridge = self.dialog.maestro.client
        bridge.definitions["gex-3"] = joystick("gex-3", enabled=False)
        bridge.active_only["gex-2"] = joystick("gex-2")
        self.preset(2)
        creates = [args[0] for address, args in bridge.requests if address == "/maestro_create_custom"]
        self.assertEqual(creates, ["gex-4", "gex-5"])
        self.assertFalse(bridge.definitions["gex-3"]["enabled"])

    def test_gamepad_preset_uses_dedicated_creation_command(self):
        self.preset(2, "gamepad")
        self.assertEqual(self.dialog.maestro.client.requests, [
            ("/maestro_create_gamepad", ("gex-gp-1", "gex-gp-1")),
            ("/maestro_create_gamepad", ("gex-gp-2", "gex-gp-2")),
        ])
        self.assertEqual(set(self.dialog.config.maestro_device_map), {"gex-1", "gex-gp-1", "gex-gp-2"})

    def test_preset_creates_and_attaches_devices_beyond_sixteen(self):
        bridge = self.dialog.maestro.client
        bridge.definitions.update({f"gex-{n}": joystick(f"gex-{n}") for n in range(2, 17)})
        self.preset(8)
        created = [args[0] for address, args in bridge.requests if address == "/maestro_create_custom"]
        self.assertEqual(created, [f"gex-{n}" for n in range(17, 25)])
        self.assertTrue(set(created).issubset(self.dialog.config.maestro_device_map))
        self.assertEqual([self.dialog.config.maestro_device_map[id] for id in created], list(range(16, 24)))
        self.assertFalse(self.dialog.warning_widget.text())

    def test_preset_with_insufficient_ids_creates_nothing(self):
        bridge = self.dialog.maestro.client
        bridge.definitions.update({f"gex-{n}": joystick(f"gex-{n}") for n in range(2, 253)})
        self.preset()
        self.assertFalse(bridge.requests)
        self.assertIn("only 4 are available", self.dialog.warning_widget.text())
        self.dialog.config.save.assert_not_called()

    def test_preset_with_insufficient_target_slots_creates_nothing(self):
        self.dialog._selected_service_device_ids = {f"gex-{n}" for n in range(1, 250)}
        self.preset()
        self.assertFalse(self.dialog.maestro.client.requests)
        self.assertIn("including the preset", self.dialog.warning_widget.text())

    def test_test_device_dialog_creates_on_worker_and_publishes_rows_on_ui_thread(self):
        self.add_test_profiles()
        changes = []
        self.dialog.devices_changed.connect(lambda: changes.append(threading.get_ident()))
        before = len(self.dialog.maestro.capability_threads)
        self.create_test_devices_from_dialog()
        self.assertEqual(changes, [threading.get_ident()])
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(self.dialog.status_widget.text(), "Created 3 test devices.")
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id),
                         {"gex-1", "test-wingman-1", "test-saitek-x52-1", "test-t16000m-1"})
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0})
        self.assertTrue(all(tid != threading.get_ident() for tid in self.dialog.maestro.client.request_threads))
        self.assertTrue(all(tid != threading.get_ident() for tid in self.dialog.maestro.capability_threads[before:]))

    def test_test_device_dialog_reports_errors_without_worker_qt_calls(self):
        changed = Mock()
        self.dialog.devices_changed.connect(changed)
        with patch.object(self.dialog.maestro, "createTestDevices", side_effect=RuntimeError("Profiles unavailable")):
            self.create_test_devices_from_dialog()
        self.assertEqual(self.dialog.warning_widget.text(), "Profiles unavailable")
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})
        changed.assert_not_called()

    def test_test_device_dialog_publishes_partial_creation_before_showing_error(self):
        self.add_test_profiles()
        changes = []
        self.dialog.devices_changed.connect(lambda: changes.append(threading.get_ident()))
        request = self.dialog.maestro.client.request

        def fail_second(address, *args, **kwargs):
            if args[0] == "test-saitek-x52-1":
                raise RuntimeError("Device limit reached")
            return request(address, *args, **kwargs)

        with patch.object(self.dialog.maestro.client, "request", side_effect=fail_second):
            self.create_test_devices_from_dialog()
        self.assertEqual(self.dialog.warning_widget.text(), "Device limit reached")
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1", "test-wingman-1"})
        self.assertEqual(changes, [threading.get_ident()])
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0})

    def test_manual_helper_creates_non_gex_catalog_devices_without_selecting_them(self):
        self.add_test_profiles()
        created_service_ids = self.dialog.maestro.createTestDevices()
        self.assertEqual(created_service_ids, ["test-wingman-1", "test-saitek-x52-1", "test-t16000m-1"])
        self.assertEqual(self.dialog.maestro.client.requests, [
            ("/maestro_create", ("test-wingman-1", "logitech-wingman-formula-gp", "Logitech WingMan Formula GP")),
            ("/maestro_create", ("test-saitek-x52-1", "saitek-x52", "Saitek X52 Flight Control System")),
            ("/maestro_create", ("test-t16000m-1", "thrustmaster-t16000m", "Thrustmaster T.16000M Joystick")),
        ])
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1", *created_service_ids})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})
        self.assertTrue(all(not self.dialog._selection_widgets_by_service_id[sid].isChecked()
                            for sid in created_service_ids))
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0})
        self.dialog.config.save.assert_not_called()
        self.dialog.maestro.refreshDevices.assert_called_once_with()

    def test_repeated_test_creation_skips_existing_devices(self):
        self.add_test_profiles()
        first = self.dialog.maestro.createTestDevices()
        self.dialog.maestro.client.requests.clear()
        self.dialog.maestro.refreshDevices.reset_mock()
        self.assertEqual(self.dialog.maestro.createTestDevices(), [])
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-1", *first})
        self.assertEqual(self.dialog.maestro.client.requests, [])
        self.dialog.maestro.refreshDevices.assert_not_called()

    def test_test_creation_recreates_only_a_deleted_sample(self):
        self.add_test_profiles()
        self.dialog.maestro.createTestDevices()
        del self.dialog.maestro.client.definitions["test-saitek-x52-1"]
        self.dialog.maestro.client.requests.clear()
        self.assertEqual(self.dialog.maestro.createTestDevices(), ["test-saitek-x52-1"])
        self.assertEqual(len(self.dialog.maestro.client.requests), 1)

    def test_existing_samples_do_not_require_catalog_profiles(self):
        self.add_test_profiles()
        self.dialog.maestro.createTestDevices()
        self.dialog.maestro.client.profiles.clear()
        self.assertEqual(self.dialog.maestro.createTestDevices(), [])
        del self.dialog.maestro.client.definitions["test-t16000m-1"]
        self.dialog.maestro.client.profiles["thrustmaster-t16000m"] = dict(
            id="thrustmaster-t16000m", name="Thrustmaster T.16000M Joystick", deployable=True)
        self.assertEqual(self.dialog.maestro.createTestDevices(), ["test-t16000m-1"])

    def test_manual_helper_skips_saved_and_active_service_ids(self):
        self.add_test_profiles()
        saved = joystick("test-wingman-1", enabled=False)
        active = joystick("test-saitek-x52-1")
        self.dialog.maestro.client.definitions[saved["id"]] = saved
        self.dialog.maestro.client.active_only[active["id"]] = active
        self.assertEqual(self.dialog.maestro.createTestDevices(),
                         ["test-t16000m-1"])
        self.assertEqual(self.dialog.maestro.client.definitions[saved["id"]], saved)
        self.assertEqual(self.dialog.maestro.client.active_only[active["id"]], active)

    def test_manual_helper_rejects_unavailable_profiles_before_creating_any_devices(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                self.add_test_profiles()
                if missing:
                    del self.dialog.maestro.client.profiles["saitek-x52"]
                else:
                    self.dialog.maestro.client.profiles["saitek-x52"]["deployable"] = False
                with self.assertRaisesRegex(RuntimeError, "saitek-x52"):
                    self.dialog.maestro.createTestDevices()
                self.assertFalse(self.dialog.maestro.client.requests)
                self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-1"})
                self.dialog.maestro.refreshDevices.assert_not_called()

    def test_manual_helper_requires_a_connection(self):
        self.dialog.maestro.ensureConnected.return_value = False
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            self.dialog.maestro.createTestDevices()
        self.assertFalse(self.dialog.maestro.client.requests)
        self.dialog.maestro.refreshDevices.assert_not_called()

    def test_manual_helper_publishes_successful_creations_before_a_later_service_error(self):
        self.add_test_profiles()
        request = self.dialog.maestro.client.request

        def fail_saitek(address, *args):
            if args[0] == "test-saitek-x52-1":
                error = UI["MaestroServiceError"](address, "create_failed", "Device limit reached")
                return UI["MaestroResult"].from_error(address, error)
            return request(address, *args)

        with patch.object(self.dialog.maestro.client, "request", side_effect=fail_saitek):
            with self.assertRaisesRegex(RuntimeError, "Device limit reached"):
                self.dialog.maestro.createTestDevices()
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-1", "test-wingman-1"})
        self.dialog.maestro.refreshDevices.assert_called_once_with()
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertIn("test-wingman-1", self.dialog._selection_widgets_by_service_id)
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0})

    def test_new_device_remains_listed_after_automatic_apply(self):
        before = len(self.dialog.maestro.capability_threads)
        self.create_device()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1", "gex-2"})
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0, "gex-2": 1})
        self.assertEqual(len(self.dialog.labels()), 2)
        self.assertTrue(all("8 axes, 128 buttons, 4 hats" in label for label in self.dialog.labels()))
        self.assertTrue(all(tid != threading.get_ident() for tid in self.dialog.maestro.capability_threads[before:]))

    def test_apply_keeps_existing_rows(self):
        self.dialog._apply()
        pump_until(lambda: not self.dialog._busy)
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})

    def test_delete_removes_the_definition_and_row_but_keeps_other_devices(self):
        self.create_device()
        changed = Mock()
        self.dialog.devices_changed.connect(changed)
        self.dialog._delete_device("gex-1")
        pump_until(lambda: not self.dialog._busy)
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-2"})
        self.assertEqual(set(self.dialog._definitions_by_service_id), {"gex-2"})
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-2"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-2"})
        self.assertEqual(len(self.dialog.labels()), 1)
        self.assertIn("gex-2", self.dialog.labels()[0])
        self.assertEqual(self.dialog.maestro.client.requests[-1], ("/maestro_delete", ("gex-1",)))
        self.assertNotEqual(self.dialog.maestro.client.request_threads[-1], threading.get_ident())
        self.dialog.maestro.refreshDevices.assert_called_once_with()
        changed.assert_called_once_with()
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertNotIn("gex-1", self.dialog._selection_widgets_by_service_id)

    def test_row_deletion_distinguishes_app_and_external_devices_with_the_same_name(self):
        # The shared display name also matches another device's actual ID.
        self.dialog.maestro.client.definitions["gex-1"]["name"] = "external-stick"
        self.create_device(name="external-stick")
        self.dialog.maestro.client.definitions["external-stick"] = joystick("external-stick")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1", "gex-2", "external-stick"})
        self.assertEqual(len(self.dialog.labels()), 3)
        self.assertTrue(all(label.startswith("external-stick  [") for label in self.dialog.labels()))
        self.assertTrue(any("[gex-1/" in label and "GEX failover (active)" in label for label in self.dialog.labels()))
        for device_id in ("gex-2", "external-stick"):
            delete = next(button for button in self.dialog.device_list.findChildren(QtWidgets.QPushButton)
                          if getattr(button, "data", None) == device_id)
            QtTest.QTest.mouseClick(delete, QtCore.Qt.MouseButton.LeftButton)
            pump_until(lambda: not self.dialog._busy)
            self.assertFalse(self.dialog.warning_widget.text())
            self.assertNotIn(device_id, self.dialog._selection_widgets_by_service_id)
            self.assertIn("gex-1", self.dialog._selection_widgets_by_service_id)
            self.assertEqual(self.dialog.maestro.client.requests[-1], ("/maestro_delete", (device_id,)))
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-1"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})

    def test_bulk_deletion_removes_all_selected_duplicate_names(self):
        self.dialog.maestro.client.definitions["gex-1"]["name"] = "Shared joystick"
        self.create_device(name="Shared joystick")
        self.dialog.maestro.client.definitions["external-stick"] = joystick("external-stick") | dict(name="Shared joystick")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.dialog._handle_select_all()
        self.delete_selected()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual([args for address, args in self.dialog.maestro.client.requests if address == "/maestro_delete"],
                         [("gex-1",), ("gex-2",), ("external-stick",)])
        self.assertFalse(self.dialog.maestro.client.definitions)
        self.assertFalse(self.dialog._selection_widgets_by_service_id)
        self.assertIn("No devices were found", self.dialog.labels()[0])

    def test_bulk_deletion_preserves_unchecked_duplicates_after_external_creation(self):
        self.dialog.maestro.client.definitions["gex-1"].update(name="Shared joystick", profileId="shared-layout")
        self.dialog._load_snapshot(self.dialog.snapshot())
        # An external client adds two devices with the same name and profile.
        for device_id in ("external-a", "external-b"):
            self.dialog.maestro.client.definitions[device_id] = joystick(device_id) | dict(
                name="Shared joystick", profileId="shared-layout")
        snapshot = self.dialog.snapshot()
        self.assertEqual({cap.id for cap in snapshot["capabilities"].values()}, {"shared-layout"})
        self.assertEqual({cap.service_device_id for cap in snapshot["capabilities"].values()},
                         {"gex-1", "external-a", "external-b"})
        self.dialog._load_snapshot(snapshot)
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1", "external-a", "external-b"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})
        self.assertFalse(self.dialog._selection_widgets_by_service_id["external-a"].isChecked())
        self.assertFalse(self.dialog._selection_widgets_by_service_id["external-b"].isChecked())
        self.dialog._selection_widgets_by_service_id["external-a"].setChecked(True)
        self.delete_selected()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(self.dialog.maestro.client.requests, [
            ("/maestro_delete", ("gex-1",)), ("/maestro_delete", ("external-a",))])
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"external-b"})
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"external-b"})
        self.assertFalse(self.dialog._selection_widgets_by_service_id["external-b"].isChecked())
        self.assertFalse(self.dialog._selected_service_device_ids)
        self.assertIn("Shared joystick  [external-b/", self.dialog.labels()[0])

    def test_duplicate_inactive_devices_remain_independent_without_capabilities(self):
        self.dialog.maestro.client.definitions["gex-1"].update(name="Shared joystick", enabled=False)
        self.dialog.maestro.client.definitions["external-stick"] = joystick("external-stick", enabled=False) | dict(
            name="Shared joystick")
        self.dialog.maestro.missing_capabilities.update({"gex-1", "external-stick"})
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(len(self.dialog.labels()), 2)
        self.dialog._handle_select_none()
        self.dialog._selection_widgets_by_service_id["external-stick"].setChecked(True)
        self.assertEqual(self.dialog._selected_service_device_ids, {"external-stick"})
        self.delete_selected()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(self.dialog.maestro.client.requests, [("/maestro_delete", ("external-stick",))])
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})
        self.assertFalse(self.dialog._selected_service_device_ids)
        self.assertIn("Shared joystick  [gex-1/", self.dialog.labels()[0])

    def test_delete_last_inactive_device_shows_the_empty_list_message(self):
        self.dialog.maestro.client.definitions["gex-1"]["enabled"] = False
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.dialog._delete_device("gex-1")
        pump_until(lambda: not self.dialog._busy)
        self.assertFalse(self.dialog._definitions_by_service_id)
        self.assertFalse(self.dialog._selection_widgets_by_service_id)
        self.assertFalse(self.dialog._selected_service_device_ids)
        self.assertIn("No devices were found", self.dialog.labels()[0])
        self.assertFalse(self.dialog.select_all_button.isEnabled())
        self.assertFalse(self.dialog.delete_all_button.isEnabled())
        self.assertTrue(self.dialog.maestro._default_devices_prompted)

    def test_delete_all_suppresses_default_device_offers(self):
        self.create_device()
        self.dialog._delete_all_devices(True, None)
        pump_until(lambda: not self.dialog._busy)
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertFalse(self.dialog.maestro.client.definitions)
        self.assertFalse(self.dialog._definitions_by_service_id)
        self.assertFalse(self.dialog._selected_service_device_ids)
        self.assertTrue(self.dialog.maestro._default_devices_prompted)
        self.dialog.maestro.refreshDevices.assert_called_once_with()

    def test_selected_deletion_breadcrumbs_cover_worker_and_ui_completion(self):
        trail = []
        with patch.object(GREMLIN.util, "_trace", side_effect=lambda label: trail.append(
            (label, threading.get_ident())
        ), create=True):
            self.delete_selected()
        labels = [label for label, _ in trail]
        self.assertEqual(labels[0], "maestro delete selected: 1 devices")
        self.assertIn("maestro delete begin gex-1", labels)
        self.assertIn("maestro delete acknowledged gex-1", labels)
        self.assertIn("maestro delete snapshot ready", labels)
        self.assertEqual(labels[-2:], ["maestro delete updating dialog rows", "maestro delete dialog rows updated"])
        self.assertEqual(trail[0][1], threading.get_ident())
        self.assertTrue(all(tid != threading.get_ident() for _, tid in trail[1:-2]))
        self.assertTrue(all(tid == threading.get_ident() for _, tid in trail[-2:]))

    def test_delete_selected_button_deletes_all_checked_devices_and_updates_ui(self):
        self.create_device()
        changed_threads = []
        self.dialog.devices_changed.connect(lambda: changed_threads.append(threading.get_ident()))
        self.dialog._handle_select_all()
        self.delete_selected()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertFalse(self.dialog.maestro.client.definitions)
        self.assertFalse(self.dialog._definitions_by_service_id)
        self.assertFalse(self.dialog._selection_widgets_by_service_id)
        self.assertFalse(self.dialog._selected_service_device_ids)
        self.assertIn("No devices were found", self.dialog.labels()[0])
        self.assertFalse(self.dialog.delete_all_button.isEnabled())
        self.assertFalse(self.dialog.select_all_button.isEnabled())
        self.assertEqual(changed_threads, [threading.get_ident()])
        deletions = [(address, args) for address, args in self.dialog.maestro.client.requests
                     if address.startswith("/maestro_delete")]
        self.assertEqual(deletions, [("/maestro_delete", ("gex-1",)), ("/maestro_delete", ("gex-2",))])
        self.assertTrue(all(tid != threading.get_ident() for tid in self.dialog.maestro.client.request_threads))
        self.dialog.maestro.refreshDevices.assert_called_once_with()
        self.assertTrue(self.dialog.maestro._default_devices_prompted)
        self.assertEqual(self.dialog.status_widget.text(), "Selected devices have been deleted.")

    def test_delete_selected_preserves_unchecked_and_management_only_devices(self):
        self.create_device()
        self.dialog.maestro.client.definitions["gex-0"] = joystick("gex-0")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.dialog._selection_widgets_by_service_id["gex-2"].setChecked(False)
        self.delete_selected()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-2", "gex-0"})
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-2", "gex-0"})
        self.assertFalse(self.dialog._selected_service_device_ids)
        self.assertEqual(len(self.dialog.labels()), 2)
        self.assertFalse(self.dialog.delete_all_button.isEnabled())
        self.dialog.maestro.refreshDevices.assert_called_once_with()
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertFalse(self.dialog._selection_widgets_by_service_id["gex-2"].isChecked())

    def test_delete_selected_uses_ids_for_gamepads_and_custom_vendor_devices(self):
        self.dialog.maestro.client.definitions.update({
            "gex-gp-1": joystick("gex-gp-1"),
            "external-stick": joystick("external-stick") | dict(vendorId=0x1234, productId=0x5678),
        })
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.dialog._handle_select_all()
        self.delete_selected()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertFalse(self.dialog.maestro.client.definitions)
        self.assertFalse(self.dialog._selection_widgets_by_service_id)
        self.assertFalse(any(address == "/maestro_delete_all"
                             for address, _ in self.dialog.maestro.client.requests))
        self.dialog.maestro.refreshDevices.assert_called_once_with()

    def test_cancelled_delete_selected_preserves_devices_and_selection(self):
        changed = Mock()
        self.dialog.devices_changed.connect(changed)
        self.delete_selected(confirmed=False)
        self.assertEqual(set(self.dialog._definitions_by_service_id), {"gex-1"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})
        self.assertFalse(self.dialog.maestro.client.requests)
        self.assertFalse(self.dialog.maestro._default_devices_prompted)
        self.dialog.maestro.refreshDevices.assert_not_called()
        changed.assert_not_called()

    def test_partial_bulk_failure_refreshes_deleted_rows_and_preserves_failed_device(self):
        self.create_device()
        changed = Mock()
        self.dialog.devices_changed.connect(changed)
        request = self.dialog.maestro.client.request

        def fail_second_delete(address, *args, **kwargs):
            if address == "/maestro_delete" and args == ("gex-2",):
                error = UI["MaestroServiceError"](address, "delete_failed", "Device is busy")
                return UI["MaestroResult"].from_error(address, error)
            return request(address, *args, **kwargs)

        with (patch.object(self.dialog.maestro.client, "request", side_effect=fail_second_delete),
              patch.dict(UI, syslog=Mock()), patch.dict(NAMESPACE, syslog=Mock())):
            self.delete_selected()
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-2"})
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-2"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-2"})
        self.assertIn("Device is busy", self.dialog.warning_widget.text())
        self.assertIn("did not complete", self.dialog.status_widget.text())
        self.dialog.maestro.refreshDevices.assert_called_once_with()
        changed.assert_called_once_with()

    def test_failed_delete_selected_preserves_devices_without_a_success_notification(self):
        changed = Mock()
        self.dialog.devices_changed.connect(changed)
        error = UI["MaestroServiceError"]("/maestro_delete", "delete_failed", "Device is busy")
        result = UI["MaestroResult"].from_error("/maestro_delete", error)
        with (patch.object(self.dialog.maestro.client, "request", return_value=result),
              patch.dict(UI, syslog=Mock()), patch.dict(NAMESPACE, syslog=Mock())):
            self.delete_selected()
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})
        self.assertIn("Device is busy", self.dialog.warning_widget.text())
        self.assertFalse(self.dialog.maestro._default_devices_prompted)
        self.dialog.maestro.refreshDevices.assert_not_called()
        changed.assert_not_called()

    def test_cancelled_delete_all_does_not_suppress_device_offers(self):
        self.dialog._delete_all_devices(False, None)
        self.assertEqual(set(self.dialog._definitions_by_service_id), {"gex-1"})
        self.assertFalse(self.dialog.maestro._default_devices_prompted)
        self.dialog.maestro.refreshDevices.assert_not_called()

    def test_failed_delete_all_preserves_devices_and_does_not_suppress_offers(self):
        error = UI["MaestroServiceError"]("/maestro_delete_all", "delete_failed", "Device busy")
        result = UI["MaestroResult"].from_error("/maestro_delete_all", error)
        with (patch.object(self.dialog.maestro.client, "request", return_value=result),
              patch.dict(UI, syslog=Mock())):
            self.dialog._delete_all_devices(True, None)
            pump_until(lambda: not self.dialog._busy)
        self.assertEqual(set(self.dialog._definitions_by_service_id), {"gex-1"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})
        self.assertFalse(self.dialog.maestro._default_devices_prompted)
        self.assertIn("Device busy", self.dialog.warning_widget.text())
        self.dialog.maestro.refreshDevices.assert_not_called()

    def test_failed_delete_preserves_the_device_and_selection(self):
        changed = Mock()
        self.dialog.devices_changed.connect(changed)
        for error in (
            UI["MaestroServiceError"]("/maestro_delete", "delete_failed", "Device is busy"),
            TimeoutError("No reply from the bridge"),
        ):
            with self.subTest(error=error), patch.dict(UI, syslog=Mock()):
                result = UI["MaestroResult"].from_error("/maestro_delete", error)
                with patch.object(self.dialog.maestro.client, "request", return_value=result):
                    self.dialog._delete_device("gex-1")
                    pump_until(lambda: not self.dialog._busy)
                self.assertEqual(set(self.dialog._definitions_by_service_id), {"gex-1"})
                self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})
                self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})
                self.assertIn(str(error), self.dialog.warning_widget.text())
                self.dialog.maestro.refreshDevices.assert_not_called()
                self.assertFalse(self.dialog.maestro._default_devices_prompted)
                changed.assert_not_called()

    def test_created_but_unselected_device_is_still_visible(self):
        self.create_device(include=False)
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1", "gex-2"})
        self.assertFalse(self.dialog._selection_widgets_by_service_id["gex-2"].isChecked())
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0})

    def test_all_host_devices_are_visible_with_distinct_failover_colors(self):
        for device_id in ("gex-gp-1", "external-stick", "gex-0"):
            self.dialog.maestro.client.definitions[device_id] = joystick(device_id)
        self.dialog.maestro.client.definitions["external-stick"]["enabled"] = False
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(set(self.dialog._definitions_by_service_id), {"gex-1", "gex-gp-1", "external-stick", "gex-0"})
        labels = {label.text().split("  [")[0]: label
                  for label in self.dialog.device_list.findChildren(QtWidgets.QLabel)}
        self.assertIn("GEX failover", labels["gex-1"].text())
        self.assertIn("GEX gamepad (non-failover)", labels["gex-gp-1"].text())
        self.assertIn("Inactive", labels["external-stick"].text())
        self.assertNotEqual(labels["gex-1"].styleSheet(), labels["external-stick"].styleSheet())
        self.assertEqual(labels["gex-gp-1"].styleSheet(), labels["external-stick"].styleSheet())
        self.assertFalse(self.dialog._selection_widgets_by_service_id["gex-0"].isEnabled())
        self.assertNotIn("gex-0", self.dialog._selected_service_device_ids)

    def test_inactive_gex_joystick_is_not_identified_as_active_failover(self):
        self.dialog.maestro.client.definitions["gex-2"] = joystick("gex-2", enabled=False)
        self.dialog._load_snapshot(self.dialog.snapshot())
        labels = {label.text().split("  [")[0]: label
                  for label in self.dialog.device_list.findChildren(QtWidgets.QLabel)}
        self.assertIn("GEX failover (active)", labels["gex-1"].text())
        self.assertIn("GEX joystick (inactive)", labels["gex-2"].text())
        self.assertNotIn("GEX failover", labels["gex-2"].text())
        self.assertNotEqual(labels["gex-1"].styleSheet(), labels["gex-2"].styleSheet())

    def test_select_all_skips_management_only_devices(self):
        self.dialog.maestro.client.definitions["gex-0"] = joystick("gex-0")
        self.dialog.maestro.client.definitions["external-stick"] = joystick("external-stick")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.dialog._handle_select_all()
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1", "external-stick"})
        self.assertFalse(self.dialog._selection_widgets_by_service_id["gex-0"].isChecked())
        self.dialog._apply()
        pump_until(lambda: not self.dialog._busy)
        self.assertEqual(set(self.dialog.config.maestro_device_map), {"gex-1", "external-stick"})
        self.assertFalse(self.dialog.warning_widget.text())

    def test_non_gex_and_legacy_devices_can_be_deleted_individually(self):
        for device_id in ("external-stick", "gex-0"):
            with self.subTest(device_id=device_id):
                self.dialog.maestro.client.definitions[device_id] = joystick(device_id)
                self.dialog._load_snapshot(self.dialog.snapshot())
                self.dialog._delete_device(device_id)
                pump_until(lambda: not self.dialog._busy)
                self.assertNotIn(device_id, self.dialog._definitions_by_service_id)
                self.assertIn("gex-1", self.dialog._definitions_by_service_id)
                self.assertIn(("/maestro_delete", (device_id,)), self.dialog.maestro.client.requests)

    def test_active_device_without_saved_definition_is_visible_and_deletable(self):
        self.dialog.maestro.client.active_only["external-live"] = joystick("external-live")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertIn("external-live", self.dialog._definitions_by_service_id)
        self.assertTrue(any("external-live" in text and "Active" in text for text in self.dialog.labels()))
        self.assertFalse(self.dialog._selection_widgets_by_service_id["external-live"].isEnabled())
        delete = next(button for button in self.dialog.device_list.findChildren(QtWidgets.QPushButton)
                      if getattr(button, "data", None) == "external-live")
        delete._handle_callback()
        pump_until(lambda: not self.dialog._busy)
        self.assertNotIn("external-live", self.dialog._definitions_by_service_id)
        self.assertIn(("/maestro_delete", ("external-live",)), self.dialog.maestro.client.requests)

    def test_saved_definition_remains_visible_when_capabilities_are_unavailable(self):
        self.dialog.maestro.missing_capabilities.add("gex-1")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})
        self.assertIn("8 axes, 128 buttons, 4 hats", self.dialog.labels()[0])
        self.dialog._selection_widgets_by_service_id["gex-1"].setChecked(False)
        self.assertNotIn("gex-1", self.dialog._selected_service_device_ids)

    def test_inactive_catalog_device_uses_saved_profile_when_capabilities_are_unavailable(self):
        self.dialog.maestro.client.profiles["catalog-stick"] = dict(
            id="catalog-stick", name="Catalog stick", axes=["X", "Y", "Z"], addressableButtons=12, hatCount=1
        )
        self.dialog.maestro.client.definitions["gex-2"] = dict(
            id="gex-2", name="Saved stick", kind="profile", profileId="catalog-stick", enabled=False
        )
        self.dialog.maestro.missing_capabilities.add("gex-2")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1", "gex-2"})
        self.assertTrue(any("Saved stick" in text and "3 axes, 12 buttons, 1 hats" in text
                            and "Inactive" in text for text in self.dialog.labels()))

    def test_first_device_replaces_the_empty_host_message(self):
        self.dialog.maestro.client.definitions.clear()
        self.dialog.config.maestro_device_map = {}
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertFalse(self.dialog._selection_widgets_by_service_id)
        self.create_device("gex-1")
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})
        self.assertEqual(len(self.dialog.labels()), 1)
        self.assertIn("gex-1", self.dialog.labels()[0])

    def test_failed_creation_preserves_rows_and_reports_an_error(self):
        with patch.dict(UI, save_device_definition=Mock(return_value=False), syslog=Mock()):
            self.create_device()
        self.assertEqual(set(self.dialog._selection_widgets_by_service_id), {"gex-1"})
        self.assertEqual(self.dialog._selected_service_device_ids, {"gex-1"})
        self.assertIn("could not create gex-2", self.dialog.warning_widget.text())
        self.dialog.config.save.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
