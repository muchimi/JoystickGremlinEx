# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import copy
import logging
import re
import threading
import time
import traceback

from PySide6 import QtCore, QtWidgets

import dinput
import gremlin.config
import gremlin.shared_state
import gremlin.singleton_decorator
import gremlin.util
from dinput import GUID, DeviceSummary
from gremlin.input_types import InputType
from gremlin.types import DeviceCategory, DeviceType
from gremlin.virtual_output_startup import vjoy_installed
from vjoy import vjoy

from . import error, util

# initialized flag
_joystick_initialized = False

# signature of the DINPUT device list used by the last completed initialization
_last_device_signature = None

# invalid device GUID - used when a GUID is needed but could not be derived
_invalid_device_guid = "f765ae4c4dac40cbabefe9f6187d4689"
_invalid_device: DeviceSummary = None

syslog = logging.getLogger("system")

# List of all joystick devices
_joystick_devices = []  # enabled detected joystick devices only (including virtual devices that exist all the time like OSC or Modes)
_all_joystick_devices = []  # [DeviceSummary] of all devices, virtual, connected or disconnected (from a profile)
_vjoy_devices_map = {}  #  connected vjoy devices (int) -> device
_raw_vjoy_target_map = {}  # raw vjoy devices (int) -> device (detected vjoy devices)
_vjoy_devices = []  # list of connected vjoy devices
_native_vjoy_devices = {}  # list of native vjoy device (int) -> device - this will always be 16 devices, not all of them connected
_maestro_devices_map = {}  # connected maestro devices (int) -> device
_maestro_failover_map = {}  # vJoy IDs and provider GUIDs -> resolved OutputTarget
_maestro_devices = []  # list of connected maestro devices
_all_vjoy_devices_map = {}  # all vjoy devices (int) -> device
_maestro_devices_map = {}  # all maestro devices (int) -> device
_all_virtual_devices_map = {
    DeviceType.VJoy: {},
    DeviceType.Maestro: {},
}  # all virtual input devices (vjoy and maestro) [device_type:DeviceType][index:int] -> device : DeviceSummary

_joystick_device_guid_map = {}  # map of DeviceSummary objects keyed by dInput GUID (special devices)
_disconnected_devices_map = {}  # map of disconnected devices dinput.GUID -> device
_disconnected_devices = []  # list of disconnected devices
_special_devices_map = {}  # map of special devices dinput.GUID -> device
_special_devices = []  # list of special devices
_config_devices_map = {}  # map of DeviceSummary objects keyed by dInput GUID (config devices)
_config_devices = []  # list of config devices (setings, plugins)
_all_devices_map = gremlin.util.TriggerDict()  # all detected or loaded devices [dinput.GUID] -> device
_device_registry_lock = threading.RLock()
_maestro_service_devices = {}  # selected OSC service devices, keyed by stable GUID
_maestro_replaced_devices = {}  # native registry entries covered by service metadata
_maestro_excluded_native_guids = set()  # obsolete legacy devices absent from the bridge inventory


def _is_cached_maestro_device(device):
    """Recognize older GEX cache entries as well as current service summaries."""
    data = getattr(device, "data", {})
    if device.device_type == DeviceType.Maestro or data.get("maestro_key") or data.get("maestro_native_input"):
        return True
    if device.device_type == DeviceType.VJoy:
        return False
    name = (device.name or "").casefold()
    if name.startswith("gex-gp-") and name[7:].isdecimal():
        return True
    if (getattr(device, "vendor_id", -1), getattr(device, "product_id", -1)) not in (
        (0x0001, 0x0001),
        (0xFEED, 0x8010),
    ):
        return False
    name = device.name or ""
    prefix = dinput.GEX_PRODUCT_STRING
    legacy_name = name == prefix or (name.startswith(prefix + " ") and name[len(prefix) :].strip().isdecimal())
    legacy_id = name.casefold().startswith("gex-") and name.casefold()[4:].removeprefix("gp-").isdecimal()
    return legacy_name or legacy_id


def _maestro_output_summary(device):
    """Use bridge output capabilities without changing the native input layout."""
    return getattr(device, "data", {}).get("maestro_output_summary", device)


def set_maestro_devices(devices, *, known_devices=None):
    """Replace the Maestro service list and rebuild all virtual device maps."""
    global _maestro_service_devices, _maestro_excluded_native_guids, _maestro_failover_map
    native_devices = None
    if getattr(dinput.DILL, "initialized", True):
        native_devices = {device.device_guid: device for device in dinput.DILL.getDevices()}
    devices = {device.device_guid: device for device in devices}
    with _device_registry_lock:
        registry = dict(_all_devices_map)
        selected_keys = {device.data["maestro_key"] for device in devices.values() if device.data.get("maestro_key")}
        alias_owners = {}
        for guid, device in devices.items():
            for alias in device.data.get("maestro_native_guids", ()):
                alias_owners.setdefault(alias, set()).add(guid)
        aliases = {alias for alias, owners in alias_owners.items() if len(owners) == 1 and alias not in devices}
        # Old 0001:0001 GEX controllers can remain attached after migration to
        # the bridge's current devices. A native descriptor is not proof that
        # they still belong to an active service definition.
        # Keep deletion tombstones until the same identity is explicitly
        # attached again. A native discovery snapshot may predate this update.
        _maestro_excluded_native_guids = set(_maestro_excluded_native_guids)
        _maestro_excluded_native_guids.difference_update(devices, aliases)
        if known_devices is not None:
            candidates = dict(registry)
            candidates.update(native_devices or {})
            for guid, native in candidates.items():
                if guid in devices or guid in aliases:
                    continue
                if (native.vendor_id, native.product_id) != (0x0001, 0x0001):
                    continue
                name = native.name or ""
                prefix = dinput.GEX_PRODUCT_STRING
                if name != prefix and not (name.startswith(prefix + " ") and name[len(prefix) :].strip().isdecimal()):
                    continue
                key = native.data.get("maestro_key") or getattr(registry.get(guid), "data", {}).get(
                    "maestro_key"
                )
                if key in known_devices and known_devices[key].get("active") is not False:
                    _maestro_excluded_native_guids.discard(guid)
                    continue
                _maestro_excluded_native_guids.add(guid)
        # An overlay may outlive the native controller it originally replaced.
        # Only restore native devices that are still present in DirectInput.
        deleted_guids = set()
        for guid, previous in _maestro_service_devices.items():
            original = _maestro_replaced_devices.pop(guid, None)
            previous_key = previous.data.get("maestro_key")
            deleted = known_devices is not None and (
                previous_key not in known_devices or known_devices[previous_key].get("active") is False
            )
            if deleted:
                deleted_guids.add(guid)
                deleted_guids.update(previous.data.get("maestro_native_guids", ()))
            if registry.get(guid) is previous:
                native = (native_devices or {}).get(guid) if original is not None and not deleted else None
                if native is None:
                    registry.pop(guid, None)
                    _joystick_device_guid_map.pop(guid, None)
                else:
                    # It remains a Maestro input, but is no longer an output slot.
                    native.data["maestro_native_input"] = True
                    native.device_type = DeviceType.Maestro
                    native.setVirtual(True)
                    native.virtual_id = -1
                    native.vjoy_id = -1
                    registry[guid] = native
                    _joystick_device_guid_map[guid] = native
            if original is not None and guid in devices:
                _maestro_replaced_devices[guid] = original
        # Older native/profile caches may never have been registered as service
        # overlays. Reconcile those too, including entries still marked connected.
        for guid, cached in list(registry.items()):
            if guid in aliases:
                registry.pop(guid, None)
                _joystick_device_guid_map.pop(guid, None)
                _maestro_replaced_devices.pop(guid, None)
                continue
            if guid in devices or (guid not in deleted_guids and not _is_cached_maestro_device(cached)):
                continue
            key = cached.data.get("maestro_key")
            deleted = (
                guid in deleted_guids
                or key in selected_keys
                or (
                    key
                    and known_devices is not None
                    and (key not in known_devices or (cached.connected and known_devices[key].get("active") is False))
                )
            )
            native = (native_devices or {}).get(guid)
            if native is not None and not deleted:
                # A physical pad may share a generated display name. Standard
                # gamepad VID/PIDs and names alone do not establish ownership.
                owned = (
                    cached.device_type == DeviceType.Maestro
                    or cached.data.get("maestro_key")
                    or cached.data.get("maestro_native_input")
                )
                legacy = (cached.vendor_id, cached.product_id) in ((0x0001, 0x0001), (0xFEED, 0x8010))
                if owned or legacy:
                    native.data["maestro_native_input"] = True
                    native.device_type = DeviceType.Maestro
                    native.setVirtual(True)
                    native.virtual_id = -1
                    native.vjoy_id = -1
                registry[guid] = native
                _joystick_device_guid_map[guid] = native
            elif not deleted and not cached.connected and key and known_devices is not None and key in known_devices:
                # A saved inactive definition is real metadata, not a live target.
                cached.name = known_devices[key].get("name", cached.name)
                cached.setConnected(False)
                cached.virtual_id = -1
                cached.vjoy_id = -1
            elif native_devices is not None or deleted:
                registry.pop(guid, None)
                _joystick_device_guid_map.pop(guid, None)
                _maestro_replaced_devices.pop(guid, None)
        for vid, cached in list(_all_vjoy_devices_map.items()):
            if (
                _is_cached_maestro_device(cached)
                or cached.device_guid in aliases
                or cached.device_guid in deleted_guids
            ):
                _all_vjoy_devices_map.pop(vid, None)
        _maestro_excluded_native_guids.update(deleted_guids)
        _maestro_service_devices = devices
        _replace_device_registry(registry)
        _update_joystick_device_maps()
        published = dict(_maestro_service_devices)
    _log_output_map()
    return published


def _apply_maestro_service_devices():
    """Reapply service metadata after native hot-plug enumeration."""
    devices = dict(_all_devices_map)
    service_keys = {device.data["maestro_key"] for device in _maestro_service_devices.values()
                    if device.data.get("maestro_key")}
    aliases = {guid for device in _maestro_service_devices.values()
               for guid in device.data.get("maestro_native_guids", ())}
    for device in _maestro_service_devices.values():
        output = device.data.get("maestro_output_summary")
        if output is not None:
            aliases.add(output.device_guid)
    # Native enumeration can reintroduce interfaces removed by the last bridge
    # snapshot. Keep one canonical input row per service when rebuilding maps.
    for guid, device in tuple(devices.items()):
        if guid in _maestro_service_devices:
            continue
        if guid in aliases or device.data.get("maestro_key") in service_keys:
            devices.pop(guid, None)
            _joystick_device_guid_map.pop(guid, None)
            _maestro_replaced_devices.pop(guid, None)
    for guid in _maestro_excluded_native_guids:
        devices.pop(guid, None)
        _joystick_device_guid_map.pop(guid, None)
        _maestro_replaced_devices.pop(guid, None)
    for guid, device in _maestro_service_devices.items():
        device.set_vjoy_id(_maestro_failover_id(device) or -1)
        native = devices.get(guid)
        if native is not None and native is not device:
            _maestro_replaced_devices[guid] = native
        devices[guid] = device
        _joystick_device_guid_map[guid] = device
    # Updated GEX VID/PIDs are unique per device, unlike legacy shared PIDs or
    # ordinary physical controllers. Discard extra GUID rows in every registry
    # consumer, rather than hiding duplicates only in the input viewer.
    products = {}
    candidates = sorted(devices.items(), key=lambda item: (
        bool(getattr(item[1], "input_enabled", False)),
        bool(getattr(item[1], "connected", False)),
        item[0] in _maestro_service_devices,
    ), reverse=True)
    for guid, device in candidates:
        vendor = getattr(device, "vendor_id", 0)
        product = getattr(device, "product_id", 0)
        if vendor != 1 or not (0x4701 <= product <= 0x4804 or 0x4901 <= product <= 0x49FF):
            continue
        key = (vendor, product)
        if key not in products:
            products[key] = device
            continue
        canonical = products[key]
        if device.data.get("maestro_key") and (
                not canonical.data.get("maestro_key") or (canonical.virtual_id < 0 <= device.virtual_id)):
            # Keep the DirectInput GUID and input layout, while attaching the
            # bridge's output metadata to that native identity.
            canonical.data.update(device.data)
            canonical.name = device.name
            canonical.device_type = DeviceType.Maestro
            canonical.setVirtual(True)
            canonical.virtual_id = device.virtual_id
            canonical.vjoy_id = device.vjoy_id
            if (canonical.axis_count, canonical.button_count, canonical.hat_count) != (
                    device.axis_count, device.button_count, device.hat_count):
                output = copy.copy(device)
                output.data = dict(device.data)
                output.device_guid = canonical.device_guid
                canonical.data["maestro_output_summary"] = output
            _maestro_service_devices[canonical.device_guid] = canonical
        output = canonical.data.get("maestro_output_summary")
        if output is not None and output.device_guid != canonical.device_guid:
            output = copy.copy(output)
            output.data = dict(output.data)
            output.device_guid = canonical.device_guid
            canonical.data["maestro_output_summary"] = output
        aliases = set(canonical.data.get("maestro_native_guids", ()))
        if getattr(device, "input_enabled", False):
            aliases.add(device.device_guid)
        aliases.update(device.data.get("maestro_native_guids", ()))
        aliases.discard(canonical.device_guid)
        canonical.data["maestro_native_guids"] = tuple(aliases)
        devices.pop(guid, None)
        _maestro_service_devices.pop(guid, None)
        _joystick_device_guid_map.pop(guid, None)
        _maestro_replaced_devices.pop(guid, None)
    _replace_device_registry(devices)


def _replace_device_registry(devices):
    """Swap registry storage under its lock, without invoking per-item callbacks.

    Device initialization/change signals notify consumers after publication.
    Readers retaining an older TriggerDict or its views keep that generation.
    """
    global _all_devices_map
    if isinstance(_all_devices_map, dict):
        _all_devices_map = devices
    else:
        registry = copy.copy(_all_devices_map)
        registry.data = devices
        _all_devices_map = registry


def display_devices(profile=None, *, refresh=False):
    """Return live devices plus disconnected devices referenced by this profile."""
    from copy import copy

    if refresh:
        refresh_device_inventory()
    if profile is None:
        profile = gremlin.shared_state.current_profile

    def identity(guid):
        return str(guid).strip("{}").replace("-", "").casefold()

    referenced = {}
    if profile is not None:
        for bucket in (profile.devices, profile.vjoy_devices):
            for guid, node in bucket.items():
                referenced[identity(guid)] = node.device
    # A cached connected flag is not evidence that a joystick still exists.
    native_devices = dinput.DILL.getDevices() if getattr(dinput.DILL, "initialized", False) else []
    with _device_registry_lock:
        services = {identity(guid): device for guid, device in _maestro_service_devices.items() if device.connected}
        excluded = {identity(guid) for guid in _maestro_excluded_native_guids}
        aliases = set()
        service_keys = set()
        for key, device in services.items():
            aliases.update(identity(guid) for guid in device.data.get("maestro_native_guids", ()))
            output = device.data.get("maestro_output_summary")
            if output is not None:
                aliases.add(identity(output.device_guid))
            if device.data.get("maestro_key"):
                service_keys.add(device.data["maestro_key"])
        aliases.difference_update(services)

        result = {}
        # Keep application tabs for the Order Devices dialog, which shares this
        # query. Device Information filters these out by device type.
        joystick_types = (DeviceType.Joystick, DeviceType.VJoy, DeviceType.Maestro)
        for device in _all_devices_map.values():
            if device.device_type not in joystick_types:
                result[identity(device.device_guid)] = device
        rejected = set()
        for device in native_devices:
            key = identity(device.device_guid)
            if key in excluded or key in aliases or device.device_type not in joystick_types:
                continue
            registered = _all_devices_map.get(device.device_guid)
            if (not isDeviceValid(device) or _is_excluded_native_joystick(device)
                    or device.disabled or (registered is not None and registered.disabled)):
                # Raw snapshots have not passed registry validation. Remember
                # rejected identities so profile references cannot restore them.
                rejected.add(key)
                continue
            if not device.connected:
                device = copy(device)
                device.setConnected(True)
            result[key] = device
        result.update(services)

        for key, device in referenced.items():
            if device is None or key in result or key in aliases or key in rejected:
                continue
            if device.disabled or _is_excluded_native_joystick(device):
                continue
            if device.data.get("maestro_key") in service_keys:
                continue
            missing = copy(device)
            missing.setConnected(False)
            result[key] = missing
        return list(result.values())


def getAllDevicesMap():
    """gets a map of all devices"""
    global _all_devices_map
    return _all_devices_map


def getAllDevices() -> list:
    """gets a list of all devices"""
    global _all_devices_map
    # with _device_registry_lock:
    return list(_all_devices_map.values())


def dumpDevices():
    """dumps the list of all devices to the log"""
    global _all_devices_map
    with _device_registry_lock:
        device_list = list(_all_devices_map.values())
    device_list.sort(key=lambda d: d.name.casefold())
    syslog.info(f"All devices: {len(device_list)}")
    for device in device_list:
        syslog.info(
            f"\t{device.device_id}: {device.name} type: {device.device_type.name} category: {device.device_category.name} connected: {device.connected} enabled: {device.enabled} virtual: {device.is_virtual} guid: {device.device_guid}"
        )


def _handle_change(data, key, old_value, value):
    assert isinstance(key, dinput.GUID)


_all_devices_map.addCallback(_handle_change)


# Joystick initialization lock
_joystick_init_lock = threading.Lock()

# joystick linear axis names


class AxisNames:
    joystick_linear_axis_names = ["X", "Y", "Z", "S1", "S2", "RX", "RY", "RZ"]


class VJoyProxy:
    """Manages the usage of vJoy and allows shared access all callbacks."""

    vjoy_devices = {}
    # _vjoy_proxy_lock = threading.RLock()

    def __getitem__(self, vid):
        """Returns the requested vJoy instance.

        :param key id of the vjoy device
        :return the corresponding vjoy device
        """
        # Legacy scripts keep numeric vJoy IDs; GUIDs can target either backend.
        vid = parse_virtual_device_key(vid)
        if not isinstance(vid, int):
            device = get_output_device(vid)
            if device is None:
                raise error.GremlinError(f"Virtual output device is unavailable: {vid}")
            return device
        # device IDs are 1 min to 16 max
        assert vid > 0 and vid < 17, f"Invalid VJOY device ID provided: {vid}"
        # don't lock on read, only lock on write
        # with VJoyProxy._vjoy_proxy_lock:
        if vid in VJoyProxy.vjoy_devices:
            return VJoyProxy.vjoy_devices[vid]
        else:
            if not isinstance(vid, int):
                raise error.GremlinError(f"Integer ID for vjoy device ID expected: got {vid}")

            try:
                # ok for output
                device = vjoy.VJoy(vid)
                VJoyProxy.vjoy_devices[vid] = device
                return device
            except error.VJoyError as err:
                msg = f"Failed accessing vJoy id={vid}\n{err}"
                syslog.error(msg)
                raise err

    @classmethod
    def reset(self):
        """Relinquishes control over all held VJoy devices."""
        # with VJoyProxy._vjoy_proxy_lock:
        devices = list(VJoyProxy.vjoy_devices.values())
        for device in devices:
            device.invalidate()
        VJoyProxy.vjoy_devices = {}


def joystick_devices() -> list[DeviceSummary]:
    """Returns the list of CONNECTED physical joysticks"""
    # with _device_registry_lock:
    return list(_joystick_devices)


def all_joystick_devices(include_disabled=True, *, refresh=False):
    """Return registered joysticks, optionally refreshing native and bridge data."""
    global _all_joystick_devices, _joystick_devices
    if refresh:
        refresh_device_inventory()
    with _device_registry_lock:
        if include_disabled:
            return list(_all_joystick_devices)
        return list(_joystick_devices)


def all_vjoy_devices() -> list[DeviceSummary]:
    """Get connected vJoy outputs, including resolved failover devices."""
    return vjoy_devices()


def all_maestro_devices() -> list[DeviceSummary]:
    """gets connected Maestro devices"""
    global _maestro_devices
    # with _device_registry_lock:
    return list(_maestro_devices)


def vjoy_id_list(connected=True) -> list[int]:
    """Get vJoy request IDs, retaining those IDs when output uses Maestro."""
    available = vjoy_device_map(connected_only=True)
    if connected:
        return list(available)
    return [vid for vid in vjoy_device_map() if vid not in available]


def vjoy_output_devices() -> list[DeviceSummary]:
    """gets the list of output vjoy devices"""
    import gremlin.shared_state

    profile = gremlin.shared_state.current_profile
    if profile is None or getattr(profile, "settings", None) is None:
        return []
    settings = profile.settings
    devices = [dev for vid, dev in vjoy_device_map(connected_only=True).items() if not settings.getVirtualAsInput(vid)]
    return devices


def virtual_input_candidates() -> list[DeviceSummary]:
    """Connected virtual joysticks that can generate local DirectInput events."""
    return [
        dev
        for dev in all_joystick_devices()
        if dev.device_type in (DeviceType.VJoy, DeviceType.Maestro)
        and (dev.device_type != DeviceType.VJoy or dev.vjoy_id > 0)
        and dev.connected
        and not dev.disabled
        and dev.input_enabled
        and not dev.data.get("failover", False)
    ]


def virtual_input_devices() -> list[DeviceSummary]:
    """Virtual joysticks selected as inputs in the current profile."""
    profile = gremlin.shared_state.current_profile
    if profile is None or getattr(profile, "settings", None) is None:
        return []
    return [dev for dev in virtual_input_candidates() if profile.settings.getVirtualAsInput(dev)]


def axis_input_devices() -> list[DeviceSummary]:
    """returns the list of devices that has axes"""
    global _all_joystick_devices
    devices = [dev for dev in _all_joystick_devices if dev.axis_count and dev.enabled and not dev.is_virtual]
    devices.extend(dev for dev in virtual_input_devices() if dev.axis_count)
    return devices


def button_input_devices() -> list[DeviceSummary]:
    """returns the list of devices that have buttons"""
    global _all_joystick_devices
    devices = [dev for dev in _all_joystick_devices if dev.button_count and dev.enabled and not dev.is_virtual]
    devices.extend(dev for dev in virtual_input_devices() if dev.button_count)
    return devices


def hat_input_devices() -> list[DeviceSummary]:
    """returns the list of devices that define hats"""
    global _all_joystick_devices
    devices = [dev for dev in _all_joystick_devices if dev.hat_count and dev.enabled and not dev.is_virtual]
    devices.extend(dev for dev in virtual_input_devices() if dev.hat_count)
    return devices


def filtered_input_devices(
    input_type_list=[InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat], virtual_only=False
):
    """gets a list of devices filtered by axis, button or hat"""
    providers = {
        InputType.JoystickAxis: axis_input_devices,
        InputType.JoystickButton: button_input_devices,
        InputType.JoystickHat: hat_input_devices,
    }
    devices = {}
    for input_type in input_type_list:
        provider = providers.get(input_type)
        if provider is None:
            continue
        for dev in provider():
            if not virtual_only or dev.is_virtual:
                devices[dev.device_guid] = dev
    return list(devices.values())


def is_hardware_device(device_guid) -> bool:
    """true if the device is a hardware device"""
    info = getDevice(device_guid)
    if info:
        return not info.is_special
    # not found - could be a device that is disconnected
    if device_guid:
        id = gremlin.util.parse_guid(device_guid)
        if id:
            # assume disconnected
            return True
    return False


def is_vjoy_device(device_guid) -> bool:
    """true if the device is a vjoy device"""
    info = getDevice(device_guid)
    if info:
        return info.is_virtual
    return False


def is_vjoy_connected(vjoy_id: int) -> bool:
    """True when the requested output has a connected native or failover target."""
    vjoy_id = parse_virtual_device_key(vjoy_id)
    return get_output_target(vjoy_id) is not None


def is_vjoy_guid_connected(device_guid) -> bool:
    if get_output_target(parse_virtual_device_key(device_guid)) is not None:
        return True
    vjoy_id = vjoy_id_from_guid(device_guid, None)
    if vjoy_id is not None:
        return is_vjoy_connected(vjoy_id)
    return False


def get_native_vjoy_devices(connected_only=True):
    """Read registry metadata without resolving output aliases or failover."""
    devices = dict(_all_vjoy_devices_map)
    devices.update(_vjoy_devices_map)
    return [dev for vid, dev in sorted(devices.items()) if not connected_only or dev.connected]


def vjoy_devices(connected_only=True, *, resolve_failover=True):
    """Get vJoy outputs, substituting available Maestro failover devices.

    Set resolve_failover=False when reading native provider/profile identities.
    Use vjoy_device_map() when the original vJoy request IDs are also needed.
    """
    if not resolve_failover:
        return get_native_vjoy_devices(connected_only)
    return list(vjoy_device_map(connected_only=connected_only).values())


def maestro_devices(connected_only=True) -> list:
    """Returns the list of Maestro devices.

    :param connected_only: if set, filters Maestro devices that are detected only, if not, returns all devices
    :return list of [DeviceSummary] holding the device configuration for every Maestro device
    """
    global _maestro_devices_map, _maestro_devices_map
    # with _device_registry_lock:
    if connected_only:
        device_list = list(_maestro_devices_map.values())
    else:
        device_list = list(_maestro_devices_map.values())

    return device_list


def configure_vjoy_failover(vjoy_id: int, device_guid=None):
    """Configures a single vJoy failover device based on its ID and marks it as a failover device"""
    global \
        _vjoy_devices_map, \
        _joystick_device_guid_map, \
        _joystick_devices, \
        _vjoy_devices, \
        _all_joystick_devices, \
        _all_vjoy_devices_map
    # Failover metadata must retain the requested vJoy identity, not its backend.
    device = _vjoy_devices_map.get(vjoy_id)
    if not device:
        device = _create_vjoy_device(vjoy_id)
        if device_guid is not None:
            device.device_guid = device_guid
            device.device_id = gremlin.util.normalize_guid(device_guid)
        device.setConnected(True)  # enable output via failover
        device.data["failover"] = True  # indicate this is a failover device
        syslog.info(
            f"VJOY: Configured failover VJOY for device ID [{vjoy_id}] with [{device.axis_count}] axes, [{device.button_count}] buttons, [{device.hat_count}] hats"
        )
        _vjoy_devices_map[vjoy_id] = device
        _all_vjoy_devices_map[vjoy_id] = device
        _all_devices_map[device.device_guid] = device
        _joystick_device_guid_map[device.device_guid] = device
        _joystick_devices.append(device)
        _vjoy_devices.append(device)
        _all_joystick_devices.append(device)
        _all_virtual_devices_map[DeviceType.VJoy][vjoy_id] = device
        _output_targets.clear()


def clearVjoyDevices():
    """Clears all configured vJoy devices from the internal mappings."""
    global \
        _vjoy_devices_map, \
        _joystick_device_guid_map, \
        _joystick_devices, \
        _vjoy_devices, \
        _all_joystick_devices, \
        _all_virtual_devices_map
    for vjoy_id, device in list(_vjoy_devices_map.items()):
        if device.data.get("failover", False):
            if _all_vjoy_devices_map.get(vjoy_id) is device:
                _all_vjoy_devices_map.pop(vjoy_id, None)
            if _all_devices_map.get(device.device_guid) is device:
                _all_devices_map.pop(device.device_guid, None)
        if device.device_guid in _joystick_device_guid_map:
            del _joystick_device_guid_map[device.device_guid]
        if device in _joystick_devices:
            _joystick_devices.remove(device)
        if device in _vjoy_devices:
            _vjoy_devices.remove(device)
        if device in _all_joystick_devices:
            _all_joystick_devices.remove(device)
        if vjoy_id in _all_virtual_devices_map[DeviceType.VJoy]:
            del _all_virtual_devices_map[DeviceType.VJoy][vjoy_id]
    _vjoy_devices_map.clear()
    _output_targets.clear()


def configure_failover(vjoy_map: dict):
    """Configures the vJoy failover devices based on the provided mapping

    :param vjoy_map: dictionary mapping vJoy device IDs to their device information
          {virtual_id: {"axis": [input_id], "button": [input_id], "hat": [input_id]}}

    """

    # get the index of each vjoy device in sequence - id range is 1 to 16 (1 based)
    vjoy_ids = list(vjoy_map.keys())
    vjoy_ids.sort()
    for vjoy_id in vjoy_ids:
        configure_vjoy_failover(vjoy_id)


def virtual_devices(connected_only=True) -> list:
    """Get provider identities once each, retaining configured profile targets."""
    return get_native_vjoy_devices(connected_only) + maestro_devices(connected_only=connected_only)


def parse_virtual_device_key(value):
    """Keep legacy vJoy indices numeric and virtual device GUIDs as strings."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text)  # @IgnoreException
    except TypeError, ValueError:
        return text


def virtual_device_key(device):
    """Serializable output identifier without collisions between providers."""
    return device.vjoy_id if device.device_type == DeviceType.VJoy else str(device.device_guid)


def get_virtual_device(key):
    """Read configured provider identities, including offline profile targets."""
    key = parse_virtual_device_key(key)
    if isinstance(key, int):
        return next((device for device in get_native_vjoy_devices(False) if device.vjoy_id == key), None)
    if key is None:
        return None
    device = getDevice(key, show_error=False)
    return device if device is not None and device.is_virtual else None


def scale_to_range(value, source_min=-1.0, source_max=1.0, target_min=-1.0, target_max=1.0, invert=False):
    """scales a value on one range to the new range

    value: the value to scale
    r_min: the source value's min range
    r_max: the source value's max range
    new_min: the new range's min
    new_max: the new range's max
    invert: true if the value should be reversed
    """
    r_delta = source_max - source_min
    if r_delta == 0:
        # frame the value if no valid range given
        if value < source_min:
            value = -1.0
        if value > source_max:
            value = 1.0

    if invert:
        result = (((source_max - value) * (target_max - target_min)) / (source_max - source_min)) + target_min
    else:
        result = (((value - source_min) * (target_max - target_min)) / (source_max - source_min)) + target_min

    # clamp rounding precision
    if result < target_min:
        result = target_min
    elif result > target_max:
        result = target_max
    return result + 0


def get_axis_name(axis_id):
    """gets the axis name based on the input #"""
    if axis_id == 1:
        axis_name = "X"
    elif axis_id == 2:
        axis_name = "Y"
    elif axis_id == 3:
        axis_name = "Z"
    elif axis_id == 4:
        axis_name = "RX"
    elif axis_id == 5:
        axis_name = "RY"
    elif axis_id == 6:
        axis_name = "RZ"
    elif axis_id == 7:
        axis_name = "S1"
    elif axis_id == 8:
        axis_name = "S2"
    else:
        axis_name = f"(unknown [{axis_id}])"
    return axis_name


# def get_axis_curve_data(guid, identifier):
#     """gets the curve data for an axis"""


def get_curved_axis(device_guid, axis_id):
    """returns curved/calibrated data same as the event handler"""
    import gremlin.config

    verbose = gremlin.config.Configuration().verbose_mode_curve

    if isinstance(device_guid, int):
        device_guid = getVjoyDeviceGuid(device_guid)
    device = getDevice(device_guid)
    if not device:
        if verbose:
            syslog.warning(f"APPLY CURVE: device not found: id [{device_guid}]")
        return None

    if not device.is_special:
        guid = device.device_guid
        eh = gremlin.event_handler.EventListener()
        value = device.get_axis(axis_id)
        curved = eh.apply_transforms(guid, axis_id, value)
        if verbose:
            syslog.info(f"APPLY CURVE: {device.name} axis: [{axis_id}] input: {value:0.3f} curved: {curved:0.3f}")
        return curved

    else:
        if device.device_type != DeviceType.Osc:
            return None
        import gremlin.ui.osc_device

        if isinstance(axis_id, gremlin.ui.osc_device.OscInputItem) and axis_id.is_axis:
            osc = gremlin.ui.osc_device.InputOscClient()
            osc.start()
            data = osc.getData(axis_id.message)  # gets data arguments or None if no data
            if data is None:
                data = 0  # default is centeredv
            return data

    return None


def get_device(device_guid: int | str | dinput.GUID, show_error=True) -> DeviceSummary:
    """gets the device for the given ID - issues error message if not found"""
    return getDevice(device_guid, show_error)


def get_axis(device_guid: str | dinput.GUID | int, input_id: int, normalized=True):
    """gets the value of the specified axis
    :param device_guid: device GUID (including Maestro targets), or a vJoy integer ID
    :param input_id: axis index (1 based), non linear
    :param: normalized  - if set - normalizes to -1.0 +1.0 floating point

    """
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    dev: DeviceSummary = get_device(device_guid)
    if dev and dev.axis_count:
        assert input_id in dev.axis_id_map, f"invalid axis index [{input_id}] for device {dev.name}"
        value = dev.get_axis(input_id)
        if normalized:
            value = gremlin.util.scale_to_range(value, source_min=-32767, source_max=32767, target_min=-1, target_max=1)
        return value

    return 0.0


def get_hat(device_guid: str | dinput.GUID | int, index) -> int:
    """gets the current hat value
    :param device_guid: device GUID (including Maestro targets), or a vJoy integer ID
    :param index: hat index 1 to 4
    :return: hat value

    """
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    device: DeviceSummary = get_device(device_guid)
    if device and device.hat_count:
        return device.get_hat(index)
    return -1  # center


def get_hat_position(device_guid: str | dinput.GUID | int, input_id: int) -> tuple:
    """gets the hat position as a position tuple
    :param device_guid: device guid or vjoy device ID (integer)
    :param input_id: hat index 1 to 4
    :return: hat position tuple
    """

    direction = get_hat(device_guid, input_id)
    if direction in vjoy.Hat.to_continuous_position:
        return vjoy.Hat.to_continuous_position[direction]
    return (0, 0)  # centered


def get_button(device_guid: str | dinput.GUID | int, input_id: int) -> bool:
    """gets the button pressed state if the button and device exists - defaults to FALSE if not found"""
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    device: DeviceSummary = get_device(device_guid)
    if __debug__:
        if device and device.device_type in (DeviceType.VJoy, DeviceType.Maestro, DeviceType.Joystick):
            assert input_id > 0 and input_id <= device.button_count, (
                f"Invalid button index for vjoy device [{device.name}] [{input_id}]"
            )
    if device and input_id:
        match device.device_type:
            case DeviceType.VJoy | DeviceType.Maestro | DeviceType.Joystick:
                if device.button_count:
                    vid = device.vjoy_id
                    try:
                        vid = int(vid)
                    except TypeError, ValueError:
                        vid = 0
                    # vJoy IDs are 1â€“16. -1 is the DeviceSummary default and is
                    # truthy in Python, so "if vjoy_id" is not a valid check.
                    if device.device_type == DeviceType.VJoy and 1 <= vid <= 16:
                        try:
                            button = VJoyProxy()[vid].button(input_id)
                        except Exception as exc:
                            syslog.warning(
                                "GetButton(): vjoy [%s] button [%s] unavailable: %s",
                                vid,
                                input_id,
                                exc,
                            )
                            return False
                        if button:
                            return button.is_pressed
                        syslog.warning(f"GetButton(): invalid vjoy [{vid}] button [{input_id}] not found")
                        return False
                # physical / disconnected / maestro without a vJoy id
                return device.get_button(input_id)
            case DeviceType.Osc:
                if hasattr(input_id, "message"):
                    # OSC device
                    import gremlin.ui.osc_device

                    osc = gremlin.ui.osc_device.InputOscClient()
                    osc.start()  # ensure started
                    data = osc.getData(input_id.message)  # gets data arguments or None if no data
                    if data:
                        return bool(data[0])  # first argument is the button state
                return False  # not received, assume not set
            case DeviceType.Midi:
                if hasattr(input_id, "message"):
                    # MIDI device
                    import gremlin.ui.midi_device

                    midi = gremlin.ui.midi_device.InputMidiClient()
                    midi.start()  # ensure started
                    data = midi.getData(input_id.message)  # gets data arguments or None if no data
                    if data:
                        return data
                return False  # not received, assume not set
            case DeviceType.ModeControl:
                # always trigger for mode control
                import gremlin.ui.mode_device
                import gremlin.shared_state

                mode = gremlin.shared_state.current_mode
                mode_type = gremlin.ui.mode_device.ModeInputModeType(input_id)
                profile = gremlin.shared_state.current_profile
                input_item = profile.getInputItem(device.device_guid, mode, InputType.ModeControl, mode_type)
                if input_item:
                    return input_item.value
                return False
            case DeviceType.State:
                # state device
                import gremlin.ui.state_device

                sd = gremlin.ui.state_device.StateData()
                value = sd.getValue(input_id.key)
                if value is None:
                    return False
                return value

    else:
        syslog.warning(f"JOYSTICK: unable to get button state for device for id [{device_guid}] index [{input_id}]")
        if not device:
            syslog.warning("\tdevice not found")
        if not input_id:
            syslog.warning("\tinvalid id (should be >= 1)")
    return False


class OutputTarget:
    """Resolved virtual output for a requested vjoy id or device GUID.

    kind is "vjoy" or "maestro"; out_id is the vjoy id or the maestro index that is written to.
    remote_id is the id the request was made for - it is what is sent to remote machines
    so the remote machine can apply its own failover.
    """

    __slots__ = ("device", "kind", "out_id", "virtual_id", "_maestro", "source_device")

    def __init__(self, device: DeviceSummary, kind: str, out_id: int, virtual_id: int, source_device: DeviceSummary = None):
        self.device = device
        self.kind = kind
        self.out_id = out_id  # native vJoy ID or Maestro output slot
        self.virtual_id = virtual_id  # device virtual ID (may or may not be the same as the vjoy ID)
        self._maestro = None
        self.source_device = source_device if source_device is not None else device

    @property
    def remote_id(self):
        return self.virtual_id

    @property
    def maestro(self):
        """maestro output device (created on first use)"""
        if self._maestro is None:
            from gremlin.maestro import MaestroOutputDevice

            self._maestro = MaestroOutputDevice(self.out_id)
        return self._maestro


_output_targets: dict = {}  # requested vjoy id (int) or device guid -> OutputTarget | None
_output_targets_failover = None
_OUTPUT_MISSING = object()


def _maestro_failover_id(device, *, require_active=True) -> int | None:
    """Map eligible GEX joystick outputs to their stable vJoy identity."""
    if (device.device_type != DeviceType.Maestro or getattr(device, "is_gamepad", False)
            or (require_active and (not device.connected or getattr(device, "disabled", False)
                or type(device.virtual_id) is not int or not 0 <= device.virtual_id < 16))):
        return None
    key = device.data.get("maestro_key")
    name = str(key).rsplit("/", 1)[-1] if key else (device.name or "")
    prefix, _, suffix = name.casefold().rpartition("-")
    if prefix == "gex" and suffix.isdecimal():
        device_id = int(suffix)
        if 1 <= device_id <= 16 and name.casefold() == f"gex-{device_id}":
            return device_id
    return None


def updateFailoverMap():
    """Index live output targets by vJoy ID and both providers' GUIDs."""
    global _output_targets_failover, _maestro_failover_map, _raw_vjoy_target_map
    failover = gremlin.config.Configuration().virtual_output_failover

    with _device_registry_lock:
        targets = {}
        native_targets = {}
        for vid, device in _native_vjoy_devices.items():
            if device.connected and not getattr(device, "disabled", False) and not device.data.get("failover", False):
                target = OutputTarget(device, "vjoy", vid, vid, device)
                native_targets[vid] = target
                native_targets[device.device_guid] = target
                targets[vid] = target
                targets[device.device_guid] = target

        for device in _maestro_devices:
            if (not device.connected or getattr(device, "disabled", False)
                    or type(device.virtual_id) is not int or not 0 <= device.virtual_id < dinput.GEX_MAX_DEVICES):
                continue
            output = _maestro_output_summary(device)
            direct = OutputTarget(output, "maestro", device.virtual_id, device.virtual_id, device)
            # Direct bridge output does not depend on HID discovery or failover.
            for guid in (device.device_guid, output.device_guid):
                targets[guid] = direct
            vid = _maestro_failover_id(device)
            if (not failover or getattr(device, "is_gamepad", False) or vid is None
                    or device.data.get("maestro_hid_order_valid") is False):
                continue
            source = _native_vjoy_devices.get(vid)
            target = OutputTarget(output, "maestro", device.virtual_id, vid, source)
            targets.setdefault(vid, target)
            if source is not None:
                targets.setdefault(source.device_guid, target)

        # Internally created disconnected vJoy summaries can have their own GUID,
        # distinct from the native summary for this ID. Every known alias follows
        # the same resolved target as the numeric vJoy ID.
        for device in list(_all_devices_map.values()):
            if device.device_type == DeviceType.VJoy:
                target = targets.get(device.vjoy_id)
                if target is not None:
                    targets[device.device_guid] = target

        # Preserve reverse failover for profiles targeting an offline Maestro GUID.
        if failover:
            for device in list(_all_devices_map.values()):
                if device.device_type != DeviceType.Maestro or device.device_guid in targets:
                    continue
                vid = _maestro_failover_id(device, require_active=False)
                target = native_targets.get(vid)
                if target is not None:
                    targets[device.device_guid] = OutputTarget(
                        target.device, "vjoy", target.out_id, device.virtual_id, device)
        # Readers see complete routing generations rather than a cleared map
        # progressively filled by another thread.
        _maestro_failover_map = targets
        _raw_vjoy_target_map = native_targets
        _output_targets.clear()
        _output_targets_failover = failover


def _log_output_map():
    """Log a published routing snapshot without holding the registry lock."""
    if gremlin.config.Configuration().verbose_mode_maestro:
        with _device_registry_lock:
            targets = tuple(_maestro_failover_map.items())
        syslog.info("MAESTRO: output map:")
        for key, target in targets:
            syslog.info(f"  [{key}] -> {target.device.name} ({target.kind}, slot {target.out_id})")


def _find_output_target(key: int | str | GUID) -> OutputTarget | None:
    """Resolve numeric IDs and GUIDs through the same output inventory."""
    key = parse_virtual_device_key(key)
    if isinstance(key, str):
        key = gremlin.util.to_guid(key)
    return _maestro_failover_map.get(key)


def get_output_target(key) -> OutputTarget | None:
    """Get an output target, rebuilding routing when failover is toggled."""
    if _output_targets_failover != gremlin.config.Configuration().virtual_output_failover:
        updateFailoverMap()
    return _find_output_target(key)


def get_maestro_failover_devices():
    """gets a list of DeviceSummary objects for all Maestro failover devices"""
    return list({target.device.device_guid: target.device
                 for key, target in _maestro_failover_map.items()
                 if isinstance(key, int) and target.kind == "maestro"}.values())


def get_output_device(key):
    """Get axis/button/hat access through the configured output backend."""
    key = parse_virtual_device_key(key)
    target = get_output_target(key)
    if target is None:
        return None
    return target.maestro if target.kind == "maestro" else VJoyProxy()[target.out_id]


def resolve_output_targets():
    """rebuilds the virtual device output failover cache - called at profile start and whenever devices change"""
    updateFailoverMap()
    _output_targets.clear()
    for vid in range(1, 17):
        get_output_target(vid)
    for dev in list(_all_devices_map.values()):
        if dev.is_virtual and dev.device_type in (DeviceType.VJoy, DeviceType.Maestro):
            get_output_target(dev.device_guid)


def set_button(device_guid: str | dinput.GUID | int, index: int, is_pressed: bool, update_remote: bool = False):
    """sets a vjoy device button if the index and guid exists

    :param guid: vjoy device ID or device GUID
    :param index: button id
    :param is_pressed: state of the button to set
    :param update_remote: if enabled, and remote control is enabled, also updates the remote client

    """
    import gremlin.event_handler
    import gremlin.remote

    target = get_output_target(device_guid)
    if target is None:
        return
    device = target.device

    if gremlin.event_handler.JoystickState().outputIgnored(device_guid):
        # output ignored
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            syslog.info(f"VJOY SET BUTTON: {device.name} output ignored [{index}] pressed: {is_pressed}")
        return

    if 0 < index <= device.button_count:
        if target.kind == "maestro":
            target.maestro.button(index).is_pressed = is_pressed
        else:
            VJoyProxy()[target.out_id].button(index).is_pressed = is_pressed

    if update_remote:
        (_, is_remote) = gremlin.remote.remote_control.state
        if is_remote:
            gremlin.remote.remote_client.send_button(target.remote_id, index, is_pressed)


def set_axis(device_guid, index: int, value: float, update_remote: bool = False):
    """sets a vjoy axis"""
    import gremlin.event_handler
    import gremlin.remote

    target = get_output_target(device_guid)
    if target is None:
        return
    device = target.device

    if gremlin.event_handler.JoystickState().outputIgnored(device_guid):
        # output ignored
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            syslog.info(f"VJOY SET AXIS: {device.name} output ignored [{index}] value: {value: 0.3f}")
        return

    axis_ids = getattr(device, "axis_id_map", None)
    valid_axis = index in axis_ids if axis_ids else 0 < index <= device.axis_count
    if valid_axis:
        if target.kind == "maestro":
            target.maestro.axis(index).value = value
        else:
            VJoyProxy()[target.out_id].axis(index).value = value

    if update_remote:
        (_, is_remote) = gremlin.remote.remote_control.state
        if is_remote:
            gremlin.remote.remote_client.send_axis(target.remote_id, index, value)


def set_hat(device_guid: str | dinput.GUID | int, index: int, direction: tuple):
    """sets the device hat"""
    target = get_output_target(device_guid)
    if target is None:
        return
    if 0 < index <= target.device.hat_count:
        if target.kind == "maestro":
            target.maestro.hat(index).direction = direction
        else:
            VJoyProxy()[target.out_id].hat(index).direction = direction


def physical_devices():
    """Returns the list of physical devices.

    :return list of physical devices
    """
    global _all_devices_map
    # with _device_registry_lock:
    return [dev for dev in _all_devices_map.values() if not dev.is_virtual]


def default_device():
    """gets the default device"""
    device = None
    devices = physical_devices()
    if devices:
        device = devices[0]
    if not device:
        devices = joystick_devices()
    if devices:
        device = devices[0]
    return device


def select_first_valid_vjoy_input(valid_types):
    """Returns the first valid vjoy input.

    Parameters
    ==========
    valid_types : list
        List of InputType values that are valid type to be returned

    Return
    ======
    dict
        Dictionary containing the information about the selected vJoy input
    """
    for dev in virtual_devices():
        if dev.device_type == DeviceType.VJoy:
            dev = getDeviceFromVjoyId(dev.vjoy_id) or dev
        if dev.disabled:
            continue
        if InputType.JoystickAxis in valid_types and dev.axis_count > 0:
            return {
                "device_id": virtual_device_key(dev),
                "input_type": InputType.JoystickAxis,
                "input_id": dev.axis_sequence_to_input_id(0),
            }
        elif InputType.JoystickButton in valid_types and dev.button_count > 0:
            return {"device_id": virtual_device_key(dev), "input_type": InputType.JoystickButton, "input_id": 1}
        elif InputType.JoystickHat in valid_types and dev.hat_count > 0:
            return {"device_id": virtual_device_key(dev), "input_type": InputType.JoystickHat, "input_id": 1}
    return None


def vjoy_id_from_guid(guid, not_found_id=1):
    """Returns the vJoy id corresponding to the given device GUID.

    Parameters
    ==========
    guid : GUID
        guid of the vjoy device in windows

    Return
    ======
    int
        vJoy id corresponding to the provided device
    """
    key = parse_virtual_device_key(guid)
    if isinstance(key, int):
        return key if key in vjoy_device_map() else not_found_id

    # Original profile GUIDs remain valid even when their backend is substituted.
    for dev in get_native_vjoy_devices(False):
        if gremlin.util.compare_guid(dev.device_guid, guid):
            return dev.vjoy_id
    for vid, dev in vjoy_device_map().items():
        if gremlin.util.compare_guid(dev.device_guid, guid):
            return vid

    syslog.error(f"Could not find vJoy matching guid {guid!s}")
    return not_found_id


def vjoy_guid_from_id(vid: int):
    """Get the actual native or failover GUID for a vJoy request ID."""
    device = getDeviceFromVjoyId(vid)
    return device.device_guid if device is not None else None


def registerSpecialDevice(dev):
    """adds a special device to the tracking list"""
    global _special_devices_map, _all_devices_map, _special_devices
    # device_guid = gremlin.util.normalize_guid(dev.device_guid)
    # with _device_registry_lock:
    _all_devices_map[dev.device_guid] = dev
    _special_devices_map[dev.device_guid] = dev
    _special_devices.append(dev)

    # syslog.info(f"\tid: [{dev.device_id}] type: [{dev.device_type.name}] name: [{dev.name}]")


def upsertSpecialDevice(dev):
    """Register or update a special device by GUID (no duplicate list entries)."""
    global _special_devices_map, _all_devices_map, _special_devices
    # with _device_registry_lock:
    existing = _special_devices_map.get(dev.device_guid)
    if existing is not None:
        existing.name = dev.name
        existing.device_type = dev.device_type
        existing.device_category = dev.device_category
        _all_devices_map[dev.device_guid] = existing
        return existing
    registerSpecialDevice(dev)
    return dev


def unregisterSpecialDevice(device_guid):
    """Remove a special device from tracking (profile data is left intact)."""
    global _special_devices_map, _all_devices_map, _special_devices
    if device_guid is None:
        return
    # with _device_registry_lock:
    existing = _special_devices_map.pop(device_guid, None)
    if existing is None:
        # Try string / alternate GUID identity
        for key in list(_special_devices_map.keys()):
            if gremlin.util.compare_guid(key, device_guid):
                existing = _special_devices_map.pop(key, None)
                device_guid = key
                break
    if existing is None:
        return
    if existing in _special_devices:
        _special_devices.remove(existing)
    if device_guid in _all_devices_map:
        del _all_devices_map[device_guid]
    syslog.info(f"\tunregistered special device: [{getattr(existing, 'name', device_guid)}]")


def registerDisconnectedDevice(dev):
    """adds a disconnected device to the tracking list"""
    global _disconnected_devices_map, _all_devices_map, _disconnected_devices, _joystick_devices
    # with _device_registry_lock:
    _all_devices_map[dev.device_guid] = dev
    if dev.device_type in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy):
        _joystick_devices.append(dev)
    _disconnected_devices_map[dev.device_guid] = dev
    _disconnected_devices.append(dev)

    syslog.info(f"\t[disconnected device] id: [{dev.device_id}] type: [{dev.device_type.name}] name: [{dev.name}]")


def unregisterDisconnectedDevice(dev):
    global _joystick_devices, _disconnected_devices_map, _all_devices_map, _disconnected_devices
    device_guid = dev.device_guid
    # with _device_registry_lock:
    if dev in _joystick_devices:
        _joystick_devices.remove(dev)
    if device_guid in _all_devices_map:
        del _all_devices_map[device_guid]
    if device_guid in _disconnected_devices_map:
        del _disconnected_devices_map[device_guid]
    if dev in _disconnected_devices:
        _disconnected_devices.remove(dev)


def clearDisconnectedDevices():
    """clears the list of disconnected devices"""
    global _disconnected_devices_map, _disconnected_devices
    # with _device_registry_lock:
    for dev in list(_disconnected_devices):
        unregisterDisconnectedDevice(dev)

        _disconnected_devices_map.clear()
        _disconnected_devices.clear()


def registerConfigDevice(dev):
    """adds a special device to the tracking list"""
    global _config_devices_map, _all_devices_map, _config_devices
    # device_guid = gremlin.util.normalize_guid(dev.device_guid)
    # with _device_registry_lock:
    _all_devices_map[dev.device_guid] = dev
    _config_devices_map[dev.device_guid] = dev
    _config_devices.append(dev)
    syslog.info(f"\tid: [{dev.device_id}] type: [{dev.device_type.name}] name: [{dev.name}]")


def removeDevice(dev: DeviceSummary):
    """removes a device from the tracking list"""
    global _all_joystick_devices, _vjoy_devices_map, _joystick_devices, _all_devices_map
    device_guid = dev.device_guid
    device_guid = gremlin.util.normalize_guid(dev.device_guid)
    # with _device_registry_lock:
    if device_guid in _all_devices_map:
        del _all_devices_map[device_guid]
        _update_joystick_device_maps()


def device_name_from_guid(device_guid, refresh=False) -> str:
    """gets device name from GUID"""

    dev = get_device(device_guid, False)
    if not dev:
        # not found - check for any updated devices
        if refresh:
            refresh_devices()
            dev = get_device(device_guid)
    if dev:
        return dev.name
    return ""


def known_devices() -> list:
    """gets the list of device GUID (strings) known to GremlinEx"""
    global _all_devices_map
    # with _device_registry_lock:
    return list(_all_devices_map.keys())


def getKnownDevicesGuids():
    """gets a list of known device GUIDs (iterator)"""
    global _all_devices_map
    # with _device_registry_lock:
    return list(_all_devices_map.keys())


def getDevices() -> list[DeviceSummary]:
    """gets a list of known devices, physical and virtual (iterator)"""
    global _all_devices_map
    # with _device_registry_lock:
    return list(_all_devices_map.values())


def getValidJoysticksDevices() -> list[DeviceSummary]:
    """gets a list of enabled joystick type devices"""
    global _all_joystick_devices
    # with _device_registry_lock:
    return [
        dev
        for dev in _all_joystick_devices
        if not dev.disabled and dev.device_type in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy)
    ]


def getVisibleDevices() -> list[DeviceSummary]:
    """gets a list of visible devices"""
    global _all_devices_map
    import gremlin.config

    config = gremlin.config.Configuration()
    visible_map = config.device_visible_map
    # with _device_registry_lock:
    return [dev for dev in _all_devices_map.values() if not dev.disabled and visible_map.get(dev.device_guid, True)]


def getVisibleJoystickDevices() -> list[DeviceSummary]:
    """gets a list of visible joystick type devices"""
    global _all_joystick_devices
    import gremlin.config

    config = gremlin.config.Configuration()
    visible_map = config.device_visible_map
    # with _device_registry_lock:
    return [dev for dev in _all_joystick_devices if not dev.disabled and visible_map.get(dev.device_guid, True)]


def getValidJoystickDevicesMap() -> dict[dinput.GUID, DeviceSummary]:
    """gets a map of valid joystick device keyed by device guid"""
    global _joystick_device_guid_map
    # with _device_registry_lock:
    return {
        dev.device_guid: dev
        for dev in _joystick_device_guid_map.values()
        if not dev.disabled and dev.device_type in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy)
    }


def getPhysicalDevices() -> list[DeviceSummary]:
    """gets physical joystick devices"""
    global _joystick_device_guid_map
    # with _device_registry_lock:
    return [
        dev
        for dev in _joystick_device_guid_map.values()
        if dev.device_type == DeviceType.Joystick and not dev.is_virtual
    ]


def getDevice(device_guid: int | str | dinput.GUID, show_error=False) -> DeviceSummary | None:
    """Read registry metadata; resolve outputs and log after releasing its lock."""
    global _all_devices_map, _joystick_initialized, _maestro_failover_map

    key = parse_virtual_device_key(device_guid)
    if isinstance(key, int):
        with _device_registry_lock:
            initialized = _joystick_initialized
        return getDeviceFromVjoyId(key) if initialized else None

    if device_guid and not isinstance(device_guid, dinput.GUID):
        device_guid = gremlin.util.to_guid(device_guid)
    with _device_registry_lock:
        initialized = _joystick_initialized
        device = _all_devices_map.get(device_guid) if initialized and device_guid else None
        if initialized and device_guid and device is None:
            target = _maestro_failover_map.get(device_guid)
            if target is not None:
                device = target.device
            else:
                # Bridge output GUIDs remain valid alongside native input GUIDs.
                device = next((d for d in _maestro_devices_map.values() if d.device_guid == device_guid), None)

    if not initialized:
        syslog.warning(f"Device: devices not initialized in getDevice() - device id: [{device_guid}]")
    elif device_guid and device is None and gremlin.config.Configuration().verbose_mode_joystick:
        syslog.warning(f"Device not found for GUID: [{device_guid}]")
        syslog.warning("Available devices:")
        dumpDevices()
    return device


def getDeviceName(device_guid: int | str | dinput.GUID):
    """gets the device name"""
    device = getDevice(device_guid)
    if device:
        if device.device_type == DeviceType.VJoy:
            return getVjoyDeviceName(device.vjoy_id, device.axis_count, device.button_count, device.hat_count)
        return device.name
    return f"unknown: {device_guid!s}"


def getVjoyDeviceName(vid: int, axis_count: int, button_count: int, hat_count: int):
    """gets the vjoy device name"""
    return f"VJoy {axis_count}/{button_count}/{hat_count} ({vid})"


def getDeviceFromVjoyId(vid: int, native=False) -> DeviceSummary | None:
    """Get the resolved output, retaining configured metadata if unavailable."""
    global _raw_vjoy_target_map
    if native:
        # native vjoy device requested - not failover
        return _native_vjoy_devices.get(vid)

    vid = parse_virtual_device_key(vid)
    target = get_output_target(vid)
    if target is not None:
        return target.device
    if not isinstance(vid, int):
        return get_virtual_device(vid)

    dev = next((dev for dev in get_native_vjoy_devices() if dev.vjoy_id == vid), None)
    if dev:
        return dev
    return None


def getVjoyFirstIndex():
    """Get the first available vJoy request ID, including Maestro failover."""
    devices = vjoy_device_map(connected_only=True)
    if devices:
        return next(iter(devices))
    return 1


def getVjoyDeviceGuid(vid: int):
    """Get the resolved native or failover device GUID for a vJoy ID."""
    dev = getDeviceFromVjoyId(vid)
    if dev:
        return dev.device_guid

    refresh_devices()  # do a device reload if the GUID is not found
    dev = getDeviceFromVjoyId(vid)
    if dev:
        return dev.device_guid

    return None  # not found


def getVjoyDeviceGuidStr(vid: int):
    """gets the vjoy device by the given vjoy id as a string"""
    guid = getVjoyDeviceGuid(vid)
    if guid:
        return str(guid)
    return None  # not found


def getVjoyDeviceMap() -> dict:
    """Get native or failover summaries keyed by the requested vJoy ID."""
    return vjoy_device_map()


def getMaestroDeviceMap() -> dict:
    """gets a map of maestro devices keyed by the maestro id, holds a DeviceSummary"""
    return maestro_device_map()


def vjoy_info_from_vjoy_id(vjoy_id: int, connected_only=True):  # -> DeviceSummary:
    """gets physical device info for a vjoy device

    :param vjoy_id: id of vjoy device 1 to 16
    :param connected_only: true to filter by connected vjoys only
    """

    vjoy_id = parse_virtual_device_key(vjoy_id)
    if not isinstance(vjoy_id, int):
        target = get_output_target(vjoy_id)
        if target is not None:
            return target.device
        device = get_virtual_device(vjoy_id)
        return device if device is not None and (device.connected or not connected_only) else None
    device = vjoy_device_map(connected_only=connected_only).get(vjoy_id)
    if device is not None:
        return device
    # not found - ask for a device update
    refresh_devices()
    return vjoy_device_map(connected_only=connected_only).get(vjoy_id)


def maestro_info_from_index(mid_id: int, connected_only=True):
    """gets physical device info for a maestro device

    :param mid_id: id of maestro device 1 to N
    :param connected_only: true to filter by connected maestros only
    """

    global _maestro_devices_map, _maestro_devices_map
    if connected_only:
        if mid_id in _maestro_devices_map:
            return _maestro_devices_map[mid_id]
        # refresh devices if not found to make sure the device didn't show up
        refresh_devices()
        if mid_id in _maestro_devices_map:
            return _maestro_devices_map[mid_id]
        return None

    # include disconnected
    if mid_id in _maestro_devices_map:
        return _maestro_devices_map[mid_id]
    # not found - ask for a device update
    refresh_devices()
    if mid_id in _maestro_devices_map:
        return _maestro_devices_map[mid_id]
    return None


def vjoy_device_map(connected_only=False) -> dict[int, DeviceSummary]:
    """Map vJoy request IDs to actual outputs, including Maestro failover.

    Offline/configured native metadata is retained unless connected_only is set.
    A Maestro summary keeps its own native slot and GUID; the map key is the
    vJoy ID callers must continue using for legacy mappings and remote output.
    """
    devices = {dev.vjoy_id: dev for dev in get_native_vjoy_devices(False) if 1 <= dev.vjoy_id <= 16}
    for vid in range(1, 17):
        target = get_output_target(vid)
        if target is not None:
            devices[vid] = target.device

        elif connected_only:
            devices.pop(vid, None)
    return dict(sorted(devices.items()))


def maestro_device_map() -> dict[int, DeviceSummary]:
    """returns all maestro devices indexed by maestro_id -> device"""
    global _maestro_devices_map
    # with _device_registry_lock:
    return _maestro_devices_map.copy()


def virtual_device_map() -> dict[DeviceType, dict[int, DeviceSummary]]:
    """returns all virtual input devices indexed by device_type:DeviceType, contains [virtual_id:int] -> device: DeviceSummary"""
    global _all_virtual_devices_map
    # with _device_registry_lock:
    return _all_virtual_devices_map.copy()


def is_device_connected(device_guid) -> bool:
    """true if the device is connected (reported in)"""
    device: DeviceSummary = getDevice(device_guid)
    if device:
        return device.connected
    return False


def linear_axis_index(axis_map, axis_index: int) -> int:
    """Returns the linear index for an axis based on the axis index.

    Parameters
    ==========
    axis_map : dinput.AxisMap
        AxisMap instance which contains the mapping between linear and
        axis indices
    axis_index : int
        Index of the axis for which to return the linear index

    Return
    ======
    int
        Linear axis index
    """
    for entry in axis_map:
        if entry.axis_index == axis_index:
            return entry.linear_index
    raise error.GremlinError("Linear axis lookup failed")


def reset_devices(emit=True, force=True) -> bool:
    """resets devices on device change

    :param emit: emit the device change event after re-initialization
    :param force: re-initialize even if the DINPUT device list is unchanged
    :return: True if devices were re-initialized, False if skipped
    """
    syslog.info("Joystick device change detected - re-initializing joysticks")
    if not joystick_devices_initialization(force=force):
        return False
    if emit:
        el = gremlin.event_handler.EventListener()
        el.device_change_event.emit()
    return True


def refresh_devices() -> bool:
    """updates any missing dynamic devices like VIGEM or VJOY from directInput

    :return: True if the device list changed and was re-initialized
    """
    if gremlin.shared_state.profile_loading:
        # defer device refresh until profile loading completes
        return False
    return reset_devices(False, force=False)


def refresh_device_inventory():
    """Refresh bridge metadata and native enumeration for an explicit UI refresh."""
    from gremlin.maestro import Maestro

    dinput.DILL.init()
    changed = reset_devices(False, force=True)
    maestro = Maestro()
    if maestro.enabled:
        try:
            maestro.syncBridge()
        except OSError, RuntimeError, ValueError, TimeoutError:
            syslog.exception("MAESTRO: unable to refresh the device inventory")
    else:
        set_maestro_devices([])
    return changed


def noOpCallback(self, value):
    """dummy callback for special devices that don't have a particular axis, hat or button"""
    return None


def noOpHatCallback(self, value):
    """dummy callback for special devices that don't have a hat (returns neutral position)"""
    return -1  # center position


def registerSpecialDevices():
    """registers special devices"""
    import gremlin.ui.octavi_device
    import gremlin.config

    # import gremlin.ui.osc_device
    # import gremlin.ui.midi_device
    global _special_devices_map, _special_devices, _config_devices_map, _config_devices
    special_devices = []
    config_devices = []

    syslog.info("Special devices:")

    config = gremlin.config.Configuration()

    # keyboard

    device = DeviceSummary()
    device.name = "Keyboard"
    device.device_guid = gremlin.shared_state.keyboard_tab_guid
    device.device_type = DeviceType.Keyboard
    device.device_category = DeviceCategory.Special
    special_devices.append(device)

    # state

    device = DeviceSummary()
    device.name = "State"
    device.device_guid = gremlin.shared_state.state_tab_guid
    device.device_type = DeviceType.State
    device.device_category = DeviceCategory.Special
    special_devices.append(device)

    # OSC
    if config.startup_osc_enabled:
        device = DeviceSummary()
        device.name = "OSC"
        device.device_guid = gremlin.shared_state.osc_tab_guid
        device.device_type = DeviceType.Osc
        device.device_category = DeviceCategory.Special
        special_devices.append(device)

    # MIDI
    if config.startup_midi_enabled:
        device = DeviceSummary()
        device.name = "MIDI"
        device.device_guid = gremlin.shared_state.midi_tab_guid
        device.device_type = DeviceType.Midi
        device.device_category = DeviceCategory.Special
        special_devices.append(device)

    # Octavi IFR1

    device = DeviceSummary()
    device.name = "Octavi IFR1"
    device.device_guid = gremlin.shared_state.octavi_tab_guid
    device.device_type = DeviceType.OctaviIFR1
    device.device_category = DeviceCategory.Special
    device.setAxisCallback(noOpCallback)
    device.setHatCallback(noOpHatCallback)
    oo = gremlin.ui.octavi_device.OctaviInterface()
    device.setButtonCallback(oo.get_button)
    special_devices.append(device)

    # Stream Deck legacy tab GUID (old profiles). Live decks register per deviceId.
    if config.startup_streamdeck_enabled:
        device = DeviceSummary()
        device.name = "Stream Deck (legacy)"
        device.device_guid = gremlin.shared_state.streamdeck_tab_guid
        device.device_type = DeviceType.StreamDeck
        device.device_category = DeviceCategory.Special
        special_devices.append(device)

    # voice
    if config.startup_voice_enabled:
        device = DeviceSummary()
        device.name = "Voice"
        device.device_guid = gremlin.shared_state.voice_tab_guid
        device.device_type = DeviceType.Voice
        device.device_category = DeviceCategory.Special
        special_devices.append(device)

    # mode
    device = DeviceSummary()
    device.name = "Mode/Profile"
    device.device_guid = gremlin.shared_state.mode_tab_guid
    device.device_type = DeviceType.ModeControl
    device.device_category = DeviceCategory.Special
    special_devices.append(device)

    # overlay designer
    if config.startup_overlay_enabled:
        device = DeviceSummary()
        device.name = "Overlay"
        device.device_guid = gremlin.shared_state.overlay_tab_guid
        device.device_type = DeviceType.Overlay
        device.device_category = DeviceCategory.Special
        special_devices.append(device)

    if config.afcs_enabled:
        # AFCS visual axis-flow designer
        device = DeviceSummary()
        device.name = "AFCS"
        device.device_guid = gremlin.shared_state.afcs_tab_guid
        device.device_type = DeviceType.Afcs
        device.device_category = DeviceCategory.Special
        special_devices.append(device)

    # THESE SHOULD BE LAST
    # plugin

    device = DeviceSummary()
    device.name = "Plugins"
    device.device_guid = gremlin.shared_state.plugins_tab_guid
    device.device_type = DeviceType.Plugins
    device.device_category = DeviceCategory.Config
    config_devices.append(device)

    # settings
    device = DeviceSummary()
    device.name = "Settings"
    device.device_guid = gremlin.shared_state.settings_tab_guid
    device.device_type = DeviceType.Settings
    device.device_category = DeviceCategory.Config
    config_devices.append(device)

    # Constructors and plugin callbacks above may query devices or start
    # threads. Only the completed metadata is published under the lock.
    with _device_registry_lock:
        devices = dict(_all_devices_map)
        for previous in _special_devices + _config_devices:
            if devices.get(previous.device_guid) is previous:
                devices.pop(previous.device_guid, None)
        devices.update((device.device_guid, device) for device in special_devices + config_devices)
        _special_devices = special_devices
        _config_devices = config_devices
        _special_devices_map = {device.device_guid: device for device in special_devices}
        _config_devices_map = {device.device_guid: device for device in config_devices}
        _replace_device_registry(devices)

    if config.startup_streamdeck_enabled:
        # Re-attach any Stream Decks the bridge already knows about (after a rescan).
        try:
            from gremlin.ui import streamdeck_device as streamdeck_ui

            streamdeck_ui.resync_streamdeck_special_devices()
        except Exception:
            pass


def getSpecialDevices() -> list:
    """gets all special devices"""
    global _special_devices
    # with _device_registry_lock:
    return list(_special_devices)


def isSpecialDevice(device_guid: str) -> bool:
    """checks if a device is a special device"""
    global _special_devices
    device_guid = gremlin.util.normalize_guid(device_guid)
    for device in _special_devices:
        if device.device_guid == device_guid:
            return True
    return False


def getConfigDevices() -> list:
    """gets all configuration devices"""
    global _config_devices
    # with _device_registry_lock:
    return list(_config_devices)


def scanDinput():
    """rescans dinput devices"""

    dinput.DILL.init()
    device_count = dinput.DILL.get_device_count()
    if device_count == 0:
        # no hardware input detected
        syslog.info("INIT: no DirectInput devices detected - waiting for data")
        max_retries = 3
        attempt = 1
        while device_count == 0 and attempt <= max_retries:
            time.sleep(0.25)
            device_count = dinput.DILL.get_device_count()
            syslog.info(f"INIT: attempt number {attempt}")
            attempt += 1

    for device_index, dev in enumerate(dinput.DILL.getDevices()):
        if not isDeviceValid(dev):
            continue
        device_guid = gremlin.util.normalize_guid(dev.device_guid)
        if device_guid not in _joystick_device_guid_map:
            syslog.info(f"\tindex: [{device_index}] {dev!s}")
            if _is_excluded_native_joystick(dev):
                dev.disabled = True

            _joystick_devices.append(dev)
            _joystick_device_guid_map[device_guid] = dev  # key by GUID


def _create_vjoy_device(vid: int):
    """creates a fake vjoy device"""
    assert vid > 0 and vid <= 16, "vjoy_index must be between 1 and 16"

    device = DeviceSummary()
    device.device_id = gremlin.util.get_guid()  # random GUID
    device.device_guid = gremlin.util.parse_guid(device.device_id)
    device.device_type = DeviceType.VJoy
    device.vendor_id = 0x1234  # vjoy vendor
    device.product_id = 0xBEAD  # vjoy product ID
    device.setConnected(False)

    # setup button count based on id - index 1 defaults
    button_count = 128
    axis_count = 8
    hat_count = 4

    # Adjust button, axis, and hat counts based on the vjoy index
    for i in range(vid):
        if i + 1 == vid:
            device.axis_count = axis_count
            device.button_count = button_count
            device.hat_count = hat_count
            break
        hat_count -= 1
        if hat_count < 0:
            hat_count = 4
            button_count -= 1

    device.setDeviceName(getVjoyDeviceName(vid, axis_count, button_count, hat_count))
    device.input_enabled = False
    device.joystick_id = vid - 1
    device.vjoy_id = vid
    device.virtual_id = vid
    device.axismap_list = []
    device.usage_page = None
    device.usage = None
    device.axis_names = {}
    return device


def invalidDeviceGuid():
    """invalid device guid placeholder as a dinput.GUID"""
    global _invalid_device_guid
    import gremlin.util

    return gremlin.util.parse_guid(_invalid_device_guid)


def getInvalidDevice() -> DeviceSummary:
    """returns the invalid device object"""
    global _invalid_device_guid, _invalid_device
    if _invalid_device is None:
        dev = DeviceSummary()
        dev.device_id = _invalid_device_guid
        dev.device_guid = gremlin.util.parse_guid(_invalid_device_guid)
        dev.name = "No Device"
        dev.device_type = DeviceType.NotSet
        dev.device_category = DeviceCategory.Special
        dev.disabled = True
        dev.setConnected(False)
        _invalid_device = dev
    return _invalid_device


def invalidDeviceId() -> str:
    """invalid device guid placeholder as a string"""
    global _invalid_device_guid
    return _invalid_device_guid


def _device_list_signature(devices=None) -> tuple:
    """Compare identities and layouts from one atomic native snapshot."""
    if devices is None:
        devices = dinput.DILL.getDevices()
    return tuple((str(device.device_guid), device.name, device.vendor_id, device.product_id,
                  device.axis_count, device.button_count, device.hat_count, device.usage_page, device.usage)
                 for device in devices)


def _publish_joystick_devices(devices, vjoy_devices, native_vjoy_devices, signature):
    """Commit discovered metadata, rebasing on the latest service/special devices.

    No driver calls, logging, plugin setup, or UI notifications belong in this
    section: input callbacks need this lock while those operations can wait.
    """
    global _all_vjoy_devices_map, _native_vjoy_devices, _last_device_signature, _joystick_initialized
    with _device_registry_lock:
        published = {device.device_guid: device for device in _disconnected_devices}
        published.update(devices)
        joystick_types = (DeviceType.Joystick, DeviceType.VJoy, DeviceType.Maestro)
        published.update((guid, device) for guid, device in _all_devices_map.items()
                         if device.device_type not in joystick_types)
        _replace_device_registry(published)
        _all_vjoy_devices_map = vjoy_devices
        _native_vjoy_devices = native_vjoy_devices
        _maestro_replaced_devices.clear()
        _update_joystick_device_maps()
        _last_device_signature = signature
        _joystick_initialized = True
        return tuple(_joystick_devices)


def joystick_devices_initialization(force: bool = True) -> bool:
    """Initializes joystick device information.

    :param force: if False, skip the work when the DINPUT device list is unchanged since the last initialization
    :return: True if initialization ran, False if it was skipped

    This function retrieves information about various joystick devices and
    associates them and collates their information as required.

    Amongst other things this also ensures that each vJoy device has a correct
    windows id assigned to it.
    """

    import gremlin.util

    if gremlin.event_handler.EventListener().deferDeviceChanges():
        # updates are defered due to a pending update to devices
        return False

    if not force and _joystick_initialized and _last_device_signature is not None:
        dinput.DILL.init()
        try:
            if _device_list_signature() == _last_device_signature:
                syslog.info("INIT: Device list unchanged - skipping joystick re-initialization")
                return False
        except Exception:
            pass  # fall through to a full initialization

    # Discover into local maps. Driver calls, logging and device constructors
    # must never hold the lock needed by native input callbacks.
    config = gremlin.config.Configuration()
    verbose = config.verbose_mode_inputs or config.verbose_mode_vjoy
    verbose_detailed = verbose and config.verbose_mode_extra

    # vjoy monitor handls keep alive pings to vjoy so the process maintains a hook into the interface when there is no activity
    vjm = vjoy.VJoyMonitor()

    try:
        with _joystick_init_lock:
            syslog.info("INIT: Initializing joystick devices")

            # turn off vjoy monitoring
            vjm.stop()

            dinput.DILL.init()
            _hid = gremlin.hid.Hid()
            hid_enabled = gremlin.config.Configuration().hid_list_enabled
            if hid_enabled:
                controller_count = _hid.get_controller_count()
                syslog.info(f"INIT: {controller_count} HID devices detected:")

                # # give it some time to load data
                # time.sleep(0.25)

                device_count = 0  #

                max_retries = 5
                attempt = 1
                while device_count != controller_count and attempt <= max_retries:
                    time.sleep(0.05)
                    device_count = dinput.DILL.get_device_count()
                    attempt += 1

                if verbose and device_count:
                    syslog.info(f"INIT: {device_count} hardware devices detected:")
                    dinput.DILL.dumpDevices()

                if device_count != controller_count:
                    syslog.warning(
                        f"INIT: HID device count is {controller_count}, does not match DirectX controller count: {device_count}"
                    )

                if device_count == 0:
                    syslog.warning("INIT: DirectX reports no hardware devices detected")

            else:
                max_retries = 10
                attempt = 1
                last_count = 0
                while attempt <= max_retries:
                    device_count = dinput.DILL.get_device_count()
                    if last_count != device_count:
                        attempt += 1
                        last_count = device_count
                        time.sleep(0.25)
                    else:
                        break

            native_devices = dinput.DILL.getDevices()
            # Process all connected devices in order to properly initialize the device registry
            devices = []
            _joystick_device_guid_map = {}
            configured_vjoy_devices = {}
            _vjoy_devices_map = {}
            _raw_vjoy_target_map = {}
            _maestro_devices_map = {}
            native_vjoy_devices = {}
            _all_joystick_devices = []
            discovered_devices = {}

            virtual_count = 0
            real_count = 0
            virtual_devices = {}
            dinput_vjoy_device_map = {}  # map of vjoy devices by vjoy ID

            try:
                syslog.info("DINPUT device list:")
                for device_index, dev in enumerate(native_devices):
                    # All entries belong to the same native inventory generation.
                    if not isDeviceValid(dev):
                        syslog.warning(f"\t\tInvalid device detected: {dev!s}")
                        continue  # ghost device

                    syslog.info(f"\tDevice: {dev.name} ID {dev.device_id}  Type: {dev.device_type.name}")
                    if dev.vendor_id == 0x4D8 and dev.product_id == 0xE6D6 and dev.button_count == 35:
                        # IFR1 device, disable
                        syslog.warning(
                            "\t\tOctavi IFR1 is disabled in GremlinEx as a regular joystick as it's handled at the HID level."
                        )
                    if _is_excluded_native_joystick(dev):
                        dev.disabled = True

                    dev.device_category = DeviceCategory.Physical

                    if dev.axis_count:
                        syslog.info(f"\t\tAxis definitions: {dev.axis_count} found")
                        for i in range(dev.axis_count):
                            linear = i + 1
                            axis_id = dev.linear_id_map[linear]
                            axis_name = dev.get_axis_name(axis_id)
                            syslog.info(
                                f"\t\t\tAxis {axis_name} A{axis_id} L{linear} {'(sequential)' if linear == axis_id else '(non-sequential)'}"
                            )

                    devices.append(dev)
                    syslog.info(f"\t\tIndex: [{device_index}] {dev!s}")

                    if dev.device_type in (DeviceType.Joystick, DeviceType.Maestro, DeviceType.VJoy):
                        _joystick_device_guid_map[dev.device_guid] = dev  # key by GUID

                    discovered_devices[dev.device_guid] = dev  # key by GUID

                    if dev.is_virtual:
                        virtual_count += 1
                        virtual_devices[dev.hashkey] = dev
                        dev.device_category = DeviceCategory.Virtual
                        match dev.device_type:
                            case DeviceType.VJoy:
                                dinput_vjoy_device_map[dev.hashkey] = dev
                            case DeviceType.Maestro:
                                if dev.virtual_id >= 0:
                                    _maestro_devices_map[dev.virtual_id] = dev
                            case _:
                                syslog.warning(
                                    f"\tWarning: Unknown virtual device [{dev.name}] with vendor ID: [0x{dev.vendor_id:X}] product ID: [0x{dev.product_id:X}]"
                                )

                    else:
                        real_count += 1

                syslog.info(f"INIT: Found {real_count} hardware devices and {virtual_count} virtual devices")
            except Exception as ex:
                syslog.error(f"INIT: Error while initializing devices: {ex}")
                syslog.error(traceback.format_exc())

            vjoy_lookup = {}
            vjoy_wheel_lookup = {}

            should_terminate = False

            # Query all vJoy devices in sequence until all have been processed and
            # their matching SDL counterparts have been found.
            vjoy_hash_list = []
            vjoy_proxy = VJoyProxy()
            config_map = {}
            disconnected_vid_list = []
            used_counts = []

            config.vjoy_installed = vjoy_installed(config)

            for vid in range(1, 17):  # index 1 up to 16
                # Only process devices that actually exist
                is_connected = config.vjoy_installed and vjoy.device_available(vid)
                if is_connected:
                    # device reports as available via the VJOY interface
                    axis_count = vjoy.axis_count(vid)
                    button_count = vjoy.button_count(vid)
                    hat_count = vjoy.hat_count(vid)
                    if button_count not in used_counts:
                        used_counts.append(button_count)
                    config_map[vid] = (is_connected, axis_count, button_count, hat_count)
                    vjoy.ensure_released(vid)

                    dinput_key = (axis_count, button_count, hat_count)  # (input_vjoy_device_map[dev.vjoy_id] = dev
                    # see if the device was detected in DINPUT
                    if dinput_key not in dinput_vjoy_device_map:
                        syslog.warning(
                            f"VJOY device [{vid}] exists in the VJOY API but was not detected by DINPUT indicating a possible configuration or conflict problem.  This VJOY will be disabled."
                        )
                        disconnected_vid_list.append(vid)
                        # fake device
                        device = _create_vjoy_device(vid)
                        # update the default name
                        configured_vjoy_devices[vid] = device
                        _joystick_device_guid_map[device.device_guid] = device  # key by GUID

                    else:
                        device: DeviceSummary = dinput_vjoy_device_map[dinput_key]
                        device.set_vjoy_id(vid)
                        device.setConnected(
                            True
                        )  # connected means the VJOY device is not only shown in the API but also with DINPUT.
                        syslog.info(f"VJOY device [{vid}] matched to DINPUT device [{device.device_id}]")
                        configured_vjoy_devices[vid] = device
                        _vjoy_devices_map[vid] = device
                        _joystick_device_guid_map[device.device_guid] = device  # key by GUID
                        discovered_devices[device.device_guid] = device  # key by GUID

                    # keep a reference to the raw vjoy device as other lists may contain failover data instead
                    target = OutputTarget(device, "vjoy", vid, vid, source_device=device)
                    _raw_vjoy_target_map[vid] = target
                else:
                    # device reports as not available from the vjoy interface
                    disconnected_vid_list.append(vid)
                    device = _create_vjoy_device(vid)
                    configured_vjoy_devices[vid] = device
                    _joystick_device_guid_map[device.device_guid] = device  # key by GUID
                    discovered_devices[device.device_guid] = device
                    config_map[vid] = (False, device.axis_count, device.button_count, device.hat_count)

                    if verbose:
                        syslog.warning(
                            f"VJOY device [{vid}] is not detected or not enabled in the VJOY API. This VJOY will be disabled."
                        )

                # register in the native vjoy devices map
                native_vjoy_devices[vid] = device

            for vid in range(1, 17):  # list all possible vjoy devices index 1 up to 16
                is_connected, axis_count, button_count, hat_count = config_map[vid]

                hash_value = (axis_count, button_count, hat_count)
                hash_wheel_value = (axis_count + 1, button_count, hat_count)

                if verbose:
                    syslog.info(
                        f"Vjoy Interface: device index [{vid}] Hash: {hash_value} Hash wheel: {hash_wheel_value} Axis Count: {axis_count} Button count: {button_count} Hat count: {hat_count}  Connected: {is_connected}"
                    )

                if hash_value in vjoy_hash_list:
                    syslog.error("Fatal error: This device is not unique in terms of axis/button/hat counts.")
                    should_terminate = True

                if is_connected and hat_count > 0 and not vjoy.hat_configuration_valid(vid):
                    import sys

                    import gremlin.event_handler
                    import gremlin.ui.ui_common

                    error_string = f"VJoy id {vid:d}: Hats are set to discrete but have to be set as continuous."
                    syslog.error(error_string)
                    el = gremlin.event_handler.EventListener()
                    el.terminate()  # terminates and sends the relevant shutdown triggers
                    util.display_error(error_string)
                    sys.exit(1)

            # As we are ensured that no duplicate vJoy devices exist from
            # the previous step we can directly link the SDL and vJoy device
            if hash_value in vjoy_lookup:
                # found the vjoy interface index
                vjoy_lookup[hash_value].set_vjoy_id(vid)
                syslog.info(
                    f"\tVjoy id {vid}: {'connected' if is_connected else ' disconnected'} in vjoy interface"
                )
            elif hash_wheel_value in vjoy_wheel_lookup:
                vjoy_lookup[hash_value] = vjoy_wheel_lookup[hash_value]
                vjoy_lookup[hash_value].set_vjoy_id(vid)
                syslog.info(f"\tVjoy id {vid}: found in vjoy interface (as a wheel)")
            elif hash_value in virtual_devices:
                dev = virtual_devices[hash_value]
                vjoy_lookup[hash_value] = dev
                vjoy_lookup[hash_value].set_vjoy_id(vid)
            else:
                # not found
                hash_value = (axis_count, button_count, hat_count)
                hash_wheel_value = (axis_count + 1, button_count, hat_count)
                if verbose_detailed:
                    syslog.info(
                        f"vjoy id {vid:d}: {hash_value} vJoy device exists but DILL does not see it - check HIDHide config if enabled and process is whitelisted.  This device cannot be used as input.  This message is normal if the device is not configured in VJOY."
                    )

                dev = configured_vjoy_devices[vid]
                logical_count = 0
                for i in range(8):
                    axis_map = dinput.AxisMap()
                    axis_map.axis_index = i
                    dev.axismap_list.append(axis_map)
                    axis_name = axis_map.getName()
                    if not axis_name:
                        axis_name = f"({i + 1})"
                    else:
                        logical_count += 1
                    dev.axis_names[i] = axis_name
                    dev.axismap_list.append(axis_name)

                vjoy_lookup[hash_value] = dev
                _all_joystick_devices.append(dev)
                device_guid = gremlin.util.normalize_guid(dev.device_guid)
                _joystick_device_guid_map[device_guid] = dev
                if verbose_detailed:
                    syslog.info(f"Adding undetected VJOY device: [{vid}] {dev!s}")

            if should_terminate:
                # exit gracefully
                syslog.error(
                    "A fatal error was encountered during the detection and mapping of input devices - see the log for errors."
                )
                app = QtWidgets.QApplication.instance()
                if app:
                    gremlin.util.InvokeUiMethod(app.exit)
                sys.exit(1)
                return

            # Reset all devices so we don't hog the ones we aren't actually using
            vjoy_proxy.reset()

            # Construct special devices without a registry lock too. Their current
            # entries, plus Maestro updates that arrived during discovery, are merged
            # with this native snapshot only when publishing.
            registerSpecialDevices()
            try:
                signature = _device_list_signature(native_devices)
            except Exception:
                signature = None
            published = _publish_joystick_devices(discovered_devices, configured_vjoy_devices, native_vjoy_devices, signature)
            _log_output_map()
            syslog.info("Input device summary:")
            for device in published:
                syslog.info(f"\tDevice: {device!s}")
            syslog.info("Joystick input initialized")

            # Post UI work after releasing the registry used by input lookups.
            mgr = gremlin.ui.axis_calibration.CalibrationManager()
            gremlin.util.InvokeUiMethod(mgr.reload)

    finally:
        # turn on vjoy monitoring
        if config.vjoy_installed:
            vjm.start()
        # notify listeners that joystick initialization is complete
        el = gremlin.event_handler.EventListener()
        el.device_initialized.emit()

    return True


def _is_excluded_native_joystick(device: DeviceSummary) -> bool:
    """Identify native interfaces that GEX deliberately excludes as joysticks."""
    return (
        (device.vendor_id == 0x31E3 and device.axis_count == 0)
        or (device.vendor_id == 0x04D8 and device.product_id == 0xE6D6 and device.button_count == 35)
    )


def isDeviceValid(device: DeviceSummary) -> bool:
    """Checks if the given device is a valid DINPUT spec device"""
    if not device.is_special and device.device_type in (DeviceType.Joystick, DeviceType.VJoy, DeviceType.Maestro):
        # for joystick devices, ensure they meet the DINPUT spec
        # this will remove ghost devices reported by non standard drivers
        # a valid device will report as a joystick that meets the DINPUT specification and has at least one axis, button, or hat
        return (
            device.axis_count <= 8
            and device.button_count <= 128
            and device.hat_count <= 4
            and (device.axis_count >= 1 or device.button_count >= 1 or device.hat_count >= 1)
        )
    return True


def get_failover_from_name(name):
    # Matches 'gex-' followed by 10-16 or 1-9
    match = re.fullmatch(r"gex-(1[0-6]|[1-9])", name)
    if match:
        return int(match.group(1))
    return -1


def _update_joystick_device_maps():
    """updates all device maps from the master device map"""
    global \
        _all_joystick_devices, \
        _all_devices_map, \
        _vjoy_devices_map, \
        _disconnected_devices, \
        _maestro_devices_map, \
        _maestro_devices, \
        _joystick_devices, \
        _disconnected_devices_map, \
        _vjoy_devices, \
        _all_virtual_devices_map, \
        _all_vjoy_devices_map, \
        _maestro_failover_map

    with _device_registry_lock:
        _apply_maestro_service_devices()
        _all_joystick_devices = [
            dev
            for dev in _all_devices_map.values()
            if dev.device_type in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy)
        ]
        _all_joystick_devices.sort(key=lambda x: x.name.casefold())
        _joystick_device_guid_map.clear()
        _joystick_device_guid_map.update({dev.device_guid: dev for dev in _all_joystick_devices})

        _joystick_devices = [dev for dev in _all_joystick_devices if dev.enabled]  # all connected joystick devices
        # Only index properly matched VJOY ids (1..16). Unmatched DINPUT stubs stay
        # at vjoy_id=-1 and must not enter the runtime map (profile start would crash).
        _vjoy_devices_map = {
            dev.vjoy_id: dev
            for dev in _all_devices_map.values()
            if dev.device_type == DeviceType.VJoy and isinstance(dev.vjoy_id, int) and 1 <= dev.vjoy_id <= 16
        }
        _vjoy_devices = [dev for dev in _vjoy_devices_map.values()]
        _vjoy_devices.sort(key=lambda x: x.vjoy_id)
        _disconnected_devices_map = {dev.device_guid: dev for dev in _all_devices_map.values() if not dev.connected}
        _disconnected_devices = [dev for dev in _disconnected_devices_map.values()]
        _maestro_devices_map = {
            dev.virtual_id: _maestro_output_summary(dev)
            for dev in _all_devices_map.values()
            if dev.device_type == DeviceType.Maestro and dev.virtual_id >= 0
        }
        _maestro_devices = [dev for dev in _maestro_devices_map.values()]
        _maestro_devices.sort(key=lambda x: x.name.casefold())

        # populate the failover map based on the Maestro device names
        updateFailoverMap()

        _update_virtual_map()
        _output_targets.clear()  # device set changed - failover targets are resolved again


def _update_virtual_map():
    global _all_virtual_devices_map, _maestro_devices_map, _all_vjoy_devices_map
    with _device_registry_lock:
        _all_virtual_devices_map[DeviceType.VJoy] = _all_vjoy_devices_map
        _all_virtual_devices_map[DeviceType.Maestro] = _maestro_devices_map


def joystick_initialized():
    global _joystick_initialized
    return _joystick_initialized


MAX_VJOY_DEVICE = 16  # number of devices 1..16 supported by VJOY - this includes devices that may not be configured
MAX_VJOY_BUTTON = 128  # max number of buttons per VJOY device

KEEP_ALIVE_DELAY = 120  # keep alive pulse in second


@gremlin.singleton_decorator.SingletonDecorator
class VirtualDeviceUsageState:
    """holds axis and button usage data for virtual output devices"""

    class MappingData:
        def __init__(self, device_guid: dinput.GUID, input_type: InputType, vjoy_input_id: int, action_id):
            assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
            assert isinstance(input_type, InputType), "invalid input type"
            assert isinstance(vjoy_input_id, int), "invalid vjoy input ID"
            assert action_id is not None, "invalid action ID"
            self.device_guid = device_guid
            self.vjoy_input_type = input_type
            self.vjoy_input_id = vjoy_input_id
            self.device_name = None
            self.device_input_type = None
            self.device_input_id = None
            profile = gremlin.shared_state.current_profile
            action = profile.findAction(action_id)
            if action:
                input_item = action.get_input_item()
                self.device_guid = input_item.device_guid
                self.device_name = input_item.device_name
                self.device_input_type = input_item.device_type
                self.device_input_id = input_item.input_id

    def __init__(self, profile=None):
        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self.ensure_profile)
        el.config_option_changed.connect(self._handle_config_changed)

        """ tracks assigned VJOY functions """

        self.verbose = False
        self._handle_config_changed()  # verbose flag

        self._device_list = None
        self._profile = None
        self._load_list = []
        # self._button_usage = {}  # list of used buttons and by what action / input  index is the [vjoy_id][button_index] = true if used, false if not - tracks if the output button is used by the profile
        self._button_usage_map = {}  # list of used buttons [vjoy_id][button_index] = [action id, ...] - tracks how many actions in the profile are using the output button
        self._action_map = {}  # list of action ids to devices

        # holds the mapping by vjoy device, input and ID to a list of raw hardware defining the mapping
        self._action_map = {}

        # list of users buttons by vjoy device ID
        self._used_map = {}
        # list of unused buttons by vjoy device ID
        self._unused_map = {}

        self._active_device_guid = None  # guid of the hardware device
        self._active_device_name = None  # name of the hardware device
        self._active_device_input_type = 0  # type of selected hardware input (axis, button or hat)
        self._active_device_input_id = 0  # id of the function on the hardware device (button #, hat # or axis #)

        self._axis_invert_map = {}  # holds map of inverted axes for output [device_guid] -> bool
        self._axis_range_map = {}  # holds active axis range maps [device_guid] -> [min, max]

        if profile:
            profile = gremlin.shared_state.current_profile
            self.set_profile(profile)

        if not self._device_list:
            self._device_list = virtual_devices()

        # listen for active device changes
        el = gremlin.event_handler.EventListener()
        el.profile_device_changed.connect(self._profile_device_changed)
        el.action_deleted.connect(self._handle_action_deleted)
        el.profile_unloaded.connect(self._profile_changed)  # reset on profile change
        el.set_virtual_button_usage.connect(self._handle_set_virtual_button_usage)
        el.shutdown.connect(self._handle_shutdown)
        self.reset()

    def _handle_config_changed(self):
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_vjoy and config.verbose_mode_extra

    def registerAction(self, key):
        # assert key not in self._action_map, "action already registered"
        if key not in self._action_map:
            # key could already be registered in a paste situation
            self._action_map[key] = {}
        # syslog.info(f"Button State: register action [{key}]")

    def getRegisteredActions(self):
        return list(self._action_map.keys())

    def unregisterAction(self, key):
        """unregisters an action - this can be called multiple times for the same action"""
        if key in self._action_map:
            if self.verbose:
                syslog.info(f"Button State: unregister action [{key}]")
            del self._action_map[key]
            for device_type in self._button_usage_map:
                for virtual_id in self._button_usage_map[device_type]:
                    for button_id in self._button_usage_map[device_type][virtual_id]:
                        if key in self._button_usage_map[device_type][virtual_id][button_id]:
                            self._button_usage_map[device_type][virtual_id][button_id].remove(key)

    def _handle_shutdown(self):
        pass

    def _handle_set_virtual_button_usage(self, device_guid: dinput.GUID, button_id: int, state: bool, key):
        """handles request for button changes"""
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        assert isinstance(button_id, int), "invalid button ID"
        assert isinstance(state, bool), "invalid state"
        self.set_usage_state(device_guid, button_id, key, state)

    @QtCore.Slot(object, object, object)
    def _handle_action_deleted(self, action):
        """called when an action is deleted in the profile"""
        self.delete_action(action)
        self.unregisterAction(action.id)

    def _profile_changed(self):
        """new profile - clear data"""
        if self.verbose:
            syslog.info("Button State: profile changed")

        self.reset()
        self.ensure_device_maps(force_update=True)

    def reset(self):
        """resets the usage state"""
        if self.verbose:
            syslog.info("Button State: reset usage state")
        # self._button_usage.clear()
        self._button_usage_map.clear()
        self._axis_invert_map.clear()
        self._axis_range_map.clear()
        self._load_list.clear()

    @QtCore.Slot(object)
    def _profile_device_changed(self, event):
        self._active_device_guid = event.device_guid
        self._active_device_name = event.device_name
        self._active_device_input_type = event.device_input_type
        self._active_device_input_id = event.device_input_id

    def push_load_list(self, device_guid: dinput.GUID, input_type: InputType, input_id: int):
        """ensure data loaded by this profile is updated the first time through"""
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        assert isinstance(input_type, InputType), "invalid input type"
        assert isinstance(input_id, int), "invalid input ID"
        self._load_list.append((device_guid, input_type, input_id))

    def ensure_profile(self):
        if not self._profile or gremlin.shared_state.current_profile != self._profile:
            self.set_profile(gremlin.shared_state.current_profile)

    def ensure_valid(self, device_guid: dinput.GUID, input_id: int):
        """checks vjoy button mapping exists"""
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device GUID"
        assert device.is_virtual, "device is not virtual"
        device_type = device.device_type
        virtual_id = device.virtual_id

        if device_type not in self._button_usage_map:
            self._button_usage_map[device_type] = {}

        if virtual_id not in self._button_usage_map[device_type]:
            self._button_usage_map[device_type][virtual_id] = {}

        if input_id > 0:
            # record button usage map if not already in the map
            if input_id not in self._button_usage_map[device_type][virtual_id]:
                self._button_usage_map[device_type][virtual_id][input_id] = []

    def ensure_device_maps(self, force_update=False):
        """ensures the inversion maps are loaded"""
        devices = virtual_devices()
        if not devices:
            return
        if force_update:
            self._axis_invert_map = {}
            self._axis_range_map = {}
        if self._axis_invert_map is None:
            self._axis_invert_map = {}
        if self._axis_range_map is None:
            self._axis_range_map = {}
        if self._button_usage_map is None:
            self._button_usage_map = {}

        device: DeviceSummary
        for device in devices:
            assert device.is_virtual, "device is not virtual"
            virtual_id = device.virtual_id
            device_type = device.device_type

            if device_type not in self._axis_invert_map:
                self._axis_invert_map[device_type] = {}

            if device_type not in self._axis_range_map:
                self._axis_range_map[device_type] = {}

            if virtual_id not in self._axis_invert_map[device_type]:
                self._axis_invert_map[device_type][virtual_id] = {}

            if virtual_id not in self._axis_range_map[device_type]:
                self._axis_range_map[device_type][virtual_id] = {}

            for axis_id in range(1, device.axis_count + 1):
                self._axis_invert_map[device_type][virtual_id][axis_id] = False
                self._axis_range_map[device_type][virtual_id][axis_id] = [-1.0, 1.0]

            if device_type not in self._button_usage_map:
                self._button_usage_map[device_type] = {}

        for device in devices:
            assert device.is_virtual, "device is not virtual"
            device_type = device.device_type
            virtual_id = device.virtual_id
            self._button_usage_map[device_type] = {}
            self._button_usage_map[device_type][virtual_id] = {}

    def _ensure_maps(self, device_guid, input_id):
        """automatically registers new inputs if needed"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = gremlin.joystick_handling.getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        virtual_id = device.virtual_id

        if device_type not in self._axis_invert_map:
            self._axis_invert_map[device_type] = {}
        if virtual_id not in self._axis_invert_map[device_type]:
            self._axis_invert_map[device_type][virtual_id] = {}

        if device_type not in self._axis_range_map:
            self._axis_range_map[device_type] = {}
        if virtual_id not in self._axis_range_map[device_type]:
            self._axis_range_map[device_type][virtual_id] = {}

        if input_id not in self._axis_invert_map[device_type][virtual_id]:
            self._axis_invert_map[device_type][virtual_id][input_id] = False

        if device_type not in self._axis_range_map:
            self._axis_range_map[device_type] = {}
        if input_id not in self._axis_range_map[device_type][virtual_id]:
            self._axis_range_map[device_type][virtual_id][input_id] = [-1.0, 1.0]

        if device_type not in self._button_usage_map:
            self._button_usage_map[device_type] = {}

        if virtual_id not in self._button_usage_map[device_type]:
            self._button_usage_map[device_type][virtual_id] = {}

        if input_id not in self._button_usage_map[device_type][virtual_id]:
            self._button_usage_map[device_type][virtual_id][input_id] = []

    def set_inverted(self, device_guid, input_id, inverted):
        """sets the inversion flag for a given vjoy device"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        self._ensure_maps(device_guid, input_id)
        virtual_id = device.virtual_id
        invert_map = self._axis_invert_map.get(device_type)
        if invert_map is not None and virtual_id in invert_map:
            invert_map[virtual_id][input_id] = inverted

    def is_inverted(self, device_guid, input_id):
        """returns true if the specified device/axis is inverted"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        virtual_id = device.virtual_id
        if device_type in self._axis_invert_map:
            if virtual_id in self._axis_invert_map[device_type]:
                return self._axis_invert_map[device_type][virtual_id].get(input_id, False)
        return False

    def toggle_inverted(self, device_guid, input_id):
        """toggles inversion state of specified device/axis is inverted"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        virtual_id = device.virtual_id
        self._ensure_maps(device_guid, input_id)
        if device_type in self._axis_invert_map:
            if virtual_id in self._axis_invert_map[device_type]:
                if input_id in self._axis_invert_map[device_type][virtual_id]:
                    self._axis_invert_map[device_type][virtual_id][input_id] = not self._axis_invert_map[device_type][
                        virtual_id
                    ][input_id]
                    if self.verbose:
                        syslog.info(
                            f"Vjoy [{device.name}] Axis {input_id} inverted state: {self._axis_invert_map[device_type][virtual_id][input_id]}"
                        )
                    return

    def set_range(self, device_guid, input_id, min_range=-1.0, max_range=1.0):
        """sets the axis min/max range for the active range computation"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        if min_range > max_range:
            min_range, max_range = max_range, min_range
        self._ensure_maps(device_guid, input_id)  # make sure the maps are initialized before setting the range
        device = getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        virtual_id = device.virtual_id
        self._ensure_maps(device_guid, input_id)
        if device_type in self._axis_range_map:
            if virtual_id in self._axis_range_map[device_type]:
                if input_id in self._axis_range_map[device_type][virtual_id]:
                    self._axis_range_map[device_type][virtual_id][input_id] = [min_range, max_range]
                    return

    def get_range(self, device_guid, input_id):
        """gets the current range for an axis (min,max)"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        virtual_id = device.virtual_id
        self._ensure_maps(device_guid, input_id)
        if device_type in self._axis_range_map:
            if virtual_id in self._axis_range_map[device_type]:
                if input_id in self._axis_range_map[device_type][virtual_id]:
                    return self._axis_range_map[device_type][virtual_id][input_id]
        return [-1.0, 1.0]

    def set_profile(self, profile):
        """loads profile data and free input lists"""
        if profile != self._profile:
            if self.verbose:
                syslog.info(f"Button State: load new profile: {profile.name}")
            self._profile = profile
            # self._button_usage.clear()
            # self._button_usage_map.clear()  # blits state data on profile change
            # self._load_inputs()  # load mappings from the profile

    def map_input_type(self, input_type) -> str:
        if isinstance(input_type, InputType):
            if input_type in [
                InputType.JoystickButton,
                InputType.Keyboard,
                InputType.KeyboardLatched,
                InputType.OpenSoundControl,
                InputType.Midi,
            ]:
                name = "button"
            elif input_type == InputType.JoystickAxis:
                name = "axis"
            elif input_type == InputType.JoystickHat:
                name = "hat"
        else:
            name = input_type
        return name

    def get_count(self, device_guid, input_type):
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        assert isinstance(input_type, InputType), "invalid input type"
        self.ensure_profile()
        name = self.map_input_type(input_type)
        dev = next((d for d in self._device_list if d.vjoy_id == device_guid), None)
        if dev:
            if name == "axis":
                return dev.axis_count
            elif name == "button":
                return dev.button_count
            elif name == "hat":
                return dev.hat_count
        return 0

    def delete_action(self, action, emit=True):
        """updates the usage list if the action is removed from the profile"""
        import action_plugins
        from gremlin.types import VjoyAction

        emit_list = set()

        if isinstance(action, action_plugins.map_to_vjoy.VjoyRemap):
            if not VjoyAction.is_button_action(action.action_mode):
                # not a button mapping
                return
            device = action.virtual_device
            target_device_guid = device.device_guid
            device_type = device.device_type
            virtual_id = device.virtual_id
            input_id = action.vjoy_input_id

        elif isinstance(action, action_plugins.remap.Remap):
            if action.input_type != InputType.JoystickButton:
                # not a button
                return
            virtual_id = action.vjoy_id
            target_device_guid = getVjoyDeviceGuid(virtual_id)
            device = gremlin.joystick_handling.getDevice(target_device_guid)
            device_type = DeviceType.VJoy
            input_id = action.vjoy_button_id
        else:
            # not a virtual button remap action
            return

        key = action.id

        if key in self._action_map:
            del self._action_map[key]

        if device_type in self._button_usage_map:
            if virtual_id in self._button_usage_map[device_type]:
                if input_id in self._button_usage_map[device_type][virtual_id]:
                    usage_map = self._button_usage_map[device_type][virtual_id][input_id]
                    if key in usage_map:
                        current_state = self.get_usage_state(target_device_guid, input_id)
                        usage_map.remove(key)

                        new_state = len(usage_map) > 0
                        if current_state != new_state:
                            emit_list.add(target_device_guid)

        if emit:
            self._fire_usage_changed(device_type, virtual_id)

    def _set_usage_state(self, device_type: DeviceType, virtual_id: int, button_id: int, key, used: bool, emit=True):
        """sets the usage state for a virtual button"""

        # Paste / GUID regen can briefly leave an action unregistered; auto-heal
        # instead of asserting so the mapping UI can finish building.
        if key not in self._action_map:
            self.registerAction(key)

        current_state = self._get_usage_state(device_type, virtual_id, button_id)

        if device_type not in self._button_usage_map:
            self._button_usage_map[device_type] = {}
        if virtual_id not in self._button_usage_map[device_type]:
            self._button_usage_map[device_type][virtual_id] = {}
        if button_id not in self._button_usage_map[device_type][virtual_id]:
            self._button_usage_map[device_type][virtual_id][button_id] = set()

        if device_type not in self._action_map[key]:
            self._action_map[key][device_type] = {}
        if virtual_id not in self._action_map[key][device_type]:
            self._action_map[key][device_type][virtual_id] = None

        # config = gremlin.config.Configuration()

        # verbose = True

        usage_map = self._button_usage_map[device_type][virtual_id][button_id]
        if used:
            if isinstance(usage_map, set):
                usage_map.add(key)
            else:
                usage_map.append(key)
            self._action_map[key][device_type][virtual_id] = button_id
        else:
            # remove the data
            if key in usage_map:
                usage_map.remove(key)
            self._action_map[key][device_type][virtual_id] = None

        is_mapped = len(usage_map) > 0

        changed = current_state != is_mapped

        if self.verbose:
            syslog.info(
                f"Button State: Set usage state: [{device_type.name}] id [{virtual_id}] button [{button_id}] used: [{used}] mapped: [{is_mapped}] key: [{key}]"
            )

        if __debug__:
            # Snapshot keys â€” profile load / joystick re-init can mutate _action_map
            # while the UI is still iterating it.
            action_keys = list(self._action_map.keys())
            used_list = list(
                {
                    self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None)
                    for key in action_keys
                    if self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None) is not None
                }
            )
            if used:
                assert button_id in used_list, f"button {button_id} should be in used list {used_list}"
            else:
                action_list = [
                    k
                    for k in action_keys
                    if self._action_map.get(k, {}).get(device_type, {}).get(virtual_id, None) == button_id
                ]
                assert key not in action_list, f"action {key} should not be in action list {action_list}"

        if changed and emit and not gremlin.shared_state.is_running:
            # update UI with changed button usage data
            el = gremlin.event_handler.EventListener()
            el.button_usage_changed.emit(device_type, virtual_id)
            el.vjoy_button_usage.emit(device_type, virtual_id, button_id, used)
            el.input_used_changed.emit(device_type, virtual_id, InputType.JoystickButton, button_id, used)

    def _fire_usage_changed(self, device_type, virtual_id):
        if not gremlin.shared_state.is_running:
            # update UI with changed button usage data
            el = gremlin.event_handler.EventListener()
            el.button_usage_changed.emit(device_type, virtual_id)

    def set_usage_state(self, device_guid, button_id: int, key, used: bool, emit=True):
        """sets the usage state for a virtual button"""
        if device_guid is None or not isinstance(device_guid, dinput.GUID):
            return
        self.ensure_device_maps()
        device = gremlin.joystick_handling.getDevice(device_guid)
        if device is None:
            # Profile reload can race joystick re-init; skip rather than abort the load.
            syslog.warning(
                f"VJOY usage: device not found for GUID [{device_guid}] (button {button_id}) â€” skipping usage update"
            )
            return
        if not device.is_virtual:
            syslog.warning(f"VJOY usage: device [{device.name}] is not virtual â€” skipping usage update")
            return
        device_type = device.device_type
        virtual_id = device.virtual_id
        self._set_usage_state(device_type, virtual_id, button_id, key, used, emit)

    def _get_usage_state(self, device_type: DeviceType, virtual_id: int, button_id: int) -> bool:
        """gets the usage state for a virtual button"""
        if device_type in self._button_usage_map and virtual_id in self._button_usage_map[device_type]:
            return len(self._button_usage_map[device_type][virtual_id].get(button_id, set())) > 0
        return False

    def get_usage_state(self, device_guid, button_id: int) -> bool:
        """gets the usage state for a virtual button"""
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        self.ensure_device_maps()
        self.ensure_valid(
            device_guid, button_id
        )  # create entry if needed - this can happen if the input vjoy device doesn't exist
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device GUID"
        assert device.is_virtual, "device is not virtual"
        device_type = device.device_type
        virtual_id = device.virtual_id
        return self._get_usage_state(device_type, virtual_id, button_id)

    def get_usage_list(self, device_guid, button_id: int) -> list:
        """gets the action ids for what outputs a virtual button in the profile"""
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        self.ensure_device_maps()
        self.ensure_valid(
            device_guid, button_id
        )  # create entry if needed - this can happen if the input vjoy device doesn't exist
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device GUID"
        assert device.is_virtual, "device is not virtual"
        device_type = device.device_type
        virtual_id = device.virtual_id
        return list(self._button_usage_map[device_type][virtual_id].get(button_id, set()))

    def _used_button_list(self, device_type: DeviceType, virtual_id: int) -> list[int]:
        """gets the list of used buttons for a given device"""
        # Snapshot keys first: map_to_vjoy populates its grid on the UI thread while
        # profile load / device refresh can still register/unregister actions.
        action_keys = list(self._action_map.keys())
        used_list = list(
            set(
                self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None)
                for key in action_keys
                if self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None) is not None
            )
        )

        # used_list = [button_id for button_id, map_list in self._button_usage_map.get(device_type, {}).get(virtual_id, {}).items()  if map_list]
        return used_list

    def used_button_list(self, device_guid) -> list[int]:
        """gets the list of used buttons for a given output device"""
        if not isinstance(device_guid, dinput.GUID):
            return []
        device: DeviceSummary = getDevice(device_guid)
        if device is None or not device.is_virtual:
            # Device map can be mid-rebuild during profile load / joystick refresh.
            return []
        return self._used_button_list(device.device_type, device.virtual_id)

    @property
    def device_list(self):
        return self._device_list

    def input_count(self, device_id, input_type):
        """returns the number of input counts for a given vjoy ID and type (axis, button or hat)

        :device_id:
            device ID, first VJOY is index 1

        :input_type: InputType enum


        """
        return self.get_count(device_id, input_type)

    def _load_inputs(self):
        """Returns a list of unused vjoy inputs for the given profile.

        :return dictionary of unused inputs for each input type
        """
        import action_plugins
        import gremlin.input_devices

        profile = gremlin.shared_state.current_profile
        if not profile:
            return  # nothing to load yet

        devices = profile.devices
        self.ensure_device_maps()  # ensure the vjoy devices data objects are populated

        target_deviceguid_list = set()

        # Create a list of all used remap actions
        for device_guid in devices:
            device = gremlin.joystick_handling.getDevice(device_guid)
            if not device or device.disabled:
                continue

            for mode_name in devices[device_guid].modes:
                mode_object = devices[device_guid].modes[mode_name]
                for input_type in mode_object.config:
                    for input_item in mode_object.config[input_type].values():
                        if not input_item.containers:
                            continue
                        for container in input_item.containers:
                            for action_set in container.action_sets:
                                if action_set:
                                    for action in action_set:
                                        if isinstance(action, action_plugins.remap.Remap):
                                            # legacy remap only knows about vjoy id
                                            vjoy_id = action.vjoy_id
                                            target_device_guid = getVjoyDeviceGuid(vjoy_id)
                                            target_device = gremlin.joystick_handling.getDevice(target_device_guid)
                                        elif isinstance(action, action_plugins.map_to_vjoy.VjoyRemap):
                                            # new remap action
                                            target_device = action.virtual_device
                                            target_device_guid = target_device.device_guid
                                        else:
                                            continue
                                        if hasattr(action, "action_mode"):
                                            action_mode = action.action_mode  # vjoy remap
                                            trigger = gremlin.types.VjoyAction.is_button_action(action_mode)
                                            button_id = action.vjoy_button_id
                                        else:
                                            # legacy remap
                                            trigger = action.input_type == InputType.JoystickButton
                                            button_id = action.vjoy_input_id

                                        if trigger:
                                            key = action.key
                                            self.set_usage_state(target_device_guid, button_id, key, True, emit=False)
                                            target_deviceguid_list.add(target_device_guid)
        if self.verbose:
            syslog.info("Button usage list for profile:")
            for device_guid in target_deviceguid_list:
                device = gremlin.joystick_handling.getDevice(device_guid)
                used_list = self.used_button_list(device_guid)
                syslog.info(f"Profile load: Used button list for device {device.name}: {used_list}")

    def get_action_map(self, device_guid, input_type, input_id):
        """gets what's mapped to a vjoy device by input type and input id"""
        action_map = []
        for action_data in self._button_usage_map[device_guid][input_id]:
            data = self.MappingData(action_data.device_guid, input_type, input_id, action_data)
            action_map.append(data)

        return action_map


@gremlin.singleton_decorator.SingletonDecorator
class VjoyStart:
    """helper class to handle profile startup data for vjoy output"""

    def __init__(self):

        self._axis_data = {}  # map of start profile values indexed by [vjoyid][axis] = float
        self._button_data = {}  # map of start profile buttons indexed by [vjoyid][axis] = bool
        self._connected = (
            False  # tracks event hook (we don't hook on init because of possible python import issue and load order)
        )
        self._device: DeviceSummary = None  # vjoy device info

    def _ensure_device(self, device_id):
        import gremlin.event_handler

        self._device = getDeviceFromVjoyId(device_id)
        if self._device is None:
            return
        self._vjoy_id = parse_virtual_device_key(device_id)
        if not self._connected:
            el = gremlin.event_handler.EventListener()
            el.profile_started.connect(self.apply)
            self._connected = True

    def setStartValue(self, device_id, id: int, value: float):
        """registers an axis start value"""

        self._ensure_device(device_id)
        if not self._device:
            return

        vjoy_id = self._vjoy_id
        if vjoy_id not in self._axis_data:
            self._axis_data[vjoy_id] = {}
        self._axis_data[vjoy_id][id] = value

    def setStartState(self, device_id, id: int, state: bool):
        """registers a button start value"""

        self._ensure_device(device_id)
        if not self._device:
            return

        vjoy_id = self._vjoy_id
        if vjoy_id not in self._button_data:
            self._button_data[vjoy_id] = {}
        self._button_data[vjoy_id][id] = state

    def reset(self):
        """resets the start data"""
        self.clear()

    def clear(self):
        """resets the start data"""
        self._axis_data = {}
        self._button_data = {}

    def apply(self):
        import gremlin.remote

        remote_client = gremlin.remote.remote_client
        for key, axes in self._axis_data.items():
            device = getDeviceFromVjoyId(key)
            for axis_id, value in axes.items():
                if value is not None:
                    set_axis(key, axis_id, value)
                    if device is not None:
                        remote_client.send_axis(key if isinstance(key, int) else device.virtual_id, axis_id, value)
        for key, buttons in self._button_data.items():
            device = getDeviceFromVjoyId(key)
            for button_id, state in buttons.items():
                state = bool(state)
                set_button(key, button_id, state)
                if device is not None:
                    remote_client.send_button(key if isinstance(key, int) else device.virtual_id, button_id, state)


# instance
_vjoy_start = VjoyStart()
