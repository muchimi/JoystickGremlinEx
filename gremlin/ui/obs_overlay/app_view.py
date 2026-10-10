# -*- coding: utf-8; -*-
#
# Live local window capture for overlay Application widgets.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from PySide6 import QtGui

from gremlin.singleton_decorator import SingletonDecorator

syslog = logging.getLogger("system")

_HWND_CACHE_TTL_S = 1.0
_LAUNCH_COOLDOWN_S = 12.0


def _window_exe(hwnd: int) -> str:
    path = _window_exe_path(hwnd)
    return os.path.basename(path) if path else ""


def _window_exe_path(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return str(buf.value or "")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return ""


def list_application_windows() -> list[dict[str, Any]]:
    """Visible top-level windows as {hwnd, title, exe, path} for the Application picker."""
    from gremlin.remote_video import list_top_windows

    windows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hwnd, title in list_top_windows():
        name = str(title or "").strip()
        if not name:
            continue
        path = _window_exe_path(int(hwnd))
        exe = os.path.basename(path) if path else ""
        key = (name.casefold(), exe.casefold())
        if key in seen:
            continue
        seen.add(key)
        windows.append({"hwnd": int(hwnd), "title": name, "exe": exe, "path": path})
    windows.sort(key=lambda item: (item["title"].casefold(), item["exe"].casefold()))
    return windows


def window_choice_label(title: str, exe: str) -> str:
    name = str(title or "").strip() or "(untitled)"
    proc = str(exe or "").strip()
    return f"{name}  ({proc})" if proc else name


def launch_application(path, args="") -> tuple[bool, str]:
    """Start an executable with optional CLI arguments. Returns (ok, error)."""
    import shlex
    import subprocess

    raw = str(path or "").strip().strip('"')
    if not raw:
        return False, "Set a Launch path first."
    if not os.path.isfile(raw):
        return False, f"Launch path not found:\n{raw}"
    extra: list[str] = []
    argv = str(args or "").strip()
    if argv:
        try:
            extra = shlex.split(argv, posix=os.name != "nt")
        except ValueError as err:
            return False, f"Could not parse arguments: {err}"
    cwd = os.path.dirname(raw) or None
    try:
        kwargs = {
            "cwd": cwd,
            "close_fds": True,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([raw, *extra], **kwargs)
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: launch failed {raw}: {err}")
        return False, str(err)
    return True, ""


def _hwnd_alive(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return bool(user32.IsWindow(int(hwnd)) and user32.IsWindowVisible(int(hwnd)) and not user32.IsIconic(int(hwnd)))
    except Exception:
        return False


def resolve_application_hwnd(title: str, exe: str, cached_hwnd: int = 0) -> int:
    title_key = str(title or "").strip().casefold()
    exe_key = str(exe or "").strip().casefold()
    if not title_key and not exe_key:
        return 0
    if cached_hwnd and _hwnd_alive(cached_hwnd):
        return int(cached_hwnd)
    windows = list_application_windows()

    def _exe_ok(item: dict[str, Any]) -> bool:
        return (not exe_key) or str(item.get("exe") or "").casefold() == exe_key

    if title_key:
        for item in windows:
            if str(item.get("title") or "").casefold() == title_key and _exe_ok(item):
                return int(item["hwnd"])
        for item in windows:
            if title_key in str(item.get("title") or "").casefold() and _exe_ok(item):
                return int(item["hwnd"])
    if exe_key:
        for item in windows:
            if str(item.get("exe") or "").casefold() == exe_key:
                return int(item["hwnd"])
    return 0


@SingletonDecorator
class ApplicationViewTracker:
    """Background GDI capture of a chosen local window; QPixmap is built on the UI thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._slots: dict[str, dict[str, Any]] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_queued = False

    def retain(self, widget_ids: set[str] | None):
        wanted = set(widget_ids or ())
        with self._lock:
            for widget_id in list(self._slots):
                if widget_id not in wanted:
                    self._slots.pop(widget_id, None)
            empty = not self._slots
        if empty:
            self._stop.set()
            self._wake.set()
            return
        self._ensure_thread()

    def sample(self, item: dict[str, Any] | None) -> int:
        if not item:
            return 0
        widget_id = str(item.get("id") or "")
        if not widget_id:
            return 0
        style = item.get("style") or {}
        title = str(style.get("window_title") or "").strip()
        exe = str(style.get("window_exe") or "").strip()
        launch_path = str(style.get("launch_path") or "").strip()
        launch_args = str(style.get("launch_args") or "")
        try:
            max_w = max(160, min(1280, int(item.get("w") or 480) * 2))
        except (TypeError, ValueError):
            max_w = 960
        with self._lock:
            slot = self._slots.get(widget_id)
            if slot is None:
                slot = {
                    "title": title,
                    "exe": exe,
                    "launch_path": launch_path,
                    "launch_args": launch_args,
                    "max_w": max_w,
                    "hwnd": 0,
                    "checked_at": 0.0,
                    "launched_at": 0.0,
                    "generation": 0,
                    "image": None,
                    "pixmap": None,
                    "pixmap_gen": -1,
                    "status": (
                        "Select a running application"
                        if not (title or exe or launch_path)
                        else "Looking for window…"
                    ),
                }
                self._slots[widget_id] = slot
            slot["title"] = title
            slot["exe"] = exe
            slot["launch_path"] = launch_path
            slot["launch_args"] = launch_args
            slot["max_w"] = max_w
            if not title and not exe and not launch_path:
                slot["status"] = "Select a running application"
            generation = int(slot.get("generation") or 0)
        if title or exe or launch_path:
            self._ensure_thread()
        return generation

    def pixmap(self, item: dict[str, Any] | None) -> QtGui.QPixmap | None:
        if not item:
            return None
        widget_id = str(item.get("id") or "")
        if not widget_id:
            return None
        with self._lock:
            slot = self._slots.get(widget_id)
            if not slot:
                return None
            generation = int(slot.get("generation") or 0)
            cached = slot.get("pixmap")
            if cached is not None and not cached.isNull() and int(slot.get("pixmap_gen") or -1) == generation:
                return cached
            image = slot.get("image")
        if image is None or image.isNull():
            return None
        pixmap = QtGui.QPixmap.fromImage(image)
        if pixmap.isNull():
            return None
        with self._lock:
            slot = self._slots.get(widget_id)
            if slot is not None:
                slot["pixmap"] = pixmap
                slot["pixmap_gen"] = generation
        return pixmap

    def status(self, item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        widget_id = str(item.get("id") or "")
        with self._lock:
            slot = self._slots.get(widget_id)
            if not slot:
                style = (item.get("style") or {}) if item else {}
                if not (style.get("window_title") or style.get("window_exe") or style.get("launch_path")):
                    return "Select a running application"
                return "Looking for window…"
            return str(slot.get("status") or "")

    def _ensure_thread(self):
        thread = self._thread
        if thread is not None and thread.is_alive():
            self._wake.set()
            return
        # paintEvent is a C++ → Python callback. On Python 3.14, constructing or
        # starting threading.Thread there raises RuntimeError("thread.__init__()
        # not called") and Qt reports it as a QWidget.paintEvent override error.
        if self._start_queued:
            return
        self._start_queued = True
        from PySide6 import QtCore

        app = QtCore.QCoreApplication.instance()
        if app is not None:
            QtCore.QTimer.singleShot(0, self._start_thread)
            return
        self._start_thread()

    def _start_thread(self):
        self._start_queued = False
        thread = self._thread
        if thread is not None and thread.is_alive():
            self._wake.set()
            return
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="overlay-app-view", daemon=True)
        self._thread = thread
        try:
            thread.start()
        except RuntimeError as err:
            self._thread = None
            syslog.warning(f"OBS OVERLAY: application capture thread failed to start: {err}")

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                jobs = [
                    (
                        widget_id,
                        str(slot.get("title") or ""),
                        str(slot.get("exe") or ""),
                        str(slot.get("launch_path") or ""),
                        str(slot.get("launch_args") or ""),
                        int(slot.get("max_w") or 960),
                        int(slot.get("hwnd") or 0),
                        float(slot.get("checked_at") or 0.0),
                        float(slot.get("launched_at") or 0.0),
                    )
                    for widget_id, slot in self._slots.items()
                    if slot.get("title") or slot.get("exe") or slot.get("launch_path")
                ]
            if not jobs:
                self._wake.wait(0.25)
                self._wake.clear()
                with self._lock:
                    if not any(
                        s.get("title") or s.get("exe") or s.get("launch_path") for s in self._slots.values()
                    ):
                        return
                continue
            now = time.monotonic()
            from gremlin.remote_video import grab_window_image

            for widget_id, title, exe, launch_path, launch_args, max_w, cached_hwnd, checked_at, launched_at in jobs:
                match_exe = exe or (os.path.basename(launch_path) if launch_path else "")
                hwnd = cached_hwnd if (now - checked_at) < _HWND_CACHE_TTL_S and _hwnd_alive(cached_hwnd) else 0
                if not hwnd:
                    hwnd = resolve_application_hwnd(title, match_exe, cached_hwnd)
                if not hwnd and launch_path and (now - launched_at) >= _LAUNCH_COOLDOWN_S:
                    running = False
                    try:
                        import gremlin.shared_state

                        running = bool(gremlin.shared_state.is_running)
                    except Exception:
                        running = False
                    if running:
                        ok, _err = launch_application(launch_path, launch_args)
                        launched_at = now if ok else launched_at
                        if ok:
                            hwnd = resolve_application_hwnd(title, match_exe, 0)
                image = grab_window_image(hwnd, max_w) if hwnd else None
                with self._lock:
                    slot = self._slots.get(widget_id)
                    if slot is None:
                        continue
                    slot["hwnd"] = int(hwnd or 0)
                    slot["checked_at"] = now
                    slot["launched_at"] = launched_at
                    if image is not None and not image.isNull():
                        slot["image"] = image
                        slot["generation"] = int(slot.get("generation") or 0) + 1
                        slot["status"] = ""
                    elif not slot.get("image"):
                        if not hwnd and launch_path:
                            slot["status"] = "Launching…" if (now - launched_at) < _LAUNCH_COOLDOWN_S else "Window not found"
                        else:
                            slot["status"] = "Window not found" if not hwnd else "Unable to capture"
            self._stop.wait(0.08)
