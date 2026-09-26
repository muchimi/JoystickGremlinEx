# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
import sys
import time

import math

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.shared_state

from .bindings import OverlayValueBus, widget_accepts_touch, widget_conditions_match
from .model import DEFAULT_GUIDE_COLOR, OVERLAY_WINDOW_TITLE, OverlayScene, is_interactive_overlay, is_onscreen_mode, normalize_background_mode, overlay_window_title
from .qt_guard import alive
from .touch import OverlayTouchHandler
from .widgets import (
    chroma_fill_color,
    live_window_is_layered,
    paint_background,
    paint_widget,
    paint_widget_drop_shadow,
    qcolor,
    resolve_widget_shadow,
    set_live_fast_paint,
    widget_contains_point,
    widget_dirty_rect,
    widget_local_to_scene,
    widget_rect,
    widget_rotated_bounds,
    widget_rotation_deg,
    apply_widget_rotation,
)

ROTATE_HANDLE = 8

syslog = logging.getLogger("system")

DESIGNER_OVERFLOW_PAD = 48
DESIGNER_OVERFLOW_FILL = QtGui.QColor("#151a22")
DESIGNER_CANVAS_BORDER = QtGui.QColor("#7ec8ff")


def _transparent_palette(widget: QtWidgets.QWidget):
    widget.setAutoFillBackground(False)
    pal = widget.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 0))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(0, 0, 0, 0))
    widget.setPalette(pal)


def touchable_item_at(scene: OverlayScene, x: float, y: float, page_id: str | None = None):
    """Topmost overlay widget that may receive touch, or None for pass-through."""
    for item in reversed(scene.sorted_widgets(page_id)):
        if not item.get("visible", True):
            continue
        try:
            ix, iy = float(item["x"]), float(item["y"])
            iw, ih = float(item["w"]), float(item["h"])
        except (TypeError, ValueError, KeyError):
            continue
        if widget_contains_point(item, x, y) and widget_accepts_touch(item):
            return item
    return None


def _screen_point_from_lparam(lparam) -> QtCore.QPoint:
    import ctypes

    x = ctypes.c_int16(lparam & 0xFFFF).value
    y = ctypes.c_int16((lparam >> 16) & 0xFFFF).value
    return QtCore.QPoint(x, y)


def _nchittest_passthrough(widget: QtWidgets.QWidget, lparam) -> bool:
    """True when the cursor should fall through to the window behind."""
    scene = getattr(widget, "scene", None)
    if scene is None:
        return False
    page_id = getattr(widget, "page_id", None)
    canvas = scene.canvas_for(page_id)
    global_pos = _screen_point_from_lparam(lparam)
    if isinstance(widget, OverlayWindow):
        local = widget.mapFromGlobal(global_pos)
        if widget.drag_bar.isVisible() and widget.drag_bar.geometry().contains(local):
            return False
        view = getattr(widget, "view", None)
        if view is None or not Shiboken.isValid(view):
            return True
        vl = view.mapFrom(widget, local)
        if not view.rect().contains(vl):
            return True
        scene_pos = view.map_to_scene(QtCore.QPointF(vl))
        page_id = getattr(view, "page_id", page_id)
    else:
        local = widget.mapFromGlobal(global_pos)
        if not widget.rect().contains(local):
            return True
        scene_pos = widget.map_to_scene(QtCore.QPointF(local))

    # Runtime mouse-reposition: capture any widget (click retargets), or page canvas.
    if getattr(scene, "mouse_reposition_enabled", False):
        hit = scene.hit_test(scene_pos.x(), scene_pos.y(), page_id)
        if hit is not None:
            return False
        return not _reposition_target_hit(scene, scene_pos.x(), scene_pos.y(), page_id)

    # Interactive: pass through empty space / non-touchable widgets.
    if not is_interactive_overlay(canvas):
        return False
    return touchable_item_at(scene, scene_pos.x(), scene_pos.y(), page_id) is None


def _reposition_target_hit(scene: OverlayScene, x: float, y: float, page_id: str | None = None) -> bool:
    """True when (x, y) is on the current control target (widget / group / page canvas)."""
    target = getattr(scene, "control_target", None) or {}
    kind = str(target.get("kind") or "").casefold()
    tid = str(target.get("id") or "").strip()
    page = scene.page_by_id(page_id) if page_id else scene.active_page()
    if kind == "page":
        if tid and page and tid != page.get("id"):
            return False
        canvas = scene.canvas_for(page_id)
        cw = max(1, int(canvas.get("width") or 1280))
        ch = max(1, int(canvas.get("height") or 720))
        return 0 <= float(x) <= float(cw) and 0 <= float(y) <= float(ch)
    ids = set(scene.control_target_widget_ids(target, page_id=page_id))
    if not ids:
        return False
    hit = scene.hit_test(x, y, page_id)
    return bool(hit and hit.get("id") in ids)

def _handle_nchittest(widget: QtWidgets.QWidget, eventType, message):
    if sys.platform != "win32":
        return None
        et = eventType
        if not isinstance(et, (bytes, bytearray)):
            et = bytes(et)
        if not et.startswith(b"windows_generic_MSG"):
            return None
    try:
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))
        if msg.message != 0x0084:
            return None
        if _nchittest_passthrough(widget, msg.lParam):
            return True, -1
    except Exception:
        return None
    return None


def _extend_frame_into_client(widget: QtWidgets.QWidget):
    """Let DWM composite the client area so alpha 0 shows the desktop."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from shiboken6 import Shiboken

        if widget is None or not Shiboken.isValid(widget):
            return
        hwnd = int(widget.winId())
        if not hwnd:
            return

        class _Margins(ctypes.Structure):
            _fields_ = [
                ("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int),
            ]

        margins = _Margins(-1, -1, -1, -1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    except Exception:
        pass


def list_overlay_screens() -> list[dict]:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return []
    primary = app.primaryScreen()
    screens = []
    for index, screen in enumerate(app.screens()):
        geo = screen.geometry()
        name = screen.name() or f"Display {index + 1}"
        tag = " (primary)" if screen is primary else ""
        screens.append(
            {
                "index": index,
                "name": name,
                "width": int(geo.width()),
                "height": int(geo.height()),
                "x": int(geo.x()),
                "y": int(geo.y()),
                "label": f"{index + 1}: {name} — {geo.width()}×{geo.height()}{tag}",
            }
        )
    return screens


def resolve_overlay_screen(canvas: dict | None) -> dict | None:
    screens = list_overlay_screens()
    if not screens:
        return None
    canvas = canvas or {}
    name = str(canvas.get("monitor_name") or "").strip()
    if name:
        for screen in screens:
            if screen["name"] == name:
                return screen
    try:
        index = int(canvas.get("monitor_index") or 0)
    except (TypeError, ValueError):
        index = 0
    if 0 <= index < len(screens):
        return screens[index]
    return screens[0]


def apply_onscreen_geometry(scene: OverlayScene, monitor_index=None, emit: bool = True, page_id: str | None = None) -> bool:
    """Size the canvas to the chosen monitor when on-screen mode is active."""
    canvas = scene.canvas_for(page_id)
    if not is_onscreen_mode(canvas):
        return False
    if monitor_index is not None:
        canvas["monitor_index"] = int(monitor_index)
        canvas["monitor_name"] = ""
    info = resolve_overlay_screen(canvas)
    if not info:
        return False
    changed = False
    for key in ("width", "height", "monitor_index", "monitor_name"):
        value = info["index"] if key == "monitor_index" else info["name"] if key == "monitor_name" else info[key]
        if canvas.get(key) != value:
            canvas[key] = value
            changed = True
    if changed:
        scene._dirty = True
        if emit:
            scene.changed.emit()
    return changed


def _window_on_a_screen(widget: QtWidgets.QWidget) -> bool:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return True
    geo = widget.frameGeometry()
    for screen in app.screens():
        if screen.availableGeometry().intersects(geo) or screen.geometry().intersects(geo):
            return True
    return False


def _center_on_screen(widget: QtWidgets.QWidget):
    app = QtWidgets.QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return
    frame = widget.frameGeometry()
    frame.moveCenter(screen.availableGeometry().center())
    widget.move(frame.topLeft())


class OverlayView(QtWidgets.QWidget):
    """Paints an overlay scene at 1:1 canvas size (designer may zoom)."""

    zoom_changed = QtCore.Signal(float)

    def __init__(self, scene: OverlayScene, interactive: bool = False, touch_output: bool = False, parent=None, page_id: str | None = None):
        super().__init__(parent)
        self.scene = scene
        self._page_id = page_id
        self.interactive = interactive
        self.touch_output = bool(touch_output)
        self.bus = OverlayValueBus()
        self._zoom = 1.0
        self._scene_origin = QtCore.QPoint(0, 0)
        self._rubber = QtCore.QRectF()
        self._grid_pm: QtGui.QPixmap | None = None
        self._touch = OverlayTouchHandler(self) if self.touch_output else None
        self._reposition_last: QtCore.QPointF | None = None
        self.setMouseTracking(interactive or self.touch_output)
        self.setFocusPolicy(QtCore.Qt.StrongFocus if interactive else QtCore.Qt.NoFocus)
        if live_window_is_layered(self.page_canvas, designer=interactive):
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
            _transparent_palette(self)
        if self.touch_output:
            self.setAttribute(QtCore.Qt.WA_AcceptTouchEvents, True)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        self._sync_paint_mode()
        self._apply_size()
        self._scene_connected = False
        self.scene.changed.connect(self._on_scene_changed)
        try:
            self.scene.geometry_changed.connect(self._on_geometry_changed)
        except Exception:
            pass
        self._scene_connected = True
        try:
            self.scene.selection_changed.connect(self._on_selection_or_target_changed)
            self.scene.control_target_changed.connect(self._on_selection_or_target_changed)
            self.scene.control_highlight_changed.connect(self._on_selection_or_target_changed)
            self._selection_hooks = True
        except Exception:
            self._selection_hooks = False
        self._bus_connected = False
        self._scene_queued = False
        self._update_queued = False
        self._pending_full = False
        self._pending_rect = QtCore.QRect()
        self._last_flush_mono = 0.0
        # Live HUD: static = bg+shadows; frame = full composite patched only for dirty widgets.
        self._static_pm: QtGui.QPixmap | None = None
        self._static_key = None
        self._frame_pm: QtGui.QPixmap | None = None
        self._dirty_body_ids: set[str] | None = None  # None = rebuild all bodies
        self.destroyed.connect(self._on_view_destroyed)

    def _on_view_destroyed(self, *_args):
        self.detach_from_scene()

    @property
    def page_id(self) -> str | None:
        return self._page_id

    @property
    def page_canvas(self) -> dict:
        return self.scene.canvas_for(self._page_id)

    @property
    def page_widgets(self) -> list:
        return self.scene.widgets_for(self._page_id)

    def detach_from_scene(self):
        if self._scene_connected:
            try:
                self.scene.changed.disconnect(self._on_scene_changed)
            except Exception:
                pass
            try:
                self.scene.geometry_changed.disconnect(self._on_geometry_changed)
            except Exception:
                pass
            self._scene_connected = False
        if getattr(self, "_selection_hooks", False):
            try:
                self.scene.selection_changed.disconnect(self._on_selection_or_target_changed)
            except Exception:
                pass
            try:
                self.scene.control_target_changed.disconnect(self._on_selection_or_target_changed)
            except Exception:
                pass
            try:
                self.scene.control_highlight_changed.disconnect(self._on_selection_or_target_changed)
            except Exception:
                pass
            self._selection_hooks = False
        self._end_reposition_drag()
        self.release_touch()
        self.detach_bus()

    def _on_selection_or_target_changed(self, *_args):
        if not Shiboken.isValid(self):
            return
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float):
        if not self.interactive:
            return
        zoom = max(0.25, min(4.0, float(zoom)))
        zoom = round(zoom * 100.0) / 100.0
        if abs(zoom - self._zoom) < 0.001:
            return
        self._zoom = zoom
        self._grid_pm = None
        self._apply_size()
        self.update()
        self.zoom_changed.emit(zoom)

    def canvas_size(self) -> tuple[int, int]:
        w = max(64, int(self.page_canvas.get("width") or 1280))
        h = max(64, int(self.page_canvas.get("height") or 720))
        return w, h

    def _content_rect(self) -> QtCore.QRect:
        """Scene rect that includes the canvas and, in the designer, overflow widgets."""
        cw, ch = self.canvas_size()
        canvas = QtCore.QRect(0, 0, cw, ch)
        if not self.interactive:
            return canvas
        bounds = QtCore.QRect(canvas)
        for item in self.page_widgets:
            try:
                x = int(item.get("x") or 0)
                y = int(item.get("y") or 0)
                w = max(1, int(item.get("w") or 1))
                h = max(1, int(item.get("h") or 1))
            except (TypeError, ValueError):
                continue
            bounds = bounds.united(QtCore.QRect(x, y, w, h))
        if bounds == canvas:
            return canvas
        pad = DESIGNER_OVERFLOW_PAD
        return bounds.adjusted(-pad, -pad, pad, pad).united(canvas)

    def map_to_scene(self, pos: QtCore.QPointF) -> QtCore.QPointF:
        z = self._zoom or 1.0
        origin = self._scene_origin
        return QtCore.QPointF(pos.x() / z + origin.x(), pos.y() / z + origin.y())

    def _scene_clip(self, widget_rect: QtCore.QRect) -> QtCore.QRect:
        z = self._zoom or 1.0
        ox, oy = self._scene_origin.x(), self._scene_origin.y()
        if abs(z - 1.0) < 0.001:
            return widget_rect.translated(ox, oy)
        inv = 1.0 / z
        return QtCore.QRect(
            math.floor(widget_rect.x() * inv) + ox - 2,
            math.floor(widget_rect.y() * inv) + oy - 2,
            math.ceil(widget_rect.width() * inv) + 4,
            math.ceil(widget_rect.height() * inv) + 4,
        )

    def _widget_rect(self, scene_rect: QtCore.QRect) -> QtCore.QRect:
        z = self._zoom or 1.0
        ox, oy = self._scene_origin.x(), self._scene_origin.y()
        if abs(z - 1.0) < 0.001:
            return scene_rect.translated(-ox, -oy)
        return QtCore.QRect(
            math.floor((scene_rect.x() - ox) * z),
            math.floor((scene_rect.y() - oy) * z),
            max(1, math.ceil(scene_rect.width() * z) + 1),
            max(1, math.ceil(scene_rect.height() * z) + 1),
        )

    def attach_bus(self):
        if not Shiboken.isValid(self):
            return
        if QtCore.QThread.currentThread() is not self.thread():
            QtCore.QTimer.singleShot(0, self, self.attach_bus)
            return
        self.bus.set_widgets(self.page_widgets, source=self)
        if not self._bus_connected:
            self.bus.attach(self.page_widgets, source=self)
            self.bus.values_changed.connect(self._on_values_changed)
            self._bus_connected = True

    def detach_bus(self):
        if not self._bus_connected:
            return
        try:
            self.bus.values_changed.disconnect(self._on_values_changed)
        except Exception:
            pass
        self._bus_connected = False
        self.bus.detach(source=self)

    def _on_values_changed(self, widget_ids=None):
        if not Shiboken.isValid(self):
            return
        if self.interactive:
            self._schedule_update(None)
            return
        # Track which widget bodies need a paint. Background/shadows stay in the
        # static layer and are only restored under dirty rects.
        if not widget_ids:
            self._dirty_body_ids = None
        elif self._dirty_body_ids is None and self._frame_pm is None:
            # First frame not built yet — full rebuild on paint.
            self._dirty_body_ids = None
        else:
            if self._dirty_body_ids is None:
                self._dirty_body_ids = set()
            self._dirty_body_ids.update(str(wid) for wid in widget_ids if wid)

        # Layered HWNDs must blit the full client (partial Qt updates smear), but
        # the expensive CPU work is only the dirty body patch into _frame_pm.
        if live_window_is_layered(self.page_canvas, designer=False):
            self._schedule_update(None)
            return
        if getattr(self.scene, "mouse_reposition_enabled", False):
            self._schedule_update(None)
            return
        if self._dirty_body_ids is None:
            self._schedule_update(None)
            return
        united = QtCore.QRect()
        for widget_id in self._dirty_body_ids:
            item = self.scene.widget_by_id(widget_id, self._page_id)
            if not item:
                continue
            rect = self._widget_rect(widget_dirty_rect(item))
            united = rect if united.isNull() else united.united(rect)
        if united.isNull():
            return
        self._schedule_update(united)

    def _schedule_update(self, rect: QtCore.QRect | None):
        # Translucent HWNDs must always clear the full client; partial updates smear.
        if rect is not None and live_window_is_layered(self.page_canvas, designer=self.interactive):
            rect = None
        if rect is None:
            self._pending_full = True
        elif not self._pending_full:
            if self._pending_rect.isNull():
                self._pending_rect = QtCore.QRect(rect)
            else:
                self._pending_rect = self._pending_rect.united(rect)
        if self._update_queued:
            return
        self._update_queued = True
        delay_ms = 0
        if not self.interactive:
            # Cap live paint rate. Full-scene layered redraws were starving the
            # Python GIL and delaying joystick→vJoy on the event thread.
            elapsed_ms = (time.monotonic() - self._last_flush_mono) * 1000.0
            min_ms = 33.0  # ~30 Hz
            if elapsed_ms < min_ms:
                delay_ms = int(min_ms - elapsed_ms)
        QtCore.QTimer.singleShot(delay_ms, self, self._flush_update)

    def _flush_update(self):
        full = self._pending_full
        rect = QtCore.QRect(self._pending_rect)
        self._pending_full = False
        self._pending_rect = QtCore.QRect()
        # Allow coalescing more dirties that arrive while we invalidate.
        self._update_queued = False
        self._last_flush_mono = time.monotonic()
        if not Shiboken.isValid(self):
            return
        if full or live_window_is_layered(self.page_canvas, designer=self.interactive):
            self.update()
            return
        if not rect.isNull():
            self.update(rect)

    def _on_scene_changed(self):
        if not Shiboken.isValid(self):
            return
        if QtCore.QThread.currentThread() is not self.thread():
            if self._scene_queued:
                return
            self._scene_queued = True
            QtCore.QTimer.singleShot(0, self, self._on_scene_changed)
            return
        self._scene_queued = False
        self.bus.set_widgets(self.page_widgets, source=self)
        self._grid_pm = None
        self._invalidate_static_layer()
        self._sync_paint_mode()
        self._apply_size()
        self.update()

    def _on_geometry_changed(self):
        """Move/resize only — full invalidate so layered overlays do not smear."""
        if not Shiboken.isValid(self):
            return
        if QtCore.QThread.currentThread() is not self.thread():
            QtCore.QTimer.singleShot(0, self, self._on_geometry_changed)
            return
        # Direct full update (not a sub-rect) — critical for onscreen translucency.
        self._invalidate_static_layer()
        self._pending_full = True
        self._pending_rect = QtCore.QRect()
        self.update()
        self._update_queued = False

    def _sync_paint_mode(self):
        if not alive(self):
            return
        layered = live_window_is_layered(self.page_canvas, designer=self.interactive)
        opaque = not layered
        if self.testAttribute(QtCore.Qt.WA_OpaquePaintEvent) != opaque:
            self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, opaque)
        if not self.testAttribute(QtCore.Qt.WA_NoSystemBackground):
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        if self.testAttribute(QtCore.Qt.WA_TranslucentBackground) != layered:
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, layered)

    def _apply_size(self):
        if not alive(self):
            return
        content = self._content_rect()
        old_origin = QtCore.QPoint(self._scene_origin)
        origin = content.topLeft()
        z = self._zoom if self.interactive else 1.0
        zw = max(64, int(round(content.width() * z)))
        zh = max(64, int(round(content.height() * z)))
        if self._scene_origin != origin or self.width() != zw or self.height() != zh:
            self._grid_pm = None
            self._invalidate_static_layer()
        self._scene_origin = origin
        if self.interactive and origin != old_origin:
            self._nudge_scroll((old_origin.x() - origin.x()) * z, (old_origin.y() - origin.y()) * z)
        self.setFixedSize(zw, zh)

    def center_on_scene_rect(self, rect: QtCore.QRectF):
        """Scroll the designer so *rect* sits in the middle of the viewport."""
        parent = self.parent()
        while parent is not None and not isinstance(parent, QtWidgets.QScrollArea):
            parent = parent.parent()
        if not isinstance(parent, QtWidgets.QScrollArea) or not alive(parent):
            return
        z = self._zoom if self.interactive else 1.0
        origin = self._scene_origin
        cx = (rect.center().x() - origin.x()) * z
        cy = (rect.center().y() - origin.y()) * z
        viewport = parent.viewport()
        if viewport is None:
            return
        parent.horizontalScrollBar().setValue(int(round(cx - viewport.width() / 2.0)))
        parent.verticalScrollBar().setValue(int(round(cy - viewport.height() / 2.0)))

    def _nudge_scroll(self, dx: float, dy: float):
        parent = self.parent()
        while parent is not None and not isinstance(parent, QtWidgets.QScrollArea):
            parent = parent.parent()
        if not isinstance(parent, QtWidgets.QScrollArea) or not alive(parent):
            return
        if abs(dx) >= 1:
            bar = parent.horizontalScrollBar()
            if alive(bar):
                bar.setValue(bar.value() + int(round(dx)))
        if abs(dy) >= 1:
            bar = parent.verticalScrollBar()
            if alive(bar):
                bar.setValue(bar.value() + int(round(dy)))

    def _invalidate_static_layer(self):
        self._static_pm = None
        self._static_key = None
        self._frame_pm = None
        self._dirty_body_ids = None

    def _static_layer_key(self):
        """Geometry / style fingerprint — value ticks must not rebuild shadows."""
        canvas = self.page_canvas
        cw, ch = self.canvas_size()
        parts = [
            cw,
            ch,
            normalize_background_mode(canvas),
            bool(is_onscreen_mode(canvas)),
            str(canvas.get("chroma") or ""),
            str(canvas.get("fill") or ""),
            str(canvas.get("background_image") or ""),
        ]
        for item in self.scene.sorted_widgets(self._page_id):
            wid = str(item.get("id") or "")
            visible = bool(item.get("visible", True))
            conditions_ok = widget_conditions_match(item)
            if not visible or not conditions_ok:
                parts.append((wid, False))
                continue
            shadow = resolve_widget_shadow(item.get("style"))
            style = item.get("style") or {}
            parts.append(
                (
                    wid,
                    True,
                    round(float(item.get("x") or 0), 2),
                    round(float(item.get("y") or 0), 2),
                    round(float(item.get("w") or 0), 2),
                    round(float(item.get("h") or 0), 2),
                    round(float(widget_rotation_deg(item)), 2),
                    bool(shadow.get("on")),
                    round(float(shadow.get("dx") or 0), 2),
                    round(float(shadow.get("dy") or 0), 2),
                    round(float(shadow.get("size") or 0), 2),
                    round(float(shadow.get("spread") or 0), 2),
                    str(shadow.get("color") or ""),
                    str(style.get("image_path") or ""),
                    str(style.get("image_path_on") or ""),
                    bool(style.get("image_keep_aspect", True)),
                    str(item.get("type") or ""),
                )
            )
        return tuple(parts)

    def _ensure_static_layer(self) -> QtGui.QPixmap | None:
        """Background + drop shadows for the live HUD (not rebuilt on value polls)."""
        if self.interactive:
            return None
        key = self._static_layer_key()
        if self._static_pm is not None and not self._static_pm.isNull() and key == self._static_key:
            return self._static_pm
        cw, ch = self.canvas_size()
        if cw <= 0 or ch <= 0:
            return None
        pm = QtGui.QPixmap(cw, ch)
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        canvas_rect = QtCore.QRect(0, 0, cw, ch)
        # Clear/chroma is applied in paintEvent; this layer is bg image + shadows only.
        if not is_onscreen_mode(self.page_canvas):
            paint_background(painter, self.page_canvas, canvas_rect, preview=False, fallback_chroma=False)
        set_live_fast_paint(True)
        try:
            for item in self.scene.sorted_widgets(self._page_id):
                if not item.get("visible", True):
                    continue
                if not widget_conditions_match(item):
                    continue
                if abs(widget_rotation_deg(item)) < 0.001:
                    paint_widget_drop_shadow(painter, item)
                else:
                    painter.save()
                    apply_widget_rotation(painter, item)
                    paint_widget_drop_shadow(painter, item)
                    painter.restore()
        finally:
            set_live_fast_paint(False)
        painter.end()
        self._static_pm = pm
        self._static_key = key
        # Static rebuilt ⇒ frame must be rebuilt too.
        self._frame_pm = None
        self._dirty_body_ids = None
        return pm

    def _paint_live_clear(self, painter: QtGui.QPainter, canvas_rect: QtCore.QRect):
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        if is_onscreen_mode(self.page_canvas):
            painter.fillRect(canvas_rect, QtCore.Qt.transparent)
        else:
            painter.fillRect(canvas_rect, chroma_fill_color(self.page_canvas))
        if is_interactive_overlay(self.page_canvas):
            for item in self.scene.sorted_widgets(self._page_id):
                if not widget_accepts_touch(item):
                    continue
                hit = widget_rotated_bounds(item)
                if hit.intersects(QtCore.QRectF(canvas_rect)):
                    painter.save()
                    apply_widget_rotation(painter, item)
                    painter.fillRect(widget_rect(item), QtGui.QColor(0, 0, 0, 1))
                    painter.restore()
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)

    def _paint_live_bodies(self, painter: QtGui.QPainter, items: list):
        set_live_fast_paint(True)
        try:
            for item in items:
                if not item.get("visible", True):
                    continue
                if not widget_conditions_match(item):
                    continue
                value = self.bus.value_for(item)
                paint_widget(painter, item, value, draw_shadow=False)
        finally:
            set_live_fast_paint(False)

    def _rebuild_frame_pm(self, static_pm: QtGui.QPixmap) -> QtGui.QPixmap:
        cw, ch = self.canvas_size()
        frame = QtGui.QPixmap(cw, ch)
        frame.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(frame)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        canvas_rect = QtCore.QRect(0, 0, cw, ch)
        self._paint_live_clear(painter, canvas_rect)
        if static_pm is not None and not static_pm.isNull():
            painter.drawPixmap(0, 0, static_pm)
        self._paint_live_bodies(painter, self.scene.sorted_widgets(self._page_id))
        painter.end()
        self._frame_pm = frame
        self._dirty_body_ids = set()
        return frame

    def _ensure_frame_pm(self) -> QtGui.QPixmap | None:
        """Full live composite. Only dirty widget bodies are repainted each tick."""
        if self.interactive:
            return None
        static_pm = self._ensure_static_layer()
        cw, ch = self.canvas_size()
        if cw <= 0 or ch <= 0:
            return None
        frame = self._frame_pm
        if frame is None or frame.isNull() or frame.width() != cw or frame.height() != ch:
            return self._rebuild_frame_pm(static_pm if static_pm is not None else QtGui.QPixmap())

        dirty_ids = self._dirty_body_ids
        if dirty_ids is None:
            return self._rebuild_frame_pm(static_pm if static_pm is not None else QtGui.QPixmap())
        if not dirty_ids:
            return frame

        canvas_rect = QtCore.QRect(0, 0, cw, ch)
        united = QtCore.QRect()
        for wid in dirty_ids:
            item = self.scene.widget_by_id(wid, self._page_id)
            if not item:
                continue
            united = united.united(widget_dirty_rect(item)) if not united.isNull() else widget_dirty_rect(item)
        united = united.intersected(canvas_rect)
        self._dirty_body_ids = set()
        if united.isNull():
            return frame

        # Any widget overlapping the dirty region must be redrawn for z-order.
        overlapping = []
        for item in self.scene.sorted_widgets(self._page_id):
            if not item.get("visible", True):
                continue
            if not widget_conditions_match(item):
                continue
            if widget_dirty_rect(item).intersects(united):
                overlapping.append(item)

        painter = QtGui.QPainter(frame)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setClipRect(united)
        # Restore clear + static shadows under the dirty rect, then live bodies.
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        if is_onscreen_mode(self.page_canvas):
            painter.fillRect(united, QtCore.Qt.transparent)
        else:
            painter.fillRect(united, chroma_fill_color(self.page_canvas))
        if is_interactive_overlay(self.page_canvas):
            for item in overlapping:
                if not widget_accepts_touch(item):
                    continue
                painter.save()
                apply_widget_rotation(painter, item)
                painter.fillRect(widget_rect(item), QtGui.QColor(0, 0, 0, 1))
                painter.restore()
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        if static_pm is not None and not static_pm.isNull():
            painter.drawPixmap(united.topLeft(), static_pm, united)
        self._paint_live_bodies(painter, overlapping)
        painter.end()
        return frame

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        z = self._zoom if self.interactive else 1.0
        cw, ch = self.canvas_size()
        canvas_rect = QtCore.QRect(0, 0, cw, ch)
        layered = live_window_is_layered(self.page_canvas, designer=self.interactive)
        # If a stale partial invalidate reached a translucent HWND, promote to full.
        if layered and not self.interactive and event.rect() != self.rect():
            painter.end()
            self.update()
            return
        clip = event.rect()
        scene_clip = self._scene_clip(clip)
        if self.interactive:
            scene_clip = scene_clip.intersected(self._content_rect())
        else:
            scene_clip = scene_clip.intersected(canvas_rect)
        if abs(z - 1.0) > 0.001:
            painter.scale(z, z)
        origin = self._scene_origin
        if origin.x() or origin.y():
            painter.translate(-origin.x(), -origin.y())
        painter.setClipRect(scene_clip if not layered else canvas_rect)
        # Live updates skip antialiasing so the UI thread stays free for Input Viewer.
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

        # Live: patch only dirty widget bodies into a frame buffer, then blit.
        if not self.interactive:
            frame = self._ensure_frame_pm()
            if frame is not None and not frame.isNull():
                if layered:
                    painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
                    painter.drawPixmap(0, 0, frame)
                else:
                    src = scene_clip if not scene_clip.isNull() else canvas_rect
                    painter.drawPixmap(src.topLeft(), frame, src)
            self._paint_control_target(painter)
            painter.end()
            return

        if layered:
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
            # Always clear the full canvas in layered mode. Clearing only the
            # event clip leaves ghost trails when a prior partial update raced
            # a widget move (onscreen translucent HWND).
            clear_rect = canvas_rect
            if is_onscreen_mode(self.page_canvas):
                painter.fillRect(clear_rect, QtCore.Qt.transparent)
            else:
                painter.fillRect(clear_rect, chroma_fill_color(self.page_canvas))
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
            if not is_onscreen_mode(self.page_canvas):
                paint_background(painter, self.page_canvas, canvas_rect, preview=False, fallback_chroma=False)
        else:
            if self.interactive:
                painter.fillRect(scene_clip, DESIGNER_OVERFLOW_FILL)
            paint_background(painter, self.page_canvas, canvas_rect, preview=self.interactive)
            if self.interactive:
                painter.setPen(QtGui.QPen(DESIGNER_CANVAS_BORDER, 1))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(canvas_rect.adjusted(0, 0, -1, -1))
        if self.interactive and self.page_canvas.get("snap_to_grid"):
            self._paint_grid(painter)
        paint_clip = scene_clip
        for item in self.scene.sorted_widgets(self._page_id):
            dirty = widget_dirty_rect(item)
            if not dirty.intersects(paint_clip):
                continue
            if not item.get("visible", True):
                if self.interactive:
                    painter.save()
                    apply_widget_rotation(painter, item)
                    painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1.2, QtCore.Qt.DashLine))
                    painter.setBrush(QtCore.Qt.NoBrush)
                    painter.drawRect(widget_rect(item).adjusted(0.5, 0.5, -0.5, -0.5))
                    painter.restore()
                continue
            conditions_ok = widget_conditions_match(item)
            # Designer tab: never mirror live inputs while a profile is running.
            if self.interactive and gremlin.shared_state.is_running:
                value = None
            else:
                value = self.bus.value_for(item)
            if self.interactive and not conditions_ok:
                painter.save()
                painter.setOpacity(0.32)
                paint_widget(painter, item, value)
                painter.restore()
            else:
                paint_widget(painter, item, value)
        if self.interactive:
            self._paint_guides(painter)
            self._paint_selection(painter)
            if not self._rubber.isNull():
                painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1, QtCore.Qt.DashLine))
                painter.setBrush(QtGui.QColor(126, 200, 255, 40))
                painter.drawRect(self._rubber.normalized())
        painter.end()

    def _paint_grid(self, painter: QtGui.QPainter):
        cw, ch = self.canvas_size()
        size = QtCore.QSize(cw, ch)
        if self._grid_pm is None or self._grid_pm.size() != size:
            grid = max(4, int(self.page_canvas.get("grid_size") or 8))
            pm = QtGui.QPixmap(size)
            pm.fill(QtCore.Qt.transparent)
            gp = QtGui.QPainter(pm)
            gp.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 28), 1))
            for x in range(0, cw, grid):
                gp.drawLine(x, 0, x, ch)
            for y in range(0, ch, grid):
                gp.drawLine(0, y, cw, y)
            gp.end()
            self._grid_pm = pm
        painter.drawPixmap(0, 0, self._grid_pm)

    def _paint_guides(self, painter: QtGui.QPainter):
        cw, ch = self.canvas_size()
        handle = 8.0 / max(self._zoom, 0.25)
        for guide in self.page_canvas.get("guides") or []:
            color = qcolor(guide.get("color"), DEFAULT_GUIDE_COLOR)
            painter.setPen(QtGui.QPen(color, 1.2, QtCore.Qt.DashLine))
            painter.setBrush(color)
            pos = max(0.0, min(1.0, float(guide.get("position") or 0)))
            if guide.get("axis") == "h":
                y = pos * ch
                painter.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(cw, y))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawPolygon(
                    QtGui.QPolygonF(
                        [
                            QtCore.QPointF(0, y - handle),
                            QtCore.QPointF(handle * 1.6, y),
                            QtCore.QPointF(0, y + handle),
                        ]
                    )
                )
            else:
                x = pos * cw
                painter.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, ch))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawPolygon(
                    QtGui.QPolygonF(
                        [
                            QtCore.QPointF(x - handle, 0),
                            QtCore.QPointF(x + handle, 0),
                            QtCore.QPointF(x, handle * 1.6),
                        ]
                    )
                )

    def guide_at(self, pos: QtCore.QPointF) -> dict | None:
        cw, ch = self.canvas_size()
        if cw <= 0 or ch <= 0:
            return None
        tol = 6.0 / max(self._zoom, 0.25)
        handle = 12.0 / max(self._zoom, 0.25)
        best = None
        best_dist = tol
        for guide in self.page_canvas.get("guides") or []:
            pos_t = max(0.0, min(1.0, float(guide.get("position") or 0)))
            if guide.get("axis") == "h":
                gy = pos_t * ch
                dist = abs(pos.y() - gy)
                on_handle = pos.x() <= handle * 2
            else:
                gx = pos_t * cw
                dist = abs(pos.x() - gx)
                on_handle = pos.y() <= handle * 2
            limit = tol * 1.8 if on_handle else tol
            if dist <= limit and dist <= best_dist:
                best = guide
                best_dist = dist
        return best

    def _control_target_bounds(self) -> QtCore.QRectF | None:
        """Scene bounds for the runtime control-panel target (page, group, or widget)."""
        if self.interactive or not self.scene.control_highlight_active:
            return None
        page_id = self._page_id or self.scene.active_page_id
        target = getattr(self.scene, "control_target", None) or {}
        kind = str(target.get("kind") or "").casefold()
        tid = str(target.get("id") or "").strip()

        ids: list[str] = []
        if kind in ("widget", "group"):
            ids = self.scene.control_target_widget_ids(target, page_id=page_id)
        elif kind == "page":
            if tid and page_id and tid != page_id:
                return None
            cw, ch = self.canvas_size()
            return QtCore.QRectF(0, 0, cw, ch)
        if not ids:
            return None
        bounds = QtCore.QRectF()
        found = False
        for widget_id in ids:
            item = self.scene.widget_by_id(widget_id, page_id)
            if not item:
                continue
            rect = widget_rotated_bounds(item)
            bounds = rect if not found else bounds.united(rect)
            found = True
        return bounds if found else None

    def _paint_control_target(self, painter: QtGui.QPainter):
        """Cyan dashed box around the current control target on the live overlay."""
        bounds = self._control_target_bounds()
        if bounds is None or bounds.isEmpty():
            return
        painter.save()
        pen = QtGui.QPen(QtGui.QColor("#00e8e8"), 2.0)
        pen.setStyle(QtCore.Qt.DashLine)
        pen.setDashPattern([6, 4])
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(bounds.adjusted(-2, -2, 2, 2))
        painter.restore()

    def _selected_bounds(self) -> QtCore.QRectF | None:
        bounds = QtCore.QRectF()
        found = False
        for widget_id in self.scene.selected_ids:
            item = self.scene.widget_by_id(widget_id, self._page_id)
            if not item:
                continue
            rect = widget_rotated_bounds(item)
            bounds = rect if not found else bounds.united(rect)
            found = True
        return bounds if found else None

    def _paint_selection(self, painter: QtGui.QPainter):
        painter.save()
        multi = len(self.scene.selected_ids) > 1
        hs = 4.0 / max(self._zoom, 0.25)
        # Multi-select: only the group AABB + handles. Drawing every member outline
        # for large groups (20+ image widgets) is a major drag/rotate hitch.
        if not multi:
            for widget_id in self.scene.selected_ids:
                item = self.scene.widget_by_id(widget_id, self._page_id)
                if not item:
                    continue
                rect = widget_rect(item)
                painter.save()
                apply_widget_rotation(painter, item)
                painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1.5))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(rect.adjusted(-1, -1, 1, 1))
                painter.restore()
                if widget_id == (self.scene.selected_ids[-1] if self.scene.selected_ids else None):
                    painter.setBrush(QtGui.QColor("#7ec8ff"))
                    painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1))
                    for hx, hy in self.handle_points(item):
                        painter.drawRect(QtCore.QRectF(hx - hs, hy - hs, hs * 2, hs * 2))
                    self._paint_rotation_handle(painter, item, hs)
        else:
            bounds = self._selected_bounds()
            if bounds is not None:
                painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1.5, QtCore.Qt.DashLine))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(bounds.adjusted(-2, -2, 2, 2))
                painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1))
                painter.setBrush(QtGui.QColor("#7ec8ff"))
                dummy = {"x": bounds.x(), "y": bounds.y(), "w": bounds.width(), "h": bounds.height()}
                for hx, hy in self.handle_points(dummy):
                    painter.drawRect(QtCore.QRectF(hx - hs, hy - hs, hs * 2, hs * 2))
                self._paint_rotation_handle(painter, dummy, hs)
        painter.restore()

    def _paint_rotation_handle(self, painter: QtGui.QPainter, item: dict, hs: float):
        top = self._top_center_point(item)
        handle = self.rotation_handle_point(item)
        painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1.2))
        painter.drawLine(top, handle)
        painter.setBrush(QtGui.QColor("#7ec8ff"))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(handle, hs * 1.15, hs * 1.15)

    def _top_center_point(self, item: dict) -> QtCore.QPointF:
        rect = widget_rect(item)
        return widget_local_to_scene(item, rect.center().x(), rect.top())

    def handle_points(self, item: dict):
        x, y, w, h = float(item["x"]), float(item["y"]), float(item["w"]), float(item["h"])
        local = [
            (x, y),
            (x + w / 2, y),
            (x + w, y),
            (x + w, y + h / 2),
            (x + w, y + h),
            (x + w / 2, y + h),
            (x, y + h),
            (x, y + h / 2),
        ]
        return [(widget_local_to_scene(item, px, py).x(), widget_local_to_scene(item, px, py).y()) for px, py in local]

    def rotation_handle_point(self, item: dict) -> QtCore.QPointF:
        rect = widget_rect(item)
        offset = 18.0 / max(self._zoom, 0.25)
        return widget_local_to_scene(item, rect.center().x(), rect.top() - offset)

    def handle_at(self, pos: QtCore.QPointF) -> tuple[str | None, int]:
        if not self.scene.selected_ids:
            return None, -1
        if len(self.scene.selected_ids) > 1:
            bounds = self._selected_bounds()
            if bounds is None:
                return None, -1
            item = {"x": bounds.x(), "y": bounds.y(), "w": bounds.width(), "h": bounds.height()}
            target_id = self.scene.selected_ids[-1]
        else:
            item = self.scene.widget_by_id(self.scene.selected_ids[-1], self._page_id)
            if not item:
                return None, -1
            target_id = item["id"]
        tol = 6.0 / max(self._zoom, 0.25)
        rotate = self.rotation_handle_point(item)
        if abs(pos.x() - rotate.x()) <= tol * 1.35 and abs(pos.y() - rotate.y()) <= tol * 1.35:
            return target_id, ROTATE_HANDLE
        for index, (hx, hy) in enumerate(self.handle_points(item)):
            if abs(pos.x() - hx) <= tol and abs(pos.y() - hy) <= tol:
                return target_id, index
        return None, -1

    def release_touch(self):
        if self._touch is not None:
            self._touch.release_all()

    def event(self, event: QtCore.QEvent) -> bool:
        if self._touch is not None and event.type() in (
            QtCore.QEvent.Type.TouchBegin,
            QtCore.QEvent.Type.TouchUpdate,
            QtCore.QEvent.Type.TouchEnd,
            QtCore.QEvent.Type.TouchCancel,
        ):
            handled = self._handle_touch(event)
            if handled or event.type() != QtCore.QEvent.Type.TouchBegin:
                event.accept()
                return True
            return False
        return super().event(event)

    def nativeEvent(self, eventType, message):
        result = _handle_nchittest(self, eventType, message)
        if result is not None:
            return result
        return super().nativeEvent(eventType, message)

    def _handle_touch(self, event) -> bool:
        if self._touch is None or not self._touch.enabled():
            if event.type() == QtCore.QEvent.Type.TouchCancel:
                self.release_touch()
            return False
        handled = False
        for point in event.points():
            pid = ("touch", int(point.id()))
            state = point.state()
            scene = self.map_to_scene(point.position())
            if state == QtGui.QEventPoint.State.Pressed:
                handled = self._touch.press(pid, scene) or handled
            elif state == QtGui.QEventPoint.State.Updated:
                handled = self._touch.move(pid, scene) or handled
            elif state == QtGui.QEventPoint.State.Released:
                handled = self._touch.release(pid) or handled
        if event.type() == QtCore.QEvent.Type.TouchCancel:
            self.release_touch()
            return True
        return handled

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        # Live overlay mouse-reposition: handled on the view (fills the window client).
        if (
            not self.interactive
            and self.scene.mouse_reposition_enabled
            and event.button() == QtCore.Qt.LeftButton
        ):
            scene = self.map_to_scene(event.position())
            hit = self.scene.hit_test(scene.x(), scene.y(), self.page_id)
            if hit is not None:
                # Clicking a widget selects it as the control target, then drags.
                try:
                    self.scene.set_control_target("widget", hit.get("id"))
                except Exception:
                    pass
                self._begin_reposition_drag(scene)
                event.accept()
                return
            if _reposition_target_hit(self.scene, scene.x(), scene.y(), self.page_id):
                self._begin_reposition_drag(scene)
                event.accept()
                return
            event.ignore()
            return
        if self.interactive or self._touch is None or event.button() != QtCore.Qt.LeftButton:
            super().mousePressEvent(event)
            return
        if self._touch.press("mouse", self.map_to_scene(event.position())):
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self._reposition_last is not None:
            if not (event.buttons() & QtCore.Qt.LeftButton):
                # Button state lost (alt-tab / click-through) — never leave grab stuck.
                self._end_reposition_drag()
                event.accept()
                return
            scene = self.map_to_scene(event.position())
            dx = int(round(scene.x() - self._reposition_last.x()))
            dy = int(round(scene.y() - self._reposition_last.y()))
            if dx or dy:
                self.scene.nudge_control_target(dx, dy)
                self._reposition_last = QtCore.QPointF(scene)
            event.accept()
            return
        if self.interactive or self._touch is None:
            super().mouseMoveEvent(event)
            return
        self._touch.move("mouse", self.map_to_scene(event.position()))
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton and self._reposition_last is not None:
            self._end_reposition_drag()
            event.accept()
            return
        if self.interactive or self._touch is None or event.button() != QtCore.Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        self._touch.release("mouse")
        event.accept()

    def _begin_reposition_drag(self, scene: QtCore.QPointF):
        self._reposition_last = QtCore.QPointF(scene)
        try:
            self.scene.set_control_highlight(True)
        except Exception:
            pass
        self.setCursor(QtCore.Qt.SizeAllCursor)
        self.setMouseTracking(True)
        self.grabMouse()

    def _end_reposition_drag(self):
        if self._reposition_last is None and QtWidgets.QWidget.mouseGrabber() is not self:
            return
        self._reposition_last = None
        try:
            if QtWidgets.QWidget.mouseGrabber() is self:
                self.releaseMouse()
        except Exception:
            pass
        self.unsetCursor()

    def hideEvent(self, event: QtGui.QHideEvent):
        self._end_reposition_drag()
        super().hideEvent(event)

    def changeEvent(self, event: QtCore.QEvent):
        if event.type() in (
            QtCore.QEvent.Type.WindowDeactivate,
            QtCore.QEvent.Type.WindowStateChange,
            QtCore.QEvent.Type.ActivationChange,
        ):
            self._end_reposition_drag()
        super().changeEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key_Escape and self._reposition_last is not None:
            self._end_reposition_drag()
            event.accept()
            return
        super().keyPressEvent(event)


class OverlayWindow(QtWidgets.QWidget):
    """Bordered-or-frameless capture window titled GEX Overlay — {page}."""

    def __init__(self, scene: OverlayScene, parent=None, page_id: str | None = None):
        super().__init__(parent)
        self.scene = scene
        self.page_id = page_id or scene.active_page_id
        self.setObjectName("GexOverlayWindow")
        page = scene.page_by_id(self.page_id)
        self.setWindowTitle(overlay_window_title(page))
        if live_window_is_layered(self.page_canvas):
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
            _transparent_palette(self)
        self.view = OverlayView(scene, interactive=False, touch_output=True, parent=self, page_id=self.page_id)
        self.drag_bar = QtWidgets.QWidget(self)
        self.drag_bar.setFixedHeight(22)
        self.drag_bar.setCursor(QtCore.Qt.SizeAllCursor)
        self._drag_label = QtWidgets.QLabel("GEX Overlay  —  hide this bar before capturing")
        self._drag_label.setAlignment(QtCore.Qt.AlignCenter)
        bar_layout = QtWidgets.QHBoxLayout(self.drag_bar)
        bar_layout.setContentsMargins(6, 0, 6, 0)
        bar_layout.addWidget(self._drag_label, 1)
        self._control_btn = QtWidgets.QToolButton(self.drag_bar)
        self._control_btn.setText("Control")
        self._control_btn.setToolTip("Open the runtime overlay control panel (anchors, visibility, save).")
        self._control_btn.setAutoRaise(True)
        self._control_btn.clicked.connect(self._open_control_panel)
        bar_layout.addWidget(self._control_btn)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.drag_bar)
        layout.addWidget(self.view)
        self._drag_origin = None
        self._reposition_last: QtCore.QPointF | None = None
        self._applying_flags = False
        self._host_hwnd = 0
        self._host_attached = False
        self._host_timer = QtCore.QTimer(self)
        self._host_timer.setInterval(250)
        self._host_timer.timeout.connect(self._sync_host_attach)
        self.setMouseTracking(True)
        self.setAttribute(QtCore.Qt.WA_AcceptTouchEvents, True)
        self.drag_bar.installEventFilter(self)
        self._chrome_sig = None
        self._scene_connected = False
        self.scene.changed.connect(self._on_scene_changed)
        self._scene_connected = True
        try:
            self.scene.mouse_reposition_changed.connect(self._on_mouse_reposition_changed)
        except Exception:
            pass
        self._apply_window_flags()
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.destroyed.connect(self._on_window_destroyed)

    def _on_mouse_reposition_changed(self, *_args):
        if not Shiboken.isValid(self):
            return
        self._reposition_last = None
        # Release any interactive grab so game inputs are not left held.
        view = getattr(self, "view", None)
        if view is not None and Shiboken.isValid(view):
            try:
                view._end_reposition_drag()
            except Exception:
                view._reposition_last = None
                try:
                    view.releaseMouse()
                except Exception:
                    pass
                view.unsetCursor()
            view.release_touch()
            # Ensure the painted view receives mouse while repositioning.
            view.setMouseTracking(True)
            view.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        self._apply_window_flags()
        if self.isVisible():
            self.show_without_activating()
        if Shiboken.isValid(self.view):
            self.view.update()

    def _on_window_destroyed(self, *_args):
        self.detach_from_scene()

    @property
    def page_canvas(self) -> dict:
        return self.scene.canvas_for(self.page_id)

    def nativeEvent(self, eventType, message):
        result = _handle_nchittest(self, eventType, message)
        if result is not None:
            return result
        return super().nativeEvent(eventType, message)

    def event(self, event: QtCore.QEvent) -> bool:
        if event.type() in (
            QtCore.QEvent.Type.TouchBegin,
            QtCore.QEvent.Type.TouchUpdate,
            QtCore.QEvent.Type.TouchEnd,
            QtCore.QEvent.Type.TouchCancel,
        ) and is_interactive_overlay(self.page_canvas) and not self.scene.mouse_reposition_enabled:
            if self._forward_window_touch(event):
                event.accept()
                return True
        return super().event(event)

    def _forward_window_touch(self, event) -> bool:
        touch = getattr(self.view, "_touch", None)
        if touch is None:
            return False
        handled = False
        for point in event.points():
            win_pos = point.position().toPoint()
            if self.drag_bar.isVisible() and self.drag_bar.geometry().contains(win_pos):
                continue
            local = self.view.mapFrom(self, win_pos)
            scene = self.view.map_to_scene(QtCore.QPointF(local))
            pid = ("touch", int(point.id()))
            state = point.state()
            if state == QtGui.QEventPoint.State.Pressed:
                handled = touch.press(pid, scene) or handled
            elif state == QtGui.QEventPoint.State.Updated:
                handled = touch.move(pid, scene) or handled
            elif state == QtGui.QEventPoint.State.Released:
                handled = touch.release(pid) or handled
        if event.type() == QtCore.QEvent.Type.TouchCancel:
            self.view.release_touch()
            return True
        return handled

    def showEvent(self, event):
        super().showEvent(event)
        if Shiboken.isValid(self.view):
            self.view.attach_bus()
        if not self._applying_flags:
            reposition = self.scene.mouse_reposition_enabled
            click_through = (
                is_onscreen_mode(self.page_canvas)
                and not is_interactive_overlay(self.page_canvas)
                and not reposition
            )
            self._apply_click_through(click_through)
        if live_window_is_layered(self.page_canvas):
            _extend_frame_into_client(self)
        self._start_host_follow()

    def detach_from_scene(self):
        if self._scene_connected:
            try:
                self.scene.changed.disconnect(self._on_scene_changed)
            except Exception:
                pass
            self._scene_connected = False
        view = getattr(self, "view", None)
        if view is not None and Shiboken.isValid(view):
            view.detach_from_scene()

    def hideEvent(self, event):
        view = getattr(self, "view", None)
        if view is not None and Shiboken.isValid(view):
            try:
                view._end_reposition_drag()
            except Exception:
                pass
            view.release_touch()
            view.detach_bus()
        # Stop the follow timer before detach so a tick cannot re-attach / raise
        # the host while the overlay is closing for profile stop.
        self._stop_host_follow()
        self._detach_host(activate_host=False, hide_window=True)
        super().hideEvent(event)

    def closeEvent(self, event):
        self._stop_host_follow()
        self._detach_host(activate_host=False, hide_window=True)
        self.detach_from_scene()
        super().closeEvent(event)

    def paintEvent(self, event):
        if live_window_is_layered(self.page_canvas):
            painter = QtGui.QPainter(self)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
            painter.fillRect(event.rect(), QtGui.QColor(0, 0, 0, 0))
            painter.end()
            return
        super().paintEvent(event)

    def _chrome_signature(self):
        canvas = self.page_canvas
        page = self.scene.page_by_id(self.page_id) or {}
        return (
            self.page_id,
            page.get("name"),
            page.get("window_x"),
            page.get("window_y"),
            normalize_background_mode(canvas.get("background_mode")),
            canvas.get("width"),
            canvas.get("height"),
            canvas.get("monitor_index"),
            canvas.get("monitor_name"),
            canvas.get("frameless"),
            canvas.get("always_on_top"),
            canvas.get("show_drag_bar"),
            canvas.get("chroma_color"),
            canvas.get("interactive"),
            bool(getattr(self.scene, "mouse_reposition_enabled", False)),
            canvas.get("attach_to_window"),
            canvas.get("attach_window_title"),
            canvas.get("attach_window_exe"),
        )

    def _sync_page_title(self):
        page = self.scene.page_by_id(self.page_id)
        title = overlay_window_title(page)
        self.setWindowTitle(title)
        if getattr(self, "_drag_label", None) is not None:
            name = (page or {}).get("name") or "Overlay"
            self._drag_label.setText(f"{OVERLAY_WINDOW_TITLE} — {name}  —  hide this bar before capturing")

    def _open_control_panel(self):
        try:
            from gremlin.ui.obs_overlay import OverlayManager

            OverlayManager().open_control_panel(parent=self)
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: open control panel failed: {err}")

    def _restore_or_center(self):
        if is_onscreen_mode(self.page_canvas):
            return
        page = self.scene.page_by_id(self.page_id)
        if page is None:
            _center_on_screen(self)
            return
        wx, wy = page.get("window_x"), page.get("window_y")
        if wx is None or wy is None:
            _center_on_screen(self)
            return
        self.move(int(wx), int(wy))
        if not _window_on_a_screen(self):
            page["window_x"] = None
            page["window_y"] = None
            self.scene._dirty = True
            _center_on_screen(self)

    def _record_window_position(self):
        if self._applying_flags or is_onscreen_mode(self.page_canvas) or self._host_attached:
            return
        self.scene.record_page_position(self.x(), self.y(), page_id=self.page_id, emit=False)
        self._chrome_sig = self._chrome_signature()

    def _on_scene_changed(self):
        if not Shiboken.isValid(self):
            return
        if QtCore.QThread.currentThread() is not self.thread():
            QtCore.QTimer.singleShot(0, self, self._on_scene_changed)
            return
        sig = self._chrome_signature()
        if sig == self._chrome_sig:
            return
        self._apply_window_flags()

    def show_without_activating(self):
        """Show the live overlay without pulling focus out of the game or JG Ex."""
        if not Shiboken.isValid(self):
            return
        interactive = is_interactive_overlay(self.page_canvas)
        reposition = self.scene.mouse_reposition_enabled
        if not interactive or reposition:
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.show()
        if sys.platform == "win32" and (not interactive or reposition):
            try:
                from .host_window import apply_noactivate_exstyle

                hwnd = int(self.winId() or 0)
                if hwnd:
                    apply_noactivate_exstyle(hwnd)
            except Exception:
                pass

    def _apply_window_flags(self):
        if self._applying_flags or not Shiboken.isValid(self):
            return
        self._applying_flags = True
        was_attached = bool(self._host_attached)
        try:
            self._chrome_sig = self._chrome_signature()
            self._sync_page_title()
            onscreen = is_onscreen_mode(self.page_canvas)
            interactive = is_interactive_overlay(self.page_canvas)
            reposition = self.scene.mouse_reposition_enabled
            mouse_capture = interactive or reposition
            attach = bool(self.page_canvas.get("attach_to_window"))
            visible = self.isVisible()
            # Detach only when leaving app-share or rebuilding HWND flags.
            # Unconditional detach on every apply was yanking focus from the game.
            flags_preview = None
            if onscreen:
                flags = (
                    QtCore.Qt.Window
                    | QtCore.Qt.FramelessWindowHint
                    | QtCore.Qt.WindowStaysOnTopHint
                    | QtCore.Qt.Tool
                )
                if attach:
                    flags = QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint
                    if not interactive or reposition:
                        flags |= QtCore.Qt.WindowDoesNotAcceptFocus
                elif reposition:
                    # Capture mouse on the control target only; never steal game focus.
                    flags |= QtCore.Qt.WindowDoesNotAcceptFocus
                elif not interactive:
                    flags |= QtCore.Qt.WindowDoesNotAcceptFocus | QtCore.Qt.WindowTransparentForInput
                flags_preview = flags
            else:
                layered = live_window_is_layered(self.page_canvas)
                flags = QtCore.Qt.Window | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint
                if layered or self.page_canvas.get("frameless"):
                    flags = QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint
                if self.page_canvas.get("always_on_top"):
                    flags |= QtCore.Qt.WindowStaysOnTopHint
                if not interactive or attach or reposition:
                    flags |= QtCore.Qt.WindowDoesNotAcceptFocus
                flags_preview = flags
            flags_changed = int(self.windowFlags()) != int(flags_preview)
            if was_attached and (flags_changed or not attach):
                self._detach_host()

            if onscreen:
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, not mouse_capture)
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, not interactive or reposition)
                self.setAttribute(QtCore.Qt.WA_AcceptTouchEvents, interactive and not reposition)
                if flags_changed:
                    # Never change flags while visible — Windows HWND UAF risk.
                    if visible:
                        self.hide()
                    self.setWindowFlags(flags_preview)
                    self._sync_page_title()
                self.drag_bar.setVisible(False)
                if Shiboken.isValid(self.view):
                    self.view._sync_paint_mode()
                    self.view._apply_size()
                if attach:
                    self.adjustSize()
                else:
                    apply_onscreen_geometry(self.scene, emit=False, page_id=self.page_id)
                    info = resolve_overlay_screen(self.page_canvas)
                    if info:
                        self.setGeometry(info["x"], info["y"], info["width"], info["height"])
                    else:
                        self.adjustSize()
            else:
                layered = live_window_is_layered(self.page_canvas)
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, layered)
                self.setAttribute(QtCore.Qt.WA_NoSystemBackground, layered)
                self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
                self.setAttribute(QtCore.Qt.WA_AcceptTouchEvents, interactive and not reposition)
                if layered:
                    _transparent_palette(self)
                    if Shiboken.isValid(self.view):
                        _transparent_palette(self.view)
                if flags_changed:
                    if visible:
                        self.hide()
                    self.setWindowFlags(flags_preview)
                    self._sync_page_title()
                show_bar = bool(self.page_canvas.get("show_drag_bar", True)) or layered
                if self.page_canvas.get("attach_to_window"):
                    show_bar = False
                self.drag_bar.setVisible(show_bar)
                chroma = chroma_fill_color(self.page_canvas)
                bar = chroma if chroma.alpha() > 80 else QtGui.QColor("#8a93a3")
                fg = gremlin.ui.ui_common.Color.normalColor()
                self.drag_bar.setStyleSheet(f"background:{bar.darker(130).name()}; color:{fg};")
                if Shiboken.isValid(self.view):
                    self.view._sync_paint_mode()
                    self.view._apply_size()
                self.adjustSize()
                if not self.page_canvas.get("attach_to_window"):
                    self._restore_or_center()
            if visible and flags_changed and Shiboken.isValid(self):
                self.show_without_activating()
            if Shiboken.isValid(self):
                self._apply_click_through(onscreen and not mouse_capture)
            if live_window_is_layered(self.page_canvas) and Shiboken.isValid(self) and (visible or self.isVisible()):
                _extend_frame_into_client(self)
        finally:
            self._applying_flags = False
        if Shiboken.isValid(self):
            self._sync_host_attach()

    def _apply_click_through(self, enabled: bool):
        if sys.platform != "win32":
            return
        if not Shiboken.isValid(self):
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_transparent = 0x00000020
            ws_ex_noactivate = 0x08000000
            ws_ex_toolwindow = 0x00000080
            if ctypes.sizeof(ctypes.c_void_p) == 8:
                user32.GetWindowLongPtrW.restype = ctypes.c_longlong
                user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
                style = user32.GetWindowLongPtrW(hwnd, gwl_exstyle)
                # Always keep NOACTIVATE on live overlays so app-share attach
                # and toggle show cannot steal the game's foreground.
                extras = ws_ex_noactivate | ws_ex_toolwindow
                if enabled:
                    extras |= ws_ex_transparent
                    style = style | extras
                else:
                    style = (style | (ws_ex_noactivate | ws_ex_toolwindow)) & ~ws_ex_transparent
                user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style)
            else:
                style = user32.GetWindowLongW(hwnd, gwl_exstyle)
                extras = ws_ex_noactivate | ws_ex_toolwindow
                if enabled:
                    extras |= ws_ex_transparent
                    style = style | extras
                else:
                    style = (style | (ws_ex_noactivate | ws_ex_toolwindow)) & ~ws_ex_transparent
                user32.SetWindowLongW(hwnd, gwl_exstyle, style)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020 | 0x0010)
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: click-through style failed: {err}")

    def _start_host_follow(self):
        if sys.platform != "win32" or not Shiboken.isValid(self):
            return
        if not self._host_timer.isActive():
            self._host_timer.start()
        self._sync_host_attach()

    def _stop_host_follow(self):
        timer = getattr(self, "_host_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def _sync_host_attach(self):
        if sys.platform != "win32" or not Shiboken.isValid(self) or self._applying_flags:
            return
        canvas = self.page_canvas
        want = bool(canvas.get("attach_to_window")) and is_onscreen_mode(canvas)
        title = str(canvas.get("attach_window_title") or "").strip()
        exe = str(canvas.get("attach_window_exe") or "").strip()
        # After SetParent, Qt often reports isVisible()==False even though the
        # child HWND is live. Treating that as "not shown" caused a detach every
        # tick, which promoted the game (and its cursor) over JG Ex.
        live = self.isVisible() or bool(self._host_attached)
        if not want or (not title and not exe):
            self._detach_host()
            return
        if not live:
            return
        from .app_view import resolve_application_hwnd
        from .host_window import attach_overlay_hwnd, place_overlay_in_host

        host = resolve_application_hwnd(title, exe, self._host_hwnd)
        if not host:
            self._detach_host()
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        if not self._host_attached or host != self._host_hwnd:
            self._detach_host()
            if not attach_overlay_hwnd(hwnd, host):
                return
            self._host_hwnd = host
            self._host_attached = True
        cw = int(canvas.get("width") or self.width() or 1)
        ch = int(canvas.get("height") or self.height() or 1)
        place_overlay_in_host(hwnd, host, cw, ch)
        if live_window_is_layered(canvas):
            _extend_frame_into_client(self)
        self._apply_click_through(
            is_onscreen_mode(canvas)
            and not is_interactive_overlay(canvas)
            and not self.scene.mouse_reposition_enabled
        )

    def _detach_host(self, activate_host: bool = False, hide_window: bool = False):
        if not self._host_attached:
            self._host_hwnd = 0
            return
        host = int(self._host_hwnd or 0)
        try:
            from .host_window import detach_overlay_hwnd

            if Shiboken.isValid(self):
                hwnd = int(self.winId())
                if hwnd:
                    detach_overlay_hwnd(
                        hwnd,
                        restore_hwnd=host,
                        activate_host=activate_host,
                        hide_window=hide_window,
                    )
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: host detach failed: {err}")
        self._host_attached = False
        self._host_hwnd = 0

    def _view_scene_pos(self, event: QtGui.QMouseEvent) -> QtCore.QPointF | None:
        local = self.view.mapFrom(self, event.position().toPoint())
        if not self.view.rect().contains(local):
            return None
        return self.view.map_to_scene(QtCore.QPointF(local))

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton and self.scene.mouse_reposition_enabled:
            scene = self._view_scene_pos(event)
            if scene is not None and _reposition_target_hit(self.scene, scene.x(), scene.y(), self.page_id):
                self._reposition_last = QtCore.QPointF(scene)
                try:
                    self.scene.set_control_highlight(True)
                except Exception:
                    pass
                self.setCursor(QtCore.Qt.SizeAllCursor)
                event.accept()
                return
            event.ignore()
            return
        touch = getattr(self.view, "_touch", None)
        if (
            event.button() == QtCore.Qt.LeftButton
            and touch is not None
            and is_interactive_overlay(self.page_canvas)
            and not self.scene.mouse_reposition_enabled
        ):
            scene = self._view_scene_pos(event)
            if scene is not None and touch.press("mouse", scene):
                event.accept()
                return
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self._reposition_last is not None and event.buttons() & QtCore.Qt.LeftButton:
            scene = self._view_scene_pos(event)
            if scene is not None:
                dx = int(round(scene.x() - self._reposition_last.x()))
                dy = int(round(scene.y() - self._reposition_last.y()))
                if dx or dy:
                    self.scene.nudge_control_target(dx, dy)
                    self._reposition_last = QtCore.QPointF(scene)
                event.accept()
                return
        touch = getattr(self.view, "_touch", None)
        if (
            touch is not None
            and is_interactive_overlay(self.page_canvas)
            and not self.scene.mouse_reposition_enabled
            and event.buttons() & QtCore.Qt.LeftButton
        ):
            scene = self._view_scene_pos(event)
            if scene is not None:
                touch.move("mouse", scene)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton and self._reposition_last is not None:
            self._reposition_last = None
            self.unsetCursor()
            event.accept()
            return
        touch = getattr(self.view, "_touch", None)
        if event.button() == QtCore.Qt.LeftButton and touch is not None:
            touch.release("mouse")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.drag_bar:
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QtCore.QEvent.MouseMove and self._drag_origin is not None and event.buttons() & QtCore.Qt.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                return True
            if event.type() == QtCore.QEvent.MouseButtonRelease:
                self._drag_origin = None
                self._record_window_position()
                return True
        return super().eventFilter(watched, event)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._record_window_position()

    def _context_menu(self, pos):
        if is_onscreen_mode(self.page_canvas):
            return
        menu = QtWidgets.QMenu(self)
        top = menu.addAction("Always on top")
        top.setCheckable(True)
        top.setChecked(bool(self.page_canvas.get("always_on_top")))
        bar = menu.addAction("Show drag bar")
        bar.setCheckable(True)
        bar.setChecked(bool(self.page_canvas.get("show_drag_bar", True)))
        frame = menu.addAction("Frameless window")
        frame.setCheckable(True)
        frame.setChecked(bool(self.page_canvas.get("frameless")))
        menu.addSeparator()
        close_action = menu.addAction("Close overlay")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is top:
            self.page_canvas["always_on_top"] = top.isChecked()
            self.scene._dirty = True
            self._apply_window_flags()
            self.show_without_activating()
        elif chosen is bar:
            self.page_canvas["show_drag_bar"] = bar.isChecked()
            self.scene._dirty = True
            self._apply_window_flags()
        elif chosen is frame:
            self.page_canvas["frameless"] = frame.isChecked()
            self.scene._dirty = True
            self._apply_window_flags()
            self.show_without_activating()
        elif chosen is close_action:
            self.hide()
