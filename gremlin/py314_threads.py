"""Python 3.14 + Qt: keep logging / Thread.__init__ off broken DummyThreads.

Foreign Qt threads and half-init Thread subclasses make
threading.current_thread() return an object whose _initialized is False.
logging.LogRecord then asserts Thread.__init__() not called and profile
activate / the excepthook take each other down.
"""

from __future__ import annotations

import threading

_APPLIED = False


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    _orig_current = threading.current_thread
    _orig_init = threading.Thread.__init__

    def _usable(thread) -> bool:
        return thread is not None and bool(getattr(thread, "_initialized", False))

    def current_thread():
        try:
            thread = _orig_current()
        except Exception:
            thread = None
        if _usable(thread):
            return thread
        ident = threading.get_ident()
        try:
            thread = threading._active.get(ident)
            if _usable(thread):
                return thread
        except Exception:
            pass
        dummy = object.__new__(threading._DummyThread)
        dummy._target = None
        dummy._name = f"Dummy-{ident}"
        dummy._args = ()
        dummy._kwargs = {}
        dummy._daemonic = True
        dummy._ident = ident
        dummy._native_id = None
        dummy._initialized = True
        dummy._started = threading.Event()
        dummy._started.set()
        dummy._stderr = None
        dummy._invoke_excepthook = None
        try:
            dummy._os_thread_handle = threading._ThreadHandle()
        except Exception:
            dummy._os_thread_handle = None
        try:
            with threading._active_limbo_lock:
                existing = threading._active.get(ident)
                if _usable(existing):
                    return existing
                threading._active[ident] = dummy
        except Exception:
            pass
        return dummy

    def thread_init(
        self,
        group=None,
        target=None,
        name=None,
        args=(),
        kwargs=None,
        *,
        daemon=None,
        context=None,
    ):
        if daemon is None:
            try:
                daemon = bool(getattr(current_thread(), "daemon", False))
            except Exception:
                daemon = False
        return _orig_init(
            self,
            group=group,
            target=target,
            name=name,
            args=args,
            kwargs=kwargs,
            daemon=daemon,
            context=context,
        )

    threading.current_thread = current_thread
    threading.currentThread = current_thread
    threading.Thread.__init__ = thread_init


apply()
