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
IDC_ARROW = 32512
GA_ROOT = 2
# Standard cursors LoadCursorW understands. A game cursor is none of these.
_SYSTEM_CURSOR_IDS = (
    32512, 32513, 32514, 32515, 32516,
    32640, 32641, 32642, 32643, 32644, 32645, 32646,
    32648, 32649, 32650, 32651,
)


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
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
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
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.GetCapture.argtypes = []
    user32.GetCapture.restype = wintypes.HWND
    user32.ClipCursor.argtypes = [ctypes.c_void_p]
    user32.ClipCursor.restype = wintypes.BOOL
    user32.SetCursor.argtypes = [wintypes.HANDLE]
    user32.SetCursor.restype = wintypes.HANDLE
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.GetCursorInfo.argtypes = [ctypes.c_void_p]
    user32.GetCursorInfo.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
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


def host_is_foreground(host_hwnd: int, overlay_hwnd: int = 0) -> bool:
    """True when the shared app, or the overlay parented into it, is the foreground window."""
    fg = foreground_hwnd()
    if not fg or not host_hwnd:
        return False
    if int(fg) == int(host_hwnd):
        return True
    if overlay_hwnd and int(fg) == int(overlay_hwnd):
        return True
    try:
        root = int(_user32().GetAncestor(fg, GA_ROOT) or 0)
    except Exception:
        root = 0
    return root == int(host_hwnd)


def foreground_is_this_process() -> bool:
    """True when the foreground window belongs to Joystick Gremlin Ex."""
    if sys.platform != "win32":
        return False
    fg = foreground_hwnd()
    if not fg:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _user32()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        return int(pid.value) == int(ctypes.windll.kernel32.GetCurrentProcessId())
    except Exception:
        return False


def _cursor_handle(user32) -> int:
    import ctypes
    from ctypes import wintypes

    class CURSORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hCursor", wintypes.HANDLE),
            ("ptScreenPos", wintypes.POINT),
        ]

    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(info)):
        return 0
    return int(info.hCursor or 0)


def separate_host_input(host_hwnd: int) -> None:
    """Undo the input join SetParent creates across processes.

    Cross-process SetParent attaches the two UI threads, so the game cursor
    stays on Joystick Gremlin Ex until this process exits. Detach only.
    AttachThreadInput(TRUE) is what left the pointer stuck before.
    """
    if sys.platform != "win32" or not host_hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _user32()
        if not user32.IsWindow(host_hwnd):
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        cur = int(kernel32.GetCurrentThreadId() or 0)
        pid = wintypes.DWORD()
        host_tid = int(user32.GetWindowThreadProcessId(int(host_hwnd), ctypes.byref(pid)) or 0)
        if not cur or not host_tid or cur == host_tid:
            return
        user32.AttachThreadInput(cur, host_tid, False)
        user32.AttachThreadInput(host_tid, cur, False)
    except Exception:
        pass


def _nudge_arrow_cursor() -> None:
    """Make Qt apply the arrow. SetCursor is ignored until the next mouse move."""
    try:
        from PySide6 import QtCore, QtGui, QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setOverrideCursor(QtCore.Qt.CursorShape.ArrowCursor)
            app.restoreOverrideCursor()
        pos = QtGui.QCursor.pos()
        QtGui.QCursor.setPos(pos.x() + 1, pos.y())
        QtGui.QCursor.setPos(pos)
    except Exception:
        pass


def _is_system_cursor(user32, handle: int) -> bool:
    if not handle:
        return True
    for ident in _SYSTEM_CURSOR_IDS:
        loaded = int(user32.LoadCursorW(None, ident) or 0)
        if loaded and loaded == handle:
            return True
    return False


def _capture_belongs_to_us(user32) -> bool:
    """True when this process holds the mouse, as it does while a window is dragged."""
    try:
        import ctypes
        from ctypes import wintypes

        captured = int(user32.GetCapture() or 0)
        if not captured:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(captured, ctypes.byref(pid))
        return int(pid.value) == int(ctypes.windll.kernel32.GetCurrentProcessId())
    except Exception:
        return False


def release_cursor_to_arrow(host_hwnd: int = 0) -> None:
    """Separate a joined game input queue and show the arrow. Does not change focus.

    Does not call ShowCursor. Undoing a ShowCursor(TRUE) loop hid the pointer.
    A text caret or resize cursor is left alone.
    ReleaseCapture is skipped while this process holds the mouse. The follow
    timer calls this every 250ms, and releasing that capture cancels a title-bar
    move or a border resize.
    """
    if sys.platform != "win32":
        return
    try:
        user32 = _user32()
        user32.ClipCursor(None)
        if not _capture_belongs_to_us(user32):
            user32.ReleaseCapture()
        if host_hwnd:
            separate_host_input(host_hwnd)
        current = _cursor_handle(user32)
        if _is_system_cursor(user32, current):
            return
        arrow = int(user32.LoadCursorW(None, IDC_ARROW) or 0)
        if arrow:
            user32.SetCursor(arrow)
            _nudge_arrow_cursor()
    except Exception:
        pass


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
        apply_noactivate_exstyle(overlay_hwnd)
        style = _get_style(user32, overlay_hwnd)
        style = (style | WS_CHILD | WS_CLIPSIBLINGS) & ~WS_POPUP
        _set_style(user32, overlay_hwnd, style)
        user32.SetParent(overlay_hwnd, host_hwnd)
        # Do not show or activate here. The follow timer shows the overlay
        # only while the shared app is foreground, and never steals focus.
        user32.SetWindowPos(
            overlay_hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        # SetParent joins the game's input queue. Separate before the game
        # cursor can stick to this process. Never pass TRUE.
        separate_host_input(host_hwnd)
        return True
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: attach to application window failed: {err}")
        return False


def place_overlay_in_host(overlay_hwnd: int, host_hwnd: int, width: int, height: int, *, show: bool = True) -> bool:
    """Keep the overlay at the host client origin, clipped by the host.

    *show* uses SWP_NOACTIVATE so the shared app keeps focus.
    """
    if sys.platform != "win32" or not overlay_hwnd or not host_hwnd:
        return False
    try:
        user32 = _user32()
        if not user32.IsWindow(overlay_hwnd) or not user32.IsWindow(host_hwnd):
            return False
        if not show:
            user32.ShowWindow(overlay_hwnd, SW_HIDE)
            return True
        cw, ch = host_client_size(host_hwnd)
        w = max(1, min(int(width or 1), cw or int(width or 1)))
        h = max(1, min(int(height or 1), ch or int(height or 1)))
        # NOZORDER: HWND_TOP here was raising the host over JG Ex every tick.
        # NOACTIVATE: sizing must not take focus from the shared app.
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

    This does not call SetForegroundWindow. *activate_host* is ignored so a
    page change cannot pull the shared app or Joystick Gremlin Ex forward.

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
        # SetParent(0) does not undo the input join. Detach it explicitly.
        if host:
            separate_host_input(host)
        if foreground_is_this_process():
            release_cursor_to_arrow(host)
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: detach from application window failed: {err}")
