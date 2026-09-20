# -*- coding: utf-8; -*-
#
# Companion-class surface engine (Scope B): variables, expressions, step gates, image helpers.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
from typing import Any, Optional

from PySide6 import QtCore
from psygnal import Signal

import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator

syslog = logging.getLogger("system")

SURFACE_VARS_CONFIG_KEY = "streamdeck_surface_vars"
_EXPR_RE = re.compile(r"\$\((var|state):([^)]+)\)", re.IGNORECASE)

STEP_ALL = "all"
STEP_ADVANCE = "advance"
STEP_LATCH = "latch"

# Solid black 72×72 PNG — used when a live JG Ex slot has no designer icon so
# Elgato does not fall back to the default blue action artwork.
_EMPTY_KEY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAIAAADajyQQAAAAJklEQVR42u3BMQEAAADCoPVPbQ0PoA"
    "AAAAAAAAAAAAAAAAAAAL4MPQgAAXnT8VwAAAAASUVORK5CYII="
)
_EMPTY_KEY_DATA_URL = f"data:image/png;base64,{_EMPTY_KEY_PNG_B64}"
_empty_image_cache: dict[tuple[int, int], str] = {}


def empty_key_image(width: int = 144, height: int = 144) -> str:
    """Return a solid black PNG data-URL for an unassigned Stream Deck slot.

    Sending ``setImage`` with an empty string resets to the plugin's default
    (blue) icon — always push a real black image instead.
    """
    w = max(1, int(width or 144))
    h = max(1, int(height or 144))
    key = (w, h)
    cached = _empty_image_cache.get(key)
    if cached:
        return cached
    if w == 72 and h == 72:
        _empty_image_cache[key] = _EMPTY_KEY_DATA_URL
        return _EMPTY_KEY_DATA_URL
    try:
        from PySide6 import QtGui, QtCore

        pm = QtGui.QPixmap(w, h)
        pm.fill(QtGui.QColor(0, 0, 0))
        buf = QtCore.QByteArray()
        buffer = QtCore.QBuffer(buf)
        buffer.open(QtCore.QIODevice.WriteOnly)
        if pm.save(buffer, "PNG"):
            encoded = base64.b64encode(bytes(buf)).decode("ascii")
            url = f"data:image/png;base64,{encoded}"
            _empty_image_cache[key] = url
            return url
    except Exception:
        pass
    _empty_image_cache[key] = _EMPTY_KEY_DATA_URL
    return _EMPTY_KEY_DATA_URL


def file_to_data_url(path: str) -> str:
    """Convert an image file to a data-URL for Elgato setImage."""
    if not path:
        return ""
    if str(path).startswith("data:"):
        return optimize_data_url(str(path))
    if not os.path.isfile(path):
        return ""
    return optimize_image_file(path)


def optimize_image_file(path: str, max_px: int = 144) -> str:
    """Load a file and return a deck-sized PNG data-URL (Elgato-friendly)."""
    try:
        from PySide6 import QtCore, QtGui

        pm = QtGui.QPixmap(path)
        if pm.isNull():
            return ""
        return _pixmap_to_data_url(pm, max_px)
    except Exception as err:
        syslog.error(f"SURFACE: optimize image failed ({path}): {err}")
        # Fallback: raw file bytes (may be too large for Stream Deck).
        mime, _ = mimetypes.guess_type(path)
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        with open(path, "rb") as fh:
            raw = fh.read()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"


def optimize_data_url(data_url: str, max_px: int = 144) -> str:
    """Re-encode a data-URL as a deck-sized PNG."""
    if not data_url or not str(data_url).startswith("data:"):
        return data_url or ""
    try:
        from PySide6 import QtGui

        if "," not in data_url:
            return data_url
        b64 = data_url.split(",", 1)[1]
        raw = base64.b64decode(b64)
        pm = QtGui.QPixmap()
        if not pm.loadFromData(raw):
            return data_url
        return _pixmap_to_data_url(pm, max_px)
    except Exception:
        return data_url


def _pixmap_to_data_url(pm, max_px: int = 144) -> str:
    from PySide6 import QtCore, QtGui

    if pm.isNull():
        return ""
    if pm.width() > max_px or pm.height() > max_px:
        pm = pm.scaled(
            max_px,
            max_px,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
    buf = QtCore.QByteArray()
    buffer = QtCore.QBuffer(buf)
    buffer.open(QtCore.QIODevice.WriteOnly)
    if not pm.save(buffer, "PNG"):
        return ""
    encoded = base64.b64encode(bytes(buf)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def resolve_paint_image(item) -> str:
    """Prefer re-encoding from image_path; else optimize stored data-URL."""
    path = getattr(item, "image_path", None) or ""
    if path and os.path.isfile(path):
        return optimize_image_file(path)
    img = getattr(item, "image", None) or ""
    if not img:
        return ""
    if str(img).startswith("data:"):
        return optimize_data_url(str(img))
    return file_to_data_url(img)


def _align_point(avail_w: int, avail_h: int, obj_w: int, obj_h: int, h_align: str, v_align: str) -> tuple[int, int]:
    if h_align == "left":
        x = 0
    elif h_align == "right":
        x = max(0, avail_w - obj_w)
    else:
        x = max(0, (avail_w - obj_w) // 2)
    if v_align == "top":
        y = 0
    elif v_align == "bottom":
        y = max(0, avail_h - obj_h)
    else:
        y = max(0, (avail_h - obj_h) // 2)
    return x, y


def _is_coordinate_placeholder_title(title: str) -> bool:
    """True for Companion ``col/row`` or GEX ``row:col`` empty-key labels."""
    t = str(title or "").strip()
    return bool(t) and (
        re.fullmatch(r"\d+/\d+", t) is not None or re.fullmatch(r"\d+:\d+", t) is not None
    )


def text_lines_for_item(item, pressed: bool = False) -> list[str]:
    """Up to 3 display lines for a key (title + optional lines 2–3).

    When pressed=True and any pressed title line is set, use those; otherwise
    fall back to the released title lines.
    """
    if pressed:
        p1 = str(getattr(item, "title_pressed", "") or "").strip()
        p2 = str(getattr(item, "text_line2_pressed", "") or "").strip()
        p3 = str(getattr(item, "text_line3_pressed", "") or "").strip()
        if p1 or p2 or p3:
            if _is_coordinate_placeholder_title(p1):
                p1 = ""
            lines = [p1, p2, p3]
            while lines and not lines[-1]:
                lines.pop()
            return lines[:3]
    line1 = str(getattr(item, "title", None) or "").strip()
    if _is_coordinate_placeholder_title(line1):
        line1 = ""
    lines = [line1]
    lines.append(str(getattr(item, "text_line2", "") or "").strip())
    lines.append(str(getattr(item, "text_line3", "") or "").strip())
    while lines and not lines[-1]:
        lines.pop()
    return lines[:3]


def appearance_mode(item) -> str:
    """How the active look is chosen: ``press`` (hardware hold) or ``state`` (GEX state)."""
    mode = str(getattr(item, "appearance_mode", None) or "press").strip().casefold()
    return "state" if mode == "state" else "press"


def _state_id_str(value) -> str:
    return str(value).strip() if value is not None else ""


def _state_ids_equal(left, right) -> bool:
    a = _state_id_str(left)
    b = _state_id_str(right)
    if not a or not b:
        return False
    if a == b:
        return True
    na = a.replace("-", "").replace("{", "").replace("}", "").casefold()
    nb = b.replace("-", "").replace("{", "").replace("}", "").casefold()
    return bool(na) and na == nb


def find_gex_state(state_id=None, state_name=None):
    """Resolve a GEX state by unique ID, then by name."""
    try:
        import gremlin.ui.state_device as state_device

        sd = state_device.StateData()
    except Exception:
        return None
    sid = _state_id_str(state_id)
    if sid:
        state = sd.getStateById(sid)
        if state is not None:
            return state
    name = str(state_name or "").strip()
    if name:
        return sd.getState(name)
    return None


def sync_appearance_state_fields(item) -> bool:
    """Rewrite cached appearance state name from the unique ID. Returns True if changed."""
    if item is None:
        return False
    sid = _state_id_str(getattr(item, "appearance_state_id", None) or getattr(item, "_appearance_state_id", None))
    name = _state_id_str(getattr(item, "appearance_state", None) or getattr(item, "_appearance_state", None))
    if not sid and not name:
        return False
    state = find_gex_state(sid, name)
    if state is None:
        return False
    new_id = _state_id_str(state.id)
    new_name = state.key
    changed = False
    current_id = _state_id_str(getattr(item, "_appearance_state_id", None) or getattr(item, "appearance_state_id", None))
    current_name = _state_id_str(getattr(item, "_appearance_state", None) or getattr(item, "appearance_state", None))
    if current_id != new_id:
        if hasattr(item, "_appearance_state_id"):
            item._appearance_state_id = new_id
        elif hasattr(item, "appearance_state_id"):
            item.appearance_state_id = new_id
        changed = True
    if current_name != new_name:
        if hasattr(item, "_appearance_state"):
            item._appearance_state = new_name
        elif hasattr(item, "appearance_state"):
            item.appearance_state = new_name
        changed = True
    return changed


def rewrite_state_expression(text, old_name: str, new_name: str) -> str:
    """Rewrite $(state:old) tokens in a title/image expression."""
    raw = text if isinstance(text, str) else ""
    if not raw or not old_name or old_name == new_name:
        return raw
    old = str(old_name).strip()
    new = str(new_name).strip()
    if not old or not new:
        return raw

    def _repl(match):
        kind = match.group(1) or ""
        name = (match.group(2) or "").strip()
        if kind.casefold() == "state" and name.casefold() == old.casefold():
            return f"$({kind}:{new})"
        return match.group(0)

    return _EXPR_RE.sub(_repl, raw)


def sync_streamdeck_state_refs(items, old_name: str = "", new_name: str = "") -> bool:
    """Keep Stream Deck appearance / expression state links on unique IDs."""
    changed = False
    for item in items or []:
        if sync_appearance_state_fields(item):
            changed = True
        if old_name and new_name and old_name != new_name:
            for attr in (
                "title",
                "text_line2",
                "text_line3",
                "title_pressed",
                "text_line2_pressed",
                "text_line3_pressed",
                "title_expr",
                "image_expr",
            ):
                current = getattr(item, attr, None)
                rewritten = rewrite_state_expression(current, old_name, new_name)
                if rewritten != current:
                    setattr(item, attr, rewritten)
                    changed = True
    try:
        store = SurfaceVariableStore()
        for meta in (store._vars or {}).values():
            if not isinstance(meta, dict):
                continue
            alias = meta.get("state_alias") or ""
            alias_id = meta.get("state_alias_id") or ""
            if old_name and new_name and str(alias).casefold() == str(old_name).casefold():
                alias = new_name
            state = find_gex_state(alias_id, alias)
            if state is None:
                if old_name and new_name and alias != meta.get("state_alias"):
                    meta["state_alias"] = alias
                    changed = True
                continue
            sid = _state_id_str(state.id)
            if meta.get("state_alias") != state.key or _state_id_str(meta.get("state_alias_id")) != sid:
                meta["state_alias"] = state.key
                meta["state_alias_id"] = sid
                changed = True
    except Exception:
        pass
    return changed


def appearance_state_name(item) -> str:
    sync_appearance_state_fields(item)
    return str(getattr(item, "appearance_state", None) or "").strip()


def appearance_follows_state(item) -> bool:
    """True when the key's look is driven by a GEX state (even if none selected yet)."""
    return appearance_mode(item) == "state"


def appearance_state_is_on(item) -> bool:
    """True when the GEX state driving this key's look is currently ON."""
    sid = _state_id_str(getattr(item, "appearance_state_id", None) or getattr(item, "_appearance_state_id", None))
    name = appearance_state_name(item)
    state = find_gex_state(sid, name)
    if state is None:
        return False
    return bool(getattr(state, "value", False))


def has_pressed_appearance(item) -> bool:
    """True when the key defines a distinct pressed icon, title, and/or style."""
    if not item:
        return False
    if getattr(item, "image_pressed", "") or getattr(item, "image_pressed_path", ""):
        return True
    if (
        str(getattr(item, "title_pressed", "") or "").strip()
        or str(getattr(item, "text_line2_pressed", "") or "").strip()
        or str(getattr(item, "text_line3_pressed", "") or "").strip()
    ):
        return True
    # Distinct pressed style
    if (getattr(item, "bg_color_pressed", "") or "") != (getattr(item, "bg_color", "") or ""):
        return True
    if (getattr(item, "font_family_pressed", None) or "Segoe UI") != (getattr(item, "font_family", None) or "Segoe UI"):
        return True
    if int(getattr(item, "font_size_pressed", 18) or 18) != int(getattr(item, "font_size", 18) or 18):
        return True
    if (getattr(item, "font_color_pressed", "#ffffff") or "#ffffff").lower() != (
        getattr(item, "font_color", "#ffffff") or "#ffffff"
    ).lower():
        return True
    if (getattr(item, "text_h_align_pressed", "center") or "center") != (getattr(item, "text_h_align", "center") or "center"):
        return True
    if (getattr(item, "text_v_align_pressed", "bottom") or "bottom") != (getattr(item, "text_v_align", "bottom") or "bottom"):
        return True
    if bool(getattr(item, "shrink_to_fit_pressed", True)) != bool(getattr(item, "shrink_to_fit", True)):
        return True
    if (getattr(item, "icon_h_align_pressed", "center") or "center") != (getattr(item, "icon_h_align", "center") or "center"):
        return True
    if (getattr(item, "icon_v_align_pressed", "middle") or "middle") != (getattr(item, "icon_v_align", "middle") or "middle"):
        return True
    return False


def appearance_style(item, pressed: bool = False) -> dict:
    """Font / align / background for released or pressed state."""
    if pressed:
        return {
            "font_family": getattr(item, "font_family_pressed", None) or "Segoe UI",
            "font_size": int(getattr(item, "font_size_pressed", 18) or 18),
            "font_color": getattr(item, "font_color_pressed", None) or "#ffffff",
            "text_h": getattr(item, "text_h_align_pressed", None) or "center",
            "text_v": getattr(item, "text_v_align_pressed", None) or "bottom",
            "shrink": bool(getattr(item, "shrink_to_fit_pressed", True)),
            "icon_h": getattr(item, "icon_h_align_pressed", None) or "center",
            "icon_v": getattr(item, "icon_v_align_pressed", None) or "middle",
            "bg": getattr(item, "bg_color_pressed", "") or "",
        }
    return {
        "font_family": getattr(item, "font_family", None) or "Segoe UI",
        "font_size": int(getattr(item, "font_size", 18) or 18),
        "font_color": getattr(item, "font_color", None) or "#ffffff",
        "text_h": getattr(item, "text_h_align", None) or "center",
        "text_v": getattr(item, "text_v_align", None) or "bottom",
        "shrink": bool(getattr(item, "shrink_to_fit", True)),
        "icon_h": getattr(item, "icon_h_align", None) or "center",
        "icon_v": getattr(item, "icon_v_align", None) or "middle",
        "bg": getattr(item, "bg_color", "") or "",
    }


def item_needs_composite(item, pressed: bool = False) -> bool:
    """True when Companion-style paint should bake bg/icon/text into one image."""
    if not item:
        return False
    style = appearance_style(item, pressed=pressed)
    if style.get("bg"):
        return True
    if pressed:
        if getattr(item, "image_pressed_path", "") or getattr(item, "image_pressed", ""):
            return True
        if getattr(item, "image_path", "") or getattr(item, "image", "") or getattr(item, "image_expr", ""):
            if has_pressed_appearance(item) or text_lines_for_item(item, pressed=True):
                return True
    else:
        if getattr(item, "image_path", "") or getattr(item, "image", ""):
            return True
        if getattr(item, "image_expr", ""):
            return True
    if text_lines_for_item(item, pressed=pressed):
        return True
    if style.get("font_size", 18) != 18:
        return True
    if (style.get("font_color") or "").lower() not in ("#ffffff", "#fff", "white", ""):
        return True
    if style.get("text_h") != "center":
        return True
    if style.get("text_v") != "bottom":
        return True
    if style.get("icon_h") != "center":
        return True
    if style.get("icon_v") != "middle":
        return True
    return False


def compose_key_pixmap(item, size: int = 144, pressed: bool = False, width: int | None = None, height: int | None = None):
    """Render Companion-style key (background + icon + up to 3 text lines).

    Pass width/height for non-square canvases (Stream Deck + dial LCD is 200×100).
    """
    from PySide6 import QtCore, QtGui

    w = max(72, int(width if width is not None else size))
    h = max(36, int(height if height is not None else size))
    style = appearance_style(item, pressed=pressed)
    pm = QtGui.QPixmap(w, h)
    bg = style.get("bg") or "#1a1a1a"
    color = QtGui.QColor(bg)
    if not color.isValid():
        color = QtGui.QColor("#1a1a1a")
    pm.fill(color)

    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

    # Scale typography/margins against the shorter side so dial LCDs stay readable.
    # Light inset (smaller than the old size//16 ≈ 9px on a 144 key).
    ref = min(w, h)
    margin = max(2, ref // 32)
    lines = text_lines_for_item(item, pressed=pressed)
    font_family = style.get("font_family") or "Segoe UI"
    font_size = int(style.get("font_size") or 18)
    font_color = QtGui.QColor(style.get("font_color") or "#ffffff")
    if not font_color.isValid():
        font_color = QtGui.QColor("#ffffff")
    text_h = style.get("text_h") or "center"
    text_v = style.get("text_v") or "bottom"
    shrink = bool(style.get("shrink", True))
    icon_h = style.get("icon_h") or "center"
    icon_v = style.get("icon_v") or "middle"

    # Reserve text band when text is bottom/top so icon does not collide.
    text_band = 0
    if lines:
        text_band = max(18, int(h * 0.28)) if text_v in ("top", "bottom") else int(h * 0.36)

    icon_rect = QtCore.QRect(margin, margin, w - 2 * margin, h - 2 * margin)
    if lines and text_v == "bottom":
        icon_rect.setBottom(h - margin - text_band)
    elif lines and text_v == "top":
        icon_rect.setTop(margin + text_band)

    # Icon layer (pressed icon if set, else released)
    icon_pm = QtGui.QPixmap()
    if pressed and (getattr(item, "image_pressed_path", "") or getattr(item, "image_pressed", "")):
        path = getattr(item, "image_pressed_path", "") or ""
        raw = getattr(item, "image_pressed", "") or ""
    else:
        path = getattr(item, "image_path", "") or ""
        raw = getattr(item, "image", "") or ""
    if path and os.path.isfile(path):
        icon_pm = QtGui.QPixmap(path)
    elif raw.startswith("data:") and "," in raw:
        try:
            data = base64.b64decode(raw.split(",", 1)[1])
            icon_pm.loadFromData(data)
        except Exception:
            icon_pm = QtGui.QPixmap()
    elif (not pressed) and (getattr(item, "image_expr", "") or ""):
        try:
            resolved = evaluate_expression(item.image_expr)
            if resolved.startswith("data:"):
                data = base64.b64decode(resolved.split(",", 1)[1])
                icon_pm.loadFromData(data)
            elif resolved and os.path.isfile(resolved):
                icon_pm = QtGui.QPixmap(resolved)
        except Exception:
            pass

    if not icon_pm.isNull() and icon_rect.width() > 0 and icon_rect.height() > 0:
        # Cover the key edge-to-edge (may crop non-square sources).
        scaled = icon_pm.scaled(
            icon_rect.size(),
            QtCore.Qt.KeepAspectRatioByExpanding,
            QtCore.Qt.SmoothTransformation,
        )
        if scaled.width() > icon_rect.width() or scaled.height() > icon_rect.height():
            x0 = max(0, (scaled.width() - icon_rect.width()) // 2)
            y0 = max(0, (scaled.height() - icon_rect.height()) // 2)
            scaled = scaled.copy(x0, y0, icon_rect.width(), icon_rect.height())
            painter.drawPixmap(icon_rect.x(), icon_rect.y(), scaled)
        else:
            ox, oy = _align_point(
                icon_rect.width(),
                icon_rect.height(),
                scaled.width(),
                scaled.height(),
                icon_h,
                icon_v,
            )
            painter.drawPixmap(icon_rect.x() + ox, icon_rect.y() + oy, scaled)

    # Text layer (up to 3 lines)
    if lines:
        font = QtGui.QFont(font_family)
        font.setBold(True)
        point = font_size
        # Approximate: treat font_size as px relative to 144 canvas short side
        font.setPixelSize(max(8, int(point * ref / 144)))

        def _layout(fnt):
            metrics = QtGui.QFontMetrics(fnt)
            block_h = 0
            widths = []
            for line in lines:
                widths.append(metrics.horizontalAdvance(line) if line else 0)
                block_h += metrics.height()
            return metrics, max(widths) if widths else 0, block_h

        if shrink:
            while point >= 8:
                font.setPixelSize(max(8, int(point * ref / 144)))
                _, tw, th = _layout(font)
                if tw <= w - 2 * margin and th <= h - 2 * margin:
                    break
                point -= 1

        painter.setFont(font)
        painter.setPen(font_color)
        metrics, tw, th = _layout(font)
        tx, ty = _align_point(w - 2 * margin, h - 2 * margin, tw, th, text_h, text_v)
        y = margin + ty
        for line in lines:
            lw = metrics.horizontalAdvance(line)
            if text_h == "left":
                x = margin
            elif text_h == "right":
                x = w - margin - lw
            else:
                x = (w - lw) // 2
            painter.drawText(x, y + metrics.ascent(), line)
            y += metrics.height()

    painter.end()
    return pm


def compose_key_image(item, size: int = 144, pressed: bool = False, width: int | None = None, height: int | None = None) -> str:
    """Companion-style composite key image as a PNG data-URL."""
    if not item_needs_composite(item, pressed=pressed):
        if pressed:
            return resolve_paint_image_pressed(item)
        return resolve_paint_image(item)
    try:
        w = width
        h = height
        # Dial LCD windows are 200×100 on Stream Deck +.
        if w is None and h is None and (getattr(item, "kind", "") or "") in ("dial", "dial_press"):
            w, h = 200, 100
        pm = compose_key_pixmap(item, size=size, pressed=pressed, width=w, height=h)
        max_px = max(w or size, h or size)
        return _pixmap_to_data_url(pm, max_px=max_px)
    except Exception as err:
        syslog.error(f"SURFACE: compose key image failed: {err}")
        if pressed:
            return resolve_paint_image_pressed(item)
        return resolve_paint_image(item)


def compose_pressed_image(item, size: int = 144) -> str:
    """Image to flash while the key is held (pressed icon + pressed title)."""
    return compose_key_image(item, size=size, pressed=True)


def resolve_paint_image_pressed(item) -> str:
    """Raw pressed icon data-URL (no composite), falling back to released."""
    raw = getattr(item, "image_pressed", "") or ""
    if raw.startswith("data:"):
        return raw
    path = getattr(item, "image_pressed_path", "") or ""
    if path and os.path.isfile(path):
        return file_to_data_url(path) or ""
    return resolve_paint_image(item)


def resolved_pressed_title(item):
    """Title string for pressed flash, or None when text is baked into the image."""
    if item_needs_composite(item, pressed=True):
        return ""  # clear HW title; text is in the composite
    lines = text_lines_for_item(item, pressed=True)
    if lines:
        return "\n".join(lines)
    return None


@SingletonDecorator
class SurfaceVariableStore(QtCore.QObject):
    """Per-profile Companion-style surface variables."""

    changed = Signal(str, object)  # name, value
    variables_changed = Signal()

    def __init__(self):
        super().__init__()
        self._vars: dict[str, dict] = {}  # name -> {type, value, default, description, state_alias}
        self._hooked = False

    def ensure_hooks(self):
        if self._hooked:
            return
        self._hooked = True
        try:
            el = gremlin.event_handler.EventListener()
            el.profile_loaded.connect(self.load_from_profile)
            el.profile_start.connect(self._on_profile_start)
            el.profile_stop.connect(self._on_profile_stop)
        except Exception:
            pass

    def load_from_profile(self, *_args):
        profile = gremlin.shared_state.current_profile
        data = {}
        try:
            if profile is not None and hasattr(profile, "_readConfig"):
                cfg = profile._readConfig() or {}
                data = cfg.get(SURFACE_VARS_CONFIG_KEY) or {}
        except Exception:
            data = {}
        self._vars = {}
        if isinstance(data, dict):
            for name, meta in data.items():
                if not name:
                    continue
                if not isinstance(meta, dict):
                    meta = {"value": meta, "type": "string", "default": meta}
                self._vars[str(name)] = {
                    "type": meta.get("type") or "string",
                    "value": meta.get("value", meta.get("default", "")),
                    "default": meta.get("default", meta.get("value", "")),
                    "description": meta.get("description") or "",
                    "state_alias": meta.get("state_alias") or "",
                    "state_alias_id": meta.get("state_alias_id") or "",
                }
        self.variables_changed.emit()

    def persist_to_profile(self):
        profile = gremlin.shared_state.current_profile
        if profile is None:
            return
        payload = {k: dict(v) for k, v in self._vars.items()}
        try:
            if hasattr(profile, "_setConfig"):
                profile._setConfig(SURFACE_VARS_CONFIG_KEY, payload)
        except Exception as err:
            syslog.error(f"SURFACE: persist variables failed: {err}")

    def _on_profile_start(self):
        self.load_from_profile()
        self._sync_aliases_from_states()

    def _on_profile_stop(self):
        # Reset to defaults
        for name, meta in self._vars.items():
            meta["value"] = meta.get("default", "")
        self.variables_changed.emit()

    def list_names(self) -> list[str]:
        return sorted(self._vars.keys(), key=lambda s: s.casefold())

    def get_meta(self, name: str) -> dict:
        return dict(self._vars.get(name) or {})

    def get(self, name: str, default: Any = None) -> Any:
        meta = self._vars.get(name)
        if not meta:
            return default
        return meta.get("value", default)

    def set(self, name: str, value: Any, persist: bool = True, emit: bool = True):
        name = (name or "").strip()
        if not name:
            return
        if name not in self._vars:
            self._vars[name] = {
                "type": "string",
                "value": value,
                "default": value,
                "description": "",
                "state_alias": "",
            }
        else:
            self._vars[name]["value"] = value
        if persist:
            self.persist_to_profile()
        if emit:
            self.changed.emit(name, value)
            self.variables_changed.emit()
        self._push_alias_to_state(name)

    def toggle(self, name: str):
        cur = self.get(name, False)
        if isinstance(cur, str):
            cur_b = cur.strip().lower() in ("1", "true", "yes", "on")
        else:
            cur_b = bool(cur)
        self.set(name, not cur_b)

    def add(self, name: str, var_type: str = "string", default: Any = "", description: str = "", state_alias: str = ""):
        name = (name or "").strip()
        if not name:
            return False
        if name in self._vars:
            return False
        self._vars[name] = {
            "type": var_type or "string",
            "value": default,
            "default": default,
            "description": description or "",
            "state_alias": state_alias or "",
            "state_alias_id": "",
        }
        self.persist_to_profile()
        self.variables_changed.emit()
        return True

    def remove(self, name: str):
        if name in self._vars:
            del self._vars[name]
            self.persist_to_profile()
            self.variables_changed.emit()

    def update_meta(self, name: str, **kwargs):
        if name not in self._vars:
            return
        meta = self._vars[name]
        for k, v in kwargs.items():
            if k in ("type", "default", "description", "state_alias", "state_alias_id", "value"):
                meta[k] = v
        self.persist_to_profile()
        self.variables_changed.emit()

    def _sync_aliases_from_states(self):
        for name, meta in self._vars.items():
            alias = (meta.get("state_alias") or "").strip()
            alias_id = (meta.get("state_alias_id") or "").strip()
            if not alias and not alias_id:
                continue
            st = find_gex_state(alias_id, alias)
            if st is not None:
                meta["state_alias"] = st.key
                meta["state_alias_id"] = _state_id_str(st.id)
                meta["value"] = getattr(st, "value", meta.get("value"))

    def _push_alias_to_state(self, name: str):
        meta = self._vars.get(name) or {}
        alias = (meta.get("state_alias") or "").strip()
        alias_id = (meta.get("state_alias_id") or "").strip()
        if not alias and not alias_id:
            return
        try:
            st = find_gex_state(alias_id, alias)
            if st is not None:
                st.value = meta.get("value")
                meta["state_alias"] = st.key
                meta["state_alias_id"] = _state_id_str(st.id)
        except Exception:
            pass


def evaluate_expression(text: str) -> str:
    """Replace $(var:name) and $(state:name) in a title/expression string."""
    if not text or "$(" not in text:
        return text or ""

    store = SurfaceVariableStore()

    def _repl(m):
        kind = (m.group(1) or "").lower()
        name = (m.group(2) or "").strip()
        if kind == "var":
            val = store.get(name, "")
            return "" if val is None else str(val)
        if kind == "state":
            try:
                import gremlin.ui.state_device as state_device

                st = state_device.StateData().getState(name)
                if st is None:
                    return ""
                return str(getattr(st, "value", ""))
            except Exception:
                return ""
        return m.group(0)

    return _EXPR_RE.sub(_repl, text)


def resolved_title(item) -> str:
    """Title sent to Elgato. When text is baked into the composite image, clear HW title.

    Do not fall back to ``button_id`` (``row:col``) — that painted coordinate
    strings like ``1:4`` onto empty keys that had a profile slot but no title.
    Also ignore Companion-style empty-key placeholders (``col/row``).
    """
    if item_needs_composite(item) and (
        getattr(item, "bg_color", "")
        or getattr(item, "image", "")
        or getattr(item, "image_path", "")
        or text_lines_for_item(item)
    ):
        return ""
    title = str(getattr(item, "title", None) or "").strip()
    if not title or _is_coordinate_placeholder_title(title):
        return ""
    return title


def resolved_image(item) -> str:
    """Composite appearance when style/icon/text present; else simple icon paint."""
    if item_needs_composite(item):
        return compose_key_image(item)
    expr = getattr(item, "image_expr", None) or ""
    if expr.strip():
        path_or_url = evaluate_expression(expr)
        return file_to_data_url(path_or_url) if path_or_url and not path_or_url.startswith("data:") else path_or_url
    return resolve_paint_image(item)


def _resolve_input_item(container=None, event=None, extra_data=None):
    if container is not None:
        item = getattr(container, "input_item", None)
        if item is not None:
            return item
        parent = getattr(container, "parent", None)
        if parent is not None and hasattr(parent, "step_mode"):
            return parent
    if isinstance(extra_data, dict):
        item = extra_data.get("input_item")
        if item is not None:
            return item
    if event is not None:
        ed = getattr(event, "extra_data", None) or {}
        if isinstance(ed, dict):
            return ed.get("input_item")
    return None


def container_allowed_for(container, input_item) -> bool:
    """Whether this container may run for the input item's current step mode."""
    try:
        if container is None or input_item is None:
            return True
        mode = getattr(input_item, "step_mode", STEP_ALL) or STEP_ALL
        if mode == STEP_ALL:
            return True
        containers = list(getattr(input_item, "containers", []) or [])
        if not containers:
            return True
        try:
            idx = containers.index(container)
        except ValueError:
            return True
        step = int(getattr(input_item, "step_index", 0) or 0)
        if mode == STEP_LATCH:
            return idx == (step % max(1, min(2, len(containers))))
        return idx == (step % len(containers))
    except Exception:
        return True


def container_allowed(functor, event, extra_data=None) -> bool:
    """Gate container functors for Stream Deck Advance/Latch step modes."""
    try:
        container = getattr(functor, "action_data", None)
        if container is None:
            container = getattr(functor, "container", None)
        # Action functors: walk to owning container
        if container is not None and not hasattr(container, "action_sets"):
            parent = getattr(container, "parent", None)
            if parent is not None and hasattr(parent, "action_sets"):
                container = parent
            else:
                return True
        input_item = _resolve_input_item(container, event, extra_data)
        return container_allowed_for(container, input_item)
    except Exception:
        return True


def advance_step(item, is_pressed: bool):
    """Advance step_index after a press for Advance/Latch modes."""
    if not is_pressed:
        return
    mode = getattr(item, "step_mode", STEP_ALL) or STEP_ALL
    if mode == STEP_ALL:
        return
    containers = list(getattr(item, "containers", []) or [])
    n = len(containers)
    if n <= 0:
        return
    cur = int(getattr(item, "step_index", 0) or 0)
    if mode == STEP_LATCH:
        item.step_index = 1 - (cur % 2)
    else:
        wrap = bool(getattr(item, "step_wrap", True))
        nxt = cur + 1
        if wrap:
            item.step_index = nxt % n
        else:
            item.step_index = min(nxt, n - 1)


def install_functor_step_gate():
    """Patch ExecutionContext.execute_node once so Advance/Latch skip whole container subtrees."""
    import gremlin.execution_graph as eg

    # ExecutionContext is a SingletonDecorator wrapper — patch the real class.
    cls = getattr(eg.ExecutionContext, "klass", None) or eg.ExecutionContext
    if getattr(cls.execute_node, "_sd_step_gated", False):
        return
    _orig = cls.execute_node

    def _gated(self, node, event, value, extra_data: dict = None, manual=False, visited=None):
        try:
            if getattr(node, "nodeType", None) == eg.ExecutionGraphNodeType.Container:
                container = getattr(node, "container", None)
                item = _resolve_input_item(container, event, extra_data)
                if not container_allowed_for(container, item):
                    return True
        except Exception:
            pass
        return _orig(self, node, event, value, extra_data, manual, visited)

    _gated._sd_step_gated = True
    cls.execute_node = _gated


def request_feedback_paint():
    """Re-paint active pages on all known decks after variable/state change."""
    try:
        from gremlin.ui.streamdeck_device import StreamDeckBridge

        bridge = StreamDeckBridge()
        for device_id in list(getattr(bridge, "devices", {}) or {}):
            bridge._schedule_paint(device_id)
    except Exception as err:
        syslog.error(f"SURFACE: feedback paint failed: {err}")


def hook_feedback_engine():
    """Connect variable/state changes to coalesced deck paint."""
    store = SurfaceVariableStore()
    store.ensure_hooks()
    if getattr(hook_feedback_engine, "_done", False):
        return
    hook_feedback_engine._done = True

    def _on_var(_name=None, _value=None):
        request_feedback_paint()

    def _on_state(*_args):
        try:
            store._sync_aliases_from_states()
        except Exception:
            pass
        request_feedback_paint()

    store.changed.connect(_on_var)
    try:
        import gremlin.ui.state_device as state_device

        sd = state_device.StateData()
        sd.changed.connect(_on_state)
    except Exception:
        pass
