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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import time


class EMAFilter:
    # ~1.5% of a ±32767 DirectInput axis — large enough to catch flick-release
    # to center without defeating the spam throttle for micro-jitter.
    _LARGE_JUMP_RAW = 500.0

    def __init__(self, smoothing_factor=0.25, change_threshold=0.01, min_interval_ms=10):
        """
        Optimized filter for rapid stream axis data.

        :param smoothing_factor: Alpha for EMA (0.0 to 1.0). Lower = smoother, higher = faster response.
        :param change_threshold: Minimal physical difference to propagate an action (deadzone).
        :param min_interval_ms: Hard rate-limiter to prevent excessive high-CPU loops.
        """
        self.alpha = smoothing_factor
        self.threshold = change_threshold
        self.min_interval = min_interval_ms / 1000.0  # Convert to seconds

        self.smoothed_value = None
        self.last_sent_value = None
        self.last_process_time = 0.0

    def process_input(self, raw_value):
        """
        Processes an incoming axis data point.
        Returns the filtered value if it represents a meaningful event, otherwise returns None.

        Callers must treat only ``None`` as filtered-out — never truthiness —
        because a valid center sample is ``0``.
        """
        current_time = time.time()
        raw_value = float(raw_value)

        # Initialize base value if this is the first data point
        if self.smoothed_value is None:
            self.smoothed_value = raw_value
            self.last_sent_value = raw_value
            self.last_process_time = current_time
            return raw_value

        # Always fold the sample into the smoother so throttled centers are not lost.
        self.smoothed_value = (self.alpha * raw_value) + ((1.0 - self.alpha) * self.smoothed_value)

        delta = abs(self.smoothed_value - self.last_sent_value)
        raw_delta = abs(raw_value - self.last_sent_value)
        # Rapid release often lands inside the throttle window; never drop a big jump.
        large_jump = raw_delta >= self._LARGE_JUMP_RAW

        throttled = (current_time - self.last_process_time) < self.min_interval
        if throttled and not large_jump:
            return None

        if delta < self.threshold and not large_jump:
            return None

        self.last_process_time = current_time
        # Prefer the latest raw sample on large jumps so return-to-center settles exactly.
        out = raw_value if large_jump else self.smoothed_value
        self.last_sent_value = out
        if large_jump:
            self.smoothed_value = out
        return out
