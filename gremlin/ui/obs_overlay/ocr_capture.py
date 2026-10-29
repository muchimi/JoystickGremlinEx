# -*- coding: utf-8; -*-
#
# Screen capture helpers for the overlay OCR widget (widget ROI or fullscreen).
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets

from .model import is_onscreen_mode, normalize_ocr_region

syslog = logging.getLogger("system")

_TEST_COUNTDOWN_S = 5
_TEST_CAPTURE_LEASES = 0
_TEST_CAPTURE_WINDOWS = []
_LAST_TOPMOST_ASSERT_S = 0.0
_TOPMOST_ASSERT_MIN_INTERVAL_S = 2.0


def _overlay_windows() -> list[QtWidgets.QWidget]:
    windows = []
    try:
        from gremlin.ui.obs_overlay import OverlayManager

        mgr = OverlayManager()
        for window in getattr(mgr, "_overlays", {}).values():
            if window is None:
                continue
            try:
                from shiboken6 import Shiboken

                if Shiboken.isValid(window) and window.isVisible():
                    windows.append(window)
            except Exception:
                if window.isVisible():
                    windows.append(window)
    except Exception:
        pass
    return windows


def _item_geometry(item: dict[str, Any]) -> QtCore.QRect | None:
    try:
        x = int(item.get("x") or 0)
        y = int(item.get("y") or 0)
        w = max(1, int(item.get("w") or 1))
        h = max(1, int(item.get("h") or 1))
    except (TypeError, ValueError):
        return None
    return QtCore.QRect(x, y, w, h)


def _page_id_for_item(item: dict[str, Any]) -> str | None:
    try:
        from gremlin.ui.obs_overlay import OverlayManager

        widget_id = str(item.get("id") or "")
        for page in OverlayManager().scene.pages:
            for widget in page.get("widgets") or []:
                if str(widget.get("id") or "") == widget_id:
                    return page.get("id")
    except Exception:
        pass
    return None


def _widget_screen_rect_from_overlay(item: dict[str, Any], *, require_visible: bool = True) -> QtCore.QRect | None:
    """Map canvas widget coords through a live OverlayWindow client origin."""
    try:
        from gremlin.ui.obs_overlay import OverlayManager
        from shiboken6 import Shiboken

        mgr = OverlayManager()
        page_id = _page_id_for_item(item)
        window = None
        if page_id:
            window = getattr(mgr, "_overlays", {}).get(page_id)
        if window is None:
            overlays = getattr(mgr, "_overlays", {}) or {}
            window = next(iter(overlays.values()), None) if overlays else None
        if window is None or not Shiboken.isValid(window):
            return None
        # App-share SetParent makes Qt report isVisible()==False while the child
        # HWND is live — still map through it when attached.
        live = bool(window.isVisible()) or bool(getattr(window, "_host_attached", False))
        if require_visible and not live:
            return None
        local = _item_geometry(item)
        if local is None:
            return None
        origin = window.mapToGlobal(QtCore.QPoint(0, 0))
        return QtCore.QRect(origin.x() + local.x(), origin.y() + local.y(), local.width(), local.height())
    except Exception as err:
        syslog.debug(f"OBS OVERLAY OCR: widget screen rect failed: {err}")
        return None


def _widget_screen_rect_from_monitor(item: dict[str, Any]) -> QtCore.QRect | None:
    """On-screen mode: canvas is 1:1 with the chosen monitor — map widget → desktop."""
    try:
        from gremlin.ui.obs_overlay import OverlayManager
        from .overlay_window import resolve_overlay_screen

        mgr = OverlayManager()
        page_id = _page_id_for_item(item)
        canvas = mgr.scene.canvas_for(page_id) if page_id else mgr.scene.canvas
        if not is_onscreen_mode(canvas):
            return None
        info = resolve_overlay_screen(canvas)
        if not info:
            return None
        local = _item_geometry(item)
        if local is None:
            return None
        return QtCore.QRect(
            int(info["x"]) + local.x(),
            int(info["y"]) + local.y(),
            local.width(),
            local.height(),
        )
    except Exception as err:
        syslog.debug(f"OBS OVERLAY OCR: monitor rect failed: {err}")
        return None


def resolve_capture_rect(item: dict[str, Any]) -> tuple[QtCore.QRect | None, str]:
    """Resolve the desktop capture target before any hide/show side effects.

    Returns (rect_or_none, region) where region is widget|fullscreen.
    For fullscreen, rect is the chosen monitor geometry.
    """
    style = item.get("style") or {}
    region = normalize_ocr_region(style.get("ocr_region"))
    if region == "fullscreen":
        try:
            from gremlin.ui.obs_overlay import OverlayManager
            from .overlay_window import resolve_overlay_screen

            page_id = _page_id_for_item(item)
            mgr = OverlayManager()
            canvas = mgr.scene.canvas_for(page_id) if page_id else mgr.scene.canvas
            info = resolve_overlay_screen(canvas)
            if info:
                return (
                    QtCore.QRect(int(info["x"]), int(info["y"]), int(info["width"]), int(info["height"])),
                    "fullscreen",
                )
        except Exception:
            pass
        app = QtWidgets.QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return None, "fullscreen"
        geo = screen.geometry()
        return QtCore.QRect(geo.x(), geo.y(), geo.width(), geo.height()), "fullscreen"

    rect = _widget_screen_rect_from_overlay(item, require_visible=True)
    if rect is None:
        rect = _widget_screen_rect_from_monitor(item)
    if rect is None:
        # Last resort: overlay may be hidden but still positioned.
        rect = _widget_screen_rect_from_overlay(item, require_visible=False)
    return rect, "widget"


def _monitor_index_for_item(item: dict[str, Any]) -> int:
    try:
        from gremlin.ui.obs_overlay import OverlayManager

        page_id = _page_id_for_item(item)
        canvas = OverlayManager().scene.canvas_for(page_id) if page_id else OverlayManager().scene.canvas
        return int(canvas.get("monitor_index") or 0)
    except Exception:
        return 0


def _invalidate_live_overlays() -> None:
    """Force live overlay frame rebuild after hide/show or GDI capture."""
    try:
        from gremlin.ui.obs_overlay import OverlayManager

        for window in getattr(OverlayManager(), "_overlays", {}).values():
            if window is None:
                continue
            try:
                from shiboken6 import Shiboken

                if not Shiboken.isValid(window):
                    continue
            except Exception:
                pass
            try:
                view = getattr(window, "view", None)
                target = view if view is not None else window
                invalidate = getattr(target, "_invalidate_static_layer", None)
                if callable(invalidate):
                    invalidate()
                target.update()
            except Exception:
                pass
    except Exception:
        pass


def _assert_overlays_topmost(*, force: bool = False) -> None:
    """Re-pin live overlays in the TOPMOST band (no show/hide, no Qt update).

    Armed OCR scans used to call this on every frame; that contended with AFCS
    on the UI thread. Throttle unless ``force`` (hide/show restore path).
    """
    global _LAST_TOPMOST_ASSERT_S
    try:
        import time

        now = time.monotonic()
        if not force and (now - _LAST_TOPMOST_ASSERT_S) < _TOPMOST_ASSERT_MIN_INTERVAL_S:
            return
        _LAST_TOPMOST_ASSERT_S = now
        from gremlin.ui.obs_overlay import OverlayManager

        for window in getattr(OverlayManager(), "_overlays", {}).values():
            if window is None:
                continue
            try:
                from shiboken6 import Shiboken

                if not Shiboken.isValid(window):
                    continue
            except Exception:
                pass
            assert_fn = getattr(window, "assert_topmost", None)
            if callable(assert_fn):
                try:
                    assert_fn()
                except Exception:
                    pass
    except Exception:
        pass


def capture_for_item(
    item: dict[str, Any],
    *,
    hide_overlay: bool = False,
    rect: QtCore.QRect | None = None,
) -> QtGui.QImage | None:
    """Capture the OCR region for a widget.

    Periodic scans keep the overlay visible: GDI ``SRCCOPY`` omits layered
    windows from the bitmap, and a cached re-blit repairs any on-screen
    corruption. Pass ``hide_overlay=True`` for one-shot Test captures when a
    clean grab without the HUD is preferred.

    Hide/show + processEvents must run on the UI thread — callers on a worker
    should use ``capture_for_item_sync`` which marshals here via InvokeUiMethod.
    """
    from gremlin.remote_video import grab_screen_image, grab_screen_rect

    style = item.get("style") or {}
    region = normalize_ocr_region(style.get("ocr_region"))
    # Resolve geometry *before* hiding — a hidden overlay window made the old
    # path fall back to primary-monitor grab (wrong screen in multi-monitor setups).
    if rect is None:
        rect, region = resolve_capture_rect(item)

    hidden: list[tuple[QtWidgets.QWidget, bool]] = []
    try:
        if hide_overlay:
            for window in _overlay_windows():
                hidden.append((window, window.isVisible()))
                try:
                    window.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
                    window.hide()
                except Exception:
                    pass
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)

        if region == "fullscreen" and (rect is None or rect.width() <= 0):
            image = grab_screen_image(_monitor_index_for_item(item), max_width=1920)
            if image is None or image.isNull():
                syslog.warning("OBS OVERLAY OCR: fullscreen GDI grab returned null")
            return image

        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            syslog.warning(
                "OBS OVERLAY OCR: capture region unresolved widget=%s region=%s",
                item.get("id"),
                region,
            )
            return None
        image = grab_screen_rect(rect.x(), rect.y(), rect.width(), rect.height(), max_width=1920)
        if image is None or image.isNull():
            syslog.warning(
                "OBS OVERLAY OCR: GDI grab null rect=(%s,%s %sx%s) widget=%s",
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height(),
                item.get("id"),
            )
        return image
    finally:
        restored = False
        for window, was_visible in hidden:
            try:
                window.setAttribute(QtCore.Qt.WA_DontShowOnScreen, False)
                if was_visible:
                    window.show()
                    restored = True
            except Exception:
                pass
        if restored or hide_overlay:
            # Full rebuild after hide/show so layered bodies are not left blank.
            _invalidate_live_overlays()
            _assert_overlays_topmost(force=True)
        else:
            # Armed scans leave the HUD up; BitBlt can still knock the HWND out of
            # the TOPMOST band. Re-pin only — no update()/hide (those reopen-flash).
            _assert_overlays_topmost(force=False)


def _wait_capture(done, timeout, cancelled):
    deadline = time.monotonic() + timeout
    while not (cancelled is not None and cancelled()):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if done.wait(min(0.02, remaining)):
            return not (cancelled is not None and cancelled())
    return False


def _capture_armed_on_worker(
    item: dict[str, Any],
    *,
    rect: QtCore.QRect | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> QtGui.QImage | None:
    """Armed-scan capture: resolve geometry on UI (fast), BitBlt on the worker.

    The previous path marshaled the entire GDI grab onto the UI thread and
    blocked the OCR worker until it finished — that stalled AFCS / input while
    detection was armed.
    """
    import threading

    import gremlin.util
    from gremlin.remote_video import grab_screen_image, grab_screen_rect

    external_cancelled = cancelled
    abandoned = threading.Event()
    cancelled = lambda: abandoned.is_set() or (external_cancelled is not None and external_cancelled())
    style = item.get("style") or {}
    region = normalize_ocr_region(style.get("ocr_region"))
    resolved: dict[str, Any] = {"rect": rect, "region": region, "error": None}

    def _resolve():
        if cancelled is not None and cancelled():
            return
        try:
            if resolved["rect"] is None:
                resolved["rect"], resolved["region"] = resolve_capture_rect(item)
            # Cheap, throttled topmost re-pin on the UI thread (no wait for BitBlt).
            _assert_overlays_topmost(force=False)
        except Exception as err:
            resolved["error"] = err

    try:
        if gremlin.util.is_ui_thread():
            _resolve()
        else:
            done = threading.Event()

            def _resolve_and_signal():
                try:
                    _resolve()
                finally:
                    done.set()

            gremlin.util.InvokeUiMethod(_resolve_and_signal)
            if not _wait_capture(done, 1.0, cancelled):
                was_cancelled = cancelled()
                abandoned.set()
                if was_cancelled:
                    return None
                syslog.warning(
                    "OBS OVERLAY OCR: rect resolve timed out widget=%s",
                    item.get("id") if item else None,
                )
                return None
    except Exception as err:
        syslog.warning(f"OBS OVERLAY OCR: armed capture resolve failed: {err}")
        return None
    if cancelled is not None and cancelled():
        return None
    if resolved.get("error") is not None:
        syslog.warning(f"OBS OVERLAY OCR: armed capture resolve error: {resolved['error']}")
        return None

    use_rect = resolved.get("rect")
    use_region = str(resolved.get("region") or region)
    if use_region == "fullscreen" and (use_rect is None or use_rect.width() <= 0):
        return grab_screen_image(_monitor_index_for_item(item), max_width=1920)
    if use_rect is None or use_rect.width() <= 0 or use_rect.height() <= 0:
        syslog.warning(
            "OBS OVERLAY OCR: capture region unresolved widget=%s region=%s",
            item.get("id"),
            use_region,
        )
        return None
    return grab_screen_rect(use_rect.x(), use_rect.y(), use_rect.width(), use_rect.height(), max_width=1920)


def capture_for_item_sync(
    item: dict[str, Any],
    *,
    hide_overlay: bool = False,
    rect: QtCore.QRect | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> QtGui.QImage | None:
    """Thread-safe capture for OCR.

    Armed scans (``hide_overlay=False``) only marshal rect resolution to the UI
    thread; BitBlt runs on the worker. Test captures that hide the overlay still
    run fully on the UI thread (hide/show + processEvents).
    """
    import threading

    import gremlin.util

    if cancelled is not None and cancelled():
        return None
    if not hide_overlay:
        try:
            return _capture_armed_on_worker(item, rect=rect, cancelled=cancelled)
        except Exception as err:
            syslog.warning(f"OBS OVERLAY OCR: armed capture failed: {err}")
            return None

    holder: dict[str, Any] = {"image": None, "error": None}
    external_cancelled = cancelled
    abandoned = threading.Event()
    cancelled = lambda: abandoned.is_set() or (external_cancelled is not None and external_cancelled())

    def _run():
        if cancelled is not None and cancelled():
            return
        try:
            holder["image"] = capture_for_item(item, hide_overlay=True, rect=rect)
        except Exception as err:
            holder["error"] = err
            holder["image"] = None
            syslog.warning(f"OBS OVERLAY OCR: capture_for_item raised: {err}")

    try:
        if gremlin.util.is_ui_thread():
            _run()
        else:
            done = threading.Event()

            def _run_and_signal():
                try:
                    _run()
                finally:
                    done.set()

            gremlin.util.InvokeUiMethod(_run_and_signal)
            if not _wait_capture(done, 5.0, cancelled):
                was_cancelled = cancelled()
                abandoned.set()
                if was_cancelled:
                    return None
                syslog.warning(
                    "OBS OVERLAY OCR: capture timed out waiting for UI thread widget=%s",
                    item.get("id") if item else None,
                )
                return None
    except Exception as err:
        syslog.warning(f"OBS OVERLAY OCR: capture_for_item_sync failed: {err}")
        return None
    if (cancelled is not None and cancelled()) or holder.get("error") is not None:
        return None
    return holder.get("image")


class OcrRegionCountdown(QtWidgets.QWidget):
    """Click-through highlight of the OCR capture rect with a countdown."""

    finished = QtCore.Signal()
    cancelled = QtCore.Signal()

    def __init__(self, rect: QtCore.QRect, seconds: int = _TEST_COUNTDOWN_S, parent=None):
        super().__init__(parent)
        self._done = False
        self._seconds_left = max(1, int(seconds))
        self._rect = QtCore.QRect(rect)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowTransparentForInput
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        # Slightly pad so the border is visible around the capture region.
        pad = 4
        self.setGeometry(
            self._rect.x() - pad,
            self._rect.y() - pad,
            self._rect.width() + pad * 2,
            self._rect.height() + pad * 2,
        )
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self.show()
        self.raise_()
        self._timer.start()
        self.update()

    def _tick(self):
        if self._done:
            return
        self._seconds_left -= 1
        if self._seconds_left <= 0:
            self._done = True
            self._timer.stop()
            self.hide()
            self.finished.emit()
            self.deleteLater()
            return
        self.update()

    def cancel(self):
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.hide()
        self.cancelled.emit()
        self.deleteLater()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        # Hollow frame — leave the interior fully clear so the user can place text.
        border = QtCore.QRect(2, 2, self.width() - 4, self.height() - 4)
        pen = QtGui.QPen(QtGui.QColor(0, 200, 255, 230), 3)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(border)
        # Countdown badge at the top-left of the frame (outside the capture hole).
        badge = QtCore.QRect(8, 8, 72, 48)
        painter.setBrush(QtGui.QColor(0, 0, 0, 180))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(badge, 8, 8)
        painter.setPen(QtGui.QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge, QtCore.Qt.AlignCenter, str(self._seconds_left))
        painter.end()


def _hide_overlays_for_test() -> list[tuple[QtWidgets.QWidget, bool]]:
    """Hide live overlays so the countdown frame sits over real screen content."""
    global _TEST_CAPTURE_LEASES, _TEST_CAPTURE_WINDOWS
    if _TEST_CAPTURE_LEASES:
        _TEST_CAPTURE_LEASES += 1
        return _TEST_CAPTURE_WINDOWS
    _TEST_CAPTURE_LEASES = 1
    hidden: list[tuple[QtWidgets.QWidget, bool]] = []
    _TEST_CAPTURE_WINDOWS = hidden
    for window in _overlay_windows():
        hidden.append((window, window.isVisible()))
        try:
            window.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
            window.hide()
        except Exception:
            pass
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
    return hidden


def _restore_overlays(hidden: list[tuple[QtWidgets.QWidget, bool]]) -> None:
    global _TEST_CAPTURE_LEASES, _TEST_CAPTURE_WINDOWS
    if _TEST_CAPTURE_LEASES:
        _TEST_CAPTURE_LEASES -= 1
        if _TEST_CAPTURE_LEASES:
            return
        hidden, _TEST_CAPTURE_WINDOWS = _TEST_CAPTURE_WINDOWS, []
    for window, was_visible in hidden:
        try:
            window.setAttribute(QtCore.Qt.WA_DontShowOnScreen, False)
            if was_visible:
                window.show()
        except Exception:
            pass


class OcrTestCapture(QtCore.QObject):
    """Owned countdown handle; completion/cancellation restores the HUD once."""

    def __init__(self, item, rect, seconds, on_done, cancelled):
        super().__init__(QtWidgets.QApplication.instance())
        self._item = item
        self._rect = rect
        self._on_done = on_done
        self._cancelled = cancelled
        self._done = False
        self._hidden = _hide_overlays_for_test()
        try:
            self._countdown = OcrRegionCountdown(rect, seconds=seconds)
        except Exception:
            _restore_overlays(self._hidden)
            self.deleteLater()
            raise
        self._countdown.finished.connect(self._finish)
        self._countdown.cancelled.connect(self._cancel_ui)

    def start(self):
        if self._cancelled is not None and self._cancelled():
            self._cancel_ui()
        else:
            self._countdown.start()

    def cancel(self):
        import gremlin.util

        gremlin.util.InvokeUiMethod(self._cancel_ui)

    def _cleanup(self):
        hidden, self._hidden = self._hidden, []
        _restore_overlays(hidden)
        self._countdown = None
        self._on_done = None
        self._item = None
        self.deleteLater()

    def _cancel_ui(self):
        if self._done:
            return
        self._done = True
        try:
            self._countdown.cancel()
        finally:
            self._cleanup()

    def _finish(self):
        if self._done:
            return
        if self._cancelled is not None and self._cancelled():
            self._cancel_ui()
            return
        self._done = True
        callback = self._on_done
        try:
            image = capture_for_item(self._item, hide_overlay=False, rect=self._rect)
        except Exception as err:
            syslog.warning("OBS OVERLAY OCR: Test once capture failed: %s", err)
            image = None
        finally:
            self._cleanup()
        if callback is not None and not (self._cancelled is not None and self._cancelled()):
            callback(image)


def run_test_capture_countdown(
    item: dict[str, Any],
    *,
    seconds: int = _TEST_COUNTDOWN_S,
    on_done: Callable[[QtGui.QImage | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> OcrTestCapture | None:
    """Show the OCR region on screen, countdown, then capture. UI thread only.

    Returns a cancellation handle, or None if the region cannot be resolved.
    """
    # Resolve before hiding so on-screen multi-monitor mapping stays correct.
    rect, _region = resolve_capture_rect(item)
    if rect is None or rect.width() <= 0 or rect.height() <= 0:
        syslog.warning("OBS OVERLAY OCR: Test once — could not resolve capture region")
        return None

    handle = OcrTestCapture(item, rect, seconds, on_done, cancelled)
    handle.start()
    syslog.info(
        f"OBS OVERLAY OCR: Test once — region {rect.x()},{rect.y()} "
        f"{rect.width()}x{rect.height()}, countdown {seconds}s"
    )
    return handle
