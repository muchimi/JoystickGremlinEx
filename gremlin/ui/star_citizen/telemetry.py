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


"""Star Citizen telemetry client, vehicle state transitions, and virtual inputs."""

import logging
import os
import threading
import time
import winreg
from dataclasses import dataclass
from itertools import chain

from psygnal import Signal
from PySide6 import QtCore

import gremlin.config
import gremlin.shared_state
from gremlin.input_types import InputType
from gremlin.singleton_decorator import SingletonDecorator

ADDRESS = "127.0.0.1:2942"
ENVIRONMENT_FLAG = "GRPC_CLIENT_SERVER_ENABLED"
syslog = logging.getLogger("system")


def telemetry_enabled():
    value = os.getenv(ENVIRONMENT_FLAG)
    if value is None:
        for hive, path in (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ):
            try:
                with winreg.OpenKey(hive, path) as key:
                    value, _ = winreg.QueryValueEx(key, ENVIRONMENT_FLAG)  # @IgnoreException
                break
            except OSError:
                continue
    return str(value).strip().casefold() in {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class TelemetryInput:
    button: int
    label: str
    address: str
    field: str


DEPLOYMENT = {1: "retracted", 2: "deploying", 3: "deployed", 4: "retracting"}
ANNUNCIATOR = {1: "nominal", 2: "off", 3: "minor-flashing", 4: "minor", 5: "major-flashing", 6: "major"}
MASTER_MODE = {1: "navigation", 2: "scm", 3: "stealth"}

# Button IDs are persisted in profiles. Append new groups after the existing groups.
_STATES = (
    ("gear", "Landing gear", DEPLOYMENT.values()),
    ("lights", "Lights", ("on", "off")),
    ("shield-generators", "Shield generators", ("on", "off")),
    ("shield-emitters", "Shield emitters", ("on", "off")),
    ("shield-status", "Shield status", ANNUNCIATOR.values()),
    ("quantum-drive", "Quantum drive status", ANNUNCIATOR.values()),
    ("quantum-spool", "Quantum spool", ("on", "off")),
    ("flight-ready", "Flight ready", ("on", "off")),
    ("engines", "Engines", ("on", "off")),
    ("wings", "Wing transformation", DEPLOYMENT.values()),
    ("vtol", "VTOL", DEPLOYMENT.values()),
    ("main-power", "Main power", ("on", "off")),
    ("weapons-power", "Weapons power", ("on", "off")),
    ("landed", "Landed", ("on", "off")),
    ("master-mode", "Master mode", MASTER_MODE.values()),
)


_ADDITIONAL_POWER_STATES = (
    ("shields", "Shields", ("on", "off")),
    ("coolers", "Coolers", ("on", "off")),
    ("life-support", "Life support", ("on", "off")),
    ("gravity-generators", "Gravity generators", ("on", "off")),
    ("sensors", "Sensors", ("on", "off")),
)


def _make_inputs(states):
    for field, label, values in states:
        for value in ("changed", *values):
            yield field, value, f"{label} — {value.replace('-', ' ')}"

    for field, label, values in states:
        if "deployed" in values or "on" in values:
            active = "deployed" if "deployed" in values else "on"
            yield field, "state", f"{label} (held while {active})"


_inputs_by_state = {
    (field, value): TelemetryInput(index, label, f"/star-citizen/{field}/{value}", field)
    for index, (field, value, label) in enumerate(chain(_make_inputs(_STATES), _make_inputs(_ADDITIONAL_POWER_STATES)), 1)
}
INPUTS = {key: item for key, item in _inputs_by_state.items() if key[1] != "state"}
HELD_INPUTS = {field: item for (field, value), item in _inputs_by_state.items() if value == "state"}
BUTTONS = {item.button: item for item in _inputs_by_state.values()}


def _on_off(value):
    return "on" if value else "off"


def vehicle_snapshot(frame):
    """Decode only states whose containing message is present."""
    if not frame.vehicle.HasField("state"):
        return None
    state = frame.vehicle.state
    # A frame with no vehicle identity or state subsystems is not a snapshot.
    if not state.ListFields():
        return None
    values = {"lights": _on_off(state.lights)}
    if state.flight.HasField("state"):
        flight = state.flight.state
        values["landed"] = _on_off(flight.landed)
        for name, value in (("gear", flight.gear), ("vtol", flight.vtol), ("wings", flight.transformation)):
            if value in DEPLOYMENT:
                values[name] = DEPLOYMENT[value]
    if state.HasField("power"):
        power = state.power
        values.update(
            {
                "main-power": _on_off(power.main),
                "engines": _on_off(power.engines),
                "weapons-power": _on_off(power.weapons),
                "shield-generators": _on_off(power.shield_generators),
                "shield-emitters": _on_off(power.shield_emitters),
                "shields": _on_off(power.shield_generators and power.shield_emitters),
                "coolers": _on_off(power.coolers),
                "life-support": _on_off(power.life_support),
                "gravity-generators": _on_off(power.gravity_generators),
                "sensors": _on_off(power.sensors),
                "flight-ready": _on_off(power.main and power.engines),
            }
        )
    if state.HasField("annunciators"):
        for name, value in (("shield-status", state.annunciators.shields), ("quantum-drive", state.annunciators.quantum_drive)):
            if value in ANNUNCIATOR:
                values[name] = ANNUNCIATOR[value]
    if state.HasField("master_mode"):
        values["quantum-spool"] = _on_off(state.master_mode.spooled)
        if state.master_mode.mode in MASTER_MODE:
            values["master-mode"] = MASTER_MODE[state.master_mode.mode]
    return (state.name, state.class_name), values


class StateChanges:
    def __init__(self):
        self._identity = None
        self._values = {}
        self._held_buttons = set()
        self._last_vehicle = None

    def snapshot(self):
        if self._identity is None:
            return None
        return self._identity, dict(self._values)

    @property
    def held_buttons(self):
        return frozenset(self._held_buttons)

    def update(self, frame, now):
        snapshot = vehicle_snapshot(frame)
        if self._last_vehicle is not None and now - self._last_vehicle > 2:
            self._identity = None
            self._values.clear()
            self._held_buttons.clear()
            self._last_vehicle = None
        if snapshot is None:
            return []

        identity, values = snapshot
        self._last_vehicle = now
        if identity != self._identity:
            self._identity = identity
            self._values.clear()
            self._held_buttons.clear()
        changes = []
        for field, value in values.items():
            held_input = HELD_INPUTS.get(field)
            if held_input is not None:
                if value in ("on", "deployed"):
                    self._held_buttons.add(held_input.button)
                elif value in ("off", "retracted"):
                    self._held_buttons.discard(held_input.button)
            previous = self._values.get(field)
            if previous is not None and value != previous:
                changes.extend((INPUTS[field, kind], previous, value) for kind in ("changed", value))
        self._values.update(values)
        return changes


@SingletonDecorator
class StarCitizenClient(QtCore.QObject):
    """Star Citizen client for handling telemetry and input events."""

    frame_changed = Signal(object)
    status_changed = QtCore.Signal(str)
    snapshot_changed = QtCore.Signal(object)
    input_preview_changed = QtCore.Signal(object, object)
    _transition = QtCore.Signal(object, object, object)
    _snapshot_ready = QtCore.Signal(object)
    _frame_ready = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        from gremlin import shared_state
        from gremlin.event_handler import EventListener

        app = QtCore.QCoreApplication.instance()
        if app is not None and self.thread() != app.thread():
            self.moveToThread(app.thread())

        self.device_guid = shared_state.star_citizen_tab_guid
        self.current_button = None
        self._held_buttons = set()
        self.preview_held_buttons = frozenset()
        self.status = "Waiting for Star Citizen"
        self.snapshot = None
        self._listener = EventListener()
        self._activation = None
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._channel = None
        self._actions = {}
        self._commands = set()
        self._worker = None
        self._transition.connect(self._handle_telemetry_inputs, QtCore.Qt.ConnectionType.QueuedConnection)
        self._snapshot_ready.connect(self._set_snapshot, QtCore.Qt.ConnectionType.QueuedConnection)
        self._frame_ready.connect(self._emit_frame_changed, QtCore.Qt.ConnectionType.QueuedConnection)
        self._listener.profile_started.connect(self._profile_started)
        self._listener.profile_stopping.connect(self._profile_stopping)
        self._listener.profile_stop.connect(self._profile_stopping)
        self._listener.shutdown.connect(self.close)
        if telemetry_enabled():
            self._worker = threading.Thread(target=self._read_telemetry, name="Star Citizen telemetry", daemon=True)
            self._worker.start()
        else:
            self._set_status("Set GRPC_CLIENT_SERVER_ENABLED=true to enable telemetry")

    def _set_status(self, text):
        if text != self.status:
            self.status = text
            self.status_changed.emit(text)

    @QtCore.Slot(object)
    def _set_snapshot(self, snapshot):
        if self.snapshot != snapshot:
            self.snapshot = snapshot
            self.snapshot_changed.emit(snapshot)

    @QtCore.Slot(object)
    def _emit_frame_changed(self, frame):
        self.frame_changed.emit(frame)

    def is_pressed(self, button):
        return button == self.current_button or button in self._held_buttons

    def _profile_started(self):
        with self._lock:
            self._activation = object()

    def _profile_stopping(self):
        with self._lock:
            self._activation = None
            self._held_buttons.clear()
            pending = tuple(self._commands)
        for command in pending:
            command.cancel()

    def close(self):
        self._closed.set()
        self._profile_stopping()
        with self._lock:
            channel = self._channel
        if channel is not None:
            channel.close()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(timeout=1.25)

    def _read_telemetry(self):
        try:
            import grpc

            from . import protocol
        except ImportError:
            self._set_status("Star Citizen telemetry requires grpcio and protobuf")
            return

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_star_citizen

        while not self._closed.is_set():
            previous_snapshot = None
            channel = grpc.insecure_channel(ADDRESS, options=(("grpc.enable_http_proxy", 0),))
            with self._lock:
                if self._closed.is_set():
                    channel.close()
                    return
                self._channel = channel
            try:
                grpc.channel_ready_future(channel).result(timeout=1) # @IgnoreException
                discover = channel.unary_unary(
                    protocol.SERVICE + "ListTriggerableActions",
                    response_deserializer=protocol.ActionList.FromString,
                )
                try:
                    # fails if the game is not running
                    actions = discover(b"", timeout=1)  # @IgnoreException
                    with self._lock:
                        self._actions = {item.action_name: item.holdable for item in actions.actions if item.action_name}
                except grpc.RpcError as error:
                    if error.code() != grpc.StatusCode.UNIMPLEMENTED:
                        syslog.debug("Star Citizen action discovery: %s", error.code().name)
                stream = channel.unary_stream(
                    protocol.SERVICE + "TelemetryStream",
                    response_deserializer=protocol.TelemetryFrame.FromString,
                )  # @IgnoreException
                previous_frame = protocol.TelemetryFrame()
                changes = StateChanges()
                previous_activation = None
                previous_held_buttons = frozenset()
                self._set_status("Connected to Star Citizen (telemetry and actions)" if self._actions else "Connected to Star Citizen (read-only telemetry)")
                for frame_number, frame in enumerate(stream(b""), 1):  # @IgnoreException
                    if frame_number == 1 and verbose:
                        syslog.info("STAR CITIZEN: receiving telemetry frames")
                    with self._lock:
                        activation = self._activation
                    transitions = changes.update(frame, time.monotonic())
                    snapshot = changes.snapshot()
                    if snapshot != previous_snapshot:
                        if verbose:
                            self._log_snapshot_change(previous_snapshot, snapshot)
                        self._snapshot_ready.emit(snapshot)
                        previous_snapshot = snapshot
                    held_buttons = changes.held_buttons
                    if transitions or held_buttons != previous_held_buttons or activation is not previous_activation:
                        self._transition.emit(activation, transitions, held_buttons)
                    previous_activation = activation
                    previous_held_buttons = held_buttons
                    if frame_number == 1 or frame != previous_frame:
                        previous_frame.CopyFrom(frame)
                        self._frame_ready.emit(frame)
            except grpc.FutureTimeoutError:
                if not self._closed.is_set():
                    self._set_status("Waiting for Star Citizen")
            except grpc.RpcError as error:
                if not self._closed.is_set():
                    self._set_status(f"Star Citizen telemetry: {error.code().name}")
            finally:
                channel.close()
                with self._lock:
                    self._channel = None
                    self._actions = {}
                    activation = self._activation
                if not self._closed.is_set():
                    if previous_snapshot is not None and verbose:
                        syslog.info("STAR CITIZEN: telemetry stream ended")
                    self._snapshot_ready.emit(None)
                    self._transition.emit(activation, [], frozenset())
            self._closed.wait(2)

    @staticmethod
    def _log_snapshot_change(previous, snapshot):
        if snapshot is None:
            syslog.info("STAR CITIZEN: vehicle telemetry unavailable")
            return

        identity, values = snapshot
        vehicle = identity[1] or identity[0] or "unknown vehicle"
        if previous is None or previous[0] != identity:
            state = ", ".join(f"{field}={value}" for field, value in sorted(values.items()))
            syslog.info("STAR CITIZEN: %s initial state: %s", vehicle, state)
            return

        previous_values = previous[1]
        updates = ", ".join(
            f"{field}: {previous_values.get(field, 'unavailable')} -> {values.get(field, 'unavailable')}"
            for field in sorted(previous_values.keys() | values.keys())
            if previous_values.get(field) != values.get(field)
        )
        syslog.info("STAR CITIZEN: %s %s", vehicle, updates)

    @QtCore.Slot(object, object, object)
    def _handle_telemetry_inputs(self, activation, transitions, held_buttons):
        if transitions or held_buttons != self.preview_held_buttons:
            newly_pressed = held_buttons - self.preview_held_buttons
            self.preview_held_buttons = held_buttons
            pulse_buttons = frozenset(item.button for item, _, _ in transitions)
            self.input_preview_changed.emit(pulse_buttons, held_buttons)
            if transitions:
                self._highlight_input(transitions, newly_pressed)
        if activation is not None:
            self._emit_inputs(activation, transitions, held_buttons)

    def _highlight_input(self, transitions, newly_pressed):

        profile = gremlin.shared_state.current_profile
        if profile is None or gremlin.shared_state.is_running or gremlin.shared_state.is_highlighting_suspended():
            return
        config = gremlin.config.Configuration()
        if not config.highlight_enabled or not config.highlight_input_buttons:
            return

        # Each change supplies a destination and a generic pulse. Select one row
        # so a single frame cannot repeatedly change the input selection.
        destinations = []
        changed = []
        for item, previous, value in transitions:
            candidates = changed if item == INPUTS[item.field, "changed"] else destinations
            candidates.append((item, previous, value))

        held = [(BUTTONS[button], "off", "on") for button in sorted(newly_pressed)]
        for item, previous, value in (*destinations, *held, *changed):
            if profile.settings.getInputVisible(self.device_guid, InputType.StarCitizen, item.button):
                self._listener.button_state_change.emit(self._button_event(item, previous, value, True))
                return

    def _emit_inputs(self, activation, transitions, held_buttons):

        if not gremlin.shared_state.is_running or self._activation is not activation:
            return

        released = self._held_buttons - held_buttons
        pressed = held_buttons - self._held_buttons
        self._held_buttons = set(held_buttons)
        osc = None
        if (released or pressed or transitions) and gremlin.config.Configuration().startup_osc_enabled:
            from gremlin.ui.osc_device import OscInterface

            osc = OscInterface()
        for button in sorted(released | pressed):
            if self._activation is not activation:
                return
            is_pressed = button in pressed
            previous, value = ("off", "on") if is_pressed else ("on", "off")
            self._emit_button(activation, BUTTONS[button], previous, value, is_pressed, osc)

        for item, previous, value in transitions:
            try:
                for is_pressed in (True, False):
                    if self._activation is not activation:
                        return
                    self.current_button = item.button if is_pressed else None
                    self._emit_button(activation, item, previous, value, is_pressed, osc)
            finally:
                self.current_button = None

    def _emit_button(self, activation, item, previous, value, pressed, osc):
        self._listener.joystick_event.emit(self._button_event(item, previous, value, pressed))
        if osc is not None and self._activation is activation:
            osc.osc_message.emit(item.address, (float(pressed),))

    def _button_event(self, item, previous, value, pressed):
        from gremlin.event_handler import Event
        from gremlin.input_types import InputType
        from gremlin.types import EventSourceType

        return Event(
            event_type=InputType.StarCitizen,
            override_input_type=InputType.JoystickButton,
            device_guid=self.device_guid,
            identifier=item.button,
            is_pressed=pressed,
            value=pressed,
            is_virtual=True,
            source=EventSourceType.Virtual,
            extra_data={"osc_address": item.address, "previous": previous, "state": value},
        )

    def action_names(self):
        with self._lock:
            return sorted(self._actions)

    def trigger(self, action_name, hold_ms=0):
        """Submit an advertised command without waiting on the input thread."""
        with self._lock:
            if (
                self._activation is None
                or self._channel is None
                or action_name not in self._actions
                or (hold_ms and not self._actions[action_name])
                or len(self._commands) >= 16
            ):
                return False
            from . import protocol

            command = self._channel.unary_unary(
                protocol.SERVICE + "TriggerGameAction",
                request_serializer=protocol.ActionRequest.SerializeToString,
                response_deserializer=protocol.ActionResponse.FromString,
            )
            request = protocol.ActionRequest(action_name=action_name)
            if hold_ms:
                request.hold_ms = hold_ms
            result = command.future(request, timeout=1)
            self._commands.add(result)
            result.add_done_callback(self._command_done)
            return True

    def _command_done(self, future):
        import grpc

        with self._lock:
            self._commands.discard(future)
        try:
            result = future.result()
            if result.status != 1:
                syslog.warning("Star Citizen action rejected: %s (%s)", result.message, result.status)
        except grpc.FutureCancelledError:
            pass
        except grpc.RpcError as error:
            syslog.warning("Star Citizen action RPC: %s", error.code().name)


_client_lock = threading.Lock()


def get_client():
    """Return the shared telemetry client.

    Connect to frame_changed to receive each distinct protobuf TelemetryFrame on
    the Qt application thread. Treat the frame as read-only. The first frame of
    each connection is delivered.
    """
    with _client_lock:
        return StarCitizenClient()


def is_button_pressed(button):
    """Read a virtual button without starting the telemetry client."""
    client = StarCitizenClient.instance
    return client is not None and client.is_pressed(button)
