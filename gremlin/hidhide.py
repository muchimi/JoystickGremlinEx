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




"""
new for m77:Read and edit the installed Windows HidHide driver configuration.
This module uses the API exposed by HidHide  through DeviceIoControl calls and
is documented in the documentation provided by the HidHide project.

"""

import ctypes as c
import logging
import re
import sys
from contextlib import contextmanager
from ctypes import wintypes as w
from dataclasses import dataclass, replace
from functools import lru_cache
from threading import RLock

log = logging.getLogger("system")
_lock = RLock()


def _ioctl(function):
    # CTL_CODE(32769, function, METHOD_BUFFERED, FILE_READ_DATA)
    return (0x8001 << 16) | (1 << 14) | (function << 2)


GET_WHITELIST, SET_WHITELIST, GET_BLACKLIST, SET_BLACKLIST, GET_ACTIVE, SET_ACTIVE, GET_INVERSE = map(_ioctl, range(2048, 2055))


@lru_cache(maxsize=1)
def _kernel():
    api = c.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    api.CreateFileW.restype = w.HANDLE
    api.CloseHandle.argtypes = [w.HANDLE]
    api.CloseHandle.restype = w.BOOL
    api.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p]
    api.DeviceIoControl.restype = w.BOOL
    api.GetCurrentProcess.argtypes = []
    api.GetCurrentProcess.restype = w.HANDLE
    api.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
    api.QueryFullProcessImageNameW.restype = w.BOOL
    return api


@contextmanager
def _control_device():
    api = _kernel()
    with _lock:
        # GENERIC_READ, share read/write/delete, OPEN_EXISTING.
        handle = api.CreateFileW(r"\\.\HidHide", 0x80000000, 7, None, 3, 0x80, None)
        if handle == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            yield handle
        finally:
            api.CloseHandle(handle)


def _device_io(handle, code, payload=None, capacity=0):
    inbound = c.create_string_buffer(payload, len(payload)) if payload is not None else None
    outbound = c.create_string_buffer(capacity) if capacity else None
    transferred = w.DWORD()
    ok = _kernel().DeviceIoControl(handle, code, inbound, len(payload or b""), outbound, capacity, c.byref(transferred), None)
    if not ok:
        raise c.WinError(c.get_last_error())
    return (outbound.raw[:transferred.value] if outbound is not None else b""), transferred.value


def _encode_multi_sz(values):
    # HidHide's native client writes one terminating WCHAR for an empty list.
    return ("".join(f"{value}\0" for value in values) + "\0").encode("utf-16-le")


def _multi_sz(handle, code):
    for _ in range(3):
        _, size = _device_io(handle, code)
        if size < 2 or size % 2 or size > 4 * 1024 * 1024:
            raise RuntimeError("HidHide returned an invalid configuration buffer size.")
        try:
            data, _ = _device_io(handle, code, capacity=size)
        except OSError as error:
            if error.winerror not in (122, 234):  # Configuration may have grown between the two calls.
                raise
            continue
        try:
            text = data.decode("utf-16-le")
        except UnicodeDecodeError as error:
            raise RuntimeError("HidHide returned an invalid UTF-16 configuration list.") from error
        if text != "\0" and not text.endswith("\0\0"):
            raise RuntimeError("HidHide returned an unterminated configuration list.")
        return {value.casefold(): value for value in text.split("\0") if value}
    raise RuntimeError("HidHide configuration changed while it was being read.")


def _flag(handle, code):
    data, size = _device_io(handle, code, capacity=1)
    if size != 1:
        raise RuntimeError("HidHide returned an invalid configuration flag.")
    return bool(data[0])


def _process_image():
    api = _kernel()
    path = c.create_unicode_buffer(32768)
    length = w.DWORD(len(path))
    # PROCESS_NAME_NATIVE returns the same NT namespace stored by HidHide.
    if not api.QueryFullProcessImageNameW(api.GetCurrentProcess(), 1, path, c.byref(length)):
        raise c.WinError(c.get_last_error())
    return path.value


def is_installed():
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\HidHide"):
            return True
    except OSError:
        return False


def _interface_key(path):
    path = (path or "").casefold().removeprefix("\\\\?\\").removeprefix("\\??\\")
    return path.split("#{", 1)[0]


@dataclass(frozen=True)
class HidDevice:
    name: str
    paths: tuple[str, ...]
    interface: str = ""
    present: bool = False
    gaming: bool = False
    role: str = ""
    bulk_hide: bool = False
    is_virtual: bool | None = None
    apis: tuple[str, ...] = ()


@dataclass(frozen=True)
class Configuration:
    devices: tuple[HidDevice, ...]
    hidden: dict[str, str]
    active: bool
    gex_allowed: bool
    inverse: bool


def _device_rows(interfaces, hid_metadata, hidden, directinput_paths=()):
    rows = {}
    aliases = {}
    shared_paths = set()
    directinput = {_interface_key(path) for path in directinput_paths}
    for instance, interface, present, name, gaming, xusb, ancestors, xinput in interfaces:
        interface_key = _interface_key(interface)
        metadata = hid_metadata.get(interface_key, {})
        usage = metadata.get("usage_page"), metadata.get("usage")
        gaming = gaming or usage in ((1, 4), (1, 5), (1, 8))
        name = metadata.get("product_string") or name
        key = instance.casefold()
        apis = tuple(api for api, detected in (("DirectInput", interface_key in directinput), ("XInput", xinput))
                     if present and detected)
        rows[key] = HidDevice(name, (instance,), interface, present, gaming, apis=apis)
        if not gaming:
            shared_paths.update(path.casefold() for path in ancestors)
        elif xusb and xusb.casefold() != key:
            aliases[key] = xusb
    for key, alias in aliases.items():
        if alias.casefold() not in shared_paths:
            rows[key] = replace(rows[key], paths=(*rows[key].paths, alias))
    known = {path.casefold() for row in rows.values() for path in row.paths}
    for key, path in hidden.items():
        if key not in known:
            rows[key] = HidDevice(path, (path,))
    return tuple(sorted(rows.values(), key=lambda row: (not row.present, row.name.casefold(), row.paths[0].casefold())))


def _enumerate_devices(hidden):
    from dinput.device_identity import get_directinput_controller_paths, get_hid_interfaces
    from gremlin.hid import enumerate_devices

    try:
        metadata = {}
        for row in enumerate_devices():
            path = row.get("path", "")
            if isinstance(path, bytes):
                path = path.decode("utf-8", errors="replace")
            metadata[_interface_key(path)] = row
    except OSError:
        log.debug("HidHide could not read HID product strings", exc_info=True)
        metadata = {}
    try:
        directinput_paths = get_directinput_controller_paths()
    except OSError:
        log.debug("HidHide could not enumerate DirectInput controllers", exc_info=True)
        directinput_paths = ()
    return _device_rows(get_hid_interfaces(), metadata, hidden, directinput_paths)


class HidHide:
    @staticmethod
    def _gex_allowed(handle, inverse):
        listed = _process_image().casefold() in _multi_sz(handle, GET_WHITELIST)
        return listed != inverse

    def gex_allowed(self):
        """Check whether this executable can see hidden devices without enumerating them."""
        with _control_device() as handle:
            return self._gex_allowed(handle, _flag(handle, GET_INVERSE))

    def read(self):
        with _control_device() as handle:
            hidden = _multi_sz(handle, GET_BLACKLIST)
            active = _flag(handle, GET_ACTIVE)
            inverse = _flag(handle, GET_INVERSE)
            allowed = self._gex_allowed(handle, inverse)
        return Configuration(_enumerate_devices(hidden), hidden, active, allowed, inverse)

    def apply(self, changes, active, previous_active):
        if not changes and active == previous_active:
            return
        with _control_device() as handle:
            if changes:
                current = _multi_sz(handle, GET_BLACKLIST)
                updated = current.copy()
                for path, hide in changes.items():
                    if hide:
                        updated.setdefault(path.casefold(), path)
                    else:
                        updated.pop(path.casefold(), None)
                if updated != current:
                    _device_io(handle, SET_BLACKLIST, _encode_multi_sz(updated.values()))
            if active != previous_active and active != _flag(handle, GET_ACTIVE):
                _device_io(handle, SET_ACTIVE, bytes((active,)))

    def allow_gex(self):
        image = _process_image()
        key = image.casefold()
        with _control_device() as handle:
            inverse = _flag(handle, GET_INVERSE)
            current = _multi_sz(handle, GET_WHITELIST)
            if (key in current) != inverse:
                return
            if inverse:
                current.pop(key)
            else:
                current[key] = image
            _device_io(handle, SET_WHITELIST, _encode_multi_sz(current.values()))


@dataclass(frozen=True)
class VirtualDevice:
    name: str
    provider: str
    hardware_id: tuple[int, int]
    interfaces: frozenset[str]
    output: bool


def _hardware_id(paths):
    for path in paths:
        if match := re.search(r"vid_([a-f\d]{4})&pid_([a-f\d]{4})", path, re.IGNORECASE):
            return tuple(int(value, 16) for value in match.groups())
    return None


def classify_device(row, virtuals, profile_known, ancestors=()):
    if not row.present:
        return replace(row, role="Disconnected")
    if not row.gaming:
        return replace(row, role="Other HID device")
    interface = _interface_key(row.interface)
    exact = [device for device in virtuals if interface and interface in device.interfaces]
    if exact:
        provider = exact[0].provider
        hardware_id = exact[0].hardware_id
        # An unresolved output interface with the same hardware IDs could
        # refer to this collection. Protect it until Windows identifies it.
        output = any(device.output for device in exact) or any(
            device.output and not device.interfaces and device.hardware_id == hardware_id for device in virtuals
        )
        return replace(row, role=f"{provider} output" if output else provider, bulk_hide=profile_known and not output, is_virtual=True)

    hardware_id = _hardware_id((row.interface, *row.paths))
    candidates = [device for device in virtuals if hardware_id and device.hardware_id == hardware_id]
    signature = " ".join((row.name, *row.paths, *ancestors)).casefold()
    provider = ""
    if "vjoy" in signature or hardware_id == (0x1234, 0xBEAD):
        provider = "vJoy"
    elif ("maestro" in signature or "gex custom device" in signature or re.fullmatch(r"gex-(?:gp-)?[1-9]\d*", row.name.casefold()) or
          (hardware_id and (hardware_id[0] == 1 and 0x4701 <= hardware_id[1] <= 0x4804 or
                            hardware_id[0] == 0x1209 and 0x1000 <= hardware_id[1] <= 0x100F))):
        provider = "Maestro"
    if provider:
        if provider == "Maestro" and not candidates:
            candidates = [device for device in virtuals if device.provider == provider and device.name.casefold() == row.name.casefold()]
        if not candidates:
            unused = profile_known and not any(device.provider == provider and device.output for device in virtuals)
            return replace(row, role=provider if unused else f"{provider} (unmatched)", bulk_hide=unused, is_virtual=True)
        if any(device.output for device in candidates):
            return replace(row, role=f"{provider} (possible output)", is_virtual=True)
        return replace(row, role=provider, bulk_hide=profile_known, is_virtual=True)
    if any(marker in signature for marker in ("vigem", "vhf", "virtual", "vgamepad")):
        return replace(row, role="Virtual or shared hardware ID", is_virtual=True)
    if candidates:
        return replace(row, role="Virtual or shared hardware ID")
    return replace(row, role="Physical controller", bulk_hide=True, is_virtual=False)


def read_devices(client, profile, master_mode):
    """Resolve the HidHide inventory against current GEX output mappings."""
    from dinput.device_identity import get_device_ancestors, get_device_identities
    from gremlin import joystick_handling
    from gremlin.device_remap import guid_key
    from gremlin.profile_statistics import collect_profile_statistics

    configuration = client.read()
    devices = [device for device in joystick_handling.get_native_vjoy_devices(False) + joystick_handling.maestro_devices(False)
               if not device.data.get("failover")]
    output_keys = set()
    profile_known = profile is not None
    if profile is not None:
        try:
            stats = collect_profile_statistics(profile, master_mode)
            output_keys = {key for kind, key in stats.outputs if kind == "Virtual"}
        except Exception:
            log.exception("HidHide could not identify the profile's virtual outputs")
            profile_known = False
    output_guids = {guid_key(key) for key in output_keys} - {None}
    output_ids = {int(key) for key in output_keys if str(key).isdecimal()}
    try:
        identities = get_device_identities({device.device_guid for device in devices if device.connected})
    except OSError:
        identities = {}
    virtuals = []
    resolved_guids = set()
    resolved_ids = set()
    for device in devices:
        guid = guid_key(device.device_guid)
        provider = device.device_type.name
        paths = {device.data.get("maestro_hid_path"), identities.get(guid, {}).get("path")}
        aliases = {guid_key(alias) for alias in device.data.get("maestro_native_guids", ())}
        resolved_guids.update(aliases | {guid})
        if provider == "VJoy":
            resolved_ids.add(device.vjoy_id)
        output = (guid in output_guids or bool(aliases & output_guids) or
                  (provider == "VJoy" and device.vjoy_id in output_ids))
        virtuals.append(VirtualDevice(device.name or "", "vJoy" if provider == "VJoy" else provider,
                                      (device.vendor_id, device.product_id),
                                      frozenset(_interface_key(path) for path in paths if path), output))
    profile_known = profile_known and output_guids <= resolved_guids and output_ids <= resolved_ids
    # Multiple rows can share an XInput path. Treat any protected interface as
    # protecting the whole controller for the bulk operation.
    rows = tuple(classify_device(row, virtuals, profile_known,
                                 get_device_ancestors(row.paths[0]) if row.present and row.gaming else ())
                 for row in configuration.devices)
    protected = {path.casefold() for row in rows if not row.bulk_hide for path in row.paths}
    return replace(configuration, devices=tuple(
        replace(row, bulk_hide=False) if any(path.casefold() in protected for path in row.paths) else row for row in rows
    ))
