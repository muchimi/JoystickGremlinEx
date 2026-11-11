"""Hardware-free failover output checks: python tools/test_vjoy_failover_output.py."""

import ast
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType
from gremlin.types import DeviceType, SyncMode, VjoyAction


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
    return NS(device_guid=f"{kind.name}-1", name=f"{kind.name} 1", device_type=kind, is_virtual=True,
              vjoy_id=1 if kind == DeviceType.VJoy else -1, virtual_id=1,
              connected=connected, button_count=128, data={"failover": failover})


class MacroOutput:
    def __init__(self, vjoy_id, device_guid=None):
        self.vjoy_id, self.device_guid = vjoy_id, device_guid


class FailoverOutputChecks(unittest.TestCase):
    def setUp(self):
        self.vjoy = device(DeviceType.VJoy, failover=True)
        self.maestro = device(DeviceType.Maestro)
        self.devices = [self.vjoy]
        self.config = NS(virtual_output_failover=True, verbose_mode_outputs=False, verbose_mode_vjoy=False)
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
            remote=NS(remote_control=NS(paired=False)),
            shared_state=NS(runtime_mode="Default", current_profile=NS(get_start_mode=lambda: "Default")),
            ui=NS(ui_common=NS(MessageBoxWarning=self.warning)), macro=NS(VJoyMacroAction=MacroOutput),
        )
        self.namespace = dict(
            gremlin=services, joystick_handling=self.handling, DeviceType=DeviceType,
            InputType=InputType, VjoyAction=VjoyAction, SyncMode=SyncMode, time=time,
            syslog=logging.getLogger("failover-output-checks"), VJoyProxy=self.native,
            MessageBoxWarning=self.warning,
            getDevice=self.handling.getDevice, _output_targets={}, _OUTPUT_MISSING=object(),
            _all_devices_map={dev.device_guid: dev for dev in self.devices},
            vjoy_devices=lambda connected_only=True: [dev for dev in self.devices
                if dev.device_type == DeviceType.VJoy and (dev.connected or not connected_only)],
            maestro_devices=lambda: [dev for dev in self.devices if dev.device_type == DeviceType.Maestro],
            VJoyRemapWidget=NS(input_type_buttons=[InputType.JoystickButton]),
        )
        load("gremlin/joystick_handling.py", {
            "OutputTarget", "_find_output_target", "get_output_target", "get_output_device", "parse_virtual_device_key",
            "get_virtual_device", "virtual_device_key", "resolve_output_targets",
        }, self.namespace)
        for name in ("get_output_target", "get_output_device", "get_virtual_device", "virtual_device_key",
                     "parse_virtual_device_key", "resolve_output_targets"):
            setattr(self.handling, name, self.namespace[name])
        self.handling.is_vjoy_connected = lambda index: True  # Failover metadata is connected.
        load("action_plugins/map_to_vjoy/__init__.py", {"VJoyRemapFunctor"}, self.namespace, {
            "_is_maestro_target", "_output_key", "_target_device", "_is_output_connected", "_output_device",
            "_send_flags", "getSteppedIndexDataKey", "profile_start", "_set_axis", "_get_axis", "_process_event",
        })
        self.functor = self.namespace["VJoyRemapFunctor"]()
        f = self.functor
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
        return self.handling.get_output_target(key)

    def use_maestro(self):
        self.devices.append(self.maestro)
        self.namespace["_output_targets"].clear()
        target = self.target()
        if target is not None and target.kind == "maestro":
            target._maestro = self.backend
        return target

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

    def test_profile_start_uses_same_index_maestro(self):
        self.assertEqual(self.use_maestro().kind, "maestro")
        self.functor.profile_start()
        self.assertTrue(self.button.is_pressed)
        self.native.assert_not_called()

    def test_disabled_failover_does_not_use_maestro(self):
        self.config.virtual_output_failover = False
        self.assertIsNone(self.use_maestro())
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
        self.devices.append(self.maestro)
        self.functor.action_data.virtual_device = self.maestro
        self.assertEqual(self.target(self.maestro.device_guid).kind, "vjoy")
        self.assertTrue(self.functor._is_output_connected(1))
        self.assertIs(self.functor._output_device(1), self.backend)

    def test_native_vjoy_still_takes_precedence(self):
        self.vjoy.data.clear()
        self.assertEqual(self.use_maestro().kind, "vjoy")
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
        self.assertIn("- Maestro 1", self.warning.call_args.kwargs["prompt"])
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


if __name__ == "__main__":
    unittest.main()
