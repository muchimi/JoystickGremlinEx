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

'''
Handles raw mouse input at a very low level.
This API allows a client to register a callback for mouse movement.
If a callback is defined, the API hooks a custom message loop to trap low level WM_INPUT messages related to the mouse.
The messageloop only runs when a callback exists.

'''




import ctypes as ct
import ctypes.wintypes as w
import win32api, win32gui, win32con
import threading

import logging
syslog = logging.getLogger("system")

# Constants derived from WinSDK headers.
RIDEV_INPUTSINK = 0x00000100
RID_HEADER = 0x10000005
RID_INPUT = 0x10000003
WM_INPUT = 0x00FF
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02

# Types not available in ctypes.wintypes
LRESULT = ct.c_ssize_t
HCURSOR = ct.c_void_p
HRAWINPUT = ct.c_void_p

# callback prototype
WNDPROC = ct.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

# Use wintypes that exactly match MSDN documentation when possible.
class RAWINPUTDEVICE(ct.Structure):
    _fields_ = (('usUsagePage', w.USHORT),
                ('usUsage', w.USHORT),
                ('dwFlags', w.DWORD),
                ('hwndTarget', w.HWND))

class RAWINPUTHEADER(ct.Structure):
    _fields_ = (('dwType', w.DWORD),
                ('dwSize', w.DWORD),
                ('hDevice', w.HANDLE),
                ('wParam', w.WPARAM))

class DUMMYSTRUCTNAME(ct.Structure):
    _fields_ = (('usButtonFlags', w.USHORT),
                ('usButtonData', w.USHORT))

class DUMMYUNIONNAME(ct.Union):
    _anonymous_ = 's',
    _fields_ = (('ulButtons', w.ULONG),
                ('s', DUMMYSTRUCTNAME))
class RAWMOUSE(ct.Structure):
    _anonymous_ = 'u',
    _fields_ = (('usFlags', w.USHORT),
                ('u', DUMMYUNIONNAME),
                ('ulRawButtons', w.ULONG),
                ('lLastX', w.LONG),
                ('lLastY', w.LONG),
                ('ulExtraInformation', w.ULONG))

class RAWKEYBOARD(ct.Structure):
    _fields_ = (('MakeCode', w.USHORT),
                ('Flags', w.USHORT),
                ('Reserved', w.USHORT),
                ('vKey', w.USHORT),
                ('Message', w.UINT),
                ('ExtraInformation', w.ULONG))

class RAWHID(ct.Structure):
    _fields_ = (('dwSizeHid', w.DWORD),
                ('dwCount', w.DWORD),
                ('bRawData', w.BYTE * 1))

class DUMMYUNIONNAME(ct.Union):
    _fields_ = (('mouse', RAWMOUSE),
                ('keyboard', RAWKEYBOARD),
                ('hid', RAWHID))
class RAWINPUT(ct.Structure):
    _fields_ = (('header', RAWINPUTHEADER),
                ('data', DUMMYUNIONNAME))

class WNDCLASSW(ct.Structure):
    _fields_ = (('style', w.UINT),
                ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ct.c_int),
                ('cbWndExtra', ct.c_int),
                ('hInstance', w.HINSTANCE),
                ('hIcon', w.HICON),
                ('hCursor', HCURSOR),
                ('hbrBackground', w.HBRUSH),
                ('lpszMenuName', w.LPCWSTR),
                ('lpszClassName', w.LPCWSTR))

# Error checking handlers post-process function results
# and raise exceptions if the API fails.
def rawinputcheck(result, func, args):
    if result == w.UINT(-1).value:
        raise ct.OSError('GetRawInputData failed')
    return result

def zerocheck(result, func, args):
    if result == 0:
        raise ct.WinError(ct.get_last_error())
    return result

def nullcheck(result, func, args):
    if result is None:
        raise ct.WinError(ct.get_last_error())
    return result

def boolcheck(result, func, args):
    if result != 0:
        last_error = ct.get_last_error()
        syslog.info(last_error)
        #raise ct.WinError(ct.get_last_error())
    return None

user32 = ct.WinDLL('user32', use_last_error=True)
GetRawInputData = user32.GetRawInputData
GetRawInputData.argtypes = HRAWINPUT, w.UINT, w.LPVOID, w.PUINT, w.UINT
GetRawInputData.restype = w.UINT
GetRawInputData.errcheck = rawinputcheck
DefWindowProcW = user32.DefWindowProcW
DefWindowProcW.argtypes = w.HWND, w.UINT, w.WPARAM, w.LPARAM
DefWindowProcW.restype = LRESULT
RegisterClassW = user32.RegisterClassW
RegisterClassW.argtypes = ct.POINTER(WNDCLASSW),
RegisterClassW.restype = w.ATOM
# RegisterClassW.errcheck = zerocheck
CreateWindowExW = user32.CreateWindowExW
CreateWindowExW.argtypes = w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ct.c_int, ct.c_int, ct.c_int, ct.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID
CreateWindowExW.restype = w.HWND
CreateWindowExW.errcheck = nullcheck
RegisterRawInputDevices = user32.RegisterRawInputDevices
RegisterRawInputDevices.argtypes = ct.POINTER(RAWINPUTDEVICE), w.UINT, w.UINT
RegisterRawInputDevices.restype = w.BOOL
RegisterRawInputDevices.errcheck = boolcheck
GetMessageW = user32.GetMessageW
GetMessageW.argtypes = ct.POINTER(w.MSG), w.HWND, w.UINT, w.UINT
GetMessageW.restype = w.BOOL
GetMessageW.errcheck = boolcheck
TranslateMessage = user32.TranslateMessage
TranslateMessage.argtypes = ct.POINTER(w.MSG),
TranslateMessage.restype = w.BOOL
DispatchMessageW = user32.DispatchMessageW
DispatchMessageW.argtypes = ct.POINTER(w.MSG),
DispatchMessageW.restype = LRESULT

# globals
_raw_input_hooked = False
_raw_input_hwnd = None
_raw_input_thread = None
_raw_input_thread_id = None
_raw_input_running = False
_raw_input_callbacks = [] # callback to call when hooking the raw input (x,y)



def handle_raw_input(lparam):
    ''' called when a raw mouse input is received '''
    global _raw_input_callbacks
    if _raw_input_callbacks:
        raw_input_data = RAWINPUT()
        raw_input_size = w.UINT(ct.sizeof(raw_input_data))

        # convert to the delta values 
        GetRawInputData(HRAWINPUT(lparam), RID_INPUT, ct.byref(raw_input_data), ct.byref(raw_input_size), ct.sizeof(RAWINPUTHEADER))
        if raw_input_data.header.dwType == 0:
            dx = raw_input_data.data.mouse.lLastX
            dy = raw_input_data.data.mouse.lLastY
            for callback in _raw_input_callbacks:
                callback(dx, dy)
            

@WNDPROC 
def raw_input_wnd_proc(hwnd, msg, wparam, lparam):
    ''' custom message loop message processor '''
    if msg == WM_INPUT:
        handle_raw_input(lparam)
    elif msg == win32con.WM_QUIT:
            syslog.info("quit")
            return 0
    return DefWindowProcW(hwnd, msg, wparam, lparam)

def registerHook(callback):
    ''' registers a raw mouse input callback hook '''
    global _raw_input_hooked, _raw_input_hwnd, _raw_input_thread, _raw_input_running, _raw_input_callbacks
    if callback and not callback in _raw_input_callbacks:
        _raw_input_callbacks.append(callback)

    if not _raw_input_callbacks:
        # no callbacks to process - ignore
        return

    if _raw_input_hooked:
        # already hooked
        return
    
    # start the message loop if not started
    _raw_input_hooked = True
    _raw_input_running = True
    _raw_input_thread = threading.Thread(target = _raw_input_runner)
    _raw_input_thread.name = "raw input runner"
    _raw_input_thread.start()


    
def _raw_input_runner():
    ''' raw input message loop - each thread gets its own message loop'''
    global _raw_input_hooked, _raw_input_hwnd, _raw_input_thread, _raw_input_running, _raw_input_callbacks, _raw_input_thread_id

    #syslog.info("raw input thread start")

    # register a dummpy windows class for our message loop
    wndclass = WNDCLASSW()
    wndclass.lpfnWndProc = raw_input_wnd_proc
    wndclass.lpszClassName = 'RawInputClass'
    RegisterClassW(ct.byref(wndclass)) # will fail if registered a second time but we ignore that error

    # get a handle to our message loop
    hwnd = CreateWindowExW(0, 'RawInputClass', 'Raw Input Window', 0, 0, 0, 0, 0, None, None, None, None)

    # Register raw input device
    rid = RAWINPUTDEVICE()
    rid.usUsagePage = HID_USAGE_PAGE_GENERIC
    rid.usUsage = HID_USAGE_GENERIC_MOUSE
    rid.dwFlags = RIDEV_INPUTSINK
    rid.hwndTarget = hwnd

    RegisterRawInputDevices(ct.byref(rid), 1, ct.sizeof(rid)) # will also fail if already registered

    # grab the thread ID so we can send a quit message to it later
    _raw_input_thread_id = win32api.GetCurrentThreadId()

    win32gui.PumpMessages() # blocks until WM_QUIT is sent
    syslog.info("raw input thread terminate")


def registerUnhook(callback):
    ''' remove a registered raw mouse input callback '''
    global _raw_input_hooked, _raw_input_hwnd, _raw_input_thread, _raw_input_running, _raw_input_callbacks,_raw_input_thread_id
    if callback and callback in _raw_input_callbacks:
        _raw_input_callbacks.remove(callback)

    # kill the message loop if there are no more callbacks
    if not _raw_input_callbacks and _raw_input_hooked:
            _raw_input_running = False
            # kill the window
            win32api.PostThreadMessage(_raw_input_thread_id, win32con.WM_QUIT, 0, 0)
            # # win32gui.DestroyWindow(_raw_input_hwnd)
            # syslog.info("destroyed")
    
            # wait for the dispatch to finish
            if _raw_input_thread.is_alive():
                # wait for quit message to have been processed
                _raw_input_thread.join()
            _raw_input_thread = None
            _raw_input_hwnd = None
            _raw_input_hooked = False 





        