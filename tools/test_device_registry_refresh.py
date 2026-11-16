"""Hardware-free registry race checks: python tools/test_device_registry_refresh.py."""

import ast
from collections import UserDict
import copy
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum
import logging
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from test_device_change_suppression import listener_fixture


class DiscoveryStopped(Exception):
    pass


class DeviceType(IntEnum):
    Joystick = 1
    VJoy = 2
    Maestro = 3
    Keyboard = 4


class RegistryRefreshChecks(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "gremlin/joystick_handling.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name in {"getDevice", "joystick_devices_initialization", "_device_list_signature",
                                         "scanDinput", "isDeviceValid", "_is_excluded_native_joystick",
                                         "_publish_joystick_devices", "_replace_device_registry", "dumpDevices",
                                         "set_maestro_devices", "_log_output_map", "_is_cached_maestro_device",
                                         "_apply_maestro_service_devices", "_maestro_failover_id", "_maestro_output_summary"}]
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                                 *definitions], type_ignores=[])
        self.keyboard_guid = "keyboard-guid"
        self.keyboard = NS(device_guid=self.keyboard_guid, device_type=DeviceType.Keyboard,
                           name="Keyboard", vendor_id=0, product_id=0, data={}, connected=True)
        self.config = config = NS(verbose_mode_inputs=False, verbose_mode_vjoy=False, vjoy_installed=False,
                                 verbose_mode_extra=False, verbose_mode_joystick=False, verbose_mode_maestro=False,
                                 hid_list_enabled=False)
        self.gremlin = ModuleType("gremlin")
        self.gremlin.util = ModuleType("gremlin.util")
        self.gremlin.config = NS(Configuration=lambda: config)
        self.listener = listener_fixture()
        self.listener.device_initialized = NS(emit=Mock())
        self.gremlin.event_handler = NS(EventListener=lambda: self.listener)
        self.namespace = dict(
            gremlin=self.gremlin, copy=copy, syslog=logging.getLogger(__name__),
            dinput=NS(GUID=str, DILL=NS(init=Mock())),
            vjoy=NS(VJoyMonitor=lambda: NS(stop=Mock())),
            _joystick_initialized=True, _last_device_signature=None,
            _joystick_init_lock=threading.Lock(), _device_registry_lock=threading.RLock(),
            _all_devices_map={self.keyboard_guid: self.keyboard},
            _maestro_failover_map={}, _maestro_devices_map={},
            parse_virtual_device_key=lambda key: key,
        )
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), self.namespace)

    def enumeration_fixture(self):
        self.gremlin.hid = NS(Hid=Mock())
        self.gremlin.ui = NS(axis_calibration=NS(CalibrationManager=lambda: NS(reload=Mock())))
        self.gremlin.util.InvokeUiMethod = Mock()
        self.gremlin.util.normalize_guid = lambda guid: guid
        native = self.namespace["dinput"].DILL
        native.getDevices = Mock(return_value=[])
        native.get_device_count = lambda: 0
        self.namespace["dinput"].AxisMap = lambda: NS(getName=lambda: "")
        self.namespace.update(DeviceType=DeviceType, DeviceCategory=NS(Physical=1, Virtual=2),
                              _joystick_devices=[], _all_joystick_devices=[], _disconnected_devices=[],
                              _special_devices=[self.keyboard], _config_devices=[], _joystick_device_guid_map={},
                              _all_vjoy_devices_map={}, _vjoy_devices_map={}, _native_vjoy_devices={},
                              _raw_vjoy_target_map={}, _maestro_replaced_devices={}, _vjoy_devices=[],
                              _maestro_devices=[], VJoyProxy=lambda: NS(reset=Mock()),
                              _maestro_service_devices={}, _maestro_excluded_native_guids=set(),
                              _apply_maestro_service_devices=Mock(), _update_joystick_device_maps=Mock(),
                              _update_virtual_map=Mock(), _log_output_map=Mock())
        self.namespace["_create_vjoy_device"] = lambda vid: NS(
            device_guid=f"vjoy-{vid}", button_count=128, axis_count=8, hat_count=4,
            axismap_list=[], axis_names={}, device_type=DeviceType.VJoy)

        def register_special():
            self.namespace["_all_devices_map"][self.keyboard_guid] = self.keyboard

        self.namespace["registerSpecialDevices"] = register_special

    def test_vjoy_probe_can_wait_for_input_lookup_during_refresh(self):
        self.enumeration_fixture()
        finished = threading.Event()
        observed = []
        lookup_worker = None

        def query_driver(config):
            nonlocal lookup_worker

            def input_callback():
                observed.append(self.namespace["getDevice"](self.keyboard_guid))
                finished.set()

            lookup_worker = threading.Thread(target=input_callback)
            lookup_worker.start()
            observed.append(finished.wait(0.5))
            return False

        self.namespace["vjoy_installed"] = query_driver
        with patch.dict(sys.modules, {"gremlin": self.gremlin, "gremlin.util": self.gremlin.util}):
            self.assertTrue(self.namespace["joystick_devices_initialization"]())
        lookup_worker.join(timeout=1)
        self.assertIn(True, observed, "Driver probe blocked its input callback on _device_registry_lock")
        self.assertIn(self.keyboard, observed)

    def assert_lookup_completes_during(self, operation):
        observed, workers = [], []

        def call_consumer(*args, **kwargs):
            done = threading.Event()

            def lookup():
                self.namespace["getDevice"](self.keyboard_guid)
                done.set()

            worker = threading.Thread(target=lookup)
            workers.append(worker)
            worker.start()
            observed.append(done.wait(0.5))

        operation(call_consumer)
        for worker in workers:
            worker.join(timeout=1)
        self.assertTrue(observed)
        self.assertTrue(all(observed), "Registry lock was held while calling another subsystem")

    def test_output_resolution_does_not_hold_registry_lock(self):
        def operation(consumer):
            self.namespace["getDeviceFromVjoyId"] = consumer
            self.namespace["getDevice"](1)

        self.assert_lookup_completes_during(operation)

    def test_missing_device_logging_does_not_hold_registry_lock(self):
        self.config.verbose_mode_joystick = True
        self.namespace["dumpDevices"] = Mock()

        def operation(consumer):
            self.namespace["syslog"] = NS(warning=consumer)
            self.assertIsNone(self.namespace["getDevice"]("missing-guid"))

        self.assert_lookup_completes_during(operation)

    def test_service_creation_and_removal_log_after_releasing_registry_lock(self):
        log_output = self.namespace["_log_output_map"]
        self.enumeration_fixture()
        self.namespace["_log_output_map"] = log_output
        self.config.verbose_mode_maestro = True
        service = NS(device_guid="service-guid", device_type=DeviceType.Maestro,
                     data={"maestro_key": "maestro://127.0.0.1:8010/gex-1"})

        def operation(consumer):
            self.namespace["syslog"] = NS(info=consumer)
            self.namespace["set_maestro_devices"]([service])
            self.namespace["set_maestro_devices"]([], known_devices={})

        self.assert_lookup_completes_during(operation)

    def test_failed_discovery_keeps_the_published_inventory(self):
        self.enumeration_fixture()
        self.namespace["vjoy_installed"] = Mock(side_effect=RuntimeError("Driver unavailable"))
        with patch.dict(sys.modules, {"gremlin": self.gremlin, "gremlin.util": self.gremlin.util}):
            with self.assertRaisesRegex(RuntimeError, "Driver unavailable"):
                self.namespace["joystick_devices_initialization"]()
        self.assertIs(self.namespace["getDevice"](self.keyboard_guid), self.keyboard)

    def test_special_device_setup_and_proxy_reset_can_query_the_registry(self):
        for call_site in ("special devices", "proxy reset"):
            with self.subTest(call_site=call_site):
                self.enumeration_fixture()
                self.namespace["vjoy_installed"] = Mock(return_value=False)

                def operation(consumer):
                    if call_site == "special devices":
                        self.namespace["registerSpecialDevices"] = consumer
                    else:
                        self.namespace["VJoyProxy"] = lambda: NS(reset=consumer)
                    with patch.dict(sys.modules, {"gremlin": self.gremlin, "gremlin.util": self.gremlin.util}):
                        self.namespace["joystick_devices_initialization"]()

                self.assert_lookup_completes_during(operation)

    def test_publication_rebases_on_services_changed_during_discovery(self):
        apply_services = self.namespace["_apply_maestro_service_devices"]
        self.enumeration_fixture()
        self.namespace["_update_joystick_device_maps"] = apply_services
        service = NS(device_guid="new-service", device_type=DeviceType.Maestro, virtual_id=0,
                     connected=True, disabled=False, is_gamepad=False, name="gex-1", data={})
        service.set_vjoy_id = lambda vid: setattr(service, "vjoy_id", vid)
        self.namespace["_maestro_service_devices"] = {service.device_guid: service}
        old = NS(device_guid="removed-service", device_type=DeviceType.Maestro, data={})
        self.namespace["_maestro_excluded_native_guids"].add(old.device_guid)
        self.namespace["_publish_joystick_devices"]({old.device_guid: old}, {}, {}, ())
        self.assertIs(self.namespace["getDevice"](self.keyboard_guid), self.keyboard)
        self.assertIs(self.namespace["getDevice"](service.device_guid), service)
        self.assertNotIn(old.device_guid, self.namespace["_all_devices_map"])

    def test_existing_registry_views_keep_the_previous_complete_generation(self):
        previous = UserDict({self.keyboard_guid: self.keyboard})
        view = previous.items()
        self.namespace["_all_devices_map"] = previous
        extra = NS(device_guid="new-device", device_type=DeviceType.Joystick)
        with self.namespace["_device_registry_lock"]:
            self.namespace["_replace_device_registry"]({self.keyboard_guid: self.keyboard, extra.device_guid: extra})
        self.assertEqual(list(view), [(self.keyboard_guid, self.keyboard)])
        self.assertEqual(set(self.namespace["_all_devices_map"]), {self.keyboard_guid, extra.device_guid})

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

    def test_creation_suppression_leaves_registry_and_native_inventory_untouched(self):
        self.listener.pushDeviceChangeSuppression()
        with patch.dict(sys.modules, {"gremlin": self.gremlin, "gremlin.util": self.gremlin.util}):
            with self.namespace["_joystick_init_lock"], self.namespace["_device_registry_lock"]:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    result = executor.submit(self.namespace["joystick_devices_initialization"])
                    self.assertFalse(result.result(timeout=1))
        self.namespace["dinput"].DILL.init.assert_not_called()
        self.assertEqual(self.namespace["_all_devices_map"], {self.keyboard_guid: self.keyboard})
        self.assertTrue(self.listener._device_change_pending)
        self.listener.popDeviceChangeSuppression()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once_with(force=False)

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
