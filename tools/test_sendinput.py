"""Hardware-free SendInput regression checks.

Run with: python tools/test_sendinput.py
Win32 input injection and the application's device services are replaced by fakes.
"""

import ctypes
import importlib.util
import math
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gremlin  # noqa: E402
from gremlin.types import MouseButton  # noqa: E402


def load_sendinput(source=None):
    spec = importlib.util.spec_from_file_location("_sendinput_checks", ROOT / "gremlin/sendinput.py")
    module = importlib.util.module_from_spec(spec)
    util = SimpleNamespace(safeJoin=lambda thread: thread.join(timeout=1))
    user32 = SimpleNamespace(SendInput=Mock(return_value=1))
    with patch.dict(sys.modules, {"gremlin.util": util}), \
            patch.object(gremlin, "util", util, create=True), \
            patch.object(ctypes.windll, "user32", user32):
        if source is None:
            spec.loader.exec_module(module)
        else:
            exec(compile(source, str(spec.origin), "exec"), module.__dict__)
    return module


sendinput = load_sendinput()


class InputChecks(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.timeline = []
        self.native = Mock(side_effect=self.capture)
        self.native_patch = patch.object(sendinput, "_SendInput", self.native)
        self.native_patch.start()
        self.addCleanup(self.native_patch.stop)

    def capture(self, count, buffer, size):
        self.assertEqual(size, ctypes.sizeof(sendinput._INPUT))
        pointer = ctypes.cast(buffer, ctypes.POINTER(sendinput._INPUT))
        for index in range(count):
            event = sendinput._INPUT.from_buffer_copy(pointer[index])
            self.events.append(event)
            self.timeline.append((event.union.mi.dwFlags, event.union.mi.mouseData))
        return count

    def test_windows_structure_layout(self):
        is_64_bit = ctypes.sizeof(ctypes.c_void_p) == 8
        self.assertEqual(ctypes.sizeof(sendinput._INPUT), 40 if is_64_bit else 28)
        self.assertEqual(sendinput._INPUT.union.offset, 8 if is_64_bit else 4)
        self.assertEqual(ctypes.sizeof(sendinput._MOUSEINPUT), 32 if is_64_bit else 24)
        self.assertEqual(ctypes.sizeof(sendinput._KEYBDINPUT), 24 if is_64_bit else 16)

    def test_native_signature(self):
        module = load_sendinput()
        native = module._SendInput
        self.assertEqual(native.argtypes, (
            ctypes.wintypes.UINT, ctypes.POINTER(module._INPUT), ctypes.c_int,
        ))
        self.assertIs(native.restype, ctypes.wintypes.UINT)

    def test_ctypes_stdcall_boundary(self):
        received = []
        signature = ctypes.WINFUNCTYPE(
            ctypes.wintypes.UINT, ctypes.wintypes.UINT,
            ctypes.POINTER(sendinput._INPUT), ctypes.c_int,
        )

        @signature
        def native(count, inputs, size):
            received.append((count, size, [inputs[index].type for index in range(count)]))
            return count

        with patch.object(sendinput, "_SendInput", native):
            sendinput.send_mouse_motion(5, -5)
            sendinput.send_key(0x41, 0x1E, 2)
            self.assertEqual(sendinput._send_input(
                sendinput._mouse_input(1), sendinput._keyboard_input(0x41, 0x1E, 2),
            ), 2)
        size = ctypes.sizeof(sendinput._INPUT)
        self.assertEqual(received, [(1, size, [0]), (1, size, [1]), (2, size, [0, 1])])

    def test_single_input_uses_original_buffer(self):
        event = sendinput._mouse_input(sendinput.MOUSEEVENTF_MOVE, -20, 30)
        self.assertEqual(sendinput._send_input(event), 1)
        self.assertIs(self.native.call_args.args[1]._obj, event)
        actual = self.events[0]
        self.assertEqual(actual.type, sendinput.INPUT_MOUSE)
        self.assertEqual((actual.union.mi.dx, actual.union.mi.dy), (-20, 30))
        self.assertEqual(actual.union.mi.time, 0)
        self.assertFalse(actual.union.mi.dwExtraInfo)

    def test_batch_preserves_order_and_keyboard_flags(self):
        flags = sendinput.KEYEVENTF_KEYUP | sendinput.KEYEVENTF_EXTENDEDKEY
        mouse = sendinput._mouse_input(sendinput.MOUSEEVENTF_LEFTDOWN)
        keyboard = sendinput._keyboard_input(0x41, 0x1E, flags)
        self.assertEqual(sendinput._send_input(mouse, keyboard), 2)
        self.assertEqual([event.type for event in self.events], [0, 1])
        actual = self.events[1].union.ki
        self.assertEqual((actual.wVk, actual.wScan, actual.dwFlags), (0x41, 0x1E, flags))
        self.assertEqual(actual.time, 0)
        self.assertFalse(actual.wExtraInfo)

    def test_empty_batch_does_not_call_windows(self):
        self.assertEqual(sendinput._send_input(), 0)
        self.native.assert_not_called()

    def test_native_result_is_returned(self):
        self.native.side_effect = None
        self.native.return_value = 0
        self.assertEqual(sendinput._send_input(sendinput._mouse_input(1)), 0)
        self.native.return_value = 1
        self.assertEqual(sendinput._send_input(sendinput._mouse_input(1), sendinput._mouse_input(2)), 1)

    def test_public_keyboard_and_motion_helpers(self):
        sendinput.send_key(0x41, 0x1E, sendinput.KEYEVENTF_KEYUP)
        sendinput.send_mouse_motion(-15, 25)
        self.assertEqual(self.events[0].type, sendinput.INPUT_KEYBOARD)
        mouse = self.events[1].union.mi
        self.assertEqual((mouse.dx, mouse.dy, mouse.dwFlags), (-15, 25, sendinput.MOUSEEVENTF_MOVE))

    def test_absolute_position_reads_current_screen_dimensions(self):
        with patch.object(sendinput.win32api, "GetSystemMetrics", side_effect=[1920, 1080, 2560, 1440]):
            sendinput.send_mouse_position(960, 540)
            sendinput.send_mouse_position(1280, 720)
        for event in self.events:
            mouse = event.union.mi
            self.assertEqual((mouse.dx, mouse.dy), (32767, 32767))
            self.assertEqual(mouse.dwFlags, sendinput.MOUSEEVENTF_ABSOLUTE | sendinput.MOUSEEVENTF_MOVE)

    def button_cases(self):
        return (
            (MouseButton.Left, sendinput.MOUSEEVENTF_LEFTDOWN, sendinput.MOUSEEVENTF_LEFTUP, 0),
            (MouseButton.Right, sendinput.MOUSEEVENTF_RIGHTDOWN, sendinput.MOUSEEVENTF_RIGHTUP, 0),
            (MouseButton.Middle, sendinput.MOUSEEVENTF_MIDDLEDOWN, sendinput.MOUSEEVENTF_MIDDLEUP, 0),
            (MouseButton.Back, sendinput.MOUSEEVENTF_XDOWN, sendinput.MOUSEEVENTF_XUP, sendinput.XBUTTON1),
            (MouseButton.Forward, sendinput.MOUSEEVENTF_XDOWN, sendinput.MOUSEEVENTF_XUP, sendinput.XBUTTON2),
        )

    def test_button_press_and_release(self):
        for button, down, up, data in self.button_cases():
            with self.subTest(button=button):
                self.timeline.clear()
                sendinput.mouse_press(button)
                sendinput.mouse_release(button)
                self.assertEqual(self.timeline, [(down, data), (up, data)])

    def test_double_click_preserves_event_order_and_delays(self):
        for button, down, up, data in self.button_cases():
            with self.subTest(button=button), \
                    patch.object(sendinput.time, "sleep", side_effect=lambda delay: self.timeline.append(("sleep", delay))):
                self.timeline.clear()
                sendinput.mouse_press_double_click(button, 0.025)
                self.assertEqual(self.timeline, [
                    (down, data), ("sleep", 0.025), (up, data), ("sleep", 0.025),
                    (down, data), ("sleep", 0.025), (up, data),
                ])

    def test_unsupported_buttons_do_not_send_or_sleep(self):
        with patch.object(sendinput.time, "sleep") as sleep:
            for button in (MouseButton.NotSet, MouseButton.WheelUp, 999, None):
                sendinput.mouse_press(button)
                sendinput.mouse_release(button)
                sendinput.mouse_press_double_click(button)
        self.native.assert_not_called()
        sleep.assert_not_called()

    def test_directional_wheel_helpers_use_signed_dword_deltas(self):
        sendinput.send_mouse_wheel_up()
        sendinput.send_mouse_wheel_down()
        sendinput.send_mouse_wheel_left()
        sendinput.send_mouse_wheel_right()
        self.assertEqual([
            (event.union.mi.dwFlags, ctypes.c_int32(event.union.mi.mouseData).value)
            for event in self.events
        ], [
            (sendinput.MOUSEEVENTF_WHEEL, 120), (sendinput.MOUSEEVENTF_WHEEL, -120),
            (sendinput.MOUSEEVENTF_HWHEEL, -120), (sendinput.MOUSEEVENTF_HWHEEL, 120),
        ])

    def test_wheel_factors_preserve_sign_and_magnitude(self):
        for factor in (-3, 0, 2):
            sendinput.mouse_wheel(factor)
            sendinput.mouse_h_wheel(factor)
        self.assertEqual([
            ctypes.c_int32(event.union.mi.mouseData).value for event in self.events
        ], [-360, -360, 0, 0, 240, 240])

    def test_simultaneous_senders_do_not_change_cached_payloads(self):
        barrier = threading.Barrier(5)

        def send(case):
            button, down, up, data = case
            barrier.wait(timeout=2)
            for _ in range(20):
                sendinput.mouse_press(button)
                sendinput.mouse_release(button)

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(send, self.button_cases()))
        self.assertEqual(len(self.events), 200)
        for _, down, up, data in self.button_cases():
            self.assertEqual(self.timeline.count((down, data)), 20)
            self.assertEqual(self.timeline.count((up, data)), 20)


class MotionChecks(unittest.TestCase):
    def setUp(self):
        self.clock = SimpleNamespace(monotonic=Mock(return_value=100.0))
        clock_patch = patch.object(sendinput, "time", self.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def test_motion_discretization_and_axis_intervals(self):
        motion = sendinput.MouseMotion(150, -50)
        self.assertEqual(motion(), (2, -1))
        self.clock.monotonic.return_value = 100.015
        self.assertEqual(motion(), (2, 0))
        self.clock.monotonic.return_value = 100.025
        self.assertEqual(motion(), (0, -1))

    def test_zero_and_negligible_motion(self):
        for dx, dy in ((0, 0), (None, None), (1e-8, -1e-8)):
            with self.subTest(dx=dx, dy=dy):
                self.assertEqual(sendinput.MouseMotion(dx, dy)(), (0, 0))
        self.clock.monotonic.assert_not_called()

    def test_fixed_motion_waits_for_interval_and_recovers_after_pause(self):
        motion = sendinput.FixedMouseMotion(3, -4, rate=0.5)
        for timestamp, expected in (
            (100.0, (3, -4)), (100.49, (0, 0)), (100.5, (3, -4)),
            (105.0, (3, -4)), (105.1, (0, 0)),
        ):
            with self.subTest(timestamp=timestamp):
                self.clock.monotonic.return_value = timestamp
                self.assertEqual(motion(), expected)

    def test_fixed_default_interval_and_updates(self):
        motion = sendinput.FixedMouseMotion(None, 4)
        self.assertEqual(motion(), (0, 4))
        motion.set_dx(-7)
        motion.set_dy(2)
        self.clock.monotonic.return_value = 101.0
        self.assertEqual(motion(), (-7, 2))

    def test_nonpositive_fixed_rate_emits_on_every_call(self):
        for rate in (0, -1):
            with self.subTest(rate=rate):
                motion = sendinput.FixedMouseMotion(2, 3, rate=rate)
                self.assertEqual(motion(), (2, 3))
                self.assertEqual(motion(), (2, 3))

    def test_acceleration_reaches_maximum_without_repeated_trigonometry(self):
        motion = sendinput.AcceleratedMouseMotion(90, 10, 20, 0.1)
        with patch.object(sendinput.math, "cos", wraps=math.cos) as cosine, \
                patch.object(sendinput.math, "sin", wraps=math.sin) as sine:
            for step in range(15):
                self.clock.monotonic.return_value = 100.0 + step * 0.01
                motion()
                self.assertAlmostEqual(motion.current_velocity, min(20, 11 + step))
                self.assertAlmostEqual(motion.dx, motion.current_velocity)
                self.assertAlmostEqual(motion.dy, 0)
        cosine.assert_not_called()
        sine.assert_not_called()

    def test_maximum_speed_avoids_recalculating_steps(self):
        motion = sendinput.AcceleratedMouseMotion(45, 20, 20, 1)
        with patch.object(motion, "_compute_values", wraps=motion._compute_values) as compute:
            for _ in range(10):
                motion()
        compute.assert_not_called()

    def test_direction_changes_at_maximum_speed(self):
        motion = sendinput.AcceleratedMouseMotion(90, 20, 20, 1)
        motion.set_direction(180)
        self.assertEqual(motion(), (0, 1))
        self.assertAlmostEqual(motion.dx, 0)
        self.assertAlmostEqual(motion.dy, 20)

    def test_instant_acceleration_remains_capped(self):
        motion = sendinput.AcceleratedMouseMotion(270, 5, 15, 0)
        motion()
        self.assertEqual(motion.current_velocity, 15)
        self.assertAlmostEqual(motion.dx, -15)


class ControllerChecks(unittest.TestCase):
    def make_controller(self):
        controller = object.__new__(sendinput.MouseController.klass)
        controller._motion_type = sendinput.MotionType.Fixed
        controller._delta_generator = None
        controller._accel_generator = None
        controller._stop = threading.Event()
        controller._motion_condition = threading.Condition()
        controller._thread = None
        return controller

    def test_partial_axis_updates_preserve_other_axis(self):
        controller = self.make_controller()
        controller.set_absolute_motion(10, 20)
        generator = controller._delta_generator
        controller.set_absolute_motion(dy=-5)
        controller.set_absolute_motion(dx=0)
        controller.set_absolute_motion()
        self.assertIs(controller._delta_generator, generator)
        self.assertEqual((generator.dx, generator.dy), (0, -5))

    def test_fixed_mode_does_not_resume_stale_acceleration(self):
        controller = self.make_controller()
        controller._accel_generator = Mock(return_value=(5, 6))
        with patch.object(sendinput, "send_mouse_motion") as send, \
                patch.object(controller._motion_condition, "wait", side_effect=controller._stop.set) as idle_wait, \
                patch.object(controller._stop, "wait") as tick_wait:
            controller._control_loop()
        controller._accel_generator.assert_not_called()
        send.assert_not_called()
        idle_wait.assert_called_once_with()
        tick_wait.assert_not_called()

    def test_control_loop_sends_motion_and_waits_each_tick(self):
        controller = self.make_controller()
        controller._motion_type = sendinput.MotionType.Accelerated
        controller._accel_generator = Mock(side_effect=[(2.9, -3.9), (0, 0)], current_velocity=1, max_velocity=10)
        with patch.object(sendinput, "send_mouse_motion") as send, \
                patch.object(controller._stop, "wait") as tick_wait:
            tick_wait.side_effect = lambda delay: controller._stop.set() if controller._accel_generator.call_count == 2 else None
            controller._control_loop()
        send.assert_called_once_with(2, -3)
        self.assertEqual(tick_wait.call_args_list, [call(0.01), call(0.01)])

    def test_stop_interrupts_long_wait_and_allows_restart(self):
        controller = self.make_controller()
        controller._delta_generator = sendinput.FixedMouseMotion(1, 0, rate=0)
        emitted = threading.Event()
        util = SimpleNamespace(safeJoin=lambda thread: thread.join(timeout=1))
        with patch.object(sendinput, "gremlin", SimpleNamespace(util=util)), \
                patch.object(sendinput.MouseMotion, "delta_t", 10), \
                patch.object(sendinput, "send_mouse_motion", side_effect=lambda *args: emitted.set()):
            try:
                for _ in range(2):
                    emitted.clear()
                    controller.start()
                    thread = controller._thread
                    controller.start()
                    self.assertIs(controller._thread, thread)
                    self.assertTrue(emitted.wait(timeout=1))
                    controller.stop()
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(controller.started)
            finally:
                controller.stop()

    def test_idle_worker_blocks_until_motion_arrives_and_stops_when_idle(self):
        controller = self.make_controller()
        idle = threading.Event()
        emitted = threading.Event()
        original_wait = controller._motion_condition.wait

        def wait(timeout=None):
            self.assertIsNone(timeout)
            idle.set()
            return original_wait(timeout)

        util = SimpleNamespace(safeJoin=lambda thread: thread.join(timeout=1))
        with patch.object(sendinput, "gremlin", SimpleNamespace(util=util)), \
                patch.object(controller._motion_condition, "wait", side_effect=wait) as idle_wait, \
                patch.object(controller._stop, "wait", wraps=controller._stop.wait) as tick_wait, \
                patch.object(sendinput, "send_mouse_motion", side_effect=lambda *args: emitted.set()) as send:
            try:
                controller.start()
                self.assertTrue(idle.wait(timeout=1))
                self.assertEqual(idle_wait.call_count, 1)
                tick_wait.assert_not_called()
                send.assert_not_called()
                idle.clear()
                controller.set_absolute_motion(10, -20)
                self.assertTrue(emitted.wait(timeout=1))
                send.assert_called_with(10, -20)
                controller.set_absolute_motion(0, 0)
                self.assertTrue(idle.wait(timeout=1))
                thread = controller._thread
                controller.stop()
                self.assertFalse(thread.is_alive())
                self.assertFalse(controller.started)
            finally:
                controller.stop()

    def test_acceleration_from_zero_does_not_get_mistaken_for_idle(self):
        controller = self.make_controller()
        controller.set_accelerated_motion(90, 0, 100, 0.1)
        emitted = threading.Event()
        util = SimpleNamespace(safeJoin=lambda thread: thread.join(timeout=1))
        with patch.object(sendinput, "gremlin", SimpleNamespace(util=util)), \
                patch.object(sendinput, "send_mouse_motion", side_effect=lambda *args: emitted.set()) as send:
            try:
                controller.start()
                self.assertTrue(emitted.wait(timeout=1))
                self.assertGreater(send.call_args.args[0], 0)
            finally:
                controller.stop()

    def test_zero_accelerated_motion_blocks_without_timed_ticks(self):
        controller = self.make_controller()
        controller.set_accelerated_motion(90, 0, 0, 1)
        with patch.object(controller._motion_condition, "wait", side_effect=controller._stop.set) as idle_wait, \
                patch.object(controller._stop, "wait") as tick_wait, \
                patch.object(sendinput, "send_mouse_motion") as send:
            controller._control_loop()
        idle_wait.assert_called_once_with()
        tick_wait.assert_not_called()
        send.assert_not_called()

    def test_fixed_interval_gaps_do_not_put_active_motion_to_sleep(self):
        controller = self.make_controller()
        controller.set_absolute_motion(2, 3)
        clock = SimpleNamespace(monotonic=Mock(side_effect=[100.0, 100.1, 101.0]))
        ticks = []

        def wait(delay):
            ticks.append(delay)
            if len(ticks) == 3:
                controller._stop.set()

        with patch.object(sendinput, "time", clock), \
                patch.object(controller._stop, "wait", side_effect=wait), \
                patch.object(controller._motion_condition, "wait", side_effect=AssertionError("active motion slept indefinitely")), \
                patch.object(sendinput, "send_mouse_motion") as send:
            controller._control_loop()
        self.assertEqual(send.call_args_list, [call(2, 3), call(2, 3)])
        self.assertEqual(ticks, [.01, .01, .01])

    def test_motion_updates_keep_the_existing_active_tick(self):
        controller = self.make_controller()
        controller.set_absolute_motion(2, 3)
        controller._delta_generator._rate = 0
        ticks = []

        def wait(delay):
            ticks.append(delay)
            if len(ticks) == 1:
                controller.set_absolute_motion(dx=7)
            else:
                controller._stop.set()

        with patch.object(controller._stop, "wait", side_effect=wait), \
                patch.object(sendinput, "send_mouse_motion") as send:
            controller._control_loop()
        self.assertEqual(send.call_args_list, [call(2, 3), call(7, 3)])
        self.assertEqual(ticks, [.01, .01])

    def test_profile_reset_stops_worker_and_preserves_its_stop_event(self):
        controller = self.make_controller()
        stop_event = controller._stop
        idle = threading.Event()
        original_wait = controller._motion_condition.wait

        def wait(timeout=None):
            idle.set()
            return original_wait(timeout)

        util = SimpleNamespace(safeJoin=lambda thread: thread.join(timeout=1))
        with patch.object(sendinput, "gremlin", SimpleNamespace(util=util)), \
                patch.object(controller._motion_condition, "wait", side_effect=wait):
            try:
                controller.start()
                self.assertTrue(idle.wait(timeout=1))
                thread = controller._thread
                controller._profile_start()
                self.assertFalse(thread.is_alive())
                self.assertIs(controller._stop, stop_event)
                self.assertIsNone(controller._delta_generator)
                self.assertIsNone(controller._accel_generator)
                controller._profile_stop()
                self.assertIs(controller._stop, stop_event)
            finally:
                controller.stop()

    def test_stop_from_input_callback_does_not_join_the_current_thread(self):
        controller = self.make_controller()
        controller.set_absolute_motion(1, 0)
        with patch.object(sendinput, "send_mouse_motion", side_effect=lambda *args: controller.stop()):
            controller.start()
            thread = controller._thread
            if thread is not None:
                thread.join(timeout=1)
                self.assertFalse(thread.is_alive())
            self.assertFalse(controller.started)

    def test_start_failure_keeps_controller_restartable(self):
        controller = self.make_controller()
        for factory in (Mock(side_effect=RuntimeError("start failed")), Mock(return_value=SimpleNamespace(start=Mock(side_effect=RuntimeError("start failed"))))):
            with self.subTest(factory=factory), patch.object(sendinput, "threading", SimpleNamespace(Thread=factory)):
                with self.assertRaisesRegex(RuntimeError, "start failed"):
                    controller.start()
            self.assertIsNone(controller._thread)
            self.assertTrue(controller._stop.is_set())

    def test_stop_keeps_live_thread_reference_until_it_exits(self):
        controller = self.make_controller()
        thread = SimpleNamespace(is_alive=Mock(return_value=True))
        controller._thread = thread
        util = SimpleNamespace(safeJoin=Mock())
        with patch.object(sendinput, "gremlin", SimpleNamespace(util=util)):
            controller.stop()
            self.assertIs(controller._thread, thread)
            controller.start()
            self.assertIs(controller._thread, thread)
            self.assertTrue(controller._stop.is_set())
            thread.is_alive.return_value = False
            controller.stop()
            self.assertIsNone(controller._thread)

    def test_simultaneous_starts_create_only_one_worker(self):
        controller = self.make_controller()
        barrier = threading.Barrier(3)
        factory = Mock(wraps=threading.Thread)
        thread_api = SimpleNamespace(Thread=factory, current_thread=threading.current_thread)
        util = SimpleNamespace(safeJoin=lambda thread: thread.join(timeout=1))

        def start():
            barrier.wait(timeout=1)
            controller.start()

        callers = [threading.Thread(target=start) for _ in range(2)]
        with patch.object(sendinput, "threading", thread_api), \
                patch.object(sendinput, "gremlin", SimpleNamespace(util=util)):
            try:
                for caller in callers:
                    caller.start()
                barrier.wait(timeout=1)
                for caller in callers:
                    caller.join(timeout=1)
                    self.assertFalse(caller.is_alive())
                self.assertEqual(factory.call_count, 1)
                self.assertTrue(controller.started)
            finally:
                controller.stop()


if __name__ == "__main__":
    unittest.main()
