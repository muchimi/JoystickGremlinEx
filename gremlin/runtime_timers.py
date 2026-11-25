# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""Timers owned by one profile activation.
The timers are associated with a specific profile activation and are automatically canceled when the activation ends.
These timers should be used by actions that fire timers like double tap, tempo/tempoEx and other time-based events.
"""

import threading


class RuntimeTimers:
    def __init__(self):
        self._lock = threading.Lock()
        self._timers = set()
        self._callback = threading.local()
        self.activation = None

    @property
    def active(self):
        activation = self.activation
        return activation is not None and getattr(self._callback, "activation", activation) is activation

    def start(self):
        self.stop()
        with self._lock:
            self.activation = object()

    def stop(self):
        with self._lock:
            self.activation = None
            for timer in self._timers:
                timer.cancel()
            self._timers.clear()

    def cancel(self, timer):
        if timer is None:
            return
        with self._lock:
            self._timers.discard(timer)
            timer.cancel()

    def schedule(self, delay, callback):
        with self._lock:
            activation = self.activation
            if not self.active:
                return None

            def run():
                with self._lock:
                    pending = timer in self._timers and self.activation is activation
                    self._timers.discard(timer)
                if pending:
                    self._callback.activation = activation
                    try:
                        if self.active:
                            callback()
                    finally:
                        del self._callback.activation

            timer = threading.Timer(delay, run)
            timer.daemon = True
            self._timers.add(timer)
            timer.start()
            return timer
