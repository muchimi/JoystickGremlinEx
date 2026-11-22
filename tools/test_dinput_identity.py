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
"""Read-only identity API checks: python tools/test_dinput_identity.py."""

import ctypes as c
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import uuid


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dinput_identity_checks", ROOT / "dinput/device_identity.py")
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)
sys.path.insert(0, str(ROOT))
from gremlin.maestro_identity import instance_token_for_key, matches_instance


class IdentityReaderChecks(unittest.TestCase):
    def setUp(self):
        self.released = []
        self.create_error = self.property_error = False
        self.path = r"\\?\hid#controller#instance#{interface}"
        self.container = "48494430-4d41-4553-6ca1-8125804d3151"
        self.libraries = {
            "dinput8.dll": NS(DirectInput8Create=Mock(side_effect=self.create_root)),
            "kernel32.dll": NS(GetModuleHandleW=Mock(return_value=123)),
        }
        for target, value in (("sys", NS(platform="win32")), ("_library", Mock(side_effect=self.libraries.__getitem__)),
                              ("_method", Mock(side_effect=self.method)), ("_container_id", Mock(return_value=self.container))):
            patched = patch.object(IDENTITY, target, value)
            patched.start()
            self.addCleanup(patched.stop)

    def create_root(self, instance, version, iid, pointer, outer):
        self.assertEqual(version, 0x0800)
        pointer._obj.value = 1
        return 0

    def create_device(self, root, guid, pointer, outer):
        if self.create_error:
            return -1
        pointer._obj.value = 2
        return 0

    def property(self, device, key, pointer):
        self.assertEqual(key, 12)
        prop = pointer._obj
        self.assertEqual(prop.header.size, c.sizeof(prop))
        self.assertEqual(prop.header.header_size, c.sizeof(IDENTITY._PropertyHeader))
        self.assertEqual((prop.header.object, prop.header.how), (0, 0))
        prop.path = self.path
        return -1 if self.property_error else 0

    def method(self, pointer, index, *types):
        if index == 2:
            return lambda device: self.released.append(device.value)
        if pointer.value == 1 and index == 3:
            return self.create_device
        if pointer.value == 2 and index == 5:
            return self.property
        self.fail(f"Unexpected COM call: {pointer.value}, {index}")

    def test_reads_interface_and_container_with_normalized_guid(self):
        guid = uuid.uuid4()
        rows = IDENTITY.get_device_identities(["{" + str(guid).upper() + "}"])
        self.assertEqual(rows, {guid.hex: dict(path=self.path, container_id=self.container)})
        self.assertEqual(self.released, [2, 1])

    def test_unplugged_device_is_omitted_and_root_released(self):
        self.create_error = True
        self.assertEqual(IDENTITY.get_device_identities([uuid.uuid4()]), {})
        self.assertEqual(self.released, [1])

    def test_unsupported_property_still_releases_both_interfaces(self):
        self.property_error = True
        self.assertEqual(IDENTITY.get_device_identities([uuid.uuid4()]), {})
        self.assertEqual(self.released, [2, 1])

    def test_container_query_error_does_not_leak_com_interfaces(self):
        IDENTITY._container_id.side_effect = OSError("Read failed")
        with self.assertRaises(OSError):
            IDENTITY.get_device_identities([uuid.uuid4()])
        self.assertEqual(self.released, [2, 1])

    def test_non_windows_does_not_load_windows_libraries(self):
        IDENTITY.sys.platform = "other"
        self.assertEqual(IDENTITY.get_device_identities([uuid.uuid4()]), {})
        IDENTITY._library.assert_not_called()


class InstanceMatchChecks(unittest.TestCase):
    def test_legacy_key_hash_matches_the_installed_sdk_golden_vector(self):
        self.assertEqual(instance_token_for_key("GEX:gex-1"), "HM_6CA18125804D3151")

    def test_sdk_golden_container_matches_across_different_interface_paths(self):
        self.assertTrue(matches_instance(dict(path="hid#primary", container_id="48494430-4d41-4553-6ca1-8125804d3151"),
                                         "HM_6CA18125804D3151"))
        self.assertTrue(matches_instance(dict(path="xusb#companion", container_id="{48494430-4D41-4553-6CA1-8125804D3151}"),
                                         "HM_6CA18125804D3151"))

    def test_different_container_is_not_merged_even_if_path_has_a_matching_prefix(self):
        row = dict(path="hid#1&6ca18125&0&0000#interface", container_id=str(uuid.uuid4()))
        self.assertFalse(matches_instance(row, "HM_6CA18125804D3151"))

    def test_path_fallback_remains_available_without_a_container_property(self):
        self.assertTrue(matches_instance(dict(path="hid#1&6ca18125&3&0000#interface"), "HM_6CA18125804D3151"))
        self.assertFalse(matches_instance(dict(path="hid#1&6ca18125&3&0000#interface"), None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
