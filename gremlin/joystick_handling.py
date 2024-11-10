# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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
import gremlin.event_handler
import gremlin.shared_state

from . import common, error, util
from vjoy import vjoy
from dinput import DeviceSummary
from gremlin.input_types import InputType
import gremlin.config


# List of all joystick devices
_joystick_devices = []

# map of physical devices by their GUID
_joystick_device_guid_map = {}

# Joystick initialization lock
_joystick_init_lock = threading.Lock()


class VJoyProxy:

    """Manages the usage of vJoy and allows shared access all callbacks."""

    vjoy_devices = {}

    def __getitem__(self, key):
        """Returns the requested vJoy instance.

        :param key id of the vjoy device
        :return the corresponding vjoy device
        """
        if key in VJoyProxy.vjoy_devices:
            return VJoyProxy.vjoy_devices[key]
        else:
            if not isinstance(key, int):
                raise error.GremlinError(
                    "Integer ID for vjoy device ID expected"
                )

            try:
                device = vjoy.VJoy(key)
                VJoyProxy.vjoy_devices[key] = device
                # msg = f"Registering vJoy id={key}"
                # logging.getLogger("system").debug(msg)
                return device
            except error.VJoyError as e:
                msg = f"Failed accessing vJoy id={key}, error is: {e}"
                logging.getLogger("system").debug(msg)
                logging.getLogger("system").error(msg)
                raise e

    @classmethod
    def reset(self):
        """Relinquishes control over all held VJoy devices."""
        devices = list(VJoyProxy.vjoy_devices.values())
        for device in devices:
            device.invalidate()
        VJoyProxy.vjoy_devices = {}

      
def joystick_devices() -> list[DeviceSummary]:
    """Returns the list of joystick like devices.

    :return list containing information about all joystick like devices
    """
    return _joystick_devices

def axis_input_devices() -> list[DeviceSummary]:
    ''' returns the list of input devices '''
    devices = [dev for dev in _joystick_devices if dev.axis_count]
    return devices
    
def button_input_devices() -> list[DeviceSummary]:
    devices = [dev for dev in _joystick_devices if dev.button_count]
    return devices


def vjoy_devices() -> list[DeviceSummary]:
    """Returns the list of vJoy devices.

    :return list of vJoy devices
    """
    return [dev for dev in _joystick_devices if dev.is_virtual]

def scale_to_range(value, source_min = -1.0, source_max = 1.0, target_min = -1.0, target_max = 1.0, invert = False):
    ''' scales a value on one range to the new range
    
    value: the value to scale
    r_min: the source value's min range
    r_max: the source value's max range
    new_min: the new range's min
    new_max: the new range's max
    invert: true if the value should be reversed
    '''
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

def get_axis(guid, index, normalized = True):
    ''' gets the value of the specified axis
     
    :param: normalized  - if set - normalizes to -1.0 +1.0 floating point
       
    '''
    value = dinput.DILL.get_axis(guid, index)
    if normalized:
        return gremlin.util.scale_to_range(value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1)


def get_curved_axis(guid, index):
    ''' returns curved data same as the event handler '''
    eh = gremlin.event_handler.EventListener()
    value = dinput.DILL.get_axis(guid, index)
    return eh.apply_transforms(guid, index, value)

    


def physical_devices():
    """Returns the list of physical devices.

    :return list of physical devices
    """
    return [dev for dev in _joystick_devices if not dev.is_virtual]


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
            return {
                "device_id": dev.vjoy_id,
                "input_type": InputType.JoystickAxis,
                "input_id": dev.axis_map[0].axis_index
            }
        elif InputType.JoystickButton in valid_types and dev.button_count > 0:
            return {
                "device_id": dev.vjoy_id,
                "input_type": InputType.JoystickButton,
                "input_id": 1
            }
        elif InputType.JoystickHat in valid_types and dev.hat_count > 0:
            return {
                "device_id": dev.vjoy_id,
                "input_type": InputType.JoystickHat,
                "input_id": 1
            }
    return None


def vjoy_id_from_guid(guid : str | dinput.GUID):
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
    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID 
    for dev in vjoy_devices():
        if dev.device_guid == guid:
            return dev.vjoy_id

    logging.getLogger("system").error(
        f"Could not find vJoy matching guid {str(guid)}"
    )
    return 1

def device_name_from_guid(guid : str | dinput.GUID) -> str:
    ''' gets device name from GUID '''
    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID 
    if guid in _joystick_device_guid_map.keys():
        return _joystick_device_guid_map[guid].name
    return None
    
def device_info_from_guid(guid : str | dinput.GUID) -> DeviceSummary:
    ''' gets physical device information '''
    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID 
    if guid in _joystick_device_guid_map.keys():
        return _joystick_device_guid_map[guid]
    return None


def is_device_connected(guid : str | dinput.GUID) -> bool:
    ''' true if the device is connected (reported in) '''
    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID 
    return guid in _joystick_device_guid_map.keys()



def linear_axis_index(axis_map : dinput.AxisMap, axis_index : int) -> int:
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
    ''' resets devices on device change '''
    logging.getLogger("system").info("Joystick device change detected - re-initializing joysticks")
    joystick_devices_initialization()
    el = gremlin.event_handler.EventListener()
    el.device_change_event.emit()


def joystick_devices_initialization():
    """Initializes joystick device information.

    This function retrieves information about various joystick devices and
    associates them and collates their information as required.

    Amongst other things this also ensures that each vJoy device has a correct
    windows id assigned to it.
    """
    global _joystick_devices, _joystick_init_lock
    
    verbose = gremlin.config.Configuration().verbose_mode_inputs

    _joystick_init_lock.acquire()

    syslog = logging.getLogger("system")
    syslog.info("Initializing joystick devices")
    syslog.debug(
        f"{dinput.DILL.get_device_count():d} joysticks detected"
    )

    # Process all connected devices in order to properly initialize the
    # device registry
    devices = []
    device_count = dinput.DILL.get_device_count()
    virtual_count = 0
    real_count = 0
    for i in range(device_count):
        info = dinput.DILL.get_device_information_by_index(i)
        devices.append(info)
        syslog.info(f"\t[{i}] {info.device_id} {info.name}")
        if info.is_virtual: 
            virtual_count += 1
        else:
            real_count += 1

    syslog.info(f"Found {real_count} hardware devices and {virtual_count} virtual devices")


    # Process all devices again to detect those that have been added and those
    # that have been removed since the last time this function ran.

    # Compare existing versus observed devices and only proceed if there
    # is a change to avoid unnecessary work.
    device_added = False
    device_removed = False
    for new_dev in devices:
        if new_dev not in _joystick_devices:
            device_added = True
            if verbose:
                syslog.debug(f"Added: name={new_dev.name} guid={new_dev.device_guid}")
                
    for old_dev in _joystick_devices:
        if old_dev not in devices:
            device_removed = True
            if verbose:
                syslog.debug(f"Removed: name={old_dev.name} guid={old_dev.device_guid}")

    # Terminate if no change occurred
    if not device_added and not device_removed:
        _joystick_init_lock.release()
        return

    # In order to associate vJoy devices and their ids correctly with SDL
    # device ids a hash is constructed from the number of axes, buttons, and
    # hats. This information is used to attempt to find unambiguous mappings
    # between vJoy and SDL devices. If this is not possible Gremlin will
    # terminate as this is a non-recoverable error.

    vjoy_lookup = {}
    vjoy_wheel_lookup = {}
    for dev in [dev for dev in devices if dev.is_virtual]:
        hash_value = (dev.axis_count, dev.button_count, dev.hat_count)
        hash_value_wheel = (dev.axis_count+1, dev.button_count, dev.hat_count)
        if verbose:
            syslog.debug(f"vJoy guid={dev.device_guid}: {hash_value}")

        # Only unique combinations of axes, buttons, and hats are allowed
        # for vJoy devices
        if hash_value in vjoy_lookup:
            raise error.GremlinError(
                "Indistinguishable vJoy devices present.\n\n"
                "vJoy devices have to differ in the number of "
                "(at least one of) axes, buttons, or hats in order to work "
                "properly with Joystick Gremlin."
            )

        vjoy_lookup[hash_value] = dev
        vjoy_wheel_lookup[hash_value_wheel] = dev


    # Query all vJoy devices in sequence until all have been processed and
    # their matching SDL counterparts have been found.
    vjoy_proxy = VJoyProxy()
    should_terminate = False
    for i in range(1, 17):
        # Only process devices that actually exist
        if not vjoy.device_exists(i):
            continue

        # Compute a hash for the vJoy device and match it against the SDL
        # device hashes
        hash_value = (
            vjoy.axis_count(i),
            vjoy.button_count(i),
            vjoy.hat_count(i)
        )

        if not vjoy.hat_configuration_valid(i):
            error_string = f"vJoy id {i:d}: Hats are set to discrete but have to be set as continuous."
            syslog.debug(error_string)
            util.display_error(error_string)

        # As we are ensured that no duplicate vJoy devices exist from
        # the previous step we can directly link the SDL and vJoy device
        if hash_value in vjoy_lookup:
            vjoy_lookup[hash_value].set_vjoy_id(i)
            if verbose:
                syslog.debug(f"vjoy id {i:d}: {hash_value} - MATCH")
        elif hash_value in vjoy_wheel_lookup:
            vjoy_wheel_lookup[hash_value].set_vjoy_id(i)
            vjoy_lookup[hash_value] = vjoy_wheel_lookup[hash_value]
            if verbose:
                syslog.debug(f"vjoy id {i:d}: {hash_value} - WHEEL MATCH")

        else:
            # should_terminate = True
            syslog.debug(f"vjoy id {i:d}: {hash_value} - ERROR - vJoy device exists but DILL does not see it - check HIDHide config if enabled and process is whitelisted")

        # If the device can be acquired, configure the mapping from
        # vJoy axis id, which may not be sequential, to the
        # sequential SDL axis id
        if hash_value in vjoy_lookup:
            try:
                vjoy_dev = vjoy_proxy[i]
            except error.VJoyError as e:
                syslog.debug(f"vJoy id {i:} can't be acquired")

    if should_terminate:
        raise error.GremlinError(
            "Unable to match vJoy devices to windows devices."
        )

    # Reset all devices so we don't hog the ones we aren't actually using
    vjoy_proxy.reset()

    # Update device list which will be used when queries for joystick devices
    # are made
    _joystick_devices = devices
    # device: dinput.DILL.DeviceSummary
    for device in devices:
        _joystick_device_guid_map[device.device_guid] = device
        syslog.info(f"Device: {str(device.device_guid)} {device.name} Axis count: {device.axis_count} Button count: {device.button_count} Hat count: {device.hat_count}")

    _joystick_init_lock.release()


