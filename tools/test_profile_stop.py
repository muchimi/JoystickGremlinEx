"""Headless regressions for deferred actions across profile restart."""

import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import gremlin.base_classes
import gremlin.base_profile
from gremlin import joystick_handling, shared_state
from gremlin.event_handler import EventHandler
from gremlin.execution_graph import ExecutionContext, ExecutionGraphContainerNode, ExecutionGraphNodeType, ExecutionGraphRootNode
from gremlin.input_types import InputType
from gremlin.macro import Macro, MacroManager, MacroState, PauseAction
from gremlin.runtime_timers import RuntimeTimers
from gremlin.types import SyncMode

from action_plugins.map_to_state import MapToStateFunctor
from container_plugins.double_tap import DoubleTapContainerFunctor
from container_plugins.tempo import TempoContainerFunctor
from container_plugins.tempoEx import TempoExContainerFunctor


class PendingTimer:
    def __init__(self, delay, callback):
        self.callback = callback
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


class ProfileStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        joystick_handling.registerSpecialDevices()
        joystick_handling._joystick_initialized = True
        shared_state.current_profile = gremlin.base_profile.Profile()

    def pump_until(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate():
            self.app.processEvents()
            self.assertLess(time.monotonic(), deadline, "timed out waiting for profile work")
            time.sleep(0.002)

    def test_map_to_state_listener_follows_activation_and_remembers_its_key(self):
        action = SimpleNamespace(
            name="Map to State",
            id="listener-action",
            key="observed-state",
            description="",
            hardware_device_guid=None,
            hardware_input_id=None,
            input_item=SimpleNamespace(display_name="Test input"),
            get_input_type=lambda: InputType.State,
            mode="pulse",
            sync_mode=SyncMode.Ignore,
            target_states=lambda: [],
            reset_default_on_stop=False,
        )
        registry = shared_state.current_profile.state
        self.addCleanup(registry.remove, action.key)
        functor = MapToStateFunctor(action)
        self.addCleanup(functor.unhook)
        self.assertNotIn(action.key, registry._state_change_callbacks)
        functor.profile_start()
        functor.profile_start()
        self.assertEqual(registry._state_change_callbacks[action.key], [functor._handle_state_changed])
        original_key = action.key
        action.key = "renamed-state"
        functor.profile_stop()
        self.assertNotIn(original_key, registry._state_change_callbacks)
        functor.profile_start()
        functor.unhook()
        self.assertNotIn(action.key, registry._state_change_callbacks)

    def test_registered_container_lookup_uses_profile_id_index(self):
        context = ExecutionContext()
        self.addCleanup(context.clear)
        context.clear()
        context.graph = ExecutionGraphRootNode()
        container = SimpleNamespace(id="saved-container-id")
        node = ExecutionGraphContainerNode(container)
        node.ref = container.id
        node.parent = context.graph
        callbacks = {0: {0: {0: [(SimpleNamespace(id=container.id), None)]}}}
        context.registerCallbacks(callbacks)

        with patch.object(context, "_safe_preorder_iter", side_effect=AssertionError("unexpected graph scan")):
            self.assertIs(context.find(container, ExecutionGraphNodeType.Container), node)

        context.clear()
        self.assertIsNone(context.find(container, ExecutionGraphNodeType.Container))

    def test_stop_discards_blocked_mode_change_before_restart(self):
        handler = EventHandler()
        self.addCleanup(handler.stop_mode_queue)
        allowed = threading.Event()
        calls = []
        args = (True, False, True, True)
        with (
            patch.object(handler, "ModeChangeAllowed", side_effect=allowed.is_set),
            patch.object(handler, "_change_mode", side_effect=lambda mode, _: calls.append((mode, threading.get_ident()))),
        ):
            handler._profile_start()
            handler.queueModeChange("old", args)
            self.pump_until(handler._mode_queue_timer.isActive)
            handler._profile_stop()
            handler.queueModeChange("while stopped", args)
            handler._profile_start()
            self.app.processEvents()
            self.assertEqual(calls, [])

            allowed.set()
            sender = threading.Thread(target=handler.queueModeChange, args=("fresh", args))
            sender.start()
            sender.join(timeout=2)
            self.pump_until(lambda: bool(calls))
            self.assertEqual(calls, [("fresh", threading.get_ident())])
            handler._profile_stop()

    def test_tap_container_drops_timer_already_delivered_after_restart(self):
        with patch("gremlin.runtime_timers.threading.Timer", PendingTimer):
            for functor in (DoubleTapContainerFunctor, TempoContainerFunctor, TempoExContainerFunctor):
                with self.subTest(functor=functor.__name__):
                    instance = SimpleNamespace(_timers=RuntimeTimers())
                    calls = []
                    instance._timers.start()
                    old = instance._timers.schedule(1, lambda: calls.append("old"))
                    functor.profile_stopping(instance)
                    self.assertTrue(old.cancelled)
                    instance._timers.start()
                    old.callback()
                    instance._timers.schedule(1, lambda: calls.append("new")).callback()
                    self.assertEqual(calls, ["new"])

    def test_macro_stop_interrupts_pause_and_drops_old_work(self):
        manager = MacroManager()
        for use_v2 in (False, True):
            with self.subTest(use_v2=use_v2), patch.object(manager, "_use_v2_mode", use_v2):
                entered = threading.Event()
                calls = []

                class MarkedPause(PauseAction):
                    def __call__(self, *args, **kwargs):
                        entered.set()
                        super().__call__(*args, **kwargs)

                macro = Macro()
                macro.add_action(MarkedPause(60))
                macro.add_action(lambda *args, **kwargs: calls.append("action"))
                macro.completed_callback = lambda: calls.append("completion")
                manager.start()
                try:
                    self.assertEqual(manager.queue_macro(macro, is_local=True), macro.id)
                    self.assertTrue(entered.wait(timeout=2))
                    manager.stop()
                    self.assertIsNone(manager.queue_macro(macro, is_local=True))
                    manager.start()
                    self.pump_until(lambda: macro.id not in manager._active and macro.id not in manager._macro_flags)
                    self.assertIs(macro.state, MacroState.Idle)
                    self.assertEqual(calls, [])
                finally:
                    manager.stop()


if __name__ == "__main__":
    unittest.main()
