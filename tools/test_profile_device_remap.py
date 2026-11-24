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
"""Hardware-free checks: python tools/test_profile_device_remap.py."""

import ast
import importlib.util
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, patch

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


remap = load("profile_device_remap_checks", ROOT / "gremlin/device_remap.py")
OLD = "c8d925a058e311f08002444553540000"
NEW = "ec787120dc1b11f18009444553540000"
OTHER = "f1d73a0058e311f08004444553540000"


def profile(target_mapped=False):
    root = etree.fromstring(f'<profile><devices><device type="joystick" name="LEFT VPC Stick WarBRD" device-guid="{OLD}"><mode name="Default"><axis id="1"><container id="kept"/></axis></mode></device></devices><condition device-guid="{{C8D925A0-58E3-11F0-8002-444553540000}}"/><merge-axis><lower device-guid="{OLD}"/></merge-axis><start><devices><device device-guid="{OLD}"><axis id="1" value="0.5"/></device></devices></start></profile>')
    target = etree.SubElement(root.find("devices"), "device", {"device-guid": NEW, "name": "L-VPC Stick WarBRD", "type": "joystick"})
    if target_mapped:
        etree.SubElement(target, "container", id="existing")
    return root


class GuidNormalizationChecks(unittest.TestCase):
    def test_supported_guid_formats_and_non_guid_xml_values_do_not_raise(self):
        exceptions = []
        def trace(frame, event, arg):
            if frame.f_code.co_filename == remap.__file__ and event == "exception":
                exceptions.append((frame.f_code.co_name, arg[0].__name__))
            return trace
        previous = sys.gettrace()
        sys.settrace(trace)
        try:
            for value in (OLD, OLD.upper(), "{C8D925A0-58E3-11F0-8002-444553540000}",
                          "urn:uuid:c8d925a0-58e3-11f0-8002-444553540000"):
                self.assertEqual(remap.guid_key(value), OLD)
            for value in (None, "", "True", "Default", "0.00000000", "1", 1,
                          "x" * 32, "-" * 36, "gex-1"):
                self.assertIsNone(remap.guid_key(value))
            for value in (None, "not-a-device", "+-1", "--2", NEW):
                self.assertIsNone(remap._vjoy_source_id(value, {}))
        finally:
            sys.settrace(previous)
        self.assertEqual(exceptions, [])


class RemapChecks(unittest.TestCase):
    def test_references_and_empty_target_are_replaced_without_mutating_source(self):
        original = profile()
        result = remap.remap_profile_devices(original, {OLD: (NEW, "L-VPC Stick WarBRD")})
        self.assertEqual(len(result.findall("./devices/device")), 1)
        self.assertEqual(result.find("./devices/device").get("name"), "L-VPC Stick WarBRD")
        self.assertEqual(result.find(".//container").get("id"), "kept")
        self.assertTrue(all(node.get("device-guid") == NEW for node in result.xpath("//*[@device-guid]")))
        self.assertEqual(original.find("./devices/device").get("device-guid"), OLD)

    def test_existing_target_mappings_are_protected(self):
        with self.assertRaisesRegex(ValueError, "already has mappings"):
            remap.remap_profile_devices(profile(True), {OLD: (NEW, "target")})

    def test_duplicate_targets_are_rejected(self):
        root = profile()
        etree.SubElement(root.find("devices"), "device", {"device-guid": OTHER})
        with self.assertRaisesRegex(ValueError, "different target"):
            remap.remap_profile_devices(root, {OLD: (NEW, "left"), OTHER: (NEW, "right")})

    def test_swaps_are_simultaneous(self):
        result = remap.remap_profile_devices(profile(True), {OLD: (NEW, "new"), NEW: (OLD, "old")})
        self.assertEqual([node.get("device-guid") for node in result.findall("./devices/device")], [NEW, OLD])
        self.assertEqual(result.find("condition").get("device-guid"), NEW)
        self.assertEqual(len(result.findall(".//container")), 2)

    def test_none_and_invalid_sources_are_rejected(self):
        for changes in ({}, {"invalid": (NEW, "new")}, {OTHER: (NEW, "new")}):
            with self.assertRaises(ValueError):
                remap.remap_profile_devices(profile(), changes)

    def test_unique_left_right_name_suggestions(self):
        source = profile().find("./devices/device")
        left = NS(name="L-VPC Stick WarBRD")
        right = NS(name="R-VPC Stick WarBRD")
        self.assertIs(remap.suggest_target(source, [right, left]), left)
        self.assertIsNone(remap.suggest_target(source, [left, left]))
        self.assertIsNone(remap.suggest_target(source, [right]))

    def test_atomic_write_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.xml"
            path.write_bytes(b"original")
            backup = remap.write_remapped_profile(path, profile())
            self.assertEqual(backup.read_bytes(), b"original")
            self.assertEqual(etree.parse(str(path)).getroot().tag, "profile")
            self.assertEqual(len(list(Path(folder).glob("*.tmp"))), 0)

    def test_failed_backup_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.xml"
            path.write_bytes(b"original")
            with patch.object(remap.shutil, "copy2", side_effect=OSError("backup failed")):
                with self.assertRaises(OSError):
                    remap.write_remapped_profile(path, profile())
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(len(list(Path(folder).glob("*.tmp"))), 0)


def maestro(slot=7, **kwargs):
    values = dict(name="gex-1", device_guid=NEW, connected=True, is_virtual=True,
                  device_type=NS(name="Maestro"), virtual_id=slot, data={})
    values.update(kwargs)
    return NS(**values)


class OutputRemapChecks(unittest.TestCase):
    def test_condition_only_profile_remaps_legacy_vjoy_reference(self):
        root = etree.fromstring('<profile><condition condition-type="vjoy" vjoy-id="1" input="button" id="3"/></profile>')
        target = maestro()
        self.assertEqual(remap.output_device_sources(root, [target])[0]["key"], 1)

        result, _ = remap.remap_output_devices(root, [target], {1: target})

        self.assertEqual(result[0].get("vjoy-id"), NEW)
        self.assertEqual(result[0].get("condition-type"), "vjoy")
        self.assertEqual(result[0].get("id"), "3")
        self.assertEqual(root[0].get("vjoy-id"), "1")

    def test_missing_output_guid_without_declaration_is_offered_and_remapped_everywhere(self):
        old = "dde8a0111f5251cca3315b66849e9991"
        target = maestro(data={"maestro_key": "maestro://127.0.0.1:8010/gex-1"})
        root = etree.fromstring(f'''<profile>
            <remap vjoy="{old}" axis="3"/>
            <split-axis device-low-vjoy-id="{old}" device-high-vjoy-id="{old}"/>
            <macro><actions><vjoy device-guid="{old}" vjoy-id="0" input-type="button" input-id="2"/></actions></macro>
            <variable type="VirtualInput" vjoy-id="{old}"/>
            <start><devices><device device-guid="{old}"><axis id="1" value="0.5"/></device></devices></start>
        </profile>''')
        rows = remap.output_device_sources(root, [target])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], old)
        self.assertEqual(rows[0]["suggested-guid"], NEW)
        result, changes = remap.remap_output_devices(root, [target], {old: target})
        self.assertTrue(changes)
        self.assertNotIn(old, etree.tostring(result).decode())
        self.assertEqual(result.find("remap").get("vjoy"), NEW)
        self.assertEqual(result.find("./start/devices/device").get("device-guid"), NEW)
        self.assertIn(old, etree.tostring(root).decode())

    def test_unknown_output_guid_can_be_manually_mapped_without_guessing(self):
        root = etree.fromstring(f'<profile><remap vjoy="{OLD}" button="4"/></profile>')
        rows = remap.output_device_sources(root, [maestro()])
        self.assertEqual(rows[0]["key"], OLD)
        self.assertNotIn("suggested-guid", rows[0])
        result, _ = remap.remap_output_devices(root, [maestro()], {OLD: maestro()})
        self.assertEqual(result[0].get("vjoy"), NEW)

    def test_maestro_guid_stored_in_virtual_id_is_offered_and_replaced(self):
        root = etree.fromstring(f'<profile><vjoyremap device-type="Maestro" virtual-id="{OLD}" axis="3"/></profile>')
        rows = remap.output_device_sources(root, [maestro()])
        self.assertEqual(rows[0]["key"], OLD)
        result, _ = remap.remap_output_devices(root, [maestro()], {OLD: maestro()})
        self.assertEqual(result[0].get("virtual-id"), "7")

    def test_modern_outputs_use_stable_identity_and_actual_slot(self):
        root = etree.fromstring('<profile><vjoyremap device-type="VJoy" virtual-id="1" axis="3"/><vjoyremap device-type="Maestro" virtual-id="2" button="5"/></profile>')
        original = etree.tostring(root)
        result, changes = remap.remap_vjoy_outputs(root, [maestro()])
        self.assertEqual(result[0].attrib, {"device-type": "Maestro", "virtual-id": "7", "axis": "3"})
        self.assertEqual(result[1].get("virtual-id"), "2")
        self.assertEqual(len(changes), 1)
        self.assertEqual(etree.tostring(root), original)

    def test_legacy_outputs_use_guids_and_preserve_input_numbers(self):
        root = etree.fromstring('<profile><vjoyremap vjoy="1" hat="2"/><remap vjoy="1" button="8"/><split-axis device-low-vjoy-id="1" device-high-vjoy-id="1" device-low-axis="2"/><macro><actions><vjoy vjoy-id="1" input-type="button" input-id="6"/></actions></macro><merge-axis><vjoy vjoy-id="1" axis="4"/></merge-axis></profile>')
        result, changes = remap.remap_vjoy_outputs(root, [maestro()])
        self.assertEqual(result[0].get("device-type"), "Maestro")
        self.assertNotIn("vjoy", result[0].attrib)
        self.assertEqual(result[0].get("hat"), "2")
        self.assertEqual(result[1].get("vjoy"), NEW)
        self.assertEqual(result[1].get("button"), "8")
        self.assertEqual(result[2].get("device-high-vjoy-id"), NEW)
        self.assertEqual(result[2].get("device-low-axis"), "2")
        self.assertEqual(result.find(".//actions/vjoy").get("device-guid"), NEW)
        self.assertEqual(result.find(".//actions/vjoy").get("input-id"), "6")
        self.assertEqual(result.find(".//merge-axis/vjoy").get("vjoy-id"), NEW)
        self.assertEqual(len(changes), 1)

    def test_missing_ambiguous_or_unavailable_equivalents_reject_conversion(self):
        root = etree.fromstring('<profile><vjoyremap virtual-id="1"/></profile>')
        for devices in ([], [maestro(), maestro()], [maestro(connected=False)],
                        [maestro(virtual_id=-1)], [maestro(disabled=True)],
                        [maestro(data={"maestro_hid_order_valid": False})]):
            with self.subTest(devices=devices), self.assertRaisesRegex(ValueError, "Maestro equivalent"):
                remap.remap_vjoy_outputs(root, devices)
        self.assertIsNone(root[0].get("device-type"))

    def test_maestro_key_takes_precedence_over_display_name(self):
        root = etree.fromstring('<profile><vjoyremap virtual-id="1"/></profile>')
        result, changes = remap.remap_vjoy_outputs(root, [maestro(name="Custom name", data={"maestro_key": "bridge/gex-1"})])
        self.assertEqual(result[0].get("virtual-id"), "7")
        self.assertEqual(len(changes), 1)

    def test_native_vjoy_guid_and_legacy_sentinel_are_converted(self):
        root = etree.fromstring(f'<profile><remap vjoy="{OLD}" button="9"/><vjoyremap virtual-id="-1" vjoy="1" axis="2"/></profile>')
        native = NS(device_type=NS(name="VJoy"), device_guid=OLD, vjoy_id=1)
        result, changes = remap.remap_vjoy_outputs(root, [native, maestro()])
        self.assertEqual(result[0].get("vjoy"), NEW)
        self.assertEqual(result[1].get("virtual-id"), "7")
        self.assertEqual(result[1].get("axis"), "2")
        self.assertEqual(len(changes), 1)

    def test_existing_maestro_guids_are_unchanged(self):
        root = etree.fromstring(f'<profile><remap vjoy="{NEW}"/><macro><actions><vjoy vjoy-id="1" device-guid="{NEW}" input-type="button"/></actions></macro></profile>')
        result, changes = remap.remap_vjoy_outputs(root, [maestro()])
        self.assertEqual(etree.tostring(result), etree.tostring(root))
        self.assertEqual(changes, [])


class SelectedOutputRemapChecks(unittest.TestCase):
    def test_unchecked_outputs_and_their_startup_values_remain_unchanged(self):
        root = etree.fromstring('<profile><vjoyremap virtual-id="1" axis="2"/><vjoyremap virtual-id="2" button="3"/><settings><vjoy id="1"><axis id="2" value="0.4" enabled="True"/></vjoy><vjoy id="2"><axis id="3" value="0.7" enabled="True"/></vjoy></settings></profile>')
        target = maestro(name="gex-3", slot=9)
        result, changes = remap.remap_output_devices(root, [target], {1: target})
        self.assertEqual(result[0].get("virtual-id"), "9")
        self.assertEqual(result[0].get("device-type"), "Maestro")
        self.assertEqual(etree.tostring(result[1]), etree.tostring(root[1]))
        self.assertEqual([n.get("id") for n in result.findall("./settings/vjoy")], ["2"])
        self.assertEqual(result.find("./start/devices/device").get("device-guid"), NEW)
        self.assertEqual(result.find("./start/devices/device/axis").get("value"), "0.4")
        self.assertEqual(set(remap.vjoy_references(result)), {2})
        self.assertEqual(changes, ["vJoy 1 -> gex-3"])

    def test_unchecked_native_declarations_are_preserved(self):
        root = etree.fromstring(f'<profile><devices><device type="vjoy" name="vJoy (1)" device-guid="{OLD}" virtual-id="1"/><device type="vjoy" name="vJoy (2)" device-guid="{OTHER}" virtual-id="2"/></devices><remap vjoy="{OTHER}"/></profile>')
        result, _ = remap.remap_output_devices(root, [maestro()], {1: maestro()})
        self.assertEqual(etree.tostring(result.find("./devices/device[2]")), etree.tostring(root.find("./devices/device[2]")))
        self.assertEqual(result.find("remap").get("vjoy"), OTHER)

    def test_existing_maestro_actions_and_startup_can_change_target(self):
        source = maestro()
        target = maestro(name="gex-2", slot=11, device_guid=OTHER)
        root = etree.fromstring(f'<profile><vjoyremap device-type="Maestro" virtual-id="7" axis="3"/><remap vjoy="{NEW}" button="2"/><start><devices><device device-guid="{NEW}"><axis id="3" value="-0.5" enabled="True"/></device></devices></start></profile>')
        rows = remap.output_device_sources(root, [source, target])
        self.assertEqual(len(rows), 1)
        result, _ = remap.remap_output_devices(root, [source, target], {NEW: target})
        self.assertEqual(result[0].get("virtual-id"), "11")
        self.assertEqual(result[0].get("axis"), "3")
        self.assertEqual(result[1].get("vjoy"), OTHER)
        self.assertEqual(result.find("./start/devices/device").get("device-guid"), OTHER)
        self.assertEqual(result.find("./start/devices/device/axis").get("value"), "-0.5")

    def test_output_swaps_use_original_slots_and_guids(self):
        first = maestro()
        second = maestro(name="gex-2", slot=11, device_guid=OTHER)
        root = etree.fromstring(f'<profile><vjoyremap device-type="Maestro" virtual-id="7"/><vjoyremap device-type="Maestro" virtual-id="11"/><remap vjoy="{NEW}"/><remap vjoy="{OTHER}"/></profile>')
        result, _ = remap.remap_output_devices(root, [first, second], {NEW: second, OTHER: first})
        self.assertEqual([n.get("virtual-id") for n in result.findall("vjoyremap")], ["11", "7"])
        self.assertEqual([n.get("vjoy") for n in result.findall("remap")], [OTHER, NEW])

    def test_unavailable_and_duplicate_targets_are_rejected(self):
        root = etree.fromstring('<profile><vjoyremap virtual-id="1"/><vjoyremap virtual-id="2"/></profile>')
        for mapping in ({1: maestro(connected=False)}, {1: maestro(), 2: maestro()}):
            with self.assertRaises(ValueError):
                remap.remap_output_devices(root, [maestro()], mapping)

    def test_existing_mapped_maestro_destination_is_protected(self):
        first = maestro()
        second = maestro(name="gex-2", slot=11, device_guid=OTHER)
        root = etree.fromstring(f'<profile><devices><device type="maestro" device-guid="{NEW}" virtual-id="7"><mode><axis><container/></axis></mode></device><device type="maestro" device-guid="{OTHER}" virtual-id="11"><mode><axis><container/></axis></mode></device></devices><vjoyremap device-type="Maestro" virtual-id="7"/></profile>')
        with self.assertRaisesRegex(ValueError, "already has mappings"):
            remap.remap_output_devices(root, [first, second], {NEW: second})
        self.assertEqual(root.find("./devices/device").get("device-guid"), NEW)

    def test_mixed_provider_remap_does_not_remap_newly_converted_actions_twice(self):
        first = maestro()
        second = maestro(name="gex-2", slot=11, device_guid=OTHER)
        root = etree.fromstring('<profile><vjoyremap virtual-id="1" axis="2"/><vjoyremap device-type="Maestro" virtual-id="7" button="3"/></profile>')
        result, _ = remap.remap_output_devices(root, [first, second], {1: first, NEW: second})
        self.assertEqual([n.get("virtual-id") for n in result], ["7", "11"])

    def test_slot_without_device_metadata_can_be_remapped_explicitly(self):
        root = etree.fromstring('<profile><vjoyremap device-type="Maestro" virtual-id="3" button="4"/></profile>')
        target = maestro()
        rows = remap.output_device_sources(root, [target])
        result, _ = remap.remap_output_devices(root, [target], {rows[0]["key"]: target})
        self.assertEqual(result[0].get("virtual-id"), "7")


class ProfileFailoverReloadChecks(unittest.TestCase):
    def configure(self, root, installed=False):
        tree = ast.parse((ROOT / "gremlin/base_profile.py").read_bytes())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Profile")
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_configure_vjoy_failover")
        config = NS(vjoy_failover=True, vjoy_installed=installed)
        handling = NS(clearVjoyDevices=Mock(), configure_vjoy_failover=Mock())
        namespace = dict(gremlin=NS(config=NS(Configuration=lambda: config), joystick_handling=handling),
                         parse_guid=lambda value: value, syslog=logging.getLogger(__name__))
        exec(compile(ast.Module(body=[method], type_ignores=[]), "base_profile.py", "exec"), namespace)
        with patch.dict(sys.modules, {"gremlin.device_remap": remap}):
            namespace[method.name](None, root)
        return config, handling

    def test_full_xml_conversion_stays_out_of_failover_after_save_and_reload(self):
        root = etree.fromstring(f'''<profile><devices>
          <device type="vjoy" name="vJoy Device (1)" device-guid="{OLD}" virtual-id="1">
            <mode name="Default"><axis id="2"><container id="kept">
              <vjoyremap virtual-id="1" axis="3"/>
            </container></axis></mode>
          </device>
          <device type="maestro" name="gex-1" device-guid="{NEW}"/>
        </devices><settings>
          <vjoy-input id="1" enabled="False"/>
          <vjoy id="1"><axis id="2" value="0.4" enabled="True"/></vjoy>
        </settings><start><devices><device device-guid="{OLD}">
          <button id="3" value="True"/>
        </device></devices></start>
        <macro><actions><vjoy device-guid="{OLD}" vjoy-id="1" input-type="button" input-id="8"/></actions></macro>
        <split-axis device-low-vjoy-id="1" device-high-vjoy-id="1"/>
        <merge-axis><vjoy vjoy-id="1" axis-id="4"/></merge-axis>
        <plugins><variable type="VirtualInput" vjoy-id="1" input-id="5"/></plugins>
        <condition device-guid="{OLD}"/>
        </profile>''')
        self.assertTrue(self.configure(root)[0].vjoy_failover)
        result, changes = remap.remap_vjoy_outputs(root, [maestro()])
        self.assertEqual(len(changes), 1)
        self.assertEqual(remap.vjoy_references(result), {})
        self.assertEqual(len(result.findall("./devices/device")), 1)
        device = result.find("./devices/device")
        self.assertEqual(device.get("type"), "maestro")
        self.assertEqual(device.get("virtual-id"), "7")
        self.assertEqual(device.find(".//container").get("id"), "kept")
        selection = result.find("./settings/maestro-input")
        self.assertEqual(selection.get("guid"), NEW)
        self.assertEqual(selection.get("enabled"), "False")
        self.assertIsNone(result.find("./settings/vjoy"))
        startup = result.find("./start/devices/device")
        self.assertEqual(len(result.findall("./start/devices/device")), 1)
        self.assertEqual(startup.get("device-guid"), NEW)
        self.assertEqual(startup.find("axis").attrib, {"id": "2", "value": "0.4", "enabled": "True"})
        self.assertEqual(startup.find("button").get("id"), "3")
        self.assertEqual(result.find(".//actions/vjoy").get("device-guid"), NEW)
        self.assertEqual(result.find(".//variable").get("vjoy-id"), NEW)
        self.assertEqual(result.find("condition").get("device-guid"), NEW)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.xml"
            path.write_bytes(etree.tostring(root))
            remap.write_remapped_profile(path, result)
            config, handling = self.configure(etree.parse(str(path)).getroot())
        self.assertFalse(config.vjoy_failover)
        handling.configure_vjoy_failover.assert_not_called()
        # Repeating the operation is harmless and finds no native references.
        again, changes = remap.remap_vjoy_outputs(result, [maestro()])
        self.assertEqual(etree.tostring(again), etree.tostring(result))
        self.assertEqual(changes, [])

    def test_all_legacy_outputs_enable_failover_until_converted(self):
        for xml in (
            '<vjoyremap virtual-id="-1" vjoy="1"/>',
            '<macro><actions><vjoy vjoy-id="1" input-type="button"/></actions></macro>',
            '<split-axis device-low-vjoy-id="1" device-high-vjoy-id="1"/>',
            '<merge-axis><vjoy vjoy-id="1"/></merge-axis>',
            '<plugins><variable type="VirtualInput" vjoy-id="1"/></plugins>',
            '<settings><vjoy id="1"><axis id="1" value="0.5"/></vjoy></settings>',
            '<settings><vjoy-input id="1"/></settings>',
            f'<vjoy-devices><vjoy-device device-guid="{OLD}" name="vJoy Device (1)" vjoy-id="1"/></vjoy-devices>',
        ):
            with self.subTest(xml=xml):
                root = etree.fromstring(f"<profile>{xml}</profile>")
                config, handling = self.configure(root)
                self.assertTrue(config.vjoy_failover)
                self.assertEqual(handling.configure_vjoy_failover.call_args.args[0], 1)
                result, _ = remap.remap_vjoy_outputs(root, [maestro()])
                self.assertFalse(self.configure(result)[0].vjoy_failover)

    def test_maestro_macro_guid_overrides_legacy_vjoy_id(self):
        root = etree.fromstring(f'<profile><macro><actions><vjoy vjoy-id="1" device-guid="{NEW}" input-type="button"/></actions></macro></profile>')
        self.assertFalse(self.configure(root)[0].vjoy_failover)

    def test_visibility_filters_do_not_enable_failover_or_require_targets(self):
        root = etree.fromstring(f'<profile><settings><input-filter><device name="VJoy 8/128/0 (5)" device="{OLD}"/></input-filter></settings><vjoyremap device-type="Maestro" virtual-id="0"/></profile>')
        self.assertFalse(self.configure(root)[0].vjoy_failover)
        result, changes = remap.remap_vjoy_outputs(root, [])
        self.assertEqual(etree.tostring(result), etree.tostring(root))
        self.assertEqual(changes, [])

    def test_filter_guid_can_identify_a_legacy_output_without_driver(self):
        root = etree.fromstring(f'<profile><settings><input-filter><device name="VJoy 8/128/0 (1)" device="{OLD}"/></input-filter></settings><remap vjoy="{OLD}"/></profile>')
        self.assertTrue(self.configure(root)[0].vjoy_failover)
        result, changes = remap.remap_vjoy_outputs(root, [maestro()])
        self.assertEqual(result.find("remap").get("vjoy"), NEW)
        self.assertEqual(result.find(".//input-filter/device").get("name"), "gex-1")
        self.assertEqual(len(changes), 1)

    def test_native_driver_resets_previous_failover(self):
        config, handling = self.configure(etree.fromstring('<profile><remap vjoy="1"/></profile>'), installed=True)
        self.assertFalse(config.vjoy_failover)
        handling.configure_vjoy_failover.assert_not_called()

    def test_mapped_maestro_declaration_is_not_overwritten(self):
        root = etree.fromstring(f'<profile><devices><device type="vjoy" name="vJoy Device (1)" device-guid="{OLD}"><mode><axis><container/></axis></mode></device><device type="maestro" device-guid="{NEW}"><mode><axis><container/></axis></mode></device></devices></profile>')
        with self.assertRaisesRegex(ValueError, "already has mappings"):
            remap.remap_vjoy_outputs(root, [maestro()])


class DialogChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtGui, QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        # Load the actual UI controls without importing the joystick drivers.
        tree = ast.parse((ROOT / "gremlin/ui/ui_common.py").read_bytes())
        names = {"QDataComboBox", "HtmlItemDelegate", "QHtmlDataComboBox", "QRoundedGroupBox"}
        widgets = ast.Module(body=[node for node in tree.body if getattr(node, "name", None) in names],
                             type_ignores=[])
        combo_namespace = dict(
            QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, Qt=QtCore.Qt, QSize=QtCore.QSize, Callable=Callable,
            QTextDocument=QtGui.QTextDocument, QComboBox=QtWidgets.QComboBox,
            QStyledItemDelegate=QtWidgets.QStyledItemDelegate, Buttons=NS(_default_parent=None),
            gremlin=NS(config=NS(Configuration=lambda: NS(dropdown_use_mouse_wheel=True)),
                       shared_state=NS(is_dark_theme=True)),
        )
        colors = NS(groupBoxGreenColor=lambda: "#0f8633", groupBoxBlueColor=lambda: "#78c5ff")
        combo_namespace["Color"] = lambda: colors
        exec(compile(widgets, "gremlin/ui/ui_common.py", "exec"), combo_namespace)
        common = ModuleType("gremlin.ui.ui_common")
        class RememberDialog(QtWidgets.QDialog):
            def __init__(self, name, parent=None, width=None, height=None):
                super().__init__(parent)
        def container(widgets, **kwargs):
            result = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(result)
            for widget in widgets:
                layout.addWidget(widget)
            return result
        common.QInfoBox = QtWidgets.QLabel
        common.Color = combo_namespace["Color"]
        common.MessageBoxYesNo = Mock()
        common.QRememberDialog = RememberDialog
        common.QRoundedGroupBox = combo_namespace["QRoundedGroupBox"]
        common.QWarningWidget = QtWidgets.QLabel
        common.QDataCheckbox = QtWidgets.QCheckBox
        common.QDataComboBox = combo_namespace["QDataComboBox"]
        common.QHtmlDataComboBox = combo_namespace["QHtmlDataComboBox"]
        common.QDataPushButton = QtWidgets.QPushButton
        common.getHContainer = container
        common.getVContainer = lambda widget, **kwargs: container([widget])
        services = ModuleType("gremlin")
        services.__path__ = []
        services.shared_state = NS(is_dark_theme=True)
        with patch.dict(sys.modules, {"gremlin": services, "gremlin.shared_state": services.shared_state,
                                      "gremlin.device_remap": remap, "gremlin.ui.ui_common": common}):
            cls.dialog_type = load("device_remap_dialog_checks", ROOT / "gremlin/ui/device_remap.py").ProfileDeviceRemapDialog

    def setUp(self):
        target = NS(name="L-VPC Stick WarBRD", device_guid=NEW, connected=True, is_virtual=False)
        self.apply = Mock()
        self.dialog = self.dialog_type(etree.tostring(profile()), [target], self.apply)
        self.addCleanup(self.dialog.close)

    def test_suggestion_selection_and_apply(self):
        # Old device is proposed; the already connected empty target is unchecked.
        self.assertTrue(self.dialog._rows[0][1].isChecked())
        self.assertTrue(self.dialog._apply_button.isEnabled())
        self.dialog._select(False)
        self.assertFalse(self.dialog._apply_button.isEnabled())
        self.dialog._rows[0][1].setChecked(True)
        self.dialog._apply(True)
        self.apply.assert_called_once()
        self.assertEqual(self.dialog.result(), 1)

    def test_missing_old_maestro_guid_is_visible_with_native_guid_suggested(self):
        old = "dde8a0111f5251cca3315b66849e9991"
        target = maestro(data={"maestro_key": "maestro://127.0.0.1:8010/gex-1"})
        root = etree.fromstring(f'<profile><remap vjoy="{old}" axis="3"/></profile>')
        dialog = self.dialog_type(etree.tostring(root), [target], self.apply)
        self.addCleanup(dialog.close)
        self.assertEqual(len(dialog._output_rows), 1)
        source, check, combo = dialog._output_rows[0]
        self.assertEqual(source["device-guid"], old)
        self.assertIs(combo.currentData(), target)
        self.assertTrue(check.isChecked())
        result = dialog._replacement_root()
        self.assertEqual(result[0].get("vjoy"), NEW)

    def test_choosing_gex_output_for_an_unknown_guid_selects_the_row(self):
        root = etree.fromstring(f'<profile><remap vjoy="{OLD}" axis="3"/></profile>')
        dialog = self.dialog_type(etree.tostring(root), [maestro()], self.apply)
        self.addCleanup(dialog.close)
        _, check, combo = dialog._output_rows[0]
        self.assertFalse(dialog._apply_button.isEnabled())
        combo.setCurrentIndex(1)
        self.assertTrue(check.isChecked())
        self.assertTrue(dialog._apply_button.isEnabled())
        check.setChecked(False)
        self.assertFalse(dialog._apply_button.isEnabled())
        combo.setCurrentIndex(0)
        combo.setCurrentIndex(1)
        dialog._apply(True)
        self.assertEqual(self.apply.call_args.args[0][0].get("vjoy"), NEW)

    def test_gex_output_is_automatically_checked_for_only_one_suggested_row(self):
        root = etree.fromstring('''<profile>
            <vjoyremap virtual-id="1" button="2"/>
            <remap vjoy="dde8a0111f5251cca3315b66849e9991" axis="3"/>
        </profile>''')
        target = maestro(data={"maestro_key": "maestro://127.0.0.1:8010/gex-1"})
        dialog = self.dialog_type(etree.tostring(root), [target], self.apply)
        self.addCleanup(dialog.close)
        maestro_row, vjoy_row = dialog._output_rows
        self.assertIs(maestro_row[2].currentData(), target)
        self.assertIs(vjoy_row[2].currentData(), target)
        self.assertTrue(maestro_row[1].isChecked())
        self.assertFalse(vjoy_row[1].isChecked())
        self.assertTrue(dialog._apply_button.isEnabled())
        vjoy_row[1].setChecked(True)
        self.assertFalse(dialog._apply_button.isEnabled())
        self.assertIn('both target "gex-1"', dialog._status.text())
        vjoy_row[1].setChecked(False)
        result = dialog._replacement_root()
        self.assertEqual(result.find("remap").get("vjoy"), NEW)
        self.assertIsNone(result.find("vjoyremap").get("device-type"))

    def test_output_only_conversion_is_preselected_and_previewed(self):
        root = etree.fromstring('<profile><devices/><vjoyremap device-type="VJoy" virtual-id="1" button="4"/></profile>')
        dialog = self.dialog_type(etree.tostring(root), [maestro()], self.apply)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog._output_rows[0][1].isChecked())
        self.assertTrue(dialog._apply_button.isEnabled())
        self.assertIn("vJoy 1 -> gex-1", dialog._status.text())
        dialog._output_rows[0][1].setChecked(False)
        self.assertFalse(dialog._apply_button.isEnabled())
        dialog._output_rows[0][1].setChecked(True)
        dialog._apply(True)
        result = self.apply.call_args.args[0]
        self.assertEqual(result.find("vjoyremap").get("device-type"), "Maestro")
        self.assertEqual(result.find("vjoyremap").get("button"), "4")

    def test_output_conversion_and_input_remap_apply_together(self):
        root = profile()
        etree.SubElement(root, "vjoyremap", {"virtual-id": "1"})
        target = NS(name="L-VPC Stick WarBRD", device_guid=NEW, connected=True, is_virtual=False)
        dialog = self.dialog_type(etree.tostring(root), [target, maestro(device_guid=OTHER)], self.apply)
        self.addCleanup(dialog.close)
        dialog._output_rows[0][1].setChecked(True)
        self.assertTrue(dialog._apply_button.isEnabled())
        result = dialog._replacement_root()
        self.assertEqual(result.find("./devices/device").get("device-guid"), NEW)
        self.assertEqual(result.find("vjoyremap").get("device-type"), "Maestro")

    def test_missing_equivalent_disables_apply(self):
        root = profile()
        etree.SubElement(root, "vjoyremap", {"virtual-id": "1"})
        dialog = self.dialog_type(etree.tostring(root), [], self.apply)
        self.addCleanup(dialog.close)
        dialog._output_rows[0][1].setChecked(True)
        self.assertFalse(dialog._apply_button.isEnabled())
        self.assertIn("Choose a target output", dialog._status.text())

    def test_output_rows_offer_other_gex_targets_and_preserve_unchecked_rows(self):
        root = etree.fromstring('<profile><devices/><vjoyremap virtual-id="1" axis="3"/><vjoyremap virtual-id="2" button="4"/></profile>')
        second = maestro(name="gex-2", slot=11, device_guid=OTHER)
        dialog = self.dialog_type(etree.tostring(root), [maestro(), second], self.apply)
        self.addCleanup(dialog.close)
        self.assertEqual(len(dialog._output_rows), 2)
        source, check, combo = next(row for row in dialog._output_rows if row[0]["key"] == 1)
        self.assertEqual(combo.currentData().name, "gex-1")
        self.assertTrue(check.isChecked())
        other_check = next(row[1] for row in dialog._output_rows if row[0]["key"] == 2)
        other_check.setChecked(False)
        combo.setCurrentIndex(next(i for i in range(1, combo.count()) if combo.itemData(i).name == "gex-2"))
        check.setChecked(True)
        result = dialog._replacement_root()
        self.assertEqual(result.findall("vjoyremap")[0].get("virtual-id"), "11")
        self.assertIsNone(result.findall("vjoyremap")[1].get("device-type"))
        self.assertIn("vJoy 1 -> gex-2", dialog._status.text())
        dialog._select(True)
        self.assertTrue(all(check.isChecked() for _, check, _ in dialog._output_rows))
        self.assertFalse(dialog._apply_button.isEnabled())  # Both selected outputs target gex-2.
        dialog._select(False)
        self.assertFalse(dialog._apply_button.isEnabled())

    def test_input_and_output_rows_show_connected_suggested_and_manual_status(self):
        from PySide6 import QtWidgets

        unknown_input = "0000000000000000000000000000000a"
        old_maestro = "0000000000000000000000000000000b"
        unknown_output = "0000000000000000000000000000000c"
        native_guid = "0000000000000000000000000000000d"
        root = profile()
        devices = root.find("devices")
        etree.SubElement(devices, "device", type="joystick", name="Other stick", **{"device-guid": unknown_input})
        etree.SubElement(devices, "device", type="maestro", name="Panel", **{
            "device-guid": old_maestro, "virtual-id": "18",
        })
        etree.SubElement(root, "vjoyremap", **{"device-type": "Maestro", "virtual-id": "18", "button": "2"})
        etree.SubElement(root, "vjoyremap", **{"device-type": "VJoy", "virtual-id": "1", "button": "3"})
        etree.SubElement(root, "remap", vjoy=unknown_output, axis="1")
        stick = NS(name="L-VPC Stick WarBRD", device_guid=NEW, connected=True, is_virtual=False)
        native = NS(name="vJoy 1", device_guid=native_guid, device_type=NS(name="VJoy"), connected=True,
                    is_virtual=True, vjoy_id=1, virtual_id=1, data={})
        panel = maestro(name="Panel", device_guid=OTHER, slot=18)
        expected = {
            "inputDevices": {NEW: ("Connected", NEW), OLD: ("Suggested", NEW), unknown_input: ("Manual", None)},
            "outputDevices": {
                1: ("Connected", native_guid), old_maestro: ("Suggested", OTHER), unknown_output: ("Manual", None),
            },
        }
        for startup_missing in (None, ()):
            with self.subTest(startup=startup_missing is not None):
                dialog = self.dialog_type(etree.tostring(root), [stick, native, panel], self.apply,
                                          startup_missing=startup_missing, saved_root=root)
                self.addCleanup(dialog.close)
                for section_name, rows in (("inputDevices", dialog._rows), ("outputDevices", dialog._output_rows)):
                    grid = dialog.findChild(QtWidgets.QGroupBox, section_name).layout()
                    self.assertEqual(len(rows), len(expected[section_name]))
                    for index, (source, check, combo) in enumerate(rows, 1):
                        status = grid.itemAtPosition(index, 0).widget()
                        key = source["key"] if section_name == "outputDevices" else source.get("device-guid")
                        name, default = expected[section_name][key]
                        self.assertEqual(status.objectName(), f"deviceStatus{name}")
                        self.assertFalse(status.pixmap().isNull())
                        self.assertTrue(status.toolTip())
                        self.assertEqual(status.accessibleName(), status.toolTip())
                        self.assertEqual(getattr(combo.currentData(), "device_guid", None), default)
                        self.assertEqual(check.isChecked(), name == "Suggested")
                self.assertTrue(dialog._apply_button.isEnabled())
                dialog._select(True)
                self.assertTrue(dialog._apply_button.isEnabled())
                self.assertEqual(sum(check.isChecked() for _, check, _ in dialog._rows + dialog._output_rows), 2)

    def test_select_all_validates_once_for_the_entire_grid(self):
        root = profile()
        etree.SubElement(root, "vjoyremap", {"virtual-id": "1"})
        target = NS(name="L-VPC Stick WarBRD", device_guid=NEW, connected=True, is_virtual=False)
        dialog = self.dialog_type(etree.tostring(root), [target, maestro(device_guid=OTHER)], self.apply)
        self.addCleanup(dialog.close)
        with patch.object(dialog, "_replacement_root", wraps=dialog._replacement_root) as validate:
            dialog._select(True)
            self.assertEqual(validate.call_count, 1)
            dialog._select(False)
            self.assertEqual(validate.call_count, 2)

    def test_output_without_matching_gex_can_choose_another_gex(self):
        root = etree.fromstring('<profile><devices/><vjoyremap virtual-id="1" button="4"/></profile>')
        second = maestro(name="gex-2", slot=11, device_guid=OTHER)
        dialog = self.dialog_type(etree.tostring(root), [second], self.apply)
        self.addCleanup(dialog.close)
        _, check, combo = dialog._output_rows[0]
        self.assertIsNone(combo.currentData())
        check.setChecked(True)
        self.assertFalse(dialog._apply_button.isEnabled())
        combo.setCurrentIndex(1)
        self.assertTrue(dialog._apply_button.isEnabled())
        self.assertEqual(dialog._replacement_root().find("vjoyremap").get("virtual-id"), "11")

    def test_existing_maestro_output_is_listed_and_requires_a_different_target(self):
        root = etree.fromstring('<profile><devices/><vjoyremap device-type="Maestro" virtual-id="7" button="4"/></profile>')
        second = maestro(name="gex-2", slot=11, device_guid=OTHER)
        dialog = self.dialog_type(etree.tostring(root), [maestro(), second], self.apply)
        self.addCleanup(dialog.close)
        source, check, combo = dialog._output_rows[0]
        self.assertEqual(source["name"], "gex-1")
        check.setChecked(True)
        self.assertFalse(dialog._apply_button.isEnabled())
        combo.setCurrentIndex(next(i for i in range(1, combo.count()) if combo.itemData(i).name == "gex-2"))
        self.assertTrue(dialog._apply_button.isEnabled())
        self.assertEqual(dialog._replacement_root().find("vjoyremap").get("virtual-id"), "11")
        from PySide6 import QtWidgets
        titles = {section.title() for section in dialog.findChildren(QtWidgets.QGroupBox)}
        self.assertEqual(titles, {"Input devices", "Output devices"})
        self.assertTrue(dialog.findChild(QtWidgets.QGroupBox, "outputDevices").styleSheet())

    def test_connected_device_can_be_remapped_without_validation_exceptions(self):
        devices = [
            NS(name="LEFT VPC Stick WarBRD", device_guid=OLD, connected=True, is_virtual=False),
            NS(name="L-VPC Stick WarBRD", device_guid=NEW, connected=True, is_virtual=False),
            NS(name="New joystick", device_guid=OTHER, connected=True, is_virtual=False),
        ]
        raised = []
        filename = self.dialog_type._validate.__code__.co_filename
        def trace(frame, event, arg):
            if frame.f_code.co_filename == filename and event == "exception" and arg[0] is ValueError:
                raised.append(str(arg[1]))
            return trace
        previous_trace = sys.gettrace()
        sys.settrace(trace)
        try:
            dialog = self.dialog_type(etree.tostring(profile()), devices, self.apply)
            self.addCleanup(dialog.close)
            self.assertEqual(len(dialog._rows), 2)
            self.assertTrue(all(not check.isChecked() for _, check, _ in dialog._rows))
            self.assertFalse(dialog._apply_button.isEnabled())
            source, check, combo = next(row for row in dialog._rows if row[0].get("device-guid") == OLD)
            check.setChecked(True)
            self.assertFalse(dialog._apply_button.isEnabled())
            combo.setCurrentIndex(next(i for i in range(1, combo.count()) if combo.itemData(i).device_guid == OLD))
            self.assertFalse(dialog._apply_button.isEnabled())
            combo.setCurrentIndex(next(i for i in range(1, combo.count()) if combo.itemData(i).device_guid == OTHER))
            self.assertTrue(dialog._apply_button.isEnabled())
            dialog._apply(True)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(raised, [])
        result = self.apply.call_args.args[0]
        moved = next(node for node in result.findall("./devices/device") if node.get("device-guid") == OTHER)
        self.assertEqual(moved.get("name"), "New joystick")
        self.assertIsNotNone(moved.find(".//container"))

    def test_empty_selection_never_saves_or_reloads(self):
        self.dialog._select(False)
        self.assertIsNone(self.dialog._replacement_root())
        self.dialog._apply(True)
        self.apply.assert_not_called()
        self.assertEqual(self.dialog.result(), 0)

    def test_manual_alternate_target(self):
        alternate = NS(name="Different stick", device_guid=OTHER)
        combo = self.dialog._rows[0][2]
        combo.addItem(alternate.name, alternate)
        combo.setCurrentIndex(combo.count() - 1)
        self.assertTrue(self.dialog._apply_button.isEnabled())
        self.dialog._apply(True)
        changed = self.apply.call_args.args[0]
        self.assertEqual(changed.find("./devices/device").get("device-guid"), OTHER)

    def test_no_connected_devices(self):
        dialog = self.dialog_type(etree.tostring(profile()), [], self.apply)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog._apply_button.isEnabled())
        dialog._select(True)
        self.assertFalse(dialog._apply_button.isEnabled())
        dialog.reject()
        self.apply.assert_not_called()

    def test_cancel_does_not_apply(self):
        self.dialog.reject()
        self.apply.assert_not_called()

    def test_startup_preselects_replacement_guids_for_native_and_maestro_outputs(self):
        old_maestro = "dde8a0111f5251cca3315b66849e9991"
        saved = etree.fromstring(f"""<profile><devices>
            <vjoy-device type="vjoy" vjoy-id="1" device-guid="{OLD}"/>
            <device type="maestro" name="Panel" virtual-id="4" device-guid="{old_maestro}"/>
        </devices></profile>""")
        current = etree.fromstring(f"""<profile>
            <vjoyremap device-type="VJoy" virtual-id="1" button="2"/>
            <vjoyremap device-type="Maestro" virtual-id="4" axis="3"/>
            <start><devices><device device-guid="{OLD}"><button id="2" value="true"/></device></devices></start>
        </profile>""")
        native = NS(name="vJoy 1", device_guid=NEW, device_type=NS(name="VJoy"), connected=True,
                    is_virtual=True, vjoy_id=1, virtual_id=1, data={})
        panel = maestro(name="Panel", device_guid=OTHER, slot=8, data={"maestro_hid_order_valid": False})
        dialog = self.dialog_type(etree.tostring(current), [native, panel], self.apply, startup_missing=(),
                                  saved_root=saved)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.has_matches)
        self.assertTrue(dialog._apply_button.isEnabled())
        self.assertEqual({combo.currentData().device_guid for _, check, combo in dialog._output_rows
                          if check.isChecked()}, {NEW, OTHER})
        changed = dialog._replacement_root()
        self.assertEqual([node.get("virtual-id") for node in changed.findall("vjoyremap")], ["1", "8"])
        self.assertEqual(changed.find("./start/devices/device").get("device-guid"), NEW)
        self.assertEqual(changed.find("./start/devices/device/button").get("id"), "2")

    def test_startup_remaps_an_input_referenced_only_by_a_condition(self):
        saved = etree.fromstring(f'''<profile><devices>
            <device type="joystick" name="Panel" device-guid="{OLD}"/>
        </devices></profile>''')
        current = etree.fromstring(f'<profile><devices/><condition device-guid="{OLD}"/></profile>')
        panel = NS(name="Panel", device_guid=NEW, connected=True, is_virtual=False)
        dialog = self.dialog_type(etree.tostring(current), [panel], self.apply, startup_missing=(), saved_root=saved)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.has_matches)
        self.assertEqual(dialog._replacement_root().find("condition").get("device-guid"), NEW)

    def test_startup_ignores_ambiguous_matches_and_working_failover(self):
        root = etree.fromstring(f"""<profile>
            <devices><device type="joystick" name="Panel" device-guid="{OLD}"/></devices>
            <vjoyremap device-type="VJoy" virtual-id="1" button="2"/>
        </profile>""")
        panels = [NS(name="Panel", device_guid=guid, connected=True, is_virtual=False) for guid in (NEW, OTHER)]
        dialog = self.dialog_type(etree.tostring(root), [*panels, maestro()], self.apply, startup_missing=())
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.has_matches)

    def test_declining_confirmation_leaves_dialog_open_without_writing(self):
        from PySide6 import QtWidgets
        message = self.dialog._apply_confirmation.__globals__["MessageBoxYesNo"]
        message.reset_mock()
        self.dialog._apply_confirmation()
        message.call_args.kwargs["callback"](QtWidgets.QMessageBox.StandardButton.No)
        self.assertEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.apply.assert_not_called()

    def test_startup_apply_backs_up_and_reloads_the_edited_profile(self):
        from PySide6 import QtWidgets
        method = next(
            node for node in ast.walk(ast.parse((ROOT / "gremlinEx.py").read_bytes()))
            if isinstance(node, ast.FunctionDef) and node.name == "_show_profile_device_remap"
        )
        panel = NS(name="L-VPC Stick WarBRD", device_guid=NEW, connected=True, is_virtual=False)
        sidecar = Mock()
        gremlin = NS(joystick_handling=NS(all_joystick_devices=lambda: [panel], virtual_devices=list),
                     event_handler=NS(EventListener=lambda: NS(update_sidecar=sidecar)),
                     profile=NS(parse_profile_xml=etree.parse),
                     util=NS(centerDialog=Mock()))
        namespace = dict(os=os, gremlin=gremlin, QtWidgets=QtWidgets, syslog=logging.getLogger(__name__))
        exec(compile(ast.Module(body=[method], type_ignores=[]), "gremlinEx.py", "exec"), namespace)
        window = NS(_do_load_profile=Mock())
        dialog_type = self.dialog_type
        apply_on_exec = False

        class StartupDialog(dialog_type):
            def __init__(self, xml, devices, apply_changes, parent, **kwargs):
                super().__init__(xml, devices, apply_changes, **kwargs)

            def exec(self):
                if apply_on_exec:
                    self._apply(True)
                return self.result()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.xml"
            original = etree.tostring(profile())
            path.write_bytes(original)
            edited = profile()
            edited.set("unsaved-edit", "kept")
            model = NS(profile_file=path, to_xml=lambda: etree.tostring(edited))
            with patch.dict(sys.modules, {"gremlin.device_remap": remap,
                                          "gremlin.ui.device_remap": NS(ProfileDeviceRemapDialog=StartupDialog)}):
                self.assertFalse(namespace["_show_profile_device_remap"](window, model, ()))
                self.assertEqual(list(path.parent.glob("*.xml")), [path])
                self.assertEqual(path.read_bytes(), original)
                window._do_load_profile.assert_not_called()
                sidecar.emit.assert_not_called()

                apply_on_exec = True
                self.assertTrue(namespace["_show_profile_device_remap"](window, model, ()))
            backup, = path.parent.glob("*.guid-remap-*.xml")
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(etree.parse(path).getroot().get("unsaved-edit"), "kept")
            self.assertEqual(etree.parse(path).find("./devices/device").get("device-guid"), NEW)
            window._do_load_profile.assert_called_once_with(path)
            sidecar.emit.assert_called_once()

    def test_missing_target_and_failure_stay_open(self):
        self.dialog._rows[0][2].setCurrentIndex(0)
        self.assertFalse(self.dialog._apply_button.isEnabled())
        self.dialog._rows[0][2].setCurrentIndex(1)
        self.apply.side_effect = OSError("disk full")
        self.dialog._apply(True)
        self.assertEqual(self.dialog.result(), 0)
        self.assertIn("disk full", self.dialog._status.text())


if __name__ == "__main__":
    unittest.main()
