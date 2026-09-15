# -*- coding: utf-8; -*-
#
# Live axis history for the overlay Temporal graph widget.
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


def graph_period_s(style: dict[str, Any] | None) -> float:
    try:
        return max(0.5, min(120.0, float((style or {}).get("period_s") or 8.0)))
    except (TypeError, ValueError):
        return 8.0


def graph_value_range(style: dict[str, Any] | None) -> tuple[float, float]:
    try:
        lo = float((style or {}).get("value_min") if (style or {}).get("value_min") is not None else -1.0)
    except (TypeError, ValueError):
        lo = -1.0
    try:
        hi = float((style or {}).get("value_max") if (style or {}).get("value_max") is not None else 1.0)
    except (TypeError, ValueError):
        hi = 1.0
    if hi <= lo:
        hi = lo + 0.001
    return lo, hi


def graph_unit(style: dict[str, Any] | None) -> str:
    return str((style or {}).get("unit") or "").strip()


def graph_series_label(series: dict[str, Any] | None) -> str:
    series = series or {}
    custom = str(series.get("label") or "").strip()
    if custom:
        return custom
    source = str(series.get("source") or "physical").casefold()
    try:
        input_id = int(series.get("input_id") or 0)
    except (TypeError, ValueError):
        input_id = 0
    try:
        axis_name = ""
        if input_id:
            import gremlin.joystick_handling

            axis_name = gremlin.joystick_handling.get_axis_name(input_id) or ""
    except Exception:
        axis_name = ""
    if source == "vjoy":
        try:
            vjoy_id = int(series.get("vjoy_id") or 0)
        except (TypeError, ValueError):
            vjoy_id = 0
        device = f"vJoy {vjoy_id}" if vjoy_id else "vJoy"
    else:
        device = str(series.get("device_name") or "").strip() or "Physical"
    if axis_name:
        return f"{device} Axis {input_id} ({axis_name})"
    if input_id:
        return f"{device} Axis {input_id}"
    return f"{device} (not set)"


@SingletonDecorator
class GraphOverlayTracker:
    """Per-widget / per-series time history for overlay Temporal graph widgets."""

    def __init__(self):
        self._histories: dict[tuple[str, str], list[tuple[float, float]]] = {}

    def retain(self, keys: set[tuple[str, str]] | None):
        if not keys:
            self._histories.clear()
            return
        for ident in list(self._histories):
            if ident not in keys:
                self._histories.pop(ident, None)

    def sample(self, item: dict[str, Any] | None):
        """Append live samples and return a fingerprint so the overlay view redraws."""
        if not item:
            return ()
        widget_id = str(item.get("id") or "")
        if not widget_id:
            return ()
        from .bindings import binding_is_configured, read_axis

        now = time.monotonic()
        period = graph_period_s(item.get("style"))
        cutoff = now - period
        fingerprint = []
        for series in item.get("series") or []:
            if not isinstance(series, dict):
                continue
            series_id = str(series.get("id") or "")
            if not series_id:
                continue
            ident = (widget_id, series_id)
            hist = self._histories.setdefault(ident, [])
            if binding_is_configured(series):
                value = read_axis(series, series.get("input_id"), bool(series.get("invert")))
                hist.append((now, float(value)))
            while hist and hist[0][0] < cutoff:
                hist.pop(0)
            last = hist[-1][1] if hist else None
            fingerprint.append((series_id, last, len(hist)))
        return tuple(fingerprint)

    def history(self, widget_id: str, series_id: str) -> list[tuple[float, float]]:
        return self._histories.get((str(widget_id), str(series_id)), [])
