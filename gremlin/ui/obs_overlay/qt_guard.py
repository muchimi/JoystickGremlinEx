# -*- coding: utf-8; -*-
#
# Qt UI-thread / Shiboken helpers for the overlay designer.
# psygnal delivers on the emitting thread; Qt widgets must not be touched there,
# and C++ objects can already be gone while the Python wrapper still exists.
#
# 60 Hz paths must not use InvokeUiMethod: that allocates a QObject every tick.

from __future__ import annotations

from PySide6 import QtCore
from shiboken6 import Shiboken

import gremlin.util


def alive(obj) -> bool:
    if obj is None:
        return False
    try:
        return bool(Shiboken.isValid(obj))
    except Exception:
        return False


def on_owner_thread(obj) -> bool:
    """True when `obj` lives on the current thread (QObject affinity)."""
    if obj is None:
        return gremlin.util.is_ui_thread()
    try:
        return QtCore.QThread.currentThread() is obj.thread()
    except Exception:
        return False


def on_ui(obj, method, *args):
    """Run `method` on `obj`'s thread (QWidget/QObject) without InvokeUiMethod."""
    if obj is not None and not alive(obj):
        return
    if obj is not None and not on_owner_thread(obj):
        if args:
            def _run(m=method, a=args, o=obj):
                if alive(o):
                    m(*a)

            QtCore.QTimer.singleShot(0, obj, _run)
        else:
            QtCore.QTimer.singleShot(0, obj, method)
        return
    if obj is None and not gremlin.util.is_ui_thread():
        if args:
            gremlin.util.InvokeUiMethod(method, *args)
        else:
            gremlin.util.InvokeUiMethod(method)
        return
    if args:
        method(*args)
    else:
        method()


def later(obj, method):
    """Post `method` to `obj`'s event loop, cancelled if `obj` is destroyed."""
    if not alive(obj):
        return
    if on_owner_thread(obj):
        QtCore.QTimer.singleShot(0, obj, method)
        return
    QtCore.QTimer.singleShot(0, obj, method)
