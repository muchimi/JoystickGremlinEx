"""Hardware-free vJoy wrapper checks: python tools/test_vjoy.py.

Load the real wrapper code with driver, event, and UI services replaced by
in-memory doubles. No vJoy DLL or live device is opened.
"""

import ast
import ctypes
import enum
import importlib.util
import logging
import math
import os
import sys
import threading
import time
import unittest
from functools import cache
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.error import VJoyError  # noqa: E402
from gremlin.input_types import InputType  # noqa: E402
from gremlin.singleton_decorator import SingletonDecorator  # noqa: E402
from gremlin.types import AxisNames, EventSourceType  # noqa: E402
from vjoy.vjoy_interface import VJoyState  # noqa: E402
import gremlin as gremlin_package  # noqa: E402
import vjoy as vjoy_package  # noqa: E402


class Signal:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def connect(self, callback):
        pass


class NoAppImports(ast.NodeTransformer):
    def visit_Import(self, node):
        if all(alias.name.startswith(("gremlin", "vjoy")) for alias in node.names):
            return ast.Pass()
        return node

    def visit_ImportFrom(self, node):
        if node.module and node.module.startswith(("gremlin", "vjoy")):
            return ast.Pass()
        return node


def load_vjoy(source=None):
    tree = ast.parse(source if source is not None else (ROOT / "vjoy/vjoy.py").read_bytes())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *nodes,
    ], type_ignores=[])
    services = NS()
    namespace = dict(
        ctypes=ctypes, enum=enum, logging=logging, threading=threading, time=time,
        os=os, cache=cache, gremlin=services, VJoyState=VJoyState, VJoyError=VJoyError,
        InputType=InputType, EventSourceType=EventSourceType,
        SingletonDecorator=SingletonDecorator, syslog=logging.getLogger("vjoy-checks"),
    )
    module = NoAppImports().visit(module)
    exec(compile(ast.fix_missing_locations(module), str(ROOT / "vjoy/vjoy.py"), "exec"), namespace)
    return namespace


class VJoyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace = load_vjoy()

    def setUp(self):
        self.ns = self.namespace
        self.services = self.ns["gremlin"]
        self.on_ui = True
        self.pending = []
        self.listener = NS(
            vjoy_output_event=Signal(), vjoy_output_event_ui=Signal(),
            vjoy_event=Signal(), shutdown=Signal(),
        )
        self.services.event_handler = NS(
            Event=lambda **fields: NS(**fields),
            VjoyEvent=lambda *args: args,
            EventListener=Mock(return_value=self.listener),
        )
        self.services.shared_state = NS(current_profile=None)
        self.services.joystick_handling = NS(getVjoyDeviceGuid=lambda vid: f"vjoy-{vid}")
        self.services.types = NS(AxisNames=AxisNames)
        self.services.config = NS(Configuration=lambda: NS(verbose_mode_vjoy=False))
        self.services.spline = NS(
            CubicSpline=lambda points: lambda value: value * value,
            CubicBezierSpline=lambda points: lambda value: value / 2,
        )
        self.services.util = NS(
            is_ui_thread=lambda: self.on_ui,
            InvokeUiMethod=Mock(side_effect=self.invoke),
            safeJoin=lambda thread: thread.join(timeout=1),
        )
        self.driver = NS(
            vJoyEnabled=Mock(return_value=True),
            GetVJDStatus=Mock(return_value=VJoyState.Free.value),
            AcquireVJD=Mock(return_value=True), RelinquishVJD=Mock(),
            GetOwnerPid=Mock(return_value=os.getpid()),
            GetVJDAxisExist=Mock(side_effect=lambda vid, axis: int(axis in (0x30, 0x35))),
            GetVJDAxisMin=Mock(side_effect=lambda vid, axis, pointer: setattr(pointer._obj, "value", 0)),
            GetVJDAxisMax=Mock(side_effect=lambda vid, axis, pointer: setattr(pointer._obj, "value", 32767)),
            GetVJDButtonNumber=Mock(return_value=2),
            GetVJDDiscPovNumber=Mock(return_value=0), GetVJDContPovNumber=Mock(return_value=1),
            SetAxis=Mock(return_value=True), SetBtn=Mock(return_value=True),
            SetContPov=Mock(return_value=True), SetDiscPov=Mock(return_value=True),
            ResetVJD=Mock(return_value=True),
        )
        self.ns["VJoyInterface"] = self.driver
        self.ns["VJoyMonitor"].instance = None
        if "_output_event_context" in self.ns:
            self.ns["_output_event_context"].cache_clear()
        self.device = self.ns["VJoy"](1)
        self.monitor = self.device._vjoy_monitor
        self.addCleanup(self.monitor.stop)
        self.axis = self.device.axis(6)
        self.button = self.device.button(1)
        self.hat = self.device.hat(1)
        self.clear_events()
        self.services.util.InvokeUiMethod.reset_mock()
        for function in vars(self.driver).values():
            function.reset_mock()

    def invoke(self, function, *args):
        if self.on_ui:
            return function(*args)
        self.pending.append((function, args))

    def flush_ui(self):
        self.on_ui = True
        while self.pending:
            function, args = self.pending.pop(0)
            function(*args)

    def clear_events(self):
        self.listener.vjoy_output_event.events.clear()
        self.listener.vjoy_output_event_ui.events.clear()
        self.listener.vjoy_event.events.clear()

    def test_axis_scaling_clamping_and_nan(self):
        for value, expected in ((-2, -1), (-1, -1), (-0.5, -0.5), (0, 0), (0.5, 0.5), (1, 1), (2, 1), (math.nan, -1)):
            with self.subTest(value=value):
                self.axis.value = value
                self.assertEqual(self.axis.value, expected)
                self.driver.SetAxis.assert_called_with(int(16383 + 16383 * expected), 1, 0x35)

    def test_null_axis_value_is_ignored(self):
        self.axis.value = None
        self.driver.SetAxis.assert_not_called()
        self.assertEqual(self.listener.vjoy_output_event.events, [])

    def test_custom_deadzone_and_response_curve_are_applied_in_order(self):
        self.axis.set_deadzone(-1, -0.2, 0.2, 1)
        self.axis.set_response_curve("cubic-spline", [])
        self.axis.value = 0.6
        self.assertAlmostEqual(self.axis.value, 0.25)
        self.axis.set_response_curve("cubic-bezier-spline", [])
        self.axis.value = -0.6
        self.assertAlmostEqual(self.axis.value, -0.25)

    def test_default_deadzone_and_invalid_curve_reset_to_identity(self):
        self.axis.set_deadzone(-1, -0.2, 0.2, 1)
        self.axis.set_deadzone(-1, 0, 0, 1)
        self.axis.set_response_curve("invalid", [])
        self.axis.value = -0.4
        self.assertAlmostEqual(self.axis.value, -0.4)

    def test_absolute_axis_write_bypasses_curves_without_emitting_events(self):
        self.axis.set_deadzone(-1, -0.9, 0.9, 1)
        self.axis.set_response_curve("cubic-spline", [])
        self.axis.set_absolute_value(0.5)
        self.assertEqual(self.axis.value, 0.5)
        self.driver.SetAxis.assert_called_once_with(24574, 1, 0x35)
        self.assertEqual(self.listener.vjoy_output_event.events, [])

    def test_axis_output_signals_preserve_axis_id_value_and_source(self):
        self.axis.value = 0.25
        event = self.listener.vjoy_output_event.events[0]
        self.assertEqual((event.device_guid, event.event_type, event.identifier, event.value), ("vjoy-1", InputType.JoystickAxis, 6, 0.25))
        self.assertTrue(event.is_axis)
        self.assertEqual(event.source, EventSourceType.Virtual)
        self.assertIs(self.listener.vjoy_output_event_ui.events[0], event)

    def test_duplicate_values_still_write_and_emit_every_sample(self):
        for _ in range(3):
            self.axis.value = 0.5
        self.assertEqual(self.driver.SetAxis.call_count, 3)
        self.assertEqual(self.driver.GetOwnerPid.call_count, 3)
        self.assertEqual(len(self.listener.vjoy_output_event.events), 3)

    def test_button_press_release_and_failed_write_behavior(self):
        for pressed in (True, False):
            self.button.is_pressed = pressed
            self.assertEqual(self.button.is_pressed, pressed)
            self.driver.SetBtn.assert_called_with(pressed, 1, 1)
            self.assertEqual(self.listener.vjoy_output_event.events[-1].is_pressed, pressed)
        self.clear_events()
        self.driver.SetBtn.return_value = False
        self.button.is_pressed = True
        self.assertEqual(self.listener.vjoy_output_event.events, [])

    def test_continuous_hats_preserve_all_directions(self):
        for direction, native in self.ns["Hat"].to_continuous_direction.items():
            with self.subTest(direction=direction):
                self.hat.direction = direction
                self.assertEqual(self.hat.direction, direction)
                self.driver.SetContPov.assert_called_with(native, 1, 1)
                self.assertEqual(self.listener.vjoy_output_event.events[-1].value, direction)

    def test_discrete_hats_preserve_directions_and_reject_diagonals(self):
        self.hat.hat_type = self.ns["HatType"].Discrete
        for direction, native in self.ns["Hat"].to_discrete_direction.items():
            self.hat.direction = direction
            self.driver.SetDiscPov.assert_called_with(native, 1, 1)
        with self.assertRaises(VJoyError):
            self.hat.direction = (1, 1)

    def test_hat_center_aliases_and_driver_errors(self):
        for direction in (None, False):
            self.hat.direction = direction
            self.assertEqual(self.hat.direction, (0, 0))
            self.driver.SetContPov.assert_called_with(-1, 1, 1)
        self.driver.SetContPov.return_value = False
        with self.assertRaises(VJoyError):
            self.hat.direction = (1, 0)

    def test_loopback_tracks_profile_changes_without_rebuilding_controls(self):
        controls = (
            (lambda: setattr(self.axis, "value", 0.5), InputType.JoystickAxis, 6, 0.5),
            (lambda: setattr(self.button, "is_pressed", True), InputType.JoystickButton, 1, True),
            (lambda: setattr(self.hat, "direction", (1, 1)), InputType.JoystickHat, 1, (1, 1)),
        )
        for write, input_type, identifier, value in controls:
            with self.subTest(input_type=input_type):
                self.clear_events()
                self.services.shared_state.current_profile = None
                write()
                self.assertEqual(self.listener.vjoy_event.events, [])
                self.services.shared_state.current_profile = NS(settings=NS(getVjoyAsInput=lambda vid: True))
                write()
                self.assertEqual(self.listener.vjoy_event.events, [(1, input_type, identifier, value)])
                self.services.shared_state.current_profile = NS(settings=NS(getVjoyAsInput=lambda vid: False))
                write()
                self.assertEqual(len(self.listener.vjoy_event.events), 1)

    def test_event_services_are_cached_across_control_writes(self):
        self.services.event_handler.EventListener.reset_mock()
        self.axis.value = 0.1
        self.button.is_pressed = True
        self.hat.direction = (0, 1)
        self.services.event_handler.EventListener.assert_not_called()

    def test_full_module_import_resolves_lazy_services_without_opening_driver(self):
        spec = importlib.util.spec_from_file_location("vjoy.vjoy", ROOT / "vjoy/vjoy.py")
        module = importlib.util.module_from_spec(spec)
        replacements = {
            "gremlin.util": self.services.util,
            "gremlin.spline": self.services.spline,
            "gremlin.event_handler": self.services.event_handler,
            "gremlin.shared_state": self.services.shared_state,
            "gremlin.joystick_handling": self.services.joystick_handling,
            "vjoy.vjoy_interface": NS(VJoyState=VJoyState, VJoyInterface=self.driver),
            "vjoy.vjoy": module,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, replacements))
            for name, replacement in replacements.items():
                package_name, attribute = name.rsplit(".", 1)
                package = gremlin_package if package_name == "gremlin" else vjoy_package
                stack.enter_context(patch.object(package, attribute, replacement, create=True))
            spec.loader.exec_module(module)
            device = module.VJoy(1)
            device.axis(6).value = 0.25
            self.driver.SetAxis.assert_called_with(20478, 1, 0x35)
            self.assertEqual(self.listener.vjoy_output_event.events[-1].value, 0.25)

    def test_sparse_axis_lookup_accepts_enum_id_and_linear_index(self):
        self.assertEqual(self.device.axis_count, 2)
        self.assertIs(self.device.axis(self.ns["AxisName"].RZ), self.axis)
        self.assertIs(self.device.axis(linear_index=2), self.axis)
        self.assertEqual(self.device.axis_id(2), 6)
        self.assertIsNone(self.device.axis(2))
        self.assertIsNone(self.device.axis(linear_index=3))
        self.assertIsNone(self.device.button(99))
        self.assertIsNone(self.device.hat(99))

    def test_hat_lookup_helpers_keep_known_and_missing_results(self):
        hat_class = self.ns["Hat"]
        self.assertEqual(hat_class.getName((0, 1)), "North")
        self.assertEqual(hat_class.getDirection("North East"), (1, 1))
        self.assertEqual(hat_class.getIcon("North"), hat_class.direction_to_icon[(0, 1)])
        self.assertIsNone(hat_class.getName((2, 2)))
        self.assertIsNone(hat_class.getDirection("unknown"))
        self.assertIsNone(hat_class.getIcon("unknown"))
        self.assertEqual(hat_class.getEightDirections(), list(hat_class.direction_to_name))

    def test_ownership_check_on_ui_bypasses_dispatch_and_reports_success(self):
        self.assertTrue(self.monitor.ensure_ownership(1))
        self.services.util.InvokeUiMethod.assert_not_called()
        self.driver.GetOwnerPid.assert_called_once_with(1)
        self.driver.AcquireVJD.assert_not_called()

    def test_ownership_check_from_worker_remains_queued(self):
        self.on_ui = False
        self.monitor.ensure_ownership(1)
        self.driver.GetOwnerPid.assert_not_called()
        self.assertEqual(len(self.pending), 1)
        self.flush_ui()
        self.driver.GetOwnerPid.assert_called_once_with(1)

    def test_lost_ownership_retries_until_acquired(self):
        self.driver.GetOwnerPid.return_value = -1
        self.driver.AcquireVJD.side_effect = [False, False, True]
        with patch.object(self.ns["time"], "sleep") as sleep:
            self.assertTrue(self.monitor.ensure_ownership(1))
        self.assertEqual(self.driver.AcquireVJD.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_ownership_failure_has_finite_retries(self):
        self.driver.GetOwnerPid.return_value = -1
        self.driver.AcquireVJD.return_value = False
        with patch.object(self.ns["time"], "sleep"):
            self.assertFalse(self.monitor.ensure_ownership(1))
        self.assertEqual(self.driver.AcquireVJD.call_count, 5)

    def test_reset_preserves_all_states_without_ui_dispatch_on_ui(self):
        self.axis.value = 0.5
        self.button.is_pressed = True
        self.hat.direction = (1, -1)
        self.device.reset()
        self.assertEqual(self.axis.value, 0.5)
        self.assertTrue(self.button.is_pressed)
        self.assertEqual(self.hat.direction, (1, -1))
        self.driver.ResetVJD.assert_called_once_with(1)
        self.services.util.InvokeUiMethod.assert_not_called()

    def test_reset_from_worker_waits_for_ui(self):
        self.on_ui = False
        self.device.reset()
        self.driver.ResetVJD.assert_not_called()
        self.flush_ui()
        self.driver.ResetVJD.assert_called_once_with(1)

    def test_usage_timestamp_uses_monotonic_clock(self):
        with patch.dict(self.ns, time=NS(monotonic=lambda: 123.0)):
            self.monitor.used()
        self.assertEqual(self.monitor._last_active, 123)

    def run_keepalive(self, activities):
        clock = NS(now=100.0)
        waits = []
        awake = Mock()

        def wait(timeout):
            waits.append(timeout)
            clock.now += timeout
            if len(waits) > len(activities):
                return True
            activity = activities[len(waits) - 1]
            if activity is not None:
                self.monitor._last_active = clock.now - activity
            return False

        self.monitor._last_active = clock.now
        self.monitor._keep_alive_running = True
        self.monitor._keep_alive_abort_signal = NS(wait=wait)
        with patch.dict(self.ns, time=NS(monotonic=lambda: clock.now)), \
                patch.object(self.monitor, "keep_awake", awake), \
                patch.object(self.ns["VJoy"], "keep_alive_timeout", 30):
            self.monitor._keep_alive_runner()
        return waits, awake

    def test_keepalive_waits_between_idle_checks_without_busy_loop(self):
        waits, awake = self.run_keepalive([None, None])
        self.assertEqual(waits, [30, 30, 30])
        self.assertEqual(awake.call_count, 2)

    def test_recent_activity_postpones_keepalive_until_idle(self):
        waits, awake = self.run_keepalive([5, None])
        self.assertEqual(waits, [30, 25, 30])
        awake.assert_called_once()

    def test_monitor_stops_and_restarts_without_waiting_for_long_idle_timeout(self):
        with patch.object(self.ns["VJoy"], "keep_alive_timeout", 3600):
            for _ in range(2):
                entered = threading.Event()
                original_wait = self.monitor._keep_alive_abort_signal.wait

                def wait(timeout):
                    entered.set()
                    return original_wait(timeout)

                with patch.object(self.monitor._keep_alive_abort_signal, "wait", wait):
                    self.monitor.start()
                    thread = self.monitor._keep_alive_thread
                    self.monitor.start()
                    self.assertIs(self.monitor._keep_alive_thread, thread)
                    self.assertTrue(entered.wait(timeout=1))
                    self.monitor.stop()
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(self.monitor._keep_alive_running)
                    self.assertFalse(self.monitor._keep_alive_started)


if __name__ == "__main__":
    unittest.main()
