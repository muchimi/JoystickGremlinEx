"""State notification checks without hardware, profiles, or live output.

Run with: python tools/test_state_notifications.py
Load production state methods without initializing the device/UI services.
"""

import ast
from enum import Enum, auto
import gc
import logging
from pathlib import Path
import sys
import threading
import traceback
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
import weakref

from psygnal import Signal


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin import execution_guard

LOGGER = logging.getLogger("system")


def load_state_class(listener, handler):
    tree = ast.parse((ROOT / "gremlin/ui/state_device.py").read_bytes())
    source = next(node for node in tree.body if getattr(node, "name", None) == "StateInputItem")
    methods = {
        "value", "setValue", "default_value", "expression", "evaluate",
        "_fire_changed", "_state_change_reentry", "latch", "autorelease",
        "_set_value", "_dispatch_changed",
    }
    body = [node for node in source.body if getattr(node, "name", None) in methods]
    body.insert(0, ast.parse("changed = Signal(object)").body[0])
    state_class = ast.ClassDef(
        name="StateInputItem", bases=[], keywords=[], body=body, decorator_list=[],
    )
    namespace = dict(
        Signal=Signal, syslog=LOGGER, threading=threading, execution_guard=execution_guard,
        _state_change_context=threading.local(),
        InputType=NS(State="state", JoystickButton="button"),
        StateDeviceTabWidget=NS(device_guid="state-device"),
        gremlin=NS(
            config=NS(Configuration=lambda: NS(verbose_mode_state=True)),
            event_handler=NS(
                Event=NS, EventListener=lambda: listener, EventHandler=lambda: handler,
            ),
        ),
    )
    module = ast.fix_missing_locations(ast.Module(body=[state_class], type_ignores=[]))
    exec(compile(module, "gremlin/ui/state_device.py", "exec"), namespace)
    return namespace["StateInputItem"]


def load_engine_class(path, class_name, methods):
    """Run real engine dispatch/traversal with fake device services."""
    tree = ast.parse((ROOT / path).read_bytes())
    source = next(node for node in tree.body if getattr(node, "name", None) == class_name)
    source.bases = []
    source.decorator_list = []
    source.body = [node for node in source.body if getattr(node, "name", None) in methods]

    class RemoveServiceImports(ast.NodeTransformer):
        def visit_Import(self, node):
            return None if all(alias.name.startswith("gremlin") for alias in node.names) else node

    source = RemoveServiceImports().visit(source)
    nodes = ast.parse("from __future__ import annotations").body
    nodes.extend(node for node in tree.body if getattr(node, "name", None) == "ExecutionGraphNodeType")
    nodes.append(source)
    services = NS(
        config=NS(Configuration=lambda: NS(verbose_mode_inputs=False, verbose_mode_exec=False, verbose_mode_extra=False)),
        actions=NS(Value=lambda value: NS(current=value)),
        shared_state=NS(runtime_mode="Default", master_mode="Master", pushLog=Mock(), popLog=Mock(), logTabs=lambda: ""),
    )
    namespace = dict(
        execution_guard=execution_guard, syslog=LOGGER, traceback=traceback,
        gremlin=services, Enum=Enum, auto=auto, ActivationRule=NS(All=0, Any=1),
        InputType=NS(State="state", JoystickAxis="axis", JoystickButton="button", JoystickHat="hat"),
        LatchedCallbackData=type("LatchedCallbackData", (), {}),
    )
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, path, "exec"), namespace)
    return namespace[class_name](), namespace


class StateNotificationTests(unittest.TestCase):
    def setUp(self):
        self.listener = NS(state_event=Mock())
        self.handler = NS(execute_event=Mock())
        self.state_class = load_state_class(self.listener, self.handler)
        self.state = self.make_state("status_helmet_on")
        self.notifications = []
        self.state.changed.connect(lambda state: self.notifications.append(state.value))

    def make_state(self, key):
        state = self.state_class()
        state.key = key
        state.input_id = key
        state._is_expression = False
        state._expression = None
        state._value = False
        state._last_value = None
        state._default_value = False
        state._autorelease = False
        state._autorelease_delay = 0
        state._autorelease_timer = None
        state._autorelease_trigger_mode = "on"
        state._applying_exclusive = False
        state._exclusive_keys = []
        state._suppress_exclusive = False
        state._emit = True
        return state

    def assert_events(self, values):
        self.assertEqual(self.notifications, values)
        events = [call.args[0] for call in self.handler.execute_event.call_args_list]
        self.assertEqual([event.value for event in events], values)
        self.assertEqual([event.is_pressed for event in events], values)
        self.assertTrue(all(event.extra_data["input_item"] is self.state for event in events))
        self.assertEqual(
            self.listener.state_event.emit.call_args_list,
            self.handler.execute_event.call_args_list,
        )

    def test_one_notification_and_event_per_transition(self):
        self.state.setValue(True)
        self.state.setValue(False)
        self.assert_events([True, False])

    def test_unchanged_value_has_no_notification_or_event(self):
        self.state.setValue(False)
        self.assert_events([])

    def test_force_preserves_repeated_events_with_one_notification_each(self):
        self.state.setValue(False, force=True)
        self.state.setValue(False, force=True)
        self.assert_events([False, False])

    def test_log_reports_previous_value_instead_of_replaced_value(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.state.setValue(True)
            self.state.setValue(False)
        transitions = [line for line in logs.output if "STATE CHANGE:" in line]
        self.assertEqual(len(transitions), 2)
        self.assertIn("current value: [False] -> new value: [True]", transitions[0])
        self.assertIn("current value: [True] -> new value: [False]", transitions[1])

    def test_default_value_transition_is_logged_and_dispatched_once(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.state.default_value = True
        self.assert_events([True])
        self.assertTrue(any("current value: [False] -> new value: [True]" in line for line in logs.output))

    def test_expression_logging_does_not_reevaluate_the_expression(self):
        self.state._is_expression = True
        self.state._expression = "helmet_detected"
        self.state._expression_stack = ["helmet_detected"]
        self.state._dirty = True
        self.state._last_expression_value = False
        self.state._evaluate_stack = Mock(return_value=True)
        # Observe the signal without reading .value (which itself evaluates).
        self.state.changed.disconnect()
        self.state.changed.connect(lambda state: self.notifications.append(state._value))
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertTrue(self.state.evaluate())
        self.state._evaluate_stack.assert_called_once_with(["helmet_detected"], False)
        self.assert_events([True])
        self.assertTrue(any("current value: [False] -> new value: [True]" in line for line in logs.output))

    def test_direct_reentry_is_blocked_for_same_or_different_value(self):
        for value in (True, False):
            with self.subTest(value=value):
                self.handler.execute_event.reset_mock()
                self.listener.state_event.emit.reset_mock()
                self.notifications.clear()
                self.handler.execute_event.side_effect = lambda event: self.state.setValue(value, force=True)
                with self.assertLogs(LOGGER, level="WARNING") as logs:
                    self.state.setValue(True, force=True)
                self.assert_events([True])
                self.assertTrue(self.state.value)
                self.assertIn("status_helmet_on -> status_helmet_on", logs.output[0])

    def test_signal_subscriber_cycle_is_blocked_before_engine_dispatch(self):
        other = self.make_state("status_helmet_off")
        self.state.changed.connect(lambda state: other.setValue(True, force=True))
        other.changed.connect(lambda state: self.state.setValue(False, force=True))
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.state.setValue(True)
        self.assertTrue(self.state.value)
        self.assertTrue(other.value)
        self.assertEqual(self.handler.execute_event.call_count, 0)
        self.assertEqual(self.notifications, [True])
        self.assertIn("status_helmet_on -> status_helmet_off -> status_helmet_on", logs.output[0])
        self.assertEqual(len(logs.output), 1)

    def test_mapped_action_cycle_is_blocked_across_three_states(self):
        second = self.make_state("second")
        third = self.make_state("third")
        targets = {self.state: second, second: third, third: self.state}

        def dispatch(event):
            current = event.extra_data["input_item"]
            targets[current].setValue(True, force=True)

        self.handler.execute_event.side_effect = dispatch
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.state.setValue(True)
        self.assertEqual(self.handler.execute_event.call_count, 3)
        self.assertIn("status_helmet_on -> second -> third -> status_helmet_on", logs.output[0])

    def test_state_event_subscriber_cannot_reenter(self):
        self.listener.state_event.emit.side_effect = lambda event: self.state.setValue(False, force=True)
        with self.assertLogs(LOGGER, level="WARNING"):
            self.state.setValue(True)
        self.assertEqual(self.notifications, [True])
        self.listener.state_event.emit.assert_called_once()
        self.handler.execute_event.assert_not_called()
        self.assertTrue(self.state.value)
        self.assertFalse(self.state._last_value)

    def test_reentry_does_not_cancel_an_active_timer(self):
        timer = Mock()

        def dispatch(event):
            self.state._autorelease_timer = timer
            self.state.setValue(False, force=True)

        self.handler.execute_event.side_effect = dispatch
        with self.assertLogs(LOGGER, level="WARNING"):
            self.state.setValue(True)
        timer.cancel.assert_not_called()
        self.assertIs(self.state._autorelease_timer, timer)
        self.assertTrue(self.state.value)

    def test_exclusive_peer_callbacks_cannot_reenter_the_original_setter(self):
        other = self.make_state("exclusive_peer")
        other._value = True
        self.state._exclusive_keys = [other.key]
        self.state._apply_exclusive_off = Mock(side_effect=lambda: other.setValue(False))

        def dispatch(event):
            if event.extra_data["input_item"] is other:
                self.state.setValue(False, force=True)

        self.handler.execute_event.side_effect = dispatch
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.state.setValue(True)
        self.state._apply_exclusive_off.assert_called_once_with()
        self.assertTrue(self.state.value)
        self.assertFalse(other.value)
        self.assertEqual(self.handler.execute_event.call_count, 2)
        self.assertIn("status_helmet_on -> exclusive_peer -> status_helmet_on", logs.output[0])

    def test_reentrant_default_expression_and_latch_updates_are_ignored(self):
        def dispatch(event):
            self.state.default_value = True
            self.state.expression = "other_state"
            self.state.latch(5)

        self.handler.execute_event.side_effect = dispatch
        with self.assertLogs(LOGGER, level="WARNING"):
            self.state.setValue(True)
        self.assertFalse(self.state.default_value)
        self.assertIsNone(self.state.expression)
        self.assertFalse(self.state.autorelease)
        self.assertEqual(self.state._autorelease_delay, 0)
        self.assert_events([True])

    def test_active_expression_reads_use_committed_value(self):
        self.state._is_expression = True
        self.state._expression = "helmet_detected"
        self.state._expression_stack = ["helmet_detected"]
        self.state._dirty = True
        self.state._last_expression_value = False
        self.state._evaluate_stack = Mock(side_effect=lambda stack, as_tuple: (True, False, None) if as_tuple else True)
        reads = []
        self.state.changed.connect(lambda state: reads.append(state.evaluate(as_tuple=True, force=True)))
        self.assertTrue(self.state.evaluate())
        self.assertEqual(reads, [(True, False, None)])
        self.state._evaluate_stack.assert_called_once_with(["helmet_detected"], False)
        self.assert_events([True])

    def test_finished_branch_can_execute_again_in_the_same_chain(self):
        other = self.make_state("other")
        self.state.changed.connect(lambda state: other.setValue(True, force=True))
        self.state.changed.connect(lambda state: other.setValue(True, force=True))
        self.state.setValue(True)
        self.assertEqual(self.handler.execute_event.call_count, 3)

    def test_guard_is_cleared_after_engine_exception(self):
        self.handler.execute_event.side_effect = RuntimeError("simulated action failure")
        with self.assertRaisesRegex(RuntimeError, "simulated action failure"):
            self.state.setValue(True)
        self.handler.execute_event.side_effect = None
        self.state.setValue(False)
        self.assert_events([True, False])

    def test_guard_is_cleared_after_signal_exception(self):
        def fail(state):
            raise RuntimeError("simulated subscriber failure")

        self.state.changed.connect(fail)
        # psygnal wraps subscriber failures in EmitLoopError.
        with self.assertRaises(Exception):
            self.state.setValue(True)
        self.state.changed.disconnect(fail)
        self.state.setValue(False)
        self.assertEqual(self.notifications, [True, False])
        self.assertEqual(self.handler.execute_event.call_count, 1)

    def test_independent_thread_can_update_the_same_active_state(self):
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def dispatch(event):
            if threading.current_thread() is worker:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("worker was not released")

        def run():
            try:
                self.state.setValue(True, force=True)
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=run)
        self.handler.execute_event.side_effect = dispatch
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.state.setValue(True, force=True)
            self.assert_events([True, True])
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def make_dispatcher(self):
        return load_engine_class("gremlin/event_handler.py", "EventHandler", {
            "execute_event", "_execute_event", "_execute_callbacks", "_trigger_callbacks", "_trigger_functor_callbacks",
        })[0]

    def test_abort_stops_remaining_callbacks_and_latched_functors(self):
        dispatcher = self.make_dispatcher()
        later_callback = Mock()
        later_functor = NS(id="latched", process_event=Mock())

        def reenter(event):
            self.state.setValue(False, force=True)

        self.handler.execute_event.side_effect = lambda event: dispatcher._execute_callbacks(
            event, [reenter, later_callback], [later_functor],
        )
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.state.setValue(True)
        later_callback.assert_not_called()
        later_functor.process_event.assert_not_called()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("EXECUTION ABORTED", logs.output[0])
        self.handler.execute_event.side_effect = None
        self.state.setValue(False)
        self.assert_events([True, False])

    def test_swallowed_abort_still_stops_at_the_next_engine_checkpoint(self):
        dispatcher = self.make_dispatcher()
        later = Mock()

        def swallow(event):
            try:
                self.state.setValue(False, force=True)
            except Exception:
                pass

        self.handler.execute_event.side_effect = lambda event: dispatcher._execute_callbacks(event, [swallow, later], [])
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.state.setValue(True)
        later.assert_not_called()
        self.assertEqual(len(logs.output), 1)

    def test_cancelled_chain_cannot_mutate_another_state_after_catching_abort(self):
        other = self.make_state("other")

        def dispatch(event):
            try:
                self.state.setValue(False, force=True)
            except execution_guard.ExecutionAborted:
                pass
            other.default_value = True

        self.handler.execute_event.side_effect = dispatch
        with self.assertLogs(LOGGER, level="WARNING"):
            self.state.setValue(True)
        self.assertFalse(other.value)
        self.assertFalse(other.default_value)

    def test_abort_stops_latched_functor_siblings(self):
        dispatcher = self.make_dispatcher()
        bad = NS(id="bad", process_event=lambda event, value: self.state.setValue(False, force=True))
        later = NS(id="later", process_event=Mock())
        self.handler.execute_event.side_effect = lambda event: dispatcher._execute_callbacks(event, [], [bad, later])
        with self.assertLogs(LOGGER, level="WARNING"):
            self.state.setValue(True)
        later.process_event.assert_not_called()

    def test_external_event_boundary_aborts_before_other_mapped_inputs(self):
        dispatcher = self.make_dispatcher()
        dispatcher.registry = NS(update=Mock())
        dispatcher.runtime_mode = "Default"
        dispatcher._matching_input_item = lambda mode, event: [object(), object()]
        later = Mock()

        def dispatch(event, item, **kwargs):
            dispatcher._execute_callbacks(event, [lambda event: self.state.setValue(True), later], [])
            return [], []

        dispatcher._execute_event = Mock(side_effect=dispatch)
        self.handler.execute_event.side_effect = lambda event: dispatcher._execute_callbacks(
            event, [lambda event: self.state.setValue(False, force=True)], [],
        )
        event = NS(mode="Default", identifier="physical-button", extra_data={})
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.assertEqual(dispatcher.execute_event(event), (None, None))
        dispatcher._execute_event.assert_called_once()
        later.assert_not_called()
        self.assertIn("mode=Default input=physical-button", logs.output[0])
        self.assertEqual(len(logs.output), 1)

    def test_ordinary_callback_error_still_allows_other_callbacks(self):
        dispatcher = self.make_dispatcher()
        broken = Mock(side_effect=RuntimeError("ordinary failure"))
        later = Mock()
        event = NS(value=True)
        with self.assertLogs(LOGGER, level="ERROR"):
            dispatcher._execute_callbacks(event, [broken, later], [])
        later.assert_called_once_with(event)

    def test_state_dispatch_fallback_propagates_abort_past_generic_error_handler(self):
        dispatcher = self.make_dispatcher()
        dispatcher.registry = NS(update=Mock())
        dispatcher.runtime_mode = "Default"
        dispatcher._matching_input_item = lambda mode, event: None
        later = Mock()
        dispatcher._matching_state_callbacks = lambda event: [lambda event: self.state.setValue(True), later]
        self.handler.execute_event.side_effect = lambda event: self.state.setValue(False, force=True)
        event = NS(event_type="state", mode="Default", identifier="trigger", value=True)
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.assertEqual(dispatcher.execute_event(event), (None, None))
        later.assert_not_called()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("EXECUTION ABORTED", logs.output[0])

    def make_graph(self):
        context, namespace = load_engine_class("gremlin/execution_graph.py", "ExecutionContext", {"execute_node", "process_functor"})
        context._verbose_exec = context._verbose_detailed = context._verbose_condition = context.perf = False
        types = namespace["ExecutionGraphNodeType"]

        def node(node_id, node_type, functors=(), children=()):
            return NS(
                id=node_id, nodeType=node_type, has_actions=True, children=children,
                latched_conditions=[], is_condition=False, rule=0,
                getActionFunctors=lambda: list(functors), getConditionFunctors=lambda: list(functors),
            )

        def functor(action_id, callback):
            return NS(id=action_id, action_data=NS(), manual_callback=False, process_event=callback)

        return context, namespace, types, node, functor

    def test_graph_group_cannot_treat_abort_as_a_failed_condition(self):
        context, namespace, types, node, functor = self.make_graph()
        later = Mock(return_value=True)
        first = node("first", types.Action, [functor("action-1", lambda event, value, extra: self.state.setValue(True))])
        second = node("second", types.Action, [functor("action-2", later)])
        root = node("root", types.Group, children=[first, second])
        self.handler.execute_event.side_effect = lambda event: self.state.setValue(False, force=True)
        event = NS(mode="Default", identifier="physical-button")
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            with self.assertRaises(execution_guard.ExecutionAborted):
                context.execute_node(root, event, True)
        later.assert_not_called()
        self.assertEqual(namespace["gremlin"].shared_state.popLog.call_count, 2)
        self.assertIn("node=first action=action-1 steps=1", logs.output[0])
        self.assertEqual(len(logs.output), 1)

    def test_graph_group_still_continues_after_a_normal_condition_failure(self):
        context, namespace, types, node, functor = self.make_graph()
        later = Mock(return_value=True)
        first = node("first", types.Condition, [functor("condition", Mock(return_value=False))])
        second = node("second", types.Action, [functor("action", later)])
        root = node("root", types.Group, children=[first, second])
        self.assertTrue(context.execute_node(root, NS(mode="Default", identifier="button"), True))
        later.assert_called_once()

    def test_abort_releases_payload_without_cyclic_garbage_collection(self):
        class Payload:
            pass

        class Emitter:
            emitted = Signal()

        def cancel():
            execution_guard.abort("simulated loop")

        @execution_guard.boundary
        def dispatch(payload, wrapped):
            execution_guard.checkpoint(event=payload)
            if wrapped:
                emitter = Emitter()
                emitter.emitted.connect(cancel)
                emitter.emitted.emit()
            else:
                cancel()

        enabled = gc.isenabled()
        gc.disable()
        try:
            for wrapped in (False, True):
                with self.subTest(wrapped=wrapped):
                    payload = Payload()
                    reference = weakref.ref(payload)
                    with self.assertLogs(LOGGER, level="WARNING"):
                        dispatch(payload, wrapped)
                    del payload
                    self.assertIsNone(reference())
        finally:
            if enabled:
                gc.enable()


if __name__ == "__main__":
    unittest.main()
