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


"""Map the local Tobii Game Hub head-pose stream to joystick axes."""

import logging
import math
import socket
import struct
from time import monotonic
from uuid import NAMESPACE_URL, uuid5
from weakref import ref

from PySide6 import QtCore

import dinput
from gremlin import joystick_handling, shared_state
from gremlin.config import Configuration
from gremlin.event_handler import EventListener
from gremlin.types import DeviceType

syslog = logging.getLogger("system")
POSE_PACKET = struct.Struct("<6d")
# The local head-pose UDP format carries X/Y/Z in centimeters and yaw/pitch/roll in degrees.
AXIS_LIMITS = (50.0, 50.0, 50.0, 180.0, 180.0, 180.0)
NEUTRAL = (0,) * len(AXIS_LIMITS)
STREAM_TIMEOUT = 0.75
TOBII_GUID = dinput.GUID(uuid5(NAMESPACE_URL, "gex:tobii-game-hub"))


def decode_pose(packet):
    """Convert one little-endian Game Hub pose to signed joystick axis values."""
    if len(packet) != POSE_PACKET.size:
        return None
    pose = POSE_PACKET.unpack(packet)
    if not all(math.isfinite(value) for value in pose):
        return None
    return tuple(round(max(-1.0, min(1.0, value / limit)) * 32767) for value, limit in zip(pose, AXIS_LIMITS))


class _TobiiStream(QtCore.QObject):
    """Keep an enabled Tobii input available while its data source starts."""

    status_changed = QtCore.Signal(str)

    def __init__(self, guid, name, parent):
        super().__init__(parent)
        self.listener = EventListener()
        self.listener.shutdown.connect(self.stop)
        self.status = ""
        self.summary = dinput.DeviceSummary()
        self.summary.device_guid = guid
        self.summary.name = name
        self.summary.set_tobii_layout()
        self.summary.setConnected(False)
        self.summary.input_enabled = True
        self.summary.setAxisCallback(self.get_axis)

    def _set_status(self, text):
        if text != self.status:
            self.status = text
            self.status_changed.emit(text)

    def _register(self):
        self.summary.data["tobii_receiver"] = ref(self)
        guid = self.summary.device_guid
        joystick_handling.set_streamed_joystick_devices(DeviceType.Tobii, [self.summary], device_guid=guid)
        profile = shared_state.current_profile
        if profile is not None and (node := profile.devices.get(guid)) is not None:
            node.device = self.summary
        if shared_state.ui_ready:
            self.listener.refresh_devices.emit()

    def _mark_connected(self):
        if not self.summary.connected:
            self.summary.setConnected(True)
            self.listener.refresh_devices.emit()

    def _mark_disconnected(self):
        if self.summary.connected:
            self.summary.setConnected(False)
            self.listener.refresh_devices.emit()

    def _unregister(self):
        if "tobii_receiver" in self.summary.data:
            self.summary.setConnected(False)
            self.summary.setAxisCallback(None)
            joystick_handling.set_streamed_joystick_devices(DeviceType.Tobii, [], device_guid=self.summary.device_guid)
            self.summary.data.pop("tobii_receiver")


class TobiiReceiver(_TobiiStream):
    """Receive Game Hub packets and publish a stable GEX joystick device."""

    def __init__(self, port, parent=None):
        super().__init__(TOBII_GUID, "Tobii Head Tracking", parent)
        self.axes = NEUTRAL
        self.last_packet = None
        self.socket = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self._waiting_status = f"Waiting for Tobii Game Hub head tracking on 127.0.0.1:{port}."
        udp_socket = None
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            udp_socket.bind(("127.0.0.1", port))
            udp_socket.setblocking(False)  # @IgnoreException
        except OSError:
            if udp_socket is not None:
                udp_socket.close()
            self._set_status(f"Cannot listen for Tobii Game Hub on UDP port {port}. Check the port and restart GEX.")
            syslog.warning(f"Tobii: could not listen on UDP port {port}", exc_info=True)
        else:
            self.socket = udp_socket
            self._set_status(self._waiting_status)
            self.timer.start(8)
            syslog.info(f"Tobii: waiting for Game Hub head tracking on 127.0.0.1:{port}")
        self._register()

    def get_axis(self, index):
        return self.axes[index - 1] if 1 <= index <= len(self.axes) else 0

    def _update_axes(self, axes, *, final=False):
        old_axes, self.axes = self.axes, axes
        for index, (previous, value) in enumerate(zip(old_axes, axes), 1):
            if previous != value:
                event = dinput.InputEvent.from_values(TOBII_GUID, dinput.InputType.Axis, index, value)
                self.listener.process_joystick_input(event, final=final)

    @QtCore.Slot()
    def poll(self):
        if self.socket is None:
            return
        latest_pose = None
        for _ in range(32):
            try:
                packet = self.socket.recv(65535)  # @IgnoreException
            except BlockingIOError:
                break
            except OSError:
                syslog.exception("Tobii: UDP receiver stopped")
                self.timer.stop()
                self.socket.close()
                self.socket = None
                self.last_packet = None
                self._update_axes(NEUTRAL, final=True)
                self._set_status("Tobii Game Hub receiver stopped. Restart GEX to reconnect.")
                self._mark_disconnected()
                return
            if (pose := decode_pose(packet)) is not None:
                latest_pose = pose

        now = monotonic()
        if latest_pose is not None:
            self._mark_connected()
            if self.last_packet is None:
                self._set_status("Receiving head tracking from Tobii Game Hub.")
                syslog.info("Tobii: receiving Game Hub head tracking")
            self.last_packet = now
            self._update_axes(latest_pose)
        elif self.last_packet is not None and now - self.last_packet >= STREAM_TIMEOUT:
            self.last_packet = None
            self._update_axes(NEUTRAL, final=True)
            self._set_status(self._waiting_status)
            syslog.info("Tobii: head tracking timed out. Axes returned to center.")

    @QtCore.Slot()
    def stop(self):
        self.timer.stop()
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        self.last_packet = None
        self._update_axes(NEUTRAL, final=True)
        self._unregister()


def start_tobii():
    """Start the optional local receiver after joystick enumeration."""
    config = Configuration()
    if config.tobii_gaze_enabled:
        from .gaze import GazeReceiver

        GazeReceiver(QtCore.QCoreApplication.instance())
    if config.tobii_enabled:
        return TobiiReceiver(config.tobii_port, QtCore.QCoreApplication.instance())
    return None
