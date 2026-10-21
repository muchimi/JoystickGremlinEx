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
from ctypes import wintypes
import logging
import queue
import threading
from time import monotonic

import gremlin.singleton_decorator


user32 = ctypes.WinDLL("user32", use_last_error=True)

g_keyboard_callbacks = []
g_mouse_callbacks = []  # holds callbacks specific to non mouse movement
g_mouse_move_callbacks = []  # holds callbacks specific to mouse movement
g_mouse_wheel_callbacks = []  # holds callbacks specific to mouse wheel
g_suppress_mouse = 0  # block stack for mouse (shift + esc to terminate)
g_suppress_keyboard = 0  # block stack for keyboard (shift + esc to terminate)
_shift_keys_down = set()
g_shift_state = False  # true if either shift keys are down
g_verbose_keyboard: bool = False  # verbose mode for keyboards

syslog = logging.getLogger("system")

# Central event dispatch queue to offload heavy Python execution from Windows hook thread
_event_queue: queue.SimpleQueue = queue.SimpleQueue()
_event_worker_thread: threading.Thread | None = None


def _event_worker_loop():
    """Worker thread processing queued hook callbacks to lower CPU and prevent hook timeouts."""
    while True:
        item = _event_queue.get()
        if item is None:
            break
        callbacks, args = item
        for cb in callbacks:
            try:
                cb(*args)
            except Exception:
                syslog.exception("Error in hook callback execution")


def _ensure_event_worker():
    global _event_worker_thread
    if _event_worker_thread is None or not _event_worker_thread.is_alive():
        _event_worker_thread = threading.Thread(
            target=_event_worker_loop, name="hook-event-worker", daemon=True
        )
        _event_worker_thread.start()


_ensure_event_worker()


class KeyEvent:
    """Structure containing details about a key event."""

    def __init__(self, virtual_code, scan_code, is_extended, is_pressed, is_injected):
        self._virtual_code = virtual_code
        self._scan_code = scan_code
        self._is_extended = is_extended
        self._is_pressed = is_pressed
        self._is_injected = is_injected

    def __str__(self):
        return (
            f"(virtual: {hex(self._virtual_code)} scancode/extended ({hex(self._scan_code)} {self._is_extended}) "
            f"{'down' if self._is_pressed else 'up'}, {'injected' if self.is_injected else ''}"
        )

    @property
    def scan_code(self):
        return self._scan_code

    @property
    def is_extended(self):
        return self._is_extended

    @property
    def is_pressed(self):
        return self._is_pressed

    @property
    def is_injected(self):
        return self._is_injected

    @property
    def virtual_code(self):
        return self._virtual_code


class MouseEvent:
    """Structure containing information about a mouse event."""

    def __init__(self, button_id, is_pressed, is_injected):
        self._button_id = button_id
        self._is_pressed = is_pressed
        self._is_injected = is_injected

    @property
    def button_id(self):
        return self._button_id

    @property
    def is_pressed(self):
        return self._is_pressed

    @property
    def is_injected(self):
        return self._is_injected

    def __str__(self):
        return f"MouseEvent: {self.button_id} pressed: {self._is_pressed} injected: {self._is_injected}"


def get_last_error():
    return ctypes.get_last_error()


HOOKPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = (
    ctypes.c_int,
    HOOKPROC,
    wintypes.HINSTANCE,
    wintypes.DWORD,
)

user32.CallNextHookEx.restype = wintypes.LPARAM
user32.CallNextHookEx.argtypes = (
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

user32.GetMessageW.argtypes = (
    wintypes.LPMSG,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)

user32.GetMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = (
    wintypes.LPMSG, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
)
user32.PeekMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = (
    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
)
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = (wintypes.LPMSG,)
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = (wintypes.LPMSG,)
user32.DispatchMessageW.restype = wintypes.LPARAM

HC_ACTION = 0
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    )


LPKBDLLHOOKSTRUCT = ctypes.POINTER(KBDLLHOOKSTRUCT)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    )


LPMSLLHOOKSTRUCT = ctypes.POINTER(MSLLHOOKSTRUCT)


@HOOKPROC
def process_keyboard_event(n_code, w_param, l_param):
    global g_suppress_keyboard, g_shift_state, g_suppress_mouse, g_verbose_keyboard
    # Windows requires negative codes to pass through without dereferencing lParam.
    if n_code < 0:
        return user32.CallNextHookEx(None, n_code, w_param, l_param)
    msg = ctypes.cast(l_param, LPKBDLLHOOKSTRUCT)[0]

    if msg.scanCode:
        virtual_code = msg.vkCode
        scan_code = msg.scanCode & 0xFF
        is_extended = bool(msg.flags & 0x0001)
        is_pressed = w_param in (0x0100, 0x0104)
        is_injected = bool(msg.flags & 0x0010)

        if scan_code in (0x2A, 0x36):
            if is_pressed:
                _shift_keys_down.add(scan_code)
            else:
                _shift_keys_down.discard(scan_code)
            g_shift_state = bool(_shift_keys_down)

        if msg.scanCode != 541 and g_keyboard_callbacks:
            evt = KeyEvent(
                virtual_code=virtual_code,
                scan_code=scan_code,
                is_extended=is_extended,
                is_pressed=is_pressed,
                is_injected=is_injected,
            )
            _event_queue.put((tuple(g_keyboard_callbacks), (evt,)))

        if scan_code == 0x01 and g_shift_state:
            g_suppress_keyboard = 0
            g_suppress_mouse = 0

        if g_suppress_keyboard != 0:
            return 1

    return user32.CallNextHookEx(None, n_code, w_param, l_param)


_mouse_wheel_state = {}
_mouse_wheel_delay = 0.5
# At most four deadlines; rearming a wheel never creates a timer thread.
_mouse_wheel_deadlines = {}
_mouse_x = None
_mouse_y = None

_wheel_worker: threading.Thread | None = None
_wheel_worker_stop = threading.Event()
_wheel_lock = threading.RLock()
_wheel_condition = threading.Condition(_wheel_lock)


def _ensure_wheel_worker():
    global _wheel_worker
    with _wheel_condition:
        if _wheel_worker is not None and _wheel_worker.is_alive():
            return
        _wheel_worker_stop.clear()
        _wheel_worker = threading.Thread(
            target=_wheel_worker_loop, name="mouse-wheel-release", daemon=True,
        )
        _wheel_worker.start()


def _wheel_worker_loop():
    with _wheel_condition:
        while not _wheel_worker_stop.is_set():
            if not _mouse_wheel_deadlines:
                _wheel_condition.wait()
                continue
            button_id = min(_mouse_wheel_deadlines, key=_mouse_wheel_deadlines.get)
            remaining = _mouse_wheel_deadlines[button_id] - monotonic()
            if remaining > 0:
                _wheel_condition.wait(remaining)
                continue
            _queue_wheel_release(button_id)


def _arm_wheel_release(button_id):
    with _wheel_condition:
        _mouse_wheel_deadlines[button_id] = monotonic() + _mouse_wheel_delay
        _wheel_condition.notify()


def _cancel_wheel_release(button_id):
    with _wheel_condition:
        _mouse_wheel_deadlines.pop(button_id, None)
        _wheel_condition.notify()


_is_runtime = False


def setRunning(value: bool):
    global _is_runtime
    _is_runtime = value


def getMousePosition(self=None):
    global _mouse_x, _mouse_y
    return (_mouse_x, _mouse_y)


@HOOKPROC
def process_mouse_event(n_code, w_param, l_param):
    import gremlin.types

    global g_mouse_callbacks, _is_runtime, _mouse_x, _mouse_y
    global g_mouse_move_callbacks, g_mouse_wheel_callbacks
    global g_suppress_mouse

    if n_code < 0:
        return user32.CallNextHookEx(None, n_code, w_param, l_param)
    if n_code == HC_ACTION:
        msg = ctypes.cast(l_param, LPMSLLHOOKSTRUCT)[0]

        button_id = None
        release_button_id = None
        is_pressed = True
        is_wheel = False
        process = False

        if w_param in (WM_LBUTTONDOWN, WM_LBUTTONUP):
            button_id = gremlin.types.MouseButton.Left
            is_pressed = w_param == WM_LBUTTONDOWN
            process = True
        elif w_param in (WM_RBUTTONDOWN, WM_RBUTTONUP):
            button_id = gremlin.types.MouseButton.Right
            is_pressed = w_param == WM_RBUTTONDOWN
            process = True
        elif w_param in (WM_MBUTTONDOWN, WM_MBUTTONUP):
            button_id = gremlin.types.MouseButton.Middle
            is_pressed = w_param == WM_MBUTTONDOWN
            process = True
        elif w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            if msg.mouseData & (0x0001 << 16):
                button_id = gremlin.types.MouseButton.Back
            elif msg.mouseData & (0x0002 << 16):
                button_id = gremlin.types.MouseButton.Forward
            is_pressed = w_param == WM_XBUTTONDOWN
            process = True
        elif w_param == WM_MOUSEWHEEL:
            delta = ctypes.c_short(msg.mouseData >> 16).value
            if delta > 0:
                button_id = gremlin.types.MouseButton.WheelUp
                release_button_id = gremlin.types.MouseButton.WheelDown
            elif delta < 0:
                button_id = gremlin.types.MouseButton.WheelDown
                release_button_id = gremlin.types.MouseButton.WheelUp

            is_wheel = True
            if g_mouse_wheel_callbacks:
                _event_queue.put(
                    (tuple(g_mouse_wheel_callbacks), (delta, False))
                )
        elif w_param == WM_MOUSEHWHEEL:
            # Preserve the unsigned delta expected by existing subscribers.
            delta = msg.mouseData >> 16
            signed_delta = ctypes.c_short(delta).value
            if signed_delta > 0:
                button_id = gremlin.types.MouseButton.WheelRight
                release_button_id = gremlin.types.MouseButton.WheelLeft
            elif signed_delta < 0:
                button_id = gremlin.types.MouseButton.WheelLeft
                release_button_id = gremlin.types.MouseButton.WheelRight
            is_wheel = True
            if g_mouse_wheel_callbacks:
                _event_queue.put(
                    (tuple(g_mouse_wheel_callbacks), (delta, True))
                )
        elif w_param == WM_MOUSEMOVE:
            # CPU Optimization: Only queue callbacks if position actually shifted
            if _mouse_x == msg.pt.x and _mouse_y == msg.pt.y:
                if g_suppress_mouse == 0:
                    return user32.CallNextHookEx(None, n_code, w_param, l_param)
                return 1

            _mouse_x = msg.pt.x
            _mouse_y = msg.pt.y

            if g_mouse_move_callbacks:
                _event_queue.put(
                    (tuple(g_mouse_move_callbacks), (_mouse_x, _mouse_y))
                )

        if is_wheel and button_id and _is_runtime:
            # State, deadlines and queued press/release events must be atomic
            # with respect to the release worker, including a zero delay.
            with _wheel_condition:
                if release_button_id:
                    _queue_wheel_release(release_button_id)
                if not _mouse_wheel_state.get(button_id, False):
                    _mouse_wheel_state[button_id] = True
                    if g_mouse_callbacks:
                        evt = MouseEvent(button_id, True, False)
                        _event_queue.put((tuple(g_mouse_callbacks), (evt,)))
                _arm_wheel_release(button_id)
            process = False
        elif is_wheel and button_id:
            process = True

        if process and button_id and g_mouse_callbacks:
            evt = MouseEvent(button_id, is_pressed, False)
            _event_queue.put((tuple(g_mouse_callbacks), (evt,)))

    if g_suppress_mouse == 0:
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    return 1


def _queue_wheel_release(button_id):
    with _wheel_condition:
        _mouse_wheel_deadlines.pop(button_id, None)
        if _mouse_wheel_state.get(button_id, False):
            _mouse_wheel_state[button_id] = False
            if g_mouse_callbacks:
                evt = MouseEvent(button_id, False, False)
                _event_queue.put((tuple(g_mouse_callbacks), (evt,)))
        _wheel_condition.notify()


def _start_listener(hook, name):
    with hook._lifecycle_lock:
        if hook._listen_thread is not None and hook._listen_thread.is_alive():
            return
        hook._ready.clear()
        hook._startup_error = None
        hook._running = True
        hook._listen_thread = threading.Thread(target=hook._listen, name=name, daemon=True)
        try:
            hook._listen_thread.start()
        except Exception:
            hook._running = False
            hook._listen_thread = None
            raise
        # The queue must exist before another thread can post WM_QUIT.
        hook._ready.wait()
        if hook._startup_error is not None:
            hook._listen_thread.join()
            hook._listen_thread = None
            raise hook._startup_error


def _stop_listener(hook):
    with hook._lifecycle_lock:
        thread = hook._listen_thread
        if thread is None:
            return
        if thread.is_alive():
            if not user32.PostThreadMessageW(hook._native_thread_id, WM_QUIT, 0, 0):
                if thread.is_alive():
                    raise ctypes.WinError(get_last_error())
            if thread is not threading.current_thread():
                thread.join()
        hook._listen_thread = None
        hook._running = False


def _listen_for_events(hook, hook_type, callback):
    hook.hook_id = None
    try:
        hook._native_thread_id = threading.get_native_id()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        hook.hook_id = user32.SetWindowsHookExW(hook_type, callback, None, 0)
        if not hook.hook_id:
            raise ctypes.WinError(get_last_error())
        hook._ready.set()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:
                break
            if result == -1:
                raise ctypes.WinError(get_last_error())
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except Exception as error:
        if not hook._ready.is_set():
            hook._startup_error = error
        else:
            syslog.exception("Windows hook message loop failed")
    finally:
        if hook.hook_id:
            if not user32.UnhookWindowsHookEx(hook.hook_id):
                syslog.error("Unable to remove Windows hook: %s", get_last_error())
            hook.hook_id = None
        hook._running = False
        hook._ready.set()


@gremlin.singleton_decorator.SingletonDecorator
class KeyboardHook:
    def __init__(self):
        self._running = False
        self._listen_thread = None
        self._lifecycle_lock = threading.RLock()
        self._ready = threading.Event()
        self._startup_error = None
        self._native_thread_id = None
        self.hook_id = None

    def updateVerbose(self):
        import gremlin.config

        global g_verbose_keyboard
        g_verbose_keyboard = (
            gremlin.config.Configuration().verbose_mode_keyboard_extra
        )

    def pushSuppress(self):
        global g_suppress_keyboard
        if g_suppress_keyboard == 0:
            syslog.info("KVM: local keyboard events DISABLED")
        g_suppress_keyboard += 1

    def popSuppress(self, reset=False):
        global g_suppress_keyboard
        if reset:
            if g_suppress_keyboard != 0:
                syslog.info("KVM: local keyboard events ENABLED")
                g_suppress_keyboard = 0
        elif g_suppress_keyboard > 0:
            g_suppress_keyboard -= 1
            if g_suppress_keyboard == 0:
                syslog.info("KVM: local keyboard events ENABLED")

    def isSupressed(self) -> bool:
        global g_suppress_keyboard
        return g_suppress_keyboard != 0

    def register(self, callback):
        global g_keyboard_callbacks
        if callback and callback not in g_keyboard_callbacks:
            g_keyboard_callbacks.append(callback)
        self.start()

    def unregister(self, callback):
        global g_keyboard_callbacks
        if callback and callback in g_keyboard_callbacks:
            g_keyboard_callbacks.remove(callback)

    def start(self):
        _start_listener(self, "keyboard hook")

    def stop(self):
        _stop_listener(self)
        _shift_keys_down.clear()
        global g_shift_state
        g_shift_state = False

    def shutdown(self):
        self.stop()
        syslog.info("KBD: shutdown")

    def _listen(self):
        _listen_for_events(self, WH_KEYBOARD_LL, process_keyboard_event)


@gremlin.singleton_decorator.SingletonDecorator
class MouseHook:
    def __init__(self):
        import gremlin.config
        import gremlin.types

        self._running = False
        self._listen_thread = None
        self._lifecycle_lock = threading.RLock()
        self._ready = threading.Event()
        self._startup_error = None
        self._native_thread_id = None
        self.hook_id = None

        global _mouse_wheel_delay
        wheel_buttons = [
            gremlin.types.MouseButton.WheelDown,
            gremlin.types.MouseButton.WheelUp,
            gremlin.types.MouseButton.WheelLeft,
            gremlin.types.MouseButton.WheelRight,
        ]
        for button_id in wheel_buttons:
            _mouse_wheel_state[button_id] = False

        _mouse_wheel_delay = (
            gremlin.config.Configuration().mouse_wheel_autorelease_delay
        )

        SM_SWAPBUTTON = 23
        self._is_swapped = (
            ctypes.windll.user32.GetSystemMetrics(SM_SWAPBUTTON) != 0
        )

    def pushSuppress(self):
        global g_suppress_mouse
        g_suppress_mouse += 1

        verbose = gremlin.config.Configuration().verbose_mode_remote
        if verbose:
            syslog.info(f"MOUSE: push suppress [{g_suppress_mouse}]")

    def popSuppress(self, reset=False):
        global g_suppress_mouse
        if reset:
            g_suppress_mouse = 0
        elif g_suppress_mouse > 0:
            g_suppress_mouse -= 1

        verbose = gremlin.config.Configuration().verbose_mode_remote
        if verbose:
            syslog.info(f"MOUSE: pop supress [{g_suppress_mouse}]")

    def isSupressed(self) -> bool:
        global g_suppress_mouse
        return g_suppress_mouse != 0

    def register(self, callback):
        global g_mouse_callbacks
        if callback:
            if callback not in g_mouse_callbacks:
                g_mouse_callbacks.append(callback)
            self.start()

    def registerMouseMove(self, callback):
        global g_mouse_move_callbacks
        if callback:
            if callback not in g_mouse_move_callbacks:
                g_mouse_move_callbacks.append(callback)
            self.start()

    def registerMouseWheel(self, callback):
        global g_mouse_wheel_callbacks
        if callback:
            if callback not in g_mouse_wheel_callbacks:
                g_mouse_wheel_callbacks.append(callback)
            self.start()

    def unregister(self, callback):
        global g_mouse_callbacks
        if callback in g_mouse_callbacks:
            g_mouse_callbacks.remove(callback)

        self._stop_if_unused()

    def _stop_if_unused(self):
        if (
            not g_mouse_callbacks
            and not g_mouse_move_callbacks
            and not g_mouse_wheel_callbacks
        ):
            self.stop()

    def unregisterMouseMove(self, callback):
        global g_mouse_move_callbacks
        if callback in g_mouse_move_callbacks:
            g_mouse_move_callbacks.remove(callback)
        self._stop_if_unused()

    def unregisterMouseWheel(self, callback):
        global g_mouse_wheel_callbacks
        if callback in g_mouse_wheel_callbacks:
            g_mouse_wheel_callbacks.remove(callback)
        self._stop_if_unused()

    def start(self):
        with self._lifecycle_lock:
            _ensure_wheel_worker()
            try:
                _start_listener(self, "mouse hook")
            except Exception:
                self._stop_timers()
                raise

    def stop(self):
        with self._lifecycle_lock:
            _stop_listener(self)
            self._stop_timers()

    def shutdown(self):
        self.stop()
        syslog.info("MOUSE: shutdown")

    def _stop_timers(self):
        global _wheel_worker
        with _wheel_condition:
            _wheel_worker_stop.set()
            for button_id in tuple(_mouse_wheel_state):
                _queue_wheel_release(button_id)
            _mouse_wheel_deadlines.clear()
            _wheel_condition.notify_all()
        if _wheel_worker is not None:
            _wheel_worker.join()
            _wheel_worker = None

    def _listen(self):
        _listen_for_events(self, WH_MOUSE_LL, process_mouse_event)

    @property
    def is_swapped(self) -> bool:
        return self._is_swapped


_mouse_hook = MouseHook()
