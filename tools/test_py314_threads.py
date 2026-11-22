# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
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
"""Python 3.14 DummyThread / logging must not assert on activate."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin import py314_threads  # noqa: E402


def test_logging_survives_uninitialized_current_thread() -> None:
    py314_threads.apply()
    ident = threading.get_ident()
    broken = object.__new__(threading.Thread)
    threading.Thread._initialized  # class default False
    with threading._active_limbo_lock:
        prior = threading._active.get(ident)
        threading._active[ident] = broken
    try:
        assert getattr(broken, "_initialized", False) is False
        logging.getLogger("system").info("py314 thread patch ok")
        t = threading.current_thread()
        assert t.name
        threading.Thread(target=lambda: None, name="py314-spawn")
    finally:
        with threading._active_limbo_lock:
            if prior is not None:
                threading._active[ident] = prior
            else:
                threading._active.pop(ident, None)


if __name__ == "__main__":
    test_logging_survives_uninitialized_current_thread()
    print("PASS")
