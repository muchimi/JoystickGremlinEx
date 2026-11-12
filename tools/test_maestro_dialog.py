"""Hardware-free device-list checks: python tools/test_maestro_dialog.py."""

from dataclasses import dataclass
import re
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtWidgets
from test_maestro_startup import COMMON, GREMLIN, NAMESPACE, Maestro as MaestroService, load_definitions
from test_qt_marshalling import APP, flush_deletes, pump_until


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


GREMLIN.util.clear_layout = clear_layout
UI = dict(COMMON)
load_definitions("gremlin/ui/ui_common.py", {"QDataCheckbox", "QScrollableWidget"}, UI)
UI["Buttons"] = NS(getDeleteWidget=lambda data, callback: UI["QDataPushButton"]("Delete", data=data, callback=callback))
UI.update(dataclass=dataclass, threading=threading, re=re, Slot=QtCore.Slot, GEX_MAX_DEVICES=16,
          AXIS_NAMES=("X", "Y", "Z", "Rx", "Ry", "Rz", "Slider", "Dial"),
          _GEX_ID_PATTERN=re.compile(r"gex-(?:gp-)?(\d+)"),
          Maestro=NS(klass=NS(_service_index=lambda device_id: int(device_id.split("-")[-1]) - 1)))
load_definitions("gremlin/maestro.py", {
    "MaestroProfileInfo", "_MaestroDialogSignals", "MaestroDialog", "service_snapshot",
    "is_valid_gex_id", "save_device_definition", "MaestroServiceError", "MaestroResult",
}, UI)


def joystick(device_id, enabled=True):
    return dict(id=device_id, name=device_id, kind="custom", profileId="custom-" + device_id,
                axes=8, buttons=128, hats=4, enabled=enabled)


class Bridge:
    """In-memory management responses; no sockets or HID devices."""

    def __init__(self, definitions):
        self.definitions = {row["id"]: dict(row) for row in definitions}
        self.profiles = {}
        self.requests = []
        self.request_threads = []

    def list(self, address):
        if address == "/maestro_definitions":
            return list(self.definitions.values())
        if address == "/maestro_devices":
            return [dict(id=row["id"], name=row["name"]) for row in self.definitions.values() if row["enabled"]]
        if address == "/maestro_profiles":
            return list(self.profiles.values())
        raise AssertionError(address)

    def request(self, address, *args, **kwargs):
        self.requests.append((address, args))
        self.request_threads.append(threading.get_ident())
        if address == "/maestro_create_custom":
            device_id, name, buttons, axes, hats = args
            self.definitions[device_id] = joystick(device_id) | dict(name=name, buttons=buttons, axes=axes, hats=hats)
        elif address == "/maestro_remove":
            self.definitions[args[0]]["enabled"] = False
        elif address == "/maestro_delete":
            del self.definitions[args[0]]
        elif address == "/maestro_delete_all":
            self.definitions.clear()
        else:
            raise AssertionError(address)
        return UI["MaestroResult"](True, address)


class MaestroFixture:
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
        self.populateDeviceList = Mock()
        self.refreshDevices = Mock()

    def connected(self):
        return True

    def LoadActiveControllers(self, device_map):
        self._controller_map = {slot: NS(id=device_id) for device_id, slot in device_map.items()}

    def getCapabilities(self, device_id):
        self.capability_threads.append(threading.get_ident())
        if device_id in self.missing_capabilities:
            return None
        row = self.client.definitions[device_id]
        data = dict(name=row["name"], kind=row["kind"], type="joystick",
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
        self.verbose = False
        self._busy = False
        self._completion = None
        self._tested_settings = ("127.0.0.1", 8010, "127.0.0.1", 8011)
        self._selected_ids = set(self.config.maestro_device_map)
        self._definitions, self._profiles, self._select_widget_map = {}, {}, {}
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
                     "select_all_button", "delete_all_button", "presets_widget", "apply_button"):
            setattr(self, name, QtWidgets.QPushButton(self))
        self.enabled_widget = QtWidgets.QCheckBox(self)
        self.enabled_widget.setChecked(True)
        self.device_list = UI["QScrollableWidget"](stretch=False, parent=self)
        self.new_button = UI["QDataPushButton"]("New Device", parent=self, clicked=self._create_new_joystick)
        self._load_snapshot(self.snapshot())

    def snapshot(self):
        snapshot = UI["service_snapshot"](self.maestro.client)
        snapshot["capabilities"] = {device_id: self.maestro.getCapabilities(device_id) for device_id in self.maestro.client.definitions}
        snapshot["capabilities"] = {key: value for key, value in snapshot["capabilities"].items() if value is not None}
        return snapshot

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

    def create_device(self, device_id="gex-2", include=True):
        editor = Mock(include=include)
        editor.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted
        editor.definition.return_value = joystick(device_id)
        with patch.dict(UI, MaestroNewDeviceDialog=Mock(return_value=editor)):
            self.dialog.new_button.click()
            pump_until(lambda: not self.dialog._busy)

    def test_new_device_remains_listed_after_automatic_apply(self):
        before = len(self.dialog.maestro.capability_threads)
        self.create_device()
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-1", "gex-2"})
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0, "gex-2": 1})
        self.assertEqual(len(self.dialog.labels()), 2)
        self.assertTrue(all("8 axes, 128 buttons, 4 hats" in label for label in self.dialog.labels()))
        self.assertTrue(all(tid != threading.get_ident() for tid in self.dialog.maestro.capability_threads[before:]))

    def test_apply_keeps_existing_rows(self):
        self.dialog._apply()
        pump_until(lambda: not self.dialog._busy)
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-1"})

    def test_delete_removes_the_definition_and_row_but_keeps_other_devices(self):
        self.create_device()
        changed = Mock()
        self.dialog.devices_changed.connect(changed)
        self.dialog._delete_device("gex-1")
        pump_until(lambda: not self.dialog._busy)
        self.assertFalse(self.dialog.warning_widget.text())
        self.assertEqual(set(self.dialog.maestro.client.definitions), {"gex-2"})
        self.assertEqual(set(self.dialog._definitions), {"gex-2"})
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-2"})
        self.assertEqual(self.dialog._selected_ids, {"gex-2"})
        self.assertEqual(len(self.dialog.labels()), 1)
        self.assertIn("gex-2", self.dialog.labels()[0])
        self.assertEqual(self.dialog.maestro.client.requests[-1], ("/maestro_delete", ("gex-1",)))
        self.assertNotEqual(self.dialog.maestro.client.request_threads[-1], threading.get_ident())
        self.dialog.maestro.refreshDevices.assert_called_once_with()
        changed.assert_called_once_with()
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertNotIn("gex-1", self.dialog._select_widget_map)

    def test_delete_last_inactive_device_shows_the_empty_list_message(self):
        self.dialog.maestro.client.definitions["gex-1"]["enabled"] = False
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.dialog._delete_device("gex-1")
        pump_until(lambda: not self.dialog._busy)
        self.assertFalse(self.dialog._definitions)
        self.assertFalse(self.dialog._select_widget_map)
        self.assertFalse(self.dialog._selected_ids)
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
        self.assertFalse(self.dialog._definitions)
        self.assertFalse(self.dialog._selected_ids)
        self.assertTrue(self.dialog.maestro._default_devices_prompted)
        self.dialog.maestro.refreshDevices.assert_called_once_with()

    def test_cancelled_delete_all_does_not_suppress_device_offers(self):
        self.dialog._delete_all_devices(False, None)
        self.assertEqual(set(self.dialog._definitions), {"gex-1"})
        self.assertFalse(self.dialog.maestro._default_devices_prompted)
        self.dialog.maestro.refreshDevices.assert_not_called()

    def test_failed_delete_all_preserves_devices_and_does_not_suppress_offers(self):
        error = UI["MaestroServiceError"]("/maestro_delete_all", "delete_failed", "Device busy")
        result = UI["MaestroResult"].from_error("/maestro_delete_all", error)
        with (patch.object(self.dialog.maestro.client, "request", return_value=result),
              patch.dict(UI, syslog=Mock())):
            self.dialog._delete_all_devices(True, None)
            pump_until(lambda: not self.dialog._busy)
        self.assertEqual(set(self.dialog._definitions), {"gex-1"})
        self.assertEqual(self.dialog._selected_ids, {"gex-1"})
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
                self.assertEqual(set(self.dialog._definitions), {"gex-1"})
                self.assertEqual(set(self.dialog._select_widget_map), {"gex-1"})
                self.assertEqual(self.dialog._selected_ids, {"gex-1"})
                self.assertIn(str(error), self.dialog.warning_widget.text())
                self.dialog.maestro.refreshDevices.assert_not_called()
                self.assertFalse(self.dialog.maestro._default_devices_prompted)
                changed.assert_not_called()

    def test_created_but_unselected_device_is_still_visible(self):
        self.create_device(include=False)
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-1", "gex-2"})
        self.assertFalse(self.dialog._select_widget_map["gex-2"].isChecked())
        self.assertEqual(self.dialog.config.maestro_device_map, {"gex-1": 0})

    def test_saved_definition_remains_visible_when_capabilities_are_unavailable(self):
        self.dialog.maestro.missing_capabilities.add("gex-1")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-1"})
        self.assertIn("8 axes, 128 buttons, 4 hats", self.dialog.labels()[0])
        self.dialog._select_widget_map["gex-1"].setChecked(False)
        self.assertNotIn("gex-1", self.dialog._selected_ids)

    def test_inactive_catalog_device_uses_saved_profile_when_capabilities_are_unavailable(self):
        self.dialog.maestro.client.profiles["catalog-stick"] = dict(
            id="catalog-stick", name="Catalog stick", axes=["X", "Y", "Z"], addressableButtons=12, hatCount=1
        )
        self.dialog.maestro.client.definitions["gex-2"] = dict(
            id="gex-2", name="Saved stick", kind="profile", profileId="catalog-stick", enabled=False
        )
        self.dialog.maestro.missing_capabilities.add("gex-2")
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-1", "gex-2"})
        self.assertTrue(any("Saved stick" in text and "3 axes, 12 buttons, 1 hats" in text
                            and "Inactive" in text for text in self.dialog.labels()))

    def test_first_device_replaces_the_empty_host_message(self):
        self.dialog.maestro.client.definitions.clear()
        self.dialog.config.maestro_device_map = {}
        self.dialog._load_snapshot(self.dialog.snapshot())
        self.assertFalse(self.dialog._select_widget_map)
        self.create_device("gex-1")
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-1"})
        self.assertEqual(len(self.dialog.labels()), 1)
        self.assertIn("gex-1", self.dialog.labels()[0])

    def test_failed_creation_preserves_rows_and_reports_an_error(self):
        with patch.dict(UI, save_device_definition=Mock(return_value=False), syslog=Mock()):
            self.create_device()
        self.assertEqual(set(self.dialog._select_widget_map), {"gex-1"})
        self.assertEqual(self.dialog._selected_ids, {"gex-1"})
        self.assertIn("could not create gex-2", self.dialog.warning_widget.text())
        self.dialog.config.save.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
