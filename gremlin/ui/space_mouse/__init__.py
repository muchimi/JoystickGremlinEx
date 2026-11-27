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


"""Optional PySpaceMouse input provider for GEX - integrates 3Dconnexion SpaceMouse devices with GEX"""

import logging
import uuid

from PySide6 import QtCore

import dinput
from gremlin import joystick_handling, raw_input, shared_state
from gremlin.config import Configuration
from gremlin.event_handler import EventListener

sylog = logging.getLogger("system")
AXIS_FIELDS = ("x", "y", "z", "roll", "pitch", "yaw")
SCAN_INTERVAL_MS = 1000
READ_INTERVAL_MS = 4
MAX_REPORTS_PER_TICK = 64
USAGE_PAGE = 0x01
MULTI_AXIS_USAGE = 0x08


def _enumerate_space_mice(enumeration, supported_products):
    present = raw_input.attached_hid_products(USAGE_PAGE, MULTI_AXIS_USAGE)
    # HIDAPI opens interfaces to gather metadata. Query only models Windows sees.
    return [
        device
        for vendor, product in sorted(present.intersection(supported_products))
        for device in enumeration(vendor, product).find(usage_page=USAGE_PAGE, usage=MULTI_AXIS_USAGE)
    ]


class SpaceMouse:
    """A connected PySpaceMouse handle with a GEX joystick summary."""

    def __init__(self, mouse, hid_device, identity):
        self.mouse = mouse
        self.axes = (0,) * len(AXIS_FIELDS)
        self.buttons = (False,) * len(mouse.info.button_specs)

        spec = mouse.info
        summary = dinput.DeviceSummary()
        summary.device_guid = dinput.GUID(uuid.uuid5(uuid.NAMESPACE_URL, f"gex:space-mouse:{identity}"))
        product_name = mouse.product_name or spec.name
        summary.name = product_name if "space" in product_name.casefold() else f"SpaceMouse ({product_name})"
        summary.vendor_id = hid_device.vendor_id
        summary.product_id = hid_device.product_id
        summary.usage_page = hid_device.usage_page
        summary.usage = hid_device.usage
        summary.set_space_mouse_layout(len(self.buttons))
        summary.data["button_names"] = dict(enumerate(spec.button_names, 1))
        summary.input_enabled = True
        summary.setConnected(True)
        summary.setAxisCallback(self.get_axis)
        summary.setButtonCallback(self.get_button)
        self.summary = summary

    def get_axis(self, index):
        return self.axes[index - 1] if 0 < index <= len(self.axes) else 0

    def get_button(self, index):
        return self.buttons[index - 1] if 0 < index <= len(self.buttons) else False

    def _update_inputs(self, axes, buttons, emit, *, final=False):
        old_axes, old_buttons = self.axes, self.buttons
        self.axes, self.buttons = axes, buttons
        for input_type, old, current in (
            (dinput.InputType.Axis, old_axes, axes),
            (dinput.InputType.Button, old_buttons, buttons),
        ):
            for index, (old_value, value) in enumerate(zip(old, current), 1):
                if old_value != value:
                    event = dinput.InputEvent.from_values(self.summary.device_guid, input_type, index, int(value))
                    emit(event, final=final)

    def read(self, emit, *, verbose=False):
        """Drain queued reports, preserving button edges between polling ticks."""
        timestamp = self.mouse.state.t
        for _ in range(MAX_REPORTS_PER_TICK):
            state = self.mouse.read()
            if state.t == timestamp:
                break
            timestamp = state.t
            axes = tuple(getattr(state, axis) for axis in AXIS_FIELDS)
            buttons = tuple(map(bool, state.buttons))
            if verbose:
                sylog.info(
                    "SpaceMouse: %s report t=%.6f axes (x, y, z, roll, pitch, yaw)=%s buttons=%s",
                    self.summary.name,
                    timestamp,
                    axes,
                    buttons,
                )
            raw_axes = tuple(round(max(-1.0, min(1.0, value)) * 32767) for value in axes)
            self._update_inputs(raw_axes, buttons, emit)

    def disconnect(self, emit):
        try:
            self._update_inputs((0,) * len(self.axes), (False,) * len(self.buttons), emit, final=True)
        finally:
            # An offline profile summary can outlive its HID connection.
            self.summary.setAxisCallback(None)
            self.summary.setButtonCallback(None)
            self.summary.setConnected(False)
            self.close()

    def close(self):
        try:
            self.mouse.close()
        except Exception:  # noqa: BLE001
            sylog.debug("SpaceMouse: could not close HID handle", exc_info=True)


class SpaceMouseManager(QtCore.QObject):
    """Discover supported HID interfaces and feed their reports to GEX."""

    def __init__(self, api, enumerate_hid, hid_error, parent=None):
        super().__init__(parent)
        self.api = api
        self.enumerate_hid = enumerate_hid
        self.hid_error = hid_error
        self.config = Configuration()
        self.devices = {}
        self.identities = {}
        self.specs = {
            (spec.vendor_id, spec.product_id): api.apply_axis_convention(spec, api.AxisConvention.HID_Z_UP) for spec in api.get_device_specs().values()
        }
        self.listener = EventListener()
        self.listener.shutdown.connect(self.stop)
        self.scan_timer = QtCore.QTimer(self)
        self.scan_timer.timeout.connect(self.scan)
        self.read_timer = QtCore.QTimer(self)
        self.read_timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.read_timer.timeout.connect(self.poll)
        self.scan(startup=True)
        self.scan_timer.start(SCAN_INTERVAL_MS)

    def _identity(self, device):
        # Use the hardware serial when available. The Windows HID path identifies
        # the instance on this machine when the device has no unique serial.
        path = device.path.casefold()
        prefix = f"{device.vendor_id:04x}:{device.product_id:04x}:"
        path_identity = f"{prefix}path:{path}"
        serial = (device.serial_number or "").strip()
        identity = self.identities.get(path, f"{prefix}serial:{serial}" if serial else path_identity)
        if any(identity == self.identities[active_path] for active_path in self.devices):
            identity = path_identity
        self.identities[path] = identity
        return identity

    def _publish(self):
        summaries = [device.summary for device in self.devices.values()]
        joystick_handling.set_space_mouse_devices(summaries)
        profile = shared_state.current_profile
        if profile is not None:
            for summary in summaries:
                node = profile.devices.get(summary.device_guid)
                if node is not None:
                    node.device = summary
        self.listener.refresh_devices.emit()
        if summaries and not self.read_timer.isActive():
            self.read_timer.start(READ_INTERVAL_MS)
        elif not summaries:
            self.read_timer.stop()

    def _disconnect(self, path):
        device = self.devices.pop(path)
        device.disconnect(self.listener.process_joystick_input)
        if self.config.verbose_mode_space_mouse:
            sylog.info(f"SpaceMouse: disconnected {device.summary.name} [{device.summary.device_guid}]")

    def scan(self, *, startup=False):
        try:
            interfaces = self.enumerate_hid(self.specs)
        except Exception:  # noqa: BLE001
            if startup:
                sylog.warning("SpaceMouse: startup detection failed")
            sylog.debug("SpaceMouse: HID discovery failed", exc_info=True)
            return

        paths = {device.path.casefold(): device for device in interfaces if (device.vendor_id, device.product_id) in self.specs}
        removed = self.devices.keys() - paths.keys()
        for path in removed:
            self._disconnect(path)
        changed = bool(removed)
        for path in sorted(paths.keys() - self.devices.keys()):
            hid_device = paths[path]
            spec = self.specs[hid_device.vendor_id, hid_device.product_id]
            # Windows HID device paths cannot be opened as filesystem paths.
            mouse = self.api.SpaceMouseDevice(info=spec, device=hid_device)
            try:
                mouse.open()
                hid_device.set_nonblocking(True)
                self.devices[path] = SpaceMouse(mouse, hid_device, self._identity(hid_device))
            except Exception:  # noqa: BLE001
                sylog.debug(f"SpaceMouse: could not open {spec.name}", exc_info=True)
                try:
                    mouse.close()
                except OSError, self.hid_error:
                    sylog.debug("SpaceMouse: could not close HID handle", exc_info=True)
                continue
            changed = True
            if self.config.verbose_mode_space_mouse:
                summary = self.devices[path].summary
                sylog.info(
                    f"SpaceMouse: connected {summary.name} [{summary.device_guid}] (VID={summary.vendor_id:04X} PID={summary.product_id:04X}, {summary.axis_count} axes, {summary.button_count} buttons)",
                )
        if changed:
            self._publish()
        if startup:
            if self.devices:
                names = ", ".join(device.summary.name for device in self.devices.values())
                sylog.info(f"SpaceMouse: connected at startup: {names}")
            elif paths:
                sylog.warning("SpaceMouse: detected at startup, but no device could be opened")
            else:
                sylog.info("SpaceMouse: no supported device connected at startup")

    def poll(self):
        failed = []
        verbose = self.config.verbose_mode_space_mouse
        for path, device in self.devices.items():
            try:
                device.read(self.listener.process_joystick_input, verbose=verbose)
            except (OSError, self.hid_error) as exc:
                if verbose:
                    sylog.info(f"SpaceMouse: read failed for {device.summary.name}: {exc}")
                failed.append(path)
        for path in failed:
            self._disconnect(path)
        if failed:
            self._publish()

    def stop(self):
        self.scan_timer.stop()
        self.read_timer.stop()
        for device in self.devices.values():
            device.close()
        self.devices.clear()


def start_space_mouse():
    """Start detection when the optional dependency is available."""
    if not Configuration().startup_space_mouse_enabled:
        return None
    try:
        import pyspacemouse
        from easyhid import Enumeration, HIDException
    except (ImportError, OSError) as exc:
        sylog.info(f"SpaceMouse: startup detection unavailable: {exc}")
        return None

    try:
        return SpaceMouseManager(
            pyspacemouse, lambda products: _enumerate_space_mice(Enumeration, products),
            HIDException, QtCore.QCoreApplication.instance(),
        )
    except Exception:  # noqa: BLE001
        sylog.exception("SpaceMouse: unable to initialize optional input support")
        return None
