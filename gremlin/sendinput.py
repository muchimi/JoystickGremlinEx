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


import ctypes
import ctypes.wintypes
import enum
import logging
import math
import threading
import time
import win32api
import win32con


import gremlin.util

from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import MouseButton

"""Defines flags used when specifying MOUSEINPUT structures.

https://msdn.microsoft.com/en-us/library/ms646273(v=VS.85).aspx
"""
WHEEL_DELTA = 120
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001


"""Defines data structure type for INPUT structures.

https://msdn.microsoft.com/en-us/library/ms646270(v=vs.85).aspx
"""
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

syslog = logging.getLogger("system")

class MotionType(enum.Enum):

    """Mouse motion types available."""

    Fixed = 1,
    Accelerated = 2


class MouseMotion:

    """Base class of all mouse motion behaviours."""

    # Time step between calls
    delta_t = 0.01

    def __init__(self, dx=0, dy=0):
        """Creates a new instance.

        :param dx motion along the x axis in pixels per second
        :param dy motion along the y axis in pixels per second
        """
        self.dx = dx if dx is not None else 0
        self.dy = dy if dy is not None else 0

        self._tick_dx_value, self._tick_dx_time = self._compute_values(self.dx)
        self._tick_dy_value, self._tick_dy_time = self._compute_values(self.dy)

        self._dx_timestamp = 0
        self._dy_timestamp = 0

    def __call__(self):
        """Returns the change in x and y for this point in time.

        :return dx, dy for this time point
        """
        if self._tick_dx_value == 0 and self._tick_dy_value == 0:
            return 0, 0

        delta_x = 0
        delta_y = 0

        cur_time = time.monotonic()
        if self._dx_timestamp < cur_time:
            delta_x = self._tick_dx_value
            self._dx_timestamp = cur_time + self._tick_dx_time
        if self._dy_timestamp < cur_time:
            delta_y = self._tick_dy_value
            self._dy_timestamp = cur_time + self._tick_dy_time

        return delta_x, delta_y

    def _compute_values(self, delta):
        """Computes discretization values to send integer motions.

        :param delta the amount of change in pixels per second to discretize for
        """
        magnitude = abs(delta)
        magnitude = 0.0 if magnitude < 1e-6 else magnitude
        tick_value = math.ceil(magnitude * MouseMotion.delta_t)
        if tick_value == 0:
            tick_time = MouseMotion.delta_t
        else:
            tick_time = tick_value / magnitude
            tick_value = int(math.copysign(tick_value, delta))

        return tick_value, tick_time


class FixedMouseMotion(MouseMotion):

    """Motion generation with fixed speed - pixel ."""

    def __init__(self, dx, dy, rate = 1.0):
        """Creates a new instance.

        :param dx motion along the x axis in pixels per rate
        :param dy motion along the y axis in pixels per rate
        :param rate: rate in seconds
        """
        super().__init__(dx, dy)
        self._call_time = None
        if rate < 0:
            rate = 0
        self._rate = rate



    def set_dx(self, value):
        """Updates the x velocity.

        :param value speed in pixels per second along the x axis
        """
        self.dx = value

    def set_dy(self, value):
        """Updates the y velocity.

        :param value speed in pixels per second along the y axis
        """
        self.dy = value

    def __call__(self):
        time_now = time.monotonic()
        if self._call_time is None or self._call_time <= time_now:
            self._call_time = time_now + self._rate # next call time
            return self.dx, self.dy
        return 0,0 # no movement as time hasn't lapsed



class AcceleratedMouseMotion(MouseMotion):

    """Motion generation with acceleration over time."""

    def __init__(self, direction, min_speed, max_speed, time_to_max_speed):
        """Creates a new instance.

        :param direction the direction of motion
        :param min_speed minimum speed in pixels per second
        :param max_speed maximum speed in pixels per second
        :param time_to_max_speed time to reach max_speed
        """
        super().__init__()

        self.min_velocity = min_speed
        self.max_velocity = max_speed
        # Make sure we don't get numerical issues with acceleration computation
        if time_to_max_speed < 0.001:
            self.acceleration = 1e6
        else:
            self.acceleration = (max_speed - min_speed) / time_to_max_speed

        self.current_velocity = self.min_velocity
        self.set_direction(direction)

    def set_direction(self, direction):
        """Sets the direction for which to emit position changes.

        :param direction new direction of travel
        """
        self.direction = direction - 90.0
        self._direction_x, self._direction_y = self._decompose_xy(self.direction, 1.0)
        self.dx = self._direction_x * self.current_velocity
        self.dy = self._direction_y * self.current_velocity
        self._tick_dx_value, self._tick_dx_time = self._compute_values(self.dx)
        self._tick_dy_value, self._tick_dy_time = self._compute_values(self.dy)

    def _decompose_xy(self, direction, value):
        """Returns x and y values corresponding to a direction and value.

        :param direction direction in degrees with 0 being pure motion along
            positive y
        :param value the length of the direction vector
        """
        radians = math.radians(direction)
        return value * math.cos(radians), value * math.sin(radians)

    def __call__(self):
        """Returns the change in x and y for this point in time.

        :return dx, dy for this time point
        """
        # Get values to return using current integration step values
        dx, dy = super().__call__()

        # Apply acceleration to obtain next integration step values
        velocity = min(
            self.max_velocity,
            self.current_velocity + self.acceleration * MouseMotion.delta_t
        )
        if velocity != self.current_velocity:
            self.current_velocity = velocity
            self.dx = self._direction_x * velocity
            self.dy = self._direction_y * velocity
            self._tick_dx_value, self._tick_dx_time = self._compute_values(self.dx)
            self._tick_dy_value, self._tick_dy_time = self._compute_values(self.dy)

        # Return cached values
        return dx, dy


@SingletonDecorator
class MouseController:

    """Centralizes sending mouse events in a organized manner."""

    def __init__(self):
        """Creates a new instance."""
        import gremlin.event_handler
        self._motion_type = MotionType.Fixed
        self._delta_generator = None
        self._accel_generator = None
        self._is_running = False
        self._stop = threading.Event()
        self._motion_condition = threading.Condition()
        self._thread = None
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)

    def _profile_start(self):
        self.stop()
        with self._motion_condition:
            self._delta_generator = None
            self._accel_generator = None

    def _profile_stop(self):
        self.stop()
        with self._motion_condition:
            self._delta_generator = None
            self._accel_generator = None

    def set_absolute_motion(self, dx=None, dy=None):
        """Configures a motion using absolute velocities.

        If dx / dy are set to None their values will not be updated.

        :param dx velocity along the x axis in pixels per second
        :param dy velocity along the y axis in pixels per second
        """
        with self._motion_condition:
            self._motion_type = MotionType.Fixed
            if self._delta_generator is None:
                self._delta_generator = FixedMouseMotion(dx, dy)
            else:
                if dx is not None:
                    self._delta_generator.set_dx(dx)
                if dy is not None:
                    self._delta_generator.set_dy(dy)
            self._motion_condition.notify()

    def set_accelerated_motion(
            self,
            direction,
            min_speed,
            max_speed,
            time_to_max_speed
    ):
        """Configures a motion using acceleration.

        :param direction the direction of motion
        :param min_speed minimum speed in pixels per second
        :param max_speed maximum speed in pixels per second
        :param time_to_max_speed time to reach max_speed
        """
        with self._motion_condition:
            self._motion_type = MotionType.Accelerated
            self._accel_generator = AcceleratedMouseMotion(
                direction,
                min_speed,
                max_speed,
                time_to_max_speed
            )
            self._motion_condition.notify()


    def start(self):
        """Starts the thread that will send motions when required."""
        with self._motion_condition:
            if not self._thread or not self._thread.is_alive():
                self._stop.clear()
                try:
                    thread = threading.Thread(target=self._control_loop, name="MouseController", daemon=False)
                    self._thread = thread
                    thread.start()
                except BaseException:
                    self._thread = None
                    self._stop.set()
                    raise
                syslog.info("MouseController: start")

    @property
    def started(self) -> bool:
        ''' true if controller is running'''
        thread = self._thread
        return thread is not None and thread.is_alive()

    def stop(self):
        """Stops the thread that sends motion events."""
        with self._motion_condition:
            thread = self._thread
            self._stop.set()
            self._motion_condition.notify_all()
        if thread is not None and thread is not threading.current_thread():
            gremlin.util.safeJoin(thread)
            with self._motion_condition:
                if not thread.is_alive() and self._thread is thread:
                    self._thread = None
            syslog.info("MouseController: stop")

    def _control_loop(self):
        """Loop responsible for creating and sending mouse motion events."""

        try:
            while True:
                with self._motion_condition:
                    while not self._stop.is_set():
                        if self._motion_type == MotionType.Fixed:
                            generator = self._delta_generator
                            active = generator is not None and (generator.dx or generator.dy)
                        else:
                            generator = self._accel_generator
                            # A zero starting speed can still accelerate into motion.
                            active = generator is not None and (generator.current_velocity or generator.max_velocity)
                        if active:
                            dx, dy = generator()
                            break
                        self._motion_condition.wait()
                    else:
                        return

                # Native input hooks can reenter the controller; release the
                # motion lock before sending input or waiting for the next tick.
                if not self._stop.is_set() and (dx or dy):
                    send_mouse_motion(int(dx), int(dy))
                self._stop.wait(MouseMotion.delta_t)
        finally:
            with self._motion_condition:
                if self._thread is threading.current_thread():
                    self._thread = None


class _MOUSEINPUT(ctypes.Structure):

    """Defines the MOUSEINPUT structure.

    https://msdn.microsoft.com/en-us/library/ms646273(v=VS.85).aspx
    """

    _fields_ = (
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    )


class _KEYBDINPUT(ctypes.Structure):

    """Defines the KEYBDINPUT structure.

    https://msdn.microsoft.com/en-us/library/ms646271(v=vs.85).aspx
    """

    _fields_ = (
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("wExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG))
    )


def _keyboard_input(virtual_key, scan_code, flags):
    value = _INPUT()
    value.type = INPUT_KEYBOARD
    keyboard = value.union.ki
    keyboard.wVk = virtual_key
    keyboard.wScan = scan_code
    keyboard.dwFlags = flags
    return value

class _INPUTunion(ctypes.Union):

    """Defines the INPUT union type.

    https://msdn.microsoft.com/en-us/library/ms646270(v=vs.85).aspx
    """

    _fields_ = (
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT)
    )


class _INPUT(ctypes.Structure):

    """Defines the INPUT structure.

    https://msdn.microsoft.com/en-us/library/ms646270(v=vs.85).aspx
    """

    _fields_ = (
        ("type", ctypes.wintypes.DWORD),
        ("union", _INPUTunion)
    )


_INPUT_SIZE = ctypes.sizeof(_INPUT)
_SendInput = ctypes.windll.user32.SendInput
_SendInput.argtypes = (ctypes.wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_SendInput.restype = ctypes.wintypes.UINT


def send_mouse_motion(dx, dy):
    ''' sends mouse relative motion '''
    # https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-mouse_event
    _send_input(_mouse_input(MOUSEEVENTF_MOVE, dx, dy))

def send_mouse_position(x, y):
    ''' sends absolute coordinates '''
    # https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-mouse_event

    width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    fx = 65535 / width
    fy = 65535 / height
    dx = int(x * fx)
    dy = int(y * fy)
    _send_input(_mouse_input(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE , dx, dy))


def send_mouse_wheel_up():
    ''' sends a mouse wheel up '''
    _send_input(_MOUSE_WHEEL_UP)

def send_mouse_wheel_down():
    ''' sends a mouse wheel down '''
    _send_input(_MOUSE_WHEEL_DOWN)

def send_mouse_wheel_left():
    ''' sends a mouse wheel left '''
    _send_input(_MOUSE_WHEEL_LEFT)

def send_mouse_wheel_right():
    ''' sends a mouse wheel right  '''
    _send_input(_MOUSE_WHEEL_RIGHT)




def mouse_press(button):
    ''' sends a single click'''
    inputs = _MOUSE_BUTTON_INPUTS.get(button)
    if inputs is not None:
        _send_input(inputs[0])

def mouse_press_double_click(button, delay = 0.05):
    ''' sends a double click (also releases the mouse) '''
    inputs = _MOUSE_BUTTON_INPUTS.get(button)
    if inputs is None:
        return

    press, release = inputs
    _send_input(press)
    time.sleep(delay)
    _send_input(release)
    time.sleep(delay)
    _send_input(press)
    time.sleep(delay)
    _send_input(release)



def mouse_release(button):
    inputs = _MOUSE_BUTTON_INPUTS.get(button)
    if inputs is not None:
        _send_input(inputs[1])


def mouse_wheel(factor : int):
    ''' send vertical mouse wheel

    :param factor: 1 for up, -1 for down, factor

    '''
    _send_input(_mouse_input(MOUSEEVENTF_WHEEL, data = factor*WHEEL_DELTA))

def mouse_h_wheel(factor : int):
    ''' send horizontal mouse wheel
    :param factor: 1 for up, -1 for down, factor

    '''
    _send_input(_mouse_input(MOUSEEVENTF_HWHEEL, data = factor*WHEEL_DELTA))

def mousePos():
    ''' gets the current mouse position in pixels '''
    x = gremlin.windows_event_hook._mouse_x
    y = gremlin.windows_event_hook._mouse_y
    return x,y

def _mouse_input(flags, dx=0, dy=0, data=0):
    value = _INPUT()
    mouse = value.union.mi
    mouse.dx = dx
    mouse.dy = dy
    mouse.mouseData = data
    mouse.dwFlags = flags
    return value


# These payloads are read-only after construction and safe to share across senders.
_MOUSE_BUTTON_INPUTS = {
    MouseButton.Left: (_mouse_input(MOUSEEVENTF_LEFTDOWN), _mouse_input(MOUSEEVENTF_LEFTUP)),
    MouseButton.Right: (_mouse_input(MOUSEEVENTF_RIGHTDOWN), _mouse_input(MOUSEEVENTF_RIGHTUP)),
    MouseButton.Middle: (_mouse_input(MOUSEEVENTF_MIDDLEDOWN), _mouse_input(MOUSEEVENTF_MIDDLEUP)),
    MouseButton.Back: (_mouse_input(MOUSEEVENTF_XDOWN, data=XBUTTON1), _mouse_input(MOUSEEVENTF_XUP, data=XBUTTON1)),
    MouseButton.Forward: (_mouse_input(MOUSEEVENTF_XDOWN, data=XBUTTON2), _mouse_input(MOUSEEVENTF_XUP, data=XBUTTON2)),
}
_MOUSE_WHEEL_UP = _mouse_input(MOUSEEVENTF_WHEEL, data=WHEEL_DELTA)
_MOUSE_WHEEL_DOWN = _mouse_input(MOUSEEVENTF_WHEEL, data=-WHEEL_DELTA)
_MOUSE_WHEEL_LEFT = _mouse_input(MOUSEEVENTF_HWHEEL, data=-WHEEL_DELTA)
_MOUSE_WHEEL_RIGHT = _mouse_input(MOUSEEVENTF_HWHEEL, data=WHEEL_DELTA)


def send_key(virtual_code, scan_code, flags):
    ''' sends a key message via send input '''
    _send_input(_keyboard_input(virtual_code, scan_code, flags))


def send_key_hwnd(hwnd, virtual_code, scan_code, flags):
    ''' sends a key to a specific process '''
    import win32gui
    win32gui.PostMessage(hwnd, _keyboard_input(virtual_code, scan_code, flags))



def _send_input(*inputs):
    # https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
    count = len(inputs)
    if count == 1:
        return _SendInput(1, ctypes.byref(inputs[0]), _INPUT_SIZE)
    if count == 0:
        return 0

    buffer = (_INPUT * count)(*inputs)
    return _SendInput(count, buffer, _INPUT_SIZE)
