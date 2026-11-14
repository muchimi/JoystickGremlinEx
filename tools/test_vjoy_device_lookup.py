"""Hardware-free vJoy lookup checks: python tools/test_vjoy_device_lookup.py."""

import ast
import logging
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from test_vjoy_failover_output import DeviceType, InputType, ROOT, load


class VJoyDeviceLookupChecks(unittest.TestCase):
    def setUp(self):
        self.config = NS(virtual_output_failover=True, verbose_mode_joystick=False)
        self.services = ModuleType("gremlin")
        self.services.__path__ = []
        modules = {"gremlin": self.services}
        for name in ("config", "util", "shared_state", "event_handler", "remote"):
            module = ModuleType(f"gremlin.{name}")
            modules[module.__name__] = module
            setattr(self.services, name, module)
        self.services.config.Configuration = lambda: self.config
        self.services.util.to_guid = lambda guid: guid
        self.services.util.normalize_guid = str
        self.services.util.compare_guid = lambda left, right: str(left).strip("{}").lower() == str(right).strip("{}").lower()
        self.services.shared_state.current_profile = NS(settings=NS(getVirtualAsInput=lambda key: False))
        self.events = NS(profile_started=Mock())
        self.services.event_handler.EventListener = lambda: self.events
        self.services.remote.remote_client = Mock()
        self.services.singleton_decorator = NS(SingletonDecorator=lambda cls: cls)
        modules_patch = patch.dict(sys.modules, modules)
        modules_patch.start()
        self.addCleanup(modules_patch.stop)
        self.namespace = dict(
            gremlin=self.services, DeviceType=DeviceType, InputType=InputType,
            dinput=NS(GUID=str, DILL=Mock()), syslog=logging.getLogger("vjoy-lookup-checks"),
            _joystick_initialized=True, _output_targets={}, _output_targets_failover=None, _OUTPUT_MISSING=object(),
            refresh_devices=Mock(), _create_vjoy_device=Mock(),
            set_axis=Mock(), set_button=Mock(),
        )
        for name in ("_all_devices_map", "_all_vjoy_devices_map", "_vjoy_devices_map", "_maestro_devices_map",
                     "_joystick_device_guid_map"):
            self.namespace[name] = {}
        self.namespace["_all_virtual_devices_map"] = {DeviceType.VJoy: {}, DeviceType.Maestro: {}}
        for name in ("_vjoy_devices", "_joystick_devices", "_all_joystick_devices"):
            self.namespace[name] = []
        names = {
            "OutputTarget", "_maestro_failover_id", "_maestro_output_summary", "_find_output_target", "get_output_target",
            "parse_virtual_device_key", "virtual_device_key", "_native_vjoy_devices", "vjoy_devices",
            "maestro_devices", "virtual_devices", "virtual_device_map", "get_virtual_device",
            "vjoy_device_map", "getVjoyDeviceMap", "all_vjoy_devices", "vjoy_id_list", "vjoy_output_devices",
            "getDevice", "get_device", "getDeviceFromVjoyId", "getVjoyFirstIndex", "getVjoyDeviceGuid",
            "getVjoyDeviceGuidStr", "vjoy_info_from_vjoy_id", "vjoy_guid_from_id", "vjoy_id_from_guid",
            "is_vjoy_connected", "is_vjoy_guid_connected", "configure_vjoy_failover", "clearVjoyDevices", "VjoyStart",
        }
        load("gremlin/joystick_handling.py", names, self.namespace)
        self.vjoy = self.device(DeviceType.VJoy, 3, failover=True)
        self.maestro = self.device(DeviceType.Maestro, 3, slot=7)
        self.install(self.vjoy, self.maestro)

    def device(self, kind, device_id, *, connected=True, failover=False, slot=None):
        device = NS(
            device_guid=f"{kind.name}-{device_id}", name=f"gex-{device_id}" if kind == DeviceType.Maestro else f"VJoy {device_id}",
            device_type=kind, vjoy_id=device_id,
            virtual_id=(device_id - 1 if slot is None else slot) if kind == DeviceType.Maestro else device_id,
            connected=connected, is_virtual=True, axis_count=8, button_count=128, hat_count=4,
            disabled=False, data={"failover": failover},
        )
        device.setConnected = lambda state: setattr(device, "connected", state)
        if kind == DeviceType.Maestro:
            device.data["maestro_key"] = f"maestro://127.0.0.1:8010/gex-{device_id}"
        return device

    def install(self, *devices):
        native = {dev.vjoy_id: dev for dev in devices if dev.device_type == DeviceType.VJoy}
        maestro = {dev.virtual_id: dev for dev in devices if dev.device_type == DeviceType.Maestro}
        self.namespace.update(
            _all_devices_map={dev.device_guid: dev for dev in devices},
            _joystick_device_guid_map={dev.device_guid: dev for dev in devices},
            _all_vjoy_devices_map=dict(native), _vjoy_devices_map=dict(native),
            _maestro_devices_map=maestro, _vjoy_devices=list(native.values()),
            _joystick_devices=list(devices), _all_joystick_devices=list(devices),
            _all_virtual_devices_map={DeviceType.VJoy: native, DeviceType.Maestro: maestro},
        )
        self.namespace["_output_targets"].clear()

    def call(self, name, *args, **kwargs):
        return self.namespace[name](*args, **kwargs)

    def test_point_lookups_return_failover_for_numeric_ids_and_original_guids(self):
        for key in (3, "3", self.vjoy.device_guid):
            for name in ("getDeviceFromVjoyId", "vjoy_info_from_vjoy_id"):
                with self.subTest(key=key, name=name):
                    self.assertIs(self.call(name, key), self.maestro)
        for name in ("getDevice", "get_device"):
            self.assertIs(self.call(name, 3), self.maestro)
        self.assertIs(self.call("vjoy_info_from_vjoy_id", 3, connected_only=False), self.maestro)

    def test_guid_aliases_and_reverse_lookup_preserve_requested_vjoy_id(self):
        for name in ("getVjoyDeviceGuid", "getVjoyDeviceGuidStr", "vjoy_guid_from_id"):
            for key in (3, "3", self.vjoy.device_guid):
                with self.subTest(name=name, key=key):
                    self.assertEqual(self.call(name, key), self.maestro.device_guid)
        for key in (3, "3", self.vjoy.device_guid, self.maestro.device_guid):
            self.assertEqual(self.call("vjoy_id_from_guid", key), 3)
        self.namespace["refresh_devices"].assert_not_called()
        self.assertEqual(self.maestro.vjoy_id, 3)
        self.assertEqual(self.maestro.virtual_id, 7)

    def test_default_id_and_collections_include_failover_without_placeholder(self):
        missing = self.device(DeviceType.VJoy, 1, failover=True)
        offline = self.device(DeviceType.VJoy, 4, connected=False)
        self.install(missing, self.vjoy, self.maestro, offline)
        self.assertEqual(self.call("getVjoyFirstIndex"), 3)
        self.assertEqual(self.call("vjoy_id_list"), [3])
        self.assertEqual(self.call("vjoy_id_list", connected=False), [1, 4])
        self.assertEqual(self.call("vjoy_devices"), [self.maestro])
        self.assertEqual(self.call("all_vjoy_devices"), [self.maestro])
        for name in ("vjoy_device_map", "getVjoyDeviceMap"):
            result = self.call(name)
            self.assertEqual(list(result), [1, 3, 4])
            self.assertIs(result[3], self.maestro)
            result.clear()
            self.assertIs(self.call(name)[3], self.maestro)
        self.assertEqual(self.call("vjoy_devices", connected_only=False), [missing, self.maestro, offline])

    def test_available_maestro_does_not_require_a_vjoy_placeholder(self):
        self.install(self.maestro)
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.maestro)
        self.assertEqual(self.call("getVjoyFirstIndex"), 3)
        self.assertEqual(self.call("getVjoyDeviceGuid", 3), self.maestro.device_guid)
        self.assertEqual(self.call("vjoy_device_map"), {3: self.maestro})

    def test_native_vjoy_takes_precedence_in_all_lookups(self):
        self.vjoy.data.clear()
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.vjoy)
        self.assertIs(self.call("vjoy_info_from_vjoy_id", 3), self.vjoy)
        self.assertEqual(self.call("getVjoyDeviceGuid", 3), self.vjoy.device_guid)
        self.assertEqual(self.call("vjoy_devices"), [self.vjoy])
        self.assertIs(self.call("getVjoyDeviceMap")[3], self.vjoy)

    def test_disabled_failover_and_disconnected_maestro_do_not_claim_available_output(self):
        for enabled, connected in ((False, True), (True, False)):
            with self.subTest(failover=enabled, connected=connected):
                self.config.virtual_output_failover = enabled
                self.maestro.connected = connected
                self.install(self.vjoy, self.maestro)
                self.assertIs(self.call("getDeviceFromVjoyId", 3), self.vjoy)
                self.assertEqual(self.call("vjoy_devices"), [])
                self.assertFalse(self.call("is_vjoy_connected", 3))
                self.assertFalse(self.call("is_vjoy_guid_connected", self.vjoy.device_guid))
                self.assertIsNone(self.call("vjoy_info_from_vjoy_id", 3))
                self.assertIs(self.call("vjoy_info_from_vjoy_id", 3, connected_only=False), self.vjoy)

    def test_connection_helpers_recognize_failover_and_numeric_string_ids(self):
        for key in (3, "3", self.vjoy.device_guid, self.maestro.device_guid):
            self.assertTrue(self.call("is_vjoy_connected", key))
            self.assertTrue(self.call("is_vjoy_guid_connected", key))

    def test_failover_setting_changes_invalidate_previously_cached_targets(self):
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.maestro)
        self.config.virtual_output_failover = False
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.vjoy)
        self.assertEqual(self.call("vjoy_devices"), [])
        self.config.virtual_output_failover = True
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.maestro)
        self.assertEqual(self.call("getVjoyFirstIndex"), 3)

    def test_disabled_maestro_does_not_replace_the_requested_device(self):
        self.maestro.disabled = True
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.vjoy)
        self.assertEqual(self.call("vjoy_devices"), [])
        self.assertFalse(self.call("is_vjoy_connected", 3))

    def test_unverified_windows_order_blocks_automatic_failover_but_preserves_explicit_identity(self):
        self.maestro.data["maestro_hid_order_valid"] = False
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.vjoy)
        self.assertIsNone(self.call("get_output_target", 3))
        self.assertEqual(self.call("vjoy_devices"), [])
        self.assertFalse(self.call("is_vjoy_connected", 3))
        self.assertIs(self.call("getDeviceFromVjoyId", self.maestro.device_guid), self.maestro)
        self.assertTrue(self.call("is_vjoy_guid_connected", self.maestro.device_guid))
        self.maestro.data["maestro_hid_order_valid"] = True
        self.namespace["_output_targets"].clear()
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.maestro)

    def test_noncanonical_service_ids_do_not_claim_ordered_failover_numbers(self):
        self.maestro.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-03"
        self.assertIsNone(self.call("get_output_target", 3))

    def test_native_maestro_input_without_an_output_slot_is_not_an_output_target(self):
        self.maestro.virtual_id = -1
        self.install(self.maestro)
        self.assertIsNone(self.call("get_output_target", self.maestro.device_guid))
        self.assertIsNone(self.call("get_output_target", 3))

    def test_output_resolution_uses_bridge_capabilities_and_preserves_native_input_summary(self):
        output = self.device(DeviceType.Maestro, 3, slot=7)
        self.maestro.button_count = 10
        output.button_count = 32
        self.maestro.data["maestro_output_summary"] = output
        for key in (3, self.maestro.device_guid):
            self.assertIs(self.call("get_output_target", key).device, output)
        self.assertIs(self.namespace["_all_devices_map"][self.maestro.device_guid], self.maestro)
        self.assertEqual(self.maestro.button_count, 10)

    def test_stable_gamepad_output_guid_resolves_without_an_extra_inventory_row(self):
        output = self.device(DeviceType.Maestro, 3, slot=7)
        output.device_guid = "stable-gamepad-output"
        self.maestro.data["maestro_output_summary"] = output
        self.namespace["_maestro_devices_map"] = {7: output}
        self.assertIs(self.call("getDevice", output.device_guid), output)
        self.assertIs(self.call("get_output_target", output.device_guid).device, output)
        self.assertNotIn(output.device_guid, self.namespace["_all_devices_map"])

    def test_explicit_maestro_guids_remain_available_with_automatic_failover_disabled(self):
        self.config.virtual_output_failover = False
        self.assertIs(self.call("getDeviceFromVjoyId", self.maestro.device_guid), self.maestro)
        self.assertTrue(self.call("is_vjoy_guid_connected", self.maestro.device_guid))
        self.assertFalse(self.call("is_vjoy_connected", 3))

    def test_missing_guid_lookup_refreshes_and_retries_failover(self):
        self.install()
        self.namespace["refresh_devices"].side_effect = lambda: self.install(self.maestro)
        self.assertEqual(self.call("getVjoyDeviceGuid", 3), self.maestro.device_guid)
        self.namespace["refresh_devices"].assert_called_once()

    def test_output_only_list_uses_vjoy_request_id_for_input_filter(self):
        self.assertEqual(self.call("vjoy_output_devices"), [self.maestro])
        settings = self.services.shared_state.current_profile.settings
        settings.getVirtualAsInput = lambda key: key == 3
        self.assertEqual(self.call("vjoy_output_devices"), [])
        self.services.shared_state.current_profile = None
        self.assertEqual(self.call("vjoy_output_devices"), [])

    def test_native_and_profile_inventory_retain_original_provider_identities(self):
        self.assertEqual(self.call("vjoy_devices", resolve_failover=False), [self.vjoy])
        self.assertIs(self.call("get_virtual_device", 3), self.vjoy)
        self.assertIs(self.call("virtual_device_map")[DeviceType.VJoy][3], self.vjoy)
        self.assertEqual(self.call("virtual_devices"), [self.vjoy, self.maestro])

    def test_configuring_and_clearing_failover_does_not_replace_or_remove_maestro(self):
        self.install(self.maestro)
        self.call("get_output_target", 3)
        self.namespace["_create_vjoy_device"].return_value = self.vjoy
        self.call("configure_vjoy_failover", 3)
        self.namespace["_create_vjoy_device"].assert_called_once_with(3)
        self.assertIs(self.namespace["_vjoy_devices_map"][3], self.vjoy)
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.maestro)
        self.call("clearVjoyDevices")
        self.assertNotIn(self.vjoy.device_guid, self.namespace["_all_devices_map"])
        self.assertNotIn(3, self.namespace["_all_vjoy_devices_map"])
        self.assertIs(self.call("getDeviceFromVjoyId", 3), self.maestro)

    def test_profile_start_values_keep_vjoy_id_when_only_maestro_exists(self):
        self.install(self.maestro)
        startup = self.namespace["VjoyStart"]()
        startup.setStartValue("3", 1, 0.25)
        startup.setStartState(3, 2, True)
        self.assertEqual(startup._axis_data, {3: {1: 0.25}})
        self.assertEqual(startup._button_data, {3: {2: True}})
        startup.apply()
        self.namespace["set_axis"].assert_called_once_with(3, 1, 0.25)
        self.namespace["set_button"].assert_called_once_with(3, 2, True)
        self.services.remote.remote_client.send_axis.assert_called_once_with(3, 1, 0.25)
        self.services.remote.remote_client.send_button.assert_called_once_with(3, 2, True)

    def startup_overrides(self, startup):
        # Run the production startup loop without starting listeners or a profile worker.
        tree = ast.parse((ROOT / "gremlin/code_runner.py").read_bytes())
        runner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CodeRunner")
        start = next(node for node in runner.body if isinstance(node, ast.FunctionDef) and node.name == "start")
        loop = next(node for node in ast.walk(start) if isinstance(node, ast.For)
                    and ast.unparse(node.iter).startswith("gremlin.joystick_handling.vjoy_device_map("))
        self.services.joystick_handling = NS(
            vjoy_device_map=self.namespace["vjoy_device_map"],
            get_virtual_device=self.namespace["get_virtual_device"],
        )
        profile = NS(
            getStartAxisEnabled=Mock(side_effect=lambda guid, axis: axis == 1),
            getStartAxisValue=Mock(return_value=0.5),
            getStartButtonState=Mock(side_effect=lambda guid, button: button == 2),
        )
        namespace = dict(self.namespace, profile=profile, vs=startup)
        exec(compile(ast.Module(body=[loop], type_ignores=[]), "gremlin/code_runner.py", "exec"), namespace)
        return profile

    def test_profile_overrides_use_original_guid_and_vjoy_id_with_failover_capabilities(self):
        startup = self.namespace["VjoyStart"]()
        self.maestro.axis_count, self.maestro.button_count = 2, 4
        profile = self.startup_overrides(startup)
        profile.getStartAxisEnabled.assert_any_call(self.vjoy.device_guid, 1)
        profile.getStartAxisValue.assert_called_once_with(3, 1)
        self.assertEqual(startup._axis_data, {3: {1: 0.5}})
        self.assertEqual(startup._button_data, {3: {1: False, 2: True, 3: False, 4: False}})

    def test_direct_maestro_profile_does_not_gain_unrequested_vjoy_defaults(self):
        self.install(self.maestro)
        startup = self.namespace["VjoyStart"]()
        startup.setStartState(self.maestro.device_guid, 2, True)
        profile = self.startup_overrides(startup)
        profile.getStartButtonState.assert_not_called()
        self.assertEqual(startup._button_data, {self.maestro.device_guid: {2: True}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
