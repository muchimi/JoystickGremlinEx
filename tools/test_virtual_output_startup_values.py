"""Hardware-free startup routing checks: python tools/test_virtual_output_startup_values.py."""

import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def method(filename, class_name, name):
    tree = ast.parse((ROOT / filename).read_bytes())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)


class StartupOutputChecks(unittest.TestCase):
    def setUp(self):
        self.native = NS(device_guid="native-guid", vjoy_id=1, virtual_id=1, kind="vjoy")
        self.maestro = NS(device_guid="maestro-guid", vjoy_id=-1, virtual_id=7, kind="maestro")
        self.identities = {"native-guid": self.native, "maestro-guid": self.maestro}
        self.targets = {1: self.maestro, "native-guid": self.maestro, "maestro-guid": self.maestro}
        self.axis, self.buttons = {}, {}
        self.remote = NS(send_axis=Mock(), send_button=Mock())
        self.signal = Mock()
        gremlin = ModuleType("gremlin")
        gremlin.__path__ = []
        events = ModuleType("gremlin.event_handler")
        events.EventListener = lambda: NS(profile_started=self.signal)
        remote = ModuleType("gremlin.remote")
        remote.remote_client = self.remote
        gremlin.event_handler, gremlin.remote = events, remote
        self.connected_outputs = {}
        self.handling = NS(
            vjoy_device_map=lambda **kwargs: self.connected_outputs,
            get_virtual_device=lambda key: self.identities.get(key),
            virtual_device_key=lambda device: 1 if device.kind == "vjoy" else device.device_guid,
            parse_virtual_device_key=lambda key: int(key) if str(key).isdigit() else key,
        )
        gremlin.joystick_handling = self.handling
        self.modules = patch.dict(sys.modules, {"gremlin": gremlin, "gremlin.event_handler": events, "gremlin.remote": remote})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        tree = ast.parse((ROOT / "gremlin/joystick_handling.py").read_bytes())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "VjoyStart")
        cls.decorator_list = []
        namespace = dict(gremlin=gremlin,
                         getDeviceFromVjoyId=lambda key: self.targets.get(key) or self.identities.get(key),
                         parse_virtual_device_key=self.handling.parse_virtual_device_key,
                         set_axis=lambda key, axis, value: self.axis.__setitem__((self.targets[key].device_guid, axis), value),
                         set_button=lambda key, button, value: self.buttons.__setitem__((self.targets[key].device_guid, button), value))
        configure = method("gremlin/code_runner.py", "CodeRunner", "_configure_startup_outputs")
        future = ast.parse("from __future__ import annotations").body
        exec(compile(ast.fix_missing_locations(ast.Module(body=[*future, cls, configure], type_ignores=[])), "startup_checks", "exec"), namespace)
        self.startup = namespace["VjoyStart"]()
        self.handling.VjoyStart = lambda: self.startup
        self.configure = lambda profile: namespace["_configure_startup_outputs"](None, profile)
        self.profile = NS(settings=NS(get_initial_vjoy_axis_value_list=lambda: self.defaults), _start_state={})
        self.defaults = []

    def test_legacy_axis_default_reaches_maestro_failover_and_keeps_remote_id(self):
        self.defaults.append((1, 5, 0.4))
        self.configure(self.profile)
        self.startup.apply()
        self.assertEqual(self.axis, {("maestro-guid", 5): 0.4})
        self.remote.send_axis.assert_called_once_with(1, 5, 0.4)
        self.signal.connect.assert_called_once()

    def test_profile_guid_axis_overrides_global_default_on_failover(self):
        self.defaults.append((1, 5, 0.4))
        self.profile._start_state["native-guid"] = {"axis": {5: -0.7}, "enabled": {5: True}}
        self.configure(self.profile)
        self.startup.apply()
        self.assertEqual(self.axis, {("maestro-guid", 5): -0.7})
        self.assertEqual(self.startup._axis_data, {1: {5: -0.7}})

    def test_converted_maestro_startup_applies_without_vjoy_enumeration(self):
        self.profile._start_state["maestro-guid"] = {"axis": {5: 0.25}, "enabled": {5: True}, "buttons": {2: True, 3: False}}
        self.configure(self.profile)
        self.startup.apply()
        self.assertEqual(self.axis, {("maestro-guid", 5): 0.25})
        self.assertEqual(self.buttons, {("maestro-guid", 2): True, ("maestro-guid", 3): False})
        self.assertIn("maestro-guid", self.startup._axis_data)

    def test_maestro_startup_also_reaches_vjoy_failover(self):
        self.targets["maestro-guid"] = self.native
        self.profile._start_state["maestro-guid"] = {"axis": {2: 0.6}, "enabled": {2: True}, "buttons": {4: True}}
        self.configure(self.profile)
        self.startup.apply()
        self.assertEqual(self.axis, {("native-guid", 2): 0.6})
        self.assertEqual(self.buttons, {("native-guid", 4): True})

    def test_disabled_and_unconfigured_axes_do_not_override_defaults(self):
        self.defaults.append((1, 5, 0.4))
        self.profile._start_state["native-guid"] = {"axis": {5: -0.7, 6: 0.8}, "enabled": {5: False}}
        self.configure(self.profile)
        self.startup.apply()
        self.assertEqual(self.axis, {("maestro-guid", 5): 0.4})

    def test_existing_button_reset_is_preserved_before_explicit_states(self):
        self.maestro.button_count = 3
        self.connected_outputs[1] = self.maestro
        self.profile._start_state["native-guid"] = {"buttons": {2: True}}
        self.configure(self.profile)
        self.startup.apply()
        self.assertEqual(self.buttons, {("maestro-guid", 1): False, ("maestro-guid", 2): True, ("maestro-guid", 3): False})

    def test_values_follow_output_target_resolved_at_apply_time(self):
        self.defaults.append((1, 5, 0.4))
        self.configure(self.profile)
        self.targets[1] = self.native
        self.startup.apply()
        self.assertEqual(self.axis, {("native-guid", 5): 0.4})


class MaestroSlotStartupChecks(unittest.TestCase):
    def test_vjoy_one_startup_uses_matching_maestro_slot(self):
        handling = ast.parse((ROOT / "gremlin/joystick_handling.py").read_bytes())
        maestro = ast.parse((ROOT / "gremlin/maestro.py").read_bytes())
        nodes = [node for node in handling.body if getattr(node, "name", None) in {"OutputTarget", "set_button"}]
        startup = next(node for node in handling.body if isinstance(node, ast.ClassDef) and node.name == "VjoyStart")
        startup.decorator_list = []
        startup.body = [node for node in startup.body if getattr(node, "name", None) == "apply"]
        nodes.append(startup)
        nodes.extend(node for node in maestro.body if getattr(node, "name", None) in {"MaestroOutputDevice", "MaestroButton"})
        remote = NS(remote_client=NS(send_button=Mock()))
        events = NS(JoystickState=lambda: NS(outputIgnored=lambda key: False))
        services = NS(event_handler=events, remote=remote)
        namespace = dict(gremlin=services)
        future = ast.parse("from __future__ import annotations").body
        exec(compile(ast.fix_missing_locations(ast.Module(body=[*future, *nodes], type_ignores=[])),
                     "slot_startup_checks", "exec"), namespace)
        for slot in (0, 7):
            with self.subTest(slot=slot):
                controller = NS(button_count=128)
                backend = NS(getController=lambda index: controller if index == slot else None,
                             markOutputUsed=Mock(), setButton=Mock())
                namespace["Maestro"] = lambda: backend
                device = NS(button_count=128, virtual_id=slot)
                source = NS(virtual_id=1)
                target = namespace["OutputTarget"](device, "maestro", out_id=slot, virtual_id=1, source_device=source)
                namespace["get_output_target"] = lambda key: target if key == 1 else None
                namespace["getDeviceFromVjoyId"] = lambda key: device
                start = namespace["VjoyStart"]()
                start._axis_data = {}
                start._button_data = {1: {128: True, 1: False}}
                remote.remote_client.send_button.reset_mock()
                with patch.dict(sys.modules, {"gremlin": services, "gremlin.event_handler": events,
                                             "gremlin.remote": remote,
                                             "gremlin.maestro": NS(MaestroOutputDevice=namespace["MaestroOutputDevice"])}):
                    start.apply()
                self.assertEqual([args.args for args in backend.setButton.call_args_list],
                                 [(slot, 128, True), (slot, 1, False)])
                self.assertEqual([args.args for args in remote.remote_client.send_button.call_args_list],
                                 [(1, 128, True), (1, 1, False)])
                self.assertEqual(target.virtual_id, 1)


if __name__ == "__main__":
    unittest.main()
