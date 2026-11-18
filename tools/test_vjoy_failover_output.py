"""Hardware-free failover output checks: python tools/test_vjoy_failover_output.py."""

import ast
import logging
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType
from gremlin.types import DeviceCategory, DeviceType, SyncMode, VjoyAction


def load(path, names, namespace, methods=None):
    tree = ast.parse((ROOT / path).read_bytes())
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in nodes} == names
    if methods is not None:
        for node in nodes:
            node.bases = []
            node.body = [item for item in node.body if getattr(item, "name", None) in methods]
            assert {item.name for item in node.body} == methods
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *nodes,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / path), "exec"), namespace)


def device(kind, *, connected=True, failover=False):
    return NS(device_guid=f"{kind.name}-1", name="gex-1" if kind == DeviceType.Maestro else "VJoy 1", device_type=kind, is_virtual=True,
              vjoy_id=1 if kind == DeviceType.VJoy else -1, virtual_id=0 if kind == DeviceType.Maestro else 1,
              connected=connected, disabled=False, is_gamepad=False, button_count=128, data={"failover": failover})


class MacroOutput:
    def __init__(self, vjoy_id, device_guid=None):
        self.vjoy_id, self.device_guid = vjoy_id, device_guid


class FailoverOutputChecks(unittest.TestCase):
    def setUp(self):
        self.vjoy = device(DeviceType.VJoy, failover=True)
        self.maestro = device(DeviceType.Maestro)
        self.devices = [self.vjoy]
        self.config = NS(virtual_output_failover=True, verbose_mode_outputs=False, verbose_mode_vjoy=False,
                         verbose_mode_maestro=False)
        self.button, self.axis = NS(is_pressed=False), NS(value=0.25)
        self.backend = NS(button=lambda index: self.button, axis=lambda index: self.axis)
        self.native = Mock(return_value={1: self.backend})
        self.start = Mock()
        self.remote = Mock()
        self.handling = NS(
            VJoyProxy=self.native,
            getDeviceFromVjoyId=lambda index: self.vjoy,
            getDevice=lambda key, show_error=False: next((dev for dev in self.devices if dev.device_guid == key), None),
            get_button=Mock(return_value=False), VjoyStart=lambda: self.start,
        )
        self.warning = Mock()
        services = NS(
            config=NS(Configuration=lambda: self.config), joystick_handling=self.handling,
            util=NS(to_guid=lambda key: key),
            remote=NS(remote_control=NS(paired=False)),
            shared_state=NS(runtime_mode="Default", current_profile=NS(get_start_mode=lambda: "Default")),
            ui=NS(ui_common=NS(MessageBoxWarning=self.warning)), macro=NS(VJoyMacroAction=MacroOutput),
        )
        self.namespace = dict(
            gremlin=services, dinput=NS(GEX_MAX_DEVICES=256), joystick_handling=self.handling, DeviceType=DeviceType,
            InputType=InputType, VjoyAction=VjoyAction, SyncMode=SyncMode, time=time,
            syslog=logging.getLogger("failover-output-checks"), VJoyProxy=self.native,
            MessageBoxWarning=self.warning,
            getDevice=self.handling.getDevice, _output_targets={}, _output_targets_failover=None, _OUTPUT_MISSING=object(),
            _raw_vjoy_target_map={}, _maestro_failover_map={}, _maestro_devices=[],
            _device_registry_lock=threading.RLock(),
            _native_vjoy_devices={1: self.vjoy},
            _all_devices_map={dev.device_guid: dev for dev in self.devices},
            get_native_vjoy_devices=lambda connected_only=True: [dev for dev in self.devices
                if dev.device_type == DeviceType.VJoy and (dev.connected or not connected_only)],
            maestro_devices=lambda: [dev for dev in self.devices if dev.device_type == DeviceType.Maestro],
            VJoyRemapWidget=NS(input_type_buttons=[InputType.JoystickButton]),
        )
        load("gremlin/joystick_handling.py", {
            "OutputTarget", "_maestro_failover_id", "_maestro_output_summary", "_find_output_target", "get_output_target", "get_output_device", "parse_virtual_device_key",
            "get_virtual_device", "virtual_device_key", "resolve_output_targets", "updateFailoverMap",
        }, self.namespace)
        for name in ("get_output_target", "get_output_device", "get_virtual_device", "virtual_device_key",
                     "parse_virtual_device_key", "resolve_output_targets"):
            setattr(self.handling, name, self.namespace[name])
        self.handling.get_output_target = self.target
        self.handling.resolve_output_targets = self.resolve_targets
        self.handling.is_vjoy_connected = lambda index: True  # Failover metadata is connected.
        load("action_plugins/map_to_vjoy/__init__.py", {"VJoyRemapFunctor"}, self.namespace, {
            "_is_maestro_target", "_output_key", "_target_device", "_is_output_connected", "_output_device",
            "_send_flags", "getSteppedIndexDataKey", "profile_start", "_set_axis", "_get_axis", "_process_event",
        })
        self.functor = self.namespace["VJoyRemapFunctor"]()
        f = self.functor
        f._valid = True
        f.verbose = f.verbose_extra = False
        f.input_type = InputType.JoystickButton
        f.action_mode = VjoyAction.VJoyButton
        f.vjoy_id = f.vjoy_input_id = 1
        f.client_list = [0]
        f.remote_client = self.remote
        f.functor_complete = Mock()
        f.usage_data = NS(is_inverted=lambda *args: False)
        f.action_data = NS(
            virtual_device=self.vjoy, virtual_id=1, vjoy_id=1, vjoy_input_id=1, vjoy_button_id=1,
            hardware_device_guid="stick", hardware_input_id=1, hardware_raw_input_type=InputType.JoystickButton,
            button_start_value=True, action_mode=f.action_mode, sync_mode=SyncMode.Default,
            remote_config=NS(getClientList=lambda: [0]), sendFlags=lambda: (True, True),
        )
        load("gremlin/code_runner.py", {"CodeRunner"}, self.namespace, {"_warn_missing_virtual_outputs", "start"})
        self.runner = self.namespace["CodeRunner"]()
        self.actions, self.initial_values = [], []
        self.profile = NS(
            filter_actions=lambda tags, callback: [callback(action, None) for action in self.actions if action.tag in tags],
            merge_axes=[], settings=NS(get_initial_vjoy_axis_value_list=lambda: self.initial_values), _start_state={},
        )

    def remap(self, device=None, key=1):
        return NS(tag="vjoyremap", virtual_device=device, vjoy_id=key, vjoy_input_id=1)

    def target(self, key=1):
        self.refresh_device_maps()
        return self.namespace["get_output_target"](key)

    def refresh_device_maps(self):
        self.namespace["_native_vjoy_devices"] = {
            dev.vjoy_id: dev for dev in self.devices if dev.device_type == DeviceType.VJoy
        }
        self.namespace["_all_devices_map"] = {dev.device_guid: dev for dev in self.devices}
        self.namespace["_maestro_devices"] = self.namespace["maestro_devices"]()
        self.namespace["updateFailoverMap"]()
        for target in self.namespace["_maestro_failover_map"].values():
            if target.kind == "maestro":
                target._maestro = self.backend

    def resolve_targets(self):
        self.refresh_device_maps()
        self.namespace["resolve_output_targets"]()

    def use_maestro(self):
        self.devices.append(self.maestro)
        self.namespace["_output_targets"].clear()
        target = self.target()
        if target is not None and target.kind == "maestro":
            target._maestro = self.backend
        return target

    def test_high_maestro_slots_route_directly_without_vjoy_aliases(self):
        for slot in (16, 31, 127, 255):
            with self.subTest(slot=slot):
                self.maestro.virtual_id = slot
                self.maestro.name = f"gex-{slot + 1}"
                self.maestro.data["maestro_key"] = f"maestro://localhost:8010/gex-{slot + 1}"
                self.devices = [self.maestro]
                target = self.target(self.maestro.device_guid)
                self.assertIsNotNone(target)
                self.assertEqual(target.kind, "maestro")
                self.assertEqual(target.out_id, slot)
                self.assertIsNone(self.namespace["_maestro_failover_id"](self.maestro))
                self.assertNotIn(slot + 1, self.namespace["_maestro_failover_map"])

    def test_failover_placeholder_is_not_a_native_output(self):
        for key in (1, self.vjoy.device_guid):
            with self.subTest(key=key):
                self.assertIsNone(self.target(key))
                self.assertIsNone(self.handling.get_output_device(key))
        self.native.assert_not_called()

    def test_profile_start_with_neither_backend_keeps_remote_start_state(self):
        self.functor.profile_start()
        self.assertFalse(self.button.is_pressed)
        self.start.setStartState.assert_called_once_with(1, 1, True)
        self.remote.send_button.assert_called_once_with(1, 1, True, client_list=[0], force_remote=False)
        self.native.assert_not_called()

    def test_profile_start_uses_failover_maestro_summary_and_backend(self):
        self.assertEqual(self.use_maestro().kind, "maestro")
        self.assertIs(self.functor._target_device(1), self.maestro)
        key = self.functor.getSteppedIndexDataKey()
        self.maestro.data[key] = "Previous run"
        self.vjoy.data[key] = "Placeholder metadata"
        self.functor.profile_start()
        self.assertIs(self.functor.device, self.maestro)
        self.assertNotIn(key, self.maestro.data)
        self.assertIn(key, self.vjoy.data)
        self.assertTrue(self.button.is_pressed)
        self.start.setStartState.assert_called_once_with(1, 1, True)
        self.remote.send_button.assert_called_once_with(1, 1, True, client_list=[0], force_remote=False)
        self.native.assert_not_called()

    def test_target_device_returns_failover_instead_of_vjoy_placeholder(self):
        self.maestro.virtual_id = 1
        self.use_maestro()
        self.assertIs(self.functor._target_device(1), self.maestro)

    def test_profile_start_finds_maestro_without_registered_vjoy_placeholder(self):
        self.devices.clear()
        self.handling.getDeviceFromVjoyId = lambda index: None
        self.use_maestro()
        self.functor.profile_start()
        self.assertIs(self.functor.device, self.maestro)
        self.assertTrue(self.button.is_pressed)
        self.assertTrue(self.functor._valid)
        self.native.assert_not_called()

    def test_failover_uses_gex_identity_for_all_vjoy_ids_despite_slot_order(self):
        self.devices.clear()
        for device_id in range(1, 17):
            maestro = device(DeviceType.Maestro)
            maestro.name = f"gex-{device_id}"
            maestro.device_guid = f"Maestro-{device_id}"
            maestro.virtual_id = 16 - device_id
            maestro.data["maestro_key"] = f"maestro://127.0.0.1:8010/gex-{device_id}"
            self.devices.append(maestro)
        for device_id in range(1, 17):
            with self.subTest(vjoy_id=device_id):
                target = self.target(device_id)
                self.assertIs(target.device, self.devices[device_id - 1])
                self.assertIs(self.functor._target_device(device_id), target.device)
                self.assertEqual(target.out_id, 16 - device_id)
                self.assertEqual(target.remote_id, device_id)

    def test_renamed_maestro_keeps_failover_identity_and_gamepad_does_not_take_it(self):
        self.maestro.name = "Pilot controls"
        self.maestro.virtual_id = 7
        self.maestro.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-1"
        gamepad = device(DeviceType.Maestro)
        gamepad.name, gamepad.virtual_id = "gex-gp-1", 0
        gamepad.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-gp-1"
        self.devices.append(gamepad)
        self.assertIs(self.use_maestro().device, self.maestro)
        self.assertIs(self.functor._target_device(1), self.maestro)
        self.assertEqual(self.target().out_id, 7)

    def test_startup_buttons_use_the_maestro_slot_and_keep_the_remote_vjoy_id(self):
        services = self.namespace["gremlin"]
        services.event_handler = NS(JoystickState=lambda: NS(outputIgnored=lambda key: False))
        services.remote.remote_client = self.remote
        services.singleton_decorator = NS(SingletonDecorator=lambda cls: cls)
        self.namespace["getDeviceFromVjoyId"] = lambda key: self.maestro
        load("gremlin/joystick_handling.py", {"set_button"}, self.namespace)
        load("gremlin/joystick_handling.py", {"VjoyStart"}, self.namespace, {"apply"})
        load("gremlin/maestro.py", {"MaestroOutputDevice", "MaestroButton"}, self.namespace)
        self.devices.append(self.maestro)
        for slot in (0, 7):
            with self.subTest(slot=slot):
                self.maestro.virtual_id = slot
                controller = NS(button_count=128)
                backend = NS(getController=lambda index: controller if index == slot else None,
                             markOutputUsed=Mock(), setButton=Mock())
                self.namespace["Maestro"] = lambda: backend
                self.resolve_targets()
                startup = self.namespace["VjoyStart"]()
                startup._axis_data = {}
                startup._button_data = {1: {128: True, 1: False}}
                self.remote.reset_mock()
                with patch.dict(sys.modules, {
                    "gremlin": services, "gremlin.event_handler": services.event_handler,
                    "gremlin.remote": services.remote,
                    "gremlin.maestro": NS(MaestroOutputDevice=self.namespace["MaestroOutputDevice"]),
                }):
                    startup.apply()
                self.assertEqual(backend.setButton.call_args_list, [call(slot, 128, True), call(slot, 1, False)])
                self.assertEqual(self.remote.send_button.call_args_list, [call(1, 128, True), call(1, 1, False)])

    def test_profile_refresh_rebuilds_failover_before_caching_targets(self):
        self.devices.append(self.maestro)
        self.namespace["_maestro_devices"] = [self.maestro]
        self.namespace["_maestro_failover_map"][1] = self.namespace["OutputTarget"](self.maestro, "maestro", 9, 1)
        self.namespace["resolve_output_targets"]()
        target = self.namespace["get_output_target"](1)
        self.assertEqual(target.out_id, self.maestro.virtual_id)
        self.assertIs(target, self.namespace["_maestro_failover_map"][1])

    def test_disabled_maestro_is_not_a_fallback(self):
        self.maestro.disabled = True
        self.assertIsNone(self.use_maestro())

    def test_unattached_or_invalid_hid_maestro_is_not_a_fallback(self):
        self.maestro.virtual_id = -1
        self.assertIsNone(self.use_maestro())
        self.maestro.virtual_id = 0
        self.maestro.data["maestro_hid_order_valid"] = False
        self.assertIsNone(self.use_maestro())

    def test_gamepad_alone_does_not_impersonate_gex_joystick(self):
        self.maestro.name = "gex-gp-1"
        self.maestro.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-gp-1"
        self.assertIsNone(self.use_maestro())

    def test_disabled_failover_does_not_use_maestro(self):
        self.config.virtual_output_failover = False
        self.assertIsNone(self.use_maestro())
        self.assertIs(self.functor._target_device(1), self.vjoy)
        self.functor.profile_start()
        self.assertFalse(self.button.is_pressed)
        self.native.assert_not_called()

    def test_disconnected_maestro_is_not_a_fallback(self):
        self.maestro.connected = False
        self.assertIsNone(self.use_maestro())

    def test_missing_maestro_cannot_fall_back_to_a_placeholder(self):
        self.maestro.connected = False
        self.devices.append(self.maestro)
        self.assertIsNone(self.target(self.maestro.device_guid))

    def test_missing_maestro_can_fall_back_to_real_vjoy(self):
        self.vjoy.data.clear()
        self.maestro.connected = False
        self.maestro.virtual_id = 7
        self.maestro.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-1"
        self.devices.append(self.maestro)
        self.functor.action_data.virtual_device = self.maestro
        self.assertEqual(self.target(self.maestro.device_guid).kind, "vjoy")
        self.assertIs(self.functor._target_device(7), self.vjoy)
        self.assertTrue(self.functor._is_output_connected(1))
        self.assertIs(self.functor._output_device(1), self.backend)

    def test_native_vjoy_still_takes_precedence(self):
        self.vjoy.data.clear()
        self.assertEqual(self.use_maestro().kind, "vjoy")
        self.assertIs(self.functor._target_device(1), self.vjoy)
        self.functor.profile_start()
        self.assertTrue(self.button.is_pressed)
        self.native.assert_called()

    def test_axis_access_with_no_backend_skips_local_output_and_sends_remote(self):
        self.functor._set_axis(1, 1, 0.75)
        self.assertEqual(self.functor._get_axis(1, 1), 0.0)
        self.remote.send_axis.assert_called_once_with(1, 1, 0.75, client_list=[0], force_remote=False)
        self.native.assert_not_called()

    def test_axis_access_uses_maestro_fallback(self):
        self.use_maestro()
        self.functor._set_axis(1, 1, 0.75)
        self.assertEqual(self.functor._get_axis(1, 1), 0.75)
        self.native.assert_not_called()

    def test_hat_event_with_no_backend_skips_local_output_and_sends_remote(self):
        event = NS(is_axis=False, force_remote=False, getInputType=lambda: InputType.JoystickHat)
        self.assertTrue(self.functor._process_event(event, NS(current=(0, 1)), None))
        self.remote.send_hat.assert_called_once_with(1, 1, (0, 1), client_list=[0])
        self.functor.functor_complete.emit.assert_called_once_with()
        self.native.assert_not_called()

    def test_all_vjoy_ids_and_guids_share_native_or_failover_target(self):
        self.devices.clear()
        sources = []
        for index in range(1, 17):
            source = device(DeviceType.VJoy, connected=index % 2 == 0)
            source.name, source.device_guid = f"VJoy {index}", f"VJoy-{index}"
            source.vjoy_id = index
            source.data.clear()
            output = device(DeviceType.Maestro)
            output.name, output.device_guid = f"gex-{index}", f"Maestro-{index}"
            output.virtual_id = 16 - index
            output.data["maestro_key"] = f"maestro://127.0.0.1:8010/gex-{index}"
            self.devices.extend([source, output])
            sources.append(source)
        self.resolve_targets()
        lookup = self.namespace["get_output_target"]
        mapping = self.namespace["_maestro_failover_map"]
        for source in sources:
            with self.subTest(vjoy_id=source.vjoy_id):
                numeric, guid = lookup(source.vjoy_id), lookup(source.device_guid)
                self.assertIs(numeric, guid)
                self.assertIs(mapping[source.vjoy_id], mapping[source.device_guid])
                self.assertEqual(numeric.kind, "vjoy" if source.connected else "maestro")
                self.assertEqual(numeric.out_id, source.vjoy_id if source.connected else 16 - source.vjoy_id)
                self.assertEqual(numeric.remote_id, source.vjoy_id)
                self.assertIs(numeric.source_device, source)

    def test_generated_disconnected_guids_follow_vjoy_id_resolution(self):
        # Exercise the production constructor and GUID conversion, without DILL.
        from test_dill_api import load_binding
        scope = load_binding()
        scope.update(DeviceType=DeviceType, DeviceCategory=DeviceCategory)
        load("dinput/__init__.py", {"GUID", "DeviceSummary"}, scope)
        services = self.namespace["gremlin"]
        services.types = NS(DeviceType=DeviceType, DeviceCategory=DeviceCategory)
        services.util.get_guid = lambda: str(scope["uuid"].uuid4())
        services.util.parse_guid = scope["GUID"]
        services.util.to_guid = lambda key: key if isinstance(key, scope["GUID"]) else scope["GUID"](key)
        scope["gremlin"] = services
        load("gremlin/joystick_handling.py", {"_create_vjoy_device", "getVjoyDeviceName"}, scope)
        with patch.dict(sys.modules, {"gremlin": services, "gremlin.util": services.util,
                                     "gremlin.types": services.types}):
            placeholders = [scope["_create_vjoy_device"](index) for index in range(1, 17)]
        self.devices.clear()
        for index, placeholder in enumerate(placeholders, 1):
            self.assertFalse(placeholder.connected)
            self.devices.append(placeholder)
            output = device(DeviceType.Maestro)
            output.name, output.device_guid = f"gex-{index}", scope["GUID"](scope["uuid"].uuid4())
            output.virtual_id = 16 - index
            self.devices.append(output)
        self.resolve_targets()
        lookup = self.namespace["get_output_target"]
        for placeholder in placeholders:
            with self.subTest(vjoy_id=placeholder.vjoy_id):
                target = lookup(placeholder.vjoy_id)
                self.assertIs(lookup(placeholder.device_guid), target)
                self.assertIs(lookup(str(placeholder.device_guid)), target)
                self.assertIs(lookup(str(scope["uuid"].UUID(str(placeholder.device_guid)))), target)
                self.assertEqual(target.kind, "maestro")
        # A profile/configuration placeholder may coexist with a live native GUID.
        native = device(DeviceType.VJoy)
        native.data.clear()
        native.device_guid = scope["GUID"](scope["uuid"].uuid4())
        self.devices.append(native)
        self.resolve_targets()
        self.assertIs(lookup(placeholders[0].device_guid), lookup(1))
        self.assertIs(lookup(native.device_guid), lookup(1))
        self.assertEqual(lookup(1).kind, "vjoy")
        # Rebuilding must remove aliases whose numeric target is unavailable.
        native.connected = False
        self.config.virtual_output_failover = False
        self.assertIsNone(lookup(str(placeholders[0].device_guid)))
        self.assertIsNone(lookup(1))
        self.native.assert_not_called()

    def test_all_four_maestro_guids_are_available_without_native_discovery(self):
        self.devices.clear()
        self.config.virtual_output_failover = False
        for index in range(1, 5):
            row = device(DeviceType.Maestro)
            row.name, row.device_guid = f"gex-{index}", f"Maestro-{index}"
            row.virtual_id = 4 - index
            row.data.update(maestro_key=f"maestro://127.0.0.1:8010/gex-{index}",
                            maestro_hid_order_valid=False)
            self.devices.append(row)
            self.actions.append(self.remap(row))
        self.resolve_targets()
        for row in self.devices:
            target = self.namespace["get_output_target"](row.device_guid)
            self.assertIs(target.device, row)
            self.assertEqual(target.out_id, row.virtual_id)
            self.assertIs(self.namespace["_maestro_failover_map"][row.device_guid], target)
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_not_called()

    def test_native_and_maestro_guids_stay_independent_with_failover(self):
        self.vjoy.data.clear()
        self.devices.append(self.maestro)
        self.resolve_targets()
        self.assertEqual(self.namespace["get_output_target"](1).kind, "vjoy")
        self.assertIs(self.namespace["get_output_target"](self.vjoy.device_guid).device, self.vjoy)
        self.assertIs(self.namespace["get_output_target"](self.maestro.device_guid).device, self.maestro)
        self.vjoy.connected = False
        self.resolve_targets()
        target = self.namespace["get_output_target"](self.vjoy.device_guid)
        self.assertIs(target.device, self.maestro)
        self.assertEqual(target.remote_id, 1)
        self.config.virtual_output_failover = False
        self.assertIsNone(self.namespace["get_output_target"](self.vjoy.device_guid))
        self.assertIs(self.namespace["get_output_target"](self.maestro.device_guid).device, self.maestro)

    def test_no_output_mappings_does_not_warn(self):
        self.actions.append(NS(tag="macro", sequence=[NS(device_guid="physical-input")]))
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_not_called()

    def test_unconfigured_merge_outputs_do_not_warn(self):
        for entry in (
            {"mode": "Default"},
            {"vjoy": None},
            {"vjoy": {}},
            {"vjoy": {"axis_id": 1}},
            {"vjoy": {"vjoy_id": None, "axis_id": 1}},
        ):
            with self.subTest(entry=entry):
                self.profile.merge_axes = [entry]
                self.runner._warn_missing_virtual_outputs(self.profile)
                self.warning.assert_not_called()

    def test_unconfigured_merge_does_not_hide_missing_outputs(self):
        self.profile.merge_axes = [{"mode": "Default"}, {"vjoy": {"vjoy_id": 2, "axis_id": 1}}]
        self.actions.append(self.remap(self.vjoy))
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_called_once()
        self.assertIn("- VJoy 1", self.warning.call_args.kwargs["prompt"])
        self.assertIn("- vJoy 2", self.warning.call_args.kwargs["prompt"])

    def test_missing_remaps_are_grouped_in_one_warning(self):
        self.actions.extend([self.remap(self.vjoy), self.remap(key="1"), self.remap(key=2)])
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_called_once()
        message = self.warning.call_args.kwargs
        self.assertEqual(message["prompt"].count("- VJoy 1"), 1)
        self.assertIn("- vJoy 2", message["prompt"])
        self.assertIn("continue running", message["informative_text"])
        self.native.assert_not_called()

    def test_working_failover_does_not_warn(self):
        self.actions.append(self.remap(self.vjoy))
        self.use_maestro()
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_not_called()

    def test_warning_only_lists_missing_targets_when_some_outputs_exist(self):
        self.vjoy.data.clear()
        self.actions.extend([self.remap(self.vjoy), self.remap(key=2)])
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_called_once()
        self.assertNotIn("- VJoy 1", self.warning.call_args.kwargs["prompt"])
        self.assertIn("- vJoy 2", self.warning.call_args.kwargs["prompt"])

    def test_missing_maestro_is_named_independently_of_native_vjoy(self):
        self.vjoy.data.clear()
        self.maestro.connected = False
        self.config.virtual_output_failover = False
        self.devices.append(self.maestro)
        self.actions.extend([self.remap(self.vjoy), self.remap(self.maestro)])
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_called_once()
        self.assertIn("- gex-1", self.warning.call_args.kwargs["prompt"])
        self.assertNotIn("- VJoy 1", self.warning.call_args.kwargs["prompt"])

    def test_macro_split_merge_and_start_values_are_checked(self):
        self.actions.extend([
            NS(tag="macro", sequence=[MacroOutput(2)]),
            NS(tag="split-axis", device_low_vjoy_id=3, device_low_axis=1,
               device_high_vjoy_id=4, device_high_axis=2),
        ])
        self.profile.merge_axes.append({"vjoy": {"vjoy_id": 5, "axis_id": 1}})
        self.initial_values.append((6, 1, 0.0))
        self.profile._start_state.update({7: {"buttons": {1: False}}, 8: {"enabled": {1: True}}})
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_called_once()
        for key in range(2, 9):
            self.assertIn(f"- vJoy {key}", self.warning.call_args.kwargs["prompt"])

    def test_disabled_start_values_and_unconfigured_outputs_do_not_warn(self):
        self.profile._start_state[1] = {"enabled": {1: False}}
        self.actions.extend([self.remap(key=None), self.remap(key=0)])
        self.runner._warn_missing_virtual_outputs(self.profile)
        self.warning.assert_not_called()

    def test_nested_gate_outputs_are_found_by_the_real_profile_traversal(self):
        services = self.namespace["gremlin"]
        services.types = NS(DeviceType=DeviceType)
        load("gremlin/base_profile.py", {"Profile"}, self.namespace,
             {"filter_actions", "_filter_actions_input_item"})
        profile = self.namespace["Profile"]()
        profile.sync = Mock()
        nested_input = NS(containers=[NS(action_sets=[[self.remap(self.vjoy)]])])
        gate = NS(item_data_map={"enter": nested_input})
        gated = NS(tag="gated-axis", gate_data=NS(getGates=lambda: [gate], getRanges=lambda: []))
        input_item = NS(containers=[NS(action_sets=[[gated]])])
        profile.devices = {"stick": NS(device_type=DeviceType.Joystick,
            modes={"Default": NS(config={InputType.JoystickAxis: {1: input_item}})})}
        profile.merge_axes, profile._start_state, profile.settings = [], {}, self.profile.settings
        self.runner._warn_missing_virtual_outputs(profile)
        self.warning.assert_called_once()
        self.assertIn("- VJoy 1", self.warning.call_args.kwargs["prompt"])

    def test_start_refreshes_targets_then_warns_and_continues_startup(self):
        self.actions.append(self.remap(self.vjoy))
        self.profile.merge_axes.append({"mode": "Default"})
        self.namespace["_output_targets"][1] = self.namespace["OutputTarget"](self.vjoy, "vjoy", 1, 1)
        services = self.namespace["gremlin"]
        services.event_handler = NS(EventListener=Mock(), EventHandler=Mock())
        context = Mock(getLastBuildError=Mock(return_value="Stop at the test build boundary"))
        services.execution_graph = NS(ExecutionContext=lambda: context)
        self.runner.stop = Mock()
        self.assertFalse(self.runner.start({}, self.profile.settings, "Default", self.profile))
        self.warning.assert_called_once()
        context.reset.assert_called_once_with(force_rebuild=True)
        self.runner.stop.assert_called_once()

    def test_startup_remap_cancel_continues_and_apply_leaves_profile_inactive(self):
        self.actions.append(self.remap(self.vjoy))
        services = self.namespace["gremlin"]
        for applied in (False, True):
            with self.subTest(applied=applied):
                listener, handler = Mock(), Mock()
                services.event_handler = NS(EventListener=lambda: listener, EventHandler=lambda: handler)
                services.shared_state.profile_message_issued = False
                context = Mock(getLastBuildError=Mock(return_value="Stop at the test build boundary"))
                services.execution_graph = NS(ExecutionContext=lambda: context)
                remap_devices = Mock(return_value=applied)
                self.runner.stop = Mock()
                self.assertFalse(self.runner.start({}, self.profile.settings, "Default", self.profile,
                                                   remap_devices=remap_devices))
                remap_devices.assert_called_once_with(self.profile, {1})
                self.warning.assert_not_called()
                self.assertEqual(services.shared_state.profile_message_issued, applied)
                self.assertEqual(listener.profile_deactivated.emit.call_count, int(applied))
                self.assertEqual(context.reset.call_count, int(not applied))
                self.assertEqual(handler.reset.call_count, int(not applied))

    def test_start_resolves_maestro_before_building_profile_functors(self):
        self.assertIsNone(self.target())  # A missing target was cached before startup.
        self.devices.append(self.maestro)
        self.actions.append(self.remap(self.vjoy))
        services = self.namespace["gremlin"]
        services.event_handler = NS(EventListener=Mock(), EventHandler=Mock())

        class BuildBoundary(Exception):
            pass

        context = Mock(getLastBuildError=Mock(side_effect=BuildBoundary))
        services.execution_graph = NS(ExecutionContext=lambda: context)

        def build_functors(**options):
            target = self.target()
            self.assertIs(target.device, self.maestro)
            target._maestro = self.backend
            self.functor.profile_start()

        context.reset.side_effect = build_functors
        with self.assertRaises(BuildBoundary):
            self.runner.start({}, self.profile.settings, "Default", self.profile)
        self.assertIs(self.functor.device, self.maestro)
        self.assertTrue(self.button.is_pressed)
        self.assertTrue(self.functor._valid)
        self.warning.assert_not_called()
        self.native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
