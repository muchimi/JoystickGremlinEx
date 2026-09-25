"""Python 3.14 + Qt: keep logging / Thread.__init__ off broken DummyThreads.

Foreign Qt threads and half-init Thread subclasses make
threading.current_thread() return an object whose _initialized is False.
logging.LogRecord then asserts Thread.__init__() not called and profile
activate / the excepthook take each other down.

Never call the stock current_thread() from this patch — it constructs
_DummyThread via Thread.__init__, which can recurse through our wrapper
and leave a thread that logging.makeRecord then asserts on.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading

_APPLIED = False


def ensure_runtime_tempdirs() -> None:
    """Create %TEMP% (and a version-named child) so FileLock mkdir cannot WinError 3."""
    roots = [tempfile.gettempdir(), os.environ.get("TEMP"), os.environ.get("TMP")]
    for d in roots:
        if d:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass
    try:
        import gremlin.version

        base = str(getattr(gremlin.version, "APPLICATION_BASE", "") or "").strip()
        if base:
            os.makedirs(os.path.join(tempfile.gettempdir(), base), exist_ok=True)
    except Exception:
        pass


def _usable(thread) -> bool:
    return thread is not None and bool(getattr(thread, "_initialized", False))


def _dummy(ident: int):
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
    dummy._context = None
    try:
        dummy._os_thread_handle = threading._ThreadHandle()
    except Exception:
        dummy._os_thread_handle = None
    return dummy


def _patch_thread_properties() -> None:
    """3.14 Thread.name/daemon/ident assert _initialized. Logging reads .name."""

    def _wrap(prop_name: str, fallback):
        prop = getattr(threading.Thread, prop_name, None)
        if not isinstance(prop, property) or prop.fget is None:
            return
        orig = prop.fget

        def getter(self):
            if not getattr(self, "_initialized", False):
                return fallback(self)
            try:
                return orig(self)
            except AssertionError:
                return fallback(self)

        setattr(
            threading.Thread,
            prop_name,
            property(getter, prop.fset, prop.fdel, prop.__doc__),
        )

    _wrap("name", lambda self: getattr(self, "_name", None) or f"Dummy-{id(self)}")
    _wrap("daemon", lambda self: bool(getattr(self, "_daemonic", True)))
    _wrap("ident", lambda self: getattr(self, "_ident", None))
    _wrap("native_id", lambda self: getattr(self, "_native_id", None))


def _patch_log_record() -> None:
    orig = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        try:
            return orig(*args, **kwargs)
        except Exception:
            try:
                rec = orig.__wrapped__(*args, **kwargs) if hasattr(orig, "__wrapped__") else None
            except Exception:
                rec = None
            if rec is not None:
                return rec
            rec = object.__new__(logging.LogRecord)
            rec.name = str(args[0]) if args else "system"
            rec.levelno = int(args[1]) if len(args) > 1 else logging.ERROR
            rec.pathname = str(args[2]) if len(args) > 2 else ""
            rec.lineno = int(args[3]) if len(args) > 3 else 0
            rec.msg = args[4] if len(args) > 4 else ""
            rec.args = args[5] if len(args) > 5 else ()
            rec.exc_info = args[6] if len(args) > 6 else None
            rec.funcName = kwargs.get("func") or ""
            rec.sinfo = kwargs.get("sinfo")
            rec.threadName = "Dummy"
            rec.thread = threading.get_ident()
            rec.processName = "MainProcess"
            rec.process = os.getpid()
            rec.created = 0.0
            rec.msecs = 0.0
            rec.relativeCreated = 0.0
            rec.levelname = logging.getLevelName(rec.levelno)
            rec.filename = os.path.basename(rec.pathname) if rec.pathname else ""
            rec.module = ""
            rec.exc_text = None
            rec.stack_info = None
            rec.taskName = None
            rec.msg = rec.msg
            return rec

    logging.setLogRecordFactory(factory)


def safe_log(logger, level: int, msg: str, *args) -> None:
    try:
        logger.log(level, msg, *args)
    except Exception:
        try:
            print(msg if not args else (msg % args), file=sys.stderr)
        except Exception:
            pass


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    ensure_runtime_tempdirs()
    _patch_thread_properties()
    _patch_log_record()

    _orig_init = threading.Thread.__init__

    def current_thread():
        ident = threading.get_ident()
        try:
            thread = threading._active.get(ident)
            if _usable(thread):
                return thread
        except Exception:
            pass
        dummy = _dummy(ident)
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
