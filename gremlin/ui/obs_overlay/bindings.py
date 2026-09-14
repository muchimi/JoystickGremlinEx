# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
from typing import Any

from PySide6 import QtCore, QtWidgets
from shiboken6 import Shiboken

import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.util
from gremlin.singleton_decorator import SingletonDecorator

from .qt_guard import alive, on_ui

from .model import (
    NO_BINDING_WIDGET_TYPES,
    switch_binding,
    switch_positions,
    switch_rest_position,
    widget_is_switch,
)

syslog = logging.getLogger("system")

_logged_bind_errors: set[str] = set()


def _warn_once(key: str, message: str):
    if key in _logged_bind_errors:
        return
    _logged_bind_errors.add(key)
    try:
        syslog.warning(message)
    except RecursionError:
        pass


def current_profile_mode() -> str:
    """Active edit mode, or runtime mode while the profile is running."""
    try:
        import gremlin.shared_state

        return str(gremlin.shared_state.current_mode or "Default")
    except Exception:
        return "Default"


def profile_mode_choices() -> list[tuple[str, str]]:
    """(display name, mode name) pairs for the current profile."""
    try:
        import gremlin.shared_state

        profile = gremlin.shared_state.current_profile
        if profile is None:
            return [("Default", "Default")]
        pairs = list(profile.get_mode_display_list() or [])
        seen = {name for _label, name in pairs}
        for name in profile.get_modes() or []:
            if name and name not in seen:
                pairs.append((name, name))
                seen.add(name)
        return pairs or [("Default", "Default")]
    except Exception:
        return [("Default", "Default")]


def _set_profile_mode(mode_name: str) -> bool:
    name = str(mode_name or "").strip()
    if not name:
        return False
    try:
        import gremlin.event_handler

        gremlin.event_handler.EventHandler().set_mode(name)
        return True
    except Exception as err:
        _warn_once(f"write-mode:{name}", f"OBS OVERLAY: mode switch failed: {err}")
        return False


def _guid_key(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return gremlin.util.normalize_guid(value) or ""
    except Exception:
        return str(value).casefold()


def _device_for_binding(binding: dict[str, Any]):
    source = (binding.get("source") or "physical").casefold()
    if source == "vjoy":
        vjoy_id = int(binding.get("vjoy_id") or 0)
        if vjoy_id:
            return gremlin.joystick_handling.getDeviceFromVjoyId(vjoy_id)
    guid = binding.get("device_guid")
    if not guid:
        return None
    try:
        return gremlin.joystick_handling.getDevice(guid, show_error=False)
    except Exception:
        return None


def _invert(value: float, enabled: bool) -> float:
    if not enabled:
        return value
    return -value


def _proxy_axis_value(vjoy_id: int, axis_id: int) -> float | None:
    """vJoy output cache. DirectInput does not echo our own SetAxis writes."""
    try:
        axis = gremlin.joystick_handling.VJoyProxy()[int(vjoy_id)].axis(int(axis_id))
        if axis is None:
            return None
        return float(axis.value)
    except Exception:
        return None


def _proxy_hat_direction(vjoy_id: int, input_id: int) -> tuple[int, int] | None:
    try:
        hat = gremlin.joystick_handling.VJoyProxy()[int(vjoy_id)].hat(int(input_id))
        if hat is None:
            return None
        direction = hat.direction
        return (int(direction[0]), int(direction[1]))
    except Exception:
        return None


def read_axis(binding: dict[str, Any], axis_id: int | None, invert: bool = False) -> float:
    if not axis_id:
        return 0.0
    source = (binding.get("source") or "physical").casefold()
    try:
        if source == "vjoy":
            vjoy_id, _device = _vjoy_target(binding)
            if not vjoy_id:
                return 0.0
            value = _proxy_axis_value(vjoy_id, int(axis_id))
            if value is None:
                value = gremlin.joystick_handling.get_axis(vjoy_id, int(axis_id))
        else:
            guid = binding.get("device_guid")
            if not guid:
                return 0.0
            value = gremlin.joystick_handling.get_axis(guid, int(axis_id))
        if value is None:
            return 0.0
        return _invert(float(value), invert)
    except RecursionError:
        return 0.0
    except Exception as err:
        _warn_once(f"axis:{source}:{binding.get('device_guid')}:{axis_id}", f"OBS OVERLAY: axis read failed: {err}")
        return 0.0


def read_button(binding: dict[str, Any]) -> bool:
    source = (binding.get("source") or "physical").casefold()
    if source == "state":
        try:
            from gremlin.ui import state_device

            name = binding.get("state_name") or ""
            value = state_device.StateData().getValue(name)
            return bool(value)
        except Exception as err:
            _warn_once(f"state:{binding.get('state_name')}", f"OBS OVERLAY: state read failed: {err}")
            return False
    if source == "mode":
        name = str(binding.get("mode_name") or "").strip()
        return bool(name) and current_profile_mode() == name
    if source in ("keyboard", "keyboard/mouse", "mouse"):
        return read_keyboard(binding)
    input_id = int(binding.get("input_id") or 0)
    if not input_id:
        return False
    try:
        if source == "vjoy":
            vjoy_id = int(binding.get("vjoy_id") or 0)
            if not vjoy_id:
                return False
            return bool(gremlin.joystick_handling.get_button(vjoy_id, input_id))
        guid = binding.get("device_guid")
        if not guid:
            return False
        return bool(gremlin.joystick_handling.get_button(guid, input_id))
    except Exception as err:
        _warn_once(f"button:{source}:{binding.get('device_guid')}:{input_id}", f"OBS OVERLAY: button read failed: {err}")
        return False


_MOUSE_VK = {
    1: 0x01,  # Left
    2: 0x02,  # Right
    3: 0x04,  # Middle
    4: 0x06,  # Forward / XBUTTON2
    5: 0x05,  # Back / XBUTTON1
}


def overlay_keys_from_binding(binding: dict[str, Any] | None) -> list:
    from .model import deserialize_overlay_key

    keys = []
    for raw in (binding or {}).get("keys") or []:
        key = deserialize_overlay_key(raw)
        if key is not None:
            keys.append(key)
    return keys


def _key_is_down(key) -> bool:
    try:
        import gremlin.event_handler

        if gremlin.event_handler.EventListener().get_key_state(key):
            return True
    except Exception:
        pass
    try:
        import ctypes

        if bool(getattr(key, "is_mouse", False)) or int(getattr(key, "scan_code", 0) or 0) >= 0x1000:
            scan = int(getattr(key, "scan_code", 0) or 0)
            button = scan - 0x1000 if scan >= 0x1000 else int(getattr(getattr(key, "mouse_button", None), "value", 0) or 0)
            vk = _MOUSE_VK.get(button)
            if not vk:
                return False
            return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        vk = int(getattr(key, "virtual_code", 0) or 0)
        if not vk:
            from gremlin.keyboard import KeyMap

            vk = int(KeyMap.scan_code_to_virtual_code(int(key.scan_code), bool(key.is_extended)) or 0)
        if not vk:
            return False
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def read_keyboard(binding: dict[str, Any] | None) -> bool:
    keys = overlay_keys_from_binding(binding)
    if not keys:
        return False
    return all(_key_is_down(key) for key in keys)


def read_hat(binding: dict[str, Any]) -> tuple[int, int]:
    input_id = int(binding.get("input_id") or 0)
    if not input_id:
        return (0, 0)
    source = (binding.get("source") or "physical").casefold()
    try:
        if source == "vjoy":
            vjoy_id, _device = _vjoy_target(binding)
            if not vjoy_id:
                return (0, 0)
            proxy_dir = _proxy_hat_direction(vjoy_id, input_id)
            if proxy_dir is not None:
                return proxy_dir
            return gremlin.joystick_handling.get_hat_position(vjoy_id, input_id)
        guid = binding.get("device_guid")
        if not guid:
            return (0, 0)
        return gremlin.joystick_handling.get_hat_position(guid, input_id)
    except Exception as err:
        _warn_once(f"hat:{source}:{binding.get('device_guid')}:{input_id}", f"OBS OVERLAY: hat read failed: {err}")
        return (0, 0)


def widget_needs_xy(widget_type: str) -> bool:
    return widget_type in ("axis_stick_square", "axis_stick_circle", "axis_crosshair")


def binding_for_axis(item: dict[str, Any], axis: str = "x") -> dict[str, Any]:
    """X uses `binding`; Y uses `binding_y`, with legacy input_id_y fallback."""
    x_bind = dict(item.get("binding") or {})
    if axis != "y":
        return x_bind
    y_bind = item.get("binding_y")
    if isinstance(y_bind, dict) and (
        y_bind.get("device_guid")
        or y_bind.get("vjoy_id")
        or y_bind.get("input_id")
        or y_bind.get("state_name")
    ):
        return dict(y_bind)
    if x_bind.get("input_id_y"):
        legacy = dict(x_bind)
        legacy["input_id"] = x_bind.get("input_id_y")
        legacy["invert"] = bool(x_bind.get("invert_y"))
        return legacy
    return dict(y_bind or x_bind)


def binding_source(binding: dict[str, Any] | None) -> str:
    if not isinstance(binding, dict):
        return "physical"
    source = (binding.get("source") or "physical").casefold()
    kind = (binding.get("input_type") or "").casefold()
    if source == "mode" or kind == "mode":
        return "mode"
    if source == "state" or kind == "state":
        return "state"
    if source in ("keyboard", "keyboard/mouse", "mouse") or kind == "keyboard":
        return "keyboard"
    if source == "vjoy":
        return "vjoy"
    return "physical"


def binding_is_configured(binding: dict[str, Any] | None) -> bool:
    if not isinstance(binding, dict):
        return False
    source = (binding.get("source") or "physical").casefold()
    kind = (binding.get("input_type") or "").casefold()
    if source == "mode" or kind == "mode":
        return bool(str(binding.get("mode_name") or "").strip())
    if source == "state" or kind == "state":
        return bool(str(binding.get("state_name") or "").strip())
    if source in ("keyboard", "keyboard/mouse", "mouse") or kind == "keyboard":
        return bool(binding.get("keys"))
    try:
        return int(binding.get("input_id") or 0) > 0
    except (TypeError, ValueError):
        return False


def _vjoy_target(binding: dict[str, Any] | None) -> tuple[int, Any]:
    """Resolve a vJoy device from source=vjoy or a virtual device GUID."""
    binding = binding or {}
    try:
        vjoy_id = int(binding.get("vjoy_id") or 0)
    except (TypeError, ValueError):
        vjoy_id = 0
    device = None
    if vjoy_id:
        try:
            device = gremlin.joystick_handling.getDeviceFromVjoyId(vjoy_id)
        except Exception:
            device = None
    if device is None:
        guid = binding.get("device_guid")
        if guid:
            try:
                device = gremlin.joystick_handling.getDevice(guid, show_error=False)
            except Exception:
                device = None
    if vjoy_id > 0:
        return vjoy_id, device
    if device is not None:
        try:
            vjoy_id = int(getattr(device, "vjoy_id", 0) or 0)
        except (TypeError, ValueError):
            vjoy_id = 0
        if vjoy_id > 0 and getattr(device, "is_virtual", False):
            return vjoy_id, device
    if (binding.get("source") or "").casefold() == "vjoy":
        try:
            devices = gremlin.joystick_handling.vjoy_devices(connected_only=False) or []
        except Exception:
            devices = []
        if devices:
            device = devices[0]
            try:
                vjoy_id = int(getattr(device, "vjoy_id", 0) or 0)
            except (TypeError, ValueError):
                vjoy_id = 0
            if vjoy_id > 0:
                return vjoy_id, device
    return 0, None


def binding_is_writable(binding: dict[str, Any] | None) -> bool:
    """True when touch may write this binding (vJoy or GEX state, never physical)."""
    if not binding_is_configured(binding):
        return False
    if binding_source(binding) == "state":
        return True
    if binding_source(binding) == "mode":
        return True
    return vjoy_binding_writable(binding)


def vjoy_binding_writable(binding: dict[str, Any] | None) -> bool:
    if not binding_is_configured(binding):
        return False
    if binding_source(binding) in ("state", "mode"):
        return False
    vjoy_id, _device = _vjoy_target(binding)
    return vjoy_id > 0


def visibility_binding(condition: dict[str, Any] | None) -> dict[str, Any]:
    """Turn a widget visibility condition into a button-style binding for read_button."""
    cond = condition or {}
    kind = str(cond.get("kind") or "mode").casefold()
    if kind == "mode":
        return {"source": "mode", "mode_name": str(cond.get("mode_name") or ""), "input_type": "mode"}
    if kind == "state":
        return {"source": "state", "state_name": str(cond.get("state_name") or ""), "input_type": "state"}
    if kind == "keyboard":
        return {"source": "keyboard", "input_type": "keyboard", "keys": list(cond.get("keys") or [])}
    if kind == "vjoy":
        return {
            "source": "vjoy",
            "vjoy_id": cond.get("vjoy_id") or 0,
            "device_guid": cond.get("device_guid") or "",
            "input_id": cond.get("input_id") or 0,
            "input_type": "button",
        }
    return {
        "source": "physical",
        "device_guid": cond.get("device_guid") or "",
        "input_id": cond.get("input_id") or 0,
        "input_type": "button",
    }


def visibility_condition_configured(condition: dict[str, Any] | None) -> bool:
    return binding_is_configured(visibility_binding(condition))


def evaluate_visibility_condition(condition: dict[str, Any] | None) -> bool:
    if not visibility_condition_configured(condition):
        return False
    value = read_button(visibility_binding(condition))
    when = str((condition or {}).get("when") or "on").casefold()
    return (not value) if when == "off" else bool(value)


def widget_conditions_match(item: dict[str, Any] | None) -> bool:
    """True when the widget's visibility conditions currently pass (or none are set)."""
    if not item:
        return False
    vis = item.get("visibility") or {}
    conditions = [c for c in (vis.get("conditions") or []) if isinstance(c, dict)]
    configured = [c for c in conditions if visibility_condition_configured(c)]
    if not configured:
        return True
    results = [evaluate_visibility_condition(c) for c in configured]
    join = str(vis.get("join") or "all").casefold()
    if join == "any":
        return any(results)
    return all(results)


def widget_is_live_visible(item: dict[str, Any] | None) -> bool:
    """True when the widget should appear on the live overlay window."""
    if not item or not item.get("visible", True):
        return False
    return widget_conditions_match(item)


def widget_accepts_touch(item: dict[str, Any] | None) -> bool:
    if not item or not widget_is_live_visible(item):
        return False
    widget_type = item.get("type")
    if widget_type in NO_BINDING_WIDGET_TYPES:
        return False
    if widget_type == "stopwatch":
        return False
    if widget_type == "button":
        return binding_is_writable(item.get("binding"))
    if widget_type == "hat":
        return vjoy_binding_writable(item.get("binding"))
    if widget_is_switch(widget_type):
        return any(binding_is_writable(switch_binding(item, position)) for position in switch_positions(widget_type))
    if widget_needs_xy(widget_type):
        return vjoy_binding_writable(binding_for_axis(item, "x")) or vjoy_binding_writable(binding_for_axis(item, "y"))
    return vjoy_binding_writable(item.get("binding"))


def _clamp_axis(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def write_axis(binding: dict[str, Any] | None, value: float) -> bool:
    if not vjoy_binding_writable(binding):
        return False
    binding = binding or {}
    try:
        axis_id = int(binding.get("input_id") or 0)
    except (TypeError, ValueError):
        axis_id = 0
    vjoy_id, _device = _vjoy_target(binding)
    if axis_id <= 0 or vjoy_id <= 0:
        return False
    raw = _clamp_axis(value)
    if binding.get("invert"):
        raw = -raw
    try:
        gremlin.joystick_handling.VJoyProxy()[vjoy_id].axis(axis_id).value = raw
        return True
    except Exception as err:
        _warn_once(f"write-axis:{vjoy_id}:{axis_id}", f"OBS OVERLAY: axis write failed: {err}")
        return False


def write_button(binding: dict[str, Any] | None, pressed: bool) -> bool:
    if not binding_is_writable(binding):
        return False
    binding = binding or {}
    source = binding_source(binding)
    if source == "state":
        try:
            from gremlin.ui import state_device

            name = str(binding.get("state_name") or "").strip()
            if not name:
                return False
            state_device.StateData().setValue(name, bool(pressed), emit=True, force=True)
            return True
        except Exception as err:
            _warn_once(f"write-state:{binding.get('state_name')}", f"OBS OVERLAY: state write failed: {err}")
            return False
    if source == "mode":
        name = str(binding.get("mode_name") or "").strip()
        if not name:
            return False
        if pressed:
            return _set_profile_mode(name)
        fallback = str(gremlin.shared_state.previous_runtime_mode or "").strip()
        names = {choice[1] for choice in profile_mode_choices()}
        if not fallback or fallback == name or fallback not in names:
            fallback = next((choice[1] for choice in profile_mode_choices() if choice[1] != name), name)
        return _set_profile_mode(fallback)
    try:
        input_id = int(binding.get("input_id") or 0)
    except (TypeError, ValueError):
        input_id = 0
    vjoy_id, _device = _vjoy_target(binding)
    if vjoy_id <= 0 or input_id <= 0:
        return False
    try:
        gremlin.joystick_handling.VJoyProxy()[vjoy_id].button(input_id).is_pressed = bool(pressed)
        return True
    except Exception as err:
        _warn_once(f"write-button:{vjoy_id}:{input_id}", f"OBS OVERLAY: button write failed: {err}")
        return False


def toggle_state(binding: dict[str, Any] | None) -> bool | None:
    """Invert a GEX state. Returns the new raw value, or None if it did not write."""
    if binding_source(binding) != "state" or not binding_is_configured(binding):
        return None
    new_value = not read_button(binding or {})
    if write_button(binding, new_value):
        return new_value
    return None


def toggle_mode(binding: dict[str, Any] | None) -> bool | None:
    """Enter the bound mode, or leave it if it is already current."""
    if binding_source(binding) != "mode" or not binding_is_configured(binding):
        return None
    entering = not read_button(binding or {})
    if write_button(binding, entering):
        return entering
    return None


def _switch_position_pressed(binding: dict[str, Any] | None) -> bool:
    if not binding_is_configured(binding):
        return False
    pressed = read_button(binding or {})
    if (binding or {}).get("invert"):
        pressed = not pressed
    return bool(pressed)


def read_switch_position(item: dict[str, Any] | None) -> str:
    """Active switch slot, or the spring rest / empty string when none are pressed."""
    widget_type = (item or {}).get("type")
    rest = switch_rest_position(widget_type)
    for position in switch_positions(widget_type):
        if position == rest:
            continue
        if _switch_position_pressed(switch_binding(item, position)):
            return position
    if rest:
        center = switch_binding(item, rest)
        if binding_is_configured(center) and _switch_position_pressed(center):
            return rest
        return rest
    return ""


def write_switch_position(item: dict[str, Any] | None, position: str | None) -> bool:
    """Write one slot on (and the others off) for Interactive overlay use."""
    if not item:
        return False
    wrote = False
    for slot in switch_positions(item.get("type")):
        binding = switch_binding(item, slot)
        if not binding_is_writable(binding):
            continue
        invert = bool(binding.get("invert"))
        active = slot == position
        if not write_button(binding, (not active) if invert else active):
            continue
        wrote = True
    return wrote


def write_hat(binding: dict[str, Any] | None, direction: tuple[int, int]) -> bool:
    if not vjoy_binding_writable(binding):
        return False
    binding = binding or {}
    try:
        input_id = int(binding.get("input_id") or 0)
    except (TypeError, ValueError):
        input_id = 0
    vjoy_id, device = _vjoy_target(binding)
    if vjoy_id <= 0 or input_id <= 0:
        return False
    nx, ny = int(direction[0]), int(direction[1])
    if binding.get("invert"):
        nx = -nx
    if binding.get("invert_y"):
        ny = -ny
    try:
        hat_count = int(getattr(device, "hat_count", 0) or 0) if device is not None else 4
        if hat_count and not (0 < input_id <= hat_count):
            return False
        gremlin.joystick_handling.VJoyProxy()[vjoy_id].hat(input_id).direction = (nx, ny)
        return True
    except Exception as err:
        _warn_once(f"write-hat:{vjoy_id}:{input_id}", f"OBS OVERLAY: hat write failed: {err}")
        return False


def toggle_follows_level(binding: dict[str, Any] | None) -> bool:
    """True when overlay visibility should track the input (pressed=show, released=hide)."""
    return binding_source(binding) in ("state", "mode")


def read_toggle_active(binding: dict[str, Any] | None) -> bool:
    """True while the assigned toggle input is held / past threshold."""
    if not binding_is_configured(binding):
        return False
    binding = binding or {}
    kind = (binding.get("input_type") or "button").casefold()
    source = (binding.get("source") or "physical").casefold()
    invert = bool(binding.get("invert"))
    if source in ("state", "mode") or kind in ("state", "mode"):
        value = read_button(binding)
    elif kind == "axis":
        value = read_axis(binding, binding.get("input_id"), invert) >= 0.5
        invert = False
    elif kind == "hat":
        x, y = read_hat(binding)
        value = x != 0 or y != 0
    else:
        value = read_button(binding)
    return (not value) if invert else bool(value)


def _streamdeck_overlay_value(item: dict[str, Any]):
    """Fingerprint so overlay views redraw when the mirrored deck changes."""
    try:
        from gremlin.ui.streamdeck_device import StreamDeckBridge, normalize_page

        bridge = StreamDeckBridge()
        style = item.get("style") or {}
        device_id = bridge.resolve_overlay_device_id(str(style.get("streamdeck_device_id") or ""))
        follow = bool(style.get("streamdeck_follow_page", True))
        if follow:
            page = bridge.get_active_page(device_id) if device_id else 1
        else:
            page = normalize_page(style.get("streamdeck_page") or 1)
        held = tuple(sorted(bridge.held_slot_keys(device_id))) if device_id else ()
        connected = bool(device_id and device_id in bridge.devices)
        return (
            device_id,
            page,
            held,
            connected,
            bridge.overlay_generation(),
            bool(bridge.plugin_is_connected),
        )
    except Exception:
        return ("", 0, (), False, 0, False)


def _read_axis_bars(item: dict[str, Any]):
    from .model import axis_display_percent, series_is_centered

    fingerprint = []
    for series in item.get("series") or []:
        if not isinstance(series, dict):
            continue
        series_id = str(series.get("id") or "")
        if not series_id:
            continue
        if not binding_is_configured(series):
            fingerprint.append((series_id, None))
            continue
        raw = read_axis(series, series.get("input_id"), bool(series.get("invert")))
        percent = axis_display_percent(raw, series_is_centered(series))
        fingerprint.append((series_id, round(percent, 2)))
    return tuple(fingerprint)


def read_widget_value(item: dict[str, Any]):
    """Return the live value used by a widget: float, (x,y), bool, or hat tuple."""
    widget_type = item.get("type")
    binding = item.get("binding") or {}
    invert = bool(binding.get("invert"))
    if widget_type in ("label", "panel", "shape", "image"):
        if widget_type == "label" and (item.get("style") or {}).get("show_current_mode"):
            return current_profile_mode()
        return None
    if widget_type == "streamdeck":
        return _streamdeck_overlay_value(item)
    if widget_type == "axis_mouse":
        from .mouse_track import MouseOverlayTracker

        return MouseOverlayTracker().sample(item)
    if widget_type == "axis_graph":
        from .graph_track import GraphOverlayTracker

        return GraphOverlayTracker().sample(item)
    if widget_type == "axis_bars":
        return _read_axis_bars(item)
    if widget_type == "sys_stats":
        from .sys_stats import sample_counter_widget

        return sample_counter_widget(item)
    if widget_type == "stopwatch":
        from .stopwatch_track import StopwatchOverlayTracker

        return StopwatchOverlayTracker().sample(item)
    if widget_type == "input_display":
        from .input_display import KeyboardMouseTracker

        return KeyboardMouseTracker().sample(item)
    if widget_type == "button":
        from .model import button_appearance_mode, button_appearance_state_name

        if button_appearance_mode(item) == "state":
            name = button_appearance_state_name(item)
            if not name:
                return False
            try:
                from gremlin.ui import state_device

                return bool(state_device.StateData().getValue(name))
            except Exception as err:
                _warn_once(f"appearance_state:{name}", f"OBS OVERLAY: appearance state read failed: {err}")
                return False
        pressed = read_button(binding)
        return (not pressed) if invert else pressed
    if widget_type == "hat":
        x, y = read_hat(binding)
        if invert:
            x = -x
        if bool(binding.get("invert_y")):
            y = -y
        return (x, y)
    if widget_is_switch(widget_type):
        return read_switch_position(item)
    if widget_needs_xy(widget_type):
        x_bind = binding_for_axis(item, "x")
        y_bind = binding_for_axis(item, "y")
        x = read_axis(x_bind, x_bind.get("input_id"), bool(x_bind.get("invert")))
        y = read_axis(y_bind, y_bind.get("input_id"), bool(y_bind.get("invert")))
        return (x, y)
    return read_axis(binding, binding.get("input_id"), invert)


@SingletonDecorator
class OverlayValueBus(QtCore.QObject):
    """Live physical / vJoy / state values for overlay widgets.

    Steady 60 Hz DirectInput poll. Per-event UI callbacks are not used:
    HID packets from every device starve Qt's paint timer and look worse.
    """

    values_changed = QtCore.Signal(object)
    POLL_INTERVAL_MS = 16  # ~60 Hz

    def __init__(self):
        super().__init__()
        self._refcount = 0
        self._connected = False
        self._poll = QtCore.QTimer(self)
        self._poll.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._poll.setInterval(self.POLL_INTERVAL_MS)
        self._poll.timeout.connect(self.refresh)
        self._cache: dict[str, Any] = {}
        self._visible_cache: dict[str, bool] = {}
        self._locked: set[str] = set()
        self._scene_widgets: list[dict[str, Any]] = []
        self._streamdeck_hooked = False
        self._streamdeck_bridge = None
        self._refresh_queued = False
        self._emit_all = False
        app = QtWidgets.QApplication.instance()
        if app is not None and QtCore.QThread.currentThread() is not app.thread():
            self.moveToThread(app.thread())

    def attach(self, widgets: list[dict[str, Any]] | None = None):
        if widgets is not None:
            self._scene_widgets = widgets
        self._refcount += 1
        if self._refcount == 1:
            self._connect()
        self.refresh()

    def detach(self):
        self._refcount = max(0, self._refcount - 1)
        if self._refcount == 0:
            self._disconnect()

    def set_widgets(self, widgets: list[dict[str, Any]]):
        self._scene_widgets = widgets

    def _connect(self):
        if self._connected:
            return
        try:
            from gremlin.ui import state_device

            state_device.StateData().changed.connect(self.refresh)
        except Exception:
            pass
        try:
            import gremlin.event_handler

            el = gremlin.event_handler.EventListener()
            el.runtime_mode_changed.connect(self.refresh)
            el.edit_mode_changed.connect(self.refresh)
            el.profile_started.connect(self.refresh)
            el.profile_stop.connect(self.refresh)
        except Exception:
            pass
        self._hook_streamdeck(True)
        self._poll.start()
        self._connected = True

    def _disconnect(self):
        if not self._connected:
            return
        try:
            from gremlin.ui import state_device

            state_device.StateData().changed.disconnect(self.refresh)
        except Exception:
            pass
        try:
            import gremlin.event_handler

            el = gremlin.event_handler.EventListener()
            el.runtime_mode_changed.disconnect(self.refresh)
            el.edit_mode_changed.disconnect(self.refresh)
            el.profile_started.disconnect(self.refresh)
            el.profile_stop.disconnect(self.refresh)
        except Exception:
            pass
        self._hook_streamdeck(False)
        self._poll.stop()
        self._connected = False

    def _hook_streamdeck(self, enable: bool):
        if enable == self._streamdeck_hooked:
            return
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
        except Exception:
            return
        if enable:
            try:
                bridge.devices_changed.connect(self._on_streamdeck_event)
                bridge.virtual_page_changed.connect(self._on_streamdeck_event)
                bridge.inputs_changed.connect(self._on_streamdeck_event)
                bridge.slot_pressed.connect(self._on_streamdeck_event)
            except Exception:
                return
            self._streamdeck_bridge = bridge
            self._streamdeck_hooked = True
            return
        try:
            if self._streamdeck_bridge is not None:
                self._streamdeck_bridge.devices_changed.disconnect(self._on_streamdeck_event)
                self._streamdeck_bridge.virtual_page_changed.disconnect(self._on_streamdeck_event)
                self._streamdeck_bridge.inputs_changed.disconnect(self._on_streamdeck_event)
                self._streamdeck_bridge.slot_pressed.disconnect(self._on_streamdeck_event)
        except Exception:
            pass
        self._streamdeck_bridge = None
        self._streamdeck_hooked = False

    def _on_streamdeck_event(self, *args):
        """Stream Deck paint reads live bridge state; force every overlay view to redraw."""
        self._emit_all = True
        self.refresh()

    def refresh(self, *args):
        # Poll timer and DirectInput reads belong on this QObject's thread.
        # Do not InvokeUiMethod here: that allocates a QObject every 16 ms.
        if QtCore.QThread.currentThread() is not self.thread():
            if self._refresh_queued:
                return
            self._refresh_queued = True
            QtCore.QTimer.singleShot(0, self, self.refresh)
            return
        self._refresh_queued = False
        if not alive(self):
            return
        if any(item.get("type") == "sys_stats" for item in self._scene_widgets):
            from .sys_stats import SysStatsSampler

            SysStatsSampler().tick()
        changed_ids = []
        mouse_ids = set()
        graph_keys = set()
        stopwatch_ids = set()
        input_display_ids = set()
        manual_ids = set()
        for item in self._scene_widgets:
            widget_id = item.get("id")
            widget_type = item.get("type")
            if widget_type == "axis_mouse" and widget_id:
                mouse_ids.add(widget_id)
            if widget_type == "axis_graph" and widget_id:
                for series in item.get("series") or []:
                    sid = str((series or {}).get("id") or "")
                    if sid:
                        graph_keys.add((widget_id, sid))
            if widget_type == "stopwatch" and widget_id:
                stopwatch_ids.add(widget_id)
            if widget_type == "input_display" and widget_id:
                input_display_ids.add(widget_id)
            if widget_type == "sys_stats" and widget_id:
                for entry in item.get("stats") or []:
                    sid = str((entry or {}).get("id") or "")
                    if sid:
                        manual_ids.add(f"{widget_id}:{sid}")
            if widget_id in self._locked:
                continue
            value = read_widget_value(item)
            live = widget_is_live_visible(item)
            if self._cache.get(widget_id) != value or self._visible_cache.get(widget_id) != live:
                self._cache[widget_id] = value
                self._visible_cache[widget_id] = live
                changed_ids.append(widget_id)
        from .mouse_track import MouseOverlayTracker
        from .graph_track import GraphOverlayTracker
        from .stopwatch_track import StopwatchOverlayTracker
        from .input_display import KeyboardMouseTracker
        from .sys_stats import ManualCounterTracker

        MouseOverlayTracker().retain(mouse_ids)
        GraphOverlayTracker().retain(graph_keys)
        StopwatchOverlayTracker().retain(stopwatch_ids)
        KeyboardMouseTracker().retain(input_display_ids)
        ManualCounterTracker().retain(manual_ids)
        if self._emit_all:
            self._emit_all = False
            self.values_changed.emit([])
        elif changed_ids:
            self.values_changed.emit(changed_ids)

    def value_for(self, item: dict[str, Any]):
        widget_id = item.get("id")
        if widget_id in self._cache:
            return self._cache[widget_id]
        value = read_widget_value(item)
        self._cache[widget_id] = value
        self._visible_cache[widget_id] = widget_is_live_visible(item)
        return value

    def poke(self, widget_id: str, value, lock: bool = False):
        """Push a value immediately so paint does not wait for the next poll."""
        if not widget_id:
            return
        if QtCore.QThread.currentThread() is not self.thread():
            on_ui(self, self.poke, widget_id, value, lock)
            return
        if lock:
            self._locked.add(widget_id)
        if self._cache.get(widget_id) == value:
            return
        self._cache[widget_id] = value
        self.values_changed.emit([widget_id])

    def unlock(self, widget_id: str | None):
        if widget_id:
            self._locked.discard(widget_id)
