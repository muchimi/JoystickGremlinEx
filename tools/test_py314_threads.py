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
