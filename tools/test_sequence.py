"""Sequence execution checks without hardware, profile services, or live output.

Run with: python -m pytest tools/test_sequence.py -q -p no:cacheprovider
Real sequence classes run with fake application services and real worker threads.
"""

import ast
import random
import sys
import threading
import time
import unittest
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType  # noqa: E402
from gremlin.singleton_decorator import SingletonDecorator  # noqa: E402
from gremlin.types import Interactions, SyncMode  # noqa: E402


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in self.callbacks:
            callback()


class BaseContainer:
    def __init__(self, *args, **kwargs):
        self.activation_condition = NS(conditions=[])
        self.id = "sequence-check"
        self.comment = "test sequence"
        self.hardware_device_guid = "joystick"
        self.hardware_input_id = 1

    def get_input_type(self):
        return InputType.JoystickButton


class BaseFunctor:
    def __init__(self, action_data, parent=None):
        self.action_data = action_data
        self.id = action_data.id
        self.valid = True

    def profile_started(self):
        pass


class Event:
    def __init__(self, event_type, identifier, device_guid, is_pressed, **kwargs):
        self.is_pressed = is_pressed

    def fake_button(self, is_pressed, force=False):
        return NS(is_pressed=is_pressed)


def load_sequence(source=None):
    """Load production definitions without importing the application/device hooks."""
    config = NS(
        max_concurrent_sequence=0, verbose_mode_container=False,
        verbose_mode_sequence=False, verbose_mode_extra=False,
        mode_change_aborts_sequence=True, macro_mode_affinity=True,
    )
    listener = NS(profile_start=Signal())
    services = NS(
        config=NS(Configuration=lambda: config),
        base_profile=NS(AbstractSelfTriggerFunctor=BaseFunctor),
        input_item=NS(BaseInputActionCondition=type("InputCondition", (), {})),
        event_handler=NS(EventListener=lambda: listener, Event=Event, EventHandler=Mock()),
        shared_state=NS(current_mode="Default", fake_tab_guid="fake"),
        joystick_handling=NS(get_button=Mock(return_value=False)),
    )
    thread_api = NS(**{name: getattr(threading, name) for name in ("Lock", "RLock", "Event", "Thread", "current_thread")})
    namespace = dict(
        gremlin=services, threading=thread_api, random=NS(randint=random.randint, randrange=random.randrange),
        time=NS(time=time.time, monotonic=time.monotonic, sleep=time.sleep), IntEnum=IntEnum, syslog=Mock(),
        SingletonDecorator=SingletonDecorator, InputType=InputType, SyncMode=SyncMode,
        Interactions=Interactions, AbstractContainer=BaseContainer,
        QtCore=NS(Slot=lambda *args: lambda method: method), QtWidgets=NS(QWidget=object),
        SequenceContainerWidget=object, ElementTree=etree,
    )
    util_names = {"safeJoin"}
    util_nodes = [node for node in ast.parse((ROOT / "gremlin/util.py").read_bytes()).body if getattr(node, "name", None) in util_names]
    exec(compile(ast.Module(body=util_nodes, type_ignores=[]), "gremlin/util.py", "exec"), namespace)
    services.util = NS(safeJoin=namespace["safeJoin"])
    names = {"SequenceMode", "SequenceRepeatMode", "GlobalSequence", "StepOptions", "StepOptionsWidget", "SequenceContainerFunctor", "SequenceContainer"}
    assignments = {"_SEQUENCE_MODE_LOOKUP", "_SEQUENCE_REPEAT_MODE_LOOKUP", "_global_sequence"}
    nodes = []
    for node in ast.parse(source if source is not None else (ROOT / "container_plugins/sequence/__init__.py").read_bytes()).body:
        if getattr(node, "name", None) in names or (
            isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in assignments for target in node.targets)
        ):
            nodes.append(node)
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *nodes,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "container_plugins/sequence/__init__.py", "exec"), namespace)
    return namespace, config, listener


class SequenceChecks(unittest.TestCase):
    def setUp(self):
        self.ns, self.config, self.listener = load_sequence()
        self.mode = self.ns["SequenceMode"]
        self.repeat = self.ns["SequenceRepeatMode"]
        self.global_sequence = self.ns["_global_sequence"]
        self.functors = []
        self.calls = []

    def tearDown(self):
        for functor in self.functors:
            functor._stop_runner()

    def make_functor(self, mode=None, count=3):
        container = self.ns["SequenceContainer"]()
        container.mode = self.mode.Normal if mode is None else mode
        container.normal_autorelease_delay = 0
        container.wiggle_exec_delay = 0
        container.wiggle_step_delay = 0
        container.wiggle_min_delay = container.wiggle_max_delay = 0
        functor = self.ns["SequenceContainerFunctor"](container)
        functor.action_set_nodes = [NS(id=index) for index in range(count)]
        functor._ec = NS(execute_node=lambda node, event, pressed, extra: self.calls.append((node.id, pressed, bool(extra and extra.get("sequence_end")))))
        self.functors.append(functor)
        return functor

    def run_direct(self, functor, runner):
        functor.action_data._is_running = True
        functor._stop_event.clear()
        getattr(functor, runner)()

    def join_runner(self, functor):
        thread = functor.action_data._thread
        if thread is not None:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive(), "Sequence worker did not finish")
        self.assertFalse(functor.action_data._is_running)
        self.assertIsNone(functor.action_data._thread)

    def test_concurrency_limit_includes_exactly_the_configured_number(self):
        for limit in (0, 1, 3):
            with self.subTest(limit=limit):
                self.config.max_concurrent_sequence = limit
                self.global_sequence.resetSequenceCount()
                count = limit or 5
                for _ in range(count):
                    self.assertTrue(self.global_sequence.canExecute())
                    self.assertTrue(self.global_sequence.tryPushSequence())
                self.assertEqual(self.global_sequence.sequence_count, count)
                if limit:
                    self.assertFalse(self.global_sequence.canExecute())
                    self.assertFalse(self.global_sequence.tryPushSequence())
                for _ in range(count + 1):
                    self.global_sequence.popSequence()
                self.assertEqual(self.global_sequence.sequence_count, 0)

    def test_concurrent_reservations_are_atomic(self):
        self.config.max_concurrent_sequence = 3
        barrier = threading.Barrier(17)
        results = []
        result_lock = threading.Lock()

        def reserve():
            barrier.wait(timeout=2)
            reserved = self.global_sequence.tryPushSequence()
            with result_lock:
                results.append(reserved)

        threads = [threading.Thread(target=reserve) for _ in range(16)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results.count(True), 3)
        self.assertEqual(self.global_sequence.sequence_count, 3)

    def test_profile_signal_resets_global_count_once(self):
        self.global_sequence.pushSequence()
        self.assertEqual(len(self.listener.profile_start.callbacks), 1)
        self.listener.profile_start.emit()
        self.assertEqual(self.global_sequence.sequence_count, 0)

    def test_profile_start_does_not_reset_another_functors_reservation(self):
        functor = self.make_functor()
        self.global_sequence.pushSequence()
        functor.profile_start()
        self.assertEqual(self.global_sequence.sequence_count, 1)

    def test_long_wait_uses_one_event_wait_and_a_bounded_sleep_tail(self):
        functor = self.make_functor()
        functor.action_data._is_running = True
        functor._stop_event = Mock()
        self.ns["time"].time = Mock(side_effect=AssertionError("wall clock read"))
        self.ns["time"].monotonic = Mock(side_effect=[1, 1.234375, 1.24609375, 1.25])
        self.ns["time"].sleep = Mock()
        functor._wait(.25)
        functor._stop_event.wait.assert_called_once_with(.23)
        self.assertEqual([call.args[0] for call in self.ns["time"].sleep.call_args_list], [.01, .00390625])
        functor._wait(0)
        functor._wait(-1)
        functor.action_data._is_running = False
        functor._wait(30)
        self.assertEqual(functor._stop_event.wait.call_count, 1)

    def test_short_wait_sleeps_only_the_remaining_delay(self):
        functor = self.make_functor()
        functor.action_data._is_running = True
        functor._stop_event = Mock()
        self.ns["time"].monotonic = Mock(side_effect=[0, 0, .001])
        self.ns["time"].sleep = Mock()
        functor._wait(.001)
        functor._stop_event.wait.assert_not_called()
        self.ns["time"].sleep.assert_called_once_with(.001)

    def test_stop_wakes_a_long_wait_and_runner_can_restart(self):
        functor = self.make_functor()
        for _ in range(2):
            entered = threading.Event()
            exited = threading.Event()

            def runner():
                entered.set()
                functor._wait(30)
                exited.set()

            functor._start_runner(runner, "sequence-wait-check")
            self.assertTrue(entered.wait(timeout=2))
            self.assertEqual(self.global_sequence.sequence_count, 1)
            functor._stop_runner()
            self.assertTrue(exited.is_set())
            self.join_runner(functor)
            self.assertEqual(self.global_sequence.sequence_count, 0)

    def test_duplicate_start_does_not_allocate_another_thread(self):
        functor = self.make_functor()
        entered = threading.Event()

        def runner():
            entered.set()
            functor._wait(30)

        functor._start_runner(runner, "sequence-start-check")
        self.assertTrue(entered.wait(timeout=2))
        thread = functor.action_data._thread
        duplicate = Mock()
        functor._start_runner(duplicate, "duplicate")
        self.assertIs(functor.action_data._thread, thread)
        duplicate.assert_not_called()
        self.assertEqual(self.global_sequence.sequence_count, 1)

    def test_limit_rejection_does_not_change_runner_state(self):
        self.config.max_concurrent_sequence = 1
        self.global_sequence.pushSequence()
        functor = self.make_functor()
        runner = Mock()
        functor._start_runner(runner, "limited")
        runner.assert_not_called()
        self.assertFalse(functor.action_data._is_running)
        self.assertIsNone(functor.action_data._thread)
        self.assertEqual(self.global_sequence.sequence_count, 1)

    def test_thread_creation_and_start_failures_release_the_reservation(self):
        functor = self.make_functor()
        for constructor in (Mock(side_effect=RuntimeError("constructor failed")), Mock(return_value=NS(start=Mock(side_effect=RuntimeError("start failed"))))):
            with self.subTest(constructor=constructor), patch.object(self.ns["threading"], "Thread", constructor):
                with self.assertRaises(RuntimeError):
                    functor._start_runner(lambda: None, "broken")
                self.assertEqual(self.global_sequence.sequence_count, 0)
                self.assertFalse(functor.action_data._is_running)
                self.assertIsNone(functor.action_data._thread)
                self.assertTrue(functor._stop_event.is_set())

    def test_runner_exception_releases_the_reservation(self):
        functor = self.make_functor()
        self.global_sequence.pushSequence()
        functor.action_data._is_running = True
        functor.action_data._thread = threading.current_thread()
        with self.assertRaisesRegex(RuntimeError, "execution failed"):
            functor._run_runner(Mock(side_effect=RuntimeError("execution failed")))
        self.assertEqual(self.global_sequence.sequence_count, 0)
        self.assertFalse(functor.action_data._is_running)
        self.assertIsNone(functor.action_data._thread)

    def test_normal_sequence_runs_in_order_and_sends_end_notifications(self):
        functor = self.make_functor()
        self.run_direct(functor, "_normal_runner")
        self.assertEqual(self.calls, [
            (0, True, False), (0, False, False),
            (1, True, False), (1, False, False),
            (2, True, False), (2, False, False),
            (0, False, True), (1, False, True), (2, False, True),
        ])
        self.assertFalse(functor.action_data._is_running)
        self.ns["syslog"].info.assert_not_called()

    def test_normal_mode_always_starts_at_the_first_step(self):
        functor = self.make_functor()
        functor.action_data.resume_mode = True
        functor.action_data.last_step = 2
        self.run_direct(functor, "_normal_runner")
        self.assertEqual(self.calls[0], (0, True, False))

    def test_repeats_preserve_autorelease_and_interval_delays(self):
        for runner in ("_normal_runner", "_stepped_runner"):
            with self.subTest(runner=runner):
                self.calls.clear()
                functor = self.make_functor(count=1)
                options = functor.action_data.getOptions(0)
                options.mode = self.repeat.Loop
                options.repeat_count = 3
                options.repeat_min_delay = 7
                options.autorelease_min_delay = 11
                functor._wait = Mock()
                self.run_direct(functor, runner)
                self.assertEqual([call.args[0] for call in functor._wait.call_args_list], [.011, .007, .011, .007, .011])
                self.assertEqual([call for call in self.calls if not call[2]], [(0, pressed, False) for _ in range(3) for pressed in (True, False)])

    def test_random_repeat_can_skip_a_step(self):
        functor = self.make_functor(count=1)
        options = functor.action_data.getOptions(0)
        options.mode = self.repeat.Random
        self.ns["random"].randint = Mock(return_value=0)
        self.run_direct(functor, "_normal_runner")
        self.assertEqual(self.calls, [(0, False, True)])

    def test_stepped_mode_cycles_one_step_per_trigger(self):
        functor = self.make_functor(self.mode.Step)
        for _ in range(4):
            self.run_direct(functor, "_stepped_runner")
        self.assertEqual([node for node, pressed, _ in self.calls if pressed], [0, 1, 2, 0])
        self.assertEqual(functor._current_step, 1)

    def test_stepped_resume_and_profile_reset(self):
        functor = self.make_functor(self.mode.Step)
        functor.action_data.resume_mode = True
        functor.action_data.last_step = 2
        self.run_direct(functor, "_stepped_runner")
        self.assertEqual(self.calls[0], (2, True, False))
        functor.action_data.stepped_exec_reset = True
        functor.profile_start()
        self.assertIsNone(functor._current_step)

    def test_loop_and_wiggle_resume_safely_after_steps_are_removed(self):
        for runner, mode in (("_normal_runner", self.mode.Loop), ("_wiggle_runner", self.mode.Wiggle)):
            with self.subTest(runner=runner):
                self.calls.clear()
                functor = self.make_functor(mode)
                functor.action_data.resume_mode = True
                functor.action_data.last_step = 99

                def execute(node, event, pressed, extra):
                    self.calls.append((node.id, pressed))
                    if pressed:
                        functor._stop_runner()

                functor._ec.execute_node = execute
                self.run_direct(functor, runner)
                self.assertEqual(self.calls[0], (0, True))
                self.assertEqual(self.calls[1], (0, False))

    def test_wiggle_stops_at_the_requested_step_count(self):
        functor = self.make_functor(self.mode.Wiggle, count=2)
        functor.action_data.wiggle_count_enabled = True
        functor.action_data.wiggle_count_min = functor.action_data.wiggle_count_max = 3
        self.run_direct(functor, "_wiggle_runner")
        self.assertEqual([node for node, pressed, _ in self.calls if pressed], [0, 1, 0])
        self.assertFalse(functor.action_data._is_running)

    def test_random_wiggle_honors_repeat_delays_without_unused_random_draws(self):
        functor = self.make_functor(self.mode.Wiggle, count=1)
        data = functor.action_data
        data.wiggle_count_enabled = True
        data.wiggle_count_min = data.wiggle_count_max = 1
        data.wiggle_min_delay, data.wiggle_max_delay = 20, 40
        options = data.getOptions(0)
        options.mode = self.repeat.Loop
        options.repeat_count = 3
        options.repeat_min_delay = 7
        options.autorelease_min_delay = 11
        functor._wait = Mock()
        self.ns["random"].randrange = Mock(return_value=30)
        self.run_direct(functor, "_wiggle_runner")
        self.assertEqual([call.args[0] for call in functor._wait.call_args_list], [.011, .007, .011, .007, .011, .030])
        self.ns["random"].randrange.assert_called_once_with(20, 40)

    def test_cancellation_during_a_pulse_still_releases_the_active_step(self):
        for mode, start in ((self.mode.Normal, "start_normal"), (self.mode.Step, "start_stepped"), (self.mode.Wiggle, "start_wiggle")):
            with self.subTest(mode=mode):
                self.calls.clear()
                functor = self.make_functor(mode)
                functor.action_data.normal_autorelease_delay = 30_000
                functor.action_data.wiggle_exec_delay = 30_000

                def execute(node, event, pressed, extra):
                    self.calls.append((node.id, pressed, bool(extra and extra.get("sequence_end"))))
                    if pressed:
                        functor._stop_runner()  # Called by an action on the worker itself.

                functor._ec.execute_node = execute
                getattr(functor, start)()
                self.join_runner(functor)
                self.assertEqual(self.calls[:2], [(0, True, False), (0, False, False)])
                self.assertEqual(sum(pressed for _, pressed, _ in self.calls), 1)
                self.assertEqual(self.global_sequence.sequence_count, 0)

    def test_stopped_step_worker_does_not_issue_a_new_press(self):
        functor = self.make_functor(self.mode.Step)
        functor._stepped_runner()
        self.assertEqual(self.calls, [])
        self.assertIsNone(functor._current_step)

    def test_stop_during_autorelease_wait_releases_the_step_before_returning(self):
        for mode, start in ((self.mode.Normal, "start_normal"), (self.mode.Step, "start_stepped"), (self.mode.Wiggle, "start_wiggle")):
            with self.subTest(mode=mode):
                self.calls.clear()
                functor = self.make_functor(mode)
                functor.action_data.normal_autorelease_delay = 30_000
                functor.action_data.wiggle_exec_delay = 30_000
                entered_wait = threading.Event()
                original_wait = functor._wait

                def wait(delay):
                    entered_wait.set()
                    original_wait(delay)

                functor._wait = wait
                getattr(functor, start)()
                self.assertTrue(entered_wait.wait(timeout=2))
                functor._stop_runner()
                self.join_runner(functor)
                self.assertEqual(self.calls[:2], [(0, True, False), (0, False, False)])
                self.assertEqual(sum(pressed for _, pressed, _ in self.calls), 1)
                self.assertEqual(self.global_sequence.sequence_count, 0)

    def test_empty_sequences_exit_without_output(self):
        for runner in ("_normal_runner", "_stepped_runner", "_wiggle_runner"):
            with self.subTest(runner=runner):
                functor = self.make_functor(count=0)
                self.run_direct(functor, runner)
                self.assertEqual(self.calls, [])

    def test_process_event_routes_each_mode_and_respects_logging(self):
        for mode in self.mode:
            with self.subTest(mode=mode):
                functor = self.make_functor(mode)
                functor.action_data.ignore_release = False
                starts, stops = [], []

                def start(name):
                    starts.append(name)
                    functor.action_data._is_running = True

                def stop(name):
                    stops.append(name)
                    functor.action_data._is_running = False

                for name in ("normal", "stepped", "wiggle"):
                    setattr(functor, f"start_{name}", lambda name=name: start(name))
                    setattr(functor, f"stop_{name}", lambda name=name: stop(name))
                for pressed in (True, False, True, False):
                    self.assertTrue(functor.process_event(NS(is_pressed=pressed), pressed))
                name = "stepped" if mode == self.mode.Step else "wiggle" if mode == self.mode.Wiggle else "normal"
                self.assertEqual(starts, [name] if mode == self.mode.Toggle else [name, name])
                self.assertEqual(stops, [name] if mode == self.mode.Toggle else [name, name])
        self.ns["syslog"].info.assert_not_called()

    def test_trigger_on_release_and_continue_on_reset(self):
        functor = self.make_functor()
        functor.container.exec_on_press = False
        functor.container.exec_on_release = True
        functor.start_normal = Mock()
        functor.stop_normal = Mock()
        functor.process_event(NS(is_pressed=True), True)
        functor.stop_normal.assert_called_once()
        functor.process_event(NS(is_pressed=False), False)
        functor.start_normal.assert_called_once()
        functor.action_data._is_running = True
        functor.process_event(NS(is_pressed=True), True)
        self.assertEqual(functor.stop_normal.call_count, 1)

    def test_invalid_functor_does_not_start(self):
        functor = self.make_functor()
        functor.valid = False
        functor.start_normal = Mock()
        self.assertFalse(functor.process_event(NS(is_pressed=True), True))
        functor.start_normal.assert_not_called()

    def test_options_are_created_lazily_and_reused(self):
        functor = self.make_functor()
        first = functor.action_data.getOptions(2)
        self.assertEqual(first.index, 2)
        self.assertIs(functor.action_data.getOptions(2), first)
        self.assertEqual(len(functor.action_data.step_options), 1)

    def test_autorelease_controls_update_only_autorelease_settings(self):
        options = self.ns["StepOptions"]()
        widget = self.ns["StepOptionsWidget"].__new__(self.ns["StepOptionsWidget"])
        widget.options = options
        widget._handle_autorelease_delay_min_changed(10)
        widget._handle_autorelease_delay_max_changed(20)
        self.assertEqual((options.autorelease_min_delay, options.autorelease_max_delay), (10, 20))
        self.assertEqual((options.repeat_min_delay, options.repeat_max_delay), (250, 250))
        options.mode = self.repeat.Loop
        self.assertEqual(options.getAutoreleaseDelay(), .010)

    def test_step_timing_uses_defaults_or_the_selected_repeat_settings(self):
        options = self.ns["StepOptions"]()
        self.assertEqual(options.getCount(), 1)
        self.assertEqual(options.getDelay(7), .007)
        self.assertEqual(options.getAutoreleaseDelay(11), .011)
        options.mode = self.repeat.Random
        options.repeat_count = 5
        options.randomize_delay = options.randomize_autorelease_delay = True
        options.repeat_min_delay, options.repeat_max_delay = 10, 20
        options.autorelease_min_delay, options.autorelease_max_delay = 30, 40
        self.ns["random"].randint = Mock(side_effect=[3, 15, 35])
        self.assertEqual(options.getCount(), 3)
        self.assertEqual(options.getDelay(), .015)
        self.assertEqual(options.getAutoreleaseDelay(), .035)
        self.assertEqual([call.args for call in self.ns["random"].randint.call_args_list], [(0, 5), (10, 20), (30, 40)])


if __name__ == "__main__":
    unittest.main()
