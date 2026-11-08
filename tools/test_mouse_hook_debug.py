"""Hardware-free mouse hook bypass checks: python tools/test_mouse_hook_debug.py."""

import ast
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_class(path, name, namespace, methods=None):
    source = next(node for node in ast.parse((ROOT / path).read_bytes()).body
                  if isinstance(node, ast.ClassDef) and node.name == name)
    source.bases = []
    source.decorator_list = []
    if methods is not None:
        source.body = [node for node in source.body if getattr(node, "name", None) in methods]
    module = ast.Module(body=[*ast.parse("from __future__ import annotations").body, source], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / path), "exec"), namespace)
    return namespace[name]


class MouseHookDebugTests(unittest.TestCase):
    def setUp(self):
        self.config = NS(startup_mouse_hook_disabled=True, mouse_wheel_autorelease_delay=0.5)
        services = ModuleType("gremlin")
        services.__path__ = []
        services.config = ModuleType("gremlin.config")
        services.config.Configuration = lambda: self.config
        services.types = ModuleType("gremlin.types")
        services.types.MouseButton = NS(WheelDown=1, WheelUp=2, WheelLeft=3, WheelRight=4)
        services.windows_event_hook = ModuleType("gremlin.windows_event_hook")
        modules = {"gremlin": services, "gremlin.config": services.config,
                   "gremlin.types": services.types, "gremlin.windows_event_hook": services.windows_event_hook}
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.start = Mock(side_effect=lambda hook, name: setattr(hook, "_running", True))
        self.stop = Mock(side_effect=lambda hook: setattr(hook, "_running", False))
        self.wheel_worker = Mock()
        self.namespace = dict(
            gremlin=services, threading=threading, syslog=Mock(),
            ctypes=NS(windll=NS(user32=NS(GetSystemMetrics=lambda metric: 0))),
            g_mouse_callbacks=[], g_mouse_move_callbacks=[], g_mouse_wheel_callbacks=[],
            _mouse_wheel_state={}, _start_listener=self.start, _stop_listener=self.stop,
            _ensure_wheel_worker=self.wheel_worker,
        )
        hook_type = load_class("gremlin/windows_event_hook.py", "MouseHook", self.namespace)
        self.hook = hook_type()
        self.hook._stop_timers = Mock()
        self.factory = services.windows_event_hook.MouseHook = Mock(return_value=self.hook)
        listener_type = load_class("gremlin/event_handler.py", "EventListener", self.namespace,
                                   {"enableMouse", "disableMouse", "mouseEnabled"})
        self.listener = listener_type()
        self.listener.enable_mouse_hook = False
        self.listener.mouse_hook = None
        self.listener._mouse_hook_stack = 0
        self.listener._mouse_handler = Mock()

    def assert_not_started(self):
        self.start.assert_not_called()
        self.wheel_worker.assert_not_called()
        self.assertFalse(self.hook._running)
        self.assertIsNone(self.hook._listen_thread)
        self.assertIsNone(self.hook.hook_id)

    def test_disabled_direct_start_creates_neither_hook_nor_wheel_worker(self):
        self.hook.start()
        self.assert_not_started()

    def test_all_registration_paths_honor_the_disable_flag(self):
        for method in (self.hook.register, self.hook.registerMouseMove, self.hook.registerMouseWheel):
            method(Mock())
        self.assert_not_started()

    def test_forced_and_regular_requests_leave_listener_disabled(self):
        self.listener.enable_mouse_hook = True  # stale state must not override the startup setting
        for force in (False, True):
            self.listener.enableMouse(force=force)
            self.assertEqual(self.listener._mouse_hook_stack, 0)
            self.assertFalse(self.listener.mouseEnabled())
        self.factory.assert_not_called()
        self.assert_not_started()

    def test_enabled_direct_start_starts_the_worker_and_listener(self):
        self.config.startup_mouse_hook_disabled = False
        self.hook.start()
        self.start.assert_called_once_with(self.hook, "mouse hook")
        self.wheel_worker.assert_called_once()
        self.assertTrue(self.hook._running)

    def test_allowed_listener_requests_keep_existing_stack_behavior(self):
        self.config.startup_mouse_hook_disabled = False
        self.listener.enable_mouse_hook = True
        self.listener.enableMouse()
        self.listener.enableMouse()
        self.assertEqual(self.listener._mouse_hook_stack, 2)
        self.assertTrue(self.listener.mouseEnabled())
        self.assertTrue(self.hook._running)
        self.listener.disableMouse()
        self.assertEqual(self.listener._mouse_hook_stack, 1)
        self.assertTrue(self.hook._running)
        self.listener.disableMouse(reset=True)
        self.assertEqual(self.listener._mouse_hook_stack, 0)
        self.assertFalse(self.listener.mouseEnabled())
        self.assertFalse(self.hook._running)

    def test_force_still_works_when_startup_allows_mouse_hooks(self):
        self.config.startup_mouse_hook_disabled = False
        self.listener.enableMouse(force=True)
        self.assertEqual(self.listener._mouse_hook_stack, 1)
        self.assertTrue(self.listener.mouseEnabled())
        self.assertTrue(self.hook._running)


if __name__ == "__main__":
    unittest.main()
