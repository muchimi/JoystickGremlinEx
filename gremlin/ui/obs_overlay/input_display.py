# -*- coding: utf-8; -*-
#
# Keyboard / Mouse overlay widget: picker layout, presets, and live press tracking.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import threading
import time
from typing import Any, NamedTuple

from PySide6 import QtWidgets

from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import MouseButton

DEFAULT_PRESET = "wasd_mouse"

PRESET_CHOICES = (
    ("wasd_mouse", "WASD + mouse"),
    ("wasd_extra", "WASD + extra mouse"),
    ("full", "Full keyboard"),
    ("full_mouse", "Full keyboard + mouse"),
    ("mouse", "Mouse only"),
    ("all", "All picker keys"),
    ("custom", "Custom"),
)

MOUSE_GRAPHIC_CHOICES = (
    ("silhouette", "Silhouette"),
    ("buttons", "Button map"),
)

_WHEEL_BUTTONS = {
    MouseButton.WheelUp,
    MouseButton.WheelDown,
    MouseButton.WheelLeft,
    MouseButton.WheelRight,
}

_SHORT_LABELS = {
    "esc": "ESC",
    "escape": "ESC",
    "tab": "TAB",
    "capslock": "CAPS",
    "leftshift": "SHIFT",
    "rightshift": "SHIFT",
    "leftcontrol": "CTRL",
    "rightcontrol": "CTRL",
    "leftalt": "ALT",
    "rightalt": "ALT",
    "rightalt2": "ALT",
    "leftwin": "WIN",
    "rightwin": "WIN",
    "backspace": "←",
    "enter": "ENTER",
    "space": "SPACE",
    "printscreen": "PrtSc",
    "scrolllock": "ScrLk",
    "pause": "Pause",
    "insert": "Ins",
    "delete": "Del",
    "home": "Home",
    "end": "End",
    "pageup": "PgUp",
    "pagedown": "PgDn",
    "numlock": "NmLk",
    "npdivide": "/",
    "npmultiply": "*",
    "npminus": "-",
    "npplus": "+",
    "npenter": "ENT",
    "np0": "0",
    "np1": "1",
    "np2": "2",
    "np3": "3",
    "np4": "4",
    "np5": "5",
    "np6": "6",
    "np7": "7",
    "np8": "8",
    "np9": "9",
    "npdelete": ".",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}

# Same grid as InputKeyboardDialog._get_keyboard_widget (keyboard picker).
_KEYBOARD_ROWS = (
    ["", "", "F13", "F14", "F15", "F16", "F17", "F18", "F19", "F20", "F21", "F22", "F23", "F24"],
    [
        "Esc",
        "",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
        "F7",
        "F8",
        "F9",
        "F10",
        "F11",
        "F12",
        "",
        ["PrtSc", "printscreen"],
        ["Scrlck", "scrolllock"],
        ["Pause", "pause"],
    ],
    [
        "`",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "0",
        "-",
        "=",
        ["Back", "backspace"],
        "",
        ["Ins", "insert"],
        ["Home", "home"],
        ["PgUp", "pageup"],
        "",
        ["NLck", "numlock"],
        ["/", "npdivide"],
        ["*", "npmultiply"],
        ["-", "npminus"],
    ],
    [
        ["Tab", "tab"],
        "Q",
        "W",
        "E",
        "R",
        "T",
        "Y",
        "U",
        "I",
        "O",
        "P",
        "[",
        "]",
        "\\",
        "",
        ["Del", "delete"],
        "End",
        ["PgDn", "pagedown"],
        "",
        ["7", "np7"],
        ["8", "np8"],
        ["9", "np9"],
        ["+", "npplus", 1, 2],
    ],
    [
        ["CpLck", "capslock"],
        "A",
        "S",
        "D",
        "F",
        "G",
        "H",
        "J",
        "K",
        "L",
        "'",
        ";",
        ["Enter", 2],
        "",
        "",
        "",
        "",
        "",
        ["4", "np4"],
        ["5", "np5"],
        ["6", "np6"],
    ],
    [
        ["LShift", "leftshift", 2],
        "Z",
        "X",
        "C",
        "V",
        "B",
        "N",
        "M",
        ",",
        ".",
        "/",
        ["RShift", "rightshift", 2],
        "",
        "",
        "",
        "",
        "up",
        "",
        "",
        ["1", "np1"],
        ["2", "np2"],
        ["3", "np3"],
        ["Enter", "npenter", 1, 2],
    ],
    [
        ["LCtrl", "leftcontrol"],
        ["LWin", "leftwin"],
        ["LAlt", "leftalt"],
        ["Spacebar", "space", 6],
        ["RAlt", "rightalt2"],
        ["RWin", "rightwin"],
        ["RCtrl", "rightcontrol"],
        "",
        "",
        "",
        "left",
        "down",
        "right",
        "",
        ["0/Ins", "np0", 2],
        ["./Del", "npdelete"],
    ],
)

_PRESET_NAMES = {
    "wasd_mouse": (
        "`",
        "1",
        "2",
        "3",
        "4",
        "5",
        "tab",
        "q",
        "w",
        "e",
        "r",
        "t",
        "a",
        "s",
        "d",
        "f",
        "g",
        "leftshift",
        "z",
        "x",
        "c",
        "v",
        "b",
        "leftcontrol",
        "leftalt",
        "space",
        "mouse_1",
        "mouse_2",
        "mouse_3",
        "mouse_4",
        "mouse_5",
        "wheel_up",
        "wheel_down",
    ),
    "wasd_extra": (
        "1",
        "2",
        "3",
        "4",
        "5",
        "tab",
        "q",
        "w",
        "e",
        "r",
        "t",
        "capslock",
        "a",
        "s",
        "d",
        "f",
        "g",
        "leftshift",
        "z",
        "x",
        "c",
        "v",
        "leftalt",
        "space",
        "mouse_1",
        "mouse_2",
        "mouse_3",
        "mouse_4",
        "mouse_5",
        "wheel_up",
        "wheel_down",
    ),
    "full": (
        "esc",
        "f1",
        "f2",
        "f3",
        "f4",
        "f5",
        "f6",
        "f7",
        "f8",
        "f9",
        "f10",
        "f11",
        "f12",
        "`",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "0",
        "-",
        "=",
        "backspace",
        "tab",
        "q",
        "w",
        "e",
        "r",
        "t",
        "y",
        "u",
        "i",
        "o",
        "p",
        "[",
        "]",
        "\\",
        "capslock",
        "a",
        "s",
        "d",
        "f",
        "g",
        "h",
        "j",
        "k",
        "l",
        ";",
        "'",
        "enter",
        "leftshift",
        "z",
        "x",
        "c",
        "v",
        "b",
        "n",
        "m",
        ",",
        ".",
        "/",
        "rightshift",
        "leftcontrol",
        "leftwin",
        "leftalt",
        "space",
        "rightalt2",
        "rightwin",
        "rightcontrol",
    ),
    "mouse": (
        "mouse_1",
        "mouse_2",
        "mouse_3",
        "mouse_4",
        "mouse_5",
        "wheel_up",
        "wheel_down",
        "wheel_left",
        "wheel_right",
        "mouse_d_1",
        "mouse_d_2",
        "mouse_d_3",
    ),
}

_PRESET_NAMES["full_mouse"] = _PRESET_NAMES["full"] + _PRESET_NAMES["mouse"]

_MOUSE_LOOKUPS = {
    "mouse_1",
    "mouse_2",
    "mouse_3",
    "mouse_4",
    "mouse_5",
    "wheel_up",
    "wheel_down",
    "wheel_left",
    "wheel_right",
    "mouse_d_1",
    "mouse_d_2",
    "mouse_d_3",
    "v_wheel",
    "h_wheel",
}

_layout_cells: list["KeyCell"] | None = None
_layout_by_lookup: dict[str, "KeyCell"] | None = None
_layout_by_scan: dict[tuple[int, bool], "KeyCell"] | None = None

# GEX/Windows names these keys differently than the layout cell ids.
_LOOKUP_ALIASES = {
    "rightalt": "rightalt2",
    "ralt": "rightalt2",
    "rightmenu": "rightalt2",
    "rmenu": "rightalt2",
    "rshift": "rightshift",
    "lshift": "leftshift",
    "lctrl": "leftcontrol",
    "rctrl": "rightcontrol",
    "lalt": "leftalt",
    "escape": "esc",
    "grave": "`",
    "tilde": "`",
    "apostrophe": "'",
    "quote": "'",
    "oem3": "`",
    "oem7": "'",
    "oem1": ";",
}

# Physical US positions (set-1 scan, extended). Used when lookup names don't match.
_LAYOUT_SCANS = {
    "`": ((0x29, False),),
    "'": ((0x28, False),),
    ";": ((0x27, False),),
    "rightshift": ((0x36, False), (0x36, True)),
    "leftshift": ((0x2A, False),),
    "rightalt2": ((0x38, True),),
    "leftalt": ((0x38, False),),
    "leftcontrol": ((0x1D, False),),
    "rightcontrol": ((0x1D, True),),
    "leftwin": ((0x5B, True),),
    "rightwin": ((0x5C, True),),
    "enter": ((0x1C, False),),
    "npenter": ((0x1C, True),),
    "\\": ((0x2B, False),),
    "-": ((0x0C, False),),
    "=": ((0x0D, False),),
    "[": ((0x1A, False),),
    "]": ((0x1B, False),),
    ",": ((0x33, False),),
    ".": ((0x34, False),),
    "/": ((0x35, False),),
}


class KeyCell(NamedTuple):
    lookup: str
    col: int
    row: int
    colspan: int
    rowspan: int
    label: str


def _canonical_lookup(lookup: str) -> str:
    raw = "".join(ch for ch in str(lookup or "").casefold() if ch not in " _-")
    return _LOOKUP_ALIASES.get(raw, raw)


def normalize_input_preset(value) -> str:
    raw = str(value or DEFAULT_PRESET).casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "wasd": "wasd_mouse",
        "compact": "wasd_mouse",
        "wasd_plus": "wasd_extra",
        "chroma": "wasd_extra",
        "keyboard": "full",
        "full_keyboard": "full",
        "fullkeyboard": "full",
        "mouse_only": "mouse",
        "all_keys": "all",
        "select_all": "all",
    }
    raw = aliases.get(raw, raw)
    known = {key for key, _label in PRESET_CHOICES}
    return raw if raw in known else "custom"


def normalize_mouse_graphic(value) -> str:
    raw = str(value or "silhouette").casefold()
    if raw in ("buttons", "button", "panel", "map", "extra"):
        return "buttons"
    return "silhouette"


def key_ident(key) -> tuple:
    try:
        scan = int(getattr(key, "scan_code", 0) or 0)
    except (TypeError, ValueError):
        scan = 0
    return (scan, bool(getattr(key, "is_extended", False)), bool(getattr(key, "is_mouse", False) or scan >= 0x1000))


def key_lookup(key) -> str:
    name = str(getattr(key, "lookup_name", None) or "").casefold()
    if name:
        return name
    if getattr(key, "is_mouse", False):
        button = getattr(key, "mouse_button", None)
        if button is not None:
            try:
                return str(MouseButton.to_lookup_string(button) or "").casefold()
            except Exception:
                pass
    return str(getattr(key, "name", "") or "").casefold()


def is_mouse_key(key) -> bool:
    if bool(getattr(key, "is_mouse", False)):
        return True
    try:
        if int(getattr(key, "scan_code", 0) or 0) >= 0x1000:
            return True
    except (TypeError, ValueError):
        pass
    return key_lookup(key) in _MOUSE_LOOKUPS


def display_label(key) -> str:
    lookup = key_lookup(key)
    canon = _canonical_lookup(lookup)
    if canon in _SHORT_LABELS:
        return _SHORT_LABELS[canon]
    if lookup in _SHORT_LABELS:
        return _SHORT_LABELS[lookup]
    if lookup in _MOUSE_LOOKUPS or canon in _MOUSE_LOOKUPS:
        from gremlin.keyboard import KeyMap

        return KeyMap.get_name(key) or lookup
    if canon.startswith("f") and canon[1:].isdigit():
        return canon.upper()
    if len(canon) == 1:
        return canon.upper()
    from gremlin.keyboard import KeyMap

    name = KeyMap.get_name(key) or getattr(key, "name", None) or lookup
    return str(name)


def cell_display_label(cell: KeyCell, key) -> str:
    canon = _canonical_lookup(cell.lookup)
    if canon in _SHORT_LABELS:
        return _SHORT_LABELS[canon]
    if cell.label:
        return cell.label
    return display_label(key)


def _scans_for_lookup(lookup: str) -> list[tuple[int, bool]]:
    scans: list[tuple[int, bool]] = []
    seen: set[tuple[int, bool]] = set()
    for pair in _LAYOUT_SCANS.get(lookup, ()):
        if pair not in seen:
            seen.add(pair)
            scans.append(pair)
    try:
        from gremlin.keyboard import KeyMap

        data = KeyMap._g_name_map.get(lookup)
        if data:
            pair = (int(data[1]), bool(data[2]))
            if pair not in seen:
                seen.add(pair)
                scans.append(pair)
        key = KeyMap._key_map.get(lookup)
        if key is not None:
            pair = (int(key.scan_code), bool(key.is_extended))
            if pair not in seen:
                seen.add(pair)
                scans.append(pair)
    except Exception:
        pass
    return scans


def _parse_row_entry(data) -> tuple[str, str, int, int] | None:
    if isinstance(data, list):
        key = None
        key_name = None
        column_span = 1
        row_span = 1
        found_key = found_name = found_column = found_row = False
        for item in data:
            if not found_key:
                key = item
                key_name = str(key).lower()
                found_key = True
                continue
            if not found_name and isinstance(item, str):
                found_name = True
                key_name = item
                continue
            if not found_column and isinstance(item, int):
                found_column = True
                column_span = item
                continue
            if not found_row and isinstance(item, int):
                found_row = True
                row_span = item
                continue
        if not key:
            return None
        return str(key), str(key_name), int(column_span), int(row_span)
    if not data:
        return None
    key = str(data)
    return key, key.lower(), 1, 1


def keyboard_layout_cells() -> list[KeyCell]:
    global _layout_cells, _layout_by_lookup, _layout_by_scan
    if _layout_cells is not None:
        return _layout_cells
    cells: list[KeyCell] = []
    by_lookup: dict[str, KeyCell] = {}
    by_scan: dict[tuple[int, bool], KeyCell] = {}
    for row_index, row in enumerate(_KEYBOARD_ROWS):
        column = 0
        for data in row:
            parsed = _parse_row_entry(data)
            if parsed is None:
                column += 1
                continue
            _label, lookup, colspan, rowspan = parsed
            lookup = _canonical_lookup(lookup)
            cell = KeyCell(lookup, column, row_index, colspan, rowspan, _label)
            cells.append(cell)
            by_lookup[lookup] = cell
            for scan in _scans_for_lookup(lookup):
                by_scan[scan] = cell
            column += colspan
    for alias, target in _LOOKUP_ALIASES.items():
        if target in by_lookup:
            by_lookup[alias] = by_lookup[target]
    _layout_cells = cells
    _layout_by_lookup = by_lookup
    _layout_by_scan = by_scan
    return cells


def keyboard_cell_for(lookup: str) -> KeyCell | None:
    keyboard_layout_cells()
    raw = str(lookup or "").casefold()
    table = _layout_by_lookup or {}
    return table.get(_canonical_lookup(raw)) or table.get(raw)


def keyboard_cell_for_key(key) -> KeyCell | None:
    keyboard_layout_cells()
    try:
        scan = int(getattr(key, "scan_code", 0) or 0)
        extended = bool(getattr(key, "is_extended", False))
    except (TypeError, ValueError):
        scan = 0
        extended = False
    table = _layout_by_scan or {}
    cell = table.get((scan, extended))
    if cell is None and scan == 0x36:
        cell = table.get((scan, not extended))
    if cell is not None:
        return cell
    return keyboard_cell_for(key_lookup(key))


def keys_from_names(names) -> list:
    from gremlin.keyboard import key_from_name

    from .model import normalize_overlay_keys, serialize_overlay_key

    keys = []
    for name in names or []:
        try:
            key = key_from_name(str(name), validate=True)
        except Exception:
            key = None
        if key is None:
            continue
        keys.append(serialize_overlay_key(key))
    return normalize_overlay_keys(keys)


def all_picker_key_names() -> list[str]:
    names = [cell.lookup for cell in keyboard_layout_cells()]
    names.extend(sorted(_MOUSE_LOOKUPS))
    try:
        from gremlin.keyboard import KeyMap

        for key in KeyMap.get_media_keys() or []:
            if key is None:
                continue
            lookup = key_lookup(key)
            if lookup:
                names.append(lookup)
    except Exception:
        pass
    seen = set()
    unique = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        unique.append(name)
    return unique


def preset_key_names(preset: str) -> list[str]:
    preset = normalize_input_preset(preset)
    if preset == "all":
        return all_picker_key_names()
    if preset == "custom":
        return list(_PRESET_NAMES[DEFAULT_PRESET])
    return list(_PRESET_NAMES.get(preset) or _PRESET_NAMES[DEFAULT_PRESET])


def preset_keys(preset: str) -> list[dict[str, Any]]:
    return keys_from_names(preset_key_names(preset))


def default_widget_keys() -> list[dict[str, Any]]:
    return preset_keys(DEFAULT_PRESET)


def preset_mouse_graphic(preset: str) -> str:
    preset = normalize_input_preset(preset)
    if preset in ("wasd_extra", "mouse"):
        return "buttons"
    return "silhouette"


def overlay_keys_from_item(item: dict[str, Any] | None) -> list:
    from .model import deserialize_overlay_key

    keys = []
    seen = set()
    for raw in (item or {}).get("keys") or []:
        key = deserialize_overlay_key(raw)
        if key is None:
            continue
        ident = key_ident(key)
        if ident in seen:
            continue
        seen.add(ident)
        keys.append(key)
    return keys


def matching_preset(item: dict[str, Any] | None) -> str:
    keys = overlay_keys_from_item(item)
    current = {key_ident(key) for key in keys}
    if not current:
        return "custom"
    for preset, _label in PRESET_CHOICES:
        if preset == "custom":
            continue
        preset_idents = set()
        from .model import deserialize_overlay_key

        for raw in preset_keys(preset):
            key = deserialize_overlay_key(raw)
            if key is not None:
                preset_idents.add(key_ident(key))
        if current == preset_idents:
            return preset
    return "custom"


def split_display_keys(keys) -> tuple[list, list]:
    keyboard = []
    mouse = []
    for key in keys or []:
        if is_mouse_key(key):
            mouse.append(key)
        else:
            keyboard.append(key)
    return keyboard, mouse


def _build_picker_class():
    from gremlin.ui.virtual_keyboard import InputKeyboardDialog

    class OverlayInputDisplayPicker(InputKeyboardDialog):
        """Keyboard picker with select-all / deselect-all for overlay display keys."""

        def __init__(self, sequence=None, parent=None):
            super().__init__(sequence=sequence, parent=parent, select_single=False, allow_modifiers=True)
            self.setWindowTitle("Select keys and mouse buttons to display")
            self.clear_widget.setText("Deselect all")
            self.clear_widget.setToolTip("Clear every selected key and mouse button.")
            self.select_all_widget = QtWidgets.QPushButton("Select all")
            self.select_all_widget.setToolTip("Select every key and mouse button on this picker.")
            self.select_all_widget.clicked.connect(self._select_all_cb)
            self.button_layout.insertWidget(1, self.select_all_widget)

        def _unique_key_widgets(self):
            seen = set()
            widgets = []
            for widget in self._key_widget_map.values():
                ident = id(widget)
                if ident in seen:
                    continue
                seen.add(ident)
                if getattr(widget, "key", None) is None:
                    continue
                widgets.append(widget)
            return widgets

        def _select_all_cb(self):
            for widget in self._unique_key_widgets():
                widget.selected = True

    return OverlayInputDisplayPicker


OverlayInputDisplayPicker = _build_picker_class()


@SingletonDecorator
class KeyboardMouseTracker:
    """Live keyboard / mouse down set for overlay Keyboard / Mouse widgets."""

    def __init__(self):
        self._hooked = False
        self._mouse_hook = None
        self._lock = threading.Lock()
        self._mouse_down: set[str] = set()
        self._wheel_until: dict[str, float] = {}

    def retain(self, widget_ids: set[str] | None):
        if widget_ids:
            self._ensure_hooks()
            return
        self._unhook()
        with self._lock:
            self._mouse_down.clear()
            self._wheel_until.clear()

    def _ensure_hooks(self):
        if self._hooked:
            return
        try:
            import gremlin.windows_event_hook

            self._mouse_hook = gremlin.windows_event_hook.MouseHook()
            self._mouse_hook.register(self._on_mouse)
        except Exception:
            self._mouse_hook = None
        self._hooked = True

    def _unhook(self):
        if not self._hooked:
            return
        try:
            if self._mouse_hook is not None:
                self._mouse_hook.unregister(self._on_mouse)
        except Exception:
            pass
        self._mouse_hook = None
        self._hooked = False

    def _on_mouse(self, event):
        try:
            button = event.button_id
            pressed = bool(event.is_pressed)
        except Exception:
            return
        lookup = None
        try:
            lookup = MouseButton.to_lookup_string(button)
        except Exception:
            lookup = None
        if not lookup:
            return
        lookup = str(lookup).casefold()
        now = time.monotonic()
        with self._lock:
            if button in _WHEEL_BUTTONS:
                if pressed:
                    self._wheel_until[lookup] = now + 0.35
                else:
                    self._wheel_until.pop(lookup, None)
                return
            if pressed:
                self._mouse_down.add(lookup)
            else:
                self._mouse_down.discard(lookup)

    def _mouse_lookups_down(self) -> set[str]:
        now = time.monotonic()
        with self._lock:
            expired = [name for name, until in self._wheel_until.items() if until <= now]
            for name in expired:
                self._wheel_until.pop(name, None)
            down = set(self._mouse_down)
            down.update(self._wheel_until.keys())
        return down

    def sample(self, item: dict[str, Any] | None) -> tuple:
        keys = overlay_keys_from_item(item)
        if not keys:
            return ()
        from .bindings import _key_is_down

        mouse_down = self._mouse_lookups_down()
        pressed = []
        for key in keys:
            lookup = key_lookup(key)
            if lookup in mouse_down:
                pressed.append(lookup)
                continue
            if _key_is_down(key):
                pressed.append(lookup)
        return tuple(sorted(set(pressed)))
