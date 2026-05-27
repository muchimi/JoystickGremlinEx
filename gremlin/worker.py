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
# import gremlin.event_handler
# import gremlin.shared_state


syslog = logging.getLogger("system")

class WorkerSignals(QObject):
    progress = QtCore.Signal(int)
    result = QtCore.Signal(str)
    finished = QtCore.Signal()

@SingletonDecorator
class WorkManager(QObject):
    """handles UI wait cursor management when work is submitted - an hourglass is displayed while the work is completed
    multiple tasks can be submitted

    """

    def __init__(self):
        super().__init__()
        self._cursor_push = 0
        self._cursor_timer = None  # timer to display hourglass
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
        """executes work and displays an hourglass cursor while doing it

        If a callback is specified, a worker thread will be started and called so the UI thread remains responsive.

        :param immediate: if true, sets the cursor immediately instead of waiting for a short delay (provided it's not displayed already) - if false, the cursor pops up 1 second after
        :param callback: optional, the function to call while the cursor is displayed - this function should take in (*args, **kwargs) as parameters
        :param complete_callback: optional, the function to call when the work is completed - this function should take in (*args, **kwargs) as parameters

        :param args: positional arguments for the callback
        :param kwargs: keyword arguments for the callback
        """
        


        
        self.pushCursor()  # display hourglass

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
            syslog.info(f"starting task: [{callback.__name__}]")
            self._threadpool.start(worker)


    def _handle_worker_finish(self):
        self.popCursor()
        syslog.info("worker finished")


    def pushCursor(self, immediate=True):
        """displays an hourglass cursor"""

        if self._cursor_push == 0:
            # syslog.info("PUSH CURSOR: show cursor timer [immediate]")

            if immediate:
                # show the wait cursor
                InvokeUiMethod(self._pushCursor_ui)  # ensure on UI thread
                QtWidgets.QApplication.processEvents()
            else:
                # syslog.info("PUSH CURSOR: show cursor timer [delay]")
                if self._cursor_timer:
                    self._cursor_timer.cancel()
                self._cursor_timer = threading.Timer(1.0, self._cursor_show_hourglass)
                self._cursor_timer.start()

        self._cursor_push += 1

        # allow other processing to happen
        syslog.info(f"PUSH CURSOR: [{self._cursor_push}]")

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

        self._cursor_timer = None
        # syslog.info(f"PUSH CURSOR: [{_cursor_push}]")
        if not self._cursor_wait:
            self._cursor_wait = True

            if not self._qt_wait_cursor:
                # create a wait cursor
                self._qt_wait_cursor = QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor)

            syslog.info("set hourglass")
            win32gui.LoadCursor(None, win32con.IDC_WAIT)
            QtWidgets.QApplication.setOverrideCursor(self._qt_wait_cursor)
            QtWidgets.QApplication.processEvents()

            # cursor = QtWidgets.QApplication.overrideCursor()
            # while cursor != _qt_wait_cursor:
            #     time.sleep(0)
            #     QtWidgets.QApplication.processEvents()
            #     cursor = QtWidgets.QApplication.overrideCursor()

            syslog.info("show hourglass")

    def popCursor(self, reset=False):
        """decreases the wait cursor stack"""
        syslog.info(f"POP CURSOR: [{self._cursor_push}]")
        if self._cursor_push > 0:
            self._cursor_push -= 1
        if self._cursor_push == 0 or reset:
            if self._cursor_timer is not None:
                self._cursor_timer.cancel()
                self._cursor_timer = None
            if self._cursor_wait or reset:
                InvokeUiMethod(self._popCursor_ui, reset)
                time.sleep(0.1)  # allow other processing to occur

    def _popCursor_ui(self, force: bool = False):
        """restores the normal cursor"""

        if self._cursor_wait or force:
            self._cursor_wait = False
            # syslog.info("PUSH CURSOR: change to normal cursor")
            # win32gui.LoadCursor(None, win32con.IDC_ARROW)

            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QApplication.processEvents()
            syslog.info("hide hourglass")

    def isWaitCursor(self) -> bool:
        """true if the cursor is an hourglass"""
        return self._cursor_push > 0

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
        self._cursor_timer = None
        if not self._cursor_wait:
            # syslog.info("PUSH CURSOR: show cursor timer")
            InvokeUiMethod(self._pushCursor_ui)  # ensure on UI thread
            time.sleep(0.1)

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


# class WorkRunner(QObject):
#     def __init__(self):
#         super().__init__()
#         el = gremlin.event_handler.EventListener()
#         el.shutdown.connect(self._handle_shutdown)
#         self._running = True

#     def _handle_shutdown(self):
#         self._running = False


#     @Slot()
#     def runner(self):
#         # start the worker thread
#         syslog.info("worker monitor start")

#         while self._running:
#             if self._completed_callback_map:
#                 remove_task = None
#                 task: Thread
#                 for task in self._completed_callback_map:
#                     if not task.is_alive() and task.native_id:
#                         syslog.info(f"task completed: [{task.name}]")
#                         completed_callback, args, kwargs = self._completed_callback_map[
#                             task
#                         ]
#                         del self._completed_callback_map[task]
#                         if completed_callback:
#                             # call the completion callback
#                             completed_callback(args, kwargs)
#                         remove_task = task
#                         break

#                 if remove_task:
#                     del self._completed_callback_map[remove_task]

#             QThread.sleep(0)  # do other work

#         # restore the cursor
#         self.popCursor()

#         syslog.info("worker thread(s) completed")
#         self._cursor_thread_monitor = None
#         self._running = False


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
       
        QThread.currentThread().setObjectName(self._name)
        syslog.info(f"executing task: [{self._name}]")
        result = self._callback(self._args)
        syslog.info(f"callback complete: [{self._name}]")
        if self._completed_callback:
            self._completed_callback(result, self._args)
        self.signals.finished.emit()
        
