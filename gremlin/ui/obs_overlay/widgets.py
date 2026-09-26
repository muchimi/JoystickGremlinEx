# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import math
import os
from typing import Any

from PySide6 import QtCore, QtGui

from .model import (
    is_onscreen_mode,
    normalize_paddle_direction,
    normalize_switch_appearance,
    switch_2way_cardinal_slots,
    switch_2way_cardinal_to_value,
    switch_2way_value_to_cardinal,
)
from .shapes import button_uses_shape_path, normalize_shape_kind, shape_path, uses_shape_geometry


def qcolor(value, default="#ffffff") -> QtGui.QColor:
    """Parse a solid color. Gradient dicts resolve to their first stop (or default)."""
    if isinstance(value, QtGui.QColor):
        return value if value.isValid() else QtGui.QColor(default)
    if isinstance(value, dict):
        # Overlay gradients are stored as {"type":"gradient", "stops":[{"color":...}, ...]}.
        if str(value.get("type") or "").casefold() == "gradient":
            stops = value.get("stops")
            if isinstance(stops, list):
                for stop in stops:
                    if isinstance(stop, dict) and stop.get("color"):
                        value = stop.get("color")
                        break
                else:
                    value = default
            else:
                value = default
        else:
            value = default
    try:
        color = QtGui.QColor(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        color = QtGui.QColor()
    if not color.isValid():
        color = QtGui.QColor(default)
        if not color.isValid():
            color = QtGui.QColor("#ffffff")
    return color


def chroma_fill_color(canvas: dict[str, Any] | None) -> QtGui.QColor:
    return qcolor((canvas or {}).get("chroma_color"), "#00FF00")


def live_window_is_layered(canvas: dict[str, Any] | None, designer: bool = False) -> bool:
    """True when the live overlay must composite onto the desktop (not a black fill)."""
    if designer:
        return False
    if is_onscreen_mode(canvas):
        return True
    return chroma_fill_color(canvas).alpha() < 255


def _font_scale(item: dict[str, Any] | None) -> float:
    if not item:
        return 1.0
    style = item.get("style") or {}
    if not style.get("auto_scale_font"):
        return 1.0
    base = float(style.get("font_scale_base") or 0)
    if base <= 1:
        base = 100.0
    current = min(float(item.get("w") or 1), float(item.get("h") or 1))
    return max(0.35, min(6.0, current / base))


def _scaled_font_px(style: dict[str, Any], key: str, item: dict[str, Any] | None, default: int = 11) -> int:
    size = style.get(key)
    if size is None and key.startswith("axis_"):
        size = style.get("font_size")
    px = float(size if size is not None else default)
    return max(6, int(round(px * _font_scale(item))))


def effective_font_size(item: dict[str, Any] | None, key: str = "font_size", default: int = 11) -> int:
    """Pixel size actually drawn, including auto-scale."""
    style = (item or {}).get("style") or {}
    return _scaled_font_px(style, key, item, default)


def _make_font(family: str | None, size, bold: bool, italic: bool = False, underline: bool = False, strike: bool = False) -> QtGui.QFont:
    font = QtGui.QFont()
    font.setFamily(family or "Segoe UI")
    font.setPixelSize(max(6, int(size or 11)))
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    font.setUnderline(bool(underline))
    font.setStrikeOut(bool(strike))
    font.setStyleStrategy(QtGui.QFont.PreferAntialias)
    return font


def _font_flag(style: dict[str, Any], name: str, prefix: str = "", default=False):
    key = f"{prefix}{name}" if prefix else name
    if key in style:
        return style.get(key, default)
    return style.get(name, default)


def _font(style: dict[str, Any], item: dict[str, Any] | None = None, prefix: str = "") -> QtGui.QFont:
    size_key = f"{prefix}font_size" if prefix else "font_size"
    family = style.get(f"{prefix}font_family") if prefix else style.get("font_family")
    if prefix:
        family = family or style.get("font_family")
    return _make_font(
        family,
        _scaled_font_px(style, size_key, item),
        _font_flag(style, "font_bold", prefix, True),
        _font_flag(style, "font_italic", prefix, False),
        _font_flag(style, "font_underline", prefix, False),
        _font_flag(style, "font_strike", prefix, False),
    )


def _axis_label_font(style: dict[str, Any], item: dict[str, Any] | None = None) -> QtGui.QFont:
    return _font(style, item, prefix="axis_label_")


def _painter_is_designer(painter: QtGui.QPainter | None) -> bool:
    """True when painting the Overlay tab canvas (not the live overlay window)."""
    try:
        device = painter.device() if painter is not None else None
    except Exception:
        return False
    return bool(getattr(device, "interactive", False))


def _outline_pen(
    border,
    width,
    fill_color: QtGui.QColor,
    default_border="#2c3a52",
    designer: bool = False,
) -> QtGui.QPen:
    """Pen for a shape. Designer-only ghost when fill and border are both transparent."""
    try:
        w = float(width)
    except (TypeError, ValueError):
        w = 2.0
    border_c = qcolor(border, default_border)
    if border_c.alpha() <= 0:
        if designer and fill_color.alpha() <= 0:
            ghost = QtGui.QPen(QtGui.QColor("#ffffff"))
            ghost.setWidthF(max(1.0, w))
            ghost.setStyle(QtCore.Qt.DashLine)
            ghost.setJoinStyle(QtCore.Qt.RoundJoin)
            ghost.setCapStyle(QtCore.Qt.RoundCap)
            return ghost
        return QtGui.QPen(QtCore.Qt.NoPen)
    if fill_color.alpha() <= 0:
        return _pen(border_c, max(1.0, w) if designer else w)
    return _pen(border, w)


def set_fill_and_outline(
    painter: QtGui.QPainter,
    fill,
    border,
    width,
    default_fill="#121826",
    default_border="#2c3a52",
    rect=None,
):
    from .gradient import gradient_preview_color, is_gradient, paint_value_brush

    if is_gradient(fill):
        target = QtCore.QRectF(rect) if rect is not None else QtCore.QRectF(painter.clipBoundingRect())
        if target.isEmpty():
            target = QtCore.QRectF(0, 0, 100, 100)
        painter.setBrush(paint_value_brush(fill, target, default_fill))
        fill_c = qcolor(gradient_preview_color(fill), default_fill)
    else:
        fill_c = qcolor(fill, default_fill)
        painter.setBrush(QtCore.Qt.NoBrush if fill_c.alpha() <= 0 else QtGui.QBrush(fill_c))
    painter.setPen(
        _outline_pen(
            border,
            width,
            fill_c,
            default_border,
            designer=_painter_is_designer(painter),
        )
    )


def _shadow_offset_xy(angle_deg: float, distance: float) -> tuple[float, float]:
    """0° = right, 90° = up (screen Y is down)."""
    rad = math.radians(float(angle_deg) % 360.0)
    dist = max(0.0, float(distance))
    return dist * math.cos(rad), -dist * math.sin(rad)


def resolve_font_shadow(style: dict[str, Any] | None, prefix: str = "") -> dict[str, Any]:
    """Normalize font shadow style; migrates legacy dx/dy into angle/distance."""
    style = style or {}
    on = bool(_font_flag(style, "font_shadow", prefix, False))
    color = qcolor(_font_flag(style, "font_shadow_color", prefix, "#80000000"), "#80000000")
    angle_raw = _font_flag(style, "font_shadow_angle", prefix, None)
    distance_raw = _font_flag(style, "font_shadow_distance", prefix, None)
    try:
        dx_legacy = float(_font_flag(style, "font_shadow_dx", prefix, 2) or 0)
    except (TypeError, ValueError):
        dx_legacy = 2.0
    try:
        dy_legacy = float(_font_flag(style, "font_shadow_dy", prefix, 2) or 0)
    except (TypeError, ValueError):
        dy_legacy = 2.0

    if angle_raw is None or distance_raw is None:
        distance = math.hypot(dx_legacy, dy_legacy)
        angle = (math.degrees(math.atan2(-dy_legacy, dx_legacy)) % 360.0) if distance > 1e-6 else 135.0
    else:
        try:
            angle = float(angle_raw) % 360.0
        except (TypeError, ValueError):
            angle = 135.0
        try:
            distance = max(0.0, float(distance_raw))
        except (TypeError, ValueError):
            distance = 3.0

    try:
        spread = max(0.0, min(100.0, float(_font_flag(style, "font_shadow_spread", prefix, 0) or 0)))
    except (TypeError, ValueError):
        spread = 0.0
    try:
        size = max(0.0, float(_font_flag(style, "font_shadow_size", prefix, 0) or 0))
    except (TypeError, ValueError):
        size = 0.0

    dx, dy = _shadow_offset_xy(angle, distance)
    # Dirty-rect padding: offset + blur (spread expansion is capped in the painter).
    expand = min(size * (spread / 100.0), size, 24.0)
    return {
        "on": on,
        "color": color,
        "angle": angle,
        "distance": distance,
        "spread": spread,
        "size": size,
        "dx": dx,
        "dy": dy,
        "extent": distance + min(size, 48.0) + expand,
    }


def _draw_text_at(painter: QtGui.QPainter, text: str, rect, point, flags: int, ox: float, oy: float):
    if rect is not None:
        painter.drawText(rect.translated(ox, oy), flags, text)
    elif point is not None:
        painter.drawText(point + QtCore.QPointF(ox, oy), text)


def _expand_path(path: QtGui.QPainterPath, expand: float) -> QtGui.QPainterPath:
    """Grow a filled path outward (round join) for shadow spread."""
    if expand <= 0.25 or path.isEmpty():
        return QtGui.QPainterPath(path)
    stroker = QtGui.QPainterPathStroker()
    stroker.setWidth(float(expand) * 2.0)
    stroker.setJoinStyle(QtCore.Qt.RoundJoin)
    stroker.setCapStyle(QtCore.Qt.RoundCap)
    return path.united(stroker.createStroke(path))


def _paint_font_shadow(
    painter: QtGui.QPainter,
    text: str,
    font: QtGui.QFont,
    shadow: dict[str, Any],
    rect,
    point,
    flags: int,
    path: QtGui.QPainterPath | None = None,
):
    """Drop shadow.

    Size = blur radius (px). Spread = modest silhouette growth before blur
    (0–100% of Size, capped). Softness is approximated by faint offset stamps —
    never by scaling the shape up (that created a huge black slab).
    """
    if not shadow.get("on"):
        return
    dx = float(shadow.get("dx") or 0)
    dy = float(shadow.get("dy") or 0)
    blur = max(0.0, float(shadow.get("size") or 0))
    spread = max(0.0, min(100.0, float(shadow.get("spread") or 0)))
    # Keep spread from exploding into a giant opaque pad behind the widget.
    expand = min(blur * (spread / 100.0), max(0.0, blur), 24.0)
    soft = min(blur, 48.0)
    base = QtGui.QColor(shadow.get("color") or "#80000000")
    if base.alpha() <= 0:
        return

    def _fill_text(color: QtGui.QColor, ox: float, oy: float):
        painter.setPen(color)
        _draw_text_at(painter, text, rect, point, flags, ox, oy)

    if path is not None:
        shape = _expand_path(path, expand)
        painter.save()
        painter.setPen(QtCore.Qt.NoPen)
        if soft < 0.5:
            stamp = QtGui.QPainterPath(shape)
            stamp.translate(dx, dy)
            painter.fillPath(stamp, base)
            painter.restore()
            return
        # Soft edge: same-sized stamps at small offsets (box/gaussian approx).
        layers = max(3, min(8, int(math.ceil(soft * 0.5)) + 2))
        ring = max(8, min(14, 6 + layers))
        for layer in range(layers, 0, -1):
            t = layer / float(layers)
            radius = soft * t
            falloff = math.exp(-3.2 * t * t)
            sample = QtGui.QColor(base)
            # Keep stamps very faint so overlaps only soften the rim.
            sample.setAlphaF(min(0.12, base.alphaF() * falloff * (0.55 / layers)))
            for i in range(ring):
                a = (2.0 * math.pi * i) / ring
                stamp = QtGui.QPainterPath(shape)
                stamp.translate(dx + radius * math.cos(a), dy + radius * math.sin(a))
                painter.fillPath(stamp, sample)
        core = QtGui.QPainterPath(shape)
        core.translate(dx, dy)
        core_color = QtGui.QColor(base)
        core_color.setAlphaF(min(0.55, base.alphaF() * 0.75))
        painter.fillPath(core, core_color)
        painter.restore()
        return

    # Text (no path): same offset-stamp approach.
    if soft < 0.5 and expand < 0.5:
        _fill_text(base, dx, dy)
        return
    layers = max(3, min(8, int(math.ceil(soft * 0.5)) + 2))
    ring = max(8, min(14, 6 + layers))
    for layer in range(layers, 0, -1):
        t = layer / float(layers)
        radius = soft * t + expand * 0.25
        falloff = math.exp(-3.2 * t * t)
        sample = QtGui.QColor(base)
        sample.setAlphaF(min(0.14, base.alphaF() * falloff * (0.6 / layers)))
        for i in range(ring):
            a = (2.0 * math.pi * i) / ring
            _fill_text(sample, dx + radius * math.cos(a), dy + radius * math.sin(a))
    core = QtGui.QColor(base)
    core.setAlphaF(min(0.7, base.alphaF() * 0.85))
    _fill_text(core, dx, dy)


def _draw_text_ex(
    painter: QtGui.QPainter,
    text: str,
    target,
    font: QtGui.QFont,
    color,
    style: dict[str, Any] | None = None,
    prefix: str = "",
    flags: int | None = None,
):
    """Draw widget text with optional shadow and pixel stroke."""
    if not text:
        return
    style = style or {}
    flags = int(QtCore.Qt.AlignCenter if flags is None else flags)
    fill = qcolor(color, "#f4efe4")
    shadow = resolve_font_shadow(style, prefix)
    try:
        stroke_w = float(_font_flag(style, "font_stroke_width", prefix, 0) or 0)
    except (TypeError, ValueError):
        stroke_w = 0.0
    stroke_color = qcolor(_font_flag(style, "font_stroke_color", prefix, "#000000"), "#000000")
    painter.save()
    painter.setFont(font)
    rect = target if isinstance(target, QtCore.QRectF) else None
    point = target if isinstance(target, QtCore.QPointF) else None
    if stroke_w > 0:
        metrics = QtGui.QFontMetricsF(font)
        if rect is not None:
            br = metrics.boundingRect(text)
            x = rect.center().x() - br.width() / 2.0 - br.left()
            y = rect.center().y() + (metrics.ascent() - metrics.descent()) / 2.0
        else:
            x = point.x() if point is not None else 0.0
            y = point.y() if point is not None else 0.0
        path = QtGui.QPainterPath()
        path.addText(QtCore.QPointF(x, y), font, text)
        _paint_font_shadow(painter, text, font, shadow, rect, point, flags, path=path)
        painter.strokePath(path, _pen(stroke_color, stroke_w))
        painter.fillPath(path, fill)
    else:
        _paint_font_shadow(painter, text, font, shadow, rect, point, flags, path=None)
        painter.setPen(fill)
        if rect is not None:
            painter.drawText(rect, flags, text)
        elif point is not None:
            painter.drawText(point, text)
    painter.restore()


def fill_brush(value, default="#121826", rect=None):
    from .gradient import is_gradient, paint_value_brush

    if is_gradient(value):
        target = QtCore.QRectF(rect) if rect is not None else QtCore.QRectF(0, 0, 100, 100)
        return paint_value_brush(value, target, default)
    color = qcolor(value, default)
    if color.alpha() <= 0:
        return QtCore.Qt.NoBrush
    return color


def resolve_widget_shadow(style: dict[str, Any] | None) -> dict[str, Any]:
    """Widget body drop shadow (Appearance), same params as font shadow."""
    style = style or {}
    mapped = {
        "font_shadow": style.get("shadow"),
        "font_shadow_color": style.get("shadow_color"),
        "font_shadow_angle": style.get("shadow_angle"),
        "font_shadow_distance": style.get("shadow_distance"),
        "font_shadow_spread": style.get("shadow_spread"),
        "font_shadow_size": style.get("shadow_size"),
        "font_shadow_dx": style.get("shadow_dx"),
        "font_shadow_dy": style.get("shadow_dy"),
    }
    return resolve_font_shadow(mapped, "")


def widget_body_path(item: dict[str, Any]) -> QtGui.QPainterPath:
    """Approximate filled body used for widget drop shadows."""
    rect = widget_rect(item)
    style = item.get("style") or {}
    path = QtGui.QPainterPath()
    wtype = str(item.get("type") or "")
    try:
        radius = max(0.0, float(style.get("corner_radius") or 0))
    except (TypeError, ValueError):
        radius = 0.0
    circular = wtype in {
        "axis_stick_circle",
        "axis_radial",
        "axis_dial",
        "axis_encoder",
        "hat",
        "axis_radio",
    }
    if uses_shape_geometry(item):
        try:
            shaped = shape_path(item)
            if shaped is not None and not shaped.isEmpty():
                return shaped
        except Exception:
            pass
    if circular or (wtype == "button" and normalize_shape_kind(style.get("shape")) in ("circle", "ellipse")):
        path.addEllipse(rect)
    elif radius > 0.05:
        path.addRoundedRect(rect, radius, radius)
    else:
        path.addRect(rect)
    return path


def _widget_shadow_image_path(item: dict[str, Any]) -> str:
    """File path whose alpha should mask the drop shadow (empty → geometric body)."""
    style = item.get("style") or {}
    # Prefer off/base image; any widget with a raster/SVG asset shadows that silhouette.
    for key in ("image_path", "paddle_image", "image_path_on"):
        path = str(style.get(key) or "").strip()
        if path:
            return path
    return ""


_widget_shadow_cache: dict[tuple, QtGui.QPixmap] = {}
# While True, skip drop shadows so large-group move/rotate cannot stall the UI thread.
_interaction_paint = False


def set_interaction_paint(enabled: bool):
    global _interaction_paint
    _interaction_paint = bool(enabled)


def interaction_paint() -> bool:
    return _interaction_paint


def _image_shadow_silhouette(path: str, width: int, height: int, color: QtGui.QColor) -> QtGui.QPixmap:
    """Tinted copy of *path* that keeps the image alpha (transparent where the image is)."""
    width = max(1, int(width))
    height = max(1, int(height))
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    key = (path, mtime, width, height, color.rgba(), 2)  # v2 = DestinationIn mask
    cached = _widget_shadow_cache.get(key)
    if cached is not None and not cached.isNull():
        return cached

    from .images import is_svg_path, render_svg

    buffer = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    buffer.fill(QtCore.Qt.transparent)
    layer = QtGui.QPainter(buffer)
    layer.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    layer.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
    local = QtCore.QRectF(0.0, 0.0, float(width), float(height))
    # Fill shadow color, then DestinationIn with the image alpha (keeps transparency).
    layer.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
    layer.fillRect(local, color)
    layer.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
    if is_svg_path(path):
        render_svg(layer, path, local, keep_aspect=False)
    else:
        pixmap = _widget_image_pixmap(path)
        if pixmap.isNull():
            layer.end()
            return QtGui.QPixmap()
        image = pixmap.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        scaled = QtGui.QPixmap.fromImage(image).scaled(
            QtCore.QSize(width, height),
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        layer.drawPixmap(0, 0, scaled)
    layer.end()
    out = QtGui.QPixmap.fromImage(buffer)
    if len(_widget_shadow_cache) > 48:
        _widget_shadow_cache.clear()
    _widget_shadow_cache[key] = out
    return out


def _paint_image_drop_shadow(painter: QtGui.QPainter, item: dict[str, Any], path: str, shadow: dict[str, Any]):
    """Drop shadow masked to the image alpha; Size/Spread match geometric widget shadows."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    keep_aspect = bool(style.get("image_keep_aspect", True))
    content = _image_content_rect(path, rect, keep_aspect)
    if content is None or content.isEmpty():
        return
    dx = float(shadow.get("dx") or 0)
    dy = float(shadow.get("dy") or 0)
    blur = max(0.0, float(shadow.get("size") or 0))
    spread = max(0.0, min(100.0, float(shadow.get("spread") or 0)))
    expand = min(blur * (spread / 100.0), max(0.0, blur), 24.0)
    soft = min(blur, 48.0)
    base = QtGui.QColor(shadow.get("color") or "#80000000")
    if base.alpha() <= 0:
        return
    width = max(1, int(math.ceil(content.width())))
    height = max(1, int(math.ceil(content.height())))
    # Opaque RGB silhouette; stamp strength comes from painter opacity × base alpha.
    tint = QtGui.QColor(base)
    tint.setAlpha(255)
    silhouette = _image_shadow_silhouette(path, width, height, tint)
    if silhouette.isNull():
        return
    origin = content.topLeft()
    widget_op = _opacity(style)
    base_a = max(0.0, min(1.0, base.alphaF()))

    def _stamp(alpha: float, ox: float, oy: float, pad: float = 0.0):
        painter.setOpacity(widget_op * max(0.0, min(1.0, alpha)))
        if pad <= 0.05:
            painter.drawPixmap(QtCore.QPointF(origin.x() + ox, origin.y() + oy), silhouette)
            return
        painter.drawPixmap(
            QtCore.QRectF(origin.x() + ox - pad, origin.y() + oy - pad, width + pad * 2.0, height + pad * 2.0),
            silhouette,
            QtCore.QRectF(0, 0, width, height),
        )

    painter.save()
    if soft < 0.5:
        _stamp(base_a, dx, dy, expand)
        painter.restore()
        return
    # Same soft-stamp model as geometric shadows, but on the alpha silhouette.
    layers = max(3, min(6, int(math.ceil(soft * 0.4)) + 2))
    ring = max(6, min(10, 4 + layers))
    for layer in range(layers, 0, -1):
        t = layer / float(layers)
        radius = soft * t
        falloff = math.exp(-3.2 * t * t)
        sample_a = min(0.12, base_a * falloff * (0.55 / layers))
        for i in range(ring):
            a = (2.0 * math.pi * i) / ring
            _stamp(sample_a, dx + radius * math.cos(a), dy + radius * math.sin(a), expand)
    _stamp(min(0.55, base_a * 0.75), dx, dy, expand)
    painter.restore()


def paint_widget_drop_shadow(painter: QtGui.QPainter, item: dict[str, Any]):
    shadow = resolve_widget_shadow(item.get("style"))
    if not shadow.get("on"):
        return
    # Drag/rotate of large groups must not pay for soft-shadow stamps on the UI thread.
    if _interaction_paint:
        return
    image_path = _widget_shadow_image_path(item)
    if image_path:
        from .images import is_svg_path, svg_renderer

        usable = (is_svg_path(image_path) and svg_renderer(image_path) is not None) or (
            not is_svg_path(image_path) and not _widget_image_pixmap(image_path).isNull()
        )
        if usable:
            _paint_image_drop_shadow(painter, item, image_path, shadow)
            return
        # Asset configured but unloadable — never fall back to a solid rectangle slab.
        return
    path = widget_body_path(item)
    if path.isEmpty():
        return
    painter.save()
    painter.setOpacity(_opacity(item.get("style") or {}))
    _paint_font_shadow(painter, "", QtGui.QFont(), shadow, None, None, int(QtCore.Qt.AlignCenter), path=path)
    painter.restore()


def _border_w(style: dict[str, Any] | None, default: float = 2.0) -> float:
    """Border width in px. 0 is valid (no stroke); missing falls back to *default*."""
    if not border_is_enabled(style):
        return 0.0
    value = (style or {}).get("border_width")
    if value is None or value == "":
        return float(default)
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return float(default)


def border_is_enabled(style: dict[str, Any] | None) -> bool:
    """True when the widget should stroke a border. Missing key keeps legacy width behavior."""
    if not style:
        return True
    if "border_enabled" in style:
        return bool(style.get("border_enabled"))
    try:
        return float(style.get("border_width") or 0) > 0
    except (TypeError, ValueError):
        return True


def _pen(color, width=1.0) -> QtGui.QPen:
    try:
        w = float(width)
    except (TypeError, ValueError):
        w = 1.0
    if w <= 0:
        return QtGui.QPen(QtCore.Qt.NoPen)
    pen_color = qcolor(color)
    if pen_color.alpha() <= 0:
        return QtGui.QPen(QtCore.Qt.NoPen)
    pen = QtGui.QPen(pen_color)
    pen.setWidthF(w)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    return pen


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _opacity(style: dict[str, Any]) -> float:
    try:
        value = style.get("opacity")
        if value is None:
            return 1.0
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def _deadzone(value: float, style: dict) -> float:
    zone = float(style.get("deadzone") or 0.0)
    if zone > 0 and abs(value) < zone:
        return 0.0
    return value


def _xy(value) -> tuple[float, float]:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return _clamp(float(value[0])), _clamp(float(value[1]))
    if isinstance(value, (int, float)):
        return _clamp(float(value)), 0.0
    return 0.0, 0.0


def _axis(value) -> float:
    if isinstance(value, (tuple, list)):
        return _clamp(float(value[0] if value else 0.0))
    if isinstance(value, (int, float)):
        return _clamp(float(value))
    return 0.0


def _pressed(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return abs(value) > 0.5
    if isinstance(value, (tuple, list)) and value:
        return any(abs(float(v)) > 0.15 for v in value)
    return False


def widget_rect(item: dict[str, Any]) -> QtCore.QRectF:
    return QtCore.QRectF(item["x"], item["y"], item["w"], item["h"])


def normalize_rotation(value) -> float:
    try:
        angle = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    angle = (angle + 180.0) % 360.0 - 180.0
    if abs(angle) < 1e-9:
        return 0.0
    return angle


def widget_rotation_deg(item: dict[str, Any] | None) -> float:
    if not item:
        return 0.0
    return normalize_rotation(item.get("rotation"))


def widget_center(item: dict[str, Any]) -> QtCore.QPointF:
    return widget_rect(item).center()


def rotate_point_around(x: float, y: float, cx: float, cy: float, degrees: float) -> tuple[float, float]:
    """Rotate (x, y) around (cx, cy) by *degrees* using QPainter's clockwise convention."""
    if abs(degrees) < 1e-9:
        return float(x), float(y)
    rad = math.radians(float(degrees))
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    dx = float(x) - float(cx)
    dy = float(y) - float(cy)
    # Same 2D matrix as QTransform.rotate (clockwise on screen y-down coords).
    return cx + cos_a * dx - sin_a * dy, cy + sin_a * dx + cos_a * dy


def apply_group_rotation_delta(
    items: list[dict[str, Any]],
    start_geoms: dict[str, dict[str, float]],
    pivot_x: float,
    pivot_y: float,
    delta_deg: float,
):
    """Orbit widget centers around a shared pivot and add *delta_deg* to each rotation.

    ``start_geoms`` maps widget id → ``{x, y, w, h, rotation}`` captured before the gesture.
    """
    for item in items:
        wid = str(item.get("id") or "")
        geom = start_geoms.get(wid)
        if not geom:
            continue
        w = max(1.0, float(geom.get("w") or item.get("w") or 1))
        h = max(1.0, float(geom.get("h") or item.get("h") or 1))
        ox = float(geom.get("x") or 0.0) + w * 0.5
        oy = float(geom.get("y") or 0.0) + h * 0.5
        nx, ny = rotate_point_around(ox, oy, pivot_x, pivot_y, delta_deg)
        item["x"] = int(round(nx - w * 0.5))
        item["y"] = int(round(ny - h * 0.5))
        item["rotation"] = normalize_rotation(float(geom.get("rotation") or 0.0) + float(delta_deg))


def widget_transform(item: dict[str, Any]) -> QtGui.QTransform:
    angle = widget_rotation_deg(item)
    center = widget_center(item)
    transform = QtGui.QTransform()
    transform.translate(center.x(), center.y())
    transform.rotate(angle)
    transform.translate(-center.x(), -center.y())
    return transform


def scene_to_widget_local(item: dict[str, Any], x: float, y: float) -> QtCore.QPointF:
    if abs(widget_rotation_deg(item)) < 0.001:
        return QtCore.QPointF(x, y)
    inverted, ok = widget_transform(item).inverted()
    if not ok:
        return QtCore.QPointF(x, y)
    return inverted.map(QtCore.QPointF(x, y))


def widget_local_to_scene(item: dict[str, Any], x: float, y: float) -> QtCore.QPointF:
    if abs(widget_rotation_deg(item)) < 0.001:
        return QtCore.QPointF(x, y)
    return widget_transform(item).map(QtCore.QPointF(x, y))


def widget_contains_point(item: dict[str, Any], x: float, y: float) -> bool:
    point = scene_to_widget_local(item, x, y)
    if uses_shape_geometry(item):
        path = shape_path(item)
        if path.contains(point):
            return True
        stroker = QtGui.QPainterPathStroker()
        border = _border_w(item.get("style"))
        stroker.setWidth(max(8.0, border + 6.0))
        return stroker.createStroke(path).contains(point)
    return widget_rect(item).contains(point)


def widget_rotated_bounds(item: dict[str, Any]) -> QtCore.QRectF:
    rect = widget_rect(item)
    if abs(widget_rotation_deg(item)) < 0.001:
        return rect
    return widget_transform(item).mapRect(rect)


def apply_widget_rotation(painter: QtGui.QPainter, item: dict[str, Any]):
    angle = widget_rotation_deg(item)
    if abs(angle) < 0.001:
        return
    center = widget_center(item)
    painter.translate(center)
    painter.rotate(angle)
    painter.translate(-center)


def _inner_rect(rect: QtCore.QRectF, style: dict[str, Any]) -> QtCore.QRectF:
    inset = max(0.5, _border_w(style) * 0.5)
    return rect.adjusted(inset, inset, -inset, -inset)


def _corner_radius(style: dict[str, Any], default: float = 6.0) -> float:
    try:
        value = style.get("corner_radius")
        if value is None:
            return default
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _clip_rounded(painter: QtGui.QPainter, rect: QtCore.QRectF, style: dict[str, Any], radius: float) -> QtCore.QRectF:
    inner = _inner_rect(rect, style)
    inset = max(0.5, _border_w(style) * 0.5)
    inner_r = max(0.0, radius - inset)
    if inner_r > 0:
        painter.setClipPath(_rounded(inner, inner_r))
    else:
        painter.setClipRect(inner)
    return inner


def _with_grid_fade(painter: QtGui.QPainter, bounds: QtCore.QRectF, style: dict[str, Any], circular: bool, draw_cb):
    if not style.get("grid_fade") or bounds.width() < 4 or bounds.height() < 4:
        draw_cb(painter)
        return
    width = max(1, int(math.ceil(bounds.width())))
    height = max(1, int(math.ceil(bounds.height())))
    pm = QtGui.QPixmap(width, height)
    pm.fill(QtCore.Qt.transparent)
    gp = QtGui.QPainter(pm)
    gp.translate(-bounds.left(), -bounds.top())
    draw_cb(gp)
    gp.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
    radius = min(bounds.width(), bounds.height()) / 2.0 if circular else max(bounds.width(), bounds.height()) / 2.0
    gradient = QtGui.QRadialGradient(bounds.center(), max(1.0, radius))
    gradient.setColorAt(0.0, QtGui.QColor(0, 0, 0, 255))
    gradient.setColorAt(0.55, QtGui.QColor(0, 0, 0, 255))
    gradient.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
    gp.fillRect(bounds, gradient)
    gp.end()
    painter.drawPixmap(bounds.topLeft(), pm)


def _draw_square_grid(painter: QtGui.QPainter, inner: QtCore.QRectF, style: dict[str, Any]):
    if not style.get("show_grid", True):
        return

    def _lines(target: QtGui.QPainter):
        target.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
        for i in range(1, 4):
            t = i / 4.0
            target.drawLine(
                QtCore.QPointF(inner.left() + inner.width() * t, inner.top()),
                QtCore.QPointF(inner.left() + inner.width() * t, inner.bottom()),
            )
            target.drawLine(
                QtCore.QPointF(inner.left(), inner.top() + inner.height() * t),
                QtCore.QPointF(inner.right(), inner.top() + inner.height() * t),
            )

    _with_grid_fade(painter, inner, style, False, _lines)


def _draw_ring_grid(painter: QtGui.QPainter, circle: QtCore.QRectF, style: dict[str, Any], rings: int):
    if not style.get("show_grid", True):
        return
    rings = max(1, int(rings))

    def _rings(target: QtGui.QPainter):
        target.setBrush(QtCore.Qt.NoBrush)
        target.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
        for i in range(1, rings + 1):
            t = i / float(rings)
            inset = (1.0 - t) * min(circle.width(), circle.height()) / 2.0
            target.drawEllipse(circle.adjusted(inset, inset, -inset, -inset))

    _with_grid_fade(painter, circle, style, True, _rings)


def _draw_crosshairs(painter: QtGui.QPainter, bounds: QtCore.QRectF, style: dict[str, Any]):
    if not style.get("show_center_line", True):
        return
    painter.setPen(_pen(style.get("crosshair"), max(1.0, float(style.get("grid_width") or 1.2))))
    painter.drawLine(QtCore.QPointF(bounds.center().x(), bounds.top()), QtCore.QPointF(bounds.center().x(), bounds.bottom()))
    painter.drawLine(QtCore.QPointF(bounds.left(), bounds.center().y()), QtCore.QPointF(bounds.right(), bounds.center().y()))


def widget_dirty_rect(item: dict[str, Any]) -> QtCore.QRect:
    """Widget bounds plus label overflow, for partial updates."""
    rect = widget_rotated_bounds(item).toAlignedRect()
    style = item.get("style") or {}
    pad = max(28, _scaled_font_px(style, "font_size", item) + 12)
    if abs(widget_rotation_deg(item)) >= 0.001:
        pad = max(pad, 36)
    extra = 0
    if _font_flag(style, "font_shadow", "", False) or _font_flag(style, "font_shadow", "axis_label_", False):
        extra = max(
            extra,
            float(resolve_font_shadow(style, "").get("extent") or 0),
            float(resolve_font_shadow(style, "axis_label_").get("extent") or 0),
        )
    if style.get("shadow"):
        extra = max(extra, float(resolve_widget_shadow(style).get("extent") or 0))
    try:
        extra = max(extra, float(_font_flag(style, "font_stroke_width", "", 0) or 0), float(_font_flag(style, "font_stroke_width", "axis_label_", 0) or 0))
    except (TypeError, ValueError):
        pass
    pad = max(pad, int(extra) + 12)
    return rect.adjusted(-pad, -pad, pad, pad)


def _draw_label(painter: QtGui.QPainter, item: dict[str, Any], rect: QtCore.QRectF, color=None, text_override=None):
    style = item.get("style") or {}
    show_mode = bool(style.get("show_current_mode")) and item.get("type") == "label"
    if text_override is not None:
        text = text_override
    elif show_mode:
        from .bindings import current_profile_mode

        text = current_profile_mode()
    elif not style.get("show_label", True):
        return
    else:
        text = item.get("label") or ""
    if not text:
        return
    label_rect = rect.adjusted(
        float(style.get("label_offset_x") or 0),
        float(style.get("label_offset_y") or 0),
        float(style.get("label_offset_x") or 0),
        float(style.get("label_offset_y") or 0),
    )
    painter.save()
    _draw_text_ex(painter, text, label_rect, _font(style, item), color or style.get("font_color"), style)
    painter.restore()


def _rounded(rect: QtCore.QRectF, radius: float) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def paint_shape(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .gradient import is_gradient

    style = item.get("style") or {}
    rect = widget_rect(item)
    kind = normalize_shape_kind(style.get("shape_kind"))
    painter.save()
    painter.setOpacity(_opacity(style))
    fill_value = style.get("fill")
    set_fill_and_outline(painter, fill_value, style.get("border"), _border_w(style), "#101820", rect=rect)
    closed = bool(style.get("shape_closed")) if kind == "line" else True
    if kind == "line" and not closed:
        painter.setBrush(QtCore.Qt.NoBrush)
    elif not is_gradient(fill_value) and qcolor(fill_value, "#101820").alpha() <= 0:
        painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawPath(shape_path(item))
    _draw_label(painter, item, rect)
    painter.restore()


_widget_image_cache: dict[str, QtGui.QPixmap] = {}
_widget_fill_cache: dict[tuple, QtGui.QImage] = {}


def _widget_image_pixmap(path: str) -> QtGui.QPixmap:
    if not path:
        return QtGui.QPixmap()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return QtGui.QPixmap()
    key = f"{path}|{mtime}"
    pixmap = _widget_image_cache.get(key)
    if pixmap is not None and not pixmap.isNull():
        return pixmap
    from .images import pixmap_from_image_path

    pixmap = pixmap_from_image_path(path, max_edge=2048)
    if pixmap.isNull():
        return QtGui.QPixmap()
    if len(_widget_image_cache) > 24:
        _widget_image_cache.clear()
    _widget_image_cache[key] = pixmap
    return pixmap


def _fill_cache_key(fill) -> str:
    """Stable key for solid or gradient fills used by the tinted-image cache."""
    from .gradient import is_gradient, normalize_gradient

    if is_gradient(fill):
        g = normalize_gradient(fill)
        stops = tuple(
            (round(float(s.get("pos", 0.0)), 4), str(s.get("color") or ""))
            for s in (g.get("stops") or [])
        )
        return (
            f"g|{g.get('style')}|{round(float(g.get('angle') or 0.0), 2)}|"
            f"{round(float(g.get('scale') or 100.0), 2)}|"
            f"{round(float(g.get('smoothness') or 0.0), 2)}|{stops}"
        )
    return f"c|{qcolor(fill, '#00000000').name(QtGui.QColor.NameFormat.HexArgb)}"


def _image_content_rect(path: str, rect: QtCore.QRectF, keep_aspect: bool) -> QtCore.QRectF | None:
    """Fitted rect where an image path is drawn inside ``rect`` (aspect-aware)."""
    if not path or rect.isEmpty():
        return None
    from .images import fitted_content_rect, is_svg_path, svg_default_size

    if is_svg_path(path):
        size = svg_default_size(path)
        if not size:
            return QtCore.QRectF(rect)
        return fitted_content_rect(size[0], size[1], rect, keep_aspect)
    pixmap = _widget_image_pixmap(path)
    if pixmap.isNull():
        return None
    return fitted_content_rect(pixmap.width(), pixmap.height(), rect, keep_aspect)


def _draw_image_path_with_fill(
    painter: QtGui.QPainter,
    path: str,
    rect: QtCore.QRectF,
    keep_aspect: bool,
    fill=None,
    default_fill: str = "#3a1518",
) -> QtCore.QRectF | None:
    """Draw an image; optional fill is masked to the image alpha via an offscreen buffer.

    Compositing on the live painter is wrong: SourceAtop would also tint whatever was
    already under the widget (chroma / previous paint). The buffer starts transparent.
    """
    from .gradient import is_gradient
    from .images import is_svg_path, render_svg

    content = _image_content_rect(path, rect, keep_aspect)
    if content is None or content.isEmpty():
        return None
    fill_visible = fill is not None and (is_gradient(fill) or qcolor(fill, "#00000000").alpha() > 0)
    if not fill_visible:
        _draw_image_path(painter, path, rect, keep_aspect)
        return content

    width = max(1, int(math.ceil(content.width())))
    height = max(1, int(math.ceil(content.height())))
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    cache_key = (path, mtime, width, height, _fill_cache_key(fill), default_fill)
    buffer = _widget_fill_cache.get(cache_key)
    if buffer is None or buffer.isNull() or buffer.width() != width or buffer.height() != height:
        buffer = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        buffer.fill(QtCore.Qt.transparent)
        layer = QtGui.QPainter(buffer)
        layer.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        layer.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        local = QtCore.QRectF(0.0, 0.0, float(width), float(height))
        if is_svg_path(path):
            render_svg(layer, path, local, keep_aspect=False)
        else:
            pixmap = _widget_image_pixmap(path)
            if pixmap.isNull():
                layer.end()
                return content
            scaled = pixmap.scaled(
                QtCore.QSize(width, height),
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            layer.drawPixmap(0, 0, scaled)
        # Keep image alpha; replace/tint with the fill color only on those pixels.
        layer.setCompositionMode(QtGui.QPainter.CompositionMode_SourceAtop)
        layer.setPen(QtCore.Qt.NoPen)
        layer.setBrush(fill_brush(fill, default_fill, rect=local))
        layer.drawRect(local)
        layer.end()
        if len(_widget_fill_cache) > 32:
            _widget_fill_cache.clear()
        _widget_fill_cache[cache_key] = buffer
    painter.drawImage(content.topLeft(), buffer)
    return content


def _draw_image_path(painter: QtGui.QPainter, path: str, rect: QtCore.QRectF, keep_aspect: bool) -> bool:
    """Paint a file path into rect — SVG via QSvgRenderer (vector-sharp), else pixmap."""
    if not path or rect.isEmpty():
        return False
    from .images import is_svg_path, render_svg

    if is_svg_path(path):
        return render_svg(painter, path, rect, keep_aspect=keep_aspect)
    pixmap = _widget_image_pixmap(path)
    if pixmap.isNull():
        return False
    _draw_fitted_pixmap(painter, pixmap, rect, keep_aspect)
    return True


def _fitted_pixmap_rect(pixmap: QtGui.QPixmap, rect: QtCore.QRectF, keep_aspect: bool) -> tuple[QtCore.QRectF, QtGui.QPixmap]:
    mode = QtCore.Qt.KeepAspectRatio if keep_aspect else QtCore.Qt.IgnoreAspectRatio
    scaled = pixmap.scaled(rect.size().toSize(), mode, QtCore.Qt.SmoothTransformation)
    return QtCore.QRectF(
        rect.center().x() - scaled.width() / 2.0,
        rect.center().y() - scaled.height() / 2.0,
        scaled.width(),
        scaled.height(),
    ), scaled


def _draw_fitted_pixmap(painter: QtGui.QPainter, pixmap: QtGui.QPixmap, rect: QtCore.QRectF, keep_aspect: bool):
    if pixmap.isNull():
        return
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    target, scaled = _fitted_pixmap_rect(pixmap, rect, keep_aspect)
    painter.drawPixmap(target.toRect(), scaled)


def _button_outline_path(item: dict[str, Any], rect: QtCore.QRectF) -> QtGui.QPainterPath:
    if button_uses_shape_path(item):
        return shape_path(item)
    style = item.get("style") or {}
    path = QtGui.QPainterPath()
    shape = (style.get("shape") or "rounded").casefold()
    radius = float(style.get("corner_radius") or 6)
    if shape == "circle":
        side = min(rect.width(), rect.height())
        path.addEllipse(QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side))
    elif shape == "pill":
        return _rounded(rect, rect.height() / 2)
    elif shape == "rect":
        path.addRect(rect)
    else:
        return _rounded(rect, radius)
    return path


def paint_image(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .gradient import is_gradient
    from .images import is_svg_path, svg_renderer

    style = item.get("style") or {}
    rect = widget_rect(item)
    painter.save()
    painter.setOpacity(_opacity(style))
    fill_value = style.get("fill")
    border_w = _border_w(style, 0)
    if is_gradient(fill_value) or qcolor(fill_value, "#00000000").alpha() > 0:
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(fill_brush(fill_value, "#00000000", rect=rect))
        painter.drawRect(rect)
    path = style.get("image_path") or ""
    keep_aspect = bool(style.get("image_keep_aspect", True))
    has_content = bool(path) and (
        (is_svg_path(path) and svg_renderer(path) is not None)
        or (not is_svg_path(path) and not _widget_image_pixmap(path).isNull())
    )
    if not has_content:
        painter.setPen(_pen(style.get("border"), border_w))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(rect)
        painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
        painter.drawText(rect, int(QtCore.Qt.AlignCenter), "No image")
        _draw_label(painter, item, rect)
        painter.restore()
        return
    _draw_image_path(painter, path, rect, keep_aspect)
    if border_w > 0:
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(_pen(style.get("border"), border_w))
        painter.drawRect(rect)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_remote_view(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Live remote client screen/app feed (master Overlay)."""
    from gremlin.remote_video import RemoteVideoHub

    style = item.get("style") or {}
    rect = widget_rect(item)
    painter.save()
    painter.setOpacity(_opacity(style))
    try:
        radius = max(0.0, float(style.get("corner_radius") or 0))
    except (TypeError, ValueError):
        radius = 0.0
    border_w = _border_w(style)
    painter.setPen(_pen(style.get("border"), border_w))
    painter.setBrush(fill_brush(style.get("fill"), "#0a0c10", rect=rect))
    if radius > 0.05:
        painter.drawRoundedRect(rect, radius, radius)
    else:
        painter.drawRect(rect)

    try:
        client_id = int(style.get("remote_client_id") or 0)
    except (TypeError, ValueError):
        client_id = 0
    hub = RemoteVideoHub()
    pixmap = hub.pixmap(client_id) if client_id else None
    if pixmap is not None and not pixmap.isNull():
        keep = bool(style.get("image_keep_aspect", True))
        mode = QtCore.Qt.KeepAspectRatio if keep else QtCore.Qt.IgnoreAspectRatio
        scaled = pixmap.scaled(rect.size().toSize(), mode, QtCore.Qt.FastTransformation)
        target = QtCore.QRectF(
            rect.center().x() - scaled.width() / 2.0,
            rect.center().y() - scaled.height() / 2.0,
            scaled.width(),
            scaled.height(),
        )
        clip = QtGui.QPainterPath()
        if radius > 0.05:
            clip.addRoundedRect(rect, radius, radius)
        else:
            clip.addRect(rect)
        painter.setClipPath(clip)
        painter.drawPixmap(target.toRect(), scaled)
        painter.setClipping(False)
    else:
        painter.setPen(qcolor(style.get("font_color"), "#8899aa"))
        msg = hub.feed_status(client_id)
        painter.drawText(rect, int(QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap), msg)
    # Don't stack the widget title over the status / live picture.
    if pixmap is not None and not pixmap.isNull():
        _draw_label(painter, item, rect)
    elif not client_id:
        _draw_label(painter, item, rect)
    painter.restore()


def paint_application(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Live capture of a local running application window."""
    from .app_view import ApplicationViewTracker

    style = item.get("style") or {}
    rect = widget_rect(item)
    painter.save()
    painter.setOpacity(_opacity(style))
    try:
        radius = max(0.0, float(style.get("corner_radius") or 0))
    except (TypeError, ValueError):
        radius = 0.0
    border_w = _border_w(style)
    painter.setPen(_pen(style.get("border"), border_w))
    painter.setBrush(fill_brush(style.get("fill"), "#0a0c10", rect=rect))
    if radius > 0.05:
        painter.drawRoundedRect(rect, radius, radius)
    else:
        painter.drawRect(rect)

    tracker = ApplicationViewTracker()
    pixmap = tracker.pixmap(item)
    if pixmap is not None and not pixmap.isNull():
        keep = bool(style.get("image_keep_aspect", True))
        clip = QtGui.QPainterPath()
        if radius > 0.05:
            clip.addRoundedRect(rect, radius, radius)
        else:
            clip.addRect(rect)
        painter.setClipPath(clip)
        _draw_fitted_pixmap(painter, pixmap, rect, keep)
        painter.setClipping(False)
        _draw_label(painter, item, rect)
    else:
        painter.setPen(qcolor(style.get("font_color"), "#8899aa"))
        msg = tracker.status(item) or "Select a running application"
        painter.drawText(rect, int(QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap), msg)
        if not (style.get("window_title") or style.get("window_exe")):
            _draw_label(painter, item, rect)
    painter.restore()


_streamdeck_pm_cache: dict[tuple, QtGui.QPixmap] = {}


def streamdeck_preferred_size(device_type=None) -> tuple[int, int]:
    """Bezel size that matches a Stream Deck key grid (and Plus dials)."""
    try:
        from gremlin.ui.streamdeck_device import device_grid_size, parse_streamdeck_device_type

        grid = device_grid_size(device_type)
        dtype = parse_streamdeck_device_type(device_type)
    except Exception:
        grid = None
        dtype = None
    cols, rows = grid or (5, 3)
    plus = dtype in (7, 8)
    key = 52
    gap = 6
    pad = 18
    width = pad * 2 + cols * key + (cols - 1) * gap
    height = pad * 2 + rows * key + (rows - 1) * gap
    if plus:
        height += gap + max(18, int(key * 0.42)) + gap + max(28, int(key * 0.62))
    return (int(width), int(height))


def _streamdeck_slot_pixmap(slot_item, pressed: bool, side: int, lcd: bool = False) -> QtGui.QPixmap:
    if slot_item is None:
        return QtGui.QPixmap()
    width = 200 if lcd else max(24, int(side))
    height = 100 if lcd else width
    key = (
        id(slot_item),
        bool(pressed),
        int(width),
        int(height),
        getattr(slot_item, "image_path", "") or "",
        getattr(slot_item, "image_pressed_path", "") or "",
        getattr(slot_item, "title", "") or "",
        getattr(slot_item, "title_pressed", "") or "",
        getattr(slot_item, "bg_color", "") or "",
        getattr(slot_item, "bg_color_pressed", "") or "",
    )
    cached = _streamdeck_pm_cache.get(key)
    if cached is not None and not cached.isNull():
        return cached
    pixmap = QtGui.QPixmap()
    try:
        from gremlin.ui.streamdeck_surface import compose_key_pixmap, item_needs_composite

        kind = getattr(slot_item, "kind", "") or ""
        use_lcd = lcd or kind in ("dial", "dial_press")
        if item_needs_composite(slot_item, pressed=pressed) or (
            pressed and item_needs_composite(slot_item, pressed=False)
        ) or (use_lcd and (getattr(slot_item, "bg_color", "") or getattr(slot_item, "bg_color_pressed", ""))):
            if use_lcd:
                pixmap = compose_key_pixmap(slot_item, pressed=pressed, width=200, height=100)
            else:
                pixmap = compose_key_pixmap(slot_item, size=max(72, width), pressed=pressed)
        if pixmap is None or pixmap.isNull():
            from gremlin.ui.streamdeck_surface import resolve_paint_image, resolve_paint_image_pressed

            raw = resolve_paint_image_pressed(slot_item) if pressed else resolve_paint_image(slot_item)
            if raw and str(raw).startswith("data:") and "," in str(raw):
                import base64

                data = base64.b64decode(str(raw).split(",", 1)[1])
                pixmap = QtGui.QPixmap()
                pixmap.loadFromData(data)
            else:
                path = ""
                if pressed:
                    path = getattr(slot_item, "image_pressed_path", "") or getattr(slot_item, "image_path", "") or ""
                else:
                    path = getattr(slot_item, "image_path", "") or ""
                if path:
                    pixmap = QtGui.QPixmap(path)
    except Exception:
        pixmap = QtGui.QPixmap()
    if len(_streamdeck_pm_cache) > 64:
        _streamdeck_pm_cache.clear()
    _streamdeck_pm_cache[key] = pixmap
    return pixmap


def _streamdeck_message_rect(painter: QtGui.QPainter, item: dict[str, Any], rect: QtCore.QRectF, text: str):
    style = item.get("style") or {}
    painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
    painter.drawText(rect.adjusted(8, 8, -8, -8), int(QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap), text)
    _draw_label(painter, item, rect)


def paint_streamdeck(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Draw a connected Stream Deck key grid (and Plus dials) on the overlay."""
    from .gradient import is_gradient

    style = item.get("style") or {}
    rect = widget_rect(item)
    painter.save()
    painter.setOpacity(_opacity(style))
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

    radius = float(style.get("corner_radius") or 0)
    fill_value = style.get("fill")
    fill = qcolor(fill_value, "#1a1d22")
    has_fill = is_gradient(fill_value) or fill.alpha() > 0
    border_w = _border_w(style, 0)
    show_bezel = bool(style.get("show_bezel", True))
    if show_bezel:
        if border_w > 0:
            painter.setPen(_pen(style.get("border"), border_w))
        else:
            painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(fill_brush(fill_value, "#1a1d22", rect=rect) if has_fill else QtCore.Qt.NoBrush)
        if radius > 0:
            painter.drawRoundedRect(rect, radius, radius)
        else:
            painter.drawRect(rect)
        if radius > 0:
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.setClipPath(clip)
    elif has_fill:
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(fill_brush(fill_value, "#1a1d22", rect=rect))
        painter.drawRect(rect)

    try:
        from gremlin.ui.streamdeck_device import (
            StreamDeckBridge,
            device_grid_size,
            friendly_streamdeck_name,
            is_streamdeck_designer_supported,
            make_slot_key,
            normalize_page,
            parse_streamdeck_device_type,
        )

        bridge = StreamDeckBridge()
        device_id = bridge.resolve_overlay_device_id(str(style.get("streamdeck_device_id") or ""))
        info = bridge.devices.get(device_id, {}) if device_id else {}
        dtype = parse_streamdeck_device_type(info.get("type")) if info else None
        if not device_id:
            _streamdeck_message_rect(
                painter,
                item,
                rect,
                "No Stream Deck connected" if not bridge.plugin_is_connected else "Select a Stream Deck",
            )
            painter.restore()
            return
        if device_id not in bridge.devices:
            label = friendly_streamdeck_name("", None, device_id)
            _streamdeck_message_rect(painter, item, rect, f"Waiting for {label}")
            painter.restore()
            return
        if not is_streamdeck_designer_supported(dtype):
            label = friendly_streamdeck_name(info.get("name"), info.get("type"), device_id)
            _streamdeck_message_rect(painter, item, rect, f"{label}\nnot supported")
            painter.restore()
            return

        grid = device_grid_size(dtype) or (5, 3)
        cols, rows = int(grid[0]), int(grid[1])
        plus = dtype in (7, 8)
        follow = bool(style.get("streamdeck_follow_page", True))
        page = bridge.get_active_page(device_id) if follow else normalize_page(style.get("streamdeck_page") or 1)
        slots = bridge.overlay_slots(device_id, page)
        held = bridge.held_slot_keys(device_id)

        pad = 10.0 if show_bezel else 2.0
        inner = rect.adjusted(pad, pad, -pad, -pad)
        lcd_frac = 0.42
        dial_frac = 0.62
        units = float(rows) + (lcd_frac + dial_frac if plus else 0.0)
        gap = max(2.0, min(inner.width() / max(1, cols * 10), inner.height() / max(1, units * 10)))
        extra_gaps = 2.0 if plus else 0.0
        key = min(
            (inner.width() - gap * max(0, cols - 1)) / max(1, cols),
            (inner.height() - gap * (max(0, rows - 1) + extra_gaps)) / max(0.5, units),
        )
        lcd_h = key * lcd_frac if plus else 0.0
        dial_h = key * dial_frac if plus else 0.0
        keys_h = rows * key + max(0, rows - 1) * gap
        grid_w = cols * key + max(0, cols - 1) * gap
        grid_h = keys_h + ((2.0 * gap + lcd_h + dial_h) if plus else 0.0)
        ox = inner.center().x() - grid_w / 2.0
        oy = inner.center().y() - grid_h / 2.0
        key_r = max(2.0, min(8.0, key * 0.12))
        empty_fill = qcolor("#111318")
        empty_pen = QtGui.QPen(qcolor("#2a3038"), 1)

        def _key_rect(row: int, col: int) -> QtCore.QRectF:
            return QtCore.QRectF(ox + col * (key + gap), oy + row * (key + gap), key, key)

        for row in range(rows):
            for col in range(cols):
                cell = _key_rect(row, col)
                slot_item = slots.get(("button", row, col))
                pressed = make_slot_key("button", row, col) in held
                pixmap = _streamdeck_slot_pixmap(slot_item, pressed, max(24, int(key)))
                if pixmap.isNull():
                    painter.setPen(empty_pen)
                    painter.setBrush(empty_fill)
                    painter.drawRoundedRect(cell, key_r, key_r)
                else:
                    path = QtGui.QPainterPath()
                    path.addRoundedRect(cell, key_r, key_r)
                    painter.save()
                    painter.setClipPath(path)
                    scaled = pixmap.scaled(cell.size().toSize(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
                    painter.drawPixmap(cell.toRect(), scaled)
                    painter.restore()
                    if pressed:
                        painter.setPen(QtCore.Qt.NoPen)
                        painter.setBrush(QtGui.QColor(255, 255, 255, 36))
                        painter.drawRoundedRect(cell, key_r, key_r)

        if plus:
            lcd_y = oy + keys_h + gap
            dial_y = lcd_y + lcd_h + gap
            lcd_w = key * 0.92
            for col in range(min(4, cols)):
                cx = ox + col * (key + gap) + key / 2.0
                lcd = QtCore.QRectF(cx - lcd_w / 2.0, lcd_y, lcd_w, lcd_h)
                slot_item = slots.get(("dial_press", 0, col))
                pixmap = _streamdeck_slot_pixmap(slot_item, False, max(24, int(key)), lcd=True)
                painter.setPen(empty_pen)
                painter.setBrush(empty_fill)
                painter.drawRoundedRect(lcd, 3, 3)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(lcd.size().toSize(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
                    painter.drawPixmap(lcd.toRect(), scaled)
                dial_r = min(key, dial_h) * 0.42
                center = QtCore.QPointF(cx, dial_y + dial_h / 2.0)
                pressed = make_slot_key("dial_press", 0, col) in held
                painter.setPen(empty_pen)
                painter.setBrush(qcolor("#2a2f36") if not pressed else qcolor("#4a5560"))
                painter.drawEllipse(center, dial_r, dial_r)
                painter.setBrush(qcolor("#111318"))
                painter.drawEllipse(center, dial_r * 0.38, dial_r * 0.38)
    except Exception:
        _streamdeck_message_rect(painter, item, rect, "Stream Deck unavailable")
        painter.restore()
        return

    _draw_label(painter, item, rect)
    painter.restore()


def paint_panel(painter: QtGui.QPainter, item: dict[str, Any], value):
    paint_shape(painter, item, value)


def paint_label(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .gradient import is_gradient

    style = item.get("style") or {}
    rect = widget_rect(item)
    painter.save()
    painter.setOpacity(_opacity(style))
    fill_value = style.get("fill")
    fill = qcolor(fill_value if not is_gradient(fill_value) else "#ffffffff", "#00000000")
    border_w = _border_w(style, 0)
    if is_gradient(fill_value) or fill.alpha() > 0 or border_w > 0 or fill.alpha() <= 0:
        set_fill_and_outline(painter, fill_value, style.get("border"), border_w, "#00000000", rect=rect)
        radius = float(style.get("corner_radius") or 0)
        if radius > 0:
            painter.drawRoundedRect(rect, radius, radius)
        else:
            painter.drawRect(rect)
    _draw_label(painter, item, rect, text_override=value if isinstance(value, str) else None)
    painter.restore()


def paint_button(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .images import is_svg_path, svg_renderer

    style = item.get("style") or {}
    rect = widget_rect(item)
    on = _pressed(value)
    fill = style.get("fill_on") if on else style.get("fill")
    border = style.get("border_on") if on else style.get("border")
    off_path = str(style.get("image_path") or "")
    on_path = str(style.get("image_path_on") or "")
    # Keep showing the off image when pressed unless a dedicated on image is set.
    image_path = on_path if (on and on_path) else off_path
    keep_aspect = bool(style.get("image_keep_aspect", True))
    has_image = bool(image_path) and (
        (is_svg_path(image_path) and svg_renderer(image_path) is not None)
        or (not is_svg_path(image_path) and not _widget_image_pixmap(image_path).isNull())
    )
    use_shape = button_uses_shape_path(item)
    painter.save()
    painter.setOpacity(_opacity(style))
    border_w = _border_w(style)
    if has_image and not use_shape:
        content = _draw_image_path_with_fill(painter, image_path, rect, keep_aspect, fill, "#3a1518")
        outline = _button_outline_path(item, content if content is not None else rect)
        if border_w > 0:
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(_pen(border, border_w))
            painter.drawPath(outline)
    else:
        outline = _button_outline_path(item, rect)
        set_fill_and_outline(painter, fill, border, border_w, "#3a1518", rect=rect)
        painter.drawPath(outline)
        if has_image:
            painter.save()
            painter.setClipPath(outline)
            _draw_image_path(painter, image_path, rect, keep_aspect)
            painter.restore()
            if border_w > 0:
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setPen(_pen(border, border_w))
                painter.drawPath(outline)
    _draw_label(painter, item, rect)
    painter.restore()


def _axis_label_spread(style: dict[str, Any]) -> float:
    try:
        value = style.get("axis_label_spread")
        if value is None:
            return 1.0
        return max(0.0, min(100.0, float(value))) / 100.0
    except (TypeError, ValueError):
        return 1.0


def _draw_axis_label_at(painter: QtGui.QPainter, text: str, x: float, y: float, font: QtGui.QFont, style: dict[str, Any], item: dict[str, Any] | None = None):
    if not text:
        return
    metrics = QtGui.QFontMetricsF(font)
    bounds = metrics.tightBoundingRect(text)
    rect = QtCore.QRectF(x - bounds.width() / 2.0, y - bounds.height() / 2.0, max(1.0, bounds.width()), max(1.0, bounds.height()))
    _draw_text_ex(
        painter,
        text,
        rect,
        font,
        style.get("axis_label_font_color") or style.get("font_color"),
        style,
        prefix="axis_label_",
    )


def _draw_axis_labels(painter: QtGui.QPainter, item: dict[str, Any], rect: QtCore.QRectF, ends: str | None = "all"):
    style = item.get("style") or {}
    if not style.get("show_axis_labels", True):
        return
    painter.save()
    font = _axis_label_font(style, item)
    metrics = QtGui.QFontMetrics(font)
    spread = _axis_label_spread(style)
    edge_pad = max(0.0, _border_w(style)) * 0.5 + 4.0
    cx = rect.center().x()
    cy = rect.center().y()
    ns = ends in (None, "all", "ns")
    ew = ends in (None, "all", "ew")

    def _reach(text: str, vertical: bool) -> float:
        bounds = metrics.tightBoundingRect(text or "X")
        half = (bounds.height() if vertical else bounds.width()) / 2.0
        span = (rect.height() if vertical else rect.width()) / 2.0
        return max(0.0, span - edge_pad - half)

    if ns:
        north = style.get("axis_label_n") or ""
        south = style.get("axis_label_s") or ""
        _draw_axis_label_at(painter, north, cx, cy - spread * _reach(north, True), font, style, item)
        _draw_axis_label_at(painter, south, cx, cy + spread * _reach(south, True), font, style, item)
    if ew:
        east = style.get("axis_label_e") or ""
        west = style.get("axis_label_w") or ""
        _draw_axis_label_at(painter, west, cx - spread * _reach(west, False), cy, font, style, item)
        _draw_axis_label_at(painter, east, cx + spread * _reach(east, False), cy, font, style, item)
    painter.restore()


def _indicator(painter: QtGui.QPainter, center: QtCore.QPointF, style: dict[str, Any], glow=None):
    size = float(style.get("indicator_size") or 12)
    color = qcolor(style.get("indicator"), "#ff5a3c")
    shape = (style.get("indicator_shape") or "circle").casefold()
    if glow is None:
        glow = bool(style.get("show_dot_shadow", True))
    painter.setPen(QtCore.Qt.NoPen)
    if glow:
        glow_color = QtGui.QColor(color)
        glow_color.setAlpha(80)
        painter.setBrush(glow_color)
        extra = size * 0.45
        if shape == "square":
            painter.drawRect(QtCore.QRectF(center.x() - size / 2 - extra / 2, center.y() - size / 2 - extra / 2, size + extra, size + extra))
        else:
            painter.drawEllipse(center, size * 0.95, size * 0.95)
    painter.setBrush(color)
    if shape == "square":
        painter.drawRect(QtCore.QRectF(center.x() - size / 2, center.y() - size / 2, size, size))
    else:
        painter.drawEllipse(center, size / 2, size / 2)


def _draw_dot_crosshair(painter: QtGui.QPainter, bounds: QtCore.QRectF, cx: float, cy: float, style: dict[str, Any], circular: bool = False):
    """Horizontal/vertical lines through the moving dot, in the dot color."""
    if not style.get("show_dot_crosshair"):
        return
    painter.setPen(_pen(style.get("indicator"), style.get("grid_width") or 1.0))
    if circular:
        origin = bounds.center()
        radius = min(bounds.width(), bounds.height()) / 2.0
        dx2 = radius * radius - (cy - origin.y()) ** 2
        dy2 = radius * radius - (cx - origin.x()) ** 2
        if dx2 > 0.5:
            dx = math.sqrt(dx2)
            painter.drawLine(QtCore.QPointF(origin.x() - dx, cy), QtCore.QPointF(origin.x() + dx, cy))
        if dy2 > 0.5:
            dy = math.sqrt(dy2)
            painter.drawLine(QtCore.QPointF(cx, origin.y() - dy), QtCore.QPointF(cx, origin.y() + dy))
        return
    painter.drawLine(QtCore.QPointF(bounds.left(), cy), QtCore.QPointF(bounds.right(), cy))
    painter.drawLine(QtCore.QPointF(cx, bounds.top()), QtCore.QPointF(cx, bounds.bottom()))


def _angle_step(style: dict[str, Any]) -> int:
    try:
        step = int(style.get("angle_step") or 0)
    except (TypeError, ValueError):
        return 0
    return step if step in (15, 30, 45) else 0


def _draw_angle_lines(painter: QtGui.QPainter, center: QtCore.QPointF, radius: float, style: dict[str, Any]):
    step = _angle_step(style)
    if not step:
        return
    painter.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
    for deg in range(0, 360, step):
        angle = math.radians(deg)
        painter.drawLine(center, QtCore.QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius))


def _caption(painter: QtGui.QPainter, item: dict[str, Any], rect: QtCore.QRectF, vertical: bool):
    if not (item.get("style") or {}).get("show_label", True) or not item.get("label"):
        return
    if vertical:
        _draw_label(painter, item, QtCore.QRectF(rect.x(), rect.bottom() + 2, rect.width(), 18))
    else:
        _draw_label(painter, item, QtCore.QRectF(rect.x(), rect.y() - 18, rect.width(), 16))


def paint_axis_bar(painter: QtGui.QPainter, item: dict[str, Any], value):
    """1D pad: track + moving dot, horizontal or vertical."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
    radius = _corner_radius(style, 6.0)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setOpacity(_opacity(style))
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
    if radius > 0:
        painter.drawPath(_rounded(rect, radius))
    else:
        painter.drawRect(rect)
    inner = _clip_rounded(painter, rect, style, radius)
    if style.get("show_grid", True):

        def _bar_grid(target: QtGui.QPainter):
            target.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
            if vertical:
                for i in range(1, 4):
                    t = i / 4.0
                    y = inner.top() + inner.height() * t
                    target.drawLine(QtCore.QPointF(inner.left(), y), QtCore.QPointF(inner.right(), y))
            else:
                for i in range(1, 4):
                    t = i / 4.0
                    x = inner.left() + inner.width() * t
                    target.drawLine(QtCore.QPointF(x, inner.top()), QtCore.QPointF(x, inner.bottom()))

        _with_grid_fade(painter, inner, style, False, _bar_grid)
    if style.get("show_center_line", True):
        painter.setPen(_pen(style.get("crosshair"), 1.2))
        if vertical:
            painter.drawLine(QtCore.QPointF(inner.center().x(), inner.top()), QtCore.QPointF(inner.center().x(), inner.bottom()))
        else:
            painter.drawLine(QtCore.QPointF(inner.left(), inner.center().y()), QtCore.QPointF(inner.right(), inner.center().y()))
    if vertical:
        t = (axis + 1.0) / 2.0
        cx = inner.center().x()
        cy = inner.bottom() - t * inner.height()
    else:
        t = (axis + 1.0) / 2.0
        cx = inner.left() + t * inner.width()
        cy = inner.center().y()
    _draw_dot_crosshair(painter, inner, cx, cy, style)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    painter.setClipping(False)
    _draw_axis_labels(painter, item, rect, ends="ns" if vertical else "ew")
    _caption(painter, item, rect, vertical)
    painter.restore()


def paint_axis_radio(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Stepped 1D selector (Touch OSC Radio)."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    steps = max(2, int(style.get("radio_steps") or 5))
    idx = int(round((axis + 1.0) / 2.0 * (steps - 1)))
    idx = max(0, min(steps - 1, idx))
    vertical = (style.get("orientation") or "horizontal").casefold() == "vertical"
    painter.save()
    painter.setOpacity(_opacity(style))
    gap = 3.0
    if vertical:
        cell_h = (rect.height() - gap * (steps - 1)) / steps
        for i in range(steps):
            cell = QtCore.QRectF(rect.x(), rect.y() + i * (cell_h + gap), rect.width(), cell_h)
            on = i == (steps - 1 - idx)
            painter.setPen(_pen(style.get("border_on") if on else style.get("border"), _border_w(style, 1.5)))
            painter.setBrush(fill_brush(style.get("fill_on") if on else style.get("fill"), "#121826", rect=cell))
            painter.drawRoundedRect(cell, 3, 3)
    else:
        cell_w = (rect.width() - gap * (steps - 1)) / steps
        for i in range(steps):
            cell = QtCore.QRectF(rect.x() + i * (cell_w + gap), rect.y(), cell_w, rect.height())
            on = i == idx
            painter.setPen(_pen(style.get("border_on") if on else style.get("border"), _border_w(style, 1.5)))
            painter.setBrush(fill_brush(style.get("fill_on") if on else style.get("fill"), "#121826", rect=cell))
            painter.drawRoundedRect(cell, 3, 3)
    _caption(painter, item, rect, vertical)
    painter.restore()


def paint_axis_fader(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Touch OSC fader: ladder track, value fill up to the thumb, sliding thumb."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
    steps = max(3, int(style.get("radio_steps") or 8))
    painter.save()
    painter.setOpacity(_opacity(style))
    radius = float(style.get("corner_radius") or 4)
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill") or style.get("track"), "#121826", rect=rect))
    painter.drawRoundedRect(rect, radius, radius)
    inner = rect.adjusted(3, 3, -3, -3)
    t = (axis + 1.0) / 2.0
    painter.setClipPath(_rounded(rect, radius))
    if vertical:
        thumb_h = max(8.0, float(style.get("indicator_size") or 0) or (inner.height() / steps))
        thumb_h = min(thumb_h, inner.height() * 0.45)
        travel = max(0.0, inner.height() - thumb_h)
        y = inner.bottom() - thumb_h - t * travel
        thumb = QtCore.QRectF(inner.x(), y, inner.width(), thumb_h)
        fill_h = max(0.0, inner.bottom() - thumb.bottom())
        filled = QtCore.QRectF(inner.x(), thumb.bottom(), inner.width(), fill_h)
    else:
        thumb_w = max(8.0, float(style.get("indicator_size") or 0) or (inner.width() / steps))
        thumb_w = min(thumb_w, inner.width() * 0.45)
        travel = max(0.0, inner.width() - thumb_w)
        x = inner.left() + t * travel
        thumb = QtCore.QRectF(x, inner.y(), thumb_w, inner.height())
        filled = QtCore.QRectF(inner.x(), inner.y(), max(0.0, thumb.left() - inner.left()), inner.height())
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(fill_brush(style.get("fill_bar"), "#ff6b35", rect=filled))
    painter.drawRect(filled)
    painter.setPen(_pen(style.get("grid"), style.get("grid_width") or 1.2))
    if vertical:
        for i in range(1, steps):
            gy = inner.top() + inner.height() * (i / steps)
            painter.drawLine(QtCore.QPointF(inner.left(), gy), QtCore.QPointF(inner.right(), gy))
    else:
        for i in range(1, steps):
            gx = inner.left() + inner.width() * (i / steps)
            painter.drawLine(QtCore.QPointF(gx, inner.top()), QtCore.QPointF(gx, inner.bottom()))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(fill_brush(style.get("fill_on") or style.get("indicator"), "#ff5a3c", rect=thumb))
    painter.drawRect(thumb)
    painter.setClipping(False)
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    _caption(painter, item, rect, vertical)
    painter.restore()


def paint_axis_radial(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Touch OSC radial: 270° arc with ticks and value fill."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    painter.save()
    painter.setOpacity(_opacity(style))
    side = min(rect.width(), rect.height())
    circle = QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    track = circle.adjusted(12, 12, -12, -12)
    width = max(8.0, float(style.get("needle_width") or 14))
    start = 225 * 16
    span = -270 * 16
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(_pen(style.get("track") or style.get("fill"), width))
    painter.drawArc(track, start, span)
    filled = int(-270 * ((axis + 1) / 2) * 16)
    painter.setPen(_pen(style.get("fill_bar") or style.get("indicator"), width))
    painter.drawArc(track, start, filled)
    border_w = _border_w(style)
    if border_w > 0:
        cx_track, cy_track = track.center().x(), track.center().y()
        track_r = min(track.width(), track.height()) / 2.0
        outer_r = track_r + width / 2.0
        inner_r_track = max(1.0, track_r - width / 2.0)
        painter.setPen(_pen(style.get("border"), border_w))
        painter.drawArc(QtCore.QRectF(cx_track - outer_r, cy_track - outer_r, outer_r * 2, outer_r * 2), start, span)
        painter.drawArc(QtCore.QRectF(cx_track - inner_r_track, cy_track - inner_r_track, inner_r_track * 2, inner_r_track * 2), start, span)
        for deg in (225.0, -45.0):
            rad = math.radians(deg)
            c, s = math.cos(rad), math.sin(rad)
            painter.drawLine(
                QtCore.QPointF(cx_track + c * inner_r_track, cy_track - s * inner_r_track),
                QtCore.QPointF(cx_track + c * outer_r, cy_track - s * outer_r),
            )
    ticks = max(2, int(style.get("radio_steps") or 11))
    painter.setPen(_pen(style.get("grid") or style.get("border"), 1.5))
    cx, cy = circle.center().x(), circle.center().y()
    outer = side / 2 - 2
    inner_r = side / 2 - width - 10
    for i in range(ticks):
        t = i / (ticks - 1)
        angle = math.radians(225 - 270 * t)
        painter.drawLine(
            QtCore.QPointF(cx + math.cos(angle) * inner_r, cy - math.sin(angle) * inner_r),
            QtCore.QPointF(cx + math.cos(angle) * outer, cy - math.sin(angle) * outer),
        )
    _draw_label(painter, item, rect)
    painter.restore()


def _donut_slice(cx: float, cy: float, inner_r: float, outer_r: float, start_deg: float, span_deg: float) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    outer = QtCore.QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
    inner = QtCore.QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
    path.arcMoveTo(outer, start_deg)
    path.arcTo(outer, start_deg, span_deg)
    path.arcTo(inner, start_deg + span_deg, -span_deg)
    path.closeSubpath()
    return path


def paint_axis_encoder(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Touch OSC encoder: full donut with ticks and one moving highlighted wedge."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    ticks = max(4, int(style.get("radio_steps") or 16))
    idx = int(round((axis + 1.0) / 2.0 * (ticks - 1)))
    idx = max(0, min(ticks - 1, idx))
    painter.save()
    painter.setOpacity(_opacity(style))
    side = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    outer_r = side / 2 - 2
    ring_w = float(style.get("needle_width") or 0)
    if ring_w >= 8:
        inner_r = max(outer_r * 0.22, outer_r - ring_w)
    else:
        inner_r = outer_r * 0.48
    span = 360.0 / ticks
    dim = qcolor(style.get("fill") or style.get("track"), "#121826")
    lit = qcolor(style.get("fill_on") or style.get("indicator") or style.get("fill_bar"), "#ff5a3c")
    painter.setPen(QtCore.Qt.NoPen)
    for i in range(ticks):
        painter.setBrush(lit if i == idx else dim)
        # Qt 0° = 3 o'clock, positive CCW; start at 12 o'clock and walk clockwise.
        start = 90.0 - i * span
        painter.drawPath(_donut_slice(cx, cy, inner_r, outer_r, start, -span))
    painter.setPen(_pen(style.get("grid") or style.get("border"), style.get("grid_width") or 1.2))
    inset = 1.0
    for i in range(ticks):
        rad = math.radians(90.0 - i * span)
        c, s = math.cos(rad), math.sin(rad)
        painter.drawLine(
            QtCore.QPointF(cx + c * (inner_r + inset), cy - s * (inner_r + inset)),
            QtCore.QPointF(cx + c * (outer_r - inset), cy - s * (outer_r - inset)),
        )
    border_w = _border_w(style)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(_pen(style.get("border"), border_w))
    painter.drawEllipse(QtCore.QPointF(cx, cy), outer_r, outer_r)
    painter.drawEllipse(QtCore.QPointF(cx, cy), inner_r, inner_r)
    _draw_label(painter, item, rect)
    painter.restore()


def _paddle_deg(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _paddle_axis_t(value, style: dict) -> float:
    """Map axis [-1, 1] to travel 0..1 (start→end)."""
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    return max(0.0, min(1.0, (axis + 1.0) / 2.0))


def _paddle_angle_at(start_deg: float, end_deg: float, t: float, direction: str) -> float:
    """Clockwise-positive degrees from tip-up (0°). Interpolate start→end along CW or CCW."""
    start = start_deg % 360.0
    end = end_deg % 360.0
    t = max(0.0, min(1.0, float(t)))
    if normalize_paddle_direction(direction) == "ccw":
        span = (start - end) % 360.0
        return (start - span * t) % 360.0
    span = (end - start) % 360.0
    return (start + span * t) % 360.0


def _paddle_progress_along_arc(angle_deg: float, start_deg: float, end_deg: float, direction: str) -> float:
    """How far along the configured arc [0,1] a clock angle sits (clamped)."""
    start = start_deg % 360.0
    end = end_deg % 360.0
    ang = angle_deg % 360.0
    if normalize_paddle_direction(direction) == "ccw":
        span = (start - end) % 360.0
        if span < 1e-6:
            return 0.0
        along = (start - ang) % 360.0
    else:
        span = (end - start) % 360.0
        if span < 1e-6:
            return 0.0
        along = (ang - start) % 360.0
    if along > span:
        # Snap to nearer endpoint
        return 0.0 if along - span > (360.0 - along) else 1.0
    return along / span


_PADDLE_ASSET = os.path.join(os.path.dirname(__file__), "assets", "paddle.png")
_PADDLE_PM_CACHE: dict[str, QtGui.QPixmap] = {}
_PADDLE_TINT_CACHE: dict[tuple, QtGui.QPixmap] = {}


def _paddle_body_path(length: float) -> QtGui.QPainterPath:
    """Fallback vector paddle if the bundled asset is missing."""
    L = max(28.0, float(length))
    hub_r = L * 0.26

    arm = QtGui.QPainterPath()
    arm.moveTo(QtCore.QPointF(-hub_r * 0.35, -hub_r * 0.78))
    arm.cubicTo(
        QtCore.QPointF(-L * 0.18, -L * 0.42),
        QtCore.QPointF(-L * 0.12, -L * 0.72),
        QtCore.QPointF(L * 0.02, -L * 0.93),
    )
    arm.cubicTo(
        QtCore.QPointF(L * 0.08, -L * 1.00),
        QtCore.QPointF(L * 0.18, -L * 0.99),
        QtCore.QPointF(L * 0.22, -L * 0.92),
    )
    tip = QtCore.QPointF(L * 0.22, -L * 0.92)
    c1 = QtCore.QPointF(L * 0.48, -L * 0.70)
    c2 = QtCore.QPointF(L * 0.46, -L * 0.22)
    end = QtCore.QPointF(hub_r * 0.72, -hub_r * 0.55)
    serrations = 10
    prev = tip
    for i in range(1, serrations + 1):
        u = i / serrations
        u1 = 1.0 - u
        pt = QtCore.QPointF(
            u1**3 * tip.x() + 3 * u1**2 * u * c1.x() + 3 * u1 * u**2 * c2.x() + u**3 * end.x(),
            u1**3 * tip.y() + 3 * u1**2 * u * c1.y() + 3 * u1 * u**2 * c2.y() + u**3 * end.y(),
        )
        if 0 < i < serrations and i % 2 == 1 and u < 0.85:
            dx = pt.x() - prev.x()
            dy = pt.y() - prev.y()
            mag = math.hypot(dx, dy) or 1.0
            nx, ny = dy / mag, -dx / mag
            depth = L * (0.034 if u < 0.55 else 0.022)
            pt = QtCore.QPointF(pt.x() + nx * depth, pt.y() + ny * depth)
        arm.lineTo(pt)
        prev = pt
    arm.lineTo(QtCore.QPointF(hub_r * 0.15, -hub_r * 0.85))
    arm.closeSubpath()
    hub = QtGui.QPainterPath()
    hub.addEllipse(QtCore.QPointF(0.0, 0.0), hub_r, hub_r)
    return hub.united(arm)


def _paddle_pixmap(style: dict) -> QtGui.QPixmap | None:
    raw = str(style.get("paddle_image") or "").strip()
    path = raw if raw and os.path.isfile(raw) else (_PADDLE_ASSET if os.path.isfile(_PADDLE_ASSET) else "")
    if not path:
        return None
    cached = _PADDLE_PM_CACHE.get(path)
    if cached is not None and not cached.isNull():
        return cached
    from .images import pixmap_from_image_path

    pm = pixmap_from_image_path(path, max_edge=1024)
    if pm.isNull():
        return None
    _PADDLE_PM_CACHE[path] = pm
    return pm


def _tint_paddle_pixmap(pm: QtGui.QPixmap, body: QtGui.QColor, size: int) -> QtGui.QPixmap:
    """Scale + colorize a white/alpha paddle silhouette (cached)."""
    key = (id(pm), body.rgba(), int(size))
    hit = _PADDLE_TINT_CACHE.get(key)
    if hit is not None and not hit.isNull():
        return hit
    scaled = pm.scaled(int(size), int(size), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    out = QtGui.QPixmap(scaled.size())
    out.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(out)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    painter.drawPixmap(0, 0, scaled)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), body)
    painter.end()
    if len(_PADDLE_TINT_CACHE) > 64:
        _PADDLE_TINT_CACHE.clear()
    _PADDLE_TINT_CACHE[key] = out
    return out


def paint_axis_paddle(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Single-axis paddle: rotates from start° to end° (CW or CCW); off at start, on when moved."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    t = _paddle_axis_t(value, style)
    start_deg = _paddle_deg(style.get("paddle_start_deg"), 0.0)
    end_deg = _paddle_deg(style.get("paddle_end_deg"), 70.0)
    direction = normalize_paddle_direction(style.get("paddle_direction"))
    angle = _paddle_angle_at(start_deg, end_deg, t, direction)
    is_on = t > 0.02

    painter.save()
    painter.setOpacity(_opacity(style))
    side = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    length = side * 0.44

    body = qcolor(style.get("fill_on") if is_on else style.get("fill"), "#6a6f78" if not is_on else "#c4c8d0")
    pin = qcolor(style.get("indicator"), "#2a2e36")
    border_w = max(0.0, _border_w(style))
    source = _paddle_pixmap(style)
    user_image = bool(str(style.get("paddle_image") or "").strip())

    painter.save()
    painter.translate(cx, cy)
    # 0° = tip up; positive degrees rotate clockwise (matches QPainter).
    painter.rotate(angle)

    if source is not None:
        target = max(16, int(side * 0.95))
        if user_image:
            pm = source.scaled(target, target, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        else:
            pm = _tint_paddle_pixmap(source, body, target)
        painter.drawPixmap(int(-pm.width() / 2), int(-pm.height() / 2), pm)
        if not user_image:
            pin_r = max(2.0, side * 0.028)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(pin)
            painter.drawEllipse(QtCore.QPointF(0, 0), pin_r, pin_r)
    else:
        path = _paddle_body_path(length)
        painter.setPen(_pen(style.get("border"), border_w if border_w > 0 else 1.4))
        painter.setBrush(body)
        painter.drawPath(path)
        hub_r = length * 0.26
        pin_r = max(2.0, hub_r * 0.28)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(_pen(style.get("border"), max(1.0, border_w * 0.85)))
        painter.drawEllipse(QtCore.QPointF(0, 0), pin_r * 1.65, pin_r * 1.65)
        painter.setBrush(pin)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(QtCore.QPointF(0, 0), pin_r, pin_r)
    painter.restore()

    _draw_label(painter, item, rect)
    painter.restore()


def paint_axis_dial(painter: QtGui.QPainter, item: dict[str, Any], value):
    paint_axis_radial(painter, item, value)


def paint_axis_stick_square(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    x, y = _deadzone(x, style), _deadzone(y, style)
    painter.save()
    painter.setOpacity(_opacity(style))
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
    try:
        radius = max(0.0, float(style.get("corner_radius")))
    except (TypeError, ValueError):
        radius = 6.0
    painter.drawRoundedRect(rect, radius, radius)
    inner = _inner_rect(rect, style)
    inset = max(0.5, _border_w(style) * 0.5)
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(inner, max(0.0, radius - inset), max(0.0, radius - inset))
    painter.setClipPath(clip)
    _draw_square_grid(painter, inner, style)
    _draw_crosshairs(painter, inner, style)
    cx = inner.center().x() + x * (inner.width() / 2)
    cy = inner.center().y() + y * (inner.height() / 2)
    _draw_dot_crosshair(painter, inner, cx, cy, style)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    painter.setClipping(False)
    _draw_axis_labels(painter, item, rect)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_axis_stick_circle(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    x, y = _deadzone(x, style), _deadzone(y, style)
    painter.save()
    painter.setOpacity(_opacity(style))
    side = min(rect.width(), rect.height())
    circle = QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
    painter.drawEllipse(circle)
    radius = min(circle.width(), circle.height()) / 2.0
    _draw_angle_lines(painter, circle.center(), radius, style)
    _draw_ring_grid(painter, circle, style, int(style.get("ring_count") or 2))
    _draw_crosshairs(painter, circle, style)
    cx = circle.center().x() + x * radius
    cy = circle.center().y() + y * radius
    _draw_dot_crosshair(painter, circle, cx, cy, style, circular=True)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    _draw_axis_labels(painter, item, rect)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_axis_crosshair(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    x, y = _deadzone(x, style), _deadzone(y, style)
    painter.save()
    painter.setOpacity(_opacity(style))
    side = min(rect.width(), rect.height())
    circle = QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    painter.setPen(_pen(style.get("border"), _border_w(style, 1.5)))
    painter.setBrush(fill_brush(style.get("fill"), "#0a1220", rect=circle))
    painter.drawEllipse(circle)
    radius = min(circle.width(), circle.height()) / 2.0
    _draw_angle_lines(painter, circle.center(), radius, style)
    _draw_ring_grid(painter, circle, style, int(style.get("ring_count") or 3))
    _draw_crosshairs(painter, circle, style)
    origin = circle.center()
    travel = max(8.0, radius - 2)
    cx = origin.x() + x * travel
    cy = origin.y() + y * travel
    _draw_dot_crosshair(painter, circle, cx, cy, style, circular=True)
    dist = math.hypot(cx - origin.x(), cy - origin.y())
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(_pen(style.get("indicator"), max(1.5, float(style.get("needle_width") or 2))))
    if dist > 2:
        painter.drawEllipse(origin, dist, dist)
    painter.drawLine(origin, QtCore.QPointF(cx, cy))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(qcolor(style.get("indicator"), "#ff5a3c"))
    painter.drawEllipse(origin, 2.5, 2.5)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    _draw_label(painter, item, rect)
    painter.restore()


def _hat_plus(painter: QtGui.QPainter, cx: float, cy: float, arm: float, thickness: float):
    painter.drawRoundedRect(QtCore.QRectF(cx - thickness / 2, cy - arm * 2, thickness, arm * 4), 4, 4)
    painter.drawRoundedRect(QtCore.QRectF(cx - arm * 2, cy - thickness / 2, arm * 4, thickness), 4, 4)


def _draw_vector_arrow(painter: QtGui.QPainter, origin: QtCore.QPointF, tip: QtCore.QPointF, style: dict[str, Any]):
    color = qcolor(style.get("indicator") or style.get("needle"), "#ff5a3c")
    try:
        width = max(1.5, float(style.get("needle_width") or 4.0))
    except (TypeError, ValueError):
        width = 4.0
    dx = tip.x() - origin.x()
    dy = tip.y() - origin.y()
    length = math.hypot(dx, dy)
    painter.setPen(_pen(color, width))
    painter.setBrush(color)
    if length < 3.0:
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(origin, width * 1.2, width * 1.2)
        return
    painter.drawLine(origin, tip)
    ux, uy = dx / length, dy / length
    head = max(8.0, width * 3.2)
    left = QtCore.QPointF(tip.x() - ux * head + -uy * head * 0.45, tip.y() - uy * head + ux * head * 0.45)
    right = QtCore.QPointF(tip.x() - ux * head + uy * head * 0.45, tip.y() - uy * head + -ux * head * 0.45)
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawPolygon(QtGui.QPolygonF([tip, left, right]))


def _draw_mouse_icon(painter: QtGui.QPainter, center: QtCore.QPointF, nx: float, ny: float, style: dict[str, Any]):
    """Top-down mouse silhouette; faces the movement direction."""
    try:
        size = max(14.0, float(style.get("indicator_size") or 28.0))
    except (TypeError, ValueError):
        size = 28.0
    color = qcolor(style.get("indicator"), "#ff5a3c")
    fill = QtGui.QColor(color)
    fill.setAlpha(max(180, fill.alpha()))
    body = QtGui.QPainterPath()
    hw = size * 0.38
    hh = size * 0.55
    body.addRoundedRect(QtCore.QRectF(-hw, -hh, hw * 2, hh * 2), hw * 0.9, hw * 0.9)
    seam = QtGui.QPainterPath()
    seam.moveTo(0, -hh * 0.15)
    seam.lineTo(0, hh * 0.35)
    wheel = QtGui.QPainterPath()
    wheel.addRoundedRect(QtCore.QRectF(-hw * 0.18, -hh * 0.12, hw * 0.36, hh * 0.28), 2.0, 2.0)
    angle = math.degrees(math.atan2(nx, -ny)) if (abs(nx) > 0.02 or abs(ny) > 0.02) else 0.0
    painter.save()
    painter.translate(center)
    painter.rotate(angle)
    if bool(style.get("show_dot_shadow", True)):
        glow = QtGui.QColor(color)
        glow.setAlpha(70)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QtCore.QPointF(0, hh * 0.15), hw * 1.15, hh * 0.55)
    painter.setPen(_pen(color.darker(125), 1.4))
    painter.setBrush(fill)
    painter.drawPath(body)
    painter.setPen(_pen(color.lighter(130), 1.2))
    painter.drawPath(seam)
    painter.setBrush(fill)
    painter.drawPath(wheel)
    painter.restore()


def paint_axis_mouse(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .mouse_track import normalize_mouse_mode

    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    painter.save()
    painter.setOpacity(_opacity(style))
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
    radius = _corner_radius(style)
    painter.drawRoundedRect(rect, radius, radius)
    inner = _inner_rect(rect, style)
    inset = max(0.5, _border_w(style) * 0.5)
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(inner, max(0.0, radius - inset), max(0.0, radius - inset))
    painter.setClipPath(clip)
    _draw_square_grid(painter, inner, style)
    _draw_crosshairs(painter, inner, style)
    cx = inner.center().x()
    cy = inner.center().y()
    origin = QtCore.QPointF(cx, cy)
    px = cx + x * (inner.width() / 2.0)
    py = cy + y * (inner.height() / 2.0)
    tip = QtCore.QPointF(px, py)
    if normalize_mouse_mode(style.get("mouse_mode")) == "standard":
        _draw_mouse_icon(painter, tip, x, y, style)
    else:
        _draw_vector_arrow(painter, origin, tip, style)
    painter.setClipping(False)
    _draw_label(painter, item, rect)
    painter.restore()


def _format_graph_tick(value: float, unit: str) -> str:
    if abs(value) >= 100:
        text = f"{value:.0f}"
    elif abs(value) >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:g}"
    return f"{text}{unit}" if unit else text


_BAR_UNSET = object()


def paint_axis_graph(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Scrolling time plot of one or more physical / vJoy axes."""
    from .graph_track import GraphOverlayTracker, graph_period_s, graph_series_label, graph_unit, graph_value_range

    style = item.get("style") or {}
    rect = widget_rect(item)
    radius = _corner_radius(style, 6.0)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    painter.setOpacity(_opacity(style))
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
    if radius > 0:
        painter.drawPath(_rounded(rect, radius))
    else:
        painter.drawRect(rect)
    inner = _clip_rounded(painter, rect, style, radius)
    vmin, vmax = graph_value_range(style)
    unit = graph_unit(style)
    period = graph_period_s(style)
    font = _font(style, item)
    metrics = QtGui.QFontMetrics(font)
    ticks = (vmax, (vmin + vmax) / 2.0, vmin)
    tick_w = max(metrics.horizontalAdvance(_format_graph_tick(v, unit)) for v in ticks) + 8
    legend_h = 0.0
    series = [s for s in (item.get("series") or []) if isinstance(s, dict)]
    if style.get("show_legend", True) and series:
        legend_h = metrics.height() + 8
    plot = inner.adjusted(tick_w, 6, -8, -(legend_h + 6) if legend_h else -6)
    if plot.width() < 8 or plot.height() < 8:
        _draw_label(painter, item, rect)
        painter.restore()
        return

    grid_color = style.get("grid") or "#2a3a55"
    if style.get("show_grid", True):
        painter.setPen(QtGui.QPen(qcolor(grid_color), float(style.get("grid_width") or 1), QtCore.Qt.DashLine))
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = plot.top() + plot.height() * t
            painter.drawLine(QtCore.QPointF(plot.left(), y), QtCore.QPointF(plot.right(), y))
        seconds = max(1, int(round(period)))
        for i in range(1, seconds + 1):
            x = plot.right() - (i / period) * plot.width()
            if x <= plot.left():
                continue
            painter.drawLine(QtCore.QPointF(x, plot.top()), QtCore.QPointF(x, plot.bottom()))

    painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
    painter.setFont(font)
    for t, val in ((0.0, vmax), (0.5, (vmin + vmax) / 2.0), (1.0, vmin)):
        y = plot.top() + plot.height() * t
        label_rect = QtCore.QRectF(inner.left() + 2, y - metrics.height() / 2.0, tick_w - 4, metrics.height())
        painter.drawText(label_rect, int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter), _format_graph_tick(val, unit))

    import time as _time

    now_mono = _time.monotonic()
    tracker = GraphOverlayTracker()
    widget_id = str(item.get("id") or "")
    span = max(0.001, vmax - vmin)
    for series_item in series:
        hist = tracker.history(widget_id, str(series_item.get("id") or ""))
        if len(hist) < 2:
            if len(hist) == 1:
                hist = [hist[0], hist[0]]
            else:
                continue
        path = QtGui.QPainterPath()
        started = False
        for ts, sample in hist:
            nx = plot.left() + ((ts - (now_mono - period)) / period) * plot.width()
            ny = plot.top() + ((vmax - sample) / span) * plot.height()
            nx = max(plot.left() - 2, min(plot.right() + 2, nx))
            ny = max(plot.top() - 2, min(plot.bottom() + 2, ny))
            if not started:
                path.moveTo(nx, ny)
                started = True
            else:
                path.lineTo(nx, ny)
        if not started:
            continue
        pen = _pen(series_item.get("color") or "#e41a1c", 2.0)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawPath(path)

    if legend_h:
        lx = plot.left()
        ly = plot.bottom() + 4
        for series_item in series:
            text = graph_series_label(series_item)
            width = metrics.horizontalAdvance(text) + 14
            if lx + width > inner.right():
                break
            painter.setPen(qcolor(series_item.get("color") or "#e41a1c"))
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(lx, ly, width, legend_h - 2), int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter), text)
            lx += width + 8

    painter.setClipping(False)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_axis_bars(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Grouped moving bars for one or more physical / vJoy axes."""
    from .bindings import binding_is_configured, read_axis
    from .graph_track import graph_series_label
    from .model import axis_display_percent, bars_value_range, series_is_centered

    style = item.get("style") or {}
    rect = widget_rect(item)
    radius = _corner_radius(style, 6.0)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    painter.setOpacity(_opacity(style))
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
    if radius > 0:
        painter.drawPath(_rounded(rect, radius))
    else:
        painter.drawRect(rect)
    inner = _clip_rounded(painter, rect, style, radius)
    vmin, vmax = bars_value_range(item)
    span = max(0.001, vmax - vmin)
    unit = str(style.get("unit") or "%")
    font = _font(style, item)
    metrics = QtGui.QFontMetrics(font)
    ticks = (vmax, (vmin + vmax) / 2.0, vmin)
    tick_w = max(metrics.horizontalAdvance(_format_graph_tick(v, unit)) for v in ticks) + 8
    series = [s for s in (item.get("series") or []) if isinstance(s, dict)]
    legend_h = (metrics.height() + 8) if (style.get("show_legend", True) and series) else 0.0
    vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
    if vertical:
        plot = inner.adjusted(tick_w, 6, -8, -(legend_h + 6) if legend_h else -6)
    else:
        plot = inner.adjusted(8, metrics.height() + 6, -8, -(legend_h + 6) if legend_h else -6)
    if plot.width() < 8 or plot.height() < 8 or not series:
        _draw_label(painter, item, rect)
        painter.restore()
        return

    grid_color = style.get("grid") or "#2a3a55"
    zero_t = (0.0 - vmin) / span
    if style.get("show_grid", True):
        painter.setPen(QtGui.QPen(qcolor(grid_color), float(style.get("grid_width") or 1), QtCore.Qt.DashLine))
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            if vertical:
                y = plot.bottom() - plot.height() * t
                painter.drawLine(QtCore.QPointF(plot.left(), y), QtCore.QPointF(plot.right(), y))
            else:
                x = plot.left() + plot.width() * t
                painter.drawLine(QtCore.QPointF(x, plot.top()), QtCore.QPointF(x, plot.bottom()))
    if 0.0 <= zero_t <= 1.0:
        painter.setPen(_pen(style.get("crosshair") or "#5a6a84", max(1.2, float(style.get("grid_width") or 1) + 0.5)))
        if vertical:
            y0 = plot.bottom() - plot.height() * zero_t
            painter.drawLine(QtCore.QPointF(plot.left(), y0), QtCore.QPointF(plot.right(), y0))
        else:
            x0 = plot.left() + plot.width() * zero_t
            painter.drawLine(QtCore.QPointF(x0, plot.top()), QtCore.QPointF(x0, plot.bottom()))

    painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
    painter.setFont(font)
    for t, val in ((1.0, vmax), (0.5, (vmin + vmax) / 2.0), (0.0, vmin)):
        label = _format_graph_tick(val, unit)
        if vertical:
            y = plot.bottom() - plot.height() * t
            label_rect = QtCore.QRectF(inner.left() + 2, y - metrics.height() / 2.0, tick_w - 4, metrics.height())
            painter.drawText(label_rect, int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter), label)
        else:
            x = plot.left() + plot.width() * t
            label_rect = QtCore.QRectF(x - tick_w / 2.0, inner.top() + 2, tick_w, metrics.height())
            painter.drawText(label_rect, int(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop), label)

    count = max(1, len(series))
    gap = 6.0
    percents = {}
    if isinstance(value, tuple):
        for entry in value:
            if isinstance(entry, tuple) and len(entry) >= 2:
                percents[str(entry[0])] = entry[1]

    def _bar_percent(series_item):
        series_id = str(series_item.get("id") or "")
        cached = percents.get(series_id, _BAR_UNSET)
        if cached is not _BAR_UNSET:
            return 0.0 if cached is None else float(cached)
        if binding_is_configured(series_item):
            raw = read_axis(series_item, series_item.get("input_id"), bool(series_item.get("invert")))
            return axis_display_percent(raw, series_is_centered(series_item))
        return 0.0

    painter.setPen(QtCore.Qt.NoPen)
    if vertical:
        bar_w = max(6.0, (plot.width() - gap * (count - 1)) / count)
        for index, series_item in enumerate(series):
            x = plot.left() + index * (bar_w + gap)
            percent = max(vmin, min(vmax, _bar_percent(series_item)))
            y_val = plot.bottom() - ((percent - vmin) / span) * plot.height()
            y_zero = plot.bottom() - ((0.0 - vmin) / span) * plot.height()
            y_zero = max(plot.top(), min(plot.bottom(), y_zero))
            top = min(y_val, y_zero)
            height = max(1.0, abs(y_val - y_zero))
            bar = QtCore.QRectF(x, top, bar_w, height)
            painter.setBrush(qcolor(series_item.get("color") or "#e41a1c"))
            painter.drawRoundedRect(bar, min(4.0, bar_w / 3.0), min(4.0, bar_w / 3.0))
    else:
        bar_h = max(6.0, (plot.height() - gap * (count - 1)) / count)
        for index, series_item in enumerate(series):
            y = plot.top() + index * (bar_h + gap)
            percent = max(vmin, min(vmax, _bar_percent(series_item)))
            x_val = plot.left() + ((percent - vmin) / span) * plot.width()
            x_zero = plot.left() + ((0.0 - vmin) / span) * plot.width()
            x_zero = max(plot.left(), min(plot.right(), x_zero))
            left = min(x_val, x_zero)
            width = max(1.0, abs(x_val - x_zero))
            bar = QtCore.QRectF(left, y, width, bar_h)
            painter.setBrush(qcolor(series_item.get("color") or "#e41a1c"))
            painter.drawRoundedRect(bar, min(4.0, bar_h / 3.0), min(4.0, bar_h / 3.0))

    if legend_h:
        lx = plot.left()
        ly = plot.bottom() + 4
        for series_item in series:
            text = graph_series_label(series_item)
            width = metrics.horizontalAdvance(text) + 14
            if lx + width > inner.right():
                break
            painter.setPen(qcolor(series_item.get("color") or "#e41a1c"))
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(lx, ly, width, legend_h - 2), int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter), text)
            lx += width + 8

    painter.setClipping(False)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_sys_stats(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .gradient import is_gradient
    from .sys_stats import sample_counter_widget

    style = item.get("style") or {}
    rect = widget_rect(item)
    radius = _corner_radius(style, 8.0)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setOpacity(_opacity(style))
    fill_value = style.get("fill")
    border_w = _border_w(style, 0)
    fill_alpha = 255 if is_gradient(fill_value) else qcolor(fill_value, "#121826").alpha()
    if fill_alpha > 0 or border_w > 0 or fill_alpha <= 0:
        set_fill_and_outline(painter, fill_value, style.get("border"), border_w, "#00000000", rect=rect)
        if radius > 0:
            painter.drawPath(_rounded(rect, radius))
        else:
            painter.drawRect(rect)
    inner = rect.adjusted(6, 4, -6, -4)
    rows = value if isinstance(value, tuple) else sample_counter_widget(item)
    if not rows:
        rows = sample_counter_widget(item)
    caption_on = bool(style.get("show_caption", True))
    vertical = str(style.get("orientation") or "vertical").casefold() != "horizontal"
    count = max(1, len(rows))
    if vertical:
        cell_h = inner.height() / count
        cell_w = inner.width()
    else:
        cell_h = inner.height()
        cell_w = inner.width() / count
    base_font = _font(style, item)
    for index, row in enumerate(rows):
        _sid, text, color, caption = row if len(row) >= 4 else ("", str(row), style.get("font_color") or "#f4efe4", "")
        if vertical:
            cell = QtCore.QRectF(inner.left(), inner.top() + index * cell_h, cell_w, cell_h)
        else:
            cell = QtCore.QRectF(inner.left() + index * cell_w, inner.top(), cell_w, cell_h)
        if caption_on and caption:
            cap_font = QtGui.QFont(base_font)
            cap_font.setPixelSize(max(8, int(round(_scaled_font_px(style, "font_size", item, 22) * 0.42))))
            cap_font.setBold(True)
            cap_h = QtGui.QFontMetrics(cap_font).height()
            _draw_text_ex(
                painter,
                caption,
                QtCore.QRectF(cell.left(), cell.top(), cell.width(), min(cap_h, cell.height() * 0.45)),
                cap_font,
                color,
                style,
                flags=int(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop),
            )
            value_rect = QtCore.QRectF(
                cell.left(),
                cell.top() + cap_h - 2,
                cell.width(),
                max(12.0, cell.height() - cap_h + 2),
            )
        else:
            value_rect = cell
        _draw_text_ex(painter, str(text or ""), value_rect, base_font, color, style)
    if style.get("show_label", False):
        _draw_label(painter, item, rect)
    painter.restore()


def _watch_point(cx: float, cy: float, length: float, clock_deg: float) -> QtCore.QPointF:
    math_rad = math.radians(90.0 - clock_deg)
    return QtCore.QPointF(cx + math.cos(math_rad) * length, cy - math.sin(math_rad) * length)


def _draw_watch_needle(painter: QtGui.QPainter, cx: float, cy: float, length: float, clock_deg: float, color, width: float, arrow: bool):
    width = max(0.5, float(width or 2.0))
    tip = _watch_point(cx, cy, length, clock_deg)
    tail = _watch_point(cx, cy, -length * 0.16, clock_deg)
    painter.setPen(_pen(color, width))
    painter.setBrush(qcolor(color))
    if arrow:
        math_rad = math.radians(90.0 - clock_deg)
        ux, uy = math.cos(math_rad), -math.sin(math_rad)
        px, py = -uy, ux
        arrow_len = max(7.0, width * 3.0)
        arrow_w = max(4.0, width * 1.7)
        base = QtCore.QPointF(tip.x() - ux * arrow_len, tip.y() - uy * arrow_len)
        painter.drawLine(tail, base)
        path = QtGui.QPainterPath()
        path.moveTo(tip)
        path.lineTo(QtCore.QPointF(base.x() + px * arrow_w, base.y() + py * arrow_w))
        path.lineTo(QtCore.QPointF(base.x() - px * arrow_w, base.y() - py * arrow_w))
        path.closeSubpath()
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawPath(path)
    else:
        painter.drawLine(tail, tip)


def paint_stopwatch(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .stopwatch_track import (
        StopwatchOverlayTracker,
        format_stopwatch,
        normalize_stopwatch_face,
        normalize_stopwatch_format,
    )

    style = item.get("style") or {}
    rect = widget_rect(item)
    tracker = StopwatchOverlayTracker()
    widget_id = str(item.get("id") or "")
    elapsed = tracker.elapsed(widget_id)
    running = tracker.running(widget_id)
    fmt = normalize_stopwatch_format(style.get("stopwatch_format"))
    face = normalize_stopwatch_face(style.get("stopwatch_face"))
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setOpacity(_opacity(style))
    if face == "analog":
        side = min(rect.width(), rect.height())
        dial = QtCore.QRectF(rect.center().x() - side / 2.0, rect.center().y() - side / 2.0, side, side)
        painter.setPen(_pen(style.get("border"), _border_w(style)))
        painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
        painter.drawEllipse(dial)
        cx, cy = dial.center().x(), dial.center().y()
        radius = side / 2.0 - max(4.0, _border_w(style) + 2.0)
        tick_color = qcolor(style.get("grid") or style.get("font_color") or "#f4efe4")
        for i in range(60):
            major = i % 5 == 0
            inner_r = radius * (0.78 if major else 0.88)
            painter.setPen(_pen(tick_color, 2.2 if major else 1.0))
            painter.drawLine(_watch_point(cx, cy, inner_r, i * 6.0), _watch_point(cx, cy, radius, i * 6.0))
        hours = elapsed / 3600.0
        minutes = (elapsed % 3600.0) / 60.0
        seconds = elapsed % 60.0
        _draw_watch_needle(
            painter,
            cx,
            cy,
            radius * 0.52,
            (hours % 12.0) * 30.0 + minutes * 0.5,
            style.get("needle_hour_color") or "#f4efe4",
            style.get("needle_hour_width") or 5.0,
            bool(style.get("needle_hour_arrow", True)),
        )
        _draw_watch_needle(
            painter,
            cx,
            cy,
            radius * 0.72,
            minutes * 6.0 + seconds * 0.1,
            style.get("needle_minute_color") or "#f4efe4",
            style.get("needle_minute_width") or 3.5,
            bool(style.get("needle_minute_arrow", True)),
        )
        _draw_watch_needle(
            painter,
            cx,
            cy,
            radius * 0.86,
            seconds * 6.0,
            style.get("needle_second_color") or "#ff5a3c",
            style.get("needle_second_width") or 2.0,
            bool(style.get("needle_second_arrow", False)),
        )
        cap = max(3.0, min(8.0, radius * 0.06))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(qcolor(style.get("needle_second_color") or "#ff5a3c"))
        painter.drawEllipse(QtCore.QPointF(cx, cy), cap, cap)
        painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
        digital_font = _font(style, item)
        digital_font.setPixelSize(max(8, int(round(_scaled_font_px(style, "font_size", item, 22) * 0.38))))
        painter.setFont(digital_font)
        _draw_text_ex(
            painter,
            format_stopwatch(elapsed, fmt),
            QtCore.QRectF(cx - radius * 0.55, cy + radius * 0.28, radius * 1.1, radius * 0.28),
            digital_font,
            style.get("font_color"),
            style,
        )
    else:
        radius = _corner_radius(style, 8.0)
        set_fill_and_outline(painter, style.get("fill"), style.get("border"), _border_w(style), rect=rect)
        if radius > 0:
            painter.drawPath(_rounded(rect, radius))
        else:
            painter.drawRect(rect)
        _draw_text_ex(
            painter,
            format_stopwatch(elapsed, fmt),
            rect,
            _font(style, item),
            style.get("needle_second_color") if running else style.get("font_color"),
            style,
        )
        if style.get("show_label", False):
            _draw_label(painter, item, rect)
    painter.restore()


def paint_hat(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    eight = int(style.get("hat_positions") or 4) >= 8
    painter.save()
    painter.setOpacity(_opacity(style))
    painter.setPen(_pen(style.get("border"), _border_w(style)))
    painter.setBrush(fill_brush(style.get("fill"), "#121826", rect=rect))
    radius = float(style.get("corner_radius") or 8)
    painter.drawRoundedRect(rect, radius, radius)
    cx, cy = rect.center().x(), rect.center().y()
    arm = min(rect.width(), rect.height()) * 0.18
    thickness = min(rect.width(), rect.height()) * (0.14 + 0.04 * float(style.get("grid_width") or 1))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(qcolor(style.get("crosshair"), "#5a6a84"))
    _hat_plus(painter, cx, cy, arm, thickness)
    if eight:
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(45)
        _hat_plus(painter, 0, 0, arm * 0.92, thickness * 0.85)
        painter.restore()
    nx, ny = 0, 0
    if abs(x) > 0.15 or abs(y) > 0.15:
        if eight:
            nx = 0 if abs(x) < 0.15 else (1 if x > 0 else -1)
            ny = 0 if abs(y) < 0.15 else (1 if y > 0 else -1)
        elif abs(x) >= abs(y):
            nx = 1 if x > 0 else -1
        else:
            ny = 1 if y > 0 else -1
    if nx or ny:
        length = math.hypot(nx, ny) or 1.0
        dist = arm * 1.45
        px = cx + (nx / length) * dist
        py = cy - (ny / length) * dist
        color = qcolor(style.get("fill_on") or style.get("indicator"), "#ff6b35")
    else:
        px, py = cx, cy
        color = qcolor(style.get("indicator"), "#ff5a3c")
    size = float(style.get("indicator_size") or 12) * 0.45
    painter.setBrush(color)
    painter.drawEllipse(QtCore.QPointF(px, py), size, size)
    _draw_axis_labels(painter, item, rect)
    painter.restore()


def _switch_fill_colors(style: dict[str, Any], active: bool):
    if active:
        return qcolor(style.get("fill_on"), "#ff6b35"), qcolor(style.get("border_on") or style.get("fill_on"), "#ffcc66")
    return qcolor(style.get("fill"), "#1a2230"), qcolor(style.get("border"), "#3a4a62")


def _switch_4way_geometry(item: dict[str, Any]) -> dict[str, float]:
    """Shared layout for arrows/arcs paint and hit-testing."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    side = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    margin = max(2.0, side * 0.04)
    outer_r = max(8.0, side / 2.0 - margin)
    # indicator_size is ~diameter preference for the center button
    center_r = float(style.get("indicator_size") or 28) * 0.5
    center_r = max(6.0, min(outer_r * 0.55, center_r))
    gap = max(2.5, side * 0.035)
    ring_inner = min(outer_r - gap * 1.5, center_r + gap)
    ring_inner = max(center_r + gap * 0.75, ring_inner)
    if ring_inner >= outer_r - 2.0:
        ring_inner = max(center_r + 1.5, outer_r * 0.55)
    return {
        "cx": cx,
        "cy": cy,
        "side": side,
        "outer_r": outer_r,
        "center_r": center_r,
        "gap": gap,
        "ring_inner": ring_inner,
    }


def _cardinal_arrow_path(cx: float, cy: float, slot: str, inner: float, outer: float, half_w: float) -> QtGui.QPainterPath:
    """Blocky cardinal arrow pointing outward; tip at `outer`, base near `inner`."""
    tip_len = max(6.0, (outer - inner) * 0.42)
    body_outer = outer - tip_len
    body_inner = inner
    if body_outer <= body_inner + 2.0:
        body_outer = (inner + outer) * 0.55
        tip_len = max(4.0, outer - body_outer)
    tip_half = half_w * 1.55
    path = QtGui.QPainterPath()
    if slot == "n":
        path.moveTo(cx, cy - outer)
        path.lineTo(cx + tip_half, cy - body_outer)
        path.lineTo(cx + half_w, cy - body_outer)
        path.lineTo(cx + half_w, cy - body_inner)
        path.lineTo(cx - half_w, cy - body_inner)
        path.lineTo(cx - half_w, cy - body_outer)
        path.lineTo(cx - tip_half, cy - body_outer)
    elif slot == "s":
        path.moveTo(cx, cy + outer)
        path.lineTo(cx + tip_half, cy + body_outer)
        path.lineTo(cx + half_w, cy + body_outer)
        path.lineTo(cx + half_w, cy + body_inner)
        path.lineTo(cx - half_w, cy + body_inner)
        path.lineTo(cx - half_w, cy + body_outer)
        path.lineTo(cx - tip_half, cy + body_outer)
    elif slot == "e":
        path.moveTo(cx + outer, cy)
        path.lineTo(cx + body_outer, cy + tip_half)
        path.lineTo(cx + body_outer, cy + half_w)
        path.lineTo(cx + body_inner, cy + half_w)
        path.lineTo(cx + body_inner, cy - half_w)
        path.lineTo(cx + body_outer, cy - half_w)
        path.lineTo(cx + body_outer, cy - tip_half)
    else:  # w
        path.moveTo(cx - outer, cy)
        path.lineTo(cx - body_outer, cy + tip_half)
        path.lineTo(cx - body_outer, cy + half_w)
        path.lineTo(cx - body_inner, cy + half_w)
        path.lineTo(cx - body_inner, cy - half_w)
        path.lineTo(cx - body_outer, cy - half_w)
        path.lineTo(cx - body_outer, cy - tip_half)
    path.closeSubpath()
    return path


def paint_switch_4way(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Physical 4-way hat that reports as five buttons (N/E/S/W/center)."""
    position = str(value or "")
    if position not in ("n", "e", "s", "w", "center"):
        position = ""
    _paint_switch_cardinal(painter, item, position, ("n", "e", "s", "w"), show_center=True)


def _paint_switch_cardinal(
    painter: QtGui.QPainter,
    item: dict[str, Any],
    position: str,
    slots: tuple[str, ...],
    show_center: bool = True,
):
    """Shared arrows/arcs paint for 4-way and 2-way (subset of cardinals)."""
    style = item.get("style") or {}
    appearance = normalize_switch_appearance(style.get("switch_appearance"))
    geo = _switch_4way_geometry(item)
    cx, cy = geo["cx"], geo["cy"]
    outer_r = geo["outer_r"]
    center_r = geo["center_r"]
    ring_inner = geo["ring_inner"]
    border_w = _border_w(style)
    painter.save()
    painter.setOpacity(_opacity(style))
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    if appearance == "arcs":
        # Wider slices when only two directions so the ring still reads clearly.
        span = 78.0 if len(slots) >= 4 else 140.0
        starts = {"e": -span / 2.0, "n": 90.0 - span / 2.0, "w": 180.0 - span / 2.0, "s": -90.0 - span / 2.0}
        for slot in slots:
            active = slot == position
            fill, border = _switch_fill_colors(style, active)
            path = _donut_slice(cx, cy, ring_inner, outer_r, starts[slot], span)
            painter.setPen(_pen(border, border_w * 0.85) if border_w > 0 else QtCore.Qt.NoPen)
            painter.setBrush(fill)
            painter.drawPath(path)
    else:
        half_w = max(5.0, (outer_r - ring_inner) * 0.38)
        for slot in slots:
            active = slot == position
            fill, border = _switch_fill_colors(style, active)
            path = _cardinal_arrow_path(cx, cy, slot, ring_inner, outer_r, half_w)
            painter.setPen(_pen(border, border_w * 0.9) if border_w > 0 else QtCore.Qt.NoPen)
            painter.setBrush(fill)
            painter.drawPath(path)

    if show_center:
        center_active = position == "center"
        if center_active:
            center_fill, center_border = _switch_fill_colors(style, True)
        else:
            center_fill = qcolor(style.get("indicator"), "#2a3548")
            center_border = qcolor(style.get("border"), "#3a4a62")
        painter.setPen(_pen(center_border, border_w) if border_w > 0 else QtCore.Qt.NoPen)
        painter.setBrush(center_fill)
        painter.drawEllipse(QtCore.QPointF(cx, cy), center_r, center_r)

    housing = QtCore.QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
    _draw_axis_labels(painter, item, housing)
    painter.restore()


def _switch_is_vertical(item: dict[str, Any]) -> bool:
    return ((item.get("style") or {}).get("orientation") or "vertical").casefold() != "horizontal"


def paint_switch_toggle(painter: QtGui.QPainter, item: dict[str, Any], value):
    """2-way latching or 3-way spring-center switch (slot highlight only, no bat handle)."""
    style = item.get("style") or {}
    widget_type = item.get("type")
    if widget_type == "switch_2way" and normalize_switch_appearance(style.get("switch_appearance")) != "bars":
        slots = switch_2way_cardinal_slots(item)
        raw = str(value or "")
        cardinal = "center" if raw == "center" else switch_2way_value_to_cardinal(item, raw)
        _paint_switch_cardinal(painter, item, cardinal, slots, show_center=True)
        return

    rect = widget_rect(item)
    position = str(value or "")
    vertical = _switch_is_vertical(item)
    painter.save()
    painter.setOpacity(_opacity(style))
    fill, border = _switch_fill_colors(style, False)
    painter.setPen(_pen(border, _border_w(style)) if _border_w(style) > 0 else QtCore.Qt.NoPen)
    painter.setBrush(fill)
    radius = _corner_radius(style, 10.0)
    painter.drawPath(_rounded(rect, radius))

    if vertical:
        inner = rect.adjusted(rect.width() * 0.18, rect.height() * 0.08, -rect.width() * 0.18, -rect.height() * 0.08)
    else:
        inner = rect.adjusted(rect.width() * 0.08, rect.height() * 0.18, -rect.width() * 0.08, -rect.height() * 0.18)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(qcolor(style.get("track") or "#0b1220"))
    painter.drawPath(_rounded(inner, max(4.0, radius * 0.45)))

    slots = ("a", "center", "b") if widget_type == "switch_2way" else ("up", "center", "down")
    count = len(slots)
    for index, slot in enumerate(slots):
        if vertical:
            h = inner.height() / count
            slot_rect = QtCore.QRectF(inner.left() + 3, inner.top() + h * index + 2, inner.width() - 6, h - 4)
        else:
            w = inner.width() / count
            slot_rect = QtCore.QRectF(inner.left() + w * index + 2, inner.top() + 3, w - 4, inner.height() - 6)
        active = slot == position
        slot_fill, slot_border = _switch_fill_colors(style, active)
        slot_fill.setAlpha(80 if active else 28)
        painter.setPen(_pen(slot_border, 1.1 if active else 0.6))
        painter.setBrush(slot_fill)
        painter.drawRoundedRect(slot_rect, 4, 4)

    painter.restore()

    painter.save()
    painter.setOpacity(_opacity(style))
    _draw_axis_labels(painter, item, rect, ends="ns" if vertical else "ew")
    painter.restore()


def paint_switch_2way(painter: QtGui.QPainter, item: dict[str, Any], value):
    paint_switch_toggle(painter, item, value)


def paint_switch_3way(painter: QtGui.QPainter, item: dict[str, Any], value):
    paint_switch_toggle(painter, item, value)


def _input_key_colors(style: dict[str, Any], pressed: bool):
    if pressed:
        fill = qcolor(style.get("fill_on"), "#4ec8ff")
        border = qcolor(style.get("border_on") or style.get("fill_on"), "#4ec8ff")
    else:
        fill = qcolor(style.get("fill"), "#1a1d22")
        border = qcolor(style.get("border"), "#e8eef8")
    return fill, border


def _map_unit_rect(bounds: QtCore.QRectF, x: float, y: float, w: float, h: float) -> QtCore.QRectF:
    return QtCore.QRectF(
        bounds.left() + bounds.width() * x,
        bounds.top() + bounds.height() * y,
        bounds.width() * w,
        bounds.height() * h,
    )


def _paint_input_keycap(painter: QtGui.QPainter, rect: QtCore.QRectF, style: dict[str, Any], label: str, pressed: bool, font: QtGui.QFont):
    radius = min(_corner_radius(style, 6.0), rect.width() * 0.28, rect.height() * 0.28)
    fill, border = _input_key_colors(style, pressed)
    set_fill_and_outline(painter, fill, border, max(1.0, _border_w(style)), rect=rect)
    if radius > 0:
        painter.drawPath(_rounded(rect, radius))
    else:
        painter.drawRect(rect)
    if not label:
        return
    _draw_text_ex(painter, label, rect, font, style.get("font_color"), style)


def _paint_mouse_region(painter: QtGui.QPainter, path: QtGui.QPainterPath, style: dict[str, Any], pressed: bool, selected: bool, label: str, font: QtGui.QFont):
    fill, border = _input_key_colors(style, pressed and selected)
    if not selected:
        fill.setAlpha(max(30, int(fill.alpha() * 0.35)))
        border.setAlpha(max(50, int(border.alpha() * 0.45)))
    painter.setPen(_pen(border, max(1.2, _border_w(style))))
    painter.setBrush(fill)
    painter.drawPath(path)
    if label and selected:
        painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
        painter.setFont(font)
        painter.drawText(path.boundingRect(), int(QtCore.Qt.AlignCenter), label)


def _mouse_region_path(rect: QtCore.QRectF, kind: str) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    if kind == "circle":
        path.addEllipse(rect)
        return path
    radius = min(6.0, rect.width() * 0.18, rect.height() * 0.18)
    path.addRoundedRect(rect, radius, radius)
    return path


def _paint_mouse_silhouette(painter: QtGui.QPainter, bounds: QtCore.QRectF, style: dict[str, Any], selected: set[str], pressed: set[str], font: QtGui.QFont):
    body = _map_unit_rect(bounds, 0.16, 0.04, 0.68, 0.92)
    body_path = QtGui.QPainterPath()
    body_path.addRoundedRect(body, body.width() * 0.42, body.height() * 0.22)
    fill, border = _input_key_colors(style, False)
    fill.setAlpha(max(40, int(fill.alpha() * 0.55)))
    painter.setPen(_pen(border, max(1.6, _border_w(style) + 0.4)))
    painter.setBrush(fill)
    painter.drawPath(body_path)

    regions = (
        ("mouse_1", _map_unit_rect(bounds, 0.20, 0.08, 0.28, 0.30), "L"),
        ("mouse_2", _map_unit_rect(bounds, 0.52, 0.08, 0.28, 0.30), "R"),
        ("mouse_3", _map_unit_rect(bounds, 0.44, 0.16, 0.12, 0.16), ""),
        ("wheel_up", _map_unit_rect(bounds, 0.45, 0.10, 0.10, 0.08), "▲"),
        ("wheel_down", _map_unit_rect(bounds, 0.45, 0.30, 0.10, 0.08), "▼"),
        ("mouse_5", _map_unit_rect(bounds, 0.08, 0.40, 0.12, 0.14), "M5"),
        ("mouse_4", _map_unit_rect(bounds, 0.08, 0.56, 0.12, 0.14), "M4"),
        ("wheel_left", _map_unit_rect(bounds, 0.40, 0.18, 0.06, 0.10), "◀"),
        ("wheel_right", _map_unit_rect(bounds, 0.54, 0.18, 0.06, 0.10), "▶"),
        ("mouse_d_1", _map_unit_rect(bounds, 0.22, 0.40, 0.18, 0.08), "2×"),
        ("mouse_d_2", _map_unit_rect(bounds, 0.60, 0.40, 0.18, 0.08), "2×"),
        ("mouse_d_3", _map_unit_rect(bounds, 0.42, 0.42, 0.16, 0.08), "2×"),
    )
    for lookup, rect, label in regions:
        if lookup not in selected and lookup not in ("mouse_1", "mouse_2", "mouse_3"):
            continue
        kind = "circle" if lookup in ("mouse_3", "wheel_up", "wheel_down") else "rect"
        _paint_mouse_region(
            painter,
            _mouse_region_path(rect, kind),
            style,
            lookup in pressed,
            lookup in selected,
            label if lookup in selected else "",
            font,
        )


def _paint_mouse_buttons(painter: QtGui.QPainter, bounds: QtCore.QRectF, style: dict[str, Any], selected: set[str], pressed: set[str], font: QtGui.QFont):
    regions = (
        ("mouse_1", _map_unit_rect(bounds, 0.02, 0.08, 0.22, 0.44), "M1", "rect"),
        ("wheel_up", _map_unit_rect(bounds, 0.28, 0.02, 0.26, 0.16), "ScU", "rect"),
        ("mouse_3", _map_unit_rect(bounds, 0.28, 0.20, 0.26, 0.18), "M3", "rect"),
        ("wheel_down", _map_unit_rect(bounds, 0.28, 0.40, 0.26, 0.14), "ScD", "rect"),
        ("mouse_2", _map_unit_rect(bounds, 0.58, 0.08, 0.22, 0.44), "M2", "rect"),
        ("mouse_5", _map_unit_rect(bounds, 0.06, 0.56, 0.18, 0.16), "M5", "rect"),
        ("mouse_4", _map_unit_rect(bounds, 0.12, 0.74, 0.16, 0.16), "M4", "rect"),
        ("wheel_left", _map_unit_rect(bounds, 0.54, 0.60, 0.18, 0.16), "ScL", "circle"),
        ("wheel_right", _map_unit_rect(bounds, 0.74, 0.60, 0.18, 0.16), "ScR", "circle"),
        ("mouse_d_1", _map_unit_rect(bounds, 0.02, 0.00, 0.22, 0.08), "DC1", "rect"),
        ("mouse_d_2", _map_unit_rect(bounds, 0.58, 0.00, 0.22, 0.08), "DC2", "rect"),
        ("mouse_d_3", _map_unit_rect(bounds, 0.28, 0.54, 0.26, 0.08), "DC3", "rect"),
    )

    for lookup, rect, label, kind in regions:
        if lookup not in selected:
            continue
        _paint_mouse_region(
            painter,
            _mouse_region_path(rect, kind),
            style,
            lookup in pressed,
            True,
            label,
            font,
        )


def paint_input_display(painter: QtGui.QPainter, item: dict[str, Any], value):
    from .input_display import (
        KeyboardMouseTracker,
        cell_display_label,
        display_label,
        key_lookup,
        keyboard_cell_for_key,
        normalize_mouse_graphic,
        overlay_keys_from_item,
        split_display_keys,
    )

    style = item.get("style") or {}
    rect = widget_rect(item)
    keys = overlay_keys_from_item(item)
    keyboard_keys, mouse_keys = split_display_keys(keys)
    show_keyboard = bool(style.get("show_keyboard", True)) and bool(keyboard_keys)
    show_mouse = bool(style.get("show_mouse", True)) and bool(mouse_keys)
    pressed = set(value) if isinstance(value, (tuple, list, set)) else set()
    if not pressed:
        pressed = set(KeyboardMouseTracker().sample(item) or ())
    selected_mouse = {key_lookup(key) for key in mouse_keys}

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setOpacity(_opacity(style))
    inner = rect.adjusted(6, 6, -6, -6)
    font = _font(style, item)
    if not show_keyboard and not show_mouse:
        painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
        painter.setFont(font)
        painter.drawText(inner, int(QtCore.Qt.AlignCenter), "Select keys in the inspector")
        if style.get("show_label", False):
            _draw_label(painter, item, rect)
        painter.restore()
        return

    mouse_width = 0.0
    if show_mouse:
        mouse_width = min(inner.height() * 0.95, inner.width() * (0.34 if show_keyboard else 0.9))
    key_area = QtCore.QRectF(inner)
    mouse_area = QtCore.QRectF()
    if show_mouse:
        mouse_area = QtCore.QRectF(inner.right() - mouse_width, inner.top(), mouse_width, inner.height())
        if show_keyboard:
            key_area = QtCore.QRectF(inner.left(), inner.top(), max(12.0, inner.width() - mouse_width - 8.0), inner.height())

    if show_keyboard:
        cells = []
        extra = []
        for key in keyboard_keys:
            cell = keyboard_cell_for_key(key)
            if cell is None:
                extra.append(key)
                continue
            cells.append((cell, key))
        if cells:
            min_c = min(cell.col for cell, _key in cells)
            min_r = min(cell.row for cell, _key in cells)
            max_c = max(cell.col + cell.colspan for cell, _key in cells)
            max_r = max(cell.row + cell.rowspan for cell, _key in cells)
            extra_rows = 1 if extra else 0
            grid_w = max(1, max_c - min_c)
            grid_h = max(1, max_r - min_r + extra_rows)
            gap = max(2.0, min(key_area.width(), key_area.height()) * 0.018)
            unit = min((key_area.width() - gap) / grid_w, (key_area.height() - gap) / grid_h)
            used_w = unit * grid_w
            used_h = unit * grid_h
            ox = key_area.left() + max(0.0, (key_area.width() - used_w) / 2.0)
            oy = key_area.top() + max(0.0, (key_area.height() - used_h) / 2.0)
            key_font = QtGui.QFont(font)
            key_font.setPixelSize(max(7, min(18, int(unit * 0.38))))
            for cell, key in cells:
                kx = ox + (cell.col - min_c) * unit + gap * 0.5
                ky = oy + (cell.row - min_r) * unit + gap * 0.5
                kw = cell.colspan * unit - gap
                kh = cell.rowspan * unit - gap
                cap = QtCore.QRectF(kx, ky, max(4.0, kw), max(4.0, kh))
                _paint_input_keycap(painter, cap, style, cell_display_label(cell, key), key_lookup(key) in pressed, key_font)
            if extra:
                extra_unit = min(unit, (used_w - gap) / max(1, len(extra)))
                ey = oy + (max_r - min_r) * unit + gap * 0.5
                for index, key in enumerate(extra):
                    cap = QtCore.QRectF(ox + index * extra_unit + gap * 0.5, ey, max(4.0, extra_unit - gap), max(4.0, unit - gap))
                    _paint_input_keycap(painter, cap, style, display_label(key), key_lookup(key) in pressed, key_font)
        elif extra:
            count = max(1, len(extra))
            cols = min(count, 8)
            rows = math.ceil(count / cols)
            unit_w = key_area.width() / cols
            unit_h = key_area.height() / rows
            key_font = QtGui.QFont(font)
            key_font.setPixelSize(max(7, min(16, int(min(unit_w, unit_h) * 0.35))))
            for index, key in enumerate(extra):
                col = index % cols
                row = index // cols
                cap = QtCore.QRectF(
                    key_area.left() + col * unit_w + 2,
                    key_area.top() + row * unit_h + 2,
                    max(4.0, unit_w - 4),
                    max(4.0, unit_h - 4),
                )
                _paint_input_keycap(painter, cap, style, display_label(key), key_lookup(key) in pressed, key_font)

    if show_mouse and mouse_area.width() > 8:
        mouse_font = QtGui.QFont(font)
        mouse_font.setPixelSize(max(7, min(14, int(mouse_area.width() * 0.09))))
        if normalize_mouse_graphic(style.get("mouse_graphic")) == "buttons":
            _paint_mouse_buttons(painter, mouse_area, style, selected_mouse, pressed, mouse_font)
        else:
            _paint_mouse_silhouette(painter, mouse_area, style, selected_mouse, pressed, mouse_font)

    if style.get("show_label", False):
        _draw_label(painter, item, rect)
    painter.restore()


_PAINTERS = {
    "axis_bar": paint_axis_bar,
    "axis_radio": paint_axis_radio,
    "axis_fader": paint_axis_fader,
    "axis_radial": paint_axis_radial,
    "axis_encoder": paint_axis_encoder,
    "axis_paddle": paint_axis_paddle,
    "axis_dial": paint_axis_radial,
    "axis_stick_square": paint_axis_stick_square,
    "axis_stick_circle": paint_axis_stick_circle,
    "axis_crosshair": paint_axis_crosshair,
    "axis_mouse": paint_axis_mouse,
    "axis_graph": paint_axis_graph,
    "axis_bars": paint_axis_bars,
    "button": paint_button,
    "hat": paint_hat,
    "switch_4way": paint_switch_4way,
    "switch_2way": paint_switch_2way,
    "switch_3way": paint_switch_3way,
    "label": paint_label,
    "sys_stats": paint_sys_stats,
    "stopwatch": paint_stopwatch,
    "input_display": paint_input_display,
    "shape": paint_shape,
    "panel": paint_shape,
    "image": paint_image,
    "application": paint_application,
    "remote_view": paint_remote_view,
    "streamdeck": paint_streamdeck,
}


def paint_widget(painter: QtGui.QPainter, item: dict[str, Any], value):
    if not item.get("visible", True):
        return
    from .blink import blink_paint_item

    item = blink_paint_item(item, value) or item
    fn = _PAINTERS.get(item.get("type"), paint_button)
    if abs(widget_rotation_deg(item)) < 0.001:
        paint_widget_drop_shadow(painter, item)
        fn(painter, item, value)
        return
    painter.save()
    apply_widget_rotation(painter, item)
    paint_widget_drop_shadow(painter, item)
    fn(painter, item, value)
    painter.restore()


def _math_angle_deg(px: float, py: float, cx: float, cy: float) -> float:
    """0° = east, counter-clockwise, Y up (matches paint_axis_radial / encoder)."""
    return math.degrees(math.atan2(-(py - cy), px - cx))


def _undo_invert_display(item: dict[str, Any], axis: float) -> float:
    if (item.get("style") or {}).get("invert_display"):
        return -axis
    return axis


def value_from_point(item: dict[str, Any], x: float, y: float):
    """Map a scene point onto the value the widget would display (before binding invert)."""
    widget_type = item.get("type")
    style = item.get("style") or {}
    local = scene_to_widget_local(item, x, y)
    x, y = local.x(), local.y()
    rect = widget_rect(item)
    if widget_type in ("label", "panel", "shape", "image", "application", "remote_view", "streamdeck", "button", "axis_mouse", "axis_graph", "axis_bars", "sys_stats", "stopwatch", "input_display"):
        return None
    if widget_type == "switch_4way":
        geo = _switch_4way_geometry(item)
        cx, cy = geo["cx"], geo["cy"]
        dx = x - cx
        dy = cy - y
        if math.hypot(dx, dy) <= geo["center_r"]:
            return "center"
        if abs(dx) >= abs(dy):
            return "e" if dx > 0 else "w"
        return "n" if dy > 0 else "s"
    if widget_type == "switch_2way":
        style_app = normalize_switch_appearance((style.get("switch_appearance") or "arrows"))
        if style_app != "bars":
            geo = _switch_4way_geometry(item)
            cx, cy = geo["cx"], geo["cy"]
            dx = x - cx
            dy = cy - y
            if math.hypot(dx, dy) <= geo["center_r"]:
                return "center"
            first, second = switch_2way_cardinal_slots(item)
            if first in ("n", "s"):
                cardinal = "n" if dy > 0 else "s"
            else:
                cardinal = "e" if dx > 0 else "w"
            return switch_2way_cardinal_to_value(item, cardinal) or None
        vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
        t = (y - rect.y()) / max(1.0, rect.height()) if vertical else (x - rect.x()) / max(1.0, rect.width())
        if t < 1.0 / 3.0:
            return "a"
        if t > 2.0 / 3.0:
            return "b"
        return "center"
    if widget_type == "switch_3way":
        vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
        t = (y - rect.y()) / max(1.0, rect.height()) if vertical else (x - rect.x()) / max(1.0, rect.width())
        if t < 1.0 / 3.0:
            return "up"
        if t > 2.0 / 3.0:
            return "down"
        return "center"
    if widget_type == "hat":
        cx, cy = rect.center().x(), rect.center().y()
        dx = x - cx
        dy = cy - y
        dead = min(rect.width(), rect.height()) * 0.18
        if math.hypot(dx, dy) < dead:
            return (0, 0)
        eight = int(style.get("hat_positions") or 4) >= 8
        if eight:
            nx = 0 if abs(dx) < dead * 0.55 else (1 if dx > 0 else -1)
            ny = 0 if abs(dy) < dead * 0.55 else (1 if dy > 0 else -1)
            if nx == 0 and ny == 0:
                if abs(dx) >= abs(dy):
                    nx = 1 if dx > 0 else -1
                else:
                    ny = 1 if dy > 0 else -1
            return (nx, ny)
        if abs(dx) >= abs(dy):
            return (1 if dx > 0 else -1, 0)
        return (0, 1 if dy > 0 else -1)
    if widget_type in ("axis_stick_square", "axis_stick_circle", "axis_crosshair"):
        if widget_type == "axis_stick_square":
            inner = _inner_rect(rect, style)
            hw = max(1.0, inner.width() / 2.0)
            hh = max(1.0, inner.height() / 2.0)
            ax = _clamp((x - inner.center().x()) / hw)
            ay = _clamp((y - inner.center().y()) / hh)
        else:
            side = min(rect.width(), rect.height())
            radius = max(1.0, side / 2.0)
            if widget_type == "axis_crosshair":
                radius = max(8.0, radius - 2)
            ax = (x - rect.center().x()) / radius
            ay = (y - rect.center().y()) / radius
            mag = math.hypot(ax, ay)
            if mag > 1.0:
                ax /= mag
                ay /= mag
        return (_clamp(ax), _clamp(ay))
    if widget_type == "axis_radio":
        steps = max(2, int(style.get("radio_steps") or 5))
        vertical = (style.get("orientation") or "horizontal").casefold() == "vertical"
        if vertical:
            t = (y - rect.y()) / max(1.0, rect.height())
            cell = max(0, min(steps - 1, int(t * steps)))
            idx = steps - 1 - cell
        else:
            t = (x - rect.x()) / max(1.0, rect.width())
            idx = max(0, min(steps - 1, int(t * steps)))
        axis = _clamp(-1.0 + 2.0 * idx / (steps - 1))
        return _undo_invert_display(item, axis)
    if widget_type == "axis_encoder":
        ticks = max(4, int(style.get("radio_steps") or 16))
        cx, cy = rect.center().x(), rect.center().y()
        ang = _math_angle_deg(x, y, cx, cy)
        span = 360.0 / ticks
        cw = (90.0 - ang) % 360.0
        idx = int(cw / span) % ticks
        axis = _clamp(-1.0 + 2.0 * idx / (ticks - 1))
        return _undo_invert_display(item, axis)
    if widget_type == "axis_paddle":
        cx, cy = rect.center().x(), rect.center().y()
        # Clock degrees: 0 = up, positive clockwise (matches paint).
        math_ang = _math_angle_deg(x, y, cx, cy)
        clock_ang = (90.0 - math_ang) % 360.0
        start_deg = _paddle_deg(style.get("paddle_start_deg"), 0.0)
        end_deg = _paddle_deg(style.get("paddle_end_deg"), 70.0)
        direction = normalize_paddle_direction(style.get("paddle_direction"))
        t = _paddle_progress_along_arc(clock_ang, start_deg, end_deg, direction)
        return _undo_invert_display(item, _clamp(t * 2.0 - 1.0))
    if widget_type in ("axis_radial", "axis_dial"):
        cx, cy = rect.center().x(), rect.center().y()
        ang = _math_angle_deg(x, y, cx, cy)
        rel = (225.0 - ang) % 360.0
        if rel <= 270.0:
            t = rel / 270.0
        else:
            t = 0.0 if rel >= 315.0 else 1.0
        return _undo_invert_display(item, _clamp(t * 2.0 - 1.0))
    inner = _inner_rect(rect, style)
    if widget_type == "axis_fader":
        inner = rect.adjusted(3, 3, -3, -3)
    vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
    if vertical:
        t = (inner.bottom() - y) / max(1.0, inner.height())
    else:
        t = (x - inner.left()) / max(1.0, inner.width())
    return _undo_invert_display(item, _clamp(t * 2.0 - 1.0))


def _fill_checkerboard(painter: QtGui.QPainter, rect: QtCore.QRect, tile: int = 8):
    light = QtGui.QColor("#3a4250")
    dark = QtGui.QColor("#2a3140")
    painter.fillRect(rect, dark)
    y = rect.y()
    while y < rect.y() + rect.height():
        x = rect.x()
        row = ((y - rect.y()) // tile) & 1
        while x < rect.x() + rect.width():
            col = ((x - rect.x()) // tile) & 1
            if (row + col) & 1:
                painter.fillRect(x, y, tile, tile, light)
            x += tile
        y += tile


def paint_background(
    painter: QtGui.QPainter,
    canvas: dict[str, Any],
    rect: QtCore.QRect,
    preview: bool = False,
    fallback_chroma: bool = True,
):
    if is_onscreen_mode(canvas):
        if preview:
            painter.fillRect(rect, QtGui.QColor("#1b2230"))
        return
    if not fallback_chroma:
        return
    color = chroma_fill_color(canvas)
    if preview and color.alpha() < 255:
        _fill_checkerboard(painter, rect)
        if color.alpha() > 0:
            painter.fillRect(rect, color)
        return
    painter.fillRect(rect, color)
