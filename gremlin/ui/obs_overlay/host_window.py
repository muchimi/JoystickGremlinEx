# -*- coding: utf-8; -*-
#
# Parent the live overlay HWND into another window so Discord / similar
# application-share capture can include it. Screen share already composites
# a separate overlay; app share only captures that process's window tree.

from __future__ import annotations

import logging
import sys

syslog = logging.getLogger("system")

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CLIPSIBLINGS = 0x04000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
    else:
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
    return user32


def _get_style(user32, hwnd: int) -> int:
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return int(user32.GetWindowLongPtrW(hwnd, GWL_STYLE) or 0)
    return int(user32.GetWindowLongW(hwnd, GWL_STYLE) or 0)


def _set_style(user32, hwnd: int, style: int) -> None:
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
    else:
        user32.SetWindowLongW(hwnd, GWL_STYLE, style)


def host_client_size(hwnd: int) -> tuple[int, int]:
    if sys.platform != "win32" or not hwnd:
        return (0, 0)
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _user32()
        if not user32.IsWindow(hwnd):
            return (0, 0)
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return (0, 0)
        return (max(0, int(rect.right)), max(0, int(rect.bottom)))
    except Exception:
        return (0, 0)


def attach_overlay_hwnd(overlay_hwnd: int, host_hwnd: int) -> bool:
    """Make the overlay a child of *host_hwnd* so window capture can include it."""
    if sys.platform != "win32" or not overlay_hwnd or not host_hwnd:
        return False
    try:
        user32 = _user32()
        if not user32.IsWindow(overlay_hwnd) or not user32.IsWindow(host_hwnd):
            return False
        style = _get_style(user32, overlay_hwnd)
        style = (style | WS_CHILD | WS_CLIPSIBLINGS) & ~WS_POPUP
        _set_style(user32, overlay_hwnd, style)
        user32.SetParent(overlay_hwnd, host_hwnd)
        user32.SetWindowPos(
            overlay_hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
        return True
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: attach to application window failed: {err}")
        return False


def place_overlay_in_host(overlay_hwnd: int, host_hwnd: int, width: int, height: int) -> bool:
    """Keep the overlay at the host client origin, clipped by the host."""
    if sys.platform != "win32" or not overlay_hwnd or not host_hwnd:
        return False
    try:
        user32 = _user32()
        if not user32.IsWindow(overlay_hwnd) or not user32.IsWindow(host_hwnd):
            return False
        cw, ch = host_client_size(host_hwnd)
        w = max(1, min(int(width or 1), cw or int(width or 1)))
        h = max(1, min(int(height or 1), ch or int(height or 1)))
        user32.SetWindowPos(
            overlay_hwnd,
            0,
            0,
            0,
            w,
            h,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        return True
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: place in application window failed: {err}")
        return False


def detach_overlay_hwnd(overlay_hwnd: int) -> None:
    """Restore a top-level overlay after attach_overlay_hwnd."""
    if sys.platform != "win32" or not overlay_hwnd:
        return
    try:
        user32 = _user32()
        if not user32.IsWindow(overlay_hwnd):
            return
        user32.SetParent(overlay_hwnd, 0)
        style = _get_style(user32, overlay_hwnd)
        style = (style | WS_POPUP) & ~WS_CHILD
        _set_style(user32, overlay_hwnd, style)
        user32.SetWindowPos(
            overlay_hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: detach from application window failed: {err}")
