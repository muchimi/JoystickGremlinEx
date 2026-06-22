# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.	If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations  # deprecated with python 3.14+
import threading
import logging
from PySide6 import QtCore

syslog = logging.getLogger("system")


class AbortableThread(threading.Thread, QtCore.QObject):
    """killable thread"""

    def __init__(self, *args, **kwargs):

        QtCore.QObject.__init__(self)
        threading.Thread.__init__(self, *args, **kwargs)

        if "eh" in kwargs:
            eh = kwargs["eh"]
        else:
            import gremlin.event_handler

            eh = gremlin.event_handler.EventListener()

        eh.shutdown.connect(self.stop)

        # self._stop_event = threading.Event()
        self._shutdown_requested = False

    def reset(self):
        """reset the thread"""
        self._shutdown_requested = False

    def stop(self):
        # self._stop_event.set()
        self._shutdown_requested = True

    def stopped(self):
        return self._shutdown_requested
        # return self._stop_event.is_set()


class AbortableThreadX(threading.Thread):
    """killable thread"""

    def __init__(self, target=None, eh=None):

        super().__init__(target=target)

        if not eh:
            import gremlin.event_handler

            eh = gremlin.event_handler.EventListener()

        eh.shutdown.connect(self.stop)

        # self._stop_event = threading.Event()
        self._shutdown_requested = False

    def reset(self):
        """reset the thread"""
        self._shutdown_requested = False

    def stop(self):
        # self._stop_event.set()
        self._shutdown_requested = True

    def stopped(self):
        return self._shutdown_requested
        # return self._stop_event.is_set()


def TimerEx(*args, **kwargs):
    """Global function for Timer"""
    return _TimerEx(*args, **kwargs)


class _TimerEx:
    def __init__(self, interval, target, args=None, kwargs=None):
        self._interval = interval
        self._callback = target
        self._args = args if args is not None else []
        self._kwargs = kwargs if kwargs is not None else {}
        self._timer = None
        self._is_running = False
        self._one_shot = False
        self._name = None

    def _run(self):
        self._is_running = False
        self.start()
        syslog.info(f"timer trigger: {self._name if self._name else ''}")
        self._callback(*self._args, **self._kwargs)

        if self._one_shot:
            self._timer.cancel()

    def setName(self, name: str):
        self._name = name

    def start(self, oneshot=False):
        """starts the timer, if oneshot is set, the timer runs once and stops when it lapses, if not set, runs until canceled"""
        if not self._is_running:
            self._timer = threading.Timer(self._interval, self._run)
            self._is_running = True
            self._one_shot = oneshot
            self._timer.start()
            syslog.info(f"timer start {self._name if self._name else ''}")

    def isRunning(self) -> bool:
        return self._is_running

    def cancel(self):
        if self._is_running:
            self._timer.cancel()
            self._is_running = False
            syslog.info(f"timer cancel {self._name if self._name else ''}")

    def reset(self, oneshot=False):
        syslog.info(f"timer reset {self._name if self._name else ''}")
        self.cancel()
        self.start(oneshot)


# class Lock():
#     ''' handles simple lock mechanism to work around QT threading problems with python thread locks '''

#     def __init__(self):
#         self._lock = False


#     def acquire_lock(self, block = True, timeout = 0) -> bool:

#         if block:
#             if timeout > 0:
#                 lapsed = time.time() + timeout
#                 while self._lock and lapsed < time.time():
#                     time.sleep(0.01)
#         if self._lock:
#             # timed out
#             return False

#         if not self._lock:
#             self._lock = True
#             return True
#         return False


#     def release_lock(self):
#         self._lock = False

#     def locked(self) -> bool:
#         return self._lock
