# -*- coding: utf-8; -*-
#
# Overlay color gradients (linear / radial) — Photoshop-like limited editor.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import copy
import math
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from .widgets import qcolor

MAX_STOPS = 6
GRADIENT_TYPE = "gradient"


def default_gradient(seed_color: str | None = None) -> dict[str, Any]:
    color = str(seed_color or "#ffffffff")
    if not str(color).startswith("#"):
        color = "#ffffffff"
    dark = "#ff000000"
    return {
        "type": GRADIENT_TYPE,
        "style": "linear",
        "angle": 90.0,
        "scale": 100.0,
        "smoothness": 100.0,
        "stops": [
            {"pos": 0.0, "color": color},
            {"pos": 100.0, "color": dark},
        ],
        "midpoints": [0.5],
    }


def is_gradient(value) -> bool:
    return isinstance(value, dict) and str(value.get("type") or "").casefold() == GRADIENT_TYPE


def normalize_gradient(raw, seed_color: str | None = None) -> dict[str, Any]:
    base = default_gradient(seed_color)
    if not isinstance(raw, dict):
        return base
    style = str(raw.get("style") or "linear").strip().casefold()
    base["style"] = "radial" if style.startswith("rad") else "linear"
    try:
        base["angle"] = float(raw.get("angle") if raw.get("angle") is not None else 90.0) % 360.0
    except (TypeError, ValueError):
        base["angle"] = 90.0
    try:
        base["scale"] = max(1.0, min(400.0, float(raw.get("scale") if raw.get("scale") is not None else 100.0)))
    except (TypeError, ValueError):
        base["scale"] = 100.0
    try:
        base["smoothness"] = max(0.0, min(100.0, float(raw.get("smoothness") if raw.get("smoothness") is not None else 100.0)))
    except (TypeError, ValueError):
        base["smoothness"] = 100.0

    stops_in = raw.get("stops")
    stops: list[dict[str, Any]] = []
    if isinstance(stops_in, list):
        for entry in stops_in:
            if not isinstance(entry, dict):
                continue
            try:
                pos = max(0.0, min(100.0, float(entry.get("pos") if entry.get("pos") is not None else 0.0)))
            except (TypeError, ValueError):
                continue
            color = str(entry.get("color") or "#ffffffff")
            col = qcolor(color, "#ffffffff")
            stops.append({"pos": pos, "color": col.name(QtGui.QColor.HexArgb)})
    if len(stops) < 2:
        stops = copy.deepcopy(base["stops"])
    stops.sort(key=lambda s: float(s["pos"]))
    # Enforce unique-ish positions and max count
    cleaned: list[dict[str, Any]] = []
    for stop in stops[:MAX_STOPS]:
        if cleaned and abs(float(stop["pos"]) - float(cleaned[-1]["pos"])) < 0.05:
            cleaned[-1] = stop
        else:
            cleaned.append(stop)
    while len(cleaned) < 2:
        cleaned.append({"pos": 100.0, "color": "#ff000000"})
    cleaned[0]["pos"] = 0.0
    cleaned[-1]["pos"] = 100.0
    base["stops"] = cleaned

    mids_in = raw.get("midpoints")
    mids: list[float] = []
    if isinstance(mids_in, list):
        for entry in mids_in:
            try:
                mids.append(max(0.05, min(0.95, float(entry))))
            except (TypeError, ValueError):
                mids.append(0.5)
    needed = max(0, len(cleaned) - 1)
    while len(mids) < needed:
        mids.append(0.5)
    base["midpoints"] = mids[:needed]
    return base


def gradient_preview_color(value) -> str:
    """Representative solid color for swatches / tooltips."""
    if is_gradient(value):
        grad = normalize_gradient(value)
        stops = grad.get("stops") or []
        if stops:
            return str(stops[0].get("color") or "#ffffffff")
    return str(value or "#ffffffff")


def _lerp_color(a: QtGui.QColor, b: QtGui.QColor, t: float) -> QtGui.QColor:
    t = max(0.0, min(1.0, float(t)))
    return QtGui.QColor(
        int(round(a.red() + (b.red() - a.red()) * t)),
        int(round(a.green() + (b.green() - a.green()) * t)),
        int(round(a.blue() + (b.blue() - a.blue()) * t)),
        int(round(a.alpha() + (b.alpha() - a.alpha()) * t)),
    )


def _segment_t(local: float, midpoint: float) -> float:
    """Map 0..1 within a stop pair through a Photoshop-like midpoint bias."""
    mid = max(0.05, min(0.95, float(midpoint)))
    local = max(0.0, min(1.0, float(local)))
    if local <= mid:
        return 0.5 * (local / mid) if mid > 1e-6 else 0.0
    remain = 1.0 - mid
    return 0.5 + 0.5 * ((local - mid) / remain) if remain > 1e-6 else 1.0


def sample_gradient_color(gradient: dict[str, Any], t: float) -> QtGui.QColor:
    """Sample gradient at normalized position t in [0, 1]."""
    grad = normalize_gradient(gradient)
    stops = grad["stops"]
    mids = grad["midpoints"]
    pos = max(0.0, min(1.0, float(t))) * 100.0
    if pos <= float(stops[0]["pos"]):
        return qcolor(stops[0]["color"], "#ffffffff")
    if pos >= float(stops[-1]["pos"]):
        return qcolor(stops[-1]["color"], "#ff000000")
    for i in range(len(stops) - 1):
        a = stops[i]
        b = stops[i + 1]
        a_pos = float(a["pos"])
        b_pos = float(b["pos"])
        if pos < a_pos or pos > b_pos:
            continue
        span = max(1e-6, b_pos - a_pos)
        local = (pos - a_pos) / span
        mid = mids[i] if i < len(mids) else 0.5
        eased = _segment_t(local, mid)
        # Softness lightly blends toward linear
        smooth = float(grad.get("smoothness") or 100.0) / 100.0
        mix = eased * smooth + local * (1.0 - smooth)
        return _lerp_color(qcolor(a["color"], "#ffffffff"), qcolor(b["color"], "#ff000000"), mix)
    return qcolor(stops[-1]["color"], "#ffffffff")


def gradient_qgradient(gradient: dict[str, Any], rect: QtCore.QRectF | None = None) -> QtGui.QGradient:
    """Build a QGradient mapped to the painted object's bounding rect (full span)."""
    grad = normalize_gradient(gradient)
    scale = max(0.01, float(grad.get("scale") or 100.0) / 100.0)
    if grad.get("style") == "radial":
        qg = QtGui.QRadialGradient(QtCore.QPointF(0.5, 0.5), max(0.01, 0.5 * scale))
    else:
        angle = float(grad.get("angle") or 90.0)
        rad = math.radians(angle)
        # Cover the unit square diagonally so corners receive the end stops.
        extent = 0.5 * math.sqrt(2.0) * scale
        dx = math.cos(rad) * extent
        dy = -math.sin(rad) * extent
        qg = QtGui.QLinearGradient(
            QtCore.QPointF(0.5 - dx, 0.5 - dy),
            QtCore.QPointF(0.5 + dx, 0.5 + dy),
        )
    qg.setCoordinateMode(QtGui.QGradient.ObjectBoundingMode)

    # Bake midpoints by sampling many stops into QGradient
    samples = max(24, (len(grad["stops"]) - 1) * 16)
    for i in range(samples + 1):
        t = i / float(samples)
        color = sample_gradient_color(grad, t)
        qg.setColorAt(t, color)
    return qg


def gradient_brush(gradient: dict[str, Any], rect: QtCore.QRectF | None = None) -> QtGui.QBrush:
    return QtGui.QBrush(gradient_qgradient(gradient, rect))


def swatch_gradient_brush(gradient: dict[str, Any], rect: QtCore.QRectF | None = None) -> QtGui.QBrush:
    """Left-to-right stop preview for editor bars and color wells (ignores angle/style)."""
    preview = {
        **normalize_gradient(gradient),
        "style": "linear",
        "angle": 0.0,
        "scale": 100.0,
    }
    return gradient_brush(preview, rect)


def paint_gradient_spectrum(painter: QtGui.QPainter, rect: QtCore.QRectF, gradient: dict[str, Any]):
    """Paint a horizontal spectrum of the gradient stops (pixel columns — always visible)."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    grad = normalize_gradient(gradient)
    # Checkerboard for translucent stops
    painter.fillRect(rect, QtGui.QColor("#2a2a2a"))
    tile = 6
    light = QtGui.QColor("#3a3a3a")
    left = int(math.floor(rect.left()))
    top = int(math.floor(rect.top()))
    right = int(math.ceil(rect.right()))
    bottom = int(math.ceil(rect.bottom()))
    for y in range(top, bottom, tile):
        for x in range(left, right, tile):
            if ((x // tile) + (y // tile)) % 2 == 0:
                painter.fillRect(x, y, tile, tile, light)
    width = max(1, right - left)
    for i in range(width):
        t = i / float(max(1, width - 1))
        color = sample_gradient_color(grad, t)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        painter.drawRect(QtCore.QRectF(left + i, rect.top(), 1.25, rect.height()))


def paint_value_brush(value, rect: QtCore.QRectF | None = None, default: str = "#121826"):
    """Brush for a solid color string or gradient dict (uses angle / style)."""
    if is_gradient(value):
        target = rect if rect is not None else QtCore.QRectF(0, 0, 64, 64)
        return gradient_brush(value, target)
    color = qcolor(value, default)
    if color.alpha() <= 0:
        return QtCore.Qt.NoBrush
    return QtGui.QBrush(color)


class _GradientBar(QtWidgets.QWidget):
    """Preview bar with color stops (bottom) and midpoint diamonds."""

    changed = QtCore.Signal()
    stop_selected = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(56)
        self.setMinimumWidth(260)
        self._gradient = default_gradient()
        self._selected = 0
        self._drag = None  # ("stop", i) | ("mid", i)

    def set_gradient(self, gradient: dict[str, Any]):
        self._gradient = normalize_gradient(gradient)
        self._selected = max(0, min(self._selected, len(self._gradient["stops"]) - 1))
        self.update()

    def gradient(self) -> dict[str, Any]:
        return copy.deepcopy(self._gradient)

    def selected_index(self) -> int:
        return self._selected

    def _bar_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(12, 18, max(8.0, self.width() - 24), 16)

    def _pos_to_x(self, pos: float) -> float:
        bar = self._bar_rect()
        return bar.left() + (max(0.0, min(100.0, pos)) / 100.0) * bar.width()

    def _x_to_pos(self, x: float) -> float:
        bar = self._bar_rect()
        if bar.width() <= 1e-6:
            return 0.0
        return max(0.0, min(100.0, (x - bar.left()) / bar.width() * 100.0))

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        bar = self._bar_rect()
        paint_gradient_spectrum(painter, bar, self._gradient)
        painter.setPen(QtGui.QPen(QtGui.QColor("#666"), 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(bar)

        stops = self._gradient["stops"]
        mids = self._gradient["midpoints"]
        for i, mid in enumerate(mids):
            a = float(stops[i]["pos"])
            b = float(stops[i + 1]["pos"])
            pos = a + (b - a) * float(mid)
            x = self._pos_to_x(pos)
            diamond = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, bar.top() - 10),
                    QtCore.QPointF(x + 5, bar.top() - 5),
                    QtCore.QPointF(x, bar.top()),
                    QtCore.QPointF(x - 5, bar.top() - 5),
                ]
            )
            painter.setBrush(QtGui.QColor("#dddddd"))
            painter.setPen(QtGui.QPen(QtGui.QColor("#222"), 1))
            painter.drawPolygon(diamond)

        for i, stop in enumerate(stops):
            x = self._pos_to_x(float(stop["pos"]))
            selected = i == self._selected
            marker = QtCore.QRectF(x - 6, bar.bottom() + 2, 12, 14)
            painter.setBrush(qcolor(stop.get("color"), "#ffffff"))
            painter.setPen(QtGui.QPen(QtGui.QColor("#4ea1ff" if selected else "#222"), 2 if selected else 1))
            painter.drawRect(marker)
            tip = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, bar.bottom()),
                    QtCore.QPointF(x - 5, bar.bottom() + 5),
                    QtCore.QPointF(x + 5, bar.bottom() + 5),
                ]
            )
            painter.drawPolygon(tip)
        painter.end()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() != QtCore.Qt.LeftButton:
            return
        pos = event.position() if hasattr(event, "position") else event.localPos()
        x, y = float(pos.x()), float(pos.y())
        bar = self._bar_rect()
        stops = self._gradient["stops"]
        # Midpoints
        for i, mid in enumerate(self._gradient["midpoints"]):
            a = float(stops[i]["pos"])
            b = float(stops[i + 1]["pos"])
            mx = self._pos_to_x(a + (b - a) * float(mid))
            if abs(x - mx) <= 7 and bar.top() - 12 <= y <= bar.top() + 2:
                self._drag = ("mid", i)
                return
        # Stops
        for i, stop in enumerate(stops):
            sx = self._pos_to_x(float(stop["pos"]))
            if abs(x - sx) <= 8 and bar.bottom() - 2 <= y <= bar.bottom() + 18:
                self._selected = i
                self._drag = ("stop", i)
                self.stop_selected.emit(i)
                self.update()
                return
        # Double-ish add: click on bar adds stop if room
        if bar.contains(QtCore.QPointF(x, y)) and len(stops) < MAX_STOPS:
            new_pos = self._x_to_pos(x)
            color = sample_gradient_color(self._gradient, new_pos / 100.0).name(QtGui.QColor.HexArgb)
            stops.append({"pos": new_pos, "color": color})
            stops.sort(key=lambda s: float(s["pos"]))
            stops[0]["pos"] = 0.0
            stops[-1]["pos"] = 100.0
            self._gradient["stops"] = stops
            self._gradient["midpoints"] = [0.5] * (len(stops) - 1)
            # select nearest
            self._selected = min(range(len(stops)), key=lambda i: abs(float(stops[i]["pos"]) - new_pos))
            self.stop_selected.emit(self._selected)
            self.changed.emit()
            self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if not self._drag:
            return
        pos = event.position() if hasattr(event, "position") else event.localPos()
        x = float(pos.x())
        kind, index = self._drag
        stops = self._gradient["stops"]
        if kind == "stop":
            if index in (0, len(stops) - 1):
                return
            left = float(stops[index - 1]["pos"]) + 0.5
            right = float(stops[index + 1]["pos"]) - 0.5
            stops[index]["pos"] = max(left, min(right, self._x_to_pos(x)))
            self.changed.emit()
            self.update()
        elif kind == "mid":
            a = float(stops[index]["pos"])
            b = float(stops[index + 1]["pos"])
            span = max(1e-6, b - a)
            rel = (self._x_to_pos(x) - a) / span
            self._gradient["midpoints"][index] = max(0.05, min(0.95, rel))
            self.changed.emit()
            self.update()

    def mouseReleaseEvent(self, _event):
        self._drag = None

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if self._selected <= 0 or self._selected >= len(self._gradient["stops"]) - 1:
            return
        if len(self._gradient["stops"]) <= 2:
            return
        menu = QtWidgets.QMenu(self)
        act = menu.addAction("Delete stop")
        chosen = menu.exec(event.globalPos())
        if chosen is act:
            del self._gradient["stops"][self._selected]
            self._gradient["stops"][0]["pos"] = 0.0
            self._gradient["stops"][-1]["pos"] = 100.0
            self._gradient["midpoints"] = [0.5] * (len(self._gradient["stops"]) - 1)
            self._selected = min(self._selected, len(self._gradient["stops"]) - 1)
            self.stop_selected.emit(self._selected)
            self.changed.emit()
            self.update()


class GradientEditorDialog(QtWidgets.QDialog):
    """Limited Photoshop-like gradient editor."""

    preview_changed = QtCore.Signal(object)

    def __init__(self, gradient=None, seed_color: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gradient")
        self.setMinimumWidth(420)
        self._gradient = normalize_gradient(gradient, seed_color=seed_color)
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self._emit_preview)
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self._style = QtWidgets.QComboBox()
        self._style.addItem("Linear", "linear")
        self._style.addItem("Radial", "radial")
        self._style.setCurrentIndex(1 if self._gradient.get("style") == "radial" else 0)
        self._style.currentIndexChanged.connect(self._on_style)
        form.addRow("Style", self._style)

        angle_row = QtWidgets.QWidget()
        angle_layout = QtWidgets.QHBoxLayout(angle_row)
        angle_layout.setContentsMargins(0, 0, 0, 0)
        self._dial = QtWidgets.QDial()
        self._dial.setRange(0, 359)
        self._dial.setWrapping(True)
        self._dial.setNotchesVisible(True)
        self._dial.setFixedSize(52, 52)
        self._dial.setValue(int(round(float(self._gradient.get("angle") or 90))) % 360)
        self._angle = QtWidgets.QSpinBox()
        self._angle.setRange(0, 359)
        self._angle.setSuffix("°")
        self._angle.setValue(int(round(float(self._gradient.get("angle") or 90))) % 360)
        self._dial.valueChanged.connect(self._on_angle)
        self._angle.valueChanged.connect(self._on_angle)
        angle_layout.addWidget(self._dial)
        angle_layout.addWidget(self._angle)
        angle_layout.addStretch()
        form.addRow("Angle", angle_row)

        self._scale = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._scale.setRange(1, 400)
        self._scale.setValue(int(round(float(self._gradient.get("scale") or 100))))
        self._scale_spin = QtWidgets.QSpinBox()
        self._scale_spin.setRange(1, 400)
        self._scale_spin.setSuffix("%")
        self._scale_spin.setValue(self._scale.value())
        scale_row = QtWidgets.QWidget()
        scale_layout = QtWidgets.QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.addWidget(self._scale, 1)
        scale_layout.addWidget(self._scale_spin)
        self._scale.valueChanged.connect(self._on_scale)
        self._scale_spin.valueChanged.connect(self._on_scale)
        form.addRow("Scale", scale_row)

        self._smooth = QtWidgets.QSpinBox()
        self._smooth.setRange(0, 100)
        self._smooth.setSuffix("%")
        self._smooth.setValue(int(round(float(self._gradient.get("smoothness") or 100))))
        self._smooth.valueChanged.connect(self._on_smooth)
        form.addRow("Smoothness", self._smooth)
        layout.addLayout(form)

        hint = QtWidgets.QLabel("Click the bar to add a stop (max 6). Drag stops and diamonds to adjust. Right-click a middle stop to delete.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._bar = _GradientBar()
        self._bar.set_gradient(self._gradient)
        self._bar.changed.connect(self._from_bar)
        self._bar.stop_selected.connect(self._on_stop_selected)
        layout.addWidget(self._bar)

        stop_row = QtWidgets.QHBoxLayout()
        self._stop_color = QtWidgets.QPushButton()
        self._stop_color.setFixedHeight(28)
        self._stop_color.setCursor(QtCore.Qt.PointingHandCursor)
        self._stop_color.clicked.connect(self._pick_stop_color)
        self._stop_pos = QtWidgets.QDoubleSpinBox()
        self._stop_pos.setRange(0.0, 100.0)
        self._stop_pos.setSuffix(" %")
        self._stop_pos.valueChanged.connect(self._on_stop_pos)
        stop_row.addWidget(QtWidgets.QLabel("Stop color"))
        stop_row.addWidget(self._stop_color, 1)
        stop_row.addWidget(QtWidgets.QLabel("Location"))
        stop_row.addWidget(self._stop_pos)
        layout.addLayout(stop_row)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_angle_enabled()
        self._refresh_stop_editors()

    def result_gradient(self) -> dict[str, Any]:
        return normalize_gradient(self._gradient)

    def _emit_preview(self):
        self.preview_changed.emit(self.result_gradient())

    def _schedule_preview(self):
        if not self._preview_timer.isActive():
            self._preview_timer.start()

    def _sync_angle_enabled(self):
        linear = self._style.currentData() == "linear"
        self._dial.setEnabled(linear)
        self._angle.setEnabled(linear)

    def _push(self):
        self._gradient = normalize_gradient(self._gradient)
        self._bar.set_gradient(self._gradient)
        self._refresh_stop_editors()
        self._schedule_preview()

    def _from_bar(self):
        self._gradient = self._bar.gradient()
        self._refresh_stop_editors()
        self._schedule_preview()

    def _on_style(self, _i=None):
        self._gradient["style"] = str(self._style.currentData() or "linear")
        self._sync_angle_enabled()
        self._push()

    def _on_angle(self, value):
        value = int(value) % 360
        for w in (self._dial, self._angle):
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)
        self._gradient["angle"] = float(value)
        self._push()

    def _on_scale(self, value):
        value = int(value)
        for w in (self._scale, self._scale_spin):
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)
        self._gradient["scale"] = float(value)
        self._push()

    def _on_smooth(self, value):
        self._gradient["smoothness"] = float(value)
        self._push()

    def _on_stop_selected(self, index: int):
        self._refresh_stop_editors()

    def _refresh_stop_editors(self):
        stops = self._gradient.get("stops") or []
        idx = self._bar.selected_index()
        if not stops:
            return
        idx = max(0, min(idx, len(stops) - 1))
        color = qcolor(stops[idx].get("color"), "#ffffff")
        self._stop_color.setStyleSheet(
            f"background:{color.name(QtGui.QColor.HexArgb)}; border:1px solid #555; border-radius:3px;"
        )
        self._stop_pos.blockSignals(True)
        self._stop_pos.setValue(float(stops[idx].get("pos") or 0))
        edge = idx in (0, len(stops) - 1)
        self._stop_pos.setEnabled(not edge)
        self._stop_pos.blockSignals(False)

    def _pick_stop_color(self):
        idx = self._bar.selected_index()
        stops = self._gradient.get("stops") or []
        if not stops:
            return
        idx = max(0, min(idx, len(stops) - 1))
        current = qcolor(stops[idx].get("color"), "#ffffff")
        chosen = QtWidgets.QColorDialog.getColor(
            current,
            self,
            "Stop color",
            QtWidgets.QColorDialog.DontUseNativeDialog | QtWidgets.QColorDialog.ShowAlphaChannel,
        )
        if chosen.isValid():
            self._gradient["stops"][idx]["color"] = chosen.name(QtGui.QColor.HexArgb)
            self._push()

    def _on_stop_pos(self, value):
        idx = self._bar.selected_index()
        stops = self._gradient.get("stops") or []
        if idx <= 0 or idx >= len(stops) - 1:
            return
        left = float(stops[idx - 1]["pos"]) + 0.5
        right = float(stops[idx + 1]["pos"]) - 0.5
        stops[idx]["pos"] = max(left, min(right, float(value)))
        self._push()
