# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Live overlay touch / mouse → vJoy and GEX state writes."""

from __future__ import annotations

import logging
from typing import Any

from PySide6 import QtCore
from shiboken6 import Shiboken

from .bindings import (
    binding_for_axis,
    binding_source,
    read_widget_value,
    toggle_mode,
    toggle_state,
    vjoy_binding_writable,
    widget_accepts_touch,
    widget_needs_xy,
    write_axis,
    write_button,
    write_hat,
    write_switch_position,
)
from .model import is_interactive_overlay, switch_rest_position, widget_is_switch
from .widgets import value_from_point, widget_dirty_rect

syslog = logging.getLogger("system")
SPRING_TYPES = ("axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat")


class OverlayTouchHandler:
    """Tracks pointer grabs on the live overlay and writes vJoy / states."""

    def __init__(self, view):
        self.view = view
        self._grabs: dict[object, dict[str, Any]] = {}
        self._logged_ignore = False

    def enabled(self) -> bool:
        return bool(getattr(self.view, "touch_output", False)) and is_interactive_overlay(self.view.page_canvas)

    def _ignore(self, reason: str):
        if self._logged_ignore:
            return
        self._logged_ignore = True
        syslog.warning(
            f"OBS OVERLAY: touch ignored ({reason}). "
            "Check Interactive on the Overlay toolbar, then click the live overlay window (not the designer)."
        )

    def press(self, pointer_id, scene_pos: QtCore.QPointF) -> bool:
        if not self.enabled() or pointer_id in self._grabs:
            if not self.enabled():
                self._ignore("Interactive is off")
            return False
        item = self.view.scene.hit_test(scene_pos.x(), scene_pos.y(), self.view.page_id)
        if not item or not widget_accepts_touch(item):
            if item and not widget_accepts_touch(item):
                self._ignore(f"{item.get('type')} is not bound to vJoy or a state")
            return False
        if any(grab.get("item_id") == item["id"] for grab in self._grabs.values()):
            return False
        widget_type = item.get("type")
        grab = {"item_id": item["id"], "type": widget_type, "held": False}
        if widget_type == "button":
            binding = item.get("binding") or {}
            from .model import button_appearance_mode

            appearance_follows_press = button_appearance_mode(item) == "press"
            if binding_source(binding) == "state":
                if toggle_state(binding) is None:
                    return False
                grab["kind"] = "state"
                self._poke(item, read_widget_value(item))
            elif binding_source(binding) == "mode":
                if toggle_mode(binding) is None:
                    return False
                grab["kind"] = "mode"
                self._poke(item, read_widget_value(item))
            else:
                invert = bool(binding.get("invert"))
                down = not invert
                if not write_button(binding, down):
                    return False
                grab["kind"] = "button"
                grab["held"] = True
                grab["up_value"] = invert
                # State-driven look must not flash with the finger press.
                self._poke(item, True if appearance_follows_press else read_widget_value(item))
        elif widget_is_switch(widget_type):
            mapped = value_from_point(item, scene_pos.x(), scene_pos.y())
            position = mapped if isinstance(mapped, str) else (switch_rest_position(widget_type) or "")
            if not write_switch_position(item, position or None):
                return False
            grab["kind"] = "switch"
            grab["spring"] = widget_type in ("switch_4way", "switch_3way")
            grab["position"] = position
            self._poke(item, position)
        else:
            grab["kind"] = "value"
            grab["spring"] = widget_type in SPRING_TYPES
            self._apply_value(item, scene_pos)
        self._grabs[pointer_id] = grab
        return True

    def move(self, pointer_id, scene_pos: QtCore.QPointF) -> bool:
        grab = self._grabs.get(pointer_id)
        if not grab:
            return False
        item = self.view.scene.widget_by_id(grab["item_id"], self.view.page_id)
        if not item:
            return False
        if grab.get("kind") == "switch":
            mapped = value_from_point(item, scene_pos.x(), scene_pos.y())
            position = mapped if isinstance(mapped, str) else (switch_rest_position(item.get("type")) or "")
            if position == grab.get("position"):
                return True
            if not write_switch_position(item, position or None):
                return False
            grab["position"] = position
            self._poke(item, position)
            return True
        if grab.get("kind") != "value":
            return False
        self._apply_value(item, scene_pos)
        return True

    def release(self, pointer_id) -> bool:
        grab = self._grabs.pop(pointer_id, None)
        if not grab:
            return False
        item = self.view.scene.widget_by_id(grab["item_id"], self.view.page_id)
        try:
            if not item:
                return True
            if grab.get("kind") == "button" and grab.get("held"):
                write_button(item.get("binding"), bool(grab.get("up_value")))
                from .model import button_appearance_mode

                if button_appearance_mode(item) == "press":
                    self._poke(item, False)
                else:
                    self._poke(item, read_widget_value(item))
            elif grab.get("kind") == "switch":
                rest = switch_rest_position(item.get("type")) if grab.get("spring") else grab.get("position")
                write_switch_position(item, rest or None)
                self._poke(item, rest or "")
            elif grab.get("kind") == "value" and grab.get("spring"):
                self._spring(item)
            return True
        finally:
            self._unlock(grab.get("item_id"))

    def release_all(self):
        for pointer_id in list(self._grabs):
            self.release(pointer_id)

    def _apply_value(self, item: dict[str, Any], scene_pos: QtCore.QPointF):
        mapped = value_from_point(item, scene_pos.x(), scene_pos.y())
        widget_type = item.get("type")
        if widget_type == "hat":
            direction = mapped if isinstance(mapped, tuple) else (0, 0)
            write_hat(item.get("binding"), (int(direction[0]), int(direction[1])))
            self._poke(item, (int(direction[0]), int(direction[1])))
            return
        if widget_needs_xy(widget_type):
            x_val, y_val = mapped if isinstance(mapped, tuple) else (0.0, 0.0)
            x_bind = binding_for_axis(item, "x")
            y_bind = binding_for_axis(item, "y")
            if vjoy_binding_writable(x_bind):
                write_axis(x_bind, float(x_val))
            if vjoy_binding_writable(y_bind):
                write_axis(y_bind, float(y_val))
            self._poke(item, (float(x_val), float(y_val)))
            return
        axis = float(mapped) if isinstance(mapped, (int, float)) else 0.0
        write_axis(item.get("binding"), axis)
        self._poke(item, axis)

    def _spring(self, item: dict[str, Any]):
        widget_type = item.get("type")
        if widget_type == "hat":
            write_hat(item.get("binding"), (0, 0))
            self._poke(item, (0, 0))
            return
        if widget_needs_xy(widget_type):
            x_bind = binding_for_axis(item, "x")
            y_bind = binding_for_axis(item, "y")
            if vjoy_binding_writable(x_bind):
                write_axis(x_bind, 0.0)
            if vjoy_binding_writable(y_bind):
                write_axis(y_bind, 0.0)
            self._poke(item, (0.0, 0.0))

    def _poke(self, item: dict[str, Any], value):
        view = self.view
        if view is None or not Shiboken.isValid(view):
            return
        bus = getattr(view, "bus", None)
        if bus is not None:
            bus.poke(item.get("id"), value, lock=True)
        else:
            view.update(widget_dirty_rect(item).toRect())

    def _unlock(self, widget_id: str | None):
        bus = getattr(self.view, "bus", None)
        if bus is not None:
            bus.unlock(widget_id)
