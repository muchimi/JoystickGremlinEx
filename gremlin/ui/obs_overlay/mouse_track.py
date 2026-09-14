# -*- coding: utf-8; -*-
#
# Live mouse tracking for the overlay Mouse widget.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import time
from typing import Any

from PySide6 import QtGui

from gremlin.singleton_decorator import SingletonDecorator


def normalize_mouse_mode(value) -> str:
    mode = str(value or "vjoy").casefold()
    return "standard" if mode == "standard" else "vjoy"


def _mouse_max_px(style: dict[str, Any]) -> float:
    try:
        return max(1.0, float(style.get("mouse_max") or 250))
    except (TypeError, ValueError):
        return 250.0


def _mouse_idle_s(style: dict[str, Any]) -> float:
    try:
        return max(0.0, float(style.get("mouse_idle_s") if style.get("mouse_idle_s") is not None else 1.0))
    except (TypeError, ValueError):
        return 1.0


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


@SingletonDecorator
class MouseOverlayTracker:
    """Per-widget mouse origin / idle state for overlay Mouse widgets."""

    def __init__(self):
        self._states: dict[str, dict[str, Any]] = {}

    def retain(self, widget_ids: set[str] | None):
        if not widget_ids:
            self._states.clear()
            return
        for widget_id in list(self._states):
            if widget_id not in widget_ids:
                self._states.pop(widget_id, None)

    def sample(self, item: dict[str, Any] | None) -> tuple[float, float]:
        """Normalized overlay XY in -1..1 (Y up)."""
        if not item:
            return 0.0, 0.0
        widget_id = str(item.get("id") or "")
        if not widget_id:
            return 0.0, 0.0
        pos = QtGui.QCursor.pos()
        cx, cy = float(pos.x()), float(pos.y())
        now = time.monotonic()
        style = item.get("style") or {}
        mode = normalize_mouse_mode(style.get("mouse_mode"))
        max_px = _mouse_max_px(style)
        idle_s = _mouse_idle_s(style)
        state = self._states.get(widget_id)
        if state is None or state.get("mode") != mode:
            state = {
                "mode": mode,
                "origin": (cx, cy),
                "last": (cx, cy),
                "last_move": now,
                "sx": 0.0,
                "sy": 0.0,
            }
            self._states[widget_id] = state
        dx = cx - state["last"][0]
        dy = cy - state["last"][1]
        state["last"] = (cx, cy)
        if abs(dx) >= 0.5 or abs(dy) >= 0.5:
            state["last_move"] = now
        if mode == "standard":
            state["sx"] += dx
            state["sy"] += dy
            if idle_s > 0.0 and (now - state["last_move"]) >= idle_s:
                state["sx"] = 0.0
                state["sy"] = 0.0
            nx = _clamp(state["sx"] / max_px)
            ny = _clamp(state["sy"] / max_px)
        else:
            ox, oy = state["origin"]
            nx = _clamp((cx - ox) / max_px)
            ny = _clamp((cy - oy) / max_px)
        # Screen Y grows downward; overlay 2D widgets treat up as negative Y.
        return nx, -ny
