#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lightweight JG Ex remote-control client simulator.

Joins the same UDP multicast group the master uses for discovery and answers
`identify` with `identify_client` — so you can test Target Client(s) / Refresh
without rebuilding gremlinEx.exe.

Requires: msgpack (project .venv has it)

Examples:
  .\\.venv\\Scripts\\python.exe scripts\\remote_client_sim.py --name Lolo-SERVER
  .\\.venv\\Scripts\\python.exe scripts\\remote_client_sim.py --name Lolo-SERVER --version m77T50L2Rb --video
  .\\.venv\\Scripts\\python.exe scripts\\remote_client_sim.py --name Fake-PC --iface 192.168.50.10
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import threading
import time
import uuid

try:
    import msgpack
except ImportError:
    print("msgpack is required. Use the project venv:", file=sys.stderr)
    print(r"  .\.venv\Scripts\python.exe scripts\remote_client_sim.py ...", file=sys.stderr)
    sys.exit(1)

MULTICAST_GROUP = "224.3.29.72"
MULTICAST_TTL = 2
DEFAULT_PORT = 6012
VIDEO_MAGIC = b"GEXV"
VIDEO_CODEC_JPEG = 1
VIDEO_HEADER = struct.Struct("!4sBBHHI")


def start_video_server(port: int, stop: threading.Event, label: str) -> threading.Thread:
    """Serve a simple animated MJPEG test pattern (same framing as gremlin.remote_video)."""

    def _jpeg_frame(seq: int) -> bytes:
        from PySide6 import QtCore, QtGui

        w, h = 640, 360
        img = QtGui.QImage(w, h, QtGui.QImage.Format_RGB32)
        # Animated bar so the overlay clearly shows a live feed
        t = (seq % 60) / 60.0
        r = int(40 + 80 * t)
        g = int(90 + 100 * (1.0 - t))
        b = 140
        img.fill(QtGui.QColor(r, g, b))
        p = QtGui.QPainter(img)
        p.setPen(QtGui.QColor(255, 255, 255))
        p.setFont(QtGui.QFont("Segoe UI", 22, QtGui.QFont.Bold))
        p.drawText(img.rect(), int(QtCore.Qt.AlignCenter), f"{label}\nsim frame {seq}")
        x = int((seq * 11) % max(1, w - 40))
        p.fillRect(x, h // 2 - 8, 40, 16, QtGui.QColor(255, 220, 40))
        p.end()
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        img.save(buf, "JPG", 70)
        jpeg = bytes(buf.data())
        header = VIDEO_HEADER.pack(VIDEO_MAGIC, 1, VIDEO_CODEC_JPEG, w, h, seq & 0xFFFFFFFF)
        return header + struct.pack("!I", len(jpeg)) + jpeg

    def _client(conn: socket.socket, addr):
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"video client connected from {addr[0]}")
            seq = 0
            while not stop.is_set():
                packet = _jpeg_frame(seq)
                try:
                    conn.sendall(packet)
                except OSError:
                    break
                seq += 1
                time.sleep(1.0 / 15.0)
        finally:
            try:
                conn.close()
            except OSError:
                pass
            print(f"video client disconnected {addr[0]}")

    def _serve():
        try:
            from PySide6 import QtWidgets

            # QImage needs an app instance for fonts/plugins on some setups
            if QtWidgets.QApplication.instance() is None:
                QtWidgets.QApplication([])
        except Exception as err:
            print(f"video serve needs PySide6: {err}", file=sys.stderr)
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(4)
        sock.settimeout(0.5)
        print(f"video publisher on TCP {port}")
        sessions = []
        try:
            while not stop.is_set():
                try:
                    conn, addr = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                t = threading.Thread(target=_client, args=(conn, addr), daemon=True)
                t.start()
                sessions.append(t)
        finally:
            sock.close()

    thread = threading.Thread(target=_serve, daemon=True, name="SimVideoServe")
    thread.start()
    return thread


def pack(data: dict) -> bytes:
    return msgpack.packb(data, use_bin_type=True)


def unpack(raw: bytes) -> dict | None:
    try:
        data = msgpack.unpackb(raw, raw=False)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def make_client_payload(
    client_id: int,
    client_name: str,
    custom_name: str | None,
    version: str,
    video_enabled: bool,
    video_port: int,
) -> dict:
    return {
        "client_id": client_id,
        "client_name": client_name,
        "client_custom": custom_name or "",
        "client_version": version,
        "client_timestamp": time.time(),
        "video_enabled": bool(video_enabled),
        "video_port": int(video_port) if video_enabled else 0,
        "host_ip": "",
    }


def make_packet(
    action: str,
    sender_id: int,
    sender_name: str,
    payload: dict | None = None,
    to: int = 0,
) -> dict:
    block = {
        "action": action,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "to": to,
    }
    if payload is not None:
        block["data"] = payload
    return block


def open_listen_socket(port: int, iface: str | None) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    sock.bind(("", port))

    group = socket.inet_aton(MULTICAST_GROUP)
    if iface:
        mreq = struct.pack("4s4s", group, socket.inet_aton(iface))
    else:
        mreq = struct.pack("4sL", group, socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(0.5)
    return sock


def open_send_socket(iface: str | None) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    ttl = struct.pack("b", MULTICAST_TTL)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
    # Do NOT bind to the RPC port — that collides with the listener (same bug as the real client).
    if iface:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
    return sock


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulate a JG Ex remote client for discovery testing")
    ap.add_argument("--name", default="Sim-Client", help="Custom display name (shows in Target Client list)")
    ap.add_argument("--host-name", default=None, help="Hostname field (default: local hostname)")
    ap.add_argument("--version", default="sim-m77T50L2Rb", help="Client version string")
    ap.add_argument("--client-id", type=int, default=None, help="Unique client id (default: derived from --name)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Multicast port (default {DEFAULT_PORT})")
    ap.add_argument("--iface", default=None, help="Local IPv4 to join/send on (multi-NIC machines)")
    ap.add_argument("--video", action="store_true", help="Advertise video + serve a test MJPEG feed on --video-port")
    ap.add_argument("--video-port", type=int, default=6013, help="Video TCP port when --video is set")
    ap.add_argument("--announce", action="store_true", help="Send identify_client once at startup")
    ap.add_argument("--quiet", action="store_true", help="Less console noise")
    args = ap.parse_args()

    host_name = args.host_name or socket.gethostname()
    custom_name = args.name
    display = custom_name or host_name
    # Stable synthetic id from name so restarts don't look like a new machine unless --client-id is set
    if args.client_id is not None:
        client_id = args.client_id
    else:
        client_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"jgex-sim:{custom_name}:{host_name}").int & ((1 << 63) - 1)

    payload = make_client_payload(
        client_id=client_id,
        client_name=host_name,
        custom_name=custom_name,
        version=args.version,
        video_enabled=args.video,
        video_port=args.video_port,
    )

    listen = open_listen_socket(args.port, args.iface)
    send = open_send_socket(args.iface)
    target = (MULTICAST_GROUP, args.port)
    stop_video = threading.Event()
    video_thread = None
    if args.video:
        video_thread = start_video_server(args.video_port, stop_video, display)

    def emit(action: str) -> None:
        pkt = make_packet(action, client_id, display, payload)
        send.sendto(pack(pkt), target)
        if not args.quiet:
            print(f"-> {action} as [{display}] id={client_id} ver={args.version}")

    print(
        f"Sim client listening on {MULTICAST_GROUP}:{args.port}"
        f"{' iface=' + args.iface if args.iface else ''}"
    )
    print(f"  name={display!r} host={host_name!r} id={client_id} version={args.version}")
    if args.video:
        print(f"  video_enabled port={args.video_port} (test pattern publisher)")
    print("Waiting for master Refresh / identify... (Ctrl+C to quit)")

    if args.announce:
        emit("identify_client")

    try:
        while True:
            try:
                raw, addr = listen.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as err:
                print(f"recv error: {err}", file=sys.stderr)
                continue

            data = unpack(raw)
            if not data:
                continue

            action = data.get("action")
            sender = data.get("sender_name") or data.get("sender_id")
            if action == "identify":
                if not args.quiet:
                    print(f"<- identify from {addr[0]} ({sender})")
                emit("identify_client")
            elif action in ("identify_client", "unregister_client", "hb") and not args.quiet:
                peer = (data.get("data") or {}).get("client_custom") or data.get("sender_name")
                print(f"<- {action} from {addr[0]} ({peer})")
    except KeyboardInterrupt:
        print("\nShutting down...")
        try:
            emit("unregister_client")
        except OSError:
            pass
    finally:
        stop_video.set()
        listen.close()
        send.close()
        if video_thread is not None:
            video_thread.join(timeout=1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
