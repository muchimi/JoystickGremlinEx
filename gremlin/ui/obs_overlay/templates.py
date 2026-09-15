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
import re

import gremlin.shared_state

from .model import new_widget


def _at(widget_type: str, x: int, y: int, w: int | None = None, h: int | None = None, **fields):
    item = new_widget(widget_type, x, y)
    if w is not None:
        item["w"] = w
    if h is not None:
        item["h"] = h
    for key, value in fields.items():
        if key == "style":
            item["style"].update(value)
        elif key in ("binding", "binding_y"):
            item.setdefault(key, {}).update(value)
        elif key == "bindings" and isinstance(value, dict):
            item.setdefault("bindings", {}).update(value)
        else:
            item[key] = value
    return item


def dual_stick_hud():
    """Left/right X/Y pads with a 1D axis bar under each stick."""
    group = "dual-stick-hud"
    stick = {"indicator_size": 16}
    bar = {"orientation": "horizontal", "show_label": False, "indicator_size": 10}
    items = [
        _at(
            "axis_stick_square",
            80,
            80,
            210,
            210,
            group=group,
            style={**stick, "axis_label_n": "F", "axis_label_s": "A", "axis_label_e": "R", "axis_label_w": "L"},
        ),
        _at("axis_bar", 80, 300, 210, 28, label="", group=group, style=bar),
        _at(
            "axis_stick_square",
            360,
            80,
            210,
            210,
            group=group,
            style={**stick, "axis_label_n": "U", "axis_label_s": "D", "axis_label_e": "R", "axis_label_w": "L"},
        ),
        _at("axis_bar", 360, 300, 210, 28, label="", group=group, style=bar),
    ]
    return items


def gamepad_controller():
    """Xbox-style pad silhouette; each control is independently bindable."""
    group = "gamepad"
    body = {"fill": "#2b313a", "border": "#111418", "border_width": 2.0, "opacity": 1.0}
    stick = {"show_axis_labels": False, "indicator_size": 14, "fill": "#161b22", "border": "#3a424c"}
    pill = {"shape": "pill", "font_size": 10, "fill": "#1a1f26", "fill_on": "#c44a2a", "border": "#5a221c"}
    trigger = {"orientation": "horizontal", "show_label": False, "indicator_size": 8, "fill": "#1a1f26", "border": "#5a221c"}
    face = {"shape": "circle", "font_size": 12, "fill": "#1a1f26", "border": "#3a424c"}
    items = [
        # Two hanging grips + a wider face so the outline reads as a controller, not a pill.
        _at("panel", 40, 176, 250, 260, group=group, style={**body, "corner_radius": 120}),
        _at("panel", 510, 176, 250, 260, group=group, style={**body, "corner_radius": 120}),
        _at("panel", 88, 72, 624, 228, group=group, style={**body, "corner_radius": 56}),
        # Analog triggers sit above digital bumpers, matching Xbox LT/RT then LB/RB.
        _at("axis_bar", 112, 40, 124, 24, label="LT", group=group, style=trigger),
        _at("axis_bar", 564, 40, 124, 24, label="RT", group=group, style=trigger),
        _at("button", 112, 80, 124, 26, label="LB", group=group, style=pill),
        _at("button", 564, 80, 124, 26, label="RB", group=group, style=pill),
        # Left stick (upper left) and d-pad (lower left).
        _at("axis_stick_circle", 116, 140, 132, 132, group=group, style=stick),
        _at("button", 160, 276, 44, 20, label="L3", group=group, style={**pill, "font_size": 9}),
        _at("hat", 144, 312, 100, 100, group=group, style={"show_axis_labels": False, "fill": "#161b22", "border": "#3a424c"}),
        # View / Menu in the center spine.
        _at("button", 332, 196, 52, 22, label="View", group=group, style={**pill, "font_size": 9}),
        _at("button", 416, 196, 52, 22, label="Menu", group=group, style={**pill, "font_size": 9}),
        # Right stick sits lower and inward, same as an Xbox pad.
        _at("axis_stick_circle", 392, 268, 120, 120, group=group, style=stick),
        _at("button", 430, 392, 44, 20, label="R3", group=group, style={**pill, "font_size": 9}),
    ]
    for label, x, y, color in (
        ("Y", 572, 118, "#c9a227"),
        ("X", 526, 164, "#2f5fad"),
        ("B", 618, 164, "#c42f2f"),
        ("A", 572, 210, "#2f8a44"),
    ):
        items.append(
            _at("button", x, y, 46, 46, label=label, group=group, style={**face, "fill_on": color})
        )
    return items


def throttle_pair():
    group = "throttles"
    left = _at("axis_bar", 40, 40, 36, 220, label="L", group=group, style={"orientation": "vertical"})
    right = _at("axis_bar", 88, 40, 36, 220, label="R", group=group, style={"orientation": "vertical", "fill_bar": "#3dff9a"})
    return [left, right]


TEMPLATES = (
    ("Dual-stick HUD", "Left/right sticks with a 1D axis bar under each", dual_stick_hud),
    ("Gamepad", "Xbox-style controller with independently bindable controls", gamepad_controller),
    ("Throttle pair", "Two vertical axis bars", throttle_pair),
)


def overlay_template_dir() -> str:
    """Global (not profile-specific) folder for user-saved overlay templates."""
    root = gremlin.shared_state.data_path
    if not root:
        root = os.path.join(os.path.expanduser("~"), "Joystick Gremlin Ex")
    path = os.path.join(root, "overlay_templates")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()) or "template"
    return cleaned[:80]


def _write_template_file(path: str, name: str, widgets: list) -> str:
    payload = {"name": (name or "").strip() or "template", "widgets": copy.deepcopy(widgets)}
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def save_user_template(name: str, widgets: list) -> str:
    folder = overlay_template_dir()
    path = os.path.join(folder, f"{_safe_filename(name)}.json")
    return _write_template_file(path, name.strip(), widgets)


def update_user_template(filename: str, widgets: list) -> str:
    """Overwrite a saved template file, keeping its display name."""
    path = os.path.join(overlay_template_dir(), os.path.basename(filename))
    name = os.path.splitext(os.path.basename(filename))[0]
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
            if isinstance(data, dict) and data.get("name"):
                name = str(data["name"])
        except Exception:
            pass
    return _write_template_file(path, name, widgets)


def delete_user_template(filename: str) -> bool:
    path = os.path.join(overlay_template_dir(), os.path.basename(filename))
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def list_user_templates() -> list[tuple[str, str, object, str]]:
    """Return (title, tip, factory, filename) entries for saved templates."""
    results: list[tuple[str, str, object, str]] = []
    try:
        names = sorted(os.listdir(overlay_template_dir()))
    except OSError:
        return results
    folder = overlay_template_dir()
    for fname in names:
        if not fname.lower().endswith(".json"):
            continue
        path = os.path.join(folder, fname)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        title = str(data.get("name") or os.path.splitext(fname)[0])
        widgets = data.get("widgets") or []
        if not isinstance(widgets, list):
            continue
        results.append((title, f"Saved template ({fname})", _make_factory(widgets), fname))
    return results


def _make_factory(widgets: list):
    snapshot = copy.deepcopy(widgets)

    def factory():
        return copy.deepcopy(snapshot)

    return factory
