"""Hardware-free registry race checks: python tools/test_device_registry_refresh.py."""

import ast
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch


class DiscoveryStopped(Exception):
    pass


class RegistryRefreshChecks(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "gremlin/joystick_handling.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name in {"getDevice", "joystick_devices_initialization", "_device_list_signature",
                                         "scanDinput", "isDeviceValid", "_is_excluded_native_joystick"}]
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                                 *definitions], type_ignores=[])
        self.keyboard_guid = "keyboard-guid"
        self.keyboard = object()
        config = NS(verbose_mode_inputs=False, verbose_mode_vjoy=False, vjoy_installed=False)
        self.gremlin = ModuleType("gremlin")
        self.gremlin.util = ModuleType("gremlin.util")
        self.gremlin.config = NS(Configuration=lambda: config)
        self.gremlin.event_handler = NS(EventListener=lambda: NS(device_initialized=NS(emit=Mock())))
        self.namespace = dict(
            gremlin=self.gremlin, syslog=logging.getLogger(__name__),
            dinput=NS(GUID=str, DILL=NS(init=Mock())),
            vjoy=NS(VJoyMonitor=lambda: NS(stop=Mock())),
            _joystick_initialized=True, _last_device_signature=None,
            _joystick_init_lock=threading.Lock(), _device_registry_lock=threading.RLock(),
            _all_devices_map={self.keyboard_guid: self.keyboard},
            _maestro_failover_map={}, _maestro_devices_map={},
            parse_virtual_device_key=lambda key: key,
        )
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), self.namespace)

    def test_keyboard_remains_available_while_refresh_discovers_devices(self):
        scanning = threading.Event()
        finish = threading.Event()

        def discover():
            scanning.set()
            if not finish.wait(2):
                raise AssertionError("Discovery was not released")
            raise DiscoveryStopped()

        self.namespace["dinput"].DILL.init = discover
        with patch.dict(sys.modules, {"gremlin": self.gremlin, "gremlin.util": self.gremlin.util}):
            with ThreadPoolExecutor(max_workers=1) as executor:
                refresh = executor.submit(self.namespace["joystick_devices_initialization"])
                try:
                    self.assertTrue(scanning.wait(2))
                    self.assertIs(self.namespace["getDevice"](self.keyboard_guid), self.keyboard)
                finally:
                    finish.set()
                with self.assertRaises(DiscoveryStopped):
                    refresh.result(timeout=2)

    def test_keyboard_lookup_waits_until_registry_rebuild_finishes(self):
        started = threading.Event()
        completed = threading.Event()

        def lookup():
            started.set()
            try:
                return self.namespace["getDevice"](self.keyboard_guid)
            finally:
                completed.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.namespace["_device_registry_lock"]:
                self.namespace["_all_devices_map"].clear()
                result = executor.submit(lookup)
                try:
                    self.assertTrue(started.wait(2))
                    self.assertFalse(completed.wait(0.05))
                finally:
                    self.namespace["_all_devices_map"][self.keyboard_guid] = self.keyboard
            self.assertIs(result.result(timeout=2), self.keyboard)

    def test_device_signature_uses_one_snapshot_and_detects_layout_changes(self):
        device = NS(device_guid="native-guid", name="Controller", vendor_id=1, product_id=2,
                    axis_count=2, button_count=8, hat_count=1, usage_page=1, usage=4)
        native = self.namespace["dinput"].DILL
        native.getDevices = Mock(return_value=[device])
        first = self.namespace["_device_list_signature"]()
        native.getDevices.assert_called_once_with()
        device.button_count = 16
        second = self.namespace["_device_list_signature"]([device])
        self.assertNotEqual(first, second)
        self.assertEqual(native.getDevices.call_count, 1)

    def test_lookup_before_first_initialization_still_returns_none(self):
        self.namespace["_joystick_initialized"] = False
        self.assertIsNone(self.namespace["getDevice"](self.keyboard_guid))

    def test_runtime_scan_does_not_reintroduce_rejected_interfaces(self):
        def device(guid, vendor, axes, buttons):
            return NS(device_guid=guid, vendor_id=vendor, product_id=1,
                      axis_count=axes, button_count=buttons, hat_count=0,
                      is_special=False, device_type=1, disabled=False)

        button_box = device("button-box", 0x1234, 0, 32)
        wooting_gamepad = device("wooting-gamepad", 0x31E3, 5, 10)
        wooting_keys = device("wooting-keys", 0x31E3, 0, 674)
        wooting_buttons = device("wooting-buttons", 0x31E3, 0, 3)
        ghost = device("empty-interface", 0x31E3, 0, 0)
        native = self.namespace["dinput"].DILL
        devices = [button_box, wooting_gamepad, wooting_keys, wooting_buttons, ghost]
        native.get_device_count = lambda: len(devices)
        native.getDevices = lambda: devices
        self.gremlin.util.normalize_guid = lambda guid: guid
        self.namespace.update(DeviceType=NS(Joystick=1, VJoy=2, Maestro=3),
                              _joystick_devices=[], _joystick_device_guid_map={})
        self.namespace["scanDinput"]()
        self.assertEqual(set(self.namespace["_joystick_device_guid_map"]),
                         {"button-box", "wooting-gamepad", "wooting-buttons"})
        enabled = [d.device_guid for d in self.namespace["_joystick_devices"] if not d.disabled]
        self.assertEqual(enabled, ["button-box", "wooting-gamepad"])
        self.assertTrue(wooting_buttons.disabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
