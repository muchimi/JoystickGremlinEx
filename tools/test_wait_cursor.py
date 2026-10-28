"""Wait-cursor ownership and deferred-layout checks using real Qt.

Run: python tools/test_wait_cursor.py
No Gremlin startup, devices, or profile/configuration writes.
"""

import ast
import functools
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtGui, QtWidgets

from test_qt_marshalling import APP, UTIL, invoke, pump_until, flush_deletes


ROOT = Path(__file__).resolve().parents[1]
SERVICES = NS(config=NS(Configuration=lambda: NS(verbose_mode_ui_level=lambda level: False)),
              util=NS(InvokeUiMethod=invoke))
tree = ast.parse((ROOT / "gremlin/worker.py").read_bytes())
names = {"WorkerSignals", "_CursorReleaseEvent", "WorkManager", "WorkTask", "with_wait_cursor"}
nodes = [node for node in tree.body if getattr(node, "name", None) in names]
for node in nodes:
    if getattr(node, "name", None) == "WorkManager":
        node.decorator_list = []


class ServiceImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if all(alias.name.startswith("gremlin") for alias in node.names) else node


namespace = dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, QObject=QtCore.QObject,
                 QThread=QtCore.QThread, Slot=QtCore.Slot, QRunnable=QtCore.QRunnable,
                 QThreadPool=QtCore.QThreadPool, Callable=object, InvokeUiMethod=invoke,
                 gremlin=SERVICES, functools=functools, time=time, threading=threading,
                 syslog=logging.getLogger("cursor-checks"))
module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
exec(compile(ast.fix_missing_locations(ServiceImports().visit(module)), "gremlin/worker.py", "exec"), namespace)
Manager = namespace["WorkManager"]


def showing_wait():
    cursor = APP.overrideCursor()
    return cursor is not None and cursor.shape() == QtCore.Qt.CursorShape.WaitCursor


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNone(APP.overrideCursor())
        self.manager = Manager()
        namespace["WorkManager"] = lambda: self.manager

    def tearDown(self):
        self.manager._cursor_push = 0
        self.manager._pop_cursor_request_ui(True)
        self.manager.deleteLater()
        flush_deletes()
        self.assertIsNone(APP.overrideCursor())

    def test_release_waits_for_deferred_callbacks_and_paint(self):
        seen = []

        class PaintedWidget(QtWidgets.QWidget):
            def paintEvent(self, event):
                seen.append(("paint", showing_wait()))
                super().paintEvent(event)

        widget = PaintedWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        self.manager.pushCursor()
        widget.show()

        def refresh():
            seen.append(("refresh", showing_wait()))
            layout.addWidget(QtWidgets.QLabel("Refreshed contents"))
            widget.update()

        QtCore.QTimer.singleShot(0, widget, refresh)
        self.manager.popCursor()
        self.assertTrue(showing_wait())
        pump_until(lambda: not showing_wait())
        self.assertIn(("refresh", True), seen)
        self.assertIn(("paint", True), seen)
        self.assertTrue(all(waiting for _, waiting in seen))
        widget.deleteLater()
        flush_deletes()

    def test_nested_holds_and_new_work_cancel_old_release(self):
        self.manager.pushCursor()
        self.manager.pushCursor()
        self.manager.popCursor()
        APP.processEvents()
        self.assertTrue(showing_wait())
        self.assertEqual(self.manager._cursor_push, 1)
        self.manager.popCursor()  # queues release
        self.manager.pushCursor()  # must invalidate that release
        for _ in range(4):
            APP.processEvents()
        self.assertTrue(showing_wait())
        self.manager.popCursor()
        pump_until(lambda: not showing_wait())

    def test_two_submitted_workers_each_own_a_hold(self):
        jobs = []
        self.manager._threadpool = NS(start=jobs.append)
        self.manager.submit(callback=lambda args: None)
        self.manager.submit(callback=lambda args: None)
        self.assertEqual(self.manager._cursor_push, 2)
        jobs[0].run()
        for _ in range(4):
            APP.processEvents()
        self.assertTrue(showing_wait())
        self.assertEqual(self.manager._cursor_push, 1)
        jobs[1].run()
        pump_until(lambda: not showing_wait())

    def test_real_threadpool_releases_all_worker_holds(self):
        pool = QtCore.QThreadPool(self.manager)
        pool.setMaxThreadCount(4)
        self.manager._threadpool = pool
        release = threading.Event()
        completed = []

        def work(args):
            release.wait(timeout=1)
            completed.append(args)

        for index in range(16):
            self.manager.submit(callback=work, args=index)
        self.assertEqual(self.manager._cursor_push, 16)
        release.set()
        pump_until(lambda: len(completed) == 16 and not showing_wait())
        self.assertEqual(self.manager._cursor_push, 0)
        pool.waitForDone(1000)

    def test_worker_finished_signal_cannot_release_ui_hold(self):
        jobs = []
        self.manager._threadpool = NS(start=jobs.append)
        self.manager.pushCursor()  # scheduled UI refresh owns this hold
        self.manager.submit(callback=lambda args: None)
        worker = threading.Thread(target=jobs[0].run)
        worker.start()
        worker.join()
        pump_until(lambda: self.manager._cursor_push == 1)
        self.assertTrue(showing_wait())
        self.manager.popCursor()
        pump_until(lambda: not showing_wait())

    def test_cursor_change_does_not_reenter_the_event_loop(self):
        calls = []
        QtCore.QTimer.singleShot(0, lambda: calls.append("queued"))
        self.manager.pushCursor()
        self.assertEqual(calls, [])
        self.manager.popCursor()
        self.assertEqual(calls, [])
        pump_until(lambda: not showing_wait())
        self.assertEqual(calls, ["queued"])

    def test_cursor_state_is_only_mutated_on_gui_thread(self):
        worker = threading.Thread(target=self.manager.pushCursor)
        worker.start()
        worker.join()
        self.assertFalse(showing_wait())
        pump_until(showing_wait)
        self.assertEqual(self.manager._cursor_push, 1)
        worker = threading.Thread(target=self.manager.popCursor)
        worker.start()
        worker.join()
        self.assertTrue(showing_wait())
        pump_until(lambda: not showing_wait())

    def test_short_delayed_operation_does_not_flash_wait_cursor(self):
        self.manager.pushCursor(immediate=False)
        self.assertTrue(self.manager._cursor_timer.isActive())
        self.manager.popCursor()
        self.assertFalse(self.manager._cursor_timer.isActive())
        self.manager._cursor_show_hourglass()  # stale timeout must do nothing
        self.assertFalse(showing_wait())

    def test_layout_activity_extends_release_barrier(self):
        self.manager.pushCursor()
        self.manager.popCursor()
        initial_activity = self.manager._cursor_activity
        widget = QtWidgets.QWidget()
        QtCore.QCoreApplication.postEvent(widget, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest))
        APP.processEvents()
        self.assertGreater(self.manager._cursor_activity, initial_activity)
        self.assertTrue(showing_wait())
        pump_until(lambda: not showing_wait())
        widget.deleteLater()

    def test_layout_batches_posted_by_earlier_layouts_keep_cursor(self):
        seen = []

        class RelayoutWidget(QtWidgets.QWidget):
            remaining = 5

            def event(self, event):
                if event.type() == QtCore.QEvent.Type.LayoutRequest:
                    seen.append(showing_wait())
                    self.remaining -= 1
                    if self.remaining:
                        QtCore.QCoreApplication.postEvent(self, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest))
                    return True
                return super().event(event)

        widget = RelayoutWidget()
        self.manager.pushCursor()
        QtCore.QCoreApplication.postEvent(widget, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest))
        self.manager.popCursor()
        pump_until(lambda: not showing_wait())
        self.assertEqual(seen, [True] * 5)
        widget.deleteLater()

    def test_continuous_meter_painting_does_not_leave_wait_cursor_stuck(self):
        widget = QtWidgets.QWidget()
        widget.show()
        APP.processEvents()
        timer = QtCore.QTimer(widget)
        timer.timeout.connect(widget.update)
        self.manager.pushCursor()
        timer.start(0)
        self.manager.popCursor()
        pump_until(lambda: not showing_wait())
        timer.stop()
        widget.deleteLater()

    def test_continuous_background_layouts_do_not_keep_finished_refresh_busy(self):
        class BackgroundWidget(QtWidgets.QWidget):
            active = True

            def event(self, event):
                if event.type() == QtCore.QEvent.Type.LayoutRequest:
                    if self.active:
                        QtCore.QCoreApplication.postEvent(self, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest))
                    return True
                return super().event(event)

        widget = BackgroundWidget()
        try:
            self.manager.pushCursor()
            QtCore.QCoreApplication.postEvent(widget, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest))
            self.manager.popCursor()
            self.assertEqual(self.manager._cursor_push, 0)
            pump_until(lambda: not showing_wait(), timeout=0.5)
            self.assertTrue(widget.active)
        finally:
            widget.active = False
            widget.deleteLater()
            flush_deletes()

    def test_settling_limit_never_clears_an_active_work_hold(self):
        self.manager.pushCursor()
        self.manager.popCursor()  # starts the settling phase
        self.manager.pushCursor()  # new work cancels that phase
        deadline = time.monotonic() + self.manager._CURSOR_SETTLE_SECONDS * 2
        while time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.001)
        self.assertTrue(showing_wait())
        self.assertEqual(self.manager._cursor_push, 1)
        self.manager.popCursor()
        pump_until(lambda: not showing_wait())

    def test_suspended_startup_selection_finishes_worker_and_cursor_hold(self):
        import test_ui_refresh as ui_checks

        ui = ui_checks.main_window()
        ui.config = NS(get_last_input=lambda device: (device, "button", 3))
        ui.popLoading = Mock()
        ui_checks.CONFIG.verbose_mode_ui = False
        ui_checks.SERVICES.joystick_handling = NS(getDevice=lambda guid: NS(name="Device", device_id=guid))
        ui_checks.SERVICES.shared_state.is_input_selection_suspended = True
        del ui._select_input  # execute the real suspended-selection path
        jobs = []
        self.manager._threadpool = NS(start=jobs.append)
        self.manager.submit(callback=ui._tab_selected_worker, args="device")
        worker = threading.Thread(target=jobs[0].run)
        worker.start()
        try:
            pump_until(lambda: not worker.is_alive(), timeout=0.5)
            pump_until(lambda: not showing_wait())
            self.assertEqual(self.manager._cursor_push, 0)
            ui.popLoading.assert_called_once_with("device")
        finally:
            ui._tab_selection_completed = True
            worker.join(timeout=1)
            ui_checks.SERVICES.shared_state.is_input_selection_suspended = False
            ui.deleteLater()
            flush_deletes()

    def test_exception_still_releases_worker_hold(self):
        jobs = []
        self.manager._threadpool = NS(start=jobs.append)

        def fail(args):
            raise ValueError("test failure")

        self.manager.submit(callback=fail)
        with self.assertRaisesRegex(ValueError, "test failure"):
            jobs[0].run()
        pump_until(lambda: not showing_wait())
        self.assertEqual(self.manager._cursor_push, 0)

    def test_decorated_refresh_retains_cursor_until_qt_work_finishes(self):
        seen = []

        @namespace["with_wait_cursor"]
        def refresh():
            self.assertTrue(showing_wait())
            QtCore.QTimer.singleShot(0, lambda: seen.append(showing_wait()))

        refresh()
        self.assertTrue(showing_wait())
        pump_until(lambda: not showing_wait())
        self.assertEqual(seen, [True])

    def test_profile_refresh_hold_covers_selection_retries(self):
        # Execute the actual main-window scheduler with the actual cursor
        # manager, while profile/device services remain isolated fakes.
        import test_ui_refresh as ui_checks

        globals_ = ui_checks.MainWindow._begin_ui_refresh_ui.__globals__
        ui = ui_checks.main_window()
        tab = ui_checks.StartupDeviceTab(ui)
        ui.getRegisteredWidget.return_value = tab
        target = ("device", "button", 3)

        def build_tabs():
            self.assertTrue(showing_wait())
            ui._startup_restore_target = target

        ui._create_tabs_ui.side_effect = build_tabs
        with patch.dict(globals_, WorkManager=lambda: self.manager):
            ui.refresh()
            self.assertTrue(showing_wait())
            pump_until(lambda: ui._create_tabs_ui.called)
            self.assertTrue(showing_wait())
            self.assertEqual(self.manager._cursor_push, 1)
            ui._apply_startup_input_restore(0)
            self.assertTrue(showing_wait())
            tab.select_input(*target)
            pump_until(lambda: not showing_wait())
            self.assertIsNone(ui._startup_restore_target)
            self.assertFalse(ui._ui_refresh_cursor)
        ui.deleteLater()
        flush_deletes()

    def test_cold_start_worker_single_shot_restores_selection_and_cursor(self):
        import test_ui_refresh as ui_checks

        previous = UTIL["_single_shot_invoker"]
        UTIL["_single_shot_invoker"] = None
        ui = ui_checks.main_window()
        tab = ui_checks.StartupDeviceTab(ui)
        ui.getRegisteredWidget.return_value = tab
        ui._select_input.side_effect = tab.select_input
        hooks = []
        globals_ = ui_checks.MainWindow._begin_ui_refresh_ui.__globals__

        def build_tabs():
            ui._schedule_startup_input_restore("device", "button", 3)

        ui._create_tabs_ui.side_effect = build_tabs
        try:
            # A gated-axis constructor first uses singleShot in the parser's
            # worker thread, before any tab/input widget has been constructed.
            worker = threading.Thread(target=lambda: UTIL["singleShot"](
                lambda: hooks.append(QtCore.QThread.isMainThread()),
            ))
            worker.start()
            worker.join()
            with patch.dict(globals_, WorkManager=lambda: self.manager), patch.object(
                ui_checks.SERVICES.util, "singleShot", UTIL["singleShot"],
            ):
                ui.refresh()
                pump_until(lambda: not showing_wait(), timeout=0.5)
                self.assertEqual(hooks, [True])
                self.assertEqual(tab.getSelectedInputItem().input_id, 3)
                self.assertIsNone(ui._startup_restore_target)
                self.assertFalse(ui._ui_refresh_cursor)
                self.assertEqual(self.manager._cursor_push, 0)
        finally:
            invoker = UTIL["_single_shot_invoker"]
            UTIL["_single_shot_invoker"] = previous
            invoker.deleteLater()
            ui.deleteLater()
            flush_deletes()


if __name__ == "__main__":
    unittest.main()
