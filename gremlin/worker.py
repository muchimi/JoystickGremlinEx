# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - GremlinEx is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import functools
import threading

# from concurrent.futures import ThreadPoolExecutor, Future
from threading import Thread
import time
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QThread, QObject, Slot, QRunnable, QThreadPool

import win32con
import win32gui

from gremlin.singleton_decorator import SingletonDecorator
from gremlin.util import InvokeUiMethod
import gremlin.config
import gremlin.util
# import gremlin.event_handler
# import gremlin.shared_state

syslog = logging.getLogger("system")

class WorkerSignals(QObject):
    progress = QtCore.Signal(int)
    result = QtCore.Signal(str)
    finished = QtCore.Signal()


class _CursorReleaseEvent(QtCore.QEvent):
    EVENT_TYPE = QtCore.QEvent.Type(QtCore.QEvent.registerEventType())

    def __init__(self, generation, turns=1, activity=0):
        super().__init__(self.EVENT_TYPE)
        self.generation = generation
        self.turns = turns
        self.activity = activity


def with_wait_cursor(method):
    """Keep the wait cursor through a GUI update and its deferred Qt events."""
    @functools.wraps(method)
    def wrapped(*args, **kwargs):
        manager = WorkManager()
        manager.pushCursor()
        try:
            return method(*args, **kwargs)
        finally:
            manager.popCursor()
    return wrapped


@SingletonDecorator
class WorkManager(QObject):
    """handles UI wait cursor management when work is submitted - an hourglass is displayed while the work is completed
    multiple tasks can be submitted

    """

    # Only the final Qt settling phase is bounded; active work holds are not.
    _CURSOR_SETTLE_SECONDS = 0.1

    def __init__(self):
        super().__init__()
        self._cursor_push = 0
        self._cursor_timer = QtCore.QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.timeout.connect(self._cursor_show_hourglass)
        self._cursor_generation = 0
        self._cursor_activity = 0
        self._cursor_release_pending = False
        self._cursor_release_deadline = 0.0
        self._cursor_level = []
        self._cursor_wait = False
        self._qt_wait_cursor: QtGui.QCursor = None
        self._monitor: QThread = None  # monitoring thread
        self._threadpool = QThreadPool.globalInstance()


    def submit(
        self,
        callback: Callable = None,
        complete_callback: Callable = None,
        args = None,
    ):
        """ submits a task to the worker queue and displays an hourglass while it's running
        :param immediate: if true, sets the cursor immediately instead of waiting for a short delay (provided it's not displayed already) - if false, the cursor pops up 1 second after
        :param callback: optional, the function to call while the cursor is displayed - this function should take in (*args, **kwargs) as parameters
        :param complete_callback: optional, the function to call when the work is completed - this function should take in (*args, **kwargs) as parameters

        :param args: positional arguments for the callback
        :param kwargs: keyword arguments for the callback
        """

        # route on UI thread as the wait cursor is involved and won't display correctly unless on UI thread
        gremlin.util.InvokeUiMethod(self._submit_ui, (callback, complete_callback, args))


    def _submit_ui(self, args):
        """executes work and displays an hourglass cursor while doing it

        If a callback is specified, a worker thread will be started and called so the UI thread remains responsive.

        """

        callback, complete_callback, args = args


        self.pushCursor()  # each submitted task owns one cursor hold

        if callback is not None:
            # start a worker thread to run the work
            assert isinstance(callback, Callable), "invalid callback"
            assert (
                isinstance(complete_callback, Callable)
                if complete_callback is not None
                else True
            ), "completed callback must be a callable"

            worker = WorkTask(callback, args = args)
            worker.setCompletedCallback(complete_callback)
            worker.signals.finished.connect(self._handle_worker_finish)
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(3)
            if verbose:
                syslog.info(f"starting worker: [{callback.__name__}]")
            self._threadpool.start(worker)
        else:
            self.popCursor()


    def _handle_worker_finish(self):
        self.popCursor()

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(3)
        if verbose:
            syslog.info("worker finished")


    def pushCursor(self, immediate=True):
        """displays an hourglass cursor"""
        InvokeUiMethod(self._push_cursor_request_ui, immediate)

    def _push_cursor_request_ui(self, immediate=True):
        self._cursor_push += 1
        self._cursor_generation += 1
        self._cursor_release_pending = False
        if immediate:
            self._pushCursor_ui()
        elif not self._cursor_wait and not self._cursor_timer.isActive():
            self._cursor_timer.start(1000)

    def _pushcursor_monitor_runner(self):
        """runs while the worker thread is going to monitor it"""

        # start the worker thread
        syslog.info("worker monitor start")

        while self._running:
            if self._completed_callback_map:
                remove_task = None
                task: Thread
                for task in self._completed_callback_map:
                    if not task.is_alive() and task.native_id:
                        syslog.info(f"task completed: [{task.name}]")
                        completed_callback, args, kwargs = self._completed_callback_map[
                            task
                        ]
                        del self._completed_callback_map[task]
                        if completed_callback:
                            # call the completion callback
                            completed_callback(args, kwargs)
                        remove_task = task
                        break

                if remove_task:
                    del self._completed_callback_map[remove_task]

            time.sleep(0)  # do other work

        # restore the cursor
        self.popCursor()

        syslog.info("worker thread(s) completed")
        self._cursor_thread_monitor = None
        self._running = False

    def _pushCursor_ui(self):
        self._cursor_timer.stop()
        # syslog.info(f"PUSH CURSOR: [{_cursor_push}]")
        if not self._cursor_wait:
            self._cursor_wait = True

            if not self._qt_wait_cursor:
                # create a wait cursor
                self._qt_wait_cursor = QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor)

            # syslog.info("set hourglass")
            # win32gui.LoadCursor(None, win32con.IDC_WAIT)
            QtWidgets.QApplication.setOverrideCursor(self._qt_wait_cursor)
            QtWidgets.QApplication.instance().installEventFilter(self)

            # cursor = QtWidgets.QApplication.overrideCursor()
            # while cursor != _qt_wait_cursor:
            #     time.sleep(0)
            #     QtWidgets.QApplication.processEvents()
            #     cursor = QtWidgets.QApplication.overrideCursor()

            # syslog.info("show hourglass")

    def popCursor(self, reset=False):
        """decreases the wait cursor stack"""
        InvokeUiMethod(self._pop_cursor_request_ui, reset)

    def _pop_cursor_request_ui(self, reset=False):
        if self._cursor_push > 0:
            self._cursor_push -= 1
        if reset:
            self._cursor_generation += 1
            self._cursor_release_pending = False
            self._cursor_timer.stop()
            self._popCursor_ui(True)
        elif self._cursor_push == 0:
            self._cursor_timer.stop()
            if self._cursor_wait and not self._cursor_release_pending:
                self._cursor_release_pending = True
                self._cursor_release_deadline = time.monotonic() + self._CURSOR_SETTLE_SECONDS
                self._post_cursor_release(self._cursor_generation)

    def _post_cursor_release(self, generation, turns=1):
        # Layout/update requests can be posted by queued completion callbacks.
        # Low-priority events yield to that work; a second turn also allows
        # requests posted by the first batch to reach Qt before restoring.
        QtCore.QCoreApplication.postEvent(
            self, _CursorReleaseEvent(generation, turns, self._cursor_activity),
            QtCore.Qt.EventPriority.LowEventPriority.value,
        )

    def event(self, event):
        if event.type() == _CursorReleaseEvent.EVENT_TYPE:
            if self._cursor_release_pending and event.generation == self._cursor_generation and self._cursor_push == 0:
                if event.activity != self._cursor_activity and time.monotonic() < self._cursor_release_deadline:
                    self._post_cursor_release(event.generation)
                elif event.turns:
                    self._post_cursor_release(event.generation, event.turns - 1)
                else:
                    self._cursor_release_pending = False
                    self._popCursor_ui()
            return True
        return super().event(event)

    def eventFilter(self, watched, event):
        # Qt can post further layout/polish work while handling an earlier
        # batch. Extend the release barrier briefly, but background layouts must
        # not keep completed work busy forever. Paint events do not extend it.
        if event.type() in (QtCore.QEvent.Type.LayoutRequest, QtCore.QEvent.Type.PolishRequest):
            self._cursor_activity += 1
        return False

    def _popCursor_ui(self, force: bool = False):
        """restores the normal cursor"""

        if self._cursor_wait or force:
            self._cursor_wait = False
            # syslog.info("PUSH CURSOR: change to normal cursor")
            # win32gui.LoadCursor(None, win32con.IDC_ARROW)

            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QApplication.instance().removeEventFilter(self)
            # syslog.info("hide hourglass")

    def isWaitCursor(self) -> bool:
        """true if the cursor is an hourglass"""
        return self._cursor_wait

    def pushCursorLevel(self, pop=True):
        """saves the cursor level"""
        self._cursor_level.append(self._cursor_push)
        if pop:
            self.popCursor(True)
        time.sleep(0.01)  # allow other processing to happen

    def popCursorLevel(self):
        """restores the last saved cursor level"""

        if self._cursor_level:
            self._cursor_push = self._cursor_level.pop()
            if self._cursor_push > 0:
                InvokeUiMethod(self._pushCursor_ui)

        time.sleep(0.01)  # allow other processing to happen

    def _cursor_show_hourglass(self):
        if self._cursor_push > 0:
            self._pushCursor_ui()

    def popCursorTemporary_ui(self, pop=True):
        """restore cursor temporarily without changing the stack - use for dialog boxes/prompt

        :param pop: when true, restores the arrow, when false, shows the wait cursor if it was displayed

        """

        if self._cursor_push > 0:
            if pop:
                self._popCursor_ui()
            else:
                self._pushCursor_ui()

        time.sleep(0.01)  # allow other processing to happen

    def popCursorTemporary(self, pop=True):
        InvokeUiMethod(self.popCursorTemporary_ui, pop)
        time.sleep(0.01)  # allow other processing to happen

    def isCursorActive(self):
        """true if the cursor stack is not empty"""
        return self._cursor_push > 0




class WorkTask(QRunnable):

    def __init__(self, callback: Callable, args = None):
        super().__init__()
        self.signals = WorkerSignals()
        self._callback = callback
        self._args = args
        self._completed_callback = None
        self._name = f"Worker: {self._callback.__name__}"

    def setCompletedCallback(self, callback : Callable):
        self._completed_callback = callback

    def setName(self, value: str):
        self._name = value




    @Slot()
    def run(self):
        import gremlin.config
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(3)
        QThread.currentThread().setObjectName(self._name)
        if verbose:
            syslog.info(f"executing task: [{self._name}]")
        try:
            result = self._callback(self._args)
            if verbose:
                syslog.info(f"callback complete: [{self._name}]")
            if self._completed_callback:
                self._completed_callback(result, self._args)
            if verbose:
                syslog.info(f"work task [{self._name}] finished")
        finally:
            self.signals.finished.emit()

