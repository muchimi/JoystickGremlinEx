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


# class EMAFilterV0:
#     # ~1.5% of a ±32767 DirectInput axis — large enough to catch flick-release
#     # to center without defeating the spam throttle for micro-jitter.
#     _LARGE_JUMP_RAW = 500.0

#     def __init__(self, smoothing_factor=0.25, change_threshold=0.01, min_interval_ms=10):
#         """
#         Optimized filter for rapid stream axis data.

#         :param smoothing_factor: Alpha for EMA (0.0 to 1.0). Lower = smoother, higher = faster response.
#         :param change_threshold: Minimal physical difference to propagate an action (deadzone).
#         :param min_interval_ms: Hard rate-limiter to prevent excessive high-CPU loops.
#         """
#         self.alpha = smoothing_factor
#         self.threshold = change_threshold
#         self.min_interval = min_interval_ms / 1000.0  # Convert to seconds

#         self.smoothed_value = None
#         self.last_sent_value = None
#         self.last_process_time = 0.0

#     def process_input(self, raw_value):
#         """
#         Processes an incoming axis data point.
#         Returns the filtered value if it represents a meaningful event, otherwise returns None.

#         Callers must treat only ``None`` as filtered-out — never truthiness —
#         because a valid center sample is ``0``.
#         """
#         current_time = time.time()
#         raw_value = float(raw_value)

#         # Initialize base value if this is the first data point
#         if self.smoothed_value is None:
#             self.smoothed_value = raw_value
#             self.last_sent_value = raw_value
#             self.last_process_time = current_time
#             return raw_value

#         # Always fold the sample into the smoother so throttled centers are not lost.
#         self.smoothed_value = (self.alpha * raw_value) + ((1.0 - self.alpha) * self.smoothed_value)

#         delta = abs(self.smoothed_value - self.last_sent_value)
#         raw_delta = abs(raw_value - self.last_sent_value)
#         # Rapid release often lands inside the throttle window; never drop a big jump.
#         large_jump = raw_delta >= self._LARGE_JUMP_RAW

#         throttled = (current_time - self.last_process_time) < self.min_interval
#         if throttled and not large_jump:
#             return None

#         if delta < self.threshold and not large_jump:
#             return None

#         self.last_process_time = current_time
#         # Prefer the latest raw sample on large jumps so return-to-center settles exactly.
#         out = raw_value if large_jump else self.smoothed_value
#         self.last_sent_value = out
#         if large_jump:
#             self.smoothed_value = out
#         return out





class EMAFilter:
    __slots__ = (
        "alpha",
        "inverse_alpha",
        "threshold",
        "large_jump_threshold",
        "min_interval_ns",
        "input_min",
        "input_max",
        "clamp_input",
        "smoothed_value",
        "last_raw_value",
        "last_sent_value",
        "last_process_time_ns",
    )

    def __init__(
        self,
        smoothing_factor=0.25,
        change_threshold=0.01,
        min_interval_ms=10,
        input_min=-32768.0,
        input_max=32767.0,
        large_jump_ratio=0.015,
        clamp_input=False,
    ):
        """
        Initializes the axis input filter.

        :param smoothing_factor:
            EMA smoothing coefficient in the range ``(0.0, 1.0]``.
            Lower values produce smoother but slower output. Higher values
            respond faster but allow more input noise through.

            Typical values are:

            - ``0.10``: Heavy smoothing.
            - ``0.25``: Balanced smoothing.
            - ``0.75``: Light smoothing.
            - ``1.00``: No smoothing.

        :param change_threshold:
            Minimum change required before a filtered value can be emitted.

            Values from ``0.0`` through ``1.0`` are interpreted as a fraction
            of the complete axis range. Values greater than ``1.0`` are
            interpreted as raw axis units.

            For a range of ``-32768`` through ``32767``:

            - ``0.001`` is approximately 66 raw units.
            - ``0.010`` is approximately 655 raw units.
            - ``500.0`` is exactly 500 raw units.

        :param min_interval_ms:
            Minimum number of milliseconds between ordinary emitted events.
            Large changes bypass this rate limit so rapid movements and
            return-to-center events are not delayed. A value of ``0`` disables
            interval-based throttling.

        :param input_min:
            Minimum expected raw axis value. This is used to calculate
            proportional thresholds and optionally clamp invalid values.

        :param input_max:
            Maximum expected raw axis value. This must be greater than
            ``input_min``.

        :param large_jump_ratio:
            Fraction of the complete axis range considered a large change.
            Large changes bypass both EMA smoothing and rate limiting.

            For a 65,535-unit DirectInput range:

            - ``0.005`` is approximately 328 raw units.
            - ``0.015`` is approximately 983 raw units.
            - ``0.050`` is approximately 3,277 raw units.

        :param clamp_input:
            When ``True``, values outside ``input_min`` and ``input_max`` are
            clamped to the configured range. Leave this disabled when the
            input API already guarantees the range to avoid extra comparisons
            for every event.

        :raises ValueError:
            If a parameter is outside its permitted range.
        """
        alpha = float(smoothing_factor)
        input_min = float(input_min)
        input_max = float(input_max)

        if not 0.0 < alpha <= 1.0:
            raise ValueError(
                "smoothing_factor must be in the range (0, 1]"
            )

        if input_max <= input_min:
            raise ValueError(
                "input_max must be greater than input_min"
            )

        if change_threshold < 0.0:
            raise ValueError(
                "change_threshold cannot be negative"
            )

        if min_interval_ms < 0.0:
            raise ValueError(
                "min_interval_ms cannot be negative"
            )

        if not 0.0 <= large_jump_ratio <= 1.0:
            raise ValueError(
                "large_jump_ratio must be between 0 and 1"
            )

        input_range = input_max - input_min

        self.alpha = alpha
        self.inverse_alpha = 1.0 - alpha

        self.threshold = (
            float(change_threshold) * input_range
            if change_threshold <= 1.0
            else float(change_threshold)
        )

        self.large_jump_threshold = (
            float(large_jump_ratio) * input_range
        )

        self.min_interval_ns = int(
            float(min_interval_ms) * 1_000_000
        )

        self.input_min = input_min
        self.input_max = input_max
        self.clamp_input = bool(clamp_input)

        self.smoothed_value = None
        self.last_raw_value = 0.0
        self.last_sent_value = 0.0
        self.last_process_time_ns = 0

    def process_input(self, raw_value):
        """
        Processes one raw axis sample.

        :param raw_value:
            Current raw axis position.

        :return:
            The filtered axis value when the event should be propagated.
            Returns ``None`` when the event is suppressed by the change
            threshold or rate limiter.

            Callers must explicitly test for ``None`` because ``0.0`` is a
            valid axis value.
        """
        value = float(raw_value)

        if self.clamp_input:
            if value < self.input_min:
                value = self.input_min
            elif value > self.input_max:
                value = self.input_max

        smoothed = self.smoothed_value

        if smoothed is None:
            now_ns = time.perf_counter_ns()

            self.smoothed_value = value
            self.last_raw_value = value
            self.last_sent_value = value
            self.last_process_time_ns = now_ns
            return value

        last_raw = self.last_raw_value
        last_sent = self.last_sent_value
        jump_threshold = self.large_jump_threshold

        self.last_raw_value = value

        # Bypass smoothing and throttling for large movements, reversals,
        # or rapid returns to center.
        if (
            abs(value - last_raw) >= jump_threshold
            or abs(value - last_sent) >= jump_threshold
        ):
            self.smoothed_value = value
            self.last_sent_value = value
            self.last_process_time_ns = time.perf_counter_ns()
            return value

        smoothed = (
            self.alpha * value
            + self.inverse_alpha * smoothed
        )
        self.smoothed_value = smoothed

        # Avoid reading the timer for insignificant input jitter.
        if abs(smoothed - last_sent) < self.threshold:
            return None

        now_ns = time.perf_counter_ns()

        if now_ns - self.last_process_time_ns < self.min_interval_ns:
            return None

        self.last_sent_value = smoothed
        self.last_process_time_ns = now_ns
        return smoothed

    def reset(self, raw_value=None):
        """
        Resets the filter state.

        :param raw_value:
            Optional initial axis value. If omitted, the next input sample
            initializes the filter and is emitted immediately. If supplied,
            the filter is initialized to that value without emitting an event.

        :return:
            None.
        """
        if raw_value is None:
            self.smoothed_value = None
            self.last_raw_value = 0.0
            self.last_sent_value = 0.0
            self.last_process_time_ns = 0
            return

        value = float(raw_value)

        if self.clamp_input:
            if value < self.input_min:
                value = self.input_min
            elif value > self.input_max:
                value = self.input_max

        self.smoothed_value = value
        self.last_raw_value = value
        self.last_sent_value = value
        self.last_process_time_ns = time.perf_counter_ns()