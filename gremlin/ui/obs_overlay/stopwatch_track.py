# -*- coding: utf-8; -*-
#
# Start / stop elapsed time for the overlay Stopwatch widget.
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

from gremlin.singleton_decorator import SingletonDecorator


def normalize_stopwatch_face(value) -> str:
    raw = str(value or "digital").casefold()
    return "analog" if raw in ("analog", "analogue", "watch", "clock") else "digital"


def normalize_stopwatch_format(value) -> str:
    raw = str(value or "mmss").casefold().replace(":", "").replace("-", "")
    if raw in ("hhmmss", "hms", "hours"):
        return "hhmmss"
    return "mmss"


def format_stopwatch(elapsed_s: float, fmt: str = "mmss") -> str:
    elapsed_s = max(0.0, float(elapsed_s or 0.0))
    total = int(elapsed_s)
    if normalize_stopwatch_format(fmt) == "hhmmss":
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    minutes = total // 60
    seconds = total % 60
    return f"{minutes:02d}:{seconds:02d}"


@SingletonDecorator
class StopwatchOverlayTracker:
    """Per-widget elapsed time; start/stop and reset follow overlay button bindings."""

    def __init__(self):
        self._state: dict[str, dict[str, Any]] = {}

    def retain(self, widget_ids: set[str] | None):
        if not widget_ids:
            self._state.clear()
            return
        for ident in list(self._state):
            if ident not in widget_ids:
                self._state.pop(ident, None)

    def elapsed(self, widget_id: str) -> float:
        return float((self._state.get(str(widget_id)) or {}).get("elapsed") or 0.0)

    def running(self, widget_id: str) -> bool:
        return bool((self._state.get(str(widget_id)) or {}).get("running"))

    def sample(self, item: dict[str, Any] | None):
        if not item:
            return (0, False)
        widget_id = str(item.get("id") or "")
        if not widget_id:
            return (0, False)
        from .bindings import binding_is_configured, read_toggle_active, toggle_follows_level

        now = time.monotonic()
        st = self._state.setdefault(
            widget_id,
            {
                "elapsed": 0.0,
                "running": False,
                "last": now,
                "start_prev": False,
                "reset_prev": False,
            },
        )
        reset_bind = item.get("binding_y")
        if binding_is_configured(reset_bind):
            reset_on = read_toggle_active(reset_bind)
            if reset_on and not st["reset_prev"]:
                st["elapsed"] = 0.0
                st["last"] = now
            st["reset_prev"] = reset_on

        start_bind = item.get("binding")
        if binding_is_configured(start_bind):
            active = read_toggle_active(start_bind)
            if toggle_follows_level(start_bind):
                st["running"] = bool(active)
            elif active and not st["start_prev"]:
                st["running"] = not st["running"]
            st["start_prev"] = bool(active)

        if st["running"]:
            st["elapsed"] = max(0.0, float(st["elapsed"]) + (now - float(st["last"])))
        st["last"] = now
        tenths = int(float(st["elapsed"]) * 10.0)
        return (tenths, bool(st["running"]))
