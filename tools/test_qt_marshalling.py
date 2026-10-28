"""Real Qt thread/lifetime checks without hardware or profile/config writes.

Run with: python tools/test_qt_marshalling.py
Load the production definitions without importing device services.
"""

import ast
import gc
import inspect
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
from typing import Callable
import unittest
import weakref

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken


ROOT = Path(__file__).resolve().parents[1]
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([
    "qt-marshalling-checks", "-platform", "offscreen",
])


def definitions(path, names):
    nodes = []
    for node in ast.parse((ROOT / path).read_bytes()).body:
        if getattr(node, "name", None) in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            nodes.append(node)
    return nodes


UTIL = dict(QtCore=QtCore, QtWidgets=QtWidgets, Shiboken=Shiboken,
            threading=threading, inspect=inspect, Callable=Callable)
exec(compile(ast.Module(body=definitions("gremlin/util.py", {
    "_UiMethodDispatcher", "_ui_method_dispatcher", "_ui_method_dispatcher_lock",
    "InvokeUiMethod", "is_ui_thread", "CallbackEvent", "SingleShotInvoker",
    "_single_shot_invoker", "_single_shot_invoker_lock", "singleShot",
}), type_ignores=[]), "gremlin/util.py", "exec"), UTIL)
invoke = UTIL["InvokeUiMethod"]


def pump_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.001)
    if not predicate():
        raise AssertionError("Timed out waiting for GUI delivery")


def flush_deletes(receiver=None):
    QtCore.QCoreApplication.sendPostedEvents(receiver, QtCore.QEvent.Type.DeferredDelete)
    APP.processEvents()


class Receiver(QtWidgets.QWidget):
    def __init__(self, calls):
        super().__init__()
        self.calls = calls

    def receive(self, value):
        self.calls.append((QtCore.QThread.isMainThread(), value))
        self.setWindowTitle(str(value))

    def refresh(self):
        self.receive("refresh")


class MarshallingTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.old_handler = QtCore.qInstallMessageHandler(
            lambda kind, context, message: self.messages.append(message)
        )

    def tearDown(self):
        flush_deletes()
        QtCore.qInstallMessageHandler(self.old_handler)
        self.assertEqual(self.messages, [], "Unexpected Qt thread/paint warnings")

    def test_ui_call_is_synchronous(self):
        calls = []
        invoke(lambda: calls.append(QtCore.QThread.isMainThread()))
        self.assertEqual(calls, [True])

    def test_single_shot_first_created_in_worker_runs_on_gui(self):
        previous = UTIL["_single_shot_invoker"]
        UTIL["_single_shot_invoker"] = None
        calls = []
        try:
            worker = threading.Thread(target=lambda: UTIL["singleShot"](
                lambda: calls.append(QtCore.QThread.isMainThread()),
            ))
            worker.start()
            worker.join()
            pump_until(lambda: bool(calls), timeout=0.3)
            self.assertEqual(calls, [True])
        finally:
            invoker = UTIL["_single_shot_invoker"]
            UTIL["_single_shot_invoker"] = previous
            if invoker is not None and Shiboken.isValid(invoker):
                invoker.deleteLater()

    def test_single_shot_on_gui_is_still_deferred(self):
        calls = []
        UTIL["singleShot"](lambda: calls.append(QtCore.QThread.isMainThread()))
        self.assertEqual(calls, [])
        pump_until(lambda: bool(calls))
        self.assertEqual(calls, [True])

    def test_single_shot_skips_deleted_receiver(self):
        calls = []
        receiver = Receiver(calls)
        UTIL["singleShot"](receiver.refresh)
        receiver.deleteLater()
        flush_deletes(receiver)
        self.assertEqual(calls, [])

    def test_worker_call_is_queued_and_keeps_all_arguments(self):
        calls = []

        def receive(a, b, c, d, e, f, g, h):
            calls.append((QtCore.QThread.isMainThread(), a, b, c, d, e, f, g, h))

        worker = threading.Thread(target=lambda: invoke(receive, *range(8)))
        worker.start()
        worker.join()
        self.assertEqual(calls, [])
        pump_until(lambda: bool(calls))
        self.assertEqual(calls, [(True, *range(8))])

    def test_deleted_receiver_is_skipped_at_delivery(self):
        calls = []
        receiver = Receiver(calls)
        worker = threading.Thread(target=lambda: invoke(receiver.receive, "stale"))
        worker.start()
        worker.join()
        receiver.deleteLater()
        flush_deletes(receiver)
        self.assertFalse(Shiboken.isValid(receiver))
        self.assertEqual(calls, [])
        invoke(receiver.receive, "also stale")
        self.assertEqual(calls, [])

    def test_payload_is_kept_until_delivery_then_released_without_gc(self):
        class Payload:
            pass

        refs, calls = [], []

        def post():
            payload = Payload()
            refs.append(weakref.ref(payload))
            invoke(lambda value: calls.append(value is not None), payload)

        enabled = gc.isenabled()
        gc.disable()  # production disables cyclic collection
        try:
            worker = threading.Thread(target=post)
            worker.start()
            worker.join()
            self.assertIsNotNone(refs[0]())
            pump_until(lambda: bool(calls))
            self.assertIsNone(refs[0]())
        finally:
            if enabled:
                gc.enable()

    def test_concurrent_worker_burst_uses_one_receiver(self):
        calls = []

        def receive(worker_id, sequence):
            calls.append((QtCore.QThread.isMainThread(), worker_id, sequence))

        def post(worker_id):
            for sequence in range(2500):
                invoke(receive, worker_id, sequence)

        workers = [threading.Thread(target=post, args=(i,)) for i in range(4)]
        for worker in workers:
            worker.start()
        pump_until(lambda: all(not worker.is_alive() for worker in workers) and len(calls) == 10000, 10)
        for worker in workers:
            worker.join()
        self.assertTrue(all(call[0] for call in calls))
        for worker_id in range(4):
            self.assertEqual([call[2] for call in calls if call[1] == worker_id], list(range(2500)))
        dispatcher_type = UTIL["_UiMethodDispatcher"]
        self.assertEqual(len(APP.findChildren(dispatcher_type)), 1)


def load_http_receiver():
    tree = ast.parse((ROOT / "gremlin/ui/obs_overlay/websocket_server.py").read_bytes())
    source = next(node for node in tree.body if getattr(node, "name", None) == "OverlayWebsocketSession")
    methods = [node for node in source.body if getattr(node, "name", None) in {"query_point_empty", "queue_input"}]
    node = ast.ClassDef(name="HttpReceiver", bases=[ast.Attribute(value=ast.Name(id="QtCore", ctx=ast.Load()),
                        attr="QObject", ctx=ast.Load())], keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = dict(QtCore=QtCore, threading=threading)
    exec(compile(module, "websocket_server.py", "exec"), namespace)
    return namespace["HttpReceiver"]()


class HttpMarshallingTests(unittest.TestCase):
    def test_input_and_hit_probe_from_plain_python_thread(self):
        receiver = load_http_receiver()
        calls, result = [], []
        receiver._point_is_empty = lambda x, y: calls.append(("probe", QtCore.QThread.isMainThread(), x, y)) or False
        receiver._handle_input = lambda client, data: calls.append(("input", QtCore.QThread.isMainThread(), data))

        def request():
            receiver.queue_input({"x": 42})
            result.append(receiver.query_point_empty(10, 20))

        worker = threading.Thread(target=request)
        worker.start()
        pump_until(lambda: bool(result))
        worker.join()
        self.assertEqual(result, [False])
        self.assertEqual(calls, [("input", True, {"x": 42}), ("probe", True, 10, 20)])
        receiver.deleteLater()
        flush_deletes()

    def test_input_is_cancelled_when_session_is_destroyed(self):
        receiver = load_http_receiver()
        calls = []
        receiver._handle_input = lambda client, data: calls.append(data)
        worker = threading.Thread(target=lambda: receiver.queue_input({"x": 42}))
        worker.start()
        worker.join()
        receiver.deleteLater()
        flush_deletes(receiver)
        self.assertEqual(calls, [])


class Colors:
    def actionBackgroundColor(self):
        return "#202020"

    def Pens(self):
        return {i: QtGui.QPen(QtGui.QColor("red")) for i in range(9)}

    def PenColors(self):
        return {i: "#ff0000" for i in range(9)}


def container(widgets, font=None):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    for child in widgets:
        layout.addWidget(QtWidgets.QLabel(child) if isinstance(child, str) else child)
    return widget, layout


class TimelineTests(unittest.TestCase):
    def test_sampling_and_painting_use_owned_gui_timers(self):
        reads = []
        state = NS(getAxisValues=lambda device, axis: reads.append(QtCore.QThread.isMainThread()) or NS(actual=0.5))
        namespace = dict(QtWidgets=QtWidgets, QtCore=QtCore, QtGui=QtGui,
                         QWidget=QtWidgets.QWidget, Color=Colors, Shiboken=Shiboken, time=time,
                         getVContainer=container, getHContainer=container,
                         gremlin=NS(event_handler=NS(AxisState=lambda: state),
                                    util=NS(clear_layout=lambda layout: None)))
        exec(compile(ast.Module(body=definitions("gremlin/ui/ui_common.py", {
            "AxesTimeline", "TimeLinePlotWidget",
        }), type_ignores=[]), "ui_common.py", "exec"), namespace)
        device = NS(is_virtual=False, name="Test device", device_guid="test", axis_count=1,
                    axis_sequence_to_input_id=lambda i: i + 1, get_axis_name=lambda i: "X",
                    getAxisInputIdList=lambda: [1])
        before = set(threading.enumerate())
        viewer = namespace["AxesTimeline"](device)
        pump_until(lambda: len(reads) >= 3)
        self.assertTrue(all(reads))
        self.assertEqual(viewer.plot_widget._series[1], [-0.5, -0.5])
        self.assertEqual(set(threading.enumerate()), before)
        timers = viewer.findChildren(QtCore.QTimer)
        self.assertEqual(len(timers), 2)
        self.assertTrue(all(timer.isActive() for timer in timers))
        viewer.unhook()
        viewer.unhook()
        self.assertTrue(all(not timer.isActive() for timer in timers))
        # Destruction also stops the timers if callers forget to unhook.
        for timer in timers:
            timer.start()
        viewer.deleteLater()
        flush_deletes()
        self.assertTrue(all(not Shiboken.isValid(timer) for timer in timers))
        viewer.unhook()


if __name__ == "__main__":
    unittest.main()
