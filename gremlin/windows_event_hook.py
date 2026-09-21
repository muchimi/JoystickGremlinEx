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
import win32api

import gremlin.singleton_decorator


user32 = ctypes.WinDLL("user32")

g_keyboard_callbacks = []
g_mouse_callbacks = []  # holds callbacks specific to non mouse movement
g_mouse_move_callbacks = []  # holds callbacks specific to mouse movement
g_mouse_wheel_callbacks = []  # holds callbacks specific to mouse wheel
g_suppress_mouse = 0  # block stack for mouse (shift + esc to terminate)
g_suppress_keyboard = 0  # block stack for keyboard (shift + esc to terminate)
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
        for cb in list(callbacks):
            try:
                cb(*args)
            except Exception as e:
                syslog.error(f"Error in hook callback execution: {e}")


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
    return win32api.GetLastError()


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

user32.TranslateMessage.argtypes = (wintypes.LPMSG,)
user32.DispatchMessageW.argtypes = (wintypes.LPMSG,)

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
    msg = ctypes.cast(l_param, LPKBDLLHOOKSTRUCT)[0]

    if n_code >= 0 and msg.scanCode:
        virtual_code = msg.vkCode
        scan_code = msg.scanCode & 0xFF
        is_extended = msg.flags is not None and bool(msg.flags & 0x0001)
        is_pressed = w_param in [0x0100, 0x0104]
        is_injected = msg.flags is not None and bool(msg.flags & 0x0010)

        if scan_code == 0x2A:
            g_shift_state = is_pressed

        if msg.scanCode != 541:
            evt = KeyEvent(
                virtual_code=virtual_code,
                scan_code=scan_code,
                is_extended=is_extended,
                is_pressed=is_pressed,
                is_injected=is_injected,
            )
            if g_keyboard_callbacks:
                _event_queue.put((list(g_keyboard_callbacks), (evt,)))

        if scan_code == 0x01 and g_shift_state:
            g_suppress_keyboard = 0
            g_suppress_mouse = 0

        if g_suppress_keyboard != 0:
            # if g_verbose_keyboard:
            #     syslog.info(
            #         f"KBDHK: suppress: [{g_suppress_keyboard}] vk [{virtual_code}] sc [{scan_code:x}] ext [{is_extended}]"
            #     )
            return 1

        # if g_verbose_keyboard:
        #     syslog.info(
        #         f"KBDHK: nexthook: [{g_suppress_keyboard}] vk [{virtual_code}] sc [{scan_code:x}] ext [{is_extended}]"
        #     )

    return user32.CallNextHookEx(None, n_code, w_param, l_param)


_mouse_wheel_state = {}
_mouse_wheel_delay = 0.5
_mouse_wheel_timer = {}
_mouse_x = None
_mouse_y = None  # Fixed typo: _mouxe_y -> _mouse_y

_wheel_cmd_queue: queue.SimpleQueue | None = None
_wheel_worker: threading.Thread | None = None
_wheel_worker_stop = threading.Event()
_wheel_lock = threading.RLock()


def _ensure_wheel_worker():
    global _wheel_cmd_queue, _wheel_worker
    if _wheel_worker is not None and _wheel_worker.is_alive():
        return
    _wheel_worker_stop.clear()
    _wheel_cmd_queue = queue.SimpleQueue()
    _wheel_worker = threading.Thread(
        target=_wheel_worker_loop,
        name="mouse-wheel-release",
        daemon=True,
    )
    _wheel_worker.start()


def _wheel_worker_loop():
    global _mouse_wheel_timer
    q = _wheel_cmd_queue
    while not _wheel_worker_stop.is_set():
        try:
            cmd = q.get(timeout=0.5) # @IgnoreException
        except queue.Empty:
            continue
        if cmd is None:
            break
        op = cmd[0]
        if op == "arm":
            button_id = cmd[1]
            delay = float(cmd[2]) if len(cmd) > 2 else _mouse_wheel_delay
            with _wheel_lock:
                old = _mouse_wheel_timer.get(button_id)
                if old is not None:
                    try:
                        old.cancel()
                    except RuntimeError:
                        pass
                timer = threading.Timer(delay, _queue_wheel_release, args=(button_id,))
                _mouse_wheel_timer[button_id] = timer
                try:
                    timer.start()
                except RuntimeError:
                    _mouse_wheel_timer[button_id] = None
                    _queue_wheel_release(button_id)
        elif op == "cancel":
            button_id = cmd[1]
            with _wheel_lock:
                old = _mouse_wheel_timer.get(button_id)
                if old is not None:
                    try:
                        old.cancel()
                    except RuntimeError:
                        pass
                    _mouse_wheel_timer[button_id] = None
        elif op == "stop":
            break


def _arm_wheel_release(button_id):
    _ensure_wheel_worker()
    if _wheel_cmd_queue is not None:
        _wheel_cmd_queue.put(("arm", button_id, _mouse_wheel_delay))


def _cancel_wheel_release(button_id):
    _ensure_wheel_worker()
    if _wheel_cmd_queue is not None:
        _wheel_cmd_queue.put(("cancel", button_id))


_is_runtime = False


def setRunning(value: bool):
    global _is_runtime
    _is_runtime = value


def getMousePosition(self):
    global _mouse_x, _mouse_y
    return (_mouse_x, _mouse_y)


@HOOKPROC
def process_mouse_event(n_code, w_param, l_param):
    import gremlin.types

    global g_mouse_callbacks, _is_runtime, _mouse_x, _mouse_y
    global g_mouse_move_callbacks, g_mouse_wheel_callbacks
    global g_suppress_mouse

    verbose = False
    if n_code == HC_ACTION:
        msg = ctypes.cast(l_param, LPMSLLHOOKSTRUCT)[0]

        button_id = None
        release_button_id = None  # Guarded against UnboundLocalError
        is_pressed = True
        is_wheel = False
        process = False

        if w_param in [WM_LBUTTONDOWN, WM_LBUTTONUP]:
            button_id = gremlin.types.MouseButton.Left
            is_pressed = w_param == WM_LBUTTONDOWN
            process = True
        elif w_param in [WM_RBUTTONDOWN, WM_RBUTTONUP]:
            button_id = gremlin.types.MouseButton.Right
            is_pressed = w_param == WM_RBUTTONDOWN
            process = True
        elif w_param in [WM_MBUTTONDOWN, WM_MBUTTONUP]:
            button_id = gremlin.types.MouseButton.Middle
            is_pressed = w_param == WM_MBUTTONDOWN
            process = True
        elif w_param in [WM_XBUTTONDOWN, WM_XBUTTONUP]:
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
                    (list(g_mouse_wheel_callbacks), (delta, False))
                )
        elif w_param == WM_MOUSEHWHEEL:
            delta = msg.mouseData >> 16
            if delta == 120:
                button_id = gremlin.types.MouseButton.WheelRight
                release_button_id = gremlin.types.MouseButton.WheelLeft
            elif delta == 65416:
                button_id = gremlin.types.MouseButton.WheelLeft
                release_button_id = gremlin.types.MouseButton.WheelRight
            is_wheel = True
            if g_mouse_wheel_callbacks:
                _event_queue.put(
                    (list(g_mouse_wheel_callbacks), (delta, True))
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
                    (list(g_mouse_move_callbacks), (_mouse_x, _mouse_y))
                )

        if is_wheel and button_id:
            global _mouse_wheel_delay, _mouse_wheel_state
            # if verbose:
            #     syslog.info(f"wheel press {button_id}")

            process = True
            if _is_runtime:
                if _mouse_wheel_state.get(button_id, False):
                    process = False
                else:
                    _mouse_wheel_state[button_id] = True

                _arm_wheel_release(button_id)

                if release_button_id and _mouse_wheel_state.get(
                    release_button_id, False
                ):
                    # if verbose:
                    #     syslog.info(f"wheel timer reset {release_button_id}")
                    _queue_wheel_release(release_button_id)

        if process and button_id:
            # if verbose:
            #     syslog.info(f"Mouse event press: {button_id}")
            evt = MouseEvent(button_id, is_pressed, False)
            if g_mouse_callbacks:
                _event_queue.put((list(g_mouse_callbacks), (evt,)))

    if g_suppress_mouse == 0:
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    return 1


def _queue_wheel_release(button_id):
    global g_mouse_callbacks, _mouse_wheel_timer, _mouse_wheel_state
    verbose = False
    if _mouse_wheel_state.get(button_id):
        if verbose:
            syslog.info(f"wheel release {button_id}")
        _mouse_wheel_state[button_id] = False
        with _wheel_lock:
            timer = _mouse_wheel_timer.get(button_id)
            if timer is not None:
                try:
                    timer.cancel()
                except RuntimeError:
                    pass
                _mouse_wheel_timer[button_id] = None

        evt = MouseEvent(button_id, False, False)
        if g_mouse_callbacks:
            _event_queue.put((list(g_mouse_callbacks), (evt,)))


@gremlin.singleton_decorator.SingletonDecorator
class KeyboardHook:
    def __init__(self):
        self._running = False
        self._listen_thread = None

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
        if callback not in g_keyboard_callbacks:
            g_keyboard_callbacks.append(callback)
        self.start()

    def unregister(self, callback):
        global g_keyboard_callbacks
        if callback and callback in g_keyboard_callbacks:
            g_keyboard_callbacks.remove(callback)

    def start(self):
        if self._running:
            return
        if self._listen_thread is None:
            self._listen_thread = threading.Thread(
                target=self._listen, daemon=True
            )
            self._listen_thread.name = "keyboard hook"
        self._running = True
        self._listen_thread.start()

    def stop(self):
        if self._running:
            self._running = False
            user32.PostThreadMessageW(self._listen_thread.ident, WM_QUIT, 0, 0)
            gremlin.util.safeJoin(self._listen_thread)
            self._listen_thread = None

    def shutdown(self):
        self.stop()
        syslog.info("KBD: shutdown")

    def _listen(self):
        self.hook_id = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, process_keyboard_event, None, 0
        )

        msg = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if not result:
                break
            if result == -1:
                raise ctypes.WinError(get_last_error())
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


@gremlin.singleton_decorator.SingletonDecorator
class MouseHook:
    def __init__(self):
        import gremlin.config
        import gremlin.types

        self._running = False
        self._listen_thread = None

        global _mouse_wheel_state, _mouse_wheel_timer, _mouse_wheel_delay
        wheel_buttons = [
            gremlin.types.MouseButton.WheelDown,
            gremlin.types.MouseButton.WheelUp,
            gremlin.types.MouseButton.WheelLeft,
            gremlin.types.MouseButton.WheelRight,
        ]
        for button_id in wheel_buttons:
            _mouse_wheel_state[button_id] = False
            _mouse_wheel_timer[button_id] = None

        _mouse_wheel_delay = (
            gremlin.config.Configuration().mouse_wheel_autorelease_delay
        )
        _ensure_wheel_worker()

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
        if callback and callback not in g_mouse_callbacks:
            g_mouse_callbacks.append(callback)
            self.start()

    def registerMouseMove(self, callback):
        global g_mouse_move_callbacks
        if callback and callback not in g_mouse_move_callbacks:
            g_mouse_move_callbacks.append(callback)
            self.start()

    def registerMouseWheel(self, callback):
        global g_mouse_wheel_callbacks
        if callback and callback not in g_mouse_wheel_callbacks:
            g_mouse_wheel_callbacks.append(callback)
            self.start()

    def unregister(self, callback):
        global g_mouse_callbacks
        if callback in g_mouse_callbacks:
            g_mouse_callbacks.remove(callback)

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

    def unregisterMouseWheel(self, callback):
        global g_mouse_wheel_callbacks
        if callback in g_mouse_wheel_callbacks:
            g_mouse_wheel_callbacks.remove(callback)

    def start(self):
        if self._running:
            return
        if self._listen_thread is None:
            self._listen_thread = threading.Thread(
                target=self._listen, daemon=False
            )
            self._listen_thread.name = "mouse hook"
        try:
            self._listen_thread.start()
            self._running = True
        except Exception:
            syslog.error("MOUSE HOOK: unable to create listen thread")

    def stop(self):
        if self._running:
            self._running = False
            user32.PostThreadMessageW(self._listen_thread.ident, WM_QUIT, 0, 0)
            gremlin.util.safeJoin(self._listen_thread)
            self._listen_thread = None
            self._stop_timers()

    def shutdown(self):
        self.stop()
        syslog.info("MOUSE: shutdown")
        if self._listen_thread:
            gremlin.util.safeJoin(self._listen_thread)
            self._listen_thread = None

    def _stop_timers(self):
        global _mouse_wheel_timer, _wheel_cmd_queue, _wheel_worker
        with _wheel_lock:
            for id in list(_mouse_wheel_timer.keys()):
                if _mouse_wheel_timer[id]:
                    try:
                        _mouse_wheel_timer[id].cancel()
                    except RuntimeError:
                        pass
                    _mouse_wheel_timer[id] = None
        _wheel_worker_stop.set()
        if _wheel_cmd_queue is not None:
            try:
                _wheel_cmd_queue.put(None)
            except Exception:
                pass
        if _wheel_worker is not None and _wheel_worker.is_alive():
            _wheel_worker.join(timeout=1.0)
        _wheel_worker = None

    def _listen(self):
        self.hook_id = user32.SetWindowsHookExW(
            WH_MOUSE_LL, process_mouse_event, None, 0
        )

        msg = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if not result:
                break
            if result == -1:
                raise ctypes.WinError(get_last_error())

            if g_suppress_mouse == 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

    @property
    def is_swapped(self) -> bool:
        return self._is_swapped


_mouse_hook = MouseHook()