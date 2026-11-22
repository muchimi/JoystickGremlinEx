# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
# Module created by Joop de Hoog, 14-11-2026 for the map to application action
# Modified for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""gex_core.py 1.0 - shared core of the GremlinEx (GEX) action "Map to Application"
(Joop de Hoog, 14-11-2026; the presets are shared when GremlinEx uses a version based folder).
Copied into the action folder by install_gex_actions.bat.
Successor of gx_core.py (which stays unchanged for "Map to Keyboard Ex (App)" v3.1.1).

Contents
  - finding the app window by process name / window title
  - input items: a keyboard key (vk, scan, extended) or a mouse button / wheel ("mouse:left" ...)
  - delivery  window : PostMessage into the app (no focus change, the sim never sees it).
                       Keys go to the app's main window; the optional preset setting window_class
                       picks a specific child window (e.g. Chrome_RenderWidgetHostHWND).
                       Mouse buttons go to the child window under the mouse when the mouse is over the
                       app, otherwise under the centre of the app window.
              focus  : bring the app to the front, SendInput (keys or mouse where the mouse is),
                       give the focus back to the previous window (or the sim)
  - UI element (UI Automation, own ctypes COM, no extra packages)


  - preset files <Joystick Gremlin Ex>\\gex_apps\\*.ini (shared by all GremlinEx versions, also with
    GremlinEx's option "Version based Configuration Data")
  - a background worker, so the GremlinEx event thread is never blocked
Only Python's standard library (ctypes) is used; GremlinEx is imported lazily where needed.
License: GPL-3.0 (as GremlinEx).
"""

import ctypes
import logging
import os
import queue
import re
import threading
import time
from ctypes import wintypes

VERSION = "1.0"
log = logging.getLogger("system")
TAG = "gex_actions"

# =========================================================================== Win32 setup
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ole = ctypes.WinDLL("ole32")
_oleaut = ctypes.WinDLL("oleaut32")
_H, _P = wintypes.HWND, wintypes.POINT
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, _H, wintypes.LPARAM)


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", _H),
        ("hwndFocus", _H),
        ("hwndCapture", _H),
        ("hwndMenuOwner", _H),
        ("hwndMoveSize", _H),
        ("hwndCaret", _H),
        ("rcCaret", wintypes.RECT),
    ]


for _n, _a, _r in [
    ("EnumWindows", [_WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
    ("EnumChildWindows", [_H, _WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
    ("IsWindow", [_H], wintypes.BOOL),
    ("IsWindowVisible", [_H], wintypes.BOOL),
    ("IsIconic", [_H], wintypes.BOOL),
    ("IsChild", [_H, _H], wintypes.BOOL),
    ("GetWindow", [_H, wintypes.UINT], _H),
    ("GetAncestor", [_H, wintypes.UINT], _H),
    ("GetWindowThreadProcessId", [_H, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
    ("GetGUIThreadInfo", [wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO)], wintypes.BOOL),
    ("GetWindowTextW", [_H, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
    ("GetClassNameW", [_H, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
    ("PostMessageW", [_H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
    ("MapVirtualKeyW", [wintypes.UINT, wintypes.UINT], wintypes.UINT),
    ("GetForegroundWindow", [], _H),
    ("SetForegroundWindow", [_H], wintypes.BOOL),
    ("BringWindowToTop", [_H], wintypes.BOOL),
    ("ShowWindow", [_H, ctypes.c_int], wintypes.BOOL),
    ("AttachThreadInput", [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
    ("GetWindowRect", [_H, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
    ("GetClientRect", [_H, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
    ("ClientToScreen", [_H, ctypes.POINTER(_P)], wintypes.BOOL),
    ("ScreenToClient", [_H, ctypes.POINTER(_P)], wintypes.BOOL),
    ("ChildWindowFromPointEx", [_H, _P, wintypes.UINT], _H),
    ("WindowFromPoint", [_P], _H),
    ("GetCursorPos", [ctypes.POINTER(_P)], wintypes.BOOL),
    ("SetCursorPos", [ctypes.c_int, ctypes.c_int], wintypes.BOOL),
    ("GetAsyncKeyState", [ctypes.c_int], ctypes.c_short),
]:
    _f = getattr(_u32, _n)
    _f.argtypes, _f.restype = _a, _r
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.GetCurrentThreadId.restype = wintypes.DWORD

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x0200, 0x020A, 0x020E
GA_ROOT = 2
MK_SHIFT, MK_CONTROL = 0x0004, 0x0008


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_u32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_u32.SendInput.restype = wintypes.UINT

# =========================================================================== input items
# A key is a tuple (vk, scan, extended). A mouse item is a string "mouse:<name>".
# A list of items is in press order (modifiers first); releases happen in reverse order.
VK = {
    "enter": (0x0D, False),
    "return": (0x0D, False),
    "escape": (0x1B, False),
    "esc": (0x1B, False),
    "tab": (0x09, False),
    "space": (0x20, False),
    "backspace": (0x08, False),
    "pause": (0x13, False),
    "capslock": (0x14, False),
    "pgup": (0x21, True),
    "pageup": (0x21, True),
    "pgdn": (0x22, True),
    "pagedown": (0x22, True),
    "end": (0x23, True),
    "home": (0x24, True),
    "left": (0x25, True),
    "up": (0x26, True),
    "right": (0x27, True),
    "down": (0x28, True),
    "insert": (0x2D, True),
    "ins": (0x2D, True),
    "delete": (0x2E, True),
    "del": (0x2E, True),
    "numpadmult": (0x6A, False),
    "numpadadd": (0x6B, False),
    "numpadsub": (0x6D, False),
    "numpaddot": (0x6E, False),
    "numpaddiv": (0x6F, True),
    "numpadenter": (0x0D, True),
    "-": (0xBD, False),
    "=": (0xBB, False),
    ",": (0xBC, False),
    ".": (0xBE, False),
    "/": (0xBF, False),
    ";": (0xBA, False),
    "'": (0xDE, False),
    "[": (0xDB, False),
    "]": (0xDD, False),
    "\\": (0xDC, False),
    "`": (0xC0, False),
}
for _i in range(1, 25):
    VK[f"f{_i}"] = (0x6F + _i, False)
for _i in range(10):
    VK[f"numpad{_i}"] = (0x60 + _i, False)
MODS = {"ctrl": (0x11, False), "control": (0x11, False), "shift": (0x10, False), "alt": (0x12, False), "win": (0x5B, True)}
ALT_VKS = {0x12, 0xA4, 0xA5}
CTRL_VKS = {0x11, 0xA2, 0xA3}
SHIFT_VKS = {0x10, 0xA0, 0xA1}
MODIFIER_VKS = ALT_VKS | CTRL_VKS | SHIFT_VKS | {0x5B, 0x5C}

# mouse: name -> (down msg, up msg, MK flag, xbutton, SendInput down flag, SendInput up flag)
MOUSE_BUTTONS = {
    "left": (0x0201, 0x0202, 0x0001, 0, 0x0002, 0x0004),
    "right": (0x0204, 0x0205, 0x0002, 0, 0x0008, 0x0010),
    "middle": (0x0207, 0x0208, 0x0010, 0, 0x0020, 0x0040),
    "x1": (0x020B, 0x020C, 0x0020, 1, 0x0080, 0x0100),
    "x2": (0x020B, 0x020C, 0x0040, 2, 0x0080, 0x0100),
}
# wheel: name -> (vertical?, sign)
MOUSE_WHEELS = {"wheel_up": (True, 1), "wheel_down": (True, -1), "wheel_left": (False, -1), "wheel_right": (False, 1)}
MOUSE_NAMES = tuple(MOUSE_BUTTONS) + tuple(MOUSE_WHEELS)
_MOUSE_ALIASES = {
    "back": "x1",
    "forward": "x2",
    "xbutton1": "x1",
    "xbutton2": "x2",
    "wheelup": "wheel_up",
    "wheeldown": "wheel_down",
    "wheelleft": "wheel_left",
    "wheelright": "wheel_right",
}


def is_mouse(item):
    return isinstance(item, str)


def mouse_name(item):
    """'mouse:left' -> 'left' (None if the item is not a mouse item)"""
    if not is_mouse(item):
        return None
    n = item.split(":", 1)[-1].strip().lower()
    n = _MOUSE_ALIASES.get(n, n)
    return n if n in MOUSE_NAMES else None


def mouse_item(name):
    n = (name or "").strip().lower()
    n = _MOUSE_ALIASES.get(n, n)
    return f"mouse:{n}" if n in MOUSE_NAMES else None


def is_wheel(item):
    return mouse_name(item) in MOUSE_WHEELS


def make_key(vk, ext=False, scan=None):
    if scan is None:
        scan = _u32.MapVirtualKeyW(vk, 0) & 0xFF
    return (int(vk), int(scan), bool(ext))


# fixed click point: (x, y, pct) - pct=True: percent of the window's client area, False: pixels
_RE_AT = re.compile(r"^(?P<name>[^@]+?)\s*(?:@\s*(?P<x>\d+(?:\.\d+)?)\s*(?P<px>%?)\s*,\s*(?P<y>\d+(?:\.\d+)?)\s*(?P<py>%?))?\s*$")


def _split_mouse(part):
    """'left@30%,84%' -> ('left', (30.0, 84.0, True)); 'left' -> ('left', None); invalid -> (None, None)"""
    m = _RE_AT.match(part)
    if not m:
        return None, None
    if m.group("x") is None:
        return m.group("name"), None
    pct = bool(m.group("px") or m.group("py"))
    x, y = float(m.group("x")), float(m.group("y"))
    if pct and (x > 100 or y > 100):
        return None, None
    return m.group("name"), (x, y, pct)


def parse_click(text):
    """fixed click point written after a mouse button in a preset value ('mouse:left@30%,84%'), or None"""
    for part in (text or "").split("+"):
        low = part.strip().lower()
        if low.startswith("mouse:"):
            _name, click = _split_mouse(low[6:])
            if click:
                return click
    return None


def click_to_text(click):
    """(30.0, 84.0, True) -> '@30%,84%' ; None -> ''"""
    if not click:
        return ""
    x, y, pct = click
    fmt = (lambda v: f"{v:g}") if pct else (lambda v: str(round(v)))
    unit = "%" if pct else ""
    return f"@{fmt(x)}{unit},{fmt(y)}{unit}"


def value_text(items, click=None):
    """items (+ fixed click point) -> preset value, e.g. 'ctrl+mouse:left@30%,84%'"""
    text = items_to_text(items)
    return text + click_to_text(click) if click and any(is_mouse(i) for i in items) else text


def parse_items(text):
    """'ctrl+shift+F9' / 'q' / 'mouse:right' / 'ctrl+mouse:left@30%,84%' -> [items] or None
    (a fixed click point after a mouse button is read with parse_click)"""
    parts = [p.strip() for p in (text or "").strip().strip("{}").split("+")]
    if not parts or not parts[-1]:
        return None
    out = []
    for i, part in enumerate(parts):
        low = part.lower()
        if low.startswith("mouse:"):
            name, _click = _split_mouse(low[6:])
            m = mouse_item(name) if name else None
            if not m:
                return None
            out.append(m)
        elif low in MODS:
            out.append(make_key(*MODS[low]))
        elif low in VK:
            out.append(make_key(*VK[low]))
        elif len(low) == 1 and low.isascii() and (low.isalpha() or low.isdigit()):
            out.append(make_key(ord(low.upper())))
        elif re.fullmatch(r"vk[0-9a-f]{2}", low):  # any other key by its virtual key code, e.g. vk5D
            out.append(make_key(int(low, 0)))
        else:
            return None
    return out


_VK_TO_NAME = {}
for _name, (_vk, _ext) in VK.items():
    _VK_TO_NAME.setdefault(_vk, _name)
_NICE = {
    "pgup": "PgUp",
    "pgdn": "PgDn",
    "enter": "Enter",
    "escape": "Escape",
    "tab": "Tab",
    "space": "Space",
    "backspace": "Backspace",
    "pause": "Pause",
    "capslock": "CapsLock",
    "end": "End",
    "home": "Home",
    "left": "Left",
    "up": "Up",
    "right": "Right",
    "down": "Down",
    "insert": "Insert",
    "delete": "Delete",
}
_MOD_NAME = {
    0x11: "ctrl",
    0xA2: "ctrl",
    0xA3: "ctrl",
    0x10: "shift",
    0xA0: "shift",
    0xA1: "shift",
    0x12: "alt",
    0xA4: "alt",
    0xA5: "alt",
    0x5B: "win",
    0x5C: "win",
}


def vk_to_name(vk):
    """virtual key -> name as used in presets ('a', '7', 'F5', 'PgUp', 'Numpad3'); None if unknown"""
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk).lower()
    n = _VK_TO_NAME.get(vk)
    if not n:
        return None
    if n.startswith("f") and n[1:].isdigit():
        return n.upper()
    if n.startswith("numpad"):
        return "Numpad" + (n[6:] if n[6:].isdigit() else n[6:].capitalize())
    return _NICE.get(n, n)


def items_to_text(items):
    """[items] -> 'ctrl+q' / 'mouse:left' (for display and logs)"""
    names = []
    for it in items or []:
        if is_mouse(it):
            names.append(f"mouse:{mouse_name(it) or '?'}")
        else:
            vk = it[0]
            if vk == 0x0D and it[2]:
                names.append("NumpadEnter")
            else:
                names.append(_MOD_NAME.get(vk) or vk_to_name(vk) or f"vk{vk:02X}")
    return "+".join(names)


def items_signature(items):
    """comparable form of items: a key is (vk, extended) without its scan code, a mouse item its name"""
    return [it if is_mouse(it) else (it[0], bool(it[2])) for it in items or []]


def _keys(items):
    return [it for it in items if not is_mouse(it)]


def _mouse(items):
    return [it for it in items if is_mouse(it)]


# =========================================================================== windows
def process_name(hwnd, cache=None):
    """-> (exe name in lower case, thread id). cache: a dict that lives for ONE enumeration only
    (a process id can be reused by another program later, so names are never kept longer)."""
    pid = wintypes.DWORD()
    tid = _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = cache.get(pid.value) if cache is not None else None
    if name is None:
        name = ""
        h = _k32.OpenProcess(0x1000, False, pid.value)
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
            _k32.CloseHandle(h)
        if cache is not None:
            cache[pid.value] = name
    return name, tid


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    _u32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _matches(proc, program):
    p = (program or "").strip().lower()
    return bool(p) and (proc == p if p.endswith(".exe") else p in proc)


def find_windows(program, title=""):
    """visible top-level windows of the program -> [(hwnd, tid)], largest unowned window first"""
    title = (title or "").strip().lower()
    found = []
    names = {}

    def _cb(hwnd, _lp):
        if _u32.IsWindowVisible(hwnd):
            name, tid = process_name(hwnd, names)
            if name and _matches(name, program) and (not title or title in window_title(hwnd).lower()):
                r = wintypes.RECT()
                _u32.GetWindowRect(hwnd, ctypes.byref(r))
                area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
                found.append((bool(_u32.GetWindow(hwnd, 4)), -area, hwnd, tid))
        return True

    _u32.EnumWindows(_WNDENUMPROC(_cb), 0)
    found.sort(key=lambda w: (w[0], w[1]))
    return [(w[2], w[3]) for w in found]


def main_window(program, title=""):
    w = find_windows(program, title)
    return w[0] if w else (None, 0)


def is_running(program, title=""):
    return bool(main_window(program, title)[0])


def belongs_to(w, hwnd):
    """True if window w is hwnd, a child of it, or another window of the same process"""
    if not w or not hwnd:
        return False
    if w == hwnd or _u32.IsChild(hwnd, w):
        return True
    pa, pb = wintypes.DWORD(), wintypes.DWORD()
    _u32.GetWindowThreadProcessId(w, ctypes.byref(pa))
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pb))
    return pa.value == pb.value


def running_programs():
    """exe names of programs with a visible titled window (for the Select... list)"""
    seen = set()
    names = {}

    def _cb(hwnd, _lp):
        if _u32.IsWindowVisible(hwnd) and window_title(hwnd):
            n = process_name(hwnd, names)[0]
            if n:
                seen.add(n)
        return True

    _u32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return sorted(seen, key=str.lower)


def child_windows(hwnd):
    out = []

    def _cb(h, _lp):
        out.append(h)
        return True

    _u32.EnumChildWindows(hwnd, _WNDENUMPROC(_cb), 0)
    return out


# =========================================================================== window delivery: target
def focus_child(hwnd):
    """the window inside the app that has the keyboard focus, or None.
    Only known while the app is in front: Windows clears it when the app loses the focus
    (tested 12-11-2026), so for an app in the background this returns None."""
    _proc, tid = process_name(hwnd)
    gti = _GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(_GUITHREADINFO)
    if tid and _u32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
        f = gti.hwndFocus
        if f == hwnd or _u32.IsChild(hwnd, f):
            return f
    return None


def key_target(hwnd, wclass=""):
    """where keys are posted: the child of class wclass (if given), else the app's main window
    (or, only while the app itself is in front, its focused control - where real keys would go too)"""
    wclass = (wclass or "").strip().lower()
    focus = focus_child(hwnd)
    if wclass:
        if focus and window_class(focus).lower() == wclass:
            return focus
        fallback = None
        for c in child_windows(hwnd):
            if window_class(c).lower() == wclass:
                if _u32.IsWindowVisible(c):
                    return c
                fallback = fallback or c
        if fallback:
            return fallback
        log.warning(f"{TAG}: window class '{wclass}' not found in the app; using the focused window")
    return focus or hwnd


def fixed_point(hwnd, click):
    """screen point of a fixed click point in the app's client area, or None (e.g. window minimized)"""
    x, y, pct = click
    r = wintypes.RECT()
    if not _u32.GetClientRect(hwnd, ctypes.byref(r)) or r.right <= 0 or r.bottom <= 0:
        return None
    cx, cy = (round(r.right * x / 100.0), round(r.bottom * y / 100.0)) if pct else (int(x), int(y))
    cx, cy = min(max(cx, 0), r.right - 1), min(max(cy, 0), r.bottom - 1)
    pt = _P(cx, cy)
    _u32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt


def over_app(hwnd, pt):
    """True if screen point pt is over the app window hwnd (or one of its children)"""
    under = _u32.WindowFromPoint(pt)
    return bool(under) and (under == hwnd or _u32.GetAncestor(under, GA_ROOT) == hwnd)


def click_from_screen(program, title, pt):
    """screen point -> fixed click point in percent of the app's client area (1 decimal), or None if the
    point is not over the app (used by Pick...)"""
    hwnd, _ = main_window(program, title)
    if not hwnd or not over_app(hwnd, pt):
        return None
    r = wintypes.RECT()
    _u32.GetClientRect(hwnd, ctypes.byref(r))
    cp = _P(pt.x, pt.y)
    _u32.ScreenToClient(hwnd, ctypes.byref(cp))
    if r.right <= 0 or r.bottom <= 0 or not (0 <= cp.x < r.right and 0 <= cp.y < r.bottom):
        return None
    return (round(cp.x * 100.0 / r.right, 1), round(cp.y * 100.0 / r.bottom, 1), True)


def cursor_pos():
    pt = _P()
    _u32.GetCursorPos(ctypes.byref(pt))
    return pt


def button_down(vk, or_since_last=False):
    """True while the key / mouse button vk is held (global, for Pick...). or_since_last=True also counts a
    press since the previous call (catches clicks shorter than the polling interval)."""
    state = _u32.GetAsyncKeyState(vk)
    return bool(state & 0x8000) or (or_since_last and bool(state & 0x0001))


def mouse_point(hwnd):
    """screen point for a window-delivery click: the mouse when it is over the app, else the centre"""
    pt = _P()
    if _u32.GetCursorPos(ctypes.byref(pt)):
        under = _u32.WindowFromPoint(pt)
        if under and (under == hwnd or _u32.GetAncestor(under, GA_ROOT) == hwnd):
            return pt
    r = wintypes.RECT()
    _u32.GetClientRect(hwnd, ctypes.byref(r))
    c = _P(r.right // 2, r.bottom // 2)
    _u32.ClientToScreen(hwnd, ctypes.byref(c))
    return c


def child_at(hwnd, pt):
    """deepest child window of hwnd at screen point pt -> (window, client point in that window)"""
    dest = hwnd
    for _ in range(16):
        cp = _P(pt.x, pt.y)
        _u32.ScreenToClient(dest, ctypes.byref(cp))
        child = _u32.ChildWindowFromPointEx(dest, cp, 0x0003)  # skip invisible + disabled
        if not child or child == dest:
            break
        dest = child
    local = _P(pt.x, pt.y)
    _u32.ScreenToClient(dest, ctypes.byref(local))
    return dest, local


# =========================================================================== window delivery
def _lp(scan, ext, up, alt):
    lp = 1 | ((scan & 0xFF) << 16) | ((1 << 24) if ext else 0) | ((1 << 29) if alt else 0)
    return lp | ((1 << 30) | (1 << 31) if up else 0)


REFUSED = "the application did not accept the input (is it running as administrator?)"
NO_POINT = "the fixed click point is not available (is the window minimized?)"
_held = {}  # (application binding, hold identity, input) -> destination of the press


def _post(hwnd, msg, wp, lp):
    return bool(_u32.PostMessageW(hwnd, msg, wp, lp))


def _held_get(key):
    target = _held.pop(key, None)
    hwnd = target[0] if isinstance(target, tuple) else target
    return target if hwnd and _u32.IsWindow(hwnd) else None


def _post_keys(target, keys, down, up, alt):
    """-> True if every message was accepted"""
    kd, ku = (WM_SYSKEYDOWN, WM_SYSKEYUP) if alt else (WM_KEYDOWN, WM_KEYUP)
    ok = True
    if down:
        for vk, scan, ext in keys:
            ok = _post(target, kd, vk, _lp(scan, ext, False, alt)) and ok
    if up:
        for vk, scan, ext in reversed(keys):
            ok = _post(target, ku, vk, _lp(scan, ext, True, alt)) and ok
    return ok


def _mk_mods(keys):
    vks = {k[0] for k in keys}
    return (MK_CONTROL if vks & CTRL_VKS else 0) | (MK_SHIFT if vks & SHIFT_VKS else 0)


def _post_mouse(hwnd, name, down, up, mods, wheel_factor, click, hold_key):
    """-> '' or the reason it failed. A release without a press in the same call goes to the window and
    point of the press (the mouse may have moved since)."""
    held = _held_get(hold_key) if (up and not down and name in MOUSE_BUTTONS) else None
    if held:
        dest, lp = held
        pt = None
    else:
        pt = fixed_point(hwnd, click) if click else mouse_point(hwnd)
        if pt is None:
            return NO_POINT
        dest, local = child_at(hwnd, pt)
        lp = ((local.y & 0xFFFF) << 16) | (local.x & 0xFFFF)
    if name in MOUSE_WHEELS:
        if not down:
            return ""
        vertical, sign = MOUSE_WHEELS[name]
        delta = 120 * max(1, int(wheel_factor)) * sign
        wp = ((delta & 0xFFFF) << 16) | mods
        lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)  # wheel: screen coordinates
        return "" if _post(dest, WM_MOUSEWHEEL if vertical else WM_MOUSEHWHEEL, wp, lp) else REFUSED
    md, mu, mk, xb, _sd, _su = MOUSE_BUTTONS[name]
    ok = True
    if down:
        ok = _post(dest, WM_MOUSEMOVE, mods, lp) and ok
        ok = _post(dest, md, (xb << 16) | mk | mods, lp) and ok
        if not up:
            _held[hold_key] = (dest, lp)
    if up:
        ok = _post(dest, mu, (xb << 16) | mods, lp) and ok
    return "" if ok else REFUSED


def window_send(program, title, items, down=True, up=True, wclass="", wheel_factor=1, click=None, hold_id=None):
    """post the items into the app (no focus change; the application in front never sees them).
    -> '' if sent, otherwise the reason. Keys go to the main window (or the wclass child), mouse items to
    the child under the click point (the fixed point 'click', or the mouse when it is over the app, or the
    centre). A release goes to the same window as its press."""
    keys = _keys(items)
    mouse_names = [mouse_name(item) for item in _mouse(items)]
    alt = any(k[0] in ALT_VKS for k in keys)
    mods = _mk_mods(keys)
    reason = ""
    target = None
    # A complete pulse must not replace a longer hold on the same button.
    if down and up:
        hold_id = object()
    binding = ((program or "").strip().casefold(), (title or "").strip().casefold())
    mouse_owner = hold_id if hold_id is not None else click
    mouse_holds = [(name, (binding, mouse_owner, name)) for name in mouse_names]
    key_hold = (binding, hold_id if hold_id is not None else (wclass, tuple(keys)), "keys")
    hwnd, _tid = main_window(program, title)
    if not hwnd:
        if up and not down:
            _held.pop(key_hold, None)
            for _, hold_key in mouse_holds:
                _held.pop(hold_key, None)
        return f"{program or 'target application'} not running"
    if keys:
        target = (_held_get(key_hold) if up and not down else None) or key_target(hwnd, wclass)
        if down and not up:
            _held[key_hold] = target
    if down:
        if keys and not _post_keys(target, keys, True, False, alt):
            reason = REFUSED
        for name, hold_key in mouse_holds:
            reason = _post_mouse(hwnd, name, True, False, mods, wheel_factor, click, hold_key) or reason
    if up:
        for name, hold_key in reversed(mouse_holds):
            reason = _post_mouse(hwnd, name, False, True, mods, wheel_factor, click, hold_key) or reason
        if keys and not _post_keys(target, keys, False, True, alt):
            reason = REFUSED
    return reason


# =========================================================================== SendInput
def _send_key(vk, scan, ext, up):
    flags = (0x0001 if ext else 0) | (0x0002 if up else 0)
    inp = _INPUT(type=1, u=_INPUTUNION(ki=_KEYBDINPUT(wVk=vk, wScan=scan & 0xFF, dwFlags=flags)))
    return _u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) == 1


def _send_mouse(name, up, wheel_factor=1):
    if name in MOUSE_WHEELS:
        if up:
            return True
        vertical, sign = MOUSE_WHEELS[name]
        data = (120 * max(1, int(wheel_factor)) * sign) & 0xFFFFFFFF
        mi = _MOUSEINPUT(mouseData=data, dwFlags=0x0800 if vertical else 0x1000)
    else:
        _md, _mu, _mk, xb, sd, su = MOUSE_BUTTONS[name]
        mi = _MOUSEINPUT(mouseData=xb, dwFlags=su if up else sd)
    inp = _INPUT(type=0, u=_INPUTUNION(mi=mi))
    return _u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) == 1


def input_send(items, down=True, up=True, wheel_factor=1):
    """real input (SendInput) to whatever has the focus; mouse acts where the mouse is"""
    ok = True
    if down:
        for it in items:
            if is_mouse(it):
                ok = _send_mouse(mouse_name(it), False, wheel_factor) and ok
            else:
                ok = _send_key(it[0], it[1], it[2], False) and ok
    if up:
        for it in reversed(items):
            if is_mouse(it):
                ok = _send_mouse(mouse_name(it), True, wheel_factor) and ok
            else:
                ok = _send_key(it[0], it[1], it[2], True) and ok
    return ok


# =========================================================================== focus and return
def activate(hwnd):
    """bring hwnd to the foreground from a background process; True if it worked"""
    fg = _u32.GetForegroundWindow()
    cur = _k32.GetCurrentThreadId()
    fg_tid = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(fg_tid and fg_tid != cur and _u32.AttachThreadInput(cur, fg_tid, True))
    try:
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, 9)
        # no Alt-tap trick: it puts the target in menu mode and the Alt reaches the sim
        _u32.BringWindowToTop(hwnd)
        _u32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _u32.AttachThreadInput(cur, fg_tid, False)
    for _ in range(15):
        if _u32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.01)
    return False


def focus_send(program, title, items, sim="Condor.exe", hold_s=0.05, wheel_factor=1, click=None):
    """app to the front, SendInput press - hold - release, focus back to the previous window (or the sim).
    Always a complete pulse (press and release). With a fixed click point the mouse moves there for the
    click and back afterwards. -> '' if sent, otherwise the reason."""
    hwnd, _tid = main_window(program, title)
    if not hwnd:
        return f"{program or 'target application'} not running"
    previous = _u32.GetForegroundWindow()
    if not previous or previous == hwnd:
        previous = main_window(sim)[0] if sim else None
    if _u32.GetForegroundWindow() != hwnd and not activate(hwnd):
        return f"could not bring {program} to the front"
    restore = None
    try:
        if click and _mouse(items):
            pt = fixed_point(hwnd, click)
            if pt is None:
                return NO_POINT
            restore = cursor_pos()
            if restore is None or not _u32.SetCursorPos(pt.x, pt.y):
                return "could not move the mouse to the fixed click point"
        if _u32.GetForegroundWindow() != hwnd:
            return f"{program} lost focus before input was sent"

        try:
            pressed = input_send(items, True, False, wheel_factor)
            if pressed:
                time.sleep(max(0.02, min(hold_s, 1.0)))
        finally:
            foreground = _u32.GetForegroundWindow()
            lost_focus = foreground != hwnd
            if lost_focus and foreground:
                previous = foreground
            if lost_focus:
                activate(hwnd)
            still_unfocused = _u32.GetForegroundWindow() != hwnd
            # Send the releases even if Windows refuses to restore the target.
            # Leaving injected keys down would affect subsequent physical input.
            released = input_send(items, False, True, wheel_factor)
        if not pressed or not released:
            return REFUSED
        if still_unfocused:
            return f"{program} lost focus before input could be released there"
        time.sleep(0.02)
    finally:
        if restore is not None:
            _u32.SetCursorPos(restore.x, restore.y)
        if previous and previous != hwnd and _u32.GetForegroundWindow() == hwnd:
            for _ in range(3):  # retry: the target may still be activating
                if activate(previous):
                    break
                time.sleep(0.05)
    return ""


# =========================================================================== UI Automation
class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        super().__init__()
        _ole.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(self))


_oleaut.SysFreeString.argtypes = [ctypes.c_void_p]
_ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_uia_tls = threading.local()


def _vcall(ptr, index, *args, argtypes=()):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])(ptr, *args)


def _release(p):
    if p:
        _vcall(p, 2)


def _uia():
    obj = getattr(_uia_tls, "obj", None)
    if obj is None:
        _ole.CoInitializeEx(None, 0)
        p = ctypes.c_void_p()
        hr = _ole.CoCreateInstance(
            ctypes.byref(_GUID("{FF48DBA4-60EF-4201-AA87-54103EEF594E}")),
            None,
            1,
            ctypes.byref(_GUID("{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}")),
            ctypes.byref(p),
        )
        if hr < 0 or not p.value:
            raise OSError("UI Automation not available")
        obj = _uia_tls.obj = p.value
    return obj


def _el_name(el):
    b = ctypes.c_void_p()
    if _vcall(el, 23, ctypes.byref(b), argtypes=(ctypes.POINTER(ctypes.c_void_p),)) < 0:
        return ""
    s = ctypes.wstring_at(b.value) if b.value else ""
    _oleaut.SysFreeString(b)
    return s


def _all_elements(root):
    cond, arr, out = ctypes.c_void_p(), ctypes.c_void_p(), []
    _vcall(_uia(), 21, ctypes.byref(cond), argtypes=(ctypes.POINTER(ctypes.c_void_p),))
    _vcall(root, 6, 7, cond, ctypes.byref(arr), argtypes=(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)))
    _release(cond.value)
    if arr.value:
        n = ctypes.c_int()
        _vcall(arr.value, 3, ctypes.byref(n), argtypes=(ctypes.POINTER(ctypes.c_int),))
        for i in range(n.value):
            e = ctypes.c_void_p()
            _vcall(arr.value, 4, i, ctypes.byref(e), argtypes=(ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)))
            if e.value:
                out.append(e.value)
        _release(arr.value)
    return out


# pattern id -> (interface id, vtable slot of the press method): Invoke, Toggle, LegacyIAccessible.DoDefaultAction
_PATTERNS = (
    (10000, "{FB377FBE-8EA6-46D5-9C73-6499642D3059}", 3),
    (10015, "{94CF8058-9B8D-4AB9-8BFD-4CD0A33C8C70}", 3),
    (10018, "{828055AD-355B-4435-86D5-3B51C14A9B1B}", 4),
)


def _pattern(el, pid, iid):
    """the pattern interface of an element (QueryInterface on what GetCurrentPattern returns), or None"""
    unk = ctypes.c_void_p()
    if _vcall(el, 16, pid, ctypes.byref(unk), argtypes=(ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))) < 0 or not unk.value:
        return None
    pat = ctypes.c_void_p()
    hr = _vcall(unk.value, 0, ctypes.byref(_GUID(iid)), ctypes.byref(pat), argtypes=(ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)))
    _release(unk.value)
    return pat.value if hr >= 0 and pat.value else None


def _press_element(el):
    for pid, iid, idx in _PATTERNS:
        pat = _pattern(el, pid, iid)
        if pat:
            try:
                hr = _vcall(pat, idx)
            finally:
                _release(pat)
            if hr >= 0:
                return True
    return False


def _root(hwnd):
    root = ctypes.c_void_p()
    if _vcall(_uia(), 6, hwnd, ctypes.byref(root), argtypes=(ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))) < 0:
        return None
    return root.value


def uia_press(program, title, name):
    """press a UI element by name (exact match first, else the first name containing it);
    if the app grabs the focus doing so, give it back"""
    hwnd, _ = main_window(program, title)
    if not hwnd:
        return False
    previous = _u32.GetForegroundWindow()
    try:
        root = _root(hwnd)
        if not root:
            return False
        low = (name or "").strip().lower()
        if not low:
            _release(root)
            return False
        target, exact = None, None
        elements = _all_elements(root)
        try:
            for i, e in enumerate(elements):
                n = _el_name(e).strip().lower()
                if exact is None and n == low:
                    exact, elements[i] = e, None
                elif target is None and low in n:
                    target, elements[i] = e, None
            chosen = exact or target
            ok = bool(chosen) and _press_element(chosen)
        finally:
            for e in elements + [exact, target]:
                _release(e)
            _release(root)
        if not chosen:
            log.warning(f"{TAG}: UI element '{name}' not found in {program}")
        return ok
    finally:
        if previous and not belongs_to(previous, hwnd):
            time.sleep(0.05)
            if belongs_to(_u32.GetForegroundWindow(), hwnd):
                activate(previous)


def uia_names(program, title=""):
    """names of pressable UI elements of the app (for the 'List elements...' helper)"""
    hwnd, _ = main_window(program, title)
    out = []
    root = _root(hwnd) if hwnd else None
    if root:
        elements = _all_elements(root)
        try:
            for e in elements:
                n = _el_name(e)
                if n:
                    for pid, iid, _idx in _PATTERNS[:2]:
                        pat = _pattern(e, pid, iid)
                        if pat:
                            _release(pat)
                            out.append(n)
                            break
        finally:
            for e in elements:
                _release(e)
            _release(root)
    return sorted(set(out))


# =========================================================================== delivery entry point
DELIVERIES = ("window", "focus")
DELIVERY_LABEL = {"window": "Window (no focus change)", "focus": "Focus and return"}


def deliver(program, title, delivery, items, down=True, up=True, sim="Condor.exe", hold_s=0.05, wclass="", wheel_factor=1, click=None, hold_id=None):
    """one press and/or release of the items with the chosen delivery -> (ok, message).
    Focus and return always sends a complete pulse, on the press only. click = fixed click point or None."""
    try:
        if not items:
            return False, "nothing to send"
        if delivery == "focus":
            if not down:
                return True, ""
            reason = focus_send(program, title, items, sim, hold_s, wheel_factor, click)
        else:
            reason = window_send(program, title, items, down, up, wclass, wheel_factor, click, hold_id)
        return (not reason), reason
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


def deliver_uia(program, title, name):
    """press a UI element -> (ok, message)"""
    try:
        ok = uia_press(program, title, name)
        return ok, ("" if ok else f"UI element '{name}' not found or {program} not running")
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


class _Worker:
    """one background thread that runs queued jobs in order"""

    def __init__(self, name):
        self._name = name
        self._q = queue.Queue()
        self._started = False
        self._lock = threading.Lock()

    def put(self, job):
        with self._lock:
            if not self._started:
                threading.Thread(target=self._run, name=self._name, daemon=True).start()
                self._started = True
        self._q.put(job)

    def flush(self, timeout=0.3):
        """wait (at most timeout seconds) until everything queued so far has been done"""
        if not self._started or threading.current_thread().name == self._name:
            return
        done = threading.Event()
        self._q.put(done.set)
        done.wait(timeout)

    def _run(self):
        while True:
            job = self._q.get()
            try:
                job()
            except Exception as e:  # noqa: BLE001
                log.warning(f"{TAG}: {e}")


Worker = _Worker(TAG)  # keys and mouse: fast, keeps press / release in order
UiaWorker = _Worker(TAG + "_uia")  # UI Automation (COM in one thread); may be slow, never delays a release


# =========================================================================== presets (.ini)
# [app]        program, window_title, delivery (window|focus), optional window_class, sim
# [source]     optional (used by the update command only)
# [functions]  name = value [window|focus]
#              value: key combination ('ctrl+q', 'F5'), mouse button ('mouse:left|right|middle|x1|x2',
#              'mouse:wheel_up|wheel_down|wheel_left|wheel_right', may follow modifiers: 'ctrl+mouse:left',
#              optional fixed click point in % or pixels of the window: 'mouse:left@30%,84%', 'mouse:left@176,789')
#              or a UI element ('uia:<name>')
_LINE = re.compile(r"^\s*(?P<name>[^=]+?)\s*=\s*(?P<value>.*?)\s*(?:\[(?P<opt>window|focus|keyboard)\])?\s*$", re.IGNORECASE)
LEGACY_DELIVERY = {"keyboard": "focus"}  # v3 'keyboard' (SendInput) -> Focus and return


def norm_delivery(value, default="window"):
    d = (value or "").split()[0].lower() if (value or "").split() else ""
    d = LEGACY_DELIVERY.get(d, d)
    return d if d in DELIVERIES else default


class Function:
    """one preset line:  name = value [option]"""

    def __init__(self, name, value, option=""):
        self.name, self.value = name, (value or "").strip()
        self.option = norm_delivery(option, "") if option else ""

    def kind(self):
        """'uia' | 'mouse' | 'key' (a function is a key combination, a mouse button or a UI element)"""
        v = self.value.lower()
        if v.startswith("uia:"):
            return "uia"
        return "mouse" if "mouse:" in v else "key"

    @property
    def uia_name(self):
        return self.value.split(":", 1)[1].strip() if self.kind() == "uia" else ""

    def items(self):
        return [] if self.kind() == "uia" else (parse_items(self.value) or [])

    def click(self):
        """fixed click point (x, y, pct) or None (= where the mouse is)"""
        return parse_click(self.value) if self.kind() == "mouse" else None

    @property
    def label(self):
        return f"{self.name}  ({self.value}{' [' + self.option + ']' if self.option else ''})"


def value_problem(value):
    """'' if a preset value is valid, otherwise a short explanation"""
    v = (value or "").strip()
    if not v:
        return "empty"
    low = v.lower()
    if low == "focus":
        return "'focus' (toggle focus) is not supported; use OS Actions > Set Window Focus"
    if low.startswith("uia:"):
        return "" if v[4:].strip() else "use uia:<element name>"
    if parse_items(v):
        return ""
    if "mouse:" in low:
        return (
            "unknown mouse button or click point; use mouse:left|right|middle|x1|x2|wheel_up|wheel_down|"
            "wheel_left|wheel_right, optional @x%,y% (0-100) or @x,y (pixels)"
        )
    return "unknown key; e.g. ctrl+z, F5, PgUp, q"


class Preset:
    def __init__(self, name, path, settings, functions, skipped):
        self.name, self.path = name, path
        self.settings = settings
        self.functions = functions  # valid functions only
        self.skipped = skipped  # [(name, value, reason)]

    @property
    def program(self):
        return self.settings.get("program", "")

    @property
    def window_title(self):
        return self.settings.get("window_title", "")

    @property
    def delivery(self):
        return norm_delivery(self.settings.get("delivery", "window"))

    @property
    def window_class(self):
        return self.settings.get("window_class", "")

    @property
    def sim(self):
        """the main application that gets the focus back when the previous window is unknown"""
        return self.settings.get("main_app", "") or self.settings.get("sim", "") or self.settings.get("sim_program", "")

    def function(self, name):
        """by name; exact first, then ignoring case (as gex_update_presets.ps1 does)"""
        low = (name or "").lower()
        return next((f for f in self.functions if f.name == name), None) or next((f for f in self.functions if low and f.name.lower() == low), None)

    def delivery_of(self, func):
        return func.option or self.delivery


def gex_user_folder():
    """the user folder GremlinEx uses now: <Joystick Gremlin Ex>, or - with GremlinEx's option
    "Version based Configuration Data" - a separate folder per version next to it, e.g.
    <Joystick Gremlin Ex>_1_0ex_m77t100"""
    try:
        import gremlin.util as u

        for name in ("userprofile_path", "get_user_folder"):
            if hasattr(u, name):
                p = getattr(u, name)()
                if p and os.path.isdir(p):
                    return os.path.normpath(p)
    except Exception:  # noqa: BLE001, S110
        pass
    return os.path.join(os.path.expanduser("~"), "Joystick Gremlin Ex")


def shared_folder(user=None):
    """the folder for the files of Map to Application (presets): GremlinEx's user folder, or - when
    GremlinEx uses a version based folder '<name>_<version>' - the main folder '<name>' next to it.
    Presets describe the keys of other applications, not GremlinEx, so every GremlinEx version shares
    them; the profiles store the preset values themselves."""
    user = os.path.normpath(user or gex_user_folder())
    parent, name = os.path.split(user)
    best = ""
    low = name.lower()  # Windows names are case-insensitive; GremlinEx returns the path in lower case
    try:
        for d in os.listdir(parent):
            if len(d) > len(best) and low.startswith(d.lower() + "_") and len(name) > len(d) + 1 and os.path.isdir(os.path.join(parent, d)):
                best = d
    except OSError:
        pass
    return os.path.join(parent, best) if best else user


def presets_folder():
    """<Joystick Gremlin Ex>\\gex_apps (also when GremlinEx uses a version based folder)"""
    return os.path.join(shared_folder(), "gex_apps")


def log_presets_folder():
    """one line in system.log: where the presets are read from (and why, with a version based folder)"""
    user = gex_user_folder()
    folder = os.path.join(shared_folder(user), "gex_apps")
    if os.path.normcase(os.path.dirname(folder)) == os.path.normcase(user):
        log.info(f"{TAG}: presets from {folder}")
        return folder
    log.info(f"{TAG}: presets from {folder} (shared; GremlinEx uses the version based folder {user})")
    own = os.path.join(user, "gex_apps")
    if os.path.isdir(own):
        log.warning(f"{TAG}: {own} is not used; the presets are shared in {folder}")
    return folder


def clean_value(value):
    """the value of an ini line without its inline comment (same rule as gex_update_presets.ps1):
    a comment starts at whitespace + ';' ; a value that is just ';' is the semicolon key"""
    value = (value or "").strip()
    if re.fullmatch(r";(\s+;.*)?", value):
        return ";"
    if value.startswith(";"):
        return ""
    return re.sub(r"\s+;.*$", "", value)


def read_ini(path):
    """tolerant ini reader -> {section (lower case): [(name, value)]}, or None if the file cannot be read.
    Lines without '=' and lines before the first section are skipped; names keep their case."""
    try:
        with open(path, "rb") as file:  # @IgnoreException
            raw = file.read()
    except OSError as e:
        log.warning(f"{TAG}: cannot read {path}: {e}")
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    sections, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[(.+)\]", s)
        if m:
            cur = sections.setdefault(m.group(1).strip().lower(), [])
            continue
        if cur is None or not s or s[0] in ";#" or "=" not in s:
            continue
        name, value = s.split("=", 1)
        if name.strip():
            cur.append((name.strip(), clean_value(value)))
    return sections


def read_preset(path):
    """-> Preset, or None if the file cannot be read"""
    sections = read_ini(path)
    if sections is None:
        return None
    settings = {k.lower(): v for k, v in sections.get("app", [])}
    funcs, skipped = [], []
    if "functions" in sections:
        for key, val in sections["functions"]:
            m = _LINE.match(f"{key} = {val}")
            if not m or not m.group("value"):
                skipped.append((key, val, "invalid line"))
                continue
            problem = value_problem(m.group("value"))
            if problem:
                skipped.append((m.group("name"), m.group("value"), problem))
                continue
            funcs.append(Function(m.group("name"), m.group("value"), m.group("opt") or ""))
    name = os.path.splitext(os.path.basename(path))[0]
    return Preset(name, path, settings, funcs, skipped)


def load_presets(folder=None, warn=True):
    """{app name: Preset} from gex_apps\\*.ini (files starting with _ are skipped);
    warn=True logs the skipped lines"""
    folder = folder or presets_folder()
    out = {}
    if not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder), key=str.lower):
        if fn.lower().endswith(".ini") and not fn.startswith("_"):
            p = read_preset(os.path.join(folder, fn))
            if p is not None:
                out[p.name] = p
                if warn:
                    for n, v, why in p.skipped:
                        log.warning(f"{TAG}: preset {p.name}: '{n} = {v}' skipped: {why}")
    return out
