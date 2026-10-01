# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""LAN HTTP + WebSocket hybrid overlay stream for tablet/phone control."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import socket
import statistics
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from PySide6 import QtCore, QtGui, QtNetwork, QtWebSockets
from shiboken6 import Shiboken

from .model import (
    WS_DEFAULT_PORT,
    WS_RESERVED_PORTS,
    is_interactive_overlay,
    normalize_ws_fit_mode,
)
from .overlay_window import OverlayView
from .widgets import chroma_fill_color

syslog = logging.getLogger("system")

WEB_ROOT = os.path.join(os.path.dirname(__file__), "web")
FRAME_CAP_FPS = 30.0
JPEG_QUALITY = 70
INPUT_METRIC_WINDOW = 64


def lan_ipv4_addresses() -> list[str]:
    """Best-effort LAN IPv4 list for inspector URL display (excludes loopback)."""
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            addr = info[4][0]
            if addr and not addr.startswith("127.") and addr not in found:
                found.append(addr)
    except Exception:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            addr = probe.getsockname()[0]
            if addr and not addr.startswith("127.") and addr not in found:
                found.insert(0, addr)
        finally:
            probe.close()
    except Exception:
        pass
    return found or ["127.0.0.1"]


def port_is_bindable(port: int, host: str = "0.0.0.0") -> bool:
    """True if nothing is listening on the port (does not bind — avoids Windows reuse races)."""
    if port in WS_RESERVED_PORTS or port < 1024 or port > 65535:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.2)
        result = sock.connect_ex((host if host not in ("0.0.0.0", "") else "127.0.0.1", int(port)))
        # 0 = something accepted the connection → occupied
        return result != 0
    except OSError:
        return True
    finally:
        try:
            sock.close()
        except Exception:
            pass


def find_free_http_ws_ports(preferred: int | None = None) -> tuple[int, int]:
    """Suggest consecutive free ports for HTTP then WebSocket (best-effort; start still binds)."""
    start = int(preferred if preferred is not None else WS_DEFAULT_PORT)
    start = max(1024, min(65533, start))
    for http_port in range(start, 65534):
        ws_port = http_port + 1
        if http_port in WS_RESERVED_PORTS or ws_port in WS_RESERVED_PORTS:
            continue
        if port_is_bindable(http_port) and port_is_bindable(ws_port):
            return http_port, ws_port
    raise RuntimeError("No free HTTP/WebSocket port pair available")


class _OverlayHttpHandler(SimpleHTTPRequestHandler):
    """Serves static web/ assets, session JSON, JPEG frames, and input POSTs."""

    session_info: dict[str, Any] = {}
    owner: Any = None  # OverlayWebsocketSession

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory or WEB_ROOT, **kwargs)

    def log_message(self, format: str, *args):  # noqa: A003 — stdlib API
        # Frame polling hits ~30/s — keep those out of syslog.
        try:
            path = urlparse(self.path).path
        except Exception:
            path = ""
        if path in ("/frame.jpg", "/frame.jpeg"):
            return
        if path in ("/api/input", "/api/input/", "/api/hit", "/api/hit/"):
            return
        syslog.debug("OBS OVERLAY WS HTTP: " + (format % args))

    def _send_bytes(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/api/session", "/api/session/"):
            body = json.dumps(self.session_info).encode("utf-8")
            self._send_bytes(200, body, "application/json; charset=utf-8")
            return
        if path in ("/api/hit", "/api/hit/"):
            owner = self.owner
            qs = parse_qs(parsed.query or "")
            try:
                x = float((qs.get("x") or ["0"])[0])
                y = float((qs.get("y") or ["0"])[0])
            except (TypeError, ValueError):
                self._send_bytes(400, b'{"empty":true}', "application/json")
                return
            empty = True
            if owner is not None:
                empty = bool(owner.query_point_empty(x, y))
            body = json.dumps({"empty": empty}).encode("utf-8")
            self._send_bytes(200, body, "application/json; charset=utf-8")
            return
        if path in ("/frame.jpg", "/frame.jpeg"):
            owner = self.owner
            jpeg = owner.latest_jpeg() if owner is not None else None
            if not jpeg:
                self._send_bytes(503, b"no frame", "text/plain; charset=utf-8")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            seq = getattr(owner, "_frame_seq", 0) if owner is not None else 0
            self.send_header("X-Gex-Frame-Seq", str(seq))
            self.end_headers()
            self.wfile.write(jpeg)
            return
        if path in ("/", "/index.html"):
            self.path = "/index.html"
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/input", "/api/input/"):
            self.send_error(404)
            return
        owner = self.owner
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_bytes(400, b'{"ok":false}', "application/json")
            return
        if owner is None:
            self._send_bytes(503, b'{"ok":false}', "application/json")
            return
        owner.queue_input(payload if isinstance(payload, dict) else {})
        self._send_bytes(200, b'{"ok":true}', "application/json")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        # Keep the shell fresh so Home Screen / Safari pick up Apple meta + manifest.
        try:
            path = urlparse(self.path).path
        except Exception:
            path = ""
        if path in (
            "/",
            "/index.html",
            "/manifest.webmanifest",
            "/styles.css",
            "/app.js",
        ):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()


def _try_listen_http(http_port: int, handler_cls) -> ThreadingHTTPServer | None:
    if http_port in WS_RESERVED_PORTS or http_port < 1024 or http_port > 65535:
        return None
    try:
        http = ThreadingHTTPServer(("0.0.0.0", http_port), handler_cls)
        http.daemon_threads = True
        return http
    except OSError:
        return None


def _try_listen_ws(ws_port: int) -> QtWebSockets.QWebSocketServer | None:
    if ws_port in WS_RESERVED_PORTS or ws_port < 1024 or ws_port > 65535:
        return None
    server = QtWebSockets.QWebSocketServer(
        "GremlinEx-Overlay",
        QtWebSockets.QWebSocketServer.SslMode.NonSecureMode,
    )
    if not server.listen(QtNetwork.QHostAddress.Any, ws_port):
        try:
            server.close()
        except Exception:
            pass
        return None
    return server


def _try_listen_pair(
    http_port: int,
    handler_cls,
) -> tuple[ThreadingHTTPServer, QtWebSockets.QWebSocketServer | None, int, int] | None:
    """Bind HTTP on http_port; WS on http_port+1 when possible (HTTP-only is OK)."""
    http = _try_listen_http(http_port, handler_cls)
    if http is None:
        return None
    ws = _try_listen_ws(http_port + 1)
    ws_port = (http_port + 1) if ws is not None else 0
    return http, ws, http_port, ws_port

class OverlayWebsocketSession(QtCore.QObject):
    """Offscreen OverlayView + HTTP static server + QWebSocketServer for one page."""

    clients_changed = QtCore.Signal(int)
    status_changed = QtCore.Signal()

    def __init__(self, scene, page_id: str, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.page_id = str(page_id)
        self._http: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._ws_server: QtWebSockets.QWebSocketServer | None = None
        self._clients: list[QtWebSockets.QWebSocket] = []
        self._view: OverlayView | None = None
        self._http_port = 0
        self._ws_port = 0
        self._running = False
        self._frame_seq = 0
        self._frame_timer = QtCore.QTimer(self)
        self._frame_timer.setInterval(int(1000.0 / FRAME_CAP_FPS))
        self._frame_timer.timeout.connect(self._on_frame_tick)
        self._last_jpeg: bytes | None = None
        self._jpeg_lock = threading.Lock()
        self._last_frame_key: tuple | None = None
        self._encode_ms_samples: list[float] = []
        self._input_ms_samples: list[float] = []
        self._frames_sent = 0
        self._inputs_handled = 0
        self._last_error = ""
        self._verbose = False

    def latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._last_jpeg

    def _point_is_empty(self, x: float, y: float) -> bool:
        """True when (x,y) is not on an interactive control."""
        from .bindings import widget_accepts_touch
        from .widgets import value_from_point

        view = self._view
        if view is None or not Shiboken.isValid(view):
            return True
        item = self.scene.hit_test(float(x), float(y), self.page_id)
        if not item or not widget_accepts_touch(item):
            return True
        # Keyboard/mouse pad: only keycaps count as occupied (gaps are empty).
        if item.get("type") == "input_display":
            return value_from_point(item, float(x), float(y)) is None
        return False

    def query_point_empty(self, x: float, y: float) -> bool:
        """Thread-safe hit probe for the HTTP long-press toolbar gesture."""
        if QtCore.QThread.currentThread() is self.thread():
            return self._point_is_empty(x, y)
        box: dict[str, bool] = {"empty": True}
        done = threading.Event()

        def _run():
            try:
                box["empty"] = self._point_is_empty(x, y)
            except Exception:
                box["empty"] = True
            finally:
                done.set()

        QtCore.QTimer.singleShot(0, _run)
        if not done.wait(0.2):
            return True
        return bool(box["empty"])

    def queue_input(self, payload: dict):
        """Marshal pointer input from the HTTP thread onto the UI thread."""
        data = dict(payload) if isinstance(payload, dict) else {}
        QtCore.QTimer.singleShot(0, lambda d=data: self._handle_input(None, d))


    @property
    def running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def http_port(self) -> int:
        return self._http_port

    @property
    def ws_port(self) -> int:
        return self._ws_port

    @property
    def urls(self) -> list[str]:
        if not self._http_port:
            return []
        return [f"http://{ip}:{self._http_port}/" for ip in lan_ipv4_addresses()]

    def status_text(self) -> str:
        if not self._running:
            return "Websocket: stopped"
        n = self.client_count
        label = "client" if n == 1 else "clients"
        return f"Websocket: {n} {label}"

    def metrics_snapshot(self) -> dict[str, Any]:
        def _pct(samples: list[float], p: float) -> float | None:
            if not samples:
                return None
            ordered = sorted(samples)
            idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
            return ordered[idx]

        return {
            "clients": self.client_count,
            "frames_sent": self._frames_sent,
            "inputs": self._inputs_handled,
            "encode_ms_p50": _pct(self._encode_ms_samples, 50),
            "encode_ms_p95": _pct(self._encode_ms_samples, 95),
            "input_ms_p50": _pct(self._input_ms_samples, 50),
            "input_ms_p95": _pct(self._input_ms_samples, 95),
            "last_error": self._last_error,
            "http_port": self._http_port,
            "ws_port": self._ws_port,
        }

    def start(self) -> bool:
        if self._running:
            return True
        canvas = self.scene.canvas_for(self.page_id)
        preferred = int(canvas.get("ws_port") or WS_DEFAULT_PORT)
        preferred = max(1024, min(65533, preferred))

        self._view = OverlayView(
            self.scene,
            interactive=False,
            touch_output=True,
            parent=None,
            page_id=self.page_id,
        )
        self._view.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
        self._view.resize(*self._view.canvas_size())
        # Realize Qt paint resources without putting a window on a monitor.
        self._view.setVisible(False)
        self._view.attach_bus()
        self._view._dirty_body_ids = None
        self._view._frame_pm = None
        self._view._static_pm = None
        self._view._static_key = None

        handler = type(
            "OverlayHttpHandlerBound",
            (_OverlayHttpHandler,),
            {"session_info": {}, "owner": self},
        )

        bound = None
        last_err = ""
        for http_port in range(preferred, min(preferred + 64, 65534)):
            try:
                bound = _try_listen_pair(http_port, handler)
            except Exception as err:
                last_err = str(err)
                bound = None
            if bound is not None:
                break
        if bound is None:
            self._last_error = last_err or f"Could not bind HTTP near port {preferred}"
            syslog.error(f"OBS OVERLAY WS: {self._last_error}")
            self._teardown_view()
            self.status_changed.emit()
            return False

        self._http, self._ws_server, http_port, ws_port = bound
        if self._ws_server is not None:
            self._ws_server.setParent(self)
            self._ws_server.newConnection.connect(self._on_new_connection)
        self._http_port = http_port
        self._ws_port = ws_port
        self._refresh_session_info(handler)

        # Persist the port that actually bound (may have bumped past preferred).
        if http_port != int(canvas.get("ws_port") or 0):
            canvas["ws_port"] = http_port
            self.scene._dirty = True

        self._http_thread = threading.Thread(
            target=self._http.serve_forever,
            name=f"overlay-ws-http-{self.page_id[:8]}",
            daemon=True,
        )
        self._http_thread.start()

        self._running = True
        self._last_error = ""
        self._frame_timer.start()
        # Encode a first frame immediately so /frame.jpg is ready before any client.
        QtCore.QTimer.singleShot(0, lambda: self._on_frame_tick(force=True))
        mode = f"HTTP :{http_port}" + (f" WS :{ws_port}" if ws_port else " (WS unavailable)")
        syslog.info(
            f"OBS OVERLAY WS: page {self.page_id} listening {mode} "
            f"({', '.join(self.urls)})"
        )
        self.status_changed.emit()
        self.clients_changed.emit(0)
        return True

    def stop(self):
        if not self._running and self._view is None and self._http is None:
            return
        self._running = False
        self._frame_timer.stop()
        for sock in list(self._clients):
            try:
                sock.close()
            except Exception:
                pass
        self._clients.clear()
        if self._ws_server is not None:
            try:
                self._ws_server.close()
            except Exception:
                pass
            self._ws_server = None
        self._stop_http()
        self._teardown_view()
        self._http_port = 0
        self._ws_port = 0
        self._last_jpeg = None
        self._last_frame_key = None
        syslog.info(f"OBS OVERLAY WS: page {self.page_id} stopped")
        self.clients_changed.emit(0)
        self.status_changed.emit()

    def _refresh_session_info(self, handler_cls=None):
        canvas = self.scene.canvas_for(self.page_id)
        cw = max(64, int(canvas.get("width") or 1280))
        ch = max(64, int(canvas.get("height") or 720))
        info = {
            "page_id": self.page_id,
            "http_port": self._http_port,
            "ws_port": self._ws_port,
            "ws_path": "/",
            "frame_url": "/frame.jpg",
            "input_url": "/api/input",
            "canvas_w": cw,
            "canvas_h": ch,
            "fit": normalize_ws_fit_mode(canvas.get("ws_fit_mode")),
            "device_preset": str(canvas.get("ws_device_preset") or "custom"),
            "interactive": is_interactive_overlay(canvas),
            "urls": self.urls,
        }
        target = handler_cls or (
            self._http.RequestHandlerClass if self._http is not None else None
        )
        if target is not None:
            target.session_info = info
            target.owner = self

    def _stop_http(self):
        if self._http is not None:
            try:
                self._http.shutdown()
            except Exception:
                pass
            try:
                self._http.server_close()
            except Exception:
                pass
            self._http = None
        self._http_thread = None

    def _teardown_view(self):
        view = self._view
        self._view = None
        if view is None:
            return
        try:
            view.detach_from_scene()
        except Exception:
            pass
        try:
            view.deleteLater()
        except Exception:
            pass

    def _on_new_connection(self):
        if self._ws_server is None:
            return
        while self._ws_server.hasPendingConnections():
            sock = self._ws_server.nextPendingConnection()
            if sock is None:
                continue
            sock.textMessageReceived.connect(
                lambda msg, s=sock: self._on_text_message(s, msg)
            )
            sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))
            self._clients.append(sock)
            peer = sock.peerAddress().toString()
            syslog.info(f"OBS OVERLAY WS: client connected from {peer} (n={len(self._clients)})")
            self._send_json(
                sock,
                {
                    "type": "hello",
                    "page_id": self.page_id,
                    "canvas_w": self._view.canvas_size()[0] if self._view else 1280,
                    "canvas_h": self._view.canvas_size()[1] if self._view else 720,
                    "interactive": is_interactive_overlay(self.scene.canvas_for(self.page_id)),
                },
            )
            self.clients_changed.emit(len(self._clients))
            self.status_changed.emit()
            # Force a fresh frame for the new client.
            self._last_frame_key = None
            self._on_frame_tick(force=True)

    def _on_disconnected(self, sock: QtWebSockets.QWebSocket):
        if sock in self._clients:
            self._clients.remove(sock)
        try:
            sock.deleteLater()
        except Exception:
            pass
        syslog.info(f"OBS OVERLAY WS: client disconnected (n={len(self._clients)})")
        if self._view is not None and hasattr(self._view, "release_touch"):
            try:
                self._view.release_touch()
            except Exception:
                pass
        self.clients_changed.emit(len(self._clients))
        self.status_changed.emit()

    def _send_json(self, sock: QtWebSockets.QWebSocket, payload: dict):
        try:
            sock.sendTextMessage(json.dumps(payload, separators=(",", ":")))
        except Exception as err:
            self._last_error = str(err)

    def _broadcast_json(self, payload: dict):
        raw = json.dumps(payload, separators=(",", ":"))
        for sock in list(self._clients):
            try:
                sock.sendTextMessage(raw)
            except Exception:
                pass

    def _broadcast_binary(self, data: bytes):
        ba = QtCore.QByteArray(data)
        for sock in list(self._clients):
            try:
                sock.sendBinaryMessage(ba)
            except Exception:
                pass

    def _on_text_message(self, sock: QtWebSockets.QWebSocket, message: str):
        try:
            payload = json.loads(message)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        msg_type = str(payload.get("type") or "").casefold()
        if msg_type in ("hello", "ready", "auth"):
            # Open LAN: no PIN gate. Ack ready so the client can start input.
            self._send_json(
                sock,
                {
                    "type": "ready",
                    "interactive": is_interactive_overlay(self.scene.canvas_for(self.page_id)),
                    "fit": normalize_ws_fit_mode(
                        self.scene.canvas_for(self.page_id).get("ws_fit_mode")
                    ),
                },
            )
            return
        if msg_type == "input":
            self._handle_input(sock, payload)
            return
        if msg_type == "ping":
            self._send_json(sock, {"type": "pong", "t_server": time.monotonic()})

    def _handle_input(self, sock: QtWebSockets.QWebSocket | None, payload: dict):
        t0 = time.perf_counter()
        view = self._view
        if view is None or not Shiboken.isValid(view) or view._touch is None:
            return
        event = str(payload.get("event") or payload.get("action") or "down").casefold()
        try:
            x = float(payload.get("x"))
            y = float(payload.get("y"))
        except (TypeError, ValueError):
            return
        pointer_id = payload.get("pointerId", payload.get("pointer_id", "ws0"))
        pos = QtCore.QPointF(x, y)
        handled = False
        try:
            if event in ("down", "press", "pointerdown"):
                handled = bool(view._touch.press(pointer_id, pos))
            elif event in ("move", "pointermove"):
                handled = bool(view._touch.move(pointer_id, pos))
            elif event in ("up", "release", "pointerup", "cancel", "pointercancel"):
                handled = bool(view._touch.release(pointer_id))
        except Exception as err:
            self._last_error = f"input: {err}"
            syslog.debug(f"OBS OVERLAY WS: input error: {err}")
            return
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._inputs_handled += 1
        self._input_ms_samples.append(elapsed_ms)
        if len(self._input_ms_samples) > INPUT_METRIC_WINDOW:
            self._input_ms_samples = self._input_ms_samples[-INPUT_METRIC_WINDOW:]
        if self._verbose or elapsed_ms >= 15.0:
            syslog.info(
                f"OBS OVERLAY WS: input {event} handled={handled} {elapsed_ms:.2f}ms "
                f"(p50={statistics.median(self._input_ms_samples):.2f})"
            )
        if sock is not None:
            ack = {
                "type": "input_ack",
                "pointerId": pointer_id,
                "t_server": time.monotonic(),
                "t_client": payload.get("t_client"),
                "ms": round(elapsed_ms, 3),
                "ok": handled,
            }
            self._send_json(sock, ack)

    def _on_frame_tick(self, force: bool = False):
        # Always encode while the LAN server is up so /frame.jpg works without a WS client.
        if not self._running:
            return
        view = self._view
        if view is None or not Shiboken.isValid(view):
            return
        self._refresh_session_info()
        dirty = getattr(view, "_dirty_body_ids", None)
        if (
            not force
            and self._last_jpeg is not None
            and dirty is not None
            and len(dirty) == 0
        ):
            return
        t0 = time.perf_counter()
        try:
            frame = view._ensure_frame_pm()
        except Exception as err:
            self._last_error = f"frame: {err}"
            syslog.warning(f"OBS OVERLAY WS: frame encode failed: {err}")
            return
        if frame is None or frame.isNull():
            self._last_error = "frame: empty pixmap"
            return
        image = frame.toImage()
        if image.isNull():
            return
        # JPEG has no alpha. Qt's RGB conversion composites transparent pixels onto
        # black, which turns widget clear-rects into opaque black boxes. Flatten
        # onto the page chroma so holes match the live windowed overlay.
        canvas = self.scene.canvas_for(self.page_id)
        chroma = chroma_fill_color(canvas)
        if chroma.alpha() < 255:
            chroma = QtGui.QColor(chroma.red(), chroma.green(), chroma.blue(), 255)
        flat = QtGui.QImage(image.size(), QtGui.QImage.Format.Format_RGB32)
        flat.fill(chroma.rgb())
        painter = QtGui.QPainter(flat)
        try:
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
            painter.drawImage(0, 0, image)
        finally:
            if painter.isActive():
                painter.end()
        image = flat.convertToFormat(QtGui.QImage.Format.Format_RGB888)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        ok = image.save(buffer, "JPG", JPEG_QUALITY)
        buffer.close()
        if not ok:
            self._last_error = "frame: JPEG encode failed"
            return
        jpeg = bytes(buffer.data())
        if not jpeg:
            return
        encode_ms = (time.perf_counter() - t0) * 1000.0
        self._encode_ms_samples.append(encode_ms)
        if len(self._encode_ms_samples) > INPUT_METRIC_WINDOW:
            self._encode_ms_samples = self._encode_ms_samples[-INPUT_METRIC_WINDOW:]
        self._frame_seq += 1
        self._frames_sent += 1
        with self._jpeg_lock:
            self._last_jpeg = jpeg
        if self._clients:
            meta = {
                "type": "frame",
                "seq": self._frame_seq,
                "w": frame.width(),
                "h": frame.height(),
                "t_encode_ms": round(encode_ms, 3),
                "bytes": len(jpeg),
            }
            self._broadcast_json(meta)
            self._broadcast_binary(jpeg)
        if self._verbose and self._frames_sent % 60 == 0:
            snap = self.metrics_snapshot()
            syslog.info(
                f"OBS OVERLAY WS: metrics clients={snap['clients']} "
                f"encode_p50={snap['encode_ms_p50']} input_p95={snap['input_ms_p95']}"
            )


# Silence unused mimetypes import warning by ensuring common types are registered.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")
