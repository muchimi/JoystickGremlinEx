"""Read live Tobii gaze coordinates over the GEX Bridge OSC transport."""

import secrets
import struct
from time import monotonic

from PySide6 import QtCore, QtGui, QtNetwork

import dinput
from gremlin.config import Configuration
from gremlin.maestro import _decode_message, _encode_message

from . import STREAM_TIMEOUT, _TobiiStream, syslog


GAZE_COMMAND = "/maestro_tobii_gaze"
GAZE_REPLY = "/maestro_tobii_gaze_result"
NEUTRAL = (0, 0)


def normalize_gaze(x, y, width, height):
    """Convert valid screen pixel coordinates to right-positive and up-positive axes."""
    if width <= 0 or height <= 0:
        return None
    if not all(type(value) in (float, int) and -1e308 <= value <= 1e308 for value in (x, y)):
        return None
    return (
        round((2 * max(0, min(width, x)) / width - 1) * 32767),
        round((1 - 2 * max(0, min(height, y)) / height) * 32767),
    )


class GazeReceiver(_TobiiStream):
    """Publish the bridge's gaze stream as a read-only GEX joystick input."""

    def __init__(self, parent=None):
        super().__init__(dinput.TOBII_GAZE_GUID, "Tobii Eye Gaze", parent)
        self.axes = NEUTRAL
        self.last_sample = None

        config = Configuration()
        self.endpoint = (config.maestro_osc_host, config.maestro_osc_port)
        self._waiting_status = f"Waiting for eye gaze from GEX Bridge at {self.endpoint[0]}:{self.endpoint[1]}."
        self.request_id = secrets.randbelow(1 << 30)
        self.socket = QtNetwork.QUdpSocket(self)
        self.socket.setProxy(QtNetwork.QNetworkProxy(QtNetwork.QNetworkProxy.ProxyType.NoProxy))
        self.socket.readyRead.connect(self._receive)
        self.socket.connectToHost(*self.endpoint)
        self.timer = QtCore.QTimer(self, interval=250)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._set_status(self._waiting_status)
        self._register()
        syslog.info("Tobii Eye Gaze: waiting for GEX Bridge at %s:%s", *self.endpoint)

    def get_axis(self, index):
        return self.axes[index - 1] if 1 <= index <= len(self.axes) else 0

    def _poll(self):
        self._check_timeout()
        if self.socket.state() == QtNetwork.QAbstractSocket.SocketState.ConnectedState:
            self.request_id = (self.request_id + 1) % (1 << 31)
            self.socket.write(_encode_message(GAZE_COMMAND, (self.request_id,)))
        elif self.socket.state() == QtNetwork.QAbstractSocket.SocketState.UnconnectedState:
            self.socket.connectToHost(*self.endpoint)

    def _receive(self):
        while self.socket.hasPendingDatagrams():
            data, _, _ = self.socket.readDatagram(4096)
            try:
                address, values = _decode_message(bytes(data))
            except (ValueError, struct.error):
                continue
            if address != GAZE_REPLY or len(values) != 4 or values[0] != self.request_id:
                continue
            if values[1] is True:
                self._apply_gaze(*values[2:])
            elif values[1] is False and self.last_sample is not None:
                self._center()

    def _apply_gaze(self, x, y):
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return
        size = screen.size() * screen.devicePixelRatio()
        if (axes := normalize_gaze(x, y, size.width(), size.height())) is None:
            return
        self._mark_connected()
        if self.last_sample is None:
            self._set_status("Receiving eye gaze from GEX Bridge.")
            syslog.info("Tobii Eye Gaze: receiving gaze coordinates")
        self.last_sample = monotonic()
        if self.timer.interval() != 25:
            self.timer.setInterval(25)
        self._update_axes(axes)

    def _update_axes(self, axes, *, final=False):
        previous, self.axes = self.axes, axes
        for index, (old, value) in enumerate(zip(previous, axes), 1):
            if old != value:
                event = dinput.InputEvent.from_values(self.summary.device_guid, dinput.InputType.Axis, index, value)
                self.listener.process_joystick_input(event, final=final)

    def _check_timeout(self):
        if self.last_sample is not None and monotonic() - self.last_sample >= STREAM_TIMEOUT:
            self._center()

    def _center(self):
        self.last_sample = None
        self.timer.setInterval(250)
        self._update_axes(NEUTRAL, final=True)
        self._set_status(self._waiting_status)

    def stop(self):
        self.timer.stop()
        self.socket.abort()
        self._center()
        self._unregister()
