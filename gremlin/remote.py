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

from __future__ import annotations  # deprecated with python 3.14+

import enum
import html
import ipaddress
import json
import logging
import queue
import re
import socket
import socketserver
import struct
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable  # noqa: UP035

import msgpack
from lxml import etree as ElementTree
from psygnal import Signal
from PySide6 import QtCore, QtNetwork, QtWidgets

import gremlin.base_classes
import gremlin.config
import gremlin.event_handler
import gremlin.gamepad_handling
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.sendinput
import gremlin.shared_state
import gremlin.singleton_decorator
import gremlin.types
import gremlin.util
from gremlin.error import VJoyError
from gremlin.network import REMOTE_CONTROL_MULTICAST_GROUP
from gremlin.types import DeviceType, GamePadOutput, MouseButton, VjoyAction
from gremlin.util import get_guid, safe_format, safe_read

syslog = logging.getLogger("system")

_PROBE_REQUEST = "connection_test"
_PROBE_REPLY = "connection_test_reply"
_PROBE_MULTICAST = "connection_test_multicast"
_PROBE_BROADCAST_PING = "broadcast_test_ping"
_PROBE_BROADCAST_PONG = "broadcast_test_pong"
_VIRTUAL_OUTPUT_ACTIONS = ("axis", "relative_axis", "relative_Axis", "button", "toggle", "hat", "gamepad")


def _unpack_remote_packet(raw_data):
    # MessagePack is binary. Trailing whitespace bytes may be valid values.
    try:
        data = msgpack.unpackb(raw_data)
    except msgpack.UnpackException, ValueError, TypeError:
        return None
    return data if isinstance(data, dict) else None


def _hat_direction(value):
    """Restore MessagePack arrays to the tuples required by vJoy."""
    if value is None or value is False:
        return (0, 0)
    if isinstance(value, (tuple, list)) and len(value) == 2 and value[0] in (-1, 0, 1) and value[1] in (-1, 0, 1):
        return tuple(value)
    raise ValueError(f"Invalid remote hat direction: {value!r}")


def _open_remote_output(device_id):
    """Resolve a portable Maestro identity, GUID, or legacy vJoy ID."""
    joystick_handling = gremlin.joystick_handling
    config = gremlin.config.Configuration()
    verbose = config.verbose_mode_remote
    failover = config.virtual_output_failover
    if verbose:
        syslog.info(f"REMOTE: opening remote output for device_id [{device_id}]")
    try:
        if isinstance(device_id, dict):
            device = joystick_handling.match_maestro_output(device_id)
            if device is None:
                syslog.debug("REMOTE: no unique Maestro output for %s", device_id)
                return None
            return joystick_handling.get_output_device(device.device_guid)

        key = joystick_handling.parse_virtual_device_key(device_id)
        if key is None or isinstance(key, int) and not 1 <= key <= 16:
            syslog.warning(f"REMOTE: invalid virtual output id [{device_id}]")
            return None
        target = joystick_handling.get_output_target(key)
        if target is None and isinstance(key, str):
            # Older profiles can reference a vJoy GUID that predates the output map.
            key = joystick_handling.vjoy_id_from_guid(key, None)
            if key is None:
                syslog.debug("REMOTE: unknown virtual output [%s]", device_id)
                return None
            target = joystick_handling.get_output_target(key)
        if target is not None and target.kind == "maestro":
            return target.maestro

        vjoy_id = target.out_id if target is not None else key
        if not isinstance(vjoy_id, int) or not 1 <= vjoy_id <= 16:
            syslog.debug("REMOTE: unknown virtual output [%s]", device_id)
            return None

        if config.vjoy_installed:
            try:
                return joystick_handling.VJoyProxy()[vjoy_id]
            except VJoyError as err:
                if not failover:
                    syslog.error(f"REMOTE: native vJoy output [{vjoy_id}] unavailable and failover is disabled. Error: {err}")

        if failover:
            # Legacy packets carry a logical vJoy ID. Match the bridge's stable
            # service ID so an unrelated device in the same slot cannot receive it.
            device = joystick_handling.match_maestro_output({"maestro_id": f"gex-{vjoy_id}", "name": "", "gamepad": False})
            if device is not None:
                return joystick_handling.get_output_device(device.device_guid)
        syslog.warning(f"REMOTE: no available output for output device index [{device_id}] - failover mode enabled: [{failover}]")
    except Exception as err:  #  # noqa: BLE001
        syslog.warning(f"REMOTE: cannot open output device [{device_id}]: {err}")
    return None


class GremlinServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    allow_reuse_address = True
    daemon_threads = True
    max_packet_size = 65535

    # Reuse explicitly daemonized workers: high-rate axis and mouse packets
    # must not create an OS thread on every datagram (including Qt callers).
    request_worker_count = 4

    def __init__(self, *args, **kwargs):
        self._request_queues = [queue.SimpleQueue() for _ in range(self.request_worker_count)]
        self._request_workers = []
        self._request_workers_lock = threading.Lock()
        self._request_workers_stopping = False
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        """Keep each sender's datagrams on one worker to preserve arrival order."""
        try:
            with self._request_workers_lock:
                if self._request_workers_stopping:
                    self.shutdown_request(request)
                    return
                while len(self._request_workers) < self.request_worker_count:
                    request_queue = self._request_queues[len(self._request_workers)]
                    worker = threading.Thread(
                        target=self._request_worker,
                        args=(request_queue,),
                        name="remote-packet-worker",
                        daemon=bool(self.daemon_threads),
                    )
                    worker.start()
                    self._request_workers.append(worker)
                request_queue = self._request_queues[hash(client_address) % len(self._request_workers)]
                request_queue.put((request, client_address))
        except Exception:  # noqa: BLE001
            # A partially started pool can still preserve ordering. Only fall
            # back to synchronous handling when no worker could be started.
            with self._request_workers_lock:
                if self._request_workers_stopping:
                    self.shutdown_request(request)
                    return
                if self._request_workers:
                    self.request_worker_count = len(self._request_workers)
                    request_queue = self._request_queues[hash(client_address) % len(self._request_workers)]
                    request_queue.put((request, client_address))
                    return
            self.process_request_thread(request, client_address)

    def _request_worker(self, request_queue):
        while True:
            item = request_queue.get()
            if item is None:
                return
            request, client_address = item
            try:
                self.process_request_thread(request, client_address)
            except Exception:  # noqa: BLE001
                # Even an error-notification callback must not kill the worker.
                syslog.exception("RPC: packet worker failed")

    def server_close(self):
        with self._request_workers_lock:
            if not self._request_workers_stopping:
                self._request_workers_stopping = True
                # Accepted requests finish before the workers exit. As before,
                # daemon request handlers do not block application shutdown.
                for request_queue in self._request_queues[: len(self._request_workers)]:
                    request_queue.put(None)
        super().server_close()

    def handle_timeout(self):
        import gremlin.event_handler

        el = gremlin.event_handler.EventListener()
        el.remote_control_socket_timeout.emit()  # fire the event to indicate we had a timeout
        return super().handle_timeout()

    def handle_error(self, request, client_address):
        import sys
        import traceback

        err = sys.exc_info()[1]
        if err is not None:
            syslog.error(f"RPC: socket handler error from {client_address}: {err}")
            syslog.debug("".join(traceback.format_exception(*sys.exc_info())))
        el = gremlin.event_handler.EventListener()
        el.remote_control_socket_error.emit()  # fire the event to indicate we had a timeout
        # return super().handle_error(request, client_address)


class GremlinSocketHandler(socketserver.BaseRequestHandler):
    """handles remote input from a gremlin client on the network

    received network events are processed here

    """

    def handle(self):
        data = _unpack_remote_packet(self.request[0])
        if data is None:
            return

        action = data.get("action")
        if action in (_PROBE_REQUEST, _PROBE_MULTICAST, _PROBE_BROADCAST_PING, _PROBE_BROADCAST_PONG):
            self._handle_probe(action, data)
            return

        host_ip = ""
        try:
            host_ip = str(self.client_address[0] or "")
        except Exception:  # noqa: BLE001
            host_ip = ""
        try:
            remote_client.handle(data, peer_ip=host_ip)
        except (KeyError, TypeError, ValueError) as err:
            syslog.warning(f"RPC: invalid packet from {host_ip}: {err}")
        except Exception as err:
            syslog.error(f"RPC: handle failed from {host_ip}: {err}")
            raise

    def _handle_probe(self, action, data):
        nonce = data.get("nonce")
        if not isinstance(nonce, bytes) or len(nonce) != 16:
            if action in (_PROBE_BROADCAST_PING, _PROBE_BROADCAST_PONG):
                syslog.debug("RPC: Check Broadcast ignored %s from %s with an invalid nonce", action, self.client_address)
            return
        if action == _PROBE_REQUEST:
            self._reply_to_probe(nonce, data.get("multicast") is True)
            return

        port = self.server.server_address[1]
        if action == _PROBE_MULTICAST:
            remote_server.connection_test_multicast.emit(nonce, port)
            return

        sender = data.get("sender_id")
        local_id = remote_client.clientId
        if type(sender) is not int or not 0 < sender < 2**64:
            syslog.debug("RPC: Check Broadcast [%s] ignored %s from %s with an invalid sender ID", nonce.hex(), action, self.client_address)
            return
        if sender == local_id:
            syslog.debug("RPC: Check Broadcast [%s] ignored %s from %s with this instance's sender ID", nonce.hex(), action, self.client_address)
            return
        peer_ip, peer_port = self.client_address
        if action == _PROBE_BROADCAST_PING:
            config = gremlin.config.Configuration()
            syslog.info("RPC: Check Broadcast [%s] received ping from %s:%d on UDP port %d", nonce.hex(), peer_ip, peer_port, port)
            if not config.enable_remote_control:
                syslog.info("RPC: Check Broadcast [%s] skipped pong because client remote control is disabled", nonce.hex())
                return
            name = remote_client.customName or config.client_name or remote_client.clientName
            self._send_probe_reply(
                {
                    "action": _PROBE_BROADCAST_PONG,
                    "nonce": nonce,
                    "sender_id": local_id,
                    "sender_name": name[:128],
                    "to": sender,
                },
                # The ping uses the regular ephemeral send socket. Replies go to the server's RPC listener.
                (peer_ip, port),
            )
        elif data.get("to") == local_id:
            name = data.get("sender_name")
            name = " ".join(name[:128].split()) if isinstance(name, str) else ""
            syslog.info(
                "RPC: Check Broadcast [%s] received pong from %s:%d on UDP port %d (client %r)",
                nonce.hex(),
                peer_ip,
                peer_port,
                port,
                name or sender,
            )
            remote_server.broadcast_test_reply.emit(nonce, port, sender, name, peer_ip)
        else:
            syslog.debug("RPC: Check Broadcast [%s] ignored pong from %s:%d addressed to another instance", nonce.hex(), peer_ip, peer_port)

    def _send_probe_reply(self, data, address):
        broadcast_reply = data["action"] == _PROBE_BROADCAST_PONG
        try:
            self.request[1].sendto(msgpack.packb(data), address)
        except OSError as err:
            if broadcast_reply:
                syslog.warning("RPC: Check Broadcast [%s] could not send pong to %s:%d: %s", data["nonce"].hex(), *address, err)
            else:
                syslog.debug("RPC: could not send connection test reply: %s", err)
        else:
            if broadcast_reply:
                syslog.info("RPC: Check Broadcast [%s] sent unicast pong to %s:%d", data["nonce"].hex(), *address)

    def _reply_to_probe(self, nonce: bytes, multicast: bool):
        self._send_probe_reply({"action": _PROBE_REPLY, "nonce": nonce}, self.client_address)
        if multicast:
            # Use the same outbound socket and interface as normal remote control.
            remote_client.send({"action": _PROBE_MULTICAST, "nonce": nonce})


class RPCGremlin:
    """Remote UDP multicast listener"""

    MULTICAST_GROUP = REMOTE_CONTROL_MULTICAST_GROUP
    MULTICAST_TTL = 2  # max jumps

    def __init__(self):
        self._lock = threading.Lock()
        self._listener = None
        self._endpoint = None
        self._startup_ready = False
        self._warning_issued = False
        self._shutting_down = False

    @property
    def startup_ready(self):
        return self._startup_ready

    def enable_startup(self):
        """Allows socket startup once the application has initialized logging and devices."""
        with self._lock:
            self._startup_ready = True

    def _start(self, port):
        server = None
        try:
            server = GremlinServer(("", port), GremlinSocketHandler)
            group = socket.inet_aton(RPCGremlin.MULTICAST_GROUP)
            mreq = struct.pack("=4sI", group, socket.INADDR_ANY)
            server.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            thread = threading.Thread(target=self._serve, args=(server,), name="RPCRunner", daemon=True)
            thread.start()
            self._listener = server, thread
            syslog.info(
                "RPC: listening on %s:%d (UDP), joined multicast group %s on the OS default IPv4 interface",
                *server.server_address,
                self.MULTICAST_GROUP,
            )
        except Exception as err:  # noqa: BLE001
            if server is not None:
                server.server_close()
            syslog.error(f"RPC: could not listen on UDP port {port}: {err}")

    @staticmethod
    def _serve(server):
        try:
            server.serve_forever(poll_interval=0.1)
        except Exception:  # noqa: BLE001
            syslog.exception("RPC: listener failed")
        finally:
            server.server_close()

    @property
    def listening_port(self):
        listener = self._listener
        if listener is not None:
            server, thread = listener
            if thread.is_alive():
                return server.server_address[1]
        return None

    @property
    def running(self):
        return self.listening_port is not None

    def start(self):
        """Ensures the listener is running before sending remote traffic."""
        # A request handler can send a reply while the server is shutting down.
        # Keep the running check outside the lock that protects shutdown.
        if not self.running:
            self.reconfigure()

    def reconfigure(self):
        """Applies the configured listener state and UDP port."""
        with self._lock:
            if not self._startup_ready or self._shutting_down:
                return
            config = gremlin.config.Configuration()
            if not config.remoteEnabled():
                self._stop()
                if not self._warning_issued:
                    syslog.info("Remote control/broadcast disabled - Gremlin listener not started")
                    self._warning_issued = True
            else:
                port = config.server_port
                endpoint = (port, config.broadcast_host_ip)
                if not self.running or self._endpoint != endpoint:
                    self._stop(release_vjoy=False)
                    self._start(port)
                    self._endpoint = endpoint
                self._warning_issued = False

    def stop(self):
        """Stops the listener and waits until its socket is closed."""
        with self._lock:
            self._warning_issued = False
            self._stop()

    def shutdown(self):
        with self._lock:
            self._shutting_down = True
            self._stop()

    def _stop(self, *, release_vjoy=True):
        if self._listener is None:
            return

        server, thread = self._listener
        if thread.is_alive():
            server.shutdown()
        # safeJoin skips daemon threads. The replacement must wait for server_close().
        thread.join()
        self._listener = None
        syslog.info("RPC: listener stopped.")

        if release_vjoy:
            try:
                gremlin.joystick_handling.VJoyProxy().reset()
            except Exception as err:  # noqa: BLE001
                syslog.error(f"RPC: Failed to reset VJoyProxy during cleanup: {err}")


# class RPCGremlin_v0:
#     """GEX remote UDP multicast listener"""

#     MULTICAST_GROUP = "224.3.29.72"  # multicast group
#     # multicast time to live
#     MULTICAST_TTL = 2

#     def __init__(self):
#         # self._address = "0.0.0.0"
#         # self._server_address = "localhost"
#         config = gremlin.config.Configuration()
#         self._port = config.server_port
#         self._server = None
#         self._running = False
#         self._thread_event = threading.Event()
#         self._thread = None
#         self._server_thread = None
#         self._keep_running = False
#         self._warning_issued = False

#         el = gremlin.event_handler.EventListener()
#         el.shutdown.connect(self.stop)

#     def _thread_runner(self):
#         import struct

#         syslog.info("Starting GEX listener...")
#         self._server = GremlinServer(("", self._port), GremlinSocketHandler)
#         self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=False)
#         self._server_thread.daemon = True
#         try:
#             self._server_thread.start()
#             # enable listen to multicast UDP
#             group = socket.inet_aton(RPCGremlin.MULTICAST_GROUP)
#             mreq = struct.pack("4sL", group, socket.INADDR_ANY)
#             self._server.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
#             syslog.info(f"Starting GEX server listener:  multicast group {RPCGremlin.MULTICAST_GROUP} port {self._port} ...")
#             self._keep_running = True
#             self._running = True
#             while not self._thread_event.is_set() and self._keep_running:
#                 time.sleep(0.5)
#         except Exception:
#             pass

#         self._server.shutdown()
#         self._server.server_close()
#         self._running = False
#         syslog.info("Gremlin listener stopped.")
#         proxy = gremlin.joystick_handling.VJoyProxy()
#         # release any locks on devices
#         proxy.reset()

#     @property
#     def running(self):
#         return self._running

#     def start(self):
#         """starts the listener"""

#         if self._running:
#             # already running
#             return

#         config = gremlin.config.Configuration()
#         if not config.remoteEnabled():
#             if not self._warning_issued:
#                 syslog.info("Remote control/broadcast disabled - Gremlin listener not started")
#                 self._warning_issued = True
#             return

#         # Pre-acquire connected vJoy devices for remote receive (also opens on demand later)
#         for key in gremlin.joystick_handling.vjoy_id_list(connected=True):
#             try:
#                 _device = gremlin.joystick_handling.VJoyProxy()[key]
#                 syslog.info(f"Remote proxy VJOY [{key}] ok")
#             except Exception:
#                 pass
#         self._thread_event.clear()
#         self._thread = threading.Thread(target=self._thread_runner, daemon=True)
#         self._thread.name = "RPCRunner"
#         self._thread.start()

#         self._running = True

#     def stop(self):
#         """stops the loop"""
#         self._warning_issued = False
#         if not self._running:
#             return

#         # stop the server loop
#         self._keep_running = False
#         self._thread_event.set()
#         gremlin.util.safeJoin(self._thread)
#         self._thread = None

#         syslog.info("Gremlin RPC server stopped...")


@gremlin.singleton_decorator.SingletonDecorator
class RemoteServer(QtCore.QObject):
    """Provides access to remote a remote Gremlin instance events"""

    connection_test_multicast = QtCore.Signal(bytes, int)
    broadcast_test_reply = QtCore.Signal(bytes, int, object, str, str)

    def __init__(self):
        """Initialises a new object."""

        QtCore.QObject.__init__(self)
        self._rpc = RPCGremlin()
        el = gremlin.event_handler.EventListener()
        el.config_option_changed.connect(self._handle_config_options_changed)
        el.remote_control_socket_timeout.connect(self._handle_socket_timeout)
        el.remote_control_socket_error.connect(self._handle_socket_error)
        el.shutdown.connect(self._shutdown)

    @property
    def startup_ready(self):
        return self._rpc.startup_ready

    def enable_startup(self):
        self._rpc.enable_startup()

    def start(self):
        """Starts listening when either remote control or broadcast is enabled."""
        self._rpc.start()

    def stop(self):
        """stop listening"""
        self._rpc.stop()

    @QtCore.Slot()
    def _handle_config_options_changed(self):
        self._rpc.reconfigure()

    @QtCore.Slot()
    def _shutdown(self):
        self._rpc.shutdown()

    @property
    def running(self):
        """true if the server is running"""
        return self._rpc.running

    @property
    def listening_port(self):
        return self._rpc.listening_port

    @property
    def enabled(self):
        """true if server is accepting input from clients"""
        return remote_control.is_remote

    @enabled.setter
    def enabled(self, value):
        self._enabled = value

    def _handle_socket_timeout(self):
        syslog.info("RPC: socket timeout")

    def _handle_socket_error(self):
        syslog.info("RPC: socket error")


class RemoteConnectionTest(QtCore.QObject):
    """Check a GEX listener over UDP and optionally receive its multicast reply."""

    finished = QtCore.Signal(str)

    def __init__(self, host: QtNetwork.QHostAddress, port: int, check_multicast: bool, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._check_multicast = check_multicast
        self._nonce = uuid.uuid4().bytes
        self._endpoint = f"{host.toString()}:{port}"
        self._group = QtNetwork.QHostAddress(RPCGremlin.MULTICAST_GROUP)
        self._attempts = 0
        self._direct_result = ""
        self._multicast_result = ""
        self._multicast_pending = False
        self._uses_remote_listener = False
        self._multicast_socket = None

        self._direct_socket = QtNetwork.QUdpSocket(self)
        self._direct_socket.readyRead.connect(self._read_direct)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    def start(self):
        if self._check_multicast:
            self._listen_for_multicast()
        if not self._direct_socket.bind(QtNetwork.QHostAddress.SpecialAddress.AnyIPv4):
            self._direct_result = f"Could not open a UDP test socket for {self._endpoint}. {self._direct_socket.errorString()}"
            self._finish()
            return
        self._send_request()

    def _listen_for_multicast(self):
        if self._host.isLoopback() or self._host in QtNetwork.QNetworkInterface.allAddresses():
            self._multicast_result = "To check multicast through the firewall, enter a GEX server IP on another PC."
            return
        if remote_server.listening_port == self._port:
            remote_server.connection_test_multicast.connect(self._accept_multicast, QtCore.Qt.ConnectionType.QueuedConnection)
            self._uses_remote_listener = True
        else:
            listener = QtNetwork.QUdpSocket(self)
            if not listener.bind(
                QtNetwork.QHostAddress.SpecialAddress.AnyIPv4,
                self._port,
                QtNetwork.QAbstractSocket.BindFlag.DontShareAddress,
            ) or not listener.joinMulticastGroup(self._group):
                self._multicast_result = f"Could not listen for multicast on local UDP port {self._port}. {listener.errorString()}"
                listener.close()
                return
            self._multicast_socket = listener
            listener.readyRead.connect(self._read_multicast)
        self._multicast_pending = True

    def _send_request(self):
        self._attempts += 1
        packet = msgpack.packb({"action": _PROBE_REQUEST, "nonce": self._nonce, "multicast": self._multicast_pending})
        if self._direct_socket.writeDatagram(packet, self._host, self._port) < 0:
            if not self._direct_result:
                self._direct_result = f"Could not send UDP to {self._endpoint}. {self._direct_socket.errorString()}"
            if self._multicast_pending:
                self._multicast_result = "The multicast request could not be sent."
            self._finish()
        else:
            self._timer.start(1500)

    @QtCore.Slot()
    def _read_direct(self):
        while self._direct_socket.hasPendingDatagrams():
            datagram = self._direct_socket.receiveDatagram()
            if datagram.senderAddress() != self._host or datagram.senderPort() != self._port:
                continue
            data = _unpack_remote_packet(bytes(datagram.data()))
            if data and data.get("action") == _PROBE_REPLY and data.get("nonce") == self._nonce:
                self._direct_result = f"GEX responded at {self._endpoint} over UDP."
                if not self._multicast_pending:
                    self._finish()
                    return

    @QtCore.Slot()
    def _read_multicast(self):
        listener = self._multicast_socket
        while listener.hasPendingDatagrams():
            datagram = listener.receiveDatagram()
            data = _unpack_remote_packet(bytes(datagram.data()))
            if data and data.get("action") == _PROBE_MULTICAST:
                self._accept_multicast(data.get("nonce"), self._port)

    @QtCore.Slot(bytes, int)
    def _accept_multicast(self, nonce, port):
        # The nonce identifies the requested server even if it multicasts from a different adapter.
        if self._multicast_pending and port == self._port and nonce == self._nonce:
            self._multicast_pending = False
            self._multicast_result = f"Server multicast reached this PC on {RPCGremlin.MULTICAST_GROUP}:{port} (UDP)."
            if self._direct_result:
                self._finish()

    @QtCore.Slot()
    def _on_timeout(self):
        if self._attempts < 2:
            self._send_request()
            return
        if not self._direct_result:
            self._direct_result = (
                f"No GEX reply from {self._endpoint} over UDP. "
                "Check that the server is running a GEX version with connection testing, "
                "broadcast is enabled, and the configured UDP port matches and is allowed through the firewall."
            )
        if self._multicast_pending:
            self._multicast_result = (
                f"No multicast reply reached this PC on {RPCGremlin.MULTICAST_GROUP}:{self._port} (UDP). "
                "Check the server's outbound and this PC's inbound firewall rules and the network's multicast settings."
            )
        self._finish()

    def _finish(self):
        self.cancel()
        self.finished.emit("\n".join(filter(None, (self._direct_result, self._multicast_result))))

    def cancel(self):
        self._timer.stop()
        self._direct_socket.close()
        self._multicast_pending = False
        if self._multicast_socket is not None:
            self._multicast_socket.close()
        if self._uses_remote_listener:
            remote_server.connection_test_multicast.disconnect(self._accept_multicast)
            self._uses_remote_listener = False


class RemoteBroadcastTest(QtCore.QObject):
    """Send a multicast ping and collect unicast replies from remote-control clients."""

    finished = QtCore.Signal(str, list)

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self._port = port
        self._nonce = uuid.uuid4().bytes
        self._responders = {}
        self._collecting = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finish)

    def start(self):
        remote_server.start()
        if remote_server.listening_port != self._port:
            syslog.warning(
                "RPC: Check Broadcast [%s] could not start on UDP port %d (listener port: %s)",
                self._nonce.hex(),
                self._port,
                remote_server.listening_port,
            )
            self.finished.emit(f"Could not listen for replies on UDP port {self._port}.", [])
            return

        remote_server.broadcast_test_reply.connect(self._accept_reply, QtCore.Qt.ConnectionType.QueuedConnection)
        self._collecting = True
        if remote_client.send({"action": _PROBE_BROADCAST_PING, "nonce": self._nonce}):
            self._timer.start(2000)
        else:
            syslog.warning(
                "RPC: Check Broadcast [%s] could not send multicast ping to %s:%d",
                self._nonce.hex(),
                RPCGremlin.MULTICAST_GROUP,
                self._port,
            )
            self.cancel()
            self.finished.emit(f"Could not send the multicast ping to {RPCGremlin.MULTICAST_GROUP}:{self._port}.", [])

    @QtCore.Slot(bytes, int, object, str, str)
    def _accept_reply(self, nonce, port, client_id, name, peer_ip):
        if self._collecting and nonce == self._nonce and port == self._port:
            self._responders.setdefault(client_id, (name, peer_ip))
        elif self._collecting:
            syslog.debug(
                "RPC: Check Broadcast [%s] ignored pong [%s] from %s on UDP port %d (expected port %d)",
                self._nonce.hex(),
                nonce.hex(),
                peer_ip,
                port,
                self._port,
            )

    @QtCore.Slot()
    def _finish(self):
        self.cancel()
        clients = sorted(self._responders.values(), key=lambda client: (client[0].casefold(), client[1]))
        count = len(clients)
        if count:
            message = "1 client replied to the multicast ping." if count == 1 else f"{count} clients replied to the multicast ping."
        else:
            message = (
                f"No clients replied to the multicast ping on {RPCGremlin.MULTICAST_GROUP}:{self._port}. "
                "Check that clients have remote control enabled, use the same UDP port, and run a build with Check Broadcast support."
            )
        syslog.info("RPC: Check Broadcast [%s] completed with %d unique client replies", self._nonce.hex(), count)
        self.finished.emit(message, clients)

    def cancel(self):
        self._timer.stop()
        if self._collecting:
            self._collecting = False
            remote_server.broadcast_test_reply.disconnect(self._accept_reply)


@gremlin.singleton_decorator.SingletonDecorator
class RemoteClient:
    """Provides access to a remote Gremlin instance and handles sending/receiving information between all clients on the network"""

    class ClientMode(enum.Enum):
        Local = 1
        Remote = 2
        LocalAndRemote = 3

    def __init__(self):
        """Initialises a new object."""

        self._sock = None
        self._socket_lock = threading.RLock()
        self._socket_settings = None
        config = gremlin.config.Configuration()
        self._verbose_remote_extra = config.verbose_mode_remote_extra
        self._verbose_remote = config.verbose_mode_remote
        self._verbose_outputs = config.verbose_mode_outputs
        # unique ID of this client
        self._id = get_guid()

        # self._alive_thread = None
        # self._alive_thread_event = threading.Event()
        # self._alive_thread_stop_requested = False
        self._started = False

        self._callbacks = {}  # map of callbacks by client ID
        self._callbacks_lock = threading.Lock()

        self.remote_control = RemoteControl()

        el = gremlin.event_handler.EventListener()
        # el.profile_stop.connect(self.stop) # hook stop event
        el.shutdown.connect(self.stop)  # hook stop event
        el.config_option_changed.connect(self._handle_config_options_changed)
        el.remote_control_enable.connect(self._handle_enable_control_request)
        el.remote_control_identify.connect(self.requestIdentify)  # request network clients to identify
        el.profile_stop.connect(self._handle_profile_stop)

    @property
    def clientName(self) -> str:
        return self.remote_control.clientName

    @property
    def customName(self) -> str:
        """custom client name, if any"""
        return self.remote_control.customName

    def getClientName(self) -> str:
        """gets the custom or host name"""
        return self.remote_control.clientName

    def _handle_profile_stop(self):
        self.remote_control.is_remote = False  # turn off profile remote mode on profile stop

    @property
    def clientId(self) -> int:
        """unique client ID"""
        return self.remote_control.clientId

    def _handle_config_options_changed(self):
        """called when configuration options are changed"""

        config = gremlin.config.Configuration()
        self._verbose_remote_extra = config.verbose_mode_remote_extra
        self._verbose_remote = config.verbose_mode_remote
        self._verbose_outputs = config.verbose_mode_outputs

        # get remote control options and start/stop as needed
        enabled = self.remote_control.remoteEnabled()
        if not enabled:
            if self._started:
                self.stop()
            return

        settings = (config.server_port, config.broadcast_host_ip, config.broadcast_bind_all_ips)
        with self._socket_lock:
            socket_changed = self._socket_settings != settings
            if socket_changed and self._sock is not None:
                self._sock.close()
                self._sock = None
        if not self._started:
            self._handle_enable_control_request()
        elif socket_changed:
            self.requestIdentify()

    def _handle_enable_control_request(self):
        """called when request to enable remote control has been made"""
        self.start()

    def getDatablock(self, action: str | None = None, key: str | None = None, data=None) -> dict:
        """gets a dict with the sender info"""
        block = {}
        if action:
            block["action"] = action
        if key:
            block["key"] = key
        if data is not None:
            block["data"] = data

        return block

    def start(self):
        """creates a multicast client send socket on profile start"""
        if remote_server.startup_ready and not self._started and self.remote_control.remoteEnabled():
            # Always bring the UDP listener up before sending identify.
            remote_server.start()
            if self.ensure_socket():
                el = gremlin.event_handler.EventListener()
                el.heartbeat.connect(self._alive_ticker)
                self._started = True

                # send ID request when starting to update clients
                self.requestIdentify()

    def stop(self):
        """closes the client socket"""
        if self._started:
            # notify this client is disconnecting
            self.requestDisconnect()

            try:
                el = gremlin.event_handler.EventListener()
                el.heartbeat.disconnect(self._alive_ticker)
            except Exception:  # noqa: BLE001, S110
                pass

            self._started = False

        with self._socket_lock:
            if self._sock is not None:
                self._sock.close()
                self._sock = None
                syslog.info("Gremlin RPC client stopped.")
        with self._callbacks_lock:
            pending = list(self._callbacks.values())
            self._callbacks.clear()
        for packet in pending:
            packet.stop()

    def ensure_socket(self):
        with self._socket_lock:
            return self._ensure_socket()

    def _ensure_socket(self):
        # makes sure the socket exists
        import struct

        try:
            if not self._sock:
                config = gremlin.config.Configuration()
                broadcast_host = config.broadcast_host_ip
                port = config.server_port
                bind_all = config.broadcast_bind_all_ips
                settings = (port, broadcast_host, bind_all)
                if not bind_all and broadcast_host == "127.0.0.1":
                    broadcast_host = gremlin.util.getHostIp()[0]
                    syslog.warning(
                        f"RPC: broadcast host is not configured (using localhost). Using [{broadcast_host}].  This may not be correct if you have multiple IP addresses."
                    )

                self._address = (RPCGremlin.MULTICAST_GROUP, port)
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                ttl = struct.pack("b", RPCGremlin.MULTICAST_TTL)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
                # Never bind the *send* socket to server_port — that collides with the
                # UDP listener and produces RPC socket errors / missed identify replies.
                # Optionally pin the outbound multicast interface instead.
                if (not bind_all) and broadcast_host and broadcast_host not in ("0.0.0.0", ""):
                    try:
                        self._sock.setsockopt(
                            socket.IPPROTO_IP,
                            socket.IP_MULTICAST_IF,
                            socket.inet_aton(broadcast_host),
                        )
                        syslog.info("RPC: multicast sender configured for %s:%d using interface %s", *self._address, broadcast_host)
                    except OSError as err:
                        syslog.warning(f"RPC: could not set multicast iface {broadcast_host}: {err}")
                        syslog.info("RPC: multicast sender configured for %s:%d using the OS default IPv4 interface", *self._address)
                else:
                    syslog.info("RPC: multicast sender configured for %s:%d using the OS default IPv4 interface", *self._address)
                self._socket_settings = settings
            return self._sock is not None
        except Exception:  # noqa: BLE001
            syslog.error("SOCKET: unable to open remote control socket. Feature will be disabled.")
            if self._sock is not None:
                self._sock.close()
            self._sock = None
            return False

    def registerClient(self):
        """sends network our client data - this is called on network start"""
        enabled = gremlin.config.Configuration().remoteEnabled()
        if enabled:
            client = ClientData()
            data = self.getDatablock("register_client", data=client.toPayload())
            self.send(data)  # send to all
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"Register client [{client.client_name}]/[{client.client_id}]")

    def unregisterClient(self):
        enabled = gremlin.config.Configuration().remoteEnabled()
        if enabled:
            client = ClientData()
            data = self.getDatablock("unregister_client", data=client.toPayload())
            self.send(data)  # send to all
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"Unregister client [{client.client_name}]/[{client.client_id}]")

    def requestIdentify(self):
        """sends a network identify request which prompts each running client to send their information"""
        enabled = gremlin.config.Configuration().remoteEnabled()
        if enabled:
            data = self.getDatablock("identify")
            self.send(data)

    def requestDisconnect(self):
        """sends a network notice the current client is disconnecting"""
        self.unregisterClient()

    def _dispatch(self, data, client_list):
        """Send output to the requested targets allowed by the master filter."""
        if client_list is None:
            targets = (0,)
        elif isinstance(client_list, (str, int)):
            targets = (int(client_list),)
        else:
            targets = tuple(dict.fromkeys(int(client_id) for client_id in client_list))

        for client_id in self.remote_control.filterClientTargets(targets):
            self.send(data, client_id)

    def _alive_ticker(self):
        """sends an alive packet to keep the socket alive"""
        enabled = gremlin.config.Configuration().enable_remote_broadcast
        if enabled:
            data = self.getDatablock("hb")
            self.send(data)  # send to all
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info("Alive heartbeat")

    def send_pause(self, duration, client_list=None):
        if self.enabled:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: send pause: {duration}")
            data = self.getDatablock("pause")
            data["value"] = duration
            self._dispatch(data, client_list)

    def send_button(self, device_id, button_id, is_pressed, client_list=None, force_remote=False):
        """sends joystick buttons to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: send button: VJoyId: {device_id} button {button_id} pressed: {is_pressed}")
            self._send_joystick("button", ButtonData.key, device_id, button_id, is_pressed, client_list)

    def toggle_button(self, device_id, button_id, client_list=None, force_remote=False):
        """sends toggle button to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: toggle button: VJoyId: {device_id} button {button_id}")
            self._send_joystick("toggle", ButtonData.key, device_id, button_id, None, client_list)

    def send_axis(self, device_id, axis_id, value, client_list=None, force_remote=False):
        """sends axis data to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                stub = f"{value:0.3f}" if value is not None else "None"
                syslog.info(f"REMOTE OUTPUT: send axis: VJoyId: [{device_id}] axis: [{axis_id}] value: [{stub}]")
            self._send_joystick("axis", AxisData.key, device_id, axis_id, value, client_list)

    def send_relative_axis(self, device_id, axis_id, value, client_list=None, force_remote=False):
        """sends relative axis data to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_outputs
            if verbose:
                stub = f"{value:0.3f}" if value is not None else "None"
                syslog.info(f"REMOTE OUTPUT: send relative axis: VJoyId: [{device_id}] axis: [{axis_id}] value: [{stub}]")
            self._send_joystick("axis", AxisData.key, device_id, axis_id, None, client_list, relative_value=value)

    def send_hat(self, device_id, hat_id, direction, client_list=None, force_remote=False):
        """sends joystick hats to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: VJoyId: {device_id} hat: {hat_id} direction: {direction}")
            self._send_joystick("hat", HatData.key, device_id, hat_id, _hat_direction(direction), client_list)

    def _send_joystick(self, action, key, device_id, target, value, client_list, relative_value=None):
        """Encode a portable identity for Maestro and preserve legacy vJoy IDs."""
        joystick_handling = gremlin.joystick_handling
        device_id = joystick_handling.parse_virtual_device_key(device_id)
        if isinstance(device_id, str):
            device = joystick_handling.get_virtual_device(device_id)
            if device is not None:
                if device.device_type == DeviceType.Maestro:
                    device_id = joystick_handling.maestro_output_identity(device)
                elif device.device_type == DeviceType.VJoy:
                    device_id = device.vjoy_id
        command = action if key == ButtonData.key else "value"
        if relative_value is not None:
            command = "relative"
        payload = {
            "key": key,
            "action": command,
            "extra_data": None,
            "device": device_id,
            "target": target,
            "value": value,
        }
        if key == AxisData.key:
            payload["rvalue"] = relative_value
        self._dispatch({"action": action, "key": key, "data": payload}, client_list)

    def send_key(
        self,
        virtual_code,
        scan_code,
        flags,
        client_list=None,
        force_remote=False,
        extra_data=None,
    ):
        """sends keyboard events to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                code = int(scan_code)
                syslog.info(f"REMOTE OUTPUT: key: 0x{code:02x} flags: 0x{flags:02x}")
            payload = KeyData.create(virtual_code, scan_code, flags, action="value", extra_data=extra_data).toPayload()

            data = self.getDatablock("key", key=KeyData.key, data=payload)
            self._dispatch(data, client_list)

    def send_mouse_button(
        self,
        button_id,
        is_pressed,
        client_list=None,
        force_remote=False,
        extra_data: dict | None = None,
    ):
        """sends a mouse button press or release to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse button: {button_id} pressed: {is_pressed}")

            payload = MouseData.create(button_id, is_pressed, "button", extra_data).toPayload()
            data = self.getDatablock("mouse", key=MouseData.key, data=payload)
            self._dispatch(data, client_list)

    def send_mouse_button_double_click(
        self,
        button_id,
        is_pressed,
        client_list=None,
        force_remote=False,
        extra_data: dict | None = None,
    ):
        """sends a mouse button press or release to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse dblclick {button_id} pressed: {is_pressed}")
            payload = MouseData.create(button_id, is_pressed, "button_double", extra_data).toPayload()
            data = self.getDatablock("mouse", key=MouseData.key, data=payload)
            self._dispatch(data, client_list)

    def send_mouse_wheel(self, direction, client_list=None, force_remote=False, extra_data: dict | None = None):
        """sends vertical mousewheel data  to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse wheel: {direction}")
            payload = MouseData.create(MouseButton.Wheel, direction, "wheel", extra_data).toPayload()
            data = self.getDatablock("mouse", key=MouseData.key, data=payload)
            self._dispatch(data, client_list)

    def send_mouse_h_wheel(self, direction, client_list=None, force_remote=False, extra_data: dict | None = None):
        """sends horizontal mousewheel data to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_outputs
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse H wheel: {direction}")

            payload = MouseData.create(MouseButton.HWheel, direction, "hwheel", extra_data).toPayload()
            data = self.getDatablock("mouse", key=MouseData.key, data=payload)
            self._dispatch(data, client_list)

    def send_mouse_motion(self, dx, dy, client_list=None, force_remote=False, extra_data: dict | None = None):
        """sends mouse motion data to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse motion: {dx}, {dy}")

            payload = MouseData.create(MouseButton.NotSet, (dx, dy), "axis", extra_data).toPayload()
            data = self.getDatablock("mouse", key=MouseData.key, data=payload)
            self._dispatch(data, client_list)

    def send_mouse_motion_acceleration(
        self,
        a,
        min_speed,
        max_speed,
        time_to_max_speed,
        client_list=None,
        force_remote=False,
        extra_data: dict | None = None,
    ):
        """sends mouse acceleration data to clients"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info("REMOTE OUTPUT: mouse motion acceleration")
            payload = MouseData.create(
                MouseButton.NotSet,
                (a, min_speed, max_speed, time_to_max_speed),
                "amotion",
                extra_data,
            ).toPayload()
            data = self.getDatablock("mouse", key=MouseData.key, data=payload)
            self._dispatch(data, client_list)

    # Retain the name used by the mouse mapper plugins.
    send_mouse_acceleration = send_mouse_motion_acceleration

    def send_gamepad_axis(self, device_id: int | str, mode, value, client_list=None, force_remote=False):
        """sends a gamepad axis to the remote client"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: gamepad axis: index: {device_id} mode: {mode} value: {value:0.3f}")

            data = self.getDatablock("gamepad")
            data["key"] = "gamepad"
            data["subtype"] = "axis"
            data["index"] = device_id  # which device to send to
            data["mode"] = getattr(mode, "value", mode)
            data["value"] = value
            self._dispatch(data, client_list)

    def send_gamepad_button(self, device_id: int | str, mode, is_pressed, client_list=None, force_remote=False):
        """sends a gamepad button to the remote client"""
        if self.enabled or force_remote:
            verbose = self._verbose_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: gamepad: index: {device_id} mode: {mode} pressed: {is_pressed}")

            data = self.getDatablock("gamepad")
            data["key"] = "gamepad"
            data["index"] = device_id  # which device to send to (int or string)
            data["subtype"] = "button"
            data["mode"] = getattr(mode, "value", mode)
            data["is_pressed"] = is_pressed
            self._dispatch(data, client_list)

    def send_kvm_mouse_motion_start(self, client_list=None):
        """sends kvm init"""
        data = self.getDatablock("kvm")
        data["subtype"] = "start"
        self._dispatch(data, client_list)

    def send_kvm_mouse_motion_stop(self, client_list=None):
        """sends kvm terminate"""
        data = self.getDatablock("kvm")
        data["subtype"] = "stop"
        self._dispatch(data, client_list)

    def send_kvm_mouse_motion(self, x: int, y: int, dx: int, dy: int, client_list=None):
        """sends mouse position"""
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "motion"
            data["x"] = x
            data["y"] = y
            data["dx"] = dx
            data["dy"] = dy
            self._dispatch(data, client_list)

    def send_kvm_mouse_button(self, button_id: int, is_pressed: bool, client_list=None):
        """sends mouse button"""
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "button"
            data["button"] = button_id
            data["is_pressed"] = is_pressed
            self._dispatch(data, client_list)

    def send_kvm_mouse_wheel(self, delta: int, leftright: bool, client_list=None):
        """sends mouse wheel"""
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "hwheel" if leftright else "wheel"
            data["delta"] = 1 if delta > 0 else -1  # 120 for up, 65416 for down
            self._dispatch(data, client_list)

    def send_kvm_keyboard(self, virtual_code, scan_code, flags, client_list=None):
        """handles a kvm key event"""
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "key"
            data["vc"] = virtual_code
            data["sc"] = scan_code
            data["flags"] = flags
            self._dispatch(data, client_list)

    @property
    def enabled(self):
        """enables or disabled sending remote events"""
        return True  # as of T176 always enable due to the overrides
        # return remote_state.is_remote

    @property
    def id(self):
        return self._id

    def send(self, data=None, client_id: int = 0) -> bool:
        """sends data to the socket. Returns True if a datagram was sent."""
        if not data or not remote_server.startup_ready:
            return False
        data = data.copy()
        data["sender_id"] = self.clientId
        data["sender_name"] = self.clientName
        data["to"] = int(client_id) if client_id is not None else 0

        # ensure listener is up when remote is enabled
        remote_server.start()

        verbose = self._verbose_remote_extra
        if verbose:
            syslog.info(f"RPC:  send data {data}")

        # encode the data
        try:
            raw_data = msgpack.packb(data)
        except Exception as err:  # noqa: BLE001
            syslog.error(f"RPC: msgpack failed: {err}")
            return False

        with self._socket_lock:
            if self._sock is None and not self.ensure_socket():
                syslog.warning("RPC: send aborted — no outbound socket")
                return False
            try:
                self._sock.sendto(raw_data, self._address)
            except OSError as err:
                syslog.error(f"RPC: sendto failed: {err}")
                return False
            if data.get("action") == _PROBE_BROADCAST_PING:
                nonce = data.get("nonce")
                if isinstance(nonce, bytes):
                    self._log_broadcast_ping(nonce)
            return True

    def _log_broadcast_ping(self, nonce):
        try:
            local_port = self._sock.getsockname()[1]
            address = socket.inet_ntoa(self._sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, 4))
            interface = address if address != "0.0.0.0" else "the OS default IPv4 interface"
        except OSError:
            local_port = "unknown"
            interface = "an unknown IPv4 interface"
        group, port = self._address
        syslog.info(
            "RPC: Check Broadcast [%s] sent multicast ping to %s:%d using %s, source UDP port %s, expecting unicast replies on UDP port %d",
            nonce.hex(),
            group,
            port,
            interface,
            local_port,
            port,
        )

    def sendRequest(self, callback, payload: dict | None = None, client_id: str | None = None):
        """sends a packet request to clients expecting a response

        :param callback: callback to call when the data is received, sends the packet block
        :param data: the data (dict) if any to send to the network - request dependent
        :param client_id: the id of the specific client to send the data to, None means broadcast to all

        if a packet is sent to multiple clients, the callback will be called multiple times, once for each responding client

        """
        client_id = int(client_id) if client_id is not None else 0

        id = gremlin.util.get_guid()
        data = self.getDatablock("request")
        data["request_id"] = id
        data["target"] = client_id
        data["reply_id"] = self.clientId
        data["data"] = payload

        pd = PacketData(id=id, callback=callback, client_id=client_id, server_id=self.clientId, data=data, on_timeout=self._expire_request)
        with self._callbacks_lock:
            self._callbacks[id] = pd
        # Arm the timer before sending: an immediate reply must not restart it.
        pd.start()
        if not self.send(data, client_id=client_id):
            pd._handle_timeout()

    def _expire_request(self, packet):
        with self._callbacks_lock:
            if self._callbacks.get(packet.id) is packet:
                del self._callbacks[packet.id]

    def handleResponse(self, request_id, data: dict):
        """process a response from a client from sendRequest()"""
        with self._callbacks_lock:
            pd = self._callbacks.get(request_id)
            if pd is not None and pd.client_id:
                del self._callbacks[request_id]
        if pd is not None:
            pd.trigger(data)

    def requestAlive(self, callback):
        """sends an alive request to a client or all clients"""
        payload = {"action": "alive", "response": None}
        self.sendRequest(callback=callback, payload=payload)

    def requestClients(self, callback):
        """sends a client request to identify"""
        payload = {"action": "identify", "response": None}
        syslog.info("RPC: send identify request")
        self.sendRequest(callback=callback, payload=payload)

    def handle(self, data: dict, peer_ip: str = ""):
        """handles received data from the sender

        :param peer_ip: UDP source address when known (used for video return connect-back)
        """

        sender = data.get("sender_id")
        action = data.get("action")
        target = data.get("to", 0)
        if sender is None or not isinstance(action, str):
            return

        client_id = self.clientId
        if sender == client_id or (target and target != client_id):
            return
        if action in _VIRTUAL_OUTPUT_ACTIONS and type(data.get("to")) is not int:
            return
        if action not in (
            "identify",
            "identify_client",
            "unregister_client",
            "register_client",
            "request",
            "reply",
            "hb",
        ) and (not gremlin.shared_state.is_running or not gremlin.config.Configuration().enable_remote_control):
            return

        verbose = self._verbose_remote
        if verbose:
            syslog.info(f"REMOTE: received remote data: {data}")

        match action:
            case "hb":
                # heartbeat
                return

            case "key":
                # keyboard output
                import win32con
                import win32gui

                key_data = KeyData.fromPayload(data["data"])
                virtual_code = key_data.virtual_code
                scan_code = key_data.scan_code
                flags = key_data.flags
                if verbose:
                    syslog.info(f"REMOTE: key 0x{scan_code:X}")
                extra_data = key_data.extra_data
                process_name = extra_data["process_name"] if extra_data and "process_name" in extra_data else None

                hwnd = 0
                if process_name:
                    partial_match = extra_data["partial_match"] if extra_data and "partial_match" in extra_data else False

                    ph = gremlin.process.ProcessHelper()
                    hwnd = ph.findProcessHwnd(process_name, partial_match)
                    if hwnd:
                        # Keyup Bits: (Transition=0, Previous=0, Extended=0, Scancode=0x1E, Repeat=1)
                        lparam = 0x00000001 | scan_code << 16  # Scan code, repeat=1
                        is_extended = flags & win32con.KEYEVENTF_EXTENDEDKEY
                        msg = win32con.WM_KEYUP if flags & win32con.KEYEVENTF_KEYUP else win32con.WM_KEYDOWN
                        if is_extended:
                            lparam |= 0x01000000  # Extended code if required
                        hwnd_list = gremlin.keyboard.getInnerWindows(hwnd)
                        if msg == win32con.WM_KEYUP:
                            lparam |= 0xC0000000  # key up
                        for sub_hwnd in hwnd_list:  # must send to specific process subhandles for POST method
                            win32gui.PostMessage(sub_hwnd, msg, virtual_code, lparam)
                    else:
                        # send to window with focus
                        gremlin.sendinput.send_key(virtual_code, scan_code, flags)
                else:
                    gremlin.sendinput.send_key(virtual_code, scan_code, flags)

                # win32api.keybd_event(virtual_code, scan_code, flags, 0) # deprecated

            case "mouse":
                # mouse output
                payload = data["data"]
                mouse_data = MouseData.fromPayload(payload)
                subtype = mouse_data.action
                match subtype:
                    case "wheel":
                        direction = mouse_data.value
                        if verbose:
                            syslog.info(f"REMOTE: wheel {direction}")
                        gremlin.sendinput.mouse_wheel(direction)
                    case "hwheel":
                        direction = mouse_data.value
                        if verbose:
                            syslog.info(f"REMOTE: wheel {direction}")
                        gremlin.sendinput.mouse_h_wheel(direction)
                    case "button":
                        button_id = mouse_data.button_id
                        button = gremlin.types.MouseButton.to_enum(button_id)
                        is_pressed = mouse_data.value
                        if is_pressed:
                            if verbose:
                                syslog.info(f"REMOTE: mouse button down {button.name}")
                            gremlin.sendinput.mouse_press(button)
                        else:
                            if verbose:
                                syslog.info(f"REMOTE: mouse button up {button.name}")
                            gremlin.sendinput.mouse_release(button)
                    case "button_double":
                        button_id = mouse_data.button_id
                        button = gremlin.types.MouseButton.to_enum(button_id)
                        is_pressed = mouse_data.value
                        if is_pressed:
                            if verbose:
                                syslog.info(f"REMOTE: double click {button.name}")
                            gremlin.sendinput.mouse_press_double_click(button)
                    case "axis":
                        dx, dy = mouse_data.value
                        mouse_controller = gremlin.sendinput.MouseController()
                        if verbose:
                            syslog.info(f"REMOTE: mouse axis [{dx},{dy}]")
                        mouse_controller.set_absolute_motion(dx, dy)

                    case "amotion":
                        # accelerated motion
                        a, min_speed, max_speed, time_to_max_speed = mouse_data.value
                        mouse_controller = gremlin.sendinput.MouseController()
                        if verbose:
                            syslog.info("REMOTE: mouse accelerated motion")
                        mouse_controller.set_accelerated_motion(a, min_speed, max_speed, time_to_max_speed)

            case "kvm":
                # kvm mode

                subtype = data["subtype"]
                match subtype:
                    case "start" | "stop":
                        # set/reset
                        pass
                    case "motion":
                        # mouse movement (via deltas)
                        dx = data["dx"]
                        dy = data["dy"]

                        if verbose:
                            syslog.info(f"KVM (client): received motion delta {dx} {dy}")
                        gremlin.sendinput.send_mouse_motion(dx, dy)

                    case "button":
                        # mouse button 1 to 5 for normal buttons, > 5 for wheel codes
                        button_id = data["button"]
                        if button_id > 5:
                            # wheel
                            button = MouseButton(button_id)
                            if verbose:
                                syslog.info(f"KVM (client): received mouse wheel: {button.name}")
                            match button:
                                case MouseButton.WheelUp:
                                    gremlin.sendinput.mouse_wheel(1)
                                case MouseButton.WheelDown:
                                    gremlin.sendinput.mouse_wheel(-1)
                                case MouseButton.WheelLeft:
                                    gremlin.sendinput.mouse_h_wheel(-1)
                                case MouseButton.WheelRight:
                                    gremlin.sendinput.mouse_h_wheel(1)
                        else:
                            # mouse button 1 to 5
                            is_pressed = data["is_pressed"]
                            if verbose:
                                syslog.info(f"KVM (client): received mouse button: {button_id} pressed: {is_pressed}")
                            if is_pressed:
                                gremlin.sendinput.mouse_press(button_id)
                            else:
                                gremlin.sendinput.mouse_release(button_id)
                    case "wheel":
                        delta = data["delta"]
                        gremlin.sendinput.mouse_wheel(delta)
                    case "hwheel":
                        delta = data["delta"]
                        gremlin.sendinput.mouse_h_wheel(delta)
                    case "key":
                        virtual_code = data["vc"]
                        scan_code = data["sc"]
                        flags = data["flags"]
                        gremlin.sendinput.send_key(virtual_code, scan_code, flags)

            case "request":
                # received a requet for information from a specific client - this is recevied by clients that need to reply
                request_data = data["data"]
                match request_data["action"]:
                    case "identify" | "alive":
                        reply = {
                            **data,
                            "action": "reply",
                            "data": {
                                **request_data,
                                "response": ClientData().toPayload(),
                            },
                        }
                        self.send(reply, client_id=data["reply_id"])

            case "reply":
                # received a reply packet from a prior request - this is received by the requesting client
                request_id = data["request_id"]
                self.handleResponse(request_id, data["data"]["response"])

            case "identify":
                # received a request to self identify to the network
                try:
                    data = self.getDatablock("identify_client", data=ClientData().toPayload())
                    ok = self.send(data)  # send to all
                    if not ok:
                        syslog.warning("RPC: identify reply send failed (no socket?)")
                    else:
                        syslog.info("RPC: identify reply sent")
                except Exception as err:  # noqa: BLE001
                    syslog.error(f"RPC: identify reply failed: {err}")

            case "identify_client" | "register_client":
                # request to register the specified client as a result of a prior "identify" request
                # Older T50L2R builds accidentally put the payload in "key" instead of "data".
                payload = data.get("data")
                if not isinstance(payload, dict):
                    payload = data.get("key")
                if not isinstance(payload, dict):
                    syslog.warning(f"RPC: identify_client missing payload from {peer_ip}: keys={list(data.keys())}")
                    return
                cd = ClientData.fromPayload(payload)
                if peer_ip:
                    cd.host_ip = peer_ip
                syslog.info(f"RPC: identity received: {cd} version=[{cd.client_version}] ip=[{cd.host_ip}]")

                self.remote_control.registerClient(cd)

            case "unregister_client":
                # request to unregister the specified client
                payload = data.get("data")
                if not isinstance(payload, dict):
                    payload = data.get("key")
                if not isinstance(payload, dict):
                    return
                cd = ClientData.fromPayload(payload)
                if verbose:
                    syslog.info(f"RPC: disconnect received: {cd!s}")

                self.remote_control.unregisterClient(cd.client_id)

            case "gamepad":
                # gamepad handling
                index = data["index"]  # id of the gamepad to send the data to
                subtype = data["subtype"]  # axis or button
                output_mode = data["mode"]  # either a gamepadoutput or the translated button code
                vigem = gremlin.gamepad_handling.getGamepad(index)
                if vigem is not None:
                    if subtype == "axis":
                        value = data["value"]
                        output_mode = GamePadOutput.to_enum(output_mode) if isinstance(output_mode, str) else GamePadOutput(output_mode)

                        if vigem:
                            if output_mode == GamePadOutput.LeftStickX:
                                if verbose:
                                    syslog.info(f"REMOTE: pad left x {value:0.3f}")
                                vigem.left_joystick_float_x(value)
                            elif output_mode == GamePadOutput.LeftStickY:
                                if verbose:
                                    syslog.info(f"REMOTE: pad left y {value:0.3f}")
                                vigem.left_joystick_float_y(value)
                            if output_mode == GamePadOutput.RightStickX:
                                if verbose:
                                    syslog.info(f"REMOTE: pad right x {value:0.3f}")
                                vigem.right_joystick_float_x(value)
                            elif output_mode == GamePadOutput.RightStickY:
                                if verbose:
                                    syslog.info(f"REMOTE: pad right y {value:0.3f}")
                                vigem.right_joystick_float_y(value)
                            if output_mode == GamePadOutput.LeftTrigger:
                                # vscaled = gremlin.util.scale_to_range(value.current,target_min=0.0, target_max=1.0)
                                if verbose:
                                    syslog.info(f"REMOTE: pad left trigger {value:0.3f}")
                                vigem.left_trigger_float(value)
                            if output_mode == GamePadOutput.RightTrigger:
                                # vscaled = gremlin.util.scale_to_range(value.current,target_min=0.0, target_max=1.0)
                                if verbose:
                                    syslog.info(f"REMOTE: pad right trigger {value:0.3f}")
                                vigem.right_trigger_float(value)

                    elif subtype == "button":
                        button = output_mode
                        is_pressed = data["is_pressed"]
                        if is_pressed:
                            if verbose:
                                syslog.info(f"REMOTE: pad button press {button}")
                            vigem.press_button(button)
                        else:
                            if verbose:
                                syslog.info(f"REMOTE: pad button release {button}")
                            vigem.release_button(button)
                    vigem.update()

            case "button" | "axis" | "hat" | "relative_axis" | "relative_Axis" | "toggle":
                # Open the client's joystick output on demand.

                payload = data["data"]
                device = payload["device"]
                target = payload["target"]
                value = payload["value"]
                match action:
                    case "button" | "toggle":
                        if payload.get("key") != ButtonData.key:
                            raise ValueError("Invalid button payload")
                    case "axis" | "relative_axis" | "relative_Axis":
                        if payload.get("key") != AxisData.key:
                            raise ValueError("Invalid axis payload")
                        relative_value = payload.get("rvalue")
                    case "hat":
                        # Accept HatData; also tolerate legacy AxisData payloads (wrong key) from older masters
                        if payload.get("key") not in (HatData.key, AxisData.key):
                            raise ValueError("Invalid hat payload")
                        value = _hat_direction(value)

                output = _open_remote_output(device)
                if output is None:
                    return

                match action:
                    case "button":
                        if verbose:
                            syslog.info(f"REMOTE: output [{device}] button {target} pressed: {value}")
                        if target > 0 and target <= output.button_count:
                            output.button(target).is_pressed = value
                    case "toggle":
                        if verbose:
                            syslog.info(f"REMOTE: output [{device}] toggle button {target}")
                        if target > 0 and target <= output.button_count:
                            button = output.button(target)
                            button.is_pressed = not button.is_pressed
                    case "axis" | "relative_axis" | "relative_Axis":
                        if target <= 0 or not output.is_axis_valid(axis_id=target):
                            if verbose:
                                syslog.error(f"REMOTE: output [{device}] invalid axis target: {target}")
                            return
                        axis = output.axis(target)
                        if value is None:
                            value = axis.value
                        if relative_value:
                            value = gremlin.util.clamp(value + relative_value)
                            if verbose:
                                syslog.info(f"REMOTE: output [{device}] axis {target} relative value: {relative_value:0.3f}")
                        if verbose:
                            stub = f"{value:0.3f}" if value is not None else "None"
                            syslog.info(f"REMOTE: output [{device}] axis {target}: {stub}")
                        axis.value = value
                    case "hat":
                        if target > 0 and target <= output.hat_count:
                            if verbose:
                                syslog.info(f"REMOTE: output [{device}] hat {target} direction: {value}")
                            output.hat(target).direction = value
                    case _:
                        syslog.error(f"REMOTE: unknown action code received [{action}]")

            case "pause":
                # pause client
                duration = data["value"]
                time.sleep(duration)

            case _:
                syslog.error(f"REMOTE: don't know how to handle action [{action}]")


class InternalSpeech:
    """tts interface"""

    def __init__(self):
        import win32com.client

        self.speaker = win32com.client.Dispatch("SAPI.SpVoice")

    def speak(self, text):
        try:
            self.speaker.speak(text)
        except Exception:  # noqa: BLE001, S110
            pass


class BaseData:
    """base class for input data"""

    def __init__(self, key: str, action: str, extra_data: dict | None = None):
        self.key: str = key
        self.action: str = action
        self.extra_data: dict = extra_data

    def toPayload(self) -> dict:
        """creates a payload from the data"""
        return {
            "key": self.key,
            "action": self.action,
            "extra_data": self.extra_data,
        }

    def fromPayload(data: dict) -> BaseData:
        """loads from payload"""
        return BaseData(key=data["key"], action=data["action"], extra_data=data.get("extra_data"))


class ButtonData(BaseData):
    """holds button data"""

    key = "button"

    def __init__(self, action: str | None = None, extra_data: dict | None = None):
        super().__init__(self.key, action, extra_data)
        self.device_id: int | str = None  # vjoy device ID (int or guid) GUID
        self.button_id: int = None
        self.is_pressed: bool = None

    @staticmethod
    def create(device_id: int | str, button_id: int, is_pressed: bool | None = None, action: str | None = None, extra_data: dict | None = None):
        self = ButtonData(action, extra_data=extra_data)
        self.device_id = device_id
        self.button_id = button_id
        self.is_pressed = is_pressed
        return self

    def toPayload(self) -> dict:
        """creates a payload from the data"""
        payload = super().toPayload()
        return {
            **payload,
            "device": self.device_id,
            "target": self.button_id,
            "value": self.is_pressed,
        }

    @staticmethod
    def fromPayload(data: dict) -> ButtonData:
        """loads from payload"""
        if data.get("key") != ButtonData.key:
            raise ValueError("Invalid key for ButtonData")
        self = ButtonData(action=data["action"], extra_data=data.get("extra_data"))
        self.device_id = data["device"]
        self.button_id = data["target"]
        self.is_pressed = data["value"]
        return self


class AxisData(BaseData):
    """holds axis data"""

    key = "axis"

    def __init__(self, action: str | None = None, extra_data: dict | None = None):
        super().__init__(self.key, action, extra_data)
        self.device_id: int | str = None
        self.axis_id: int = None
        self.value: float = None
        self.relative_value: float = None

    @staticmethod
    def create(
        device_id: int | str,
        axis_id: int,
        value: float | None = None,
        relative_value: float | None = None,
        action: str | None = None,
    ):
        self = AxisData(action=action)
        self.device_id = device_id
        self.axis_id = axis_id
        self.value = value
        self.relative_value = relative_value

        return self

    def toPayload(self) -> dict:
        """creates a payload from the data"""
        payload = super().toPayload()
        return {
            **payload,
            "device": self.device_id,
            "target": self.axis_id,
            "value": self.value,
            "rvalue": self.relative_value,
        }

    @staticmethod
    def fromPayload(data: dict) -> AxisData:
        """loads from payload"""
        if data.get("key") != AxisData.key:
            raise ValueError("Invalid key for AxisData")
        self = AxisData(action=data["action"], extra_data=data.get("extra_data"))
        self.device_id = data["device"]
        self.axis_id = data["target"]
        self.value = data["value"]
        self.relative_value = data.get("rvalue")

        return self


class HatData(BaseData):
    """holds hat data"""

    key = "hat"

    def __init__(self, action: str | None = None, extra_data: dict | None = None):
        super().__init__(self.key, action, extra_data)
        self.device_id: int | str = None
        self.hat_id: int = None
        self.direction: tuple | None = None  # tuple

    @staticmethod
    def create(device_id: int | str, hat_id: int, direction: tuple, action: str | None = None, extra_data: dict | None = None) -> HatData:
        self = HatData(action=action, extra_data=extra_data)
        self.device_id = device_id
        self.hat_id = hat_id
        self.direction = _hat_direction(direction)
        self.action = action
        return self

    def toPayload(self) -> dict:
        payload = super().toPayload()
        return {
            **payload,
            "device": self.device_id,
            "target": self.hat_id,
            "value": self.direction,
        }

    @staticmethod
    def fromPayload(data: dict) -> HatData:
        if data.get("key") != HatData.key:
            raise ValueError("Invalid key for HatData")
        self = HatData(action=data.get("action"), extra_data=data.get("extra_data"))
        self.device_id = data["device"]
        self.hat_id = data["target"]
        self.direction = _hat_direction(data["value"])

        return self


class KeyData(BaseData):
    """holds key data"""

    key = "key"

    def __init__(self, action: str | None = None, extra_data: dict | None = None):
        super().__init__(self.key, action, extra_data)
        self.virtual_code: int = None
        self.scan_code: int = None
        self.flags: int = None

    @staticmethod
    def create(
        virtual_code: int,
        scan_code: int,
        flags: int,
        action: str | None = None,
        extra_data: dict | None = None,
    ) -> KeyData:
        self = KeyData(action=action, extra_data=extra_data)
        self.virtual_code = virtual_code
        self.scan_code = scan_code
        self.flags = flags
        self.action = action
        self.extra_data = extra_data
        return self

    def toPayload(self) -> dict:
        payload = super().toPayload()
        return {
            **payload,
            "vc": self.virtual_code,
            "sc": self.scan_code,
            "flags": self.flags,
        }

    @staticmethod
    def fromPayload(data: dict) -> KeyData:
        if data.get("key") != KeyData.key:
            raise ValueError("Invalid key for KeyData")
        self = KeyData(action=data.get("action"), extra_data=data.get("extra_data"))
        self.virtual_code = data["vc"]
        self.scan_code = data["sc"]
        self.flags = data["flags"]

        return self


class MouseData(BaseData):
    """holds mouse data"""

    key = "mouse"

    def __init__(self, action: str | None = None, extra_data: dict | None = None):
        super().__init__(self.key, action, extra_data)
        self.button_id: int = None
        self.value: int | None = None

    @staticmethod
    def create(button_id: int, value: int | None, action: str | None = None, extra_data: dict | None = None) -> MouseData:
        self = MouseData(action=action, extra_data=extra_data)
        self.button_id = button_id
        self.value = value
        self.action = action
        self.extra_data = extra_data
        return self

    def toPayload(self) -> dict:
        payload = super().toPayload()
        return {
            **payload,
            "button": self.button_id,
            "value": self.value,
        }

    @staticmethod
    def fromPayload(data: dict) -> MouseData:
        if data.get("key") != MouseData.key:
            raise ValueError("Invalid key for MouseData")
        self = MouseData(action=data.get("action"), extra_data=data.get("extra_data"))
        self.button_id = data["button"]
        self.value = data["value"]
        return self


class BlockData(BaseData):
    """holds generic block data"""

    key = "data"

    def __init__(self, data: dict, action: str | None = None, extra_data: dict | None = None):
        super().__init__(self.key, action, extra_data)
        self.data = data

    @staticmethod
    def create(data: dict, action: str | None = None, extra_data: dict | None = None) -> BlockData:
        self = BlockData(data=data, action=action, extra_data=extra_data)
        return self

    def toPayload(self) -> dict:
        payload = super().toPayload()
        return {**payload, "data": self.data}

    @staticmethod
    def fromPayload(data: dict) -> BlockData:
        assert data.get("key") == BlockData.key, "Invalid key for BlockData"
        self = BlockData(data=data["data"], action=data.get("action"), extra_data=data.get("extra_data"))
        return self


def _client_address_key(address: str) -> str:
    return address.strip().rstrip(".").casefold()


def normalize_client_address(address: str) -> str:
    """Normalize an IPv4 address or network name used as a client selector."""
    address = _client_address_key(address)
    if re.fullmatch(r"[\d.]+", address) and "." in address:
        ip = ipaddress.IPv4Address(address)
        if ip.is_unspecified or ip.is_multicast or address == "255.255.255.255":
            raise ValueError("Enter a client IPv4 address or network name.")
    elif not re.fullmatch(r"[\w-]+(?:\.[\w-]+)*", address):
        raise ValueError("Enter a client IPv4 address or network name.")
    return address


def read_client_selection(node) -> frozenset[str] | None:
    """Read the saved checklist. An absent element represents Select All."""
    if node is None:
        return None
    return frozenset(
        address for client in node.findall("client")
        if (address := _client_address_key(client.get("address", "")))
    )


def write_client_selection(parent, tag: str, selection: frozenset[str] | None):
    """Write an explicit allowlist, including an empty one."""
    if selection is not None:
        node = ElementTree.SubElement(parent, tag)
        for address in sorted(selection):
            ElementTree.SubElement(node, "client", address=address)


class ClientData:
    """holds network client data"""

    def __init__(self, auto: bool = True):
        cfg = gremlin.config.Configuration()
        self.client_id = remote_client.clientId if auto else None  # id is a unique id corresponding to the host

        # client name - user specified or system default
        client_name = cfg.client_name
        if client_name:
            self.client_name = client_name
        else:
            self.client_name = remote_client.clientName if auto else gremlin.util.getHostName()

        self.custom_name = remote_client.customName if auto else None  # custom name of the client (optional)
        self.client_version = gremlin.shared_state.application_version if auto else None  # version of the client (optional)
        self.client_timestamp = gremlin.shared_state.application_start_time if auto else None  # start time of the client (optional)
        self.host_name = socket.gethostname() if auto else ""
        self.host_ip = ""  # filled by receiver from UDP peer address
        self.video_enabled = False
        self.video_port = 0
        if auto:
            try:
                self.video_enabled = bool(cfg.enable_remote_control and cfg.remote_video_enabled)
                self.video_port = int(cfg.remote_video_port) if self.video_enabled else 0
            except Exception:  # noqa: BLE001
                self.video_enabled = False
                self.video_port = 0

    def getClientName(self):
        """gets the client name custom or system"""
        return self.custom_name if self.custom_name else self.client_name

    def addresses(self) -> tuple[str, ...]:
        """Return the advertised names and observed IPv4 address used for routing."""
        addresses = []
        for value in (self.host_name, self.client_name, self.custom_name, self.host_ip):
            if isinstance(value, str) and value:
                try:
                    addresses.append(normalize_client_address(value))
                except ValueError:
                    continue
        return tuple(addresses)

    @staticmethod
    def fromData(
        client_id: int,
        client_name: str,
        custom_name: str,
        client_version: str | None = None,
        client_timestamp: int | None = None,
    ):
        self = ClientData(False)
        self.client_name = client_name
        self.custom_name = custom_name
        self.client_id = client_id
        self.client_version = client_version
        self.client_timestamp = client_timestamp

        return self

    def toPayload(self) -> dict:
        """creates a payload from the data"""
        return {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "client_custom": self.custom_name,
            "client_version": self.client_version,
            "client_timestamp": self.client_timestamp,
            "host_name": self.host_name,
            "video_enabled": bool(self.video_enabled),
            "video_port": int(self.video_port or 0),
            "host_ip": str(self.host_ip or ""),
        }

    @staticmethod
    def fromPayload(data: dict) -> ClientData:
        """loads from payload"""
        cd = ClientData(auto=False)
        cd.client_id = data["client_id"]
        cd.client_name = data["client_name"]
        cd.custom_name = data["client_custom"]
        cd.client_version = data["client_version"]
        cd.client_timestamp = data["client_timestamp"]
        cd.host_name = str(data.get("host_name") or "")
        cd.video_enabled = bool(data.get("video_enabled", False))
        try:
            cd.video_port = int(data.get("video_port") or 0)
        except TypeError, ValueError:
            cd.video_port = 0
        cd.host_ip = str(data.get("host_ip") or "")
        return cd

    @property
    def uptime(self):
        """client up time"""
        if self.client_timestamp:
            return time.time() - self.client_timestamp
        return None

    def __hash__(self):
        return hash((self.client_id, self.client_name, self.custom_name, self.client_version, self.video_enabled, self.video_port, self.host_ip, self.host_name))

    def __eq__(self, other):
        if not isinstance(other, ClientData):
            return NotImplemented
        return (
            self.client_id == other.client_id
            and self.client_name == other.client_name
            and self.custom_name == other.custom_name
            and self.client_version == other.client_version
            and bool(self.video_enabled) == bool(other.video_enabled)
            and int(self.video_port or 0) == int(other.video_port or 0)
            and str(self.host_ip or "") == str(other.host_ip or "")
            and self.host_name == other.host_name
        )

    def __str__(self):
        stub = f"({self.custom_name})" if self.custom_name else ""
        video = f" video:{self.video_port}" if self.video_enabled else ""
        return f"client: {stub}[{self.client_name}]/[{self.client_id}]{video}"


class ClientOperation(enum.Enum):
    Select = "select"
    EnableAll = "enable-all"
    DisableAll = "disable-all"
    Unchanged = "unchanged"


class OutputMode(enum.Enum):
    Unchanged = "unchanged"
    LocalOnly = "local-only"
    RemoteOnly = "remote-only"
    LocalAndRemote = "local-and-remote"


class SelectionBehavior(enum.Enum):
    Permanent = "permanent"
    Temporary = "temporary"
    Toggle = "toggle"


_OUTPUT_MODES = {
    OutputMode.LocalOnly: VjoyAction.VJoyEnableLocalOnly,
    OutputMode.RemoteOnly: VjoyAction.VJoyEnableRemoteOnly,
    OutputMode.LocalAndRemote: VjoyAction.VJoyEnableLocalAndRemote,
}


@gremlin.singleton_decorator.SingletonDecorator
class RemoteControl:
    """holds remote control status information and known network client tracker"""

    def __init__(self):

        self._is_remote = False
        self._is_local = False
        self._is_paired = False
        config = gremlin.config.Configuration()
        self._global_remote_enabled = config.enable_remote_broadcast
        self._client_enabled = config.enable_remote_control
        self._clients = {}
        self._client_lock = threading.Lock()
        self._clients_path = Path(config.data_path()) / "clients.json"
        self._known_clients = self._load_known_clients()
        self._active_client_map: dict[str | int, bool] = {}
        self._client_overrides: dict[object, tuple[frozenset[str] | None, bool]] = {}
        self._active_client_ids: frozenset[int] = frozenset()
        self._all_clients_active = True
        self._broadcast_to_all_clients = True

        self._startup_commands: list[tuple[bool, VjoyAction]] | None = None
        self._mode = VjoyAction.VJoyEnableLocalOnly
        self._update(self._mode)
        el = gremlin.event_handler.EventListener()
        el.config_changed.connect(self._handle_options_changed)
        el.config_option_changed.connect(self._handle_options_changed)
        el.remote_control_enable.connect(self._handle_remote_control_enable)
        el.remote_control_disable.connect(self._handle_remote_control_disable)

        self.registerSelf()

    def registerSelf(self):
        """registers the current client"""

        self.registerClient(
            ClientData.fromData(
                self.clientId,
                self.hostName,
                self.customName,
                gremlin.shared_state.application_version,
                gremlin.shared_state.application_start_time,
            )
        )

    def _handle_remote_control_enable(self):
        """called when remote control should be enabled"""
        gremlin.config.Configuration().enable_remote_broadcast = True

    def _handle_remote_control_disable(self):
        """called when remote control should be enabled"""
        gremlin.config.Configuration().enable_remote_broadcast = False

    @property
    def customName(self) -> str:
        config = gremlin.config.Configuration()
        return config.custom_host_name

    @property
    def hostName(self) -> str:
        """host name of the current instance"""
        return socket.gethostname()

    @property
    def clientId(self) -> int:
        """unique instance id for this instance"""
        return uuid.getnode()

    @property
    def clientName(self) -> str:
        custom_name = self.customName
        return custom_name if custom_name else self.hostName

    @property
    def clientEnabled(self) -> bool:
        """true if remote control by another client is enabled"""
        config = gremlin.config.Configuration()
        return config.enable_remote_control

    def clientActive(self, client_id: int | str) -> bool:
        """Return whether the specified client ID is allowed to receive output."""
        with self._client_lock:
            return self._client_active(int(client_id))

    def _client_active(self, client_id: int) -> bool:
        if self._broadcast_to_all_clients:
            return True
        if self._all_clients_active and not self._client_overrides:
            return self._active_client_map.get(client_id, True)
        return client_id in self._active_client_ids

    def _refresh_active_client_ids(self):
        if self._client_overrides:
            addresses, solo = next(reversed(self._client_overrides.values()))
            self._broadcast_to_all_clients = addresses is None
            matches = frozenset(
                client_id for client_id, client in self._clients.items()
                if client_id != self.clientId and (addresses is None or not addresses.isdisjoint(client.addresses()))
            )
            self._active_client_ids = frozenset() if solo and len(matches) != 1 else matches
            return

        self._broadcast_to_all_clients = self._all_clients_active and not self._active_client_map
        self._active_client_ids = frozenset(
            client_id for client_id, client in self._clients.items()
            if client_id != self.clientId and self._active_client_map.get(
                client_id,
                self._all_clients_active or any(self._active_client_map.get(address) for address in client.addresses()),
            )
        )

    def setClientActive(self, client_id: int | str, active: bool):
        """Override the state of one client by ID."""
        with self._client_lock:
            self._active_client_map[int(client_id)] = active
            self._refresh_active_client_ids()

    def setActiveClients(self, addresses: frozenset[str] | None):
        """Replace the master filter with the selected IP addresses or names."""
        active = dict.fromkeys(map(_client_address_key, addresses or ()), True)
        with self._client_lock:
            self._active_client_map = active
            self._all_clients_active = not active
            self._refresh_active_client_ids()

    def resetActiveClients(self):
        """resets all clients to active"""
        self.setAllClientsActive(True)

    def setAllClientsActive(self, active: bool):
        """Enable or mute every client in the regular filter."""
        with self._client_lock:
            self._active_client_map.clear()
            self._all_clients_active = active
            self._refresh_active_client_ids()

    def applyClientOperation(self, operation: ClientOperation, selection: frozenset[str] | None):
        """Apply a client operation to the regular filter."""
        if operation is ClientOperation.Select:
            self.setActiveClients(selection)
        elif operation in (ClientOperation.EnableAll, ClientOperation.DisableAll):
            self.setAllClientsActive(operation is ClientOperation.EnableAll)

    def applyOutputMode(self, output_mode: OutputMode):
        """Apply the requested profile output routing."""
        if output_mode in _OUTPUT_MODES:
            self.mode = _OUTPUT_MODES[output_mode]

    def beginClientSolo(self, hold: object, address: str):
        """Temporarily filter output to one uniquely identified client."""
        self.beginClientOverride(hold, frozenset({address}), solo=True)

    def endClientSolo(self, hold: object):
        """Remove the temporary filter for a Solo input."""
        self.endClientOverride(hold)

    def beginClientOverride(self, owner: object, addresses: frozenset[str] | None, *, solo: bool = False):
        """Override the filter. None enables all clients and an empty set disables all."""
        active = None if addresses is None else frozenset(map(_client_address_key, addresses))
        with self._client_lock:
            self._client_overrides[owner] = active, solo
            self._refresh_active_client_ids()

    def endClientOverride(self, owner: object):
        """Reveal the previous override or the regular filter."""
        with self._client_lock:
            if self._client_overrides.pop(owner, None) is not None:
                self._refresh_active_client_ids()

    def getActiveClients(self) -> set[int]:
        """Return IDs of registered remote clients allowed to receive output."""
        with self._client_lock:
            return set(self._active_client_ids)

    @property
    def clientFiltered(self) -> bool:
        """true if any clients are currently filtered for output"""
        return not self._broadcast_to_all_clients

    def filterClientTargets(self, targets: tuple[int, ...]) -> tuple[int, ...] | frozenset[int]:
        """Resolve the broadcast target (0) or intersect explicit targets with the filter."""
        with self._client_lock:
            if 0 in targets:
                return self._active_client_ids if self.clientFiltered else (0,)
            return tuple(client_id for client_id in targets if self._client_active(client_id))

    @property
    def serverEnabled(self) -> bool:
        """true if remote control enabled for broadcast/server"""
        config = gremlin.config.Configuration()
        return config.enable_remote_broadcast

    def remoteEnabled(self) -> bool:
        """true if remote control is enabled - client or server - this checks the global options"""
        config = gremlin.config.Configuration()
        return config.remoteEnabled()

    def getLocalClientId(self):
        """gets the local client ID (this machine)"""
        return self.clientId

    def getClients(self) -> dict:
        """Get the currently registered clients."""
        with self._client_lock:
            return self._clients.copy()

    def getClient(self, client_id: str):
        """gets a registered client"""
        with self._client_lock:
            return self._clients.get(client_id)

    def _load_known_clients(self) -> dict[str, str]:
        try:
            with self._clients_path.open(encoding="utf-8") as stream: # @IgnoreException
                clients = json.load(stream)["clients"]
            return {
                normalize_client_address(address): details
                for address, details in clients.items()
                if isinstance(details, str)
            }
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            syslog.exception("RPC: unable to load remote clients from %s", self._clients_path)
            return {}

    def _save_known_clients(self, clients: dict[str, str]):
        self._clients_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._clients_path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"clients": clients}, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
            gremlin.util.safeReplace(temporary, self._clients_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._known_clients = clients

    def getKnownClients(self) -> dict[str, str]:
        """Return saved client addresses and display details, including offline clients."""
        with self._client_lock:
            return self._known_clients.copy()

    def addKnownClient(self, address: str):
        """Remember an IPv4 address or network name entered by the user."""
        address = normalize_client_address(address)
        with self._client_lock:
            if address in self._known_clients:
                return
            self._save_known_clients({**self._known_clients, address: ""})
        self._emit_client_change()

    def addDiscoveredClients(self, computers: list[tuple[str, str]]) -> int:
        """Merge Windows Network Discovery results into the shared client catalog."""
        discovered = {}
        for name, address in computers:
            try:
                key = normalize_client_address(name)
            except ValueError:
                key = address
            discovered.setdefault(key, set()).add(address)

        with self._client_lock:
            clients = self._known_clients.copy()
            for name, addresses in discovered.items():
                if name in clients or any(address in clients for address in addresses):
                    continue
                clients[name] = ", ".join(sorted(addresses - {name}, key=ipaddress.IPv4Address))

            added = len(clients) - len(self._known_clients)
            if added:
                self._save_known_clients(clients)
        if added:
            self._emit_client_change()
        return added

    def removeKnownClient(self, address: str):
        """Forget a saved client address."""
        with self._client_lock:
            if address not in self._known_clients:
                return
            clients = self._known_clients.copy()
            del clients[address]
            self._save_known_clients(clients)
        self._emit_client_change()

    def registerClient(self, data: ClientData):
        """registers a client"""
        client_id = data.client_id
        if type(client_id) is not int or client_id <= 0:
            return
        with self._client_lock:
            changed = self._clients.get(client_id) != data
            if changed:
                self._clients[client_id] = data
                self._refresh_active_client_ids()

            config = gremlin.config.Configuration()
            if client_id != self.clientId and (config.enable_remote_broadcast or config.master):
                addresses = data.addresses()
                if addresses:
                    address = next((value for value in addresses if value in self._known_clients), addresses[0])
                    labels = (
                        value for value in (data.host_name, data.getClientName(), data.host_ip)
                        if isinstance(value, str) and value and _client_address_key(value) != address
                    )
                    details = ", ".join(dict.fromkeys(labels))
                    if self._known_clients.get(address) != details:
                        try:
                            self._save_known_clients({**self._known_clients, address: details})
                            changed = True
                        except OSError:
                            syslog.exception("RPC: unable to save remote clients to %s", self._clients_path)

        if changed:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"RPC: new/updated client registered: {data}")
            self._emit_client_change()

    def unregisterClient(self, client_id: str):
        """unregisters a client"""
        with self._client_lock:
            data = self._clients.pop(client_id, None)
            if data is None:
                return
            self._refresh_active_client_ids()

        if gremlin.config.Configuration().verbose_mode_remote:
            syslog.info(f"RPC: client unregistered: {data}")

        self._emit_client_change()

    def _emit_client_change(self):
        """Notify UI of client list changes on the UI thread (UDP handlers are not)."""

        def _do():
            el = gremlin.event_handler.EventListener()
            el.remote_control_client_change.emit()

        # is_ui_thread() is True when QApplication is not up yet (import-time init)
        if gremlin.util.is_ui_thread():
            _do()
        else:
            gremlin.util.InvokeUiMethod(_do)

    @contextmanager
    def collect_startup_commands(self):
        """Apply startup commands after reading the inputs for the initial mode."""
        commands = []
        self._startup_commands = commands
        try:
            yield
        finally:
            self._startup_commands = None

        # Released inputs establish the fallback routing. Held inputs then
        # take precedence, independent of which mapping was registered first.
        for _, command in sorted(commands, key=lambda item: item[0]):
            self.mode = command

    def sync_startup_command(self, command: VjoyAction, pressed: bool):
        if self._startup_commands is None:
            self.mode = command
        else:
            self._startup_commands.append((pressed, command))

    def _update(self, value):
        is_local = self._is_local
        is_remote = self._is_remote
        is_paired = self._is_paired
        if value == VjoyAction.VJoyDisableLocal:
            is_local = False
        elif value == VjoyAction.VJoyDisableRemote:
            is_remote = False
        elif value == VjoyAction.VJoyEnableLocalOnly:
            is_local = True
            is_remote = False
        elif value == VjoyAction.VJoyEnableRemoteOnly:
            is_local = False
            is_remote = True
        elif value == VjoyAction.VJoyEnableLocalAndRemote:
            is_local = True
            is_remote = True
        elif value == VjoyAction.VJoyEnableLocal:
            is_local = True
        elif value == VjoyAction.VJoyEnableRemote:
            is_remote = True
        elif value == VjoyAction.VJoyToggleRemote:
            is_local = not self._is_local
            is_remote = not self._is_remote
        elif value == VjoyAction.VJoyEnablePairedRemote:
            is_paired = True
        elif value == VjoyAction.VJoyDisablePairedRemote:
            is_paired = False
        else:
            # not sure what this was
            return

        self._mode = value

        if self._is_local != is_local or self._is_remote != is_remote:
            # status changed
            self._is_local = is_local
            self._is_remote = is_remote

            # Publish the complete routing state, including local-only changes.
            el = gremlin.event_handler.EventListener()
            el.remote_control_state_change.emit()

            syslog.info(f"REMOTE CONTROL: local [{'ENABLED' if self._is_local else 'DISABLED'}] remote [{'ENABLED' if self.is_remote else 'DISABLED'}]")

            self._handle_options_changed()

        if self._is_paired != is_paired:
            # pairing mode changed
            self._is_paired = is_paired
            if is_paired:
                msg = "Paired mode enabled"
            else:
                msg = "Paired mode disabled"
            syslog.info(f"REMOTE CONTROL: Paired mode changed: {msg}")
            thread = threading.Thread(target=self.say, args=(msg,), daemon=True)
            thread.name = "REMOTE CONTROL remote control paired update"
            thread.start()

    def _handle_options_changed(self):
        """Publish changes to the configured remote roles."""
        config = gremlin.config.Configuration()
        broadcast_changed = self._global_remote_enabled != config.enable_remote_broadcast
        client_changed = self._client_enabled != config.enable_remote_control
        if not (broadcast_changed or client_changed):
            return
        self._global_remote_enabled = config.enable_remote_broadcast
        self._client_enabled = config.enable_remote_control

        el = gremlin.event_handler.EventListener()
        if broadcast_changed:
            el.broadcast_changed.emit(self.to_state_event())
            self.registerSelf()
        if client_changed and gremlin.shared_state.is_running and config.remote_video_enabled:
            try:
                from gremlin.remote_video import sync_publisher_with_runtime

                gremlin.util.InvokeUiMethod(sync_publisher_with_runtime)
            except Exception:  # noqa: BLE001
                syslog.exception("RPC: could not update remote video after a role change")
        el.remote_control_state_change.emit()

    def say(self, msg):
        speech = InternalSpeech()
        speech.speak(msg)

    def setLocal(self, value: bool):
        """enable/disable local"""
        if value:
            self._update(VjoyAction.VJoyEnableLocal)
        else:
            self._update(VjoyAction.VJoyDisableLocal)

    def setRemote(self, value: bool):
        """enable/disable local"""
        if value:
            self._update(VjoyAction.VJoyEnableRemote)
        else:
            self._update(VjoyAction.VJoyDisableRemote)

    def toggleRemote(self):
        self._update(VjoyAction.VJoyToggleRemote)

    def isKeyboardSupressed(self) -> bool:
        """gets the current suspended state"""
        import gremlin.windows_event_hook

        return gremlin.windows_event_hook.KeyboardHook().isSupressed()

    def isMouseSupressed(self) -> bool:
        """gets the current suspended state"""
        import gremlin.windows_event_hook

        return gremlin.windows_event_hook.MouseHook().isSupressed()

    def _broadcast_changed(self, event):
        config = gremlin.config.Configuration()
        if config.enable_broadcast_speech:
            msg = None
            if event.is_local and event.is_remote:
                msg = "Concurrent control mode enabled"
            elif event.is_local:
                msg = "Local control is enabled"
            elif event.is_remote:
                msg = "Remote control is enabled"
            if msg:
                thread = threading.Thread(target=self.say, args=(msg,), daemon=True)
                thread.name = "remove control broadcast"
                thread.start()

    @property
    def mode(self):
        """gets the current mode"""
        return self._mode

    @mode.setter
    def mode(self, value):
        self._update(value)

    @property
    def is_local(self):
        """status of local control"""
        return self._is_local

    @is_local.setter
    def is_local(self, value: bool):
        if self._is_local != value:
            self._is_local = value
            el = gremlin.event_handler.EventListener()
            el.remote_control_state_change.emit()

    @property
    def is_remote(self):
        """status of remote control - requires both remote and broadcast to be enabled"""
        return self._is_remote and self.serverEnabled

    @is_remote.setter
    def is_remote(self, value: bool):
        if self._is_remote != value:
            self._is_remote = value
            el = gremlin.event_handler.EventListener()
            el.remote_control_state_change.emit()  # indicate remote control changed

    @property
    def state(self):
        """returns status as a pair of flags, local, remote"""
        kvm_mode = self.isKeyboardSupressed() or self.isMouseSupressed()
        return (self.is_local and not kvm_mode, self.is_remote or kvm_mode)

    @property
    def paired(self):
        """paired status"""
        return self._is_paired

    def to_state_event(self):
        """returns event data for the current state"""
        from gremlin.event_handler import StateChangeEvent

        config = gremlin.config.Configuration()
        event = StateChangeEvent(self.is_local, self.is_remote, config.enable_remote_broadcast)
        return event


class PacketState(enum.Enum):
    New = 0
    Sent = 1
    Received = 2
    TimedOut = 3


class PacketData:
    """holds callback data info to track sent requests to other GEX clients"""

    def __init__(
        self,
        id: str | None = None,
        client_id: str | None = None,
        server_id: str | None = None,
        callback: Callable | None = None,
        data: dict | None = None,
        on_timeout: Callable | None = None,
    ):
        self.id = id if id else gremlin.util.get_guid()
        self.callback = callback
        self.on_timeout = on_timeout
        self._lock = threading.RLock()
        self._active = False
        self.data = data
        self.response = None
        self.sent = time.time()
        self.received = None
        self.client_id = client_id  # who to send the request to
        self.server_id = server_id  # who to send the request response to
        self.client_name = None  # optional name
        self.timer = None
        self.status = PacketState.New
        self.response = None  # receive data

    def start(self):
        with self._lock:
            if self.status != PacketState.New:
                return
            self._active = True
            self.status = PacketState.Sent
            self.timer = threading.Timer(4, self._handle_timeout)
            self.timer.daemon = True
            self.timer.start()

    def stop(self):
        """stops the timeout timer when a response is received"""
        with self._lock:
            self._active = False
            if self.timer:
                self.timer.cancel()
                self.timer = None

    def trigger(self, data: dict | None = None):
        """trigger the callback"""
        with self._lock:
            if not self._active:
                return
            self.response = data
            self.received = time.time()
            self.status = PacketState.Received
            if self.client_id:
                self.stop()
            if self.callback is not None:
                self.callback(self)

    def _handle_timeout(self):
        """called when request times out before getting a response"""
        with self._lock:
            if not self._active:
                return
            self.stop()
            if self.on_timeout is not None:
                self.on_timeout(self)
            if self.received is None:
                self.status = PacketState.TimedOut
                if self.callback is not None:
                    self.callback(self)


class RemoteClientData:
    def __init__(
        self,
        client_name: str | None = None,
        custom_client_name: str | None = None,
        client_id: int = 0,
        client_version: str | None = None,
        selected: bool = False,
    ):
        self.client_name = client_name  # client to send the data to (we store the name) - None = ANY
        self.custom_name = custom_client_name
        self._client_id = 0
        self.client_id = client_id  # client MAC address (the client ID may change session to session) - None = ANY
        self.client_version = client_version
        self.selected = selected
        self.discovered = False  # true if discovered on the network

    def getClientName(self) -> str:
        """gets the custom or host name"""
        return self.custom_name if self.custom_name else self.client_name

    @staticmethod
    def fromClientData(client: ClientData):
        self = RemoteClientData()
        self.client_name = client.client_name
        self.client_id = client.client_id
        self.client_version = client.client_version
        self.custom_name = client.custom_name
        return self

    @property
    def client_id(self) -> str:
        return self._client_id

    @client_id.setter
    def client_id(self, value: str):
        assert isinstance(value, int)
        self._client_id = value

    def to_xml(self):  # -> Any:
        """creates a node from the data block and returns it"""
        node = ElementTree.Element("client")

        # only save selected clients
        if self.client_name:
            node.set("client-name", self.client_name)
        if self.custom_name:
            node.set("custom-name", self.custom_name)
        if self.client_id:
            node.set("client-id", safe_format(self.client_id, int))
        node.set("selected", safe_format(self.selected, bool))
        return node

    def from_xml(self, node):
        """reads from the xml node - the node should be the parent node"""
        if "client-name" in node.attrib:
            self.client_name = node.get("client-name")
        if "custom-name" in node.attrib:
            self.custom_name = node.get("custom-name")
        if "client-id" in node.attrib:
            client_id = node.get("client-id")
            if client_id == "any":
                client_id = 0
            else:
                client_id = safe_read(node, "client-id", int, 0)
            if client_id == "any":
                client_id = 0  # legacy change
            self.client_id = client_id
        self.selected = safe_read(node, "selected", bool, False)

    @property
    def connected(self) -> bool:
        """true if the client is currently known to GremlinEx"""
        remote_control = RemoteControl()
        return remote_control.getClient(self.client_id) is not None

    @property
    def isLocalClient(self) -> bool:
        """true if the data is for our own client"""
        remote_control = RemoteControl()
        return self._client_id == remote_control.getLocalClientId()

    @staticmethod
    def any() -> RemoteClientData:
        return RemoteClientData("Any", 0)

    def __str__(self):
        version_stub = f"/[{self.client_version}]" if self.client_version else ""
        return f"[{self.client_name}]/[{self.client_id}]{version_stub}"


class RemoteConfig:
    """holds configuration data for a remote client broadcast - this is persisted to the profile per action if needed"""

    client_changed = Signal()  # fires when clients are added or removed

    def __init__(
        self,
        local: bool = True,
        remote: bool = False,
        local_enabled: bool = True,
        remote_enabled: bool = True,
        remote_profile_enabled: bool = True,
        singleton: bool = False,
        client_change_callback=None,
    ):

        self._local: bool = local  # send to local client
        self._local_enabled: bool = local_enabled  # true if the action can send to the local client

        self._clients = {}  # map of client [client_id] -> RemoteClientData

        self._remote: bool = remote  # send to remote client
        self._remote_enabled: bool = remote_enabled  # true if remote is enabled

        self._remote_profile: bool = True  # true if the action is sending local when profile is not in remote mode, and remote when profile is in remote mode
        self._remote_profile_enabled: bool = (
            remote_profile_enabled  # true when remote profile is enabled for this configuration (this is set by actions that don't allow this mode)
        )

        self._is_custom: bool = False  # true if the configuration is custom set

        self._profile_remote_mode_enabled: bool = remote_enabled  # true if the action can send to a remote client
        self._process_name: str = None  # target process name (None if target is the window with focus)
        self._is_target_process: bool = False  # true if a target process is defined
        self._is_partial_match: bool = True  # true if we are matching partial titles when looking for a target process by title

        self._client_changed_callbacks = []
        if client_change_callback:
            self._client_change_callbacks.append(client_change_callback)
        self.ensureAnyClient()  # ensure the ANY client is in the list
        self._clients[0].selected = True
        self.singleton: bool = singleton  # true if the remote control can only send to a single client
        el = gremlin.event_handler.EventListener()
        el.remote_control_client_change.connect(self._clients_changed)

        self._sync_clients()  # populate existing clients

    def registerClientChangeCallback(self, callback):
        """add a callback on client changes"""
        if callback and callback not in self._client_changed_callbacks:
            self._client_changed_callbacks.append(callback)

    def unregisterClientChangeCallback(self, callback):
        """removes a callback from this config object"""
        if callback and callback in self._client_changed_callbacks:
            self._client_changed_callbacks.remove(callback)

    def _clients_changed(self):
        """known client list chagned - synchronize with current list"""

        verbose = gremlin.config.Configuration().verbose_mode_remote_extra
        if verbose:
            syslog.info("RPC: remote config: received client change event")

        changed = self._sync_clients()

        # notify clients changed
        if changed:
            if self._client_changed_callbacks:
                for callback in self._client_changed_callbacks:
                    callback()

            self.client_changed.emit()

    def _sync_clients(self) -> bool:
        """synchronizes clients list with received network data"""
        _verbose = gremlin.config.Configuration().verbose_mode_remote
        clients = remote_control.getClients()
        changed = len(self._clients) != (len(clients) if clients else 0)

        if clients:
            # update clients
            for client_id in clients:
                client: ClientData = clients[client_id]
                if client_id not in self._clients:
                    # if verbose: syslog.info(f"RPC: config: register new client [{client.client_name}]")
                    self.addClient(
                        client.client_name,
                        client.client_id,
                        client.client_version,
                        client.custom_name,
                    )
                    if client.client_id in self._clients:
                        self._clients[client.client_id].discovered = True
                    changed = True
                else:
                    c1: RemoteClientData = self._clients[client_id]
                    # record changes
                    if c1.custom_name != client.custom_name:
                        c1.custom_name = client.custom_name
                        changed = True
                    if getattr(client, "client_version", None) and c1.client_version != client.client_version:
                        c1.client_version = client.client_version
                        changed = True

            client: RemoteClientData
            for client in self._clients.values():
                connected = client.connected
                if client.discovered != connected:
                    client.discovered = connected
                    changed = True

        return changed

    def getClientList(self) -> list:
        """gets the list of active output clients"""
        if not self.isCustom or self.anySelected():
            return [0]  # any
        return [client.client_id for client in self._clients.values() if client.selected and client.client_id != 0]

    @property
    def isCustom(self) -> bool:
        """true if using custom routing"""
        return self._is_custom

    @isCustom.setter
    def isCustom(self, value: bool):
        self._is_custom = value

    @property
    def isProcess(self) -> bool:
        """true if a custom target process is used"""
        return self._is_target_process

    @isProcess.setter
    def isProcess(self, value: bool):
        self._is_target_process = value

    @property
    def partialMatch(self) -> bool:
        return self._is_partial_match

    @partialMatch.setter
    def partialMatch(self, value: bool):
        self._is_partial_match = value

    @property
    def localEnabled(self) -> bool:
        """true if local mode is enabled for active output"""
        if self._remote_profile:
            # exclusive mode
            rc = RemoteControl()
            return self._local_enabled and rc.is_local
        return self._local_enabled

    @localEnabled.setter
    def localEnabled(self, value: bool):
        self._local_enabled = value

    @property
    def remote(self) -> bool:
        """true if remote control is enabled"""
        return self._remote

    @remote.setter
    def remote(self, value: bool):
        self._remote = value

    @property
    def remoteEnabled(self) -> bool:
        return self._remote_enabled

    @remoteEnabled.setter
    def remoteEnabled(self, value: bool):
        self._remote_enabled = value

    @property
    def activeRemote(self) -> bool:
        """true if remote control is actively enabled for this action (runtime)"""
        if gremlin.shared_state.is_running:
            # profile must be running
            rc = RemoteControl()
            if self._remote_profile:
                return self.remoteProfileEnabled and rc.is_remote
            if self._remote:
                return self.remoteEnabled and rc.remoteEnabled
        return False

    @property
    def activeLocal(self) -> bool:
        """true if local mode is enabled (runtime)"""
        return gremlin.shared_state.is_running and self._local and self.localEnabled

    @property
    def remoteProfile(self) -> bool:
        return self._remote_profile

    @remoteProfile.setter
    def remoteProfile(self, value: bool):
        self._remote_profile = value

    @property
    def remoteProfileEnabled(self) -> bool:
        return self._remote_profile_enabled

    @remoteProfileEnabled.setter
    def remoteProfileEnabled(self, value: bool):
        self._remote_profile_enabled = value

    @property
    def local(self) -> bool:
        """true if local is enabled"""
        return self._local_enabled and self._local

    @local.setter
    def local(self, value: bool):
        self._local = value

    @property
    def process(self) -> str:
        return self._process_name

    @process.setter
    def process(self, value: str):
        self._process_name = value

    def selectAll(self):
        """selects all clients"""
        for client in self._clients.values():
            client.selected = True

    def selectNone(self):
        """selects no clients"""
        for client in self._clients.values():
            client.selected = False

    @property
    def state(self) -> tuple:
        """gets the active local, remote state"""
        return (self.activeLocal, self.activeRemote)

    def _handle_request_client_response(self, packet: PacketData):
        """called as clients respond to the request"""
        response = packet.response
        if response:
            client = ClientData(False).fromPayload(response)
            syslog.info("REMOTE: received client response:")
            syslog.info(f"client [{client.client_name}][{client.client_id}] version: [{client.client_version}]")
            remote_control.registerClient(client)

        syslog.info(f"Status: [{packet.status.name}]")

    def getState(self) -> tuple:
        """gets the connection state"""
        return (self.activeLocal, self.activeRemote)

    def getClient(self, client_id: int) -> RemoteClientData:
        """gets a client by ID"""
        if client_id in self._clients:
            return self._clients[client_id]
        return None

    def getLocalClientId(self):
        return remote_control.getLocalClientId()

    def addClient(
        self,
        client_name: str,
        client_id: str | int,
        client_version: str | None = None,
        custom_name: str | None = None,
    ) -> RemoteClientData:
        """adds a new client to the config if it doesn't exist, can also update the name"""
        if client_id in self._clients:
            client = self._clients[client_id]
            if client.client_name != client_name:
                client.client_name = client_name
        else:
            client = RemoteClientData(client_name, custom_name, client_id, client_version)
            self._clients[client_id] = client

        return client

    def ensureAnyClient(self):
        """makes sure the ANY client is in the client list"""
        if 0 not in self._clients:
            self.addClient("Any", 0)

    def removeClient(self, client_id: str):
        """removes a client from the client list"""
        if client_id in self._clients:
            del self._clients[client_id]

    def anySelected(self) -> bool:
        """true if the any client is selected"""
        self.ensureAnyClient()
        return self._clients[0].selected

    def getClients(self) -> list[RemoteClientData]:
        """gets a list of all clients for this configuration"""
        self.ensureAnyClient()
        client_list = [client for client in self._clients.values()]
        if client_list:
            client_list.sort(key=lambda x: x.getClientName().casefold() if x.getClientName() else "")
        return client_list

    def getClientCount(self) -> int:
        """gets the number of clients"""
        return len(self._clients)

    def getSelectedCount(self) -> int:
        """returns the number of selected clients"""
        return sum(1 if client.selected else 0 for client in self._clients.values())

    @property
    def enabled(self) -> bool:
        """true if remote control is enabled in GremlinEx"""
        return remote_client.enabled

    def setSelected(self, client_id: str, selected: bool):
        """selects or unselects a client"""

    def to_xml(self):  # -> Any:
        """creates a node from the data block and returns it"""
        node = ElementTree.Element("remote-config")
        node.set("custom", safe_format(self._is_custom, bool))
        node.set("local", safe_format(self._local, bool))
        node.set("remote", safe_format(self._remote, bool))
        node.set("remote-profile", safe_format(self._remote_profile, bool))
        node.set("singleton", safe_format(self.singleton, bool))
        if self.process:
            node.set("process", safe_format(self.process, str, escape=True))
        node.set("target-process", safe_format(self.isProcess, bool))
        node.set("partial-title", safe_format(self.partialMatch, bool))

        client: RemoteClientData
        for client in self._clients.values():
            if client.selected:
                client_node = client.to_xml()
                node.append(client_node)

        return node

    def from_xml(self, node):
        """reads from the xml node - the node should be the parent node"""
        self._is_custom = safe_read(node, "custom", bool, False)
        self._local = safe_read(node, "local", bool, True)
        self._remote = safe_read(node, "remote", bool, True)
        self._remote_profile = safe_read(node, "remote-profile", bool, True)
        self.singleton = safe_read(node, "singleton", bool, False)
        if "process" in node.attrib:
            self.process = safe_read(node, "process", str, None, unescape=True)
        self.isProcess = safe_read(node, "target-process", bool, False)
        self.partialMatch = safe_read(node, "partial-title", bool, True)

        # list of clients
        self.ensureAnyClient()
        for client in self._clients.values():
            client.selected = False
        client_nodes = node.xpath(".//client")
        for client_node in client_nodes:
            client = RemoteClientData()
            client.from_xml(client_node)
            self._clients[client.client_id] = client

        # ensure at least one client is selected
        count = self.getSelectedCount()
        if not count:
            client = self.getClient(0)
            client.selected = True


def remote_client_row_label(address: str, details: str) -> QtWidgets.QLabel:
    """Create a client label shared by the catalog and selection widgets."""
    from gremlin.ui.ui_common import Color, QDataLabel

    text = f"<b>{html.escape(address)}</b>"
    if details:
        text += f" — {html.escape(details)}"
    label = QDataLabel(text)
    label.setTextFormat(QtCore.Qt.TextFormat.RichText)
    label.setWordWrap(True)
    colors = Color()
    label.setStyleSheet(
        f"color: {colors.normalColor()}; background-color: {colors.actionBackgroundColor()};"
        f" border: 1px solid {colors.borderColor()}; border-radius: 6px; padding: 5px;"
    )
    return label


class RemoteClientSelectionWidget(QtWidgets.QWidget):
    """Edit a remote client selection using the shared catalog."""

    selectionChanged = QtCore.Signal(object)

    def __init__(
        self,
        selection: frozenset[str] | None = None,
        parent=None,
        *,
        show_solo=False,
        empty_selection_text="No clients selected. All clients are enabled.",
    ):
        from gremlin.ui.ui_common import QDataPushButton, QScrollableWidget

        super().__init__(parent)
        self._selection = selection
        self._show_solo = show_solo
        self._empty_selection_text = empty_selection_text
        self._catalog_entries = None
        self._checks = {}

        self._clients = QScrollableWidget(stretch=False, horizontal_scroll=False)
        self._clients.setAccessibleName("Remote clients")
        self._clients.getLayout().setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self._clients.setMinimumHeight(110)
        self._clients.setMaximumHeight(180)

        select_all = QDataPushButton("Select All", clicked=lambda: self._set_selection(None))
        select_none = QDataPushButton("Select None", clicked=lambda: self._set_selection(frozenset()))
        edit = QDataPushButton("Edit Clients…", clicked=self._manage_clients)
        for button in (select_all, select_none, edit):
            button.setAutoDefault(False)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(select_all)
        buttons.addWidget(select_none)
        buttons.addStretch()
        buttons.addWidget(edit)

        self._status = QtWidgets.QLabel()
        self._status.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._clients)
        layout.addLayout(buttons)
        layout.addWidget(self._status)

        gremlin.event_handler.EventListener().remote_control_client_change.connect(self._refresh)
        self._refresh()

    @QtCore.Slot()
    def _refresh(self):
        from gremlin.ui.ui_common import QDataCheckbox, QDataLabel, QDataPushButton, getHContainer

        known = remote_control.getKnownClients()
        for address in self._selection or ():
            known.setdefault(address, "")
        if known != self._catalog_entries:
            self._catalog_entries = known
            self._clients.clear()
            self._checks.clear()
            if not known:
                self._clients.addWidget(QDataLabel("No clients are saved. Use Edit Clients to add a client."))
            for address, details in sorted(known.items()):
                checkbox = QDataCheckbox()
                checkbox.setAccessibleName(f"Include {address}")
                checkbox.toggled.connect(self._checked_changed)
                self._checks[address] = checkbox
                label = remote_client_row_label(address, details)
                widgets = [checkbox, (label, 1)]
                if self._show_solo:
                    solo = QDataPushButton(
                        "Solo",
                        clicked=lambda _checked=False, address=address: self._set_selection(frozenset({address})),
                        tooltip=f"Select only {address}",
                    )
                    solo.setAccessibleName(f"Solo {address}")
                    solo.setAutoDefault(False)
                    widgets.append(solo)
                self._clients.addWidget(getHContainer(widgets, right_stretch=False, widget_only=True))
        for address, checkbox in self._checks.items():
            with QtCore.QSignalBlocker(checkbox):
                checkbox.setChecked(self._selection is None or address in self._selection)
        self._update_status()

    def _update_status(self):
        if self._selection:
            self._status.setText("Only checked clients receive remote output.")
        elif self._selection is None:
            self._status.setText("All clients are enabled, including newly discovered clients.")
        else:
            self._status.setText(self._empty_selection_text)

    def _set_selection(self, selection):
        if self._selection != selection:
            self._selection = selection
            self._refresh()
            self.selectionChanged.emit(selection)

    @QtCore.Slot()
    def _checked_changed(self):
        self._selection = frozenset(address for address, checkbox in self._checks.items() if checkbox.isChecked())
        self._update_status()
        self.selectionChanged.emit(self._selection)

    @QtCore.Slot()
    def _manage_clients(self):
        from gremlin.ui.dialogs import show_remote_clients

        show_remote_clients(self)


class RemoteClientOptionsWidget(QtWidgets.QWidget):
    """Edit the shared client filter and output routing options."""

    changed = QtCore.Signal()

    def __init__(
        self,
        operation: ClientOperation,
        output_mode: OutputMode,
        selection: frozenset[str] | None,
        parent=None,
        *,
        behavior: SelectionBehavior | None = None,
    ):
        from gremlin.ui.ui_common import QDataCheckbox, QDataRadioButtonGroup, getHContainer

        super().__init__(parent)
        self.operation = operation
        self.output_mode = output_mode
        self.selection = selection
        self.behavior = behavior

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QDataRadioButtonGroup(
            options=[
                ("No change", ClientOperation.Unchanged, "Keep the current remote client filter"),
                ("Selection", ClientOperation.Select, "Choose clients from the checklist"),
                ("Enable all", ClientOperation.EnableAll, "Enable all remote clients"),
                ("Mute all", ClientOperation.DisableAll, "Mute all remote clients"),
            ],
            value=operation,
            label="Mode",
            callback=self._operation_changed,
        ))
        layout.addWidget(QDataRadioButtonGroup(
            options=[
                ("No change", OutputMode.Unchanged, "Keep the current profile output routing"),
                ("Local", OutputMode.LocalOnly),
                ("Remote", OutputMode.RemoteOnly),
                ("Both", OutputMode.LocalAndRemote),
            ],
            value=output_mode,
            label="Routing",
            callback=self._output_changed,
        ))

        if behavior is not None:
            self._hold_widget = QDataCheckbox("Hold", tooltip="Apply the remote client filter while the mapped input is held.")
            self._hold_widget.toggled.connect(self._hold_changed)
            self._toggle_widget = QDataCheckbox(
                "Toggle on each trigger", tooltip="Apply or remove this client selection each time the action executes."
            )
            self._toggle_widget.toggled.connect(self._toggle_changed)
            self._behavior_container = getHContainer(["Behavior", self._hold_widget, self._toggle_widget], widget_only=True)
            layout.addWidget(self._behavior_container)

        checklist_options = {}
        if behavior is not None:
            checklist_options["empty_selection_text"] = "No clients selected. This action is skipped at runtime."
        self._client_list_widget = RemoteClientSelectionWidget(selection, self, show_solo=True, **checklist_options)
        self._client_list_widget.selectionChanged.connect(self._selection_changed)
        layout.addWidget(self._client_list_widget)
        self._update_options()

    def _update_options(self):
        selecting = self.operation is ClientOperation.Select
        self._client_list_widget.setVisible(selecting)
        if self.behavior is not None:
            self._behavior_container.setVisible(self.operation is not ClientOperation.Unchanged)
            self._toggle_widget.setVisible(selecting)
            with QtCore.QSignalBlocker(self._hold_widget), QtCore.QSignalBlocker(self._toggle_widget):
                self._hold_widget.setChecked(self.behavior is SelectionBehavior.Temporary)
                self._toggle_widget.setChecked(self.behavior is SelectionBehavior.Toggle)

    def _operation_changed(self, operation):
        self.operation = operation
        if operation in (ClientOperation.EnableAll, ClientOperation.DisableAll) and self.behavior is SelectionBehavior.Toggle:
            self.behavior = SelectionBehavior.Permanent
        self._update_options()
        self.changed.emit()

    def _output_changed(self, output_mode):
        self.output_mode = output_mode
        self.changed.emit()

    def _hold_changed(self, enabled):
        self._set_behavior(SelectionBehavior.Temporary if enabled else SelectionBehavior.Permanent)

    def _toggle_changed(self, enabled):
        self._set_behavior(SelectionBehavior.Toggle if enabled else SelectionBehavior.Permanent)

    def _set_behavior(self, behavior):
        self.behavior = behavior
        self._update_options()
        self.changed.emit()

    @QtCore.Slot(object)
    def _selection_changed(self, selection):
        self.selection = selection
        self.changed.emit()


# remote state
remote_control = RemoteControl()

# Global remote server = listens to remote client events
remote_server = RemoteServer()

# Global remote client = sends events to server
remote_client = RemoteClient()
