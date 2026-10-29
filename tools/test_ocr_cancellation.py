"""Real Qt/worker cancellation checks without OCR models, capture, or hardware.

Run: python -m pytest tools/test_ocr_cancellation.py -q -p no:cacheprovider
"""

import ast
from collections import deque
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
from typing import Any, Callable
import unittest
from unittest.mock import Mock

from PySide6 import QtCore, QtGui, QtWidgets

from test_qt_marshalling import APP, UTIL, flush_deletes, invoke, pump_until


ROOT = Path(__file__).resolve().parents[1]


def load(path, names, namespace):
    class Services(ast.NodeTransformer):
        def visit_Import(self, node):
            return None if all(a.name.startswith("gremlin") for a in node.names) else node

        def visit_ImportFrom(self, node):
            return None if node.level or (node.module or "").startswith("gremlin") else node

    tree = ast.parse((ROOT / path).read_bytes())
    nodes = ast.parse("from __future__ import annotations").body
    for node in tree.body:
        if getattr(node, "name", None) in names:
            if isinstance(node, ast.ClassDef):
                node.decorator_list = []
            nodes.append(Services().visit(node))
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, path, "exec"), namespace)


def image():
    result = QtGui.QImage(20, 20, QtGui.QImage.Format.Format_RGB32)
    result.fill(QtGui.QColor("white"))
    return result


class OcrCancellationTests(unittest.TestCase):
    def setUp(self):
        self.running = True
        self.release_workers = threading.Event()
        self.events = []
        self.done = []
        self.capture = Mock(return_value=image())
        self.recognize = Mock(return_value=([{"text": "HELMET"}], "fake"))
        self.ns = dict(
            threading=threading, time=time, deque=deque, Any=Any, Callable=Callable,
            QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets,
            syslog=logging.getLogger("ocr-cancellation-tests"), _TEST_COUNTDOWN_S=5,
            gremlin=NS(util=NS(InvokeUiMethod=invoke, singleShot=UTIL["singleShot"], is_ui_thread=UTIL["is_ui_thread"]),
                       shared_state=NS(is_running=True)),
            normalize_ocr_arm_mode=lambda value: value or "toggle",
            normalize_ocr_arm_pulses=lambda value: value or 5,
            normalize_ocr_arm_pulse_spacing_ms=lambda value: value or 500,
            normalize_ocr_confidence=lambda value: value or 0.7,
            normalize_ocr_engine=lambda value: value or "auto",
            normalize_ocr_miss_tolerance=lambda value: value or 3,
            normalize_ocr_rules=lambda rules: rules or [],
            binding_is_configured=lambda binding: True,
            read_toggle_active=lambda binding: binding.get("active", False),
            rule_match_result=lambda text, rule: (text == "HELMET", None, "Helmet"),
            _resolve_rule_runtime=lambda rule, extra: {},
            ocr_rule_input_id=lambda widget_id, rule_id: f"{widget_id}:{rule_id}",
            find_overlay_input=lambda input_id: NS(input_id=input_id),
            ensure_overlay_input=lambda input_id, title: NS(input_id=input_id),
            overlay_input_has_mappings=lambda item: True,
            emit_overlay_button_event=lambda item, pressed, extra_data: self.events.append((item.input_id, pressed, QtCore.QThread.isMainThread())),
            capture_for_item_sync=lambda *args, **kwargs: self.capture(*args, **kwargs),
            recognize=lambda *args, **kwargs: self.recognize(*args, **kwargs),
            joined_text=lambda hits: " ".join(hit["text"] for hit in hits),
            resolve_capture_rect=lambda item: (QtCore.QRect(0, 0, 20, 20), "widget"),
            _hide_overlays_for_test=Mock(return_value=[("overlay", True)]),
            _restore_overlays=Mock(),
            capture_for_item=lambda *args, **kwargs: self.capture(*args, **kwargs),
        )
        load("gremlin/ui/obs_overlay/ocr_capture.py", {"OcrRegionCountdown", "OcrTestCapture", "run_test_capture_countdown", "_wait_capture"}, self.ns)
        # Keep the real timer and completion path, without displaying a window.
        self.ns["OcrRegionCountdown"].start = lambda countdown: countdown._timer.start()
        load("gremlin/ui/obs_overlay/ocr_track.py", {"_OcrSession", "OcrOverlayTracker"}, self.ns)
        self.tracker = self.ns["OcrOverlayTracker"]()
        self.tracker._profile_running = lambda: self.running
        self.tracker._app_allows_scan = lambda: True
        self.item = {
            "id": "helmet", "binding": {"active": True},
            "style": {"ocr_arm_mode": "hold", "ocr_interval_ms": 5000},
            "ocr_rules": [{"id": "rule", "name": "Helmet", "text": "HELMET"}],
        }

    def tearDown(self):
        self.tracker.stop_runtime()
        self.release_workers.set()
        thread = self.tracker._thread
        if thread is not None:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        APP.processEvents()
        flush_deletes()

    def session(self, item=None):
        item = self.item if item is None else item
        slot = self.tracker._slots.setdefault(item["id"], {"item": item, "armed": False, "generation": 0})
        session = self.tracker._new_session(item["id"], slot)
        return session, slot

    def emit_on_worker(self, pressed=True):
        thread = threading.Thread(target=lambda: self.tracker._emit_rule("helmet", self.item["ocr_rules"][0], pressed, "Helmet", None))
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_cancel_drops_an_already_queued_press(self):
        self.session()
        self.emit_on_worker()
        self.tracker.cancel("helmet")
        APP.processEvents()
        self.assertEqual(self.events, [])
        self.assertEqual(self.tracker.status(self.item), "Cancelled")

    def test_stop_releases_only_delivered_presses_once_on_gui(self):
        self.session()
        self.tracker._emit_rule("helmet", self.item["ocr_rules"][0], True, "Helmet", None)
        self.tracker.cancel("helmet")
        self.tracker.cancel("helmet")
        pump_until(lambda: len(self.events) == 2)
        self.assertEqual(self.events, [("helmet:rule", True, True), ("helmet:rule", False, True)])
        self.assertEqual(self.tracker._delivered, {})

    def test_stop_from_a_mapped_press_discards_other_queued_rules(self):
        self.session()

        def emit(item, pressed, extra_data):
            self.events.append((item.input_id, pressed, QtCore.QThread.isMainThread()))
            if pressed:
                self.tracker.cancel()

        self.ns["emit_overlay_button_event"] = emit
        first = self.item["ocr_rules"][0]
        second = dict(first, id="second")

        def queue():
            self.tracker._emit_rule("helmet", first, True, "Helmet", None)
            self.tracker._emit_rule("helmet", second, True, "Helmet", None)

        worker = threading.Thread(target=queue)
        worker.start()
        worker.join(1)
        pump_until(lambda: len(self.events) == 2)
        self.assertEqual(self.events, [("helmet:rule", True, True), ("helmet:rule", False, True)])
        self.assertEqual(self.tracker._delivered, {})

    def test_old_cleanup_cannot_release_a_new_session_press(self):
        self.session()
        self.tracker._emit_rule("helmet", self.item["ocr_rules"][0], True, "Helmet", None)
        self.tracker.cancel("helmet")
        self.session()
        self.tracker._emit_rule("helmet", self.item["ocr_rules"][0], True, "Helmet", None)
        APP.processEvents()
        self.assertEqual([event[1] for event in self.events], [True, False, True])
        self.assertEqual(len(self.tracker._delivered), 1)

    def test_stop_during_native_recognition_is_nonblocking_and_discards_results(self):
        entered = threading.Event()

        def recognize(*args, **kwargs):
            entered.set()
            self.release_workers.wait(2)
            return [{"text": "HELMET"}], "fake"

        self.recognize.side_effect = recognize
        self.tracker.sample(self.item)
        pump_until(entered.is_set)
        thread = self.tracker._thread
        started = time.monotonic()
        self.tracker.stop_runtime()
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertIs(self.tracker._thread, thread)
        self.assertTrue(thread.is_alive())
        self.release_workers.set()
        thread.join(2)
        APP.processEvents()
        self.assertEqual(self.events, [])
        self.assertEqual(self.tracker.status(self.item), "Cancelled")
        self.assertEqual(self.tracker.last_text(self.item), "")

    def test_held_arm_input_requires_release_before_rearming(self):
        self.tracker._ensure_thread = Mock()
        self.assertTrue(self.tracker.sample(self.item))
        old = self.tracker._slots["helmet"]["session"]
        self.tracker.cancel("helmet")
        self.assertFalse(self.tracker.sample(self.item))
        self.item["binding"]["active"] = False
        self.assertFalse(self.tracker.sample(self.item))
        self.item["binding"]["active"] = True
        self.assertTrue(self.tracker.sample(self.item))
        self.assertIsNot(self.tracker._slots["helmet"]["session"], old)
        self.assertTrue(old.cancelled.is_set())

    def test_rearm_during_stopping_worker_uses_fresh_stop_flag_and_no_overlap(self):
        entered = threading.Event()
        calls = []
        active = []

        def recognize(*args, **kwargs):
            calls.append(threading.current_thread())
            active.append(1)
            self.assertEqual(len(active), 1)
            if len(calls) == 1:
                entered.set()
                self.release_workers.wait(2)
            active.pop()
            return [{"text": "HELMET"}], "fake"

        self.recognize.side_effect = recognize
        self.tracker.sample(self.item)
        pump_until(entered.is_set)
        old_thread, old_stop = self.tracker._thread, self.tracker._stop
        self.tracker.stop_runtime()
        self.item["binding"]["active"] = False
        self.tracker.sample(self.item)
        self.item["binding"]["active"] = True
        self.tracker.sample(self.item)
        self.assertIs(self.tracker._thread, old_thread)
        self.assertTrue(old_stop.is_set())
        self.release_workers.set()
        pump_until(lambda: len(calls) == 2 and bool(self.events))
        self.assertIsNot(calls[0], calls[1])
        self.assertIsNot(self.tracker._stop, old_stop)
        self.assertTrue(old_stop.is_set())
        self.assertEqual([event[1] for event in self.events], [True])

    def test_test_once_recognizes_on_worker_and_completes_on_gui(self):
        self.running = False
        threads = []
        self.recognize.side_effect = lambda *args, **kwargs: threads.append(QtCore.QThread.isMainThread()) or ([{"text": "HELMET"}], "fake")
        self.tracker.test_once(self.item, lambda text: self.done.append((text, QtCore.QThread.isMainThread())))
        handle = self.tracker._slots["helmet"]["session"].countdown
        handle._countdown._seconds_left = 1
        handle._countdown._tick()
        pump_until(lambda: bool(self.done))
        self.assertEqual(threads, [False])
        self.assertEqual(self.done, [("HELMET", True)])
        self.ns["_restore_overlays"].assert_called_once_with([("overlay", True)])

    def test_cancel_countdown_restores_overlay_and_never_captures(self):
        self.tracker.test_once(self.item, self.done.append)
        handle = self.tracker._slots["helmet"]["session"].countdown
        countdown = handle._countdown
        self.tracker.cancel("helmet")
        countdown._tick()
        self.capture.assert_not_called()
        self.recognize.assert_not_called()
        self.assertEqual(self.done, [])
        self.ns["_restore_overlays"].assert_called_once_with([("overlay", True)])

    def test_stop_from_worker_cancels_countdown_on_gui(self):
        self.tracker.test_once(self.item)
        thread = threading.Thread(target=lambda: self.tracker.cancel("helmet"))
        thread.start()
        thread.join(2)
        pump_until(lambda: self.ns["_restore_overlays"].called)
        self.recognize.assert_not_called()

    def test_cancel_test_during_recognition_drops_completion_callback(self):
        entered = threading.Event()

        def recognize(*args, **kwargs):
            entered.set()
            self.release_workers.wait(2)
            return [{"text": "HELMET"}], "fake"

        self.recognize.side_effect = recognize
        self.tracker.test_once(self.item, self.done.append)
        self.tracker._slots["helmet"]["session"].countdown._finish()
        pump_until(entered.is_set)
        thread = self.tracker._thread
        self.tracker.cancel("helmet")
        self.release_workers.set()
        thread.join(2)
        APP.processEvents()
        self.assertEqual(self.done, [])
        self.assertEqual(self.events, [])
        self.assertEqual(self.tracker.status(self.item), "Cancelled")

    def test_clear_results_discards_existing_scan_session(self):
        session, slot = self.session()
        self.emit_on_worker()
        self.tracker.clear_results(self.item)
        APP.processEvents()
        self.assertTrue(session.cancelled.is_set())
        self.assertEqual(self.events, [])

    def test_pulse_delivers_press_and_release_after_natural_disarm(self):
        self.item["style"]["ocr_arm_mode"] = "pulse"
        self.tracker.sample(self.item)
        pump_until(lambda: len(self.events) == 2)
        self.assertEqual([event[1] for event in self.events], [True, False])
        self.assertFalse(self.tracker.armed(self.item))

    def test_hold_disarm_releases_its_delivered_output(self):
        self.tracker._ensure_thread = Mock()
        self.tracker.sample(self.item)
        self.tracker._emit_rule("helmet", self.item["ocr_rules"][0], True, "Helmet", None)
        self.item["binding"]["active"] = False
        self.tracker.sample(self.item)
        pump_until(lambda: len(self.events) == 2)
        self.assertEqual([event[1] for event in self.events], [True, False])

    def test_cancelling_one_widget_preserves_another_widgets_output(self):
        self.session()
        other = dict(self.item, id="other")
        second, slot = self.session(other)
        for item in (self.item, other):
            self.tracker._emit_rule(item["id"], item["ocr_rules"][0], True, "Helmet", None)
        self.tracker.cancel("helmet")
        pump_until(lambda: len(self.events) == 3)
        self.assertFalse(second.cancelled.is_set())
        self.assertEqual(self.events[-1], ("helmet:rule", False, True))
        self.assertIn(("other", "rule"), self.tracker._delivered)

    def test_cancel_drops_queued_test_completion_after_recognition_finishes(self):
        self.running = False
        self.tracker.test_once(self.item, self.done.append)
        self.tracker._slots["helmet"]["session"].countdown._finish()
        thread = self.tracker._thread
        if thread is not None:
            thread.join(2)
        self.tracker.cancel("helmet")
        APP.processEvents()
        self.assertEqual(self.done, [])
        self.assertEqual(self.events, [])

    def capture_namespace(self):
        namespace = dict(self.ns,
                         normalize_ocr_region=lambda value: value or "widget",
                         _assert_overlays_topmost=Mock(), _invalidate_live_overlays=Mock(),
                         _overlay_windows=lambda: [], _monitor_index_for_item=lambda item: 0,
                         grab_screen_rect=Mock(return_value=image()), grab_screen_image=Mock(return_value=image()))
        load("gremlin/ui/obs_overlay/ocr_capture.py", {
            "capture_for_item", "capture_for_item_sync", "_capture_armed_on_worker", "_wait_capture",
        }, namespace)
        return namespace

    def test_capture_paths_still_capture_when_not_cancelled(self):
        namespace = self.capture_namespace()
        self.assertFalse(namespace["capture_for_item"](self.item).isNull())
        self.assertFalse(namespace["capture_for_item_sync"](self.item).isNull())
        self.assertEqual(namespace["grab_screen_rect"].call_count, 2)

    def test_cancelled_capture_skips_queued_gui_geometry_work(self):
        namespace = self.capture_namespace()
        cancelled = threading.Event()
        posted = threading.Event()

        def post(method):
            invoke(method)
            posted.set()

        namespace["gremlin"] = NS(util=NS(InvokeUiMethod=post, is_ui_thread=UTIL["is_ui_thread"]))
        namespace["resolve_capture_rect"] = Mock(return_value=(QtCore.QRect(0, 0, 20, 20), "widget"))
        result = []
        thread = threading.Thread(target=lambda: result.append(namespace["capture_for_item_sync"](self.item, cancelled=cancelled.is_set)))
        thread.start()
        self.assertTrue(posted.wait(1))
        cancelled.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        APP.processEvents()
        namespace["resolve_capture_rect"].assert_not_called()
        namespace["grab_screen_rect"].assert_not_called()
        self.assertEqual(result, [None])

    def test_timed_out_capture_skips_late_gui_work(self):
        namespace = self.capture_namespace()
        namespace["_wait_capture"] = lambda *args: False
        namespace["resolve_capture_rect"] = Mock()
        thread = threading.Thread(target=lambda: namespace["capture_for_item_sync"](self.item))
        thread.start()
        thread.join(1)
        APP.processEvents()
        namespace["resolve_capture_rect"].assert_not_called()
        namespace["grab_screen_rect"].assert_not_called()

    def test_capture_wait_responds_to_cancellation(self):
        cancelled = threading.Event()
        result = []
        thread = threading.Thread(target=lambda: result.append(self.ns["_wait_capture"](threading.Event(), 5, cancelled.is_set)))
        thread.start()
        cancelled.set()
        thread.join(0.5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])

    def test_overlapping_test_captures_restore_overlay_only_after_last_cancel(self):
        overlay = QtWidgets.QWidget()
        overlay.show()
        namespace = dict(self.ns, _overlay_windows=lambda: [overlay],
                         _TEST_CAPTURE_LEASES=0, _TEST_CAPTURE_WINDOWS=[])
        load("gremlin/ui/obs_overlay/ocr_capture.py", {"_hide_overlays_for_test", "_restore_overlays"}, namespace)
        try:
            first = namespace["_hide_overlays_for_test"]()
            second = namespace["_hide_overlays_for_test"]()
            self.assertFalse(overlay.isVisible())
            namespace["_restore_overlays"](first)
            self.assertFalse(overlay.isVisible())
            namespace["_restore_overlays"](second)
            self.assertTrue(overlay.isVisible())
            self.assertEqual(namespace["_TEST_CAPTURE_LEASES"], 0)
            self.assertEqual(namespace["_TEST_CAPTURE_WINDOWS"], [])
        finally:
            overlay.hide()
            overlay.deleteLater()

    def test_engine_cancellation_skips_fallback_engine(self):
        cancelled = threading.Event()
        rapid = Mock(side_effect=lambda *args: cancelled.set())
        windows = Mock()
        namespace = dict(self.ns, _recognize_rapid=rapid, _recognize_windows=windows)
        load("gremlin/ui/obs_overlay/ocr_engine.py", {"recognize"}, namespace)
        self.assertEqual(namespace["recognize"](image(), cancelled=cancelled.is_set), ([], "none"))
        rapid.assert_called_once()
        windows.assert_not_called()

    def test_control_action_stops_ocr_on_configured_edge(self):
        from gremlin.types import ControlAction

        tree = ast.parse((ROOT / "action_plugins/control/__init__.py").read_bytes())
        source = next(n for n in tree.body if getattr(n, "name", None) == "ControlFunctor")
        method = next(n for n in source.body if getattr(n, "name", None) == "process_event")
        path = "action_plugins/control/__init__.py"
        source.bases = []
        source.body = [method]
        # load() selects the class with all methods; isolate process_event here.
        class NoServices(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                return None if (node.module or "").startswith("gremlin") else node

        source = NoServices().visit(source)
        listener = NS(control_event=Mock())
        namespace = dict(
            ControlAction=ControlAction, OcrOverlayTracker=lambda: self.tracker,
            gremlin=NS(config=NS(Configuration=lambda: NS(verbose=False)), event_handler=NS(EventListener=lambda: listener)),
        )
        module = ast.fix_missing_locations(ast.Module(body=ast.parse("from __future__ import annotations").body + [source], type_ignores=[]))
        exec(compile(module, path, "exec"), namespace)
        functor = namespace["ControlFunctor"]()
        functor.action_data = NS(action=ControlAction.OCRStop, exec_on_press=True, exec_on_release=False)
        session, slot = self.session()
        functor.process_event(NS(extra_data=None, is_pressed=False), False)
        self.assertFalse(session.cancelled.is_set())
        self.assertTrue(functor.process_event(NS(extra_data=None, is_pressed=True), True))
        self.assertTrue(session.cancelled.is_set())
        self.assertEqual(ControlAction.from_string(ControlAction.to_string(ControlAction.OCRStop)), ControlAction.OCRStop)
        self.assertIn("Stop OCR", ControlAction.to_display_name(ControlAction.OCRStop))


if __name__ == "__main__":
    unittest.main()
