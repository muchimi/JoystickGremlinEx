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
        """
        current_time = time.time()

        # 1. Temporal Throttle: Drop events arriving too fast (e.g., thousands of times/sec)
        if current_time - self.last_process_time < self.min_interval:
            return None

        self.last_process_time = current_time

        # Initialize base value if this is the first data point
        if self.smoothed_value is None:
            self.smoothed_value = raw_value
            self.last_sent_value = raw_value
            return raw_value

        # 2. Math Filter: Low-Pass Exponential Moving Average (EMA)
        # Smooths out extreme micro-spikes/jitter immediately
        self.smoothed_value = (self.alpha * raw_value) + ((1.0 - self.alpha) * self.smoothed_value)

        # 3. Delta Variance Filter: Block propagation if the change is negligible
        delta = abs(self.smoothed_value - self.last_sent_value)
        if delta >= self.threshold:
            self.last_sent_value = self.smoothed_value
            return self.smoothed_value

        return None
