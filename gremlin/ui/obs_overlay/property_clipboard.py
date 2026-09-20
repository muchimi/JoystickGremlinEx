# -*- coding: utf-8; -*-
#
# Copy / paste overlay widget properties (geometry, visibility, label, appearance).
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import copy
from typing import Any

from PySide6 import QtWidgets

from .blink import normalize_blink
from .model import default_style, normalize_visibility, widget_is_locked

PROPERTY_GROUPS = (
    ("geometry_position", "Geometry (position)"),
    ("geometry_size", "Geometry (size)"),
    ("visibility", "Visibility"),
    ("label", "Label"),
    ("appearance", "Appearance"),
)

LABEL_STYLE_KEYS = (
    "show_label",
    "show_current_mode",
    "font_family",
    "font_size",
    "font_bold",
    "font_italic",
    "font_underline",
    "font_strike",
    "font_shadow",
    "font_shadow_color",
    "font_shadow_angle",
    "font_shadow_distance",
    "font_shadow_spread",
    "font_shadow_size",
    "font_shadow_dx",
    "font_shadow_dy",
    "font_stroke_width",
    "font_stroke_color",
    "font_color",
    "label_offset_x",
    "label_offset_y",
)

# Type-specific identity / wiring — never paste these onto another widget.
_IDENTITY_STYLE_KEYS = {
    "shape_kind",
    "shape_closed",
    "input_preset",
    "mouse_graphic",
    "window_title",
    "window_exe",
    "remote_client_id",
    "streamdeck_device_id",
    "streamdeck_follow_page",
    "streamdeck_page",
    "stat",
    "font_scale_base",
}

_clipboard: dict[str, Any] | None = None


def has_property_clipboard() -> bool:
    return bool(_clipboard) and bool(_clipboard.get("groups"))


def clipboard_groups() -> list[str]:
    if not _clipboard:
        return []
    return list(_clipboard.get("groups") or [])


class PropertyGroupsDialog(QtWidgets.QDialog):
    def __init__(self, title: str, action: str, groups: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        hint = QtWidgets.QLabel("Choose which properties to include. Items that do not apply to the target widget are skipped.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        allowed = {key for key, _title in PROPERTY_GROUPS} if groups is None else set(groups)
        self._boxes: dict[str, QtWidgets.QCheckBox] = {}
        for key, label in PROPERTY_GROUPS:
            box = QtWidgets.QCheckBox(label)
            box.setChecked(key in allowed)
            box.setEnabled(key in allowed)
            self._boxes[key] = box
            layout.addWidget(box)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(action)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_groups(self) -> list[str]:
        return [key for key, box in self._boxes.items() if box.isChecked() and box.isEnabled()]


def copy_widget_properties(item: dict[str, Any] | None, groups: list[str]) -> bool:
    global _clipboard
    snapshot = collect_widget_properties(item, groups)
    if not snapshot:
        _clipboard = None
        return False
    _clipboard = snapshot
    return True


def collect_widget_properties(item: dict[str, Any] | None, groups: list[str]) -> dict[str, Any] | None:
    if not item or not groups:
        return None
    style = dict(item.get("style") or {})
    payload: dict[str, Any] = {"groups": list(groups)}
    if "geometry_position" in groups:
        payload["x"] = int(item.get("x") or 0)
        payload["y"] = int(item.get("y") or 0)
        payload["rotation"] = item.get("rotation") or 0
    if "geometry_size" in groups:
        payload["w"] = max(8, int(item.get("w") or 8))
        payload["h"] = max(8, int(item.get("h") or 8))
    if "visibility" in groups:
        payload["visible"] = bool(item.get("visible", True))
        payload["visibility"] = copy.deepcopy(normalize_visibility(item.get("visibility")))
    if "label" in groups:
        payload["label"] = str(item.get("label") or "")
        payload["label_style"] = {key: copy.deepcopy(style[key]) for key in LABEL_STYLE_KEYS if key in style}
    if "appearance" in groups:
        skip = set(LABEL_STYLE_KEYS) | _IDENTITY_STYLE_KEYS
        payload["appearance"] = {key: copy.deepcopy(value) for key, value in style.items() if key not in skip}
        payload["blink"] = copy.deepcopy(normalize_blink(item.get("blink")))
    return payload


def paste_widget_properties(item: dict[str, Any] | None, payload: dict[str, Any] | None = None, groups: list[str] | None = None) -> dict[str, Any]:
    """Return apply_widget_update fields for *item*. Unknown / inapplicable keys are omitted."""
    clip = payload if payload is not None else _clipboard
    if not item or not clip:
        return {}
    use = list(groups if groups is not None else (clip.get("groups") or []))
    fields: dict[str, Any] = {}
    locked = widget_is_locked(item)
    if "geometry_position" in use and not locked:
        if "x" in clip:
            fields["x"] = int(clip.get("x") or 0)
        if "y" in clip:
            fields["y"] = int(clip.get("y") or 0)
        if "rotation" in clip:
            fields["rotation"] = clip.get("rotation") or 0
    if "geometry_size" in use and not locked:
        if "w" in clip:
            fields["w"] = max(8, int(clip.get("w") or 8))
        if "h" in clip:
            fields["h"] = max(8, int(clip.get("h") or 8))
    if "visibility" in use:
        if "visible" in clip:
            fields["visible"] = bool(clip.get("visible", True))
        if "visibility" in clip:
            fields["visibility"] = copy.deepcopy(normalize_visibility(clip.get("visibility")))
    style_update: dict[str, Any] = {}
    allowed_style = set((item.get("style") or {}).keys()) | set(default_style(str(item.get("type") or "")).keys())
    if "label" in use:
        if "label" in clip:
            fields["label"] = str(clip.get("label") or "")
        for key, value in (clip.get("label_style") or {}).items():
            if key == "show_current_mode" and item.get("type") != "label":
                continue
            if key in allowed_style:
                style_update[key] = copy.deepcopy(value)
    if "appearance" in use:
        for key, value in (clip.get("appearance") or {}).items():
            if key in _IDENTITY_STYLE_KEYS or key in LABEL_STYLE_KEYS:
                continue
            if key in allowed_style:
                style_update[key] = copy.deepcopy(value)
        if "blink" in clip:
            fields["blink"] = copy.deepcopy(normalize_blink(clip.get("blink")))
    if style_update:
        fields["style"] = style_update
    return fields


def paste_clipboard_to_widgets(scene, items: list[dict[str, Any]], groups: list[str] | None = None) -> int:
    clip = _clipboard
    if not clip or not items:
        return 0
    updates: list[tuple[str, dict[str, Any]]] = []
    for item in items:
        fields = paste_widget_properties(item, clip, groups)
        if fields:
            updates.append((str(item.get("id") or ""), fields))
    if not updates:
        return 0
    scene.push_undo()
    scene._suspend += 1
    try:
        for widget_id, fields in updates:
            scene.apply_widget_update(widget_id, **fields)
    finally:
        scene._suspend = max(0, int(getattr(scene, "_suspend", 0) or 0) - 1)
        scene._dirty = True
        scene._emit()
    return len(updates)
