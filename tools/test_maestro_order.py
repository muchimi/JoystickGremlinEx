"""Check GEX Windows HID order without creating devices: python tools/test_maestro_order.py."""

from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.maestro_identity import inspect_hid_order
import test_maestro_cache as cache
from test_maestro_osc import GREMLIN, MAESTRO, CONFIG


def service_row(number):
    token = f"HM_{0x0f + number:02X}{number:014X}"
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
