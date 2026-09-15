# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import copy
import json
import logging
import os
import uuid
from typing import Any

from PySide6 import QtCore
from psygnal import Signal

import gremlin.shared_state
import gremlin.util

syslog = logging.getLogger("system")

SCENE_VERSION = 2
OVERLAY_WINDOW_TITLE = "GEX Overlay"


def overlay_window_title(page: dict[str, Any] | None = None, name: str | None = None) -> str:
    label = str(name if name is not None else (page or {}).get("name") or "Overlay").strip() or "Overlay"
    return f"{OVERLAY_WINDOW_TITLE} — {label}"


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

WIDGET_TYPES = (
    "axis_bar",
    "axis_radio",
    "axis_fader",
    "axis_radial",
    "axis_encoder",
    "axis_paddle",
    "axis_graph",
    "axis_bars",
    "axis_stick_square",
    "axis_crosshair",
    "axis_stick_circle",
    "axis_mouse",
    "button",
    "hat",
    "switch_4way",
    "switch_2way",
    "switch_3way",
    "label",
    "sys_stats",
    "stopwatch",
    "input_display",
    "shape",
    "image",
    "streamdeck",
    "panel",  # legacy alias of shape
    "axis_dial",  # legacy alias of axis_radial
)

PALETTE_TYPES = (
    "button",
    "hat",
    "switch_4way",
    "switch_2way",
    "switch_3way",
    "axis_bar",
    "axis_radio",
    "axis_fader",
    "axis_radial",
    "axis_encoder",
    "axis_paddle",
    "axis_stick_square",
    "axis_crosshair",
    "axis_stick_circle",
    "axis_mouse",
    "sys_stats",
    "stopwatch",
    "axis_graph",
    "axis_bars",
    "label",
    "input_display",
    "shape",
    "image",
    "streamdeck",
)

PALETTE_GROUPS = (
    ("Buttons", ("button", "hat", "switch_4way", "switch_2way", "switch_3way")),
    ("Single axis", ("axis_bar", "axis_radio", "axis_fader", "axis_radial", "axis_encoder", "axis_paddle")),
    ("Double axis", ("axis_stick_square", "axis_crosshair", "axis_stick_circle", "axis_mouse")),
    ("Meters", ("sys_stats", "stopwatch")),
    ("Other", ("axis_graph", "axis_bars", "label", "input_display", "shape", "image", "streamdeck")),
)

DEFAULT_SIZES = {
    "axis_bar": (48, 180),
    "axis_radio": (220, 36),
    "axis_fader": (40, 180),
    "axis_radial": (150, 150),
    "axis_encoder": (150, 150),
    "axis_paddle": (160, 160),
    "axis_graph": (420, 180),
    "axis_bars": (220, 180),
    "axis_dial": (150, 150),
    "axis_stick_square": (168, 168),
    "axis_stick_circle": (180, 180),
    "axis_crosshair": (220, 220),
    "axis_mouse": (180, 180),
    "button": (88, 32),
    "hat": (108, 108),
    "switch_4way": (120, 120),
    "switch_2way": (100, 100),
    "switch_3way": (48, 120),
    "label": (140, 28),
    "sys_stats": (220, 88),
    "stopwatch": (180, 180),
    "input_display": (560, 220),
    "shape": (280, 160),
    "image": (200, 120),
    "streamdeck": (320, 208),
    "panel": (280, 160),
}

DEFAULT_LABELS = {
    "axis_bar": "",
    "axis_radio": "",
    "axis_fader": "",
    "axis_radial": "",
    "axis_encoder": "",
    "axis_paddle": "",
    "axis_graph": "",
    "axis_bars": "",
    "axis_dial": "",
    "axis_stick_square": "",
    "axis_stick_circle": "",
    "axis_crosshair": "",
    "axis_mouse": "",
    "button": "BTN",
    "hat": "",
    "switch_4way": "",
    "switch_2way": "",
    "switch_3way": "",
    "label": "Label",
    "sys_stats": "",
    "stopwatch": "",
    "input_display": "",
    "shape": "",
    "image": "",
    "streamdeck": "",
    "panel": "",
}


def _new_id() -> str:
    return str(uuid.uuid4())


def default_style(widget_type: str) -> dict[str, Any]:
    """Default visual style for a widget type."""
    style: dict[str, Any] = {
        "fill": "#121826",
        "fill_on": "#ff6b35",
        "border": "#2c3a52",
        "border_on": "#ffb347",
        "border_width": 2.0,
        "corner_radius": 6.0,
        "indicator": "#ff5a3c",
        "indicator_size": 12.0,
        "track": "#0b1220",
        "fill_bar": "#ff6b35",
        "grid": "#2a3a55",
        "grid_width": 1.0,
        "crosshair": "#5a6a84",
        "needle": "#ff5a3c",
        "needle_width": 3.0,
        "font_family": "Segoe UI",
        "font_size": 11,
        "font_bold": True,
        "font_color": "#f4efe4",
        "axis_label_font_family": "Segoe UI",
        "axis_label_font_size": 11,
        "axis_label_font_bold": True,
        "axis_label_font_color": "#f4efe4",
        "label_offset_x": 0,
        "label_offset_y": 0,
        "show_label": True,
        "show_axis_labels": True,
        "axis_label_n": "U",
        "axis_label_s": "D",
        "axis_label_e": "R",
        "axis_label_w": "L",
        "axis_label_spread": 100,
        "orientation": "vertical",
        "shape": "rounded",
        "ring_count": 3,
        "show_center_line": True,
        "show_dot_crosshair": False,
        "show_dot_shadow": True,
        "show_grid": True,
        "grid_fade": False,
        "indicator_shape": "circle",
        "angle_step": 0,
        "radio_steps": 5,
        "deadzone": 0.0,
        "invert_display": False,
        "opacity": 1.0,
        "auto_scale_font": False,
        "show_current_mode": False,
    }
    if widget_type == "axis_bar":
        style.update({"corner_radius": 6.0, "indicator_size": 14.0, "show_label": False, "show_dot_shadow": True})
    elif widget_type == "axis_radio":
        style.update({"orientation": "horizontal", "radio_steps": 5, "show_label": False})
    elif widget_type == "axis_fader":
        style.update(
            {
                "corner_radius": 4.0,
                "indicator_size": 0.0,
                "radio_steps": 8,
                "show_label": False,
                "fill_bar": "#b04a25",
            }
        )
    elif widget_type in ("axis_radial", "axis_dial"):
        style.update({"indicator_size": 10.0, "show_label": False, "needle_width": 14.0, "radio_steps": 11})
    elif widget_type == "axis_encoder":
        style.update({"show_label": False, "needle_width": 0.0, "radio_steps": 16})
    elif widget_type == "axis_paddle":
        style.update(
            {
                "show_label": False,
                "fill": "#6a6f78",
                "fill_on": "#c4c8d0",
                "border": "#1a1d22",
                "indicator": "#2a2e36",
                "indicator_size": 18.0,
                "paddle_start_deg": 0.0,
                "paddle_end_deg": 70.0,
                "paddle_direction": "cw",
            }
        )
    elif widget_type == "axis_graph":
        style.update(
            {
                "show_label": False,
                "show_legend": True,
                "show_grid": True,
                "period_s": 8.0,
                "value_min": -1.0,
                "value_max": 1.0,
                "unit": "",
                "grid_width": 1.0,
            }
        )
    elif widget_type == "axis_bars":
        style.update(
            {
                "show_label": False,
                "show_legend": True,
                "show_grid": True,
                "orientation": "vertical",
                "range_auto": True,
                "value_min": 0.0,
                "value_max": 100.0,
                "unit": "%",
                "grid_width": 1.0,
            }
        )
    elif widget_type == "axis_stick_square":
        style.update(
            {
                "axis_label_n": "F",
                "axis_label_s": "A",
                "axis_label_e": "R",
                "axis_label_w": "L",
                "indicator_size": 14.0,
                "show_label": False,
            }
        )
    elif widget_type == "axis_stick_circle":
        style.update({"indicator_size": 14.0, "show_label": False, "ring_count": 2})
    elif widget_type == "axis_crosshair":
        style.update(
            {
                "fill": "#0a1220",
                "indicator_size": 14.0,
                "show_label": False,
                "ring_count": 3,
            }
        )
    elif widget_type == "axis_mouse":
        style.update(
            {
                "show_label": False,
                "show_axis_labels": False,
                "indicator_size": 28.0,
                "needle_width": 4.0,
                "mouse_mode": "vjoy",
                "mouse_max": 250,
                "mouse_idle_s": 1.0,
            }
        )
    elif widget_type == "button":
        style.update(
            {
                "fill": "#3a1518",
                "fill_on": "#ff6b35",
                "border": "#6a2a22",
                "border_on": "#ffcc66",
                "font_size": 10,
                "shape": "rounded",
                "corner_radius": 5.0,
            }
        )
    elif widget_type == "hat":
        style.update({"indicator_size": 12.0, "show_label": False, "show_axis_labels": True, "hat_positions": 4})
    elif widget_type == "switch_4way":
        style.update(
            {
                "switch_appearance": "arrows",
                "fill": "#1a2230",
                "fill_on": "#ff6b35",
                "border": "#3a4a62",
                "border_on": "#ffcc66",
                "border_width": 2.0,
                "indicator": "#2a3548",
                "indicator_size": 28.0,
                "show_label": False,
                "show_axis_labels": False,
                "axis_label_n": "N",
                "axis_label_s": "S",
                "axis_label_e": "E",
                "axis_label_w": "W",
                "track": "#0b1220",
                "crosshair": "#5a6a84",
            }
        )
    elif widget_type == "switch_2way":
        style.update(
            {
                "switch_appearance": "arrows",
                "fill": "#1a2230",
                "fill_on": "#ff6b35",
                "border": "#3a4a62",
                "border_on": "#ffcc66",
                "border_width": 2.0,
                "indicator": "#2a3548",
                "indicator_size": 28.0,
                "orientation": "vertical",
                "show_label": False,
                "show_axis_labels": False,
                "axis_label_n": "N",
                "axis_label_s": "S",
                "axis_label_e": "E",
                "axis_label_w": "W",
                "track": "#0b1220",
                "crosshair": "#5a6a84",
            }
        )
    elif widget_type == "switch_3way":
        style.update(
            {
                "fill": "#1a2230",
                "fill_on": "#ff6b35",
                "border": "#3a4a62",
                "border_on": "#ffcc66",
                "orientation": "vertical",
                "indicator_size": 10.0,
                "show_label": False,
                "show_axis_labels": True,
                "axis_label_n": "+",
                "axis_label_s": "−",
                "axis_label_e": "−",
                "axis_label_w": "+",
            }
        )
    elif widget_type == "label":
        style.update(
            {
                "fill": "#00000000",
                "border": "#ff2a2a",
                "border_width": 0.0,
                "corner_radius": 4.0,
                "font_size": 13,
                "show_label": True,
            }
        )
    elif widget_type == "sys_stats":
        style.update(
            {
                "fill": "#121826",
                "border": "#2c3a52",
                "border_width": 2.0,
                "corner_radius": 8.0,
                "font_size": 22,
                "show_label": False,
                "show_caption": True,
                "stat": "time",
                "time_format": "24h",
                "temp_unit": "C",
                "orientation": "vertical",
            }
        )
    elif widget_type == "stopwatch":
        style.update(
            {
                "fill": "#121826",
                "border": "#2c3a52",
                "border_width": 2.0,
                "corner_radius": 8.0,
                "font_size": 22,
                "show_label": False,
                "stopwatch_face": "digital",
                "stopwatch_format": "mmss",
                "needle_hour_color": "#f4efe4",
                "needle_hour_width": 5.0,
                "needle_hour_arrow": True,
                "needle_minute_color": "#f4efe4",
                "needle_minute_width": 3.5,
                "needle_minute_arrow": True,
                "needle_second_color": "#ff5a3c",
                "needle_second_width": 2.0,
                "needle_second_arrow": False,
            }
        )
    elif widget_type == "input_display":
        style.update(
            {
                "fill": "#1a1d22",
                "fill_on": "#4ec8ff",
                "border": "#e8eef8",
                "border_on": "#4ec8ff",
                "border_width": 2.0,
                "corner_radius": 6.0,
                "font_size": 11,
                "show_label": False,
                "show_keyboard": True,
                "show_mouse": True,
                "mouse_graphic": "silhouette",
                "input_preset": "wasd_mouse",
            }
        )
    elif widget_type in ("shape", "panel"):
        style.update(
            {
                "fill": "#101820",
                "border": "#1e2a3a",
                "border_width": 2.0,
                "corner_radius": 18.0,
                "opacity": 0.92,
                "show_label": False,
                "shape_kind": "rectangle",
                "shape_closed": True,
            }
        )
    elif widget_type == "image":
        style.update(
            {
                "fill": "#00000000",
                "border": "#1e2a3a",
                "border_width": 0.0,
                "opacity": 1.0,
                "show_label": False,
                "image_path": "",
                "image_keep_aspect": True,
            }
        )
    elif widget_type == "streamdeck":
        style.update(
            {
                "fill": "#1a1d22",
                "border": "#3a414c",
                "border_width": 2.0,
                "corner_radius": 14.0,
                "opacity": 1.0,
                "show_label": False,
                "streamdeck_device_id": "",
                "streamdeck_follow_page": True,
                "streamdeck_page": 1,
                "show_bezel": True,
            }
        )
    return style


def _refresh_font_scale_base(item: dict[str, Any], style_updates: dict[str, Any] | None = None):
    """Remember the widget size that the current font size was chosen at."""
    style = item.get("style") or {}
    if not style.get("auto_scale_font"):
        return
    updates = style_updates or {}
    if "font_scale_base" in updates:
        return
    if not (
        "auto_scale_font" in updates
        or "font_size" in updates
        or "axis_label_font_size" in updates
        or not style.get("font_scale_base")
    ):
        return
    style["font_scale_base"] = min(max(1, int(item.get("w") or 1)), max(1, int(item.get("h") or 1)))


OVERLAY_CONFIG_KEY = "obs_overlay"
XY_WIDGET_TYPES = ("axis_stick_square", "axis_stick_circle", "axis_crosshair")
NO_CORNER_RADIUS_TYPES = (
    "axis_radio",
    "axis_radial",
    "axis_dial",
    "axis_encoder",
    "axis_paddle",
    "axis_crosshair",
    "axis_stick_circle",
)
SINGLE_AXIS_TYPES = (
    "axis_bar",
    "axis_radio",
    "axis_fader",
    "axis_radial",
    "axis_encoder",
    "axis_paddle",
    "axis_dial",
)
SERIES_WIDGET_TYPES = ("axis_graph", "axis_bars")
NO_BINDING_WIDGET_TYPES = (
    "label",
    "panel",
    "shape",
    "image",
    "streamdeck",
    "axis_mouse",
    "axis_graph",
    "axis_bars",
    "sys_stats",
    "input_display",
)
NO_DEADZONE_WIDGET_TYPES = NO_BINDING_WIDGET_TYPES + (
    "stopwatch",
    "switch_4way",
    "switch_2way",
    "switch_3way",
)

SWITCH_WIDGET_TYPES = ("switch_4way", "switch_2way", "switch_3way")
SWITCH_4WAY_POSITIONS = ("n", "e", "s", "w", "center")
SWITCH_2WAY_POSITIONS = ("a", "center", "b")
SWITCH_3WAY_POSITIONS = ("up", "center", "down")
SWITCH_POSITION_TITLES = {
    "switch_4way": (("n", "North"), ("e", "East"), ("s", "South"), ("w", "West"), ("center", "Center")),
    "switch_2way": (("a", "North / Position 1"), ("center", "Center"), ("b", "South / Position 2")),
    "switch_3way": (("up", "Up"), ("center", "Center"), ("down", "Down")),
}
_SWITCH_POSITION_ALIASES = {
    "a": "up",
    "b": "down",
    "up": "a",
    "down": "b",
    "n": "up",
    "s": "down",
}


def widget_uses_series(widget_type: str) -> bool:
    return widget_type in SERIES_WIDGET_TYPES


def widget_is_switch(widget_type: str | None) -> bool:
    return canonical_widget_type(widget_type or "") in SWITCH_WIDGET_TYPES


def switch_positions(widget_type: str | None) -> tuple[str, ...]:
    kind = canonical_widget_type(widget_type or "")
    if kind == "switch_4way":
        return SWITCH_4WAY_POSITIONS
    if kind == "switch_2way":
        return SWITCH_2WAY_POSITIONS
    if kind == "switch_3way":
        return SWITCH_3WAY_POSITIONS
    return ()


def switch_rest_position(widget_type: str | None) -> str | None:
    kind = canonical_widget_type(widget_type or "")
    if kind in ("switch_4way", "switch_3way", "switch_2way"):
        return "center"
    return None


def switch_channel(position: str) -> str:
    return f"bindings.{position}"


def normalize_switch_appearance(value) -> str:
    raw = str(value or "").strip().casefold()
    if raw in ("arcs", "arc"):
        return "arcs"
    if raw in ("bars", "bar", "slots", "slot", "toggle"):
        return "bars"
    return "arrows"


def normalize_paddle_direction(value) -> str:
    raw = str(value or "").strip().casefold()
    if raw in ("ccw", "counterclockwise", "counter-clockwise", "anticlockwise"):
        return "ccw"
    return "cw"


def switch_2way_cardinal_slots(item: dict[str, Any] | None) -> tuple[str, str]:
    """Visual cardinal slots for a 2-way: vertical N/S, horizontal W/E."""
    vertical = ((item or {}).get("style") or {}).get("orientation") or "vertical"
    if str(vertical).casefold() == "horizontal":
        return ("w", "e")
    return ("n", "s")


def switch_2way_value_to_cardinal(item: dict[str, Any] | None, value: str) -> str:
    first, second = switch_2way_cardinal_slots(item)
    if value == "a":
        return first
    if value == "b":
        return second
    return ""


def switch_2way_cardinal_to_value(item: dict[str, Any] | None, cardinal: str) -> str:
    first, second = switch_2way_cardinal_slots(item)
    if cardinal == first:
        return "a"
    if cardinal == second:
        return "b"
    return ""


def switch_binding(item: dict[str, Any] | None, position: str) -> dict[str, Any]:
    bindings = (item or {}).get("bindings")
    if isinstance(bindings, dict) and isinstance(bindings.get(position), dict):
        return bindings[position]
    return default_toggle_binding()


def default_switch_bindings(widget_type: str | None) -> dict[str, Any]:
    return {position: default_toggle_binding() for position in switch_positions(widget_type)}


def normalize_switch_bindings(widget_type: str | None, raw=None) -> dict[str, Any]:
    result = default_switch_bindings(widget_type)
    if isinstance(raw, dict):
        src = raw.get("bindings") if isinstance(raw.get("bindings"), dict) else raw
    else:
        src = {}
    if not isinstance(src, dict):
        src = {}
    for position in result:
        if position in src:
            result[position] = normalize_toggle_binding(src.get(position))
            continue
        alias = _SWITCH_POSITION_ALIASES.get(position)
        if alias and alias in src:
            result[position] = normalize_toggle_binding(src.get(alias))
    return result


def widget_binding_kind(widget_type: str) -> str:
    if widget_type in XY_WIDGET_TYPES:
        return "xy"
    if widget_type in ("button", "stopwatch"):
        return "button"
    if widget_type in SWITCH_WIDGET_TYPES:
        return "switch"
    if widget_type == "hat":
        return "hat"
    if widget_type in NO_BINDING_WIDGET_TYPES:
        return "none"
    if widget_type in SINGLE_AXIS_TYPES or str(widget_type).startswith("axis"):
        return "axis"
    return "none"


def serialize_overlay_key(key) -> dict[str, Any]:
    """JSON-safe keyboard/mouse key for overlay bindings."""
    try:
        scan_code = int(getattr(key, "scan_code", 0) or 0)
    except (TypeError, ValueError):
        scan_code = 0
    return {
        "scan_code": scan_code,
        "is_extended": bool(getattr(key, "is_extended", False)),
        "is_mouse": bool(getattr(key, "is_mouse", False) or scan_code >= 0x1000),
        "name": str(getattr(key, "name", None) or ""),
    }


def deserialize_overlay_key(raw) -> Any:
    """Rebuild a GEX Key from overlay JSON (or pass a Key through)."""
    from gremlin.keyboard import Key, key_from_code

    if isinstance(raw, Key):
        return raw
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return key_from_code(int(raw[0]), bool(raw[1]))
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    try:
        scan_code = int(raw.get("scan_code") or 0)
    except (TypeError, ValueError):
        scan_code = 0
    is_mouse = bool(raw.get("is_mouse") or scan_code >= 0x1000)
    try:
        if is_mouse:
            return Key(scan_code=scan_code, is_mouse=True)
        return key_from_code(scan_code, bool(raw.get("is_extended")))
    except Exception:
        return None


def normalize_overlay_keys(raw) -> list[dict[str, Any]]:
    keys = []
    seen: set[tuple] = set()
    for item in raw or []:
        key = deserialize_overlay_key(item)
        if key is None:
            continue
        try:
            ident = (int(key.scan_code), bool(key.is_extended), bool(getattr(key, "is_mouse", False)))
        except Exception:
            continue
        if ident in seen:
            continue
        seen.add(ident)
        keys.append(serialize_overlay_key(key))
    return keys


def default_binding(axis_id: int = 1) -> dict[str, Any]:
    return {
        "source": "physical",
        "device_guid": "",
        "device_name": "",
        "vjoy_id": 0,
        "input_type": "axis",
        "input_id": int(axis_id),
        "state_name": "",
        "mode_name": "",
        "invert": False,
        "keys": [],
    }


GRAPH_SERIES_COLORS = (
    "#e41a1c",
    "#377eb8",
    "#4daf4a",
    "#984ea3",
    "#ff7f00",
    "#c9b037",
    "#9cad1c",
    "#2cb2f5",
)


def default_graph_series(index: int = 0) -> dict[str, Any]:
    color = GRAPH_SERIES_COLORS[int(index) % len(GRAPH_SERIES_COLORS)]
    return {
        "id": _new_id(),
        "source": "physical",
        "device_guid": "",
        "device_name": "",
        "vjoy_id": 0,
        "input_id": 0,
        "invert": False,
        "color": color,
        "label": "",
        "range_mode": "auto",
    }


def normalize_graph_series(raw) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        entry = default_graph_series(index)
        entry.update({key: item[key] for key in entry.keys() if key in item})
        source = str(entry.get("source") or "physical").casefold()
        entry["source"] = "vjoy" if source == "vjoy" else "physical"
        entry["device_guid"] = str(entry.get("device_guid") or "")
        entry["device_name"] = str(entry.get("device_name") or "")
        entry["label"] = str(entry.get("label") or "")
        color = str(entry.get("color") or "").strip() or GRAPH_SERIES_COLORS[index % len(GRAPH_SERIES_COLORS)]
        entry["color"] = color
        try:
            entry["vjoy_id"] = int(entry.get("vjoy_id") or 0)
        except (TypeError, ValueError):
            entry["vjoy_id"] = 0
        try:
            entry["input_id"] = int(entry.get("input_id") or 0)
        except (TypeError, ValueError):
            entry["input_id"] = 0
        entry["invert"] = bool(entry.get("invert"))
        entry["range_mode"] = normalize_series_range_mode(entry.get("range_mode") or entry.get("centered"))
        cid = str(entry.get("id") or "")
        if not cid or cid in seen:
            entry["id"] = _new_id()
        seen.add(entry["id"])
        series.append(entry)
    return series


def default_stat_entry(index: int = 0, stat: str = "time") -> dict[str, Any]:
    from .sys_stats import normalize_stat

    color = "#f4efe4" if int(index) == 0 else GRAPH_SERIES_COLORS[int(index) % len(GRAPH_SERIES_COLORS)]
    return {
        "id": _new_id(),
        "stat": normalize_stat(stat),
        "color": color,
        "label": "",
        "step": 1,
        "value": 0,
        "binding": default_toggle_binding(),
        "binding_y": default_toggle_binding(),
        "binding_z": default_toggle_binding(),
    }


def normalize_stat_series(raw, fallback_stat: str = "time") -> list[dict[str, Any]]:
    from .sys_stats import normalize_stat

    series: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        entry = default_stat_entry(index, item.get("stat") or fallback_stat)
        entry.update({key: item[key] for key in entry.keys() if key in item})
        entry["stat"] = normalize_stat(entry.get("stat"))
        entry["label"] = str(entry.get("label") or "")
        color = str(entry.get("color") or "").strip() or GRAPH_SERIES_COLORS[index % len(GRAPH_SERIES_COLORS)]
        entry["color"] = color
        try:
            entry["step"] = max(1, int(entry.get("step") or 1))
        except (TypeError, ValueError):
            entry["step"] = 1
        try:
            entry["value"] = int(entry.get("value") or 0)
        except (TypeError, ValueError):
            entry["value"] = 0
        entry["binding"] = normalize_toggle_binding(entry.get("binding"))
        entry["binding_y"] = normalize_toggle_binding(entry.get("binding_y"))
        entry["binding_z"] = normalize_toggle_binding(entry.get("binding_z"))
        cid = str(entry.get("id") or "")
        if not cid or cid in seen:
            entry["id"] = _new_id()
        seen.add(entry["id"])
        series.append(entry)
    if not series:
        series.append(default_stat_entry(0, fallback_stat))
    return series


SERIES_RANGE_MODES = ("auto", "centered", "unipolar")
_UNIPOLAR_NAME_HINTS = (
    "throttle",
    "slider",
    "brake",
    "accelerator",
    "pedal",
    "collective",
    "s1",
    "s2",
)


def normalize_series_range_mode(value) -> str:
    raw = str(value or "auto").casefold().strip()
    if raw in ("centered", "bipolar", "yes", "true", "1"):
        return "centered"
    if raw in ("unipolar", "no", "false", "0"):
        return "unipolar"
    return "auto"


def series_is_centered(series: dict[str, Any] | None) -> bool:
    """True when this axis should plot −100..+100 instead of 0..100."""
    series = series or {}
    mode = normalize_series_range_mode(series.get("range_mode") or series.get("centered"))
    if mode == "centered":
        return True
    if mode == "unipolar":
        return False
    try:
        input_id = int(series.get("input_id") or 0)
    except (TypeError, ValueError):
        input_id = 0
    names: list[str] = []
    try:
        import gremlin.joystick_handling

        names.append(gremlin.joystick_handling.get_axis_name(input_id) or "")
        guid = series.get("device_guid")
        if guid:
            device = gremlin.joystick_handling.getDevice(guid, show_error=False)
            getter = getattr(device, "get_axis_name", None) if device is not None else None
            if callable(getter):
                names.append(str(getter(input_id) or ""))
    except Exception:
        pass
    blob = " ".join(names).casefold()
    if any(hint in blob for hint in _UNIPOLAR_NAME_HINTS):
        return False
    if input_id in (7, 8):
        return False
    return True


def axis_display_percent(raw_value: float, centered: bool) -> float:
    """Map a GEX axis (−1..+1) to percent for bar-graph display."""
    try:
        value = max(-1.0, min(1.0, float(raw_value)))
    except (TypeError, ValueError):
        value = 0.0
    if centered:
        return value * 100.0
    return (value + 1.0) * 50.0


def bars_value_range(item: dict[str, Any] | None) -> tuple[float, float]:
    """Min/max percent for a bar-graph widget, auto or custom."""
    style = (item or {}).get("style") or {}
    auto = bool(style.get("range_auto", True))
    if auto:
        series = (item or {}).get("series") or []
        bipolar = False
        any_axis = False
        for entry in series:
            if not isinstance(entry, dict):
                continue
            try:
                if int(entry.get("input_id") or 0) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            any_axis = True
            if series_is_centered(entry):
                bipolar = True
                break
        if not any_axis:
            return (0.0, 100.0)
        return (-100.0, 100.0) if bipolar else (0.0, 100.0)
    try:
        lo = float(style.get("value_min") if style.get("value_min") is not None else 0.0)
    except (TypeError, ValueError):
        lo = 0.0
    try:
        hi = float(style.get("value_max") if style.get("value_max") is not None else 100.0)
    except (TypeError, ValueError):
        hi = 100.0
    if hi <= lo:
        hi = lo + 0.001
    return lo, hi


def default_toggle_binding() -> dict[str, Any]:
    binding = default_binding(1)
    binding["input_type"] = "button"
    binding["input_id"] = 0
    return binding


def normalize_toggle_binding(raw) -> dict[str, Any]:
    binding = default_toggle_binding()
    if isinstance(raw, dict):
        binding.update(raw)
    kind = str(binding.get("input_type") or "button").casefold()
    source = str(binding.get("source") or "").casefold()
    if source in ("keyboard", "keyboard/mouse", "mouse"):
        binding["source"] = "keyboard"
        binding["input_type"] = "keyboard"
    else:
        binding["input_type"] = kind if kind in ("axis", "button", "hat", "state", "mode", "keyboard") else "button"
    try:
        binding["input_id"] = int(binding.get("input_id") or 0)
    except (TypeError, ValueError):
        binding["input_id"] = 0
    binding["invert"] = bool(binding.get("invert"))
    binding["keys"] = normalize_overlay_keys(binding.get("keys"))
    return binding


VISIBILITY_KINDS = ("mode", "state", "physical", "vjoy", "keyboard")


def default_visibility() -> dict[str, Any]:
    return {"join": "all", "conditions": []}


def normalize_visibility_kind(kind) -> str:
    value = str(kind or "mode").casefold()
    if value in ("joystick", "button", "physical"):
        return "physical"
    if value in ("keyboard/mouse", "mouse"):
        return "keyboard"
    if value in VISIBILITY_KINDS:
        return value
    return "mode"


def default_visibility_condition(kind: str = "mode") -> dict[str, Any]:
    return {
        "id": _new_id(),
        "kind": normalize_visibility_kind(kind),
        "when": "on",
        "mode_name": "",
        "state_name": "",
        "device_guid": "",
        "device_name": "",
        "vjoy_id": 0,
        "input_id": 0,
        "keys": [],
    }


def normalize_visibility(raw) -> dict[str, Any]:
    vis = default_visibility()
    if not isinstance(raw, dict):
        return vis
    join = str(raw.get("join") or "all").casefold()
    vis["join"] = "any" if join == "any" else "all"
    seen: set[str] = set()
    conditions: list[dict[str, Any]] = []
    for cond in raw.get("conditions") or []:
        if not isinstance(cond, dict):
            continue
        item = default_visibility_condition(cond.get("kind"))
        item.update({key: cond[key] for key in item.keys() if key in cond})
        item["kind"] = normalize_visibility_kind(item.get("kind"))
        item["when"] = "off" if str(item.get("when") or "on").casefold() == "off" else "on"
        item["mode_name"] = str(item.get("mode_name") or "")
        item["state_name"] = str(item.get("state_name") or "")
        item["device_guid"] = str(item.get("device_guid") or "")
        item["device_name"] = str(item.get("device_name") or "")
        try:
            item["vjoy_id"] = int(item.get("vjoy_id") or 0)
        except (TypeError, ValueError):
            item["vjoy_id"] = 0
        try:
            item["input_id"] = int(item.get("input_id") or 0)
        except (TypeError, ValueError):
            item["input_id"] = 0
        item["keys"] = normalize_overlay_keys(item.get("keys"))
        cid = str(item.get("id") or "")
        if not cid or cid in seen:
            item["id"] = _new_id()
        seen.add(item["id"])
        conditions.append(item)
    vis["conditions"] = conditions
    return vis


def default_canvas() -> dict[str, Any]:
    return {
        "width": 1280,
        "height": 720,
        "background_mode": "chroma",
        "chroma_color": "#00FF00",
        "image_path": "",
        "grid_size": 8,
        "snap_to_grid": True,
        "always_on_top": False,
        "frameless": False,
        "show_drag_bar": True,
        "show_on_profile_start": False,
        "interactive": False,
        "toggle_binding": default_toggle_binding(),
        "monitor_index": 0,
        "monitor_name": "",
        "capture_width": 1280,
        "capture_height": 720,
        "guides": [],
    }


def default_page(name: str = "Overlay") -> dict[str, Any]:
    return {
        "id": _new_id(),
        "name": str(name).strip() or "Overlay",
        "visible": True,
        "window_x": None,
        "window_y": None,
        "canvas": default_canvas(),
        "widgets": [],
    }


DEFAULT_GUIDE_COLOR = "#c44cff"


def normalize_guides(canvas: dict[str, Any] | None) -> list[dict[str, Any]]:
    canvas = canvas if isinstance(canvas, dict) else {}
    guides = []
    for raw in canvas.get("guides") or []:
        if not isinstance(raw, dict):
            continue
        axis = str(raw.get("axis") or "v").casefold()
        axis = "h" if axis.startswith("h") else "v"
        try:
            pos = float(raw.get("position") if raw.get("position") is not None else 0.5)
        except (TypeError, ValueError):
            pos = 0.5
        if pos > 1.0:
            pos = pos / 100.0
        pos = max(0.0, min(1.0, pos))
        color = str(raw.get("color") or DEFAULT_GUIDE_COLOR)
        gid = str(raw.get("id") or "") or _new_id()
        guides.append({"id": gid, "axis": axis, "position": pos, "color": color})
    canvas["guides"] = guides
    return guides


def normalize_background_mode(value) -> str:
    mode = str(value or "chroma").casefold().replace("_", "-").replace(" ", "-")
    if mode in ("onscreen", "on-screen"):
        return "onscreen"
    if mode == "image":
        return "image"
    return "chroma"


def is_onscreen_mode(canvas: dict[str, Any] | None) -> bool:
    return normalize_background_mode((canvas or {}).get("background_mode")) == "onscreen"


def is_interactive_overlay(canvas: dict[str, Any] | None) -> bool:
    return bool((canvas or {}).get("interactive"))


def button_appearance_mode(item: dict[str, Any] | None) -> str:
    """How an overlay button's lit look is chosen: ``press`` (binding) or ``state``."""
    style = (item or {}).get("style") if isinstance(item, dict) else None
    raw = ""
    if isinstance(style, dict):
        raw = str(style.get("appearance_mode") or "").strip().casefold()
    if not raw and isinstance(item, dict):
        raw = str(item.get("appearance_mode") or "").strip().casefold()
    return "state" if raw == "state" else "press"


def button_appearance_state_name(item: dict[str, Any] | None) -> str:
    """GEX state name when button appearance follows a state (ON/OFF fills)."""
    style = (item or {}).get("style") if isinstance(item, dict) else None
    if isinstance(style, dict):
        name = str(style.get("appearance_state") or style.get("appearance_state_name") or "").strip()
        if name:
            return name
    if isinstance(item, dict):
        return str(item.get("appearance_state") or item.get("appearance_state_name") or "").strip()
    return ""


def canonical_widget_type(widget_type: str) -> str:
    if widget_type == "panel":
        return "shape"
    if widget_type == "axis_dial":
        return "axis_radial"
    return widget_type or "button"


def new_widget(widget_type: str, x: int = 40, y: int = 40) -> dict[str, Any]:
    widget_type = canonical_widget_type(widget_type)
    if widget_type not in WIDGET_TYPES:
        widget_type = "button"
    w, h = DEFAULT_SIZES[widget_type]
    item = {
        "id": _new_id(),
        "type": widget_type,
        "x": int(x),
        "y": int(y),
        "w": int(w),
        "h": int(h),
        "z": 0,
        "rotation": 0,
        "label": DEFAULT_LABELS.get(widget_type, ""),
        "visible": True,
        "visibility": default_visibility(),
        "group": "",
        "style": default_style(widget_type),
        "binding": default_binding(1),
        "binding_y": default_binding(2),
        "bindings": {},
        "points": [],
        "series": [],
        "keys": [],
        "stats": [],
    }
    if widget_uses_series(widget_type):
        item["series"] = [default_graph_series(0)]
    if widget_type == "sys_stats":
        item["stats"] = [default_stat_entry(0, (item["style"] or {}).get("stat") or "time")]
    if widget_type == "input_display":
        from .input_display import DEFAULT_PRESET, default_widget_keys, preset_mouse_graphic

        item["keys"] = default_widget_keys()
        item["style"]["input_preset"] = DEFAULT_PRESET
        item["style"]["mouse_graphic"] = preset_mouse_graphic(DEFAULT_PRESET)
    if widget_type == "stopwatch":
        item["binding"] = default_toggle_binding()
        item["binding_y"] = default_toggle_binding()
    if widget_type in SWITCH_WIDGET_TYPES:
        item["bindings"] = default_switch_bindings(widget_type)
    if widget_type == "shape":
        from .shapes import default_shape_points, normalize_shape_kind

        kind = normalize_shape_kind(item["style"].get("shape_kind"))
        item["points"] = default_shape_points(kind)
    return item


def profile_xml_path(profile=None) -> str | None:
    profile = profile or gremlin.shared_state.current_profile
    if profile is None:
        return None
    return getattr(profile, "profile_file", None) or getattr(profile, "_profile_fname", None)


def profile_display_name(profile=None) -> str:
    profile = profile or gremlin.shared_state.current_profile
    if profile is None:
        return "No profile"
    name = getattr(profile, "name", None) or getattr(profile, "_profile_name", None)
    if name:
        return str(name)
    path = profile_xml_path(profile)
    if path:
        return os.path.splitext(os.path.basename(path))[0]
    return "Unsaved profile"


def overlay_path_for_profile(profile=None) -> str | None:
    """Optional sidecar JSON next to the profile XML (fallback / export)."""
    fname = profile_xml_path(profile)
    if not fname:
        return None
    return gremlin.util.swap_ext(fname, "overlay.json")


def _same_profile_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    try:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    except Exception:
        return str(left).casefold() == str(right).casefold()


def _overlay_payload_has_content(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    pages = data.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if isinstance(page, dict) and page.get("widgets"):
                return True
    return bool(data.get("widgets"))


class OverlayScene(QtCore.QObject):
    """Versioned overlay layout: pages of canvas + widgets. canvas/widgets alias the active page."""

    changed = Signal()
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages: list[dict[str, Any]] = []
        self.active_page_id: str | None = None
        self.canvas: dict[str, Any] = {}
        self.widgets: list[dict[str, Any]] = []
        self.selected_ids: list[str] = []
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._suspend = 0
        self._path: str | None = None
        self._profile_key: str | None = None
        self._dirty = False
        self._save_later_pending = False
        self._sorted_cache: list[dict[str, Any]] | None = None
        self._reset_default_pages(emit=False)

    def _reset_default_pages(self, emit: bool = True):
        page = default_page("Overlay")
        self.pages = [page]
        self.active_page_id = page["id"]
        self._sync_active_aliases()
        self.selected_ids = []
        if emit:
            self._emit()
            self.selection_changed.emit()

    def _sync_active_aliases(self):
        page = self.active_page()
        if page is None:
            page = default_page("Overlay")
            self.pages = [page]
            self.active_page_id = page["id"]
        self.canvas = page["canvas"]
        self.widgets = page["widgets"]
        self._sorted_cache = None

    def _set_active_widgets(self, widgets: list[dict[str, Any]]):
        page = self.active_page()
        if page is None:
            self.widgets = widgets
            return
        page["widgets"] = widgets
        self.widgets = widgets

    def _normalize_canvas(self, raw) -> dict[str, Any]:
        canvas = default_canvas()
        if isinstance(raw, dict):
            canvas.update(raw)
        canvas["background_mode"] = normalize_background_mode(canvas.get("background_mode"))
        canvas["toggle_binding"] = normalize_toggle_binding(canvas.get("toggle_binding"))
        normalize_guides(canvas)
        return canvas

    def _normalize_page(self, raw) -> dict[str, Any]:
        page = default_page()
        data = raw if isinstance(raw, dict) else {}
        page_id = str(data.get("id") or "").strip()
        if page_id:
            page["id"] = page_id
        name = str(data.get("name") or "").strip()
        if name:
            page["name"] = name
        page["visible"] = bool(data.get("visible", True))
        page["window_x"] = _optional_int(data.get("window_x"))
        page["window_y"] = _optional_int(data.get("window_y"))
        page["canvas"] = self._normalize_canvas(data.get("canvas"))
        page["widgets"] = [self._normalize_widget(item) for item in data.get("widgets") or [] if isinstance(item, dict)]
        return page

    def _legacy_page(self, data: dict[str, Any]) -> dict[str, Any]:
        page = default_page("Overlay")
        page["canvas"] = self._normalize_canvas(data.get("canvas"))
        page["widgets"] = [self._normalize_widget(item) for item in data.get("widgets") or [] if isinstance(item, dict)]
        page["visible"] = bool(data.get("visible", True))
        page["window_x"] = _optional_int(data.get("window_x"))
        page["window_y"] = _optional_int(data.get("window_y"))
        return page

    def page_by_id(self, page_id: str | None) -> dict[str, Any] | None:
        if not page_id:
            return None
        for page in self.pages:
            if page.get("id") == page_id:
                return page
        return None

    def active_page(self) -> dict[str, Any] | None:
        page = self.page_by_id(self.active_page_id)
        if page is not None:
            return page
        return self.pages[0] if self.pages else None

    def canvas_for(self, page_id: str | None = None) -> dict[str, Any]:
        page = self.page_by_id(page_id) if page_id else self.active_page()
        if page is None:
            if page_id:
                return default_canvas()
            return self.canvas if isinstance(self.canvas, dict) else default_canvas()
        return page["canvas"]

    def widgets_for(self, page_id: str | None = None) -> list[dict[str, Any]]:
        page = self.page_by_id(page_id) if page_id else self.active_page()
        if page is None:
            return [] if page_id else self.widgets
        return page["widgets"]

    def set_active_page(self, page_id: str | None, emit: bool = True) -> bool:
        page = self.page_by_id(page_id)
        if page is None:
            return False
        if self.active_page_id == page["id"] and self.canvas is page["canvas"] and self.widgets is page["widgets"]:
            return False
        self.active_page_id = page["id"]
        self._sync_active_aliases()
        self.selected_ids = []
        if emit:
            self._emit()
            self.selection_changed.emit()
        return True

    def _unique_page_name(self, base: str) -> str:
        base = str(base).strip() or "Page"
        names = {str(page.get("name") or "") for page in self.pages}
        if base not in names:
            return base
        index = 2
        while f"{base} {index}" in names:
            index += 1
        return f"{base} {index}"

    def add_page(self, name: str | None = None, activate: bool = True) -> dict[str, Any]:
        self.push_undo()
        page = default_page(self._unique_page_name(name or "Page"))
        self.pages.append(page)
        self._dirty = True
        if activate:
            self.set_active_page(page["id"], emit=True)
        else:
            self._emit()
        return page

    def duplicate_page(self, page_id: str | None = None, activate: bool = True) -> dict[str, Any] | None:
        src = self.page_by_id(page_id) or self.active_page()
        if src is None:
            return None
        self.push_undo()
        page = copy.deepcopy(src)
        page["id"] = _new_id()
        page["name"] = self._unique_page_name(f"{src.get('name') or 'Page'} copy")
        page["window_x"] = None
        page["window_y"] = None
        group_map: dict[str, str] = {}
        for item in page.get("widgets") or []:
            item["id"] = _new_id()
            old_group = str(item.get("group") or "").strip()
            if old_group:
                item["group"] = group_map.setdefault(old_group, _new_id())
        self.pages.append(page)
        self._dirty = True
        if activate:
            self.set_active_page(page["id"], emit=True)
        else:
            self._emit()
        return page

    def delete_page(self, page_id: str | None = None) -> bool:
        if len(self.pages) <= 1:
            return False
        page = self.page_by_id(page_id) or self.active_page()
        if page is None:
            return False
        index = self.pages.index(page)
        self.push_undo()
        self.pages = [item for item in self.pages if item is not page]
        neighbor = self.pages[min(index, len(self.pages) - 1)]
        self.active_page_id = neighbor["id"]
        self._sync_active_aliases()
        self.selected_ids = []
        self._dirty = True
        self._emit()
        self.selection_changed.emit()
        return True

    def reorder_pages(self, page_ids: list[str]) -> bool:
        by_id = {page["id"]: page for page in self.pages}
        ordered = [by_id[page_id] for page_id in page_ids if page_id in by_id]
        for page in self.pages:
            if page not in ordered:
                ordered.append(page)
        if [page["id"] for page in ordered] == [page["id"] for page in self.pages]:
            return False
        self.push_undo()
        self.pages = ordered
        self._dirty = True
        self._emit()
        return True

    def rename_page(self, name: str, page_id: str | None = None) -> bool:
        page = self.page_by_id(page_id) or self.active_page()
        if page is None:
            return False
        label = str(name).strip() or page.get("name") or "Overlay"
        if page.get("name") == label:
            return False
        page["name"] = label
        self._dirty = True
        self._emit()
        # Persist immediately: activate/deactivate can reload the profile sidecar
        # and would otherwise wipe an in-memory-only rename.
        try:
            if profile_xml_path():
                self.save_to_profile()
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: page rename autosave failed: {err}")
        return True

    def set_page_visible(self, visible: bool, page_id: str | None = None) -> bool:
        page = self.page_by_id(page_id) or self.active_page()
        if page is None:
            return False
        flag = bool(visible)
        if bool(page.get("visible", True)) == flag:
            return False
        page["visible"] = flag
        self._dirty = True
        self._emit()
        return True

    def record_page_position(self, x: int, y: int, page_id: str | None = None, emit: bool = False):
        page = self.page_by_id(page_id) or self.active_page()
        if page is None:
            return
        xi, yi = int(x), int(y)
        if page.get("window_x") == xi and page.get("window_y") == yi:
            return
        page["window_x"] = xi
        page["window_y"] = yi
        self._dirty = True
        if emit:
            self._emit()

    def reset_page_position(self, page_id: str | None = None, emit: bool = True):
        page = self.page_by_id(page_id) or self.active_page()
        if page is None:
            return
        page["window_x"] = None
        page["window_y"] = None
        canvas = page.get("canvas") if isinstance(page.get("canvas"), dict) else None
        if canvas is not None and is_onscreen_mode(canvas):
            canvas["monitor_index"] = 0
            canvas["monitor_name"] = ""
        self._dirty = True
        if emit:
            self._emit()

    def to_dict(self) -> dict[str, Any]:
        self._sync_active_aliases()
        return {
            "version": SCENE_VERSION,
            "active_page_id": self.active_page_id,
            "pages": copy.deepcopy(self.pages),
        }

    def from_dict(self, data: dict[str, Any] | None):
        data = data or {}
        raw_pages = data.get("pages")
        if isinstance(raw_pages, list) and raw_pages:
            pages = [self._normalize_page(raw) for raw in raw_pages]
        elif data.get("canvas") is not None or data.get("widgets") is not None:
            pages = [self._legacy_page(data)]
        else:
            pages = [default_page("Overlay")]
        seen: set[str] = set()
        for page in pages:
            pid = str(page.get("id") or "")
            if not pid or pid in seen:
                page["id"] = _new_id()
            seen.add(page["id"])
        self.pages = pages or [default_page("Overlay")]
        active = data.get("active_page_id")
        if not self.page_by_id(active):
            active = self.pages[0]["id"]
        self.active_page_id = active
        self._sync_active_aliases()
        self.selected_ids = [wid for wid in self.selected_ids if self.widget_by_id(wid)]
        self._emit()
        self.selection_changed.emit()

    def _normalize_widget(self, raw: dict[str, Any]) -> dict[str, Any]:
        from .shapes import default_shape_points, normalize_shape_kind, normalize_shape_points

        widget_type = canonical_widget_type(raw.get("type", "button"))
        item = new_widget(widget_type)
        item.update(
            {
                k: raw[k]
                for k in item.keys()
                if k in raw and k not in ("style", "binding", "binding_y", "bindings", "points", "visibility", "series", "keys", "stats")
            }
        )
        style = default_style(widget_type)
        style.update(raw.get("style") or {})
        item["style"] = style
        item["visibility"] = normalize_visibility(raw.get("visibility"))
        item["series"] = normalize_graph_series(raw.get("series") if widget_uses_series(widget_type) else [])
        if widget_uses_series(widget_type) and not item["series"]:
            item["series"] = [default_graph_series(0)]
        if widget_type == "sys_stats":
            item["stats"] = normalize_stat_series(raw.get("stats") if "stats" in raw else None, style.get("stat") or "time")
        else:
            item["stats"] = []
        if widget_type == "input_display":
            from .input_display import DEFAULT_PRESET, default_widget_keys, normalize_input_preset, normalize_mouse_graphic

            item["keys"] = normalize_overlay_keys(raw.get("keys") if "keys" in raw else item.get("keys") or default_widget_keys())
            style["input_preset"] = normalize_input_preset(style.get("input_preset") or DEFAULT_PRESET)
            style["mouse_graphic"] = normalize_mouse_graphic(style.get("mouse_graphic"))
        else:
            item["keys"] = []
        item["binding"], item["binding_y"] = self._normalize_bindings(widget_type, raw)
        if widget_type == "stopwatch":
            item["binding"] = normalize_toggle_binding(item.get("binding"))
            item["binding_y"] = normalize_toggle_binding(item.get("binding_y"))
        if widget_type in SWITCH_WIDGET_TYPES:
            item["bindings"] = normalize_switch_bindings(widget_type, raw)
            if widget_type in ("switch_4way", "switch_2way"):
                style["switch_appearance"] = normalize_switch_appearance(style.get("switch_appearance"))
        else:
            item["bindings"] = {}
        if widget_type == "shape":
            kind = normalize_shape_kind(style.get("shape_kind"))
            style["shape_kind"] = kind
            raw_points = raw.get("points")
            item["points"] = normalize_shape_points(raw_points, kind) if raw_points else default_shape_points(kind)
        elif widget_type == "button" and (style.get("shape_kind") or raw.get("points")):
            if style.get("shape_kind"):
                style["shape_kind"] = normalize_shape_kind(style.get("shape_kind"))
            kind = style.get("shape_kind") or "freeform"
            raw_points = raw.get("points")
            item["points"] = normalize_shape_points(raw_points, kind) if raw_points else default_shape_points(kind)
        if not item.get("id"):
            item["id"] = _new_id()
        from .widgets import normalize_rotation

        item["rotation"] = normalize_rotation(item.get("rotation"))
        return item

    def _normalize_bindings(self, widget_type: str, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        raw_x = dict(raw.get("binding") or {})
        raw_y = raw.get("binding_y")
        x = default_binding(1)
        x.update(raw_x)
        legacy_y_id = x.pop("input_id_y", None)
        legacy_y_inv = x.pop("invert_y", None)
        y = default_binding(2)
        if isinstance(raw_y, dict) and raw_y:
            y.update(raw_y)
            y.pop("input_id_y", None)
            y.pop("invert_y", None)
        elif widget_type in XY_WIDGET_TYPES:
            for key in ("source", "device_guid", "device_name", "vjoy_id", "state_name"):
                if x.get(key) not in (None, ""):
                    y[key] = x.get(key)
            y["input_type"] = "axis"
            y["input_id"] = int(legacy_y_id or y.get("input_id") or 2)
            y["invert"] = bool(legacy_y_inv)
        for binding in (x, y):
            if str(binding.get("source") or "").casefold() in ("keyboard", "keyboard/mouse", "mouse"):
                binding["source"] = "keyboard"
                binding["input_type"] = "keyboard"
            binding["keys"] = normalize_overlay_keys(binding.get("keys"))
        return x, y

    def snapshot(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def restore_snapshot(self, blob: str):
        self.from_dict(json.loads(blob))
        self._dirty = True

    def push_undo(self):
        self._undo.append(self.snapshot())
        if len(self._undo) > 60:
            self._undo = self._undo[-60:]
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self.snapshot())
        self.restore_snapshot(self._undo.pop())

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self.snapshot())
        self.restore_snapshot(self._redo.pop())

    def _emit(self):
        self._sorted_cache = None
        if self._suspend <= 0:
            self.changed.emit()

    def begin_edit(self):
        self.push_undo()
        self._suspend += 1

    def end_edit(self):
        self._suspend = max(0, self._suspend - 1)
        self._dirty = True
        self._emit()

    def widget_by_id(self, widget_id: str, page_id: str | None = None) -> dict[str, Any] | None:
        for item in self.widgets_for(page_id):
            if item["id"] == widget_id:
                return item
        return None

    def sorted_widgets(self, page_id: str | None = None) -> list[dict[str, Any]]:
        widgets = self.widgets_for(page_id)
        if page_id in (None, self.active_page_id):
            if self._sorted_cache is None:
                order = {id(widget): index for index, widget in enumerate(widgets)}
                self._sorted_cache = sorted(widgets, key=lambda w: (w.get("z", 0), order.get(id(w), 0)))
            return self._sorted_cache
        order = {id(widget): index for index, widget in enumerate(widgets)}
        return sorted(widgets, key=lambda w: (w.get("z", 0), order.get(id(w), 0)))

    def add_widget(self, widget_type: str, x: int = 40, y: int = 40, push_undo: bool = True) -> dict[str, Any]:
        if push_undo:
            self.push_undo()
        item = new_widget(widget_type, x, y)
        item["z"] = (max((w.get("z", 0) for w in self.widgets), default=-1) + 1)
        if self.canvas.get("snap_to_grid"):
            grid = max(1, int(self.canvas.get("grid_size", 8)))
            item["x"] = int(round(item["x"] / grid) * grid)
            item["y"] = int(round(item["y"] / grid) * grid)
        self.widgets.append(item)
        self.selected_ids = [item["id"]]
        self._dirty = True
        self._emit()
        self.selection_changed.emit()
        return item

    def convert_selected(self, widget_type: str) -> bool:
        """Change selected widgets to another type, keeping compatible settings.

        Returns False when nothing is selected so the caller can add a new widget.
        """
        widget_type = canonical_widget_type(widget_type)
        if widget_type not in WIDGET_TYPES:
            widget_type = "button"
        selected = self.selected_widgets()
        if not selected:
            return False
        if all(item.get("type") == widget_type for item in selected):
            return False
        self.push_undo()
        self._suspend += 1
        try:
            for item in selected:
                self._convert_widget(item, widget_type)
        finally:
            self._suspend = max(0, self._suspend - 1)
            self._dirty = True
            self._emit()
            self.selection_changed.emit()
        return True

    def convert_widgets_to(self, items: list[dict[str, Any]], widget_type: str) -> bool:
        widget_type = canonical_widget_type(widget_type)
        if widget_type not in WIDGET_TYPES:
            widget_type = "button"
        targets = [item for item in items if item and item.get("type") != widget_type]
        if not targets:
            return False
        self.push_undo()
        self._suspend += 1
        try:
            for item in targets:
                self._convert_widget(item, widget_type)
        finally:
            self._suspend = max(0, self._suspend - 1)
            self._dirty = True
            self._emit()
            self.selection_changed.emit()
        return True

    def _convert_widget(self, item: dict[str, Any], widget_type: str):
        old_type = item.get("type") or "button"
        if old_type == widget_type:
            return
        old_style = dict(item.get("style") or {})
        new_style = default_style(widget_type)
        new_style.update(old_style)
        old_size = DEFAULT_SIZES.get(old_type)
        new_size = DEFAULT_SIZES.get(widget_type)
        keep_size = old_type in ("shape", "panel") and widget_type == "button"
        if old_type == "button" and widget_type in ("shape", "panel"):
            from .shapes import button_uses_shape_path

            keep_size = button_uses_shape_path(item)
        if (
            not keep_size
            and old_size
            and new_size
            and (int(item.get("w") or 0), int(item.get("h") or 0)) == tuple(int(v) for v in old_size)
        ):
            item["w"], item["h"] = int(new_size[0]), int(new_size[1])
        item["type"] = widget_type
        item["style"] = new_style
        if widget_uses_series(widget_type):
            item["series"] = normalize_graph_series(item.get("series"))
            if not item["series"]:
                item["series"] = [default_graph_series(0)]
        if widget_type == "shape":
            from .shapes import default_shape_points, normalize_shape_kind

            kind = normalize_shape_kind(new_style.get("shape_kind"))
            new_style["shape_kind"] = kind
            if not item.get("points"):
                item["points"] = default_shape_points(kind)
        if old_type in ("shape", "panel") and widget_type == "button":
            from .shapes import normalize_shape_kind

            kind = normalize_shape_kind(new_style.get("shape_kind"))
            new_style["shape_kind"] = kind
            new_style["shape_closed"] = True
            new_style.setdefault("fill_on", default_style("button").get("fill_on"))
            new_style.setdefault("border_on", default_style("button").get("border_on"))
        if widget_type == "input_display":
            from .input_display import default_widget_keys, normalize_mouse_graphic

            item["keys"] = normalize_overlay_keys(item.get("keys") or default_widget_keys())
            new_style["mouse_graphic"] = normalize_mouse_graphic(new_style.get("mouse_graphic"))
            new_style.setdefault("show_keyboard", True)
            new_style.setdefault("show_mouse", True)
        if widget_type == "sys_stats":
            item["stats"] = normalize_stat_series(item.get("stats"), new_style.get("stat") or "time")
        old_kind = widget_binding_kind(old_type)
        new_kind = widget_binding_kind(widget_type)
        saved_binding = dict(item.get("binding") or {})
        saved_bindings = item.get("bindings") if isinstance(item.get("bindings"), dict) else None
        if widget_type in SWITCH_WIDGET_TYPES:
            previous = saved_bindings if old_kind == "switch" else None
            item["bindings"] = normalize_switch_bindings(widget_type, previous)
            if widget_type in ("switch_4way", "switch_2way"):
                new_style["switch_appearance"] = normalize_switch_appearance(new_style.get("switch_appearance"))
            if old_kind == "button":
                first = next(iter(switch_positions(widget_type)), None)
                if first:
                    item["bindings"][first] = normalize_toggle_binding(saved_binding)
        elif old_kind == "switch":
            item["bindings"] = {}
        if new_kind == "none" or old_kind == new_kind:
            return
        if {old_kind, new_kind} <= {"axis", "xy"}:
            binding = item.get("binding") or default_binding(1)
            if binding.get("input_type") != "axis":
                item["binding"] = default_binding(1)
            if new_kind == "xy":
                y = item.get("binding_y")
                if not isinstance(y, dict) or not y:
                    item["binding_y"] = default_binding(2)
            return
        item["binding"] = default_binding(1)
        item["binding_y"] = default_binding(2)
        if new_kind == "button":
            item["binding"]["input_type"] = "button"
            if widget_type == "stopwatch":
                item["binding"] = default_toggle_binding()
                item["binding_y"] = default_toggle_binding()
        elif new_kind == "hat":
            item["binding"]["input_type"] = "hat"

    def add_widgets(self, items: list[dict[str, Any]], push_undo: bool = True):
        if push_undo:
            self.push_undo()
        ids = []
        z = max((w.get("z", 0) for w in self.widgets), default=-1)
        for raw in items:
            item = self._normalize_widget(raw)
            item["id"] = _new_id()
            z += 1
            item["z"] = z
            self.widgets.append(item)
            ids.append(item["id"])
        self.selected_ids = ids
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def remove_selected(self):
        if not self.selected_ids:
            return
        self.push_undo()
        ids = set(self.selected_ids)
        self._set_active_widgets([w for w in self.widgets if w["id"] not in ids])
        self.selected_ids = []
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def clear_widgets(self):
        if not self.widgets:
            return
        self.push_undo()
        self._set_active_widgets([])
        self.selected_ids = []
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def duplicate_selected(self):
        if not self.selected_ids:
            return
        self.push_undo()
        copies = []
        group_map: dict[str, str] = {}
        grid = max(1, int(self.canvas.get("grid_size", 8)))
        for widget_id in list(self.selected_ids):
            src = self.widget_by_id(widget_id)
            if not src:
                continue
            item = copy.deepcopy(src)
            item["id"] = _new_id()
            item["x"] = int(item["x"]) + grid * 2
            item["y"] = int(item["y"]) + grid * 2
            item["z"] = (max((w.get("z", 0) for w in self.widgets), default=0) + 1)
            old_group = str(item.get("group") or "").strip()
            if old_group:
                item["group"] = group_map.setdefault(old_group, _new_id())
            self.widgets.append(item)
            copies.append(item["id"])
        self.selected_ids = copies
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def expand_group_ids(self, ids: list[str]) -> list[str]:
        """Include every widget that shares a group with any of the given ids."""
        seen: list[str] = []
        idset: set[str] = set()
        groups: set[str] = set()
        for widget_id in ids:
            if widget_id in idset:
                continue
            item = self.widget_by_id(widget_id)
            if not item:
                continue
            seen.append(widget_id)
            idset.add(widget_id)
            group = str(item.get("group") or "").strip()
            if group:
                groups.add(group)
        if not groups:
            return seen
        for item in self.widgets:
            group = str(item.get("group") or "").strip()
            if group in groups and item["id"] not in idset:
                seen.append(item["id"])
                idset.add(item["id"])
        return seen

    def group_selected(self) -> bool:
        ids = list(self.selected_ids)
        if len(ids) < 2:
            return False
        self.push_undo()
        gid = _new_id()
        for widget_id in ids:
            item = self.widget_by_id(widget_id)
            if item:
                item["group"] = gid
        self._dirty = True
        self._emit()
        self.selection_changed.emit()
        return True

    def ungroup_selected(self):
        ids = self.expand_group_ids(list(self.selected_ids))
        if not ids:
            return
        self.push_undo()
        for widget_id in ids:
            item = self.widget_by_id(widget_id)
            if item:
                item["group"] = ""
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def set_selection(self, ids: list[str], additive: bool = False):
        ids = [i for i in ids if self.widget_by_id(i)]
        if additive:
            merged = list(self.selected_ids)
            for i in ids:
                if i in merged:
                    merged.remove(i)
                else:
                    merged.append(i)
            self.selected_ids = merged
        else:
            self.selected_ids = ids
        self.selection_changed.emit()

    def primary_selection(self) -> dict[str, Any] | None:
        if not self.selected_ids:
            return None
        return self.widget_by_id(self.selected_ids[-1])

    def bring_forward(self):
        self._shift_z_order(1)

    def send_backward(self):
        self._shift_z_order(-1)

    def _shift_z_order(self, delta: int):
        """Move selected widgets one paint-order step without hopping other selected items."""
        if not self.selected_ids:
            return
        selected = set(self.selected_ids)
        ordered = self.sorted_widgets()
        if len(ordered) < 2:
            return
        moved = False
        if delta > 0:
            for i in range(len(ordered) - 2, -1, -1):
                if ordered[i]["id"] in selected and ordered[i + 1]["id"] not in selected:
                    ordered[i], ordered[i + 1] = ordered[i + 1], ordered[i]
                    moved = True
        else:
            for i in range(1, len(ordered)):
                if ordered[i]["id"] in selected and ordered[i - 1]["id"] not in selected:
                    ordered[i], ordered[i - 1] = ordered[i - 1], ordered[i]
                    moved = True
        if not moved:
            return
        self.push_undo()
        for z, item in enumerate(ordered):
            item["z"] = z
        self._set_active_widgets(ordered)
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def hit_test(self, x: float, y: float, page_id: str | None = None) -> dict[str, Any] | None:
        from .widgets import widget_contains_point

        for item in reversed(self.sorted_widgets(page_id)):
            if not item.get("visible", True):
                continue
            if widget_contains_point(item, x, y):
                return item
        return None

    def widgets_in_rect(self, x: float, y: float, w: float, h: float) -> list[str]:
        from .widgets import widget_rotated_bounds

        x2, y2 = x + w, y + h
        x, x2 = min(x, x2), max(x, x2)
        y, y2 = min(y, y2), max(y, y2)
        ids = []
        for item in self.widgets:
            bounds = widget_rotated_bounds(item)
            if bounds.right() >= x and bounds.left() <= x2 and bounds.bottom() >= y and bounds.top() <= y2:
                ids.append(item["id"])
        return ids

    def snap_value(self, value: float) -> int:
        if not self.canvas.get("snap_to_grid"):
            return int(round(value))
        grid = max(1, int(self.canvas.get("grid_size", 8)))
        return int(round(value / grid) * grid)

    def guide_by_id(self, guide_id: str) -> dict[str, Any] | None:
        for guide in self.canvas.get("guides") or []:
            if guide.get("id") == guide_id:
                return guide
        return None

    def add_guide(self, axis: str, position: float = 0.5, color: str | None = None) -> dict[str, Any]:
        self.push_undo()
        axis = "h" if str(axis).casefold().startswith("h") else "v"
        pos = max(0.0, min(1.0, float(position)))
        existing = [float(g.get("position") or 0) for g in (self.canvas.get("guides") or []) if g.get("axis") == axis]
        if any(abs(pos - other) < 0.005 for other in existing):
            for candidate in (0.25, 0.75, 0.33, 0.67, 0.1, 0.9, 0.4, 0.6):
                if not any(abs(candidate - other) < 0.005 for other in existing):
                    pos = candidate
                    break
        guide = {
            "id": _new_id(),
            "axis": axis,
            "position": pos,
            "color": color or DEFAULT_GUIDE_COLOR,
        }
        self.canvas.setdefault("guides", []).append(guide)
        self._dirty = True
        self._emit()
        return guide

    def remove_guide(self, guide_id: str):
        guides = list(self.canvas.get("guides") or [])
        next_guides = [g for g in guides if g.get("id") != guide_id]
        if len(next_guides) == len(guides):
            return
        self.push_undo()
        self.canvas["guides"] = next_guides
        self._dirty = True
        self._emit()

    def update_guide(self, guide_id: str, **fields):
        guide = self.guide_by_id(guide_id)
        if not guide:
            return
        if "position" in fields:
            try:
                pos = float(fields["position"])
            except (TypeError, ValueError):
                pos = float(guide.get("position") or 0.5)
            if pos > 1.0:
                pos = pos / 100.0
            guide["position"] = max(0.0, min(1.0, pos))
        if "color" in fields and fields["color"]:
            guide["color"] = str(fields["color"])
        if "axis" in fields:
            axis = str(fields["axis"]).casefold()
            guide["axis"] = "h" if axis.startswith("h") else "v"
        self._dirty = True
        self._emit()

    def snap_geom_to_guides(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        x_edges: tuple[str, ...] | None = None,
        y_edges: tuple[str, ...] | None = None,
        mode: str = "move",
    ) -> tuple[float, float, float, float]:
        guides = self.canvas.get("guides") or []
        if not guides:
            return x, y, w, h
        cw = max(1.0, float(self.canvas.get("width") or 1280))
        ch = max(1.0, float(self.canvas.get("height") or 720))
        threshold = float(max(8, int(self.canvas.get("grid_size") or 8)))
        if x_edges is None:
            x_edges = ("left", "center", "right")
        if y_edges is None:
            y_edges = ("top", "center", "bottom")
        vertical = [float(g.get("position") or 0) * cw for g in guides if g.get("axis") == "v"]
        horizontal = [float(g.get("position") or 0) * ch for g in guides if g.get("axis") == "h"]

        def _best(current: dict[str, float], targets: list[float]):
            best_dist = threshold + 1.0
            best = None
            for name, value in current.items():
                for target in targets:
                    dist = abs(value - target)
                    if dist < best_dist:
                        best_dist = dist
                        best = (name, target)
            return best

        x_map = {}
        if "left" in x_edges:
            x_map["left"] = x
        if "center" in x_edges:
            x_map["center"] = x + w / 2.0
        if "right" in x_edges:
            x_map["right"] = x + w
        hit = _best(x_map, vertical) if vertical else None
        if hit:
            edge, target = hit
            if mode == "resize":
                if edge == "left":
                    right = x + w
                    x = target
                    w = max(8.0, right - x)
                elif edge == "right":
                    w = max(8.0, target - x)
                elif edge == "center":
                    x = target - w / 2.0
            else:
                if edge == "left":
                    x = target
                elif edge == "right":
                    x = target - w
                else:
                    x = target - w / 2.0

        y_map = {}
        if "top" in y_edges:
            y_map["top"] = y
        if "center" in y_edges:
            y_map["center"] = y + h / 2.0
        if "bottom" in y_edges:
            y_map["bottom"] = y + h
        hit = _best(y_map, horizontal) if horizontal else None
        if hit:
            edge, target = hit
            if mode == "resize":
                if edge == "top":
                    bottom = y + h
                    y = target
                    h = max(8.0, bottom - y)
                elif edge == "bottom":
                    h = max(8.0, target - y)
                elif edge == "center":
                    y = target - h / 2.0
            else:
                if edge == "top":
                    y = target
                elif edge == "bottom":
                    y = target - h
                else:
                    y = target - h / 2.0
        return x, y, w, h

    def snap_selection_to_guides(self):
        primary = self.primary_selection()
        if not primary:
            return
        nx, ny, nw, nh = self.snap_geom_to_guides(
            float(primary["x"]),
            float(primary["y"]),
            float(primary["w"]),
            float(primary["h"]),
            mode="move",
        )
        dx = int(round(nx - float(primary["x"])))
        dy = int(round(ny - float(primary["y"])))
        if dx == 0 and dy == 0:
            return
        for widget_id in self.selected_ids:
            item = self.widget_by_id(widget_id)
            if not item:
                continue
            item["x"] = int(item["x"]) + dx
            item["y"] = int(item["y"]) + dy

    def move_selected(self, dx: int, dy: int, snap: bool = True):
        if not self.selected_ids:
            return
        for widget_id in self.selected_ids:
            item = self.widget_by_id(widget_id)
            if not item:
                continue
            nx = item["x"] + dx
            ny = item["y"] + dy
            item["x"] = self.snap_value(nx) if snap else int(nx)
            item["y"] = self.snap_value(ny) if snap else int(ny)
        if snap:
            self.snap_selection_to_guides()
        self._dirty = True
        self._emit()

    def apply_widget_update(self, widget_id: str, **fields):
        item = self.widget_by_id(widget_id)
        if not item:
            return
        for key, value in fields.items():
            if key == "style":
                item["style"].update(value)
                if item.get("type") in ("switch_4way", "switch_2way") and "switch_appearance" in (value or {}):
                    item["style"]["switch_appearance"] = normalize_switch_appearance(
                        item["style"].get("switch_appearance")
                    )
                _refresh_font_scale_base(item, value)
            elif key in ("binding", "binding_y"):
                item.setdefault(key, default_binding()).update(value)
            elif key == "bindings" and isinstance(value, dict):
                current = dict(item.get("bindings") or {})
                for position, fields in value.items():
                    entry = normalize_toggle_binding(current.get(position))
                    if isinstance(fields, dict):
                        entry.update(fields)
                        entry = normalize_toggle_binding(entry)
                    current[position] = entry
                item["bindings"] = normalize_switch_bindings(item.get("type"), current)
            elif key == "visibility":
                item["visibility"] = normalize_visibility(value)
            elif key == "series":
                item["series"] = normalize_graph_series(value)
            elif key == "keys":
                item["keys"] = normalize_overlay_keys(value)
            elif key == "stats":
                item["stats"] = normalize_stat_series(value, (item.get("style") or {}).get("stat") or "time")
            elif key == "rotation":
                from .widgets import normalize_rotation

                item["rotation"] = normalize_rotation(value)
            else:
                item[key] = value
        self._dirty = True
        self._emit()

    def apply_widget_updates(self, ids: list[str], **fields):
        ids = [i for i in ids if self.widget_by_id(i)]
        if not ids:
            return
        if len(ids) == 1:
            self.apply_widget_update(ids[0], **fields)
            return
        self._suspend += 1
        try:
            for widget_id in ids:
                self.apply_widget_update(widget_id, **fields)
        finally:
            self._suspend = max(0, self._suspend - 1)
            self._dirty = True
            self._emit()

    def selected_widgets(self) -> list[dict[str, Any]]:
        items = []
        seen = set()
        for widget_id in self.selected_ids:
            if widget_id in seen:
                continue
            item = self.widget_by_id(widget_id)
            if item:
                items.append(item)
                seen.add(widget_id)
        return items

    def default_path(self) -> str | None:
        return overlay_path_for_profile()

    def belongs_to_profile(self, profile=None) -> bool:
        path = profile_xml_path(profile)
        if not path:
            return self._profile_key is None
        if not self._profile_key:
            return False
        return _same_profile_path(self._profile_key, path)

    def load_for_profile(self, profile=None) -> bool:
        profile = profile or gremlin.shared_state.current_profile
        self._undo.clear()
        self._redo.clear()
        self.selected_ids = []
        path = profile_xml_path(profile)
        self._profile_key = path
        self._path = overlay_path_for_profile(profile)
        data = None
        if profile is not None:
            try:
                # force=True: never trust a stale in-memory cache that predates
                # a page-rename autosave written by another code path.
                cfg = profile._readConfig(force=True) or {}
                candidate = cfg.get(OVERLAY_CONFIG_KEY)
                if isinstance(candidate, dict):
                    data = candidate
            except Exception as err:
                syslog.warning(f"OBS OVERLAY: profile overlay read failed: {err}")
        sidecar = self._read_sidecar(self._path)
        if _overlay_payload_has_content(sidecar) and not _overlay_payload_has_content(data):
            data = sidecar
            if profile is not None and isinstance(data, dict):
                try:
                    profile._setConfig(OVERLAY_CONFIG_KEY, data)
                except Exception:
                    pass
        if isinstance(data, dict) and (data.get("pages") or data.get("widgets") or data.get("canvas")):
            self.from_dict(data)
            self._dirty = False
            self._undo.clear()
            self._redo.clear()
            return True
        # No stored layout. If the profile path is temporarily missing but we still
        # have unsaved edits (e.g. a page rename), keep them instead of wiping.
        if not path and self._dirty and self.pages:
            return False
        self._reset_default_pages(emit=True)
        self._dirty = False
        return False

    def load(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.from_dict(data)
            self._dirty = True
            self._undo.clear()
            self._redo.clear()
            return True
        except Exception as err:
            syslog.error(f"OBS OVERLAY: failed to load layout {path}: {err}")
            return False

    def save(self, path: str | None = None) -> bool:
        if path:
            return self._write_sidecar(path, self.to_dict())
        return self.save_to_profile()

    def save_to_profile(self, profile=None, dest_xml: str | None = None) -> bool:
        profile = profile or gremlin.shared_state.current_profile
        path = dest_xml or profile_xml_path(profile)
        if not path:
            syslog.warning("OBS OVERLAY: save the GEX profile first so the overlay can be stored with it")
            return False
        data = self.to_dict()
        # Merge into the profile JSON on disk. Avoid profile._setConfig here:
        # it asserts UI thread and can fail during tab-switch / nested Qt events,
        # which previously left widgets unsaved.
        ok = self._persist_files(path, data)
        if ok:
            self._profile_key = path
            self._path = gremlin.util.swap_ext(path, "overlay.json")
            if profile is not None and getattr(profile, "_config_data_read", False):
                cfg = getattr(profile, "_config_data", None)
                if isinstance(cfg, dict):
                    cfg[OVERLAY_CONFIG_KEY] = copy.deepcopy(data)
            syslog.info(f"OBS OVERLAY: saved layout {gremlin.util.toUrl(self._path)}")
        return ok

    def save_later(self):
        """Persist after the current Qt event finishes. Never call save() from hideEvent."""
        if not gremlin.util.is_ui_thread():
            gremlin.util.InvokeUiMethod(self.save_later)
            return
        if self._save_later_pending:
            return
        self._save_later_pending = True
        QtCore.QTimer.singleShot(0, self._save_later_run)

    def _save_later_run(self):
        self._save_later_pending = False
        if not self._dirty:
            return
        try:
            self.save_to_profile()
        except Exception:
            pass

    def save_owned(self) -> bool:
        """Persist this scene to the profile it was loaded from, even after a switch."""
        if not self._profile_key:
            return False
        current = profile_xml_path()
        if current and _same_profile_path(current, self._profile_key):
            return self.save_to_profile()
        return self._persist_files(self._profile_key, self.to_dict())

    def _write_sidecar(self, path: str, data: dict[str, Any]) -> bool:
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            return True
        except Exception as err:
            syslog.error(f"OBS OVERLAY: failed to save layout {path}: {err}")
            return False

    def _read_sidecar(self, path: str | None) -> dict[str, Any] | None:
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: failed to load sidecar {path}: {err}")
            return None

    def _persist_files(self, profile_xml: str, data: dict[str, Any]) -> bool:
        config_path = gremlin.util.swap_ext(profile_xml, "json")
        merged: dict[str, Any] | None = {}
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle) or {}
                if not isinstance(loaded, dict):
                    syslog.error(f"OBS OVERLAY: profile config is not an object: {config_path}")
                    merged = None
                else:
                    merged = loaded
            except Exception as err:
                syslog.error(f"OBS OVERLAY: could not merge overlay into {config_path}: {err}")
                merged = None
        wrote_config = False
        if merged is not None:
            merged[OVERLAY_CONFIG_KEY] = data
            try:
                folder = os.path.dirname(config_path)
                if folder and not os.path.isdir(folder):
                    os.makedirs(folder, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(merged, handle, indent=4, sort_keys=True)
                wrote_config = True
            except Exception as err:
                syslog.error(f"OBS OVERLAY: failed to write profile overlay config {config_path}: {err}")
        sidecar_ok = self._write_sidecar(gremlin.util.swap_ext(profile_xml, "overlay.json"), data)
        if wrote_config or sidecar_ok:
            self._dirty = False
            return True
        return False

    @property
    def dirty(self) -> bool:
        return self._dirty
