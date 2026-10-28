"""Hardware-free KVM hat checks: python tools/test_kvm.py.

Load the real action and hat-normalization code with device hooks and remote
output replaced by mocks, so these checks cannot suppress or send real input.
"""

import ast
import logging
import sys
import unittest
from abc import ABCMeta, abstractmethod
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gremlin.fsm  # noqa: E402
from gremlin.input_types import InputType  # noqa: E402
from gremlin.types import SyncMode  # noqa: E402


def load_definitions(path, names, namespace):
    source = ROOT / path
    nodes = [node for node in ast.parse(source.read_bytes()).body if getattr(node, "name", None) in names]
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *nodes,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)


class BaseFunctor:
    def __init__(self, action, parent=None):
        self.action_data = action

    def profile_started(self):
        pass


class Event:
    def __init__(self, event_type, identifier=1, device_guid="joystick", value=None, is_pressed=False, **kwargs):
        self.event_type = event_type
        self.identifier = identifier
        self.device_guid = device_guid
        self.value = value
        self.is_pressed = is_pressed


# Use the application's actual event conversion for the virtual hat path.
event_source = ast.parse((ROOT / "gremlin/event_handler.py").read_bytes())
event_class = next(node for node in event_source.body if isinstance(node, ast.ClassDef) and node.name == "Event")
fake_button = next(node for node in event_class.body if isinstance(node, ast.FunctionDef) and node.name == "fake_button")
event_namespace = {"InputType": InputType}
exec(compile(ast.Module(body=[fake_button], type_ignores=[]), str(ROOT / "gremlin/event_handler.py"), "exec"), event_namespace)
Event.fake_button = event_namespace["fake_button"]


class KVMChecks(unittest.TestCase):
    def setUp(self):
        self.mouse = Mock()
        self.keyboard = Mock()
        self.remote = Mock()
        self.raw = Mock()
        self.joystick = Mock()
        self.joystick.get_hat_position.return_value = (0, 0)
        self.cursor = NS(GetCursorPos=Mock(return_value=(100, 200)))
        self.services = NS(
            base_profile=NS(AbstractFunctor=BaseFunctor),
            input_item=NS(AbstractAction=object),
            windows_event_hook=NS(MouseHook=lambda: self.mouse, KeyboardHook=lambda: self.keyboard),
            remote=NS(remote_client=self.remote),
            raw_input=self.raw,
            config=NS(Configuration=lambda: NS(verbose_mode_remote=False)),
            joystick_handling=self.joystick,
            event_handler=NS(Event=Event),
            fsm=gremlin.fsm,
        )
        self.namespace = {
            "gremlin": self.services, "InputType": InputType, "SyncMode": SyncMode,
            "syslog": logging.getLogger("kvm-checks"), "win32api": self.cursor,
            "KVMWidget": object, "ABCMeta": ABCMeta, "abstractmethod": abstractmethod,
            "AbstractCondition": object,
        }
        load_definitions("gremlin/util.py", {"hat_tuple_to_direction"}, self.namespace)
        self.services.util = NS(hat_tuple_to_direction=self.namespace["hat_tuple_to_direction"])
        load_definitions("gremlin/actions.py", {"Value", "VirtualButton", "HatButton", "VirtualButtonCondition"}, self.namespace)
        load_definitions("action_plugins/kvm/__init__.py", {"KVMFunctor", "KVM"}, self.namespace)
        self.container = NS(has_virtual_button=True, virtual_button=NS(directions=["north"]))
        self.action = NS(
            hardware_device_guid="joystick", hardware_input_id=2,
            get_input_type=lambda: InputType.JoystickHat,
            get_container=lambda: self.container,
            sync_mode=SyncMode.Ignore,
            remote_config=NS(getClientList=lambda: [7]),
            mouse_enabled=True, keyboard_enabled=True,
        )
        self.functor = self.namespace["KVMFunctor"](self.action)

    def deliver(self, position, pressed=True):
        event = Event(InputType.JoystickHat, value=position, is_pressed=pressed)
        self.functor.process_event(event, self.namespace["Value"](position))

    def test_hat_mapping_requires_virtual_button_without_motion_input_attribute(self):
        action_class = self.namespace["KVM"]
        for input_type, expected in ((InputType.JoystickHat, True), (InputType.JoystickAxis, True), (InputType.JoystickButton, False)):
            with self.subTest(input_type=input_type):
                action = object.__new__(action_class)
                action.get_input_type = lambda: input_type
                self.assertEqual(action.requires_virtual_button(), expected)

    def test_raw_hat_directions_stop_when_centered(self):
        for position in ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)):
            with self.subTest(position=position):
                self.deliver(position)
                self.assertTrue(self.functor._is_running)
                self.deliver(position, pressed=False)
                self.deliver((0, 0))  # Center arrives as a press of the new position.
                self.assertFalse(self.functor._is_running)

    def test_virtual_hat_uses_selected_directions_including_center(self):
        for selected, sequence in (
            (["north"], [((0, 0), False), ((0, 1), True), ((1, 1), False), ((0, 0), False)]),
            (["center"], [((0, 0), True), ((0, 1), False), ((0, 0), True)]),
        ):
            with self.subTest(selected=selected):
                condition = object.__new__(self.namespace["VirtualButtonCondition"])
                condition.virtual_button = self.namespace["HatButton"](selected)
                for position, expected in sequence:
                    # DirectInput emits release of the old position, then press of the new one.
                    event = Event(InputType.JoystickHat, value=position, is_pressed=True)
                    value = self.namespace["Value"](position)
                    self.assertTrue(condition.process_event(event, value, {}))
                    self.functor.process_event(event, value)
                    self.assertEqual(self.functor._is_running, expected)
        self.functor.stop()

    def test_sync_to_selected_hat_direction(self):
        self.action.sync_mode = SyncMode.Input
        self.joystick.get_hat_position.return_value = (0, 1)
        self.functor.profile_started()
        self.assertTrue(self.functor._is_running)
        self.joystick.get_hat_position.assert_called_once_with("joystick", 2)
        self.assertEqual(self.functor.client_list, [7])

    def test_sync_does_not_activate_for_unselected_hat_direction(self):
        self.action.sync_mode = SyncMode.Input
        self.joystick.get_hat_position.return_value = (1, 0)
        self.functor.profile_started()
        self.assertFalse(self.functor._is_running)
        self.remote.send_kvm_mouse_motion_start.assert_not_called()

    def test_sync_can_activate_for_explicitly_selected_center(self):
        self.action.sync_mode = SyncMode.Input
        self.container.virtual_button.directions = ["center"]
        self.functor.profile_started()
        self.assertTrue(self.functor._is_running)

    def test_sync_without_virtual_button_uses_hat_deflection(self):
        self.action.sync_mode = SyncMode.Input
        self.container.has_virtual_button = False
        self.joystick.get_hat_position.return_value = (-1, -1)
        self.functor.profile_started()
        self.assertTrue(self.functor._is_running)
        self.joystick.get_hat_position.return_value = (0, 0)
        self.functor.profile_started()
        self.assertFalse(self.functor._is_running)

    def test_ignore_sync_does_not_read_hat_or_activate(self):
        self.functor.profile_started()
        self.joystick.get_hat_position.assert_not_called()
        self.assertFalse(self.functor._is_running)

    def test_profile_stop_cleans_up_and_allows_hat_reactivation(self):
        self.deliver((0, 1))
        self.functor.profile_stop()
        self.assertFalse(self.functor._is_running)
        self.assertFalse(self.functor._raw_input_hooked)
        self.raw.registerUnhook.assert_called_once_with(self.functor._mouse_move_handler)
        self.keyboard.unregister.assert_called_once_with(self.functor._keyboard_handler)
        self.deliver((0, 1))
        self.assertTrue(self.functor._is_running)
        self.assertEqual(self.raw.registerHook.call_count, 2)

    def test_button_press_release_and_sync_still_work(self):
        self.functor.process_event(Event(InputType.JoystickButton, is_pressed=True), True)
        self.assertTrue(self.functor._is_running)
        self.functor.process_event(Event(InputType.JoystickButton, is_pressed=False), False)
        self.assertFalse(self.functor._is_running)
        self.action.get_input_type = lambda: InputType.JoystickButton
        self.action.sync_mode = SyncMode.Input
        self.joystick.get_button.return_value = True
        self.functor.profile_started()
        self.assertTrue(self.functor._is_running)
        self.joystick.get_button.assert_called_once_with("joystick", 2)


if __name__ == "__main__":
    unittest.main()
