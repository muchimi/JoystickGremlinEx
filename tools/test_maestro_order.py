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
"""Check GEX Windows HID order without creating devices: python tools/test_maestro_order.py."""

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.maestro_identity import inspect_hid_order
import test_maestro_cache as cache
from test_maestro_osc import GREMLIN, MAESTRO, CONFIG


def service_row(number):
    token = (f"HM_{0x0f + number:02X}{number:014X}" if number <= 16
             else f"HM_{0x2000 + ((number - 17) << 4):04X}{number:012X}")
    return dict(id=f"gex-{number}", instanceToken=token, identityKey=f"ordered-key-{number}",
                hidParentIdPrefix=f"1&{int(token[3:11], 16):x}&0")


def hid_row(device, *, counter=0):
    prefix = device["hidParentIdPrefix"].rsplit("&", 1)[0]
    return dict(path=fr"\\?\hid#hidclass#{prefix}&{counter}&0000#{{hid-guid}}".encode(),
                product_string=device["id"], usage_page=1, usage=4)


class HidOrderChecks(unittest.TestCase):
    def test_all_sixteen_ids_follow_actual_hid_scan_order(self):
        devices = [service_row(n) for n in range(1, 17)]
        report = inspect_hid_order(list(reversed(devices)), [hid_row(d) for d in devices])
        self.assertTrue(report["verified"])
        self.assertEqual(report["order"], [f"gex-{n}" for n in range(1, 17)])
        self.assertEqual([report["devices"][d["id"]]["windows_order"] for d in devices], list(range(1, 17)))

    def test_full_bridge_capacity_preserves_observed_numeric_order(self):
        devices = [service_row(n) for n in range(1, 257)]
        report = inspect_hid_order(list(reversed(devices)), [hid_row(d) for d in devices])
        self.assertTrue(report["verified"])
        self.assertEqual(report["order"], [d["id"] for d in devices])
        self.assertEqual(report["devices"]["gex-256"]["windows_order"], 256)

    def test_wrong_windows_order_is_reported_without_sorting_it_away(self):
        first, second = service_row(1), service_row(2)
        report = inspect_hid_order([first, second], [hid_row(second), hid_row(first)])
        self.assertFalse(report["verified"])
        self.assertTrue(report["mismatch"])
        self.assertEqual(report["order"], ["gex-2", "gex-1"])

    def test_physical_devices_gamepads_and_duplicate_collections_do_not_shift_order(self):
        first, second = service_row(1), service_row(2)
        gamepad = service_row(3) | dict(id="gex-gp-1")
        physical = dict(path=b"physical-device", usage_page=1, usage=4, product_string="gex-1")
        report = inspect_hid_order([first, second, gamepad],
                                   [physical, hid_row(first), hid_row(first), hid_row(gamepad), physical, hid_row(second)])
        self.assertTrue(report["verified"])
        self.assertEqual(report["order"], ["gex-1", "gex-2"])
        self.assertEqual(report["devices"]["gex-1"]["hid_index"], 1)
        self.assertEqual(report["devices"]["gex-2"]["hid_index"], 5)

    def test_alternate_child_prefix_and_cached_product_names_still_match_identity(self):
        device = service_row(1)
        row = hid_row(device, counter=3) | dict(product_string="Cached Windows name")
        report = inspect_hid_order([device], [row])
        self.assertTrue(report["verified"])
        self.assertEqual(report["devices"]["gex-1"]["product_string"], "Cached Windows name")

    def test_missing_or_ambiguous_identities_cannot_pass_verification(self):
        first, second = service_row(1), service_row(2)
        report = inspect_hid_order([first, second], [hid_row(first)])
        self.assertFalse(report["verified"])
        self.assertEqual(report["missing"], ["gex-2"])
        second["instanceToken"] = first["instanceToken"]
        report = inspect_hid_order([first, second], [hid_row(first)])
        self.assertFalse(report["verified"])
        self.assertTrue(report["ambiguous"])

    def test_inactive_lower_ids_do_not_prevent_verifying_relative_order(self):
        second, fourth = service_row(2), service_row(4)
        report = inspect_hid_order([fourth, second], [hid_row(second), hid_row(fourth)])
        self.assertTrue(report["verified"])
        self.assertFalse(report["mismatch"])
        self.assertEqual(report["order"], ["gex-2", "gex-4"])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["devices"]["gex-2"]["windows_order"], 1)

    def test_an_active_controller_without_identity_metadata_cannot_be_verified(self):
        first, second = service_row(1), dict(id="gex-2")
        report = inspect_hid_order([first, second], [hid_row(first)])
        self.assertFalse(report["verified"])
        self.assertEqual(report["missing"], ["gex-2"])


class PublishedHidOrderChecks(unittest.TestCase):
    setUp = cache.MaestroCacheChecks.setUp
    list_devices = cache.MaestroCacheChecks.list_devices
    request = cache.MaestroCacheChecks.request
    load = cache.MaestroCacheChecks.load
    published = cache.MaestroCacheChecks.published

    def controller_rows(self):
        self.definitions = {f"gex-{n}": cache.identity.definition(f"gex-{n}") | service_row(n) for n in (1, 2)}
        self.active_ids = ["gex-2", "gex-1"]
        CONFIG.maestro_device_map = {"gex-1": 7, "gex-2": 3}
        self.maestro._local_service = True
        hid = ModuleType("gremlin.hid")
        self.rows = [hid_row(self.definitions[f"gex-{n}"]) for n in (1, 2)]
        hid.enumerate_devices = lambda: self.rows
        modules = patch.dict("sys.modules", {"gremlin.hid": hid})
        modules.start()
        self.addCleanup(modules.stop)
        output_cache = patch.object(GREMLIN.joystick_handling, "_output_targets", {}, create=True)
        output_cache.start()
        self.addCleanup(output_cache.stop)
        self.load()

    def map_native_inputs(self):
        self.maestro._device_map = {
            index: NS(input_enabled=True, data={"maestro_key": controller.key})
            for index, controller in self.maestro._controller_map.items()
        }

    def test_hid_order_failure_does_not_keep_native_discovery_pending(self):
        self.controller_rows()
        self.map_native_inputs()
        self.rows.reverse()
        with patch.object(MAESTRO, "syslog"):
            self.maestro._scan_hid_order()
        self.assertTrue(all(not c.hid_order_valid for c in self.maestro._controller_map.values()))
        self.assertFalse(self.maestro._compare_list())
        # An unavailable HID scan still blocks automatic failover, but is not
        # evidence that already matched DirectInput devices are missing.
        with patch("gremlin.hid.enumerate_devices", side_effect=OSError("scan unavailable")), patch.object(MAESTRO, "syslog"):
            self.maestro._scan_hid_order()
        self.assertFalse(self.maestro._compare_list())
        self.maestro._device_map.pop(next(iter(self.maestro._device_map)))
        self.assertTrue(self.maestro._compare_list())

    def test_hid_scan_updates_every_published_device_without_verbose_logging(self):
        self.controller_rows()
        self.map_native_inputs()
        with patch.object(CONFIG, "verbose_mode_maestro", False):
            self.maestro._scan_hid_order()
            self.assertTrue(all(d.data["maestro_hid_order_valid"] for d in self.maestro._device_map.values()))
            self.rows.reverse()
            with patch.object(MAESTRO, "syslog"):
                self.maestro._scan_hid_order()
            for index, device in self.maestro._device_map.items():
                controller = self.maestro._controller_map[index]
                self.assertFalse(device.data["maestro_hid_order_valid"])
                self.assertEqual(device.data["maestro_windows_order"], controller.windows_order)

    def test_real_discovery_timeout_names_only_unmatched_devices(self):
        self.controller_rows()
        self.map_native_inputs()
        index = next(iter(self.maestro._device_map))
        missing = self.maestro._controller_map[index]
        del self.maestro._device_map[index]
        with patch.object(self.maestro, "syncDinput"), patch.object(MAESTRO.time, "monotonic", side_effect=[0, 21]), patch.object(
            MAESTRO, "syslog"
        ) as log:
            self.maestro._sync_worker_runner()
        log.warning.assert_called_once()
        warning, unmatched = log.warning.call_args.args
        self.assertIn("no native input match", warning)
        self.assertEqual(unmatched, f"{missing.id} ({missing.name})")
        self.assertIsNone(self.maestro._sync_worker)

    def test_worker_finishes_for_matched_inputs_even_when_hid_order_is_invalid(self):
        self.controller_rows()
        self.map_native_inputs()
        for controller in self.maestro._controller_map.values():
            controller.hid_order_valid = False
        self.maestro._dirty = True
        with patch.object(self.maestro, "syncDinput"), patch.object(self.maestro, "populateDeviceList") as publish, patch.object(
            GREMLIN.joystick_handling, "joystick_devices_initialization", create=True
        ) as initialize, patch.object(self.maestro._stopping, "wait") as wait, patch.object(MAESTRO, "syslog") as log:
            self.maestro._sync_worker_runner()
        publish.assert_called_once_with()
        initialize.assert_called_once_with()
        wait.assert_not_called()
        log.warning.assert_not_called()
        self.assertFalse(self.maestro._dirty)
        self.assertIsNone(self.maestro._sync_worker)

    def test_worker_defers_registry_rebuild_until_creation_request_finishes(self):
        from test_device_change_suppression import listener_fixture

        self.controller_rows()
        self.map_native_inputs()
        listener = listener_fixture()
        listener.pushDeviceChangeSuppression()
        with patch.object(self.maestro, "syncDinput"), patch.object(self.maestro, "populateDeviceList") as publish, patch.object(
            GREMLIN.event_handler, "EventListener", return_value=listener
        ), patch.object(GREMLIN.joystick_handling, "joystick_devices_initialization", create=True) as initialize:
            self.maestro._sync_worker_runner()
        initialize.assert_not_called()
        publish.assert_not_called()
        self.assertTrue(listener._device_change_pending)
        listener.popDeviceChangeSuppression()
        listener._device_update_timer.fire()
        listener.reset_devices.assert_called_once_with(force=False)

    def test_published_windows_order_uses_instance_token_not_transport_or_saved_slot(self):
        self.controller_rows()
        devices = self.published()
        self.assertEqual(devices["gex-1"].virtual_id, 7)
        self.assertEqual(devices["gex-1"].vjoy_id, 1)
        self.assertEqual(devices["gex-1"].data["maestro_windows_order"], 1)
        self.assertEqual(devices["gex-2"].data["maestro_windows_order"], 2)
        self.assertEqual(devices["gex-2"].data["maestro_hid_index"], 1)
        self.assertTrue(all(d.data["maestro_hid_order_valid"] for d in devices.values()))

    def test_mismatched_live_order_is_not_marked_verified(self):
        self.controller_rows()
        GREMLIN.joystick_handling._output_targets[2] = object()
        self.rows.reverse()
        with patch.object(MAESTRO, "syslog"):
            devices = self.published()
        self.assertFalse(devices["gex-1"].data["maestro_hid_order_valid"])
        self.assertEqual(devices["gex-1"].data["maestro_windows_order"], 2)
        self.assertEqual(GREMLIN.joystick_handling._output_targets, {})

    def test_unselected_bridge_devices_still_count_in_windows_order(self):
        self.controller_rows()
        CONFIG.maestro_device_map = {"gex-2": 7}
        self.load()
        devices = self.published()
        self.assertEqual(list(devices), ["gex-2"])
        self.assertEqual(devices["gex-2"].data["maestro_windows_order"], 2)
        self.assertTrue(devices["gex-2"].data["maestro_hid_order_valid"])

    def test_inactive_lower_id_does_not_change_failover_identity(self):
        self.controller_rows()
        self.active_ids = ["gex-2"]
        self.rows.pop(0)
        self.load()
        devices = self.published()
        self.assertEqual(list(devices), ["gex-2"])
        self.assertEqual(devices["gex-2"].vjoy_id, 2)
        self.assertEqual(devices["gex-2"].data["maestro_windows_order"], 1)
        self.assertTrue(devices["gex-2"].data["maestro_hid_order_valid"])

    def test_disappearing_hid_device_clears_previous_verification(self):
        self.controller_rows()
        self.rows.pop()
        devices = self.published()
        self.assertTrue(all(not d.data["maestro_hid_order_valid"] for d in devices.values()))
        self.assertIsNone(devices["gex-2"].data["maestro_windows_order"])

    def test_failed_hid_scan_clears_previous_verification(self):
        self.controller_rows()
        with patch("gremlin.hid.enumerate_devices", side_effect=OSError("scan failed")), patch.object(MAESTRO, "syslog"):
            devices = self.published()
        self.assertTrue(all(not d.data["maestro_hid_order_valid"] for d in devices.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
