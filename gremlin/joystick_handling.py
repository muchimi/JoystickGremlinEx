# -*- coding: utf-8; -*-

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


import logging
import threading

import dinput
import time


import gremlin.config
import gremlin.types

import gremlin.shared_state
import gremlin.types
from gremlin.types import DeviceType, DeviceCategory
import gremlin.singleton_decorator
import gremlin.util
import gremlin.types


from . import error, util
from vjoy import vjoy

# from dinput import DeviceSummary
from gremlin.input_types import InputType
import gremlin.config

from PySide6 import QtWidgets, QtCore


# List of all joystick devices
_joystick_devices = []  # detected devices only (including virtual devices that exist all the time like OSC or Modes)
_all_joystick_devices = []  # [DeviceSummary] of all devices, virtual, connected and disconnected
_vjoy_devices_map = {}  #  connected vjoy devices (int) -> device
_maestro_devices_map = {}  # connected maestro devices (int) -> device
_all_vjoy_devices_map = {}  # all vjoy devices (int) -> device
_all_maestro_devices_map = {}  # all maestro devices (int) -> device
_all_virtual_devices_map = {
    DeviceType.VJoy: {},
    DeviceType.Maestro: {},
}  # all virtual input devices (vjoy and maestro) [device_type:DeviceType][index:int] -> device : dinput.DeviceSummary

_joystick_device_guid_map = {}  # map of DeviceSummary objects keyed by dInput GUID (special devices)
_special_devices_map = {}  # map of special devices dinput.GUID -> device
_special_devices = []  # list of special devices
_config_devices_map = {}  # map of DeviceSummary objects keyed by dInput GUID (config devices)
_config_devices = []  # list of config devices (setings, plugins)
_all_devices_map = gremlin.util.TriggerDict()  # all detected devices [dinput.GUID] -> device


def getAllDevicesMap():
    """gets a map of all devices"""
    global _all_devices_map
    return _all_devices_map


def _handle_change(data, key, old_value, value):
    assert isinstance(key, dinput.GUID)


_all_devices_map.addCallback(_handle_change)


# Joystick initialization lock
_joystick_init_lock = threading.Lock()

# joystick linear axis names


class AxisNames:
    joystick_linear_axis_names = ["X", "Y", "Z", "S1", "S2", "RX", "RY", "RZ"]


# initialized flag
_joystick_initialized = False

# invalid device GUID - used when a GUID is needed but could not be derived
_invalid_device_guid = "f765ae4c4dac40cbabefe9f6187d4689"

syslog = logging.getLogger("system")


class VJoyProxy:
    """Manages the usage of vJoy and allows shared access all callbacks."""

    vjoy_devices = {}

    def __getitem__(self, vid):
        """Returns the requested vJoy instance.

        :param key id of the vjoy device
        :return the corresponding vjoy device
        """
        # device IDs are 1 min to 16 max
        assert vid > 0 and vid < 17, f"Invalid VJOY device ID provided: {vid}"
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
        devices = list(VJoyProxy.vjoy_devices.values())
        for device in devices:
            device.invalidate()
        VJoyProxy.vjoy_devices = {}


def joystick_devices() -> list[dinput.DeviceSummary]:
    """Returns the list of CONNECTED physical joysticks"""
    return _joystick_devices


def all_joystick_devices():
    """Returns the list of CONNECTED AND DISCONNECTED  devices - iterator"""
    global _all_devices_map
    return _all_devices_map.values()


def all_vjoy_devices() -> list[dinput.DeviceSummary]:
    """gets connected vjoy devices"""
    return list(_vjoy_devices_map.values())


def all_maestro_devices() -> list[dinput.DeviceSummary]:
    """gets connected Maestro devices"""
    return list(_maestro_devices_map.values())


def axis_input_devices() -> list[dinput.DeviceSummary]:
    """returns the list of devices that has axes"""
    devices = [dev for dev in _joystick_devices if dev.axis_count]
    return devices


def button_input_devices() -> list[dinput.DeviceSummary]:
    """returns the list of devices that have buttons"""
    devices = [dev for dev in _joystick_devices if dev.button_count]
    return devices


def hat_input_devices() -> list[dinput.DeviceSummary]:
    """returns the list of devices that define hats"""
    devices = [dev for dev in _joystick_devices if dev.hat_count]
    return devices


def filtered_input_devices(input_type_list=[InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat], virtual_only=False):
    """gets a list of devices filtered by axis, button or hat"""

    def filter_func(dev: dinput.DeviceSummary):
        if virtual_only and not dev.is_virtual:
            return False
        for input_type in input_type_list:
            match input_type:
                case InputType.JoystickAxis:
                    return dev.axis_count > 0
                case InputType.JoystickButton:
                    return dev.button_count > 0
                case InputType.JoystickHat:
                    return dev.hat_count > 0
            return False

    devices = [dev for dev in _joystick_devices if filter_func(dev)]
    return devices


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
    """true if the vjoy device is connected"""
    global _vjoy_devices_map
    return vjoy_id in _vjoy_devices_map


def is_vjoy_guid_connected(device_guid) -> bool:
    vjoy_id = vjoy_id_from_guid(device_guid, None)
    if vjoy_id is not None:
        return is_vjoy_connected(vjoy_id)
    return False


def vjoy_devices(connected_only=True):  # -> list[DeviceSummary]:
    """Returns the list of vJoy devices.

    :param connected_only: if set, filters VJOY devices that are detected only, if not, returns all 16 devices
    :return list of [DeviceSummary] holding the device configuration for every vjoy device
    """
    global _vjoy_devices_map, _all_vjoy_devices_map
    if connected_only:
        device_list = list(_vjoy_devices_map.values())
    else:
        device_list = list(_all_vjoy_devices_map.values())

    return device_list


def maestro_devices(connected_only=True) -> list:
    """Returns the list of Maestro devices.

    :param connected_only: if set, filters Maestro devices that are detected only, if not, returns all devices
    :return list of [DeviceSummary] holding the device configuration for every Maestro device
    """
    global _maestro_devices_map, _all_maestro_devices_map
    if connected_only:
        device_list = list(_maestro_devices_map.values())
    else:
        device_list = list(_all_maestro_devices_map.values())

    return device_list


def virtual_devices(connected_only=True) -> list:
    """gets the list of all virtual devices with a connection filter"""
    return vjoy_devices(connected_only=connected_only) + maestro_devices(connected_only=connected_only)


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
    import gremlin.ui.osc_device
    import gremlin.config

    verbose = gremlin.config.Configuration().verbose_mode_curve

    device = getDevice(device_guid)
    if not device:
        if verbose:
            syslog.warning(f"APPLY CURVE: device not found: id [{device_guid}]")
        return None

    if not device.is_special:
        guid = device.device_guid
        eh = gremlin.event_handler.EventListener()
        value = dinput.DILL.get_axis(guid, axis_id)
        curved = eh.apply_transforms(guid, axis_id, value)
        if verbose:
            syslog.info(f"APPLY CURVE: {device.name} axis: [{axis_id}] input: {value:0.3f} curved: {curved:0.3f}")
        return curved

    else:
        if device.device_type == DeviceType.Osc and isinstance(axis_id, gremlin.ui.osc_device.OscInputItem) and axis_id.is_axis:
            osc = gremlin.ui.osc_device.InputOscClient()
            osc.start()
            data = osc.getData(axis_id.message)  # gets data arguments or None if no data
            if data is None:
                data = 0  # default is centeredv
            return data

    return None


def get_device(device_guid: int | str | dinput.GUID, show_error=True) -> dinput.DeviceSummary:
    """gets the device for the given ID - issues error message if not found"""
    return getDevice(device_guid, show_error)


def get_axis(device_guid: str | dinput.GUID | int, input_id: int, normalized=True):
    """gets the value of the specified axis
    :param device_guid: device guid
    :param input_id: axis index (1 based), non linear
    :param: normalized  - if set - normalizes to -1.0 +1.0 floating point

    """
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    dev: dinput.DeviceSummary = get_device(device_guid)
    if dev and dev.axis_count:
        assert input_id in dev.axis_id_map, f"invalid axis index [{input_id}] for device {dev.name}"
        value = dinput.DILL.get_axis(dev.device_guid, input_id)
        if normalized:
            value = gremlin.util.scale_to_range(value, source_min=-32767, source_max=32767, target_min=-1, target_max=1)
        return value

    return 0.0


def get_hat(device_guid : str | dinput.GUID | int, index) -> int:
    """gets the current hat value
    :param device_guid: device guid or vjoy device ID (integer)
    :param index: hat index 1 to 4
    :return: hat value

    """
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    device: dinput.DeviceSummary = get_device(device_guid)
    if device and device.hat_count:
        return device.get_hat(index)
    return -1  # center


def get_hat_position(device_guid : str | dinput.GUID | int, input_id : int) -> tuple:
    """gets the hat position as a position tuple
    :param device_guid: device guid or vjoy device ID (integer)
    :param input_id: hat index 1 to 4
    :return: hat position tuple
    """

    direction = get_hat(device_guid, input_id)
    if direction in vjoy.Hat.to_continuous_position:
        return vjoy.Hat.to_continuous_position[direction]
    return (0, 0)  # centered


def get_button(device_guid : str | dinput.GUID | int, input_id : int) -> bool:
    """gets the button pressed state if the button and device exists - defaults to FALSE if not found"""
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    device: dinput.DeviceSummary = get_device(device_guid)
    if __debug__:
        if device and device.device_type in (DeviceType.VJoy, DeviceType.Maestro, DeviceType.Joystick):
            assert input_id > 0 and input_id <= device.button_count, f"Invalid button index for vjoy device [{device.name}] [{input_id}]"
    if device and input_id:
        if device.button_count:
            if device.is_virtual and device.vjoy_id:
                # query the vjoy interface rather than dinput
                button = VJoyProxy()[device.vjoy_id].button(input_id)
                if button:
                    return button.is_pressed
                else:
                    syslog.warning(f"GetButton(): invalid vjoy [{device.vjoy_id}] button [{input_id}] not found")
                # invalid button
                return False
            # physical device
            return device.get_button(input_id)
        else:
            if device.device_type == DeviceType.Osc:
                if hasattr(input_id, "message"):
                    # OSC device
                    import gremlin.ui.osc_device

                    osc = gremlin.ui.osc_device.InputOscClient()
                    osc.start()  # ensure started
                    data = osc.getData(input_id.message)  # gets data arguments or None if no data
                    if data:
                        return data
                return False  # not received, assume not set

    else:
        syslog.error(f"JOYSTICK: unable to get button state for device for id [{device_guid}] index [{input_id}]")
    return False


def set_button(device_guid : str | dinput.GUID | int, index: int, is_pressed: bool, update_remote: bool = False):
    """sets a vjoy device button if the index and guid exists

    :param guid: vjoy device ID or device GUID
    :param index: button id
    :param is_pressed: state of the button to set
    :param update_remote: if enabled, and remote control is enabled, also updates the remote client

    """
    import gremlin.event_handler
    import gremlin.remote

    sd = gremlin.event_handler.JoystickState()
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    device = get_device(device_guid)
    if not device:
        syslog.error(f"VJOY SET BUTTON: Don't know device [{device_guid}]")
        return

    if not device.is_virtual and sd.outputIgnored(device_guid):
        # output ignored
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            device = getDevice(device_guid)
            syslog.info(f"VJOY SET BUTTON: {device.name} output ignored [{index}] pressed: {is_pressed}")
        return

    # local input
    vjoy_id = device.vjoy_id
    if 0 < index <= device.button_count:
        proxy = gremlin.joystick_handling.VJoyProxy()
        proxy[vjoy_id].button(index).is_pressed = is_pressed

        if update_remote:
            (_, is_remote) = gremlin.remote.remote_control.state
            if is_remote:
                remote_client = gremlin.remote.remote_client
                remote_client.send_button(vjoy_id, index, is_pressed)


def set_axis(device_guid, index: int, value: float, update_remote: bool = False):
    """sets a vjoy axis"""
    import gremlin.event_handler
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    sd = gremlin.event_handler.JoystickState()
    device = get_device(device_guid)
    if not device:
        syslog.error(f"VJOY SET AXIS: Don't know device [{device_guid}]")
        return
    if not device.is_virtual and sd.outputIgnored(device_guid):
        # output ignored
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            syslog.info(f"VJOY SET AXIS: {device.name} output ignored [{index}] value: {value: 0.3f}")
        return

    if device and device.is_virtual:
        vjoy_id = device.vjoy_id
        if 0 < index <= device.axis_count:
            proxy = gremlin.joystick_handling.VJoyProxy()
            proxy[vjoy_id].axis(index).value = value

            if update_remote:
                (_, is_remote) = gremlin.remote.remote_control.state
                if is_remote:
                    remote_client = gremlin.remote.remote_client
                    remote_client.send_axis(vjoy_id, index, value)


def set_hat(device_guid : str | dinput.GUID | int, index: int, direction: tuple):
    """sets the device hat"""
    if isinstance(device_guid, int):
        # convert to guid from vjoy ID
        device_guid = getVjoyDeviceGuid(device_guid)
    device = get_device(device_guid)
    if device and device.is_virtual:
        vjoy_id = device.vjoy_id
        if 0 < index < device.hat_count:
            proxy = gremlin.joystick_handling.VJoyProxy()
            proxy[vjoy_id].hat(index).direction = direction


def physical_devices():
    """Returns the list of physical devices.

    :return list of physical devices
    """
    return [dev for dev in _joystick_devices if dev.device_type == gremlin.types.DeviceType.Joystick and not dev.is_virtual]


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
    for dev in vjoy_devices():
        if InputType.JoystickAxis in valid_types and dev.axis_count > 0:
            return {"device_id": dev.vjoy_id, "input_type": InputType.JoystickAxis, "input_id": dev.axismap_list[0].axis_index}
        elif InputType.JoystickButton in valid_types and dev.button_count > 0:
            return {"device_id": dev.vjoy_id, "input_type": InputType.JoystickButton, "input_id": 1}
        elif InputType.JoystickHat in valid_types and dev.hat_count > 0:
            return {"device_id": dev.vjoy_id, "input_type": InputType.JoystickHat, "input_id": 1}
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
    if isinstance(guid, int):
        # already a vjoy id = make sure it's defined
        for dev in _all_vjoy_devices_map.values():
            if dev.vjoy_id == guid:
                return guid  # valid
        return not_found_id

    if isinstance(guid, str):
        guid = util.parse_guid(guid)  # convert to dinput GUID

    for dev in _all_vjoy_devices_map.values():
        if gremlin.util.compare_guid(dev.device_guid, guid):
            return dev.vjoy_id

    syslog.error(f"Could not find vJoy matching guid {str(guid)}")
    return not_found_id


def vjoy_guid_from_id(vid: int):
    """gets the vjoy GUID from a vjoy integer id"""
    for dev in vjoy_devices():
        if dev.vjoy_id == vid:
            return dev.device_guid
    return None


def registerSpecialDevice(dev):
    """adds a special device to the tracking list"""
    global _special_devices_map, _all_devices_map, _special_devices
    # device_guid = gremlin.util.normalize_guid(dev.device_guid)
    _all_devices_map[dev.device_guid] = dev
    _special_devices_map[dev.device_guid] = dev
    _special_devices.append(dev)

    syslog.info(f"\tid: [{dev.device_id}] type: [{dev.device_type.name}] name: [{dev.name}]")


def registerConfigDevice(dev):
    """adds a special device to the tracking list"""
    global _config_devices_map, _all_devices_map, _config_devices
    # device_guid = gremlin.util.normalize_guid(dev.device_guid)
    _all_devices_map[dev.device_guid] = dev
    _config_devices_map[dev.device_guid] = dev
    _config_devices.append(dev)
    syslog.info(f"\tid: [{dev.device_id}] type: [{dev.device_type.name}] name: [{dev.name}]")


def removeDevice(dev: dinput.DeviceSummary):
    """removes a device from the tracking list"""
    global _all_joystick_devices, _vjoy_devices_map, _joystick_devices, _all_devices_map
    device_guid = dev.device_guid
    device_guid = gremlin.util.normalize_guid(dev.device_guid)
    if device_guid in _joystick_device_guid_map:
        del _joystick_device_guid_map[device_guid]
        _all_joystick_devices = [d for d in _all_joystick_devices if d.device_guid != device_guid]
        if dev.device_type == DeviceType.VJoy:
            _vjoy_devices_map = {d.vjoy_id: d for d in _vjoy_devices_map if d.device_guid != device_guid}

        _joystick_devices = [d for d in _joystick_devices if d.device_guid != device_guid]


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
    return list(_all_devices_map.keys())


def getKnownDevicesGuids():
    """gets a list of known device GUIDs (iterator)"""
    global _all_devices_map
    return _all_devices_map.keys()


def getDevices() -> list[dinput.DeviceSummary]:
    """gets a list of known devices, physical and virtual (iterator)"""
    global _all_devices_map
    return _all_devices_map.values()


def getValidJoysticksDevices() -> list[dinput.DeviceSummary]:
    """gets a list of enabled joystick type devices"""
    global _all_joystick_devices
    return [dev for dev in _all_joystick_devices.values() if not dev.disabled and dev.device_type == DeviceType.Joystick]


def getValidJoystickDevicesMap() -> dict[dinput.GUID, dinput.DeviceSummary]:
    """gets a map of valid joystick device keyed by device guid"""
    global _joystick_device_guid_map
    return {dev.device_guid: dev for dev in _joystick_device_guid_map.values() if not dev.disabled and dev.device_type == DeviceType.Joystick}


def getPhysicalDevices() -> list[dinput.DeviceSummary]:
    """gets physical joystick devices"""
    global _joystick_device_guid_map
    return [dev for dev in _joystick_device_guid_map.values() if dev.device_type == DeviceType.Joystick and not dev.is_virtual]


def getDevice(device_guid: int | str | dinput.GUID, show_error=False) -> dinput.DeviceSummary:
    """gets the device for the given ID - issues error message if not found"""
    global _all_devices_map
    if device_guid:
        if not isinstance(device_guid, dinput.GUID):
            device_guid = gremlin.util.to_guid(device_guid)  # ensure a dinput.GUID
        if device_guid in _all_devices_map:
            return _all_devices_map[device_guid]
    return None


def getDeviceName(device_guid: int | str | dinput.GUID):
    """gets the device name"""
    device = getDevice(device_guid)
    if device:
        return device.name
    return f"unknown: {str(device_guid)}"


def getVjoyDeviceGuid(vid : int):
    """gets the vjoy device by the given vjoy id"""
    assert isinstance(vid, int), f"Invalid vjoy id [{vid}]"
    dev = next((dev for dev in vjoy_devices() if dev.vjoy_id == vid), None)
    if dev:
        return dev.device_guid

    refresh_devices()  # do a device reload if the GUID is not found
    dev = next((dev for dev in vjoy_devices() if dev.vjoy_id == vid), None)
    if dev:
        return dev.device_guid

    return None  # not found

def getVjoyDeviceGuidStr(vid : int):
    """gets the vjoy device by the given vjoy id as a string"""
    assert isinstance(vid, int), f"Invalid vjoy id [{vid}]"
    guid = getVjoyDeviceGuid(vid)
    if guid:
        return str(guid)
    return None  # not found


def getVjoyDeviceMap() -> dict:
    """gets a map of vjoy devices keyed by the vjoy id, holds a DeviceSummary"""
    return dinput.DILL.getVjoyDeviceMap()


def getMaestroDeviceMap() -> dict:
    """gets a map of maestro devices keyed by the maestro id, holds a DeviceSummary"""
    return dinput.DILL.getMaestroDeviceMap()


def vjoy_info_from_vjoy_id(vjoy_id: int, connected_only=True):  # -> DeviceSummary:
    """gets physical device info for a vjoy device

    :param vjoy_id: id of vjoy device 1 to 16
    :param connected_only: true to filter by connected vjoys only
    """

    global _all_vjoy_devices_map, _vjoy_devices_map
    if connected_only:
        if vjoy_id in _vjoy_devices_map:
            return _vjoy_devices_map[vjoy_id]
        # refresh devices if not found to make sure the device didn't shou up
        refresh_devices()
        if vjoy_id in _vjoy_devices_map:
            return _vjoy_devices_map[vjoy_id]
        return None

    # include disconnected
    if vjoy_id in _all_vjoy_devices_map:
        return _all_vjoy_devices_map[vjoy_id]
    # not found - ask for a device update
    refresh_devices()
    if vjoy_id in _all_vjoy_devices_map:
        return _all_vjoy_devices_map[vjoy_id]
    return None


def maestro_info_from_index(mid_id: int, connected_only=True):
    """gets physical device info for a maestro device

    :param mid_id: id of maestro device 1 to N
    :param connected_only: true to filter by connected maestros only
    """

    global _all_maestro_devices_map, _maestro_devices_map
    if connected_only:
        if mid_id in _maestro_devices_map:
            return _maestro_devices_map[mid_id]
        # refresh devices if not found to make sure the device didn't show up
        refresh_devices()
        if mid_id in _maestro_devices_map:
            return _maestro_devices_map[mid_id]
        return None

    # include disconnected
    if mid_id in _all_maestro_devices_map:
        return _all_maestro_devices_map[mid_id]
    # not found - ask for a device update
    refresh_devices()
    if mid_id in _all_maestro_devices_map:
        return _all_maestro_devices_map[mid_id]
    return None


def vjoy_device_map() -> dict[int, dinput.DeviceSummary]:
    """returns all vjoy devices indexed by vjoy_id -> device"""
    global _all_vjoy_devices_map
    return _all_vjoy_devices_map.copy()


def maestro_device_map() -> dict[int, dinput.DeviceSummary]:
    """returns all maestro devices indexed by maestro_id -> device"""
    global _all_maestro_devices_map
    return _all_maestro_devices_map.copy()


def virtual_device_map() -> dict[DeviceType, dict[int, dinput.DeviceSummary]]:
    """returns all virtual input devices indexed by device_type:DeviceType, contains [virtual_id:int] -> device: dinput.DeviceSummary"""
    global _all_virtual_devices_map
    return _all_virtual_devices_map.copy()


def is_device_connected(device_guid) -> bool:
    """true if the device is connected (reported in)"""

    if device_guid in _joystick_device_guid_map:
        device: dinput.DeviceSummary = _joystick_device_guid_map[device_guid]
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


def reset_devices():
    """resets devices on device change"""
    syslog.info("Joystick device change detected - re-initializing joysticks")
    joystick_devices_initialization()
    el = gremlin.event_handler.EventListener()

    el.device_change_event.emit()


def noOpCallback(self, value):
    """dummy callback for special devices that don't have a particular axis, hat or button"""
    return None


def noOpHatCallback(self, value):
    """dummy callback for special devices that don't have a hat (returns neutral position)"""
    return -1  # center position


def registerSpecialDevices():
    """registers special devices"""
    import gremlin.ui.octavi_device

    # import gremlin.ui.osc_device
    # import gremlin.ui.midi_device
    global _special_devices_map, _special_devices
    _special_devices_map.clear()
    _special_devices.clear()

    _config_devices_map.clear()
    _config_devices.clear()

    syslog.info("Special devices:")

    # keyboard
    device_guid = str(gremlin.shared_state.keyboard_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Keyboard"
    device.device_guid = gremlin.shared_state.keyboard_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Keyboard
    device.device_category = DeviceCategory.Special
    registerSpecialDevice(device)

    # state
    device_guid = str(gremlin.shared_state.state_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "State"
    device.device_guid = gremlin.shared_state.state_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.State
    device.device_category = DeviceCategory.Special
    registerSpecialDevice(device)

    # OSC
    device_guid = str(gremlin.shared_state.osc_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "OSC"
    device.device_guid = gremlin.shared_state.osc_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Osc
    device.device_category = DeviceCategory.Special
    registerSpecialDevice(device)

    # MIDI
    device_guid = str(gremlin.shared_state.midi_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "MIDI"
    device.device_guid = gremlin.shared_state.midi_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Midi
    device.device_category = DeviceCategory.Special
    registerSpecialDevice(device)

    # Octavi IFR1
    device_guid = str(gremlin.shared_state.octavi_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Octavi IFR1"
    device.device_guid = gremlin.shared_state.octavi_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.OctaviIFR1
    device.device_category = DeviceCategory.Special
    device.setAxisCallback(noOpCallback)
    device.setHatCallback(noOpHatCallback)
    oo = gremlin.ui.octavi_device.OctaviInterface()
    device.setButtonCallback(oo.get_button)
    registerSpecialDevice(device)

    # mode
    device_guid = str(gremlin.shared_state.mode_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Mode/Profile"
    device.device_guid = gremlin.shared_state.mode_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.ModeControl
    device.device_category = DeviceCategory.Special
    registerSpecialDevice(device)

    # plugin
    device_guid = str(gremlin.shared_state.plugins_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Plugins"
    device.device_guid = gremlin.shared_state.plugins_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Plugins
    device.device_category = DeviceCategory.Config
    registerConfigDevice(device)

    # settings
    device_guid = str(gremlin.shared_state.settings_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Settings"
    device.device_guid = gremlin.shared_state.settings_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Settings
    device.device_category = DeviceCategory.Config
    registerConfigDevice(device)


def getSpecialDevices() -> list:
    """gets all special devices"""
    global _special_devices
    return _special_devices


def getConfigDevices() -> list:
    """gets all configuration devices"""
    global _config_devices
    return _config_devices


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

    for device_index in range(device_count):
        dev = dinput.DILL.get_device_information_by_index(device_index)
        device_guid = gremlin.util.normalize_guid(dev.device_guid)
        if device_guid not in _joystick_device_guid_map:
            syslog.info(f"\tindex: [{device_index}] {str(dev)}")
            if dev.vendor_id == 0x31E3 and dev.axis_count == 0:  # handle wooting no axis/no button devices
                dev.disabled = True
            elif dev.vendor_id == 0x4D8 and dev.product_id == 0xE6D6 and dev.button_count == 35:
                dev.disabled = True

            _joystick_devices.append(dev)
            _joystick_device_guid_map[device_guid] = dev  # key by GUID


def _create_vjoy_device(vjoy_index: int):
    """creates a fake vjoy device"""
    device = dinput.DeviceSummary()
    device.device_id = gremlin.util.get_guid()  # random GUID
    device.device_guid = gremlin.util.parse_guid(device.device_id)
    device.device_type = DeviceType.VJoy
    device.name = "vJoy Device"
    device.vendor_id = 0x1234  # vjoy vendor
    device.product_id = 0xBEAD  # vjoy product ID
    device.setConnected(False)
    device.axis_count = 8
    device.button_count = 128
    device.hat_count = 4
    device.input_enabled = False
    device.joystick_id = vjoy_index - 1
    device.vjoy_id = vjoy_index
    device.virtual_id = vjoy_index
    device.axismap_list = []
    device.usage_page = None
    device.usage = None
    device.axis_names = []
    return device


def invalidDeviceGuid():
    """invalid device guid placeholder as a dinput.GUID"""
    global _invalid_device_guid
    import gremlin.util

    return gremlin.util.parse_guid(_invalid_device_guid)


def invalidDeviceId() -> str:
    """invalid device guid placeholder as a string"""
    global _invalid_device_guid
    return _invalid_device_guid


def joystick_devices_initialization():
    """Initializes joystick device information.

    This function retrieves information about various joystick devices and
    associates them and collates their information as required.

    Amongst other things this also ensures that each vJoy device has a correct
    windows id assigned to it.
    """

    import gremlin.util

    global \
        _joystick_devices, \
        _joystick_init_lock, \
        _joystick_initialized, \
        _joystick_device_guid_map, \
        _vjoy_devices_map, \
        _all_joystick_devices, \
        _invalid_device_guid, \
        _all_vjoy_devices_map, \
        _all_devices_map, \
        _maestro_devices_map, \
        _all_maestro_devices_map

    _joystick_initialized = False
    config = gremlin.config.Configuration()
    verbose = config.verbose_mode_inputs or config.verbose_mode_vjoy
    verbose_detailed = verbose and config.verbose_mode_extra

    with _joystick_init_lock:
        syslog = logging.getLogger("system")
        syslog.info("INIT: Initializing joystick devices")

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

            if device_count:
                syslog.info(f"INIT: {device_count} hardware devices detected:")
                dinput.DILL.dumpDevices()

            if device_count != controller_count:
                syslog.warning(f"INIT: HID device count is {controller_count}, does not match DirectX controller count: {device_count}")

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

        # Process all connected devices in order to properly initialize the device registry
        devices = []
        _joystick_devices = []  # [DeviceSummary] of connected devices only
        _all_joystick_devices = []  # [DeviceSummary] of all devices, virtual, connected and disconnected
        _joystick_device_guid_map.clear()
        _all_vjoy_devices_map.clear()
        _vjoy_devices_map.clear()
        _maestro_devices_map.clear()  # connected maestro devices (int) -> device

        _all_devices_map.clear()
        virtual_count = 0
        real_count = 0
        virtual_devices = {}
        dinput_vjoy_device_map = {}  # map of vjoy devices by vjoy ID

        syslog.info("DINPUT device list:")
        for device_index in range(device_count):
            # these are all connected devices
            dev = dinput.DILL.get_device_information_by_index(device_index)
            syslog.info(f"\tDevice: {dev.name} ID {dev.device_id}  Type: {dev.device_type.name}")
            if dev.vendor_id == 0x4D8 and dev.product_id == 0xE6D6 and dev.button_count == 35:
                # IFR1 device, disable
                syslog.warning("\t\tOctavi IFR1 is disabled in GremlinEx as a regular joystick as it's handled at the HID level.")
                dev.disabled = True
            if dev.vendor_id == 0x31E3 and dev.axis_count == 0:  # handle wooting no axis/no button devices
                dev.disabled = True

            dev.device_category = DeviceCategory.Physical

            if dev.axis_count:
                syslog.info(f"\t\tAxis definitions: {dev.axis_count} found")
                for i in range(dev.axis_count):
                    linear = i + 1
                    axis_id = dev.linear_id_map[linear]
                    axis_name = dev.get_axis_name(axis_id)
                    syslog.info(f"\t\t\tAxis {axis_name} A{axis_id} L{linear} {'(sequential)' if linear == axis_id else '(non-sequential)'}")

            devices.append(dev)
            syslog.info(f"\t\tIndex: [{device_index}] {str(dev)}")

            if dev.device_type == DeviceType.Joystick:
                _joystick_devices.append(dev)
                _all_joystick_devices.append(dev)
                _joystick_device_guid_map[dev.device_guid] = dev  # key by GUID

            _all_devices_map[dev.device_guid] = dev  # key by GUID

            if dev.is_virtual:
                virtual_count += 1
                virtual_devices[dev.hashkey] = dev
                dev.device_category = DeviceCategory.Virtual
                match dev.device_type:
                    case DeviceType.VJoy:
                        dinput_vjoy_device_map[dev.hashkey] = dev
                    case DeviceType.Maestro:
                        _maestro_devices_map[dev.virtual_id] = dev
                    case _:
                        raise ValueError(f"Unknown virtual device with vendor ID: 0x{dev.vendor_id:X} product ID: 0x{dev.product_id:X}")

            else:
                real_count += 1

        syslog.info(f"INIT: Found {real_count} hardware devices and {virtual_count} virtual devices")

        vjoy_lookup = {}
        vjoy_wheel_lookup = {}

        should_terminate = False

        # Query all vJoy devices in sequence until all have been processed and
        # their matching SDL counterparts have been found.
        vjoy_hash_list = []
        vjoy_proxy = VJoyProxy()
        config_map = {}
        disconnected_list = []
        used_counts = []

        for vjoy_index in range(1, 17):  # index 1 up to 16
            # Only process devices that actually exist
            is_connected = vjoy.device_available(vjoy_index)
            if is_connected:
                # device reports as available via the VJOY interface
                axis_count = vjoy.axis_count(vjoy_index)
                button_count = vjoy.button_count(vjoy_index)
                hat_count = vjoy.hat_count(vjoy_index)
                if button_count not in used_counts:
                    used_counts.append(button_count)
                config_map[vjoy_index] = (is_connected, axis_count, button_count, hat_count)
                vjoy.ensure_released(vjoy_index)

                dinput_key = (axis_count, button_count, hat_count)  # (input_vjoy_device_map[dev.vjoy_id] = dev
                # see if the device was detected in DINPUT
                if dinput_key not in dinput_vjoy_device_map:
                    syslog.warning(
                        f"VJOY device [{vjoy_index}] exists in the VJOY API but was not detected by DINPUT indicating a possible configuration or conflict problem.  This VJOY will be disabled."
                    )
                    disconnected_list.append(vjoy_index)
                    # fake device
                    device = _create_vjoy_device(vjoy_index)
                    _all_vjoy_devices_map[vjoy_index] = device
                    _joystick_device_guid_map[device.device_guid] = device  # key by GUID

                else:
                    device: dinput.DeviceSummary = dinput_vjoy_device_map[dinput_key]
                    device.vjoy_id = vjoy_index
                    device.virtual_id = vjoy_index
                    device.setConnected(True)  # connected means the VJOY device is not only shown in the API but also with DINPUT.
                    syslog.info(f"VJOY device [{vjoy_index}] matched to DINPUT device [{device.device_id}]")
                    _all_vjoy_devices_map[vjoy_index] = device
                    _vjoy_devices_map[vjoy_index] = device
                    _joystick_device_guid_map[device.device_guid] = device  # key by GUID
                    _all_devices_map[device.device_guid] = device  # key by GUID
            else:
                # device reports as not available from the vjoy interface
                disconnected_list.append(vjoy_index)
                device = _create_vjoy_device(vjoy_index)
                _all_vjoy_devices_map[vjoy_index] = device
                _joystick_device_guid_map[device.device_guid] = device  # key by GUID
                _all_devices_map[dev.device_guid] = dev

                if verbose:
                    syslog.warning(f"VJOY device [{vjoy_index}] is not detected or not enabled in the VJOY API. This VJOY will be disabled.")

        # add missing vjoy devices that are disconnected or not configured so they are still available and marked disconnected
        for vjoy_index in disconnected_list:
            count = 128
            while count in used_counts:
                count -= 1
            used_counts.append(count)
            config_map[vjoy_index] = (False, 8, count, 4)  # fake configuration, varies by button count only
            device = _all_vjoy_devices_map[vjoy_index]
            device.button_count = count  # update unique button count for disconnected devices
            device.name = f"Vjoy {device.axis_count}/{device.button_count}/{device.hat_count} ({vjoy_index})"

        for vjoy_index in range(1, 17):  # list all possible vjoy devices index 1 up to 16
            is_connected, axis_count, button_count, hat_count = config_map[vjoy_index]

            hash_value = (axis_count, button_count, hat_count)
            hash_wheel_value = (axis_count + 1, button_count, hat_count)

            if verbose:
                syslog.info(
                    f"Vjoy Interface: device index [{vjoy_index}] Hash: {hash_value} Hash wheel: {hash_wheel_value} Axis Count: {axis_count} Button count: {button_count} Hat count: {hat_count}  Connected: {is_connected}"
                )

            if hash_value in vjoy_hash_list:
                syslog.error("Fatal error: This device is not unique in terms of axis/button/hat counts.")
                should_terminate = True

            if is_connected and hat_count > 0 and not vjoy.hat_configuration_valid(vjoy_index):
                import gremlin.ui.ui_common
                import gremlin.event_handler
                import sys

                error_string = f"VJoy id {vjoy_index:d}: Hats are set to discrete but have to be set as continuous."
                syslog.error(error_string)
                el = gremlin.event_handler.EventListener()
                el.terminate()  # terminates and sends the relevant shutdown triggers
                util.display_error(error_string)
                sys.exit(1)

            # As we are ensured that no duplicate vJoy devices exist from
            # the previous step we can directly link the SDL and vJoy device
            if hash_value in vjoy_lookup:
                # found the vjoy interface index
                vjoy_lookup[hash_value].set_vjoy_id(vjoy_index)
                syslog.info(f"\tVjoy id {vjoy_index}: {'connected' if is_connected else ' disconnected'} in vjoy interface")
            elif hash_wheel_value in vjoy_wheel_lookup:
                vjoy_lookup[hash_value] = vjoy_wheel_lookup[hash_value]
                vjoy_lookup[hash_value].set_vjoy_id(vjoy_index)
                syslog.info(f"\tVjoy id {vjoy_index}: found in vjoy interface (as a wheel)")
            elif hash_value in virtual_devices:
                dev = virtual_devices[hash_value]
                vjoy_lookup[hash_value] = dev
                vjoy_lookup[hash_value].set_vjoy_id(vjoy_index)
            else:
                # not found
                hash_value = (axis_count, button_count, hat_count)
                hash_wheel_value = (axis_count + 1, button_count, hat_count)
                if verbose_detailed:
                    syslog.info(
                        f"vjoy id {vjoy_index:d}: {hash_value} vJoy device exists but DILL does not see it - check HIDHide config if enabled and process is whitelisted.  This device cannot be used as input.  This message is normal if the device is not configured in VJOY."
                    )

                dev = _all_vjoy_devices_map[vjoy_index]
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
                    dev.axis_names.append(axis_name)

                vjoy_lookup[hash_value] = dev
                _all_joystick_devices.append(dev)
                device_guid = gremlin.util.normalize_guid(dev.device_guid)
                _joystick_device_guid_map[device_guid] = dev
                if verbose_detailed:
                    syslog.info(f"Adding undetected VJOY device: [{vjoy_index}] {str(dev)}")

            # If the device can be acquired, configure the mapping from
            # vJoy axis id, which may not be sequential, to the
            # sequential SDL axis id
            # if dev.connected and hash_value in vjoy_lookup:
            #     try:
            #         # register the vjoy device with the proxy
            #         _vjoy_dev = vjoy_proxy[vjoy_index]
            #     except error.VJoyError:
            #         syslog.error(f"vJoy id {vjoy_index:} can't be acquired")

        if not should_terminate:
            if len(_joystick_device_guid_map) == 0:
                syslog.error("Error (fatal): no usable VJOY devices found.")
                should_terminate = True

        if should_terminate:
            # exit gracefully
            syslog.error("A fatal error was encountered during the detection and mapping of input devices - see the log for errors.")
            app = QtWidgets.QApplication.instance()
            if app:
                app.exit()
            sys.exit(1)
            return

        # Reset all devices so we don't hog the ones we aren't actually using
        vjoy_proxy.reset()

        # device: dinput.DILL.DeviceSummary
        syslog.info("Input device summary:")
        regular_devices_list = [dev for dev in _joystick_devices if not dev.is_virtual]
        vjoy_devices_list = [dev for dev in _joystick_devices if dev.device_type == DeviceType.VJoy]
        vjoy_devices_list.sort(key=lambda x: x.vjoy_id)
        maestro_devices_list = [dev for dev in _joystick_devices if dev.device_type == DeviceType.Maestro]

        update_virtual_map()

        _all_virtual_devices_map = {**_all_vjoy_devices_map, **_all_maestro_devices_map}
        for dev in regular_devices_list:
            syslog.info(f"\tDevice: (regular) {str(dev)}")
        for dev in vjoy_devices_list:
            syslog.info(f"\tDevice: (vjoy) {str(dev)}")
        for dev in maestro_devices_list:
            syslog.info(f"\tDevice: (maestro) {str(dev)}")

        _joystick_initialized = True
        syslog.info("Joystick input initialized")

    # register special devices
    registerSpecialDevices()

    # update calibration on initial joystick device load
    mgr = gremlin.ui.axis_calibration.CalibrationManager()
    mgr.reload()


def update_virtual_map():
    global _all_virtual_devices_map, _all_maestro_devices_map, _all_vjoy_devices_map
    _all_virtual_devices_map[DeviceType.VJoy] = _all_vjoy_devices_map
    _all_virtual_devices_map[DeviceType.Maestro] = _all_maestro_devices_map


def joystick_initialized():
    global _joystick_initialized
    return _joystick_initialized


def refresh_devices():
    """updates any missing dynamic devices like VIGEM or VJOY from directInput"""
    joystick_devices_initialization()


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

        """ tracks assigned VJOY functions """

        self._device_list = None
        self._profile = None
        self._load_list = []
        # self._button_usage = {}  # list of used buttons and by what action / input  index is the [vjoy_id][button_index] = true if used, false if not - tracks if the output button is used by the profile
        self._button_usage_map = {}  # list of used buttons [vjoy_id][button_index] = [action id, ...] - tracks how many actions in the profile are using the output button
        self._action_map = {} # list of action ids to devices

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
        el.profile_unloaded.connect(self._profile_changed) # reset on profile change
        el.set_virtual_button_usage.connect(self._handle_set_virtual_button_usage)
        el.shutdown.connect(self._handle_shutdown)
        self.reset()

    def registerAction(self, key):
        assert key not in self._action_map, "action already registered"
        self._action_map[key] = {}
        # syslog.info(f"Button State: register action [{key}]")

    def getRegisteredActions(self):
        return list(self._action_map.keys())

    def unregisterAction(self, key):
        """unregisters an action - this can be called multiple times for the same action """
        if key in self._action_map:
            # syslog.info(f"Button State: unregister action [{key}]")
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
        syslog.info("Button State: profile change event")
        self.reset()
        self.ensure_device_maps(force_update=True)

    def reset(self):
        """resets the usage state"""
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

        device: dinput.DeviceSummary
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
        device = gremlin.joystick_handling.getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        if device_type in self._axis_invert_map:
            invert_map = self._axis_invert_map[device_type]
            virtual_id = device.virtual_id
            if device.virtual_id in invert_map:
                if input_id in invert_map[virtual_id]:
                    invert_map[virtual_id][input_id] = inverted
                    return
        self._ensure_maps(device_guid, input_id)

    def is_inverted(self, device_guid, input_id):
        """returns true if the specified device/axis is inverted"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = gremlin.joystick_handling.getDevice(device_guid)
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
        device = gremlin.joystick_handling.getDevice(device_guid)
        device_type = device.device_type  # assuming device_guid has a device_type attribute
        virtual_id = device.virtual_id
        self._ensure_maps(device_guid, input_id)
        if device_type in self._axis_invert_map:
            if virtual_id in self._axis_invert_map[device_type]:
                if input_id in self._axis_invert_map[device_type][virtual_id]:
                    self._axis_invert_map[device_type][virtual_id][input_id] = not self._axis_invert_map[device_type][virtual_id][input_id]
                    verbose = gremlin.config.Configuration().verbose_mode_vjoy
                    if verbose:
                        syslog.info(f"Vjoy [{device.name}] Axis {input_id} inverted state: {self._axis_invert_map[device_type][virtual_id][input_id]}")
                    return

    def set_range(self, device_guid, input_id, min_range=-1.0, max_range=1.0):
        """sets the axis min/max range for the active range computation"""
        if isinstance(device_guid, int):
            device_guid = getVjoyDeviceGuid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        if min_range > max_range:
            min_range, max_range = max_range, min_range
        self._ensure_maps(device_guid, input_id)  # make sure the maps are initialized before setting the range
        device = gremlin.joystick_handling.getDevice(device_guid)
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
        device = gremlin.joystick_handling.getDevice(device_guid)
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
            syslog.info(f"Button State: load new profile: {profile.name}")
            self._profile = profile
            # self._button_usage.clear()
            #self._button_usage_map.clear()  # blits state data on profile change
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


    def _set_usage_state(self, device_type : DeviceType, virtual_id : int, button_id: int, key, used: bool, emit=True):
        """sets the usage state for a virtual button"""

        assert key in self._action_map, "action not registered"

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



        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_vjoy and config.verbose_mode_extra
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

        if verbose:
            syslog.info(f"Button State: Set usage state: [{device_type.name}] id [{virtual_id}] button [{button_id}] used: [{used}] mapped: [{is_mapped}] key: [{key}]")


        if __debug__:
            used_list = list(set(self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None) for key in self._action_map if self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None) is not None))
            if used:
                assert button_id in used_list, f"button {button_id} should be in used list {used_list}"
            else:
                action_list = [k for k in self._action_map if self._action_map.get(k, {}).get(device_type, {}).get(virtual_id, None) == button_id]
                assert key not in action_list, f"action {key} should not be in action list {action_list}"


        if changed:


            if emit and not gremlin.shared_state.is_running:
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
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device GUID"
        assert device.is_virtual, "device is not virtual"
        device_type = device.device_type
        virtual_id = device.virtual_id
        self._set_usage_state(device_type, virtual_id, button_id, key, used, emit)


    def _get_usage_state(self, device_type : DeviceType, virtual_id : int, button_id: int) -> bool:
        """gets the usage state for a virtual button"""
        if device_type in self._button_usage_map:
            if virtual_id in self._button_usage_map[device_type]:
                return len(self._button_usage_map[device_type][virtual_id].get(button_id, set())) > 0
        return False

    def get_usage_state(self, device_guid, button_id: int) -> bool:
        """gets the usage state for a virtual button"""
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        self.ensure_device_maps()
        self.ensure_valid(device_guid, button_id)  # create entry if needed - this can happen if the input vjoy device doesn't exist
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device GUID"
        assert device.is_virtual, "device is not virtual"
        device_type = device.device_type
        virtual_id = device.virtual_id
        return self._get_usage_state(device_type, virtual_id, button_id)

    def get_usage_list(self, device_guid, button_id: int) -> list:
        """gets the action ids for what outputs a virtual button in the profile """
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        self.ensure_device_maps()
        self.ensure_valid(device_guid, button_id)  # create entry if needed - this can happen if the input vjoy device doesn't exist
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device GUID"
        assert device.is_virtual, "device is not virtual"
        device_type = device.device_type
        virtual_id = device.virtual_id
        return list(self._button_usage_map[device_type][virtual_id].get(button_id, set()))


    def _used_button_list(self, device_type: DeviceType, virtual_id: int) -> list[int]:
        """gets the list of used buttons for a given device"""
        used_list = list(set(self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None) for key in self._action_map if self._action_map.get(key, {}).get(device_type, {}).get(virtual_id, None) is not None))

        #used_list = [button_id for button_id, map_list in self._button_usage_map.get(device_type, {}).get(virtual_id, {}).items()  if map_list]
        return used_list

    def used_button_list(self, device_guid) -> list[int]:
        """gets the list of used buttons for a given output device"""
        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device GUID"
        assert device.is_virtual, "device is not virtual"
        device_type = device.device_type
        virtual_id = device.virtual_id
        return self._used_button_list(device_type, virtual_id)


    @property
    def device_list(self):
        return self._device_list

    @property
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


        syslog.info("Button usage list for profile:")
        for device_guid in target_deviceguid_list:
            device = gremlin.joystick_handling.getDevice(device_guid)
            used_list = self.used_button_list(device_guid)
            syslog.info(f"Profile load: Used button list for device {device.name}: {used_list}")
        pass

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
        self._connected = False  # tracks event hook (we don't hook on init because of possible python import issue and load order)

    def setStartValue(self, device_id, id: int, value: float):
        """registers an axis start value"""
        import gremlin.event_handler

        if not isinstance(device_id, int):
            vjoy_id = vjoy_id_from_guid(device_id)
        else:
            vjoy_id = device_id  # integer ID

        if vjoy_id is None:
            syslog.error(f"VJOY SET START: : vjoy device [{device_id}] not available")
            return

        if not self._connected:
            # trap profile started event
            el = gremlin.event_handler.EventListener()
            el.profile_started.connect(self.apply)
            self._connected = True

        if vjoy_id not in self._axis_data:
            self._axis_data[vjoy_id] = {}
        self._axis_data[vjoy_id][id] = value

    def setStartState(self, device_id, id: int, state: bool):
        """registers a button start value"""
        import gremlin.event_handler

        vjoy_id = vjoy_id_from_guid(device_id)
        if vjoy_id is None:
            syslog.warning(f"Register VJOY start value: unknown device {device_id}")
            return

        if not self._connected:
            # trap profile started event
            el = gremlin.event_handler.EventListener()
            el.profile_started.connect(self.apply)
            self._connected = True

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
        """applies the startup data"""
        import gremlin.input_devices

        remote_client = gremlin.remote.remote_client
        for vjoy_id in self._axis_data:
            device_guid = getVjoyDeviceGuidStr(vjoy_id)
            for id in self._axis_data[vjoy_id]:
                value = self._axis_data[vjoy_id][id]
                if value is not None:
                    set_axis(device_guid, id, value)
                    remote_client.send_axis(vjoy_id, id, value)

        for vjoy_id in self._button_data:
            device_guid = getVjoyDeviceGuid(vjoy_id)
            for id in self._button_data[vjoy_id]:
                state = self._button_data[vjoy_id][id]
                if state is None:
                    state = False
                set_button(device_guid, id, state)
                remote_client.send_button(vjoy_id, id, state)


# instance
_vjoy_start = VjoyStart()
