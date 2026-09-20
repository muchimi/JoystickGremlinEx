# -*- coding: utf-8; -*-
#
# Overlay widget blink: swap off/on appearance on a timer.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import time
from typing import Any

from gremlin.singleton_decorator import SingletonDecorator

_SWAP_KEYS = (
    ("fill", "fill_on"),
    ("border", "border_on"),
    ("image_path", "image_path_on"),
)


def default_blink() -> dict[str, Any]:
    return {
        "off_to_on": False,
        "on_to_off": False,
        "while_on": False,
        "while_off": False,
        "state": False,
        "state_id": "",
        "state_name": "",
        "state_when": "on",
        "mode": "permanent",
        "duration_s": 1.0,
        "hz": 2.0,
    }


def normalize_blink(raw) -> dict[str, Any]:
    blink = default_blink()
    if not isinstance(raw, dict):
        return blink
    blink["off_to_on"] = bool(raw.get("off_to_on"))
    blink["on_to_off"] = bool(raw.get("on_to_off"))
    blink["while_on"] = bool(raw.get("while_on"))
    blink["while_off"] = bool(raw.get("while_off"))
    blink["state"] = bool(raw.get("state"))
    blink["state_id"] = str(raw.get("state_id") or "")
    blink["state_name"] = str(raw.get("state_name") or "")
    when = str(raw.get("state_when") or "on").strip().casefold()
    blink["state_when"] = "off" if when == "off" else "on"
    mode = str(raw.get("mode") or "permanent").strip().casefold()
    blink["mode"] = "temporary" if mode in ("temporary", "temp", "burst", "once") else "permanent"
    try:
        blink["duration_s"] = max(0.05, min(30.0, float(raw.get("duration_s") or 1.0)))
    except (TypeError, ValueError):
        blink["duration_s"] = 1.0
    try:
        blink["hz"] = max(0.2, min(12.0, float(raw.get("hz") or 2.0)))
    except (TypeError, ValueError):
        blink["hz"] = 2.0
    return blink


def blink_is_armed(blink: dict[str, Any] | None) -> bool:
    blink = blink or {}
    return bool(
        blink.get("off_to_on")
        or blink.get("on_to_off")
        or blink.get("while_on")
        or blink.get("while_off")
        or blink.get("state")
    )


def value_is_on(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        key = value.strip().casefold()
        return bool(key) and key not in ("center", "off", "0", "none")
    if isinstance(value, (int, float)):
        return abs(float(value)) > 0.5
    if isinstance(value, (tuple, list)) and value:
        try:
            return any(abs(float(v)) > 0.15 for v in value)
        except (TypeError, ValueError):
            return False
    return False


def _gex_state_on(blink: dict[str, Any]) -> bool:
    from .bindings import find_overlay_state

    state = find_overlay_state(blink.get("state_id"), blink.get("state_name"))
    if state is None:
        return False
    try:
        from gremlin.ui import state_device

        on = bool(state_device.StateData().value(state.key))
    except Exception:
        on = False
    want_on = str(blink.get("state_when") or "on").casefold() != "off"
    return on if want_on else (not on)


def blink_phase_on(hz: float, now: float | None = None) -> bool:
    rate = max(0.2, float(hz or 2.0))
    stamp = time.monotonic() if now is None else float(now)
    return (stamp * rate) % 1.0 < 0.5


def _swap_appearance(item: dict[str, Any]) -> dict[str, Any]:
    style = dict(item.get("style") or {})
    for off_key, on_key in _SWAP_KEYS:
        style[off_key], style[on_key] = style.get(on_key), style.get(off_key)
    clone = dict(item)
    clone["style"] = style
    return clone


@SingletonDecorator
class OverlayBlinkTracker:
    """Tracks on/off edges and temporary blink bursts per widget."""

    def __init__(self):
        self._last_on: dict[str, bool] = {}
        self._until: dict[str, float] = {}
        self._phase: dict[str, bool] = {}

    def forget(self, widget_id: str | None):
        if not widget_id:
            return
        self._last_on.pop(widget_id, None)
        self._until.pop(widget_id, None)
        self._phase.pop(widget_id, None)

    def observe(self, item: dict[str, Any] | None, value) -> bool:
        """Update edge/burst state. True when the widget should repaint for blink."""
        if not item:
            return False
        widget_id = str(item.get("id") or "")
        blink = normalize_blink(item.get("blink"))
        if not widget_id or not blink_is_armed(blink):
            if widget_id:
                self.forget(widget_id)
            return False
        now = time.monotonic()
        on = value_is_on(value)
        previous = self._last_on.get(widget_id)
        if previous is None:
            self._last_on[widget_id] = on
        elif previous != on:
            if on and blink.get("off_to_on"):
                self._until[widget_id] = now + float(blink.get("duration_s") or 1.0)
            elif (not on) and blink.get("on_to_off"):
                self._until[widget_id] = now + float(blink.get("duration_s") or 1.0)
            self._last_on[widget_id] = on
        active = self._is_active(widget_id, blink, on, now)
        if not active:
            if self._phase.pop(widget_id, None) is not None:
                return True
            return False
        phase = blink_phase_on(float(blink.get("hz") or 2.0), now)
        if self._phase.get(widget_id) != phase:
            self._phase[widget_id] = phase
            return True
        return False

    def _is_active(self, widget_id: str, blink: dict[str, Any], on: bool, now: float) -> bool:
        if blink.get("while_on") and on:
            return True
        if blink.get("while_off") and not on:
            return True
        if blink.get("state") and _gex_state_on(blink):
            return True
        until = self._until.get(widget_id)
        if until is not None:
            if now <= until:
                return True
            self._until.pop(widget_id, None)
        if str(blink.get("mode") or "permanent") == "permanent":
            if blink.get("off_to_on") and on:
                return True
            if blink.get("on_to_off") and not on:
                return True
        return False

    def should_swap(self, item: dict[str, Any] | None, value) -> bool:
        if not item:
            return False
        widget_id = str(item.get("id") or "")
        blink = normalize_blink(item.get("blink"))
        if not widget_id or not blink_is_armed(blink):
            return False
        now = time.monotonic()
        on = value_is_on(value)
        if widget_id not in self._last_on:
            self._last_on[widget_id] = on
        if not self._is_active(widget_id, blink, on, now):
            return False
        return blink_phase_on(float(blink.get("hz") or 2.0), now)


def blink_paint_item(item: dict[str, Any] | None, value) -> dict[str, Any] | None:
    """Return the item, or a copy with off/on colors swapped for this blink frame."""
    if not item:
        return item
    if OverlayBlinkTracker().should_swap(item, value):
        return _swap_appearance(item)
    return item
