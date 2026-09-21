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

import math
from typing import Callable


class EMAFilter:
    __slots__ = (
        "alpha",
        "inverse_alpha",
        "threshold",
        "large_jump_threshold",
        "min_interval_ns",
        "settle_interval_ns",
        "settle_tolerance",
        "input_min",
        "input_max",
        "clamp_input",
        "read_value_callback",
        "smoothed_value",
        "last_raw_value",
        "last_sent_value",
        "last_input_time_ns",
        "last_process_time_ns",
    )

    def __init__(
        self,
        read_value_callback: Callable[[], float],
        smoothing_factor=0.25,
        change_threshold=0.01,
        min_interval_ms=10,
        settle_interval_ms=25,
        settle_tolerance=1.0,
        input_min=-32768.0,
        input_max=32767.0,
        large_jump_ratio=0.015,
        clamp_input=False,

    ):
        """
        Initializes the axis input filter.

        :param read_value_callback: Callback that returns the axis's current
            raw value. The callback takes no arguments and is invoked by
            ``check_settling()`` after the input has been quiet for the
            configured settling interval.
        :param smoothing_factor: EMA smoothing coefficient in the range
            ``(0.0, 1.0]``. Lower values provide more smoothing, while higher
            values provide faster response. A value of ``1.0`` disables
            smoothing.
        :param change_threshold: Minimum output change required to emit an
            ordinary event. Values from ``0.0`` through ``1.0`` represent a
            fraction of the full axis range. Values greater than ``1.0``
            represent raw axis units.
        :param min_interval_ms: Minimum time in milliseconds between ordinary
            output events. Large jumps and final settling events bypass this
            rate limit.
        :param settle_interval_ms: Amount of time in milliseconds without a
            new input event before ``check_settling()`` verifies the current
            physical axis value.
        :param settle_tolerance: Maximum raw difference between the callback
            value and the last received raw value for the axis to be considered
            stationary.
        :param input_min: Minimum expected raw axis value.
        :param input_max: Maximum expected raw axis value. Must be greater
            than ``input_min``.
        :param large_jump_ratio: Fraction of the full axis range considered
            a large jump. Large jumps bypass smoothing and rate limiting.
            Set to ``0.0`` to disable large-jump detection.
        :param clamp_input: If ``True``, clamp raw values to ``input_min`` and
            ``input_max``.
        :raises TypeError: If ``read_value_callback`` is not callable.
        :raises ValueError: If a numeric parameter is invalid.
        """
        if not callable(read_value_callback):
            raise TypeError("read_value_callback must be callable")

        alpha = float(smoothing_factor)
        change_threshold = float(change_threshold)
        min_interval_ms = float(min_interval_ms)
        settle_interval_ms = float(settle_interval_ms)
        settle_tolerance = float(settle_tolerance)
        input_min = float(input_min)
        input_max = float(input_max)
        large_jump_ratio = float(large_jump_ratio)

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

        if settle_interval_ms < 0.0:
            raise ValueError(
                "settle_interval_ms cannot be negative"
            )

        if settle_tolerance < 0.0:
            raise ValueError(
                "settle_tolerance cannot be negative"
            )

        if not 0.0 <= large_jump_ratio <= 1.0:
            raise ValueError(
                "large_jump_ratio must be between 0 and 1"
            )

        input_range = input_max - input_min

        self.alpha = alpha
        self.inverse_alpha = 1.0 - alpha

        self.threshold = (
            change_threshold * input_range
            if change_threshold <= 1.0
            else change_threshold
        )

        self.large_jump_threshold = large_jump_ratio * input_range
        self.min_interval_ns = int(min_interval_ms * 1_000_000)
        self.settle_interval_ns = int(settle_interval_ms * 1_000_000)
        self.settle_tolerance = settle_tolerance

        self.input_min = input_min
        self.input_max = input_max
        self.clamp_input = bool(clamp_input)
        self.read_value_callback = read_value_callback

        self.smoothed_value = None
        self.last_raw_value = 0.0
        self.last_sent_value = 0.0
        self.last_input_time_ns = 0
        self.last_process_time_ns = 0

    def process_input(self, raw_value):
        """
        Processes one raw axis sample.

        :param raw_value: Current raw axis value.
        :return: Filtered axis value when the event should be propagated;
            otherwise, ``None``.
        :raises ValueError: If ``raw_value`` is not finite.
        """
        value = self._prepare_value(raw_value)
        now_ns = time.perf_counter_ns()

        smoothed = self.smoothed_value
        self.last_input_time_ns = now_ns

        if smoothed is None:
            self.smoothed_value = value
            self.last_raw_value = value
            self.last_sent_value = value
            self.last_process_time_ns = now_ns
            return value

        last_raw = self.last_raw_value
        last_sent = self.last_sent_value
        jump_threshold = self.large_jump_threshold

        self.last_raw_value = value

        # Zero disables large-jump handling instead of matching every sample.
        if (
            jump_threshold > 0.0
            and (
                abs(value - last_raw) >= jump_threshold
                or abs(value - last_sent) >= jump_threshold
            )
        ):
            self.smoothed_value = value
            self.last_sent_value = value
            self.last_process_time_ns = now_ns
            return value

        smoothed = (
            self.alpha * value
            + self.inverse_alpha * smoothed
        )
        self.smoothed_value = smoothed

        # Using <= prevents unchanged values from passing when the configured
        # threshold is zero.
        if abs(smoothed - last_sent) <= self.threshold:
            return None

        if now_ns - self.last_process_time_ns < self.min_interval_ns:
            return None

        self.last_sent_value = smoothed
        self.last_process_time_ns = now_ns
        return smoothed

    def check_settling(self):
        """
        Checks whether a quiet axis has reached its final physical position.

        This method should be called periodically by the input loop even when
        no new axis events have been received.

        :return: Exact current raw axis value when final settling occurs;
            otherwise, ``None``.
        :raises ValueError: If the callback returns a non-finite value.
        """
        if self.smoothed_value is None:
            return None

        now_ns = time.perf_counter_ns()

        # The input has not been quiet long enough to test for settling.
        if now_ns - self.last_input_time_ns < self.settle_interval_ns:
            return None

        value = self._prepare_value(self.read_value_callback())

        # The callback found movement that was not delivered as an event.
        # Process it as a new sample and restart the settling interval.
        if abs(value - self.last_raw_value) > self.settle_tolerance:
            return self.process_input(value)

        # The exact final position was already emitted.
        if value == self.last_sent_value:
            return None

        # The physical value remained stable during the quiet interval.
        # Snap all state to the exact value and emit it without rate limiting.
        self.smoothed_value = value
        self.last_raw_value = value
        self.last_sent_value = value
        self.last_input_time_ns = now_ns
        self.last_process_time_ns = now_ns
        return value

    def reset(self, raw_value=None):
        """
        Resets or initializes the filter state.

        :param raw_value: Optional initial axis value. If ``None``, the next
            input sample initializes the filter and is emitted immediately.
            If supplied, the filter initializes to this value without emitting
            an event.
        :return: ``None``.
        """
        if raw_value is None:
            self.smoothed_value = None
            self.last_raw_value = 0.0
            self.last_sent_value = 0.0
            self.last_input_time_ns = 0
            self.last_process_time_ns = 0
            return

        value = self._prepare_value(raw_value)
        now_ns = time.perf_counter_ns()

        self.smoothed_value = value
        self.last_raw_value = value
        self.last_sent_value = value
        self.last_input_time_ns = now_ns
        self.last_process_time_ns = now_ns

    def _prepare_value(self, raw_value):
        """
        Converts and validates an axis value.

        :param raw_value: Value to convert and validate.
        :return: Validated and optionally clamped floating-point value.
        :raises ValueError: If the value is NaN or infinite.
        """
        value = float(raw_value)

        if not math.isfinite(value):
            raise ValueError("axis value must be finite")

        if self.clamp_input:
            if value < self.input_min:
                value = self.input_min
            elif value > self.input_max:
                value = self.input_max

        return value