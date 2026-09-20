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
import os
import uuid
from typing import Any

import gremlin.shared_state

from .model import default_style

COLOR_KEYS = (
    "fill",
    "fill_on",
    "border",
    "border_on",
    "indicator",
    "track",
    "fill_bar",
    "grid",
    "crosshair",
    "needle",
    "font_color",
    "axis_label_font_color",
)

BUILTIN_IDS = ("default", "touchosc", "green_clear")

TOUCHOSC_COLORS = {
    "fill": "#000000",
    "fill_on": "#ff0000",
    "border": "#ff0000",
    "border_on": "#ff4d4d",
    "indicator": "#ff0000",
    "track": "#000000",
    "fill_bar": "#ff0000",
    "grid": "#4d0000",
    "crosshair": "#ff3333",
    "needle": "#ff0000",
    "font_color": "#ff1a1a",
    "axis_label_font_color": "#ff1a1a",
}

GREEN_CLEAR_COLORS = {
    "fill": "#00000000",
    "fill_on": "#3dff9a",
    "border": "#3dff9a",
    "border_on": "#7dffb8",
    "indicator": "#3dff9a",
    "track": "#00000000",
    "fill_bar": "#3dff9a",
    "grid": "#2a8f5c",
    "crosshair": "#3dff9a",
    "needle": "#3dff9a",
    "font_color": "#3dff9a",
    "axis_label_font_color": "#3dff9a",
}


def palette_type(widget_type: str | None) -> str:
    if widget_type == "axis_dial":
        return "axis_radial"
    if widget_type == "panel":
        return "shape"
    return widget_type or "button"


def _coerce_palette_color(value: Any, fallback: Any = "#ffffff") -> Any:
    """Keep gradient dicts intact; normalize everything else to a hex string."""
    from .gradient import is_gradient, normalize_gradient

    if is_gradient(value):
        return normalize_gradient(value)
    if value in (None, ""):
        value = fallback
    if is_gradient(value):
        return normalize_gradient(value)
    if isinstance(value, dict):
        # Unknown structured color — fall back rather than str(dict).
        value = fallback if not isinstance(fallback, dict) else "#ffffff"
    return str(value or "#ffffff")


def extract_colors(style: dict[str, Any] | None, widget_type: str | None = None) -> dict[str, Any]:
    """Extract palette color slots. Values are hex strings or gradient dicts."""
    style = style or {}
    fallback = default_style(palette_type(widget_type))
    colors = {}
    for key in COLOR_KEYS:
        colors[key] = _coerce_palette_color(style.get(key), fallback.get(key))
    return colors


def _builtin_palettes(widget_type: str) -> list[dict[str, Any]]:
    kind = palette_type(widget_type)
    return [
        {"id": "default", "label": "Default", "colors": extract_colors(default_style(kind), kind)},
        {"id": "touchosc", "label": "Touch OSC", "colors": dict(TOUCHOSC_COLORS)},
        {"id": "green_clear", "label": "Transparent green", "colors": dict(GREEN_CLEAR_COLORS)},
    ]


def palettes_path() -> str:
    root = gremlin.shared_state.data_path
    if not root:
        root = os.path.join(os.path.expanduser("~"), "Joystick Gremlin Ex")
    return os.path.join(root, "overlay_color_palettes.json")


def _load_store() -> dict[str, Any]:
    path = palettes_path()
    if not os.path.isfile(path):
        return {"version": 1, "palettes": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {"version": 1, "palettes": {}}
    if not isinstance(data, dict):
        return {"version": 1, "palettes": {}}
    palettes = data.get("palettes")
    if not isinstance(palettes, dict):
        data["palettes"] = {}
    return data


def _save_store(data: dict[str, Any]):
    path = palettes_path()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    payload = {"version": 1, "palettes": data.get("palettes") or {}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def list_builtin_palettes(widget_type: str) -> list[dict[str, Any]]:
    return [copy.deepcopy(item) for item in _builtin_palettes(palette_type(widget_type))]


def list_user_palettes(widget_type: str) -> list[dict[str, Any]]:
    kind = palette_type(widget_type)
    extras = []
    for raw in (_load_store().get("palettes") or {}).get(kind) or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        palette_id = str(raw["id"])
        if palette_id in BUILTIN_IDS:
            continue
        extras.append(
            {
                "id": palette_id,
                "label": str(raw.get("label") or "Saved palette"),
                "colors": extract_colors(raw.get("colors") or {}, kind),
            }
        )
    return extras


def list_palettes(widget_type: str) -> list[dict[str, Any]]:
    return list_builtin_palettes(widget_type) + list_user_palettes(widget_type)


def update_palette(widget_type: str, palette_id: str, colors: dict[str, Any], label: str | None = None) -> str:
    kind = palette_type(widget_type)
    palette_id = str(palette_id or uuid.uuid4())
    if palette_id in BUILTIN_IDS:
        return palette_id
    data = _load_store()
    palettes = data.setdefault("palettes", {})
    entries = list(palettes.get(kind) or [])
    payload = {"id": palette_id, "colors": extract_colors(colors, kind)}
    if label:
        payload["label"] = label
    replaced = False
    for index, raw in enumerate(entries):
        if isinstance(raw, dict) and str(raw.get("id")) == palette_id:
            if not payload.get("label") and raw.get("label"):
                payload["label"] = raw.get("label")
            entries[index] = payload
            replaced = True
            break
    if not replaced:
        entries.append(payload)
    palettes[kind] = entries
    _save_store(data)
    return palette_id


def add_palette(widget_type: str, colors: dict[str, Any]) -> str:
    return update_palette(widget_type, str(uuid.uuid4()), colors, label="Saved palette")


def delete_palette(widget_type: str, palette_id: str) -> bool:
    if palette_id in BUILTIN_IDS:
        return False
    kind = palette_type(widget_type)
    data = _load_store()
    palettes = data.setdefault("palettes", {})
    before = palettes.get(kind) or []
    after = [raw for raw in before if not (isinstance(raw, dict) and str(raw.get("id")) == palette_id)]
    if len(after) == len(before):
        return False
    palettes[kind] = after
    _save_store(data)
    return True
