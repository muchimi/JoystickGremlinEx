# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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
import threading
import time
import gremlin.common
import gremlin.event_handler
import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator


user32 = ctypes.WinDLL("user32")


g_keyboard_callbacks = []
g_mouse_callbacks = []
import win32api
import logging


class KeyEvent:

    """Structure containing details about a key event."""

    def __init__(self, virtual_code, scan_code, is_extended, is_pressed, is_injected):
        """Creates a new instance with the given data.
        :param virtual_code the virtual keyboard code this event
        :param scan_code the hardware scan code of this event
        :param is_extended whether or not the scan code is an extended one
        :param is_pressed flag indicating if the key is pressed
        :param is_injected flag indicating if the event has been injected
        """
        self._virtual_code = virtual_code
        self._scan_code = scan_code
        self._is_extended = is_extended
        self._is_pressed = is_pressed
        self._is_injected = is_injected

    def __str__(self):
        """Returns a string representation of the event.

        :return string representation of the event
        """
        return f"(virtual: {hex(self._virtual_code)}  scancode/extended ({hex(self._scan_code)} {self._is_extended}) {"down" if self._is_pressed else "up"}, {"injected" if self.is_injected else ""}"

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
    
def get_last_error():
    ''' last error implementatoin'''
    return win32api.GetLastError()


# The following pages are references to the various functions used:
#
# SetWindowsHookEx
#     https://msdn.microsoft.com/en-us/library/windows/desktop/ms644990(v=vs.85).aspx
# LowLevelMouseProc
#     https://msdn.microsoft.com/de-de/library/windows/desktop/ms644986(v=vs.85).aspx
# MSLLHOOKSTRUCT
#     https://msdn.microsoft.com/en-us/library/ms644970(v=vs.85).aspx
# LowLevelKeyboardProc
#     https://msdn.microsoft.com/en-us/library/ms644985(v=vs.85).aspx
# KBDLLHOOKSTRUCT
#     https://msdn.microsoft.com/en-us/library/windows/desktop/ms644967(v=vs.85).aspx

# Signature of a hook callback function which can be used as a decorator
HOOKPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM
)

# Function to hook into an event stream
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = (
    ctypes.c_int,           # _In_ idHook
    HOOKPROC,               # _In_ lpfn
    wintypes.HINSTANCE,     # _In_ hMod
    wintypes.DWORD          # _In_ dwThreadId
)

# Function to call next hook in the chain
user32.CallNextHookEx.restype = wintypes.LPARAM
user32.CallNextHookEx.argtypes = (
    wintypes.HHOOK,         # _In_opt_ hhk
    ctypes.c_int,           # _In_     nCode
    wintypes.WPARAM,        # _In_     wParam
    wintypes.LPARAM         # _In_     lParam
)

# Retrieve a single message from a stream
user32.GetMessageW.argtypes = (
    wintypes.LPMSG,         # _Out_    lpMsg
    wintypes.HWND,          # _In_opt_ hWnd
    wintypes.UINT,          # _In_     wMsgFilterMin
    wintypes.UINT           # _In_     wMsgFilterMax
)

# Convert message content
user32.TranslateMessage.argtypes = (wintypes.LPMSG,)

# Dispatch message to hooked processes
user32.DispatchMessageW.argtypes = (wintypes.LPMSG,)

# Action definitions
HC_ACTION       = 0
WH_KEYBOARD_LL  = 13
WH_MOUSE_LL     = 14

WM_QUIT         = 0x0012
WM_MOUSEMOVE    = 0x0200
WM_LBUTTONDOWN  = 0x0201
WM_LBUTTONUP    = 0x0202
WM_RBUTTONDOWN  = 0x0204
WM_RBUTTONUP    = 0x0205
WM_MBUTTONDOWN  = 0x0207
WM_MBUTTONUP    = 0x0208
WM_MOUSEWHEEL   = 0x020A
WM_XBUTTONDOWN  = 0x020B
WM_XBUTTONUP    = 0x020C
WM_MOUSEHWHEEL  = 0x020E




class KBDLLHOOKSTRUCT(ctypes.Structure):

    """Data structure used with keuboard callbacks."""

    _fields_ = (
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM)
    )
LPKBDLLHOOKSTRUCT = ctypes.POINTER(KBDLLHOOKSTRUCT)


class MSLLHOOKSTRUCT(ctypes.Structure):

    """Data structure used with mouse callbacks."""

    _fields_ = (
        ("pt",          wintypes.POINT),
        ("mouseData",   wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM)
    )
LPMSLLHOOKSTRUCT = ctypes.POINTER(MSLLHOOKSTRUCT)


@HOOKPROC
def process_keyboard_event(n_code, w_param, l_param):
    """Process a single keyboard event.

    :param n_code code detailing how to process the event
    :param w_param message type identifier
    :param l_param message content
    """
    msg = ctypes.cast(l_param, LPKBDLLHOOKSTRUCT)[0]

    # Only handle events we're supposed to, see
    # https://msdn.microsoft.com/en-us/library/windows/desktop/ms644985(v=vs.85).aspx
    if n_code >= 0 and msg.scanCode:
        # Extract data from the message
        virtual_code = msg.vkCode
        scan_code = msg.scanCode & 0xFF
        is_extended = msg.flags is not None and bool(msg.flags & 0x0001)
        is_pressed = w_param in [0x0100, 0x0104]
        is_injected = msg.flags is not None and bool(msg.flags & 0x0010)

        #print (f"****** KEYBOARD HOOK: raw scancode: 0x{msg.scanCode:X} w_param: 0x{w_param:X} flags: 0x{msg.flags:X} scan code: {scan_code} (0x{scan_code:x}) ext: {is_extended} pressed: {is_pressed}")


        # A scan code of 541 indicates AltGr being pressed. AltGr is sent
        # as a combination of RAlt + RCtrl to the system and as such
        # generates two key events, one for RAlt and one for RCtrl. The
        # RCtrl one is being modified due to RAlt being pressed.
        #
        # In this application we want the RAlt key press and ignore the
        # RCtrl key press.

        # Create the event and pass it to all all registered callbacks
        if msg.scanCode != 541:
            evt = KeyEvent(virtual_code = virtual_code, scan_code = scan_code, is_extended = is_extended, is_pressed = is_pressed, is_injected = is_injected)
            for cb in g_keyboard_callbacks:
                cb(evt)

    # Pass the event on to the next callback in the chain
    return user32.CallNextHookEx(None, n_code, w_param, l_param)

_mouse_h_wheel_time = None
_mouse_v_wheel_time = None

@HOOKPROC
def process_mouse_event(n_code, w_param, l_param):
    """Process a single mouse event.

    :param n_code code detailing how to process the event
    :param w_param message type identifier
    :param l_param message content
    """
    if n_code == HC_ACTION and w_param != WM_MOUSEMOVE:
        msg = ctypes.cast(l_param, LPMSLLHOOKSTRUCT)[0]

        # Only handle events we're supposed to, see
        # https://msdn.microsoft.com/en-us/library/windows/desktop/ms644985(v=vs.85).aspx
        button_id = None
        is_pressed = True
        is_wheel = False
        if w_param in [WM_LBUTTONDOWN, WM_LBUTTONUP]:
            button_id = gremlin.types.MouseButton.Left
            is_pressed = w_param == WM_LBUTTONDOWN
        elif w_param in [WM_RBUTTONDOWN, WM_RBUTTONUP]:
            button_id = gremlin.types.MouseButton.Right
            is_pressed = w_param == WM_RBUTTONDOWN
        elif w_param in [WM_MBUTTONDOWN, WM_MBUTTONUP]:
            button_id = gremlin.types.MouseButton.Middle
            is_pressed = w_param == WM_MBUTTONDOWN
        elif w_param in [WM_XBUTTONDOWN, WM_XBUTTONUP]:
            if msg.mouseData & (0x0001 << 16):
                button_id = gremlin.types.MouseButton.Back
            elif msg.mouseData & (0x0002 << 16):
                button_id = gremlin.types.MouseButton.Forward
            is_pressed = w_param == WM_XBUTTONDOWN
        elif w_param == WM_MOUSEWHEEL:
            process = False
            global _mouse_v_wheel_time
            if not _mouse_v_wheel_time:
                _mouse_v_wheel_time = time.time()
                process = True
            else:
                current_time = time.time()
                time_delta = (current_time - _mouse_v_wheel_time) * 1000 # in milliseconds
                _mouse_v_wheel_time = current_time
                process = time_delta > 500 # half a second
            if process:
                delta = msg.mouseData >> 16
                # print (f"mouse V received: data {msg.mouseData} (0x{msg.mouseData:X})  flags: {msg.flags} (0x{msg.flags:X}) time: {msg.time} (0x{msg.time:X}) extra: {msg.dwExtraInfo} (0x{msg.dwExtraInfo:X})  delta: {delta} (0x{delta:x})  delta / 120: {delta/120}")
                if delta == 120:
                    button_id = gremlin.types.MouseButton.WheelUp
                elif delta == 65416: # -120
                    button_id = gremlin.types.MouseButton.WheelDown
                is_wheel = True
        elif w_param == WM_MOUSEHWHEEL:
            # horizontal mouse wheel  https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-mousehwheel
            process = False
            global _mouse_h_wheel_time
            if not _mouse_h_wheel_time:
                _mouse_h_wheel_time = time.time()
                process = True
            else:
                current_time = time.time()
                time_delta = (current_time - _mouse_h_wheel_time) * 1000 # in milliseconds
                _mouse_h_wheel_time = current_time
                process = time_delta > 500 # half a second

            if process:
                delta = msg.mouseData >> 16
                # print (f"mouse H received: data {msg.mouseData} (0x{msg.mouseData:X})  flags: {msg.flags} (0x{msg.flags:X}) time: {msg.time} (0x{msg.time:X}) extra: {msg.dwExtraInfo} (0x{msg.dwExtraInfo:X})  delta: {delta} (0x{delta:x})  delta / 120: {delta/120}")
                if delta == 120:
                    button_id = gremlin.types.MouseButton.WheelRight
                elif delta == 65416: # -120
                    button_id = gremlin.types.MouseButton.WheelLeft
                is_wheel = True

        # if button_id:
        #     logging.getLogger("system").info(f"Mouse button: {button_id}")

        if button_id:
            # Create the event and pass it to all all registered callbacks
            evt = MouseEvent(button_id, is_pressed, False)
            if is_wheel:
                # queue a release event for mouse wheel 
                threading.Thread(target=lambda: _queue_wheel_release(button_id)).start()
            for cb in g_mouse_callbacks:
                cb(evt)

    # Pass the event on to the next callback in the chain
    return user32.CallNextHookEx(None, n_code, w_param, l_param)



def _queue_wheel_release(button_id):
    ''' queues a mouse wheel release for wheel events '''
    import time
    # print (f"wheel release: {button_id}")
    time.sleep(0.1)
    evt = MouseEvent(button_id, False, False)
    for cb in g_mouse_callbacks:
        cb(evt)



@SingletonDecorator
class KeyboardHook:

    """Hooks into the event stream and grabs keyboard related events
    and passes them on to registered callback functions.
    """

    def __init__(self):
        self._running = False
        self._listen_thread = threading.Thread(target=self._listen)
        

    def register(self, callback):
        """Registers a new message callback.

        :param callback the new callback to register
        """
        global g_keyboard_callbacks
        g_keyboard_callbacks.append(callback)

    def start(self):
        """Starts the hook if it is not yet running."""
        if self._running:
            return
        self._running = True
        self._listen_thread.start()

    def stop(self):
        """Stops the hook from running."""
        syslog = logging.getLogger("system")
        syslog.info("KEYBOARD: shutdown")
        if self._running:
            self._running = False
            user32.PostThreadMessageW(self._listen_thread.ident, WM_QUIT, 0, 0)
            self._listen_thread.join()
            # Recreate thread so we can launch it again
            self._listen_thread = threading.Thread(target=self._listen)

    def _listen(self):
        """Configures the hook and starts listening."""
        self.hook_id = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            process_keyboard_event,
            None,
            0
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



@SingletonDecorator
class MouseHook:

    """Hooks into the event stream and grabs mouse related events
    and passes them on to registered callback functions.
    """

    def __init__(self):
        self._running = False
        self._listen_thread = threading.Thread(target=self._listen)

    def register(self, callback):
        """Registers a new message callback.

        :param callback the new callback to register
        """
        global g_mouse_callbacks
        g_mouse_callbacks.append(callback)

    def start(self):
        """Starts the hook if it is not yet running."""
        if self._running:
            return
        self._running = True
        self._listen_thread.start()

    def stop(self):
        """Stops the hook from running."""
        syslog = logging.getLogger("system")
        syslog.info("MOUSE: shutdown")
        if self._running:
            self._running = False
            user32.PostThreadMessageW(self._listen_thread.ident, WM_QUIT, 0, 0)
            self._listen_thread.join()
            # Recreate thread so we can launch it again
            self._listen_thread = threading.Thread(target=self._listen)

    def _listen(self):
        """Configures the hook and starts listening."""
        self.hook_id = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            process_mouse_event,
            None,
            0
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
            
