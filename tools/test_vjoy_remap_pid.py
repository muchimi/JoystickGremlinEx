"""Hardware-free checks for vJoy PID stepping and primary/latched input routing.

Run with: python tools/test_vjoy_remap_pid.py

The real functor and event-handler methods are loaded from source with device
and UI services replaced by in-memory fakes, so no joystick listeners start.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import ast
import enum
import logging
import math
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from gremlin.pid import PIDAxisTransition
from gremlin.input_types import InputType
from gremlin.types import VjoyAction, SyncMode, ButtonOutputMode

# Load real methods without starting the application's device and UI services.
source = ROOT / 'action_plugins/map_to_vjoy/__init__.py'
module = ast.parse(source.read_bytes())
classes = [n for n in module.body if isinstance(n, ast.ClassDef) and n.name in ('StepMode', 'EncoderMode', 'VJoyRemapFunctor')]
classes[-1].bases = [ast.Name(id='object', ctx=ast.Load())]
encoder = next(n for n in ast.parse((ROOT / 'gremlin/repeater.py').read_bytes()).body if isinstance(n, ast.ClassDef) and n.name == 'AcceleratedEncoder')
device, axis = NS(data={}), NS(value=0.0)
remote_control = NS(paired=False)
joystick_handling = NS(is_vjoy_connected=lambda _: True, VJoyProxy=lambda: {1: NS(axis=lambda _: axis)}, getDeviceFromVjoyId=lambda _: device)
gremlin = NS(pid=NS(PIDAxisTransition=PIDAxisTransition), util=NS(clamp=lambda value, low, high: max(low, min(high, value))), joystick_handling=joystick_handling, remote=NS(remote_control=remote_control), config=NS(Configuration=lambda: NS(verbose_mode_outputs=False, verbose_mode_vjoy=False)), keyboard=NS(sort_keys=lambda keys: keys), shared_state=NS(keyboard_tab_guid='keyboard'))
namespace = dict(enum=enum, threading=threading, time=time, math=math, gremlin=gremlin, joystick_handling=joystick_handling, remote_control=remote_control, InputType=InputType, VjoyAction=VjoyAction, SyncMode=SyncMode, ButtonOutputMode=ButtonOutputMode, syslog=logging.getLogger('pid-check'), VJoyRemapWidget=NS(input_type_buttons=[InputType.JoystickButton, InputType.Keyboard, InputType.KeyboardLatched]))
code = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), encoder, *classes], type_ignores=[])
exec(compile(ast.fix_missing_locations(code), str(source), 'exec'), namespace)
Functor, StepMode = namespace['VJoyRemapFunctor'], namespace['StepMode']

def event(primary=True, pressed=True, force_remote=False, identifier=None, device_guid=None):
    return NS(device_guid=device_guid or ('primary' if primary else 'secondary'), identifier=(1 if primary else 2) if identifier is None else identifier, is_pressed=pressed, force_remote=force_remote, is_axis=False, getInputType=lambda: InputType.JoystickButton)

class PIDChecks(unittest.TestCase):
    def make_functor(self, mode=None, acceleration=False):
        axis.value = 0.0
        device.data.clear()
        f = object.__new__(Functor)
        f._valid = True
        f.lock = threading.Lock()
        f.verbose = f.verbose_extra = False
        f.vjoy_id = f.vjoy_input_id = 1
        f.hardware_device_guid, f.hardware_input_id = 'primary', 1
        f.action_mode = VjoyAction.VJoySetAxisStepped
        f.input_item, f.device = NS(identifier=1), device
        f.action_data = NS(input_item=f.input_item, step_mode=mode or StepMode.PID, _stepped_latched=True, latched_input_type=InputType.JoystickButton, stepped_device_guid='secondary', stepped_input_type=InputType.JoystickButton, stepped_input_id=2, target_step_direction=1, exec_on_press=True, exec_on_release=False, pid_step=0.1, pid_response_time=0.05, pid_acceleration=acceleration, pid_accel_multiplier=4.0, pid_accel_start_hz=2.0, pid_accel_full_hz=12.0, pid_accel_curve=2.0, pid_accel_timeout=0.75, axis_start_value=0.0, axis_last_value=0.0, target_step_auto=False, target_step_start_index=2, target_step_list=[-1.0, -0.5, 0.0, 0.5, 1.0], sync_mode=SyncMode.Default, sendFlags=lambda: (True, False), remote_config=NS(getClientList=lambda: [0]), vjoy_id=1, vjoy_input_id=1, hardware_device_guid='primary', hardware_input_id=1, hardware_raw_input_type=InputType.JoystickButton)
        f._pid_axis_condition = threading.Condition()
        f._pid_axis = f._pid_axis_thread = f._pid_accelerator = None
        f._pid_axis_stopping = True
        f._pid_force_remote = False
        f.outputs, f.completed = [], threading.Event()
        f.functor_complete = NS(emit=f.completed.set)
        f._get_axis = lambda *args: axis.value
        def output(vid, axis_id, value, **kwargs):
            axis.value = value
            f.outputs.append((value, kwargs.get('force_remote', False)))
        f._set_axis = output
        f.synced, f._step_start_pending = True, False
        self.addCleanup(f._stop_pid_axis)
        return f

    def test_profile_start_initializes_both_pid_modes(self):
        for mode in (StepMode.PID, StepMode.SteppedPID):
            for automatic in (False, True):
                with self.subTest(mode=mode, automatic=automatic):
                    f = self.make_functor(mode)
                    f.action_data.target_step_auto = automatic
                    f.action_data.axis_start_value, axis.value = -0.5, 0.25
                    f.profile_start()
                    self.assertFalse(f._pid_axis_stopping)
                    self.assertEqual(f._pid_axis.target, 0.25 if automatic else -0.5)
                    f._stop_pid_axis()

    def test_primary_secondary_retarget_and_reverse(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                f = self.make_functor()
                f.action_data.target_step_direction = direction
                f._start_pid_axis(0.0)
                for _ in range(2):
                    f._process_pid_axis_event(event())
                self.assertAlmostEqual(f._pid_axis.target, direction * 0.2)
                f._process_pid_axis_event(event(primary=False, force_remote=True))
                self.assertAlmostEqual(f._pid_axis.target, direction * 0.1)
                self.assertTrue(f._pid_force_remote)
                f._stop_pid_axis()

    def test_press_release_configuration(self):
        for press, release in ((True, False), (False, True), (True, True), (False, False)):
            with self.subTest(press=press, release=release):
                f = self.make_functor()
                f.action_data.exec_on_press, f.action_data.exec_on_release = press, release
                f._start_pid_axis(0.0)
                f._process_pid_axis_event(event())
                self.assertAlmostEqual(f._pid_axis.target, 0.1 * press)
                f._process_pid_axis_event(event(pressed=False))
                self.assertAlmostEqual(f._pid_axis.target, 0.1 * (press + release))
                f._stop_pid_axis()

    def test_unrelated_inputs_and_stop_are_ignored(self):
        f = self.make_functor()
        f._start_pid_axis(0.0)
        for e in (event(identifier=3), event(device_guid='unrelated'), event(primary=False, identifier=3)):
            f._process_pid_axis_event(e)
            self.assertEqual(f._pid_axis.target, 0.0)
        f._stop_pid_axis()
        f._process_pid_axis_event(event())
        f._pid_set_target(0.5)
        self.assertIsNone(f._pid_axis_thread)
        self.assertEqual(f.outputs, [])

    def test_relative_acceleration_applied_once(self):
        f = self.make_functor(acceleration=True)
        f._start_pid_axis(0.0)
        f._process_pid_axis_event(event())
        self.assertAlmostEqual(f._pid_axis.target, 0.1)
        for _ in range(3):
            f._process_pid_axis_event(event())
        self.assertGreater(f._pid_axis.target, 0.4)
        f._process_pid_axis_event(event(primary=False))
        self.assertLess(f._pid_axis.target, 1.0)

    def test_stepped_pid_exact_targets_in_both_directions(self):
        for acceleration in (False, True):
            for direction in (1, -1):
                for primary in (False, True):
                    with self.subTest(acceleration=acceleration, direction=direction, primary=primary):
                        f = self.make_functor(StepMode.SteppedPID, acceleration)
                        f.action_data.target_step_direction = direction
                        f._start_pid_axis(0.0)
                        f.process_event(event(primary=primary, force_remote=True), NS(current=True, raw=True))
                        self.assertEqual(f._pid_axis.target, 0.5 * direction * (1 if primary else -1))
                        self.assertTrue(f._pid_force_remote)
                        self.assertEqual(device.data[f.getSteppedIndexDataKey()], 2 + direction * (1 if primary else -1))
                        f._stop_pid_axis()

    def test_lazy_start_animates_and_wakes_same_worker_after_settling(self):
        f = self.make_functor(StepMode.SteppedPID)
        f.process_event(event(), NS(current=True, raw=True))
        self.assertEqual(f._pid_axis.target, 0.5)
        worker = f._pid_axis_thread
        deadline = time.monotonic() + 2.0
        while not f._pid_axis.settled and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(f._pid_axis.settled)
        self.assertEqual(axis.value, 0.5)
        self.assertTrue(any(0.0 < value < 0.5 for value, _ in f.outputs))
        f.completed.clear()
        f._pid_set_target(-0.5, force_remote=True)
        self.assertIs(f._pid_axis_thread, worker)
        self.assertTrue(f.completed.wait(2.0))
        self.assertEqual(axis.value, -0.5)
        self.assertTrue(f.outputs[-1][1])
        count = len(f.outputs)
        f._stop_pid_axis()
        time.sleep(0.02)
        self.assertEqual(len(f.outputs), count)

    def test_absolute_target_does_not_apply_acceleration(self):
        f = self.make_functor(acceleration=True)
        f._start_pid_axis(0.0)
        for target in (0.5, -0.5, 1.5, -1.5):
            f._pid_set_target(target)
            self.assertEqual(f._pid_axis.target, max(-1.0, min(1.0, target)))


    def test_direction_change_during_motion_uses_new_target(self):
        for mode in (StepMode.PID, StepMode.SteppedPID):
            with self.subTest(mode=mode):
                f = self.make_functor(mode)
                f.action_data.pid_response_time = 0.5
                f.profile_start()
                f.process_event(event(), NS(current=True, raw=True))
                worker = f._pid_axis_thread
                deadline = time.monotonic() + 1.0
                while not f.outputs[-1][0] > 0.0 and time.monotonic() < deadline:
                    time.sleep(0.002)
                self.assertGreater(axis.value, 0.0)
                self.assertLess(axis.value, f._pid_axis.target)
                f.process_event(event(primary=False), NS(current=True, raw=True))
                f.process_event(event(primary=False), NS(current=True, raw=True))
                self.assertAlmostEqual(f._pid_axis.target, -0.1 if mode == StepMode.PID else -0.5)
                self.assertIs(f._pid_axis_thread, worker)
                self.assertFalse(f._pid_axis_stopping)
                f._stop_pid_axis()


    def test_stepped_pid_selects_from_target_when_cached_index_is_stale(self):
        f = self.make_functor(StepMode.SteppedPID)
        f._start_pid_axis(0.5)
        device.data[f.getSteppedIndexDataKey()] = 0
        f.process_event(event(), NS(current=True, raw=True))
        self.assertEqual(f._pid_axis.target, 1.0)

    def test_stepped_pid_reversal_ignores_output_position_and_cached_index(self):
        f = self.make_functor(StepMode.SteppedPID)
        f._start_pid_axis(0.0)
        f._pid_axis.set_target(1.0)
        device.data[f.getSteppedIndexDataKey()] = 0
        f.process_event(event(primary=False), NS(current=True, raw=True))
        self.assertEqual(f._pid_axis.target, 0.5)

    def test_stepped_pid_keyboard_release_does_not_advance_target(self):
        f = self.make_functor(StepMode.SteppedPID)
        f.action_data.latched_input_type = InputType.KeyboardLatched
        f._start_pid_axis(0.0)
        f.process_event(event(), NS(current=True, raw=True))
        self.assertEqual(f._pid_axis.target, 0.5)
        f.process_event(event(pressed=False), NS(current=False, raw=False))
        self.assertEqual(f._pid_axis.target, 0.5)

    def test_stepped_pid_finds_next_nonuniform_step_without_synchronization(self):
        f = self.make_functor(StepMode.SteppedPID)
        f.action_data.target_step_list = [-1.0, -0.6, 0.1, 0.25, 0.85, 1.0]
        f._start_pid_axis(0.25)
        f.synced = False
        f._step_start_pending = False
        f.process_event(event(), NS(current=True, raw=True))
        self.assertEqual(f._pid_axis.target, 0.85)


    def test_repeated_presses_advance_target_without_any_pid_motion(self):
        f = self.make_functor(StepMode.SteppedPID)
        f.action_data.target_step_list = [0.0, 0.25, 0.5, 0.75, 1.0]
        f._start_pid_axis(0.0)
        with f._pid_axis_condition:
            for target in (0.25, 0.5, 0.75):
                f.process_event(event(), NS(current=True, raw=True))
                self.assertEqual(f._pid_axis.target, target)
                self.assertEqual(f._pid_axis.value, 0.0)
                self.assertFalse(f._pid_axis.settled)

    def test_repeated_reverse_presses_advance_target_without_settling(self):
        f = self.make_functor(StepMode.SteppedPID)
        f._start_pid_axis(1.0)
        with f._pid_axis_condition:
            for target in (0.5, 0.0, -0.5):
                f.process_event(event(primary=False), NS(current=True, raw=True))
                self.assertEqual(f._pid_axis.target, target)
                self.assertEqual(f._pid_axis.value, 1.0)
                self.assertFalse(f._pid_axis.settled)

    def test_overlapping_presses_each_advance_the_step_target(self):
        f = self.make_functor(StepMode.SteppedPID)
        f.action_data.target_step_list = [0.0, 0.25, 0.5, 0.75, 1.0]
        f.action_data.pid_response_time = 120.0
        f._start_pid_axis(0.0)
        original_next = f._first_step_index
        barrier = threading.Barrier(2)
        errors = []
        def next_step(value, direction):
            try:
                barrier.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                pass
            return original_next(value, direction)
        f._first_step_index = next_step
        def press():
            try:
                f.process_event(event(), NS(current=True, raw=True))
            except BaseException as error:
                errors.append(error)
        threads = [threading.Thread(target=press) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(f._pid_axis.target, 0.5)
        self.assertFalse(f._pid_axis.settled)


# Exercise the actual keyboard registration and dispatch methods as well as the functor.
import copy
import traceback
from typing import Callable

class CheckKey:
    def __init__(self, scan_code, modifiers=()):
        self.scan_code, self.is_extended = scan_code, False
        self.modifiers = list(modifiers)
        self.name, self.is_mouse = str(scan_code), False
    @property
    def key_tuple(self):
        return self.scan_code, self.is_extended
    def index_tuple(self):
        return self.key_tuple
    def getKeys(self):
        return [self, *self.modifiers]

class CheckKeyboardInput:
    def __init__(self, primary, secondary):
        self.key = primary
        self.identifier = primary.key_tuple
        self.enabled = True
        self.extra_data = {}
        self.display_name = 'Shift+F21 with latched Shift+F20'
        self.chords = [primary, secondary]
    def getLatchedInputIds(self):
        return self.chords

class CheckKeyboardEvent:
    def __init__(self, identifier, pressed=True, data=None, extra_data=None, **kwargs):
        self.identifier, self.is_pressed = identifier, pressed
        self.data, self.extra_data = data, extra_data
        self.event_type, self.device_guid = InputType.Keyboard, 'keyboard'
        self.mode, self.is_axis, self.force_remote = 'Default', False, False
    @property
    def callbackKey(self):
        key = self.identifier.index_tuple() if isinstance(self.identifier, CheckKey) else self.identifier
        return 'keyboard', InputType.KeyboardLatched, key, 0
    def getInputType(self):
        return (self.extra_data or {}).get('override_input_type', self.event_type)

handler_tree = ast.parse((ROOT / 'gremlin/event_handler.py').read_bytes())
handler_class = next(n for n in handler_tree.body if isinstance(n, ast.ClassDef) and n.name == 'EventHandler')
latched_class = next(n for n in handler_tree.body if isinstance(n, ast.ClassDef) and n.name == 'LatchedCallbackData')
wanted = {'addCallback', 'execute_event', '_execute_event', '_trigger_callbacks', '_trigger_functor_callbacks', '_execute_callbacks', '_matching_latched_callbacks'}
methods = [copy.deepcopy(n) for n in handler_class.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
class NoAppImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return ast.Pass() if all(a.name.startswith('gremlin') for a in node.names) else node
methods = [NoAppImports().visit(n) for n in methods]
handler_definition = ast.ClassDef(name='CheckHandler', bases=[], keywords=[], body=methods, decorator_list=[])
handler_config = NS(verbose_mode_inputs=False, verbose_mode_exec=False, verbose_mode_extra=False, voice_enabled=False)
handler_gremlin = NS(config=NS(Configuration=lambda: handler_config), keyboard=NS(Key=CheckKey, KeyMap=NS(reverse_translate=lambda key: key)), ui=NS(keyboard_device=NS(KeyboardInputItem=CheckKeyboardInput)), joystick_handling=NS(getValidJoystickDevicesMap=lambda: {}), shared_state=NS(), types=NS(MouseButton=type('MouseButton', (), {})), event_handler=NS(EventListener=lambda: NS(get_key_state=lambda key: False)))
handler_namespace = dict(gremlin=handler_gremlin, dinput=NS(GUID=str), Event=CheckKeyboardEvent, InputType=InputType, Callable=Callable, syslog=logging.getLogger('keyboard-check'), traceback=traceback)
handler_namespace['EventListener'] = handler_gremlin.event_handler.EventListener
handler_code = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), copy.deepcopy(latched_class), handler_definition], type_ignores=[])
exec(compile(ast.fix_missing_locations(handler_code), 'gremlin/event_handler.py', 'exec'), handler_namespace)
CheckHandler = handler_namespace['CheckHandler']

class LatchedRoutingChecks(unittest.TestCase):
    def setup_mapping(self):
        f = PIDChecks.make_functor(self, StepMode.SteppedPID)
        shift = CheckKey(42)
        primary, secondary = CheckKey(108, [shift]), CheckKey(107, [shift])
        item = CheckKeyboardInput(primary, secondary)
        f.hardware_device_guid, f.hardware_input_id, f.input_item = 'keyboard', item, item
        f.action_data.input_item = item
        f.action_data.latched_input_type = InputType.KeyboardLatched
        f.action_data.latched_keys = [shift, secondary]
        f.action_data.stepped_device_guid = 'keyboard'
        f.action_data.stepped_input_id = secondary
        f._start_pid_axis(0.0)
        h = CheckHandler()
        h.registry = NS(update=lambda e: None)
        h.process_callbacks = True
        h.latched_callbacks, h.latched_input_map = {}, {}
        h._keyboard_callback_map = {}
        h._install_plugins = lambda cb: cb
        h._mode_lookup_chain = lambda e: ('Default',)
        h._matching_input_item = lambda mode, e: h.latched_input_map.get(e.device_guid, {}).get(mode, {}).get(e.callbackKey, [])
        callback = lambda e: f.process_event(e, NS(current=e.is_pressed, raw=e.is_pressed), e.extra_data)
        h.addCallback('keyboard', 'Default', CheckKeyboardEvent(item), callback, extra_data={'input_item': item})
        h.addCallback('keyboard', 'Default', CheckKeyboardEvent(secondary), callback, extra_data={'input_item': item, 'latched': True, 'action_data': f.action_data})
        return f, h, primary, secondary, shift


    def test_down_button_on_another_device_runs_alongside_its_own_mapping(self):
        f, h, up, down, shift = self.setup_mapping()
        f.hardware_device_guid, f.hardware_input_id = 'primary', 1
        f.input_item = f.action_data.input_item = NS(identifier=1)
        f.action_data.latched_input_type = InputType.JoystickButton
        f.action_data.stepped_device_guid = 'secondary'
        f.action_data.stepped_input_type = InputType.JoystickButton
        f.action_data.stepped_input_id = 2
        e = event(primary=False)
        e.event_type, e.extra_data, e.value, e.mode = InputType.JoystickButton, None, True, 'Default'
        native_calls = []
        h._matching_callbacks = lambda e, item: [lambda e: native_calls.append(e)]
        h._matching_functors = lambda e: [f]
        handler_gremlin.actions = NS(Value=lambda value: NS(current=value, raw=value))
        with f._pid_axis_condition:
            h._execute_event(e, NS(enabled=True, display_name='Secondary device button'))
            self.assertEqual(native_calls, [e])
            self.assertEqual(f._pid_axis.target, -0.5)

    def test_reverse_shortcut_has_its_own_registration(self):
        f, h, up, down, shift = self.setup_mapping()
        callbacks = h.latched_callbacks['keyboard']['Default']
        self.assertEqual(len(callbacks[CheckKeyboardEvent(up).callbackKey][f.input_item]), 1)
        self.assertEqual(len(callbacks[CheckKeyboardEvent(down).callbackKey][f.input_item]), 1)

    def test_primary_goes_up_and_latched_second_input_goes_down_once(self):
        f, h, up, down, shift = self.setup_mapping()
        with f._pid_axis_condition:
            h.execute_event(CheckKeyboardEvent(up.key_tuple, data={shift.key_tuple: True, up.key_tuple: True}))
            self.assertEqual(f._pid_axis.target, 0.5)
            h.execute_event(CheckKeyboardEvent(down.key_tuple, data={shift.key_tuple: True, down.key_tuple: True}))
            self.assertEqual(f._pid_axis.target, 0.0)

    def test_primary_chord_completed_by_modifier_still_goes_up(self):
        f, h, up, down, shift = self.setup_mapping()
        with f._pid_axis_condition:
            h.execute_event(CheckKeyboardEvent(shift.key_tuple, data={shift.key_tuple: True, up.key_tuple: True}))
            self.assertEqual(f._pid_axis.target, 0.5)

    def test_latched_chord_completed_by_modifier_goes_down_once(self):
        f, h, up, down, shift = self.setup_mapping()
        with f._pid_axis_condition:
            h.execute_event(CheckKeyboardEvent(shift.key_tuple, data={shift.key_tuple: True, down.key_tuple: True}))
            self.assertEqual(f._pid_axis.target, -0.5)

if __name__ == '__main__':
    unittest.main(verbosity=2)
