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
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
ASFW_ANY = 0xFFFFFFFF
HWND_TOP = 0
HWND_NOTOPMOST = -2


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
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
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.ClipCursor.argtypes = [ctypes.c_void_p]
    user32.ClipCursor.restype = wintypes.BOOL
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


def _get_exstyle(user32, hwnd: int) -> int:
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0)
    return int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) or 0)


def _set_exstyle(user32, hwnd: int, style: int) -> None:
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
    else:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def apply_noactivate_exstyle(hwnd: int) -> None:
    """Mark *hwnd* so Windows will not give it foreground on show/parent changes."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = _user32()
        if not user32.IsWindow(hwnd):
            return
        style = _get_exstyle(user32, hwnd)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        _set_exstyle(user32, hwnd, style)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def restore_foreground(hwnd: int) -> None:
    """Force *hwnd* to the foreground (use sparingly — steals focus from JG Ex)."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _user32()
        if not user32.IsWindow(hwnd):
            return
        # Clear game cursor clip / capture that can make JG Ex feel dead.
        try:
            user32.ClipCursor(None)
        except Exception:
            pass
        try:
            user32.ReleaseCapture()
        except Exception:
            pass
        if int(user32.GetForegroundWindow() or 0) == int(hwnd):
            user32.BringWindowToTop(hwnd)
            return
        user32.AllowSetForegroundWindow(ASFW_ANY)
        kernel32 = ctypes.windll.kernel32
        fg = int(user32.GetForegroundWindow() or 0)
        pid = wintypes.DWORD()
        fg_tid = int(user32.GetWindowThreadProcessId(fg, ctypes.byref(pid)) or 0) if fg else 0
        host_tid = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or 0)
        cur = int(kernel32.GetCurrentThreadId())
        attached_fg = False
        attached_host = False
        try:
            if fg_tid and fg_tid != cur:
                attached_fg = bool(user32.AttachThreadInput(cur, fg_tid, True))
            if host_tid and host_tid != cur and host_tid != fg_tid:
                attached_host = bool(user32.AttachThreadInput(cur, host_tid, True))
            user32.BringWindowToTop(hwnd)
            user32.SetWindowPos(
                hwnd,
                HWND_TOP,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
            user32.SetForegroundWindow(hwnd)
        finally:
            # Always undo AttachThreadInput — a stuck attach makes the host
            # cursor/input appear over JG Ex and blocks the UI permanently.
            if attached_host:
                user32.AttachThreadInput(cur, host_tid, False)
            if attached_fg:
                user32.AttachThreadInput(cur, fg_tid, False)
    except Exception:
        pass


def release_input_hooks() -> None:
    """Drop cursor clip / mouse capture left behind by a host game."""
    if sys.platform != "win32":
        return
    try:
        user32 = _user32()
        user32.ClipCursor(None)
        user32.ReleaseCapture()
    except Exception:
        pass


def hide_overlay_hwnd(overlay_hwnd: int) -> None:
    """Native hide — Qt hide() is a no-op when isVisible() is already False after SetParent."""
    if sys.platform != "win32" or not overlay_hwnd:
        return
    try:
        user32 = _user32()
        if user32.IsWindow(overlay_hwnd):
            user32.ShowWindow(overlay_hwnd, SW_HIDE)
    except Exception:
        pass


def foreground_hwnd() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(_user32().GetForegroundWindow() or 0)
    except Exception:
        return 0


def restore_foreground_if_was(hwnd: int, previous_foreground: int) -> None:
    """Restore *hwnd* only if it previously held focus.

    Unconditional restore after app-share SetParent was putting the game
    (and its cursor) on top of JG Ex and making the UI feel dead.
    """
    if not hwnd or not previous_foreground:
        return
    if int(previous_foreground) != int(hwnd):
        return
    restore_foreground(hwnd)


def restore_previous_foreground(previous_foreground: int, host_hwnd: int = 0) -> None:
    """Put focus back where it was before SetParent, without promoting *host_hwnd*.

    SetParent often activates the host. If JG Ex (or anything else) had focus,
    give it back. If the host already had focus, leave it alone.
    """
    if not previous_foreground:
        return
    if host_hwnd and int(previous_foreground) == int(host_hwnd):
        return
    restore_foreground(previous_foreground)


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
        prev_fg = foreground_hwnd()
        apply_noactivate_exstyle(overlay_hwnd)
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
        # SetParent often activates the host. Put focus back where it was
        # (typically JG Ex). Only leave the host alone if it already had focus.
        restore_previous_foreground(prev_fg, host_hwnd)
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
        # NOZORDER: HWND_TOP here was raising the host over JG Ex every tick.
        user32.SetWindowPos(
            overlay_hwnd,
            0,
            0,
            0,
            w,
            h,
            SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW,
        )
        return True
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: place in application window failed: {err}")
        return False


def detach_overlay_hwnd(
    overlay_hwnd: int,
    restore_hwnd: int = 0,
    activate_host: bool = False,
    hide_window: bool = False,
) -> None:
    """Restore a top-level overlay after attach_overlay_hwnd.

    By default this does **not** raise *restore_hwnd* (the game). Forcing the
    host to the foreground on detach left its cursor on top of JG Ex after
    profile stop. Pass activate_host=True only when the host already had focus
    and must keep it mid-session.

    *hide_window*: after SetParent(0) the HWND can remain visible while Qt still
    thinks it is hidden — native SW_HIDE is required when tearing down.
    """
    if sys.platform != "win32" or not overlay_hwnd:
        return
    try:
        user32 = _user32()
        if not user32.IsWindow(overlay_hwnd):
            return
        host = int(restore_hwnd or 0)
        if not host:
            try:
                host = int(user32.GetParent(overlay_hwnd) or 0)
            except Exception:
                host = 0
        prev_fg = foreground_hwnd()
        # Hide while still a child so SetParent(0) cannot flash a full-size
        # top-level popup over JG Ex.
        if hide_window:
            user32.ShowWindow(overlay_hwnd, SW_HIDE)
        apply_noactivate_exstyle(overlay_hwnd)
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
        if hide_window:
            user32.ShowWindow(overlay_hwnd, SW_HIDE)
        release_input_hooks()
        if activate_host:
            restore_foreground_if_was(host, prev_fg)
        else:
            # Prefer whoever had focus before detach — never promote the game
            # over JG Ex when tearing the overlay down.
            restore_previous_foreground(prev_fg, host)
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: detach from application window failed: {err}")
