"""Hardware-free KVM routing and hat checks: python tools/test_kvm.py.

Load the real action and hat-normalization code with device hooks and remote
output replaced by mocks, so these checks cannot suppress or send real input.
"""

import ast
import logging
import sys
import threading
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
from gremlin.types import SyncMode, VjoyAction  # noqa: E402


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


class BaseAction:
    def __init__(self, parent=None, extra_data=None):
        self.remote_config = NS(localEnabled=True, remoteProfileEnabled=True, remote=False)


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self):
        for callback in tuple(self.callbacks):
            callback()


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
        self.raw.RawInputDataType = NS(Motion="motion", Button="button")
        self.joystick = Mock()
        self.joystick.get_hat_position.return_value = (0, 0)
        self.cursor = NS(GetCursorPos=Mock(return_value=(100, 200)))
        self.listener = NS(remote_control_state_change=Signal(), config_changed=Signal())
        self.config = NS(verbose_mode_remote=False, enable_remote_broadcast=True)
        self.config.remoteEnabled = lambda: self.config.enable_remote_broadcast
        self.services = NS(
            base_profile=NS(AbstractFunctor=BaseFunctor),
            input_item=NS(AbstractAction=BaseAction),
            windows_event_hook=NS(MouseHook=lambda: self.mouse, KeyboardHook=lambda: self.keyboard),
            remote=NS(remote_client=self.remote),
            raw_input=self.raw,
            config=NS(Configuration=lambda: self.config),
            joystick_handling=self.joystick,
            event_handler=NS(Event=Event, EventListener=lambda: self.listener),
            fsm=gremlin.fsm,
            singleton_decorator=NS(SingletonDecorator=lambda cls: cls),
            shared_state=NS(is_running=True),
        )
        remote_namespace = {
            "gremlin": self.services, "Signal": Signal, "VjoyAction": VjoyAction,
            "syslog": logging.getLogger("kvm-checks"),
        }
        load_definitions("gremlin/remote.py", {"RemoteControl", "RemoteConfig"}, remote_namespace)
        self.control = object.__new__(remote_namespace["RemoteControl"])
        self.control._is_local = False
        self.control._is_remote = True
        self.control._is_paired = False
        self.control._global_remote_enabled = True
        remote_namespace["RemoteControl"] = lambda: self.control
        self.routing = object.__new__(remote_namespace["RemoteConfig"])
        self.routing._local = self.routing._local_enabled = True
        self.routing._remote = self.routing._remote_enabled = True
        self.routing._remote_profile = self.routing._remote_profile_enabled = True
        self.routing.getClientList = lambda: [7]
        self.namespace = {
            "gremlin": self.services, "InputType": InputType, "SyncMode": SyncMode,
            "syslog": logging.getLogger("kvm-checks"), "win32api": self.cursor,
            "KVMWidget": object, "ABCMeta": ABCMeta, "abstractmethod": abstractmethod,
            "AbstractCondition": object, "threading": threading,
            "win32con": NS(KEYEVENTF_EXTENDEDKEY=1, KEYEVENTF_KEYUP=2),
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
            remote_config=self.routing,
            sendFlags=lambda: self.routing.state,
            mouse_enabled=True, keyboard_enabled=True,
            invert_x=False, invert_y=False, rotate=False,
        )
        self.functor = self.namespace["KVMFunctor"](self.action)

    def key(self, pressed=True, extended=False, injected=False):
        return NS(virtual_code=0x41, scan_code=0x1E, is_extended=extended, is_pressed=pressed, is_injected=injected)

    def mouse_packets(self):
        return [
            NS(contentType="motion", dx=3, dy=-2),
            NS(contentType="button", button_id=1, is_pressed=True),
            NS(contentType="button", button_id=6, is_pressed=True),
        ]

    def test_action_allows_local_and_profile_remote_routing(self):
        action = self.namespace["KVM"](None)
        self.assertTrue(action.remote_config.localEnabled)
        self.assertTrue(action.remote_config.remoteProfileEnabled)
        self.assertTrue(action.remote_config.remote)

    def test_output_modes_route_keyboard_mouse_and_wheel(self):
        for mode, local, remote in (
            (VjoyAction.VJoyEnableLocalOnly, True, False),
            (VjoyAction.VJoyEnableRemoteOnly, False, True),
            (VjoyAction.VJoyEnableLocalAndRemote, True, True),
        ):
            with self.subTest(mode=mode):
                self.control.mode = mode
                self.functor.profile_started()
                self.functor.start()
                self.functor._keyboard_handler(self.key())
                self.functor._mouse_move_handler(self.mouse_packets())
                self.functor._mouse_wheel_handler(-120, True)
                self.assertEqual(self.mouse.pushSuppress.call_count, int(not local))
                self.assertEqual(self.keyboard.pushSuppress.call_count, int(not local))
                self.assertEqual(self.remote.send_kvm_mouse_motion_start.call_count, int(remote))
                self.assertEqual(self.remote.send_kvm_keyboard.call_count, int(remote))
                self.assertEqual(self.remote.send_kvm_mouse_motion.call_count, int(remote))
                self.assertEqual(self.remote.send_kvm_mouse_button.call_count, 2 * int(remote))
                self.assertEqual(self.remote.send_kvm_mouse_wheel.call_count, int(remote))
                if remote:
                    self.remote.send_kvm_mouse_motion.assert_called_once_with(0, 0, 3, -2, client_list=[7])
                    self.remote.send_kvm_mouse_motion_start.assert_called_once_with(client_list=[7])
                self.functor.stop()
                self.assertEqual(self.mouse.popSuppress.call_count, int(not local))
                self.assertEqual(self.keyboard.popSuppress.call_count, int(not local))
                for mock in (self.mouse, self.keyboard, self.remote):
                    mock.reset_mock()

    def test_local_mode_changes_update_suppression_without_restarting_kvm(self):
        self.functor.start()
        self.control.setLocal(True)
        self.mouse.popSuppress.assert_called_once_with()
        self.keyboard.popSuppress.assert_called_once_with()
        self.assertTrue(self.functor._is_running)
        self.raw.registerUnhook.assert_not_called()
        self.remote.send_kvm_mouse_motion_stop.assert_not_called()
        self.control.setLocal(False)
        self.listener.remote_control_state_change.emit()
        self.assertEqual(self.mouse.pushSuppress.call_count, 2)
        self.assertEqual(self.keyboard.pushSuppress.call_count, 2)
        self.remote.send_kvm_mouse_motion_start.assert_called_once_with(client_list=[0])
        self.functor.stop()
        self.assertEqual(self.mouse.popSuppress.call_count, 2)
        self.assertEqual(self.keyboard.popSuppress.call_count, 2)

    def test_mode_notification_contains_complete_state(self):
        states = []
        self.listener.remote_control_state_change.connect(lambda: states.append(self.routing.state))
        self.control.mode = VjoyAction.VJoyEnableLocalOnly
        self.assertEqual(states, [(True, False)])

    def test_direct_local_state_change_notifies_active_kvm(self):
        self.functor.start()
        self.control.is_local = True
        self.mouse.popSuppress.assert_called_once_with()
        self.keyboard.popSuppress.assert_called_once_with()

    def test_disabling_remote_releases_held_input_and_stops_forwarding(self):
        self.functor.profile_started()
        self.functor.start()
        self.functor._keyboard_handler(self.key(extended=True))
        self.functor._mouse_move_handler(self.mouse_packets())
        self.control.mode = VjoyAction.VJoyEnableLocalOnly
        self.remote.send_kvm_keyboard.assert_called_with(0x41, 0x1E, 3, client_list=[7])
        self.remote.send_kvm_mouse_button.assert_called_with(1, False, client_list=[7])
        self.remote.send_kvm_mouse_motion_stop.assert_called_once_with(client_list=[7])
        self.assertEqual(self.remote.send_kvm_mouse_button.call_count, 3)  # No release for a wheel packet.
        self.remote.reset_mock()
        self.functor._keyboard_handler(self.key(pressed=False))
        self.functor._mouse_move_handler(self.mouse_packets())
        self.functor._mouse_wheel_handler(120, False)
        self.functor.stop()
        self.assertEqual(self.remote.mock_calls, [])
        self.assertEqual(self.listener.remote_control_state_change.callbacks, [])
        self.assertEqual(self.listener.config_changed.callbacks, [])

    def test_profile_stop_releases_remote_keys_and_buttons(self):
        self.functor.start()
        self.functor._keyboard_handler(self.key())
        self.functor._mouse_move_handler(self.mouse_packets())
        self.functor.profile_stop()
        self.remote.send_kvm_keyboard.assert_called_with(0x41, 0x1E, 2, client_list=[0])
        self.remote.send_kvm_mouse_button.assert_called_with(1, False, client_list=[0])
        self.assertFalse(self.functor._remote_keys)
        self.assertFalse(self.functor._remote_buttons)

    def test_extended_and_non_extended_keys_are_released_independently(self):
        self.functor.start()
        self.functor._keyboard_handler(self.key())
        self.functor._keyboard_handler(self.key(extended=True))
        self.remote.reset_mock()
        self.functor.stop()
        self.assertEqual([call.args[2] for call in self.remote.send_kvm_keyboard.call_args_list], [2, 3])

    def test_stop_releases_an_inflight_key_before_remote_mouse_stops(self):
        entered = threading.Event()
        finish = threading.Event()

        def send_key(*args, **kwargs):
            if args[2] == 0:
                entered.set()
                finish.wait(2)

        self.remote.send_kvm_keyboard.side_effect = send_key
        self.functor.start()
        worker = threading.Thread(target=self.functor._keyboard_handler, args=(self.key(),))
        worker.start()
        self.assertTrue(entered.wait(2))
        stopper = threading.Thread(target=self.functor.stop)
        stopper.start()
        finish.set()
        worker.join(2)
        stopper.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual([call.args[2] for call in self.remote.send_kvm_keyboard.call_args_list], [0, 2])
        self.assertEqual(self.remote.mock_calls[-1][0], "send_kvm_mouse_motion_stop")

    def test_released_input_is_not_released_again_on_stop(self):
        self.functor.start()
        self.functor._keyboard_handler(self.key())
        self.functor._keyboard_handler(self.key(pressed=False))
        self.functor._mouse_move_handler([NS(contentType="button", button_id=1, is_pressed=True)])
        self.functor._mouse_move_handler([NS(contentType="button", button_id=1, is_pressed=False)])
        self.remote.reset_mock()
        self.functor.stop()
        self.remote.send_kvm_keyboard.assert_not_called()
        self.remote.send_kvm_mouse_button.assert_not_called()

    def test_disabled_channels_are_not_hooked_suppressed_or_forwarded(self):
        self.action.mouse_enabled = self.action.keyboard_enabled = False
        self.functor.start()
        self.functor._keyboard_handler(self.key())
        self.functor._mouse_move_handler(self.mouse_packets())
        self.functor._mouse_wheel_handler(120, False)
        self.functor.stop()
        self.assertEqual(self.remote.mock_calls, [])
        self.assertEqual(self.mouse.mock_calls, [])
        self.assertEqual(self.keyboard.mock_calls, [])
        self.assertEqual(self.raw.mock_calls, [])

    def test_keyboard_only_and_mouse_only_routing(self):
        for mouse_enabled in (False, True):
            with self.subTest(mouse_enabled=mouse_enabled):
                self.action.mouse_enabled = mouse_enabled
                self.action.keyboard_enabled = not mouse_enabled
                self.functor.start()
                self.functor._keyboard_handler(self.key())
                self.functor._mouse_move_handler(self.mouse_packets())
                self.assertEqual(self.mouse.pushSuppress.call_count, int(mouse_enabled))
                self.assertEqual(self.keyboard.pushSuppress.call_count, int(not mouse_enabled))
                self.assertEqual(self.remote.send_kvm_keyboard.call_count, int(not mouse_enabled))
                self.assertEqual(self.remote.send_kvm_mouse_motion.call_count, int(mouse_enabled))
                self.functor.stop()
                for mock in (self.mouse, self.keyboard, self.remote):
                    mock.reset_mock()

    def test_global_remote_disable_stops_forwarding(self):
        self.control.setLocal(True)
        self.functor.start()
        self.config.enable_remote_broadcast = False
        self.listener.config_changed.emit()
        self.remote.send_kvm_mouse_motion_stop.assert_called_once_with(client_list=[0])
        self.functor._keyboard_handler(self.key())
        self.remote.send_kvm_keyboard.assert_not_called()
        self.config.enable_remote_broadcast = True
        self.listener.config_changed.emit()
        self.functor._keyboard_handler(self.key())
        self.remote.send_kvm_keyboard.assert_called_once_with(0x41, 0x1E, 0, client_list=[0])

    def test_remote_mouse_transforms_preserved_in_concurrent_mode(self):
        self.control.mode = VjoyAction.VJoyEnableLocalAndRemote
        self.action.invert_x = self.action.invert_y = self.action.rotate = True
        self.functor.start()
        self.functor._mouse_move_handler([self.mouse_packets()[0]])
        self.remote.send_kvm_mouse_motion.assert_called_once_with(0, 0, 2, -3, client_list=[0])
        self.mouse.pushSuppress.assert_not_called()

    def test_injected_and_queued_events_after_stop_are_not_forwarded(self):
        self.functor.start()
        self.functor._keyboard_handler(self.key(injected=True))
        self.remote.send_kvm_keyboard.assert_not_called()
        self.functor.stop()
        self.remote.reset_mock()
        self.functor._keyboard_handler(self.key())
        self.functor._mouse_move_handler(self.mouse_packets())
        self.functor._mouse_wheel_handler(120, False)
        self.assertEqual(self.remote.mock_calls, [])

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
