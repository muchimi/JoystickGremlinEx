# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""Select a top-level Windows application window with a crosshair."""

import pywintypes
import win32con
import win32gui
from PySide6 import QtCore, QtGui, QtWidgets

import action_plugins.map_to_application.win32_core as core
from gremlin.ui.ui_common import QIconPushButton


class _WindowOutline(QtWidgets.QWidget):
    """An input-transparent border positioned in Win32 screen coordinates."""

    def __init__(self, parent):
        super().__init__(
            parent,
            QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowTransparentForInput
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background: transparent;")

    def show_at(self, bounds):
        left, top, right, bottom = bounds
        self.show()
        win32gui.SetWindowPos(
            int(self.winId()),
            win32con.HWND_TOPMOST,
            left,
            top,
            right - left,
            bottom - top,
            win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER,
        )

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(QtGui.QPen(QtGui.QColor("black"), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        painter.setPen(QtGui.QPen(QtGui.QColor("white"), 2))
        painter.drawRect(self.rect().adjusted(3, 3, -4, -4))


class WindowPickerButton(QIconPushButton):
    """Select a window by dragging the crosshair or clicking the target."""

    picking_started = QtCore.Signal()
    window_picked = QtCore.Signal(str, str)
    status_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        self._timer = None
        super().__init__(
            "Pick...",
            icon="mdi.crosshairs",
            parent=parent,
            tooltip="Click, then click a target window, or drag the crosshair onto it. Press Esc to cancel.",
            icon_size=16,
        )

        self._outline = _WindowOutline(self)
        self._bounds = None
        self._awaiting_target_click = False
        self._timer = QtCore.QTimer(self, interval=30)
        self._timer.timeout.connect(self._update_outline)
        self.clicked.connect(self._arm)

    def eventFilter(self, watched, event):
        if watched is not self or self._timer is None:
            return super().eventFilter(watched, event)

        event_type = event.type()
        if event_type == QtCore.QEvent.Type.MouseButtonPress and event.button() == QtCore.Qt.MouseButton.LeftButton:  # noqa: SIM102
            if self.isEnabled():
                if not self._timer.isActive():
                    self._start()
                return True
        if self._timer.isActive():
            if event_type == QtCore.QEvent.Type.MouseButtonRelease and event.button() == QtCore.Qt.MouseButton.LeftButton:
                over_button = self.rect().contains(event.position().toPoint())
                if over_button and not self._awaiting_target_click:
                    self._awaiting_target_click = True
                elif over_button:
                    self.cancel()
                else:
                    self._finish()
                return True
            if (
                event_type in (QtCore.QEvent.Type.ShortcutOverride, QtCore.QEvent.Type.KeyPress)
                and event.key() == QtCore.Qt.Key.Key_Escape
            ):
                event.accept()
                if event_type == QtCore.QEvent.Type.KeyPress:
                    self.cancel()
                return True
            if event_type in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.UngrabMouse):
                self.cancel()
        return super().eventFilter(watched, event)

    def _arm(self):
        if self._timer.isActive():
            self.cancel()
        else:
            self._start()
            self._awaiting_target_click = True

    def _start(self):
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self.setDown(True)
        self._timer.start()
        self.grabMouse(QtGui.QCursor(QtCore.Qt.CursorShape.CrossCursor))
        self.picking_started.emit()
        self.status_changed.emit("Click a target window, or drag onto it and release. Press Esc to cancel.")

    def cancel(self):
        if self._timer.isActive():
            self._stop()
            self.status_changed.emit("Window pick cancelled.")

    def _stop(self):
        self._timer.stop()
        self._outline.hide()
        self._bounds = None
        self._awaiting_target_click = False
        self.setDown(False)
        if QtWidgets.QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def _window_under_cursor(self):
        point = core.cursor_pos()
        hit = win32gui.WindowFromPoint((point.x, point.y))
        if hit:
            window = win32gui.GetAncestor(hit, win32con.GA_ROOT)
            if window and window not in (int(self.window().winId()), win32gui.GetDesktopWindow()):
                return window
        return None

    def _update_outline(self):
        try:
            window = self._window_under_cursor()
            if self._outline.isVisible() and window == int(self._outline.winId()):
                return
            bounds = win32gui.GetWindowRect(window) if window else None
            if bounds and bounds != self._bounds:
                self._outline.show_at(bounds)
            elif not bounds:
                self._outline.hide()
            self._bounds = bounds
        except pywintypes.error:
            # The window can close between hit testing and reading its bounds.
            self._outline.hide()
            self._bounds = None

    def _finish(self):
        self._stop()
        try:
            window = self._window_under_cursor()
            if window:
                program, _ = core.process_name(window)
                title = core.window_title(window).strip()
                if program and win32gui.IsWindow(window):
                    self.status_changed.emit(f"Selected {program}.")
                    self.window_picked.emit(program, title)
                    return
        except pywintypes.error:
            # A window that closes during selection leaves the current target intact.
            pass
        self.status_changed.emit("Could not select a window. Try picking an open application window.")
