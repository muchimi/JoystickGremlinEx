"""Hardware-free classification checks: python tools/test_device_summary_virtual.py."""

import ast
from enum import IntEnum
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[1]


def definitions(path, select, namespace):
    tree = ast.parse((ROOT / path).read_bytes())
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    nodes = [node for node in tree.body if select(node)]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), path, "exec"), namespace)


TYPES = ModuleType("gremlin.types")
type_namespace = dict(IntEnum=IntEnum)
definitions("gremlin/types.py", lambda node: isinstance(node, ast.ClassDef)
            and node.name in ("DeviceType", "DeviceCategory"), type_namespace)
DeviceType = TYPES.DeviceType = type_namespace["DeviceType"]
DeviceCategory = TYPES.DeviceCategory = type_namespace["DeviceCategory"]
GREMLIN = ModuleType("gremlin")
GREMLIN.__path__ = []
GREMLIN.types = TYPES
GREMLIN.util = ModuleType("gremlin.util")
namespace = dict(GUID=uuid.UUID, DeviceType=DeviceType, DeviceCategory=DeviceCategory,
                 syslog=logging.getLogger("virtual-summary-checks"))
definitions("dinput/__init__.py", lambda node: (
    isinstance(node, ast.ClassDef) and node.name == "DeviceSummary"
) or (
    isinstance(node, ast.Assign) and all(isinstance(target, ast.Name)
                                       and target.id.startswith(("GEX_", "MAESTRO_", "VJOY_")) for target in node.targets)
), namespace)
DeviceSummary = namespace["DeviceSummary"]


def profile_fixture(path, class_name, methods):
    tree = ast.parse((ROOT / path).read_bytes())
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    definition.bases = []
    definition.decorator_list = []
    definition.body = [node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    scope = dict(gremlin=GREMLIN, dinput=NS(DeviceSummary=DeviceSummary), DeviceType=DeviceType)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, definition], type_ignores=[])), path, "exec"), scope)
    return scope[class_name]()


class VirtualSummaryChecks(unittest.TestCase):
    def setUp(self):
        modules = patch.dict(sys.modules, {"gremlin": GREMLIN, "gremlin.types": TYPES, "gremlin.util": GREMLIN.util})
        modules.start()
        self.addCleanup(modules.stop)

    def native(self, vendor, product, name="Controller", usage=4):
        device = DeviceSummary(NS(device_guid=str(uuid.uuid4()), vendor_id=vendor, product_id=product,
                                  joystick_id=0, name=name.encode(), axis_count=2, button_count=8,
                                  hat_count=1, usage_page=1, usage=usage, axis_map=[]))
        return device

    def test_catalog_test_joysticks_get_tabs_without_output_slot_selection(self):
        devices = [self.native(vendor, product, name) for vendor, product, name in (
            (0x046D, 0xC20E, "Logitech WingMan Formula GP"),
            (0x06A3, 0x075C, "Saitek X52 Flight Control System"),
            (0x044F, 0xB10A, "Thrustmaster T.16000M Joystick"),
        )]
        failover_outputs = [
            self.native(0x1209, 0x1000, "gex-1"),
            self.native(0xFEED, 0x8010, "GEX Custom Device 3"),
            self.native(0x1234, 0xBEAD, "vJoy - Virtual Joystick"),
        ]
        shown = devices + failover_outputs
        selected_inputs = set()
        handling = NS(display_devices=lambda profile: shown, virtual_input_candidates=lambda: failover_outputs,
                      getSpecialDevices=lambda: [], getConfigDevices=lambda: [])
        tree = ast.parse((ROOT / "gremlinEx.py").read_bytes())
        ui = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GremlinUi")
        method = next(node for node in ui.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_get_sorted_tab_map")
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        scope = dict(gremlin=GREMLIN, DeviceType=DeviceType, DeviceCategory=DeviceCategory)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[])),
                     "gremlinEx.py", "exec"), scope)
        window = NS(config=NS(tab_list={}, verbose_mode_ui_level=lambda level: False,
                              isDeviceVisible=lambda guid: True), profile=NS(settings=NS(
                                  getVirtualAsInput=lambda device: device.device_id in selected_inputs)))
        with patch.object(GREMLIN, "joystick_handling", handling, create=True), patch.object(
            GREMLIN.util, "normalize_guid", str, create=True
        ):
            saved_order = {i: (device.device_id, True) for i, device in enumerate(shown)}
            for selected in (None, *failover_outputs):
                selected_inputs.clear()
                if selected is not None:
                    selected_inputs.add(selected.device_id)
                for saved in ({}, saved_order):
                    with self.subTest(selected=selected.name if selected else None, saved=bool(saved)):
                        window.config.tab_list = saved
                        result = scope["_get_sorted_tab_map"](window)
                        expected_inputs = [] if selected is None else [selected]
                        self.assertCountEqual(result["physical"], devices)
                        self.assertCountEqual(result["sorted"], devices + expected_inputs)
                        self.assertCountEqual(result["maestro"], [device for device in expected_inputs
                                                               if device.device_type == DeviceType.Maestro])
                        self.assertCountEqual(result["vjoy"], [device for device in expected_inputs
                                                            if device.device_type == DeviceType.VJoy])
                        self.assertTrue(all(device.virtual_id == -1 for device in devices))

    def test_shared_vendor_ids_and_other_hardware_remain_physical(self):
        for vendor, product in ((0x1209, 0x0FFF), (0x1209, 0x1010), (0x1209, 0x2000),
                                (0x1234, 0x5678), (0x1234, 1), (0x045E, 0x028E), (0x054C, 0x05C4)):
            with self.subTest(vendor=vendor, product=product):
                device = self.native(vendor, product)
                self.assertEqual(device.device_type, DeviceType.Joystick)
                device.setVirtual(True)
                device.device_category = DeviceCategory.Virtual
                self.assertFalse(device.is_virtual)
                self.assertIs(device._is_virtual, False)
                self.assertEqual(device.device_category, DeviceCategory.Physical)

    def test_vjoy_driver_and_disconnected_vjoy_placeholders_are_virtual(self):
        device = self.native(0x1234, 0xBEAD, "vJoy - Virtual Joystick")
        self.assertEqual(device.device_type, DeviceType.VJoy)
        self.assertTrue(device.is_virtual)
        placeholder = DeviceSummary()
        placeholder.device_type = DeviceType.VJoy
        placeholder.setVirtual(True)
        self.assertTrue(placeholder.is_virtual)
        self.assertFalse(placeholder.connected)

    def test_all_reserved_gex_native_ids_are_virtual(self):
        for product in range(0x1000, 0x1010):
            with self.subTest(product=product):
                device = self.native(0x1209, product, "GEX controller")
                self.assertEqual(device.device_type, DeviceType.Maestro)
                self.assertTrue(device.is_virtual)
                self.assertEqual(device.virtual_id, product - 0x1000)

    def test_legacy_gex_name_requires_a_known_legacy_device_identity(self):
        for vendor, product in ((1, 1), (0xFEED, 0x8010)):
            with self.subTest(vendor=vendor, product=product):
                self.assertTrue(self.native(vendor, product, "GEX Custom Device 3").is_virtual)
                self.assertFalse(self.native(vendor, product, "Other Maestro client").is_virtual)
        self.assertFalse(self.native(0x045E, 0x028E, "GEX Custom Device 3").is_virtual)

    def test_maestro_type_alone_cannot_enable_virtual_without_gex_ownership(self):
        device = self.native(1, 1, "Other Maestro client")
        device.device_type = DeviceType.Maestro
        device.setVirtual(True)
        self.assertFalse(device.is_virtual)
        device.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-2"
        device.setVirtual(True)
        device.device_category = DeviceCategory.Virtual
        self.assertTrue(device.is_virtual)
        del device.data["maestro_key"]
        self.assertFalse(device.is_virtual)
        self.assertEqual(device.device_category, DeviceCategory.Physical)

    def test_type_changes_cannot_retain_a_stale_virtual_flag(self):
        device = self.native(0x1209, 0x1000, "GEX controller")
        device.setVirtual(True)
        device.device_type = DeviceType.Joystick
        self.assertFalse(device.is_virtual)
        self.assertEqual(device.device_category, DeviceCategory.Physical)
        device._is_virtual = True  # Simulate stale state from an older cache.
        self.assertFalse(device.is_virtual)

    def test_explicit_false_stays_false_until_enabled_again(self):
        device = self.native(0x1234, 0xBEAD)
        device.setVirtual(False)
        self.assertFalse(device.is_virtual)
        self.assertEqual(device.device_category, DeviceCategory.Physical)
        device.setVirtual(True)
        self.assertTrue(device.is_virtual)

    def test_special_device_categories_are_preserved(self):
        device = DeviceSummary()
        device.device_type = DeviceType.Keyboard
        device.device_category = DeviceCategory.Special
        device.setVirtual(True)
        self.assertFalse(device.is_virtual)
        self.assertTrue(device.is_special)
        self.assertEqual(device.device_category, DeviceCategory.Special)

    def test_profile_graph_cannot_force_physical_hardware_to_virtual(self):
        profile = profile_fixture("gremlin/profile_graph.py", "ProfileDeviceNode", {"virtual"})
        profile._device = self.native(0x045E, 0x028E)
        profile.virtual = True
        self.assertFalse(profile.virtual)
        profile._device = self.native(0x1234, 0xBEAD)
        profile.virtual = True
        self.assertTrue(profile.virtual)

    def test_profile_loading_keeps_disconnected_vjoy_placeholder_virtual(self):
        profile = profile_fixture("gremlin/base_profile.py", "Profile", {"_attach_device_summary"})
        GREMLIN.joystick_handling = NS(getDevice=lambda guid: None)
        node = NS()
        profile._attach_device_summary(node, uuid.uuid4(), DeviceType.VJoy, "VJoy 1")
        self.assertTrue(node.device.is_virtual)
        self.assertFalse(node.device.connected)
        self.assertEqual(node.device.device_type, DeviceType.VJoy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
