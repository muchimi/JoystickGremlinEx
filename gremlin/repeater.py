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


import threading
import time

from PySide6 import QtCore

import gremlin.config
import gremlin.event_handler
from typing import Callable
from gremlin.singleton_decorator import SingletonDecorator
from . import common, event_handler, input_devices, joystick_handling
import logging


syslog = logging.getLogger("system")


class Repeater(QtCore.QObject):
    """Responsible to repeatedly emit a set of given events.

    The class receives a list of events that are to be emitted in
    sequence. The events are emitted in a separate thread and the
    emission cannot be aborted once it started. While events are
    being emitted a change of events is not performed to prevent
    continuous emitting of events.
    """

    def __init__(self, events, update_func):
        """Creates a new instance.

        :param events the list of events to emit
        :param update_func function used to communicate updates to the UI
        """
        QtCore.QObject.__init__(self)
        self.is_running = False
        self._events = events
        self._thread = threading.Thread(target=self.emit_events, daemon=False)
        self._thread.name = "repeater"
        self._start_timer = threading.Timer(1.0, self.run)
        self._stop_timer = threading.Timer(5.0, self.stop)
        self._update_func = update_func
        self._timeout = time.time()
        self._vjoy_device_guids = [dev.device_guid for dev in joystick_handling.virtual_devices()]
        self._event_registry = {}

    @property
    def events(self):
        return self._events

    @events.setter
    def events(self, event_list):
        """Sets the list of events to execute and queues execution.

        Starts emitting the list of events after a short delay. If a
        new list of events is received before the timeout, the old timer
        is destroyed and replaced with a new one for the new list of
        events. Once events are being emitted all change requests will
        be ignored.

        :param event_list the list of events to emit
        """
        # Only proceed when waiting for input and valid input is provided
        if self.is_running or len(event_list) == 0:
            return
        # Discard inputs that arrive in too quick of a succession
        if time.time() - self._timeout < 0.25:
            return

        self._events = event_list
        if self._start_timer:
            self._start_timer.cancel()
        self._start_timer = threading.Timer(1.0, self.run)
        self._start_timer.start()
        self._update_func("Received input")
        self._timeout = time.time()

    def process_event(self, event):
        """Processes an input event to decide whether or not to repeat it.

        :param event the event to process
        """
        # Ignore VJoy events as well as events occurring when
        # events are repeated
        if self.is_running:
            return
        if isinstance(event, gremlin.event_handler.VjoyEvent):
            # ignore internal vjoy events
            return
        if event.device_guid in self._vjoy_device_guids:
            return

        if not input_devices.JoystickInputSignificant().should_process(event):
            return

        event_list = []
        if event.event_type in [common.InputType.Keyboard, common.InputType.JoystickButton]:
            event_list = [event.clone(), event.clone()]
            event_list[0].is_pressed = False
            event_list[1].is_pressed = True
            event_list[0].value = True
            event_list[1].value = False

        elif event.event_type == common.InputType.JoystickAxis:
            event_list = [event.clone(), event.clone(), event.clone(), event.clone()]
            event_list[0].value = -0.75
            event_list[1].value = 0.0
            event_list[2].value = 0.75
            event_list[3].value = 0.0

        elif event.event_type == common.InputType.JoystickHat:
            event_list = [event.clone(), event.clone()]
            event_list[0].value = (0, 0)

        # mark events as repeater events so actions handle forced values correctly
        for event in event_list:
            event.is_repeater = True

        self.events = event_list

    def stop(self):
        """Stops the event dispatch thread."""
        self.is_running = False
        self._start_timer.cancel()
        if self._thread.is_alive():
            self._thread.join()

    def run(self):
        """Starts the event dispatch thread."""
        if self._thread.is_alive():
            return
        self.is_running = True
        self._stop_timer = threading.Timer(5.0, self.stop)
        self._stop_timer.start()
        self._thread = threading.Thread(target=self.emit_events, daemon=False)
        self._thread.start()

    def emit_events(self):
        """Emits events until stopped."""
        index = 0
        el = event_handler.EventListener()
        syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_outputs

        # Repeatedly send events until the thread is interrupted
        while self.is_running:
            event = self._events[index]
            if event.event_type == common.InputType.Keyboard:
                if verbose:
                    syslog.info(f"REPEATER: send keyboard event: {str(event)}")
                el.keyboard_event.emit(event)
            else:
                if verbose:
                    syslog.info(f"REPEATER: send joystick event: {str(event)}")
                el.joystick_event.emit(event)

            self._update_func(f"{common.InputType.to_string(event.event_type).capitalize()} {str(event.identifier)}")

            index = (index + 1) % len(self._events)
            time.sleep(0.25)

        # This timeout prevents the below state reset to cause the
        # program to trigger another round of repeats with the same
        # input
        self._timeout = time.time()

        # Ensure we leave the input in a neutral state when done
        event = self._events[0].clone()
        if event.event_type == common.InputType.JoystickButton:
            event.is_pressed = False
        elif event.event_type == common.InputType.JoystickAxis:
            last_event = input_devices.JoystickInputSignificant().get_last_event(event)
            if last_event:
                event.value = last_event.value
            else:
                return
        elif event.event_type == common.InputType.JoystickHat:
            event.value = (0, 0)
        el.joystick_event.emit(event)
        self._event_registry = {}
        self._update_func("Waiting for input")


# class PulseWorker(QtCore.QObject):
class PulseWorker:
    """helper object to schedule repeated triggers (callback) at a given interval until the object is stopped."""

    def __init__(self, pulse_duration: float, repeat_interval: float, on_callback : Callable, off_callback: Callable = None, iteration_callback: Callable = None, data=None, count: int = None):
        """Creates a new instance.

        :param pulse_duration: duration in seconds of the pulse
        :param repeat_interval: duration in seconds of the interval between pulses - send a negative value to disable - value of 0 means no delay (not recommended)
        :param on_callback: function to call when the pulse is on - if data is provided, that will be passed as an argument
        :param off_callback: function to call when the pusle if off (optional) - if data is provided, that will be passed as an argument
        :param iteration_callback: function to call on each iteration of the pulse (optional) - if data is provided, that will be passed as an argument
        :param count: number of pulses, set to 0 to disable
        """
        # QtCore.QObject.__init__(self)
        self.is_running = False
        self._pulse_duration = pulse_duration  # singleton if none or 0
        self._repeat_interval = repeat_interval  # repeat delay, none
        self._on_callback = on_callback
        self._off_callback = off_callback
        self._iteration_callback = iteration_callback
        self._is_pulse = False  # true when the signal is active
        self._thread = None  # holds the running thread
        self._data = data  # any data
        self._repeat_count = count

        el = gremlin.event_handler.EventListener()
        el.profile_stop.connect(self.stop)  # stop processing on profile stop
        el.shutdown.connect(self.stop)  # stop processing on app shutdown

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

    def start(self):
        """request a start"""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=False)
        self._thread.name = "PulseRepeater"
        self._keep_running = True
        self._thread.start()

    def stop(self):
        """request a stop"""

        if self._thread:
            if self._off_callback:
                # fire the pulse off callback (or abort)
                if self.data:
                    self._off_callback(self.data)
                else:
                    self._off_callback()

            self._keep_running = False  # tell the worker to stop whatever it's doing
            # wait for the thread to terminate
            if self._thread.is_alive():
                self._thread.join()
            self._thread = None
            self._is_pulse = False  # true if we're pulsing
            self._is_interval = False  # true if we're waiting for the next pulse
            self.is_running = False

    def _run(self):
        """pulse worker"""
        syslog = logging.getLogger("system")
        # verbose = gremlin.config.Configuration().verbose
        verbose = False
        if not self._thread.is_alive():
            return
        while self._keep_running:
            self._is_pulse = True  # indicate pulsing phase
            self._is_interval = False

            # if verbose: syslog.info("Fire on callback")
            if self._on_callback:
                if self.data:
                    # has a callback data param
                    self._on_callback(self.data)
                else:
                    # does not have a callback param
                    self._on_callback()

            # start the pulse timer
            if self._pulse_duration:
                time_lapsed = time.time() + self._pulse_duration
                while self._keep_running and time.time() < time_lapsed:
                    time.sleep(0)

            if self._iteration_callback:
                if self.data:
                    self._iteration_callback(self.data)
                else:
                    self._iteration_callback()

            self._is_pulse = False

            # if verbose: syslog.info("Stop pulse")
            if self._off_callback:
                # fire the pulse off callback (or abort)
                if verbose:
                    syslog.info("Fire off callback")
                if self.data:
                    self._off_callback(self.data)
                else:
                    self._off_callback()

            if self._repeat_count is not None:
                self._repeat_count -= 1
                self._keep_running = self._repeat_count > 0

            if not self._keep_running or self._repeat_interval < 0:
                if verbose:
                    syslog.info("End pulse worker")
                return

            # start the repeat timer
            if self._repeat_interval > 0:
                if verbose:
                    syslog.info("Start wait")
                time_lapsed = time.time() + self._repeat_interval
                while self._keep_running and time.time() < time_lapsed:
                    time.sleep(0)
                if verbose:
                    syslog.info("Stop wait")

        if verbose:
            syslog.info("End pulse worker")

    @property
    def is_pulse(self) -> bool:
        """true if we're pulsing"""
        return self._is_pulse



class AcceleratedEncoder:
    """
    Pulse manager for encoders - converts directional pulse inputs into a smooth setpoint value
    Rotary encoder pulse -> setpoint in [-1.0, +1.0] (customizable)
    Features:
    - pulse-frequency-based acceleration
    - smooth acceleration curve
    - low-pass-filtered pulse frequency
    - acceleration reset on direction change
    - acceleration reset after an idle timeout
    """

    def __init__(
        self,
        initial_value : float =0.0,
        min_value : float =-1.0,
        max_value : float =1.0,
        min_step : float =0.002,
        max_step : float =0.08,
        accel_start_hz : float =2.0,
        accel_full_hz : float =30.0,
        curve : float =2.0,
        frequency_filter : float =0.25,
        direction_change_speed_retention : float =0.0,
        frequency_timeout : float =0.30,
    ):
        """
        Accelerated encoder

        :param initial_value (float): Initial setpoint value.
        :param min_value (float): Minimum setpoint value.
        :param max_value (float): Maximum setpoint value.
        :param min_step (float): Minimum step size per pulse.
        :param max_step (float): Maximum step size per pulse.
        :param accel_start_hz (float): Frequency at which acceleration starts.
        :param accel_full_hz (float): Frequency at which full acceleration is reached.
        :param curve (float): Exponent for shaping the acceleration curve.
        :param frequency_filter (float): Low-pass filter coefficient for pulse frequency.
        :param direction_change_speed_retention (float): Fraction of speed retained on direction change.
        :param frequency_timeout (float): Time in seconds after which acceleration resets if no pulses occur.
        """
        self.value = initial_value # starting position
        self.min_value = min_value # min range (-1)
        self.max_value = max_value # max range (+1)

        self.min_step = min_step # minimum step size per pulse
        self.max_step = max_step # maximum step size per pulse

        self.accel_start_hz = accel_start_hz # frequency at which acceleration starts
        self.accel_full_hz = accel_full_hz # frequency at which full acceleration is reached
        self.curve = curve # exponent for shaping the acceleration curve

        self.frequency_filter = frequency_filter # low-pass filter coefficient for pulse frequency

        # Fraction of previous speed retained when direction reverses.
        # 0.0 = full reset.
        self.direction_change_speed_retention = (
            direction_change_speed_retention
        )

        # Maximum time between pulses before acceleration is reset.
        self.frequency_timeout = frequency_timeout

        self.last_pulse_time = None
        self.last_direction = None
        self.filtered_frequency = 0.0

    def _acceleration(self, frequency : float) -> float:
        """
        Convert pulse frequency to an acceleration factor 0.0 ... 1.0.
        """

        if frequency <= self.accel_start_hz:
            return 0.0

        if frequency >= self.accel_full_hz:
            return 1.0

        # Normalize frequency to 0...1.
        x = (
            (frequency - self.accel_start_hz)
            / (self.accel_full_hz - self.accel_start_hz)
        )

        # Smoothstep gives a smooth transition at both ends.
        x = x * x * (3.0 - 2.0 * x)

        # Additional response shaping.
        x = x ** self.curve

        return x

    def pulse(self, direction : int, timestamp: float = None, value: float = None) -> float:
        """
        Process one encoder pulse.
        direction:
            +1 = increase
            -1 = decrease
        Returns:
            current setpoint
        """

        if direction not in (-1, 1):
            raise ValueError("direction must be +1 or -1")

        if timestamp is None:
            timestamp = time.monotonic()

        if value is not None:
            # reset the value
            self.value = value

        # elapsed time since previous pulse.
        dt = None

        if self.last_pulse_time is not None:
            dt = timestamp - self.last_pulse_time

        # idle timeout check
        timed_out = (
            dt is not None
            and dt >= self.frequency_timeout
        )

        if timed_out:
            # Previous speed is now considered stale.
            self.filtered_frequency = 0.0

            # Treat this as the beginning of a new movement.
            self.last_pulse_time = None
            dt = None

        # reversal check
        direction_changed = (
            self.last_direction is not None
            and direction != self.last_direction
        )

        if direction_changed:
            # Kill or reduce accumulated acceleration.
            self.filtered_frequency *= (
                self.direction_change_speed_retention
            )

            # Do not calculate frequency using an interval
            # that spans two different directions.
            self.last_pulse_time = None
            dt = None

        # pulse frequency.
        if dt is not None and dt > 0:
            instantaneous_frequency = 1.0 / dt

            alpha = self.frequency_filter

            self.filtered_frequency += alpha * (
                instantaneous_frequency
                - self.filtered_frequency
            )

        # state
        self.last_pulse_time = timestamp
        self.last_direction = direction

        # compute acceleration
        accel = self._acceleration(
            self.filtered_frequency
        )

        offset = self.min_step + accel * (
            self.max_step - self.min_step
        )

        # apply computed offset
        self.value += direction * offset

        # clamp
        self.value = max(
            self.min_value,
            min(self.max_value, self.value)
        )

        return self.value

    def get_value(self):
        return self.value

    def get_frequency(self):
        return self.filtered_frequency

    def get_step(self):
        accel = self._acceleration(
            self.filtered_frequency
        )

        return self.min_step + accel * (
            self.max_step - self.min_step
        )

    def reset_acceleration(self):
        """
        Manually reset the current acceleration state.
        """
        self.filtered_frequency = 0.0
        self.last_pulse_time = None
        self.last_direction = None

