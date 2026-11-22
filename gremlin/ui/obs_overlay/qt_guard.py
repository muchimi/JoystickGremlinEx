# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
# Module created by Lolo350 for GremlinEx
#
# Written for Gremlin Ex by Muchimi
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
