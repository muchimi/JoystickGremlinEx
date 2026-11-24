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


"""Pulse virtual axes without overwriting a newer output."""

import threading

# Output providers hold this during a write and its history update, so pulse
# restoration can compare the write identity and restore in one operation.
output_lock = threading.RLock()


class AxisBump:
    _active = {}

    @classmethod
    def start(cls, key, read_output, write_output, fallback, offset, delay_ms):
        """Pulse away from the last intended position and schedule its restoration.

        A provider returns a fresh one-element tuple for each successful write.
        Identity distinguishes a new write of the same value from our own pulse.
        """
        with output_lock:
            previous = cls._active.get(key)
            if previous is not None:
                previous.finish()

            last_write = read_output()
            value = last_write[0] if last_write is not None else None
            if value is None:
                value = fallback()
            if value is None:
                return None

            value = max(-1.0, min(1.0, value))
            bumped = value - offset if value >= 0 else value + offset
            write_output(bumped)
            pulse_write = read_output()
            if pulse_write is last_write:
                return None

            bump = cls(key, read_output, write_output, value, pulse_write, delay_ms)
            cls._active[key] = bump
            bump._timer.start()
            return bump

    def __init__(self, key, read_output, write_output, value, pulse_write, delay_ms):
        self._key = key
        self._read_output = read_output
        self._write_output = write_output
        self._value = value
        self._pulse_write = pulse_write
        self._timer = threading.Timer(delay_ms / 1000, self.finish)
        self._timer.daemon = True

    def finish(self):
        """Restore the axis if the pulse still owns its last write."""
        with output_lock:
            if self._active.get(self._key) is not self:
                return
            self._timer.cancel()
            del self._active[self._key]
            if self._read_output() is self._pulse_write:
                self._write_output(self._value)
