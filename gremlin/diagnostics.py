# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - GremlinEx is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Crash trail for Python, Qt, and native failures.

Python exceptions and Qt warnings go to fault.log. Breadcrumbs are appended to
trace.log immediately and snapshotted to breadcrumbs.log. A native filter
writes native-crash.txt (registers and return addresses) and native-crash.dmp
when the process dies in native code.
"""

from __future__ import annotations

from gremlin.util import debug_only

import ctypes
import faulthandler
import logging
import os
import sys
import threading
import time
import traceback
import winreg
from collections import deque

syslog = logging.getLogger("system")

_RING_LIMIT = 200
_FLUSH_SEC = 0.25
_lock = threading.Lock()
_ring: deque[str] = deque(maxlen=_RING_LIMIT)
_fault_handle = None
_trace_handle = None
_breadcrumb_path = ""
_stop = threading.Event()
_installed = False
_previous_excepthook = None
_previous_thread_hook = None
_previous_unraisable_hook = None

_QT_PATTERN = "[%{time hh:mm:ss.zzz} tid=%{threadid} %{type}] %{category}: %{message}"


def prepare() -> None:
    """Set the Qt message format before QApplication exists."""
    os.environ.setdefault("QT_MESSAGE_PATTERN", _QT_PATTERN)


def install(data_path: str) -> None:
    """Arm the crash trail. Call once, after fault.log is configured."""
    global _installed, _breadcrumb_path
    global _previous_excepthook, _previous_thread_hook, _previous_unraisable_hook
    if _installed:
        return
    _installed = True
    os.makedirs(data_path, exist_ok=True)
    fault_path = os.path.join(data_path, "fault.log")
    _breadcrumb_path = os.path.join(data_path, "breadcrumbs.log")
    _open_fault_handler(fault_path)
    _open_trace(data_path)
    _install_python_hooks()
    _install_qt_handler()
    _install_native(data_path)
    _register_local_dumps(data_path)
    thread = threading.Thread(target=_flush_loop, name="gremlin-diagnostics", daemon=True)
    thread.start()
    breadcrumb("diagnostics on")
    syslog.info(
        "DIAG: crash trail on. fault.log, trace.log and breadcrumbs.log are in the settings folder. "
        "native-crash.txt and native-crash.dmp are written in "
        f"{data_path} when native code faults."
    )

@debug_only
def breadcrumb(label: str) -> None:
    """Record one short event. Safe to call from any thread."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        line = f"{stamp} tid={_os_thread_id()} ui={int(_on_ui_thread())} {label}\n"
        with _lock:
            _ring.append(line)
            handle = _trace_handle
        if handle is not None:
            handle.write(line)
            handle.flush()
    except Exception:
        pass


def _os_thread_id() -> int:
    try:
        return int(ctypes.windll.kernel32.GetCurrentThreadId())
    except Exception:
        return threading.get_ident()


def _on_ui_thread() -> bool:
    try:
        from gremlin.util import is_ui_thread

        return bool(is_ui_thread())
    except Exception:
        return False


def _open_fault_handler(fault_path: str) -> None:
    global _fault_handle
    _fault_handle = open(fault_path, "a", encoding="utf-8", buffering=1)
    if not faulthandler.is_enabled():
        try:
            faulthandler.enable(_fault_handle, all_threads=True, c_stack=True)
        except TypeError:
            # c_stack is not supported on this Python version
            faulthandler.enable(_fault_handle, all_threads=True)


def _open_trace(data_path: str) -> None:
    global _trace_handle
    _trace_handle = open(os.path.join(data_path, "trace.log"), "a", encoding="utf-8", buffering=1)


def _install_native(data_path: str) -> None:
    try:
        import gremlin.native_fault as native_fault

        if not native_fault.install(data_path):
            syslog.warning("DIAG: native crash capture did not arm")
    except Exception as err:
        syslog.warning(f"DIAG: native crash capture did not arm: {err}")


def _write_fault(text: str) -> None:
    handle = _fault_handle
    if handle is None:
        return
    try:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
        handle.flush()
    except Exception:
        pass


def _install_python_hooks() -> None:
    global _previous_excepthook, _previous_thread_hook, _previous_unraisable_hook
    _previous_excepthook = sys.excepthook
    _previous_thread_hook = getattr(threading, "excepthook", None)
    _previous_unraisable_hook = getattr(sys, "unraisablehook", None)
    sys.excepthook = _main_excepthook
    if _previous_thread_hook is not None:
        threading.excepthook = _thread_excepthook
    if _previous_unraisable_hook is not None:
        sys.unraisablehook = _unraisable_hook


def _format_exception(exc_type, exc_value, exc_traceback) -> str:
    return "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))


def _main_excepthook(exc_type, exc_value, exc_traceback):
    if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
        if _previous_excepthook is not None:
            _previous_excepthook(exc_type, exc_value, exc_traceback)
        return
    text = _format_exception(exc_type, exc_value, exc_traceback)
    breadcrumb(f"uncaught {getattr(exc_type, '__name__', exc_type)}")
    _write_fault(f"\n--- uncaught {time.strftime('%Y-%m-%d %H:%M:%S')} tid={_os_thread_id()} ---\n{text}")
    _flush()
    if _previous_excepthook is not None and _previous_excepthook is not _main_excepthook:
        _previous_excepthook(exc_type, exc_value, exc_traceback)


def _thread_excepthook(args):
    text = _format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    name = getattr(args.thread, "name", "?")
    breadcrumb(f"thread {name} {getattr(args.exc_type, '__name__', args.exc_type)}")
    _write_fault(
        f"\n--- thread {name} {time.strftime('%Y-%m-%d %H:%M:%S')} tid={_os_thread_id()} ---\n{text}"
    )
    _flush()
    try:
        syslog.critical(f"Uncaught exception on thread {name}:\n{text}")
    except Exception:
        pass
    if _previous_thread_hook is not None and _previous_thread_hook is not _thread_excepthook:
        _previous_thread_hook(args)


def _unraisable_hook(unraisable):
    text = _format_exception(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback)
    err = getattr(unraisable, "err_msg", None) or "unraisable"
    breadcrumb(f"unraisable {err}")
    _write_fault(f"\n--- {err} {time.strftime('%Y-%m-%d %H:%M:%S')} tid={_os_thread_id()} ---\n{text}")
    _flush()
    if _previous_unraisable_hook is not None and _previous_unraisable_hook is not _unraisable_hook:
        _previous_unraisable_hook(unraisable)


def _install_qt_handler() -> None:
    try:
        from PySide6 import QtCore
    except Exception as err:
        syslog.warning(f"DIAG: Qt message handler not installed: {err}")
        return

    warning = QtCore.QtMsgType.QtWarningMsg
    critical = QtCore.QtMsgType.QtCriticalMsg
    fatal = QtCore.QtMsgType.QtFatalMsg

    def _handler(mode, context, message):
        try:
            mode_value = int(mode)
        except Exception:
            return
        if mode_value not in (int(warning), int(critical), int(fatal)):
            return
        kind = "warning"
        if mode_value == int(critical):
            kind = "critical"
        elif mode_value == int(fatal):
            kind = "fatal"
        category = ""
        try:
            category = str(getattr(context, "category", "") or "")
        except Exception:
            category = ""
        text = f"QT {kind} tid={_os_thread_id()} {category}: {message}"
        breadcrumb(text[:180])
        _write_fault(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        interesting = kind in ("critical", "fatal") or any(
            word in str(message).casefold() for word in ("thread", "qobject", "deleted", "timer")
        )
        if interesting:
            _write_fault("--- recent breadcrumbs ---\n")
            _write_fault("".join(_snapshot()))
        _flush()
        try:
            syslog.error(text)
        except Exception:
            pass

    QtCore.qInstallMessageHandler(_handler)


def _register_local_dumps(dump_dir: str) -> None:
    names = {os.path.basename(sys.executable), "gremlinex.exe"}
    for name in names:
        if not name:
            continue
        path = rf"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\{name}"
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "DumpFolder", 0, winreg.REG_SZ, dump_dir)
                winreg.SetValueEx(key, "DumpType", 0, winreg.REG_DWORD, 2)
                winreg.SetValueEx(key, "DumpCount", 0, winreg.REG_DWORD, 3)
        except OSError as err:
            syslog.warning(f"DIAG: could not register local dumps for {name}: {err}")


def _snapshot() -> list[str]:
    with _lock:
        return list(_ring)


def _flush() -> None:
    from gremlin.util import safeReplace
    if not _breadcrumb_path:
        return
    lines = _snapshot()
    tmp = _breadcrumb_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        safeReplace(tmp, _breadcrumb_path) # @IgnoreException
    except Exception:
        pass


def _flush_loop() -> None:
    while not _stop.wait(_FLUSH_SEC):
        _flush()
